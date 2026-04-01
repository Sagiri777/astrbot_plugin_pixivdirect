from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .cache_manager import CacheManager
from .commands import CommandHandler
from .config_manager import ConfigManager
from .constants import (
    DEFAULT_CACHE_SIZE,
    DEFAULT_POOL_KEY,
    IDLE_CACHE_COUNT,
    IDLE_CACHE_INTERVAL_SECONDS,
    MAX_RANDOM_PAGES,
    MIN_COMMAND_INTERVAL_SECONDS,
    SEARCH_CONNECT_TIMEOUT_SECONDS,
    SEARCH_RETRYABLE_FAILURE_BUDGET,
    SEARCH_RUNTIME_IP_CANDIDATE_LIMIT,
)
from .emoji_reaction import EmojiReactionHandler
from .image_handler import ImageHandler
from .pixivSDK import pixiv, refresh_pixiv_host_map
from .utils import command_usage, help_text


@register("pixivdirect", "Sagiri777", "PixivDirect command plugin", "1.11.4")
class PixivDirectPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        self._plugin_data_dir = Path(get_astrbot_plugin_data_path()) / "pixivdirect"

        # Initialize managers
        self._config_manager = ConfigManager(self._plugin_data_dir)
        self._cache_manager = CacheManager(self._config_manager)
        self._emoji_handler = EmojiReactionHandler(enabled=False)

        # DNS refresh state
        self._dns_refresh_lock = asyncio.Lock()
        self._dns_next_refresh_at: float = 0.0
        self._dns_force_refresh: bool = False
        self._dns_refresh_task: asyncio.Task | None = None

        # Idle cache state
        self._idle_cache_task: asyncio.Task | None = None
        self._last_idle_cache_ts: float = 0.0

        # Initialize image handler with pixiv call function
        self._image_handler = ImageHandler(
            cache_dir=self._config_manager.cache_dir,
            pixiv_call_func=self._pixiv_call,
        )

        # Initialize command handler
        self._command_handler = CommandHandler(
            config_manager=self._config_manager,
            cache_manager=self._cache_manager,
            image_handler=self._image_handler,
            emoji_handler=self._emoji_handler,
            pixiv_call_func=self._pixiv_call,
            min_command_interval=MIN_COMMAND_INTERVAL_SECONDS,
            max_random_pages=MAX_RANDOM_PAGES,
            idle_cache_count=IDLE_CACHE_COUNT,
            default_cache_size=DEFAULT_CACHE_SIZE,
            dns_time_getter=self.get_next_dns_refresh_time,
            idle_cache_time_getter=self.get_next_idle_cache_time,
            idle_cache_all_func=self.trigger_idle_cache_all,
        )
        self._command_handler.set_dns_refresh_func(self.trigger_dns_refresh)

    async def initialize(self):
        self._config_manager.ensure_directories()
        self._config_manager.load_all()
        await self._refresh_dns_cache(reason="startup")
        self._dns_refresh_task = asyncio.create_task(self._dns_refresh_loop())
        # Start idle cache task
        self._idle_cache_task = asyncio.create_task(self._idle_cache_loop())

    @staticmethod
    def _next_dns_refresh_time() -> float:
        """Calculate the next 4 AM timestamp for DNS refresh."""
        from datetime import datetime, timedelta

        now = datetime.now()
        target_hour = 4

        today_4am = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)

        if now >= today_4am:
            next_refresh = today_4am + timedelta(days=1)
        else:
            next_refresh = today_4am

        return next_refresh.timestamp()

    async def _mark_dns_refreshed(self) -> None:
        async with self._dns_refresh_lock:
            self._dns_force_refresh = False
            self._dns_next_refresh_at = self._next_dns_refresh_time()

    def get_next_dns_refresh_time(self) -> str:
        """Get the next DNS refresh time as a formatted string."""
        if self._dns_next_refresh_at <= 0:
            return "未设置"
        from datetime import datetime

        dt = datetime.fromtimestamp(self._dns_next_refresh_at)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def get_next_idle_cache_time(self) -> str:
        """Get the next idle cache time as a formatted string."""
        if self._last_idle_cache_ts <= 0:
            return "未触发过"
        from datetime import datetime

        idle_interval = float(
            self._config_manager.get_constant(
                "idle_cache_interval", IDLE_CACHE_INTERVAL_SECONDS
            )
        )
        next_ts = self._last_idle_cache_ts + idle_interval
        dt = datetime.fromtimestamp(next_ts)
        now = datetime.now()
        delta = next_ts - now.timestamp()
        if delta <= 0:
            return "即将执行"
        minutes = int(delta // 60)
        seconds = int(delta % 60)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} (约 {minutes} 分 {seconds} 秒后)"

    async def trigger_idle_cache_all(self) -> None:
        """Trigger idle cache for all users."""
        await self._perform_idle_cache()

    async def trigger_dns_refresh(self) -> None:
        async with self._dns_refresh_lock:
            self._dns_force_refresh = True
            self._dns_next_refresh_at = 0.0
        await self._refresh_dns_cache(reason="manual")

    def _effective_bypass_mode(self) -> str:
        return self._config_manager.get_effective_bypass_mode()

    def _build_pixiv_call_kwargs(
        self,
        *,
        proxy: str | None = None,
        runtime_dns_resolve: bool = False,
        dns_update_hosts: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        bypass_mode = self._effective_bypass_mode()
        enable_runtime_dns = runtime_dns_resolve and not proxy
        if bypass_mode == "accesser" and not proxy:
            # Accesser mode depends on live DNS candidates for domain override.
            enable_runtime_dns = True
        return {
            "bypass_sni": bypass_mode != "disabled" and not proxy,
            "bypass_mode": bypass_mode if bypass_mode != "disabled" else "auto",
            "proxy": proxy,
            "dns_cache_file": str(self._config_manager.host_map_file),
            "dns_update_hosts": dns_update_hosts,
            "runtime_dns_resolve": enable_runtime_dns,
            "max_retries": 2,
            **kwargs,
        }

    def _build_search_call_kwargs(
        self,
        *,
        proxy: str | None = None,
        runtime_dns_resolve: bool = False,
        dns_update_hosts: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        call_kwargs = self._build_pixiv_call_kwargs(
            proxy=proxy,
            runtime_dns_resolve=runtime_dns_resolve,
            dns_update_hosts=dns_update_hosts,
            **kwargs,
        )
        call_kwargs.update(
            {
                "connect_timeout": max(
                    0.5,
                    float(
                        self._config_manager.get_constant(
                            "search_connect_timeout", SEARCH_CONNECT_TIMEOUT_SECONDS
                        )
                    ),
                ),
                "search_runtime_ip_candidate_limit": max(
                    1,
                    int(
                        self._config_manager.get_constant(
                            "search_runtime_ip_candidate_limit",
                            SEARCH_RUNTIME_IP_CANDIDATE_LIMIT,
                        )
                    ),
                ),
                "search_retryable_failure_budget": max(
                    1,
                    int(
                        self._config_manager.get_constant(
                            "search_retryable_failure_budget",
                            SEARCH_RETRYABLE_FAILURE_BUDGET,
                        )
                    ),
                ),
            }
        )
        return call_kwargs

    @staticmethod
    def _is_search_retryable_result(result: dict[str, Any]) -> bool:
        return not result.get("ok") and result.get("status") in {
            403,
            429,
            440,
            500,
            502,
            503,
            504,
        }

    async def _invoke_pixiv(
        self, action: str, params: dict[str, Any], **call_kwargs: Any
    ) -> dict[str, Any]:
        return await asyncio.to_thread(pixiv, action, params, **call_kwargs)

    async def _run_search_request_chain(
        self,
        action: str,
        params: dict[str, Any],
        *,
        proxy: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        call_kwargs = self._build_search_call_kwargs(proxy=proxy, **kwargs)
        result = await self._invoke_pixiv(action, params, **call_kwargs)

        bypass_mode = self._effective_bypass_mode()
        if (
            proxy is None
            and self._is_search_retryable_result(result)
            and bypass_mode != "disabled"
        ):
            logger.warning(
                "[pixivdirect] Retrying %s after transient status %s with bypass_mode=%s",
                action,
                result.get("status"),
                bypass_mode,
            )
            await self._refresh_dns_cache(reason=f"retry:{action}")
            retry_kwargs = self._build_search_call_kwargs(
                runtime_dns_resolve=True,
                **kwargs,
            )
            result = await self._invoke_pixiv(action, params, **retry_kwargs)
            await self._mark_dns_refreshed()

        if result.get("ok"):
            return result
        if not self._is_search_retryable_result(result):
            return result

        web_action = (
            "web_search_illust" if action == "search_illust" else "web_search_user"
        )
        web_params = dict(params)
        if "offset" in web_params:
            try:
                web_params["page"] = max(1, int(web_params["offset"]) // 30 + 1)
            except (TypeError, ValueError):
                web_params["page"] = 1
        logger.warning(
            "[pixivdirect] %s failed with status %s, trying %s%s",
            action,
            result.get("status"),
            web_action,
            " via proxy" if proxy else "",
        )
        web_result = await self._invoke_pixiv(web_action, web_params, **call_kwargs)
        if web_result.get("ok"):
            web_result["fallback_chain"] = ["app_api", "web"]
            return web_result

        web_result["fallback_chain"] = ["app_api", "web"]
        return web_result

    async def _run_search_with_recovery(
        self, action: str, params: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        proxy_url = self._config_manager.get_search_proxy_url()
        proxy_available = self._config_manager.is_search_proxy_configured() and bool(
            proxy_url
        )

        if proxy_available and self._config_manager.is_search_proxy_active():
            logger.warning(
                "[pixivdirect] Search proxy-first mode active until %s for %s",
                self._config_manager.search_proxy_state.get("proxy_until"),
                action,
            )
            proxied_result = await self._run_search_request_chain(
                action, params, proxy=proxy_url, **kwargs
            )
            if proxied_result.get("ok"):
                proxied_result["proxy_used"] = True
                proxied_result["fallback_chain"] = [
                    "proxy",
                    *proxied_result.get("fallback_chain", []),
                ]
                return proxied_result
            logger.warning(
                "[pixivdirect] Proxy-first search failed for %s, falling back to normal chain",
                action,
            )
            return await self._run_search_request_chain(action, params, **kwargs)

        result = await self._run_search_request_chain(action, params, **kwargs)
        if result.get("ok"):
            return result

        if proxy_available:
            await self._config_manager.record_search_proxy_rescue(
                reason=f"{action}:{result.get('status')}"
            )
            logger.warning(
                "[pixivdirect] Escalating %s to configured search proxy", action
            )
            proxied_result = await self._run_search_request_chain(
                action, params, proxy=proxy_url, **kwargs
            )
            proxied_result["proxy_used"] = True
            proxied_result["fallback_chain"] = [
                *result.get("fallback_chain", ["app_api", "web"]),
                "proxy",
            ]
            return proxied_result

        return result

    async def _refresh_dns_cache(self, *, reason: str) -> bool:
        bypass_mode = self._effective_bypass_mode()
        if bypass_mode == "disabled":
            await self._mark_dns_refreshed()
            logger.info(
                "[pixivdirect] Skip DNS refresh on %s because disable_bypass_sni=true",
                reason,
            )
            return False
        if bypass_mode == "accesser":
            await self._mark_dns_refreshed()
            logger.info(
                "[pixivdirect] Skip PixEz host refresh on %s because bypass_mode=accesser",
                reason,
            )
            return False

        try:
            await asyncio.to_thread(
                refresh_pixiv_host_map,
                dns_cache_file=str(self._config_manager.host_map_file),
            )
            await self._mark_dns_refreshed()
            logger.info("[pixivdirect] Refreshed PixEz host map on %s", reason)
            return True
        except Exception as exc:
            logger.warning(
                "[pixivdirect] Failed to refresh PixEz host map on %s: %s",
                reason,
                exc,
            )
            async with self._dns_refresh_lock:
                self._dns_next_refresh_at = time.time() + 300
            return False

    async def _dns_refresh_loop(self) -> None:
        while True:
            try:
                async with self._dns_refresh_lock:
                    force_refresh = self._dns_force_refresh
                    next_refresh_at = (
                        self._dns_next_refresh_at or self._next_dns_refresh_time()
                    )
                    self._dns_next_refresh_at = next_refresh_at

                now = time.time()
                if force_refresh or now >= next_refresh_at:
                    await self._refresh_dns_cache(reason="scheduled")
                    continue

                await asyncio.sleep(min(60.0, max(1.0, next_refresh_at - now)))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[pixivdirect] DNS refresh loop error: %s", exc)
                await asyncio.sleep(60)

    async def _pixiv_call(
        self, action: str, params: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if action in {"search_illust", "search_user"}:
            return await self._run_search_with_recovery(action, params, **kwargs)
        return await self._invoke_pixiv(
            action,
            params,
            **self._build_pixiv_call_kwargs(**kwargs),
        )

    async def _idle_cache_loop(self) -> None:
        while True:
            try:
                idle_interval = float(
                    self._config_manager.get_constant(
                        "idle_cache_interval", IDLE_CACHE_INTERVAL_SECONDS
                    )
                )
                await asyncio.sleep(idle_interval)
                await self._perform_idle_cache()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[pixivdirect] Idle cache loop error: %s", exc)
                await asyncio.sleep(60)

    async def _perform_idle_cache(self) -> None:
        if not self._config_manager.token_map:
            return

        now = time.time()
        idle_interval = float(
            self._config_manager.get_constant(
                "idle_cache_interval", IDLE_CACHE_INTERVAL_SECONDS
            )
        )
        if now - self._last_idle_cache_ts < idle_interval:
            return

        self._last_idle_cache_ts = now
        logger.info(
            "[pixivdirect] Starting idle cache for %d users",
            len(self._config_manager.token_map),
        )

        for uid, refresh_token in list(self._config_manager.token_map.items()):
            try:
                await self._idle_cache_user(uid, refresh_token)
            except Exception as exc:
                # Check if it's a connection error and retry once after 5 seconds
                is_connection_error = (
                    isinstance(exc, (ConnectionError, OSError))
                    or "Connection aborted" in str(exc)
                    or "RemoteDisconnected" in str(exc)
                )

                if is_connection_error:
                    logger.warning(
                        "[pixivdirect] Idle cache connection error for user %s, retrying in 5 seconds: %s",
                        uid,
                        exc,
                    )
                    await asyncio.sleep(5)
                    try:
                        await self._idle_cache_user(uid, refresh_token)
                    except Exception as retry_exc:
                        logger.warning(
                            "[pixivdirect] Idle cache retry failed for user %s: %s",
                            uid,
                            retry_exc,
                        )
                else:
                    logger.warning(
                        "[pixivdirect] Idle cache failed for user %s: %s", uid, exc
                    )

    async def _idle_cache_user(self, uid: str, refresh_token: str) -> None:
        user_cache = self._config_manager.random_cache.get(uid, {})
        current_queue = user_cache.get(DEFAULT_POOL_KEY, [])

        default_cache_size = int(
            self._config_manager.get_constant("default_cache_size", DEFAULT_CACHE_SIZE)
        )
        if len(current_queue) >= default_cache_size:
            return

        items_to_add = default_cache_size - len(current_queue)

        # Default count from constants
        idle_cache_count = int(
            self._config_manager.get_constant("idle_cache_count", IDLE_CACHE_COUNT)
        )
        default_count = min(items_to_add, idle_cache_count)

        user_queue = self._config_manager.idle_cache_queue.get(uid, [])
        filter_params = {"restrict": "public", "max_pages": 3}
        user_count = default_count
        filter_source = "default"

        if user_queue:
            queue_item = user_queue[0]
            filter_params = queue_item.get("filter_params", filter_params)
            remaining = queue_item.get("remaining", 1)
            count = queue_item.get("count", 1)
            filter_source = "queue"

            # Use user's count setting instead of hardcoded value
            if remaining == "always":
                user_count = default_count
            else:
                # Use the user-set count, but don't exceed items_to_add
                user_count = min(
                    items_to_add, int(count) if count != "always" else default_count
                )
                remaining = int(remaining) - 1
                if remaining <= 0:
                    user_queue.pop(0)
                else:
                    queue_item["remaining"] = remaining
                if not user_queue:
                    self._config_manager.idle_cache_queue.pop(uid, None)
                await self._config_manager.save_idle_cache_queue()
        else:
            preferred_filter = self._config_manager.get_top_random_filter_for_user(uid)
            if preferred_filter:
                filter_params = preferred_filter
                filter_source = "usage"

        # Use user_count instead of items_to_add
        items_to_add = user_count

        latest_refresh_token, error = await self._command_handler._enqueue_random_items(
            user_key=uid,
            cache_key=DEFAULT_POOL_KEY,
            refresh_token=refresh_token,
            filter_params=filter_params,
            count=items_to_add,
            quality="original",
        )
        if latest_refresh_token != refresh_token:
            self._config_manager.token_map[uid] = latest_refresh_token
            await self._config_manager.save_tokens()

        if error:
            logger.warning("[pixivdirect] Idle cache error for user %s: %s", uid, error)
        else:
            filter_desc = (
                filter_params.get("tag") or filter_params.get("author") or "default"
            )
            logger.info(
                "[pixivdirect] Cached %d items for user %s (filter: %s, source: %s)",
                items_to_add,
                uid,
                filter_desc,
                filter_source,
            )

    @filter.command("pixiv")
    async def pixiv_command(self, event: AstrMessageEvent, args_str: str = ""):
        """Pixiv commands: help, login, id, random."""
        # Get full command from event message_str instead of args_str
        # because @filter.command may truncate arguments
        full_message = event.message_str or ""
        logger.info(
            f"[pixivdirect] full_message: '{full_message}', args_str: '{args_str}'"
        )

        # Remove command prefix "/pixiv " or "pixiv "
        command_match = re.match(r"^/?pixiv\s*(.*)", full_message, re.IGNORECASE)
        if command_match:
            raw_remaining_args = command_match.group(1)
        else:
            raw_remaining_args = args_str

        had_trailing_space_only = bool(raw_remaining_args) and (
            raw_remaining_args != raw_remaining_args.rstrip()
        )
        remaining_args = raw_remaining_args.strip()

        limited = await self._command_handler.rate_limit_message(event)
        if limited:
            await self._emoji_handler.add_emoji_reaction(event, "rate_limit")
            yield event.plain_result(limited)
            return

        tokens = (
            [t for t in re.split(r"\s+", remaining_args) if t] if remaining_args else []
        )
        sub_cmd = tokens[0].lower() if tokens else "help"
        logger.info(f"[pixivdirect] tokens: {tokens}, sub_cmd: {sub_cmd}")

        if had_trailing_space_only and len(tokens) == 1:
            usage = command_usage(sub_cmd)
            if usage:
                yield event.plain_result(usage)
                return

        if sub_cmd == "help":
            await self._emoji_handler.add_emoji_reaction(event, "help")
            yield event.plain_result(help_text())
        elif sub_cmd == "login":
            async for result in self._command_handler.handle_login(
                event, ["login", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "id":
            async for result in self._command_handler.handle_id(
                event, ["id", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "random":
            async for result in self._command_handler.handle_random(
                event, ["random", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "dns":
            async for result in self._command_handler.handle_random(
                event, ["random", "dns", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "config":
            async for result in self._command_handler.handle_random(
                event, ["random", "config", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "bypass":
            async for result in self._command_handler.handle_bypass(
                event, ["bypass", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "proxy":
            async for result in self._command_handler.handle_proxy(
                event, ["proxy", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "groupblock":
            async for result in self._command_handler.handle_random(
                event, ["random", "groupblock", *tokens[1:]]
            ):
                yield result
        elif sub_cmd in {"share", "r18", "unique", "quality", "cache"}:
            async for result in self._command_handler.handle_random(
                event, ["random", sub_cmd, *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "search":
            async for result in self._command_handler.handle_search(
                event, ["search", *tokens[1:]]
            ):
                yield result
        elif sub_cmd == "searchuser":
            async for result in self._command_handler.handle_search_user(
                event, ["searchuser", *tokens[1:]]
            ):
                yield result
        else:
            yield event.plain_result(
                f"❌ 未知子命令：{sub_cmd}，请使用 /pixiv help 查看帮助。"
            )

    async def terminate(self):
        if self._dns_refresh_task and not self._dns_refresh_task.done():
            self._dns_refresh_task.cancel()
            try:
                await self._dns_refresh_task
            except asyncio.CancelledError:
                pass
        if self._idle_cache_task and not self._idle_cache_task.done():
            self._idle_cache_task.cancel()
            try:
                await self._idle_cache_task
            except asyncio.CancelledError:
                pass
        self._config_manager.random_cache.clear()

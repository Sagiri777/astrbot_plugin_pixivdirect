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
    DISABLE_BYPASS_SNI,
    IDLE_CACHE_COUNT,
    IDLE_CACHE_INTERVAL_SECONDS,
    MAX_RANDOM_PAGES,
    MIN_COMMAND_INTERVAL_SECONDS,
)
from .emoji_reaction import EmojiReactionHandler
from .image_handler import ImageHandler
from .pixivSDK import pixiv, refresh_pixiv_host_map
from .utils import command_usage, help_text


@register("pixivdirect", "Sagiri777", "PixivDirect command plugin", "1.10.10")
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

    async def _refresh_dns_cache(self, *, reason: str) -> bool:
        disable_bypass_sni = bool(
            self._config_manager.get_constant("disable_bypass_sni", DISABLE_BYPASS_SNI)
        )
        if disable_bypass_sni:
            await self._mark_dns_refreshed()
            logger.info(
                "[pixivdirect] Skip DNS refresh on %s because disable_bypass_sni=true",
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
                    next_refresh_at = self._dns_next_refresh_at or self._next_dns_refresh_time()
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
        disable_bypass_sni = bool(
            self._config_manager.get_constant("disable_bypass_sni", DISABLE_BYPASS_SNI)
        )
        call_kwargs = {
            "bypass_sni": not disable_bypass_sni,
            "dns_cache_file": str(self._config_manager.host_map_file),
            "dns_update_hosts": False,
            "runtime_dns_resolve": False,
            "max_retries": 2,
            **kwargs,
        }
        result = await asyncio.to_thread(
            pixiv,
            action,
            params,
            **call_kwargs,
        )

        transient_statuses = {403, 429, 440, 500, 502, 503, 504}
        if (
            not result.get("ok")
            and action in {"search_illust", "search_user"}
            and result.get("status") in transient_statuses
            and not disable_bypass_sni
        ):
            logger.warning(
                "[pixivdirect] Retrying %s after transient status %s",
                action,
                result.get("status"),
            )
            await self._refresh_dns_cache(reason=f"retry:{action}")
            retry_kwargs = {
                **call_kwargs,
                "runtime_dns_resolve": True,
            }
            result = await asyncio.to_thread(
                pixiv,
                action,
                params,
                **retry_kwargs,
            )
            await self._mark_dns_refreshed()
        return result

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

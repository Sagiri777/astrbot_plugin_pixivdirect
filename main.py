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
)
from .emoji_reaction import EmojiReactionHandler
from .image_handler import ImageHandler
from .pixivSDK import pixiv
from .utils import help_text


@register("pixivdirect", "Sagiri777", "PixivDirect command plugin", "1.1.0")
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
        )

    async def initialize(self):
        self._config_manager.ensure_directories()
        self._config_manager.load_all()
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

    async def _consume_dns_refresh_flag(self) -> bool:
        now = time.time()
        if now < self._dns_next_refresh_at:
            return False

        async with self._dns_refresh_lock:
            now = time.time()
            if now < self._dns_next_refresh_at:
                return False

            if not self._config_manager.host_map_file.exists():
                self._dns_next_refresh_at = self._next_dns_refresh_time()
                return True

            try:
                file_mtime = self._config_manager.host_map_file.stat().st_mtime
            except OSError:
                self._dns_next_refresh_at = self._next_dns_refresh_time()
                return True

            from datetime import datetime

            today_4am = (
                datetime.now()
                .replace(hour=4, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            if now >= today_4am and file_mtime < today_4am:
                self._dns_next_refresh_at = self._next_dns_refresh_time()
                return True

            self._dns_next_refresh_at = self._next_dns_refresh_time()
            return False

    async def _mark_dns_refreshed(self) -> None:
        async with self._dns_refresh_lock:
            self._dns_next_refresh_at = self._next_dns_refresh_time()

    async def _pixiv_call(
        self, action: str, params: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        dns_update_hosts = await self._consume_dns_refresh_flag()
        result = await asyncio.to_thread(
            pixiv,
            action,
            params,
            dns_cache_file=str(self._config_manager.host_map_file),
            dns_update_hosts=dns_update_hosts,
            runtime_dns_resolve=False,
            max_retries=2,
            **kwargs,
        )
        if dns_update_hosts:
            await self._mark_dns_refreshed()
        return result

    async def _idle_cache_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(IDLE_CACHE_INTERVAL_SECONDS)
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
        if now - self._last_idle_cache_ts < IDLE_CACHE_INTERVAL_SECONDS:
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
                logger.warning(
                    "[pixivdirect] Idle cache failed for user %s: %s", uid, exc
                )

    async def _idle_cache_user(self, uid: str, refresh_token: str) -> None:
        user_cache = self._config_manager.random_cache.get(uid, {})
        current_queue = user_cache.get(DEFAULT_POOL_KEY, [])

        if len(current_queue) >= DEFAULT_CACHE_SIZE:
            return

        items_to_add = DEFAULT_CACHE_SIZE - len(current_queue)
        items_to_add = min(items_to_add, IDLE_CACHE_COUNT)

        user_queue = self._config_manager.idle_cache_queue.get(uid, [])
        filter_params = {"restrict": "public", "max_pages": 3}

        if user_queue:
            queue_item = user_queue[0]
            filter_params = queue_item.get("filter_params", filter_params)
            remaining = queue_item.get("remaining", 1)

            if remaining != "always":
                remaining = int(remaining) - 1
                if remaining <= 0:
                    user_queue.pop(0)
                else:
                    queue_item["remaining"] = remaining
                if not user_queue:
                    self._config_manager.idle_cache_queue.pop(uid, None)
                await self._config_manager.save_idle_cache_queue()

        latest_refresh_token, error = await self._command_handler._enqueue_random_items(
            user_key=uid,
            cache_key=DEFAULT_POOL_KEY,
            refresh_token=refresh_token,
            filter_params=filter_params,
            count=items_to_add,
        )

        if error:
            logger.warning("[pixivdirect] Idle cache error for user %s: %s", uid, error)
        else:
            filter_desc = (
                filter_params.get("tag") or filter_params.get("author") or "default"
            )
            logger.info(
                "[pixivdirect] Cached %d items for user %s (filter: %s)",
                items_to_add,
                uid,
                filter_desc,
            )

    @filter.command("pixiv")
    async def pixiv_command(self, event: AstrMessageEvent, args_str: str = ""):
        """Pixiv commands: help, login, id, random."""
        limited = await self._command_handler.rate_limit_message(event)
        if limited:
            await self._emoji_handler.add_emoji_reaction(event, "rate_limit")
            yield event.plain_result(limited)
            return

        tokens = (
            [t for t in re.split(r"\s+", args_str.strip()) if t] if args_str else []
        )
        sub_cmd = tokens[0].lower() if tokens else "help"

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
        else:
            yield event.plain_result(
                f"❌ 未知子命令：{sub_cmd}，请使用 /pixiv help 查看帮助。"
            )

    async def terminate(self):
        if self._idle_cache_task and not self._idle_cache_task.done():
            self._idle_cache_task.cancel()
            try:
                await self._idle_cache_task
            except asyncio.CancelledError:
                pass
        self._config_manager.random_cache.clear()

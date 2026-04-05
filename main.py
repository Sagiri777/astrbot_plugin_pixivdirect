from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .cache_manager import CacheManager
from .commands import CommandHandler
from .config_manager import ConfigManager
from .constants import PLUGIN_ID
from .image_handler import ImageHandler
from .infrastructure.pixiv_client import PixivClientFacade
from .utils import parse_command_tokens


class PixivDirectPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        root_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_ID
        self._config = ConfigManager(root_dir)
        self._cache = CacheManager(self._config)
        self._client = PixivClientFacade()
        self._image = ImageHandler(
            cache_dir=self._config.cache_dir,
            pixiv_call_func=self._pixiv_call,
        )
        self._commands = CommandHandler(
            config_manager=self._config,
            cache_manager=self._cache,
            image_handler=self._image,
            pixiv_call_func=self._pixiv_call,
        )

    async def initialize(self):
        self._config.ensure_directories()
        self._config.load_all()

    async def _pixiv_call(self, action: str, params: dict, **kwargs):
        return await asyncio.to_thread(
            self._client.call_action, action, params, **kwargs
        )

    @filter.command("pixiv")
    async def pixiv_command(self, event: AstrMessageEvent, args_str: str = ""):
        tokens = parse_command_tokens(args_str)
        if not tokens:
            async for result in self._commands.handle_help(event):
                yield result
            return

        subcommand = tokens[0].lower()
        if subcommand == "help":
            async for result in self._commands.handle_help(event):
                yield result
            return
        if subcommand == "login":
            async for result in self._commands.handle_login(event, tokens):
                yield result
            return
        if subcommand == "quality":
            async for result in self._commands.handle_quality(event, tokens):
                yield result
            return
        if subcommand == "id":
            async for result in self._commands.handle_id(event, tokens):
                yield result
            return
        if subcommand == "search":
            async for result in self._commands.handle_search(
                event, tokens, user_search=False
            ):
                yield result
            return
        if subcommand == "searchuser":
            async for result in self._commands.handle_search(
                event, tokens, user_search=True
            ):
                yield result
            return
        if subcommand == "ranking":
            async for result in self._commands.handle_ranking(event, tokens):
                yield result
            return
        if subcommand == "recommended":
            async for result in self._commands.handle_recommended(event, tokens):
                yield result
            return
        if subcommand == "related":
            async for result in self._commands.handle_related(event, tokens):
                yield result
            return
        if subcommand == "ugoira":
            async for result in self._commands.handle_ugoira(event, tokens):
                yield result
            return
        if subcommand == "random":
            async for result in self._commands.handle_random(event, tokens):
                yield result
            return
        if subcommand == "dns":
            async for result in self._commands.handle_dns(event):
                yield result
            return

        async for result in self._commands.handle_help(event):
            yield result

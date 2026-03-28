from __future__ import annotations

import asyncio
import time
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .constants import EMOJI_MAP, STAGE_EMOJIS

# Minimum interval (seconds) between duplicate stage reactions on the same message
_MIN_REACTION_INTERVAL: float = 2.0


class EmojiReactionHandler:
    """Handles emoji reactions for messages."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled
        # Track last reaction time: (message_id, stage) -> timestamp
        self._last_reaction: dict[tuple[Any, str], float] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def _is_duplicate(self, message_id: Any, stage: str) -> bool:
        """Check if the same stage was already applied to this message recently."""
        key = (message_id, stage)
        now = time.monotonic()
        last = self._last_reaction.get(key)
        if last is not None and (now - last) < _MIN_REACTION_INTERVAL:
            return True
        self._last_reaction[key] = now
        # Prune stale entries to avoid unbounded growth
        if len(self._last_reaction) > 256:
            cutoff = now - _MIN_REACTION_INTERVAL * 2
            self._last_reaction = {
                k: v for k, v in self._last_reaction.items() if v > cutoff
            }
        return False

    @staticmethod
    def _extract_aiocqhttp_message_id(event: AstrMessageEvent) -> Any | None:
        if event.get_platform_name() != "aiocqhttp":
            return None

        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )

        if not isinstance(event, AiocqhttpMessageEvent):
            return None

        return getattr(getattr(event, "message_obj", None), "message_id", None)

    @staticmethod
    def _get_stage_emoji_ids(stage: str) -> list[int]:
        emoji_ids: list[int] = []
        for emoji_name in STAGE_EMOJIS.get(stage, []):
            emoji_id = EMOJI_MAP.get(emoji_name)
            if emoji_id is not None:
                emoji_ids.append(emoji_id)
        return emoji_ids

    async def _set_emoji_like(
        self, event: AstrMessageEvent, message_id: Any, emoji_id: int, set_: bool = True
    ) -> bool:
        """Try direct bot.set_msg_emoji_like first, fall back to call_action."""
        bot = getattr(event, "bot", None)
        if bot is not None:
            # Primary: direct method call (like exampleEmojiReaction.py)
            if hasattr(bot, "set_msg_emoji_like"):
                try:
                    await bot.set_msg_emoji_like(
                        message_id=message_id, emoji_id=emoji_id, set=set_
                    )
                    return True
                except Exception as e:
                    logger.debug(
                        "[pixivdirect] Direct set_msg_emoji_like failed, trying fallback: %s",
                        e,
                    )

            # Fallback: call_action via bot.api
            api = getattr(bot, "api", None)
            if api is not None and hasattr(api, "call_action"):
                try:
                    await api.call_action(
                        "set_msg_emoji_like",
                        message_id=message_id,
                        emoji_id=str(emoji_id),
                        set=set_,
                    )
                    return True
                except Exception as e:
                    logger.warning(
                        "[pixivdirect] Fallback call_action set_msg_emoji_like failed: %s",
                        e,
                    )
                    return False

        logger.debug("[pixivdirect] No suitable bot/api for emoji reaction")
        return False

    async def add_emoji_reaction(self, event: AstrMessageEvent, stage: str) -> None:
        """Add stage-related emoji reactions to the current message."""
        if not self._enabled:
            return

        try:
            message_id = self._extract_aiocqhttp_message_id(event)
            if message_id is None:
                return

            # Rate limit: skip if same stage was applied to this message recently
            if self._is_duplicate(message_id, stage):
                logger.debug(
                    "[pixivdirect] Skipping duplicate emoji reaction: stage=%s message_id=%s",
                    stage,
                    message_id,
                )
                return

            # Get emoji list for current stage
            emoji_ids = self._get_stage_emoji_ids(stage)
            if not emoji_ids:
                return

            logger.debug(
                "[pixivdirect] Adding emoji reactions for stage=%s message_id=%s emojis=%s",
                stage,
                message_id,
                emoji_ids,
            )

            # Send emoji reactions sequentially
            for emoji_id in emoji_ids:
                await self._set_emoji_like(event, message_id, emoji_id, set_=True)
                await asyncio.sleep(0.3)

        except Exception as e:
            logger.warning("[pixivdirect] Error adding emoji reaction: %s", e)

    async def remove_emoji_reaction(self, event: AstrMessageEvent, stage: str) -> None:
        """Remove stage-related emoji reactions from the current message."""
        if not self._enabled:
            return

        try:
            message_id = self._extract_aiocqhttp_message_id(event)
            if message_id is None:
                return

            emoji_ids = self._get_stage_emoji_ids(stage)
            if not emoji_ids:
                return

            logger.debug(
                "[pixivdirect] Removing emoji reactions for stage=%s message_id=%s emojis=%s",
                stage,
                message_id,
                emoji_ids,
            )

            for emoji_id in emoji_ids:
                await self._set_emoji_like(event, message_id, emoji_id, set_=False)
                await asyncio.sleep(0.3)

        except Exception as e:
            logger.warning("[pixivdirect] Error removing emoji reaction: %s", e)

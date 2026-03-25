from __future__ import annotations

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .constants import EMOJI_MAP, STAGE_EMOJIS


class EmojiReactionHandler:
    """Handles emoji reactions for messages."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    async def add_emoji_reaction(self, event: AstrMessageEvent, stage: str) -> None:
        """Add stage-related emoji reactions to the current message."""
        if not self._enabled:
            logger.info("[pixivdirect] Emoji reaction is disabled, skipping")
            return

        try:
            logger.info(f"[pixivdirect] _add_emoji_reaction called for stage: {stage}")
            logger.info(f"[pixivdirect] Platform name: {event.get_platform_name()}")

            # Only support aiocqhttp platform
            if event.get_platform_name() != "aiocqhttp":
                logger.info("[pixivdirect] Platform is not aiocqhttp, skipping")
                return

            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )

            if not isinstance(event, AiocqhttpMessageEvent):
                logger.info(
                    f"[pixivdirect] Event is not AiocqhttpMessageEvent, type: {type(event)}"
                )
                return

            # Get emoji list for current stage
            emoji_names = STAGE_EMOJIS.get(stage, [])
            if not emoji_names:
                logger.info(f"[pixivdirect] No emoji names for stage: {stage}")
                return

            # Get emoji IDs
            emoji_ids = []
            for emoji_name in emoji_names:
                emoji_id = EMOJI_MAP.get(emoji_name)
                if emoji_id is not None:
                    emoji_ids.append(str(emoji_id))

            if not emoji_ids:
                logger.info(f"[pixivdirect] No emoji IDs found for stage: {stage}")
                return

            # Get message ID and client
            client = event.bot
            message_id = event.message_obj.message_id

            logger.info(f"[pixivdirect] Bot type: {type(client)}")
            logger.info(f"[pixivdirect] Message ID: {message_id}")
            logger.info(f"[pixivdirect] Adding emoji reactions: {emoji_ids}")

            # Send emoji reactions sequentially
            for emoji_id in emoji_ids:
                try:
                    result = await client.api.call_action(
                        "set_msg_emoji_like",
                        message_id=message_id,
                        emoji_id=emoji_id,
                    )
                    logger.info(f"[pixivdirect] Emoji reaction result: {result}")
                    await asyncio.sleep(0.3)  # Add delay to avoid too fast requests
                except Exception as e:
                    logger.warning(
                        "[pixivdirect] Failed to add emoji reaction %s: %s",
                        emoji_id,
                        e,
                    )

        except Exception as e:
            logger.warning("[pixivdirect] Error adding emoji reaction: %s", e)

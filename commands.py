from __future__ import annotations

import asyncio
import time
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .cache_manager import CacheManager
from .config_manager import ConfigManager
from .constants import (
    DEFAULT_POOL_KEY,
    MAX_RANDOM_WARMUP,
)
from .emoji_reaction import EmojiReactionHandler
from .image_handler import ImageHandler
from .utils import (
    format_author_detail,
    format_illust_detail,
    format_random_bookmark,
    user_key,
)


class CommandHandler:
    """Handles all Pixiv plugin commands."""

    def __init__(
        self,
        config_manager: ConfigManager,
        cache_manager: CacheManager,
        image_handler: ImageHandler,
        emoji_handler: EmojiReactionHandler,
        pixiv_call_func,
        min_command_interval: float,
        max_random_pages: int,
        idle_cache_count: int,
        default_cache_size: int,
    ) -> None:
        self._config = config_manager
        self._cache = cache_manager
        self._image = image_handler
        self._emoji = emoji_handler
        self._pixiv_call = pixiv_call_func
        self._min_command_interval = min_command_interval
        self._max_random_pages = max_random_pages
        self._idle_cache_count = idle_cache_count
        self._default_cache_size = default_cache_size
        self._last_command_ts: dict[str, float] = {}
        self._rate_limit_lock = asyncio.Lock()

    async def rate_limit_message(self, event: AstrMessageEvent) -> str | None:
        """Check if user is rate limited and return message if so."""
        key = user_key(event)
        now = time.time()
        async with self._rate_limit_lock:
            last = self._last_command_ts.get(key)
            self._last_command_ts[key] = now
        if last is None:
            return None
        wait_seconds = self._min_command_interval - (now - last)
        if wait_seconds > 0:
            return f"⏳ 请求过于频繁，请在 {wait_seconds:.1f} 秒后重试。"
        return None

    def get_user_token(self, event: AstrMessageEvent) -> str | None:
        """Get the user's refresh token."""
        return self._config.token_map.get(user_key(event))

    async def set_user_token(self, event: AstrMessageEvent, refresh_token: str) -> None:
        """Set the user's refresh token."""
        self._config.token_map[user_key(event)] = refresh_token
        await self._config.save_tokens()

    def find_user_by_name(self, target_name: str) -> str | None:
        """Find user key by their display name or account."""
        if not target_name:
            return None

        target_lower = target_name.lower()

        for key in self._config.token_map.keys():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue

            platform, sender_id = parts

            user_cache = self._config.random_cache.get(key, {})
            for cache_items in user_cache.values():
                for item in cache_items:
                    caption = item.get("caption", "")
                    if (
                        f"作者: {target_name}" in caption
                        or target_lower in caption.lower()
                    ):
                        return key

            if sender_id == target_name:
                return key

        return None

    def should_send_image(self, event: AstrMessageEvent, item: dict[str, Any]) -> bool:
        """Determine if an image should be sent based on R-18 and group tag filtering rules."""
        is_group = bool(event.get_group_id())
        if not is_group:
            return True

        group_id = str(event.get_group_id())
        blocked_tags = self._config.group_blocked_tags.get(group_id, [])
        if blocked_tags:
            item_tags = item.get("tags", [])
            if isinstance(item_tags, list):
                for item_tag in item_tags:
                    if isinstance(item_tag, str):
                        for blocked_tag in blocked_tags:
                            if item_tag.lower() == blocked_tag.lower():
                                return False

        if self._config.r18_in_group:
            return True
        if self._cache.is_r18_item(item):
            return False
        return True

    async def handle_login(self, event: AstrMessageEvent, args: list[str]):
        """Handle login command."""
        if len(args) < 2:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 用法：/pixiv login {refresh_token}")
            return

        refresh_token = args[1].strip()
        if not refresh_token:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ refresh_token 不能为空。")
            return

        await self._emoji.add_emoji_reaction(event, "login")
        verify_result = await self._pixiv_call(
            "random_bookmark_image",
            {"max_pages": 1},
            refresh_token=refresh_token,
        )
        if not verify_result.get("ok"):
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(
                "❌ Token 校验失败：" + self._image.format_pixiv_error(verify_result),
            )
            return

        latest_refresh_token = str(verify_result.get("refresh_token") or refresh_token)
        await self.set_user_token(event, latest_refresh_token)
        yield event.plain_result("✅ 已绑定当前用户的 Pixiv Token。")

    async def handle_id(self, event: AstrMessageEvent, args: list[str]):
        """Handle id command (illust or artist)."""
        if len(args) < 3:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(
                "❌ 用法：/pixiv id i {illust_id} 或 /pixiv id a {artist_id}"
            )
            return

        user_token = self.get_user_token(event)
        if not user_token:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
            return

        typ = args[1].lower().strip()
        target_id = args[2].strip()
        if not target_id.isdigit():
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ ID 必须是数字。")
            return

        if typ == "i":
            # Check cache first
            cached_item = self._cache.find_cached_by_illust_id(int(target_id))
            if cached_item:
                await self._emoji.add_emoji_reaction(event, "query_illust")
                caption = cached_item.get("caption") or "Pixiv 作品详情（缓存）"
                path = cached_item.get("path")
                if path and self.should_send_image(event, cached_item):
                    yield (
                        event.make_result()
                        .message(f"{caption}\n- 来源: 缓存")
                        .file_image(path)
                    )
                else:
                    yield event.plain_result(
                        f"{caption}\n- 来源: 缓存\n⚠️ R-18 内容在群聊中仅显示信息"
                    )
                return

            await self._emoji.add_emoji_reaction(event, "query_illust")
            result = await self._pixiv_call(
                "illust_detail",
                {"illust_id": int(target_id)},
                refresh_token=user_token,
            )
            if not result.get("ok"):
                await self._emoji.add_emoji_reaction(event, "error")
                yield event.plain_result(self._image.format_pixiv_error(result))
                return

            latest_refresh_token = str(result.get("refresh_token") or user_token)
            if latest_refresh_token != user_token:
                await self.set_user_token(event, latest_refresh_token)

            data = result.get("data")
            illust = data.get("illust") if isinstance(data, dict) else None
            if not isinstance(illust, dict):
                yield event.plain_result("❌ 解析作品详情失败。")
                return

            user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
            tags_raw = (
                illust.get("tags") if isinstance(illust.get("tags"), list) else []
            )
            tags: list[str] = []
            for item in tags_raw:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        tags.append(name)

            caption = format_illust_detail(illust, user, tags)

            # Handle ugoira
            illust_type = illust.get("type", "")
            if illust_type == "ugoira":
                try:
                    ugoira_result = await self._pixiv_call(
                        "ugoira_metadata",
                        {"illust_id": int(target_id)},
                        refresh_token=latest_refresh_token,
                    )
                    if not ugoira_result.get("ok"):
                        yield event.plain_result(
                            self._image.format_pixiv_error(ugoira_result)
                        )
                        return

                    ugoira_data = ugoira_result.get("data")
                    if not isinstance(ugoira_data, dict):
                        yield event.plain_result("❌ 解析动图元数据失败。")
                        return

                    ugoira_metadata = ugoira_data.get("ugoira_metadata")
                    if not isinstance(ugoira_metadata, dict):
                        yield event.plain_result("❌ 动图元数据格式异常。")
                        return

                    zip_urls = ugoira_metadata.get("zip_urls")
                    if not isinstance(zip_urls, dict):
                        yield event.plain_result("❌ 动图 zip URL 不存在。")
                        return

                    zip_url = zip_urls.get("original") or zip_urls.get("medium")
                    if not zip_url:
                        yield event.plain_result("❌ 动图 zip URL 为空。")
                        return

                    frames = ugoira_metadata.get("frames")
                    if not isinstance(frames, list):
                        yield event.plain_result("❌ 动图帧信息不存在。")
                        return

                    zip_path = await self._image.download_ugoira_zip_to_cache(
                        zip_url,
                        access_token=ugoira_result.get("access_token"),
                        refresh_token=str(
                            ugoira_result.get("refresh_token") or latest_refresh_token
                        ),
                        name_prefix=f"ugoira_{target_id}",
                    )

                    gif_path = (
                        self._config.cache_dir
                        / f"ugoira_{target_id}_{int(time.time() * 1000)}.gif"
                    )
                    await asyncio.to_thread(
                        self._image.render_ugoira_to_gif,
                        zip_path,
                        frames,
                        str(gif_path),
                    )

                    yield event.make_result().message(caption).file_image(str(gif_path))

                    # Cache the ugoira
                    try:
                        _user_key = user_key(event)
                        _user_cache = self._config.random_cache.setdefault(
                            _user_key, {}
                        )
                        _queue = _user_cache.setdefault(DEFAULT_POOL_KEY, [])
                        _queue.append(
                            {
                                "path": str(gif_path),
                                "caption": caption,
                                "x_restrict": illust.get("x_restrict", 0)
                                if isinstance(illust.get("x_restrict"), int)
                                else 0,
                                "tags": tags,
                                "illust_id": int(target_id)
                                if target_id.isdigit()
                                else None,
                            }
                        )
                        await self._config.save_cache_index()
                    except Exception as exc:
                        logger.warning(
                            "[pixivdirect] Failed to cache ugoira %s: %s",
                            target_id,
                            exc,
                        )
                    return

                except Exception as exc:
                    logger.warning("[pixivdirect] Ugoira processing failed: %s", exc)
                    yield event.plain_result(f"{caption}\n\n❌ 动图处理失败：{exc}")
                    return

            # Handle normal image
            preview_url = None
            image_urls = illust.get("image_urls")
            if isinstance(image_urls, dict):
                for key in ("large", "medium", "square_medium"):
                    value = image_urls.get(key)
                    if isinstance(value, str) and value:
                        preview_url = value
                        break
            if not preview_url:
                meta_single_page = illust.get("meta_single_page")
                if isinstance(meta_single_page, dict):
                    value = meta_single_page.get("original_image_url")
                    if isinstance(value, str) and value:
                        preview_url = value

            if preview_url:
                try:
                    local_path = await self._image.download_image_to_cache(
                        preview_url,
                        access_token=result.get("access_token"),
                        refresh_token=latest_refresh_token,
                        name_prefix=f"illust_{illust.get('id') or target_id}",
                    )
                    yield event.make_result().message(caption).file_image(local_path)

                    # Cache the illust
                    try:
                        _user_key = user_key(event)
                        _user_cache = self._config.random_cache.setdefault(
                            _user_key, {}
                        )
                        _queue = _user_cache.setdefault(DEFAULT_POOL_KEY, [])
                        _queue.append(
                            {
                                "path": local_path,
                                "caption": caption,
                                "x_restrict": illust.get("x_restrict", 0)
                                if isinstance(illust.get("x_restrict"), int)
                                else 0,
                                "tags": tags,
                                "illust_id": int(target_id)
                                if target_id.isdigit()
                                else None,
                            }
                        )
                        await self._config.save_cache_index()
                    except Exception as exc:
                        logger.warning(
                            "[pixivdirect] Failed to cache illust %s: %s",
                            target_id,
                            exc,
                        )
                    return
                except Exception as exc:
                    logger.warning("[pixivdirect] Preview download failed: %s", exc)

            yield event.plain_result(caption)
            return

        if typ == "a":
            await self._emoji.add_emoji_reaction(event, "query_artist")
            result = await self._pixiv_call(
                "user_detail",
                {"user_id": int(target_id)},
                refresh_token=user_token,
            )
            if not result.get("ok"):
                await self._emoji.add_emoji_reaction(event, "error")
                yield event.plain_result(self._image.format_pixiv_error(result))
                return

            latest_refresh_token = str(result.get("refresh_token") or user_token)
            if latest_refresh_token != user_token:
                await self.set_user_token(event, latest_refresh_token)

            data = result.get("data")
            user = data.get("user") if isinstance(data, dict) else None
            profile = data.get("profile") if isinstance(data, dict) else None
            if not isinstance(user, dict) or not isinstance(profile, dict):
                yield event.plain_result("❌ 解析作者详情失败。")
                return

            caption = format_author_detail(user, profile)
            yield event.plain_result(caption)
            return

        yield event.plain_result("❌ 未知类型，请使用 i（作品）或 a（作者）。")

    async def handle_random(self, event: AstrMessageEvent, args: list[str]):
        """Handle random bookmark command."""
        logger.info(f"[pixivdirect] handle_random called with args: {args}")
        # Handle share config
        if len(args) >= 2 and args[1].lower() == "share":
            logger.info("[pixivdirect] Processing share command")
            key = user_key(event)
            if len(args) >= 3:
                value = args[2].lower()
                if value in ("true", "1", "yes", "on"):
                    self._config.share_enabled[key] = True
                    await self._config.save_share_config()
                    yield event.plain_result("✅ 已开启收藏分享功能。")
                    return
                elif value in ("false", "0", "no", "off"):
                    self._config.share_enabled[key] = False
                    await self._config.save_share_config()
                    yield event.plain_result("✅ 已关闭收藏分享功能。")
                    return
                else:
                    yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                    return
            else:
                enabled = self._config.share_enabled.get(key, False)
                status = "开启" if enabled else "关闭"
                yield event.plain_result(f"ℹ️ 收藏分享功能当前状态：{status}")
                return

        # Handle DNS config
        if len(args) >= 2 and args[1].lower() == "dns":
            if len(args) >= 3 and args[2].lower() == "refresh":
                if not event.is_admin():
                    yield event.plain_result("❌ 仅 AstrBot 管理员可手动刷新 DNS。")
                    return
                yield event.plain_result(
                    "✅ 已触发 DNS 刷新，将在下次 Pixiv API 请求时执行。"
                )
                return
            else:
                yield event.plain_result(
                    "ℹ️ DNS 刷新状态：\n- 使用 /pixiv dns refresh 手动触发刷新"
                )
                return

        # Handle r18 config
        if len(args) >= 2 and args[1].lower() == "r18":
            if len(args) >= 3:
                if not event.is_admin():
                    yield event.plain_result(
                        "❌ 仅 AstrBot 管理员可修改 R-18 群聊设置。"
                    )
                    return
                value = args[2].lower()
                if value in ("true", "1", "yes", "on"):
                    self._config.r18_in_group = True
                    await self._config.save_r18_config()
                    yield event.plain_result("✅ 已开启群聊 R-18 内容显示。")
                    return
                elif value in ("false", "0", "no", "off"):
                    self._config.r18_in_group = False
                    await self._config.save_r18_config()
                    yield event.plain_result("✅ 已关闭群聊 R-18 内容显示。")
                    return
                else:
                    yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                    return
            else:
                status = "开启" if self._config.r18_in_group else "关闭"
                yield event.plain_result(f"ℹ️ 群聊 R-18 内容显示当前状态：{status}")
                return

        # Handle unique config
        if len(args) >= 2 and args[1].lower() == "unique":
            if len(args) >= 3:
                if not event.is_admin():
                    yield event.plain_result("❌ 仅 AstrBot 管理员可修改唯一随机设置。")
                    return
                value = args[2].lower()
                if value in ("true", "1", "yes", "on"):
                    self._config.random_unique = True
                    await self._config.save_unique_config()
                    yield event.plain_result(
                        "✅ 已开启唯一随机模式（图片发送后将从缓存池移除）。"
                    )
                    return
                elif value in ("false", "0", "no", "off"):
                    self._config.random_unique = False
                    await self._config.save_unique_config()
                    yield event.plain_result(
                        "✅ 已关闭唯一随机模式（图片发送后保留在缓存池中）。"
                    )
                    return
                else:
                    yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                    return
            else:
                status = "开启" if self._config.random_unique else "关闭"
                yield event.plain_result(f"ℹ️ 唯一随机模式当前状态：{status}")
                return

        # Handle groupblock config
        if len(args) >= 2 and args[1].lower() == "groupblock":
            group_id = event.get_group_id()
            if not group_id:
                yield event.plain_result("❌ 此命令仅可在群聊中使用。")
                return

            if not event.is_admin():
                yield event.plain_result("❌ 仅 AstrBot 管理员可修改群聊屏蔽标签。")
                return

            group_id_str = str(group_id)

            if len(args) >= 4 and args[2].lower() == "add":
                tag = args[3]
                blocked_tags = self._config.group_blocked_tags.setdefault(
                    group_id_str, []
                )
                if tag not in blocked_tags:
                    blocked_tags.append(tag)
                    await self._config.save_group_blocked_tags()
                    yield event.plain_result(
                        f"✅ 已将标签「{tag}」添加到本群屏蔽列表。"
                    )
                else:
                    yield event.plain_result(f"ℹ️ 标签「{tag}」已在本群屏蔽列表中。")
                return
            elif len(args) >= 4 and args[2].lower() == "remove":
                tag = args[3]
                blocked_tags = self._config.group_blocked_tags.get(group_id_str, [])
                if tag in blocked_tags:
                    blocked_tags.remove(tag)
                    if not blocked_tags:
                        self._config.group_blocked_tags.pop(group_id_str, None)
                    await self._config.save_group_blocked_tags()
                    yield event.plain_result(
                        f"✅ 已将标签「{tag}」从本群屏蔽列表中移除。"
                    )
                else:
                    yield event.plain_result(f"ℹ️ 标签「{tag}」不在本群屏蔽列表中。")
                return
            elif len(args) >= 3 and args[2].lower() == "list":
                blocked_tags = self._config.group_blocked_tags.get(group_id_str, [])
                if blocked_tags:
                    tags_text = "、".join(blocked_tags)
                    yield event.plain_result(f"📋 本群屏蔽的标签：{tags_text}")
                else:
                    yield event.plain_result("ℹ️ 本群没有设置屏蔽标签。")
                return
            elif len(args) >= 3 and args[2].lower() == "clear":
                self._config.group_blocked_tags.pop(group_id_str, None)
                await self._config.save_group_blocked_tags()
                yield event.plain_result("✅ 已清空本群屏蔽标签列表。")
                return
            else:
                yield event.plain_result(
                    "📋 用法：\n"
                    "- /pixiv groupblock add tag=xxx  # 添加屏蔽标签\n"
                    "- /pixiv groupblock remove tag=xxx  # 移除屏蔽标签\n"
                    "- /pixiv groupblock list  # 查看屏蔽列表\n"
                    "- /pixiv groupblock clear  # 清空屏蔽列表"
                )
                return

        # Handle cache config
        if len(args) >= 2 and args[1].lower() == "cache":
            user_token = self.get_user_token(event)
            if not user_token:
                await self._emoji.add_emoji_reaction(event, "error")
                yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
                return

            key = user_key(event)

            if len(args) >= 3 and args[2].lower() == "add":
                cache_filter_tokens = args[3:]
                cache_filter_params, cache_filter_summary = (
                    self._cache.parse_random_filter(
                        cache_filter_tokens, self._max_random_pages
                    )
                )

                count = 1
                if "count" in cache_filter_params:
                    count_raw = str(cache_filter_params.pop("count"))
                    if count_raw.lower() == "always":
                        count = "always"
                    else:
                        try:
                            count = max(1, int(count_raw))
                        except ValueError:
                            count = 1

                user_queue = self._config.idle_cache_queue.setdefault(key, [])
                user_queue.append(
                    {
                        "filter_params": cache_filter_params,
                        "count": count,
                        "remaining": count,
                    }
                )
                await self._config.save_idle_cache_queue()

                count_text = "始终" if count == "always" else f"{count}次"
                yield event.plain_result(
                    f"✅ 已添加闲时缓存任务：\n"
                    f"- 筛选条件: {cache_filter_summary}\n"
                    f"- 缓存次数: {count_text}\n"
                    f"- 队列中任务数: {len(user_queue)}"
                )
                return
            elif len(args) >= 3 and args[2].lower() == "list":
                user_queue = self._config.idle_cache_queue.get(key, [])
                if not user_queue:
                    yield event.plain_result("ℹ️ 当前没有待缓存的任务。")
                    return

                queue_text = "📋 当前闲时缓存队列：\n"
                for i, item in enumerate(user_queue, 1):
                    fp = item.get("filter_params", {})
                    remaining = item.get("remaining", 0)
                    count = item.get("count", 1)
                    _, summary = self._cache.parse_random_filter(
                        [f"{k}={v}" for k, v in fp.items()], self._max_random_pages
                    )
                    remain_text = (
                        "始终"
                        if remaining == "always"
                        else f"剩余{remaining}次/{count}次"
                    )
                    queue_text += f"{i}. {summary} ({remain_text})\n"
                yield event.plain_result(queue_text.strip())
                return
            elif len(args) >= 3 and args[2].lower() == "clear":
                self._config.idle_cache_queue.pop(key, None)
                await self._config.save_idle_cache_queue()
                yield event.plain_result("✅ 已清空闲时缓存队列。")
                return
            else:
                yield event.plain_result(
                    "📋 用法：\n"
                    "- /pixiv random cache add tag=xxx count=N|always  # 添加缓存任务\n"
                    "- /pixiv random cache list  # 查看队列\n"
                    "- /pixiv random cache clear  # 清空队列"
                )
                return

        # Parse @username and filter params
        target_user_key = None
        target_user_name = None
        remaining_args = []

        for token in args[1:]:
            if token.startswith("@"):
                target_user_name = token[1:]
                target_user_key = self.find_user_by_name(target_user_name)
                if not target_user_key:
                    yield event.plain_result(f"❌ 未找到用户：{target_user_name}")
                    return
                if not self._config.share_enabled.get(target_user_key, False):
                    yield event.plain_result(
                        f"❌ 用户 {target_user_name} 未开启收藏分享功能。"
                    )
                    return
            else:
                remaining_args.append(token)

        filter_params, filter_summary = self._cache.parse_random_filter(
            remaining_args, self._max_random_pages
        )
        filter_params.setdefault("restrict", "public")
        filter_params.setdefault("max_pages", 3)
        cache_key = self._cache.cache_key(filter_params)
        logger.info(
            f"[pixivdirect] Continuing with random bookmark, filter_params: {filter_params}"
        )

        # @someone mode - read from target user cache
        if target_user_key:
            cached_item = await self._cache.pop_cached_item(
                target_user_key, cache_key, filter_params
            )
            if cached_item:
                await self._emoji.add_emoji_reaction(event, "random")
                caption = cached_item.get("caption") or "Pixiv 随机收藏（缓存）"
                path = cached_item.get("path")
                if path and self.should_send_image(event, cached_item):
                    yield (
                        event.make_result()
                        .message(f"{caption}\n- 来源: 缓存（共享）")
                        .file_image(path)
                    )
                else:
                    msg = f"{caption}\n- 来源: 缓存（共享）"
                    if self._cache.is_r18_item(cached_item):
                        msg += "\n⚠️ R-18 内容在群聊中仅显示信息"
                    yield event.plain_result(msg)
                return
            else:
                hint = "❌ 该用户的缓存中没有找到符合条件的图片。"
                if filter_params.get("tag") or filter_params.get("author"):
                    hint += f"\n当前筛选: {filter_summary}"
                    hint += "\n💡 提示：可尝试其他筛选条件，如 tag=xxx author=xxx"
                yield event.plain_result(hint)
                return

        # Self cache mode - requires token
        user_token = self.get_user_token(event)
        if not user_token:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
            return

        key = user_key(event)

        # Try cache first
        cached_item = await self._cache.pop_cached_item(key, cache_key, filter_params)
        if cached_item:
            await self._emoji.add_emoji_reaction(event, "random")
            caption = cached_item.get("caption") or "Pixiv 随机收藏（缓存）"
            path = cached_item.get("path")
            remain_total = len(
                self._config.random_cache.get(key, {}).get(DEFAULT_POOL_KEY, [])
            )
            remain_matching = self._cache.count_matching_items(key, filter_params)
            if (
                filter_params.get("tag")
                or filter_params.get("author")
                or filter_params.get("author_id")
            ):
                remain_text = f"{remain_total}张 (匹配当前筛选: {remain_matching}张)"
            else:
                remain_text = f"{remain_total}张 (全部)"
            if path and self.should_send_image(event, cached_item):
                yield (
                    event.make_result()
                    .message(f"{caption}\n- 来源: 缓存\n- 剩余缓存: {remain_text}")
                    .file_image(path)
                )
            else:
                yield event.plain_result(
                    f"{caption}\n- 来源: 缓存\n- 剩余缓存: {remain_text}\n⚠️ R-18 内容在群聊中仅显示信息"
                )
            return

        # Cache empty, fetch new data
        warmup = 2
        raw_warmup = filter_params.pop("warmup", None)
        if raw_warmup is not None:
            try:
                warmup = max(1, min(MAX_RANDOM_WARMUP, int(str(raw_warmup))))
            except ValueError:
                warmup = 2

        await self._emoji.add_emoji_reaction(event, "random")
        latest_refresh_token, error = await self._enqueue_random_items(
            user_key=key,
            cache_key=cache_key,
            refresh_token=user_token,
            filter_params=filter_params,
            count=warmup,
        )
        if latest_refresh_token != user_token:
            await self.set_user_token(event, latest_refresh_token)

        if error:
            await self._emoji.add_emoji_reaction(event, "error")
            error_msg = f"❌ 获取随机收藏失败：{error}"
            if "No bookmarked illust matched filters" in error:
                tag_hint = filter_params.get("tag")
                if tag_hint:
                    error_msg += (
                        f"\n\n💡 提示：收藏中没有找到标签为「{tag_hint}」的作品。"
                    )
                    error_msg += "\n可能的原因："
                    error_msg += "\n1. 收藏中确实没有该标签的作品"
                    error_msg += "\n2. 标签名称不正确（Pixiv 标签区分大小写）"
                    error_msg += "\n3. 该标签的作品可能未被收藏"
                    if str(tag_hint).upper() in ("R18", "R-18"):
                        error_msg += "\n\n💡 R18 相关提示："
                        error_msg += "\n- Pixiv 上 R18 标签通常是「R-18」"
                        error_msg += "\n- 请确保收藏中确实有 R18 作品"
                        error_msg += "\n- 可尝试使用「restrict=private」查看私密收藏"
            yield event.plain_result(error_msg)
            return

        picked = await self._cache.pop_cached_item(key, cache_key, filter_params)
        if not picked:
            yield event.plain_result("❌ 未找到可发送的缓存图片。")
            return

        caption = picked.get("caption") or "Pixiv 随机收藏"
        path = picked.get("path")
        remain_total = len(
            self._config.random_cache.get(key, {}).get(DEFAULT_POOL_KEY, [])
        )
        remain_matching = self._cache.count_matching_items(key, filter_params)
        if (
            filter_params.get("tag")
            or filter_params.get("author")
            or filter_params.get("author_id")
        ):
            remain_text = f"{remain_total}张 (匹配当前筛选: {remain_matching}张)"
        else:
            remain_text = f"{remain_total}张 (全部)"
        if path and self.should_send_image(event, picked):
            yield (
                event.make_result()
                .message(
                    f"{caption}\n- 来源: 新获取\n- 剩余缓存: {remain_text}\n- 筛选条件: {filter_summary}",
                )
                .file_image(path)
            )
        else:
            yield event.plain_result(
                f"{caption}\n- 来源: 新获取\n- 剩余缓存: {remain_text}\n- 筛选条件: {filter_summary}\n⚠️ R-18 内容在群聊中仅显示信息"
            )

    async def _enqueue_random_items(
        self,
        *,
        user_key: str,
        cache_key: str,
        refresh_token: str,
        filter_params: dict[str, Any],
        count: int,
    ) -> tuple[str, str | None]:
        """Enqueue random bookmark items to cache."""
        latest_refresh_token = refresh_token
        user_cache = self._config.random_cache.setdefault(user_key, {})
        queue = user_cache.setdefault(DEFAULT_POOL_KEY, [])
        pending_items: list[dict[str, Any]] = []

        for _ in range(max(1, count)):
            random_result = await self._pixiv_call(
                "random_bookmark_image",
                filter_params,
                refresh_token=latest_refresh_token,
            )
            if not random_result.get("ok"):
                return latest_refresh_token, self._image.format_pixiv_error(
                    random_result
                )

            latest_refresh_token = str(
                random_result.get("refresh_token") or latest_refresh_token,
            )
            data = random_result.get("data")
            if not isinstance(data, dict):
                return (
                    latest_refresh_token,
                    "Pixiv 随机收藏返回数据格式异常。",
                )

            image_url = data.get("image_url")
            if not isinstance(image_url, str) or not image_url:
                return (
                    latest_refresh_token,
                    "Pixiv 随机收藏未返回图片地址。",
                )

            illust_id = data.get("id")
            title = str(data.get("title") or "（无标题）")
            author_data = (
                data.get("author") if isinstance(data.get("author"), dict) else {}
            )
            author_name = str(author_data.get("name") or "未知作者")
            author_id = author_data.get("id")

            illust_data = (
                data.get("illust") if isinstance(data.get("illust"), dict) else {}
            )

            pending_items.append(
                {
                    "illust_id": illust_id,
                    "title": title,
                    "author_name": author_name,
                    "author_id": author_id,
                    "filters": data.get("filters")
                    if isinstance(data.get("filters"), dict)
                    else {},
                    "tags": data.get("tags")
                    if isinstance(data.get("tags"), list)
                    else [],
                    "x_restrict": illust_data.get("x_restrict", 0)
                    if isinstance(illust_data.get("x_restrict"), int)
                    else 0,
                    "matched_count": data.get("matched_count"),
                    "pages_scanned": data.get("pages_scanned"),
                    "image_url": image_url,
                    "access_token": random_result.get("access_token"),
                    "refresh_token": latest_refresh_token,
                    "page_count": illust_data.get("page_count", 1),
                    "total_view": illust_data.get("total_view"),
                    "total_bookmarks": illust_data.get("total_bookmarks"),
                },
            )

        if not pending_items:
            return latest_refresh_token, "未找到符合筛选条件的收藏图片。"

        from .constants import RANDOM_DOWNLOAD_CONCURRENCY

        semaphore = asyncio.Semaphore(RANDOM_DOWNLOAD_CONCURRENCY)

        async def build_cache_item(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                local_path = await self._image.download_image_to_cache(
                    str(item["image_url"]),
                    access_token=(
                        str(item["access_token"]) if item.get("access_token") else None
                    ),
                    refresh_token=str(item["refresh_token"]),
                    name_prefix=f"bookmark_{item['illust_id'] or 'unknown'}",
                )
            caption = format_random_bookmark(
                item,
                matched_count=item.get("matched_count"),
                pages_scanned=item.get("pages_scanned"),
            )
            return {
                "path": local_path,
                "caption": caption,
                "x_restrict": item.get("x_restrict", 0),
                "tags": item.get("tags", []),
                "illust_id": item.get("illust_id"),
                "author_id": item.get("author_id"),
                "author_name": item.get("author_name"),
            }

        built_items = await asyncio.gather(
            *(build_cache_item(item) for item in pending_items),
            return_exceptions=True,
        )
        async with self._config._cache_lock:
            for built_item in built_items:
                if isinstance(built_item, Exception):
                    logger.warning(
                        "[pixivdirect] Random cache download failed: %s", built_item
                    )
                    continue
                queue.append(built_item)

        if not queue:
            return (
                latest_refresh_token,
                "随机结果图片缓存失败，请稍后重试。",
            )

        await self._config.save_cache_index()
        return latest_refresh_token, None

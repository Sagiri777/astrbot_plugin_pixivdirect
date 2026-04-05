from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .cache_manager import CacheManager
from .config_manager import ConfigManager
from .constants import (
    BYPASS_MODE_AUTO,
    BYPASS_MODE_OPTIONS,
    CONFIGURABLE_CONSTANT_ALIASES,
    CONFIGURABLE_CONSTANT_NAMES,
    CONFIGURABLE_CONSTANTS,
    DEFAULT_POOL_KEY,
    DISABLE_BYPASS_SNI,
    MAX_RANDOM_WARMUP,
    MAX_UNIQUE_SCAN_PAGES,
    MULTI_IMAGE_THRESHOLD,
    RANDOM_DOWNLOAD_CONCURRENCY,
    RANDOM_SOURCE_IMAGE,
    RANDOM_SOURCE_METADATA,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_DURATION_OPTIONS,
    SEARCH_MAX_LIMIT,
    SEARCH_SORT_OPTIONS,
    SEARCH_TARGET_OPTIONS,
    SEARCH_USER_SORT_OPTIONS,
)
from .emoji_reaction import EmojiReactionHandler
from .image_handler import ImageHandler
from .image_host import ImageHostHandler
from .utils import (
    format_author_detail,
    format_illust_detail,
    format_random_bookmark,
    format_search_result,
    format_search_user_result,
    user_key,
)


class CommandHandler:
    """Handles all Pixiv plugin commands."""

    _TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
    _FALSE_VALUES = frozenset({"false", "0", "no", "off"})

    def __init__(
        self,
        config_manager: ConfigManager,
        cache_manager: CacheManager,
        image_handler: ImageHandler,
        image_host_handler: ImageHostHandler,
        emoji_handler: EmojiReactionHandler,
        pixiv_call_func,
        min_command_interval: float,
        max_random_pages: int,
        idle_cache_count: int,
        default_cache_size: int,
        dns_time_getter=None,
        idle_cache_time_getter=None,
        idle_cache_all_func=None,
    ) -> None:
        self._config = config_manager
        self._cache = cache_manager
        self._image = image_handler
        self._image_host = image_host_handler
        self._emoji = emoji_handler
        self._pixiv_call = pixiv_call_func
        self._min_command_interval = min_command_interval
        self._max_random_pages = max_random_pages
        self._idle_cache_count = idle_cache_count
        self._default_cache_size = default_cache_size
        self._dns_time_getter = dns_time_getter
        self._idle_cache_time_getter = idle_cache_time_getter
        self._idle_cache_all_func = idle_cache_all_func
        self._last_command_ts: dict[str, float] = {}
        self._rate_limit_lock = asyncio.Lock()
        self._dns_refresh_func = None

    def set_dns_refresh_func(self, dns_refresh_func) -> None:
        self._dns_refresh_func = dns_refresh_func

    def _get_min_command_interval(self) -> float:
        return float(
            self._config.get_constant(
                "min_command_interval", self._min_command_interval
            )
        )

    def _get_max_random_pages(self) -> int:
        return int(
            self._config.get_constant("max_random_pages", self._max_random_pages)
        )

    def _get_idle_cache_count(self) -> int:
        return int(
            self._config.get_constant("idle_cache_count", self._idle_cache_count)
        )

    def _get_default_cache_size(self) -> int:
        return int(
            self._config.get_constant("default_cache_size", self._default_cache_size)
        )

    def _get_max_random_warmup(self) -> int:
        return int(self._config.get_constant("max_random_warmup", MAX_RANDOM_WARMUP))

    def _get_max_unique_scan_pages(self) -> int:
        return int(
            self._config.get_constant("max_unique_scan_pages", MAX_UNIQUE_SCAN_PAGES)
        )

    def _get_multi_image_threshold(self) -> int:
        return int(
            self._config.get_constant("multi_image_threshold", MULTI_IMAGE_THRESHOLD)
        )

    def _get_random_download_concurrency(self) -> int:
        return max(
            1,
            int(
                self._config.get_constant(
                    "random_download_concurrency",
                    RANDOM_DOWNLOAD_CONCURRENCY,
                )
            ),
        )

    @staticmethod
    def _event_log_context(event: AstrMessageEvent) -> str:
        platform = event.get_platform_name()
        sender_id = user_key(event)
        group_id = event.get_group_id()
        if group_id:
            return f"platform={platform}, group={group_id}, user={sender_id}"
        return f"platform={platform}, private_user={sender_id}"

    def _log_send_request(
        self,
        event: AstrMessageEvent,
        *,
        stage: str,
        image_path: str | None = None,
        extra: str | None = None,
    ) -> None:
        suffix = f", image={image_path}" if image_path else ""
        extra_suffix = f", {extra}" if extra else ""
        logger.info(
            "[pixivdirect] %s send request (%s%s%s)",
            stage,
            self._event_log_context(event),
            suffix,
            extra_suffix,
        )

    def _get_search_default_limit(self) -> int:
        return int(
            self._config.get_constant("search_default_limit", SEARCH_DEFAULT_LIMIT)
        )

    def _get_search_max_limit(self) -> int:
        return int(self._config.get_constant("search_max_limit", SEARCH_MAX_LIMIT))

    async def _search_user_previews(
        self,
        *,
        keyword: str,
        page: int,
        limit: int,
        user_token: str,
        sort: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        search_params: dict[str, Any] = {"word": keyword}
        if sort:
            search_params["sort"] = sort
        if page > 1:
            search_params["offset"] = (page - 1) * 30

        result = await self._pixiv_call(
            "search_user",
            search_params,
            refresh_token=user_token,
        )
        if not result.get("ok"):
            raise RuntimeError(self._image.format_pixiv_error(result))

        latest_refresh_token = str(result.get("refresh_token") or user_token)
        data = result.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("❌ 解析搜索结果失败。")

        user_previews = (
            data.get("user_previews")
            if isinstance(data.get("user_previews"), list)
            else []
        )
        return user_previews[:limit], latest_refresh_token

    async def _record_random_usage(
        self, *, owner_user_key: str, filter_params: dict[str, Any]
    ) -> None:
        normalized_filter = self._cache.normalize_random_filter_params(filter_params)
        if not normalized_filter:
            return
        await self._config.record_random_filter_usage(
            user_key=owner_user_key,
            filter_key=self._cache.cache_key(normalized_filter),
            filter_params=normalized_filter,
        )

    def _mark_sent_illust_if_needed(self, user_id: str, item: dict[str, Any]) -> bool:
        if not self._config.is_unique_enabled_for_user(user_id):
            return False
        illust_id = item.get("illust_id")
        if not isinstance(illust_id, int):
            return False
        self._config.add_sent_id_for_user(user_id, illust_id)
        return True

    @classmethod
    def _parse_bool_value(cls, raw_value: str) -> bool | None:
        value = raw_value.strip().lower()
        if value in cls._TRUE_VALUES:
            return True
        if value in cls._FALSE_VALUES:
            return False
        return None

    @staticmethod
    def _r18_mosaic_entity_key(event: AstrMessageEvent) -> str:
        group_id = event.get_group_id()
        if group_id:
            return f"group:{group_id}"
        return f"user:{user_key(event)}"

    @staticmethod
    def _r18_mosaic_scope_label(event: AstrMessageEvent) -> str:
        return "本群" if event.get_group_id() else "当前用户"

    @staticmethod
    def _parse_blur_strength(raw_value: str) -> int | None:
        try:
            strength = int(raw_value)
        except ValueError:
            return None
        if 1 <= strength <= 100:
            return strength
        return None

    @staticmethod
    def _mosaic_mode_display_name(mode: str) -> str:
        return {
            "off": "关闭",
            "hajimi": "哈基米打码",
            "blur": "全图模糊",
        }.get(mode, mode)

    def _get_effective_r18_mosaic_mode(self, event: AstrMessageEvent) -> str:
        entity_key = self._r18_mosaic_entity_key(event)
        mode = self._config.get_r18_mosaic_mode(entity_key)
        if mode in {"hajimi", "blur"}:
            return mode

        group_id = event.get_group_id()
        if group_id and self._config.is_r18_mosaic_enabled_in_group(str(group_id)):
            return "hajimi"
        return "off"

    @staticmethod
    def _mask_proxy_url(proxy_url: str) -> str:
        if "://" not in proxy_url:
            return "***"
        scheme, remainder = proxy_url.split("://", 1)
        if "@" in remainder:
            _, host_part = remainder.rsplit("@", 1)
            return f"{scheme}://***@{host_part}"
        return f"{scheme}://{remainder}"

    @staticmethod
    def _bypass_mode_label(mode: str) -> str:
        return {
            "disabled": "普通域名模式",
            "auto": "自动混合模式",
            "pixez": "PixEz 模式",
            "accesser": "Accesser 模式",
        }.get(mode, mode)

    @classmethod
    def _bypass_mode_summary(cls, mode: str) -> str:
        summaries = {
            "auto": "先走 PixEz 式直连，再回退到 Accesser 式域名覆盖。",
            "pixez": "App API 保留域名 SNI 并覆盖到缓存 IP，图片继续走禁用 SNI 的 PixEz 式直连。",
            "accesser": "只走 Accesser 式域名解析覆盖，不走直连 IP。",
            "disabled": "完全关闭绕过，直接走普通域名请求。",
        }
        return summaries.get(mode, mode)

    @staticmethod
    def _build_cache_item(
        *,
        path: str,
        caption: str,
        x_restrict: Any,
        tags: list[str],
        illust_id: int | None = None,
        author_id: int | str | None = None,
        author_name: str = "",
        page_count: Any = 1,
        extra_image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "path": path,
            "caption": caption,
            "x_restrict": x_restrict if isinstance(x_restrict, int) else 0,
            "tags": tags,
            "illust_id": illust_id,
            "author_id": author_id,
            "author_name": author_name,
            "page_count": page_count if isinstance(page_count, int) else 1,
            "extra_image_paths": extra_image_paths or [],
        }

    async def _append_cache_item(self, user_id: str, item: dict[str, Any]) -> None:
        user_cache = self._config.random_cache.setdefault(user_id, {})
        queue = user_cache.setdefault(DEFAULT_POOL_KEY, [])
        queue.append(item)
        logger.info(
            "[pixivdirect] Cached image item for user=%s, illust_id=%s, path=%s, queue_size=%d",
            user_id,
            item.get("illust_id"),
            item.get("path"),
            len(queue),
        )
        await self._config.save_cache_index()

    @staticmethod
    def _has_active_filter(filter_params: dict[str, Any]) -> bool:
        return bool(
            filter_params.get("tag")
            or filter_params.get("author")
            or filter_params.get("author_id")
        )

    def _build_remaining_cache_text(
        self,
        user_id: str,
        filter_params: dict[str, Any],
    ) -> str:
        remain_total = len(
            self._config.random_cache.get(user_id, {}).get(DEFAULT_POOL_KEY, [])
        )
        remain_matching = self._cache.count_matching_items(user_id, filter_params)
        if self._has_active_filter(filter_params):
            return f"{remain_total}张 (匹配当前筛选: {remain_matching}张)"
        return f"{remain_total}张 (全部)"

    @staticmethod
    def _entity_key_for_event(event: AstrMessageEvent) -> str:
        group_id = event.get_group_id()
        return f"group:{group_id}" if group_id else f"user:{user_key(event)}"

    def _get_random_source_mode(self, event: AstrMessageEvent) -> str:
        return self._config.get_random_source_mode_for_entity(
            self._entity_key_for_event(event)
        )

    @staticmethod
    def _metadata_to_random_item(metadata_item: dict[str, Any]) -> dict[str, Any]:
        caption_seed = (
            metadata_item.get("caption_seed")
            if isinstance(metadata_item.get("caption_seed"), dict)
            else {}
        )
        return {
            "illust_id": metadata_item.get("illust_id"),
            "title": metadata_item.get("title"),
            "author_name": metadata_item.get("author_name"),
            "author_id": metadata_item.get("author_id"),
            "tags": metadata_item.get("tags", []),
            "page_count": metadata_item.get("page_count", 1),
            "x_restrict": metadata_item.get("x_restrict", 0),
            "total_view": caption_seed.get("total_view"),
            "total_bookmarks": caption_seed.get("total_bookmarks"),
        }

    async def warmup_metadata_for_user(
        self,
        *,
        user_key: str,
        refresh_token: str,
        page_batch: int,
        item_batch: int,
    ) -> tuple[str, int]:
        state = self._config.metadata_warmup_state.get(user_key)
        if not isinstance(state, dict) or state.get("completed"):
            return refresh_token, 0

        warmup_until = state.get("warmup_until")
        if isinstance(warmup_until, str):
            try:
                if datetime.fromisoformat(warmup_until) <= datetime.now():
                    state["completed"] = True
                    await self._config.save_metadata_warmup_state()
                    return refresh_token, 0
            except ValueError:
                state["completed"] = True
                await self._config.save_metadata_warmup_state()
                return refresh_token, 0

        latest_refresh_token = refresh_token
        inserted_total = 0
        next_url = str(state.get("next_url") or "")
        next_offset = int(state.get("next_offset", 0) or 0)

        for _ in range(max(1, page_batch)):
            result = await self._pixiv_call(
                "bookmark_metadata_page",
                {
                    "restrict": "public",
                    "next_url": next_url,
                    "offset": next_offset,
                    "quality": "original",
                },
                refresh_token=latest_refresh_token,
            )
            if not result.get("ok"):
                break

            latest_refresh_token = str(
                result.get("refresh_token") or latest_refresh_token
            )
            data = result.get("data")
            if not isinstance(data, dict):
                break
            items = data.get("items") if isinstance(data.get("items"), list) else []
            if items:
                remaining_capacity = max(0, item_batch - inserted_total)
                subset = items[:remaining_capacity] if remaining_capacity else []
                inserted_total += self._config.upsert_bookmark_metadata(
                    user_key=user_key,
                    restrict="public",
                    entries=subset,
                )
            next_url = str(data.get("next_url") or "")
            next_offset += len(items)
            if not next_url or inserted_total >= item_batch:
                break

        state["next_url"] = next_url
        state["next_offset"] = next_offset
        state["last_run_at"] = datetime.now().isoformat()
        if not next_url:
            state["completed"] = True

        if inserted_total > 0:
            await self._config.save_bookmark_metadata_cache()
        await self._config.save_metadata_warmup_state()
        return latest_refresh_token, inserted_total

    async def _emit_random_item(
        self,
        event: AstrMessageEvent,
        item: dict[str, Any],
        *,
        fallback_caption: str,
        source_label: str,
        filter_summary: str | None = None,
        remain_text: str | None = None,
    ):
        caption = item.get("caption") or fallback_caption
        lines = [caption, f"- 来源: {source_label}"]
        if remain_text:
            lines.append(f"- 剩余缓存: {remain_text}")
        if filter_summary:
            lines.append(f"- 筛选条件: {filter_summary}")
        message = "\n".join(lines)

        path = item.get("path")
        if path and self.should_send_image(event, item):
            self._log_send_request(
                event,
                stage="random-primary",
                image_path=str(path),
                extra=f"source={source_label}",
            )
            for result in await self._build_text_image_results(
                event,
                message,
                path,
                item,
            ):
                yield result
            extra_image_paths = item.get("extra_image_paths", [])
            if isinstance(extra_image_paths, list):
                for extra_path in extra_image_paths:
                    if not isinstance(extra_path, str) or not extra_path:
                        continue
                    self._log_send_request(
                        event,
                        stage="random-extra",
                        image_path=extra_path,
                        extra=f"source={source_label}",
                    )
                    for result in await self._build_image_results(
                        event,
                        extra_path,
                        item,
                    ):
                        yield result
            return

        plain_message = self._format_caption_for_event(event, message, item)
        if self._cache.is_r18_item(item):
            plain_message += "\n⚠️ R-18 内容在群聊中仅显示信息"
        logger.info(
            "[pixivdirect] Sending text-only random result (%s, reason=no-image-or-blocked, source=%s)",
            self._event_log_context(event),
            source_label,
        )
        yield event.plain_result(plain_message)

    async def _pop_random_cached_item(
        self,
        user_id: str,
        cache_key: str,
        filter_params: dict[str, Any],
    ) -> dict[str, Any] | None:
        unique_enabled = self._config.is_unique_enabled_for_user(user_id)
        return await self._cache.pop_cached_item(
            user_id,
            cache_key,
            filter_params,
            exclude_sent=unique_enabled,
        )

    async def _materialize_metadata_item(
        self,
        metadata_item: dict[str, Any],
        *,
        owner_user_key: str,
        refresh_token: str,
    ) -> dict[str, Any] | None:
        illust_id = metadata_item.get("illust_id")
        if isinstance(illust_id, int):
            cached_item = self._cache.find_cached_by_illust_id(illust_id)
            if cached_item:
                return cached_item

        image_urls = (
            metadata_item.get("image_urls")
            if isinstance(metadata_item.get("image_urls"), list)
            else []
        )
        if not image_urls:
            return None

        primary_path = await self._image.download_image_to_cache(
            str(image_urls[0]),
            access_token=None,
            refresh_token=refresh_token,
            name_prefix=f"metadata_{illust_id or 'unknown'}",
        )
        extra_image_paths: list[str] = []
        for index, image_url in enumerate(
            image_urls[1 : self._get_multi_image_threshold()], start=1
        ):
            extra_image_paths.append(
                await self._image.download_image_to_cache(
                    str(image_url),
                    access_token=None,
                    refresh_token=refresh_token,
                    name_prefix=f"metadata_{illust_id or 'unknown'}_{index}",
                )
            )

        item = self._build_cache_item(
            path=primary_path,
            caption=format_random_bookmark(
                self._metadata_to_random_item(metadata_item)
            ),
            x_restrict=metadata_item.get("x_restrict"),
            tags=metadata_item.get("tags", []),
            illust_id=illust_id if isinstance(illust_id, int) else None,
            author_id=metadata_item.get("author_id"),
            author_name=str(metadata_item.get("author_name") or ""),
            page_count=metadata_item.get("page_count", 1),
            extra_image_paths=extra_image_paths,
        )
        if owner_user_key:
            await self._append_cache_item(owner_user_key, item)
        return item

    async def _fill_random_cache(
        self,
        *,
        user_id: str,
        refresh_token: str,
        cache_key: str,
        filter_params: dict[str, Any],
        count: int,
        thorough_random: bool,
        quality: str,
    ) -> tuple[str, str | None]:
        unique_enabled = self._config.is_unique_enabled_for_user(user_id)
        return await self._enqueue_random_items(
            user_key=user_id,
            cache_key=cache_key,
            refresh_token=refresh_token,
            filter_params=filter_params.copy(),
            count=count,
            exclude_sent=unique_enabled,
            extended_scan=unique_enabled,
            thorough_random=thorough_random,
            quality=quality,
        )

    async def _pick_from_metadata_cache(
        self,
        *,
        owner_user_key: str,
        filter_params: dict[str, Any],
        refresh_token: str,
    ) -> tuple[dict[str, Any] | None, str]:
        metadata_item = self._cache.pick_metadata_item(
            owner_user_key,
            restrict=str(filter_params.get("restrict", "public")),
            filter_params=filter_params,
            exclude_sent=self._config.is_unique_enabled_for_user(owner_user_key),
        )
        if metadata_item:
            materialized = await self._materialize_metadata_item(
                metadata_item,
                owner_user_key=owner_user_key,
                refresh_token=refresh_token,
            )
            return materialized, refresh_token

        latest_refresh_token, inserted = await self.warmup_metadata_for_user(
            user_key=owner_user_key,
            refresh_token=refresh_token,
            page_batch=1,
            item_batch=max(1, self._parse_warmup_count(dict(filter_params))),
        )
        if inserted <= 0:
            return None, latest_refresh_token

        metadata_item = self._cache.pick_metadata_item(
            owner_user_key,
            restrict=str(filter_params.get("restrict", "public")),
            filter_params=filter_params,
            exclude_sent=self._config.is_unique_enabled_for_user(owner_user_key),
        )
        if not metadata_item:
            return None, latest_refresh_token
        materialized = await self._materialize_metadata_item(
            metadata_item,
            owner_user_key=owner_user_key,
            refresh_token=latest_refresh_token,
        )
        return materialized, latest_refresh_token

    async def _cache_illust_result(
        self,
        event: AstrMessageEvent,
        *,
        path: str,
        caption: str,
        illust: dict[str, Any],
        tags: list[str],
        illust_id: int | None,
        author: dict[str, Any],
        log_target: str,
    ) -> None:
        try:
            await self._append_cache_item(
                user_key(event),
                self._build_cache_item(
                    path=path,
                    caption=caption,
                    x_restrict=illust.get("x_restrict"),
                    tags=tags,
                    illust_id=illust_id,
                    author_id=author.get("id"),
                    author_name=str(author.get("name") or ""),
                    page_count=illust.get("page_count", 1),
                ),
            )
            logger.info(
                "[pixivdirect] Cached illust result for target=%s (%s, path=%s)",
                log_target,
                self._event_log_context(event),
                path,
            )
        except Exception as exc:
            logger.warning(
                "[pixivdirect] Failed to cache illust %s: %s",
                log_target,
                exc,
            )

    async def _emit_primary_and_extra_images(
        self,
        event: AstrMessageEvent,
        *,
        caption: str,
        primary_path: str,
        extra_paths: list[str],
        item: dict[str, Any],
        apply_event_restrictions: bool = True,
    ):
        for result_item in await self._build_text_image_results(
            event,
            caption,
            primary_path,
            item,
            apply_event_restrictions=apply_event_restrictions,
        ):
            yield result_item

        for extra_path in extra_paths:
            self._log_send_request(
                event,
                stage="extra-image",
                image_path=extra_path,
                extra=f"apply_event_restrictions={apply_event_restrictions}",
            )
            for result_item in await self._build_image_results(
                event,
                extra_path,
                item,
                apply_event_restrictions=apply_event_restrictions,
            ):
                yield result_item

    def _parse_warmup_count(self, filter_params: dict[str, Any]) -> int:
        raw_warmup = filter_params.pop("warmup", None)
        if raw_warmup is None:
            return 2
        try:
            return max(1, min(self._get_max_random_warmup(), int(str(raw_warmup))))
        except ValueError:
            return 2

    @staticmethod
    def _resolve_config_key(raw_key: str) -> str | None:
        normalized_key = CONFIGURABLE_CONSTANT_ALIASES.get(raw_key)
        if normalized_key is not None:
            return normalized_key
        return CONFIGURABLE_CONSTANT_ALIASES.get(raw_key.lower())

    @staticmethod
    def _parse_config_value(raw_value: str, default_value: Any) -> Any | None:
        value = raw_value.strip()
        if isinstance(default_value, bool):
            normalized = value.lower()
            if normalized in CommandHandler._TRUE_VALUES:
                return True
            if normalized in CommandHandler._FALSE_VALUES:
                return False
            return None
        if isinstance(default_value, int):
            try:
                return int(value)
            except ValueError:
                return None
        if isinstance(default_value, float):
            try:
                return float(value)
            except ValueError:
                return None
        return value if isinstance(default_value, str) else None

    def _resolve_shared_target(
        self,
        event: AstrMessageEvent,
        args: list[str],
    ) -> tuple[str | None, list[str], str | None]:
        from astrbot.api.message_components import At

        target_user_key: str | None = None
        target_user_name: str | None = None
        remaining_args: list[str] = []

        at_component = next(
            (
                comp
                for comp in event.get_messages()
                if isinstance(comp, At) and comp.qq != "all"
            ),
            None,
        )

        if at_component:
            at_qq = str(at_component.qq)
            at_user_key = f"{event.get_platform_id()}:{at_qq}"
            if at_user_key not in self._config.token_map:
                return None, [], f"❌ 未找到用户：{at_qq}"

            target_user_key = at_user_key
            target_user_name = getattr(at_component, "name", None) or at_qq
            if not self._config.share_enabled.get(target_user_key, False):
                return (
                    None,
                    [],
                    f"❌ 用户 {target_user_name} 未开启收藏分享功能。",
                )

            remaining_args = [token for token in args[1:] if not token.startswith("@")]
            return target_user_key, remaining_args, None

        for token in args[1:]:
            if token.startswith("@"):
                target_user_name = token[1:]
                target_user_key = self.find_user_by_name(target_user_name)
                if not target_user_key:
                    return None, [], f"❌ 未找到用户：{target_user_name}"
            else:
                remaining_args.append(token)

        return target_user_key, remaining_args, None

    @staticmethod
    def _normalize_group_block_tag(raw_tag: str) -> str:
        tag = raw_tag.strip()
        if "=" in tag:
            key, value = tag.split("=", 1)
            if key.strip().lower() == "tag":
                tag = value
        return tag.strip()

    @staticmethod
    def _split_keyword_and_options(tokens: list[str]) -> tuple[str, list[str]]:
        keyword_parts: list[str] = []
        option_tokens: list[str] = []
        seen_option = False

        for token in tokens:
            if "=" in token:
                seen_option = True
            if seen_option:
                option_tokens.append(token)
            else:
                keyword_parts.append(token)

        return " ".join(keyword_parts).strip(), option_tokens

    def _should_hide_r18_tags(
        self,
        event: AstrMessageEvent,
        item: dict[str, Any] | None,
    ) -> bool:
        group_id = event.get_group_id()
        if not group_id or not item or not self._cache.is_r18_item(item):
            return False
        return not self._config.is_r18_tags_visible_in_group(str(group_id))

    def _format_caption_for_event(
        self,
        event: AstrMessageEvent,
        text: str,
        item: dict[str, Any] | None = None,
        *,
        apply_event_restrictions: bool = True,
    ) -> str:
        if (
            not apply_event_restrictions
            or not text
            or not self._should_hide_r18_tags(event, item)
        ):
            return text
        return "\n".join(
            line for line in text.splitlines() if not line.startswith("🏷️ ")
        )

    async def _prepare_image_path_for_event(
        self,
        event: AstrMessageEvent,
        image_path: str | None,
        item: dict[str, Any] | None = None,
        *,
        apply_event_restrictions: bool = True,
    ) -> str | None:
        if not image_path:
            return None

        prepared_path = image_path
        if (
            not apply_event_restrictions
            or not item
            or not self._cache.is_r18_item(item)
        ):
            return await self._image.prepare_image_for_send(
                prepared_path,
                platform_name=event.get_platform_name(),
            )

        group_id = event.get_group_id()
        mode = self._get_effective_r18_mosaic_mode(event)
        if mode == "off":
            logger.info(
                "[pixivdirect] R-18 image %s in context %s will be sent without censor",
                prepared_path,
                group_id if group_id else user_key(event),
            )
            return await self._image.prepare_image_for_send(
                prepared_path,
                platform_name=event.get_platform_name(),
            )

        illust_id = item.get("illust_id")
        entity_key = self._r18_mosaic_entity_key(event)
        blur_strength = self._config.get_r18_mosaic_strength(entity_key)
        name_prefix = (
            f"r18mosaic_{illust_id}"
            if isinstance(illust_id, int)
            else "r18mosaic_image"
        )

        try:
            logger.info(
                "[pixivdirect] Applying R-18 censor for illust_id=%s mode=%s strength=%s target=%s path=%s",
                illust_id,
                mode,
                blur_strength,
                group_id if group_id else user_key(event),
                prepared_path,
            )
            prepared_path = await self._image.create_censored_image(
                prepared_path,
                name_prefix=name_prefix,
                mode=mode,
                blur_strength=blur_strength,
            )
        except Exception as exc:
            logger.warning(
                "[pixivdirect] Failed to apply %s censor to image %s: %s",
                mode,
                prepared_path,
                exc,
            )
            if mode == "hajimi":
                try:
                    logger.warning(
                        "[pixivdirect] Falling back to blur censor for image %s",
                        prepared_path,
                    )
                    prepared_path = await self._image.create_censored_image(
                        prepared_path,
                        name_prefix=f"{name_prefix}_fallback",
                        mode="blur",
                        blur_strength=self._config.get_r18_mosaic_strength(entity_key),
                    )
                except Exception as fallback_exc:
                    logger.warning(
                        "[pixivdirect] Blur fallback also failed for image %s: %s",
                        prepared_path,
                        fallback_exc,
                    )
        return await self._image.prepare_image_for_send(
            prepared_path,
            platform_name=event.get_platform_name(),
        )

    async def _build_text_image_results(
        self,
        event: AstrMessageEvent,
        text: str,
        image_path: str | None,
        item: dict[str, Any] | None = None,
        *,
        apply_event_restrictions: bool = True,
    ) -> list:
        formatted_text = self._format_caption_for_event(
            event,
            text,
            item,
            apply_event_restrictions=apply_event_restrictions,
        )
        prepared_path = await self._prepare_image_path_for_event(
            event,
            image_path,
            item,
            apply_event_restrictions=apply_event_restrictions,
        )
        if not prepared_path:
            logger.info(
                "[pixivdirect] Sending text-only result (%s, apply_event_restrictions=%s)",
                self._event_log_context(event),
                apply_event_restrictions,
            )
            return [event.plain_result(formatted_text)]

        self._log_send_request(
            event,
            stage="text-image",
            image_path=prepared_path,
            extra=f"apply_event_restrictions={apply_event_restrictions}",
        )
        image_host_url = await self._image_host.upload_image(
            prepared_path,
            self._config.image_host_config,
        )
        if image_host_url:
            formatted_text = f"{formatted_text}\n🔗 图床链接: {image_host_url}"
        if event.get_platform_name() == "aiocqhttp":
            return [
                event.plain_result(formatted_text),
                event.image_result(prepared_path),
            ]

        return [event.make_result().message(formatted_text).file_image(prepared_path)]

    async def _build_image_results(
        self,
        event: AstrMessageEvent,
        image_path: str,
        item: dict[str, Any] | None = None,
        *,
        apply_event_restrictions: bool = True,
    ) -> list:
        prepared_path = await self._prepare_image_path_for_event(
            event,
            image_path,
            item,
            apply_event_restrictions=apply_event_restrictions,
        )
        if not prepared_path:
            logger.info(
                "[pixivdirect] Skipping image-only send because no prepared path (%s)",
                self._event_log_context(event),
            )
            return []

        self._log_send_request(
            event,
            stage="image-only",
            image_path=prepared_path,
            extra=f"apply_event_restrictions={apply_event_restrictions}",
        )
        if event.get_platform_name() == "aiocqhttp":
            return [event.image_result(prepared_path)]
        return [event.make_result().file_image(prepared_path)]

    async def rate_limit_message(self, event: AstrMessageEvent) -> str | None:
        """Check if user is rate limited and return message if so."""
        key = user_key(event)
        now = time.time()
        async with self._rate_limit_lock:
            last = self._last_command_ts.get(key)
            min_interval = self._get_min_command_interval()
            if last is None:
                self._last_command_ts[key] = now
                return None
            wait_seconds = min_interval - (now - last)
            if wait_seconds > 0:
                return f"⏳ 请求过于频繁，请在 {wait_seconds:.1f} 秒后重试。"
            self._last_command_ts[key] = now
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
                                logger.info(
                                    "[pixivdirect] Blocking image send due to blocked tag=%s (%s, illust_id=%s)",
                                    blocked_tag,
                                    self._event_log_context(event),
                                    item.get("illust_id"),
                                )
                                return False

        if self._config.is_r18_enabled_in_group(group_id):
            return True
        if self._cache.is_r18_item(item):
            logger.info(
                "[pixivdirect] Blocking image send due to group R-18 policy (%s, illust_id=%s)",
                self._event_log_context(event),
                item.get("illust_id"),
            )
            return False
        return True

    def _get_quality_for_event(self, event: AstrMessageEvent) -> str:
        """Get image quality setting for the current event context."""
        group_id = event.get_group_id()
        entity_key = f"group:{group_id}" if group_id else f"user:{user_key(event)}"
        return self._config.get_image_quality(entity_key)

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
        if self._config.init_metadata_warmup_user(user_key(event)):
            await self._config.save_metadata_warmup_state()
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
                logger.info(
                    "[pixivdirect] Illust detail cache hit for illust_id=%s (%s)",
                    target_id,
                    self._event_log_context(event),
                )
                await self._emoji.add_emoji_reaction(event, "query_illust")
                caption = cached_item.get("caption") or "Pixiv 作品详情（缓存）"
                path = cached_item.get("path")
                if path:
                    for result in await self._build_text_image_results(
                        event,
                        f"{caption}\n- 来源: 缓存",
                        path,
                        cached_item,
                        apply_event_restrictions=False,
                    ):
                        yield result
                else:
                    yield event.plain_result(f"{caption}\n- 来源: 缓存")
                return

            await self._emoji.add_emoji_reaction(event, "query_illust")
            logger.info(
                "[pixivdirect] Fetching illust detail for illust_id=%s (%s)",
                target_id,
                self._event_log_context(event),
            )
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

                    for result in await self._build_text_image_results(
                        event,
                        caption,
                        str(gif_path),
                        illust,
                        apply_event_restrictions=False,
                    ):
                        yield result

                    await self._cache_illust_result(
                        event,
                        path=str(gif_path),
                        caption=caption,
                        illust=illust,
                        tags=tags,
                        illust_id=int(target_id) if target_id.isdigit() else None,
                        author=user,
                        log_target=target_id,
                    )
                    return

                except Exception as exc:
                    logger.warning("[pixivdirect] Ugoira processing failed: %s", exc)
                    yield event.plain_result(f"{caption}\n\n❌ 动图处理失败：{exc}")
                    return

            # Handle normal image - support multi-image illusts
            page_count = illust.get("page_count", 1)

            # Get image quality for this entity
            group_id = event.get_group_id()
            entity_key = f"group:{group_id}" if group_id else f"user:{user_key(event)}"
            quality = self._config.get_image_quality(entity_key)

            # Import helper for multi-image
            from .pixivSDK import _pick_illust_image_urls

            all_image_urls = _pick_illust_image_urls(illust, quality)
            multi_image_threshold = self._get_multi_image_threshold()

            if all_image_urls:
                try:
                    logger.info(
                        "[pixivdirect] Illust %s resolved %d image urls (page_count=%s, threshold=%d, quality=%s)",
                        target_id,
                        len(all_image_urls),
                        page_count,
                        multi_image_threshold,
                        quality,
                    )
                    if page_count <= multi_image_threshold:
                        # Download and send all images directly
                        downloaded_paths: list[str] = []
                        for i, img_url in enumerate(
                            all_image_urls[:multi_image_threshold]
                        ):
                            try:
                                local_path = await self._image.download_image_to_cache(
                                    img_url,
                                    access_token=result.get("access_token"),
                                    refresh_token=latest_refresh_token,
                                    name_prefix=f"illust_{illust.get('id') or target_id}_{i}",
                                )
                                downloaded_paths.append(local_path)
                            except Exception as exc:
                                logger.warning(
                                    "[pixivdirect] Image download failed: %s", exc
                                )

                        if downloaded_paths:
                            logger.info(
                                "[pixivdirect] Sending %d downloaded images directly for illust_id=%s",
                                len(downloaded_paths),
                                target_id,
                            )
                            async for (
                                result_item
                            ) in self._emit_primary_and_extra_images(
                                event,
                                caption=caption,
                                primary_path=downloaded_paths[0],
                                extra_paths=downloaded_paths[1:],
                                item=illust,
                                apply_event_restrictions=False,
                            ):
                                yield result_item
                            await self._cache_illust_result(
                                event,
                                path=downloaded_paths[0],
                                caption=caption,
                                illust=illust,
                                tags=tags,
                                illust_id=int(target_id)
                                if target_id.isdigit()
                                else None,
                                author=user,
                                log_target=target_id,
                            )
                    else:
                        # Use forward message for many images
                        from astrbot.api.message_components import (
                            Image as ImageComp,
                        )
                        from astrbot.api.message_components import (
                            Node,
                            Nodes,
                        )

                        # Download all images
                        local_paths = []
                        for i, img_url in enumerate(
                            all_image_urls[:20]
                        ):  # Max 20 images
                            try:
                                local_path = await self._image.download_image_to_cache(
                                    img_url,
                                    access_token=result.get("access_token"),
                                    refresh_token=latest_refresh_token,
                                    name_prefix=f"illust_{illust.get('id') or target_id}_{i}",
                                )
                                local_paths.append(local_path)
                            except Exception as exc:
                                logger.warning(
                                    "[pixivdirect] Image download failed: %s", exc
                                )

                        if local_paths:
                            logger.info(
                                "[pixivdirect] Sending illust_id=%s with forward message for %d extra images",
                                target_id,
                                max(0, len(local_paths) - 1),
                            )
                            # Send first image with caption, then forward the rest
                            for result_item in await self._build_text_image_results(
                                event,
                                caption,
                                local_paths[0],
                                illust,
                                apply_event_restrictions=False,
                            ):
                                yield result_item

                            if len(local_paths) > 1:
                                # Construct forward message nodes
                                nodes = []
                                for path in local_paths[1:]:
                                    prepared_path = (
                                        await self._prepare_image_path_for_event(
                                            event,
                                            path,
                                            illust,
                                            apply_event_restrictions=False,
                                        )
                                    )
                                    if not prepared_path:
                                        continue
                                    node = Node(
                                        content=[ImageComp(file=prepared_path)],
                                        name="PixivBot",
                                        uin=str(event.get_self_id() or "0"),
                                    )
                                    nodes.append(node)

                                if nodes:
                                    logger.info(
                                        "[pixivdirect] Emitting forward image node chain for illust_id=%s (%d nodes)",
                                        target_id,
                                        len(nodes),
                                    )
                                    forward_msg = Nodes(nodes=nodes)
                                    yield event.make_result().chain([forward_msg])

                        if local_paths:
                            await self._cache_illust_result(
                                event,
                                path=local_paths[0],
                                caption=caption,
                                illust=illust,
                                tags=tags,
                                illust_id=int(target_id)
                                if target_id.isdigit()
                                else None,
                                author=user,
                                log_target=target_id,
                            )
                    return
                except Exception as exc:
                    logger.warning("[pixivdirect] Image processing failed: %s", exc)

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
                enabled = self._parse_bool_value(args[2])
                if enabled is True:
                    self._config.share_enabled[key] = True
                    await self._config.save_share_config()
                    yield event.plain_result("✅ 已开启收藏分享功能。")
                    return
                if enabled is False:
                    self._config.share_enabled[key] = False
                    await self._config.save_share_config()
                    yield event.plain_result("✅ 已关闭收藏分享功能。")
                    return
                yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                return
            else:
                enabled = self._config.share_enabled.get(key, False)
                status = "开启" if enabled else "关闭"
                yield event.plain_result(f"ℹ️ 收藏分享功能当前状态：{status}")
                return

        # Handle DNS config
        if len(args) >= 2 and args[1].lower() == "dns":
            effective_bypass_mode = self._config.get_effective_bypass_mode()
            bypass_enabled = effective_bypass_mode != "disabled"
            if len(args) >= 3 and args[2].lower() == "refresh":
                if not event.is_admin():
                    yield event.plain_result("❌ 仅 AstrBot 管理员可手动刷新 DNS。")
                    return
                if not bypass_enabled:
                    yield event.plain_result(
                        "ℹ️ 当前已禁用 SNI 绕过，插件会直接走域名请求，不会执行 DoH 刷新。\n"
                        "如需恢复 PixEz 风格直连，请使用 /pixiv config set disable_bypass_sni false"
                    )
                    return
                if effective_bypass_mode == "accesser":
                    yield event.plain_result(
                        "ℹ️ 当前为 Accesser 模式，请求仍可使用运行时域名覆盖，但不会刷新 PixEz IP 缓存。"
                    )
                    return
                if self._dns_refresh_func:
                    await self._dns_refresh_func()
                yield event.plain_result(
                    "✅ 已触发 DNS 刷新，将在下次 Pixiv API 请求时执行。"
                )
                return
            else:
                # Show next refresh time
                next_refresh = "未知"
                if self._dns_time_getter:
                    try:
                        next_refresh = self._dns_time_getter()
                    except Exception:
                        pass
                if effective_bypass_mode == "disabled":
                    network_mode = "普通域名模式（已禁用 SNI 绕过）"
                elif effective_bypass_mode == "pixez":
                    network_mode = "PixEz 模式（App API 保留 SNI，图片禁用 SNI）"
                elif effective_bypass_mode == "accesser":
                    network_mode = "Accesser 模式（域名覆盖解析）"
                else:
                    network_mode = "自动混合模式（PixEz 直连优先，Accesser 回退）"
                yield event.plain_result(
                    f"ℹ️ DNS 刷新状态：\n"
                    f"- 当前网络模式: {network_mode}\n"
                    f"- 下次刷新时间: {next_refresh}\n"
                    f"- 使用 /pixiv dns refresh 手动触发刷新"
                )
                return

        if len(args) >= 2 and args[1].lower() == "source":
            entity_key = self._entity_key_for_event(event)
            if len(args) >= 3:
                if not event.is_admin():
                    yield event.plain_result(
                        "❌ 仅 AstrBot 管理员可修改 random 读取模式。"
                    )
                    return
                mode = args[2].strip().lower()
                if mode not in {RANDOM_SOURCE_IMAGE, RANDOM_SOURCE_METADATA}:
                    yield event.plain_result("❌ 无效模式，请使用 image 或 metadata。")
                    return
                self._config.set_random_source_mode_for_entity(entity_key, mode)
                await self._config.save_random_source_mode()
                yield event.plain_result(
                    f"✅ 已设置当前上下文 random 读取模式为：{mode}"
                )
                return

            yield event.plain_result(
                "ℹ️ 当前 random 读取模式："
                f"{self._config.get_random_source_mode_for_entity(entity_key)}\n"
                "metadata 模式下会按 本地图片缓存 > 元数据缓存 > 实时随机 的顺序获取。"
            )
            return

        # Handle r18 config
        if len(args) >= 2 and args[1].lower() == "r18":
            group_id = event.get_group_id()
            entity_key = self._r18_mosaic_entity_key(event)
            scope_label = self._r18_mosaic_scope_label(event)
            group_id_str = str(group_id) if group_id else None
            if len(args) >= 3:
                setting = args[2].lower()
                is_group_only_setting = setting in {"display", "tag"} or (
                    setting == "mosaic"
                    and len(args) >= 4
                    and args[3].lower() not in {"mode", "strength"}
                )
                if is_group_only_setting and not group_id:
                    yield event.plain_result(
                        "❌ `/pixiv r18 true/false` 和 `/pixiv r18 tag true/false` 仅可在群聊中使用。"
                    )
                    return

                if group_id and not event.is_admin():
                    yield event.plain_result(
                        "❌ 仅 AstrBot 管理员可修改 R-18 群聊设置。"
                    )
                    return

                if setting == "mosaic" and len(args) >= 5:
                    mosaic_subcommand = args[3].lower()
                    if mosaic_subcommand == "mode":
                        mode = args[4].lower()
                        if mode not in {"off", "hajimi", "blur"}:
                            yield event.plain_result(
                                "❌ 无效的打码模式，请使用 off/hajimi/blur。"
                            )
                            return
                        self._config.r18_mosaic_mode[entity_key] = mode
                        if group_id_str:
                            self._config.r18_mosaic_in_group[group_id_str] = (
                                mode != "off"
                            )
                            await self._config.save_r18_mosaic_config()
                        await self._config.save_r18_mosaic_mode_config()
                        yield event.plain_result(
                            f"✅ 已设置{scope_label} R-18 打码模式为：{self._mosaic_mode_display_name(mode)}"
                        )
                        return
                    if mosaic_subcommand == "strength":
                        strength = self._parse_blur_strength(args[4])
                        if strength is None:
                            yield event.plain_result("❌ 模糊强度必须是 1-100 的整数。")
                            return
                        self._config.r18_mosaic_strength[entity_key] = strength
                        await self._config.save_r18_mosaic_strength_config()
                        yield event.plain_result(
                            f"✅ 已设置{scope_label}全图模糊强度为：{strength}"
                        )
                        return

                if len(args) >= 4 and setting in {"tag", "mosaic"}:
                    value = args[3].lower()
                else:
                    value = setting
                    setting = "display"

                enabled = self._parse_bool_value(value)
                if enabled is None:
                    yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                    return
                if setting == "display":
                    assert group_id_str is not None
                    self._config.r18_in_group[group_id_str] = enabled
                    await self._config.save_r18_config()
                    action = "开启" if enabled else "关闭"
                    yield event.plain_result(f"✅ 已{action}群聊 R-18 内容显示。")
                    return
                if setting == "tag":
                    assert group_id_str is not None
                    self._config.r18_tags_in_group[group_id_str] = enabled
                    await self._config.save_r18_tag_config()
                    action = "显示" if enabled else "隐藏"
                    yield event.plain_result(f"✅ 已设置群聊 R-18 标签为：{action}")
                    return
                if setting == "mosaic":
                    if group_id_str is None:
                        yield event.plain_result(
                            "❌ 私聊请使用 `/pixiv r18 mosaic mode off|hajimi|blur`。"
                        )
                        return
                    self._config.r18_mosaic_in_group[group_id_str] = enabled
                    self._config.r18_mosaic_mode[entity_key] = (
                        self._config.get_r18_mosaic_mode(entity_key)
                        if enabled
                        and self._config.get_r18_mosaic_mode(entity_key)
                        in {"hajimi", "blur"}
                        else ("hajimi" if enabled else "off")
                    )
                    await self._config.save_r18_mosaic_config()
                    await self._config.save_r18_mosaic_mode_config()
                    action = "开启" if enabled else "关闭"
                    yield event.plain_result(f"✅ 已{action}群聊 R-18 图片自动打码。")
                    return

                yield event.plain_result(
                    "❌ 用法：/pixiv random r18 true/false、/pixiv random r18 tag true/false、"
                    "/pixiv random r18 mosaic true/false、"
                    "/pixiv random r18 mosaic mode off|hajimi|blur、"
                    "/pixiv random r18 mosaic strength 1-100"
                )
                return
            else:
                mode = self._get_effective_r18_mosaic_mode(event)
                strength = self._config.get_r18_mosaic_strength(entity_key)
                if group_id_str is None:
                    yield event.plain_result(
                        "ℹ️ 当前用户 R-18 打码设置：\n"
                        f"- 打码模式: {self._mosaic_mode_display_name(mode)}\n"
                        f"- 全图模糊强度: {strength}\n"
                        "- 使用 /pixiv random r18 mosaic mode off|hajimi|blur 控制私聊打码模式\n"
                        "- 使用 /pixiv random r18 mosaic strength 1-100 控制私聊全图模糊强度"
                    )
                    return

                status = (
                    "开启"
                    if self._config.is_r18_enabled_in_group(group_id_str)
                    else "关闭"
                )
                tag_status = (
                    "显示"
                    if self._config.is_r18_tags_visible_in_group(group_id_str)
                    else "隐藏"
                )
                mosaic_status = "开启" if mode != "off" else "关闭"
                yield event.plain_result(
                    "ℹ️ 群聊 R-18 设置：\n"
                    f"- 图片显示: {status}\n"
                    f"- 标签显示: {tag_status}\n"
                    f"- 自动打码: {mosaic_status}\n"
                    f"- 打码模式: {self._mosaic_mode_display_name(mode)}\n"
                    f"- 全图模糊强度: {strength}\n"
                    "- 使用 /pixiv random r18 true/false 控制图片显示\n"
                    "- 使用 /pixiv random r18 tag true/false 控制标签显示\n"
                    "- 使用 /pixiv random r18 mosaic true/false 控制自动打码\n"
                    "- 使用 /pixiv random r18 mosaic mode off|hajimi|blur 控制打码模式\n"
                    "- 使用 /pixiv random r18 mosaic strength 1-100 控制全图模糊强度"
                )
                return

        # Handle unique config
        if len(args) >= 2 and args[1].lower() == "unique":
            user_id = user_key(event)
            if len(args) >= 3:
                if not event.is_admin():
                    yield event.plain_result("❌ 仅 AstrBot 管理员可修改唯一随机设置。")
                    return
                enabled = self._parse_bool_value(args[2])
                if enabled is True:
                    self._config.random_unique[user_id] = "true"
                    await self._config.save_unique_config()
                    yield event.plain_result(
                        "✅ 已开启唯一随机模式（图片发送后将从缓存池移除）。"
                    )
                    return
                if enabled is False:
                    self._config.random_unique[user_id] = "false"
                    await self._config.save_unique_config()
                    yield event.plain_result(
                        "✅ 已关闭唯一随机模式（图片发送后保留在缓存池中）。"
                    )
                    return
                yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                return
            else:
                status = (
                    "开启"
                    if self._config.is_unique_enabled_for_user(user_id)
                    else "关闭"
                )
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
                tag = self._normalize_group_block_tag(" ".join(args[3:]))
                if not tag:
                    yield event.plain_result("❌ 请输入要屏蔽的标签。")
                    return
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
                tag = self._normalize_group_block_tag(" ".join(args[3:]))
                if not tag:
                    yield event.plain_result("❌ 请输入要移除的标签。")
                    return
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
                        cache_filter_tokens, self._get_max_random_pages()
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
                        [f"{k}={v}" for k, v in fp.items()],
                        self._get_max_random_pages(),
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
            elif len(args) >= 3 and args[2].lower() == "now":
                # /pixiv random cache now N
                count = 1
                if len(args) >= 4:
                    try:
                        count = max(1, int(args[3]))
                    except ValueError:
                        count = 1

                yield event.plain_result(f"⏳ 正在即时缓存 {count} 张图片...")

                max_retries = 4
                retry_delay = 5
                last_error = None
                success_count = 0
                fail_count = 0
                initial_queue_len = len(
                    self._config.random_cache.get(key, {}).get(DEFAULT_POOL_KEY, [])
                )

                for attempt in range(max_retries + 1):
                    try:
                        latest_refresh_token, error = await self._enqueue_random_items(
                            user_key=key,
                            cache_key=DEFAULT_POOL_KEY,
                            refresh_token=user_token,
                            filter_params={"restrict": "public", "max_pages": 3},
                            count=count,
                        )

                        if error:
                            last_error = error
                            # 非连接错误，不重试
                            break

                        if latest_refresh_token != user_token:
                            await self.set_user_token(event, latest_refresh_token)
                            user_token = latest_refresh_token

                        # 统计成功和失败的数量
                        user_cache = self._config.random_cache.get(key, {})
                        queue = user_cache.get(DEFAULT_POOL_KEY, [])
                        success_count = min(
                            count, max(0, len(queue) - initial_queue_len)
                        )
                        fail_count = count - success_count
                        last_error = None
                        break

                    except (ConnectionError, OSError) as exc:
                        last_error = str(exc)
                        is_connection_error = (
                            "Connection aborted" in str(exc)
                            or "RemoteDisconnected" in str(exc)
                            or isinstance(exc, (ConnectionError, OSError))
                        )
                        if is_connection_error and attempt < max_retries:
                            logger.warning(
                                "[pixivdirect] Cache now connection error (attempt %d/%d): %s",
                                attempt + 1,
                                max_retries + 1,
                                exc,
                            )
                            await asyncio.sleep(retry_delay)
                        else:
                            break

                if last_error:
                    await self._emoji.add_emoji_reaction(event, "error")
                    yield event.plain_result(f"❌ 即时缓存失败：{last_error}")
                else:
                    if fail_count > 0:
                        yield event.plain_result(
                            f"✅ 即时缓存完成：已完成 {success_count} 张，有 {fail_count} 张失败"
                        )
                    else:
                        yield event.plain_result(
                            f"✅ 即时缓存 {success_count} 张已完成"
                        )
                return
            elif len(args) >= 3 and args[2].lower() == "nowall":
                if not event.is_admin():
                    yield event.plain_result("❌ 仅 AstrBot 管理员可使用此命令。")
                    return

                if not self._idle_cache_all_func:
                    yield event.plain_result("❌ 闲时缓存功能未初始化。")
                    return

                yield event.plain_result("⏳ 正在为所有用户触发闲时缓存...")
                await self._idle_cache_all_func()
                yield event.plain_result("✅ 已为所有用户触发闲时缓存完成。")
                return
            elif len(args) >= 3 and args[2].lower() == "schedule":
                next_time = "未知"
                if self._idle_cache_time_getter:
                    try:
                        next_time = self._idle_cache_time_getter()
                    except Exception:
                        pass
                yield event.plain_result(
                    f"ℹ️ 闲时缓存状态：\n"
                    f"- 下次执行时间: {next_time}\n"
                    f"- 使用 /pixiv random cache now N 为当前用户立即缓存\n"
                    f"- 使用 /pixiv random cache nowall 为所有用户触发缓存（管理员）"
                )
                return
            else:
                yield event.plain_result(
                    "📋 用法：\n"
                    "- /pixiv random cache add tag=xxx count=N|always  # 添加缓存任务\n"
                    "- /pixiv random cache list  # 查看队列\n"
                    "- /pixiv random cache clear  # 清空队列\n"
                    "- /pixiv random cache now N  # 立即为当前用户缓存N张\n"
                    "- /pixiv random cache nowall  # 管理员：为所有用户触发缓存\n"
                    "- /pixiv random cache schedule  # 查看下次闲时缓存时间"
                )
                return

        # Handle quality config
        if len(args) >= 2 and args[1].lower() == "quality":
            key = user_key(event)
            # For group chats, use group ID as key
            group_id = event.get_group_id()
            entity_key = f"group:{group_id}" if group_id else f"user:{key}"

            if len(args) >= 3:
                if not event.is_admin():
                    yield event.plain_result("❌ 仅 AstrBot 管理员可修改图片质量设置。")
                    return
                value = args[2].lower()
                if value in ("original", "原图"):
                    self._config.image_quality_config[entity_key] = "original"
                    await self._config.save_image_quality_config()
                    yield event.plain_result("✅ 已设置图片质量为：原图")
                    return
                elif value in ("medium", "中等"):
                    self._config.image_quality_config[entity_key] = "medium"
                    await self._config.save_image_quality_config()
                    yield event.plain_result("✅ 已设置图片质量为：中等")
                    return
                elif value in ("small", "小图"):
                    self._config.image_quality_config[entity_key] = "small"
                    await self._config.save_image_quality_config()
                    yield event.plain_result("✅ 已设置图片质量为：小图")
                    return
                else:
                    yield event.plain_result(
                        "❌ 无效的值，请使用 original/medium/small"
                    )
                    return
            else:
                quality = self._config.get_image_quality(entity_key)
                quality_name = {
                    "original": "原图",
                    "medium": "中等",
                    "small": "小图",
                }.get(quality, quality)
                yield event.plain_result(
                    f"ℹ️ 当前图片质量：{quality_name}\n"
                    f"使用 /pixiv random quality original/medium/small 修改"
                )
                return

        # Handle config command (admin only)
        if len(args) >= 2 and args[1].lower() == "config":
            if not event.is_admin():
                yield event.plain_result("❌ 仅 AstrBot 管理员可查看或修改常量配置。")
                return

            if len(args) >= 3 and args[2].lower() == "list":
                config_text = "📋 可配置常量：\n"
                for key, default in CONFIGURABLE_CONSTANTS.items():
                    constant_name = CONFIGURABLE_CONSTANT_NAMES[key]
                    custom = self._config.custom_constants.get(key)
                    if custom is not None:
                        config_text += (
                            f"- {key} ({constant_name}): {custom} (默认: {default})\n"
                        )
                    else:
                        config_text += f"- {key} ({constant_name}): {default}\n"
                yield event.plain_result(config_text.strip())
                return
            elif len(args) >= 3 and args[2].lower() == "get":
                if len(args) >= 4:
                    key = self._resolve_config_key(args[3])
                    if key is not None:
                        value = self._config.get_constant(
                            key, CONFIGURABLE_CONSTANTS[key]
                        )
                        constant_name = CONFIGURABLE_CONSTANT_NAMES[key]
                        yield event.plain_result(f"ℹ️ {key} ({constant_name}) = {value}")
                    else:
                        yield event.plain_result(f"❌ 未知配置项：{args[3]}")
                else:
                    yield event.plain_result("❌ 用法：/pixiv config get <key>")
                return
            elif len(args) >= 3 and args[2].lower() == "set":
                if len(args) >= 5:
                    key = self._resolve_config_key(args[3])
                    value_str = args[4]
                    if key is None:
                        yield event.plain_result(f"❌ 未知配置项：{args[3]}")
                        return
                    default_value = CONFIGURABLE_CONSTANTS[key]
                    value = self._parse_config_value(value_str, default_value)
                    if value is None:
                        expected_type = type(default_value).__name__
                        yield event.plain_result(
                            f"❌ 值类型错误，{key} 需要 {expected_type}"
                        )
                        return
                    self._config.custom_constants[key] = value
                    await self._config.save_custom_constants()
                    constant_name = CONFIGURABLE_CONSTANT_NAMES[key]
                    yield event.plain_result(
                        f"✅ 已设置 {key} ({constant_name}) = {value}"
                    )
                else:
                    yield event.plain_result("❌ 用法：/pixiv config set <key> <value>")
                return
            elif len(args) >= 3 and args[2].lower() == "reset":
                if len(args) >= 4:
                    key = self._resolve_config_key(args[3])
                    if key is not None:
                        self._config.custom_constants.pop(key, None)
                        await self._config.save_custom_constants()
                        constant_name = CONFIGURABLE_CONSTANT_NAMES[key]
                        yield event.plain_result(
                            f"✅ 已重置 {key} ({constant_name}) 为默认值"
                        )
                    else:
                        yield event.plain_result(f"❌ 未知配置项：{args[3]}")
                else:
                    # Reset all
                    self._config.custom_constants.clear()
                    await self._config.save_custom_constants()
                    yield event.plain_result("✅ 已重置所有配置为默认值")
                return
            else:
                yield event.plain_result(
                    "📋 用法：\n"
                    "- /pixiv config list  # 查看所有配置\n"
                    "- /pixiv config get <key>  # 获取配置值\n"
                    "- /pixiv config set <key> <value>  # 设置配置值\n"
                    "- /pixiv config reset [key]  # 重置配置"
                )
                return

        target_user_key, remaining_args, target_error = self._resolve_shared_target(
            event, args
        )
        if target_error:
            yield event.plain_result(target_error)
            return

        filter_params, filter_summary = self._cache.parse_random_filter(
            remaining_args, self._get_max_random_pages()
        )
        filter_params.setdefault("restrict", "public")
        filter_params.setdefault("max_pages", 3)
        cache_key = self._cache.cache_key(filter_params)
        source_mode = self._get_random_source_mode(event)
        logger.info(
            f"[pixivdirect] Continuing with random bookmark, filter_params: {filter_params}"
        )
        thorough_random = bool(filter_params.pop("random", False))

        # @someone mode - read from target user cache
        if target_user_key:
            cached_item = await self._pop_random_cached_item(
                target_user_key, cache_key, filter_params
            )
            if cached_item:
                await self._record_random_usage(
                    owner_user_key=target_user_key, filter_params=filter_params
                )
                await self._emoji.add_emoji_reaction(event, "random")
                async for result in self._emit_random_item(
                    event,
                    cached_item,
                    fallback_caption="Pixiv 随机收藏（缓存）",
                    source_label="缓存（共享）",
                ):
                    yield result
                return
            target_user_token = self._config.token_map.get(target_user_key)
            if not target_user_token:
                yield event.plain_result("❌ 该用户未登录 Pixiv。")
                return

            if source_mode == RANDOM_SOURCE_METADATA:
                (
                    metadata_item,
                    latest_refresh_token,
                ) = await self._pick_from_metadata_cache(
                    owner_user_key=target_user_key,
                    filter_params=filter_params,
                    refresh_token=target_user_token,
                )
                if latest_refresh_token != target_user_token:
                    self._config.token_map[target_user_key] = latest_refresh_token
                    await self._config.save_tokens()
                    target_user_token = latest_refresh_token
                if metadata_item:
                    async for result in self._emit_random_item(
                        event,
                        metadata_item,
                        fallback_caption="Pixiv 随机收藏（元数据）",
                        source_label="元数据缓存（共享）",
                    ):
                        yield result
                    return

            await self._record_random_usage(
                owner_user_key=target_user_key, filter_params=filter_params
            )
            warmup = self._parse_warmup_count(filter_params)

            await self._emoji.add_emoji_reaction(event, "random")
            latest_refresh_token, error = await self._fill_random_cache(
                user_id=target_user_key,
                refresh_token=target_user_token,
                cache_key=cache_key,
                filter_params=filter_params,
                count=warmup,
                thorough_random=thorough_random,
                quality=self._get_quality_for_event(event),
            )
            if latest_refresh_token != target_user_token:
                self._config.token_map[target_user_key] = latest_refresh_token
                await self._config.save_tokens()

            if error:
                await self._emoji.add_emoji_reaction(event, "error")
                yield event.plain_result(f"❌ 获取随机收藏失败：{error}")
                return

            cached_item = await self._pop_random_cached_item(
                target_user_key,
                cache_key,
                filter_params,
            )
            if not cached_item:
                yield event.plain_result("❌ 未找到可发送的缓存图片。")
                return

            await self._emoji.add_emoji_reaction(event, "random")
            async for result in self._emit_random_item(
                event,
                cached_item,
                fallback_caption="Pixiv 随机收藏（共享）",
                source_label="新获取（共享）",
            ):
                yield result
            return

        # Self cache mode - requires token
        user_token = self.get_user_token(event)
        if not user_token:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
            return

        key = user_key(event)
        await self._record_random_usage(owner_user_key=key, filter_params=filter_params)

        # Try cache first
        cached_item = await self._pop_random_cached_item(key, cache_key, filter_params)
        if cached_item:
            sent_ids_changed = self._mark_sent_illust_if_needed(key, cached_item)
            if sent_ids_changed:
                await self._config.save_sent_illust_ids()
            await self._emoji.add_emoji_reaction(event, "random")
            async for result in self._emit_random_item(
                event,
                cached_item,
                fallback_caption="Pixiv 随机收藏（缓存）",
                source_label="缓存",
                remain_text=self._build_remaining_cache_text(key, filter_params),
            ):
                yield result
            return

        if source_mode == RANDOM_SOURCE_METADATA:
            metadata_item, latest_refresh_token = await self._pick_from_metadata_cache(
                owner_user_key=key,
                filter_params=filter_params,
                refresh_token=user_token,
            )
            if latest_refresh_token != user_token:
                await self.set_user_token(event, latest_refresh_token)
                user_token = latest_refresh_token
            if metadata_item:
                sent_ids_changed = self._mark_sent_illust_if_needed(key, metadata_item)
                if sent_ids_changed:
                    await self._config.save_sent_illust_ids()
                async for result in self._emit_random_item(
                    event,
                    metadata_item,
                    fallback_caption="Pixiv 随机收藏（元数据）",
                    source_label="元数据缓存",
                    remain_text=self._build_remaining_cache_text(key, filter_params),
                ):
                    yield result
                return

        # Cache empty, fetch new data
        warmup = self._parse_warmup_count(filter_params)

        await self._emoji.add_emoji_reaction(event, "random")
        latest_refresh_token, error = await self._fill_random_cache(
            user_id=key,
            refresh_token=user_token,
            cache_key=cache_key,
            filter_params=filter_params,
            count=warmup,
            thorough_random=thorough_random,
            quality=self._get_quality_for_event(event),
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

        picked = await self._pop_random_cached_item(key, cache_key, filter_params)
        if not picked:
            yield event.plain_result("❌ 未找到可发送的缓存图片。")
            return
        sent_ids_changed = self._mark_sent_illust_if_needed(key, picked)
        if sent_ids_changed:
            await self._config.save_sent_illust_ids()
        async for result in self._emit_random_item(
            event,
            picked,
            fallback_caption="Pixiv 随机收藏",
            source_label="新获取",
            filter_summary=filter_summary,
            remain_text=self._build_remaining_cache_text(key, filter_params),
        ):
            yield result

    async def _enqueue_random_items(
        self,
        *,
        user_key: str,
        cache_key: str,
        refresh_token: str,
        filter_params: dict[str, Any],
        count: int,
        exclude_sent: bool = False,
        extended_scan: bool = False,
        thorough_random: bool = False,
        quality: str = "original",
    ) -> tuple[str, str | None]:
        """Enqueue random bookmark items to cache."""
        from .pixivSDK import _pick_illust_image_urls

        latest_refresh_token = refresh_token
        user_cache = self._config.random_cache.setdefault(user_key, {})
        queue = user_cache.setdefault(DEFAULT_POOL_KEY, [])
        pending_items: list[dict[str, Any]] = []
        multi_image_threshold = self._get_multi_image_threshold()

        # Get sent IDs for unique mode
        sent_ids = (
            self._config.get_sent_ids_for_user(user_key) if exclude_sent else set()
        )

        for _ in range(max(1, count)):
            # Build params with exclude_ids and random options
            call_params = dict(filter_params)
            if exclude_sent and sent_ids:
                call_params["exclude_ids"] = list(sent_ids)
            if extended_scan:
                call_params["extended_scan"] = True
                call_params["max_unique_scan_pages"] = self._get_max_unique_scan_pages()
            if thorough_random:
                call_params["random"] = True
            call_params["quality"] = quality

            random_result = await self._pixiv_call(
                "random_bookmark_image",
                call_params,
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
                    "illust": illust_data,
                    "access_token": random_result.get("access_token"),
                    "refresh_token": latest_refresh_token,
                    "page_count": illust_data.get("page_count", 1),
                    "total_view": illust_data.get("total_view"),
                    "total_bookmarks": illust_data.get("total_bookmarks"),
                },
            )

        if not pending_items:
            return latest_refresh_token, "未找到符合筛选条件的收藏图片。"

        semaphore = asyncio.Semaphore(self._get_random_download_concurrency())

        async def build_cache_item(item: dict[str, Any]) -> dict[str, Any]:
            cached_item = None
            if isinstance(item.get("illust_id"), int):
                cached_item = self._cache.find_cached_by_illust_id(
                    int(item["illust_id"])
                )
            if cached_item:
                return {
                    **cached_item,
                    "caption": format_random_bookmark(
                        item,
                        matched_count=item.get("matched_count"),
                        pages_scanned=item.get("pages_scanned"),
                    ),
                    "title": str(item.get("title") or "（无标题）"),
                    "total_view": item.get("total_view"),
                    "total_bookmarks": item.get("total_bookmarks"),
                }

            image_urls = (
                _pick_illust_image_urls(item.get("illust", {}), quality)
                if isinstance(item.get("illust"), dict)
                else []
            )
            selected_urls = image_urls[:multi_image_threshold] if image_urls else []
            primary_url = selected_urls[0] if selected_urls else str(item["image_url"])
            logger.info(
                "[pixivdirect] Building random cache item for illust_id=%s with %d selected image urls",
                item.get("illust_id"),
                len(selected_urls) if selected_urls else 1,
            )

            async with semaphore:
                local_path = await self._image.download_image_to_cache(
                    primary_url,
                    access_token=(
                        str(item["access_token"]) if item.get("access_token") else None
                    ),
                    refresh_token=str(item["refresh_token"]),
                    name_prefix=f"bookmark_{item['illust_id'] or 'unknown'}",
                )

            extra_image_paths: list[str] = []
            for index, extra_url in enumerate(selected_urls[1:], start=1):
                async with semaphore:
                    extra_path = await self._image.download_image_to_cache(
                        extra_url,
                        access_token=(
                            str(item["access_token"])
                            if item.get("access_token")
                            else None
                        ),
                        refresh_token=str(item["refresh_token"]),
                        name_prefix=f"bookmark_{item['illust_id'] or 'unknown'}_{index}",
                    )
                extra_image_paths.append(extra_path)

            caption = format_random_bookmark(
                item,
                matched_count=item.get("matched_count"),
                pages_scanned=item.get("pages_scanned"),
            )
            return {
                **self._build_cache_item(
                    path=local_path,
                    caption=caption,
                    x_restrict=item.get("x_restrict", 0),
                    tags=item.get("tags", []),
                    illust_id=item.get("illust_id"),
                    author_id=item.get("author_id"),
                    author_name=str(item.get("author_name") or ""),
                    page_count=item.get("page_count", 1),
                    extra_image_paths=extra_image_paths,
                ),
                "title": str(item.get("title") or "（无标题）"),
                "total_view": item.get("total_view"),
                "total_bookmarks": item.get("total_bookmarks"),
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

    def _parse_search_options(
        self,
        args: list[str],
        *,
        allowed_sorts: set[str] | None = None,
        allow_target: bool = True,
        allow_duration: bool = True,
        allow_translate: bool = True,
    ) -> dict[str, Any]:
        """Parse search options from command arguments."""
        options: dict[str, Any] = {}
        valid_sorts = allowed_sorts or set(SEARCH_SORT_OPTIONS)
        for arg in args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                key = key.lower().strip()
                value = value.strip()
                if key == "sort":
                    if value in valid_sorts:
                        options["sort"] = value
                elif key == "target" and allow_target:
                    if value in SEARCH_TARGET_OPTIONS:
                        options["search_target"] = value
                elif key == "duration" and allow_duration:
                    if value in SEARCH_DURATION_OPTIONS:
                        options["duration"] = value
                elif key == "translate" and allow_translate:
                    options["include_translated_tag_results"] = value.lower() in (
                        "true",
                        "1",
                        "yes",
                    )
                elif key == "page":
                    try:
                        page = int(value)
                        if page > 0:
                            options["page"] = page
                    except ValueError:
                        pass
                elif key == "limit":
                    try:
                        limit = int(value)
                        if 0 < limit <= self._get_search_max_limit():
                            options["limit"] = limit
                    except ValueError:
                        pass
        return options

    async def handle_bypass(self, event: AstrMessageEvent, args: list[str]):
        if not event.is_admin():
            yield event.plain_result("❌ 仅 AstrBot 管理员可查看或修改绕过模式。")
            return

        legacy_disabled = bool(
            self._config.get_constant("disable_bypass_sni", DISABLE_BYPASS_SNI)
        )
        stored_mode = self._config.bypass_mode
        effective_mode = self._config.get_effective_bypass_mode()

        if len(args) >= 3 and args[1].lower() == "mode":
            new_mode = str(args[2]).strip().lower()
            if new_mode not in BYPASS_MODE_OPTIONS:
                yield event.plain_result(
                    "❌ 无效模式，请使用 auto / pixez / accesser。"
                )
                return
            self._config.set_bypass_mode(new_mode)
            await self._config.save_bypass_mode()
            yield event.plain_result(
                f"✅ 已设置 bypass mode = {new_mode}\n"
                f"当前说明：{self._bypass_mode_summary(new_mode)}"
            )
            return

        yield event.plain_result(
            "ℹ️ 绕过模式状态：\n"
            f"- legacy disable_bypass_sni: {legacy_disabled}\n"
            f"- 已保存模式: {self._bypass_mode_label(stored_mode)} ({stored_mode})\n"
            f"- 当前生效模式: {self._bypass_mode_label(effective_mode)} ({effective_mode})\n"
            f"- auto: {self._bypass_mode_summary(BYPASS_MODE_AUTO)}\n"
            f"- pixez: {self._bypass_mode_summary('pixez')}\n"
            f"- accesser: {self._bypass_mode_summary('accesser')}"
        )

    async def handle_proxy(self, event: AstrMessageEvent, args: list[str]):
        if not event.is_admin():
            yield event.plain_result("❌ 仅 AstrBot 管理员可查看或修改搜索代理配置。")
            return

        subcommand = args[1].lower() if len(args) >= 2 else "status"
        config = self._config.search_proxy_config
        state = self._config.search_proxy_state

        if subcommand == "status":
            proxy_url = str(config.get("proxy_url") or "").strip()
            masked_proxy = self._mask_proxy_url(proxy_url) if proxy_url else "未配置"
            yield event.plain_result(
                "ℹ️ 搜索代理状态：\n"
                f"- 启用: {bool(config.get('enabled'))}\n"
                f"- 代理地址: {masked_proxy}\n"
                f"- 今日触发次数: {int(state.get('daily_rescue_counts', {}).get(time.strftime('%Y-%m-%d'), 0))}\n"
                f"- 粘滞代理截止: {state.get('proxy_until') or '未激活'}\n"
                f"- 每日阈值: {config.get('daily_threshold')}\n"
                f"- 粘滞天数: {config.get('sticky_days')}\n"
                f"- 最近原因: {state.get('last_reason') or '无'}"
            )
            return

        if subcommand == "set":
            if len(args) < 3:
                yield event.plain_result("❌ 用法：/pixiv proxy set <proxy_url>")
                return
            config["proxy_url"] = args[2].strip()
            await self._config.save_search_proxy_config()
            yield event.plain_result("✅ 已保存搜索代理地址。")
            return

        if subcommand == "clear":
            config["proxy_url"] = ""
            state["daily_rescue_counts"] = {}
            state["proxy_until"] = None
            state["last_reason"] = ""
            await self._config.save_search_proxy_config()
            await self._config.save_search_proxy_state()
            yield event.plain_result("✅ 已清除搜索代理地址并关闭当前粘滞代理窗口。")
            return

        if subcommand == "enable":
            if len(args) < 3:
                yield event.plain_result("❌ 用法：/pixiv proxy enable true|false")
                return
            enabled = self._parse_bool_value(args[2])
            if enabled is None:
                yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                return
            config["enabled"] = enabled
            await self._config.save_search_proxy_config()
            yield event.plain_result(
                f"✅ 已将搜索代理设置为 {'开启' if enabled else '关闭'}。"
            )
            return

        if subcommand == "threshold":
            if len(args) < 3:
                yield event.plain_result("❌ 用法：/pixiv proxy threshold <count>")
                return
            try:
                count = max(1, int(args[2]))
            except ValueError:
                yield event.plain_result("❌ 阈值必须是大于等于 1 的整数。")
                return
            config["daily_threshold"] = count
            await self._config.save_search_proxy_config()
            yield event.plain_result(f"✅ 已设置每日触发阈值为 {count}。")
            return

        if subcommand == "sticky":
            if len(args) < 3:
                yield event.plain_result("❌ 用法：/pixiv proxy sticky <days>")
                return
            try:
                days = max(1, int(args[2]))
            except ValueError:
                yield event.plain_result("❌ 粘滞天数必须是大于等于 1 的整数。")
                return
            config["sticky_days"] = days
            await self._config.save_search_proxy_config()
            yield event.plain_result(f"✅ 已设置粘滞代理天数为 {days}。")
            return

        yield event.plain_result(
            "📋 用法：\n"
            "- /pixiv proxy status\n"
            "- /pixiv proxy set <proxy_url>\n"
            "- /pixiv proxy clear\n"
            "- /pixiv proxy enable true|false\n"
            "- /pixiv proxy threshold <count>\n"
            "- /pixiv proxy sticky <days>"
        )

    async def handle_imagehost(self, event: AstrMessageEvent, args: list[str]):
        if not event.is_admin():
            yield event.plain_result("❌ 仅 AstrBot 管理员可查看或修改图床配置。")
            return

        config = self._config.image_host_config
        subcommand = args[1].lower() if len(args) >= 2 else "status"

        if subcommand == "status":
            yield event.plain_result(
                "ℹ️ 图床状态：\n"
                f"- 启用: {bool(config.get('enabled'))}\n"
                f"- endpoint: {config.get('endpoint') or '未配置'}\n"
                f"- method: {config.get('method')}\n"
                f"- file_field: {config.get('file_field')}\n"
                f"- success_path: {config.get('success_path') or '未配置'}\n"
                f"- headers: {len(config.get('headers', {}))}项\n"
                f"- form_fields: {len(config.get('form_fields', {}))}项\n"
                f"- timeout_seconds: {config.get('timeout_seconds')}"
            )
            return

        if subcommand == "enable" and len(args) >= 3:
            enabled = self._parse_bool_value(args[2])
            if enabled is None:
                yield event.plain_result("❌ 无效的值，请使用 true 或 false。")
                return
            config["enabled"] = enabled
            await self._config.save_image_host_config()
            yield event.plain_result(f"✅ 图床已{'开启' if enabled else '关闭'}。")
            return

        if subcommand == "set" and len(args) >= 4:
            key = args[2].lower()
            value = " ".join(args[3:]).strip()
            if key not in {
                "endpoint",
                "method",
                "file_field",
                "success_path",
                "delete_path",
                "timeout_seconds",
            }:
                yield event.plain_result(
                    "❌ 仅支持设置 endpoint/method/file_field/success_path/delete_path/timeout_seconds。"
                )
                return
            if key == "method":
                value = value.lower()
                if value not in {"post", "put"}:
                    yield event.plain_result("❌ method 仅支持 post 或 put。")
                    return
                config[key] = value
            elif key == "timeout_seconds":
                try:
                    config[key] = max(3, int(value))
                except ValueError:
                    yield event.plain_result("❌ timeout_seconds 必须是整数。")
                    return
            else:
                config[key] = value
            await self._config.save_image_host_config()
            yield event.plain_result(f"✅ 已设置图床配置 {key}。")
            return

        if subcommand in {"header", "field"} and len(args) >= 4:
            target_key = "headers" if subcommand == "header" else "form_fields"
            action = args[2].lower()
            if action == "set" and len(args) >= 5:
                config[target_key][args[3]] = " ".join(args[4:]).strip()
                await self._config.save_image_host_config()
                yield event.plain_result(f"✅ 已设置图床{target_key}项：{args[3]}")
                return
            if action == "remove":
                config[target_key].pop(args[3], None)
                await self._config.save_image_host_config()
                yield event.plain_result(f"✅ 已移除图床{target_key}项：{args[3]}")
                return

        if subcommand == "reset":
            self._config.image_host_config.clear()
            self._config.image_host_config.update(
                self._config._normalize_image_host_config({})
            )
            await self._config.save_image_host_config()
            yield event.plain_result("✅ 已重置图床配置。")
            return

        yield event.plain_result(
            "📋 用法：\n"
            "- /pixiv imagehost status\n"
            "- /pixiv imagehost enable true|false\n"
            "- /pixiv imagehost set endpoint <url>\n"
            "- /pixiv imagehost set method post|put\n"
            "- /pixiv imagehost set file_field <name>\n"
            "- /pixiv imagehost set success_path <json.path>\n"
            "- /pixiv imagehost header set <key> <value>\n"
            "- /pixiv imagehost field set <key> <value>\n"
            "- /pixiv imagehost header remove <key>\n"
            "- /pixiv imagehost field remove <key>\n"
            "- /pixiv imagehost reset"
        )

    async def handle_search(self, event: AstrMessageEvent, args: list[str]):
        """Handle search command for illustrations."""
        if len(args) < 2:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 用法：/pixiv search {关键词} [选项]")
            return

        user_token = self.get_user_token(event)
        if not user_token:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
            return

        keyword, option_tokens = self._split_keyword_and_options(args[1:])
        if not keyword:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 搜索关键词不能为空。")
            return

        # Parse options
        options = self._parse_search_options(option_tokens)
        page = options.get("page", 1)
        limit = options.get("limit", self._get_search_default_limit())

        # Build search params
        search_params: dict[str, Any] = {
            "word": keyword,
            "search_target": options.get("search_target", "partial_match_for_tags"),
            "sort": options.get("sort", "date_desc"),
            "include_translated_tag_results": options.get(
                "include_translated_tag_results", True
            ),
        }
        if "duration" in options:
            search_params["duration"] = options["duration"]

        # Calculate offset from page
        if page > 1:
            search_params["offset"] = (page - 1) * 30  # Pixiv API returns 30 per page

        await self._emoji.add_emoji_reaction(event, "search")

        try:
            result = await self._pixiv_call(
                "search_illust",
                search_params,
                refresh_token=user_token,
            )
        except Exception as exc:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(f"❌ 搜索失败：{exc}")
            return

        if not result.get("ok"):
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(self._image.format_pixiv_error(result))
            return

        latest_refresh_token = str(result.get("refresh_token") or user_token)
        if latest_refresh_token != user_token:
            await self.set_user_token(event, latest_refresh_token)

        data = result.get("data")
        if not isinstance(data, dict):
            yield event.plain_result("❌ 解析搜索结果失败。")
            return

        illusts = data.get("illusts") if isinstance(data.get("illusts"), list) else []
        total_count = data.get("total") if isinstance(data.get("total"), int) else None

        # Limit results
        illusts = illusts[:limit]

        if not illusts:
            try:
                (
                    user_previews,
                    fallback_refresh_token,
                ) = await self._search_user_previews(
                    keyword=keyword,
                    page=page,
                    limit=limit,
                    user_token=latest_refresh_token,
                )
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Search fallback to search_user failed for keyword=%s: %s",
                    keyword,
                    exc,
                )
                user_previews = []
            else:
                if fallback_refresh_token != latest_refresh_token:
                    latest_refresh_token = fallback_refresh_token
                    if latest_refresh_token != user_token:
                        await self.set_user_token(event, latest_refresh_token)

            if user_previews:
                caption = format_search_user_result(user_previews, keyword, page)
                yield event.plain_result(
                    f"🔍 搜索结果：关键词「{keyword}」没有找到相关作品。"
                    f"\n\n已自动切换为作者搜索：\n\n{caption}"
                )
                return

            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(
                f"🔍 搜索结果：关键词「{keyword}」没有找到相关作品。"
            )
            return

        # Format and send results
        caption = format_search_result(illusts, keyword, page, total_count)

        # Download first image as preview (if R-18 filtering allows)
        first_illust = illusts[0]
        first_illust_id = first_illust.get("id")
        if self.should_send_image(event, first_illust):
            try:
                from .pixivSDK import _pick_illust_image_url

                image_url = _pick_illust_image_url(
                    first_illust, self._get_quality_for_event(event)
                )
                if image_url:
                    logger.info(
                        "[pixivdirect] Downloading search preview for keyword=%s, illust_id=%s",
                        keyword,
                        first_illust_id,
                    )
                    local_path = await self._image.download_image_to_cache(
                        image_url,
                        access_token=result.get("access_token"),
                        refresh_token=latest_refresh_token,
                        name_prefix=f"search_{keyword}_{first_illust_id}",
                    )
                    for result_item in await self._build_text_image_results(
                        event,
                        caption,
                        local_path,
                        first_illust,
                    ):
                        yield result_item
                    return
            except Exception as exc:
                logger.warning("[pixivdirect] Search preview download failed: %s", exc)

        # Fallback to text only
        yield event.plain_result(caption)

    async def handle_search_user(self, event: AstrMessageEvent, args: list[str]):
        """Handle searchuser command for authors."""
        if len(args) < 2:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 用法：/pixiv searchuser {关键词} [选项]")
            return

        user_token = self.get_user_token(event)
        if not user_token:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
            return

        keyword, option_tokens = self._split_keyword_and_options(args[1:])
        if not keyword:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result("❌ 搜索关键词不能为空。")
            return

        # Parse options (only page and limit for user search)
        options = self._parse_search_options(
            option_tokens,
            allowed_sorts=set(SEARCH_USER_SORT_OPTIONS),
            allow_target=False,
            allow_duration=False,
            allow_translate=False,
        )
        page = options.get("page", 1)
        limit = options.get("limit", self._get_search_default_limit())

        # Build search params
        search_params: dict[str, Any] = {"word": keyword}
        if "sort" in options:
            search_params["sort"] = options["sort"]

        # Calculate offset from page
        if page > 1:
            search_params["offset"] = (page - 1) * 30  # Pixiv API returns 30 per page

        await self._emoji.add_emoji_reaction(event, "search")

        try:
            result = await self._pixiv_call(
                "search_user",
                search_params,
                refresh_token=user_token,
            )
        except Exception as exc:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(f"❌ 搜索失败：{exc}")
            return

        if not result.get("ok"):
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(self._image.format_pixiv_error(result))
            return

        latest_refresh_token = str(result.get("refresh_token") or user_token)
        if latest_refresh_token != user_token:
            await self.set_user_token(event, latest_refresh_token)

        data = result.get("data")
        if not isinstance(data, dict):
            yield event.plain_result("❌ 解析搜索结果失败。")
            return

        user_previews = (
            data.get("user_previews")
            if isinstance(data.get("user_previews"), list)
            else []
        )
        total_count = data.get("total") if isinstance(data.get("total"), int) else None

        # Limit results
        user_previews = user_previews[:limit]

        if not user_previews:
            await self._emoji.add_emoji_reaction(event, "error")
            yield event.plain_result(
                f"🔍 搜索作者结果：关键词「{keyword}」没有找到相关作者。"
            )
            return

        # Format and send results
        caption = format_search_user_result(user_previews, keyword, page, total_count)
        yield event.plain_result(caption)

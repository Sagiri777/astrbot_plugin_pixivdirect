from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from astrbot.api.event import AstrMessageEvent

from .cache_manager import CacheManager
from .config_manager import ConfigManager
from .constants import (
    DEFAULT_IMAGE_QUALITY,
    DEFAULT_RANDOM_SCAN_PAGES,
    MAX_RANDOM_SCAN_PAGES,
    SUPPORTED_BOOKMARK_RESTRICT,
    SUPPORTED_QUALITIES,
)
from .image_handler import ImageHandler
from .infrastructure.pixiv_client import pick_illust_image_urls
from .utils import (
    format_illust_detail,
    format_random_caption,
    format_ranking_illusts,
    format_recommended_illusts,
    format_related_illusts,
    format_search_illusts,
    format_search_users,
    format_ugoira_metadata,
    format_user_detail,
    help_text,
    parse_key_value_tokens,
    user_key,
)


class CommandHandler:
    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        cache_manager: CacheManager,
        image_handler: ImageHandler,
        pixiv_call_func,
    ) -> None:
        self._config = config_manager
        self._cache = cache_manager
        self._image = image_handler
        self._pixiv_call = pixiv_call_func

    async def _safe_pixiv_call(
        self,
        action: str,
        params: dict[str, Any],
        *,
        refresh_token: str | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._pixiv_call(
                action,
                params,
                refresh_token=refresh_token,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "exception",
                "error": {"message": str(exc)},
            }

    async def handle_help(self, event: AstrMessageEvent):
        yield event.plain_result(help_text())

    async def handle_login(self, event: AstrMessageEvent, tokens: list[str]):
        if len(tokens) < 2:
            yield event.plain_result("用法：/pixiv login <refresh_token>")
            return
        token = tokens[1].strip()
        if not token:
            yield event.plain_result("refresh_token 不能为空。")
            return
        await self._config.set_user_token(user_key(event), token)
        yield event.plain_result("已保存 Pixiv refresh_token。")

    async def handle_quality(self, event: AstrMessageEvent, tokens: list[str]):
        if len(tokens) < 2:
            current = self._config.get_quality(user_key(event))
            yield event.plain_result(f"当前图片质量：{current}")
            return
        quality = tokens[1].strip().lower()
        if quality not in SUPPORTED_QUALITIES:
            yield event.plain_result("图片质量只支持：small / medium / original")
            return
        await self._config.set_quality(user_key(event), quality)
        yield event.plain_result(f"图片质量已设置为：{quality}")

    async def handle_dns(self, event: AstrMessageEvent):
        path = self._config.host_map_file
        yield event.plain_result(f"PixEz host map 文件：{path}")

    async def handle_id(self, event: AstrMessageEvent, tokens: list[str]):
        if len(tokens) < 3:
            yield event.plain_result(
                "用法：/pixiv id i <illust_id> 或 /pixiv id a <user_id>"
            )
            return
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return

        mode = tokens[1].lower()
        object_id = tokens[2]
        if not object_id.isdigit():
            yield event.plain_result("ID 必须是数字。")
            return

        if mode == "i":
            async for result in self._send_illust_detail(
                event,
                illust_id=int(object_id),
                refresh_token=token,
            ):
                yield result
            return

        if mode == "a":
            result = await self._pixiv_call(
                "user_detail",
                {"user_id": int(object_id), "filter": "for_android"},
                refresh_token=token,
            )
            if not result.get("ok"):
                yield event.plain_result(self._image.format_pixiv_error(result))
                return
            yield event.plain_result(format_user_detail(result.get("data") or {}))
            return

        yield event.plain_result("只支持 /pixiv id i 或 /pixiv id a。")

    async def handle_search(
        self, event: AstrMessageEvent, tokens: list[str], *, user_search: bool
    ):
        if len(tokens) < 2:
            yield event.plain_result(
                "用法：/pixiv search <keyword> 或 /pixiv searchuser <keyword>"
            )
            return
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return

        plain_tokens, kv_tokens = parse_key_value_tokens(tokens[1:])
        keyword = " ".join(plain_tokens).strip()
        if not keyword:
            yield event.plain_result("请提供搜索关键词。")
            return

        action = "search_user" if user_search else "search_illust"
        params: dict[str, Any] = {"word": keyword}
        if not user_search:
            params["filter"] = "for_android"
            params["merge_plain_keyword_results"] = True
            if "sort" in kv_tokens:
                params["sort"] = kv_tokens["sort"]
            if "target" in kv_tokens:
                params["search_target"] = kv_tokens["target"]
        else:
            params["filter"] = "for_android"

        result = await self._pixiv_call(action, params, refresh_token=token)
        if not result.get("ok"):
            fallback_action = "web_search_user" if user_search else "web_search_illust"
            result = await self._pixiv_call(
                fallback_action, params, refresh_token=token
            )
        if not result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(result))
            return

        payload = result.get("data") or {}
        formatter = format_search_users if user_search else format_search_illusts
        yield event.plain_result(formatter(payload))

    async def handle_ranking(self, event: AstrMessageEvent, tokens: list[str]):
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return

        plain_tokens, kv_tokens = parse_key_value_tokens(tokens[1:])
        mode = kv_tokens.get("mode") or (plain_tokens[0] if plain_tokens else "day")
        date = kv_tokens.get("date")
        params: dict[str, Any] = {"mode": mode, "filter": "for_android"}
        if date:
            params["date"] = date

        result = await self._safe_pixiv_call(
            "illust_ranking",
            params,
            refresh_token=token,
        )
        if not result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(result))
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        data["mode"] = mode
        yield event.plain_result(format_ranking_illusts(data))

    async def handle_recommended(self, event: AstrMessageEvent, tokens: list[str]):
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return

        _, kv_tokens = parse_key_value_tokens(tokens[1:])
        recommend_type = kv_tokens.get("type", "illust").lower()
        if recommend_type == "illust":
            action = "illust_recommended"
            params: dict[str, Any] = {}
        elif recommend_type == "manga":
            action = "/v1/manga/recommended"
            params = {"filter": "for_ios", "include_ranking_label": "true"}
        elif recommend_type == "user":
            action = "/v1/user/recommended"
            params = {"filter": "for_android"}
        else:
            yield event.plain_result("type 仅支持 illust / manga / user")
            return

        result = await self._safe_pixiv_call(action, params, refresh_token=token)
        if not result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(result))
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        yield event.plain_result(
            format_recommended_illusts(data, recommend_type=recommend_type)
        )

    async def handle_related(self, event: AstrMessageEvent, tokens: list[str]):
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return
        if len(tokens) < 2 or not tokens[1].isdigit():
            yield event.plain_result("用法：/pixiv related <illust_id>")
            return

        result = await self._safe_pixiv_call(
            "illust_related",
            {"illust_id": int(tokens[1]), "filter": "for_android"},
            refresh_token=token,
        )
        if not result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(result))
            return
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        yield event.plain_result(format_related_illusts(data))

    async def handle_ugoira(self, event: AstrMessageEvent, tokens: list[str]):
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return
        if len(tokens) < 2 or not tokens[1].isdigit():
            yield event.plain_result(
                "用法：/pixiv ugoira <illust_id> [download=true|false]"
            )
            return

        _, kv_tokens = parse_key_value_tokens(tokens[2:])
        should_download = kv_tokens.get("download", "true").lower() not in {
            "false",
            "0",
            "no",
            "off",
        }
        illust_id = int(tokens[1])

        metadata_result = await self._safe_pixiv_call(
            "ugoira_metadata",
            {"illust_id": illust_id},
            refresh_token=token,
        )
        if not metadata_result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(metadata_result))
            return
        data = (
            metadata_result.get("data")
            if isinstance(metadata_result.get("data"), dict)
            else {}
        )
        yield event.plain_result(format_ugoira_metadata(data))

        if not should_download:
            return

        metadata = (
            data.get("ugoira_metadata")
            if isinstance(data.get("ugoira_metadata"), dict)
            else {}
        )
        zip_urls = (
            metadata.get("zip_urls")
            if isinstance(metadata.get("zip_urls"), dict)
            else {}
        )
        zip_url = ""
        for key in ("original", "medium"):
            candidate = zip_urls.get(key)
            if isinstance(candidate, str) and candidate:
                zip_url = candidate
                break
        frames = (
            metadata.get("frames") if isinstance(metadata.get("frames"), list) else []
        )
        if not zip_url or not frames:
            yield event.plain_result("Ugoira 元数据不完整，无法下载。")
            return

        try:
            zip_path = await self._image.download_ugoira_zip_to_cache(
                zip_url,
                refresh_token=token,
                file_stem=f"ugoira_{illust_id}",
            )
            gif_path = str(
                Path(zip_path).with_name(
                    f"ugoira_{illust_id}_{int(time.time() * 1000)}.gif"
                )
            )
            self._image.render_ugoira_to_gif(zip_path, frames, gif_path)
            yield event.make_result().message("").file_image(gif_path)
        except Exception as exc:
            yield event.plain_result(f"Ugoira 下载或渲染失败：{exc}")

    async def handle_random(self, event: AstrMessageEvent, tokens: list[str]):
        token = self._config.get_user_token(user_key(event))
        if not token:
            yield event.plain_result("请先登录：/pixiv login <refresh_token>")
            return

        _plain, kv_tokens = parse_key_value_tokens(tokens[1:])
        restrict = kv_tokens.get(
            "restrict", self._config.get_bookmark_restrict(user_key(event))
        )
        if restrict not in SUPPORTED_BOOKMARK_RESTRICT:
            yield event.plain_result("restrict 只支持 public 或 private")
            return
        pages_raw = kv_tokens.get("pages", str(DEFAULT_RANDOM_SCAN_PAGES))
        try:
            pages = max(1, min(MAX_RANDOM_SCAN_PAGES, int(pages_raw)))
        except ValueError:
            pages = DEFAULT_RANDOM_SCAN_PAGES

        result = await self._pixiv_call(
            "random_bookmark",
            {
                "restrict": restrict,
                "tag": kv_tokens.get("tag"),
                "max_pages": pages,
                "quality": self._config.get_quality(user_key(event)),
            },
            refresh_token=token,
        )
        if not result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(result))
            return

        payload = result.get("data") or {}
        illust = (
            payload.get("illust") if isinstance(payload.get("illust"), dict) else None
        )
        if not illust:
            yield event.plain_result("没有抽到符合条件的收藏作品。")
            return
        yield event.plain_result(format_random_caption(illust))
        async for item in self._send_illust_images(
            event,
            illust=illust,
            refresh_token=token,
            quality=self._config.get_quality(user_key(event)),
        ):
            yield item

    async def _send_illust_detail(
        self,
        event: AstrMessageEvent,
        *,
        illust_id: int,
        refresh_token: str,
    ):
        quality = self._config.get_quality(user_key(event)) or DEFAULT_IMAGE_QUALITY
        result = await self._pixiv_call(
            "illust_detail",
            {"illust_id": illust_id, "filter": "for_android"},
            refresh_token=refresh_token,
        )
        if not result.get("ok"):
            yield event.plain_result(self._image.format_pixiv_error(result))
            return
        yield event.plain_result(
            format_illust_detail(result.get("data") or {}, quality=quality)
        )
        data = result.get("data") or {}
        illust = data.get("illust") if isinstance(data.get("illust"), dict) else {}
        async for item in self._send_illust_images(
            event,
            illust=illust,
            refresh_token=refresh_token,
            quality=quality,
        ):
            yield item

    async def _send_illust_images(
        self,
        event: AstrMessageEvent,
        *,
        illust: dict[str, Any],
        refresh_token: str,
        quality: str,
    ):
        illust_id = illust.get("id")
        if not isinstance(illust_id, int):
            return
        image_urls = pick_illust_image_urls(illust, quality)
        owner = user_key(event)
        for index, image_url in enumerate(image_urls[:3]):
            local_path = await self._image.download_image_to_cache(
                image_url,
                refresh_token=refresh_token,
                file_stem=f"illust_{illust_id}_{index}",
            )
            await self._cache.remember_download(
                owner,
                illust_id=illust_id,
                page=index,
                path=local_path,
                url=image_url,
            )
            yield event.make_result().message("").file_image(local_path)

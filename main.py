from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_temp_path,
)

from .pixivSDK import pixiv


@register("pixivdirect", "Sagiri777", "PixivDirect command plugin", "0.1.0")
class PixivDirectPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._storage_lock = asyncio.Lock()
        self._token_map: dict[str, str] = {}
        self._random_cache: dict[str, dict[str, list[dict[str, str]]]] = {}

        self._plugin_data_dir = Path(get_astrbot_plugin_data_path()) / "pixivdirect"
        self._cache_dir = Path(get_astrbot_temp_path()) / "pixivdirect"
        self._token_file = self._plugin_data_dir / "user_refresh_tokens.json"
        self._host_map_file = self._plugin_data_dir / "pixiv_host_map.json"

    async def initialize(self):
        self._plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_tokens()

    def _load_tokens(self) -> None:
        if not self._token_file.exists():
            self._token_map = {}
            return
        try:
            raw = json.loads(self._token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("[pixivdirect] Failed to load token file, using empty mapping.")
            self._token_map = {}
            return

        users = raw.get("users") if isinstance(raw, dict) else None
        if not isinstance(users, dict):
            self._token_map = {}
            return

        loaded: dict[str, str] = {}
        for key, token in users.items():
            if isinstance(key, str) and isinstance(token, str) and key and token:
                loaded[key] = token
        self._token_map = loaded

    async def _save_tokens(self) -> None:
        async with self._storage_lock:
            payload = {"users": self._token_map}
            tmp_file = self._token_file.with_suffix(".tmp")
            tmp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_file.replace(self._token_file)

    @staticmethod
    def _user_key(event: AstrMessageEvent) -> str:
        return f"{event.get_platform_id()}:{event.get_sender_id()}"

    @staticmethod
    def _split_command(message: str) -> list[str]:
        tokens = re.split(r"\s+", (message or "").strip())
        tokens = [token for token in tokens if token]
        if tokens and tokens[0].lower() == "pixiv":
            return tokens[1:]
        return tokens

    @staticmethod
    def _format_pixiv_error(result: dict[str, Any]) -> str:
        status = result.get("status")
        error = result.get("error")
        if isinstance(error, dict):
            for key in ("message", "user_message"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return f"Pixiv API error(status={status}): {value}"
            return f"Pixiv API error(status={status}): {json.dumps(error, ensure_ascii=False)}"
        if error:
            return f"Pixiv API error(status={status}): {error}"
        return f"Pixiv API request failed(status={status})."

    async def _pixiv_call(self, action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(
            pixiv,
            action,
            params,
            dns_cache_file=str(self._host_map_file),
            dns_update_hosts=False,
            runtime_dns_resolve=False,
            max_retries=2,
            **kwargs,
        )

    @staticmethod
    def _safe_filename_from_url(url: str, fallback: str) -> str:
        raw = Path(urlsplit(url).path).name
        name = raw if raw else fallback
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", name) or fallback

    async def _download_image_to_cache(
        self,
        image_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        image_result = await self._pixiv_call(
            "image",
            {"url": image_url},
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not image_result.get("ok"):
            raise RuntimeError(self._format_pixiv_error(image_result))

        content = image_result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("Pixiv image response does not contain binary data.")

        safe_name = self._safe_filename_from_url(image_url, f"{name_prefix}.bin")
        target = self._cache_dir / f"{name_prefix}_{int(time.time() * 1000)}_{safe_name}"
        target.write_bytes(bytes(content))
        return str(target)

    @staticmethod
    def _parse_random_filter(filter_tokens: list[str]) -> tuple[dict[str, Any], str]:
        params: dict[str, Any] = {}
        loose_text: list[str] = []

        aliases = {
            "tag": "tag",
            "t": "tag",
            "author": "author",
            "a": "author",
            "author_id": "author_id",
            "aid": "author_id",
            "restrict": "restrict",
            "r": "restrict",
            "max_pages": "max_pages",
            "pages": "max_pages",
            "warmup": "warmup",
        }

        for token in filter_tokens:
            if "=" not in token:
                loose_text.append(token)
                continue
            key_raw, value_raw = token.split("=", 1)
            key = aliases.get(key_raw.strip().lower())
            value = value_raw.strip()
            if not key or not value:
                continue
            params[key] = value

        if loose_text and "tag" not in params:
            params["tag"] = " ".join(loose_text)

        if "author_id" in params:
            try:
                params["author_id"] = int(str(params["author_id"]))
            except ValueError:
                params.pop("author_id", None)

        if "max_pages" in params:
            try:
                params["max_pages"] = max(1, min(10, int(str(params["max_pages"]))))
            except ValueError:
                params.pop("max_pages", None)

        if "restrict" in params:
            restrict = str(params["restrict"]).lower()
            params["restrict"] = "private" if restrict == "private" else "public"

        summary_items: list[str] = []
        for key in ("tag", "author", "author_id", "restrict", "max_pages"):
            if key in params:
                summary_items.append(f"{key}={params[key]}")
        summary = ", ".join(summary_items) if summary_items else "none"
        return params, summary

    def _cache_key(self, filter_params: dict[str, Any]) -> str:
        identity = {
            "tag": filter_params.get("tag"),
            "author": filter_params.get("author"),
            "author_id": filter_params.get("author_id"),
            "restrict": filter_params.get("restrict", "public"),
            "max_pages": filter_params.get("max_pages", 3),
        }
        return json.dumps(identity, ensure_ascii=False, sort_keys=True)

    def _pop_cached_item(self, user_key: str, cache_key: str) -> dict[str, str] | None:
        user_cache = self._random_cache.get(user_key)
        if not user_cache:
            return None
        queue = user_cache.get(cache_key)
        if not queue:
            return None

        while queue:
            item = queue.pop(0)
            path = item.get("path")
            if isinstance(path, str) and path and Path(path).exists():
                return item
        return None

    async def _enqueue_random_items(
        self,
        *,
        user_key: str,
        cache_key: str,
        refresh_token: str,
        filter_params: dict[str, Any],
        count: int,
    ) -> tuple[str, str | None]:
        latest_refresh_token = refresh_token
        user_cache = self._random_cache.setdefault(user_key, {})
        queue = user_cache.setdefault(cache_key, [])

        for _ in range(max(1, count)):
            random_result = await self._pixiv_call(
                "random_bookmark_image",
                filter_params,
                refresh_token=latest_refresh_token,
            )
            if not random_result.get("ok"):
                return latest_refresh_token, self._format_pixiv_error(random_result)

            latest_refresh_token = str(
                random_result.get("refresh_token") or latest_refresh_token,
            )
            data = random_result.get("data")
            if not isinstance(data, dict):
                return latest_refresh_token, "Pixiv random bookmark response is invalid."

            image_url = data.get("image_url")
            if not isinstance(image_url, str) or not image_url:
                return latest_refresh_token, "Pixiv random bookmark did not return image_url."

            illust_id = data.get("id")
            title = str(data.get("title") or "(untitled)")
            author_data = data.get("author") if isinstance(data.get("author"), dict) else {}
            author_name = str(author_data.get("name") or "unknown")
            author_id = author_data.get("id")

            local_path = await self._download_image_to_cache(
                image_url,
                access_token=random_result.get("access_token"),
                refresh_token=latest_refresh_token,
                name_prefix=f"bookmark_{illust_id or 'unknown'}",
            )

            filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
            tags = data.get("tags") if isinstance(data.get("tags"), list) else []
            tags_text = ", ".join(str(tag) for tag in tags[:8]) if tags else "(none)"

            caption = (
                "Pixiv Random Bookmark\n"
                f"- illust_id: {illust_id}\n"
                f"- title: {title}\n"
                f"- author: {author_name} ({author_id})\n"
                f"- tags: {tags_text}\n"
                f"- matched_count: {data.get('matched_count')}\n"
                f"- pages_scanned: {data.get('pages_scanned')}\n"
                f"- filters: {json.dumps(filters, ensure_ascii=False)}"
            )
            queue.append({"path": local_path, "caption": caption})

        return latest_refresh_token, None

    def _get_user_token(self, event: AstrMessageEvent) -> str | None:
        return self._token_map.get(self._user_key(event))

    async def _set_user_token(self, event: AstrMessageEvent, refresh_token: str) -> None:
        self._token_map[self._user_key(event)] = refresh_token
        await self._save_tokens()

    @staticmethod
    def _help_text() -> str:
        return (
            "Pixiv commands:\n"
            "- /pixiv login {refresh_token}\n"
            "- /pixiv id i {illust_id}\n"
            "- /pixiv id a {artist_id}\n"
            "- /pixiv random [tag=xxx] [author=xxx] [author_id=123] [restrict=public|private] [max_pages=3]"
        )

    async def _handle_login(self, event: AstrMessageEvent, args: list[str]):
        if len(args) < 2:
            yield event.plain_result("Usage: /pixiv login {refresh_token}")
            return

        refresh_token = args[1].strip()
        if not refresh_token:
            yield event.plain_result("refresh_token cannot be empty.")
            return

        verify_result = await self._pixiv_call(
            "random_bookmark_image",
            {"max_pages": 1},
            refresh_token=refresh_token,
        )
        if not verify_result.get("ok"):
            yield event.plain_result(
                "Token verification failed. " + self._format_pixiv_error(verify_result),
            )
            return

        latest_refresh_token = str(verify_result.get("refresh_token") or refresh_token)
        await self._set_user_token(event, latest_refresh_token)
        yield event.plain_result("Pixiv token saved for current user.")

    async def _handle_id(self, event: AstrMessageEvent, args: list[str]):
        if len(args) < 3:
            yield event.plain_result("Usage: /pixiv id i {illust_id} or /pixiv id a {artist_id}")
            return

        user_token = self._get_user_token(event)
        if not user_token:
            yield event.plain_result("Please login first: /pixiv login {refresh_token}")
            return

        typ = args[1].lower().strip()
        target_id = args[2].strip()
        if not target_id.isdigit():
            yield event.plain_result("ID must be numeric.")
            return

        if typ == "i":
            result = await self._pixiv_call(
                "illust_detail",
                {"illust_id": int(target_id)},
                refresh_token=user_token,
            )
            if not result.get("ok"):
                yield event.plain_result(self._format_pixiv_error(result))
                return

            latest_refresh_token = str(result.get("refresh_token") or user_token)
            if latest_refresh_token != user_token:
                await self._set_user_token(event, latest_refresh_token)

            data = result.get("data")
            illust = data.get("illust") if isinstance(data, dict) else None
            if not isinstance(illust, dict):
                yield event.plain_result("Failed to parse illust detail response.")
                return

            user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
            tags_raw = illust.get("tags") if isinstance(illust.get("tags"), list) else []
            tags: list[str] = []
            for item in tags_raw:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        tags.append(name)

            title = str(illust.get("title") or "(untitled)")
            caption = (
                "Pixiv Illust Detail\n"
                f"- id: {illust.get('id')}\n"
                f"- title: {title}\n"
                f"- author: {user.get('name')} ({user.get('id')})\n"
                f"- page_count: {illust.get('page_count')}\n"
                f"- total_view: {illust.get('total_view')}\n"
                f"- total_bookmarks: {illust.get('total_bookmarks')}\n"
                f"- tags: {', '.join(tags[:12]) if tags else '(none)'}"
            )

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
                    local_path = await self._download_image_to_cache(
                        preview_url,
                        access_token=result.get("access_token"),
                        refresh_token=latest_refresh_token,
                        name_prefix=f"illust_{illust.get('id') or target_id}",
                    )
                    yield event.make_result().message(caption).file_image(local_path)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[pixivdirect] Preview download failed: %s", exc)

            yield event.plain_result(caption)
            return

        if typ == "a":
            result = await self._pixiv_call(
                "user_detail",
                {"user_id": int(target_id)},
                refresh_token=user_token,
            )
            if not result.get("ok"):
                yield event.plain_result(self._format_pixiv_error(result))
                return

            latest_refresh_token = str(result.get("refresh_token") or user_token)
            if latest_refresh_token != user_token:
                await self._set_user_token(event, latest_refresh_token)

            data = result.get("data")
            user = data.get("user") if isinstance(data, dict) else None
            profile = data.get("profile") if isinstance(data, dict) else None
            if not isinstance(user, dict) or not isinstance(profile, dict):
                yield event.plain_result("Failed to parse artist detail response.")
                return

            caption = (
                "Pixiv Artist Detail\n"
                f"- id: {user.get('id')}\n"
                f"- name: {user.get('name')}\n"
                f"- account: {user.get('account')}\n"
                f"- total_illusts: {profile.get('total_illusts')}\n"
                f"- total_manga: {profile.get('total_manga')}\n"
                f"- total_illust_bookmarks_public: {profile.get('total_illust_bookmarks_public')}\n"
                f"- webpage: {profile.get('webpage') or '(none)'}"
            )
            yield event.plain_result(caption)
            return

        yield event.plain_result("Unknown id type. Use i(illust) or a(artist).")

    async def _handle_random(self, event: AstrMessageEvent, args: list[str]):
        user_token = self._get_user_token(event)
        if not user_token:
            yield event.plain_result("Please login first: /pixiv login {refresh_token}")
            return

        filter_params, filter_summary = self._parse_random_filter(args[1:])
        filter_params.setdefault("restrict", "public")
        filter_params.setdefault("max_pages", 3)

        cache_key = self._cache_key(filter_params)
        user_key = self._user_key(event)
        cached_item = self._pop_cached_item(user_key, cache_key)
        if cached_item:
            caption = cached_item.get("caption") or "Pixiv Random Bookmark (cached)"
            path = cached_item.get("path")
            if path:
                yield event.make_result().message(f"{caption}\n- source: cache").file_image(path)
                return

        warmup = 2
        raw_warmup = filter_params.pop("warmup", None)
        if raw_warmup is not None:
            try:
                warmup = max(1, min(5, int(str(raw_warmup))))
            except ValueError:
                warmup = 2

        latest_refresh_token, error = await self._enqueue_random_items(
            user_key=user_key,
            cache_key=cache_key,
            refresh_token=user_token,
            filter_params=filter_params,
            count=warmup,
        )
        if latest_refresh_token != user_token:
            await self._set_user_token(event, latest_refresh_token)

        if error:
            yield event.plain_result(f"Failed to fetch random bookmark. {error}")
            return

        picked = self._pop_cached_item(user_key, cache_key)
        if not picked:
            yield event.plain_result("No matched bookmark image was cached.")
            return

        caption = picked.get("caption") or "Pixiv Random Bookmark"
        path = picked.get("path")
        remain = len(self._random_cache.get(user_key, {}).get(cache_key, []))
        if path:
            yield event.make_result().message(
                f"{caption}\n- source: fresh\n- cache_remain: {remain}\n- filter: {filter_summary}",
            ).file_image(path)
            return

        yield event.plain_result(caption)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=99)
    async def on_any_message(self, event: AstrMessageEvent):
        if event.get_sender_id() == event.get_self_id():
            return
        yield event.plain_result("吃瓜")

    @filter.command_group("pixiv")
    def pixiv_group(self):
        """Pixiv command group."""

    @pixiv_group.command("help")
    async def pixiv_help(self, event: AstrMessageEvent):
        """Show Pixiv command usages."""
        yield event.plain_result(self._help_text())

    @pixiv_group.command("login")
    async def pixiv_login(self, event: AstrMessageEvent, refresh_token: str = ""):
        """Bind user's Pixiv refresh token."""
        async for result in self._handle_login(event, ["login", refresh_token]):
            yield result

    @pixiv_group.command("id")
    async def pixiv_id(self, event: AstrMessageEvent, target_type: str = "", target_id: str = ""):
        """Query Pixiv by illust id or artist id."""
        async for result in self._handle_id(event, ["id", target_type, target_id]):
            yield result

    @pixiv_group.command("random")
    async def pixiv_random(self, event: AstrMessageEvent, filter_text: GreedyStr = ""):
        """Get a random bookmarked image with optional filters."""
        filter_tokens = [token for token in re.split(r"\s+", str(filter_text).strip()) if token]
        args = ["random", *filter_tokens]
        async for result in self._handle_random(event, args):
            yield result

    async def terminate(self):
        self._random_cache.clear()

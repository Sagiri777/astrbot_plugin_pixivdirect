from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .constants import (
    BYPASS_MODE_OPTIONS,
    BYPASS_MODE_PIXEZ,
    CONFIGURABLE_CONSTANT_ALIASES,
    CONFIGURABLE_CONSTANTS,
    METADATA_CACHE_TTL_HOURS,
    RANDOM_SOURCE_METADATA,
    RANDOM_SOURCE_OPTIONS,
    SEARCH_PROXY_DAILY_THRESHOLD,
    SEARCH_PROXY_STICKY_DAYS,
)


class ConfigManager:
    """Manages all configuration files for the Pixiv plugin."""

    def __init__(self, plugin_data_dir: Path) -> None:
        self._plugin_data_dir = plugin_data_dir
        self._cache_dir = plugin_data_dir / "cache"
        self._cache_index_file = self._cache_dir / "cache_index.json"
        self._token_file = plugin_data_dir / "user_refresh_tokens.json"
        self._host_map_file = plugin_data_dir / "pixiv_host_map.json"
        self._share_config_file = plugin_data_dir / "share_config.json"
        self._r18_config_file = plugin_data_dir / "r18_config.json"
        self._r18_tag_config_file = plugin_data_dir / "r18_tag_config.json"
        self._r18_mosaic_config_file = plugin_data_dir / "r18_mosaic_config.json"
        self._r18_mosaic_mode_file = plugin_data_dir / "r18_mosaic_mode_config.json"
        self._r18_mosaic_strength_file = (
            plugin_data_dir / "r18_mosaic_strength_config.json"
        )
        self._idle_cache_queue_file = plugin_data_dir / "idle_cache_queue.json"
        self._unique_config_file = plugin_data_dir / "unique_config.json"
        self._group_blocked_tags_file = plugin_data_dir / "group_blocked_tags.json"
        self._sent_illust_ids_file = plugin_data_dir / "sent_illust_ids.json"
        self._image_quality_file = plugin_data_dir / "image_quality_config.json"
        self._random_usage_stats_file = plugin_data_dir / "random_usage_stats.json"
        self._custom_constants_file = plugin_data_dir / "custom_constants.json"
        self._bypass_mode_file = plugin_data_dir / "bypass_mode.json"
        self._search_proxy_config_file = plugin_data_dir / "search_proxy_config.json"
        self._search_proxy_state_file = plugin_data_dir / "search_proxy_state.json"
        self._bookmark_metadata_cache_file = (
            plugin_data_dir / "bookmark_metadata_cache.json"
        )
        self._metadata_warmup_state_file = (
            plugin_data_dir / "metadata_warmup_state.json"
        )
        self._random_source_mode_file = plugin_data_dir / "random_source_mode.json"
        self._image_host_config_file = plugin_data_dir / "image_host_config.json"

        # Configuration state
        self._storage_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._token_map: dict[str, str] = {}
        self._share_enabled: dict[str, bool] = {}
        self._r18_in_group: dict[str, bool] = {}
        self._r18_tags_in_group: dict[str, bool] = {}
        self._r18_mosaic_in_group: dict[str, bool] = {}
        self._r18_mosaic_mode: dict[str, str] = {}
        self._r18_mosaic_strength: dict[str, int] = {}
        self._random_unique: dict[str, str] = {}
        self._idle_cache_queue: dict[str, list[dict[str, Any]]] = {}
        self._group_blocked_tags: dict[str, list[str]] = {}
        self._random_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._sent_illust_ids: dict[str, set[int]] = {}
        self._image_quality_config: dict[str, str] = {}
        self._random_usage_stats: dict[str, dict[str, dict[str, Any]]] = {}
        self._custom_constants: dict[str, Any] = {}
        self._bypass_mode: str = BYPASS_MODE_PIXEZ
        self._bookmark_metadata_cache: dict[
            str, dict[str, dict[str, dict[str, Any]]]
        ] = {}
        self._metadata_warmup_state: dict[str, dict[str, Any]] = {}
        self._random_source_mode: dict[str, str] = {}
        self._image_host_config: dict[str, Any] = {
            "enabled": False,
            "endpoint": "",
            "method": "post",
            "file_field": "file",
            "headers": {},
            "form_fields": {},
            "success_path": "",
            "delete_path": "",
            "timeout_seconds": 20,
        }
        self._search_proxy_config: dict[str, Any] = {
            "enabled": False,
            "proxy_url": "",
            "daily_threshold": SEARCH_PROXY_DAILY_THRESHOLD,
            "sticky_days": SEARCH_PROXY_STICKY_DAYS,
        }
        self._search_proxy_state: dict[str, Any] = {
            "daily_rescue_counts": {},
            "proxy_until": None,
            "last_reason": "",
        }

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def host_map_file(self) -> Path:
        return self._host_map_file

    @property
    def token_map(self) -> dict[str, str]:
        return self._token_map

    @property
    def share_enabled(self) -> dict[str, bool]:
        return self._share_enabled

    @property
    def r18_in_group(self) -> dict[str, bool]:
        return self._r18_in_group

    @r18_in_group.setter
    def r18_in_group(self, value: dict[str, bool]) -> None:
        self._r18_in_group = value

    @property
    def random_unique(self) -> dict[str, str]:
        return self._random_unique

    @random_unique.setter
    def random_unique(self, value: dict[str, str]) -> None:
        self._random_unique = value

    @property
    def r18_tags_in_group(self) -> dict[str, bool]:
        return self._r18_tags_in_group

    @property
    def r18_mosaic_in_group(self) -> dict[str, bool]:
        return self._r18_mosaic_in_group

    @property
    def idle_cache_queue(self) -> dict[str, list[dict[str, Any]]]:
        return self._idle_cache_queue

    @property
    def group_blocked_tags(self) -> dict[str, list[str]]:
        return self._group_blocked_tags

    @property
    def r18_mosaic_mode(self) -> dict[str, str]:
        return self._r18_mosaic_mode

    @property
    def r18_mosaic_strength(self) -> dict[str, int]:
        return self._r18_mosaic_strength

    def is_r18_enabled_in_group(self, group_id: str) -> bool:
        return self._r18_in_group.get(group_id, False)

    def is_r18_tags_visible_in_group(self, group_id: str) -> bool:
        return self._r18_tags_in_group.get(group_id, True)

    def is_r18_mosaic_enabled_in_group(self, group_id: str) -> bool:
        return self._r18_mosaic_in_group.get(group_id, False)

    def get_r18_mosaic_mode(self, entity_key: str) -> str:
        value = self._r18_mosaic_mode.get(entity_key, "off")
        return value if value in {"off", "hajimi", "blur"} else "off"

    def get_r18_mosaic_strength(self, entity_key: str) -> int:
        value = self._r18_mosaic_strength.get(entity_key, 12)
        return value if isinstance(value, int) and 1 <= value <= 100 else 12

    def is_unique_enabled_for_user(self, user_id: str) -> bool:
        return self._random_unique.get(user_id, "false") == "true"

    @property
    def sent_illust_ids(self) -> dict[str, set[int]]:
        return self._sent_illust_ids

    @property
    def image_quality_config(self) -> dict[str, str]:
        return self._image_quality_config

    @property
    def custom_constants(self) -> dict[str, Any]:
        return self._custom_constants

    @property
    def random_usage_stats(self) -> dict[str, dict[str, dict[str, Any]]]:
        return self._random_usage_stats

    @property
    def bookmark_metadata_cache(
        self,
    ) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
        return self._bookmark_metadata_cache

    @property
    def metadata_warmup_state(self) -> dict[str, dict[str, Any]]:
        return self._metadata_warmup_state

    @property
    def random_source_mode(self) -> dict[str, str]:
        return self._random_source_mode

    @property
    def image_host_config(self) -> dict[str, Any]:
        return self._image_host_config

    @property
    def bypass_mode(self) -> str:
        return self._bypass_mode

    @property
    def search_proxy_config(self) -> dict[str, Any]:
        return self._search_proxy_config

    @property
    def search_proxy_state(self) -> dict[str, Any]:
        return self._search_proxy_state

    def get_image_quality(self, entity_key: str) -> str:
        """Get image quality setting for an entity (user or group)."""
        return self._image_quality_config.get(entity_key, "original")

    def get_sent_ids_for_user(self, user_key: str) -> set[int]:
        """Get sent illust IDs for a user."""
        return self._sent_illust_ids.get(user_key, set())

    def add_sent_id_for_user(self, user_key: str, illust_id: int) -> None:
        """Add an illust ID to the sent set for a user."""
        if user_key not in self._sent_illust_ids:
            self._sent_illust_ids[user_key] = set()
        self._sent_illust_ids[user_key].add(illust_id)

    @property
    def random_cache(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        return self._random_cache

    @random_cache.setter
    def random_cache(self, value: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
        self._random_cache = value

    def ensure_directories(self) -> None:
        """Create necessary directories."""
        self._plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_json_file(path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _path_exists(path: Any) -> bool:
        return isinstance(path, str) and bool(path) and Path(path).exists()

    @staticmethod
    def _normalize_cache_item(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        path = item.get("path")
        if not ConfigManager._path_exists(path):
            return None

        caption = item.get("caption")
        x_restrict = item.get("x_restrict")
        tags = item.get("tags")
        illust_id = item.get("illust_id")
        author_id = item.get("author_id")
        author_name = item.get("author_name")
        page_count = item.get("page_count")
        extra_image_paths = item.get("extra_image_paths")

        return {
            "path": path,
            "caption": caption if isinstance(caption, str) else "",
            "x_restrict": x_restrict if isinstance(x_restrict, int) else 0,
            "tags": [t for t in tags if isinstance(t, str)]
            if isinstance(tags, list)
            else [],
            "illust_id": illust_id if isinstance(illust_id, int) else None,
            "author_id": author_id if isinstance(author_id, (int, str)) else None,
            "author_name": author_name if isinstance(author_name, str) else "",
            "page_count": page_count if isinstance(page_count, int) else 1,
            "extra_image_paths": [
                extra_path
                for extra_path in extra_image_paths
                if ConfigManager._path_exists(extra_path)
            ]
            if isinstance(extra_image_paths, list)
            else [],
        }

    @staticmethod
    def _normalize_usage_daily_counts(raw: Any) -> dict[str, int]:
        loaded: dict[str, int] = {}
        if not isinstance(raw, dict):
            return loaded

        for day, count in raw.items():
            if not isinstance(day, str):
                continue
            try:
                datetime.strptime(day, "%Y-%m-%d")
                normalized_count = int(count)
            except (TypeError, ValueError):
                continue
            if normalized_count > 0:
                loaded[day] = normalized_count
        return loaded

    @classmethod
    def _normalize_random_usage_entry(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        filter_params = item.get("filter_params")
        if not isinstance(filter_params, dict) or not filter_params:
            return None

        daily_counts = cls._normalize_usage_daily_counts(item.get("daily_counts"))
        return {
            "filter_params": filter_params,
            "daily_counts": daily_counts,
        }

    @staticmethod
    def _recent_day_strings(window_days: int) -> set[str]:
        today = datetime.now().date()
        return {
            (today - timedelta(days=offset)).isoformat()
            for offset in range(max(1, window_days))
        }

    def _prune_random_usage_stats(self, *, window_days: int = 7) -> None:
        keep_days = self._recent_day_strings(window_days)
        pruned: dict[str, dict[str, dict[str, Any]]] = {}

        for user_key, entries in self._random_usage_stats.items():
            if not isinstance(user_key, str) or not isinstance(entries, dict):
                continue
            valid_entries: dict[str, dict[str, Any]] = {}
            for filter_key, item in entries.items():
                if not isinstance(filter_key, str):
                    continue
                normalized = self._normalize_random_usage_entry(item)
                if normalized is None:
                    continue
                daily_counts = {
                    day: count
                    for day, count in normalized["daily_counts"].items()
                    if day in keep_days
                }
                if not daily_counts:
                    continue
                valid_entries[filter_key] = {
                    "filter_params": normalized["filter_params"],
                    "daily_counts": daily_counts,
                }
            if valid_entries:
                pruned[user_key] = valid_entries
        self._random_usage_stats = pruned

    @staticmethod
    def _normalize_bypass_mode(value: Any) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"auto", "accesser"}:
                return BYPASS_MODE_PIXEZ
            if normalized in BYPASS_MODE_OPTIONS:
                return normalized
        return BYPASS_MODE_PIXEZ

    @staticmethod
    def _normalize_search_proxy_config(raw: Any) -> dict[str, Any]:
        config = {
            "enabled": False,
            "proxy_url": "",
            "daily_threshold": SEARCH_PROXY_DAILY_THRESHOLD,
            "sticky_days": SEARCH_PROXY_STICKY_DAYS,
        }
        if not isinstance(raw, dict):
            return config

        enabled = raw.get("enabled")
        if isinstance(enabled, bool):
            config["enabled"] = enabled

        proxy_url = raw.get("proxy_url")
        if isinstance(proxy_url, str):
            config["proxy_url"] = proxy_url.strip()

        for key, default in (
            ("daily_threshold", SEARCH_PROXY_DAILY_THRESHOLD),
            ("sticky_days", SEARCH_PROXY_STICKY_DAYS),
        ):
            try:
                config[key] = max(1, int(raw.get(key, default)))
            except (TypeError, ValueError):
                config[key] = default
        return config

    @classmethod
    def _normalize_search_proxy_state(cls, raw: Any) -> dict[str, Any]:
        state = {
            "daily_rescue_counts": {},
            "proxy_until": None,
            "last_reason": "",
        }
        if not isinstance(raw, dict):
            return state

        state["daily_rescue_counts"] = cls._normalize_usage_daily_counts(
            raw.get("daily_rescue_counts")
        )
        proxy_until = raw.get("proxy_until")
        if isinstance(proxy_until, str) and proxy_until.strip():
            try:
                datetime.fromisoformat(proxy_until)
            except ValueError:
                pass
            else:
                state["proxy_until"] = proxy_until
        last_reason = raw.get("last_reason")
        if isinstance(last_reason, str):
            state["last_reason"] = last_reason.strip()
        return state

    def _prune_search_proxy_state(self, *, window_days: int = 7) -> None:
        keep_days = self._recent_day_strings(window_days)
        counts = self._normalize_usage_daily_counts(
            self._search_proxy_state.get("daily_rescue_counts")
        )
        self._search_proxy_state["daily_rescue_counts"] = {
            day: count for day, count in counts.items() if day in keep_days
        }

        proxy_until = self._search_proxy_state.get("proxy_until")
        if isinstance(proxy_until, str):
            try:
                expires_at = datetime.fromisoformat(proxy_until)
            except ValueError:
                self._search_proxy_state["proxy_until"] = None
            else:
                if expires_at <= datetime.now():
                    self._search_proxy_state["proxy_until"] = None
        elif proxy_until is not None:
            self._search_proxy_state["proxy_until"] = None

    @staticmethod
    def _normalize_random_source_mode(value: Any) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in RANDOM_SOURCE_OPTIONS:
                return normalized
        return RANDOM_SOURCE_METADATA

    @classmethod
    def _normalize_bookmark_metadata_entry(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        try:
            illust_id = int(item.get("illust_id"))
        except (TypeError, ValueError):
            return None

        image_urls = item.get("image_urls")
        if not isinstance(image_urls, list):
            image_urls = []
        normalized_urls = [
            str(url).strip()
            for url in image_urls
            if isinstance(url, str) and str(url).strip()
        ]

        caption_seed = item.get("caption_seed")
        if not isinstance(caption_seed, dict):
            caption_seed = {}

        cached_at = item.get("cached_at")
        if not isinstance(cached_at, str) or not cached_at.strip():
            cached_at = datetime.now().isoformat()

        try:
            datetime.fromisoformat(cached_at)
        except ValueError:
            cached_at = datetime.now().isoformat()

        author_id = item.get("author_id")
        if isinstance(author_id, str) and author_id.isdigit():
            author_id = int(author_id)
        elif not isinstance(author_id, int):
            author_id = None

        page_count = item.get("page_count")
        try:
            page_count = max(1, int(page_count))
        except (TypeError, ValueError):
            page_count = 1

        x_restrict = item.get("x_restrict")
        try:
            x_restrict = int(x_restrict)
        except (TypeError, ValueError):
            x_restrict = 0

        bookmark_restrict = (
            str(item.get("bookmark_restrict") or "public").strip().lower()
        )
        if bookmark_restrict not in {"public", "private"}:
            bookmark_restrict = "public"

        return {
            "illust_id": illust_id,
            "title": str(item.get("title") or "（无标题）"),
            "author_id": author_id,
            "author_name": str(item.get("author_name") or "未知作者"),
            "tags": [
                str(tag)
                for tag in item.get("tags", [])
                if isinstance(tag, str) and str(tag).strip()
            ]
            if isinstance(item.get("tags"), list)
            else [],
            "x_restrict": x_restrict,
            "page_count": page_count,
            "image_urls": normalized_urls,
            "caption_seed": caption_seed,
            "bookmark_restrict": bookmark_restrict,
            "cached_at": cached_at,
        }

    @classmethod
    def _normalize_metadata_warmup_entry(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        first_login_at = item.get("first_login_at")
        warmup_until = item.get("warmup_until")
        if not isinstance(first_login_at, str) or not isinstance(warmup_until, str):
            return None
        try:
            datetime.fromisoformat(first_login_at)
            datetime.fromisoformat(warmup_until)
        except ValueError:
            return None

        next_url = item.get("next_url")
        if next_url is not None and not isinstance(next_url, str):
            next_url = None

        try:
            next_offset = max(0, int(item.get("next_offset", 0)))
        except (TypeError, ValueError):
            next_offset = 0

        last_run_at = item.get("last_run_at")
        if last_run_at is not None and not isinstance(last_run_at, str):
            last_run_at = None

        return {
            "first_login_at": first_login_at,
            "warmup_until": warmup_until,
            "next_url": next_url or "",
            "next_offset": next_offset,
            "last_run_at": last_run_at or "",
            "completed": bool(item.get("completed")),
        }

    @classmethod
    def _normalize_image_host_config(cls, raw: Any) -> dict[str, Any]:
        config = {
            "enabled": False,
            "endpoint": "",
            "method": "post",
            "file_field": "file",
            "headers": {},
            "form_fields": {},
            "success_path": "",
            "delete_path": "",
            "timeout_seconds": 20,
        }
        if not isinstance(raw, dict):
            return config

        config["enabled"] = bool(raw.get("enabled"))
        endpoint = raw.get("endpoint")
        if isinstance(endpoint, str):
            config["endpoint"] = endpoint.strip()

        method = raw.get("method")
        if isinstance(method, str) and method.strip().lower() in {"post", "put"}:
            config["method"] = method.strip().lower()

        file_field = raw.get("file_field")
        if isinstance(file_field, str) and file_field.strip():
            config["file_field"] = file_field.strip()

        for key in ("success_path", "delete_path"):
            value = raw.get(key)
            if isinstance(value, str):
                config[key] = value.strip()

        try:
            config["timeout_seconds"] = max(3, int(raw.get("timeout_seconds", 20)))
        except (TypeError, ValueError):
            config["timeout_seconds"] = 20

        for key in ("headers", "form_fields"):
            value = raw.get(key)
            if isinstance(value, dict):
                config[key] = {
                    str(k): str(v)
                    for k, v in value.items()
                    if isinstance(k, str) and str(k).strip()
                }
        return config

    def _write_json_file(
        self,
        path: Path,
        payload: Any,
        *,
        log_label: str,
        atomic: bool = True,
    ) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            if atomic:
                tmp_file = path.with_suffix(f"{path.suffix}.tmp")
                tmp_file.write_text(content, encoding="utf-8")
                tmp_file.replace(path)
            else:
                path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("[pixivdirect] Failed to save %s: %s", log_label, exc)

    def _load_json_object(
        self,
        path: Path,
        *,
        default: dict[str, Any],
        create_log_label: str,
        invalid_log_message: str,
    ) -> dict[str, Any]:
        if not path.exists():
            self._write_json_file(path, default, log_label=create_log_label)
            return default.copy()

        raw = self._read_json_file(path)
        if not isinstance(raw, dict):
            logger.warning(invalid_log_message)
            return default.copy()

        return raw

    @staticmethod
    def _normalize_bool_mapping(raw: dict[str, Any]) -> dict[str, bool]:
        loaded: dict[str, bool] = {}
        for key, value in raw.items():
            if isinstance(key, str) and key:
                loaded[key] = bool(value)
        return loaded

    @staticmethod
    def _normalize_unique_mapping(raw: dict[str, Any]) -> dict[str, str]:
        loaded: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key:
                continue
            if isinstance(value, bool):
                loaded[key] = "true" if value else "false"
                continue
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    loaded[key] = "true"
                elif normalized in {"false", "0", "no", "off"}:
                    loaded[key] = "false"
        return loaded

    @staticmethod
    def _normalize_mosaic_mode_mapping(raw: dict[str, Any]) -> dict[str, str]:
        loaded: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key:
                continue
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if normalized in {"off", "hajimi", "blur"}:
                loaded[key] = normalized
        return loaded

    @staticmethod
    def _normalize_mosaic_strength_mapping(raw: dict[str, Any]) -> dict[str, int]:
        loaded: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key:
                continue
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= normalized <= 100:
                loaded[key] = normalized
        return loaded

    @staticmethod
    def _normalize_int_or_always(value: Any, fallback: int | str) -> int | str:
        if value == "always":
            return "always"
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return fallback

    @classmethod
    def _normalize_idle_cache_entry(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        filter_params = item.get("filter_params")
        if not isinstance(filter_params, dict):
            return None

        count = cls._normalize_int_or_always(item.get("count", 1), 1)
        remaining = cls._normalize_int_or_always(item.get("remaining", count), count)
        if count == "always":
            remaining = "always"

        return {
            "filter_params": filter_params,
            "count": count,
            "remaining": remaining,
        }

    def load_all(self) -> None:
        """Load all configuration files."""
        self._load_tokens()
        self._load_cache_index()
        self._load_bookmark_metadata_cache()
        self._load_metadata_warmup_state()
        self._load_random_source_mode()
        self._load_image_host_config()
        self._load_share_config()
        self._load_r18_config()
        self._load_r18_tag_config()
        self._load_r18_mosaic_config()
        self._load_r18_mosaic_mode_config()
        self._load_r18_mosaic_strength_config()
        self._load_idle_cache_queue()
        self._load_unique_config()
        self._load_group_blocked_tags()
        self._load_sent_illust_ids()
        self._load_image_quality_config()
        self._load_random_usage_stats()
        self._load_custom_constants()
        self._load_bypass_mode()
        self._load_search_proxy_config()
        self._load_search_proxy_state()

    def _load_tokens(self) -> None:
        raw = self._load_json_object(
            self._token_file,
            default={"users": {}},
            create_log_label="default token file",
            invalid_log_message=(
                "[pixivdirect] Failed to load token file, using empty mapping."
            ),
        )
        users = raw.get("users")
        if not isinstance(users, dict):
            self._token_map = {}
            return

        loaded: dict[str, str] = {}
        for key, token in users.items():
            if isinstance(key, str) and isinstance(token, str) and key and token:
                loaded[key] = token
        self._token_map = loaded

    def _load_cache_index(self) -> None:
        raw = self._load_json_object(
            self._cache_index_file,
            default={},
            create_log_label="default cache index file",
            invalid_log_message=(
                "[pixivdirect] Failed to load cache index, using empty cache."
            ),
        )

        loaded_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for user_key, user_cache in raw.items():
            if not isinstance(user_key, str) or not isinstance(user_cache, dict):
                continue
            loaded_user_cache: dict[str, list[dict[str, Any]]] = {}
            for cache_key, items in user_cache.items():
                if not isinstance(cache_key, str) or not isinstance(items, list):
                    continue
                valid_items: list[dict[str, Any]] = []
                for item in items:
                    normalized = self._normalize_cache_item(item)
                    if normalized is not None:
                        valid_items.append(normalized)
                if valid_items:
                    loaded_user_cache[cache_key] = valid_items
            if loaded_user_cache:
                loaded_cache[user_key] = loaded_user_cache
        self._random_cache = loaded_cache

    def _prune_bookmark_metadata_cache(self) -> None:
        ttl_hours = max(
            1,
            int(
                self.get_constant("metadata_cache_ttl_hours", METADATA_CACHE_TTL_HOURS)
            ),
        )
        cutoff = datetime.now() - timedelta(hours=ttl_hours)
        pruned: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        for user_key, restrict_map in self._bookmark_metadata_cache.items():
            if not isinstance(user_key, str) or not isinstance(restrict_map, dict):
                continue
            valid_restricts: dict[str, dict[str, dict[str, Any]]] = {}
            for restrict, entries in restrict_map.items():
                if not isinstance(restrict, str) or not isinstance(entries, dict):
                    continue
                valid_entries: dict[str, dict[str, Any]] = {}
                for illust_id, item in entries.items():
                    normalized = self._normalize_bookmark_metadata_entry(item)
                    if normalized is None:
                        continue
                    try:
                        cached_at = datetime.fromisoformat(normalized["cached_at"])
                    except ValueError:
                        continue
                    if cached_at < cutoff:
                        continue
                    valid_entries[str(normalized["illust_id"])] = normalized
                if valid_entries:
                    valid_restricts[restrict] = valid_entries
            if valid_restricts:
                pruned[user_key] = valid_restricts
        self._bookmark_metadata_cache = pruned

    def _load_bookmark_metadata_cache(self) -> None:
        raw = self._load_json_object(
            self._bookmark_metadata_cache_file,
            default={},
            create_log_label="bookmark metadata cache",
            invalid_log_message=(
                "[pixivdirect] Failed to load bookmark metadata cache, using empty cache."
            ),
        )
        loaded: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        for user_key, restrict_map in raw.items():
            if not isinstance(user_key, str) or not isinstance(restrict_map, dict):
                continue
            valid_restricts: dict[str, dict[str, dict[str, Any]]] = {}
            for restrict, entries in restrict_map.items():
                if not isinstance(restrict, str) or not isinstance(entries, dict):
                    continue
                valid_entries: dict[str, dict[str, Any]] = {}
                for illust_id, item in entries.items():
                    normalized = self._normalize_bookmark_metadata_entry(item)
                    if normalized is None:
                        continue
                    valid_entries[str(normalized["illust_id"])] = normalized
                if valid_entries:
                    valid_restricts[restrict] = valid_entries
            if valid_restricts:
                loaded[user_key] = valid_restricts
        self._bookmark_metadata_cache = loaded
        self._prune_bookmark_metadata_cache()

    def _prune_metadata_warmup_state(self) -> None:
        now = datetime.now()
        pruned: dict[str, dict[str, Any]] = {}
        for user_key, item in self._metadata_warmup_state.items():
            if not isinstance(user_key, str):
                continue
            normalized = self._normalize_metadata_warmup_entry(item)
            if normalized is None:
                continue
            try:
                warmup_until = datetime.fromisoformat(normalized["warmup_until"])
            except ValueError:
                continue
            if normalized["completed"] and warmup_until < now:
                continue
            if warmup_until < now:
                normalized["completed"] = True
            pruned[user_key] = normalized
        self._metadata_warmup_state = pruned

    def _load_metadata_warmup_state(self) -> None:
        raw = self._load_json_object(
            self._metadata_warmup_state_file,
            default={},
            create_log_label="metadata warmup state",
            invalid_log_message=(
                "[pixivdirect] Failed to load metadata warmup state, using empty state."
            ),
        )
        loaded: dict[str, dict[str, Any]] = {}
        for user_key, item in raw.items():
            if not isinstance(user_key, str):
                continue
            normalized = self._normalize_metadata_warmup_entry(item)
            if normalized is not None:
                loaded[user_key] = normalized
        self._metadata_warmup_state = loaded
        self._prune_metadata_warmup_state()

    def _load_random_source_mode(self) -> None:
        raw = self._load_json_object(
            self._random_source_mode_file,
            default={},
            create_log_label="random source mode",
            invalid_log_message=(
                "[pixivdirect] Failed to load random source mode, using defaults."
            ),
        )
        loaded: dict[str, str] = {}
        for key, value in raw.items():
            if isinstance(key, str) and key:
                loaded[key] = self._normalize_random_source_mode(value)
        self._random_source_mode = loaded

    def _load_image_host_config(self) -> None:
        raw = self._load_json_object(
            self._image_host_config_file,
            default=self._normalize_image_host_config({}),
            create_log_label="image host config",
            invalid_log_message=(
                "[pixivdirect] Failed to load image host config, using defaults."
            ),
        )
        self._image_host_config = self._normalize_image_host_config(raw)

    def _load_share_config(self) -> None:
        raw = self._load_json_object(
            self._share_config_file,
            default={},
            create_log_label="default share config",
            invalid_log_message=(
                "[pixivdirect] Failed to load share config, using default (empty)."
            ),
        )
        self._share_enabled = self._normalize_bool_mapping(raw)

    def _load_r18_config(self) -> None:
        raw = self._load_json_object(
            self._r18_config_file,
            default={},
            create_log_label="default r18 config",
            invalid_log_message=(
                "[pixivdirect] Failed to load r18 config, using default (empty)."
            ),
        )
        self._r18_in_group = self._normalize_bool_mapping(raw)

    def _load_r18_tag_config(self) -> None:
        raw = self._load_json_object(
            self._r18_tag_config_file,
            default={},
            create_log_label="default r18 tag config",
            invalid_log_message=(
                "[pixivdirect] Failed to load r18 tag config, using default (visible)."
            ),
        )
        self._r18_tags_in_group = self._normalize_bool_mapping(raw)

    def _load_r18_mosaic_config(self) -> None:
        raw = self._load_json_object(
            self._r18_mosaic_config_file,
            default={},
            create_log_label="default r18 mosaic config",
            invalid_log_message=(
                "[pixivdirect] Failed to load r18 mosaic config, using default (off)."
            ),
        )
        self._r18_mosaic_in_group = self._normalize_bool_mapping(raw)

    def _load_r18_mosaic_mode_config(self) -> None:
        raw = self._load_json_object(
            self._r18_mosaic_mode_file,
            default={},
            create_log_label="default r18 mosaic mode config",
            invalid_log_message=(
                "[pixivdirect] Failed to load r18 mosaic mode config, using default (off)."
            ),
        )
        self._r18_mosaic_mode = self._normalize_mosaic_mode_mapping(raw)

    def _load_r18_mosaic_strength_config(self) -> None:
        raw = self._load_json_object(
            self._r18_mosaic_strength_file,
            default={},
            create_log_label="default r18 mosaic strength config",
            invalid_log_message=(
                "[pixivdirect] Failed to load r18 mosaic strength config, using default (12)."
            ),
        )
        self._r18_mosaic_strength = self._normalize_mosaic_strength_mapping(raw)

    def _load_idle_cache_queue(self) -> None:
        raw = self._load_json_object(
            self._idle_cache_queue_file,
            default={},
            create_log_label="default idle_cache_queue",
            invalid_log_message=(
                "[pixivdirect] Failed to load idle cache queue, using empty queue."
            ),
        )

        loaded: dict[str, list[dict[str, Any]]] = {}
        for user_key, queue in raw.items():
            if not isinstance(user_key, str) or not isinstance(queue, list):
                continue
            valid_items: list[dict[str, Any]] = []
            for item in queue:
                normalized = self._normalize_idle_cache_entry(item)
                if normalized is not None:
                    valid_items.append(normalized)
            if valid_items:
                loaded[user_key] = valid_items
        self._idle_cache_queue = loaded

    def _load_unique_config(self) -> None:
        raw = self._load_json_object(
            self._unique_config_file,
            default={},
            create_log_label="default unique config",
            invalid_log_message=(
                "[pixivdirect] Failed to load unique config, using default (empty)."
            ),
        )
        self._random_unique = self._normalize_unique_mapping(raw)

    def _load_group_blocked_tags(self) -> None:
        raw = self._load_json_object(
            self._group_blocked_tags_file,
            default={},
            create_log_label="default group_blocked_tags",
            invalid_log_message=(
                "[pixivdirect] Failed to load group blocked tags, using empty mapping."
            ),
        )

        loaded: dict[str, list[str]] = {}
        for group_id, tags in raw.items():
            if isinstance(group_id, str) and isinstance(tags, list):
                valid_tags = [t for t in tags if isinstance(t, str) and t]
                if valid_tags:
                    loaded[group_id] = valid_tags
        self._group_blocked_tags = loaded

    def _load_random_usage_stats(self) -> None:
        raw = self._load_json_object(
            self._random_usage_stats_file,
            default={},
            create_log_label="random usage stats",
            invalid_log_message=(
                "[pixivdirect] Failed to load random usage stats, using empty stats."
            ),
        )

        loaded: dict[str, dict[str, dict[str, Any]]] = {}
        for user_key, entries in raw.items():
            if not isinstance(user_key, str) or not isinstance(entries, dict):
                continue
            valid_entries: dict[str, dict[str, Any]] = {}
            for filter_key, item in entries.items():
                if not isinstance(filter_key, str):
                    continue
                normalized = self._normalize_random_usage_entry(item)
                if normalized is not None and normalized["daily_counts"]:
                    valid_entries[filter_key] = normalized
            if valid_entries:
                loaded[user_key] = valid_entries
        self._random_usage_stats = loaded
        self._prune_random_usage_stats()

    async def save_share_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._share_config_file, self._share_enabled, log_label="share config"
            )

    async def save_r18_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._r18_config_file, self._r18_in_group, log_label="r18 config"
            )

    async def save_r18_tag_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._r18_tag_config_file,
                self._r18_tags_in_group,
                log_label="r18 tag config",
            )

    async def save_r18_mosaic_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._r18_mosaic_config_file,
                self._r18_mosaic_in_group,
                log_label="r18 mosaic config",
            )

    async def save_r18_mosaic_mode_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._r18_mosaic_mode_file,
                self._r18_mosaic_mode,
                log_label="r18 mosaic mode config",
            )

    async def save_r18_mosaic_strength_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._r18_mosaic_strength_file,
                self._r18_mosaic_strength,
                log_label="r18 mosaic strength config",
            )

    async def save_idle_cache_queue(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._idle_cache_queue_file,
                self._idle_cache_queue,
                log_label="idle cache queue",
            )

    async def save_unique_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._unique_config_file,
                self._random_unique,
                log_label="unique config",
            )

    async def save_group_blocked_tags(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._group_blocked_tags_file,
                self._group_blocked_tags,
                log_label="group blocked tags",
            )

    async def save_cache_index(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._cache_index_file, self._random_cache, log_label="cache index"
            )

    async def save_bookmark_metadata_cache(self) -> None:
        async with self._cache_lock:
            self._prune_bookmark_metadata_cache()
            self._write_json_file(
                self._bookmark_metadata_cache_file,
                self._bookmark_metadata_cache,
                log_label="bookmark metadata cache",
            )

    async def save_metadata_warmup_state(self) -> None:
        async with self._storage_lock:
            self._prune_metadata_warmup_state()
            self._write_json_file(
                self._metadata_warmup_state_file,
                self._metadata_warmup_state,
                log_label="metadata warmup state",
            )

    async def save_random_source_mode(self) -> None:
        async with self._storage_lock:
            self._write_json_file(
                self._random_source_mode_file,
                self._random_source_mode,
                log_label="random source mode",
            )

    async def save_image_host_config(self) -> None:
        async with self._storage_lock:
            self._write_json_file(
                self._image_host_config_file,
                self._normalize_image_host_config(self._image_host_config),
                log_label="image host config",
            )

    async def save_tokens(self) -> None:
        async with self._storage_lock:
            self._write_json_file(
                self._token_file,
                {"users": self._token_map},
                log_label="tokens",
            )

    def _load_sent_illust_ids(self) -> None:
        raw = self._load_json_object(
            self._sent_illust_ids_file,
            default={},
            create_log_label="sent illust ids file",
            invalid_log_message=(
                "[pixivdirect] Failed to load sent illust ids, using empty set."
            ),
        )

        loaded: dict[str, set[int]] = {}
        for user_key, ids in raw.items():
            if isinstance(user_key, str) and isinstance(ids, list):
                valid_ids = {
                    int(i)
                    for i in ids
                    if isinstance(i, (int, str)) and str(i).isdigit()
                }
                if valid_ids:
                    loaded[user_key] = valid_ids
        self._sent_illust_ids = loaded

    async def save_sent_illust_ids(self) -> None:
        async with self._cache_lock:
            serializable = {k: sorted(v) for k, v in self._sent_illust_ids.items()}
            self._write_json_file(
                self._sent_illust_ids_file,
                serializable,
                log_label="sent illust ids",
            )

    def _load_image_quality_config(self) -> None:
        raw = self._load_json_object(
            self._image_quality_file,
            default={},
            create_log_label="image quality config",
            invalid_log_message=(
                "[pixivdirect] Failed to load image quality config, using default."
            ),
        )

        loaded: dict[str, str] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, str):
                    if value in ("original", "medium", "small"):
                        loaded[key] = value
        self._image_quality_config = loaded

    async def save_image_quality_config(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._image_quality_file,
                self._image_quality_config,
                log_label="image quality config",
            )

    async def save_random_usage_stats(self) -> None:
        async with self._cache_lock:
            self._prune_random_usage_stats()
            self._write_json_file(
                self._random_usage_stats_file,
                self._random_usage_stats,
                log_label="random usage stats",
            )

    async def record_random_filter_usage(
        self,
        *,
        user_key: str,
        filter_key: str,
        filter_params: dict[str, Any],
    ) -> None:
        if not user_key or not filter_key or not filter_params:
            return

        today = datetime.now().date().isoformat()
        user_stats = self._random_usage_stats.setdefault(user_key, {})
        entry = user_stats.setdefault(
            filter_key,
            {
                "filter_params": dict(filter_params),
                "daily_counts": {},
            },
        )
        entry["filter_params"] = dict(filter_params)
        daily_counts = entry.setdefault("daily_counts", {})
        if not isinstance(daily_counts, dict):
            daily_counts = {}
            entry["daily_counts"] = daily_counts
        daily_counts[today] = int(daily_counts.get(today, 0)) + 1
        await self.save_random_usage_stats()

    def get_top_random_filter_for_user(
        self, user_key: str, *, window_days: int = 7
    ) -> dict[str, Any] | None:
        user_stats = self._random_usage_stats.get(user_key)
        if not isinstance(user_stats, dict):
            return None

        keep_days = self._recent_day_strings(window_days)
        best_item: dict[str, Any] | None = None
        best_total = 0
        best_latest_day = ""

        for item in user_stats.values():
            normalized = self._normalize_random_usage_entry(item)
            if normalized is None:
                continue
            daily_counts = normalized["daily_counts"]
            total = sum(
                count for day, count in daily_counts.items() if day in keep_days
            )
            if total <= 0:
                continue
            latest_day = max(
                (day for day in daily_counts if day in keep_days), default=""
            )
            if total > best_total or (
                total == best_total and latest_day > best_latest_day
            ):
                best_total = total
                best_latest_day = latest_day
                best_item = dict(normalized["filter_params"])

        return best_item

    def _load_custom_constants(self) -> None:
        raw = self._load_json_object(
            self._custom_constants_file,
            default={},
            create_log_label="custom constants file",
            invalid_log_message=(
                "[pixivdirect] Failed to load custom constants, using defaults."
            ),
        )

        loaded: dict[str, Any] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            normalized_key = CONFIGURABLE_CONSTANT_ALIASES.get(key)
            if normalized_key is None:
                normalized_key = CONFIGURABLE_CONSTANT_ALIASES.get(key.lower())
            if normalized_key is None:
                continue

            default_value = CONFIGURABLE_CONSTANTS[normalized_key]
            coerced_value = self._coerce_constant_value(value, default_value)
            if coerced_value is not None:
                loaded[normalized_key] = coerced_value

        self._custom_constants = loaded

    async def save_custom_constants(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._custom_constants_file,
                self._custom_constants,
                log_label="custom constants",
            )

    def _load_bypass_mode(self) -> None:
        raw = self._load_json_object(
            self._bypass_mode_file,
            default={"mode": BYPASS_MODE_PIXEZ},
            create_log_label="bypass mode config",
            invalid_log_message=(
                "[pixivdirect] Failed to load bypass mode config, using pixez."
            ),
        )
        self._bypass_mode = self._normalize_bypass_mode(raw.get("mode"))

    async def save_bypass_mode(self) -> None:
        async with self._storage_lock:
            self._write_json_file(
                self._bypass_mode_file,
                {"mode": self._bypass_mode},
                log_label="bypass mode config",
            )

    def _load_search_proxy_config(self) -> None:
        raw = self._load_json_object(
            self._search_proxy_config_file,
            default=self._normalize_search_proxy_config({}),
            create_log_label="search proxy config",
            invalid_log_message=(
                "[pixivdirect] Failed to load search proxy config, using defaults."
            ),
        )
        self._search_proxy_config = self._normalize_search_proxy_config(raw)

    async def save_search_proxy_config(self) -> None:
        async with self._storage_lock:
            self._write_json_file(
                self._search_proxy_config_file,
                self._normalize_search_proxy_config(self._search_proxy_config),
                log_label="search proxy config",
            )

    def _load_search_proxy_state(self) -> None:
        raw = self._load_json_object(
            self._search_proxy_state_file,
            default=self._normalize_search_proxy_state({}),
            create_log_label="search proxy state",
            invalid_log_message=(
                "[pixivdirect] Failed to load search proxy state, using defaults."
            ),
        )
        self._search_proxy_state = self._normalize_search_proxy_state(raw)
        self._prune_search_proxy_state()

    async def save_search_proxy_state(self) -> None:
        async with self._storage_lock:
            self._prune_search_proxy_state()
            self._write_json_file(
                self._search_proxy_state_file,
                self._search_proxy_state,
                log_label="search proxy state",
            )

    def get_effective_bypass_mode(self) -> str:
        if bool(self.get_constant("disable_bypass_sni", False)):
            return "disabled"
        return self._normalize_bypass_mode(self._bypass_mode)

    def set_bypass_mode(self, mode: str) -> None:
        self._bypass_mode = self._normalize_bypass_mode(mode)

    def is_search_proxy_configured(self) -> bool:
        return bool(self._search_proxy_config.get("enabled")) and bool(
            str(self._search_proxy_config.get("proxy_url") or "").strip()
        )

    def get_search_proxy_url(self) -> str | None:
        proxy_url = str(self._search_proxy_config.get("proxy_url") or "").strip()
        return proxy_url or None

    def is_search_proxy_active(self) -> bool:
        proxy_until = self._search_proxy_state.get("proxy_until")
        if not isinstance(proxy_until, str) or not proxy_until:
            return False
        try:
            return datetime.fromisoformat(proxy_until) > datetime.now()
        except ValueError:
            return False

    async def record_search_proxy_rescue(self, *, reason: str) -> None:
        self._prune_search_proxy_state()
        today = datetime.now().date().isoformat()
        counts = self._search_proxy_state.setdefault("daily_rescue_counts", {})
        counts[today] = int(counts.get(today, 0)) + 1
        self._search_proxy_state["last_reason"] = reason.strip()[:200]

        threshold = max(1, int(self._search_proxy_config.get("daily_threshold", 3)))
        sticky_days = max(1, int(self._search_proxy_config.get("sticky_days", 3)))
        if counts[today] >= threshold:
            self._search_proxy_state["proxy_until"] = (
                datetime.now() + timedelta(days=sticky_days)
            ).isoformat()
        await self.save_search_proxy_state()

    def init_metadata_warmup_user(self, user_key: str) -> bool:
        if not user_key or user_key in self._metadata_warmup_state:
            return False
        now = datetime.now()
        self._metadata_warmup_state[user_key] = {
            "first_login_at": now.isoformat(),
            "warmup_until": (now + timedelta(days=2)).isoformat(),
            "next_url": "",
            "next_offset": 0,
            "last_run_at": "",
            "completed": False,
        }
        return True

    def get_random_source_mode_for_entity(self, entity_key: str) -> str:
        return self._normalize_random_source_mode(
            self._random_source_mode.get(entity_key, RANDOM_SOURCE_METADATA)
        )

    def set_random_source_mode_for_entity(self, entity_key: str, mode: str) -> None:
        self._random_source_mode[entity_key] = self._normalize_random_source_mode(mode)

    def upsert_bookmark_metadata(
        self,
        *,
        user_key: str,
        restrict: str,
        entries: list[dict[str, Any]],
    ) -> int:
        if not user_key:
            return 0
        restrict_key = str(restrict or "public").strip().lower() or "public"
        user_cache = self._bookmark_metadata_cache.setdefault(user_key, {})
        restrict_cache = user_cache.setdefault(restrict_key, {})
        inserted = 0
        now_iso = datetime.now().isoformat()
        for item in entries:
            normalized = self._normalize_bookmark_metadata_entry(item)
            if normalized is None:
                continue
            normalized["cached_at"] = now_iso
            restrict_cache[str(normalized["illust_id"])] = normalized
            inserted += 1
        self._prune_bookmark_metadata_cache()
        return inserted

    def get_constant(self, key: str, default: Any = None) -> Any:
        """Get a constant value, checking custom constants first, then defaults."""
        normalized_key = CONFIGURABLE_CONSTANT_ALIASES.get(key)
        if normalized_key is None:
            normalized_key = CONFIGURABLE_CONSTANT_ALIASES.get(key.lower(), key)
        return self._custom_constants.get(normalized_key, default)

    @staticmethod
    def _coerce_constant_value(value: Any, default: Any) -> Any | None:
        if isinstance(default, bool):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
            return None

        if isinstance(default, int):
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value.strip())
                except ValueError:
                    return None
            return None

        if isinstance(default, float):
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.strip())
                except ValueError:
                    return None
            return None

        return value if isinstance(value, type(default)) else None

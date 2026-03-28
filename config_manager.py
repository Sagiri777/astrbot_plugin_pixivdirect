from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from astrbot.api import logger


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
        self._idle_cache_queue_file = plugin_data_dir / "idle_cache_queue.json"
        self._unique_config_file = plugin_data_dir / "unique_config.json"
        self._group_blocked_tags_file = plugin_data_dir / "group_blocked_tags.json"
        self._sent_illust_ids_file = plugin_data_dir / "sent_illust_ids.json"
        self._image_quality_file = plugin_data_dir / "image_quality_config.json"
        self._custom_constants_file = plugin_data_dir / "custom_constants.json"

        # Configuration state
        self._storage_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._token_map: dict[str, str] = {}
        self._share_enabled: dict[str, bool] = {}
        self._r18_in_group: dict[str, bool] = {}
        self._r18_tags_in_group: dict[str, bool] = {}
        self._r18_mosaic_in_group: dict[str, bool] = {}
        self._random_unique: dict[str, str] = {}
        self._idle_cache_queue: dict[str, list[dict[str, Any]]] = {}
        self._group_blocked_tags: dict[str, list[str]] = {}
        self._random_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._sent_illust_ids: dict[str, set[int]] = {}
        self._image_quality_config: dict[str, str] = {}
        self._custom_constants: dict[str, Any] = {}

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

    def is_r18_enabled_in_group(self, group_id: str) -> bool:
        return self._r18_in_group.get(group_id, False)

    def is_r18_tags_visible_in_group(self, group_id: str) -> bool:
        return self._r18_tags_in_group.get(group_id, True)

    def is_r18_mosaic_enabled_in_group(self, group_id: str) -> bool:
        return self._r18_mosaic_in_group.get(group_id, False)

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
        }

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
        self._load_share_config()
        self._load_r18_config()
        self._load_r18_tag_config()
        self._load_r18_mosaic_config()
        self._load_idle_cache_queue()
        self._load_unique_config()
        self._load_group_blocked_tags()
        self._load_sent_illust_ids()
        self._load_image_quality_config()
        self._load_custom_constants()

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

    def _load_custom_constants(self) -> None:
        raw = self._load_json_object(
            self._custom_constants_file,
            default={},
            create_log_label="custom constants file",
            invalid_log_message=(
                "[pixivdirect] Failed to load custom constants, using defaults."
            ),
        )

        self._custom_constants = raw

    async def save_custom_constants(self) -> None:
        async with self._cache_lock:
            self._write_json_file(
                self._custom_constants_file,
                self._custom_constants,
                log_label="custom constants",
            )

    def get_constant(self, key: str, default: Any = None) -> Any:
        """Get a constant value, checking custom constants first, then defaults."""
        return self._custom_constants.get(key, default)

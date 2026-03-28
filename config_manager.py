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
        if not self._token_file.exists():
            self._token_map = {}
            try:
                self._token_file.parent.mkdir(parents=True, exist_ok=True)
                default = {"users": {}}
                self._token_file.write_text(
                    json.dumps(default, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default token file: %s", exc
                )
            return
        try:
            raw = json.loads(self._token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load token file, using empty mapping."
            )
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

    def _load_cache_index(self) -> None:
        if not self._cache_index_file.exists():
            self._random_cache = {}
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._cache_index_file.write_text("{}\n", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default cache index file: %s", exc
                )
            return
        try:
            raw = json.loads(self._cache_index_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load cache index, using empty cache."
            )
            self._random_cache = {}
            return

        if not isinstance(raw, dict):
            self._random_cache = {}
            return

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
                    if isinstance(item, dict):
                        path = item.get("path")
                        if isinstance(path, str) and path and Path(path).exists():
                            preserved: dict[str, Any] = {"path": path}
                            caption = item.get("caption")
                            preserved["caption"] = (
                                caption if isinstance(caption, str) else ""
                            )
                            x_restrict = item.get("x_restrict")
                            preserved["x_restrict"] = (
                                x_restrict if isinstance(x_restrict, int) else 0
                            )
                            tags = item.get("tags")
                            preserved["tags"] = (
                                [t for t in tags if isinstance(t, str)]
                                if isinstance(tags, list)
                                else []
                            )
                            illust_id = item.get("illust_id")
                            preserved["illust_id"] = (
                                illust_id if isinstance(illust_id, int) else None
                            )
                            author_id = item.get("author_id")
                            preserved["author_id"] = (
                                author_id if isinstance(author_id, (int, str)) else None
                            )
                            author_name = item.get("author_name")
                            preserved["author_name"] = (
                                author_name if isinstance(author_name, str) else ""
                            )
                            page_count = item.get("page_count")
                            preserved["page_count"] = (
                                page_count if isinstance(page_count, int) else 1
                            )
                            valid_items.append(preserved)
                if valid_items:
                    loaded_user_cache[cache_key] = valid_items
            if loaded_user_cache:
                loaded_cache[user_key] = loaded_user_cache
        self._random_cache = loaded_cache

    def _load_share_config(self) -> None:
        if not self._share_config_file.exists():
            self._share_enabled = {}
            try:
                self._share_config_file.parent.mkdir(parents=True, exist_ok=True)
                self._share_config_file.write_text(
                    json.dumps({}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default share config: %s", exc
                )
            return
        try:
            raw = json.loads(self._share_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load share config, using default (empty)."
            )
            self._share_enabled = {}
            return

        if isinstance(raw, dict):
            loaded: dict[str, bool] = {}
            for key, value in raw.items():
                if isinstance(key, str) and key:
                    loaded[key] = bool(value)
            self._share_enabled = loaded
        else:
            self._share_enabled = {}

    def _load_r18_config(self) -> None:
        if not self._r18_config_file.exists():
            self._r18_in_group = {}
            try:
                self._r18_config_file.parent.mkdir(parents=True, exist_ok=True)
                self._r18_config_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default r18 config: %s", exc
                )
            return
        try:
            raw = json.loads(self._r18_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load r18 config, using default (empty)."
            )
            self._r18_in_group = {}
            return

        loaded: dict[str, bool] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and key:
                    loaded[key] = bool(value)
        self._r18_in_group = loaded

    def _load_r18_tag_config(self) -> None:
        if not self._r18_tag_config_file.exists():
            self._r18_tags_in_group = {}
            try:
                self._r18_tag_config_file.parent.mkdir(parents=True, exist_ok=True)
                self._r18_tag_config_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default r18 tag config: %s", exc
                )
            return
        try:
            raw = json.loads(self._r18_tag_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load r18 tag config, using default (visible)."
            )
            self._r18_tags_in_group = {}
            return

        loaded: dict[str, bool] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and key:
                    loaded[key] = bool(value)
        self._r18_tags_in_group = loaded

    def _load_r18_mosaic_config(self) -> None:
        if not self._r18_mosaic_config_file.exists():
            self._r18_mosaic_in_group = {}
            try:
                self._r18_mosaic_config_file.parent.mkdir(parents=True, exist_ok=True)
                self._r18_mosaic_config_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default r18 mosaic config: %s",
                    exc,
                )
            return
        try:
            raw = json.loads(self._r18_mosaic_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load r18 mosaic config, using default (off)."
            )
            self._r18_mosaic_in_group = {}
            return

        loaded: dict[str, bool] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and key:
                    loaded[key] = bool(value)
        self._r18_mosaic_in_group = loaded

    def _load_idle_cache_queue(self) -> None:
        if not self._idle_cache_queue_file.exists():
            self._idle_cache_queue = {}
            try:
                self._idle_cache_queue_file.parent.mkdir(parents=True, exist_ok=True)
                self._idle_cache_queue_file.write_text("{}\n", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default idle_cache_queue: %s", exc
                )
            return
        try:
            raw = json.loads(self._idle_cache_queue_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load idle cache queue, using empty queue."
            )
            self._idle_cache_queue = {}
            return

        if not isinstance(raw, dict):
            self._idle_cache_queue = {}
            return

        loaded: dict[str, list[dict[str, Any]]] = {}
        for user_key, queue in raw.items():
            if not isinstance(user_key, str) or not isinstance(queue, list):
                continue
            valid_items: list[dict[str, Any]] = []
            for item in queue:
                if isinstance(item, dict):
                    filter_params = item.get("filter_params")
                    if isinstance(filter_params, dict):
                        count = item.get("count", 1)
                        remaining = item.get("remaining", count)
                        valid_items.append(
                            {
                                "filter_params": filter_params,
                                "count": count,
                                "remaining": remaining,
                            }
                        )
            if valid_items:
                loaded[user_key] = valid_items
        self._idle_cache_queue = loaded

    def _load_unique_config(self) -> None:
        if not self._unique_config_file.exists():
            self._random_unique = {}
            try:
                self._unique_config_file.parent.mkdir(parents=True, exist_ok=True)
                self._unique_config_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default unique config: %s", exc
                )
            return
        try:
            raw = json.loads(self._unique_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load unique config, using default (empty)."
            )
            self._random_unique = {}
            return

        loaded: dict[str, str] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and key:
                    loaded[key] = str(value)
        self._random_unique = loaded

    def _load_group_blocked_tags(self) -> None:
        if not self._group_blocked_tags_file.exists():
            self._group_blocked_tags = {}
            try:
                self._group_blocked_tags_file.parent.mkdir(parents=True, exist_ok=True)
                self._group_blocked_tags_file.write_text("{}\n", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create default group_blocked_tags: %s", exc
                )
            return
        try:
            raw = json.loads(self._group_blocked_tags_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load group blocked tags, using empty mapping."
            )
            self._group_blocked_tags = {}
            return

        if not isinstance(raw, dict):
            self._group_blocked_tags = {}
            return

        loaded: dict[str, list[str]] = {}
        for group_id, tags in raw.items():
            if isinstance(group_id, str) and isinstance(tags, list):
                valid_tags = [t for t in tags if isinstance(t, str) and t]
                if valid_tags:
                    loaded[group_id] = valid_tags
        self._group_blocked_tags = loaded

    async def save_share_config(self) -> None:
        async with self._cache_lock:
            try:
                self._share_config_file.write_text(
                    json.dumps(
                        self._share_enabled,
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save share config: %s", exc)

    async def save_r18_config(self) -> None:
        async with self._cache_lock:
            try:
                self._r18_config_file.write_text(
                    json.dumps(
                        self._r18_in_group,
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save r18 config: %s", exc)

    async def save_r18_tag_config(self) -> None:
        async with self._cache_lock:
            try:
                self._r18_tag_config_file.write_text(
                    json.dumps(self._r18_tags_in_group, ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save r18 tag config: %s", exc)

    async def save_r18_mosaic_config(self) -> None:
        async with self._cache_lock:
            try:
                self._r18_mosaic_config_file.write_text(
                    json.dumps(
                        self._r18_mosaic_in_group,
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning(
                    "[pixivdirect] Failed to save r18 mosaic config: %s", exc
                )

    async def save_idle_cache_queue(self) -> None:
        async with self._cache_lock:
            try:
                self._idle_cache_queue_file.write_text(
                    json.dumps(self._idle_cache_queue, ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save idle cache queue: %s", exc)

    async def save_unique_config(self) -> None:
        async with self._cache_lock:
            try:
                self._unique_config_file.write_text(
                    json.dumps(
                        self._random_unique,
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save unique config: %s", exc)

    async def save_group_blocked_tags(self) -> None:
        async with self._cache_lock:
            try:
                self._group_blocked_tags_file.write_text(
                    json.dumps(self._group_blocked_tags, ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning(
                    "[pixivdirect] Failed to save group blocked tags: %s", exc
                )

    async def save_cache_index(self) -> None:
        async with self._cache_lock:
            try:
                self._cache_index_file.write_text(
                    json.dumps(self._random_cache, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save cache index: %s", exc)

    async def save_tokens(self) -> None:
        async with self._storage_lock:
            payload = {"users": self._token_map}
            tmp_file = self._token_file.with_suffix(".tmp")
            tmp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_file.replace(self._token_file)

    def _load_sent_illust_ids(self) -> None:
        if not self._sent_illust_ids_file.exists():
            self._sent_illust_ids = {}
            try:
                self._sent_illust_ids_file.parent.mkdir(parents=True, exist_ok=True)
                self._sent_illust_ids_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create sent illust ids file: %s", exc
                )
            return
        try:
            raw = json.loads(self._sent_illust_ids_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load sent illust ids, using empty set."
            )
            self._sent_illust_ids = {}
            return

        loaded: dict[str, set[int]] = {}
        if isinstance(raw, dict):
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
            try:
                serializable = {k: list(v) for k, v in self._sent_illust_ids.items()}
                self._sent_illust_ids_file.write_text(
                    json.dumps(serializable, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save sent illust ids: %s", exc)

    def _load_image_quality_config(self) -> None:
        if not self._image_quality_file.exists():
            self._image_quality_config = {}
            try:
                self._image_quality_file.parent.mkdir(parents=True, exist_ok=True)
                self._image_quality_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create image quality config: %s", exc
                )
            return
        try:
            raw = json.loads(self._image_quality_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load image quality config, using default."
            )
            self._image_quality_config = {}
            return

        loaded: dict[str, str] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, str):
                    if value in ("original", "medium", "small"):
                        loaded[key] = value
        self._image_quality_config = loaded

    async def save_image_quality_config(self) -> None:
        async with self._cache_lock:
            try:
                self._image_quality_file.write_text(
                    json.dumps(self._image_quality_config, ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning(
                    "[pixivdirect] Failed to save image quality config: %s", exc
                )

    def _load_custom_constants(self) -> None:
        if not self._custom_constants_file.exists():
            self._custom_constants = {}
            try:
                self._custom_constants_file.parent.mkdir(parents=True, exist_ok=True)
                self._custom_constants_file.write_text("{}", encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Failed to create custom constants file: %s", exc
                )
            return
        try:
            raw = json.loads(self._custom_constants_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load custom constants, using defaults."
            )
            self._custom_constants = {}
            return

        if isinstance(raw, dict):
            self._custom_constants = raw
        else:
            self._custom_constants = {}

    async def save_custom_constants(self) -> None:
        async with self._cache_lock:
            try:
                self._custom_constants_file.write_text(
                    json.dumps(self._custom_constants, ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save custom constants: %s", exc)

    def get_constant(self, key: str, default: Any = None) -> Any:
        """Get a constant value, checking custom constants first, then defaults."""
        return self._custom_constants.get(key, default)

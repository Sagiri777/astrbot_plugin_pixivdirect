from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import (
    CACHE_INDEX_FILE,
    DEFAULT_BOOKMARK_RESTRICT,
    DEFAULT_IMAGE_QUALITY,
    HOST_MAP_FILE,
    PREFERENCES_FILE,
    TOKEN_FILE,
    ensure_path,
)


class ConfigManager:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = ensure_path(root_dir)
        self.cache_dir = self.root_dir / "cache"
        self.token_file = self.root_dir / TOKEN_FILE
        self.preferences_file = self.root_dir / PREFERENCES_FILE
        self.host_map_file = self.root_dir / HOST_MAP_FILE
        self.cache_index_file = self.cache_dir / CACHE_INDEX_FILE

        self.token_map: dict[str, str] = {}
        self.preferences: dict[str, dict[str, Any]] = {}
        self.cache_index: dict[str, list[dict[str, Any]]] = {}

    def ensure_directories(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> None:
        self.token_map = self._load_json(self.token_file, {})
        self.preferences = self._load_json(self.preferences_file, {})
        self.cache_index = self._load_json(self.cache_index_file, {})

    def get_user_token(self, user_id: str) -> str | None:
        token = self.token_map.get(user_id)
        return token if isinstance(token, str) and token else None

    async def set_user_token(self, user_id: str, refresh_token: str) -> None:
        self.token_map[user_id] = refresh_token
        self._save_json(self.token_file, self.token_map)

    def get_quality(self, user_id: str) -> str:
        prefs = self.preferences.get(user_id) or {}
        quality = prefs.get("quality")
        return (
            quality if isinstance(quality, str) and quality else DEFAULT_IMAGE_QUALITY
        )

    async def set_quality(self, user_id: str, quality: str) -> None:
        prefs = self.preferences.setdefault(user_id, {})
        prefs["quality"] = quality
        self._save_json(self.preferences_file, self.preferences)

    def get_bookmark_restrict(self, user_id: str) -> str:
        prefs = self.preferences.get(user_id) or {}
        restrict = prefs.get("bookmark_restrict")
        return (
            restrict
            if isinstance(restrict, str) and restrict
            else DEFAULT_BOOKMARK_RESTRICT
        )

    async def set_bookmark_restrict(self, user_id: str, restrict: str) -> None:
        prefs = self.preferences.setdefault(user_id, {})
        prefs["bookmark_restrict"] = restrict
        self._save_json(self.preferences_file, self.preferences)

    async def add_cache_entry(self, user_id: str, entry: dict[str, Any]) -> None:
        entries = self.cache_index.setdefault(user_id, [])
        entries.append(entry)
        self._save_json(self.cache_index_file, self.cache_index)

    def find_cached_paths(self, user_id: str, illust_id: int) -> list[str]:
        entries = self.cache_index.get(user_id, [])
        return [
            str(item.get("path"))
            for item in entries
            if item.get("illust_id") == illust_id and isinstance(item.get("path"), str)
        ]

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        try:
            with path.open(encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    @staticmethod
    def _save_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")

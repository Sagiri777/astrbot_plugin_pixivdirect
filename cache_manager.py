from __future__ import annotations

from typing import Any

from .config_manager import ConfigManager


class CacheManager:
    def __init__(self, config_manager: ConfigManager) -> None:
        self._config = config_manager

    def find_downloaded_illust(self, user_id: str, illust_id: int) -> list[str]:
        return self._config.find_cached_paths(user_id, illust_id)

    async def remember_download(
        self,
        user_id: str,
        *,
        illust_id: int,
        page: int,
        path: str,
        url: str,
    ) -> None:
        await self._config.add_cache_entry(
            user_id,
            {
                "illust_id": illust_id,
                "page": page,
                "path": path,
                "url": url,
            },
        )

    @staticmethod
    def parse_random_filter(tokens: dict[str, str]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        if "tag" in tokens:
            parsed["tag"] = tokens["tag"]
        if "restrict" in tokens:
            parsed["restrict"] = tokens["restrict"]
        if "pages" in tokens:
            parsed["pages"] = tokens["pages"]
        return parsed

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .config_manager import ConfigManager
from .constants import DEFAULT_POOL_KEY


class CacheManager:
    """Manages cache operations for the Pixiv plugin."""

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config = config_manager

    @staticmethod
    def _has_live_path(item: dict[str, Any]) -> bool:
        path = item.get("path")
        return isinstance(path, str) and bool(path) and Path(path).exists()

    def find_cached_by_illust_id(self, illust_id: int) -> dict[str, Any] | None:
        """Find a cached item by illust_id across all user pools."""
        for user_cache in self._config.random_cache.values():
            pool = user_cache.get(DEFAULT_POOL_KEY, [])
            for item in pool:
                item_id = item.get("illust_id")
                if (
                    isinstance(item_id, int)
                    and item_id == illust_id
                    and self._has_live_path(item)
                ):
                    return item
        return None

    async def pop_cached_item(
        self,
        user_key: str,
        cache_key: str,
        filter_params: dict[str, Any] | None = None,
        exclude_sent: bool = False,
    ) -> dict[str, Any] | None:
        """Pop a cached item matching the filter criteria from the user's pool.

        If filter_params is provided, scans the unified pool for a matching item.
        Otherwise falls back to exact cache_key lookup (legacy behavior).
        When random_unique is False, returns a random item without removing from pool.
        When random_unique is True, removes and returns the first matching item.
        When exclude_sent is True, excludes already sent illust IDs.
        """
        async with self._config._cache_lock:
            user_cache = self._config.random_cache.get(user_key)
            if not user_cache:
                return None

            unique_enabled = self._config.is_unique_enabled_for_user(user_key)
            sent_ids = (
                self._config.get_sent_ids_for_user(user_key) if exclude_sent else set()
            )

            # Try unified pool first if filter_params provided
            if filter_params:
                pool = user_cache.get(DEFAULT_POOL_KEY)
                if pool:
                    if unique_enabled:
                        # Original behavior: return first matching item and remove it
                        for i, item in enumerate(pool):
                            if not self._has_live_path(item):
                                continue
                            # Skip already sent items
                            illust_id = item.get("illust_id")
                            if (
                                exclude_sent
                                and isinstance(illust_id, int)
                                and illust_id in sent_ids
                            ):
                                continue
                            if self._item_matches_filter(item, filter_params):
                                pool.pop(i)
                                return item
                    else:
                        # Random selection: collect all matching items and pick one randomly
                        matching_items = []
                        for item in pool:
                            if not self._has_live_path(item):
                                continue
                            # Skip already sent items
                            illust_id = item.get("illust_id")
                            if (
                                exclude_sent
                                and isinstance(illust_id, int)
                                and illust_id in sent_ids
                            ):
                                continue
                            if self._item_matches_filter(item, filter_params):
                                matching_items.append(item)
                        if matching_items:
                            return random.choice(matching_items)

            # Fallback: try exact cache_key match (legacy or no-filter)
            queue = user_cache.get(cache_key)
            if queue:
                if unique_enabled:
                    # Original behavior: pop from front
                    while queue:
                        item = queue.pop(0)
                        if self._has_live_path(item):
                            # Skip already sent items
                            illust_id = item.get("illust_id")
                            if (
                                exclude_sent
                                and isinstance(illust_id, int)
                                and illust_id in sent_ids
                            ):
                                continue
                            return item
                else:
                    # Random selection from queue
                    valid_items = [
                        item
                        for item in queue
                        if self._has_live_path(item)
                        and not (
                            exclude_sent
                            and isinstance(item.get("illust_id"), int)
                            and item.get("illust_id") in sent_ids
                        )
                    ]
                    if valid_items:
                        return random.choice(valid_items)
            return None

    def count_matching_items(
        self, user_key: str, filter_params: dict[str, Any] | None = None
    ) -> int:
        """Count cached items matching the given filter criteria."""
        user_cache = self._config.random_cache.get(user_key, {})
        pool = user_cache.get(DEFAULT_POOL_KEY, [])

        count = 0
        for item in pool:
            if not self._has_live_path(item):
                continue
            if filter_params and not self._item_matches_filter(item, filter_params):
                continue
            count += 1
        return count

    @staticmethod
    def is_r18_item(item: dict[str, Any]) -> bool:
        """Check if a cached item is R-18 content."""
        x_restrict = item.get("x_restrict", 0)
        if isinstance(x_restrict, int) and x_restrict > 0:
            return True
        tags = item.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag.upper() in ("R-18", "R18", "R-18G"):
                    return True
        return False

    @staticmethod
    def _item_matches_filter(
        item: dict[str, Any], filter_params: dict[str, Any]
    ) -> bool:
        """Check if a cached item matches the given filter criteria."""
        # Tag filter: item tags must include the requested tag (case-insensitive)
        tag_filter = filter_params.get("tag")
        if tag_filter:
            item_tags = item.get("tags", [])
            if not isinstance(item_tags, list):
                return False
            tag_lower = str(tag_filter).lower()
            if not any(
                isinstance(t, str) and t.lower() == tag_lower for t in item_tags
            ):
                return False

        # Author filter: check caption for author name
        author_filter = filter_params.get("author")
        if author_filter:
            caption = item.get("caption", "")
            if not isinstance(caption, str):
                return False
            if str(author_filter).lower() not in caption.lower():
                return False

        # Author ID filter: check author_id field or caption
        author_id_filter = filter_params.get("author_id")
        if author_id_filter is not None:
            item_author_id = item.get("author_id")
            if item_author_id is not None and int(item_author_id) != int(
                author_id_filter
            ):
                return False

        return True

    @staticmethod
    def cache_key(filter_params: dict[str, Any]) -> str:
        """Generate a cache key from filter parameters."""
        identity = {
            "tag": filter_params.get("tag"),
            "author": filter_params.get("author"),
            "author_id": filter_params.get("author_id"),
            "restrict": filter_params.get("restrict", "public"),
            "max_pages": filter_params.get("max_pages", 3),
        }
        return json.dumps(identity, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def parse_random_filter(
        filter_tokens: list[str], max_random_pages: int
    ) -> tuple[dict[str, Any], str]:
        """Parse random filter parameters from command tokens."""
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
            "count": "count",
            "random": "random",
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

        # Normalize common tag aliases (e.g. R18 -> R-18).
        if "tag" in params:
            tag_value = str(params["tag"]).strip()
            if tag_value.upper() == "R18":
                params["tag"] = "R-18"

        if "author_id" in params:
            try:
                params["author_id"] = int(str(params["author_id"]))
            except ValueError:
                params.pop("author_id", None)

        if "max_pages" in params:
            try:
                params["max_pages"] = max(
                    1,
                    min(max_random_pages, int(str(params["max_pages"]))),
                )
            except ValueError:
                params.pop("max_pages", None)

        if "restrict" in params:
            restrict = str(params["restrict"]).lower()
            params["restrict"] = "private" if restrict == "private" else "public"

        if "count" in params:
            count_raw = str(params["count"]).strip()
            if count_raw.lower() == "always":
                params["count"] = "always"
            else:
                try:
                    params["count"] = max(1, int(count_raw))
                except ValueError:
                    params.pop("count", None)

        if "random" in params:
            params["random"] = str(params["random"]).lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        summary_items: list[str] = []
        for key in ("tag", "author", "author_id", "restrict", "max_pages", "count"):
            if key in params:
                summary_items.append(f"{key}={params[key]}")
        if params.get("random") is True:
            summary_items.append("random=true")
        summary = ", ".join(summary_items) if summary_items else "无"
        return params, summary

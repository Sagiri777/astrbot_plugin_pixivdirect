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

    def pick_metadata_item(
        self,
        user_key: str,
        *,
        restrict: str = "public",
        filter_params: dict[str, Any] | None = None,
        exclude_sent: bool = False,
    ) -> dict[str, Any] | None:
        user_cache = self._config.bookmark_metadata_cache.get(user_key, {})
        restrict_cache = user_cache.get(str(restrict or "public").strip().lower(), {})
        if not isinstance(restrict_cache, dict):
            return None

        sent_ids = (
            self._config.get_sent_ids_for_user(user_key) if exclude_sent else set()
        )
        candidates: list[dict[str, Any]] = []
        for item in restrict_cache.values():
            if not isinstance(item, dict):
                continue
            illust_id = item.get("illust_id")
            if exclude_sent and isinstance(illust_id, int) and illust_id in sent_ids:
                continue
            if filter_params and not self._item_matches_filter(item, filter_params):
                continue
            candidates.append(item)
        if not candidates:
            return None
        if self._config.is_unique_enabled_for_user(user_key):
            return candidates[0]
        return random.choice(candidates)

    def count_matching_metadata_items(
        self,
        user_key: str,
        *,
        restrict: str = "public",
        filter_params: dict[str, Any] | None = None,
    ) -> int:
        user_cache = self._config.bookmark_metadata_cache.get(user_key, {})
        restrict_cache = user_cache.get(str(restrict or "public").strip().lower(), {})
        if not isinstance(restrict_cache, dict):
            return 0
        count = 0
        for item in restrict_cache.values():
            if not isinstance(item, dict):
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
        item_tags = item.get("tags", [])
        if not isinstance(item_tags, list):
            item_tags = []

        caption = item.get("caption", "")
        if not isinstance(caption, str):
            caption = ""
        if not caption:
            caption = str(item.get("author_name") or "")

        item_author_id = item.get("author_id")

        include_tags = CacheManager._as_str_list(filter_params.get("tags"))
        exclude_tags = CacheManager._as_str_list(filter_params.get("exclude_tags"))
        include_authors = CacheManager._as_str_list(filter_params.get("authors"))
        exclude_authors = CacheManager._as_str_list(
            filter_params.get("exclude_authors")
        )
        include_author_ids = CacheManager._as_int_list(filter_params.get("author_ids"))
        exclude_author_ids = CacheManager._as_int_list(
            filter_params.get("exclude_author_ids")
        )

        # Negative tag filter: item tags must NOT include excluded tag (case-insensitive)
        exclude_tag_filter = filter_params.get("exclude_tag")
        if exclude_tag_filter:
            exclude_tag_lower = str(exclude_tag_filter).lower()
            if any(
                isinstance(tag, str) and tag.lower() == exclude_tag_lower
                for tag in item_tags
            ):
                return False
        for exclude_tag in exclude_tags:
            exclude_tag_lower = exclude_tag.lower()
            if any(
                isinstance(tag, str) and tag.lower() == exclude_tag_lower
                for tag in item_tags
            ):
                return False

        # Negative author filter: caption must NOT include excluded author text
        exclude_author_filter = filter_params.get("exclude_author")
        if (
            exclude_author_filter
            and str(exclude_author_filter).lower() in caption.lower()
        ):
            return False
        for exclude_author in exclude_authors:
            if exclude_author.lower() in caption.lower():
                return False

        # Negative author ID filter: item author_id must NOT equal excluded author_id
        exclude_author_id_filter = filter_params.get("exclude_author_id")
        if exclude_author_id_filter is not None and item_author_id is not None:
            if int(item_author_id) == int(exclude_author_id_filter):
                return False
        if item_author_id is not None and int(item_author_id) in exclude_author_ids:
            return False

        # Tag filter: item tags must include the requested tag (case-insensitive)
        tag_filter = filter_params.get("tag")
        if tag_filter:
            tag_lower = str(tag_filter).lower()
            if not any(
                isinstance(t, str) and t.lower() == tag_lower for t in item_tags
            ):
                return False
        for include_tag in include_tags:
            include_tag_lower = include_tag.lower()
            if not any(
                isinstance(tag, str) and tag.lower() == include_tag_lower
                for tag in item_tags
            ):
                return False

        # Author filter: check caption for author name
        author_filter = filter_params.get("author")
        if author_filter:
            if str(author_filter).lower() not in caption.lower():
                return False
        for include_author in include_authors:
            if include_author.lower() not in caption.lower():
                return False

        # Author ID filter: check author_id field or caption
        author_id_filter = filter_params.get("author_id")
        if author_id_filter is not None:
            if item_author_id is not None and int(item_author_id) != int(
                author_id_filter
            ):
                return False
        if include_author_ids:
            if item_author_id is None or int(item_author_id) not in include_author_ids:
                return False

        return True

    @staticmethod
    def cache_key(filter_params: dict[str, Any]) -> str:
        """Generate a cache key from filter parameters."""
        identity = CacheManager.normalize_random_filter_params(filter_params)
        return json.dumps(identity, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def normalize_random_filter_params(filter_params: dict[str, Any]) -> dict[str, Any]:
        """Normalize random filter parameters for cache/stat identity."""
        identity = {
            "tag": filter_params.get("tag"),
            "tags": filter_params.get("tags"),
            "exclude_tag": filter_params.get("exclude_tag"),
            "exclude_tags": filter_params.get("exclude_tags"),
            "author": filter_params.get("author"),
            "authors": filter_params.get("authors"),
            "exclude_author": filter_params.get("exclude_author"),
            "exclude_authors": filter_params.get("exclude_authors"),
            "author_id": filter_params.get("author_id"),
            "author_ids": filter_params.get("author_ids"),
            "exclude_author_id": filter_params.get("exclude_author_id"),
            "exclude_author_ids": filter_params.get("exclude_author_ids"),
            "restrict": filter_params.get("restrict", "public"),
            "max_pages": filter_params.get("max_pages", 3),
        }
        if isinstance(identity.get("tags"), list):
            identity["tags"] = sorted(
                [str(value) for value in identity["tags"] if str(value).strip()]
            )
        if isinstance(identity.get("exclude_tags"), list):
            identity["exclude_tags"] = sorted(
                [str(value) for value in identity["exclude_tags"] if str(value).strip()]
            )
        if isinstance(identity.get("authors"), list):
            identity["authors"] = sorted(
                [str(value) for value in identity["authors"] if str(value).strip()]
            )
        if isinstance(identity.get("exclude_authors"), list):
            identity["exclude_authors"] = sorted(
                [
                    str(value)
                    for value in identity["exclude_authors"]
                    if str(value).strip()
                ]
            )
        if isinstance(identity.get("author_ids"), list):
            identity["author_ids"] = sorted(
                [int(value) for value in identity["author_ids"]]
            )
        if isinstance(identity.get("exclude_author_ids"), list):
            identity["exclude_author_ids"] = sorted(
                [int(value) for value in identity["exclude_author_ids"]]
            )
        return {
            key: value for key, value in identity.items() if value not in (None, "")
        }

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
            if key in {"tag", "author", "author_id"}:
                (
                    include_values,
                    exclude_values,
                ) = CacheManager._parse_filter_value_parts(value)
                CacheManager._merge_filter_values(
                    params, key, include_values, exclude_values
                )
                continue
            params[key] = value

        if loose_text and "tag" not in params:
            loose_tag = " ".join(loose_text).strip()
            if loose_tag:
                include_tags, exclude_tags = CacheManager._parse_filter_value_parts(
                    loose_tag
                )
                CacheManager._merge_filter_values(
                    params, "tag", include_tags, exclude_tags
                )

        # Normalize common tag aliases (e.g. R18 -> R-18).
        if "tag" in params:
            tag_value = str(params["tag"]).strip()
            if tag_value.upper() == "R18":
                params["tag"] = "R-18"
        if "tags" in params:
            params["tags"] = [
                "R-18" if str(tag).strip().upper() == "R18" else str(tag).strip()
                for tag in CacheManager._as_str_list(params.get("tags"))
            ]
        if "exclude_tag" in params:
            exclude_tag_value = str(params["exclude_tag"]).strip()
            if exclude_tag_value.upper() == "R18":
                params["exclude_tag"] = "R-18"
        if "exclude_tags" in params:
            params["exclude_tags"] = [
                "R-18" if str(tag).strip().upper() == "R18" else str(tag).strip()
                for tag in CacheManager._as_str_list(params.get("exclude_tags"))
            ]

        if "author_id" in params:
            try:
                params["author_id"] = int(str(params["author_id"]))
            except ValueError:
                params.pop("author_id", None)
        if "exclude_author_id" in params:
            try:
                params["exclude_author_id"] = int(str(params["exclude_author_id"]))
            except ValueError:
                params.pop("exclude_author_id", None)
        if "author_ids" in params:
            params["author_ids"] = CacheManager._as_int_list(params.get("author_ids"))
        if "exclude_author_ids" in params:
            params["exclude_author_ids"] = CacheManager._as_int_list(
                params.get("exclude_author_ids")
            )

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
        list_preferred_keys = {
            "tag": "tags",
            "exclude_tag": "exclude_tags",
            "author": "authors",
            "exclude_author": "exclude_authors",
            "author_id": "author_ids",
            "exclude_author_id": "exclude_author_ids",
        }
        for key in (
            "tag",
            "tags",
            "exclude_tag",
            "exclude_tags",
            "author",
            "authors",
            "exclude_author",
            "exclude_authors",
            "author_id",
            "author_ids",
            "exclude_author_id",
            "exclude_author_ids",
            "restrict",
            "max_pages",
            "count",
        ):
            preferred_list_key = list_preferred_keys.get(key)
            if preferred_list_key and preferred_list_key in params:
                continue
            if key in params:
                value = params[key]
                if key.startswith("exclude_"):
                    if isinstance(value, list):
                        summary_items.append(
                            f"{key[8:]}="
                            + "&".join(
                                f"!{v}" for v in CacheManager._as_str_list(value)
                            )
                        )
                    else:
                        summary_items.append(f"{key[8:]}=!{value}")
                elif isinstance(value, list):
                    summary_items.append(f"{key}=" + "&".join(str(v) for v in value))
                else:
                    summary_items.append(f"{key}={value}")
        if params.get("random") is True:
            summary_items.append("random=true")
        summary = ", ".join(summary_items) if summary_items else "无"
        return params, summary

    @staticmethod
    def _parse_filter_value_parts(value: str) -> tuple[list[str], list[str]]:
        include_values: list[str] = []
        exclude_values: list[str] = []
        for part in value.replace("＆", "&").split("&"):
            normalized_part = part.strip()
            if not normalized_part:
                continue
            if normalized_part.startswith(("!", "！")):
                normalized_negative = normalized_part[1:].strip()
                if normalized_negative:
                    exclude_values.append(normalized_negative)
                continue
            include_values.append(normalized_part)
        return include_values, exclude_values

    @staticmethod
    def _merge_filter_values(
        params: dict[str, Any],
        key: str,
        include_values: list[str],
        exclude_values: list[str],
    ) -> None:
        if include_values:
            params[key] = include_values[0]
            list_key = f"{key}s"
            merged_includes = CacheManager._as_str_list(params.get(list_key))
            merged_includes.extend(include_values)
            params[list_key] = CacheManager._deduplicate_str_list(merged_includes)
        if exclude_values:
            params[f"exclude_{key}"] = exclude_values[0]
            exclude_list_key = f"exclude_{key}s"
            merged_excludes = CacheManager._as_str_list(params.get(exclude_list_key))
            merged_excludes.extend(exclude_values)
            params[exclude_list_key] = CacheManager._deduplicate_str_list(
                merged_excludes
            )

    @staticmethod
    def _as_str_list(raw: Any) -> list[str]:
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, str):
            value = raw.strip()
            return [value] if value else []
        return []

    @staticmethod
    def _deduplicate_str_list(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(value)
        return result

    @staticmethod
    def _as_int_list(raw: Any) -> list[int]:
        if isinstance(raw, list):
            values = raw
        elif raw is None:
            values = []
        else:
            values = [raw]
        result: list[int] = []
        for value in values:
            try:
                result.append(int(str(value)))
            except ValueError:
                continue
        return sorted(set(result))

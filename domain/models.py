from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RequestContext:
    platform: str = ""
    user_id: str = ""
    group_id: str = ""
    command: str = ""
    trace_id: str = ""


@dataclass(slots=True)
class SearchOptions:
    keyword: str
    page: int = 1
    limit: int = 10
    sort: str = "date_desc"
    search_target: str = "partial_match_for_tags"
    duration: str | None = None
    include_translated_tag_results: bool = True


@dataclass(slots=True)
class RandomFilter:
    restrict: str = "public"
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    exclude_authors: list[str] = field(default_factory=list)
    author_ids: list[int] = field(default_factory=list)
    exclude_author_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class CacheItem:
    path: str
    caption: str = ""
    x_restrict: int = 0
    tags: list[str] = field(default_factory=list)
    illust_id: int | None = None
    author_id: int | str | None = None
    author_name: str = ""
    page_count: int = 1
    extra_image_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MetadataItem:
    illust_id: int
    title: str
    author_id: int | None
    author_name: str
    tags: list[str]
    x_restrict: int
    page_count: int
    image_urls: list[str]
    caption_seed: dict[str, Any] = field(default_factory=dict)
    bookmark_restrict: str = "public"
    cached_at: str = ""

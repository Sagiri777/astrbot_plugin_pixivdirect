from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PixivUser:
    id: int
    name: str
    account: str = ""


@dataclass(slots=True)
class PixivIllust:
    id: int
    title: str
    type: str
    user: PixivUser
    tags: list[str] = field(default_factory=list)
    page_count: int = 1
    total_view: int = 0
    total_bookmarks: int = 0
    x_restrict: int = 0
    create_date: str = ""
    image_urls: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchQuery:
    keyword: str
    page: int = 1
    sort: str | None = None
    search_target: str | None = None


@dataclass(slots=True)
class BookmarkRandomQuery:
    restrict: str = "public"
    tag: str | None = None
    pages: int = 3


@dataclass(slots=True)
class DownloadedIllust:
    illust_id: int
    page: int
    local_path: str
    source_url: str

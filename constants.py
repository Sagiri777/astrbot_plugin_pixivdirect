from __future__ import annotations

from pathlib import Path

PLUGIN_ID = "pixivdirect"

TOKEN_FILE = "user_refresh_tokens.json"
PREFERENCES_FILE = "preferences.json"
HOST_MAP_FILE = "pixiv_host_map.json"
CACHE_INDEX_FILE = "cache_index.json"

DEFAULT_ACCEPT_LANGUAGE = "zh-CN"
DEFAULT_IMAGE_QUALITY = "medium"
DEFAULT_BOOKMARK_RESTRICT = "public"
DEFAULT_RANDOM_SCAN_PAGES = 3
MAX_RANDOM_SCAN_PAGES = 8
DEFAULT_SEND_MULTI_LIMIT = 3

SUPPORTED_QUALITIES = {"small", "medium", "original"}
SUPPORTED_BOOKMARK_RESTRICT = {"public", "private"}

HELP_LINES = [
    "/pixiv help",
    "/pixiv login <refresh_token>",
    "/pixiv id i <illust_id>",
    "/pixiv id a <user_id>",
    "/pixiv search <keyword>",
    "/pixiv searchuser <keyword>",
    "/pixiv random [tag=标签] [restrict=public|private] [pages=1-8]",
    "/pixiv quality <small|medium|original>",
    "/pixiv dns",
]


def cache_file_name(illust_id: int, page: int, suffix: str) -> str:
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return f"illust_{illust_id}_p{page}{ext}"


def ensure_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)

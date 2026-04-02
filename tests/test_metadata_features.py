from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path


class _DummyLogger:
    def debug(self, *args, **kwargs) -> None:
        return None

    def info(self, *args, **kwargs) -> None:
        return None

    def warning(self, *args, **kwargs) -> None:
        return None


def _install_astrbot_stubs(root_dir: Path) -> None:
    astrbot_module = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))

    api_module = types.ModuleType("astrbot.api")
    api_module.logger = _DummyLogger()
    sys.modules["astrbot.api"] = api_module
    astrbot_module.api = api_module

    event_module = types.ModuleType("astrbot.api.event")

    class AstrMessageEvent:
        pass

    class _Filter:
        @staticmethod
        def command(_name: str):
            def decorator(func):
                return func

            return decorator

    event_module.AstrMessageEvent = AstrMessageEvent
    event_module.filter = _Filter
    sys.modules["astrbot.api.event"] = event_module

    star_module = types.ModuleType("astrbot.api.star")

    class Context:
        pass

    class Star:
        def __init__(self, context=None) -> None:
            self.context = context

    def register(*_args, **_kwargs):
        def decorator(obj):
            return obj

        return decorator

    star_module.Context = Context
    star_module.Star = Star
    star_module.register = register
    sys.modules["astrbot.api.star"] = star_module

    path_module = types.ModuleType("astrbot.core.utils.astrbot_path")
    path_module.get_astrbot_plugin_data_path = lambda: str(root_dir)
    sys.modules["astrbot.core.utils.astrbot_path"] = path_module


ROOT_DIR = Path(__file__).resolve().parents[1]
PARENT_DIR = ROOT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

_install_astrbot_stubs(ROOT_DIR)

pkg = "astrbot_plugin_pixivdirect"
ConfigManager = importlib.import_module(f"{pkg}.config_manager").ConfigManager
CacheManager = importlib.import_module(f"{pkg}.cache_manager").CacheManager
CommandHandler = importlib.import_module(f"{pkg}.commands").CommandHandler
ImageHandler = importlib.import_module(f"{pkg}.image_handler").ImageHandler
ImageHostHandler = importlib.import_module(f"{pkg}.image_host").ImageHostHandler


class _DummyEmojiHandler:
    async def add_emoji_reaction(self, *_args, **_kwargs) -> None:
        return None


def _build_handler(tmp_path: Path, pixiv_call_func) -> tuple[ConfigManager, CacheManager, CommandHandler]:
    config = ConfigManager(tmp_path / "data")
    config.ensure_directories()
    config.load_all()
    cache = CacheManager(config)
    handler = CommandHandler(
        config_manager=config,
        cache_manager=cache,
        image_handler=ImageHandler(cache_dir=config.cache_dir, pixiv_call_func=pixiv_call_func),
        image_host_handler=ImageHostHandler(),
        emoji_handler=_DummyEmojiHandler(),
        pixiv_call_func=pixiv_call_func,
        min_command_interval=2.0,
        max_random_pages=8,
        idle_cache_count=5,
        default_cache_size=10,
    )
    return config, cache, handler


def test_init_metadata_warmup_user_only_once(tmp_path: Path) -> None:
    config = ConfigManager(tmp_path / "data")
    config.ensure_directories()
    config.load_all()

    assert config.init_metadata_warmup_user("qq:1") is True
    first_state = dict(config.metadata_warmup_state["qq:1"])
    assert config.init_metadata_warmup_user("qq:1") is False
    assert config.metadata_warmup_state["qq:1"] == first_state
    assert config.get_random_source_mode_for_entity("user:qq:1") == "metadata"


def test_warmup_metadata_for_user_persists_entries(tmp_path: Path) -> None:
    async def fake_pixiv_call(action: str, params: dict[str, object], **kwargs):
        assert action == "bookmark_metadata_page"
        return {
            "ok": True,
            "refresh_token": "new-token",
            "data": {
                "items": [
                    {
                        "illust_id": 123,
                        "title": "demo",
                        "author_id": 456,
                        "author_name": "tester",
                        "tags": ["风景"],
                        "x_restrict": 0,
                        "page_count": 1,
                        "image_urls": ["https://example.com/1.jpg"],
                        "caption_seed": {
                            "total_view": 1,
                            "total_bookmarks": 2,
                            "create_date": "2024-01-01T00:00:00+00:00",
                        },
                        "bookmark_restrict": "public",
                        "cached_at": "2024-01-01T00:00:00+00:00",
                    }
                ],
                "next_url": "",
            },
        }

    config, _cache, handler = _build_handler(tmp_path, fake_pixiv_call)
    config.token_map["qq:1"] = "old-token"
    config.init_metadata_warmup_user("qq:1")

    latest_token, inserted = asyncio.run(
        handler.warmup_metadata_for_user(
            user_key="qq:1",
            refresh_token="old-token",
            page_batch=1,
            item_batch=10,
        )
    )

    assert latest_token == "new-token"
    assert inserted == 1
    assert config.bookmark_metadata_cache["qq:1"]["public"]["123"]["title"] == "demo"
    assert config.metadata_warmup_state["qq:1"]["completed"] is True


def test_pick_metadata_item_respects_filter_and_sent_ids(tmp_path: Path) -> None:
    config = ConfigManager(tmp_path / "data")
    config.ensure_directories()
    config.load_all()
    config.bookmark_metadata_cache["qq:1"] = {
        "public": {
            "1": {
                "illust_id": 1,
                "title": "a",
                "author_id": 11,
                "author_name": "Alice",
                "tags": ["猫"],
                "x_restrict": 0,
                "page_count": 1,
                "image_urls": ["https://example.com/a.jpg"],
                "caption_seed": {},
                "bookmark_restrict": "public",
                "cached_at": "2099-01-01T00:00:00",
            },
            "2": {
                "illust_id": 2,
                "title": "b",
                "author_id": 12,
                "author_name": "Bob",
                "tags": ["狗"],
                "x_restrict": 0,
                "page_count": 1,
                "image_urls": ["https://example.com/b.jpg"],
                "caption_seed": {},
                "bookmark_restrict": "public",
                "cached_at": "2099-01-01T00:00:00",
            },
        }
    }
    config.random_unique["qq:1"] = "true"
    config.sent_illust_ids["qq:1"] = {1}
    cache = CacheManager(config)

    item = cache.pick_metadata_item(
        "qq:1",
        restrict="public",
        filter_params={"tag": "狗", "restrict": "public"},
        exclude_sent=True,
    )
    assert item is not None
    assert item["illust_id"] == 2


def test_image_host_upload_success_and_failure(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "demo.jpg"
    image_path.write_bytes(b"demo")
    handler = ImageHostHandler()

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"data": {"url": "https://img.example/demo.jpg"}}

    monkeypatch.setattr(
        "astrbot_plugin_pixivdirect.image_host.requests.request",
        lambda *args, **kwargs: _Response(),
    )
    uploaded = asyncio.run(
        handler.upload_image(
            str(image_path),
            {
                "enabled": True,
                "endpoint": "https://img.example/upload",
                "method": "post",
                "file_field": "file",
                "headers": {},
                "form_fields": {},
                "success_path": "data.url",
                "timeout_seconds": 10,
            },
        )
    )
    assert uploaded == "https://img.example/demo.jpg"

    uploaded_none = asyncio.run(
        handler.upload_image(
            str(image_path),
            {
                "enabled": True,
                "endpoint": "https://img.example/upload",
                "method": "post",
                "file_field": "file",
                "headers": {},
                "form_fields": {},
                "success_path": "data.missing",
                "timeout_seconds": 10,
            },
        )
    )
    assert uploaded_none is None

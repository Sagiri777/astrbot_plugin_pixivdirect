from __future__ import annotations

import asyncio
import importlib
import io
import sys
import types
import zipfile
from pathlib import Path

from PIL import Image


class _DummyLogger:
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
        def __init__(self) -> None:
            self._platform = "qq"
            self._sender = "10001"

        def get_platform_name(self) -> str:
            return self._platform

        def get_sender_id(self) -> str:
            return self._sender

        def plain_result(self, message: str) -> dict[str, str]:
            return {"type": "text", "message": message}

        def make_result(self):
            class _Result:
                def __init__(self) -> None:
                    self.payload: dict[str, str] = {}

                def message(self, value: str):
                    self.payload["message"] = value
                    return self

                def file_image(self, value: str):
                    self.payload["image"] = value
                    return self.payload

            return _Result()

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

    star_module.Context = Context
    star_module.Star = Star
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
CommandHandler = importlib.import_module(f"{pkg}.commands").CommandHandler
CacheManager = importlib.import_module(f"{pkg}.cache_manager").CacheManager
ImageHandler = importlib.import_module(f"{pkg}.image_handler").ImageHandler
Facade = importlib.import_module(f"{pkg}.infrastructure.pixiv_client").PixivClientFacade
pick_illust_image_urls = importlib.import_module(
    f"{pkg}.infrastructure.pixiv_client"
).pick_illust_image_urls
AstrMessageEvent = importlib.import_module("astrbot.api.event").AstrMessageEvent


def _build_handler(tmp_path: Path, pixiv_call):
    config = ConfigManager(tmp_path / "data")
    config.ensure_directories()
    config.load_all()
    return config, CommandHandler(
        config_manager=config,
        cache_manager=CacheManager(config),
        image_handler=ImageHandler(config.cache_dir, pixiv_call),
        pixiv_call_func=pixiv_call,
    )


def test_config_manager_persists_token_and_quality(tmp_path: Path) -> None:
    config = ConfigManager(tmp_path / "data")
    config.ensure_directories()
    config.load_all()

    asyncio.run(config.set_user_token("qq:10001", "refresh-token"))
    asyncio.run(config.set_quality("qq:10001", "original"))

    reloaded = ConfigManager(tmp_path / "data")
    reloaded.ensure_directories()
    reloaded.load_all()

    assert reloaded.get_user_token("qq:10001") == "refresh-token"
    assert reloaded.get_quality("qq:10001") == "original"


def test_pick_illust_image_urls_prefers_meta_pages() -> None:
    urls = pick_illust_image_urls(
        {
            "meta_pages": [
                {
                    "image_urls": {
                        "square_medium": "square",
                        "medium": "medium",
                        "large": "large",
                        "original": "original",
                    }
                }
            ]
        },
        "original",
    )
    assert urls == ["original"]


def test_search_falls_back_to_web_search(tmp_path: Path) -> None:
    calls: list[str] = []

    async def fake_pixiv_call(action: str, params: dict, **kwargs):
        calls.append(action)
        if action == "search_illust":
            return {"ok": False, "status": 403, "error": {"message": "blocked"}}
        return {
            "ok": True,
            "status": 200,
            "data": {
                "illusts": [
                    {
                        "id": 1,
                        "title": "demo",
                        "user": {"name": "tester"},
                    }
                ]
            },
        }

    config, handler = _build_handler(tmp_path, fake_pixiv_call)
    asyncio.run(config.set_user_token("qq:10001", "refresh-token"))
    event = AstrMessageEvent()

    async def _run():
        return [
            item
            async for item in handler.handle_search(
                event,
                ["search", "landscape"],
                user_search=False,
            )
        ]

    results = asyncio.run(_run())

    assert calls == ["search_illust", "web_search_illust"]
    assert results[0]["type"] == "text"
    assert "demo" in results[0]["message"]


def test_facade_recommended_action_injects_pixez_params(monkeypatch) -> None:
    class _Response:
        status_code = 200
        ok = True
        text = ""

        def json(self):
            return {"illusts": []}

    captured: dict[str, object] = {}

    def fake_send(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("req_params")
        return _Response()

    monkeypatch.setattr(
        importlib.import_module(f"{pkg}.infrastructure.pixiv_client").PixivTransport,
        "send",
        fake_send,
    )

    facade = Facade()
    result = facade.call_action(
        "illust_recommended",
        {},
        access_token="token",
    )

    assert result["ok"] is True
    assert captured["params"] == {
        "filter": "for_ios",
        "include_ranking_label": "true",
    }


def test_ranking_command_calls_pixiv_ranking_action(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_pixiv_call(action: str, params: dict, **kwargs):
        calls.append((action, dict(params)))
        return {
            "ok": True,
            "status": 200,
            "data": {
                "illusts": [{"id": 10, "title": "ranked", "user": {"name": "author"}}]
            },
        }

    config, handler = _build_handler(tmp_path, fake_pixiv_call)
    asyncio.run(config.set_user_token("qq:10001", "refresh-token"))
    event = AstrMessageEvent()

    async def _run():
        return [item async for item in handler.handle_ranking(event, ["ranking"])]

    results = asyncio.run(_run())
    assert calls[0][0] == "illust_ranking"
    assert calls[0][1]["filter"] == "for_android"
    assert "排行榜" in results[0]["message"]


def test_recommended_and_related_commands_call_expected_actions(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_pixiv_call(action: str, params: dict, **kwargs):
        calls.append((action, dict(params)))
        return {
            "ok": True,
            "status": 200,
            "data": {
                "illusts": [{"id": 11, "title": "rec", "user": {"name": "author"}}]
            },
        }

    config, handler = _build_handler(tmp_path, fake_pixiv_call)
    asyncio.run(config.set_user_token("qq:10001", "refresh-token"))
    event = AstrMessageEvent()

    async def _run():
        collected = []
        collected.extend(
            [
                item
                async for item in handler.handle_recommended(
                    event,
                    ["recommended", "type=manga"],
                )
            ]
        )
        collected.extend(
            [item async for item in handler.handle_related(event, ["related", "123"])]
        )
        return collected

    results = asyncio.run(_run())
    assert calls[0][0] == "/v1/manga/recommended"
    assert calls[0][1]["filter"] == "for_ios"
    assert calls[1][0] == "illust_related"
    assert calls[1][1]["illust_id"] == 123
    assert any(
        "推荐" in item["message"] for item in results if item.get("type") == "text"
    )
    assert any(
        "相关推荐" in item["message"] for item in results if item.get("type") == "text"
    )


def test_ugoira_command_downloads_zip_and_renders_gif(tmp_path: Path) -> None:
    calls: list[str] = []

    frame_bytes = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(frame_bytes, format="PNG")
    png_payload = frame_bytes.getvalue()
    zip_payload = io.BytesIO()
    with zipfile.ZipFile(zip_payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("000000.png", png_payload)
        archive.writestr("000001.png", png_payload)
    zip_bytes = zip_payload.getvalue()

    async def fake_pixiv_call(action: str, params: dict, **kwargs):
        calls.append(action)
        if action == "ugoira_metadata":
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "ugoira_metadata": {
                        "zip_urls": {"medium": "https://example.com/ugoira.zip"},
                        "frames": [
                            {"file": "000000.png", "delay": 80},
                            {"file": "000001.png", "delay": 120},
                        ],
                    }
                },
            }
        if action == "ugoira_zip":
            return {
                "ok": True,
                "status": 200,
                "content": zip_bytes,
            }
        return {"ok": False, "status": 500, "error": {"message": "unexpected action"}}

    config, handler = _build_handler(tmp_path, fake_pixiv_call)
    asyncio.run(config.set_user_token("qq:10001", "refresh-token"))
    event = AstrMessageEvent()

    async def _run():
        return [item async for item in handler.handle_ugoira(event, ["ugoira", "123"])]

    results = asyncio.run(_run())
    assert calls == ["ugoira_metadata", "ugoira_zip"]
    assert any(
        "Ugoira 元数据" in item["message"]
        for item in results
        if item.get("type") == "text"
    )
    image_payloads = [item for item in results if "image" in item]
    assert len(image_payloads) == 1
    gif_path = Path(image_payloads[0]["image"])
    assert gif_path.exists()
    assert gif_path.suffix.lower() == ".gif"

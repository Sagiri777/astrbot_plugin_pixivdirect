from __future__ import annotations

import asyncio
import importlib
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


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

    class AstrMessageEvent:  # noqa: D401
        """Minimal stub for imports."""

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

    class Context:  # noqa: D401
        """Minimal stub for imports."""

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

main_module = importlib.import_module("astrbot_plugin_pixivdirect.main")
pixiv_sdk = importlib.import_module("astrbot_plugin_pixivdirect.pixivSDK")


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers: dict[str, str] = {}
        self.content = text.encode("utf-8")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON payload configured")
        return self._payload


class _FakeSession:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self._handler(**kwargs)


def test_search_budget_limits_runtime_candidates(monkeypatch) -> None:
    direct_ip_calls: list[str] = []
    current_dns_override: dict[str, str] = {}

    def handler(**kwargs):
        host = urlsplit(str(kwargs["url"])).hostname or ""
        if host == "app-api.pixiv.net":
            candidate = current_dns_override.get(host)
            if candidate in {"210.140.139.155", "1.1.1.1"}:
                direct_ip_calls.append(candidate)
                raise pixiv_sdk.RequestsTimeout("connect timeout")
            raise AssertionError(f"Unexpected DNS override for {host}: {candidate}")
        if host in {"210.140.139.155", "1.1.1.1"}:
            direct_ip_calls.append(host)
            raise pixiv_sdk.RequestsTimeout("connect timeout")
        raise AssertionError(f"Unexpected request host: {host}")

    @contextmanager
    def fake_dns_patch(host_map):
        current_dns_override.clear()
        current_dns_override.update(host_map)
        try:
            yield
        finally:
            current_dns_override.clear()

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_sdk, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_sdk, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_sdk, "_get_runtime_dns_cache", lambda _key: None)
    monkeypatch.setattr(pixiv_sdk, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(
        pixiv_sdk,
        "_resolve_host_ips",
        lambda *_args, **_kwargs: ["1.1.1.1", "2.2.2.2", "3.3.3.3"],
    )
    monkeypatch.setattr(
        pixiv_sdk, "_set_runtime_dns_cache", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        pixiv_sdk,
        "_rank_ips_by_latency",
        lambda ips, timeout: (list(ips), {ip: index for index, ip in enumerate(ips)}),
    )
    monkeypatch.setattr(pixiv_sdk, "_patched_dns_resolution", fake_dns_patch)

    result = pixiv_sdk.pixiv(
        "search_illust",
        {"word": "TwiAtri"},
        access_token="token",
        refresh_token="refresh",
        bypass_sni=True,
        bypass_mode="pixez",
        runtime_dns_resolve=True,
        search_runtime_ip_candidate_limit=2,
        search_retryable_failure_budget=2,
    )

    assert result["ok"] is False
    assert result["status"] == 504
    assert direct_ip_calls == ["210.140.139.155", "1.1.1.1"]


def test_non_search_requests_ignore_search_budget(monkeypatch) -> None:
    direct_ip_calls: list[str] = []
    current_dns_override: dict[str, str] = {}

    def handler(**kwargs):
        host = urlsplit(str(kwargs["url"])).hostname or ""
        if host == "app-api.pixiv.net":
            candidate = current_dns_override.get(host)
            if candidate in {"210.140.139.155", "1.1.1.1"}:
                direct_ip_calls.append(candidate)
                raise pixiv_sdk.RequestsTimeout("connect timeout")
            if candidate == "2.2.2.2":
                direct_ip_calls.append(candidate)
                return _FakeResponse(200, {"illust": {"id": 123}})
            raise AssertionError(f"Unexpected DNS override for {host}: {candidate}")
        if host in {"210.140.139.155", "1.1.1.1"}:
            direct_ip_calls.append(host)
            raise pixiv_sdk.RequestsTimeout("connect timeout")
        if host == "2.2.2.2":
            direct_ip_calls.append(host)
            return _FakeResponse(200, {"illust": {"id": 123}})
        raise AssertionError(f"Unexpected request host: {host}")

    @contextmanager
    def fake_dns_patch(host_map):
        current_dns_override.clear()
        current_dns_override.update(host_map)
        try:
            yield
        finally:
            current_dns_override.clear()

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_sdk, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_sdk, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_sdk, "_get_runtime_dns_cache", lambda _key: None)
    monkeypatch.setattr(pixiv_sdk, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(
        pixiv_sdk,
        "_resolve_host_ips",
        lambda *_args, **_kwargs: ["1.1.1.1", "2.2.2.2"],
    )
    monkeypatch.setattr(
        pixiv_sdk, "_set_runtime_dns_cache", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        pixiv_sdk,
        "_rank_ips_by_latency",
        lambda ips, timeout: (list(ips), {ip: index for index, ip in enumerate(ips)}),
    )
    monkeypatch.setattr(pixiv_sdk, "_patched_dns_resolution", fake_dns_patch)

    result = pixiv_sdk.pixiv(
        "illust_detail",
        {"illust_id": 123},
        access_token="token",
        refresh_token="refresh",
        bypass_sni=True,
        bypass_mode="pixez",
        runtime_dns_resolve=True,
        search_runtime_ip_candidate_limit=1,
        search_retryable_failure_budget=1,
    )

    assert result["ok"] is True
    assert result["status"] == 200
    assert direct_ip_calls == ["210.140.139.155", "1.1.1.1", "2.2.2.2"]


def test_app_api_pixez_mode_keeps_domain_url_and_sni(monkeypatch) -> None:
    recorded_dns_overrides: list[dict[str, str]] = []
    request_hosts: list[str] = []

    def handler(**kwargs):
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        return _FakeResponse(200, {"illust": {"id": 123}})

    @contextmanager
    def fake_dns_patch(host_map):
        recorded_dns_overrides.append(dict(host_map))
        yield

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_sdk, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_sdk, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_sdk, "_get_runtime_dns_cache", lambda _key: None)
    monkeypatch.setattr(pixiv_sdk, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(
        pixiv_sdk,
        "_resolve_host_ips",
        lambda *_args, **_kwargs: ["1.1.1.1"],
    )
    monkeypatch.setattr(
        pixiv_sdk, "_set_runtime_dns_cache", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        pixiv_sdk,
        "_rank_ips_by_latency",
        lambda ips, timeout: (list(ips), {ip: index for index, ip in enumerate(ips)}),
    )
    monkeypatch.setattr(pixiv_sdk, "_patched_dns_resolution", fake_dns_patch)

    result = pixiv_sdk.pixiv(
        "illust_detail",
        {"illust_id": 123},
        access_token="token",
        refresh_token="refresh",
        bypass_sni=True,
        bypass_mode="pixez",
        runtime_dns_resolve=True,
    )

    assert result["ok"] is True
    assert request_hosts == ["app-api.pixiv.net"]
    assert recorded_dns_overrides == [{"app-api.pixiv.net": "210.140.139.155"}]


def test_image_pixez_mode_still_uses_direct_ip_without_sni(monkeypatch) -> None:
    request_hosts: list[str] = []

    def handler(**kwargs):
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        return _FakeResponse(200, text="image-bytes")

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_sdk, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_sdk, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_sdk, "get_environ_proxies", lambda _url: {})

    result = pixiv_sdk.pixiv(
        "image",
        {"url": "https://i.pximg.net/img-original/img/2026/04/05/00/00/00/123_p0.jpg"},
        bypass_sni=True,
        bypass_mode="pixez",
        runtime_dns_resolve=False,
    )

    assert result["ok"] is True
    assert request_hosts == ["210.140.139.133"]


def test_web_search_does_not_require_refresh_token(monkeypatch) -> None:
    captured_headers: dict[str, object] = {}

    def handler(**kwargs):
        captured_headers.update(kwargs.get("headers") or {})
        return _FakeResponse(
            200,
            {
                "error": False,
                "body": {
                    "illustManga": {
                        "data": [],
                        "total": 0,
                    }
                },
            },
        )

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_sdk, "_get_session", lambda: session)

    result = pixiv_sdk.pixiv(
        "web_search_illust",
        {"word": "TwiAtri"},
        refresh_token=None,
        access_token=None,
        bypass_sni=False,
    )

    assert result["ok"] is True
    assert result["status"] == 200
    assert captured_headers["X-Requested-With"] == "XMLHttpRequest"
    assert "Mozilla/5.0" in str(captured_headers["User-Agent"])


def test_image_request_does_not_require_refresh_token(monkeypatch) -> None:
    captured_headers: dict[str, object] = {}

    def handler(**kwargs):
        captured_headers.update(kwargs.get("headers") or {})
        return _FakeResponse(200, payload=None, text="ok")

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_sdk, "_get_session", lambda: session)

    result = pixiv_sdk.pixiv(
        "image",
        {"url": "https://i.pximg.net/img-original/img/test.jpg"},
        refresh_token=None,
        access_token=None,
        bypass_sni=False,
    )

    assert result["ok"] is True
    assert result["status"] == 200
    assert captured_headers["Referer"] == "https://app-api.pixiv.net/"
    assert captured_headers["User-Agent"] == pixiv_sdk.IMAGE_UA


def test_search_request_chain_falls_back_to_web() -> None:
    class _DummyRunner:
        def __init__(self) -> None:
            self.invocations: list[tuple[str, dict[str, object]]] = []
            self.refresh_reasons: list[str] = []
            self.mark_dns_refreshed_calls = 0
            self._responses = [
                {"ok": False, "status": 403},
                {"ok": False, "status": 403},
                {"ok": True, "status": 200, "action": "web_search_illust", "data": {}},
            ]

        def _effective_bypass_mode(self) -> str:
            return "auto"

        def _build_search_call_kwargs(self, **kwargs):
            return dict(kwargs)

        async def _invoke_pixiv(self, action: str, params: dict[str, object], **kwargs):
            self.invocations.append((action, dict(kwargs)))
            return self._responses.pop(0)

        async def _refresh_dns_cache(self, *, reason: str) -> bool:
            self.refresh_reasons.append(reason)
            return True

        async def _mark_dns_refreshed(self) -> None:
            self.mark_dns_refreshed_calls += 1

    runner = _DummyRunner()
    runner._is_search_retryable_result = (
        main_module.PixivDirectPlugin._is_search_retryable_result
    )

    result = asyncio.run(
        main_module.PixivDirectPlugin._run_search_request_chain(
            runner,
            "search_illust",
            {"word": "TwiAtri"},
        )
    )

    assert result["ok"] is True
    assert result["fallback_chain"] == ["app_api", "web"]
    assert [action for action, _kwargs in runner.invocations] == [
        "search_illust",
        "search_illust",
        "web_search_illust",
    ]
    assert runner.refresh_reasons == ["retry:search_illust"]
    assert runner.mark_dns_refreshed_calls == 1


def test_search_with_recovery_escalates_to_proxy_after_web_failure() -> None:
    class _DummyConfig:
        def __init__(self) -> None:
            self.search_proxy_state = {"proxy_until": None}
            self.recorded_reason: str | None = None

        def get_search_proxy_url(self) -> str | None:
            return "http://127.0.0.1:7890"

        def is_search_proxy_configured(self) -> bool:
            return True

        def is_search_proxy_active(self) -> bool:
            return False

        async def record_search_proxy_rescue(self, *, reason: str) -> None:
            self.recorded_reason = reason

    class _DummyRunner:
        def __init__(self) -> None:
            self._config_manager = _DummyConfig()
            self.calls: list[str | None] = []

        async def _run_search_request_chain(
            self,
            action: str,
            params: dict[str, object],
            *,
            proxy: str | None = None,
            **kwargs,
        ):
            self.calls.append(proxy)
            if proxy is None:
                return {
                    "ok": False,
                    "status": 403,
                    "fallback_chain": ["app_api", "web"],
                }
            return {"ok": True, "status": 200, "data": {}, "fallback_chain": []}

    runner = _DummyRunner()

    result = asyncio.run(
        main_module.PixivDirectPlugin._run_search_with_recovery(
            runner,
            "search_illust",
            {"word": "TwiAtri"},
        )
    )

    assert result["ok"] is True
    assert result["proxy_used"] is True
    assert result["fallback_chain"] == ["app_api", "web", "proxy"]
    assert runner.calls == [None, "http://127.0.0.1:7890"]
    assert runner._config_manager.recorded_reason == "search_illust:403"

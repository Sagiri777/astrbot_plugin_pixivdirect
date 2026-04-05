from __future__ import annotations

import asyncio
import importlib
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from requests.exceptions import Timeout as RequestsTimeout


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
pixiv_client = importlib.import_module(
    "astrbot_plugin_pixivdirect.infrastructure.pixiv_client"
)
config_module = importlib.import_module("astrbot_plugin_pixivdirect.config_manager")


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


def test_legacy_bypass_modes_normalize_to_pixez(tmp_path) -> None:
    manager = config_module.ConfigManager(tmp_path)

    assert manager._normalize_bypass_mode("auto") == "pixez"
    assert manager._normalize_bypass_mode("accesser") == "pixez"
    assert manager._normalize_bypass_mode("pixez") == "pixez"


def test_app_api_pixez_mode_keeps_domain_url_and_disables_sni(monkeypatch) -> None:
    recorded_dns_overrides: list[dict[str, str]] = []
    request_hosts: list[str] = []
    sni_disabled: list[bool] = []

    def handler(**kwargs):
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        return _FakeResponse(200, {"illust": {"id": 123}})

    @contextmanager
    def fake_dns_patch(host_map):
        recorded_dns_overrides.append(dict(host_map))
        yield

    @contextmanager
    def fake_without_tls_sni():
        sni_disabled.append(True)
        yield

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_client, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_client, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(pixiv_client, "_patched_dns_resolution", fake_dns_patch)
    monkeypatch.setattr(pixiv_client, "_without_tls_sni", fake_without_tls_sni)

    result = pixiv_client.PixivClientFacade().call_action(
        "illust_detail",
        {"illust_id": 123},
        access_token="token",
        refresh_token="refresh",
        bypass_sni=True,
        runtime_dns_resolve=True,
    )

    assert result["ok"] is True
    assert request_hosts == ["app-api.pixiv.net"]
    assert recorded_dns_overrides == [{"app-api.pixiv.net": "210.140.139.155"}]
    assert sni_disabled == [True]


def test_oauth_pixez_mode_uses_domain_url_dns_override_and_disables_sni(
    monkeypatch,
) -> None:
    request_hosts: list[str] = []
    recorded_dns_overrides: list[dict[str, str]] = []
    sni_disabled: list[bool] = []

    def handler(**kwargs):
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        if request_hosts[-1] == "oauth.secure.pixiv.net":
            return _FakeResponse(
                200,
                {
                    "access_token": "token",
                    "refresh_token": "refresh-new",
                    "user": {"id": 1},
                },
            )
        return _FakeResponse(200, {"illust": {"id": 123}})

    @contextmanager
    def fake_dns_patch(host_map):
        recorded_dns_overrides.append(dict(host_map))
        yield

    @contextmanager
    def fake_without_tls_sni():
        sni_disabled.append(True)
        yield

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_client, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_client, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(pixiv_client, "_patched_dns_resolution", fake_dns_patch)
    monkeypatch.setattr(pixiv_client, "_without_tls_sni", fake_without_tls_sni)

    result = pixiv_client.PixivClientFacade().call_action(
        "illust_detail",
        {"illust_id": 123},
        refresh_token="refresh",
        access_token=None,
        bypass_sni=True,
        runtime_dns_resolve=False,
    )

    assert result["ok"] is True
    assert request_hosts == ["oauth.secure.pixiv.net", "app-api.pixiv.net"]
    assert recorded_dns_overrides == [
        {"oauth.secure.pixiv.net": "210.140.139.155"},
        {"app-api.pixiv.net": "210.140.139.155"},
    ]
    assert sni_disabled == [True, True]


def test_oauth_timeout_refreshes_host_map_before_retry(monkeypatch) -> None:
    request_hosts: list[str] = []
    recorded_dns_overrides: list[dict[str, str]] = []
    sni_disabled: list[bool] = []
    oauth_attempts = 0
    saved_host_maps: list[dict[str, str]] = []

    def handler(**kwargs):
        nonlocal oauth_attempts
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        if request_hosts[-1] == "oauth.secure.pixiv.net":
            oauth_attempts += 1
        if oauth_attempts == 1:
            raise RequestsTimeout("Connection to oauth.secure.pixiv.net timed out.")
        if request_hosts[-1] == "oauth.secure.pixiv.net":
            return _FakeResponse(
                200,
                {
                    "access_token": "token",
                    "refresh_token": "refresh-new",
                    "user": {"id": 1},
                },
            )
        return _FakeResponse(200, {"illust": {"id": 123}})

    @contextmanager
    def fake_dns_patch(host_map):
        recorded_dns_overrides.append(dict(host_map))
        yield

    @contextmanager
    def fake_without_tls_sni():
        sni_disabled.append(True)
        yield

    def fake_refresh_pixez_hosts_via_dns(
        *,
        base_map: dict[str, str],
        doh_server: str,
        timeout: int,
        session=None,
        proxies=None,
    ) -> dict[str, str]:
        del doh_server, timeout, session, proxies
        refreshed = dict(base_map)
        refreshed["oauth.secure.pixiv.net"] = "210.140.139.200"
        return refreshed

    def fake_save_host_map_file(_path: str, host_map: dict[str, str]) -> None:
        saved_host_maps.append(dict(host_map))

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_client, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_client, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(pixiv_client, "_patched_dns_resolution", fake_dns_patch)
    monkeypatch.setattr(pixiv_client, "_without_tls_sni", fake_without_tls_sni)
    monkeypatch.setattr(
        pixiv_client, "_refresh_pixez_hosts_via_dns", fake_refresh_pixez_hosts_via_dns
    )
    monkeypatch.setattr(pixiv_client, "_save_host_map_file", fake_save_host_map_file)

    result = pixiv_client.PixivClientFacade().call_action(
        "illust_detail",
        {"illust_id": 123},
        refresh_token="refresh",
        access_token=None,
        bypass_sni=True,
        runtime_dns_resolve=False,
    )

    assert result["ok"] is True
    assert request_hosts == [
        "oauth.secure.pixiv.net",
        "oauth.secure.pixiv.net",
        "app-api.pixiv.net",
    ]
    assert recorded_dns_overrides == [
        {"oauth.secure.pixiv.net": "210.140.139.155"},
        {"oauth.secure.pixiv.net": "210.140.139.200"},
        {"app-api.pixiv.net": "210.140.139.155"},
    ]
    assert sni_disabled == [True, True, True]
    assert saved_host_maps == [
        {
            "app-api.pixiv.net": "210.140.139.155",
            "oauth.secure.pixiv.net": "210.140.139.200",
            "i.pximg.net": "210.140.139.133",
            "s.pximg.net": "210.140.139.133",
        }
    ]


def test_auth_refresh_forwards_transport_network_kwargs(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class _FakeTransport:
        def send(self, method: str, url: str, **kwargs):
            captured_kwargs.update(kwargs)
            return _FakeResponse(
                200,
                {
                    "access_token": "token",
                    "refresh_token": "refresh-new",
                    "user": {"id": 1},
                },
            )

    auth_client = pixiv_client.PixivAuthClient(_FakeTransport())

    result = auth_client.refresh_access_token(
        refresh_token="refresh",
        proxy="http://127.0.0.1:7890",
        dns_cache_file="/tmp/pixiv_host_map.json",
        bypass_sni=False,
        timeout=45,
        connect_timeout=5.5,
        dns_timeout=4,
        dns_update_hosts=True,
        dns_server="1.1.1.1",
        runtime_dns_resolve=True,
        max_retries=1,
        connect_probe_timeout=1.5,
    )

    assert result["ok"] is True
    assert captured_kwargs["proxy"] == "http://127.0.0.1:7890"
    assert captured_kwargs["dns_cache_file"] == "/tmp/pixiv_host_map.json"
    assert captured_kwargs["bypass_sni"] is False
    assert captured_kwargs["timeout"] == 45
    assert captured_kwargs["connect_timeout"] == 5.5
    assert captured_kwargs["dns_timeout"] == 4
    assert captured_kwargs["dns_update_hosts"] is True
    assert captured_kwargs["dns_server"] == "1.1.1.1"
    assert captured_kwargs["runtime_dns_resolve"] is True
    assert captured_kwargs["max_retries"] == 1
    assert captured_kwargs["connect_probe_timeout"] == 1.5


def test_build_pixiv_call_kwargs_does_not_include_bypass_mode(tmp_path) -> None:
    class _DummyConfigManager:
        def __init__(self, root: Path) -> None:
            self.host_map_file = root / "pixiv_host_map.json"

        def get_effective_bypass_mode(self) -> str:
            return "pixez"

    class _DummyPlugin:
        def __init__(self, root: Path) -> None:
            self._config_manager = _DummyConfigManager(root)

        def _effective_bypass_mode(self) -> str:
            return self._config_manager.get_effective_bypass_mode()

    plugin = _DummyPlugin(tmp_path)

    call_kwargs = main_module.PixivDirectPlugin._build_pixiv_call_kwargs(plugin)

    assert "bypass_mode" not in call_kwargs
    assert call_kwargs["bypass_sni"] is True


def test_image_pixez_mode_uses_domain_url_dns_override_and_disables_sni(
    monkeypatch,
) -> None:
    request_hosts: list[str] = []
    recorded_dns_overrides: list[dict[str, str]] = []
    sni_disabled: list[bool] = []

    def handler(**kwargs):
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        return _FakeResponse(200, text="image-bytes")

    @contextmanager
    def fake_dns_patch(host_map):
        recorded_dns_overrides.append(dict(host_map))
        yield

    @contextmanager
    def fake_without_tls_sni():
        sni_disabled.append(True)
        yield

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_client, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_client, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(pixiv_client, "_patched_dns_resolution", fake_dns_patch)
    monkeypatch.setattr(pixiv_client, "_without_tls_sni", fake_without_tls_sni)

    result = pixiv_client.PixivClientFacade().call_action(
        "image",
        {"url": "https://i.pximg.net/img-original/img/2026/04/05/00/00/00/123_p0.jpg"},
        bypass_sni=True,
        runtime_dns_resolve=False,
    )

    assert result["ok"] is True
    assert request_hosts == ["i.pximg.net"]
    assert recorded_dns_overrides == [{"i.pximg.net": "210.140.139.133"}]
    assert sni_disabled == [True]


def test_disable_bypass_sni_returns_to_plain_domain_request(monkeypatch) -> None:
    request_hosts: list[str] = []
    recorded_dns_overrides: list[dict[str, str]] = []

    def handler(**kwargs):
        request_hosts.append(urlsplit(str(kwargs["url"])).hostname or "")
        return _FakeResponse(200, {"illust": {"id": 123}})

    @contextmanager
    def fake_dns_patch(host_map):
        recorded_dns_overrides.append(dict(host_map))
        yield

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_client, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_client, "get_environ_proxies", lambda _url: {})
    monkeypatch.setattr(pixiv_client, "_patched_dns_resolution", fake_dns_patch)

    result = pixiv_client.PixivClientFacade().call_action(
        "illust_detail",
        {"illust_id": 123},
        access_token="token",
        refresh_token="refresh",
        bypass_sni=False,
    )

    assert result["ok"] is True
    assert request_hosts == ["app-api.pixiv.net"]


def test_illust_recommended_request_matches_pixez_query_shape(monkeypatch) -> None:
    captured_calls: list[dict[str, object]] = []

    def handler(**kwargs):
        captured_calls.append(kwargs)
        return _FakeResponse(200, {"illusts": []})

    session = _FakeSession(handler)
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)
    monkeypatch.setattr(pixiv_client, "_load_host_map_file", lambda _path: {})
    monkeypatch.setattr(pixiv_client, "get_environ_proxies", lambda _url: {})

    result = pixiv_client.PixivClientFacade().call_action(
        "illust_recommended",
        {},
        access_token="token",
        refresh_token="refresh",
        bypass_sni=False,
    )

    assert result["ok"] is True
    assert len(captured_calls) == 1
    request_kwargs = captured_calls[0]
    assert request_kwargs["method"] == "GET"
    assert request_kwargs["url"] == "https://app-api.pixiv.net/v1/illust/recommended"
    assert request_kwargs["params"] == {
        "filter": "for_ios",
        "include_ranking_label": "true",
    }


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
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)

    result = pixiv_client.PixivClientFacade().call_action(
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
    monkeypatch.setattr(pixiv_client, "_get_session", lambda: session)

    result = pixiv_client.PixivClientFacade().call_action(
        "image",
        {"url": "https://i.pximg.net/img-original/img/test.jpg"},
        refresh_token=None,
        access_token=None,
        bypass_sni=False,
    )

    assert result["ok"] is True
    assert result["status"] == 200
    assert captured_headers["Referer"] == "https://app-api.pixiv.net/"
    assert captured_headers["User-Agent"] == pixiv_client.IMAGE_UA


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

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_sdk_module():
    logger = logging.getLogger("bypass_mode_test")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
        logger.addHandler(handler)

    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")
    astrbot_api_module.logger = logger
    astrbot_module.api = astrbot_api_module
    sys.modules.setdefault("astrbot", astrbot_module)
    sys.modules["astrbot.api"] = astrbot_api_module

    sdk_path = Path(__file__).resolve().parents[1] / "pixivSDK.py"
    spec = importlib.util.spec_from_file_location("bypass_mode_pixivSDK", sdk_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load pixivSDK from {sdk_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SDK = _load_sdk_module()
pixiv = SDK.pixiv
pick_image_url = SDK._pick_illust_image_url


@dataclass(slots=True)
class ModeConfig:
    name: str
    bypass_mode: str
    bypass_sni: bool


@dataclass(slots=True)
class CheckResult:
    mode: str
    check: str
    ok: bool
    status: int | str
    elapsed_ms: int
    detail: str


class RequestThrottler:
    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._last_request_monotonic: float | None = None

    def wait(self) -> None:
        if self._last_request_monotonic is None:
            self._last_request_monotonic = time.monotonic()
            return

        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self._cooldown_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_monotonic = time.monotonic()


DEFAULT_MODES: tuple[ModeConfig, ...] = (
    ModeConfig("auto", "auto", True),
    ModeConfig("pixez", "pixez", True),
    ModeConfig("accesser", "accesser", True),
    ModeConfig("direct", "auto", False),
)


def _load_refresh_token(explicit: str | None) -> str:
    if explicit:
        return explicit

    env_token = os.environ.get("PIXIV_REFRESH_TOKEN", "").strip()
    if env_token:
        return env_token

    helper_path = Path(__file__).with_name("getForToken.py")
    helper_spec = importlib.util.spec_from_file_location(
        "pixivdirect_get_token", helper_path
    )
    if helper_spec is None or helper_spec.loader is None:
        raise RuntimeError("Unable to load scripts/getForToken.py")
    helper_module = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper_module)
    raw_token = getattr(helper_module, "token", b"")
    if isinstance(raw_token, bytes):
        token = raw_token.decode().strip()
    else:
        token = str(raw_token).strip()
    if not token:
        raise RuntimeError("scripts/getForToken.py returned an empty token")
    return token


def _resolve_mode(name: str) -> ModeConfig:
    for mode in DEFAULT_MODES:
        if mode.name == name:
            return mode
    raise ValueError(f"Unknown mode: {name}")


def _run_call(
    mode: ModeConfig,
    action: str,
    params: dict[str, Any],
    *,
    refresh_token: str,
    dns_cache_file: Path,
    runtime_dns_resolve: bool,
    throttler: RequestThrottler,
    access_token: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    call_kwargs = {
        "refresh_token": refresh_token,
        "access_token": access_token,
        "dns_cache_file": str(dns_cache_file),
        "dns_update_hosts": False,
        "runtime_dns_resolve": runtime_dns_resolve and mode.bypass_sni,
        "max_retries": 2,
        "bypass_mode": mode.bypass_mode,
        "bypass_sni": mode.bypass_sni,
    }
    if extra:
        call_kwargs.update(extra)

    throttler.wait()
    started = time.perf_counter()
    result = pixiv(action, params, **call_kwargs)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result, elapsed_ms


def _format_status(result: dict[str, Any]) -> int | str:
    status = result.get("status")
    return status if isinstance(status, int) else str(status or "-")


def _collect_search_check(
    mode: ModeConfig,
    *,
    refresh_token: str,
    dns_cache_file: Path,
    keyword: str,
    runtime_dns_resolve: bool,
    throttler: RequestThrottler,
) -> CheckResult:
    result, elapsed_ms = _run_call(
        mode,
        "search_illust",
        {
            "word": keyword,
            "search_target": "partial_match_for_tags",
            "sort": "date_desc",
            "include_translated_tag_results": True,
        },
        refresh_token=refresh_token,
        dns_cache_file=dns_cache_file,
        runtime_dns_resolve=runtime_dns_resolve,
        throttler=throttler,
        extra={
            "connect_timeout": 5.0,
            "search_runtime_ip_candidate_limit": 2,
            "search_retryable_failure_budget": 2,
        },
    )
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    illusts = data.get("illusts") if isinstance(data.get("illusts"), list) else []
    detail = f"illusts={len(illusts)}"
    return CheckResult(
        mode=mode.name,
        check="search_illust",
        ok=bool(result.get("ok")),
        status=_format_status(result),
        elapsed_ms=elapsed_ms,
        detail=detail,
    )


def _collect_detail_and_image_checks(
    mode: ModeConfig,
    *,
    refresh_token: str,
    dns_cache_file: Path,
    illust_id: int | None,
    runtime_dns_resolve: bool,
    throttler: RequestThrottler,
) -> list[CheckResult]:
    ranking_result, ranking_elapsed_ms = _run_call(
        mode,
        "illust_ranking",
        {"mode": "day"},
        refresh_token=refresh_token,
        dns_cache_file=dns_cache_file,
        runtime_dns_resolve=runtime_dns_resolve,
        throttler=throttler,
    )
    ranking_data = (
        ranking_result.get("data")
        if isinstance(ranking_result.get("data"), dict)
        else {}
    )
    ranking_illusts = (
        ranking_data.get("illusts")
        if isinstance(ranking_data.get("illusts"), list)
        else []
    )
    resolved_illust_id = illust_id
    if resolved_illust_id is None:
        first = ranking_illusts[0] if ranking_illusts else {}
        if isinstance(first, dict):
            value = first.get("id")
            if isinstance(value, int):
                resolved_illust_id = value

    results = [
        CheckResult(
            mode=mode.name,
            check="illust_ranking",
            ok=bool(ranking_result.get("ok")),
            status=_format_status(ranking_result),
            elapsed_ms=ranking_elapsed_ms,
            detail=f"illust_id={resolved_illust_id or '-'}",
        )
    ]
    if not ranking_result.get("ok") or resolved_illust_id is None:
        return results

    detail_result, detail_elapsed_ms = _run_call(
        mode,
        "illust_detail",
        {"illust_id": resolved_illust_id},
        refresh_token=refresh_token,
        dns_cache_file=dns_cache_file,
        runtime_dns_resolve=runtime_dns_resolve,
        throttler=throttler,
    )
    detail_data = (
        detail_result.get("data") if isinstance(detail_result.get("data"), dict) else {}
    )
    illust = (
        detail_data.get("illust") if isinstance(detail_data.get("illust"), dict) else {}
    )
    image_url = pick_image_url(illust, "medium") if illust else None
    results.append(
        CheckResult(
            mode=mode.name,
            check="illust_detail",
            ok=bool(detail_result.get("ok")),
            status=_format_status(detail_result),
            elapsed_ms=detail_elapsed_ms,
            detail=f"image_url={'yes' if image_url else 'no'}",
        )
    )
    if not detail_result.get("ok") or not image_url:
        return results

    image_result, image_elapsed_ms = _run_call(
        mode,
        "image",
        {"url": image_url},
        refresh_token=str(detail_result.get("refresh_token") or refresh_token),
        access_token=(
            str(detail_result.get("access_token"))
            if detail_result.get("access_token")
            else None
        ),
        dns_cache_file=dns_cache_file,
        runtime_dns_resolve=runtime_dns_resolve,
        throttler=throttler,
    )
    content_type = str(image_result.get("content_type") or "-")
    results.append(
        CheckResult(
            mode=mode.name,
            check="image",
            ok=bool(image_result.get("ok")),
            status=_format_status(image_result),
            elapsed_ms=image_elapsed_ms,
            detail=content_type,
        )
    )
    return results


def _print_results(results: list[CheckResult]) -> None:
    print("mode       check           ok     status   elapsed_ms   detail")
    print(
        "---------  --------------  -----  -------  -----------  ------------------------------"
    )
    for item in results:
        print(
            f"{item.mode:<9}  {item.check:<14}  "
            f"{str(item.ok):<5}  {str(item.status):<7}  "
            f"{item.elapsed_ms:<11}  {item.detail}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Pixiv request behavior under different bypass modes."
    )
    parser.add_argument(
        "--refresh-token",
        dest="refresh_token",
        default="",
        help="Pixiv refresh token. Defaults to PIXIV_REFRESH_TOKEN or scripts/getForToken.py.",
    )
    parser.add_argument(
        "--keyword",
        default="TwiAtri",
        help="Keyword used for search_illust checks.",
    )
    parser.add_argument(
        "--illust-id",
        type=int,
        default=None,
        help="Optional illust id for detail/image tests. Defaults to current ranking top item.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[mode.name for mode in DEFAULT_MODES],
        default=[mode.name for mode in DEFAULT_MODES],
        help="Bypass modes to test.",
    )
    parser.add_argument(
        "--checks",
        nargs="+",
        choices=["search", "detail", "image"],
        default=["search", "detail", "image"],
        help="Checks to run. 'image' depends on detail.",
    )
    parser.add_argument(
        "--runtime-dns-resolve",
        action="store_true",
        help="Enable runtime DNS candidate probing for bypass modes that support it.",
    )
    parser.add_argument(
        "--dns-cache-file",
        default=str(Path.cwd() / ".manual_pixiv_host_map.json"),
        help="Path for the temporary DNS cache file.",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=3.0,
        help="Minimum delay between requests. Defaults to 3 seconds for conservative testing.",
    )
    args = parser.parse_args()

    refresh_token = _load_refresh_token(args.refresh_token.strip() or None)
    dns_cache_file = Path(args.dns_cache_file)
    requested_checks = set(args.checks)
    results: list[CheckResult] = []
    throttler = RequestThrottler(args.cooldown_seconds)

    for name in args.modes:
        mode = _resolve_mode(name)
        print(
            f"[bypass-test] running mode={mode.name} "
            f"(bypass_mode={mode.bypass_mode}, bypass_sni={mode.bypass_sni})"
        )

        if "search" in requested_checks:
            results.append(
                _collect_search_check(
                    mode,
                    refresh_token=refresh_token,
                    dns_cache_file=dns_cache_file,
                    keyword=args.keyword,
                    runtime_dns_resolve=args.runtime_dns_resolve,
                    throttler=throttler,
                )
            )

        if {"detail", "image"} & requested_checks:
            results.extend(
                _collect_detail_and_image_checks(
                    mode,
                    refresh_token=refresh_token,
                    dns_cache_file=dns_cache_file,
                    illust_id=args.illust_id,
                    runtime_dns_resolve=args.runtime_dns_resolve,
                    throttler=throttler,
                )
            )

    print()
    _print_results(results)

    failed = [item for item in results if not item.ok]
    if failed:
        print()
        print(f"[bypass-test] completed with {len(failed)} failed checks")
        return 1

    print()
    print("[bypass-test] all requested checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import types
from pathlib import Path
from typing import Any


def _load_sdk_module():
    logger = logging.getLogger("manual_bookmark_flow_test")
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
    spec = importlib.util.spec_from_file_location(
        "manual_bookmark_flow_pixivSDK", sdk_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load pixivSDK from {sdk_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SDK = _load_sdk_module()
pixiv = SDK.pixiv
pick_image_url = SDK._pick_illust_image_url


def _load_refresh_token(explicit: str | None) -> str:
    if explicit:
        return explicit.strip()

    env_token = os.environ.get("PIXIV_REFRESH_TOKEN", "").strip()
    if env_token:
        return env_token

    helper_path = Path(__file__).with_name("getForToken.py")
    helper_spec = importlib.util.spec_from_file_location(
        "pixivdirect_get_token", helper_path
    )
    if helper_spec is None or helper_spec.loader is None:
        raise RuntimeError(
            "Missing refresh token. Pass --refresh-token, set PIXIV_REFRESH_TOKEN, "
            "or provide scripts/getForToken.py."
        )
    helper_module = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper_module)
    raw_token = getattr(helper_module, "token", b"")
    if isinstance(raw_token, bytes):
        token = raw_token.decode().strip()
    else:
        token = str(raw_token).strip()
    if token:
        return token

    raise RuntimeError(
        "Missing refresh token. Pass --refresh-token, set PIXIV_REFRESH_TOKEN, "
        "or provide a non-empty token in scripts/getForToken.py."
    )


def _ensure_ok(step: str, result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok"):
        return result
    raise RuntimeError(
        f"{step} failed: status={result.get('status')} error={result.get('error')}"
    )


def _write_binary(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Manual integration test for login -> bookmarks -> latest bookmark "
            "detail -> image download flow."
        )
    )
    parser.add_argument(
        "--refresh-token",
        dest="refresh_token",
        default="",
        help="Pixiv refresh token. Defaults to PIXIV_REFRESH_TOKEN env var.",
    )
    parser.add_argument(
        "--restrict",
        default="public",
        choices=("public", "private"),
        help="Bookmark visibility to inspect.",
    )
    parser.add_argument(
        "--quality",
        default="original",
        choices=("original", "medium", "small"),
        help="Image quality to fetch from the latest bookmark.",
    )
    parser.add_argument(
        "--bypass-mode",
        default="pixez",
        choices=("pixez",),
        help="Bypass mode to test. Defaults to pixez.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / "tmp"),
        help="Directory where downloaded artifacts should be saved.",
    )
    parser.add_argument(
        "--dns-cache-file",
        default=str(Path.cwd() / ".manual_pixiv_host_map.json"),
        help="DNS cache file path for the SDK.",
    )
    args = parser.parse_args()

    refresh_token = _load_refresh_token(args.refresh_token or None)
    output_dir = Path(args.output_dir).resolve()
    dns_cache_file = Path(args.dns_cache_file).resolve()

    print(f"[flow] output_dir={output_dir}")
    print(
        f"[flow] bypass_mode={args.bypass_mode}, restrict={args.restrict}, quality={args.quality}"
    )

    print("[flow] step=login_and_fetch_bookmarks")
    bookmark_result = _ensure_ok(
        "bookmark_metadata_page",
        pixiv(
            "bookmark_metadata_page",
            {
                "restrict": args.restrict,
                "quality": args.quality,
            },
            refresh_token=refresh_token,
            bypass_mode=args.bypass_mode,
            bypass_sni=True,
            dns_cache_file=str(dns_cache_file),
            dns_update_hosts=True,
            runtime_dns_resolve=True,
            max_retries=2,
        ),
    )
    latest_refresh_token = str(bookmark_result.get("refresh_token") or refresh_token)
    bookmark_data = (
        bookmark_result.get("data")
        if isinstance(bookmark_result.get("data"), dict)
        else {}
    )
    metadata_items = (
        bookmark_data.get("items")
        if isinstance(bookmark_data.get("items"), list)
        else []
    )
    raw_illusts = (
        bookmark_data.get("illusts")
        if isinstance(bookmark_data.get("illusts"), list)
        else []
    )
    if not metadata_items or not raw_illusts:
        raise RuntimeError("No bookmark items returned from the first page.")

    latest_metadata = metadata_items[0]
    latest_illust = raw_illusts[0]
    illust_id = latest_metadata.get("illust_id") or latest_illust.get("id")
    if not isinstance(illust_id, int):
        raise RuntimeError(f"Unexpected illust_id in latest bookmark: {illust_id!r}")

    print(
        "[flow] bookmarks_ok "
        f"count={len(metadata_items)} latest_illust_id={illust_id} "
        f"title={latest_metadata.get('title')!r}"
    )

    print("[flow] step=fetch_latest_bookmark_detail")
    detail_result = _ensure_ok(
        "illust_detail",
        pixiv(
            "illust_detail",
            {"illust_id": illust_id},
            refresh_token=latest_refresh_token,
            bypass_mode=args.bypass_mode,
            bypass_sni=True,
            dns_cache_file=str(dns_cache_file),
            dns_update_hosts=False,
            runtime_dns_resolve=True,
            max_retries=2,
        ),
    )
    latest_refresh_token = str(
        detail_result.get("refresh_token") or latest_refresh_token
    )
    detail_data = (
        detail_result.get("data") if isinstance(detail_result.get("data"), dict) else {}
    )
    illust = (
        detail_data.get("illust") if isinstance(detail_data.get("illust"), dict) else {}
    )
    if not illust:
        raise RuntimeError("illust_detail returned no illust payload.")

    image_url = pick_image_url(illust, args.quality)
    if not image_url:
        raise RuntimeError(
            "Unable to select image URL from the latest bookmark detail."
        )

    print(
        f"[flow] detail_ok page_count={illust.get('page_count')} image_url={image_url}"
    )

    print("[flow] step=download_image")
    image_result = _ensure_ok(
        "image",
        pixiv(
            "image",
            {"url": image_url},
            refresh_token=latest_refresh_token,
            bypass_mode=args.bypass_mode,
            bypass_sni=True,
            dns_cache_file=str(dns_cache_file),
            dns_update_hosts=False,
            runtime_dns_resolve=False,
            max_retries=2,
        ),
    )
    content = image_result.get("content")
    if not isinstance(content, (bytes, bytearray)):
        raise RuntimeError("image response did not contain binary content.")

    image_name = SDK._safe_download_filename(image_url, f"illust_{illust_id}.bin")
    metadata_path = output_dir / f"bookmark_{illust_id}.json"
    image_path = output_dir / image_name

    _write_binary(image_path, bytes(content))
    metadata_path.write_text(
        json.dumps(
            {
                "illust_id": illust_id,
                "title": latest_metadata.get("title"),
                "image_url": image_url,
                "bypass_mode": args.bypass_mode,
                "restrict": args.restrict,
                "quality": args.quality,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[flow] image_saved={image_path}")
    print(f"[flow] metadata_saved={metadata_path}")
    print("[flow] success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

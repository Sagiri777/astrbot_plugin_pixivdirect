from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import os
import re
import sys
import types
from pathlib import Path
from typing import Any


def _load_pixiv_function():
    logger = logging.getLogger("manual_pixiv_test")
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
    spec = importlib.util.spec_from_file_location("manual_pixivSDK", sdk_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load pixivSDK from {sdk_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.pixiv


pixiv = _load_pixiv_function()


def _parse_search_command(message: str) -> tuple[str, dict[str, Any]]:
    command_match = re.match(r"^/?pixiv\s*(.*)", message.strip(), re.IGNORECASE)
    remaining_args = (
        command_match.group(1).strip() if command_match else message.strip()
    )
    tokens = [token for token in re.split(r"\s+", remaining_args) if token]
    if not tokens or tokens[0].lower() != "search":
        raise ValueError("Only '/pixiv search ...' commands are supported.")

    keyword_tokens: list[str] = []
    option_tokens: list[str] = []
    option_started = False
    for token in tokens[1:]:
        if not option_started and "=" not in token:
            keyword_tokens.append(token)
            continue
        option_started = True
        option_tokens.append(token)

    keyword = " ".join(keyword_tokens).strip()
    if not keyword:
        raise ValueError("Search keyword is empty.")

    options: dict[str, Any] = {}
    for token in option_tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        if key == "page":
            page = int(value)
            if page > 0:
                options["page"] = page
        elif key == "target":
            options["search_target"] = value
        elif key == "sort":
            options["sort"] = value
        elif key == "duration":
            options["duration"] = value
        elif key == "translate":
            options["include_translated_tag_results"] = value.lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        elif key == "limit":
            limit = int(value)
            if limit > 0:
                options["limit"] = limit
    return keyword, options


async def _plugin_like_search_call(
    *,
    action: str,
    params: dict[str, Any],
    refresh_token: str,
    dns_cache_file: Path,
) -> dict[str, Any]:
    call_kwargs = {
        "dns_cache_file": str(dns_cache_file),
        "dns_update_hosts": False,
        "runtime_dns_resolve": False,
        "max_retries": 2,
        "refresh_token": refresh_token,
    }
    result = await asyncio.to_thread(pixiv, action, params, **call_kwargs)

    transient_statuses = {403, 429, 440, 500, 502, 503, 504}
    if (
        not result.get("ok")
        and action in {"search_illust", "search_user"}
        and result.get("status") in transient_statuses
    ):
        print(
            f"[manual-test] retrying {action} after status {result.get('status')} "
            "with runtime DNS resolve enabled"
        )
        retry_kwargs = {
            **call_kwargs,
            "dns_update_hosts": True,
            "runtime_dns_resolve": True,
        }
        result = await asyncio.to_thread(pixiv, action, params, **retry_kwargs)
    return result


async def _plugin_like_search_user_call(
    *,
    keyword: str,
    page: int,
    limit: int,
    refresh_token: str,
    dns_cache_file: Path,
) -> dict[str, Any]:
    params: dict[str, Any] = {"word": keyword}
    if page > 1:
        params["offset"] = (page - 1) * 30
    result = await _plugin_like_search_call(
        action="search_user",
        params=params,
        refresh_token=refresh_token,
        dns_cache_file=dns_cache_file,
    )
    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("user_previews"), list):
        data["user_previews"] = data["user_previews"][:limit]
    return result


def _build_search_params(
    keyword: str, options: dict[str, Any]
) -> tuple[dict[str, Any], int, int]:
    page = int(options.get("page", 1))
    limit = int(options.get("limit", 5))
    params: dict[str, Any] = {
        "word": keyword,
        "search_target": options.get("search_target", "partial_match_for_tags"),
        "sort": options.get("sort", "date_desc"),
        "include_translated_tag_results": options.get(
            "include_translated_tag_results",
            True,
        ),
    }
    if "duration" in options:
        params["duration"] = options["duration"]
    if page > 1:
        params["offset"] = (page - 1) * 30
    return params, page, limit


def _print_search_summary(
    illusts: list[dict[str, Any]], keyword: str, page: int
) -> None:
    print(f"🔍 搜索结果：关键词「{keyword}」（第{page}页）")
    for index, illust in enumerate(illusts, 1):
        title = str(illust.get("title") or "（无标题）")
        illust_id = illust.get("id")
        user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
        user_name = user.get("name", "未知")
        user_id = user.get("id", "未知")
        print(
            f"{index}. {title} | illust_id={illust_id} | author={user_name} ({user_id})"
        )


def _print_search_user_summary(
    user_previews: list[dict[str, Any]], keyword: str, page: int
) -> None:
    print(f"🔎 作者搜索结果：关键词「{keyword}」（第{page}页）")
    for index, preview in enumerate(user_previews, 1):
        user = preview.get("user") if isinstance(preview.get("user"), dict) else {}
        user_name = user.get("name", "未知")
        user_id = user.get("id", "未知")
        account = user.get("account", "")
        summary = f"{index}. {user_name} | user_id={user_id}"
        if account:
            summary += f" | account={account}"
        print(summary)


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual network test for '/pixiv search ...' command flow."
    )
    parser.add_argument(
        "message",
        nargs="?",
        default="/pixiv search TwiAtri",
        help="Full command message to simulate.",
    )
    parser.add_argument(
        "--refresh-token",
        dest="refresh_token",
        default=os.environ.get("PIXIV_REFRESH_TOKEN", ""),
        help="Pixiv refresh token. Defaults to PIXIV_REFRESH_TOKEN env var.",
    )
    parser.add_argument(
        "--dns-cache-file",
        default=str(Path.cwd() / ".manual_pixiv_host_map.json"),
        help="Path for temporary DNS host-map cache.",
    )
    args = parser.parse_args()

    if not args.refresh_token:
        print(
            "[manual-test] missing refresh token; pass --refresh-token or set PIXIV_REFRESH_TOKEN"
        )
        return 2

    keyword, options = _parse_search_command(args.message)
    search_params, page, limit = _build_search_params(keyword, options)

    print(f"[manual-test] message={args.message!r}")
    print(f"[manual-test] keyword={keyword!r}, page={page}, limit={limit}")
    print(f"[manual-test] search_params={search_params}")

    result = await _plugin_like_search_call(
        action="search_illust",
        params=search_params,
        refresh_token=args.refresh_token,
        dns_cache_file=Path(args.dns_cache_file),
    )

    print(
        "[manual-test] result: "
        f"ok={result.get('ok')} status={result.get('status')} "
        f"action={result.get('action')}"
    )
    if not result.get("ok"):
        print(
            f"[manual-test] error payload keys={sorted((result.get('data') or {}).keys())}"
        )
        print(f"[manual-test] raw result keys={sorted(result.keys())}")
        return 1

    data = result.get("data")
    if not isinstance(data, dict):
        print("[manual-test] response data is not a dict")
        return 1

    illusts = data.get("illusts") if isinstance(data.get("illusts"), list) else []
    illusts = illusts[:limit]
    print(f"[manual-test] illust_count={len(illusts)}")
    if illusts:
        _print_search_summary(illusts, keyword, page)
    else:
        print("[manual-test] no illustrations returned; falling back to search_user")
        user_result = await _plugin_like_search_user_call(
            keyword=keyword,
            page=page,
            limit=limit,
            refresh_token=args.refresh_token,
            dns_cache_file=Path(args.dns_cache_file),
        )
        print(
            "[manual-test] fallback result: "
            f"ok={user_result.get('ok')} status={user_result.get('status')} "
            f"action={user_result.get('action')}"
        )
        if not user_result.get("ok"):
            print(f"[manual-test] fallback data={user_result.get('data')}")
            return 1
        user_data = user_result.get("data")
        user_previews = (
            user_data.get("user_previews")
            if isinstance(user_data, dict)
            and isinstance(user_data.get("user_previews"), list)
            else []
        )
        print(f"[manual-test] fallback user_count={len(user_previews)}")
        if user_previews:
            _print_search_user_summary(user_previews, keyword, page)
        else:
            print("[manual-test] no authors returned")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

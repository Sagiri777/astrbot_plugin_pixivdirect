from __future__ import annotations

import hashlib
import itertools
import json
import os
import random
import re
import socket
import ssl
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError as RequestsSSLError
from requests.exceptions import Timeout as RequestsTimeout
from requests.utils import get_environ_proxies

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PIXEZ_HOST_MAP: dict[str, str] = {
    "app-api.pixiv.net": "210.140.139.155",
    "oauth.secure.pixiv.net": "210.140.139.155",
    "i.pximg.net": "210.140.139.133",
    "s.pximg.net": "210.140.139.133",
}
HOST_ALIAS_MAP: dict[str, str] = {
    "app-api.pixiv.net": "pixiv.me",
    "oauth.secure.pixiv.net": "pixiv.me",
    "i.pximg.net": "pximg.net",
    "s.pximg.net": "pximg.net",
}

PIXIV_HASH_SALT = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"

API_BASE = "https://app-api.pixiv.net"
OAUTH_URL = "https://oauth.secure.pixiv.net/auth/token"
PIXIV_WEB_BASE = "https://www.pixiv.net"
PIXIV_WEB_REFERER = "https://www.pixiv.net/"

PIXIV_UA = "PixivAndroidApp/5.0.155 (Android 10.0; Pixel C)"
PIXIV_OAUTH_UA = "PixivAndroidApp/5.0.155 (Android 6.0; Pixel C)"
PIXIV_WEB_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
IMAGE_UA = "PixivIOSApp/5.8.0"
IMAGE_REFERER = "https://app-api.pixiv.net/"
PIXIV_APP_VERSION = "5.0.166"
PIXIV_API_OS_VERSION = "Android 10.0"
PIXIV_OAUTH_OS_VERSION = "Android 6.0"

API_ACTIONS: dict[str, str] = {
    "illust_detail": "/v1/illust/detail",
    "illust_ranking": "/v1/illust/ranking",
    "illust_recommended": "/v1/illust/recommended",
    "search_illust": "/v1/search/illust",
    "search_user": "/v1/search/user",
    "user_detail": "/v1/user/detail",
    "user_illusts": "/v1/user/illusts",
    "user_bookmarks_illust": "/v1/user/bookmarks/illust",
    "ugoira_metadata": "/v1/ugoira/metadata",
}
AUTH_OPTIONAL_ACTIONS: set[str] = {
    "image",
    "ugoira_zip",
    "web_search_illust",
    "web_search_user",
}
WEB_SEARCH_SORT_MAP: dict[str, str] = {
    "date_desc": "date_d",
    "date_asc": "date",
    "popular_desc": "popular_d",
    "popular_male_desc": "popular_male_d",
    "popular_female_desc": "popular_female_d",
}
WEB_SEARCH_TARGET_MAP: dict[str, str] = {
    "partial_match_for_tags": "s_tag",
    "exact_match_for_tags": "s_tag_full",
    "title_and_caption": "s_tc",
}
WEB_SEARCH_DURATION_MAP: dict[str, str] = {
    "within_last_day": "1d",
    "within_last_week": "1w",
    "within_last_month": "1m",
}

_RUN_RESOLVED_IPS: dict[str, list[str]] = {}
_RUN_CACHE_LOCK = threading.Lock()
_thread_local = threading.local()
_global_session: requests.Session | None = None
_session_lock = threading.Lock()
_DNS_REQUEST_COUNTER = itertools.count(random.randint(0, 65535))
_ORIGINAL_WRAP_SOCKET = ssl.SSLContext.wrap_socket


def _wrap_socket_without_sni(context: ssl.SSLContext, *args: Any, **kwargs: Any) -> Any:
    if getattr(_thread_local, "_disable_tls_sni", False):
        if "server_hostname" in kwargs:
            kwargs = dict(kwargs)
            kwargs["server_hostname"] = None
        elif len(args) >= 4:
            mutable_args = list(args)
            mutable_args[3] = None
            args = tuple(mutable_args)
        else:
            kwargs = dict(kwargs)
            kwargs["server_hostname"] = None
    return _ORIGINAL_WRAP_SOCKET(context, *args, **kwargs)


ssl.SSLContext.wrap_socket = _wrap_socket_without_sni


def _is_ipv4(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}",
            value,
        )
    )


def _pixiv_client_time() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _build_dns_query(host: str, request_id: int) -> bytes:
    labels = host.rstrip(".").split(".")
    question = bytearray()
    for label in labels:
        encoded = label.encode("idna")
        question.append(len(encoded))
        question.extend(encoded)
    question.append(0)
    question.extend((0, 1, 0, 1))
    header = request_id.to_bytes(2, "big") + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    return header + bytes(question)


def _skip_dns_name(payload: bytes, offset: int) -> int:
    while offset < len(payload):
        length = payload[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1 + length
    return offset


def _resolve_a_records_via_dns_server(
    host: str,
    *,
    dns_server: str,
    timeout: int,
) -> list[str]:
    request_id = next(_DNS_REQUEST_COUNTER) & 0xFFFF
    query = _build_dns_query(host, request_id)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(float(timeout))
    try:
        sock.sendto(query, (dns_server, 53))
        payload, _ = sock.recvfrom(2048)
    except OSError:
        return []
    finally:
        sock.close()

    if len(payload) < 12 or int.from_bytes(payload[:2], "big") != request_id:
        return []
    flags = int.from_bytes(payload[2:4], "big")
    if flags & 0x8000 == 0 or (flags & 0x000F) != 0:
        return []

    question_count = int.from_bytes(payload[4:6], "big")
    answer_count = int.from_bytes(payload[6:8], "big")
    offset = 12
    for _ in range(question_count):
        offset = _skip_dns_name(payload, offset)
        offset += 4
        if offset > len(payload):
            return []

    ips: list[str] = []
    seen: set[str] = set()
    for _ in range(answer_count):
        offset = _skip_dns_name(payload, offset)
        if offset + 10 > len(payload):
            return ips
        record_type = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 8
        rdlength = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        if offset + rdlength > len(payload):
            return ips
        if record_type == 1 and rdlength == 4:
            ip = ".".join(str(part) for part in payload[offset : offset + 4])
            if ip not in seen:
                seen.add(ip)
                ips.append(ip)
        offset += rdlength
    return ips


def _get_runtime_dns_cache(key: str) -> list[str] | None:
    with _RUN_CACHE_LOCK:
        cached = _RUN_RESOLVED_IPS.get(key)
        return list(cached) if cached is not None else None


def _set_runtime_dns_cache(key: str, values: list[str]) -> None:
    with _RUN_CACHE_LOCK:
        _RUN_RESOLVED_IPS[key] = list(values)


def _drop_runtime_dns_cache_for_hosts(
    hosts: list[str],
    *,
    doh_server: str,
    dns_timeout: int,
    proxy: str | None,
) -> None:
    suffix = f"|{doh_server}|{dns_timeout}|{proxy or ''}"
    with _RUN_CACHE_LOCK:
        for host in hosts:
            _RUN_RESOLVED_IPS.pop(f"{host}{suffix}", None)


def _resolve_host_ips(
    host: str,
    *,
    doh_server: str,
    timeout: int,
    session: requests.Session | None = None,
    proxies: dict[str, str] | None = None,
    max_doh_servers: int | None = None,
) -> list[str]:
    del session, proxies, max_doh_servers
    return _resolve_a_records_via_dns_server(
        host, dns_server=doh_server, timeout=timeout
    )


def _rank_ips_by_latency(
    ips: list[str], *, timeout: float
) -> tuple[list[str], dict[str, float]]:
    del timeout
    return ips, {}


def _build_pixez_ip_candidates(
    host: str,
    host_map: dict[str, str],
    *,
    runtime_dns_resolve: bool,
    dns_server: str,
    dns_timeout: int,
    proxy: str | None,
    session: requests.Session,
    proxies: dict[str, str] | None,
) -> list[str]:
    candidates: list[str] = []

    def add_candidate(ip: str) -> None:
        if _is_ipv4(ip) and ip not in candidates:
            candidates.append(ip)

    direct = host_map.get(host)
    if isinstance(direct, str):
        add_candidate(direct)

    if runtime_dns_resolve:
        live_cache_key = f"{host}|{dns_server}|{dns_timeout}|{proxy or ''}"
        live_ips = _get_runtime_dns_cache(live_cache_key)
        if live_ips is None:
            live_ips = _resolve_host_ips(
                host,
                doh_server=dns_server,
                timeout=dns_timeout,
                session=session,
                proxies=proxies,
            )
            _set_runtime_dns_cache(live_cache_key, live_ips)
        for ip in live_ips:
            add_candidate(ip)

    return candidates


def _load_host_map_file(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    loaded: dict[str, str] = {}
    for host, ip in raw.items():
        if (
            isinstance(host, str)
            and isinstance(ip, str)
            and host in PIXEZ_HOST_MAP
            and _is_ipv4(ip)
        ):
            loaded[host] = ip
    return loaded


def _save_host_map_file(path: str, host_map: dict[str, str]) -> None:
    payload = {
        host: host_map[host]
        for host in PIXEZ_HOST_MAP.keys()
        if host in host_map and _is_ipv4(host_map[host])
    }
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _refresh_pixez_hosts_via_dns(
    *,
    base_map: dict[str, str],
    doh_server: str,
    timeout: int,
    session: requests.Session | None = None,
    proxies: dict[str, str] | None = None,
) -> dict[str, str]:
    del session, proxies
    refreshed = dict(base_map)
    for host in base_map:
        ips = _resolve_a_records_via_dns_server(
            host, dns_server=doh_server, timeout=timeout
        )
        if ips:
            refreshed[host] = ips[0]
    return refreshed


def refresh_pixiv_host_map(
    *,
    dns_server: str = "doh.dns.sb",
    dns_cache_file: str = ".pixiv_host_map.json",
    dns_timeout: int = 3,
    proxy: str | None = None,
    hosts: list[str] | None = None,
) -> dict[str, str]:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    session = _get_session()
    base_map = {
        host: PIXEZ_HOST_MAP[host]
        for host in (hosts or list(PIXEZ_HOST_MAP.keys()))
        if host in PIXEZ_HOST_MAP
    }
    host_map = _refresh_pixez_hosts_via_dns(
        base_map=base_map,
        doh_server=dns_server,
        timeout=dns_timeout,
        session=session,
        proxies=proxies,
    )
    persisted_host_map = dict(PIXEZ_HOST_MAP)
    persisted_host_map.update(_load_host_map_file(dns_cache_file))
    persisted_host_map.update(host_map)
    _save_host_map_file(dns_cache_file, persisted_host_map)
    _drop_runtime_dns_cache_for_hosts(
        list(host_map.keys()),
        doh_server=dns_server,
        dns_timeout=dns_timeout,
        proxy=proxy,
    )
    return host_map


def _read_refresh_token_file(path: str = ".pixiv_refresh_token") -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
            return token or None
    except FileNotFoundError:
        return None


def pick_illust_image_url(
    illust: dict[str, Any], quality: str = "original"
) -> str | None:
    urls = pick_illust_image_urls(illust, quality)
    return urls[0] if urls else None


def pick_illust_image_urls(
    illust: dict[str, Any], quality: str = "original"
) -> list[str]:
    quality_keys = {
        "original": ("original", "large", "medium", "square_medium"),
        "medium": ("large", "medium", "original", "square_medium"),
        "small": ("square_medium", "medium", "large", "original"),
    }
    keys = quality_keys.get(quality, quality_keys["original"])
    urls: list[str] = []
    meta_pages = illust.get("meta_pages")
    if isinstance(meta_pages, list) and meta_pages:
        for page in meta_pages:
            if not isinstance(page, dict):
                continue
            image_urls = page.get("image_urls")
            if not isinstance(image_urls, dict):
                continue
            for key in keys:
                url = image_urls.get(key)
                if isinstance(url, str) and url:
                    urls.append(url)
                    break
    if not urls:
        meta_single = illust.get("meta_single_page")
        if isinstance(meta_single, dict):
            original = meta_single.get("original_image_url")
            if isinstance(original, str) and original:
                if quality == "small":
                    image_urls = illust.get("image_urls")
                    square = (
                        image_urls.get("square_medium")
                        if isinstance(image_urls, dict)
                        else None
                    )
                    urls.append(
                        square if isinstance(square, str) and square else original
                    )
                elif quality == "medium":
                    image_urls = illust.get("image_urls")
                    large = (
                        image_urls.get("large")
                        if isinstance(image_urls, dict)
                        else None
                    )
                    urls.append(large if isinstance(large, str) and large else original)
                else:
                    urls.append(original)
    if not urls:
        image_urls = illust.get("image_urls")
        if isinstance(image_urls, dict):
            for key in keys:
                url = image_urls.get(key)
                if isinstance(url, str) and url:
                    urls.append(url)
                    break
    return urls


def _illust_to_metadata_entry(
    illust: dict[str, Any],
    *,
    restrict: str,
    quality: str = "original",
) -> dict[str, Any]:
    user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
    tags: list[str] = []
    raw_tags = illust.get("tags")
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name:
                    tags.append(name)
    return {
        "illust_id": illust.get("id"),
        "title": illust.get("title"),
        "author_id": user.get("id"),
        "author_name": user.get("name"),
        "tags": tags,
        "x_restrict": illust.get("x_restrict", 0),
        "page_count": illust.get("page_count", 1),
        "image_urls": pick_illust_image_urls(illust, quality),
        "caption_seed": {
            "total_view": illust.get("total_view"),
            "total_bookmarks": illust.get("total_bookmarks"),
            "create_date": illust.get("create_date"),
        },
        "bookmark_restrict": restrict,
        "cached_at": datetime.now().isoformat(),
    }


def _match_author(
    illust: dict[str, Any],
    *,
    author_id: int | None,
    author_name: str | None,
) -> bool:
    user = illust.get("user")
    if not isinstance(user, dict):
        return False
    if author_id is not None and str(user.get("id")) != str(author_id):
        return False
    if author_name:
        name = str(user.get("name") or "")
        if author_name.lower() not in name.lower():
            return False
    return True


def _match_illust_tag(illust: dict[str, Any], tag: str | None) -> bool:
    if not tag:
        return True
    raw_tags = illust.get("tags")
    if not isinstance(raw_tags, list):
        return False
    tag_lower = tag.lower()
    for item in raw_tags:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        translated_name = item.get("translated_name")
        if isinstance(name, str) and name.lower() == tag_lower:
            return True
        if isinstance(translated_name, str) and translated_name.lower() == tag_lower:
            return True
    return False


def _normalize_web_illust_item(item: dict[str, Any]) -> dict[str, Any]:
    preview_url = None
    image_urls = (
        item.get("image_urls") if isinstance(item.get("image_urls"), dict) else {}
    )
    urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
    for candidate in (
        image_urls.get("large"),
        image_urls.get("medium"),
        urls.get("thumb"),
        item.get("url"),
    ):
        if isinstance(candidate, str) and candidate:
            preview_url = candidate
            break
    square_url = urls.get("small") or urls.get("thumb") or preview_url
    return {
        "id": item.get("id"),
        "title": str(item.get("title") or "（无标题）"),
        "total_bookmarks": item.get("bookmarkCount") or item.get("bookmark_count"),
        "x_restrict": int(item.get("xRestrict") or 0),
        "page_count": item.get("pageCount") or item.get("page_count") or 1,
        "tags": [{"name": tag} for tag in item.get("tags", []) if isinstance(tag, str)],
        "user": {
            "id": item.get("userId") or item.get("user_id"),
            "name": item.get("userName") or item.get("user_name") or "未知",
        },
        "image_urls": {
            "large": preview_url,
            "medium": preview_url,
            "square_medium": square_url,
        },
    }


def _normalize_web_user_preview(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "user": {
            "id": item.get("userId") or item.get("user_id"),
            "name": item.get("userName") or item.get("user_name") or "未知",
            "account": item.get("userAccount") or item.get("account") or "",
            "profile": {
                "total_illusts": item.get("illustsTotal")
                or item.get("illust_total")
                or 0,
                "total_manga": item.get("mangaTotal") or item.get("manga_total") or 0,
            },
        },
        "illusts": [
            {
                "id": illust.get("id"),
                "title": str(illust.get("title") or "（无标题）"),
            }
            for illust in item.get("illusts", [])
            if isinstance(illust, dict)
        ],
    }


def _extract_web_search_body(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error") is False and isinstance(payload.get("body"), dict):
        return payload["body"]
    body = payload.get("body")
    return body if isinstance(body, dict) else {}


@contextmanager
def _patched_dns_resolution(host_map: dict[str, str]):
    if not host_map:
        yield
        return
    normalized = {k.lower().rstrip("."): v for k, v in host_map.items()}
    original_getaddrinfo = socket.getaddrinfo
    _thread_local._original_getaddrinfo = original_getaddrinfo
    _thread_local._dns_normalized = normalized

    def patched_getaddrinfo(host: str, *args: Any, **kwargs: Any):
        if isinstance(host, str):
            key = host.lower().rstrip(".")
            dns_map = getattr(_thread_local, "_dns_normalized", {})
            ip = dns_map.get(key)
            if ip:
                original = getattr(
                    _thread_local, "_original_getaddrinfo", original_getaddrinfo
                )
                return original(ip, *args, **kwargs)
        return original_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo
        if hasattr(_thread_local, "_original_getaddrinfo"):
            delattr(_thread_local, "_original_getaddrinfo")
        if hasattr(_thread_local, "_dns_normalized"):
            delattr(_thread_local, "_dns_normalized")


@contextmanager
def _without_tls_sni():
    previous = getattr(_thread_local, "_disable_tls_sni", False)
    _thread_local._disable_tls_sni = True
    try:
        yield
    finally:
        _thread_local._disable_tls_sni = previous


def _get_session() -> requests.Session:
    global _global_session
    if _global_session is None:
        with _session_lock:
            if _global_session is None:
                session = requests.Session()
                https_adapter = HTTPAdapter(
                    pool_connections=10, pool_maxsize=20, max_retries=3
                )
                http_adapter = HTTPAdapter(
                    pool_connections=10, pool_maxsize=20, max_retries=3
                )
                session.mount("https://", https_adapter)
                session.mount("http://", http_adapter)
                _global_session = session
    return _global_session


class PixivTransport:
    def send(
        self,
        method: str,
        url: str,
        *,
        req_params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        with_auth: bool = False,
        image_mode: bool = False,
        action: str = "",
        access_token: str | None = None,
        bypass_sni: bool = True,
        accept_language: str = "zh-CN",
        proxy: str | None = None,
        timeout: int = 30,
        connect_timeout: float = 8.0,
        dns_timeout: int = 3,
        dns_update_hosts: bool = False,
        dns_server: str = "doh.dns.sb",
        dns_cache_file: str = ".pixiv_host_map.json",
        runtime_dns_resolve: bool = False,
        max_retries: int = 3,
        connect_probe_timeout: float = 2.0,
        search_runtime_ip_candidate_limit: int | None = None,
        search_retryable_failure_budget: int | None = None,
    ) -> requests.Response:
        del connect_probe_timeout
        proxies = {"http": proxy, "https": proxy} if proxy else None
        session = _get_session()
        host_map = dict(PIXEZ_HOST_MAP)
        host_map.update(_load_host_map_file(dns_cache_file))
        if dns_update_hosts:
            host_map = _refresh_pixez_hosts_via_dns(
                base_map=host_map,
                doh_server=dns_server,
                timeout=dns_timeout,
                session=session,
                proxies=proxies,
            )
            _save_host_map_file(dns_cache_file, host_map)
            _drop_runtime_dns_cache_for_hosts(
                list(host_map.keys()),
                doh_server=dns_server,
                dns_timeout=dns_timeout,
                proxy=proxy,
            )

        retryable_statuses = (
            {403} if action in {"search_illust", "search_user"} else set()
        )
        runtime_ip_candidate_limit = (
            max(1, int(search_runtime_ip_candidate_limit))
            if runtime_dns_resolve and search_runtime_ip_candidate_limit is not None
            else None
        )
        retryable_failure_budget = (
            max(1, int(search_retryable_failure_budget))
            if runtime_dns_resolve and search_retryable_failure_budget is not None
            else None
        )
        req_host = (urlsplit(url).hostname or "").lower().rstrip(".")
        is_web_request = req_host == "www.pixiv.net"
        merged_headers = {
            "User-Agent": (
                IMAGE_UA
                if image_mode
                else PIXIV_WEB_UA
                if is_web_request
                else PIXIV_OAUTH_UA
                if req_host == "oauth.secure.pixiv.net"
                else PIXIV_UA
            ),
            "Accept-Language": accept_language,
        }
        if image_mode:
            merged_headers["Referer"] = IMAGE_REFERER
        elif is_web_request:
            merged_headers.setdefault("Accept", "application/json, text/plain, */*")
        if not image_mode and req_host in {
            "app-api.pixiv.net",
            "oauth.secure.pixiv.net",
        }:
            now = _pixiv_client_time()
            merged_headers.setdefault("X-Client-Time", now)
            merged_headers.setdefault(
                "X-Client-Hash",
                hashlib.md5((now + PIXIV_HASH_SALT).encode("utf-8")).hexdigest(),
            )
            merged_headers.setdefault("App-OS", "Android")
            merged_headers.setdefault(
                "App-OS-Version",
                PIXIV_OAUTH_OS_VERSION
                if req_host == "oauth.secure.pixiv.net"
                else PIXIV_API_OS_VERSION,
            )
            merged_headers.setdefault("App-Version", PIXIV_APP_VERSION)
            if req_host == "app-api.pixiv.net":
                merged_headers.setdefault("Host", "app-api.pixiv.net")
        if with_auth:
            if not access_token:
                raise ValueError("Missing access_token after auth.")
            merged_headers["Authorization"] = f"Bearer {access_token}"
        if headers:
            merged_headers.update(headers)

        req_split = urlsplit(url)
        has_proxy = bool(proxies) or bool(get_environ_proxies(url))

        def _url_with_host(host: str) -> str:
            netloc = host if not req_split.port else f"{host}:{req_split.port}"
            return urlunsplit(
                (
                    req_split.scheme,
                    netloc,
                    req_split.path,
                    req_split.query,
                    req_split.fragment,
                )
            )

        def _do_request(
            target_url: str | None = None,
            dns_override: dict[str, str] | None = None,
            *,
            verify: bool = True,
            disable_sni: bool = False,
        ) -> requests.Response:
            last_res: requests.Response | None = None
            request_url = target_url or url
            for attempt in range(max_retries + 1):
                with _patched_dns_resolution(dns_override or {}):
                    with _without_tls_sni() if disable_sni else nullcontext():
                        res = session.request(
                            method=method,
                            url=request_url,
                            params=req_params,
                            data=data,
                            headers=merged_headers,
                            proxies=proxies,
                            timeout=(connect_timeout, timeout),
                            verify=verify,
                        )
                last_res = res
                if res.status_code != 429:
                    return res
                if attempt >= max_retries:
                    return res
                retry_after = res.headers.get("Retry-After")
                wait_seconds = 2.0 * (attempt + 1)
                if retry_after and retry_after.isdigit():
                    wait_seconds = max(wait_seconds, float(retry_after))
                time.sleep(min(wait_seconds, 15.0))
            assert last_res is not None
            return last_res

        if not (bypass_sni and req_host in host_map) or has_proxy:
            return _do_request()

        ip_candidates = _build_pixez_ip_candidates(
            req_host,
            host_map,
            runtime_dns_resolve=runtime_dns_resolve,
            dns_server=dns_server,
            dns_timeout=dns_timeout,
            proxy=proxy,
            session=session,
            proxies=proxies,
        )
        if (
            runtime_ip_candidate_limit is not None
            and len(ip_candidates) > runtime_ip_candidate_limit
        ):
            ip_candidates = ip_candidates[:runtime_ip_candidate_limit]

        failure_budget_used = 0
        last_res: requests.Response | None = None
        last_exc: Exception | None = None
        for ip in ip_candidates:
            try:
                res = _do_request(
                    dns_override={req_host: ip}, verify=False, disable_sni=True
                )
                last_res = res
                if res.ok:
                    return res
                if runtime_dns_resolve and res.status_code in retryable_statuses:
                    failure_budget_used += 1
                    if (
                        retryable_failure_budget
                        and failure_budget_used >= retryable_failure_budget
                    ):
                        break
                    continue
                return res
            except (RequestsConnectionError, RequestsTimeout, RequestsSSLError) as exc:
                last_exc = exc
                failure_budget_used += 1
                if (
                    retryable_failure_budget
                    and failure_budget_used >= retryable_failure_budget
                ):
                    break

        alias_host = HOST_ALIAS_MAP.get(req_host)
        if (
            alias_host
            and runtime_dns_resolve
            and last_res is not None
            and last_res.status_code in retryable_statuses
        ):
            try:
                return _do_request(target_url=_url_with_host(alias_host))
            except (RequestsConnectionError, RequestsTimeout, RequestsSSLError) as exc:
                last_exc = exc

        if not ip_candidates:
            return _do_request()
        if last_res is not None:
            return last_res
        if last_exc:
            raise last_exc
        return _do_request()


class PixivAuthClient:
    def __init__(self, transport: PixivTransport) -> None:
        self._transport = transport

    def refresh_access_token(
        self,
        *,
        refresh_token: str | None,
        proxy: str | None = None,
        dns_cache_file: str = ".pixiv_host_map.json",
        bypass_sni: bool = True,
    ) -> dict[str, Any]:
        refresh_token = (
            refresh_token
            or os.getenv("PIXIV_REFRESH_TOKEN")
            or _read_refresh_token_file()
        )
        if not refresh_token:
            raise ValueError(
                "Missing refresh_token. Pass it or set PIXIV_REFRESH_TOKEN."
            )
        res = self._transport.send(
            "POST",
            OAUTH_URL,
            data={
                "client_id": PIXIV_CLIENT_ID,
                "client_secret": PIXIV_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "include_policy": "true",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            action="auth",
            proxy=proxy,
            dns_cache_file=dns_cache_file,
            bypass_sni=bypass_sni,
        )
        payload = res.json()
        return {
            "ok": res.ok,
            "status": res.status_code,
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token") or refresh_token,
            "user": payload.get("user"),
            "error": payload if not res.ok else None,
        }


class PixivApiClient:
    def __init__(self, facade: PixivClientFacade) -> None:
        self._facade = facade

    def get_illust_detail(self, illust_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action(
            "illust_detail", {"illust_id": illust_id}, **kwargs
        )

    def get_user_detail(self, user_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action("user_detail", {"user_id": user_id}, **kwargs)

    def search_illusts(self, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action("search_illust", params, **kwargs)

    def search_users(self, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action("search_user", params, **kwargs)

    def get_bookmark_metadata_page(
        self, params: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return self._facade.call_action("bookmark_metadata_page", params, **kwargs)


class PixivImageClient:
    def __init__(self, facade: PixivClientFacade) -> None:
        self._facade = facade

    def download_image(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action("image", {"url": url}, **kwargs)

    def get_ugoira_metadata(self, illust_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action(
            "ugoira_metadata", {"illust_id": illust_id}, **kwargs
        )

    def download_ugoira_zip(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self._facade.call_action("ugoira_zip", {"url": url}, **kwargs)


class PixivDnsResolver:
    def refresh_host_map(self, **kwargs: Any) -> dict[str, str]:
        return refresh_pixiv_host_map(**kwargs)


class PixivClientFacade:
    def __init__(self) -> None:
        self.transport = PixivTransport()
        self.auth = PixivAuthClient(self.transport)
        self.api = PixivApiClient(self)
        self.image = PixivImageClient(self)
        self.dns = PixivDnsResolver()

    def call_action(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        refresh_token: str | None = None,
        access_token: str | None = None,
        bypass_sni: bool = True,
        accept_language: str = "zh-CN",
        proxy: str | None = None,
        timeout: int = 30,
        connect_timeout: float = 8.0,
        dns_timeout: int = 3,
        dns_update_hosts: bool = False,
        dns_server: str = "doh.dns.sb",
        dns_cache_file: str = ".pixiv_host_map.json",
        runtime_dns_resolve: bool = False,
        max_retries: int = 3,
        connect_probe_timeout: float = 2.0,
        search_runtime_ip_candidate_limit: int | None = None,
        search_retryable_failure_budget: int | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        requires_auth = action not in AUTH_OPTIONAL_ACTIONS
        current_user_id: int | None = None
        if requires_auth and not access_token:
            auth_result = self.auth.refresh_access_token(
                refresh_token=refresh_token,
                proxy=proxy,
                dns_cache_file=dns_cache_file,
                bypass_sni=bypass_sni,
            )
            if not auth_result.get("ok"):
                return {
                    "ok": False,
                    "action": "auth",
                    "status": auth_result.get("status"),
                    "error": auth_result.get("error"),
                }
            access_token = auth_result.get("access_token")
            refresh_token = auth_result.get("refresh_token") or refresh_token
            user = auth_result.get("user")
            if isinstance(user, dict):
                user_id = user.get("id")
                if isinstance(user_id, int):
                    current_user_id = user_id
                elif isinstance(user_id, str) and user_id.isdigit():
                    current_user_id = int(user_id)

        if action == "bookmark_metadata_page":
            bookmark_user_id = (
                params.get("bookmark_user_id")
                or params.get("user_id")
                or current_user_id
            )
            if bookmark_user_id is None:
                raise ValueError("Missing bookmark_user_id/user_id.")
            restrict = str(params.get("restrict") or "public").strip().lower()
            if restrict not in {"public", "private"}:
                restrict = "public"
            next_url = params.get("next_url")
            if isinstance(next_url, str) and next_url.strip():
                request_url = next_url.strip()
                request_params = None
            else:
                request_url = f"{API_BASE}{API_ACTIONS['user_bookmarks_illust']}"
                request_params = {"user_id": bookmark_user_id, "restrict": restrict}
                offset = params.get("offset")
                if offset is not None:
                    request_params["offset"] = max(0, int(offset))
                tag = params.get("tag")
                if isinstance(tag, str) and tag.strip():
                    request_params["tag"] = tag.strip()
            page_res = self.transport.send(
                "GET",
                request_url,
                req_params=request_params,
                with_auth=True,
                action=action,
                access_token=access_token,
                bypass_sni=bypass_sni,
                accept_language=accept_language,
                proxy=proxy,
                timeout=timeout,
                connect_timeout=connect_timeout,
                dns_timeout=dns_timeout,
                dns_update_hosts=dns_update_hosts,
                dns_server=dns_server,
                dns_cache_file=dns_cache_file,
                runtime_dns_resolve=runtime_dns_resolve,
                max_retries=max_retries,
                connect_probe_timeout=connect_probe_timeout,
                search_runtime_ip_candidate_limit=search_runtime_ip_candidate_limit,
                search_retryable_failure_budget=search_retryable_failure_budget,
            )
            try:
                page_data = page_res.json()
            except Exception:
                page_data = {"raw": page_res.text}
            illusts = page_data.get("illusts") if isinstance(page_data, dict) else []
            return {
                "ok": page_res.ok,
                "action": action,
                "status": page_res.status_code,
                "data": {
                    "items": [
                        _illust_to_metadata_entry(
                            illust,
                            restrict=restrict,
                            quality=str(params.get("quality") or "original"),
                        )
                        for illust in illusts
                        if isinstance(illust, dict)
                    ],
                    "illusts": illusts if isinstance(illusts, list) else [],
                    "next_url": page_data.get("next_url")
                    if isinstance(page_data, dict)
                    else None,
                },
                "error": page_data if not page_res.ok else None,
                "access_token": access_token,
                "refresh_token": refresh_token,
            }

        if action in {
            "random_bookmark_image",
            "random_bookmark",
            "random_bookmark_by_tag",
        }:
            bookmark_user_id = (
                params.get("bookmark_user_id")
                or params.get("user_id")
                or current_user_id
            )
            if bookmark_user_id is None:
                raise ValueError("Missing bookmark_user_id/user_id.")
            tag = str(params.get("tag")) if params.get("tag") else None
            author_id_raw = params.get("author_id") or params.get("author_user_id")
            author_id = (
                int(str(author_id_raw).strip())
                if author_id_raw is not None and str(author_id_raw).strip()
                else None
            )
            author_name_raw = params.get("author") or params.get("author_name")
            author_name = str(author_name_raw).strip() if author_name_raw else None
            restrict = str(params.get("restrict") or "public").strip().lower()
            if restrict not in {"public", "private"}:
                restrict = "public"
            exclude_ids_raw = params.get("exclude_ids")
            exclude_ids = (
                {
                    int(i)
                    for i in exclude_ids_raw
                    if isinstance(i, (int, str)) and str(i).isdigit()
                }
                if isinstance(exclude_ids_raw, (list, set))
                else set()
            )
            list_params: dict[str, Any] = {
                "user_id": bookmark_user_id,
                "restrict": restrict,
            }
            if tag:
                list_params["tag"] = tag
            sampled: dict[str, Any] | None = None
            matched = 0
            pages = 0
            max_pages = max(1, int(str(params.get("max_pages") or 3)))
            next_url: str | None = f"{API_BASE}{API_ACTIONS['user_bookmarks_illust']}"
            next_params: dict[str, Any] | None = list_params
            while next_url:
                page_res = self.transport.send(
                    "GET",
                    next_url,
                    req_params=next_params,
                    with_auth=True,
                    action=action,
                    access_token=access_token,
                    bypass_sni=bypass_sni,
                    accept_language=accept_language,
                    proxy=proxy,
                    timeout=timeout,
                    connect_timeout=connect_timeout,
                    dns_timeout=dns_timeout,
                    dns_update_hosts=dns_update_hosts,
                    dns_server=dns_server,
                    dns_cache_file=dns_cache_file,
                    runtime_dns_resolve=runtime_dns_resolve,
                    max_retries=max_retries,
                    connect_probe_timeout=connect_probe_timeout,
                    search_runtime_ip_candidate_limit=search_runtime_ip_candidate_limit,
                    search_retryable_failure_budget=search_retryable_failure_budget,
                )
                page_data = page_res.json()
                pages += 1
                illusts = page_data.get("illusts")
                if isinstance(illusts, list):
                    for illust in illusts:
                        if not isinstance(illust, dict):
                            continue
                        if not _match_author(
                            illust, author_id=author_id, author_name=author_name
                        ):
                            continue
                        if tag and not _match_illust_tag(illust, tag):
                            continue
                        illust_id = illust.get("id")
                        if isinstance(illust_id, int) and illust_id in exclude_ids:
                            continue
                        matched += 1
                        if random.randrange(matched) == 0:
                            sampled = illust
                next_url_val = page_data.get("next_url")
                next_url = (
                    next_url_val
                    if isinstance(next_url_val, str)
                    and next_url_val
                    and pages < max_pages
                    else None
                )
                next_params = None
            if not sampled:
                return {
                    "ok": False,
                    "action": action,
                    "status": 404,
                    "error": {"message": "No bookmarked illust matched filters."},
                }
            sampled_user = (
                sampled.get("user") if isinstance(sampled.get("user"), dict) else {}
            )
            tags = [
                item.get("name")
                for item in sampled.get("tags", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            return {
                "ok": True,
                "action": action,
                "status": 200,
                "data": {
                    "id": sampled.get("id"),
                    "title": sampled.get("title"),
                    "author": {
                        "id": sampled_user.get("id"),
                        "name": sampled_user.get("name"),
                    },
                    "tags": tags,
                    "image_url": pick_illust_image_url(
                        sampled, str(params.get("quality", "original"))
                    ),
                    "illust": sampled,
                    "matched_count": matched,
                    "pages_scanned": pages,
                },
                "access_token": access_token,
                "refresh_token": refresh_token,
            }

        if action == "image":
            image_url = params.get("url")
            if not image_url:
                raise ValueError("action=image requires params.url")
            image_res = self.transport.send(
                "GET",
                str(image_url),
                image_mode=True,
                action=action,
                bypass_sni=bypass_sni,
                accept_language=accept_language,
                proxy=proxy,
                timeout=timeout,
                connect_timeout=connect_timeout,
                dns_timeout=dns_timeout,
                dns_update_hosts=dns_update_hosts,
                dns_server=dns_server,
                dns_cache_file=dns_cache_file,
                runtime_dns_resolve=runtime_dns_resolve,
                max_retries=max_retries,
                connect_probe_timeout=connect_probe_timeout,
                search_runtime_ip_candidate_limit=search_runtime_ip_candidate_limit,
                search_retryable_failure_budget=search_retryable_failure_budget,
            )
            return {
                "ok": image_res.ok,
                "action": action,
                "status": image_res.status_code,
                "content_type": image_res.headers.get("Content-Type"),
                "content": image_res.content,
            }

        if action == "ugoira_zip":
            zip_url = params.get("url")
            if not zip_url:
                raise ValueError("action=ugoira_zip requires params.url")
            zip_res = self.transport.send(
                "GET",
                str(zip_url),
                image_mode=True,
                action=action,
                bypass_sni=bypass_sni,
                accept_language=accept_language,
                proxy=proxy,
                timeout=timeout,
                connect_timeout=connect_timeout,
                dns_timeout=dns_timeout,
                dns_update_hosts=dns_update_hosts,
                dns_server=dns_server,
                dns_cache_file=dns_cache_file,
                runtime_dns_resolve=runtime_dns_resolve,
                max_retries=max_retries,
                connect_probe_timeout=connect_probe_timeout,
                search_runtime_ip_candidate_limit=search_runtime_ip_candidate_limit,
                search_retryable_failure_budget=search_retryable_failure_budget,
            )
            return {
                "ok": zip_res.ok,
                "action": action,
                "status": zip_res.status_code,
                "content_type": zip_res.headers.get("Content-Type"),
                "content": zip_res.content,
            }

        if action in {"web_search_illust", "web_search_user"}:
            keyword = str(params.get("word") or "").strip()
            if not keyword:
                raise ValueError(f"action={action} requires params.word")
            page = max(1, int(params.get("page", 1) or 1))
            endpoint = (
                f"{PIXIV_WEB_BASE}/ajax/search/artworks/{quote(keyword)}"
                if action == "web_search_illust"
                else f"{PIXIV_WEB_BASE}/ajax/search/users/{quote(keyword)}"
            )
            web_params: dict[str, Any] = {"word": keyword, "p": page}
            sort = str(params.get("sort") or "date_desc").strip().lower()
            target = str(params.get("search_target") or "").strip().lower()
            duration = str(params.get("duration") or "").strip().lower()
            mapped_sort = WEB_SEARCH_SORT_MAP.get(sort)
            mapped_target = WEB_SEARCH_TARGET_MAP.get(target)
            mapped_duration = WEB_SEARCH_DURATION_MAP.get(duration)
            if mapped_sort and action == "web_search_illust":
                web_params["order"] = mapped_sort
            if mapped_target and action == "web_search_illust":
                web_params["s_mode"] = mapped_target
            if mapped_duration and action == "web_search_illust":
                web_params["mode"] = mapped_duration
            web_res = self.transport.send(
                "GET",
                endpoint,
                req_params=web_params,
                headers={
                    "Referer": PIXIV_WEB_REFERER,
                    "X-Requested-With": "XMLHttpRequest",
                },
                action=action,
                bypass_sni=bypass_sni,
                accept_language=accept_language,
                proxy=proxy,
                timeout=timeout,
                connect_timeout=connect_timeout,
                dns_timeout=dns_timeout,
                dns_update_hosts=dns_update_hosts,
                dns_server=dns_server,
                dns_cache_file=dns_cache_file,
                runtime_dns_resolve=runtime_dns_resolve,
                max_retries=max_retries,
                connect_probe_timeout=connect_probe_timeout,
                search_runtime_ip_candidate_limit=search_runtime_ip_candidate_limit,
                search_retryable_failure_budget=search_retryable_failure_budget,
            )
            try:
                payload = web_res.json()
            except Exception:
                payload = {"error": True, "message": web_res.text}
            body = _extract_web_search_body(
                payload if isinstance(payload, dict) else {}
            )
            if action == "web_search_illust":
                illust_container = (
                    body.get("illustManga")
                    if isinstance(body.get("illustManga"), dict)
                    else body
                )
                items = (
                    illust_container.get("data")
                    if isinstance(illust_container, dict)
                    else []
                )
                if not isinstance(items, list):
                    items = []
                data = {
                    "illusts": [
                        _normalize_web_illust_item(item)
                        for item in items
                        if isinstance(item, dict)
                    ],
                    "total": illust_container.get("total")
                    if isinstance(illust_container, dict)
                    else None,
                }
            else:
                users = body.get("users")
                if not isinstance(users, list):
                    users = body.get("user_previews")
                if not isinstance(users, list):
                    users = []
                data = {
                    "user_previews": [
                        _normalize_web_user_preview(item)
                        for item in users
                        if isinstance(item, dict)
                    ],
                    "total": body.get("total"),
                }
            return {
                "ok": web_res.ok,
                "action": action,
                "status": web_res.status_code,
                "data": data,
                "error": payload if not web_res.ok else None,
                "access_token": access_token,
                "refresh_token": refresh_token,
            }

        if action == "illust_recommended":
            params = {
                "filter": "for_ios",
                "include_ranking_label": "true",
                **params,
            }

        request_path = API_ACTIONS.get(
            action, action if str(action).startswith("/") else None
        )
        if not request_path:
            raise ValueError(f"Unsupported action: {action}")
        method = "GET"
        api_url = (
            f"{API_BASE}{request_path}"
            if request_path.startswith("/")
            else request_path
        )
        res = self.transport.send(
            method,
            api_url,
            req_params=params,
            with_auth=requires_auth,
            action=action,
            access_token=access_token,
            bypass_sni=bypass_sni,
            accept_language=accept_language,
            proxy=proxy,
            timeout=timeout,
            connect_timeout=connect_timeout,
            dns_timeout=dns_timeout,
            dns_update_hosts=dns_update_hosts,
            dns_server=dns_server,
            dns_cache_file=dns_cache_file,
            runtime_dns_resolve=runtime_dns_resolve,
            max_retries=max_retries,
            connect_probe_timeout=connect_probe_timeout,
            search_runtime_ip_candidate_limit=search_runtime_ip_candidate_limit,
            search_retryable_failure_budget=search_retryable_failure_budget,
        )
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text}
        return {
            "ok": res.ok,
            "action": action,
            "status": res.status_code,
            "data": data,
            "error": data if not res.ok else None,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

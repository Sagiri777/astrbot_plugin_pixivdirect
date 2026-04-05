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
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError as RequestsSSLError
from requests.exceptions import Timeout as RequestsTimeout
from requests.utils import get_environ_proxies

from astrbot.api import logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# PixEz host map: fixed IPv4 for CN SNI bypass.
PIXEZ_HOST_MAP: dict[str, str] = {
    "app-api.pixiv.net": "210.140.139.155",
    "oauth.secure.pixiv.net": "210.140.139.155",
    "i.pximg.net": "210.140.139.133",
    "s.pximg.net": "210.140.139.133",
}
PIXEZ_API_HOSTS: set[str] = {
    "app-api.pixiv.net",
    "oauth.secure.pixiv.net",
}
PIXEZ_IMAGE_HOSTS: set[str] = {
    "i.pximg.net",
    "s.pximg.net",
}

# Accesser-like host aliases (domain -> upstream domain).
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
PIXIV_UA = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"
PIXIV_WEB_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
IMAGE_UA = "PixivIOSApp/5.8.0"
IMAGE_REFERER = "https://app-api.pixiv.net/"
PIXIV_APP_FILTER = "for_android"
PIXIV_WEB_BASE = "https://www.pixiv.net"
PIXIV_WEB_REFERER = "https://www.pixiv.net/"

# Process-level caches for runtime DNS resolve.
_RUN_RESOLVED_IPS: dict[str, list[str]] = {}
_RUN_CACHE_LOCK = threading.Lock()

# Thread-local storage for DNS patching (thread-safe)
_thread_local = threading.local()

# Global session pool for connection reuse
_global_session: requests.Session | None = None
_session_lock = threading.Lock()
_DNS_REQUEST_COUNTER = itertools.count(random.randint(0, 65535))

# 常用 action -> API path 映射。也支持直接传入 path（以 / 开头）。
API_ACTIONS: dict[str, str] = {
    "illust_detail": "/v1/illust/detail",
    "illust_ranking": "/v1/illust/ranking",
    "illust_recommended": "/v1/illust/recommended",
    "search_illust": "/v1/search/illust",
    "user_detail": "/v1/user/detail",
    "user_illusts": "/v1/user/illusts",
    "user_bookmarks_illust": "/v1/user/bookmarks/illust",
    "search_user": "/v1/search/user",
    "ugoira_metadata": "/v1/ugoira/metadata",
}

AUTH_OPTIONAL_ACTIONS: set[str] = {
    "image",
    "ugoira_zip",
    "web_search_illust",
    "web_search_user",
}

APP_API_FILTER_ACTIONS: set[str] = {
    "illust_detail",
    "illust_ranking",
    "illust_recommended",
    "search_illust",
    "search_user",
    "user_detail",
    "user_illusts",
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
        offset += 2
        record_class = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        offset += 4
        rdlength = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        if offset + rdlength > len(payload):
            return ips
        rdata = payload[offset : offset + rdlength]
        offset += rdlength
        if record_type == 1 and record_class == 1 and rdlength == 4:
            ip = ".".join(str(part) for part in rdata)
            if _is_ipv4(ip) and ip not in seen:
                seen.add(ip)
                ips.append(ip)
    return ips


def _resolve_a_record_via_doh(
    host: str,
    *,
    doh_server: str,
    timeout: int,
    session: requests.Session,
    proxies: dict[str, str] | None,
) -> str | None:
    # 支持传入 "doh.dns.sb" 或完整 URL（例如 https://1.1.1.1/dns-query）。
    doh_url = (
        doh_server
        if doh_server.startswith("http://") or doh_server.startswith("https://")
        else f"https://{doh_server}/dns-query"
    )
    try:
        res = session.get(
            doh_url,
            params={"name": host, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=(2, timeout),
            proxies=proxies,
        )
        data = res.json()
    except Exception:
        return None

    answers = data.get("Answer") or []
    ip_candidates = [item.get("data") for item in answers if isinstance(item, dict)]
    ip_candidates = [ip for ip in ip_candidates if isinstance(ip, str) and _is_ipv4(ip)]
    return ip_candidates[0] if ip_candidates else None


def _resolve_a_records_via_doh(
    host: str,
    *,
    doh_server: str,
    timeout: int,
    session: requests.Session,
    proxies: dict[str, str] | None,
) -> list[str]:
    # 支持传入 "doh.dns.sb" 或完整 URL（例如 https://1.1.1.1/dns-query）。
    doh_url = (
        doh_server
        if doh_server.startswith("http://") or doh_server.startswith("https://")
        else f"https://{doh_server}/dns-query"
    )
    try:
        res = session.get(
            doh_url,
            params={"name": host, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=(2, timeout),
            proxies=proxies,
        )
        data = res.json()
    except Exception:
        return []

    answers = data.get("Answer") or []
    sorted_answers = sorted(
        [item for item in answers if isinstance(item, dict)],
        key=lambda item: int(item.get("TTL", 0) or 0),
        reverse=True,
    )
    ip_candidates = [item.get("data") for item in sorted_answers]
    deduped: list[str] = []
    seen: set[str] = set()
    for ip in ip_candidates:
        if isinstance(ip, str) and _is_ipv4(ip) and ip not in seen:
            seen.add(ip)
            deduped.append(ip)
    return deduped


def _doh_server_candidates(primary: str) -> list[str]:
    primary_normalized = (
        primary
        if primary.startswith("http://") or primary.startswith("https://")
        else f"https://{primary}/dns-query"
    )
    return [primary_normalized]


def _dns_server_candidates() -> list[str]:
    return []


def _get_runtime_dns_cache(key: str) -> list[str] | None:
    with _RUN_CACHE_LOCK:
        cached = _RUN_RESOLVED_IPS.get(key)
        return list(cached) if cached is not None else None


def _set_runtime_dns_cache(key: str, ips: list[str]) -> None:
    with _RUN_CACHE_LOCK:
        _RUN_RESOLVED_IPS[key] = list(ips)


def _drop_runtime_dns_cache_for_hosts(
    hosts: list[str],
    *,
    doh_server: str,
    dns_timeout: int,
    proxy: str | None,
) -> None:
    suffix = f"|{doh_server}|{dns_timeout}|{proxy or ''}"
    normalized_hosts = {host.lower().rstrip(".") for host in hosts}
    alias_hosts = {
        HOST_ALIAS_MAP.get(host)
        for host in normalized_hosts
        if HOST_ALIAS_MAP.get(host)
    }
    all_hosts = normalized_hosts | {
        str(host).lower().rstrip(".") for host in alias_hosts
    }

    with _RUN_CACHE_LOCK:
        for host in all_hosts:
            _RUN_RESOLVED_IPS.pop(f"{host}{suffix}", None)


def _probe_tcp_latency(ip: str, port: int = 443, timeout: float = 2.0) -> float | None:
    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return time.perf_counter() - start
    except OSError:
        return None


def _rank_ips_by_latency(
    ips: list[str],
    *,
    timeout: float,
    max_workers: int = 8,
) -> tuple[list[str], dict[str, float | None]]:
    if not ips:
        return [], {}

    latency_map: dict[str, float | None] = {}
    workers = max(1, min(max_workers, len(ips)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_probe_tcp_latency, ip, 443, timeout): ip for ip in ips
        }
        for future in as_completed(futures):
            ip = futures[future]
            try:
                latency_map[ip] = future.result()
            except Exception:
                latency_map[ip] = None

    ranked = sorted(
        ips,
        key=lambda ip: (
            latency_map.get(ip) is None,
            latency_map.get(ip) if latency_map.get(ip) is not None else 9999.0,
        ),
    )
    return ranked, latency_map


def _refresh_pixez_hosts_via_dns(
    *,
    base_map: dict[str, str],
    doh_server: str,
    timeout: int,
    session: requests.Session,
    proxies: dict[str, str] | None,
) -> dict[str, str]:
    updated = dict(base_map)
    for host in list(base_map.keys()):
        all_ips = _resolve_host_ips(
            host,
            doh_server=doh_server,
            timeout=timeout,
            session=session,
            proxies=proxies,
            include_system_dns=True,
        )
        ranked, _ = _rank_ips_by_latency(
            all_ips, timeout=max(1.0, min(3.0, float(timeout)))
        )
        if ranked:
            updated[host] = ranked[0]
    return updated


def _resolve_host_ips(
    host: str,
    *,
    doh_server: str,
    timeout: int,
    session: requests.Session,
    proxies: dict[str, str] | None,
    max_doh_servers: int | None = 1,
    max_ips: int = 4,
    include_system_dns: bool = False,
) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    def add_ip(ip: str) -> None:
        if _is_ipv4(ip) and ip not in seen:
            seen.add(ip)
            deduped.append(ip)

    doh_servers = _doh_server_candidates(doh_server)
    if max_doh_servers is not None:
        doh_servers = doh_servers[: max(1, max_doh_servers)]

    for doh in doh_servers:
        ips = _resolve_a_records_via_doh(
            host,
            doh_server=doh,
            timeout=timeout,
            session=session,
            proxies=proxies,
        )
        for ip in ips:
            add_ip(ip)
            if len(deduped) >= max_ips:
                return deduped

    return deduped


def _build_pixez_ip_candidates(
    req_host: str,
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

    def add_candidate(ip: str | None) -> None:
        if ip and _is_ipv4(ip) and ip not in candidates:
            candidates.append(ip)

    builtin_ip = PIXEZ_HOST_MAP.get(req_host)
    cached_ip = host_map.get(req_host)

    # Match the local PixEz clone's practical behavior:
    # App API / OAuth stay pinned to the hard-coded IP unless users explicitly
    # refresh into a clean compatible cache; image hosts may prefer cache first.
    if req_host in PIXEZ_API_HOSTS:
        add_candidate(builtin_ip)
        add_candidate(cached_ip if cached_ip == builtin_ip else None)
    else:
        add_candidate(cached_ip)
        add_candidate(builtin_ip)

    if runtime_dns_resolve and not candidates:
        live_cache_key = f"{req_host}|{dns_server}|{dns_timeout}|{proxy or ''}"
        live_ips = _get_runtime_dns_cache(live_cache_key)
        if live_ips is None:
            live_ips = _resolve_host_ips(
                req_host,
                doh_server=dns_server,
                timeout=dns_timeout,
                session=session,
                proxies=proxies,
                max_doh_servers=1,
                include_system_dns=False,
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


def refresh_pixiv_host_map(
    *,
    dns_server: str = "doh.dns.sb",
    dns_cache_file: str = ".pixiv_host_map.json",
    dns_timeout: int = 3,
    proxy: str | None = None,
    hosts: list[str] | None = None,
) -> dict[str, str]:
    """Refresh PixEz-style host cache via DoH without requiring Pixiv auth."""
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


def _pixiv_client_time() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _pick_illust_image_url(
    illust: dict[str, Any], quality: str = "original"
) -> str | None:
    urls = _pick_illust_image_urls(illust, quality)
    return urls[0] if urls else None


def _pick_illust_image_urls(
    illust: dict[str, Any], quality: str = "original"
) -> list[str]:
    """Pick all image URLs from an illust based on quality preference.

    Args:
        illust: The illust dict from Pixiv API
        quality: "original", "medium", or "small"

    Returns:
        List of image URLs
    """
    quality_keys = {
        "original": ("original", "large", "medium", "square_medium"),
        "medium": ("large", "medium", "original", "square_medium"),
        "small": ("square_medium", "medium", "large", "original"),
    }
    keys = quality_keys.get(quality, quality_keys["original"])

    urls: list[str] = []

    # Check meta_pages for multi-page illusts
    meta_pages = illust.get("meta_pages")
    if isinstance(meta_pages, list) and meta_pages:
        for page in meta_pages:
            if isinstance(page, dict):
                image_urls = page.get("image_urls")
                if isinstance(image_urls, dict):
                    for key in keys:
                        url = image_urls.get(key)
                        if isinstance(url, str) and url:
                            urls.append(url)
                            break

    # Single page illust
    if not urls:
        meta_single = illust.get("meta_single_page")
        if isinstance(meta_single, dict):
            original = meta_single.get("original_image_url")
            if isinstance(original, str) and original:
                if quality == "small":
                    # For small quality, try to get square_medium from image_urls
                    image_urls = illust.get("image_urls")
                    if isinstance(image_urls, dict):
                        sq = image_urls.get("square_medium")
                        if isinstance(sq, str) and sq:
                            urls.append(sq)
                        else:
                            urls.append(original)
                elif quality == "medium":
                    # For medium quality, try to get large from image_urls
                    image_urls = illust.get("image_urls")
                    if isinstance(image_urls, dict):
                        large = image_urls.get("large")
                        if isinstance(large, str) and large:
                            urls.append(large)
                        else:
                            urls.append(original)
                else:
                    urls.append(original)

    # Fallback to image_urls
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
        "image_urls": _pick_illust_image_urls(illust, quality),
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
    if author_id is not None:
        uid = user.get("id")
        if str(uid) != str(author_id):
            return False
    if author_name:
        name = str(user.get("name") or "")
        if author_name.lower() not in name.lower():
            return False
    return True


def _match_illust_tag(
    illust: dict[str, Any],
    tag: str | None,
) -> bool:
    """Check if the illust's own tags contain the specified tag (case-insensitive)."""
    if not tag:
        return True
    raw_tags = illust.get("tags")
    if not isinstance(raw_tags, list):
        return False
    tag_lower = tag.lower()
    for item in raw_tags:
        if isinstance(item, dict):
            name = item.get("name")
            translated_name = item.get("translated_name")
            if isinstance(name, str) and name.lower() == tag_lower:
                return True
            if (
                isinstance(translated_name, str)
                and translated_name.lower() == tag_lower
            ):
                return True
    return False


def _is_r18_illust(illust: dict[str, Any]) -> bool:
    """Check if the illust is R18 based on x_restrict field."""
    x_restrict = illust.get("x_restrict")
    return isinstance(x_restrict, int) and x_restrict >= 1


def _safe_download_filename(url: str, fallback_id: Any) -> str:
    path = urlsplit(url).path
    name = os.path.basename(path).strip()
    if not name:
        name = f"illust_{fallback_id or 'unknown'}.bin"
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name or f"illust_{fallback_id or 'unknown'}.bin"


def _normalize_web_illust_item(item: dict[str, Any]) -> dict[str, Any]:
    illust_id = item.get("id")
    title = str(item.get("title") or "（无标题）")
    user_id = item.get("userId") or item.get("user_id")
    user_name = item.get("userName") or item.get("user_name") or "未知"
    bookmark_count = item.get("bookmarkCount") or item.get("bookmark_count")
    x_restrict = item.get("xRestrict")
    if not isinstance(x_restrict, int):
        try:
            x_restrict = int(x_restrict)
        except (TypeError, ValueError):
            x_restrict = 0

    tags_raw = item.get("tags")
    tags: list[dict[str, Any]] = []
    if isinstance(tags_raw, list):
        for tag in tags_raw:
            if isinstance(tag, str) and tag:
                tags.append({"name": tag})
            elif isinstance(tag, dict):
                name = tag.get("tag") or tag.get("name")
                translated = tag.get("translation") or tag.get("translated_name")
                normalized_tag: dict[str, Any] = {}
                if isinstance(name, str) and name:
                    normalized_tag["name"] = name
                if isinstance(translated, str) and translated:
                    normalized_tag["translated_name"] = translated
                if normalized_tag:
                    tags.append(normalized_tag)

    image_urls = (
        item.get("image_urls") if isinstance(item.get("image_urls"), dict) else {}
    )
    urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
    preview_url = (
        image_urls.get("large")
        or image_urls.get("medium")
        or urls.get("thumb")
        or item.get("url")
        or item.get("profileImageUrl")
    )
    square_url = urls.get("small") or urls.get("thumb") or preview_url

    return {
        "id": illust_id,
        "title": title,
        "total_bookmarks": bookmark_count,
        "x_restrict": x_restrict,
        "page_count": item.get("pageCount") or item.get("page_count") or 1,
        "tags": tags,
        "user": {
            "id": user_id,
            "name": user_name,
        },
        "image_urls": {
            "large": preview_url,
            "medium": preview_url,
            "square_medium": square_url,
        },
    }


def _normalize_web_user_preview(item: dict[str, Any]) -> dict[str, Any]:
    user_id = item.get("userId") or item.get("user_id")
    user_name = item.get("userName") or item.get("user_name") or "未知"
    account = item.get("userAccount") or item.get("account") or ""
    illusts_raw = item.get("illusts")
    illusts: list[dict[str, Any]] = []
    if isinstance(illusts_raw, list):
        for illust in illusts_raw:
            if isinstance(illust, dict):
                illusts.append(
                    {
                        "id": illust.get("id"),
                        "title": str(illust.get("title") or "（无标题）"),
                    }
                )
    return {
        "user": {
            "id": user_id,
            "name": user_name,
            "account": account,
            "profile": {
                "total_illusts": item.get("illustsTotal")
                or item.get("illust_total")
                or 0,
                "total_manga": item.get("mangaTotal") or item.get("manga_total") or 0,
            },
        },
        "illusts": illusts,
    }


def _extract_web_search_body(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error") is False and isinstance(payload.get("body"), dict):
        return payload["body"]
    body = payload.get("body")
    if isinstance(body, dict):
        return body
    return {}


@contextmanager
def _patched_dns_resolution(host_map: dict[str, str]):
    if not host_map:
        yield
        return

    normalized = {k.lower().rstrip("."): v for k, v in host_map.items()}
    original_getaddrinfo = socket.getaddrinfo

    # Store original function in thread-local storage for thread safety
    _thread_local._original_getaddrinfo = original_getaddrinfo
    _thread_local._dns_normalized = normalized

    def patched_getaddrinfo(host: str, *args: Any, **kwargs: Any):
        if isinstance(host, str):
            key = host.lower().rstrip(".")
            normalized_map = getattr(_thread_local, "_dns_normalized", {})
            ip = normalized_map.get(key)
            if ip:
                original_func = getattr(
                    _thread_local, "_original_getaddrinfo", original_getaddrinfo
                )
                return original_func(ip, *args, **kwargs)
        return original_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo
        # Clean up thread-local storage
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
    """Get or create a global session for connection reuse."""
    global _global_session
    if _global_session is None:
        with _session_lock:
            if _global_session is None:
                session = requests.Session()
                https_adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=3,
                )
                session.mount("https://", https_adapter)
                # Standard HTTP adapter
                http_adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=3,
                )
                session.mount("http://", http_adapter)
                _global_session = session
    return _global_session


def pixiv(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    refresh_token: str | None = None,
    access_token: str | None = None,
    bypass_sni: bool = True,
    bypass_mode: str = "pixez",
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
    """
    单入口函数：调用后即可访问 Pixiv 服务（API + 图片）。

    用法示例：
      pixiv("illust_detail", {"illust_id": 123456})
      pixiv("/v1/illust/ranking", {"mode": "day"})
      pixiv("image", {"url": "https://i.pximg.net/...jpg"})
    """
    params = params or {}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    current_user_id: int | None = None
    normalized_bypass_mode = str(bypass_mode or "pixez").strip().lower()
    if normalized_bypass_mode not in {"pixez", "accesser"}:
        normalized_bypass_mode = "pixez"
    search_budget_enabled = (
        action in {"search_illust", "search_user"} and runtime_dns_resolve
    )
    runtime_ip_candidate_limit = (
        max(1, int(search_runtime_ip_candidate_limit))
        if search_budget_enabled and search_runtime_ip_candidate_limit is not None
        else None
    )
    retryable_failure_budget = (
        max(1, int(search_retryable_failure_budget))
        if search_budget_enabled and search_retryable_failure_budget is not None
        else None
    )

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

    def send(
        method: str,
        url: str,
        *,
        req_params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        with_auth: bool = False,
        image_mode: bool = False,
    ) -> requests.Response:
        retryable_bypass_statuses = (
            {403} if action in {"search_illust", "search_user"} else set()
        )
        retryable_failure_count = 0
        stop_retry_iteration = False
        req_host = (urlsplit(url).hostname or "").lower().rstrip(".")
        is_web_request = req_host == "www.pixiv.net"
        merged_headers = {
            "User-Agent": (
                IMAGE_UA if image_mode else PIXIV_WEB_UA if is_web_request else PIXIV_UA
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
            merged_headers.setdefault("App-OS-Version", "Android 11")
            merged_headers.setdefault("App-Version", "5.0.234")
        if with_auth:
            if not access_token:
                raise ValueError("Missing access_token after auth.")
            merged_headers["Authorization"] = f"Bearer {access_token}"
        if headers:
            merged_headers.update(headers)

        req_split = urlsplit(url)
        has_proxy = bool(proxies) or bool(get_environ_proxies(url))

        def _url_with_ip(ip: str) -> str:
            netloc = ip
            if req_split.port:
                netloc = f"{ip}:{req_split.port}"
            return urlunsplit(
                (
                    req_split.scheme,
                    netloc,
                    req_split.path,
                    req_split.query,
                    req_split.fragment,
                )
            )

        def _url_with_host(host: str) -> str:
            netloc = host
            if req_split.port:
                netloc = f"{host}:{req_split.port}"
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
            return (
                last_res
                if last_res is not None
                else session.request(
                    method=method,
                    url=request_url,
                    params=req_params,
                    data=data,
                    headers=merged_headers,
                    proxies=proxies,
                    timeout=(connect_timeout, timeout),
                    verify=verify,
                )
            )

        def _do_direct_ip_request(
            ip: str,
            *,
            verify: bool,
            disable_sni: bool,
        ) -> requests.Response:
            bypass_headers = dict(merged_headers)
            bypass_headers["Host"] = req_host
            with _without_tls_sni() if disable_sni else nullcontext():
                return session.request(
                    method=method,
                    url=_url_with_ip(ip),
                    params=req_params,
                    data=data,
                    headers=bypass_headers,
                    proxies=proxies,
                    timeout=(connect_timeout, timeout),
                    verify=verify,
                )

        def _do_direct_dns_override_request(
            host: str,
            ip: str,
            *,
            verify: bool,
            disable_sni: bool,
        ) -> requests.Response:
            return _do_request(
                dns_override={host: ip},
                verify=verify,
                disable_sni=disable_sni,
            )

        def _do_alias_host_request(
            alias_host: str,
            *,
            alias_ip: str | None = None,
        ) -> requests.Response:
            target_url = _url_with_host(alias_host)
            dns_override = {alias_host: alias_ip} if alias_ip else None
            return _do_request(
                target_url=target_url,
                dns_override=dns_override,
                verify=True,
                disable_sni=False,
            )

        def _build_error_response(status_code: int, message: str) -> requests.Response:
            response = requests.Response()
            response.status_code = status_code
            response.url = url
            response._content = message.encode("utf-8")
            response.encoding = "utf-8"
            return response

        def _limit_candidates(candidates: list[str], *, label: str) -> list[str]:
            if (
                runtime_ip_candidate_limit is None
                or len(candidates) <= runtime_ip_candidate_limit
            ):
                return candidates
            logger.warning(
                "[pixivdirect] %s limiting %s candidates from %d to %d for fast fallback",
                action,
                label,
                len(candidates),
                runtime_ip_candidate_limit,
            )
            return candidates[:runtime_ip_candidate_limit]

        def _consume_retryable_failure(kind: str, *, candidate: str) -> bool:
            nonlocal retryable_failure_count
            if retryable_failure_budget is None:
                return False
            retryable_failure_count += 1
            if retryable_failure_count < retryable_failure_budget:
                return False
            logger.warning(
                "[pixivdirect] %s exhausted retryable failure budget (%d) after %s on candidate %s",
                action,
                retryable_failure_budget,
                kind,
                candidate,
            )
            return True

        if not (bypass_sni and req_host in host_map):
            return _do_request()

        # 使用代理时必须保留域名 URL；否则代理链路上的证书校验会按 IP 失败。
        if has_proxy:
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
        ip_candidates = _limit_candidates(ip_candidates, label="pixez")

        last_exc: Exception | None = None
        last_res: requests.Response | None = None
        attempted = False
        for ip in ip_candidates:
            try:
                attempted = True
                res = _do_direct_dns_override_request(
                    req_host,
                    ip,
                    verify=False,
                    disable_sni=True,
                )
                last_res = res
                if res.ok:
                    return res
                if runtime_dns_resolve and res.status_code in retryable_bypass_statuses:
                    if _consume_retryable_failure("status", candidate=ip):
                        stop_retry_iteration = True
                        break
                    logger.warning(
                        "[pixivdirect] %s returned status %s via PixEz-style candidate %s, trying accessor-backup fallback",
                        action,
                        res.status_code,
                        ip,
                    )
                else:
                    return res
            except (
                RequestsConnectionError,
                RequestsTimeout,
                RequestsSSLError,
            ) as exc:
                last_exc = exc
                logger.warning(
                    "[pixivdirect] %s failed on PixEz-style candidate %s error=%s",
                    action,
                    ip,
                    exc,
                )
                if _consume_retryable_failure("network error", candidate=ip):
                    stop_retry_iteration = True
                    break

            if stop_retry_iteration:
                break

        if stop_retry_iteration:
            logger.warning(
                "[pixivdirect] %s stopping App API candidate iteration early for fast fallback",
                action,
            )

        alias_host = HOST_ALIAS_MAP.get(req_host)
        if (
            alias_host
            and runtime_dns_resolve
            and not stop_retry_iteration
            and normalized_bypass_mode == "pixez"
        ):
            alias_cache_key = f"{alias_host}|{dns_server}|{dns_timeout}|{proxy or ''}"
            alias_ips = _get_runtime_dns_cache(alias_cache_key)
            if alias_ips is None:
                alias_ips = _resolve_host_ips(
                    alias_host,
                    doh_server=dns_server,
                    timeout=dns_timeout,
                    session=session,
                    proxies=proxies,
                    max_doh_servers=None,
                )
                _set_runtime_dns_cache(alias_cache_key, alias_ips)
            ranked_alias_ips, _ = _rank_ips_by_latency(
                alias_ips, timeout=max(0.5, connect_probe_timeout)
            )
            alias_candidates = _limit_candidates(
                [ip for ip in ranked_alias_ips if ip not in ip_candidates],
                label="alias DNS",
            )
            for ip in alias_candidates:
                try:
                    attempted = True
                    res = _do_alias_host_request(alias_host, alias_ip=ip)
                    last_res = res
                    if res.ok:
                        return res
                    if (
                        runtime_dns_resolve
                        and res.status_code in retryable_bypass_statuses
                    ):
                        if _consume_retryable_failure("status", candidate=ip):
                            stop_retry_iteration = True
                            break
                        logger.warning(
                            "[pixivdirect] %s returned status %s via accessor-backup alias %s candidate %s, trying next candidate",
                            action,
                            res.status_code,
                            alias_host,
                            ip,
                        )
                        continue
                    return res
                except (
                    RequestsConnectionError,
                    RequestsTimeout,
                    RequestsSSLError,
                ) as exc:
                    last_exc = exc
                    logger.warning(
                        "[pixivdirect] %s failed on accessor-backup alias %s candidate %s error=%s",
                        action,
                        alias_host,
                        ip,
                        exc,
                    )
                    if _consume_retryable_failure("network error", candidate=ip):
                        stop_retry_iteration = True
                        break
                    continue

        # 搜索接口在所有 IP 候选都返回 403 时，再补一次原域名直连，
        # 避免固定 IP/别名 IP 全部被风控但域名链路仍可用的情况。
        if (
            attempted
            and runtime_dns_resolve
            and last_res is not None
            and last_res.status_code in retryable_bypass_statuses
        ):
            logger.warning(
                "[pixivdirect] %s exhausted IP candidates with status %s, trying direct domain request",
                action,
                last_res.status_code,
            )
            try:
                return _do_request()
            except (RequestsConnectionError, RequestsTimeout, RequestsSSLError) as exc:
                last_exc = exc

        # 只在没有任何可用 IP 候选时，才回退到原域名直连。
        if not attempted:
            try:
                return _do_request()
            except (RequestsConnectionError, RequestsTimeout, RequestsSSLError) as exc:
                last_exc = exc
                if search_budget_enabled:
                    return _build_error_response(504, str(exc))
        if last_res is not None:
            return last_res
        if last_exc:
            if search_budget_enabled:
                return _build_error_response(504, str(last_exc))
            raise last_exc
        return _do_request()

    requires_auth = action not in AUTH_OPTIONAL_ACTIONS

    # 1) 若请求需要鉴权且没给 access_token，则自动用 refresh_token 换取。
    if requires_auth and not access_token:
        refresh_token = (
            refresh_token
            or os.getenv("PIXIV_REFRESH_TOKEN")
            or _read_refresh_token_file()
        )
        if not refresh_token:
            raise ValueError(
                "Missing refresh_token. Pass it or set PIXIV_REFRESH_TOKEN."
            )

        now = _pixiv_client_time()
        x_client_hash = hashlib.md5((now + PIXIV_HASH_SALT).encode("utf-8")).hexdigest()
        token_res = send(
            "POST",
            OAUTH_URL,
            data={
                "client_id": PIXIV_CLIENT_ID,
                "client_secret": PIXIV_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "include_policy": "true",
                "refresh_token": refresh_token,
            },
            headers={
                "X-Client-Time": now,
                "X-Client-Hash": x_client_hash,
                "App-OS": "Android",
                "App-OS-Version": "Android 11",
                "App-Version": "5.0.234",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        token_json = token_res.json()
        access_token = token_json.get("access_token")
        refresh_token = token_json.get("refresh_token") or refresh_token
        token_user = token_json.get("user")
        if isinstance(token_user, dict):
            token_uid = token_user.get("id")
            if isinstance(token_uid, int):
                current_user_id = token_uid
            elif isinstance(token_uid, str) and token_uid.isdigit():
                current_user_id = int(token_uid)
        if not access_token:
            return {
                "ok": False,
                "action": "auth",
                "status": token_res.status_code,
                "error": token_json,
            }

    if action == "bookmark_metadata_page":
        bookmark_user_id = params.get("bookmark_user_id")
        if bookmark_user_id is None:
            bookmark_user_id = params.get("user_id")
        if bookmark_user_id is None:
            bookmark_user_id = current_user_id
        if bookmark_user_id is None:
            raise ValueError(
                "Missing bookmark_user_id/user_id. "
                "Pass it in params or provide refresh_token so SDK can infer current user."
            )

        restrict = str(params.get("restrict") or "public").strip().lower()
        if restrict not in {"public", "private"}:
            restrict = "public"

        next_url = params.get("next_url")
        if isinstance(next_url, str) and next_url.strip():
            request_url = next_url.strip()
            request_params = None
        else:
            request_url = f"{API_BASE}{API_ACTIONS['user_bookmarks_illust']}"
            request_params = {
                "user_id": bookmark_user_id,
                "restrict": restrict,
            }
            offset = params.get("offset")
            if offset is not None:
                request_params["offset"] = max(0, int(offset))
            tag = params.get("tag")
            if isinstance(tag, str) and tag.strip():
                request_params["tag"] = tag.strip()

        page_res = send("GET", request_url, req_params=request_params, with_auth=True)
        try:
            page_data = page_res.json()
        except Exception:
            page_data = {"raw": page_res.text}

        illusts = page_data.get("illusts") if isinstance(page_data, dict) else None
        metadata_items = (
            [
                _illust_to_metadata_entry(
                    illust,
                    restrict=restrict,
                    quality=str(params.get("quality") or "original"),
                )
                for illust in illusts
                if isinstance(illust, dict)
            ]
            if isinstance(illusts, list)
            else []
        )

        return {
            "ok": page_res.ok,
            "action": action,
            "status": page_res.status_code,
            "data": {
                "items": metadata_items,
                "illusts": illusts if isinstance(illusts, list) else [],
                "next_url": page_data.get("next_url")
                if isinstance(page_data, dict)
                else None,
            },
            "error": page_data if not page_res.ok else None,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # 2) 收藏随机图（支持 tag / 作者筛选）。
    if action in {"random_bookmark_image", "random_bookmark", "random_bookmark_by_tag"}:
        bookmark_user_id = params.get("bookmark_user_id")
        if bookmark_user_id is None:
            bookmark_user_id = params.get("user_id")
        if bookmark_user_id is None:
            bookmark_user_id = current_user_id
        if bookmark_user_id is None:
            raise ValueError(
                "Missing bookmark_user_id/user_id. "
                "Pass it in params or provide refresh_token so SDK can infer current user."
            )

        tag = params.get("tag")
        tag = str(tag) if tag else None

        author_id_raw = params.get("author_id")
        if author_id_raw is None:
            author_id_raw = params.get("author_user_id")
        author_id: int | None = None
        if author_id_raw is not None and str(author_id_raw).strip():
            author_id = int(str(author_id_raw).strip())

        author_name_raw = params.get("author")
        if author_name_raw is None:
            author_name_raw = params.get("author_name")
        author_name = str(author_name_raw).strip() if author_name_raw else None

        restrict_raw = params.get("restrict")
        restrict = str(restrict_raw or "public").strip().lower()
        if restrict not in {"public", "private"}:
            restrict = "public"

        # Exclude sent IDs for unique mode
        exclude_ids_raw = params.get("exclude_ids")
        exclude_ids: set[int] = set()
        if isinstance(exclude_ids_raw, (list, set)):
            exclude_ids = {
                int(i)
                for i in exclude_ids_raw
                if isinstance(i, (int, str)) and str(i).isdigit()
            }

        # Thorough random mode
        thorough_random = str(params.get("random", "false")).lower() in (
            "true",
            "1",
            "yes",
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
        max_pages_raw = params.get("max_pages")
        max_pages = 3
        if max_pages_raw is not None and str(max_pages_raw).strip():
            max_pages = max(1, int(str(max_pages_raw)))

        # Extended scan for unique mode
        extended_scan = params.get("extended_scan", False)
        max_unique_scan_pages = 9
        if extended_scan and params.get("max_unique_scan_pages") is not None:
            max_unique_scan_pages = max(
                1, int(str(params.get("max_unique_scan_pages")))
            )
        max_scan_pages = max_unique_scan_pages if extended_scan else max_pages
        status_code = 200

        # Collect all candidates for thorough random mode
        all_candidates: list[dict[str, Any]] = [] if thorough_random else []

        # First, try with bookmark tag filter (API-level)
        # If no results, fall back to filtering by illust's own tags
        use_illust_tag_filter = False

        next_url: str | None = f"{API_BASE}{API_ACTIONS['user_bookmarks_illust']}"
        next_params: dict[str, Any] | None = list_params

        while next_url:
            page_res = send("GET", next_url, req_params=next_params, with_auth=True)
            status_code = page_res.status_code
            if not page_res.ok:
                try:
                    err_data = page_res.json()
                except Exception:
                    err_data = {"raw": page_res.text}
                return {
                    "ok": False,
                    "action": action,
                    "status": status_code,
                    "error": err_data,
                }

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
                    if use_illust_tag_filter and not _match_illust_tag(illust, tag):
                        continue
                    # Skip excluded IDs
                    illust_id = illust.get("id")
                    if isinstance(illust_id, int) and illust_id in exclude_ids:
                        continue
                    matched += 1
                    if thorough_random:
                        all_candidates.append(illust)
                    elif random.randrange(matched) == 0:
                        sampled = illust

            next_url_val = page_data.get("next_url")
            if isinstance(next_url_val, str) and next_url_val:
                next_url = next_url_val
                next_params = None
            else:
                next_url = None
            if pages >= max_scan_pages:
                next_url = None

        # If no results with bookmark tag, retry filtering by illust's own tags
        if not sampled and not all_candidates and tag and not use_illust_tag_filter:
            use_illust_tag_filter = True
            matched = 0
            pages = 0
            next_url = f"{API_BASE}{API_ACTIONS['user_bookmarks_illust']}"
            next_params = {"user_id": bookmark_user_id, "restrict": restrict}

            while next_url:
                page_res = send("GET", next_url, req_params=next_params, with_auth=True)
                status_code = page_res.status_code
                if not page_res.ok:
                    break

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
                        if not _match_illust_tag(illust, tag):
                            continue
                        # Skip excluded IDs
                        illust_id = illust.get("id")
                        if isinstance(illust_id, int) and illust_id in exclude_ids:
                            continue
                        matched += 1
                        if thorough_random:
                            all_candidates.append(illust)
                        elif random.randrange(matched) == 0:
                            sampled = illust

                next_url_val = page_data.get("next_url")
                if isinstance(next_url_val, str) and next_url_val:
                    next_url = next_url_val
                    next_params = None
                else:
                    next_url = None
                if pages >= max_scan_pages:
                    next_url = None

        # Thorough random: pick random from all candidates
        if thorough_random and all_candidates:
            sampled = random.choice(all_candidates)

        if not sampled:
            return {
                "ok": False,
                "action": action,
                "status": status_code,
                "error": {
                    "message": "No bookmarked illust matched filters.",
                    "filters": {
                        "tag": tag,
                        "author_id": author_id,
                        "author": author_name,
                        "restrict": restrict,
                    },
                },
            }

        sampled_user = (
            sampled.get("user") if isinstance(sampled.get("user"), dict) else {}
        )
        tags: list[str] = []
        raw_tags = sampled.get("tags")
        if isinstance(raw_tags, list):
            for item in raw_tags:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        tags.append(name)

        return {
            "ok": True,
            "action": action,
            "status": status_code,
            "data": {
                "id": sampled.get("id"),
                "title": sampled.get("title"),
                "author": {
                    "id": sampled_user.get("id"),
                    "name": sampled_user.get("name"),
                },
                "tags": tags,
                "image_url": _pick_illust_image_url(
                    sampled, str(params.get("quality", "original"))
                ),
                "illust": sampled,
                "matched_count": matched,
                "pages_scanned": pages,
                "filters": {
                    "tag": tag,
                    "author_id": author_id,
                    "author": author_name,
                    "restrict": restrict,
                    "bookmark_user_id": bookmark_user_id,
                },
            },
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # 3) 图片访问。
    if action == "image":
        image_url = params.get("url")
        if not image_url:
            raise ValueError("action=image requires params.url")
        image_res = send("GET", str(image_url), image_mode=True)
        return {
            "ok": image_res.ok,
            "action": action,
            "status": image_res.status_code,
            "content_type": image_res.headers.get("Content-Type"),
            "content": image_res.content,
        }

    # 3.1) 动图元数据访问。
    if action == "ugoira_metadata":
        illust_id = params.get("illust_id")
        if not illust_id:
            raise ValueError("action=ugoira_metadata requires params.illust_id")
        api_url = f"{API_BASE}/v1/ugoira/metadata"
        res = send("GET", api_url, req_params={"illust_id": illust_id}, with_auth=True)
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text}
        return {
            "ok": res.ok,
            "action": action,
            "status": res.status_code,
            "data": data,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # 3.2) 动图 zip 文件下载。
    if action == "ugoira_zip":
        zip_url = params.get("url")
        if not zip_url:
            raise ValueError("action=ugoira_zip requires params.url")
        zip_res = send("GET", str(zip_url), image_mode=True)
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
        web_params: dict[str, Any] = {
            "word": keyword,
            "p": page,
        }
        sort = str(params.get("sort") or "date_desc").strip().lower()
        mapped_sort = WEB_SEARCH_SORT_MAP.get(sort)
        if mapped_sort and action == "web_search_illust":
            web_params["order"] = mapped_sort

        target = str(params.get("search_target") or "").strip().lower()
        mapped_target = WEB_SEARCH_TARGET_MAP.get(target)
        if mapped_target and action == "web_search_illust":
            web_params["s_mode"] = mapped_target

        duration = str(params.get("duration") or "").strip().lower()
        mapped_duration = WEB_SEARCH_DURATION_MAP.get(duration)
        if mapped_duration and action == "web_search_illust":
            web_params["mode"] = mapped_duration

        web_res = send(
            "GET",
            endpoint,
            req_params=web_params,
            headers={
                "Referer": PIXIV_WEB_REFERER,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            payload = web_res.json()
        except Exception:
            payload = {"error": True, "message": web_res.text}

        body = _extract_web_search_body(payload if isinstance(payload, dict) else {})
        if action == "web_search_illust":
            illust_container = body.get("illustManga")
            if not isinstance(illust_container, dict):
                illust_container = body
            items = illust_container.get("data")
            if not isinstance(items, list):
                items = []
            total = illust_container.get("total")
            normalized = [
                _normalize_web_illust_item(item)
                for item in items
                if isinstance(item, dict)
            ]
            data = {"illusts": normalized, "total": total}
        else:
            users = body.get("users")
            if not isinstance(users, list):
                users = body.get("user_previews")
            if not isinstance(users, list):
                users = []
            total = body.get("total")
            data = {
                "user_previews": [
                    _normalize_web_user_preview(item)
                    for item in users
                    if isinstance(item, dict)
                ],
                "total": total,
            }

        return {
            "ok": web_res.ok and not bool(payload.get("error"))
            if isinstance(payload, dict)
            else web_res.ok,
            "action": action,
            "status": web_res.status_code,
            "data": data,
            "error": payload.get("message") if isinstance(payload, dict) else None,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # 4) Pixiv API 访问。
    path = action if action.startswith("/") else API_ACTIONS.get(action)
    if not path:
        raise ValueError(f"Unknown action: {action}. Use mapped action or /v1/... path")

    api_url = f"{API_BASE}{path}"

    api_params = dict(params)
    if action in APP_API_FILTER_ACTIONS:
        api_params.setdefault("filter", PIXIV_APP_FILTER)
    if action == "search_illust":
        if isinstance(api_params.get("include_translated_tag_results"), bool):
            api_params["include_translated_tag_results"] = (
                "true" if api_params["include_translated_tag_results"] else "false"
            )
        if isinstance(api_params.get("merge_plain_keyword_results"), bool):
            api_params["merge_plain_keyword_results"] = (
                "true" if api_params["merge_plain_keyword_results"] else "false"
            )
        api_params.setdefault("merge_plain_keyword_results", "true")
    elif action == "search_user":
        api_params.pop("sort", None)
        api_params.pop("search_target", None)

    res = send("GET", api_url, req_params=api_params, with_auth=True)

    try:
        data = res.json()
    except Exception:
        data = {"raw": res.text}

    return {
        "ok": res.ok,
        "action": action,
        "status": res.status_code,
        "data": data,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "host_map": host_map if dns_update_hosts else None,
    }


def main() -> None:
    # 示例：从当前账号收藏中随机抽一张图（可按 tag / 作者筛选）
    result = pixiv(
        "random_bookmark_image",
        {
            # "tag": "R-18",
            # "author_id": 1234567,
            # "author": "作者名",
            "restrict": "public",
            "max_pages": 3,
        },
        bypass_sni=True,
        dns_update_hosts=True,
        dns_timeout=3,
        dns_server="doh.dns.sb",
        dns_cache_file=".pixiv_host_map.json",
        runtime_dns_resolve=False,
        max_retries=3,
    )
    print("status:", result["status"], "ok:", result["ok"])
    data = result.get("data") or {}
    if result.get("ok"):
        print("picked:", data.get("title"), f"(id={data.get('id')})")
        print("author:", (data.get("author") or {}).get("name"))
        image_url = data.get("image_url")
        print("image_url:", image_url)

        if isinstance(image_url, str) and image_url:
            image_result = pixiv(
                "image",
                {"url": image_url},
                access_token=result.get("access_token"),
                refresh_token=result.get("refresh_token"),
                bypass_sni=True,
                dns_update_hosts=True,
                dns_timeout=3,
                dns_server="doh.dns.sb",
                dns_cache_file=".pixiv_host_map.json",
                runtime_dns_resolve=False,
                max_retries=3,
            )
            if image_result.get("ok"):
                script_dir = os.path.dirname(os.path.abspath(__file__))
                out_dir = os.path.join(script_dir, "temp")
                os.makedirs(out_dir, exist_ok=True)
                out_name = _safe_download_filename(image_url, data.get("id"))
                out_path = os.path.join(out_dir, out_name)
                with open(out_path, "wb") as f:
                    f.write(image_result.get("content") or b"")
                print("downloaded:", out_path)
                print("content_type:", image_result.get("content_type"))
            else:
                print("image download failed:", image_result.get("status"))


if __name__ == "__main__":
    main()

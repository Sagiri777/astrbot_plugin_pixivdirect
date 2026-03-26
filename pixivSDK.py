from __future__ import annotations

import hashlib
import json
import os
import random
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError as RequestsSSLError
from requests.exceptions import Timeout as RequestsTimeout
from requests.utils import get_environ_proxies

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# PixEz host map: fixed IPv4 for CN SNI bypass.
PIXEZ_HOST_MAP: dict[str, str] = {
    "app-api.pixiv.net": "210.140.139.155",
    "oauth.secure.pixiv.net": "210.140.139.155",
    "i.pximg.net": "210.140.139.133",
    "s.pximg.net": "210.140.139.133",
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
IMAGE_UA = "PixivIOSApp/5.8.0"
IMAGE_REFERER = "https://app-api.pixiv.net/"

# Process-level caches for runtime DNS resolve.
_RUN_RESOLVED_IPS: dict[str, list[str]] = {}
_RUN_CACHE_LOCK = threading.Lock()

# Thread-local storage for DNS patching (thread-safe)
_thread_local = threading.local()

# Global session pool for connection reuse
_global_session: requests.Session | None = None
_session_lock = threading.Lock()

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


class _HostHeaderSSLAdapter(HTTPAdapter):
    """Use Host header as TLS assert_hostname when connecting to IP directly.

    This adapter disables check_hostname in the SSL context to allow
    connecting to IP addresses while still validating the certificate
    against the Host header domain (similar to pixez/Accesser approach).
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_REQUIRED
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any):
        kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def send(self, request: requests.PreparedRequest, **kwargs: Any):
        host_header = None
        for key, value in request.headers.items():
            if key.lower() == "host":
                host_header = value
                break
        if host_header and ":" in host_header:
            host_header = host_header.split(":", 1)[0]
        pool_kw = self.poolmanager.connection_pool_kw
        if host_header:
            pool_kw["assert_hostname"] = str(host_header)
        else:
            pool_kw.pop("assert_hostname", None)
        return super().send(request, **kwargs)


def _is_ipv4(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}",
            value,
        )
    )


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
    ip_candidates = [item.get("data") for item in answers if isinstance(item, dict)]
    deduped: list[str] = []
    seen: set[str] = set()
    for ip in ip_candidates:
        if isinstance(ip, str) and _is_ipv4(ip) and ip not in seen:
            seen.add(ip)
            deduped.append(ip)
    return deduped


def _doh_server_candidates(primary: str) -> list[str]:
    # Note:
    # - Aliyun public DNS (Do53): 223.5.5.5 / 223.6.6.6
    # - Aliyun public DNS IPv6 (Do53): 2400:3200::1 / 2400:3200:baba::1
    # This function builds DoH endpoints, so Ali uses dns.alidns.com here.
    defaults = [
        "https://doh.dns.sb/dns-query",
        "https://cloudflare-dns.com/dns-query",
    ]
    primary_normalized = (
        primary
        if primary.startswith("http://") or primary.startswith("https://")
        else f"https://{primary}/dns-query"
    )
    candidates = [primary_normalized]
    for server in defaults:
        if server not in candidates:
            candidates.append(server)
    return candidates


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
            include_system_dns=False,
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
    max_doh_servers: int | None = None,
    max_ips: int = 6,
    include_system_dns: bool = True,
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

    if include_system_dns:
        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            return deduped
        for info in infos:
            ip = info[4][0]
            add_ip(ip)
            if len(deduped) >= max_ips:
                return deduped
    return deduped


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


def _read_refresh_token_file(path: str = ".pixiv_refresh_token") -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
            return token or None
    except FileNotFoundError:
        return None


def _pixiv_client_time() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _pick_illust_image_url(illust: dict[str, Any]) -> str | None:
    meta_single = illust.get("meta_single_page")
    if isinstance(meta_single, dict):
        original = meta_single.get("original_image_url")
        if isinstance(original, str) and original:
            return original
    meta_pages = illust.get("meta_pages")
    if isinstance(meta_pages, list) and meta_pages:
        first = meta_pages[0]
        if isinstance(first, dict):
            image_urls = first.get("image_urls")
            if isinstance(image_urls, dict):
                for key in ("original", "large", "medium", "square_medium"):
                    url = image_urls.get(key)
                    if isinstance(url, str) and url:
                        return url
    image_urls = illust.get("image_urls")
    if isinstance(image_urls, dict):
        for key in ("large", "medium", "square_medium"):
            url = image_urls.get(key)
            if isinstance(url, str) and url:
                return url
    return None


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


def _get_session() -> requests.Session:
    """Get or create a global session for connection reuse."""
    global _global_session
    if _global_session is None:
        with _session_lock:
            if _global_session is None:
                session = requests.Session()
                # Use _HostHeaderSSLAdapter for HTTPS with custom SSL context
                # that disables check_hostname (similar to pixez/Accesser)
                https_adapter = _HostHeaderSSLAdapter(
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
    accept_language: str = "zh-CN",
    proxy: str | None = None,
    timeout: int = 30,
    dns_timeout: int = 3,
    dns_update_hosts: bool = False,
    dns_server: str = "doh.dns.sb",
    dns_cache_file: str = ".pixiv_host_map.json",
    runtime_dns_resolve: bool = False,
    max_retries: int = 3,
    connect_probe_timeout: float = 2.0,
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
        merged_headers = {
            "User-Agent": IMAGE_UA if image_mode else PIXIV_UA,
            "Accept-Language": accept_language,
        }
        if image_mode:
            merged_headers["Referer"] = IMAGE_REFERER
        if with_auth:
            if not access_token:
                raise ValueError("Missing access_token after auth.")
            merged_headers["Authorization"] = f"Bearer {access_token}"
        if headers:
            merged_headers.update(headers)

        req_host = (urlsplit(url).hostname or "").lower().rstrip(".")
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

        def _do_request(
            dns_override: dict[str, str] | None = None,
        ) -> requests.Response:
            last_res: requests.Response | None = None
            for attempt in range(max_retries + 1):
                with _patched_dns_resolution(dns_override or {}):
                    res = session.request(
                        method=method,
                        url=url,
                        params=req_params,
                        data=data,
                        headers=merged_headers,
                        proxies=proxies,
                        timeout=(8, timeout),
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
                    url=url,
                    params=req_params,
                    data=data,
                    headers=merged_headers,
                    proxies=proxies,
                    timeout=(8, timeout),
                )
            )

        if not (bypass_sni and req_host in host_map):
            return _do_request()

        # 使用代理时必须保留域名 URL；否则代理链路上的证书校验会按 IP 失败。
        if has_proxy:
            return _do_request()

        # Accesser 思路：用 IP 建连 + Host 校验，避免域名 SNI。
        # 连接失败时依次尝试：缓存 IP -> 目标域名 DoH IP -> 系统 DNS 回退。
        ip_candidates: list[str] = []
        builtin_ip = PIXEZ_HOST_MAP.get(req_host)
        if builtin_ip:
            ip_candidates.append(builtin_ip)

        cached_ip = host_map.get(req_host)
        if cached_ip and cached_ip not in ip_candidates:
            ip_candidates.append(cached_ip)

        if runtime_dns_resolve:
            live_cache_key = f"{req_host}|{dns_server}|{dns_timeout}|{proxy or ''}"
            live_ips = _get_runtime_dns_cache(live_cache_key)
            if live_ips is None:
                live_ips = _resolve_host_ips(
                    req_host,
                    doh_server=dns_server,
                    timeout=dns_timeout,
                    session=session,
                    proxies=proxies,
                    max_doh_servers=None,
                )
                _set_runtime_dns_cache(live_cache_key, live_ips)
            ranked_live_ips, _ = _rank_ips_by_latency(
                live_ips, timeout=max(0.5, connect_probe_timeout)
            )
            for ip in ranked_live_ips:
                if ip not in ip_candidates:
                    ip_candidates.append(ip)

        last_exc: Exception | None = None
        attempted = False
        for ip in ip_candidates:
            try:
                attempted = True
                bypass_headers = dict(merged_headers)
                bypass_headers["Host"] = req_host
                return session.request(
                    method=method,
                    url=_url_with_ip(ip),
                    params=req_params,
                    data=data,
                    headers=bypass_headers,
                    proxies=proxies,
                    timeout=(8, timeout),
                )
            except (RequestsConnectionError, RequestsTimeout, RequestsSSLError) as exc:
                last_exc = exc
                continue

        # 仅在主域名候选全部失败后，再尝试 Accesser 风格的别名域名解析。
        alias_host = HOST_ALIAS_MAP.get(req_host)
        if alias_host and runtime_dns_resolve:
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
            for ip in ranked_alias_ips:
                if ip in ip_candidates:
                    continue
                try:
                    attempted = True
                    bypass_headers = dict(merged_headers)
                    bypass_headers["Host"] = req_host
                    return session.request(
                        method=method,
                        url=_url_with_ip(ip),
                        params=req_params,
                        data=data,
                        headers=bypass_headers,
                        proxies=proxies,
                        timeout=(8, timeout),
                    )
                except (
                    RequestsConnectionError,
                    RequestsTimeout,
                    RequestsSSLError,
                ) as exc:
                    last_exc = exc
                    continue

        # 只在没有任何可用 IP 候选时，才回退到原域名直连。
        if not attempted:
            try:
                return _do_request()
            except (RequestsConnectionError, RequestsTimeout, RequestsSSLError) as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        return _do_request()

    # 1) 若没给 access_token，则自动用 refresh_token 换取。
    if not access_token:
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
        max_scan_pages = 9 if extended_scan else max_pages
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
                "image_url": _pick_illust_image_url(sampled),
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

    # 4) Pixiv API 访问。
    path = action if action.startswith("/") else API_ACTIONS.get(action)
    if not path:
        raise ValueError(f"Unknown action: {action}. Use mapped action or /v1/... path")

    api_url = f"{API_BASE}{path}"
    res = send("GET", api_url, req_params=params, with_auth=True)

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

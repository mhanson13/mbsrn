from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


class UnsafePublicURLError(ValueError):
    pass


def normalize_public_http_url(value: object, *, require_dns: bool = True) -> str:
    raw_value = str(value or "").strip()
    try:
        parsed = urlsplit(raw_value)
    except ValueError as exc:
        raise UnsafePublicURLError("URL is invalid.") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafePublicURLError("URL must use http or https.")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafePublicURLError("URL must include a public host without credentials.")
    if is_disallowed_host(parsed.hostname, require_dns=require_dns):
        raise UnsafePublicURLError("URL host is not allowed.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafePublicURLError("URL port is invalid.") from exc
    normalized_netloc = parsed.hostname.lower().rstrip(".")
    if port is not None:
        normalized_netloc = f"{normalized_netloc}:{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            normalized_netloc,
            parsed.path or "/",
            parsed.query or "",
            "",
        )
    )


def is_disallowed_host(hostname: str | None, *, require_dns: bool = False) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal", "metadata"}:
        return True
    if host.endswith(".localhost") or host.endswith(".local"):
        return True

    try:
        direct_ip = ipaddress.ip_address(host)
    except ValueError:
        direct_ip = None
    if direct_ip is not None:
        return is_disallowed_ip(direct_ip)

    try:
        resolved_ips = resolve_host_ips(host)
    except OSError:
        return bool(require_dns)
    if not resolved_ips:
        return bool(require_dns)
    return any(is_disallowed_ip(resolved_ip) for resolved_ip in resolved_ips)


def resolve_public_host_ips(hostname: str) -> tuple[str, ...]:
    host = str(hostname or "").strip().lower().rstrip(".")
    if not host or is_disallowed_host(host, require_dns=True):
        raise UnsafePublicURLError("URL host is not allowed.")
    try:
        resolved_ips = resolve_host_ips(host)
    except OSError as exc:
        raise UnsafePublicURLError("URL host is not allowed.") from exc
    public_ips = tuple(str(item) for item in resolved_ips if not is_disallowed_ip(item))
    if not public_ips:
        raise UnsafePublicURLError("URL host is not allowed.")
    return public_ips


def resolve_host_ips(hostname: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    normalized: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for item in resolved:
        if not isinstance(item, tuple) or len(item) < 5:
            continue
        sockaddr = item[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        candidate = sockaddr[0]
        try:
            resolved_ip = ipaddress.ip_address(str(candidate))
        except ValueError:
            continue
        key = str(resolved_ip)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(resolved_ip)
    return tuple(normalized)


def is_disallowed_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_unspecified
        or value.is_reserved
    )


def same_site_www_equivalent(source_url: str, candidate_url: str) -> bool:
    try:
        source = urlsplit(source_url)
        candidate = urlsplit(candidate_url)
    except ValueError:
        return False
    if source.scheme.lower() not in {"http", "https"} or candidate.scheme.lower() not in {"http", "https"}:
        return False
    source_host = (source.hostname or "").lower().rstrip(".")
    candidate_host = (candidate.hostname or "").lower().rstrip(".")
    if not source_host or not candidate_host:
        return False

    def normalize_host(host: str) -> str:
        return host[4:] if host.startswith("www.") else host

    return normalize_host(source_host) == normalize_host(candidate_host)

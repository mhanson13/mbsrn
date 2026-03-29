#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_EFFECTIVE_HOST_QUERY_KEYS = ("host", "hostaddr", "unix_sock")
_ALLOWED_DB_CONNECTION_MODES = {"direct", "cloudsql_proxy"}


@dataclass(frozen=True)
class DatabaseUrlDiagnostics:
    scheme: str
    query_params_present: bool
    query_param_keys: tuple[str, ...]
    effective_target_source: str
    effective_target_kind: str
    db_connection_mode: str
    socket_style_detected: bool
    loopback_detected: bool
    proxy_mode_exception_applied: bool


def _normalize_host(raw: str | None) -> str:
    if raw is None:
        return ""
    value = raw.strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip().lower()
    return value


def _first_non_empty_query_value(parsed_query: dict[str, list[str]], key: str) -> str | None:
    for raw in parsed_query.get(key, []):
        value = raw.strip()
        if value:
            return value
    return None


def _resolve_effective_target(parsed_query: dict[str, list[str]], parsed_hostname: str | None) -> tuple[str, str, bool]:
    for key in _EFFECTIVE_HOST_QUERY_KEYS:
        value = _first_non_empty_query_value(parsed_query, key)
        if value is None:
            continue
        if value.startswith("/"):
            return (f"query:{key}", "unix_socket_path", True)
        normalized = _normalize_host(value)
        if normalized:
            return (f"query:{key}", normalized, False)

    normalized_host = _normalize_host(parsed_hostname)
    if normalized_host:
        return ("url:hostname", normalized_host, False)
    return ("unresolved", "", False)


def _normalize_db_connection_mode(raw_mode: str | None) -> str:
    normalized = (raw_mode or "").strip().lower()
    if not normalized:
        return "direct"
    return normalized


def analyze_database_url(database_url: str, *, db_connection_mode: str) -> tuple[bool, str, DatabaseUrlDiagnostics]:
    normalized_mode = _normalize_db_connection_mode(db_connection_mode)
    if normalized_mode not in _ALLOWED_DB_CONNECTION_MODES:
        diagnostics = DatabaseUrlDiagnostics(
            scheme="",
            query_params_present=False,
            query_param_keys=(),
            effective_target_source="unresolved",
            effective_target_kind="invalid_connection_mode",
            db_connection_mode=normalized_mode,
            socket_style_detected=False,
            loopback_detected=False,
            proxy_mode_exception_applied=False,
        )
        return (
            False,
            (
                "DB_CONNECTION_MODE must be one of: "
                + ", ".join(sorted(_ALLOWED_DB_CONNECTION_MODES))
            ),
            diagnostics,
        )

    raw_url = database_url.strip()
    if not raw_url:
        diagnostics = DatabaseUrlDiagnostics(
            scheme="",
            query_params_present=False,
            query_param_keys=(),
            effective_target_source="unresolved",
            effective_target_kind="missing_url",
            db_connection_mode=normalized_mode,
            socket_style_detected=False,
            loopback_detected=False,
            proxy_mode_exception_applied=False,
        )
        return False, "DATABASE_URL is required for production deploy preflight validation.", diagnostics

    parsed = urlsplit(raw_url)
    query = parse_qs(parsed.query, keep_blank_values=False)
    query_keys = tuple(sorted(query.keys()))
    source, target, socket_style = _resolve_effective_target(query, parsed.hostname)
    scheme = parsed.scheme.strip().lower()
    url_hostname = _normalize_host(parsed.hostname)

    if not scheme:
        diagnostics = DatabaseUrlDiagnostics(
            scheme="",
            query_params_present=bool(query_keys),
            query_param_keys=query_keys,
            effective_target_source=source,
            effective_target_kind="invalid_url_missing_scheme",
            db_connection_mode=normalized_mode,
            socket_style_detected=socket_style,
            loopback_detected=False,
            proxy_mode_exception_applied=False,
        )
        return False, "DATABASE_URL must be a valid absolute URL for production deploy.", diagnostics

    if url_hostname in _LOOPBACK_HOSTS:
        proxy_mode_exception_applied = normalized_mode == "cloudsql_proxy"
        diagnostics = DatabaseUrlDiagnostics(
            scheme=scheme,
            query_params_present=bool(query_keys),
            query_param_keys=query_keys,
            effective_target_source="url:hostname",
            effective_target_kind="loopback_host",
            db_connection_mode=normalized_mode,
            socket_style_detected=socket_style,
            loopback_detected=True,
            proxy_mode_exception_applied=proxy_mode_exception_applied,
        )
        if proxy_mode_exception_applied:
            return True, "DATABASE_URL accepted for production deploy.", diagnostics
        return (
            False,
            "Invalid production DATABASE_URL: localhost/loopback target is not allowed for deploy-prod.",
            diagnostics,
        )

    if socket_style:
        diagnostics = DatabaseUrlDiagnostics(
            scheme=scheme,
            query_params_present=bool(query_keys),
            query_param_keys=query_keys,
            effective_target_source=source,
            effective_target_kind="unix_socket",
            db_connection_mode=normalized_mode,
            socket_style_detected=True,
            loopback_detected=False,
            proxy_mode_exception_applied=False,
        )
        return True, "DATABASE_URL accepted for production deploy.", diagnostics

    if not target:
        diagnostics = DatabaseUrlDiagnostics(
            scheme=scheme,
            query_params_present=bool(query_keys),
            query_param_keys=query_keys,
            effective_target_source=source,
            effective_target_kind="missing_host",
            db_connection_mode=normalized_mode,
            socket_style_detected=False,
            loopback_detected=False,
            proxy_mode_exception_applied=False,
        )
        return False, "DATABASE_URL must include a resolvable non-loopback target host for production deploy.", diagnostics

    is_loopback = target in _LOOPBACK_HOSTS
    diagnostics = DatabaseUrlDiagnostics(
        scheme=scheme,
        query_params_present=bool(query_keys),
        query_param_keys=query_keys,
        effective_target_source=source,
        effective_target_kind="loopback_host" if is_loopback else "remote_host",
        db_connection_mode=normalized_mode,
        socket_style_detected=False,
        loopback_detected=is_loopback,
        proxy_mode_exception_applied=False,
    )
    if is_loopback:
        return (
            False,
            "Invalid production DATABASE_URL: localhost/loopback target is not allowed for deploy-prod.",
            diagnostics,
        )
    return True, "DATABASE_URL accepted for production deploy.", diagnostics


def _print_diagnostics(diagnostics: DatabaseUrlDiagnostics, *, accepted: bool) -> None:
    query_keys = ",".join(diagnostics.query_param_keys) if diagnostics.query_param_keys else "none"
    print(
        "DATABASE_URL validation diagnostics: "
        f"accepted={str(accepted).lower()} "
        f"scheme={diagnostics.scheme or 'missing'} "
        f"target_source={diagnostics.effective_target_source} "
        f"target_kind={diagnostics.effective_target_kind} "
        f"db_connection_mode={diagnostics.db_connection_mode} "
        f"query_params_present={str(diagnostics.query_params_present).lower()} "
        f"query_param_keys={query_keys} "
        f"socket_style_detected={str(diagnostics.socket_style_detected).lower()} "
        f"loopback_detected={str(diagnostics.loopback_detected).lower()} "
        f"proxy_mode_exception_applied={str(diagnostics.proxy_mode_exception_applied).lower()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate DATABASE_URL for production deploy safety without logging credential material. "
            "Checks the effective connection target host and rejects loopback."
        )
    )
    parser.add_argument(
        "--database-url",
        help="Database URL to validate. If omitted, --env-var is used.",
    )
    parser.add_argument(
        "--env-var",
        default="DATABASE_URL",
        help="Environment variable containing the database URL when --database-url is omitted (default: DATABASE_URL).",
    )
    parser.add_argument(
        "--db-connection-mode",
        help="Explicit DB connection mode override (direct|cloudsql_proxy).",
    )
    parser.add_argument(
        "--db-connection-mode-env-var",
        default="DB_CONNECTION_MODE",
        help=(
            "Environment variable containing DB connection mode when --db-connection-mode is omitted "
            "(default: DB_CONNECTION_MODE)."
        ),
    )
    args = parser.parse_args(argv)

    database_url = args.database_url
    if database_url is None:
        database_url = os.getenv(args.env_var, "")

    db_connection_mode = args.db_connection_mode
    if db_connection_mode is None:
        db_connection_mode = os.getenv(args.db_connection_mode_env_var, "")

    accepted, message, diagnostics = analyze_database_url(
        database_url,
        db_connection_mode=db_connection_mode,
    )
    _print_diagnostics(diagnostics, accepted=accepted)
    if accepted:
        print(message)
        return 0

    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

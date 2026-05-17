from __future__ import annotations

import json
import re
from typing import Any

REDACTED_VALUE = "<redacted>"
TRUNCATED_VALUE = "<truncated>"

_MAX_DEPTH_DEFAULT = 6
_MAX_ITEMS_DEFAULT = 256
_MAX_STRING_LENGTH_DEFAULT = 512

_SENSITIVE_KEY_TERMS = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "cloud_sql_instance_connection_name",
    "cookie",
    "credential",
    "credentials",
    "database_url",
    "deploy_key",
    "dockerconfigjson",
    "gcp_deploy_key",
    "git_token",
    "id_token",
    "kubeconfig",
    "openai",
    "provider_payload",
    "passwd",
    "password",
    "private_key",
    "raw_prompt",
    "raw_request",
    "raw_response",
    "refresh_token",
    "request_body",
    "response_body",
    "secret",
    "stderr",
    "stdout",
    "token",
}

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bghp_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+\-/]+=*\b", re.IGNORECASE),
    re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{8,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

_POTENTIALLY_SENSITIVE_JSON_KEYS = {"auths", "authorization", "cookie", "dockerconfigjson", ".dockerconfigjson"}


def sanitize_log_payload(
    payload: Any,
    *,
    max_depth: int = _MAX_DEPTH_DEFAULT,
    max_items: int = _MAX_ITEMS_DEFAULT,
    max_string_length: int = _MAX_STRING_LENGTH_DEFAULT,
) -> Any:
    """Return a log-safe representation of structured payload data."""

    return _sanitize_value(
        payload,
        depth=0,
        max_depth=max_depth,
        max_items=max_items,
        max_string_length=max_string_length,
    )


def _sanitize_value(
    value: Any,
    *,
    depth: int,
    max_depth: int,
    max_items: int,
    max_string_length: int,
) -> Any:
    if depth >= max_depth:
        return TRUNCATED_VALUE

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (raw_key, raw_item) in enumerate(value.items()):
            if index >= max_items:
                sanitized["truncated_fields"] = True
                break
            key = _sanitize_key(raw_key)
            if _is_sensitive_key(key):
                sanitized[key] = REDACTED_VALUE
                continue
            sanitized[key] = _sanitize_value(
                raw_item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_string_length=max_string_length,
            )
        return sanitized

    if isinstance(value, (list, tuple, set)):
        sanitized_items: list[Any] = []
        for index, item in enumerate(value):
            if index >= max_items:
                sanitized_items.append(TRUNCATED_VALUE)
                break
            sanitized_items.append(
                _sanitize_value(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                    max_string_length=max_string_length,
                )
            )
        return sanitized_items

    if isinstance(value, bytes):
        return REDACTED_VALUE

    if isinstance(value, str):
        return _sanitize_string(value, max_string_length=max_string_length)

    return value


def _sanitize_key(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "unknown_key"
    if len(normalized) > 120:
        return normalized[:120]
    return normalized


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    if not lowered:
        return False
    if lowered.endswith("_credential_source"):
        return False

    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    if any(token in _SENSITIVE_KEY_TERMS for token in tokens):
        return True

    if lowered in _SENSITIVE_KEY_TERMS:
        return True
    if lowered.startswith("auth_") or lowered.endswith("_auth") or lowered == "auth":
        return True
    if any(term in lowered for term in ("token", "secret", "password", "authorization", "cookie")):
        return True
    if any(
        term in lowered
        for term in (
            "private_key",
            "deploy_key",
            "credential",
            "api_key",
            "database_url",
            "cloud_sql_instance_connection_name",
            "dockerconfigjson",
            "kubeconfig",
            "openai",
        )
    ):
        return True
    return False


def _sanitize_string(value: str, *, max_string_length: int) -> str:
    compact = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    if not compact:
        return compact

    lowered = compact.lower()
    if _looks_like_sensitive_json_blob(compact, lowered=lowered):
        return REDACTED_VALUE

    if any(pattern.search(compact) for pattern in _SECRET_VALUE_PATTERNS):
        return REDACTED_VALUE

    if _looks_like_credential_url(lowered):
        return REDACTED_VALUE

    if len(compact) > max_string_length:
        return compact[:max_string_length]
    return compact


def _looks_like_sensitive_json_blob(value: str, *, lowered: str) -> bool:
    if not (value.startswith("{") or value.startswith("[")):
        return False
    if len(value) > 16_000:
        return True
    if not any(marker in lowered for marker in ("auths", "token", "secret", "dockerconfigjson", "authorization")):
        return False
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return False
    return _contains_sensitive_json_key(parsed)


def _contains_sensitive_json_key(value: Any, *, depth: int = 0) -> bool:
    if depth > 6:
        return True
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key or "").strip().lower()
            if key in _POTENTIALLY_SENSITIVE_JSON_KEYS or _is_sensitive_key(key):
                return True
            if _contains_sensitive_json_key(item, depth=depth + 1):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_json_key(item, depth=depth + 1) for item in value[:64])
    if isinstance(value, str):
        lowered = value.lower()
        if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            return True
        if _looks_like_credential_url(lowered):
            return True
    return False


def _looks_like_credential_url(lowered: str) -> bool:
    schemes = ("postgres://", "postgresql://", "mysql://", "mariadb://", "mongodb://", "redis://")
    if not any(lowered.startswith(scheme) for scheme in schemes):
        return False
    return "@" in lowered and ":" in lowered.split("@", 1)[0]

from __future__ import annotations

from app.core.log_sanitizer import REDACTED_VALUE, sanitize_log_payload


def test_sanitize_log_payload_redacts_nested_sensitive_keys() -> None:
    payload = {
        "event": "security_test",
        "git_token": "ghp_FAKE_SUPER_SECRET_TOKEN_FOR_TEST",
        "nested": {
            "Authorization": "Bearer FAKE_BEARER_SECRET_FOR_TEST",
            "cookie": "session=FAKE_COOKIE_SECRET_FOR_TEST",
            "safe_flag": True,
        },
        "items": [
            {"status": "ok", "database_url": "postgresql://user:pass@localhost:5432/db"},
            {"access_token": "FAKE_ACCESS_TOKEN_FOR_TEST"},
        ],
    }

    sanitized = sanitize_log_payload(payload)

    assert sanitized["event"] == "security_test"
    assert sanitized["git_token"] == REDACTED_VALUE
    assert sanitized["nested"]["Authorization"] == REDACTED_VALUE
    assert sanitized["nested"]["cookie"] == REDACTED_VALUE
    assert sanitized["nested"]["safe_flag"] is True
    assert sanitized["items"][0]["status"] == "ok"
    assert sanitized["items"][0]["database_url"] == REDACTED_VALUE
    assert sanitized["items"][1]["access_token"] == REDACTED_VALUE


def test_sanitize_log_payload_redacts_secret_like_string_patterns() -> None:
    payload = {
        "safe_message": "request failed",
        "header_value": "Bearer FAKE_BEARER_SECRET_FOR_TEST",
        "github_pat": "ghp_FAKE_SUPER_SECRET_TOKEN_FOR_TEST",
        "basic_auth": "Basic dXNlcjpzZWNyZXQ=",
        "stderr": "ERROR deploy failed with token=FAKE_SECRET",
    }

    sanitized = sanitize_log_payload(payload)

    assert sanitized["safe_message"] == "request failed"
    assert sanitized["header_value"] == REDACTED_VALUE
    assert sanitized["github_pat"] == REDACTED_VALUE
    assert sanitized["basic_auth"] == REDACTED_VALUE
    assert sanitized["stderr"] == REDACTED_VALUE


def test_sanitize_log_payload_redacts_sensitive_json_blobs() -> None:
    docker_blob = (
        '{"auths":{"ghcr.io":{"username":"bot","password":"super-secret","auth":"abc"}},"meta":"x"}'
    )
    payload = {
        "event": "pull_secret_test",
        "docker_blob": docker_blob,
        "safe_count": 3,
    }

    sanitized = sanitize_log_payload(payload)

    assert sanitized["event"] == "pull_secret_test"
    assert sanitized["docker_blob"] == REDACTED_VALUE
    assert sanitized["safe_count"] == 3


def test_sanitize_log_payload_bounds_depth_and_collections() -> None:
    payload = {"items": [{"nested": {"level3": {"level4": {"level5": {"token": "x"}}}}}] * 100}

    sanitized = sanitize_log_payload(payload, max_depth=3, max_items=2)

    assert sanitized["items"][0]["nested"] == "<truncated>"
    assert sanitized["items"][1]["nested"] == "<truncated>"
    assert sanitized["items"][2] == "<truncated>"

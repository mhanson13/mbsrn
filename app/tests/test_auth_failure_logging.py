from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.deps import _log_auth_failure, get_tenant_context
from app.core.config import get_settings
from app.core.session_token import AppSessionTokenError


class _DummySessionTokenService:
    def verify_access_token(self, _token: str):
        raise AppSessionTokenError("invalid")


class _DummyRateLimiter:
    def check(self, *, key: str, limit: int, window_seconds: int) -> SimpleNamespace:
        return SimpleNamespace(allowed=True, retry_after_seconds=0)


def _build_request(*, user_agent: str = "example-user-agent", client_ip: str = "35.191.112.178") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/leads",
        "raw_path": b"/api/leads",
        "query_string": b"",
        "headers": [(b"user-agent", user_agent.encode("utf-8"))],
        "client": (client_ip, 443),
        "server": ("testserver", 443),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_log_auth_failure_emits_warning_with_bounded_fields(caplog: pytest.LogCaptureFixture) -> None:
    request = _build_request()

    with caplog.at_level(logging.WARNING, logger="app.api.deps"):
        _log_auth_failure(request=request, reason="invalid_access_token", auth_kind="jwt")

    auth_records = [record for record in caplog.records if "auth_failure" in record.getMessage()]
    assert len(auth_records) == 1
    record = auth_records[0]
    message = record.getMessage()

    assert record.levelno == logging.WARNING
    assert "reason=invalid_access_token" in message
    assert "auth_kind=jwt" in message
    assert "client_ip=35.191.112.178" in message
    assert "user_agent_bucket=" in message
    assert "example-user-agent" not in message
    assert "authorization" not in message.lower()
    assert "bearer " not in message.lower()


def test_invalid_jwt_auth_logs_warning_and_returns_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    request = _build_request()

    with caplog.at_level(logging.WARNING, logger="app.api.deps"):
        with pytest.raises(HTTPException) as exc_info:
            get_tenant_context(
                request=request,
                authorization="Bearer a.b.c",
                api_credential_repository=SimpleNamespace(),
                principal_repository=SimpleNamespace(),
                principal_identity_repository=SimpleNamespace(),
                session_token_service=_DummySessionTokenService(),
                rate_limiter=_DummyRateLimiter(),
            )

    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("reason_code") == "session_expired"

    auth_records = [record for record in caplog.records if "auth_failure" in record.getMessage()]
    assert len(auth_records) == 1
    record = auth_records[0]
    message = record.getMessage()

    assert record.levelno == logging.WARNING
    assert "reason=invalid_access_token" in message
    assert "auth_kind=jwt" in message
    assert "a.b.c" not in message
    assert "authorization" not in message.lower()
    assert "bearer " not in message.lower()

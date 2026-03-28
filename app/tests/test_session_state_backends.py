from __future__ import annotations

import logging

import pytest

import app.core.session_state as session_state_module
from app.core.config import get_settings
from app.core.session_state import InMemorySessionStateStore, RedisSessionStateStore


class _FailingRedisClient:
    def ping(self) -> None:
        raise session_state_module.RedisError("redis unavailable")


class _RedisFactory:
    @staticmethod
    def from_url(*args, **kwargs):  # noqa: ANN002, ANN003
        return _FailingRedisClient()


class _HealthyRedisClient:
    def ping(self) -> None:
        return None


class _HealthyRedisFactory:
    @staticmethod
    def from_url(*args, **kwargs):  # noqa: ANN002, ANN003
        return _HealthyRedisClient()


def _clear_session_store_cache() -> None:
    session_state_module._SESSION_STATE_STORE = None
    session_state_module._SESSION_STATE_STORE_SIG = None


@pytest.fixture(autouse=True)
def _clear_settings_and_store_cache() -> None:
    get_settings.cache_clear()
    _clear_session_store_cache()
    yield
    get_settings.cache_clear()
    _clear_session_store_cache()


def test_session_state_builder_rejects_redis_backend_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    _clear_session_store_cache()
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        session_state_module._build_store()


def test_settings_parse_production_safe_session_redis_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "prod-pepper")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SESSION_STATE_BACKEND", "redis")
    monkeypatch.setenv("SESSION_STATE_FAIL_OPEN", "false")
    monkeypatch.setenv("SESSION_STATE_ALLOW_INMEMORY_FALLBACK", "false")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.environment == "production"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.session_state_backend == "redis"
    assert settings.session_state_fail_open is False
    assert settings.session_state_allow_inmemory_fallback is False


def test_session_state_builder_defaults_to_inmemory_when_auto_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    _clear_session_store_cache()
    store = session_state_module._build_store()
    assert isinstance(store, InMemorySessionStateStore)


def test_session_state_builder_selects_redis_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(session_state_module, "Redis", _HealthyRedisFactory)
    get_settings.cache_clear()
    _clear_session_store_cache()
    store = session_state_module._build_store()
    assert isinstance(store, RedisSessionStateStore)


def test_session_state_builder_logs_dev_inmemory_fallback_as_non_degraded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    caplog.set_level(logging.INFO)
    get_settings.cache_clear()
    _clear_session_store_cache()
    store = session_state_module._build_store()
    assert isinstance(store, InMemorySessionStateStore)
    selection_event = next(
        record for record in caplog.records if "event=session_state_backend_selection" in record.getMessage()
    )
    message = selection_event.getMessage()
    assert selection_event.levelno == logging.WARNING
    assert "selected_backend=inmemory" in message
    assert "degraded_mode=False" in message
    assert "risk_level=normal" in message


def test_session_state_builder_production_rejects_fail_open_redis_security_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SESSION_STATE_FAIL_OPEN", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "prod-pepper")
    monkeypatch.setattr(session_state_module, "Redis", _RedisFactory)
    get_settings.cache_clear()
    _clear_session_store_cache()
    with pytest.raises(RuntimeError, match="must be fail-closed"):
        session_state_module._build_store()


def test_session_state_builder_fail_open_falls_back_to_inmemory_for_local_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SESSION_STATE_FAIL_OPEN", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(session_state_module, "Redis", _RedisFactory)
    get_settings.cache_clear()
    _clear_session_store_cache()
    store = session_state_module._build_store()
    assert isinstance(store, InMemorySessionStateStore)


def test_session_state_builder_fail_closed_raises_on_redis_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SESSION_STATE_FAIL_OPEN", "false")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "prod-pepper")
    monkeypatch.setattr(session_state_module, "Redis", _RedisFactory)
    get_settings.cache_clear()
    _clear_session_store_cache()
    with pytest.raises(RuntimeError, match="Unable to initialize Redis session state store"):
        session_state_module._build_store()


def test_session_state_builder_logs_production_inmemory_fallback_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "prod-pepper")
    caplog.set_level(logging.INFO)
    get_settings.cache_clear()
    _clear_session_store_cache()
    store = session_state_module._build_store()
    assert isinstance(store, InMemorySessionStateStore)
    selection_event = next(
        record for record in caplog.records if "event=session_state_backend_selection" in record.getMessage()
    )
    message = selection_event.getMessage()
    assert selection_event.levelno == logging.ERROR
    assert "selected_backend=inmemory" in message
    assert "degraded_mode=True" in message
    assert "risk_level=high" in message
    assert any(
        record.levelno == logging.ERROR and "degraded for multi-replica production runtime" in record.getMessage()
        for record in caplog.records
    )


def test_session_state_builder_blocks_production_inmemory_when_guardrail_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "prod-pepper")
    monkeypatch.setenv("SESSION_STATE_ALLOW_INMEMORY_FALLBACK", "false")
    get_settings.cache_clear()
    _clear_session_store_cache()
    with pytest.raises(RuntimeError, match="SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false"):
        session_state_module._build_store()

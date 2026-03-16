from __future__ import annotations

import pytest

import app.core.session_state as session_state_module
from app.core.config import get_settings
from app.core.session_state import InMemorySessionStateStore


class _FailingRedisClient:
    def ping(self) -> None:
        raise session_state_module.RedisError("redis unavailable")


class _RedisFactory:
    @staticmethod
    def from_url(*args, **kwargs):  # noqa: ANN002, ANN003
        return _FailingRedisClient()


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


def test_session_state_builder_defaults_to_inmemory_when_auto_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_STATE_BACKEND", "auto")
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    _clear_session_store_cache()
    store = session_state_module._build_store()
    assert isinstance(store, InMemorySessionStateStore)


def test_session_state_builder_fail_open_falls_back_to_inmemory(
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

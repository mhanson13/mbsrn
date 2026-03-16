from __future__ import annotations

import pytest

import app.core.rate_limit as rate_limit_module
from app.core.config import get_settings
from app.core.rate_limit import InMemoryRateLimiter, RedisError, RedisRateLimiter, RateLimitDecision


class _FailingPipeline:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def incr(self, key):  # noqa: ARG002
        return None

    def ttl(self, key):  # noqa: ARG002
        return None

    def execute(self):
        raise RedisError("redis unavailable")


class _FakeRedisClient:
    def pipeline(self):
        return _FailingPipeline()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_inmemory_rate_limiter_enforces_limit() -> None:
    limiter = InMemoryRateLimiter()
    assert limiter.check(key="auth:test", limit=2, window_seconds=60).allowed is True
    assert limiter.check(key="auth:test", limit=2, window_seconds=60).allowed is True
    denied = limiter.check(key="auth:test", limit=2, window_seconds=60)
    assert denied.allowed is False
    assert denied.retry_after_seconds >= 1


def test_redis_rate_limiter_fail_open_allows_when_backend_unavailable() -> None:
    limiter = RedisRateLimiter(client=_FakeRedisClient(), fail_open=True)
    decision = limiter.check(key="auth:test", limit=1, window_seconds=60)
    assert isinstance(decision, RateLimitDecision)
    assert decision.allowed is True


def test_redis_rate_limiter_fail_closed_denies_when_backend_unavailable() -> None:
    limiter = RedisRateLimiter(client=_FakeRedisClient(), fail_open=False)
    decision = limiter.check(key="auth:test", limit=1, window_seconds=60)
    assert isinstance(decision, RateLimitDecision)
    assert decision.allowed is False
    assert decision.retry_after_seconds >= 1


def test_rate_limiter_builder_rejects_redis_backend_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        rate_limit_module._build_rate_limiter()


def test_rate_limiter_builder_defaults_to_inmemory_when_auto_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "auto")
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    limiter = rate_limit_module._build_rate_limiter()
    assert isinstance(limiter, InMemoryRateLimiter)

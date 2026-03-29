from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure_non_local_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "test-pepper")
    monkeypatch.setenv("GOOGLE_AUTH_ENABLED", "false")
    monkeypatch.delenv("API_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


def test_missing_database_url_raises_in_non_local_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_non_local_runtime(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(
        RuntimeError,
        match="DATABASE_URL is required and must not default to localhost in this environment",
    ):
        get_settings()


def test_localhost_database_url_rejected_in_non_local_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_non_local_runtime(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn")

    with pytest.raises(RuntimeError, match="Invalid DATABASE_URL: localhost is not allowed in this environment"):
        get_settings()


def test_valid_remote_database_url_accepted_in_non_local_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_non_local_runtime(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app_user:secret@db.internal:5432/mbsrn")

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://app_user:secret@db.internal:5432/mbsrn"


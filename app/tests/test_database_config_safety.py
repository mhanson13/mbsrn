from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure_production_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "test-pepper")
    monkeypatch.setenv("GOOGLE_AUTH_ENABLED", "false")
    monkeypatch.delenv("API_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


def test_missing_database_url_raises_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_production_runtime(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required when APP_ENV=production"):
        get_settings()


def test_localhost_database_url_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_production_runtime(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn")

    with pytest.raises(RuntimeError, match="Invalid DATABASE_URL: localhost is not allowed when APP_ENV=production"):
        get_settings()


def test_valid_remote_database_url_accepted_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_production_runtime(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app_user:secret@db.internal:5432/mbsrn")

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://app_user:secret@db.internal:5432/mbsrn"


@pytest.mark.parametrize("app_env", ["ci", "test", "development", "dev", "local"])
def test_localhost_database_url_allowed_for_local_like_app_env(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn")

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn"


def test_localhost_database_url_rejected_when_app_env_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ENV", "qa")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn")

    with pytest.raises(RuntimeError, match="Invalid DATABASE_URL: localhost is not allowed when APP_ENV=qa"):
        get_settings()


def test_localhost_database_url_rejected_when_app_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn")

    with pytest.raises(RuntimeError, match="Invalid DATABASE_URL: localhost is not allowed when APP_ENV is unset"):
        get_settings()


def test_fallback_database_url_requires_local_like_app_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "ci")
    settings = get_settings()
    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn"

    get_settings.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "qa")
    with pytest.raises(
        RuntimeError,
        match="DATABASE_URL is required when APP_ENV is not one of local/development/dev/test/ci",
    ):
        get_settings()


def test_postgresql_scheme_is_normalized_to_psycopg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mbsrn")

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/mbsrn"

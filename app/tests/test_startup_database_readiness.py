from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

import app.main as main_module


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeConnection:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else [("1",)]

    def execute(self, _query):
        return _FakeResult(self._rows)


class _ConnectionContext:
    def __init__(self, rows=None):
        self._rows = rows

    def __enter__(self):
        return _FakeConnection(rows=self._rows)

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, *, fail_attempts: int = 0, rows=None):
        self.fail_attempts = fail_attempts
        self.rows = rows
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self.connect_calls <= self.fail_attempts:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return _ConnectionContext(rows=self.rows)


@pytest.fixture(autouse=True)
def _preserve_module_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(app_env="test", db_connection_mode="direct", app_name="MBSRN", db_auto_create_local=False),
    )
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "db.internal")
    monkeypatch.setattr(main_module, "DATABASE_TARGET_PORT_LABEL", "5432")
    monkeypatch.setattr(main_module, "_CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_MAX_ATTEMPTS", 15)
    monkeypatch.setattr(main_module, "_CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_RETRY_DELAY_SECONDS", 1.0)
    monkeypatch.setattr(main_module, "_SCHEMA_READINESS_LOGGED_REVISION", None)


def test_schema_readiness_accepts_revision_0039(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    fake_engine = _FakeEngine(rows=[("0039_competitor_domain_verification_status",)])
    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "EXPECTED_ALEMBIC_HEAD", "0039_competitor_domain_verification_status")
    caplog.set_level(logging.INFO)

    ready, payload = main_module._check_schema_readiness()

    assert ready is True
    assert payload["schema_revision"] == "0039_competitor_domain_verification_status"
    assert "Schema readiness passed expected=0039_competitor_domain_verification_status" in caplog.text


def test_startup_connectivity_retries_for_cloudsql_proxy_localhost(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_engine = _FakeEngine(fail_attempts=2)
    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(app_env="production", db_connection_mode="cloudsql_proxy"))
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "127.0.0.1")
    monkeypatch.setattr(main_module, "_CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(main_module.time, "sleep", lambda _seconds: None)
    caplog.set_level(logging.INFO)

    main_module._ensure_database_connectivity()

    assert fake_engine.connect_calls == 3
    assert "Startup database connectivity check using cloudsql proxy retry budget" in caplog.text
    assert "Startup database connectivity check succeeded" in caplog.text
    assert "recovered_after_retry=True" in caplog.text
    assert "postgresql+psycopg://" not in caplog.text


def test_startup_connectivity_immediate_success_logs_without_recovery(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_engine = _FakeEngine(fail_attempts=0)
    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(app_env="production", db_connection_mode="direct"))
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "db.internal")
    caplog.set_level(logging.INFO)

    main_module._ensure_database_connectivity()

    assert fake_engine.connect_calls == 1
    assert "Startup database connectivity check succeeded" in caplog.text
    assert "proxy_retry_path_entered=False" in caplog.text
    assert "recovered_after_retry=False" in caplog.text
    assert "postgresql+psycopg://" not in caplog.text


def test_startup_connectivity_fails_fast_on_production_localhost_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = _FakeEngine(fail_attempts=0)
    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(app_env="production", db_connection_mode="direct"))
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "localhost")

    with pytest.raises(
        RuntimeError,
        match="Production DB config regression detected: resolved localhost target is invalid when APP_ENV=production",
    ):
        main_module._ensure_database_connectivity()

    assert fake_engine.connect_calls == 0


def test_startup_connectivity_logs_guard_before_production_localhost_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_engine = _FakeEngine(fail_attempts=0)
    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(app_env="production", db_connection_mode="direct"))
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "localhost")
    caplog.set_level(logging.INFO)

    with pytest.raises(
        RuntimeError,
        match="Production DB config regression detected: resolved localhost target is invalid when APP_ENV=production",
    ):
        main_module._ensure_database_connectivity()

    assert "Production DB config regression detected host=localhost port=5432 app_env=production db_connection_mode=direct" in caplog.text
    assert "postgresql+psycopg://" not in caplog.text


def test_startup_connectivity_raises_after_retry_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_engine = _FakeEngine(fail_attempts=10)
    monkeypatch.setattr(main_module, "engine", fake_engine)
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(app_env="production", db_connection_mode="cloudsql_proxy"))
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "127.0.0.1")
    monkeypatch.setattr(main_module, "_CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(main_module.time, "sleep", lambda _seconds: None)
    caplog.set_level(logging.INFO)

    with pytest.raises(
        RuntimeError,
        match="Startup database connectivity check failed. Verify DATABASE_URL and database reachability.",
    ):
        main_module._ensure_database_connectivity()

    assert fake_engine.connect_calls == 2
    assert "Startup database connectivity check failed host=127.0.0.1 port=5432 app_env=production db_connection_mode=cloudsql_proxy attempt=2 max_attempts=2" in caplog.text
    assert "postgresql+psycopg://" not in caplog.text


def test_startup_logs_schema_expectation(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(main_module, "EXPECTED_ALEMBIC_HEAD", "0039_competitor_domain_verification_status")
    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(
            app_env="production",
            db_connection_mode="cloudsql_proxy",
            db_auto_create_local=False,
        ),
    )
    monkeypatch.setattr(main_module, "DATABASE_TARGET_HOST", "127.0.0.1")
    monkeypatch.setattr(main_module, "DATABASE_TARGET_PORT_LABEL", "5432")
    monkeypatch.setattr(main_module, "_should_enforce_schema_readiness", lambda: True)
    monkeypatch.setattr(main_module, "_should_auto_create_schema", lambda: False)
    monkeypatch.setattr(main_module, "_ensure_database_connectivity", lambda: None)
    caplog.set_level(logging.INFO)

    main_module.on_startup()

    assert "Startup schema readiness expectation expected_revision=0039_competitor_domain_verification_status" in caplog.text
    assert "database_target_classification=loopback" in caplog.text
    assert "db_connection_mode=cloudsql_proxy" in caplog.text

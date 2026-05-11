from __future__ import annotations

from app.db.session import _build_engine_options


def test_build_engine_options_adds_postgres_pool_hardening() -> None:
    options = _build_engine_options("postgresql+psycopg://user:pass@db.internal:5432/mbsrn")

    assert options["pool_pre_ping"] is True
    assert options["pool_timeout"] == 10
    assert options["pool_recycle"] == 1800
    assert options["connect_args"] == {"connect_timeout": 10}


def test_build_engine_options_keeps_non_postgres_minimal() -> None:
    options = _build_engine_options("sqlite+pysqlite:///:memory:")

    assert options == {"pool_pre_ping": True}

from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import make_url

# Ensure repo-root imports (app.*) resolve when Alembic runs from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.base import Base
from app.models import api_credential, auth_audit_event, business, lead, lead_event, principal

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def _resolve_sqlalchemy_url() -> str:
    env_database_url = os.getenv("DATABASE_URL")
    if env_database_url:
        config.set_main_option("sqlalchemy.url", env_database_url)

    resolved_url = config.get_main_option("sqlalchemy.url")
    if not resolved_url:
        raise RuntimeError("Alembic sqlalchemy.url is not configured.")
    return resolved_url


def _render_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001
        return "<invalid sqlalchemy.url>"


def _connect_args_for_url(url: str) -> dict[str, object]:
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001
        return {}

    if parsed.get_backend_name() != "postgresql":
        return {}

    # Keep local diagnostics predictable on network DBs without altering explicit URL query settings.
    if "connect_timeout" in parsed.query:
        return {}

    timeout_seconds = int(os.getenv("ALEMBIC_CONNECT_TIMEOUT_SECONDS", "5"))
    if timeout_seconds <= 0:
        return {}
    return {"connect_timeout": timeout_seconds}


def run_migrations_offline() -> None:
    url = _resolve_sqlalchemy_url()
    logger.info("Alembic offline migration context using database URL: %s", _render_url(url))
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _resolve_sqlalchemy_url()
    redacted_url = _render_url(url)
    connect_args = _connect_args_for_url(url)
    engine_kwargs: dict[str, object] = {"poolclass": pool.NullPool}
    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    logger.info("Alembic engine initialization for database URL: %s", redacted_url)
    try:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            **engine_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Alembic failed during engine initialization for database URL {redacted_url}: {exc}"
        ) from exc

    try:
        with connectable.connect() as connection:
            logger.info("Alembic database connection established.")
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Alembic reached the DB connection/migration phase but failed. "
            f"Database URL: {redacted_url}. Original error: {exc}"
        ) from exc


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

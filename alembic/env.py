from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import make_url

# Ensure repo-root imports (app.*) resolve when Alembic runs from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.base import Base
from app.models import (
    api_credential,
    auth_audit_event,
    business,
    lead,
    lead_event,
    principal,
    principal_identity,
    provider_connection,
    provider_oauth_state,
    seo_audit_finding,
    seo_audit_page,
    seo_audit_run,
    seo_audit_summary,
    seo_automation_config,
    seo_automation_run,
    seo_action_chain_draft,
    seo_action_decision,
    seo_action_execution_item,
    seo_competitor_comparison_finding,
    seo_competitor_comparison_run,
    seo_competitor_comparison_summary,
    seo_competitor_domain,
    seo_competitor_profile_draft,
    seo_competitor_profile_generation_run,
    seo_competitor_tuning_preview_event,
    seo_competitor_set,
    seo_competitor_snapshot_page,
    seo_competitor_snapshot_run,
    seo_recommendation,
    seo_recommendation_narrative,
    seo_recommendation_run,
    seo_site,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata
ALEMBIC_VERSION_COLUMN_LEN = 64


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


def _ensure_alembic_version_column_capacity(connection: sa.engine.Connection) -> None:
    inspector = sa.inspect(connection)
    table_names = set(inspector.get_table_names())
    if "alembic_version" not in table_names:
        if connection.dialect.name == "postgresql":
            connection.execute(
                sa.text(
                    f"""
                    CREATE TABLE IF NOT EXISTS alembic_version (
                        version_num VARCHAR({ALEMBIC_VERSION_COLUMN_LEN}) NOT NULL PRIMARY KEY
                    )
                    """
                )
            )
            logger.info(
                "Ensured alembic_version table exists with version_num length=%s.",
                ALEMBIC_VERSION_COLUMN_LEN,
            )
        return

    version_columns = {column.get("name"): column for column in inspector.get_columns("alembic_version")}
    version_num = version_columns.get("version_num")
    if not version_num:
        return

    if connection.dialect.name != "postgresql":
        return

    current_length = getattr(version_num.get("type"), "length", None)
    if current_length is None or current_length >= ALEMBIC_VERSION_COLUMN_LEN:
        return

    connection.execute(
        sa.text(
            f"""
            ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_COLUMN_LEN})
            """
        )
    )
    logger.info(
        "Expanded alembic_version.version_num from length=%s to length=%s for compatibility.",
        current_length,
        ALEMBIC_VERSION_COLUMN_LEN,
    )


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
            _ensure_alembic_version_column_capacity(connection)
            if connection.in_transaction():
                connection.commit()
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

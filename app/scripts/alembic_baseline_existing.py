from __future__ import annotations

import os
import sys

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


BASELINE_REVISION = "0024_google_business_profile_oauth_connections"
LIFECYCLE_COLUMNS = {"last_audit_run_id", "last_audit_status", "last_audit_completed_at"}
REQUIRED_TABLES = {"businesses", "seo_sites"}


def _fail(message: str, code: int) -> int:
    print(message, file=sys.stderr)
    return code


def _read_current_revisions(connection: sa.engine.Connection) -> list[str]:
    rows = connection.execute(sa.text("SELECT version_num FROM alembic_version")).all()
    revisions: list[str] = []
    for row in rows:
        value = str(row[0]).strip() if row and row[0] is not None else ""
        if value:
            revisions.append(value)
    return revisions


def main() -> int:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        return _fail("DATABASE_URL is required for baseline alignment.", 1)

    engine = sa.create_engine(database_url, future=True, pool_pre_ping=True)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        table_names = set(inspector.get_table_names())

        missing_tables = sorted(table for table in REQUIRED_TABLES if table not in table_names)
        if missing_tables:
            return _fail(
                "Refusing baseline alignment: expected existing schema tables are missing: "
                + ", ".join(missing_tables),
                2,
            )

        if "alembic_version" in table_names:
            revisions = _read_current_revisions(connection)
            if revisions:
                return _fail(
                    "Refusing baseline alignment: alembic_version already contains revision(s): "
                    + ", ".join(revisions)
                    + ". Use normal migration mode.",
                    3,
                )

        seo_site_columns = {column["name"] for column in inspector.get_columns("seo_sites")}
        lifecycle_present = sorted(column for column in LIFECYCLE_COLUMNS if column in seo_site_columns)
        if len(lifecycle_present) == len(LIFECYCLE_COLUMNS):
            return _fail(
                "Refusing baseline alignment: seo_sites already has lifecycle columns. Use normal migration mode.",
                4,
            )
        if lifecycle_present:
            return _fail(
                "Refusing baseline alignment: seo_sites has a partial lifecycle column set: "
                + ", ".join(lifecycle_present)
                + ". Manual intervention required.",
                5,
            )

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    print(f"Stamping existing schema baseline to revision {BASELINE_REVISION}...")
    command.stamp(alembic_config, BASELINE_REVISION)
    print(
        "Baseline alignment completed. Run normal migrations next to apply "
        "0025_seo_site_audit_lifecycle_fields and newer revisions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

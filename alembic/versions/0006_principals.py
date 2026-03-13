"""add persisted principals and bind api_credentials to principals

Revision ID: 0006_principals
Revises: 0005_api_credentials
Create Date: 2026-03-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector


revision = "0006_principals"
down_revision = "0005_api_credentials"
branch_labels = None
depends_on = None


def _table_exists(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: Inspector, table: str, name: str) -> bool:
    for index in inspector.get_indexes(table):
        if index.get("name") == name:
            return True
    return False


def _has_composite_fk(
    inspector: Inspector,
    *,
    table: str,
    constrained_columns: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> bool:
    for foreign_key in inspector.get_foreign_keys(table):
        if (
            foreign_key.get("referred_table") == referred_table
            and tuple(foreign_key.get("constrained_columns") or ()) == constrained_columns
            and tuple(foreign_key.get("referred_columns") or ()) == referred_columns
        ):
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "principals"):
        op.create_table(
            "principals",
            sa.Column("business_id", sa.String(length=36), sa.ForeignKey("businesses.id"), nullable=False),
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("business_id", "id", name="pk_principals_business_id_id"),
        )
        op.create_index("ix_principals_business_id", "principals", ["business_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO principals (business_id, id, display_name, is_active, created_at, updated_at)
            SELECT DISTINCT c.business_id, c.principal_id, c.principal_id, true, now(), now()
            FROM api_credentials AS c
            LEFT JOIN principals AS p
              ON p.business_id = c.business_id
             AND p.id = c.principal_id
            WHERE p.id IS NULL
            """
        )
    )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "api_credentials", "ix_api_credentials_business_id_principal_id"):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.create_index(
                "ix_api_credentials_business_id_principal_id",
                ["business_id", "principal_id"],
                unique=False,
            )

    inspector = sa.inspect(bind)
    if not _has_composite_fk(
        inspector,
        table="api_credentials",
        constrained_columns=("business_id", "principal_id"),
        referred_table="principals",
        referred_columns=("business_id", "id"),
    ):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.create_foreign_key(
                "fk_api_credentials_business_id_principal_id_principals",
                "principals",
                ["business_id", "principal_id"],
                ["business_id", "id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_composite_fk(
        inspector,
        table="api_credentials",
        constrained_columns=("business_id", "principal_id"),
        referred_table="principals",
        referred_columns=("business_id", "id"),
    ):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.drop_constraint("fk_api_credentials_business_id_principal_id_principals", type_="foreignkey")

    inspector = sa.inspect(bind)
    if _has_index(inspector, "api_credentials", "ix_api_credentials_business_id_principal_id"):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.drop_index("ix_api_credentials_business_id_principal_id")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "principals"):
        if _has_index(inspector, "principals", "ix_principals_business_id"):
            op.drop_index("ix_principals_business_id", table_name="principals")
        op.drop_table("principals")

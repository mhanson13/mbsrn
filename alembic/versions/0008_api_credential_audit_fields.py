"""add api credential audit metadata fields

Revision ID: 0008_api_credential_audit
Revises: 0007_principal_roles
Create Date: 2026-03-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector


revision = "0008_api_credential_audit"
down_revision = "0007_principal_roles"
branch_labels = None
depends_on = None


def _has_index(inspector: Inspector, table: str, name: str) -> bool:
    for index in inspector.get_indexes(table):
        if index.get("name") == name:
            return True
    return False


def _has_fk(inspector: Inspector, table: str, name: str) -> bool:
    for foreign_key in inspector.get_foreign_keys(table):
        if foreign_key.get("name") == name:
            return True
    return False


def upgrade() -> None:
    with op.batch_alter_table("api_credentials") as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("rotated_from_credential_id", sa.String(length=36), nullable=True))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_fk(inspector, "api_credentials", "fk_api_credentials_rotated_from_credential_id"):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.create_foreign_key(
                "fk_api_credentials_rotated_from_credential_id",
                "api_credentials",
                ["rotated_from_credential_id"],
                ["id"],
            )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "api_credentials", "ix_api_credentials_last_used_at"):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.create_index("ix_api_credentials_last_used_at", ["last_used_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "api_credentials", "ix_api_credentials_last_used_at"):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.drop_index("ix_api_credentials_last_used_at")

    inspector = sa.inspect(bind)
    if _has_fk(inspector, "api_credentials", "fk_api_credentials_rotated_from_credential_id"):
        with op.batch_alter_table("api_credentials") as batch_op:
            batch_op.drop_constraint("fk_api_credentials_rotated_from_credential_id", type_="foreignkey")

    with op.batch_alter_table("api_credentials") as batch_op:
        batch_op.drop_column("rotated_from_credential_id")
        batch_op.drop_column("last_used_at")
        batch_op.drop_column("label")

"""add principal audit metadata fields

Revision ID: 0009_principal_audit_metadata
Revises: 0008_api_credential_audit
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector


revision = "0009_principal_audit_metadata"
down_revision = "0008_api_credential_audit"
branch_labels = None
depends_on = None


def _has_index(inspector: Inspector, table: str, name: str) -> bool:
    for index in inspector.get_indexes(table):
        if index.get("name") == name:
            return True
    return False


def upgrade() -> None:
    with op.batch_alter_table("principals") as batch_op:
        batch_op.add_column(sa.Column("created_by_principal_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("updated_by_principal_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "principals", "ix_principals_last_authenticated_at"):
        with op.batch_alter_table("principals") as batch_op:
            batch_op.create_index("ix_principals_last_authenticated_at", ["last_authenticated_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, "principals", "ix_principals_last_authenticated_at"):
        with op.batch_alter_table("principals") as batch_op:
            batch_op.drop_index("ix_principals_last_authenticated_at")

    with op.batch_alter_table("principals") as batch_op:
        batch_op.drop_column("last_authenticated_at")
        batch_op.drop_column("updated_by_principal_id")
        batch_op.drop_column("created_by_principal_id")

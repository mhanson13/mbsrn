"""add business migration draft timeout setting

Revision ID: 0051_business_migration_draft_timeout_seconds
Revises: 0050_business_default_ai_model
Create Date: 2026-04-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0051_business_migration_draft_timeout_seconds"
down_revision = "0050_business_default_ai_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(sa.Column("migration_draft_timeout_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_column("migration_draft_timeout_seconds")

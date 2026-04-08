"""add business default ai model setting

Revision ID: 0050_business_default_ai_model
Revises: 0049_seo_migration_publish_and_deploy
Create Date: 2026-04-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0050_business_default_ai_model"
down_revision = "0049_seo_migration_publish_and_deploy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(sa.Column("default_ai_model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_column("default_ai_model")

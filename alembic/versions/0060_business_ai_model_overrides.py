"""add business ai model overrides json

Revision ID: 0060_business_ai_model_overrides
Revises: 0059_competitor_domain_feedback
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0060_business_ai_model_overrides"
down_revision = "0059_competitor_domain_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(sa.Column("ai_model_overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_column("ai_model_overrides")

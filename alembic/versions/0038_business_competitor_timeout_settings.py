"""add business competitor timeout settings

Revision ID: 0038_business_competitor_timeout_settings
Revises: 0037_business_ai_prompt_text_overrides
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0038_business_competitor_timeout_settings"
down_revision = "0037_business_ai_prompt_text_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(sa.Column("competitor_primary_timeout_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("competitor_degraded_timeout_seconds", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_biz_cmp_primary_timeout_seconds",
            (
                "competitor_primary_timeout_seconds IS NULL OR "
                "(competitor_primary_timeout_seconds >= 10 AND competitor_primary_timeout_seconds <= 90)"
            ),
        )
        batch_op.create_check_constraint(
            "ck_biz_cmp_degraded_timeout_seconds",
            (
                "competitor_degraded_timeout_seconds IS NULL OR "
                "(competitor_degraded_timeout_seconds >= 10 AND competitor_degraded_timeout_seconds <= 90)"
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_constraint("ck_biz_cmp_degraded_timeout_seconds", type_="check")
        batch_op.drop_constraint("ck_biz_cmp_primary_timeout_seconds", type_="check")
        batch_op.drop_column("competitor_degraded_timeout_seconds")
        batch_op.drop_column("competitor_primary_timeout_seconds")

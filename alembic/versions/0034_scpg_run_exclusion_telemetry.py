"""add run-level exclusion telemetry for competitor profile generation

Revision ID: 0034_scpg_run_exclusion_telemetry
Revises: 0033_scpg_draft_relevance_score
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0034_scpg_run_exclusion_telemetry"
down_revision = "0033_scpg_draft_relevance_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seo_competitor_profile_generation_runs") as batch_op:
        batch_op.add_column(sa.Column("raw_candidate_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("included_candidate_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("excluded_candidate_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column(
                "exclusion_counts_by_reason",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.create_check_constraint(
            "ck_scpg_runs_candidate_counts_nonneg",
            "raw_candidate_count >= 0 AND included_candidate_count >= 0 AND excluded_candidate_count >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("seo_competitor_profile_generation_runs") as batch_op:
        batch_op.drop_constraint("ck_scpg_runs_candidate_counts_nonneg", type_="check")
        batch_op.drop_column("exclusion_counts_by_reason")
        batch_op.drop_column("excluded_candidate_count")
        batch_op.drop_column("included_candidate_count")
        batch_op.drop_column("raw_candidate_count")

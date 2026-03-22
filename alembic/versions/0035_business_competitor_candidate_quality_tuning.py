"""add business competitor candidate quality tuning settings

Revision ID: 0035_business_competitor_candidate_quality_tuning
Revises: 0034_scpg_run_exclusion_telemetry
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_business_competitor_candidate_quality_tuning"
down_revision = "0034_scpg_run_exclusion_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "competitor_candidate_min_relevance_score",
                sa.Integer(),
                nullable=False,
                server_default="35",
            )
        )
        batch_op.add_column(
            sa.Column(
                "competitor_candidate_big_box_penalty",
                sa.Integer(),
                nullable=False,
                server_default="20",
            )
        )
        batch_op.add_column(
            sa.Column(
                "competitor_candidate_directory_penalty",
                sa.Integer(),
                nullable=False,
                server_default="35",
            )
        )
        batch_op.add_column(
            sa.Column(
                "competitor_candidate_local_alignment_bonus",
                sa.Integer(),
                nullable=False,
                server_default="10",
            )
        )
        batch_op.create_check_constraint(
            "ck_biz_cmp_min_rel_score",
            "competitor_candidate_min_relevance_score >= 0 AND competitor_candidate_min_relevance_score <= 100",
        )
        batch_op.create_check_constraint(
            "ck_biz_cmp_big_box_penalty",
            "competitor_candidate_big_box_penalty >= 0 AND competitor_candidate_big_box_penalty <= 50",
        )
        batch_op.create_check_constraint(
            "ck_biz_cmp_dir_penalty",
            "competitor_candidate_directory_penalty >= 0 AND competitor_candidate_directory_penalty <= 50",
        )
        batch_op.create_check_constraint(
            "ck_biz_cmp_local_bonus",
            "competitor_candidate_local_alignment_bonus >= 0 AND competitor_candidate_local_alignment_bonus <= 50",
        )


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_constraint("ck_biz_cmp_local_bonus", type_="check")
        batch_op.drop_constraint("ck_biz_cmp_dir_penalty", type_="check")
        batch_op.drop_constraint("ck_biz_cmp_big_box_penalty", type_="check")
        batch_op.drop_constraint("ck_biz_cmp_min_rel_score", type_="check")
        batch_op.drop_column("competitor_candidate_local_alignment_bonus")
        batch_op.drop_column("competitor_candidate_directory_penalty")
        batch_op.drop_column("competitor_candidate_big_box_penalty")
        batch_op.drop_column("competitor_candidate_min_relevance_score")

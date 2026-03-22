"""add relevance score to seo competitor profile drafts

Revision ID: 0033_scpg_draft_relevance_score
Revises: 0032_seo_audit_run_crawl_limit_observability
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0033_scpg_draft_relevance_score"
down_revision = "0032_seo_audit_run_crawl_limit_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seo_competitor_profile_drafts") as batch_op:
        batch_op.add_column(sa.Column("relevance_score", sa.Integer(), nullable=False, server_default="50"))
        batch_op.create_check_constraint(
            "ck_scpg_drafts_relevance",
            "relevance_score >= 0 AND relevance_score <= 100",
        )


def downgrade() -> None:
    with op.batch_alter_table("seo_competitor_profile_drafts") as batch_op:
        batch_op.drop_constraint("ck_scpg_drafts_relevance", type_="check")
        batch_op.drop_column("relevance_score")

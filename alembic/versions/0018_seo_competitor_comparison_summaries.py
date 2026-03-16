"""add seo competitor comparison ai summaries

Revision ID: 0018_seo_competitor_comparison_summaries
Revises: 0017_seo_comparison_run_rollups
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_seo_competitor_comparison_summaries"
down_revision = "0017_seo_comparison_run_rollups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_competitor_comparison_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("competitor_set_id", sa.String(length=36), nullable=False),
        sa.Column("comparison_run_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("overall_gap_summary", sa.Text(), nullable=True),
        sa.Column("top_gaps_json", sa.JSON(), nullable=True),
        sa.Column("plain_english_explanation", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(["competitor_set_id"], ["seo_competitor_sets.id"]),
        sa.ForeignKeyConstraint(["comparison_run_id"], ["seo_competitor_comparison_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "comparison_run_id",
            "version",
            name="uq_seo_competitor_comparison_summaries_business_run_version",
        ),
    )
    op.create_index(
        "ix_seo_competitor_comparison_summaries_business_id",
        "seo_competitor_comparison_summaries",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_summaries_site_id",
        "seo_competitor_comparison_summaries",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_summaries_competitor_set_id",
        "seo_competitor_comparison_summaries",
        ["competitor_set_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_summaries_comparison_run_id",
        "seo_competitor_comparison_summaries",
        ["comparison_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_summaries_business_run_created_at",
        "seo_competitor_comparison_summaries",
        ["business_id", "comparison_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_summaries_business_status",
        "seo_competitor_comparison_summaries",
        ["business_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_competitor_comparison_summaries_business_status",
        table_name="seo_competitor_comparison_summaries",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_summaries_business_run_created_at",
        table_name="seo_competitor_comparison_summaries",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_summaries_comparison_run_id",
        table_name="seo_competitor_comparison_summaries",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_summaries_competitor_set_id",
        table_name="seo_competitor_comparison_summaries",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_summaries_site_id",
        table_name="seo_competitor_comparison_summaries",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_summaries_business_id",
        table_name="seo_competitor_comparison_summaries",
    )
    op.drop_table("seo_competitor_comparison_summaries")

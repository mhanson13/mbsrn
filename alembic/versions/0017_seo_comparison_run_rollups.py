"""add seo comparison run rollup fields

Revision ID: 0017_seo_comparison_run_rollups
Revises: 0016_seo_competitor_comparison_foundations
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_seo_comparison_run_rollups"
down_revision = "0016_seo_competitor_comparison_foundations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_competitor_comparison_runs",
        sa.Column("client_pages_analyzed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "seo_competitor_comparison_runs",
        sa.Column("competitor_pages_analyzed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "seo_competitor_comparison_runs",
        sa.Column("metric_rollups_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "seo_competitor_comparison_runs",
        sa.Column("finding_type_counts_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "seo_competitor_comparison_runs",
        sa.Column("category_counts_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "seo_competitor_comparison_runs",
        sa.Column("severity_counts_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("seo_competitor_comparison_runs", "severity_counts_json")
    op.drop_column("seo_competitor_comparison_runs", "category_counts_json")
    op.drop_column("seo_competitor_comparison_runs", "finding_type_counts_json")
    op.drop_column("seo_competitor_comparison_runs", "metric_rollups_json")
    op.drop_column("seo_competitor_comparison_runs", "competitor_pages_analyzed")
    op.drop_column("seo_competitor_comparison_runs", "client_pages_analyzed")

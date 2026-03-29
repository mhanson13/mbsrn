"""add SEO competitor tuning preview events for accuracy tracking

Revision ID: 0036_scpg_tuning_preview_accuracy_events
Revises: 0035_business_competitor_candidate_quality_tuning
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0036_scpg_tuning_preview_accuracy_events"
down_revision = "0035_business_competitor_candidate_quality_tuning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_competitor_tuning_preview_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("source_narrative_id", sa.String(length=36), nullable=True),
        sa.Column("source_recommendation_run_id", sa.String(length=36), nullable=True),
        sa.Column("preview_request", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("preview_response", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_generation_run_id", sa.String(length=36), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_included_delta", sa.Integer(), nullable=True),
        sa.Column("actual_included_delta", sa.Integer(), nullable=True),
        sa.Column("error_margin", sa.Integer(), nullable=True),
        sa.Column("direction_correct", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("error_margin IS NULL OR error_margin >= 0", name="ck_sctpe_error_margin_nonneg"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(["source_narrative_id"], ["seo_recommendation_narratives.id"]),
        sa.ForeignKeyConstraint(["source_recommendation_run_id"], ["seo_recommendation_runs.id"]),
        sa.ForeignKeyConstraint(
            ["evaluated_generation_run_id"],
            ["seo_competitor_profile_generation_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sctpe_biz_site_created",
        "seo_competitor_tuning_preview_events",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_sctpe_biz_site_applied",
        "seo_competitor_tuning_preview_events",
        ["business_id", "site_id", "applied_at"],
        unique=False,
    )
    op.create_index(
        "ix_sctpe_biz_site_eval",
        "seo_competitor_tuning_preview_events",
        ["business_id", "site_id", "evaluated_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_tuning_preview_events_business_id",
        "seo_competitor_tuning_preview_events",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_tuning_preview_events_site_id",
        "seo_competitor_tuning_preview_events",
        ["site_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seo_competitor_tuning_preview_events_site_id", table_name="seo_competitor_tuning_preview_events")
    op.drop_index(
        "ix_seo_competitor_tuning_preview_events_business_id", table_name="seo_competitor_tuning_preview_events"
    )
    op.drop_index("ix_sctpe_biz_site_eval", table_name="seo_competitor_tuning_preview_events")
    op.drop_index("ix_sctpe_biz_site_applied", table_name="seo_competitor_tuning_preview_events")
    op.drop_index("ix_sctpe_biz_site_created", table_name="seo_competitor_tuning_preview_events")
    op.drop_table("seo_competitor_tuning_preview_events")

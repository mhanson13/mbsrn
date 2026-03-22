"""add scpg observability fields and cleanup execution table

Revision ID: 0030_scpg_observability
Revises: 0029_scpg_run_raw_output
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0030_scpg_observability"
down_revision = "0029_scpg_run_raw_output"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seo_competitor_profile_generation_runs") as batch_op:
        batch_op.add_column(sa.Column("failure_category", sa.String(length=64), nullable=True))
        batch_op.create_check_constraint(
            "ck_scpg_runs_failure_cat",
            (
                "failure_category IS NULL OR failure_category IN "
                "('timeout', 'provider_auth', 'provider_config', 'malformed_output', "
                "'schema_validation', 'internal_error', 'provider_request', 'unknown')"
            ),
        )
        batch_op.create_index(
            "ix_scpg_runs_biz_site_failcat",
            ["business_id", "site_id", "failure_category"],
            unique=False,
        )

    op.create_table(
        "seo_competitor_profile_cleanup_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stale_runs_reconciled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_output_pruned_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_drafts_pruned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_pruned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="ck_scpg_cleanup_status"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scpg_cleanup_biz_site_started",
        "seo_competitor_profile_cleanup_executions",
        ["business_id", "site_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_scpg_cleanup_biz_status_started",
        "seo_competitor_profile_cleanup_executions",
        ["business_id", "status", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_cleanup_executions_business_id",
        "seo_competitor_profile_cleanup_executions",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_cleanup_executions_site_id",
        "seo_competitor_profile_cleanup_executions",
        ["site_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_competitor_profile_cleanup_executions_site_id",
        table_name="seo_competitor_profile_cleanup_executions",
    )
    op.drop_index(
        "ix_seo_competitor_profile_cleanup_executions_business_id",
        table_name="seo_competitor_profile_cleanup_executions",
    )
    op.drop_index(
        "ix_scpg_cleanup_biz_status_started",
        table_name="seo_competitor_profile_cleanup_executions",
    )
    op.drop_index(
        "ix_scpg_cleanup_biz_site_started",
        table_name="seo_competitor_profile_cleanup_executions",
    )
    op.drop_table("seo_competitor_profile_cleanup_executions")

    with op.batch_alter_table("seo_competitor_profile_generation_runs") as batch_op:
        batch_op.drop_index("ix_scpg_runs_biz_site_failcat")
        batch_op.drop_constraint("ck_scpg_runs_failure_cat", type_="check")
        batch_op.drop_column("failure_category")

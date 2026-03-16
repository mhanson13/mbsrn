"""add seo automation config and run tracking

Revision ID: 0022_seo_automation_operationalization
Revises: 0021_seo_recommendation_narratives
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_seo_automation_operationalization"
down_revision = "0021_seo_recommendation_narratives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_automation_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cadence_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("cadence_minutes", sa.Integer(), nullable=True),
        sa.Column("trigger_audit", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trigger_audit_summary", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trigger_competitor_snapshot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trigger_comparison", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trigger_competitor_summary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trigger_recommendations", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trigger_recommendation_narrative", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "cadence_type IN ('manual', 'interval_minutes')",
            name="ck_seo_automation_configs_cadence_type",
        ),
        sa.CheckConstraint(
            "(cadence_type = 'manual' AND cadence_minutes IS NULL) OR "
            "(cadence_type = 'interval_minutes' AND cadence_minutes IS NOT NULL AND cadence_minutes >= 5)",
            name="ck_seo_automation_configs_cadence_minutes",
        ),
        sa.CheckConstraint(
            "last_status IS NULL OR last_status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="ck_seo_automation_configs_last_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "site_id", name="uq_seo_automation_configs_business_site"),
    )
    op.create_index(
        "ix_seo_automation_configs_business_id",
        "seo_automation_configs",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_configs_site_id",
        "seo_automation_configs",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_configs_business_enabled_next_run",
        "seo_automation_configs",
        ["business_id", "is_enabled", "next_run_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_configs_business_site_enabled",
        "seo_automation_configs",
        ["business_id", "site_id", "is_enabled"],
        unique=False,
    )

    op.create_table(
        "seo_automation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("automation_config_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("steps_json", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "trigger_source IN ('manual', 'scheduled')",
            name="ck_seo_automation_runs_trigger_source",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="ck_seo_automation_runs_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(["automation_config_id"], ["seo_automation_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_seo_automation_runs_business_id",
        "seo_automation_runs",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_runs_site_id",
        "seo_automation_runs",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_runs_automation_config_id",
        "seo_automation_runs",
        ["automation_config_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_runs_business_site_created_at",
        "seo_automation_runs",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_runs_business_site_status",
        "seo_automation_runs",
        ["business_id", "site_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_seo_automation_runs_business_config_created_at",
        "seo_automation_runs",
        ["business_id", "automation_config_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seo_automation_runs_business_config_created_at", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_business_site_status", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_business_site_created_at", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_automation_config_id", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_site_id", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_business_id", table_name="seo_automation_runs")
    op.drop_table("seo_automation_runs")

    op.drop_index("ix_seo_automation_configs_business_site_enabled", table_name="seo_automation_configs")
    op.drop_index("ix_seo_automation_configs_business_enabled_next_run", table_name="seo_automation_configs")
    op.drop_index("ix_seo_automation_configs_site_id", table_name="seo_automation_configs")
    op.drop_index("ix_seo_automation_configs_business_id", table_name="seo_automation_configs")
    op.drop_table("seo_automation_configs")

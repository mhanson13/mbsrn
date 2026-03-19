"""add seo competitor deterministic comparison foundations

Revision ID: 0016_seo_competitor_comparison_foundations
Revises: 0015_seo_competitor_phase2a_foundations
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_seo_competitor_comparison_foundations"
down_revision = "0015_seo_competitor_phase2a_foundations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_competitor_comparison_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("competitor_set_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_run_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_audit_run_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("total_findings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_findings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_findings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("info_findings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["snapshot_run_id"], ["seo_competitor_snapshot_runs.id"]),
        sa.ForeignKeyConstraint(["baseline_audit_run_id"], ["seo_audit_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_business_id",
        "seo_competitor_comparison_runs",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_site_id",
        "seo_competitor_comparison_runs",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_competitor_set_id",
        "seo_competitor_comparison_runs",
        ["competitor_set_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_snapshot_run_id",
        "seo_competitor_comparison_runs",
        ["snapshot_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_baseline_audit_run_id",
        "seo_competitor_comparison_runs",
        ["baseline_audit_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_business_set_created_at",
        "seo_competitor_comparison_runs",
        ["business_id", "competitor_set_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_business_status",
        "seo_competitor_comparison_runs",
        ["business_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_runs_business_snapshot_run",
        "seo_competitor_comparison_runs",
        ["business_id", "snapshot_run_id"],
        unique=False,
    )

    op.create_table(
        "seo_competitor_comparison_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("competitor_set_id", sa.String(length=36), nullable=False),
        sa.Column("comparison_run_id", sa.String(length=36), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("rule_key", sa.String(length=128), nullable=False),
        sa.Column("client_value", sa.Text(), nullable=True),
        sa.Column("competitor_value", sa.Text(), nullable=True),
        sa.Column("gap_direction", sa.String(length=32), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
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
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_business_id",
        "seo_competitor_comparison_findings",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_site_id",
        "seo_competitor_comparison_findings",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_competitor_set_id",
        "seo_competitor_comparison_findings",
        ["competitor_set_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_comparison_run_id",
        "seo_competitor_comparison_findings",
        ["comparison_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_finding_type",
        "seo_competitor_comparison_findings",
        ["finding_type"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_category",
        "seo_competitor_comparison_findings",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_severity",
        "seo_competitor_comparison_findings",
        ["severity"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_rule_key",
        "seo_competitor_comparison_findings",
        ["rule_key"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_business_run_created_at",
        "seo_competitor_comparison_findings",
        ["business_id", "comparison_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_business_category",
        "seo_competitor_comparison_findings",
        ["business_id", "category"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_business_severity",
        "seo_competitor_comparison_findings",
        ["business_id", "severity"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_comparison_findings_business_finding_type",
        "seo_competitor_comparison_findings",
        ["business_id", "finding_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_competitor_comparison_findings_business_finding_type",
        table_name="seo_competitor_comparison_findings",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_findings_business_severity",
        table_name="seo_competitor_comparison_findings",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_findings_business_category",
        table_name="seo_competitor_comparison_findings",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_findings_business_run_created_at",
        table_name="seo_competitor_comparison_findings",
    )
    op.drop_index("ix_seo_competitor_comparison_findings_rule_key", table_name="seo_competitor_comparison_findings")
    op.drop_index("ix_seo_competitor_comparison_findings_severity", table_name="seo_competitor_comparison_findings")
    op.drop_index("ix_seo_competitor_comparison_findings_category", table_name="seo_competitor_comparison_findings")
    op.drop_index("ix_seo_competitor_comparison_findings_finding_type", table_name="seo_competitor_comparison_findings")
    op.drop_index(
        "ix_seo_competitor_comparison_findings_comparison_run_id", table_name="seo_competitor_comparison_findings"
    )
    op.drop_index(
        "ix_seo_competitor_comparison_findings_competitor_set_id", table_name="seo_competitor_comparison_findings"
    )
    op.drop_index("ix_seo_competitor_comparison_findings_site_id", table_name="seo_competitor_comparison_findings")
    op.drop_index("ix_seo_competitor_comparison_findings_business_id", table_name="seo_competitor_comparison_findings")
    op.drop_table("seo_competitor_comparison_findings")

    op.drop_index(
        "ix_seo_competitor_comparison_runs_business_snapshot_run",
        table_name="seo_competitor_comparison_runs",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_runs_business_status",
        table_name="seo_competitor_comparison_runs",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_runs_business_set_created_at",
        table_name="seo_competitor_comparison_runs",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_runs_baseline_audit_run_id",
        table_name="seo_competitor_comparison_runs",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_runs_snapshot_run_id",
        table_name="seo_competitor_comparison_runs",
    )
    op.drop_index(
        "ix_seo_competitor_comparison_runs_competitor_set_id",
        table_name="seo_competitor_comparison_runs",
    )
    op.drop_index("ix_seo_competitor_comparison_runs_site_id", table_name="seo_competitor_comparison_runs")
    op.drop_index("ix_seo_competitor_comparison_runs_business_id", table_name="seo_competitor_comparison_runs")
    op.drop_table("seo_competitor_comparison_runs")

"""add seo competitor profile generation runs and drafts

Revision ID: 0026_seo_competitor_profile_generation_drafts
Revises: 0025_seo_site_audit_lifecycle_fields
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0026_seo_competitor_profile_generation_drafts"
down_revision = "0025_seo_site_audit_lifecycle_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_competitor_profile_generation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("requested_candidate_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("generated_draft_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_name", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default="unknown"),
        sa.Column("prompt_version", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_seo_competitor_profile_generation_runs_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_seo_competitor_profile_generation_runs_business_id",
        "seo_competitor_profile_generation_runs",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_generation_runs_site_id",
        "seo_competitor_profile_generation_runs",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_generation_runs_business_site_created_at",
        "seo_competitor_profile_generation_runs",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_generation_runs_business_status",
        "seo_competitor_profile_generation_runs",
        ["business_id", "status"],
        unique=False,
    )

    op.create_table(
        "seo_competitor_profile_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("generation_run_id", sa.String(length=36), nullable=False),
        sa.Column("suggested_name", sa.String(length=255), nullable=False),
        sa.Column("suggested_domain", sa.String(length=255), nullable=False),
        sa.Column("competitor_type", sa.String(length=64), nullable=False, server_default="direct"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("why_competitor", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="ai_generated"),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("edited_fields_json", sa.JSON(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_competitor_set_id", sa.String(length=36), nullable=True),
        sa.Column("accepted_competitor_domain_id", sa.String(length=36), nullable=True),
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
            "review_status IN ('pending', 'edited', 'accepted', 'rejected')",
            name="ck_seo_competitor_profile_drafts_review_status",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_seo_competitor_profile_drafts_confidence_score",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["seo_competitor_profile_generation_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["accepted_competitor_set_id"],
            ["seo_competitor_sets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["accepted_competitor_domain_id"],
            ["seo_competitor_domains.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "generation_run_id",
            "suggested_domain",
            name="uq_seo_competitor_profile_drafts_business_run_domain",
        ),
    )
    op.create_index(
        "ix_seo_competitor_profile_drafts_business_id",
        "seo_competitor_profile_drafts",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_drafts_site_id",
        "seo_competitor_profile_drafts",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_drafts_generation_run_id",
        "seo_competitor_profile_drafts",
        ["generation_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_drafts_business_run_created_at",
        "seo_competitor_profile_drafts",
        ["business_id", "generation_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_drafts_business_site_created_at",
        "seo_competitor_profile_drafts",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_competitor_profile_drafts_business_review_status",
        "seo_competitor_profile_drafts",
        ["business_id", "review_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_competitor_profile_drafts_business_review_status",
        table_name="seo_competitor_profile_drafts",
    )
    op.drop_index(
        "ix_seo_competitor_profile_drafts_business_site_created_at",
        table_name="seo_competitor_profile_drafts",
    )
    op.drop_index(
        "ix_seo_competitor_profile_drafts_business_run_created_at",
        table_name="seo_competitor_profile_drafts",
    )
    op.drop_index(
        "ix_seo_competitor_profile_drafts_generation_run_id",
        table_name="seo_competitor_profile_drafts",
    )
    op.drop_index("ix_seo_competitor_profile_drafts_site_id", table_name="seo_competitor_profile_drafts")
    op.drop_index("ix_seo_competitor_profile_drafts_business_id", table_name="seo_competitor_profile_drafts")
    op.drop_table("seo_competitor_profile_drafts")

    op.drop_index(
        "ix_seo_competitor_profile_generation_runs_business_status",
        table_name="seo_competitor_profile_generation_runs",
    )
    op.drop_index(
        "ix_seo_competitor_profile_generation_runs_business_site_created_at",
        table_name="seo_competitor_profile_generation_runs",
    )
    op.drop_index(
        "ix_seo_competitor_profile_generation_runs_site_id",
        table_name="seo_competitor_profile_generation_runs",
    )
    op.drop_index(
        "ix_seo_competitor_profile_generation_runs_business_id",
        table_name="seo_competitor_profile_generation_runs",
    )
    op.drop_table("seo_competitor_profile_generation_runs")

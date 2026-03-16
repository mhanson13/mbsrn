"""add seo recommendation narrative summaries

Revision ID: 0021_seo_recommendation_narratives
Revises: 0020_seo_recommendation_workflow_fields
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021_seo_recommendation_narratives"
down_revision = "0020_seo_recommendation_workflow_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_recommendation_narratives",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("recommendation_run_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("narrative_text", sa.Text(), nullable=True),
        sa.Column("top_themes_json", sa.JSON(), nullable=True),
        sa.Column("sections_json", sa.JSON(), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "status IN ('completed', 'failed')",
            name="ck_seo_recommendation_narratives_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(["recommendation_run_id"], ["seo_recommendation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "recommendation_run_id",
            "version",
            name="uq_seo_recommendation_narratives_business_run_version",
        ),
    )
    op.create_index(
        "ix_seo_recommendation_narratives_business_id",
        "seo_recommendation_narratives",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_recommendation_narratives_site_id",
        "seo_recommendation_narratives",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_recommendation_narratives_recommendation_run_id",
        "seo_recommendation_narratives",
        ["recommendation_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_recommendation_narratives_business_run_created_at",
        "seo_recommendation_narratives",
        ["business_id", "recommendation_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_recommendation_narratives_business_site_created_at",
        "seo_recommendation_narratives",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_recommendation_narratives_business_status",
        "seo_recommendation_narratives",
        ["business_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seo_recommendation_narratives_business_status", table_name="seo_recommendation_narratives")
    op.drop_index(
        "ix_seo_recommendation_narratives_business_site_created_at",
        table_name="seo_recommendation_narratives",
    )
    op.drop_index(
        "ix_seo_recommendation_narratives_business_run_created_at",
        table_name="seo_recommendation_narratives",
    )
    op.drop_index(
        "ix_seo_recommendation_narratives_recommendation_run_id",
        table_name="seo_recommendation_narratives",
    )
    op.drop_index("ix_seo_recommendation_narratives_site_id", table_name="seo_recommendation_narratives")
    op.drop_index("ix_seo_recommendation_narratives_business_id", table_name="seo_recommendation_narratives")
    op.drop_table("seo_recommendation_narratives")

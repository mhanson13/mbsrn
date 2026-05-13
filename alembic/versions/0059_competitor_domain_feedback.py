"""add operator competitor domain feedback table

Revision ID: 0059_competitor_domain_feedback
Revises: 0058_github_publish_config_repo_auto_create
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0059_competitor_domain_feedback"
down_revision = "0058_github_publish_config_repo_auto_create"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_competitor_domain_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("feedback_status", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_principal_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "site_id",
            "domain",
            name="uq_seo_competitor_domain_feedback_business_site_domain",
        ),
    )
    op.create_index(
        "ix_seo_competitor_domain_feedback_business_site_status",
        "seo_competitor_domain_feedback",
        ["business_id", "site_id", "feedback_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_seo_competitor_domain_feedback_business_id"),
        "seo_competitor_domain_feedback",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_seo_competitor_domain_feedback_site_id"),
        "seo_competitor_domain_feedback",
        ["site_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_seo_competitor_domain_feedback_site_id"), table_name="seo_competitor_domain_feedback")
    op.drop_index(op.f("ix_seo_competitor_domain_feedback_business_id"), table_name="seo_competitor_domain_feedback")
    op.drop_index(
        "ix_seo_competitor_domain_feedback_business_site_status",
        table_name="seo_competitor_domain_feedback",
    )
    op.drop_table("seo_competitor_domain_feedback")

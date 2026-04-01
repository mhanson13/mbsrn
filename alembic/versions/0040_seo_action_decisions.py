"""add persisted seo action decisions

Revision ID: 0040_seo_action_decisions
Revises: 0039_competitor_domain_verification_status
Create Date: 2026-04-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0040_seo_action_decisions"
down_revision = "0039_competitor_domain_verification_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_action_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'deferred')",
            name="ck_seo_action_decisions_decision",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "site_id",
            "action_id",
            name="uq_seo_action_decisions_business_site_action",
        ),
    )
    op.create_index(
        "ix_seo_action_decisions_business_id",
        "seo_action_decisions",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_decisions_site_id",
        "seo_action_decisions",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_decisions_action_id",
        "seo_action_decisions",
        ["action_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_decisions_business_site_updated_at",
        "seo_action_decisions",
        ["business_id", "site_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_seo_action_decisions_business_site_updated_at", table_name="seo_action_decisions")
    op.drop_index("ix_seo_action_decisions_action_id", table_name="seo_action_decisions")
    op.drop_index("ix_seo_action_decisions_site_id", table_name="seo_action_decisions")
    op.drop_index("ix_seo_action_decisions_business_id", table_name="seo_action_decisions")
    op.drop_table("seo_action_decisions")

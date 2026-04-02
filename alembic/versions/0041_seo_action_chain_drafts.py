"""add deterministic action chain drafts

Revision ID: 0041_seo_action_chain_drafts
Revises: 0040_seo_action_decisions
Create Date: 2026-04-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0041_seo_action_chain_drafts"
down_revision = "0040_seo_action_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_action_chain_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("source_action_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'completed', 'dismissed')",
            name="ck_seo_action_chain_drafts_state",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "site_id",
            "source_action_id",
            "action_type",
            name="uq_seo_action_chain_drafts_source_action_type",
        ),
    )
    op.create_index(
        "ix_seo_action_chain_drafts_business_id",
        "seo_action_chain_drafts",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_site_id",
        "seo_action_chain_drafts",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_source_action_id",
        "seo_action_chain_drafts",
        ["source_action_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_action_type",
        "seo_action_chain_drafts",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_state",
        "seo_action_chain_drafts",
        ["state"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_business_site_created_at",
        "seo_action_chain_drafts",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_business_site_source_action",
        "seo_action_chain_drafts",
        ["business_id", "site_id", "source_action_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_action_chain_drafts_business_site_source_action",
        table_name="seo_action_chain_drafts",
    )
    op.drop_index(
        "ix_seo_action_chain_drafts_business_site_created_at",
        table_name="seo_action_chain_drafts",
    )
    op.drop_index("ix_seo_action_chain_drafts_state", table_name="seo_action_chain_drafts")
    op.drop_index("ix_seo_action_chain_drafts_action_type", table_name="seo_action_chain_drafts")
    op.drop_index("ix_seo_action_chain_drafts_source_action_id", table_name="seo_action_chain_drafts")
    op.drop_index("ix_seo_action_chain_drafts_site_id", table_name="seo_action_chain_drafts")
    op.drop_index("ix_seo_action_chain_drafts_business_id", table_name="seo_action_chain_drafts")
    op.drop_table("seo_action_chain_drafts")


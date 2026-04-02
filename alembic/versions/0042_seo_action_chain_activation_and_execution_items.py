"""add activation fields for chained drafts and action execution items

Revision ID: 0042_seo_action_chain_activation_and_execution_items
Revises: 0041_seo_action_chain_drafts
Create Date: 2026-04-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0042_seo_action_chain_activation_and_execution_items"
down_revision = "0041_seo_action_chain_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_action_chain_drafts",
        sa.Column("activation_state", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "seo_action_chain_drafts",
        sa.Column("activated_action_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "seo_action_chain_drafts",
        sa.Column("automation_template_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "seo_action_chain_drafts",
        sa.Column("automation_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_seo_action_chain_drafts_activation_state",
        "seo_action_chain_drafts",
        "activation_state IN ('pending', 'activated')",
    )
    op.create_index(
        "ix_seo_action_chain_drafts_activation_state",
        "seo_action_chain_drafts",
        ["activation_state"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_chain_drafts_activated_action_id",
        "seo_action_chain_drafts",
        ["activated_action_id"],
        unique=False,
    )

    op.create_table(
        "seo_action_execution_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("source_action_id", sa.String(length=36), nullable=False),
        sa.Column("source_draft_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("automation_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("automation_template_key", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'in_progress', 'completed', 'blocked')",
            name="ck_seo_action_execution_items_state",
        ),
        sa.CheckConstraint(
            "source IN ('chained')",
            name="ck_seo_action_execution_items_source",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(["source_draft_id"], ["seo_action_chain_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "site_id",
            "source_draft_id",
            name="uq_seo_action_execution_items_source_draft",
        ),
    )
    op.create_index(
        "ix_seo_action_execution_items_business_id",
        "seo_action_execution_items",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_site_id",
        "seo_action_execution_items",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_source_action_id",
        "seo_action_execution_items",
        ["source_action_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_source_draft_id",
        "seo_action_execution_items",
        ["source_draft_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_action_type",
        "seo_action_execution_items",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_state",
        "seo_action_execution_items",
        ["state"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_business_site_created_at",
        "seo_action_execution_items",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_business_site_state",
        "seo_action_execution_items",
        ["business_id", "site_id", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_action_execution_items_business_site_state",
        table_name="seo_action_execution_items",
    )
    op.drop_index(
        "ix_seo_action_execution_items_business_site_created_at",
        table_name="seo_action_execution_items",
    )
    op.drop_index("ix_seo_action_execution_items_state", table_name="seo_action_execution_items")
    op.drop_index("ix_seo_action_execution_items_action_type", table_name="seo_action_execution_items")
    op.drop_index("ix_seo_action_execution_items_source_draft_id", table_name="seo_action_execution_items")
    op.drop_index("ix_seo_action_execution_items_source_action_id", table_name="seo_action_execution_items")
    op.drop_index("ix_seo_action_execution_items_site_id", table_name="seo_action_execution_items")
    op.drop_index("ix_seo_action_execution_items_business_id", table_name="seo_action_execution_items")
    op.drop_table("seo_action_execution_items")

    op.drop_index("ix_seo_action_chain_drafts_activated_action_id", table_name="seo_action_chain_drafts")
    op.drop_index("ix_seo_action_chain_drafts_activation_state", table_name="seo_action_chain_drafts")
    op.drop_constraint(
        "ck_seo_action_chain_drafts_activation_state",
        "seo_action_chain_drafts",
        type_="check",
    )
    op.drop_column("seo_action_chain_drafts", "automation_ready")
    op.drop_column("seo_action_chain_drafts", "automation_template_key")
    op.drop_column("seo_action_chain_drafts", "activated_action_id")
    op.drop_column("seo_action_chain_drafts", "activation_state")


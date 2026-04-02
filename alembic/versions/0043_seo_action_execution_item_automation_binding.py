"""add automation binding fields for action execution items

Revision ID: 0043_seo_action_execution_item_automation_binding
Revises: 0042_seo_action_chain_activation_and_execution_items
Create Date: 2026-04-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0043_seo_action_execution_item_automation_binding"
down_revision = "0042_seo_action_chain_activation_and_execution_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_action_execution_items",
        sa.Column("bound_automation_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "seo_action_execution_items",
        sa.Column(
            "automation_binding_state",
            sa.String(length=16),
            nullable=False,
            server_default="unbound",
        ),
    )
    op.add_column(
        "seo_action_execution_items",
        sa.Column("automation_bound_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_seo_action_execution_items_automation_binding_state",
        "seo_action_execution_items",
        "automation_binding_state IN ('unbound', 'bound')",
    )
    op.create_foreign_key(
        "fk_seo_action_execution_items_bound_automation_id",
        "seo_action_execution_items",
        "seo_automation_configs",
        ["bound_automation_id"],
        ["id"],
    )
    op.create_index(
        "ix_seo_action_execution_items_bound_automation_id",
        "seo_action_execution_items",
        ["bound_automation_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_automation_binding_state",
        "seo_action_execution_items",
        ["automation_binding_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_action_execution_items_automation_binding_state",
        table_name="seo_action_execution_items",
    )
    op.drop_index(
        "ix_seo_action_execution_items_bound_automation_id",
        table_name="seo_action_execution_items",
    )
    op.drop_constraint(
        "fk_seo_action_execution_items_bound_automation_id",
        "seo_action_execution_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_seo_action_execution_items_automation_binding_state",
        "seo_action_execution_items",
        type_="check",
    )
    op.drop_column("seo_action_execution_items", "automation_bound_at")
    op.drop_column("seo_action_execution_items", "automation_binding_state")
    op.drop_column("seo_action_execution_items", "bound_automation_id")


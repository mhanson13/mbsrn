"""add automation execution gating fields for action execution items

Revision ID: 0044_seo_action_execution_item_automation_execution
Revises: 0043_seo_action_execution_item_automation_binding
Create Date: 2026-04-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0044_seo_action_execution_item_automation_execution"
down_revision = "0043_seo_action_execution_item_automation_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_action_execution_items",
        sa.Column(
            "automation_execution_state",
            sa.String(length=24),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "seo_action_execution_items",
        sa.Column("automation_execution_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "seo_action_execution_items",
        sa.Column("automation_execution_requested_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "seo_action_execution_items",
        sa.Column("last_automation_run_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "seo_action_execution_items",
        sa.Column("automation_last_executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_seo_action_execution_items_automation_execution_state",
        "seo_action_execution_items",
        "automation_execution_state IN ('not_requested', 'requested', 'running', 'succeeded', 'failed')",
    )
    op.create_foreign_key(
        "fk_seo_action_execution_items_last_automation_run_id",
        "seo_action_execution_items",
        "seo_automation_runs",
        ["last_automation_run_id"],
        ["id"],
    )
    op.create_index(
        "ix_seo_action_execution_items_automation_execution_state",
        "seo_action_execution_items",
        ["automation_execution_state"],
        unique=False,
    )
    op.create_index(
        "ix_seo_action_execution_items_last_automation_run_id",
        "seo_action_execution_items",
        ["last_automation_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_action_execution_items_last_automation_run_id",
        table_name="seo_action_execution_items",
    )
    op.drop_index(
        "ix_seo_action_execution_items_automation_execution_state",
        table_name="seo_action_execution_items",
    )
    op.drop_constraint(
        "fk_seo_action_execution_items_last_automation_run_id",
        "seo_action_execution_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_seo_action_execution_items_automation_execution_state",
        "seo_action_execution_items",
        type_="check",
    )
    op.drop_column("seo_action_execution_items", "automation_last_executed_at")
    op.drop_column("seo_action_execution_items", "last_automation_run_id")
    op.drop_column("seo_action_execution_items", "automation_execution_requested_by")
    op.drop_column("seo_action_execution_items", "automation_execution_requested_at")
    op.drop_column("seo_action_execution_items", "automation_execution_state")


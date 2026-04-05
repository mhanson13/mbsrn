"""add per-site Search Console configuration fields

Revision ID: 0045_seo_sites_search_console_config
Revises: 0044_seo_action_execution_item_automation_execution
Create Date: 2026-04-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0045_seo_sites_search_console_config"
down_revision = "0044_seo_action_execution_item_automation_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_sites",
        sa.Column("search_console_property_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "seo_sites",
        sa.Column(
            "search_console_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("seo_sites", "search_console_enabled")
    op.drop_column("seo_sites", "search_console_property_url")


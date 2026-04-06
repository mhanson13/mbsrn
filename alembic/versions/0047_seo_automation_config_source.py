"""add automation config source provenance field

Revision ID: 0047_seo_automation_config_source
Revises: 0046_seo_sites_ga4_onboarding_config
Create Date: 2026-04-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0047_seo_automation_config_source"
down_revision = "0046_seo_sites_ga4_onboarding_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_automation_configs",
        sa.Column(
            "config_source",
            sa.String(length=16),
            nullable=False,
            server_default="site",
        ),
    )
    op.create_check_constraint(
        "ck_seo_automation_configs_config_source",
        "seo_automation_configs",
        "config_source IN ('default', 'site')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_seo_automation_configs_config_source",
        "seo_automation_configs",
        type_="check",
    )
    op.drop_column("seo_automation_configs", "config_source")


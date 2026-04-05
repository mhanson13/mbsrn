"""add per-site GA4 onboarding configuration fields

Revision ID: 0046_seo_sites_ga4_onboarding_config
Revises: 0045_seo_sites_search_console_config
Create Date: 2026-04-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0046_seo_sites_ga4_onboarding_config"
down_revision = "0045_seo_sites_search_console_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_sites",
        sa.Column(
            "ga4_onboarding_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_connected",
        ),
    )
    op.add_column(
        "seo_sites",
        sa.Column("ga4_account_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "seo_sites",
        sa.Column("ga4_property_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "seo_sites",
        sa.Column("ga4_data_stream_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "seo_sites",
        sa.Column("ga4_measurement_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("seo_sites", "ga4_measurement_id")
    op.drop_column("seo_sites", "ga4_data_stream_id")
    op.drop_column("seo_sites", "ga4_property_id")
    op.drop_column("seo_sites", "ga4_account_id")
    op.drop_column("seo_sites", "ga4_onboarding_status")


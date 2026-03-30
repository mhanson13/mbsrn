"""add competitor domain verification status

Revision ID: 0039_competitor_domain_verification_status
Revises: 0038_business_competitor_timeout_settings
Create Date: 2026-03-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0039_competitor_domain_verification_status"
down_revision = "0038_business_competitor_timeout_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seo_competitor_domains") as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=16),
                nullable=False,
                server_default="verified",
            )
        )
        batch_op.create_check_constraint(
            "ck_seo_competitor_domains_verification_status",
            "verification_status IN ('verified', 'unverified')",
        )


def downgrade() -> None:
    with op.batch_alter_table("seo_competitor_domains") as batch_op:
        batch_op.drop_constraint("ck_seo_competitor_domains_verification_status", type_="check")
        batch_op.drop_column("verification_status")

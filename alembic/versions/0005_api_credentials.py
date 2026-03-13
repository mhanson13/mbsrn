"""add persisted api credentials for principal-bound tenant resolution

Revision ID: 0005_api_credentials
Revises: 0004_lead_events_tenant_fk
Create Date: 2026-03-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_api_credentials"
down_revision = "0004_lead_events_tenant_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("business_id", sa.String(length=36), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_api_credentials_business_id", "api_credentials", ["business_id"], unique=False)
    op.create_index("ix_api_credentials_principal_id", "api_credentials", ["principal_id"], unique=False)
    op.create_index("ix_api_credentials_token_hash", "api_credentials", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_credentials_token_hash", table_name="api_credentials")
    op.drop_index("ix_api_credentials_principal_id", table_name="api_credentials")
    op.drop_index("ix_api_credentials_business_id", table_name="api_credentials")
    op.drop_table("api_credentials")

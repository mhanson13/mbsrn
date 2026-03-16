"""add principal identities for external auth providers

Revision ID: 0023_principal_identities_google_auth
Revises: 0022_seo_automation_operationalization
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0023_principal_identities_google_auth"
down_revision = "0022_seo_automation_operationalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "principal_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name="fk_principal_identities_business_id_businesses",
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "principal_id"],
            ["principals.business_id", "principals.id"],
            name="fk_principal_identities_business_id_principal_id_principals",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_principal_identities_provider_subject"),
        sa.UniqueConstraint(
            "provider",
            "business_id",
            "principal_id",
            name="uq_principal_identities_provider_business_principal",
        ),
    )
    op.create_index("ix_principal_identities_business_id", "principal_identities", ["business_id"], unique=False)
    op.create_index("ix_principal_identities_principal_id", "principal_identities", ["principal_id"], unique=False)
    op.create_index(
        "ix_principal_identities_business_principal",
        "principal_identities",
        ["business_id", "principal_id"],
        unique=False,
    )
    op.create_index(
        "ix_principal_identities_provider_business",
        "principal_identities",
        ["provider", "business_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_principal_identities_provider_business", table_name="principal_identities")
    op.drop_index("ix_principal_identities_business_principal", table_name="principal_identities")
    op.drop_index("ix_principal_identities_principal_id", table_name="principal_identities")
    op.drop_index("ix_principal_identities_business_id", table_name="principal_identities")
    op.drop_table("principal_identities")

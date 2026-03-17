"""add provider oauth state and connection persistence for google business profile

Revision ID: 0024_google_business_profile_oauth_connections
Revises: 0023_principal_identities_google_auth
Create Date: 2026-03-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0024_google_business_profile_oauth_connections"
down_revision = "0023_principal_identities_google_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("updated_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("granted_scopes", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("token_key_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_subject", sa.String(length=255), nullable=True),
        sa.Column("external_account_email", sa.String(length=320), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_provider_connections_business_id_businesses",
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "principal_id"],
            ["principals.business_id", "principals.id"],
            name="fk_provider_connections_business_id_principal_id_principals",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "business_id", name="uq_provider_connections_provider_business"),
    )
    op.create_index("ix_provider_connections_business_id", "provider_connections", ["business_id"], unique=False)
    op.create_index("ix_provider_connections_principal_id", "provider_connections", ["principal_id"], unique=False)
    op.create_index(
        "ix_provider_connections_business_provider",
        "provider_connections",
        ["business_id", "provider"],
        unique=False,
    )
    op.create_index(
        "ix_provider_connections_business_principal",
        "provider_connections",
        ["business_id", "principal_id"],
        unique=False,
    )

    op.create_table(
        "provider_oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=True),
        sa.Column("code_verifier_key_version", sa.String(length=32), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_provider_oauth_states_business_id_businesses",
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "principal_id"],
            ["principals.business_id", "principals.id"],
            name="fk_provider_oauth_states_business_id_principal_id_principals",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "state_hash", name="uq_provider_oauth_states_provider_state_hash"),
    )
    op.create_index("ix_provider_oauth_states_business_id", "provider_oauth_states", ["business_id"], unique=False)
    op.create_index("ix_provider_oauth_states_principal_id", "provider_oauth_states", ["principal_id"], unique=False)
    op.create_index(
        "ix_provider_oauth_states_provider_business_principal",
        "provider_oauth_states",
        ["provider", "business_id", "principal_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_oauth_states_provider_expires",
        "provider_oauth_states",
        ["provider", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provider_oauth_states_provider_expires", table_name="provider_oauth_states")
    op.drop_index("ix_provider_oauth_states_provider_business_principal", table_name="provider_oauth_states")
    op.drop_index("ix_provider_oauth_states_principal_id", table_name="provider_oauth_states")
    op.drop_index("ix_provider_oauth_states_business_id", table_name="provider_oauth_states")
    op.drop_table("provider_oauth_states")

    op.drop_index("ix_provider_connections_business_principal", table_name="provider_connections")
    op.drop_index("ix_provider_connections_business_provider", table_name="provider_connections")
    op.drop_index("ix_provider_connections_principal_id", table_name="provider_connections")
    op.drop_index("ix_provider_connections_business_id", table_name="provider_connections")
    op.drop_table("provider_connections")

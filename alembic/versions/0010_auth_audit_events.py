"""add auth admin audit event history table

Revision ID: 0010_auth_audit_events
Revises: 0009_principal_audit_metadata
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_auth_audit_events"
down_revision = "0009_principal_audit_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=64), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_audit_events_business_id", "auth_audit_events", ["business_id"], unique=False)
    op.create_index("ix_auth_audit_events_target_type", "auth_audit_events", ["target_type"], unique=False)
    op.create_index("ix_auth_audit_events_event_type", "auth_audit_events", ["event_type"], unique=False)
    op.create_index("ix_auth_audit_events_target_id", "auth_audit_events", ["target_id"], unique=False)
    op.create_index("ix_auth_audit_events_created_at", "auth_audit_events", ["created_at"], unique=False)
    op.create_index(
        "ix_auth_audit_events_business_created_at",
        "auth_audit_events",
        ["business_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_audit_events_business_created_at", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_created_at", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_target_id", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_event_type", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_target_type", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_business_id", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")

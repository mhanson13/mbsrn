"""create phase1 lead intake tables

Revision ID: 0001_init
Revises:
Create Date: 2026-03-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    lead_source = postgresql.ENUM(
        "godaddy_email", "manual", "phone", "other", name="leadsource", create_type=False
    )
    lead_status = postgresql.ENUM(
        "new", "contacted", "estimate_scheduled", "won", "lost", name="leadstatus", create_type=False
    )
    actor_type = postgresql.ENUM(
        "system", "owner", "admin", "customer", name="actortype", create_type=False
    )

    lead_source.create(op.get_bind(), checkfirst=True)
    lead_status.create(op.get_bind(), checkfirst=True)
    actor_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "businesses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("primary_phone", sa.String(length=32), nullable=True),
        sa.Column("notification_phone", sa.String(length=32), nullable=True),
        sa.Column("notification_email", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="America/Denver"),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("business_id", sa.String(length=36), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("source", lead_source, nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("service_type", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", lead_status, nullable=False),
        sa.Column("customer_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_human_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_job_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("actual_job_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_leads_business_id", "leads", ["business_id"])
    op.create_index("ix_leads_submitted_at", "leads", ["submitted_at"])
    op.create_index("ix_leads_status", "leads", ["status"])

    op.create_table(
        "lead_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lead_id", sa.String(length=36), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])
    op.create_index("ix_lead_events_event_type", "lead_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_lead_events_event_type", table_name="lead_events")
    op.drop_index("ix_lead_events_lead_id", table_name="lead_events")
    op.drop_table("lead_events")

    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_submitted_at", table_name="leads")
    op.drop_index("ix_leads_business_id", table_name="leads")
    op.drop_table("leads")

    op.drop_table("businesses")

    sa.Enum(name="actortype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="leadstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="leadsource").drop(op.get_bind(), checkfirst=True)

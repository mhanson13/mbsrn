from __future__ import annotations

from enum import Enum as PyEnum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, ForeignKeyConstraint, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class LeadEventType(str, PyEnum):
    EMAIL_RECEIVED = "email_received"
    LEAD_PARSED = "lead_parsed"
    PARSING_FAILED = "parsing_failed"
    DUPLICATE_DETECTED = "duplicate_detected"
    LEAD_CREATED = "lead_created"
    CUSTOMER_ACK_TRIGGERED = "customer_ack_triggered"
    CONTRACTOR_NOTIFICATION_TRIGGERED = "contractor_notification_triggered"
    NOTIFICATION_DISPATCH_REQUESTED = "notification_dispatch_requested"
    NOTIFICATION_DISPATCH_SENT = "notification_dispatch_sent"
    NOTIFICATION_DISPATCH_FAILED = "notification_dispatch_failed"
    NOTIFICATION_FALLBACK_ATTEMPTED = "notification_fallback_attempted"
    NOTIFICATION_FALLBACK_SENT = "notification_fallback_sent"
    NOTIFICATION_DISPATCH_SKIPPED = "notification_dispatch_skipped"
    STATUS_CHANGED = "status_changed"
    REMINDER_15M_TRIGGERED = "reminder_15m_triggered"
    REMINDER_2H_TRIGGERED = "reminder_2h_triggered"
    NOTE = "note"


class ActorType(str, PyEnum):
    SYSTEM = "system"
    OWNER = "owner"
    ADMIN = "admin"
    CUSTOMER = "customer"


class LeadEvent(Base):
    __tablename__ = "lead_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "business_id"],
            ["leads.id", "leads.business_id"],
            name="fk_lead_events_lead_id_business_id_leads",
        ),
        Index("ix_lead_events_business_id_lead_id", "business_id", "lead_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(String(36), ForeignKey("leads.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(SAEnum(ActorType), default=ActorType.SYSTEM, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    business = relationship("Business", back_populates="events")
    lead = relationship("Lead", back_populates="events", foreign_keys=[lead_id])

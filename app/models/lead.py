from __future__ import annotations

from enum import Enum as PyEnum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class LeadStatus(str, PyEnum):
    NEW = "new"
    CONTACTED = "contacted"
    ESTIMATE_SCHEDULED = "estimate_scheduled"
    WON = "won"
    LOST = "lost"


class LeadSource(str, PyEnum):
    GODADDY_EMAIL = "godaddy_email"
    MANUAL = "manual"
    PHONE = "phone"
    OTHER = "other"


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("id", "business_id", name="uq_leads_id_business_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    source: Mapped[LeadSource] = mapped_column(SAEnum(LeadSource), default=LeadSource.MANUAL, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    service_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[LeadStatus] = mapped_column(SAEnum(LeadStatus), default=LeadStatus.NEW, nullable=False, index=True)
    customer_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_human_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_job_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_job_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="leads")
    events = relationship(
        "LeadEvent",
        back_populates="lead",
        cascade="all, delete-orphan",
        foreign_keys="LeadEvent.lead_id",
    )

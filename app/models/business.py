from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notification_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notification_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Denver", nullable=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    customer_auto_ack_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    contractor_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    seo_audit_crawl_max_pages: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    competitor_candidate_min_relevance_score: Mapped[int] = mapped_column(Integer, default=35, nullable=False)
    competitor_candidate_big_box_penalty: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    competitor_candidate_directory_penalty: Mapped[int] = mapped_column(Integer, default=35, nullable=False)
    competitor_candidate_local_alignment_bonus: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    competitor_primary_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competitor_degraded_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Business-scoped prompt override values. Runtime prompt resolution remains:
    # business override -> deployment env fallback -> default.
    ai_prompt_text_competitor: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_prompt_text_recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    events = relationship("LeadEvent", back_populates="business")
    leads = relationship("Lead", back_populates="business")
    principals = relationship("Principal", back_populates="business")

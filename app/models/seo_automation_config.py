from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOAutomationConfig(Base):
    __tablename__ = "seo_automation_configs"
    __table_args__ = (
        UniqueConstraint("business_id", "site_id", name="uq_seo_automation_configs_business_site"),
        CheckConstraint(
            "cadence_type IN ('manual', 'interval_minutes')",
            name="ck_seo_automation_configs_cadence_type",
        ),
        CheckConstraint(
            "(cadence_type = 'manual' AND cadence_minutes IS NULL) OR "
            "(cadence_type = 'interval_minutes' AND cadence_minutes IS NOT NULL AND cadence_minutes >= 5)",
            name="ck_seo_automation_configs_cadence_minutes",
        ),
        CheckConstraint(
            "last_status IS NULL OR last_status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="ck_seo_automation_configs_last_status",
        ),
        Index(
            "ix_seo_automation_configs_business_enabled_next_run",
            "business_id",
            "is_enabled",
            "next_run_at",
        ),
        Index(
            "ix_seo_automation_configs_business_site_enabled",
            "business_id",
            "site_id",
            "is_enabled",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id"),
        nullable=False,
        index=True,
    )
    site_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_sites.id"),
        nullable=False,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cadence_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    cadence_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trigger_audit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_audit_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_competitor_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trigger_comparison: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trigger_competitor_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trigger_recommendations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_recommendation_narrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    site = relationship("SEOSite")

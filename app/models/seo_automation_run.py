from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOAutomationRun(Base):
    __tablename__ = "seo_automation_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_source IN ('manual', 'scheduled')",
            name="ck_seo_automation_runs_trigger_source",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="ck_seo_automation_runs_status",
        ),
        Index(
            "ix_seo_automation_runs_business_site_created_at",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_seo_automation_runs_business_site_status",
            "business_id",
            "site_id",
            "status",
        ),
        Index(
            "ix_seo_automation_runs_business_config_created_at",
            "business_id",
            "automation_config_id",
            "created_at",
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
    automation_config_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_automation_configs.id"),
        nullable=False,
        index=True,
    )
    trigger_source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    config = relationship("SEOAutomationConfig")
    site = relationship("SEOSite")

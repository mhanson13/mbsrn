from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorProfileCleanupExecution(Base):
    __tablename__ = "seo_competitor_profile_cleanup_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_scpg_cleanup_status",
        ),
        Index(
            "ix_scpg_cleanup_biz_site_started",
            "business_id",
            "site_id",
            "started_at",
        ),
        Index(
            "ix_scpg_cleanup_biz_status_started",
            "business_id",
            "status",
            "started_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id"),
        nullable=False,
        index=True,
    )
    site_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_sites.id"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    stale_runs_reconciled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_output_pruned_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_drafts_pruned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_pruned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

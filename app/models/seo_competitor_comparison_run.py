from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorComparisonRun(Base):
    __tablename__ = "seo_competitor_comparison_runs"
    __table_args__ = (
        Index(
            "ix_seo_competitor_comparison_runs_business_set_created_at",
            "business_id",
            "competitor_set_id",
            "created_at",
        ),
        Index("ix_seo_competitor_comparison_runs_business_status", "business_id", "status"),
        Index("ix_seo_competitor_comparison_runs_business_snapshot_run", "business_id", "snapshot_run_id"),
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
    competitor_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_sets.id"),
        nullable=False,
        index=True,
    )
    snapshot_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_snapshot_runs.id"),
        nullable=False,
        index=True,
    )
    baseline_audit_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_audit_runs.id"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    total_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_pages_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competitor_pages_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metric_rollups_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    finding_type_counts_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    category_counts_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    severity_counts_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    competitor_set = relationship("SEOCompetitorSet")
    snapshot_run = relationship("SEOCompetitorSnapshotRun")
    site = relationship("SEOSite")

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorComparisonSummary(Base):
    __tablename__ = "seo_competitor_comparison_summaries"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "comparison_run_id",
            "version",
            name="uq_seo_competitor_comparison_summaries_business_run_version",
        ),
        Index(
            "ix_seo_competitor_comparison_summaries_business_run_created_at",
            "business_id",
            "comparison_run_id",
            "created_at",
        ),
        Index(
            "ix_seo_competitor_comparison_summaries_business_status",
            "business_id",
            "status",
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
    competitor_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_sets.id"),
        nullable=False,
        index=True,
    )
    comparison_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_comparison_runs.id"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    overall_gap_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_gaps_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    plain_english_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    comparison_run = relationship("SEOCompetitorComparisonRun")

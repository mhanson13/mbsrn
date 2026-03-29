from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorProfileGenerationRun(Base):
    __tablename__ = "seo_competitor_profile_generation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_seo_competitor_profile_generation_runs_status",
        ),
        Index(
            "ix_scpg_runs_biz_site_created",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_scpg_runs_biz_status",
            "business_id",
            "status",
        ),
        Index(
            "ix_scpg_runs_parent",
            "parent_run_id",
        ),
        Index(
            "ix_scpg_runs_biz_site_failcat",
            "business_id",
            "site_id",
            "failure_category",
        ),
        CheckConstraint(
            (
                "failure_category IS NULL OR failure_category IN "
                "('timeout', 'provider_auth', 'provider_config', 'malformed_output', "
                "'schema_validation', 'internal_error', 'provider_request', 'unknown')"
            ),
            name="ck_scpg_runs_failure_cat",
        ),
        CheckConstraint(
            ("raw_candidate_count >= 0 AND included_candidate_count >= 0 " "AND excluded_candidate_count >= 0"),
            name="ck_scpg_runs_candidate_counts_nonneg",
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
    parent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_profile_generation_runs.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    requested_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    generated_draft_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    included_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusion_counts_by_reason: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    drafts = relationship("SEOCompetitorProfileDraft", back_populates="generation_run")

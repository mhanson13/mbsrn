from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorProfileDraft(Base):
    __tablename__ = "seo_competitor_profile_drafts"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "generation_run_id",
            "suggested_domain",
            name="uq_seo_competitor_profile_drafts_business_run_domain",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'edited', 'accepted', 'rejected')",
            name="ck_seo_competitor_profile_drafts_review_status",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_seo_competitor_profile_drafts_confidence_score",
        ),
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 100",
            name="ck_scpg_drafts_relevance",
        ),
        Index(
            "ix_scpg_drafts_biz_run_created",
            "business_id",
            "generation_run_id",
            "created_at",
        ),
        Index(
            "ix_scpg_drafts_biz_site_created",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_scpg_drafts_biz_review_status",
            "business_id",
            "review_status",
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
    generation_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_profile_generation_runs.id"),
        nullable=False,
        index=True,
    )
    suggested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_type: Mapped[str] = mapped_column(String(64), nullable=False, default="direct")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_competitor: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_generated")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    edited_fields_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_competitor_set_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_sets.id"),
        nullable=True,
    )
    accepted_competitor_domain_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_competitor_domains.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    generation_run = relationship("SEOCompetitorProfileGenerationRun", back_populates="drafts")

    @property
    def forced_inclusion(self) -> bool:
        return self.source == "ai_forced_fallback"

    @property
    def forced_reason(self) -> str | None:
        if self.forced_inclusion:
            return "no_valid_drafts_after_filtering"
        return None

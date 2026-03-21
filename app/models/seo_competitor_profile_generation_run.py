from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorProfileGenerationRun(Base):
    __tablename__ = "seo_competitor_profile_generation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_seo_competitor_profile_generation_runs_status",
        ),
        Index(
            "ix_seo_competitor_profile_generation_runs_business_site_created_at",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_seo_competitor_profile_generation_runs_business_status",
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
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    requested_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    generated_draft_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
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

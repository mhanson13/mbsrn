from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEORecommendationNarrative(Base):
    __tablename__ = "seo_recommendation_narratives"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "recommendation_run_id",
            "version",
            name="uq_seo_recommendation_narratives_business_run_version",
        ),
        CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_seo_recommendation_narratives_status",
        ),
        Index(
            "ix_seo_recommendation_narratives_business_run_created_at",
            "business_id",
            "recommendation_run_id",
            "created_at",
        ),
        Index(
            "ix_seo_recommendation_narratives_business_site_created_at",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_seo_recommendation_narratives_business_status",
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
    recommendation_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_recommendation_runs.id"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    narrative_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_themes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sections_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    recommendation_run = relationship("SEORecommendationRun")

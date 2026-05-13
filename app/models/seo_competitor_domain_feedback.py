from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorDomainFeedback(Base):
    __tablename__ = "seo_competitor_domain_feedback"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "site_id",
            "domain",
            name="uq_seo_competitor_domain_feedback_business_site_domain",
        ),
        Index(
            "ix_seo_competitor_domain_feedback_business_site_status",
            "business_id",
            "site_id",
            "feedback_status",
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
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    feedback_status: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by_principal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

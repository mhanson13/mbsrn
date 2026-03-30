from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOCompetitorDomain(Base):
    __tablename__ = "seo_competitor_domains"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "competitor_set_id",
            "domain",
            name="uq_seo_competitor_domains_business_set_domain",
        ),
        Index(
            "ix_seo_competitor_domains_business_set_active",
            "business_id",
            "competitor_set_id",
            "is_active",
        ),
        Index("ix_seo_competitor_domains_business_site", "business_id", "site_id"),
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
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="verified")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    competitor_set = relationship("SEOCompetitorSet")
    site = relationship("SEOSite")

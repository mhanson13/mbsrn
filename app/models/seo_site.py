from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOSite(Base):
    __tablename__ = "seo_sites"
    __table_args__ = (
        UniqueConstraint("business_id", "normalized_domain", name="uq_seo_sites_business_normalized_domain"),
        Index(
            "uq_seo_sites_one_primary_per_business",
            "business_id",
            unique=True,
            sqlite_where=text("is_primary = 1"),
            postgresql_where=text("is_primary = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    primary_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_areas_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    search_console_property_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    search_console_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ga4_onboarding_status: Mapped[str] = mapped_column(
        String(32),
        default="not_connected",
        nullable=False,
    )
    ga4_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ga4_property_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ga4_data_stream_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ga4_measurement_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_audit_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_audit_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_audit_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    business = relationship("Business")

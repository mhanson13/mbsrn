from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class TLSCertificateAsset(Base):
    __tablename__ = "tls_certificate_assets"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "fingerprint_sha256",
            name="uq_tls_certificate_assets_business_fingerprint",
        ),
        Index(
            "ix_tls_certificate_assets_business_hostname_status",
            "business_id",
            "hostname",
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
    hostname: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    custody: Mapped[str] = mapped_column(String(32), nullable=False)
    certificate_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    key_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    san_dns_names_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    not_valid_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    not_valid_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vault_secret_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vault_secret_version: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gcp_project_id: Mapped[str] = mapped_column(String(63), nullable=False)
    gcp_resource_name: Mapped[str | None] = mapped_column(String(63), nullable=True, index=True)
    gcp_resource_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    business = relationship("Business")


class SiteTLSCertificateBinding(Base):
    __tablename__ = "site_tls_certificate_bindings"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "site_id",
            "certificate_asset_id",
            name="uq_site_tls_certificate_bindings_site_asset",
        ),
        Index(
            "uq_site_tls_certificate_bindings_one_active_per_site",
            "business_id",
            "site_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
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
    certificate_asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tls_certificate_assets.id"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manifest_state: Mapped[str] = mapped_column(String(32), nullable=False, default="republish_required")
    serving_state: Mapped[str] = mapped_column(String(32), nullable=False, default="not_verified")
    observed_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    business = relationship("Business")
    site = relationship("SEOSite")
    certificate_asset = relationship("TLSCertificateAsset")

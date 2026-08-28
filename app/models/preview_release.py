from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class PreviewRelease(Base):
    __tablename__ = "preview_releases"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "site_id",
            "artifact_version_id",
            name="uq_preview_releases_business_site_artifact",
        ),
        UniqueConstraint("site_id", "release_number", name="uq_preview_releases_site_number"),
        Index("ix_preview_releases_business_site_created", "business_id", "site_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String(36), ForeignKey("seo_sites.id"), nullable=False, index=True)
    artifact_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_migration_artifact_versions.id"),
        nullable=False,
        index=True,
    )
    release_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    preview_slug: Mapped[str] = mapped_column(String(63), nullable=False)
    preview_hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    media_manifest_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    repo_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    repo_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repo_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    git_commit_sha: Mapped[str | None] = mapped_column(String(80), nullable=True)
    certificate_asset_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tls_certificate_assets.id"),
        nullable=True,
    )
    certificate_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    certificate_resource_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    dns_hostname: Mapped[str | None] = mapped_column(String(253), nullable=True)
    deployment_run_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    artifact = relationship("SEOMigrationArtifactVersion")
    site = relationship("SEOSite")


class PreviewReleaseOperation(Base):
    __tablename__ = "preview_release_operations"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_preview_release_operations_release"),
        UniqueConstraint("business_id", "idempotency_key", name="uq_preview_release_operations_idempotency"),
        Index("ix_preview_release_operations_business_site", "business_id", "site_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(36), ForeignKey("preview_releases.id"), nullable=False, index=True)
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String(36), ForeignKey("seo_sites.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    active_gate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_reason_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class PreviewReleaseGate(Base):
    __tablename__ = "preview_release_gates"
    __table_args__ = (
        UniqueConstraint("release_id", "gate_name", name="uq_preview_release_gates_release_name"),
        Index("ix_preview_release_gates_release_ordinal", "release_id", "ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    release_id: Mapped[str] = mapped_column(String(36), ForeignKey("preview_releases.id"), nullable=False, index=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("preview_release_operations.id"),
        nullable=False,
        index=True,
    )
    gate_name: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    reason_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    details_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class SEOMigrationSourceCapture(Base):
    __tablename__ = "seo_migration_source_captures"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('analyze_rebuild', 'faithful_snapshot')",
            name="ck_seo_migration_source_captures_mode",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_seo_migration_source_captures_status",
        ),
        CheckConstraint(
            "page_count >= 0 AND asset_count >= 0 AND total_bytes >= 0 AND attempt_count >= 0",
            name="ck_seo_migration_source_captures_counts",
        ),
        UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_seo_migration_source_captures_idempotency",
        ),
        UniqueConstraint(
            "site_id",
            "source_version",
            name="uq_seo_migration_source_captures_site_version",
        ),
        Index(
            "ix_seo_migration_source_captures_business_site_created",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_seo_migration_source_captures_status_created",
            "status",
            "created_at",
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
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_migration_workspaces.id"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    requested_source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    authorization_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authorization_statement_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorization_acknowledged_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorization_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_page_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_asset_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_max_total_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    browser_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manifest_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    manifest_storage_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manifest_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    manifest_storage_generation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_features_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    warning_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    failure_reason_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

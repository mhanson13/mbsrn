from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOMigrationWorkspace(Base):
    __tablename__ = "seo_migration_workspaces"
    __table_args__ = (
        UniqueConstraint("business_id", "site_id", name="uq_seo_migration_workspaces_business_site"),
        Index(
            "ix_seo_migration_workspaces_business_site_status",
            "business_id",
            "site_id",
            "migration_status",
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
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ingestion_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="analyze_rebuild")
    latest_source_capture_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_migration_source_captures.id"),
        nullable=True,
        index=True,
    )
    source_site_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_ingested")
    migration_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    operator_requirements_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    enriched_content_notes_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    brand_business_facts_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    imported_source_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    latest_generated_artifact_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_generated_artifact_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_approved_artifact_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_approved_artifact_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publish_config_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    deploy_config_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    analytics_config_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    publish_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_ready")
    deploy_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_ready")
    last_published_artifact_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_published_artifact_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_published_commit_sha: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_published_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_deployed_artifact_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_deployed_artifact_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_deployed_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_history_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    deploy_history_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    site = relationship("SEOSite")

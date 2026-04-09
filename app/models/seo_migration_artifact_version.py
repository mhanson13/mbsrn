from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class SEOMigrationArtifactVersion(Base):
    __tablename__ = "seo_migration_artifact_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version", name="uq_seo_migration_artifact_versions_workspace_version"),
        Index(
            "ix_seo_migration_artifact_versions_business_site_created_at",
            "business_id",
            "site_id",
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
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    context_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    strategy_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_map_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    homepage_structure_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    service_page_suggestions_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    cta_contact_structure_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    seo_meta_suggestions_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    redirect_suggestions_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    analytics_placeholders_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    generated_files_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    artifact_quality_evaluation_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, default="mock")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="mock-seo-migration-v1")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="seo-migration-v1")
    parse_warnings_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    approved_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    publish_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_published")
    deploy_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_deployed")
    last_published_commit_sha: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_publish_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_deploy_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    workspace = relationship("SEOMigrationWorkspace")
    site = relationship("SEOSite")

    @property
    def artifact_quality_evaluation(self) -> dict[str, object] | None:
        value = self.artifact_quality_evaluation_json
        if isinstance(value, dict):
            return value
        return None

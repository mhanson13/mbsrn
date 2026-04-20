from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class GitHubPublishConfig(Base):
    __tablename__ = "github_publish_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    default_branch: Mapped[str] = mapped_column(String(120), nullable=False, default="main")
    base_path: Mapped[str] = mapped_column(String(160), nullable=False, default="/")
    deploy_workflow_mode: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="site_repo_template_v1",
    )
    target_environment_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="gke_prod",
    )
    target_environment_source: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="admin_config",
    )
    managed_gke_cluster_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    managed_gke_cluster_location: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    managed_gke_project_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    namespace_isolation_defaults_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

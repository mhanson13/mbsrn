from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.seo_migration_artifact_version import SEOMigrationArtifactVersion
from app.models.seo_migration_workspace import SEOMigrationWorkspace


class SEOMigrationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_workspace(self, workspace: SEOMigrationWorkspace) -> SEOMigrationWorkspace:
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def save_workspace(self, workspace: SEOMigrationWorkspace) -> SEOMigrationWorkspace:
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def get_workspace_for_business_site(self, business_id: str, site_id: str) -> SEOMigrationWorkspace | None:
        stmt: Select[tuple[SEOMigrationWorkspace]] = (
            select(SEOMigrationWorkspace)
            .where(SEOMigrationWorkspace.business_id == business_id)
            .where(SEOMigrationWorkspace.site_id == site_id)
        )
        return self.session.scalar(stmt)

    def create_artifact_version(self, artifact_version: SEOMigrationArtifactVersion) -> SEOMigrationArtifactVersion:
        self.session.add(artifact_version)
        self.session.flush()
        return artifact_version

    def save_artifact_version(self, artifact_version: SEOMigrationArtifactVersion) -> SEOMigrationArtifactVersion:
        self.session.add(artifact_version)
        self.session.flush()
        return artifact_version

    def list_artifact_versions_for_business_site(
        self,
        business_id: str,
        site_id: str,
        *,
        limit: int = 20,
    ) -> list[SEOMigrationArtifactVersion]:
        bounded_limit = max(1, min(100, int(limit)))
        stmt: Select[tuple[SEOMigrationArtifactVersion]] = (
            select(SEOMigrationArtifactVersion)
            .where(SEOMigrationArtifactVersion.business_id == business_id)
            .where(SEOMigrationArtifactVersion.site_id == site_id)
            .order_by(SEOMigrationArtifactVersion.version.desc(), SEOMigrationArtifactVersion.created_at.desc())
            .limit(bounded_limit)
        )
        return list(self.session.scalars(stmt))

    def get_artifact_version_for_business_site(
        self,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
    ) -> SEOMigrationArtifactVersion | None:
        stmt: Select[tuple[SEOMigrationArtifactVersion]] = (
            select(SEOMigrationArtifactVersion)
            .where(SEOMigrationArtifactVersion.business_id == business_id)
            .where(SEOMigrationArtifactVersion.site_id == site_id)
            .where(SEOMigrationArtifactVersion.id == artifact_version_id)
        )
        return self.session.scalar(stmt)

    def next_artifact_version_number(self, workspace_id: str) -> int:
        stmt = select(func.max(SEOMigrationArtifactVersion.version)).where(
            SEOMigrationArtifactVersion.workspace_id == workspace_id
        )
        max_version = self.session.scalar(stmt)
        return int(max_version or 0) + 1

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.preview_release import PreviewRelease, PreviewReleaseGate, PreviewReleaseOperation


class PreviewReleaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_business_site(self, business_id: str, site_id: str, release_id: str) -> PreviewRelease | None:
        stmt: Select[tuple[PreviewRelease]] = (
            select(PreviewRelease)
            .where(PreviewRelease.business_id == business_id)
            .where(PreviewRelease.site_id == site_id)
            .where(PreviewRelease.id == release_id)
        )
        return self.session.scalar(stmt)

    def get_for_artifact(self, business_id: str, site_id: str, artifact_id: str) -> PreviewRelease | None:
        stmt: Select[tuple[PreviewRelease]] = (
            select(PreviewRelease)
            .where(PreviewRelease.business_id == business_id)
            .where(PreviewRelease.site_id == site_id)
            .where(PreviewRelease.artifact_version_id == artifact_id)
        )
        return self.session.scalar(stmt)

    def list_for_business_site(self, business_id: str, site_id: str, *, limit: int = 20) -> list[PreviewRelease]:
        stmt: Select[tuple[PreviewRelease]] = (
            select(PreviewRelease)
            .where(PreviewRelease.business_id == business_id)
            .where(PreviewRelease.site_id == site_id)
            .order_by(PreviewRelease.release_number.desc())
            .limit(max(1, min(100, int(limit))))
        )
        return list(self.session.scalars(stmt))

    def next_release_number(self, site_id: str) -> int:
        maximum = self.session.scalar(
            select(func.max(PreviewRelease.release_number)).where(PreviewRelease.site_id == site_id)
        )
        return int(maximum or 0) + 1

    def create_release(self, release: PreviewRelease) -> PreviewRelease:
        self.session.add(release)
        self.session.flush()
        return release

    def save_release(self, release: PreviewRelease) -> PreviewRelease:
        self.session.add(release)
        self.session.flush()
        return release

    def create_operation(self, operation: PreviewReleaseOperation) -> PreviewReleaseOperation:
        self.session.add(operation)
        self.session.flush()
        return operation

    def get_operation(self, release_id: str) -> PreviewReleaseOperation | None:
        return self.session.scalar(
            select(PreviewReleaseOperation).where(PreviewReleaseOperation.release_id == release_id)
        )

    def save_operation(self, operation: PreviewReleaseOperation) -> PreviewReleaseOperation:
        self.session.add(operation)
        self.session.flush()
        return operation

    def create_gate(self, gate: PreviewReleaseGate) -> PreviewReleaseGate:
        self.session.add(gate)
        self.session.flush()
        return gate

    def list_gates(self, release_id: str) -> list[PreviewReleaseGate]:
        stmt: Select[tuple[PreviewReleaseGate]] = (
            select(PreviewReleaseGate)
            .where(PreviewReleaseGate.release_id == release_id)
            .order_by(PreviewReleaseGate.ordinal.asc())
        )
        return list(self.session.scalars(stmt))

    def save_gate(self, gate: PreviewReleaseGate) -> PreviewReleaseGate:
        self.session.add(gate)
        self.session.flush()
        return gate

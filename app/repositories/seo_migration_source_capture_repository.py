from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.models.seo_migration_source_capture import SEOMigrationSourceCapture


class SEOMigrationSourceCaptureRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, capture: SEOMigrationSourceCapture) -> SEOMigrationSourceCapture:
        self.session.add(capture)
        self.session.flush()
        return capture

    def save(self, capture: SEOMigrationSourceCapture) -> SEOMigrationSourceCapture:
        self.session.add(capture)
        self.session.flush()
        return capture

    def get_for_business_site(
        self,
        *,
        business_id: str,
        site_id: str,
        capture_id: str,
    ) -> SEOMigrationSourceCapture | None:
        stmt: Select[tuple[SEOMigrationSourceCapture]] = (
            select(SEOMigrationSourceCapture)
            .where(SEOMigrationSourceCapture.business_id == business_id)
            .where(SEOMigrationSourceCapture.site_id == site_id)
            .where(SEOMigrationSourceCapture.id == capture_id)
        )
        return self.session.scalar(stmt)

    def get_by_id(self, *, capture_id: str) -> SEOMigrationSourceCapture | None:
        return self.session.get(SEOMigrationSourceCapture, capture_id)

    def get_by_idempotency_key(
        self,
        *,
        business_id: str,
        idempotency_key: str,
    ) -> SEOMigrationSourceCapture | None:
        stmt = (
            select(SEOMigrationSourceCapture)
            .where(SEOMigrationSourceCapture.business_id == business_id)
            .where(SEOMigrationSourceCapture.idempotency_key == idempotency_key)
        )
        return self.session.scalar(stmt)

    def list_for_business_site(
        self,
        *,
        business_id: str,
        site_id: str,
        limit: int = 20,
    ) -> list[SEOMigrationSourceCapture]:
        stmt = (
            select(SEOMigrationSourceCapture)
            .where(SEOMigrationSourceCapture.business_id == business_id)
            .where(SEOMigrationSourceCapture.site_id == site_id)
            .order_by(SEOMigrationSourceCapture.created_at.desc())
            .limit(max(1, min(100, int(limit))))
        )
        return list(self.session.scalars(stmt))

    def next_source_version(self, *, site_id: str) -> int:
        maximum = self.session.scalar(
            select(func.max(SEOMigrationSourceCapture.source_version)).where(
                SEOMigrationSourceCapture.site_id == site_id
            )
        )
        return int(maximum or 0) + 1

    def claim_for_execution(self, *, capture_id: str) -> bool:
        result = self.session.execute(
            update(SEOMigrationSourceCapture)
            .where(SEOMigrationSourceCapture.id == capture_id)
            .where(SEOMigrationSourceCapture.status == "queued")
            .values(status="running", attempt_count=SEOMigrationSourceCapture.attempt_count + 1)
        )
        return bool(result.rowcount == 1)

    def oldest_queued_id(self) -> str | None:
        return self.session.scalar(
            select(SEOMigrationSourceCapture.id)
            .where(SEOMigrationSourceCapture.status == "queued")
            .order_by(SEOMigrationSourceCapture.created_at.asc())
            .limit(1)
        )

    def list_stale_running(self, *, started_before: datetime, limit: int = 20) -> list[SEOMigrationSourceCapture]:
        stmt = (
            select(SEOMigrationSourceCapture)
            .where(SEOMigrationSourceCapture.status == "running")
            .where(SEOMigrationSourceCapture.started_at < started_before)
            .order_by(SEOMigrationSourceCapture.started_at.asc())
            .limit(max(1, min(100, int(limit))))
        )
        return list(self.session.scalars(stmt))

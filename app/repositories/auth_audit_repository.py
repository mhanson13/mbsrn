from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.auth_audit_event import AuthAuditEvent


class AuthAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, event: AuthAuditEvent) -> AuthAuditEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def list_for_business(
        self,
        business_id: str,
        *,
        target_type: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuthAuditEvent]:
        stmt: Select[tuple[AuthAuditEvent]] = select(AuthAuditEvent).where(AuthAuditEvent.business_id == business_id)
        if target_type:
            stmt = stmt.where(AuthAuditEvent.target_type == target_type)
        if event_type:
            stmt = stmt.where(AuthAuditEvent.event_type == event_type)

        stmt = stmt.order_by(AuthAuditEvent.created_at.desc(), AuthAuditEvent.id.desc()).limit(limit)
        return list(self.session.scalars(stmt))

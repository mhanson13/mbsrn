from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.auth_audit_event import AuthAuditEvent
from app.repositories.auth_audit_repository import AuthAuditRepository
from app.repositories.business_repository import BusinessRepository

_SENSITIVE_DETAIL_KEYS = {"token", "token_hash", "authorization", "bearer_token"}


class AuthAuditNotFoundError(ValueError):
    pass


class AuthAuditService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        auth_audit_repository: AuthAuditRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.auth_audit_repository = auth_audit_repository

    def record_event(
        self,
        *,
        business_id: str,
        actor_principal_id: str | None,
        target_type: str,
        target_id: str,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> AuthAuditEvent:
        self._ensure_business_exists(business_id)
        sanitized_details = self._sanitize_details(details or {})
        if not isinstance(sanitized_details, dict):
            sanitized_details = {}
        event = AuthAuditEvent(
            id=str(uuid4()),
            business_id=business_id,
            actor_principal_id=actor_principal_id,
            target_type=target_type,
            target_id=target_id,
            event_type=event_type,
            details_json=sanitized_details,
        )
        self.auth_audit_repository.create(event)
        return event

    def list_for_business(
        self,
        *,
        business_id: str,
        target_type: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuthAuditEvent]:
        self._ensure_business_exists(business_id)
        bounded_limit = max(1, min(limit, 200))
        return self.auth_audit_repository.list_for_business(
            business_id,
            target_type=target_type,
            event_type=event_type,
            limit=bounded_limit,
        )

    def _ensure_business_exists(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise AuthAuditNotFoundError("Business not found")

    def _sanitize_details(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                if key.lower() in _SENSITIVE_DETAIL_KEYS:
                    continue
                sanitized[key] = self._sanitize_details(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_details(item) for item in value]
        return value

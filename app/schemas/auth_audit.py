from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuthAuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    actor_principal_id: str | None
    target_type: str
    target_id: str
    event_type: str
    details_json: dict
    created_at: datetime


class AuthAuditEventListResponse(BaseModel):
    items: list[AuthAuditEventRead]
    total: int

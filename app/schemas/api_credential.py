from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APICredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    principal_id: str
    is_active: bool
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APICredentialCreateRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=64)

    @field_validator("principal_id", mode="before")
    @classmethod
    def normalize_principal_id(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("principal_id is required.")
        return normalized


class APICredentialIssueResponse(BaseModel):
    credential: APICredentialRead
    token: str


class APICredentialRotateResponse(BaseModel):
    replaced_credential_id: str
    credential: APICredentialRead
    token: str


class APICredentialListResponse(BaseModel):
    items: list[APICredentialRead]
    total: int

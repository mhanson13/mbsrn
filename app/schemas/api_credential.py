from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.principal import PrincipalRole


class APICredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    principal_id: str
    principal_display_name: str
    principal_role: PrincipalRole
    label: str | None
    rotated_from_credential_id: str | None
    is_active: bool
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APICredentialCreateRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=64)
    principal_display_name: str | None = Field(default=None, max_length=255)
    principal_role: PrincipalRole | None = None
    credential_label: str | None = Field(default=None, max_length=128)

    @field_validator("principal_id", mode="before")
    @classmethod
    def normalize_principal_id(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("principal_id is required.")
        return normalized

    @field_validator("principal_display_name", mode="before")
    @classmethod
    def normalize_principal_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized

    @field_validator("credential_label", mode="before")
    @classmethod
    def normalize_credential_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
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

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.principal import PrincipalRole


class PrincipalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: str
    id: str
    display_name: str
    created_by_principal_id: str | None
    updated_by_principal_id: str | None
    role: PrincipalRole
    is_active: bool
    last_authenticated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PrincipalListResponse(BaseModel):
    items: list[PrincipalRead]
    total: int


class PrincipalCreateRequest(BaseModel):
    principal_id: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    role: PrincipalRole = PrincipalRole.OPERATOR

    @field_validator("principal_id", mode="before")
    @classmethod
    def normalize_principal_id(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("principal_id is required.")
        return normalized

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized


class PrincipalUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: PrincipalRole | None = None
    is_active: bool | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized

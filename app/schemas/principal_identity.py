from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PrincipalIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    provider_subject: str
    business_id: str
    principal_id: str
    email: str | None
    email_verified: bool
    is_active: bool
    last_authenticated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PrincipalIdentityListResponse(BaseModel):
    items: list[PrincipalIdentityRead]
    total: int


class PrincipalIdentityCreateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    provider_subject: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=320)
    email_verified: bool = False
    is_active: bool = True

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if not normalized:
            raise ValueError("provider is required.")
        return normalized

    @field_validator("provider_subject", mode="before")
    @classmethod
    def normalize_provider_subject(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("provider_subject is required.")
        return normalized

    @field_validator("principal_id", mode="before")
    @classmethod
    def normalize_principal_id(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("principal_id is required.")
        return normalized

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if not normalized:
            return None
        return normalized

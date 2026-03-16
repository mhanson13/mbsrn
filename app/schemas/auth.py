from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.principal import PrincipalRole


class GoogleAuthExchangeRequest(BaseModel):
    id_token: str = Field(min_length=1)

    @field_validator("id_token", mode="before")
    @classmethod
    def normalize_id_token(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("id_token is required.")
        return normalized


class AuthPrincipalRead(BaseModel):
    business_id: str
    principal_id: str
    display_name: str
    role: PrincipalRole
    is_active: bool


class AuthExchangeResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: str
    refresh_expires_at: str
    auth_source: str
    principal: AuthPrincipalRead


class AuthRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)

    @field_validator("refresh_token", mode="before")
    @classmethod
    def normalize_refresh_token(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("refresh_token is required.")
        return normalized


class AuthRefreshResponse(AuthExchangeResponse):
    pass


class AuthLogoutRequest(BaseModel):
    refresh_token: str | None = None

    @field_validator("refresh_token", mode="before")
    @classmethod
    def normalize_refresh_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class AuthMeResponse(BaseModel):
    business_id: str
    principal_id: str
    display_name: str
    role: PrincipalRole
    auth_source: str

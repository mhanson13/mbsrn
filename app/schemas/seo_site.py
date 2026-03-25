from __future__ import annotations

from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ZIP_CODE_PATTERN = re.compile(r"\b(?P<zip>\d{5})\b")


def extract_primary_business_zip(value: str | None) -> str | None:
    if value is None:
        return None
    match = _ZIP_CODE_PATTERN.search(value)
    if match is None:
        return None
    return match.group("zip")


def normalize_primary_business_zip(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if _ZIP_CODE_PATTERN.fullmatch(cleaned) is None:
        raise ValueError("primary_business_zip must be a 5-digit ZIP code")
    return cleaned


class SEOSiteCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=2048)
    industry: str | None = Field(default=None, max_length=128)
    primary_location: str | None = Field(default=None, max_length=255)
    primary_business_zip: str | None = Field(default=None, max_length=5)
    service_areas: list[str] | None = None
    is_active: bool = True
    is_primary: bool = False

    @field_validator("primary_business_zip", mode="before")
    @classmethod
    def validate_primary_business_zip(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_primary_business_zip(str(value))


class SEOSiteUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    industry: str | None = Field(default=None, max_length=128)
    primary_location: str | None = Field(default=None, max_length=255)
    primary_business_zip: str | None = Field(default=None, max_length=5)
    service_areas: list[str] | None = None
    is_active: bool | None = None
    is_primary: bool | None = None

    @field_validator("primary_business_zip", mode="before")
    @classmethod
    def validate_primary_business_zip(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_primary_business_zip(str(value))


class SEOSiteAdminUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def require_name_or_url(self) -> "SEOSiteAdminUpdateRequest":
        if self.name is None and self.url is None:
            raise ValueError("At least one of name or url must be provided")
        return self


class SEOSiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    display_name: str
    base_url: str
    normalized_domain: str
    industry: str | None
    primary_location: str | None
    primary_business_zip: str | None = None
    service_areas_json: list[str] | None
    is_active: bool
    is_primary: bool
    last_audit_run_id: str | None
    last_audit_status: str | None
    last_audit_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def derive_primary_business_zip(self) -> "SEOSiteRead":
        if self.primary_business_zip is None:
            self.primary_business_zip = extract_primary_business_zip(self.primary_location)
        return self


class SEOSiteListResponse(BaseModel):
    items: list[SEOSiteRead]
    total: int

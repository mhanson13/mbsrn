from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.preview_identity import build_site_preview_identity, normalize_preview_slug

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
    search_console_property_url: str | None = Field(default=None, max_length=2048)
    search_console_enabled: bool | None = None
    ga4_account_id: str | None = Field(default=None, max_length=128)
    ga4_property_id: str | None = Field(default=None, max_length=128)
    ga4_data_stream_id: str | None = Field(default=None, max_length=128)
    ga4_measurement_id: str | None = Field(default=None, max_length=64)
    is_active: bool = True
    is_primary: bool = False
    preview_slug: str | None = Field(default=None, max_length=63)

    @field_validator("primary_business_zip", mode="before")
    @classmethod
    def validate_primary_business_zip(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_primary_business_zip(str(value))

    @field_validator("preview_slug", mode="before")
    @classmethod
    def validate_preview_slug(cls, value: object) -> str | None:
        return normalize_preview_slug(value)


class SEOSiteUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    industry: str | None = Field(default=None, max_length=128)
    primary_location: str | None = Field(default=None, max_length=255)
    primary_business_zip: str | None = Field(default=None, max_length=5)
    service_areas: list[str] | None = None
    search_console_property_url: str | None = Field(default=None, max_length=2048)
    search_console_enabled: bool | None = None
    ga4_account_id: str | None = Field(default=None, max_length=128)
    ga4_property_id: str | None = Field(default=None, max_length=128)
    ga4_data_stream_id: str | None = Field(default=None, max_length=128)
    ga4_measurement_id: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None
    is_primary: bool | None = None
    preview_slug: str | None = Field(default=None, max_length=63)

    @field_validator("primary_business_zip", mode="before")
    @classmethod
    def validate_primary_business_zip(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_primary_business_zip(str(value))

    @field_validator("preview_slug", mode="before")
    @classmethod
    def validate_preview_slug(cls, value: object) -> str | None:
        return normalize_preview_slug(value)


class SEOSiteAdminUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    search_console_property_url: str | None = Field(default=None, max_length=2048)
    search_console_enabled: bool | None = None
    ga4_account_id: str | None = Field(default=None, max_length=128)
    ga4_property_id: str | None = Field(default=None, max_length=128)
    ga4_data_stream_id: str | None = Field(default=None, max_length=128)
    ga4_measurement_id: str | None = Field(default=None, max_length=64)
    preview_slug: str | None = Field(default=None, max_length=63)

    @model_validator(mode="after")
    def require_name_or_url(self) -> "SEOSiteAdminUpdateRequest":
        if (
            self.name is None
            and self.url is None
            and self.search_console_property_url is None
            and self.search_console_enabled is None
            and self.ga4_account_id is None
            and self.ga4_property_id is None
            and self.ga4_data_stream_id is None
            and self.ga4_measurement_id is None
            and self.preview_slug is None
        ):
            raise ValueError(
                "At least one of name, url, search_console_property_url, search_console_enabled, "
                "ga4_account_id, ga4_property_id, ga4_data_stream_id, or ga4_measurement_id must be provided"
            )
        return self

    @field_validator("preview_slug", mode="before")
    @classmethod
    def validate_preview_slug(cls, value: object) -> str | None:
        return normalize_preview_slug(value)


class SEOSiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    display_name: str
    base_url: str
    normalized_domain: str
    preview_slug: str | None = None
    preview_hostname: str | None = None
    preview_slug_locked_at: datetime | None = None
    industry: str | None
    primary_location: str | None
    primary_business_zip: str | None = None
    service_areas_json: list[str] | None
    search_console_property_url: str | None = None
    search_console_enabled: bool = False
    ga4_onboarding_status: str = "not_connected"
    ga4_account_id: str | None = None
    ga4_property_id: str | None = None
    ga4_data_stream_id: str | None = None
    ga4_measurement_id: str | None = None
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
        if self.preview_slug is not None:
            self.preview_hostname = build_site_preview_identity(self.preview_slug).hostname
        return self


class SEOSiteListResponse(BaseModel):
    items: list[SEOSiteRead]
    total: int


class SEOSiteDeleteIssueRead(BaseModel):
    reason_code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)


class SEOSiteDeleteDependencySummaryRead(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=0)
    model_count: int = Field(ge=0)
    model_names: list[str] = Field(default_factory=list)


class SEOSiteDeleteResourceRead(BaseModel):
    resource_type: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=40)
    reason_code: str | None = Field(default=None, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    static_ip_ownership_status: str | None = Field(default=None, max_length=40)
    static_ip_ownership_method: str | None = Field(default=None, max_length=40)
    static_ip_delete_attempted: bool | None = None
    static_ip_delete_selected: bool | None = None
    static_ip_delete_reason_code: str | None = Field(default=None, max_length=120)
    static_ip_delete_safe_summary: str | None = Field(default=None, max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)


class SEOSiteDeleteExecutionDefaultsRead(BaseModel):
    delete_github_repo: bool = False
    delete_runtime_resources: bool = False
    delete_dns_resources: bool = False
    force_delete_active: bool = False


class SEOSiteDeletePlanRead(BaseModel):
    reason_code: str = Field(min_length=1, max_length=120)
    site_id: str = Field(min_length=1, max_length=36)
    site_name: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=255)
    is_active: bool
    generated_repo_owner: str | None = Field(default=None, max_length=120)
    generated_repo_name: str | None = Field(default=None, max_length=255)
    kubernetes_namespace: str | None = Field(default=None, max_length=63)
    preview_hostname: str | None = Field(default=None, max_length=253)
    static_ip_name: str | None = Field(default=None, max_length=80)
    managed_certificate_name: str | None = Field(default=None, max_length=63)
    dns_records_expected: list[dict[str, Any]] = Field(default_factory=list)
    db_dependency_total: int = Field(ge=0)
    db_dependencies: list[SEOSiteDeleteDependencySummaryRead] = Field(default_factory=list)
    external_resources: list[SEOSiteDeleteResourceRead] = Field(default_factory=list)
    blockers: list[SEOSiteDeleteIssueRead] = Field(default_factory=list)
    warnings: list[SEOSiteDeleteIssueRead] = Field(default_factory=list)
    required_confirmation_phrase: str = Field(min_length=1, max_length=500)
    execution_defaults: SEOSiteDeleteExecutionDefaultsRead = Field(default_factory=SEOSiteDeleteExecutionDefaultsRead)


class SEOSiteDeleteExecuteRequest(BaseModel):
    confirmation_phrase: str = Field(min_length=1, max_length=500)
    acknowledge_delete_database_records: bool = False
    delete_github_repo: bool = False
    acknowledge_delete_github_repo: bool = False
    delete_runtime_resources: bool = False
    acknowledge_delete_runtime_resources: bool = False
    delete_dns_resources: bool = False
    acknowledge_delete_dns_resources: bool = False
    force_delete_active: bool = False

    @field_validator("confirmation_phrase", mode="before")
    @classmethod
    def _normalize_confirmation_phrase(cls, value: object) -> str:
        return " ".join(str(value or "").split()).strip()


class SEOSiteDeleteExecutionResultRead(BaseModel):
    reason_code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    site_id: str = Field(min_length=1, max_length=36)
    site_name: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=255)
    db_deleted: bool
    site_deleted: bool
    external_cleanup_selected: bool
    external_cleanup_partial: bool
    db_dependency_total: int = Field(ge=0)
    db_dependencies: list[SEOSiteDeleteDependencySummaryRead] = Field(default_factory=list)
    external_resources: list[SEOSiteDeleteResourceRead] = Field(default_factory=list)
    blockers: list[SEOSiteDeleteIssueRead] = Field(default_factory=list)
    warnings: list[SEOSiteDeleteIssueRead] = Field(default_factory=list)

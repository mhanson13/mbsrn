from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEOCompetitorRunStatus = Literal["queued", "running", "completed", "failed"]
SEOCompetitorProfileGenerationRunStatus = Literal["running", "completed", "failed"]
SEOCompetitorProfileDraftReviewStatus = Literal["pending", "edited", "accepted", "rejected"]
SEOSummaryStatus = Literal["completed", "failed"]
SEOFindingCategory = Literal["SEO", "CONTENT", "STRUCTURE", "TECHNICAL"]
SEOFindingSeverity = Literal["INFO", "WARNING", "CRITICAL"]
SEOGapDirection = Literal["client_leads", "client_trails", "parity", "unknown"]
SEOCompetitorProfileType = Literal["direct", "indirect", "local", "marketplace", "informational", "unknown"]

_FINDING_CATEGORIES: set[str] = {"SEO", "CONTENT", "STRUCTURE", "TECHNICAL"}
_FINDING_SEVERITIES: set[str] = {"INFO", "WARNING", "CRITICAL"}
_GAP_DIRECTIONS: set[str] = {"client_leads", "client_trails", "parity", "unknown"}
_COMPETITOR_PROFILE_TYPES: set[str] = {"direct", "indirect", "local", "marketplace", "informational", "unknown"}


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_count_map(raw: Any) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("Expected object for count map")
    normalized: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            normalized[key] = int(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_finding_category(raw: Any) -> SEOFindingCategory:
    normalized = str(raw or "").strip().upper()
    if normalized not in _FINDING_CATEGORIES:
        return "TECHNICAL"
    return normalized  # type: ignore[return-value]


def _normalize_finding_severity(raw: Any) -> SEOFindingSeverity:
    normalized = str(raw or "").strip().upper()
    if normalized not in _FINDING_SEVERITIES:
        return "INFO"
    return normalized  # type: ignore[return-value]


def _normalize_gap_direction(raw: Any) -> SEOGapDirection:
    normalized = str(raw or "").strip().lower()
    if normalized not in _GAP_DIRECTIONS:
        return "unknown"
    return normalized  # type: ignore[return-value]


class SEOCompetitorSetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=64)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned

    @field_validator("city", "state", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))


class SEOCompetitorSetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be empty")
        return cleaned

    @field_validator("city", "state", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))


class SEOCompetitorSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    name: str
    city: str | None
    state: str | None
    is_active: bool
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime


class SEOCompetitorSetListResponse(BaseModel):
    items: list[SEOCompetitorSetRead]
    total: int


class SEOCompetitorDomainCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    display_name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True

    @field_validator("domain", "base_url", "display_name", "notes", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @model_validator(mode="after")
    def validate_domain_or_base_url(self) -> "SEOCompetitorDomainCreateRequest":
        if self.domain is None and self.base_url is None:
            raise ValueError("Either domain or base_url is required")
        return self


class SEOCompetitorDomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    domain: str
    base_url: str
    display_name: str | None
    source: str
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SEOCompetitorDomainListResponse(BaseModel):
    items: list[SEOCompetitorDomainRead]
    total: int


class SEOCompetitorProfileGenerationRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_count: int = Field(default=5, ge=1, le=20)


class SEOCompetitorProfileGenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    status: SEOCompetitorProfileGenerationRunStatus
    requested_candidate_count: int
    generated_draft_count: int
    provider_name: str
    model_name: str
    prompt_version: str
    error_summary: str | None
    completed_at: datetime | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime


class SEOCompetitorProfileDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    generation_run_id: str
    suggested_name: str
    suggested_domain: str
    competitor_type: SEOCompetitorProfileType
    summary: str | None
    why_competitor: str | None
    evidence: str | None
    confidence_score: float
    source: str
    review_status: SEOCompetitorProfileDraftReviewStatus
    edited_fields_json: dict[str, object] | None
    review_notes: str | None
    reviewed_by_principal_id: str | None
    reviewed_at: datetime | None
    accepted_competitor_set_id: str | None
    accepted_competitor_domain_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("competitor_type", mode="before")
    @classmethod
    def normalize_competitor_type(cls, value: Any) -> SEOCompetitorProfileType:
        normalized = str(value or "").strip().lower()
        if normalized not in _COMPETITOR_PROFILE_TYPES:
            return "unknown"
        return normalized  # type: ignore[return-value]


class SEOCompetitorProfileGenerationRunListResponse(BaseModel):
    items: list[SEOCompetitorProfileGenerationRunRead]
    total: int


class SEOCompetitorProfileGenerationRunDetailRead(BaseModel):
    run: SEOCompetitorProfileGenerationRunRead
    drafts: list[SEOCompetitorProfileDraftRead]
    total_drafts: int


class SEOCompetitorProfileDraftEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_name: str | None = Field(default=None, min_length=1, max_length=255)
    suggested_domain: str | None = Field(default=None, min_length=1, max_length=255)
    competitor_type: SEOCompetitorProfileType | None = None
    summary: str | None = Field(default=None, max_length=4000)
    why_competitor: str | None = Field(default=None, max_length=4000)
    evidence: str | None = Field(default=None, max_length=4000)
    confidence_score: float | None = Field(default=None, ge=0, le=1)

    @field_validator("suggested_name", "suggested_domain", "summary", "why_competitor", "evidence", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("competitor_type", mode="before")
    @classmethod
    def normalize_optional_competitor_type(cls, value: Any) -> SEOCompetitorProfileType | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in _COMPETITOR_PROFILE_TYPES:
            raise ValueError("Invalid competitor_type")
        return normalized  # type: ignore[return-value]

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "SEOCompetitorProfileDraftEditRequest":
        if not self.model_fields_set:
            raise ValueError("At least one draft field is required")
        return self


class SEOCompetitorProfileDraftRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))


class SEOCompetitorProfileDraftAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_set_id: str | None = Field(default=None, min_length=1, max_length=36)
    suggested_name: str | None = Field(default=None, min_length=1, max_length=255)
    suggested_domain: str | None = Field(default=None, min_length=1, max_length=255)
    competitor_type: SEOCompetitorProfileType | None = None
    summary: str | None = Field(default=None, max_length=4000)
    why_competitor: str | None = Field(default=None, max_length=4000)
    evidence: str | None = Field(default=None, max_length=4000)
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    review_notes: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "competitor_set_id",
        "suggested_name",
        "suggested_domain",
        "summary",
        "why_competitor",
        "evidence",
        "review_notes",
        mode="before",
    )
    @classmethod
    def normalize_optional_accept_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("competitor_type", mode="before")
    @classmethod
    def normalize_accept_competitor_type(cls, value: Any) -> SEOCompetitorProfileType | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in _COMPETITOR_PROFILE_TYPES:
            raise ValueError("Invalid competitor_type")
        return normalized  # type: ignore[return-value]


class SEOCompetitorSnapshotRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_audit_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    max_domains: int = Field(default=10, ge=1, le=50)
    max_pages_per_domain: int = Field(default=5, ge=1, le=50)
    max_depth: int = Field(default=1, ge=0, le=5)
    same_domain_only: bool = True

    @field_validator("client_audit_run_id", mode="before")
    @classmethod
    def normalize_client_audit_run_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))


class SEOCompetitorSnapshotRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    client_audit_run_id: str | None
    status: SEOCompetitorRunStatus
    max_domains: int
    max_pages_per_domain: int
    max_depth: int
    same_domain_only: bool
    domains_targeted: int
    domains_completed: int
    pages_attempted: int
    pages_captured: int
    pages_skipped: int
    errors_encountered: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_summary: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime


class SEOCompetitorSnapshotRunListResponse(BaseModel):
    items: list[SEOCompetitorSnapshotRunRead]
    total: int


class SEOCompetitorSnapshotPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    snapshot_run_id: str
    competitor_domain_id: str
    url: str
    status_code: int | None
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    h1_json: list[str] | None
    h2_json: list[str] | None
    word_count: int | None
    internal_link_count: int | None
    fetched_at: datetime
    error_summary: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("h1_json", "h2_json", mode="before")
    @classmethod
    def normalize_heading_lists(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item) for item in value]
        raise TypeError("Expected list for heading fields")


class SEOCompetitorSnapshotPageListResponse(BaseModel):
    items: list[SEOCompetitorSnapshotPageRead]
    total: int


class SEOCompetitorComparisonRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_run_id: str = Field(min_length=1, max_length=36)
    baseline_audit_run_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("snapshot_run_id")
    @classmethod
    def normalize_snapshot_run_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("snapshot_run_id is required")
        return cleaned

    @field_validator("baseline_audit_run_id", mode="before")
    @classmethod
    def normalize_baseline_run_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))


class SEOCompetitorComparisonRunSiteCreateRequest(BaseModel):
    competitor_set_id: str
    snapshot_run_id: str
    baseline_audit_run_id: str | None = None


class SEOCompetitorComparisonRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    snapshot_run_id: str
    baseline_audit_run_id: str | None
    status: SEOCompetitorRunStatus
    total_findings: int
    critical_findings: int
    warning_findings: int
    info_findings: int
    client_pages_analyzed: int
    competitor_pages_analyzed: int
    finding_type_counts_json: dict[str, int] = Field(default_factory=dict)
    category_counts_json: dict[str, int] = Field(default_factory=dict)
    severity_counts_json: dict[str, int] = Field(default_factory=dict)
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_summary: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "finding_type_counts_json",
        "category_counts_json",
        "severity_counts_json",
        mode="before",
    )
    @classmethod
    def normalize_count_maps(cls, value: Any) -> dict[str, int]:
        return _normalize_count_map(value)


class SEOCompetitorComparisonRunListResponse(BaseModel):
    items: list[SEOCompetitorComparisonRunRead]
    total: int


class SEOCompetitorComparisonFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    comparison_run_id: str
    finding_type: str
    category: SEOFindingCategory
    severity: SEOFindingSeverity
    title: str
    details: str | None
    rule_key: str
    client_value: str | None
    competitor_value: str | None
    gap_direction: SEOGapDirection | None
    evidence_json: dict[str, object] | None
    created_at: datetime

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> SEOFindingCategory:
        return _normalize_finding_category(value)

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> SEOFindingSeverity:
        return _normalize_finding_severity(value)

    @field_validator("gap_direction", mode="before")
    @classmethod
    def normalize_gap_direction(cls, value: Any) -> SEOGapDirection | None:
        if value is None:
            return None
        return _normalize_gap_direction(value)


class SEOCompetitorComparisonFindingListResponse(BaseModel):
    items: list[SEOCompetitorComparisonFindingRead]
    total: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class SEOCompetitorComparisonMetricRollupRead(BaseModel):
    key: str
    title: str
    category: SEOFindingCategory
    unit: str
    higher_is_better: bool
    client_value: int
    competitor_value: int
    delta: int
    severity: SEOFindingSeverity
    gap_direction: SEOGapDirection

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> SEOFindingCategory:
        return _normalize_finding_category(value)

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> SEOFindingSeverity:
        return _normalize_finding_severity(value)

    @field_validator("gap_direction", mode="before")
    @classmethod
    def normalize_gap_direction(cls, value: Any) -> SEOGapDirection:
        return _normalize_gap_direction(value)


class SEOCompetitorComparisonRunRollupsRead(BaseModel):
    client_pages_analyzed: int
    competitor_pages_analyzed: int
    findings_by_type: dict[str, int] = Field(default_factory=dict)
    findings_by_category: dict[str, int] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    metric_rollups: list[SEOCompetitorComparisonMetricRollupRead] = Field(default_factory=list)


class SEOCompetitorComparisonReportRead(BaseModel):
    run: SEOCompetitorComparisonRunRead
    rollups: SEOCompetitorComparisonRunRollupsRead
    findings: SEOCompetitorComparisonFindingListResponse


class SEOCompetitorComparisonSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    comparison_run_id: str
    version: int
    status: SEOSummaryStatus
    overall_gap_summary: str | None
    top_gaps_json: list[str] = Field(default_factory=list)
    plain_english_explanation: str | None
    provider_name: str
    model_name: str
    prompt_version: str
    error_summary: str | None
    error_message: str | None = None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("top_gaps_json", mode="before")
    @classmethod
    def normalize_top_gaps(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        raise TypeError("top_gaps_json must be a list")

    @model_validator(mode="after")
    def sync_error_fields(self) -> "SEOCompetitorComparisonSummaryRead":
        if self.error_message is None:
            self.error_message = self.error_summary
        if self.error_summary is None:
            self.error_summary = self.error_message
        return self


class SEOCompetitorComparisonSummaryListResponse(BaseModel):
    items: list[SEOCompetitorComparisonSummaryRead]
    total: int

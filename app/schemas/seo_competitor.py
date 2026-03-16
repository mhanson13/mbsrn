from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SEOCompetitorSetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=64)
    is_active: bool = True


class SEOCompetitorSetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


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
    domain: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    display_name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True

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


class SEOCompetitorSnapshotRunCreateRequest(BaseModel):
    client_audit_run_id: str | None = None
    max_domains: int = Field(default=10, ge=1, le=50)
    max_pages_per_domain: int = Field(default=5, ge=1, le=50)
    max_depth: int = Field(default=1, ge=0, le=5)
    same_domain_only: bool = True


class SEOCompetitorSnapshotRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    competitor_set_id: str
    client_audit_run_id: str | None
    status: str
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


class SEOCompetitorComparisonRunCreateRequest(BaseModel):
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
    status: str
    total_findings: int
    critical_findings: int
    warning_findings: int
    info_findings: int
    client_pages_analyzed: int
    competitor_pages_analyzed: int
    finding_type_counts_json: dict[str, int] | None = None
    category_counts_json: dict[str, int] | None = None
    severity_counts_json: dict[str, int] | None = None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_summary: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime


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
    category: str
    severity: str
    title: str
    details: str | None
    rule_key: str
    client_value: str | None
    competitor_value: str | None
    gap_direction: str | None
    evidence_json: dict[str, object] | None
    created_at: datetime


class SEOCompetitorComparisonFindingListResponse(BaseModel):
    items: list[SEOCompetitorComparisonFindingRead]
    total: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class SEOCompetitorComparisonMetricRollupRead(BaseModel):
    key: str
    title: str
    category: str
    unit: str
    higher_is_better: bool
    client_value: int
    competitor_value: int
    delta: int
    severity: str
    gap_direction: str


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

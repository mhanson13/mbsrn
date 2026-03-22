from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEORecommendationRunStatus = Literal["queued", "running", "completed", "failed"]
SEORecommendationCategory = Literal["SEO", "CONTENT", "STRUCTURE", "TECHNICAL"]
SEORecommendationSeverity = Literal["INFO", "WARNING", "CRITICAL"]
SEORecommendationEffort = Literal["LOW", "MEDIUM", "HIGH"]
SEORecommendationNarrativeStatus = Literal["completed", "failed"]
SEORecommendationWorkspaceSummaryState = Literal[
    "no_runs",
    "no_completed_runs",
    "completed_no_narrative",
    "completed_with_narrative",
]
SEORecommendationPriorityBand = Literal["low", "medium", "high", "critical"]
SEORecommendationStatus = Literal["open", "in_progress", "accepted", "dismissed", "snoozed", "resolved"]
SEORecommendationDecision = Literal["accept", "dismiss", "snooze", "resolve", "reopen", "start"]
SEORecommendationSourceType = Literal["audit", "comparison", "mixed"]
SEORecommendationSortBy = Literal["priority_score", "priority_band", "severity", "created_at", "updated_at", "due_at"]
SortOrder = Literal["asc", "desc"]
SEORecommendationTuningSuggestionConfidence = Literal["low", "medium", "high"]
RecommendationTuningSetting = Literal[
    "competitor_candidate_min_relevance_score",
    "competitor_candidate_big_box_penalty",
    "competitor_candidate_directory_penalty",
    "competitor_candidate_local_alignment_bonus",
]

_CATEGORIES = {"SEO", "CONTENT", "STRUCTURE", "TECHNICAL"}
_SEVERITIES = {"INFO", "WARNING", "CRITICAL"}
_EFFORT_BUCKETS = {"LOW", "MEDIUM", "HIGH"}
_PRIORITY_BANDS = {"low", "medium", "high", "critical"}
_STATUSES = {"open", "in_progress", "accepted", "dismissed", "snoozed", "resolved"}
_DECISIONS = {"accept", "dismiss", "snooze", "resolve", "reopen", "start"}
_SOURCE_TYPES = {"audit", "comparison", "mixed"}
_SORT_FIELDS = {"priority_score", "priority_band", "severity", "created_at", "updated_at", "due_at"}
_SORT_ORDERS = {"asc", "desc"}


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_int_map(raw: Any) -> dict[str, int]:
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


def _normalize_category(value: Any) -> SEORecommendationCategory:
    normalized = str(value or "").strip().upper()
    if normalized not in _CATEGORIES:
        return "TECHNICAL"
    return normalized  # type: ignore[return-value]


def _normalize_severity(value: Any) -> SEORecommendationSeverity:
    normalized = str(value or "").strip().upper()
    if normalized not in _SEVERITIES:
        return "INFO"
    return normalized  # type: ignore[return-value]


def _normalize_effort(value: Any) -> SEORecommendationEffort:
    normalized = str(value or "").strip().upper()
    if normalized not in _EFFORT_BUCKETS:
        return "MEDIUM"
    return normalized  # type: ignore[return-value]


def _normalize_priority_band(value: Any) -> SEORecommendationPriorityBand:
    normalized = str(value or "").strip().lower()
    if normalized not in _PRIORITY_BANDS:
        return "medium"
    return normalized  # type: ignore[return-value]


def _normalize_status(value: Any) -> SEORecommendationStatus:
    normalized = str(value or "").strip().lower()
    if normalized not in _STATUSES:
        return "open"
    return normalized  # type: ignore[return-value]


def _normalize_decision(value: Any) -> SEORecommendationDecision | None:
    normalized = _strip_or_none(str(value)) if value is not None else None
    if normalized is None:
        return None
    normalized = normalized.lower()
    if normalized not in _DECISIONS:
        raise ValueError("Invalid recommendation decision")
    return normalized  # type: ignore[return-value]


def _normalize_source_type(value: Any) -> SEORecommendationSourceType:
    normalized = str(value or "").strip().lower()
    if normalized not in _SOURCE_TYPES:
        raise ValueError("Invalid source_type")
    return normalized  # type: ignore[return-value]


def _normalize_sort_by(value: Any) -> SEORecommendationSortBy:
    normalized = str(value or "").strip().lower()
    if normalized not in _SORT_FIELDS:
        raise ValueError("Invalid sort_by")
    return normalized  # type: ignore[return-value]


def _normalize_sort_order(value: Any) -> SortOrder:
    normalized = str(value or "").strip().lower()
    if normalized not in _SORT_ORDERS:
        raise ValueError("Invalid sort_order")
    return normalized  # type: ignore[return-value]


class SEORecommendationRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    comparison_run_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("audit_run_id", "comparison_run_id", mode="before")
    @classmethod
    def normalize_optional_ids(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @model_validator(mode="after")
    def require_at_least_one_lineage_reference(self) -> "SEORecommendationRunCreateRequest":
        if self.audit_run_id is None and self.comparison_run_id is None:
            raise ValueError("At least one of audit_run_id or comparison_run_id is required")
        return self


class SEORecommendationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    audit_run_id: str | None
    comparison_run_id: str | None
    status: SEORecommendationRunStatus
    total_recommendations: int
    critical_recommendations: int
    warning_recommendations: int
    info_recommendations: int
    category_counts_json: dict[str, int] = Field(default_factory=dict)
    effort_bucket_counts_json: dict[str, int] = Field(default_factory=dict)
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_summary: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("category_counts_json", "effort_bucket_counts_json", mode="before")
    @classmethod
    def normalize_count_maps(cls, value: Any) -> dict[str, int]:
        return _normalize_int_map(value)


class SEORecommendationRunListResponse(BaseModel):
    items: list[SEORecommendationRunRead]
    total: int


class SEORecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    recommendation_run_id: str
    audit_run_id: str | None
    comparison_run_id: str | None
    rule_key: str
    category: SEORecommendationCategory
    severity: SEORecommendationSeverity
    title: str
    rationale: str
    priority_score: int
    priority_band: SEORecommendationPriorityBand
    effort_bucket: SEORecommendationEffort
    status: SEORecommendationStatus
    decision: SEORecommendationDecision | None = None
    decision_reason: str | None = None
    assigned_principal_id: str | None = None
    due_at: datetime | None = None
    snoozed_until: datetime | None = None
    resolved_at: datetime | None = None
    updated_by_principal_id: str | None = None
    evidence_json: dict[str, object] | None
    created_at: datetime
    updated_at: datetime

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category_field(cls, value: Any) -> SEORecommendationCategory:
        return _normalize_category(value)

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity_field(cls, value: Any) -> SEORecommendationSeverity:
        return _normalize_severity(value)

    @field_validator("effort_bucket", mode="before")
    @classmethod
    def normalize_effort_field(cls, value: Any) -> SEORecommendationEffort:
        return _normalize_effort(value)

    @field_validator("priority_band", mode="before")
    @classmethod
    def normalize_priority_band_field(cls, value: Any) -> SEORecommendationPriorityBand:
        return _normalize_priority_band(value)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status_field(cls, value: Any) -> SEORecommendationStatus:
        return _normalize_status(value)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision_field(cls, value: Any) -> SEORecommendationDecision | None:
        return _normalize_decision(value)


class SEORecommendationFilteredSummary(BaseModel):
    total: int
    open: int = 0
    accepted: int = 0
    dismissed: int = 0
    high_priority: int = 0


class SEORecommendationListResponse(BaseModel):
    items: list[SEORecommendationRead]
    total: int
    filtered_summary: SEORecommendationFilteredSummary | None = None
    by_status: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_effort_bucket: dict[str, int] = Field(default_factory=dict)
    by_priority_band: dict[str, int] = Field(default_factory=dict)


class SEORecommendationRunReportRead(BaseModel):
    recommendation_run: SEORecommendationRunRead
    rollups: dict[str, dict[str, int]]
    recommendations: SEORecommendationListResponse


class SEORecommendationWorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SEORecommendationStatus | None = None
    decision: SEORecommendationDecision | None = None
    decision_reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    assigned_principal_id: str | None = Field(default=None, max_length=64)
    due_at: datetime | None = None
    snoozed_until: datetime | None = None

    @field_validator("assigned_principal_id", mode="before")
    @classmethod
    def normalize_assigned_principal(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("decision_reason", mode="before")
    @classmethod
    def normalize_decision_reason(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status_input(cls, value: Any) -> SEORecommendationStatus | None:
        if value is None:
            return None
        return _normalize_status(value)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision_input(cls, value: Any) -> SEORecommendationDecision | None:
        return _normalize_decision(value)

    @model_validator(mode="after")
    def validate_note_alias_consistency(self) -> "SEORecommendationWorkflowUpdateRequest":
        if "note" in self.model_fields_set and "decision_reason" in self.model_fields_set:
            if self.note != self.decision_reason:
                raise ValueError("note and decision_reason must match when both are provided")
        return self

    @model_validator(mode="after")
    def require_update_field(self) -> "SEORecommendationWorkflowUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one workflow field is required")
        return self


class SEORecommendationBacklogRead(BaseModel):
    business_id: str
    site_id: str
    total_actionable: int
    items: list[SEORecommendationRead]


class SEORecommendationPrioritizedReportRead(BaseModel):
    business_id: str
    site_id: str
    generated_at: datetime
    total_recommendations: int
    backlog_total: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_severity: dict[str, int]
    by_effort_bucket: dict[str, int]
    by_priority_band: dict[str, int]
    backlog: SEORecommendationListResponse


class SEORecommendationNarrativeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    recommendation_run_id: str
    version: int
    status: SEORecommendationNarrativeStatus
    narrative_text: str | None
    top_themes_json: list[str] = Field(default_factory=list)
    sections_json: dict[str, object] | None
    provider_name: str
    model_name: str
    prompt_version: str
    error_message: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("top_themes_json", mode="before")
    @classmethod
    def normalize_top_themes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        raise TypeError("top_themes_json must be a list")


class SEORecommendationNarrativeListResponse(BaseModel):
    items: list[SEORecommendationNarrativeRead]
    total: int


class SEORecommendationTuningSuggestionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting: RecommendationTuningSetting
    current_value: int = Field(ge=0, le=100)
    recommended_value: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=500)
    linked_recommendation_ids: list[str] = Field(default_factory=list)
    confidence: SEORecommendationTuningSuggestionConfidence

    @field_validator("linked_recommendation_ids", mode="before")
    @classmethod
    def normalize_linked_recommendation_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("linked_recommendation_ids must be a list")
        normalized: list[str] = []
        for item in value:
            cleaned = _strip_or_none(str(item) if item is not None else None)
            if cleaned:
                normalized.append(cleaned)
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> SEORecommendationTuningSuggestionConfidence:
        normalized = str(value or "").strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("Invalid tuning suggestion confidence")
        return normalized  # type: ignore[return-value]

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str:
        cleaned = _strip_or_none(str(value) if value is not None else None)
        if cleaned is None:
            raise ValueError("reason is required")
        return cleaned


class SEORecommendationWorkspaceSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: str
    site_id: str
    state: SEORecommendationWorkspaceSummaryState
    latest_run: SEORecommendationRunRead | None
    latest_completed_run: SEORecommendationRunRead | None
    recommendations: SEORecommendationListResponse
    latest_narrative: SEORecommendationNarrativeRead | None
    tuning_suggestions: list[SEORecommendationTuningSuggestionRead] = Field(default_factory=list)


class SEORecommendationTuningValuesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_candidate_min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    competitor_candidate_big_box_penalty: int | None = Field(default=None, ge=0, le=50)
    competitor_candidate_directory_penalty: int | None = Field(default=None, ge=0, le=50)
    competitor_candidate_local_alignment_bonus: int | None = Field(default=None, ge=0, le=50)


class SEORecommendationTuningValuesRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_candidate_min_relevance_score: int = Field(ge=0, le=100)
    competitor_candidate_big_box_penalty: int = Field(ge=0, le=50)
    competitor_candidate_directory_penalty: int = Field(ge=0, le=50)
    competitor_candidate_local_alignment_bonus: int = Field(ge=0, le=50)


class SEORecommendationTuningImpactPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_values: SEORecommendationTuningValuesPatch | None = None
    proposed_values: SEORecommendationTuningValuesPatch
    recommendation_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    narrative_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("recommendation_run_id", "narrative_id", mode="before")
    @classmethod
    def normalize_optional_ids(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @model_validator(mode="after")
    def require_proposed_values(self) -> "SEORecommendationTuningImpactPreviewRequest":
        if not self.proposed_values.model_dump(exclude_none=True):
            raise ValueError("At least one proposed tuning value is required")
        return self


class SEORecommendationTuningTelemetryWindowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_days: int = Field(ge=1)
    total_runs: int = Field(ge=0)
    total_raw_candidate_count: int = Field(ge=0)
    total_included_candidate_count: int = Field(ge=0)
    total_excluded_candidate_count: int = Field(ge=0)
    exclusion_counts_by_reason: dict[str, int] = Field(default_factory=dict)


class SEORecommendationTuningImpactEstimateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insufficient_data: bool
    estimated_included_candidate_delta: int
    estimated_excluded_candidate_delta: int
    estimated_exclusion_reason_deltas: dict[str, int] = Field(default_factory=dict)
    summary: str
    risk_flags: list[str] = Field(default_factory=list)


class SEORecommendationTuningImpactPreviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: str
    site_id: str
    preview_event_id: str | None
    source_recommendation_run_id: str | None
    source_narrative_id: str | None
    current_values: SEORecommendationTuningValuesRead
    proposed_values: SEORecommendationTuningValuesRead
    telemetry_window: SEORecommendationTuningTelemetryWindowRead
    estimated_impact: SEORecommendationTuningImpactEstimateRead
    caveat: str


class SEORecommendationListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SEORecommendationStatus | None = None
    category: SEORecommendationCategory | None = None
    severity: SEORecommendationSeverity | None = None
    effort_bucket: SEORecommendationEffort | None = None
    priority_band: SEORecommendationPriorityBand | None = None
    assigned_principal_id: str | None = None
    source_type: SEORecommendationSourceType | None = None
    recommendation_run_id: str | None = None
    sort_by: SEORecommendationSortBy = "priority_score"
    sort_order: SortOrder = "desc"
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=25, ge=1, le=100)

    @field_validator("assigned_principal_id", mode="before")
    @classmethod
    def normalize_query_assignee(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("recommendation_run_id", mode="before")
    @classmethod
    def normalize_query_run_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, value: Any) -> SEORecommendationSourceType | None:
        if value is None:
            return None
        return _normalize_source_type(value)

    @field_validator("sort_by", mode="before")
    @classmethod
    def normalize_sort_by(cls, value: Any) -> SEORecommendationSortBy:
        return _normalize_sort_by(value)

    @field_validator("sort_order", mode="before")
    @classmethod
    def normalize_sort_order(cls, value: Any) -> SortOrder:
        return _normalize_sort_order(value)

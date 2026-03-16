from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SEOAutomationCadenceType = Literal["manual", "interval_minutes"]
SEOAutomationTriggerSource = Literal["manual", "scheduled"]
SEOAutomationStatus = Literal["queued", "running", "completed", "failed", "skipped"]
SEOAutomationStepName = Literal[
    "audit_run",
    "audit_summary",
    "competitor_snapshot_run",
    "comparison_run",
    "competitor_summary",
    "recommendation_run",
    "recommendation_narrative",
]


class SEOAutomationConfigUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool = False
    cadence_type: SEOAutomationCadenceType = "manual"
    cadence_minutes: int | None = Field(default=None, ge=5, le=10080)

    trigger_audit: bool = True
    trigger_audit_summary: bool = True
    trigger_competitor_snapshot: bool = False
    trigger_comparison: bool = False
    trigger_competitor_summary: bool = False
    trigger_recommendations: bool = True
    trigger_recommendation_narrative: bool = False

    @model_validator(mode="after")
    def validate_config(self) -> "SEOAutomationConfigUpsertRequest":
        if self.cadence_type == "manual" and self.cadence_minutes is not None:
            raise ValueError("cadence_minutes must be null when cadence_type=manual")
        if self.cadence_type == "interval_minutes" and self.cadence_minutes is None:
            raise ValueError("cadence_minutes is required when cadence_type=interval_minutes")

        trigger_flags = [
            self.trigger_audit,
            self.trigger_audit_summary,
            self.trigger_competitor_snapshot,
            self.trigger_comparison,
            self.trigger_competitor_summary,
            self.trigger_recommendations,
            self.trigger_recommendation_narrative,
        ]
        if not any(trigger_flags):
            raise ValueError("At least one automation trigger must be enabled")
        return self


class SEOAutomationConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool | None = None
    cadence_type: SEOAutomationCadenceType | None = None
    cadence_minutes: int | None = Field(default=None, ge=5, le=10080)

    trigger_audit: bool | None = None
    trigger_audit_summary: bool | None = None
    trigger_competitor_snapshot: bool | None = None
    trigger_comparison: bool | None = None
    trigger_competitor_summary: bool | None = None
    trigger_recommendations: bool | None = None
    trigger_recommendation_narrative: bool | None = None

    @model_validator(mode="after")
    def require_fields(self) -> "SEOAutomationConfigPatchRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class SEOAutomationConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    is_enabled: bool
    cadence_type: SEOAutomationCadenceType
    cadence_minutes: int | None

    trigger_audit: bool
    trigger_audit_summary: bool
    trigger_competitor_snapshot: bool
    trigger_comparison: bool
    trigger_competitor_summary: bool
    trigger_recommendations: bool
    trigger_recommendation_narrative: bool

    last_run_at: datetime | None
    next_run_at: datetime | None
    last_status: SEOAutomationStatus | None
    last_error_message: str | None

    created_at: datetime
    updated_at: datetime


class SEOAutomationStepRead(BaseModel):
    step_name: SEOAutomationStepName
    status: SEOAutomationStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    linked_output_id: str | None = None
    error_message: str | None = None


class SEOAutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    automation_config_id: str
    trigger_source: SEOAutomationTriggerSource
    status: SEOAutomationStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    steps_json: list[SEOAutomationStepRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def normalize_steps(cls, data: Any) -> Any:
        if isinstance(data, dict):
            payload = dict(data)
            raw_steps = payload.get("steps_json")
            if raw_steps is None:
                payload["steps_json"] = []
            return payload
        return data


class SEOAutomationRunListResponse(BaseModel):
    items: list[SEOAutomationRunRead]
    total: int


class SEOAutomationStatusRead(BaseModel):
    business_id: str
    site_id: str
    config: SEOAutomationConfigRead
    latest_run: SEOAutomationRunRead | None


class SEOAutomationDueRunSummaryRead(BaseModel):
    scanned_configs: int
    triggered_runs: int
    skipped_active_runs: int
    failed_triggers: int


class SEOAutomationDueRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: str | None = None
    limit: int = Field(default=25, ge=1, le=200)


class SEOAutomationStepWrite(BaseModel):
    step_name: SEOAutomationStepName
    status: SEOAutomationStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    linked_output_id: str | None = None
    error_message: str | None = None

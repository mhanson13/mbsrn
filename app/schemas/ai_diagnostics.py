from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AIDiagnosticsSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_category: str | None = Field(default=None, max_length=80)
    failure_reason: str | None = Field(default=None, max_length=120)
    failure_source: str | None = Field(default=None, max_length=80)
    retryable: bool | None = None
    hint: str | None = Field(default=None, max_length=220)
    budget_outcome: str | None = Field(default=None, max_length=80)
    retry_suppressed: bool | None = None
    trimming_pass_count: int | None = Field(default=None, ge=0)
    difficulty_bucket: str | None = Field(default=None, max_length=32)
    input_size_bucket: str | None = Field(default=None, max_length=32)
    degraded_state: str | None = Field(default=None, max_length=120)

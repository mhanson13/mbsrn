from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ActionChainActivationState = Literal["pending", "activated"]
ActionAutomationBindingState = Literal["unbound", "bound"]
ActionAutomationExecutionState = Literal["not_requested", "requested", "running", "succeeded", "failed"]


class ActionExecutionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str | None = None
    action_type: str
    state: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NextActionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    action_type: str
    title: str
    description: str
    source_action_id: str | None = None
    priority: str | None = None
    activation_state: ActionChainActivationState = "pending"
    activated_action_id: str | None = None
    automation_template_key: str | None = None
    automation_ready: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("activation_state", mode="before")
    @classmethod
    def normalize_activation_state(cls, value: Any) -> str:
        normalized = str(value or "pending").strip().lower()
        if normalized not in {"pending", "activated"}:
            raise ValueError("Invalid activation_state")
        return normalized


class ActionLineageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_action_id: str
    action_type: str
    title: str
    description: str
    draft_state: str
    activation_state: ActionChainActivationState
    activated_action_id: str | None = None
    automation_ready: bool = False
    automation_template_key: str | None = None
    created_at: datetime | None = None


class ActionLineageActivatedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_draft_id: str
    source_action_id: str
    action_type: str
    title: str
    description: str
    state: str
    automation_ready: bool = False
    automation_template_key: str | None = None
    automation_binding_state: ActionAutomationBindingState = "unbound"
    bound_automation_id: str | None = None
    automation_bound_at: datetime | None = None
    automation_execution_state: ActionAutomationExecutionState = "not_requested"
    automation_execution_requested_at: datetime | None = None
    last_automation_run_id: str | None = None
    automation_last_executed_at: datetime | None = None
    automation_run_status: str | None = None
    automation_run_started_at: datetime | None = None
    automation_run_completed_at: datetime | None = None
    automation_run_error_summary: str | None = None
    created_at: datetime | None = None


class ActionLineageCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chained_draft_count: int = Field(default=0, ge=0)
    activated_action_count: int = Field(default=0, ge=0)
    automation_ready_count: int = Field(default=0, ge=0)


class ActionLineageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_action_id: str
    chained_drafts: list[ActionLineageDraft] = Field(default_factory=list)
    activated_actions: list[ActionLineageActivatedAction] = Field(default_factory=list)
    counts: ActionLineageCounts


class BindActionAutomationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automation_id: str


class BoundActionAutomationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_execution_item_id: str
    automation_binding_state: ActionAutomationBindingState
    bound_automation_id: str | None = None
    automation_bound_at: datetime | None = None
    automation_ready: bool = False
    automation_template_key: str | None = None


class RequestedActionAutomationExecutionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_execution_item_id: str
    automation_binding_state: ActionAutomationBindingState
    bound_automation_id: str | None = None
    automation_bound_at: datetime | None = None
    automation_execution_state: ActionAutomationExecutionState
    automation_execution_requested_at: datetime | None = None
    last_automation_run_id: str | None = None
    automation_last_executed_at: datetime | None = None
    automation_ready: bool = False
    automation_template_key: str | None = None

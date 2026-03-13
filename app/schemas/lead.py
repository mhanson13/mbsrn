from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.lead import LeadSource, LeadStatus
from app.models.lead_event import ActorType


class ManualIntakeRequest(BaseModel):
    # Deprecated for tenant-scoped routes; kept optional for backward compatibility.
    business_id: str | None = None
    submitted_at: datetime
    customer_name: str | None = None
    phone: str | None = None
    email: str | None = None
    service_type: str | None = None
    city: str | None = None
    message: str | None = None
    estimated_job_value: float | None = None


class EmailLeadFields(BaseModel):
    customer_name: str | None = None
    phone: str | None = None
    email: str | None = None
    service_type: str | None = None
    city: str | None = None
    message: str | None = None


class EmailIntakeRequest(BaseModel):
    # Deprecated for tenant-scoped routes; kept optional for backward compatibility.
    business_id: str | None = None
    source_ref: str | None = None
    received_at: datetime
    from_address: str | None = None
    subject: str | None = None
    body_text: str | None = None
    normalized_fields: EmailLeadFields | None = None

    @model_validator(mode="after")
    def validate_input_mode(self) -> "EmailIntakeRequest":
        has_raw = bool((self.body_text or "").strip())
        has_normalized = self.normalized_fields is not None
        if not has_raw and not has_normalized:
            raise ValueError("Either body_text or normalized_fields must be provided.")
        return self


class LeadStatusPatchRequest(BaseModel):
    status: LeadStatus
    actor_type: ActorType = ActorType.OWNER
    actor_id: str | None = None
    event_note: str | None = None


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    source: LeadSource
    source_ref: str | None
    submitted_at: datetime
    customer_name: str | None
    phone: str | None
    email: str | None
    service_type: str | None
    city: str | None
    message: str | None
    status: LeadStatus
    customer_acknowledged_at: datetime | None
    owner_notified_at: datetime | None
    first_human_response_at: datetime | None
    estimated_job_value: float | None
    actual_job_value: float | None
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    items: list[LeadRead]
    total: int


class LeadSummaryResponse(BaseModel):
    by_status: dict[str, int]
    total_leads: int
    new_leads: int
    leads_awaiting_response: int
    stale_15m_count: int
    stale_2h_count: int
    avg_response_minutes: float | None
    median_response_minutes: float | None
    avg_minutes_to_first_response: float | None
    uncontacted_over_30_min: int
    period_start: datetime
    period_end: datetime


class ManualIntakeResponse(BaseModel):
    lead: LeadRead
    message: str


class EmailIntakeResponse(BaseModel):
    lead: LeadRead
    duplicate: bool
    parse_status: Literal["parsed", "normalized", "failed"]
    events_recorded: list[str]
    message: str


class StatusPatchResponse(BaseModel):
    lead: LeadRead
    previous_status: LeadStatus
    current_status: LeadStatus


class LeadTimelineEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    event_timestamp: datetime
    actor_type: ActorType
    actor_id: str | None
    payload_json: dict


class LeadTimelineResponse(BaseModel):
    lead_id: str
    events: list[LeadTimelineEventRead]


class ReminderRunRequest(BaseModel):
    # Deprecated for tenant-scoped routes; kept optional for backward compatibility.
    business_id: str | None = None


class ReminderRunActionRead(BaseModel):
    lead_id: str
    threshold_minutes: int
    event_type: str
    notification_sent: bool
    channel: str | None
    recipient: str | None


class ReminderRunResponse(BaseModel):
    business_id: str
    scanned_leads: int
    reminders_sent: int
    reminder_15m_sent: int
    reminder_2h_sent: int
    actions: list[ReminderRunActionRead]


SummaryWindow = Literal["24h", "7d", "30d"]


@dataclass
class ParsedLeadData:
    source_ref: str | None
    submitted_at: datetime
    customer_name: str | None
    phone: str | None
    email: str | None
    service_type: str | None
    city: str | None
    message: str | None
    parse_status: Literal["parsed", "normalized", "failed"]
    parse_errors: list[str]

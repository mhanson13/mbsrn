from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.lead import Lead, LeadStatus
from app.models.lead_event import ActorType, LeadEvent, LeadEventType
from app.repositories.lead_repository import LeadRepository


class InvalidStatusTransitionError(ValueError):
    pass


class LeadLifecycleService:
    ALLOWED_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
        LeadStatus.NEW: {LeadStatus.CONTACTED, LeadStatus.ESTIMATE_SCHEDULED, LeadStatus.LOST},
        LeadStatus.CONTACTED: {LeadStatus.ESTIMATE_SCHEDULED, LeadStatus.WON, LeadStatus.LOST},
        LeadStatus.ESTIMATE_SCHEDULED: {LeadStatus.WON, LeadStatus.LOST},
        LeadStatus.WON: set(),
        LeadStatus.LOST: set(),
    }

    def __init__(self, session: Session, lead_repository: LeadRepository) -> None:
        self.session = session
        self.lead_repository = lead_repository

    def validate_transition(self, current_status: LeadStatus, next_status: LeadStatus) -> None:
        if next_status == current_status:
            return

        allowed = self.ALLOWED_TRANSITIONS.get(current_status, set())
        if next_status not in allowed:
            raise InvalidStatusTransitionError(f"Invalid transition: {current_status.value} -> {next_status.value}")

    def patch_status(
        self,
        *,
        business_id: str,
        lead_id: str,
        next_status: LeadStatus,
        actor_type: ActorType,
        actor_id: str | None,
        event_note: str | None,
    ) -> tuple[Lead, LeadStatus]:
        lead = self.lead_repository.get_for_business(business_id, lead_id)
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")
        if lead.business_id != business_id:
            raise ValueError(
                "Lead/business scope mismatch in lifecycle status update: " f"{lead.business_id} != {business_id}"
            )

        previous = lead.status
        self.validate_transition(previous, next_status)

        lead.status = next_status
        now = utc_now()
        if lead.first_human_response_at is None and next_status != LeadStatus.NEW:
            lead.first_human_response_at = now

        event_payload = {"from": previous.value, "to": next_status.value}
        if event_note:
            event_payload["note"] = event_note

        self.lead_repository.add_event(
            LeadEvent(
                id=str(uuid4()),
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.STATUS_CHANGED.value,
                actor_type=actor_type,
                actor_id=actor_id,
                payload_json=event_payload,
            )
        )

        self.session.commit()
        self.session.refresh(lead)
        return lead, previous

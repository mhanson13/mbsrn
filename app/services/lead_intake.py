from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_event import ActorType, LeadEvent, LeadEventType
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import ManualIntakeRequest


class LeadIntakeService:
    """Phase 1 manual lead capture service."""

    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        lead_repository: LeadRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.lead_repository = lead_repository

    def create_manual_lead(self, payload: ManualIntakeRequest) -> Lead:
        if not payload.business_id:
            raise ValueError("Business not found")

        business = self.business_repository.get(payload.business_id)
        if not business:
            raise ValueError("Business not found")

        lead = Lead(
            id=str(uuid4()),
            business_id=business.id,
            source=LeadSource.MANUAL,
            source_ref=None,
            submitted_at=payload.submitted_at,
            customer_name=payload.customer_name,
            phone=payload.phone,
            email=payload.email,
            service_type=payload.service_type,
            city=payload.city,
            message=payload.message,
            estimated_job_value=payload.estimated_job_value,
            status=LeadStatus.NEW,
        )
        self.lead_repository.create(lead)

        self.lead_repository.add_event(
            LeadEvent(
                id=str(uuid4()),
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.LEAD_CREATED.value,
                actor_type=ActorType.OWNER,
                payload_json={"source": LeadSource.MANUAL.value},
            )
        )

        self.session.commit()
        self.session.refresh(lead)
        return lead

from __future__ import annotations

from app.models.lead_event import LeadEvent
from app.repositories.lead_repository import LeadRepository


class LeadTimelineService:
    def __init__(self, lead_repository: LeadRepository) -> None:
        self.lead_repository = lead_repository

    def get_timeline(self, *, business_id: str, lead_id: str) -> list[LeadEvent]:
        lead = self.lead_repository.get_for_business(business_id, lead_id)
        if not lead:
            raise ValueError("Lead not found")
        if lead.business_id != business_id:
            raise ValueError("Lead/business scope mismatch in timeline lookup: " f"{lead.business_id} != {business_id}")
        return self.lead_repository.list_events_for_business_lead(business_id, lead_id)

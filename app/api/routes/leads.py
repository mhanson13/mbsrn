from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    get_lead_repository,
    get_lifecycle_service,
    get_summary_service,
    get_timeline_service,
)
from app.models.lead import LeadStatus
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import (
    LeadListResponse,
    LeadRead,
    LeadStatusPatchRequest,
    LeadSummaryResponse,
    LeadTimelineEventRead,
    LeadTimelineResponse,
    StatusPatchResponse,
)
from app.services.lifecycle import InvalidStatusTransitionError, LeadLifecycleService
from app.services.summary import LeadSummaryService
from app.services.timeline import LeadTimelineService

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("/summary", response_model=LeadSummaryResponse)
def get_summary(
    business_id: str = Query(...),
    window: str = Query("7d", pattern="^(24h|7d|30d)$"),
    summary_service: LeadSummaryService = Depends(get_summary_service),
) -> LeadSummaryResponse:
    payload = summary_service.get_summary(business_id=business_id, window=window)
    return LeadSummaryResponse(**payload)


@router.get("", response_model=LeadListResponse)
def list_leads(
    business_id: str = Query(...),
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> LeadListResponse:
    items = lead_repository.list(business_id=business_id, status=status_filter)
    return LeadListResponse(items=[LeadRead.model_validate(item) for item in items], total=len(items))


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(
    lead_id: str,
    business_id: str = Query(...),
    lead_repository: LeadRepository = Depends(get_lead_repository),
) -> LeadRead:
    lead = lead_repository.get_for_business(business_id, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return LeadRead.model_validate(lead)


@router.get("/{lead_id}/timeline", response_model=LeadTimelineResponse)
def get_lead_timeline(
    lead_id: str,
    business_id: str = Query(...),
    timeline_service: LeadTimelineService = Depends(get_timeline_service),
) -> LeadTimelineResponse:
    try:
        events = timeline_service.get_timeline(business_id=business_id, lead_id=lead_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return LeadTimelineResponse(
        lead_id=lead_id,
        events=[LeadTimelineEventRead.model_validate(event) for event in events],
    )


@router.patch("/{lead_id}/status", response_model=StatusPatchResponse)
def patch_lead_status(
    lead_id: str,
    payload: LeadStatusPatchRequest,
    business_id: str = Query(...),
    lifecycle_service: LeadLifecycleService = Depends(get_lifecycle_service),
) -> StatusPatchResponse:
    try:
        lead, previous = lifecycle_service.patch_status(
            business_id=business_id,
            lead_id=lead_id,
            next_status=payload.status,
            actor_type=payload.actor_type,
            actor_id=payload.actor_id,
            event_note=payload.event_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return StatusPatchResponse(
        lead=LeadRead.model_validate(lead),
        previous_status=previous,
        current_status=lead.status,
    )

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_lead_reminder_job,
    get_tenant_context,
    resolve_tenant_business_id,
    TenantContext,
)
from app.jobs.lead_reminders import LeadReminderJob
from app.schemas.lead import ReminderRunActionRead, ReminderRunRequest, ReminderRunResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/lead-reminders/run", response_model=ReminderRunResponse, status_code=status.HTTP_200_OK)
def run_lead_reminders(
    payload: ReminderRunRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    reminder_job: LeadReminderJob = Depends(get_lead_reminder_job),
) -> ReminderRunResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=payload.business_id,
    )
    try:
        result = reminder_job.run(business_id=scoped_business_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ReminderRunResponse(
        business_id=result.business_id,
        scanned_leads=result.scanned_leads,
        reminders_sent=result.reminders_sent,
        reminder_15m_sent=result.reminder_15m_sent,
        reminder_2h_sent=result.reminder_2h_sent,
        actions=[ReminderRunActionRead(**action.__dict__) for action in result.actions],
    )

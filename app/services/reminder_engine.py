from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import ensure_utc, utc_now
from app.models.lead_event import ActorType, LeadEvent, LeadEventType
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.services.notifications import NotificationDispatchService


@dataclass(frozen=True)
class ReminderAction:
    lead_id: str
    threshold_minutes: int
    event_type: str
    notification_sent: bool
    channel: str | None
    recipient: str | None


@dataclass(frozen=True)
class ReminderRunResult:
    business_id: str
    scanned_leads: int
    reminders_sent: int
    reminder_15m_sent: int
    reminder_2h_sent: int
    actions: list[ReminderAction]


class ReminderEngineService:
    THRESHOLDS: tuple[tuple[int, LeadEventType], ...] = (
        (15, LeadEventType.REMINDER_15M_TRIGGERED),
        (120, LeadEventType.REMINDER_2H_TRIGGERED),
    )

    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        lead_repository: LeadRepository,
        notification_service: NotificationDispatchService,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.lead_repository = lead_repository
        self.notification_service = notification_service

    def run_for_business(self, *, business_id: str) -> ReminderRunResult:
        business = self.business_repository.get(business_id)
        if not business:
            raise ValueError("Business not found")

        leads = self.lead_repository.list_awaiting_first_response(business_id)
        lead_ids = [lead.id for lead in leads]
        existing_events = self.lead_repository.list_events_for_business(
            business_id,
            lead_ids=lead_ids,
            event_types=[event.value for _, event in self.THRESHOLDS],
        )
        sent_thresholds: dict[str, set[str]] = {}
        for event in existing_events:
            sent_thresholds.setdefault(event.lead_id, set()).add(event.event_type)

        reminder_15m_sent = 0
        reminder_2h_sent = 0
        actions: list[ReminderAction] = []
        now = utc_now()

        for lead in leads:
            if lead.business_id != business_id:
                raise ValueError(
                    "Lead/business scope mismatch in reminder engine: " f"{lead.business_id} != {business_id}"
                )
            submitted_at = ensure_utc(lead.submitted_at)
            age_minutes = max((now - submitted_at).total_seconds() / 60.0, 0.0)
            already_sent = sent_thresholds.setdefault(lead.id, set())

            for threshold_minutes, event_type in self.THRESHOLDS:
                if age_minutes < threshold_minutes:
                    continue
                if event_type.value in already_sent:
                    continue

                notification = self.notification_service.send_owner_reminder(
                    lead=lead,
                    business=business,
                    threshold_minutes=threshold_minutes,
                    age_minutes=round(age_minutes, 1),
                    idempotency_key=f"reminder:{threshold_minutes}:{lead.id}",
                )
                if notification.sent:
                    lead.owner_notified_at = now

                self.lead_repository.add_event(
                    LeadEvent(
                        id=str(uuid4()),
                        business_id=lead.business_id,
                        lead_id=lead.id,
                        event_type=event_type.value,
                        actor_type=ActorType.SYSTEM,
                        payload_json={
                            "threshold_minutes": threshold_minutes,
                            "lead_age_minutes": round(age_minutes, 1),
                            "notification": {
                                "attempted": notification.attempted,
                                "sent": notification.sent,
                                "channel": notification.channel,
                                "recipient": notification.recipient,
                                "provider": notification.provider,
                                "detail": notification.detail,
                            },
                        },
                    )
                )

                already_sent.add(event_type.value)
                if threshold_minutes == 15:
                    reminder_15m_sent += 1
                elif threshold_minutes == 120:
                    reminder_2h_sent += 1

                actions.append(
                    ReminderAction(
                        lead_id=lead.id,
                        threshold_minutes=threshold_minutes,
                        event_type=event_type.value,
                        notification_sent=notification.sent,
                        channel=notification.channel,
                        recipient=notification.recipient,
                    )
                )

        self.session.commit()
        return ReminderRunResult(
            business_id=business_id,
            scanned_leads=len(leads),
            reminders_sent=len(actions),
            reminder_15m_sent=reminder_15m_sent,
            reminder_2h_sent=reminder_2h_sent,
            actions=actions,
        )

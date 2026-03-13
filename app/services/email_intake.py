from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_event import ActorType, LeadEvent, LeadEventType
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import EmailIntakeRequest
from app.services.dedupe import LeadDeduplicationService
from app.services.notifications import NotificationDispatchService
from app.services.parser import LeadParserService


@dataclass(frozen=True)
class EmailIntakeResult:
    lead: Lead
    duplicate: bool
    parse_status: Literal["parsed", "normalized", "failed"]
    events_recorded: list[str]
    message: str


class EmailIntakeService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        lead_repository: LeadRepository,
        parser_service: LeadParserService,
        dedupe_service: LeadDeduplicationService,
        notification_service: NotificationDispatchService,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.lead_repository = lead_repository
        self.parser_service = parser_service
        self.dedupe_service = dedupe_service
        self.notification_service = notification_service

    def ingest(self, payload: EmailIntakeRequest) -> EmailIntakeResult:
        if not payload.business_id:
            raise ValueError("Business not found")

        business = self.business_repository.get(payload.business_id)
        if not business:
            raise ValueError("Business not found")

        parsed = self.parser_service.parse_payload(
            received_at=payload.received_at,
            source_ref=payload.source_ref,
            subject=payload.subject,
            body_text=payload.body_text,
            normalized_fields=payload.normalized_fields,
        )

        dedupe_match = self.dedupe_service.find_duplicate(
            business_id=payload.business_id,
            submitted_at=parsed.submitted_at,
            customer_name=parsed.customer_name,
            phone=parsed.phone,
            email=parsed.email,
        )

        events_recorded: list[str] = []
        duplicate = dedupe_match is not None

        if duplicate:
            lead = dedupe_match.lead
            merged_fields = self.dedupe_service.merge_duplicate(lead=lead, parsed=parsed)
        else:
            lead = Lead(
                id=str(uuid4()),
                business_id=payload.business_id,
                source=LeadSource.GODADDY_EMAIL,
                source_ref=parsed.source_ref,
                submitted_at=parsed.submitted_at,
                customer_name=parsed.customer_name,
                phone=parsed.phone,
                email=parsed.email,
                service_type=parsed.service_type,
                city=parsed.city,
                message=parsed.message or payload.body_text,
                status=LeadStatus.NEW,
            )
            self.lead_repository.create(lead)
            merged_fields = []

        self._add_event(
            business_id=lead.business_id,
            lead_id=lead.id,
            event_type=LeadEventType.EMAIL_RECEIVED,
            payload={
                "source": LeadSource.GODADDY_EMAIL.value,
                "source_ref": payload.source_ref,
                "from_address": payload.from_address,
                "subject": payload.subject,
                "received_at": payload.received_at.isoformat(),
            },
            events_recorded=events_recorded,
        )

        if parsed.parse_status == "failed":
            self._add_event(
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.PARSING_FAILED,
                payload={
                    "errors": parsed.parse_errors,
                    "subject": payload.subject,
                },
                events_recorded=events_recorded,
            )
        else:
            self._add_event(
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.LEAD_PARSED,
                payload={
                    "parse_status": parsed.parse_status,
                    "fields": {
                        "customer_name": parsed.customer_name,
                        "phone": parsed.phone,
                        "email": parsed.email,
                        "service_type": parsed.service_type,
                        "city": parsed.city,
                        "message": parsed.message,
                    },
                },
                events_recorded=events_recorded,
            )

        if duplicate and dedupe_match is not None:
            self._add_event(
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.DUPLICATE_DETECTED,
                payload={
                    "rule": dedupe_match.rule,
                    "updated_fields": merged_fields,
                },
                events_recorded=events_recorded,
            )
        else:
            self._add_event(
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.LEAD_CREATED,
                payload={"source": LeadSource.GODADDY_EMAIL.value},
                events_recorded=events_recorded,
            )

        customer_ack = self.notification_service.send_customer_ack(
            lead=lead,
            business=business,
            idempotency_key=self._idempotency_key(payload.source_ref, "customer_ack"),
        )
        if customer_ack.sent:
            lead.customer_acknowledged_at = utc_now()
        self._add_event(
            business_id=lead.business_id,
            lead_id=lead.id,
            event_type=LeadEventType.CUSTOMER_ACK_TRIGGERED,
            payload={
                "attempted": customer_ack.attempted,
                "sent": customer_ack.sent,
                "channel": customer_ack.channel,
                "recipient": customer_ack.recipient,
                "provider": customer_ack.provider,
                "detail": customer_ack.detail,
            },
            events_recorded=events_recorded,
        )

        contractor_alert = self.notification_service.send_owner_notification(
            lead=lead,
            business=business,
            idempotency_key=self._idempotency_key(payload.source_ref, "contractor_alert"),
        )
        if contractor_alert.sent:
            lead.owner_notified_at = utc_now()
        self._add_event(
            business_id=lead.business_id,
            lead_id=lead.id,
            event_type=LeadEventType.CONTRACTOR_NOTIFICATION_TRIGGERED,
            payload={
                "attempted": contractor_alert.attempted,
                "sent": contractor_alert.sent,
                "channel": contractor_alert.channel,
                "recipient": contractor_alert.recipient,
                "provider": contractor_alert.provider,
                "detail": contractor_alert.detail,
            },
            events_recorded=events_recorded,
        )

        self.session.commit()
        self.session.refresh(lead)

        message = "Lead captured from email intake."
        if duplicate:
            message = "Duplicate lead detected; existing lead was updated."
        elif parsed.parse_status == "failed":
            message = "Email captured but parsing failed; lead created for manual review."

        return EmailIntakeResult(
            lead=lead,
            duplicate=duplicate,
            parse_status=parsed.parse_status,
            events_recorded=events_recorded,
            message=message,
        )

    def _add_event(
        self,
        *,
        business_id: str,
        lead_id: str,
        event_type: LeadEventType,
        payload: dict,
        events_recorded: list[str],
    ) -> None:
        self.lead_repository.add_event(
            LeadEvent(
                id=str(uuid4()),
                business_id=business_id,
                lead_id=lead_id,
                event_type=event_type.value,
                actor_type=ActorType.SYSTEM,
                payload_json=payload,
            )
        )
        events_recorded.append(event_type.value)

    def _idempotency_key(self, source_ref: str | None, purpose: str) -> str | None:
        if not source_ref:
            return None
        return f"{purpose}:{source_ref}"

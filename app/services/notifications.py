from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal
from uuid import uuid4

from app.integrations import EmailProvider, SMSProvider
from app.models.business import Business
from app.models.lead import Lead
from app.models.lead_event import ActorType, LeadEvent, LeadEventType
from app.repositories.lead_repository import LeadRepository


_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")


@dataclass(frozen=True)
class NotificationAttempt:
    channel: Literal["sms", "email"]
    recipient: str
    sent: bool
    provider: str | None
    provider_message_id: str | None
    detail: str
    fallback: bool


@dataclass(frozen=True)
class NotificationResult:
    requested: bool
    attempted: bool
    sent: bool
    skipped: bool
    channel: str | None
    recipient: str | None
    provider: str | None
    detail: str
    attempts: list[NotificationAttempt]


class NotificationDispatchService:
    def __init__(
        self,
        *,
        lead_repository: LeadRepository | None = None,
        email_provider: EmailProvider,
        sms_provider: SMSProvider,
    ) -> None:
        self.lead_repository = lead_repository
        self.email_provider = email_provider
        self.sms_provider = sms_provider

    def send_customer_ack(
        self,
        *,
        lead: Lead,
        business: Business,
        idempotency_key: str | None = None,
    ) -> NotificationResult:
        scope_mismatch = self._scope_guard(
            lead=lead,
            business=business,
            kind="customer_ack",
            idempotency_key=idempotency_key,
        )
        if scope_mismatch:
            return scope_mismatch

        if not business.customer_auto_ack_enabled:
            reason = "Customer auto acknowledgment is disabled for this business."
            self._record_event(
                lead_id=lead.id,
                event_type=LeadEventType.NOTIFICATION_DISPATCH_SKIPPED,
                payload={
                    "notification_kind": "customer_ack",
                    "idempotency_key": idempotency_key,
                    "reason": reason,
                },
            )
            return self._skipped_result(reason)

        message = (
            f"Hi {lead.customer_name or 'there'}, we received your request for "
            f"{lead.service_type or 'service'}. {business.name or 'your contractor'} will follow up soon."
        )
        subject = f"{business.name or 'Work Boots Console'}: we received your request"
        channels = self._customer_channels(lead=lead, business=business)
        return self._dispatch(
            lead=lead,
            kind="customer_ack",
            subject=subject,
            message=message,
            channels=channels,
            idempotency_key=idempotency_key,
        )

    def send_owner_notification(
        self,
        *,
        lead: Lead,
        business: Business,
        idempotency_key: str | None = None,
    ) -> NotificationResult:
        scope_mismatch = self._scope_guard(
            lead=lead,
            business=business,
            kind="contractor_alert",
            idempotency_key=idempotency_key,
        )
        if scope_mismatch:
            return scope_mismatch

        if not business.contractor_alerts_enabled:
            reason = "Contractor alerts are disabled for this business."
            self._record_event(
                lead_id=lead.id,
                event_type=LeadEventType.NOTIFICATION_DISPATCH_SKIPPED,
                payload={
                    "notification_kind": "contractor_alert",
                    "idempotency_key": idempotency_key,
                    "reason": reason,
                },
            )
            return self._skipped_result(reason)

        summary = (
            f"New lead for {business.name}: "
            f"{lead.customer_name or 'Unknown'} | "
            f"{lead.phone or lead.email or 'No contact'} | "
            f"{lead.service_type or 'No service'} | "
            f"{lead.city or 'No city'}"
        )
        channels = self._contractor_channels(business=business)
        return self._dispatch(
            lead=lead,
            kind="contractor_alert",
            subject="Work Boots Console: New lead received",
            message=summary,
            channels=channels,
            idempotency_key=idempotency_key,
        )

    def send_owner_reminder(
        self,
        *,
        lead: Lead,
        business: Business,
        threshold_minutes: int,
        age_minutes: float,
        idempotency_key: str | None = None,
    ) -> NotificationResult:
        scope_mismatch = self._scope_guard(
            lead=lead,
            business=business,
            kind="owner_reminder",
            idempotency_key=idempotency_key,
            extra_payload={
                "threshold_minutes": threshold_minutes,
                "lead_age_minutes": age_minutes,
            },
        )
        if scope_mismatch:
            return scope_mismatch

        if not business.contractor_alerts_enabled:
            reason = "Contractor alerts are disabled for this business."
            self._record_event(
                lead_id=lead.id,
                event_type=LeadEventType.NOTIFICATION_DISPATCH_SKIPPED,
                payload={
                    "notification_kind": "owner_reminder",
                    "idempotency_key": idempotency_key,
                    "threshold_minutes": threshold_minutes,
                    "lead_age_minutes": age_minutes,
                    "reason": reason,
                },
            )
            return self._skipped_result(reason)

        summary = (
            f"Reminder ({threshold_minutes}m): lead still waiting. "
            f"{lead.customer_name or 'Unknown'} | "
            f"{lead.phone or lead.email or 'No contact'} | "
            f"age={age_minutes:.1f} minutes | "
            f"{lead.service_type or 'No service'}"
        )
        channels = self._contractor_channels(business=business)
        return self._dispatch(
            lead=lead,
            kind="owner_reminder",
            subject=f"Work Boots Console: Lead reminder ({threshold_minutes}m)",
            message=summary,
            channels=channels,
            idempotency_key=idempotency_key,
            extra_payload={
                "threshold_minutes": threshold_minutes,
                "lead_age_minutes": age_minutes,
            },
        )

    def _dispatch(
        self,
        *,
        lead: Lead,
        kind: str,
        subject: str,
        message: str,
        channels: list[tuple[Literal["sms", "email"], str]],
        idempotency_key: str | None,
        extra_payload: dict | None = None,
    ) -> NotificationResult:
        payload_base = {
            "notification_kind": kind,
            "idempotency_key": idempotency_key,
            "business_id": lead.business_id,
        }
        if extra_payload:
            payload_base.update(extra_payload)

        self._record_event(
            lead_id=lead.id,
            event_type=LeadEventType.NOTIFICATION_DISPATCH_REQUESTED,
            payload={**payload_base, "channel_count": len(channels)},
        )

        if not channels:
            self._record_event(
                lead_id=lead.id,
                event_type=LeadEventType.NOTIFICATION_DISPATCH_SKIPPED,
                payload={**payload_base, "reason": "No valid enabled notification target found."},
            )
            return NotificationResult(
                requested=True,
                attempted=False,
                sent=False,
                skipped=True,
                channel=None,
                recipient=None,
                provider=None,
                detail="No valid enabled notification target found.",
                attempts=[],
            )

        if idempotency_key and self._already_sent(lead_id=lead.id, kind=kind, idempotency_key=idempotency_key):
            self._record_event(
                lead_id=lead.id,
                event_type=LeadEventType.NOTIFICATION_DISPATCH_SKIPPED,
                payload={**payload_base, "reason": "Duplicate idempotency key detected."},
            )
            return NotificationResult(
                requested=True,
                attempted=False,
                sent=False,
                skipped=True,
                channel=None,
                recipient=None,
                provider=None,
                detail="Dispatch skipped due to duplicate idempotency key.",
                attempts=[],
            )

        attempts: list[NotificationAttempt] = []
        for index, (channel, recipient) in enumerate(channels):
            is_fallback = index > 0
            if is_fallback:
                self._record_event(
                    lead_id=lead.id,
                    event_type=LeadEventType.NOTIFICATION_FALLBACK_ATTEMPTED,
                    payload={**payload_base, "channel": channel, "recipient": recipient},
                )
            try:
                if channel == "sms":
                    dispatch = self.sms_provider.send_sms(to_number=recipient, body=message)
                    provider = dispatch.provider
                    detail = dispatch.status
                    provider_message_id = dispatch.provider_message_id
                else:
                    dispatch = self.email_provider.send_email(
                        to_address=recipient,
                        subject=subject,
                        body=message,
                    )
                    provider = dispatch.provider
                    detail = dispatch.status
                    provider_message_id = dispatch.provider_message_id
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)
                attempts.append(
                    NotificationAttempt(
                        channel=channel,
                        recipient=recipient,
                        sent=False,
                        provider=None,
                        provider_message_id=None,
                        detail=detail,
                        fallback=is_fallback,
                    )
                )
                self._record_event(
                    lead_id=lead.id,
                    event_type=LeadEventType.NOTIFICATION_DISPATCH_FAILED,
                    payload={
                        **payload_base,
                        "channel": channel,
                        "recipient": recipient,
                        "error": detail,
                        "fallback": is_fallback,
                    },
                )
                continue

            attempts.append(
                NotificationAttempt(
                    channel=channel,
                    recipient=recipient,
                    sent=True,
                    provider=provider,
                    provider_message_id=provider_message_id,
                    detail=detail,
                    fallback=is_fallback,
                )
            )
            self._record_event(
                lead_id=lead.id,
                event_type=LeadEventType.NOTIFICATION_DISPATCH_SENT,
                payload={
                    **payload_base,
                    "channel": channel,
                    "recipient": recipient,
                    "provider": provider,
                    "provider_message_id": provider_message_id,
                    "detail": detail,
                    "fallback": is_fallback,
                },
            )
            if is_fallback:
                self._record_event(
                    lead_id=lead.id,
                    event_type=LeadEventType.NOTIFICATION_FALLBACK_SENT,
                    payload={
                        **payload_base,
                        "channel": channel,
                        "recipient": recipient,
                        "provider": provider,
                        "provider_message_id": provider_message_id,
                    },
                )
            return NotificationResult(
                requested=True,
                attempted=True,
                sent=True,
                skipped=False,
                channel=channel,
                recipient=recipient,
                provider=provider,
                detail=detail,
                attempts=attempts,
            )

        return NotificationResult(
            requested=True,
            attempted=bool(attempts),
            sent=False,
            skipped=False,
            channel=None,
            recipient=None,
            provider=None,
            detail="All notification attempts failed.",
            attempts=attempts,
        )

    def _customer_channels(
        self,
        *,
        lead: Lead,
        business: Business,
    ) -> list[tuple[Literal["sms", "email"], str]]:
        channels: list[tuple[Literal["sms", "email"], str]] = []
        if business.sms_enabled:
            normalized_phone = self._normalize_phone(lead.phone)
            if normalized_phone:
                channels.append(("sms", normalized_phone))
        if business.email_enabled:
            normalized_email = self._normalize_email(lead.email)
            if normalized_email:
                channels.append(("email", normalized_email))
        return channels

    def _contractor_channels(self, *, business: Business) -> list[tuple[Literal["sms", "email"], str]]:
        channels: list[tuple[Literal["sms", "email"], str]] = []
        if business.sms_enabled:
            normalized_phone = self._normalize_phone(business.notification_phone)
            if normalized_phone:
                channels.append(("sms", normalized_phone))
        if business.email_enabled:
            normalized_email = self._normalize_email(business.notification_email)
            if normalized_email:
                channels.append(("email", normalized_email))
        return channels

    def _already_sent(self, *, lead_id: str, kind: str, idempotency_key: str) -> bool:
        if self.lead_repository is None:
            return False
        for event in self.lead_repository.list_events_for_lead(lead_id):
            if event.event_type != LeadEventType.NOTIFICATION_DISPATCH_SENT.value:
                continue
            payload = event.payload_json or {}
            if payload.get("notification_kind") == kind and payload.get("idempotency_key") == idempotency_key:
                return True
        return False

    def _record_event(self, *, lead_id: str, event_type: LeadEventType, payload: dict) -> None:
        if self.lead_repository is None:
            return
        self.lead_repository.add_event(
            LeadEvent(
                id=str(uuid4()),
                lead_id=lead_id,
                event_type=event_type.value,
                actor_type=ActorType.SYSTEM,
                payload_json=payload,
            )
        )

    def _skipped_result(self, reason: str) -> NotificationResult:
        return NotificationResult(
            requested=False,
            attempted=False,
            sent=False,
            skipped=True,
            channel=None,
            recipient=None,
            provider=None,
            detail=reason,
            attempts=[],
        )

    def _scope_guard(
        self,
        *,
        lead: Lead,
        business: Business,
        kind: str,
        idempotency_key: str | None,
        extra_payload: dict | None = None,
    ) -> NotificationResult | None:
        if lead.business_id == business.id:
            return None

        reason = "Lead does not belong to the supplied business context."
        payload = {
            "notification_kind": kind,
            "idempotency_key": idempotency_key,
            "lead_business_id": lead.business_id,
            "business_id": business.id,
            "reason": reason,
        }
        if extra_payload:
            payload.update(extra_payload)
        self._record_event(
            lead_id=lead.id,
            event_type=LeadEventType.NOTIFICATION_DISPATCH_SKIPPED,
            payload=payload,
        )
        return self._skipped_result(reason)

    def _normalize_email(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = str(value).strip().lower()
        if not _EMAIL_REGEX.match(normalized):
            return None
        return normalized

    def _is_valid_email(self, value: str | None) -> bool:
        return self._normalize_email(value) is not None

    def _is_valid_phone(self, value: str | None) -> bool:
        return self._normalize_phone(value) is not None

    def _normalize_phone(self, value: str | None) -> str | None:
        if not value:
            return None
        condensed = re.sub(r"[()\s\-.]", "", str(value).strip())
        if not condensed:
            return None

        if condensed.startswith("+"):
            if condensed.count("+") != 1:
                return None
            digits = condensed[1:]
            if not digits.isdigit():
                return None
            normalized = f"+{digits}"
            if not _E164_REGEX.match(normalized):
                return None
            return normalized

        if "+" in condensed or not condensed.isdigit():
            return None
        if len(condensed) == 10:
            return f"+1{condensed}"
        if len(condensed) == 11 and condensed.startswith("1"):
            return f"+{condensed}"
        return None


# Backward-compatible alias used by existing imports.
NotificationService = NotificationDispatchService

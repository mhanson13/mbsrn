from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.core.time import utc_now
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_event import LeadEvent
from app.repositories.lead_repository import LeadRepository
from app.services.notifications import NotificationDispatchService


class RecordingSMSProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_sms(self, *, to_number: str, body: str):
        self.calls.append((to_number, body))
        from app.integrations.sms_provider import SMSDispatchResult

        return SMSDispatchResult(provider="recording_sms", recipient=to_number, status="sent")


class RecordingEmailProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def send_email(self, *, to_address: str, subject: str, body: str):
        self.calls.append((to_address, subject, body))
        from app.integrations.email_provider import EmailDispatchResult

        return EmailDispatchResult(
            provider="recording_email",
            recipient=to_address,
            subject=subject,
            status="sent",
        )


class FailingSMSProvider:
    def send_sms(self, *, to_number: str, body: str):
        _ = to_number, body
        raise RuntimeError("sms provider failed")


class FailingEmailProvider:
    def send_email(self, *, to_address: str, subject: str, body: str):
        _ = to_address, subject, body
        raise RuntimeError("email provider failed")


def _seed_lead(db_session, business_id: str, *, email: str | None, phone: str | None) -> Lead:
    lead = Lead(
        id=str(uuid4()),
        business_id=business_id,
        source=LeadSource.GODADDY_EMAIL,
        source_ref="dispatch-test",
        submitted_at=utc_now() - timedelta(minutes=5),
        customer_name="Dispatch Lead",
        phone=phone,
        email=email,
        service_type="Fire cleanup",
        city="Denver",
        message="Need help",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


def test_contractor_sms_path(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = False
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = "+13035550999"
    seeded_business.notification_email = None
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email="lead@example.com", phone="+13035550000")
    sms = RecordingSMSProvider()
    email = RecordingEmailProvider()
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=email,
        sms_provider=sms,
    )

    result = service.send_owner_notification(lead=lead, business=seeded_business)

    assert result.sent is True
    assert result.channel == "sms"
    assert len(sms.calls) == 1
    assert len(email.calls) == 0


def test_customer_ack_prefers_sms_path(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = True
    seeded_business.customer_auto_ack_enabled = True
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email="customer@example.com", phone="+13035550111")
    sms = RecordingSMSProvider()
    email = RecordingEmailProvider()
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=email,
        sms_provider=sms,
    )

    result = service.send_customer_ack(lead=lead, business=seeded_business)

    assert result.sent is True
    assert result.channel == "sms"
    assert len(sms.calls) == 1
    assert len(email.calls) == 0


def test_dispatch_failure_records_and_fallback_succeeds(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = True
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = "+13035550122"
    seeded_business.notification_email = "owner@tmfire.example"
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email=None, phone="+13035550111")
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=RecordingEmailProvider(),
        sms_provider=FailingSMSProvider(),
    )

    result = service.send_owner_notification(lead=lead, business=seeded_business)
    event_types = [
        event.event_type
        for event in db_session.query(LeadEvent).filter(LeadEvent.lead_id == lead.id).all()
    ]

    assert result.sent is True
    assert result.channel == "email"
    assert "notification_dispatch_failed" in event_types
    assert "notification_fallback_attempted" in event_types
    assert "notification_fallback_sent" in event_types


def test_dispatch_failure_does_not_raise_when_no_fallback(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = False
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = "+13035550122"
    seeded_business.notification_email = None
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email=None, phone="+13035550111")
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=FailingEmailProvider(),
        sms_provider=FailingSMSProvider(),
    )

    result = service.send_owner_notification(lead=lead, business=seeded_business)
    assert result.sent is False
    assert result.attempted is True
    assert result.detail == "All notification attempts failed."


def test_early_skipped_cases_record_skip_events(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = True
    seeded_business.customer_auto_ack_enabled = False
    seeded_business.contractor_alerts_enabled = False
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email="customer@example.com", phone="+13035550111")
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=RecordingEmailProvider(),
        sms_provider=RecordingSMSProvider(),
    )

    ack_result = service.send_customer_ack(lead=lead, business=seeded_business, idempotency_key="ack-skip")
    owner_result = service.send_owner_notification(
        lead=lead,
        business=seeded_business,
        idempotency_key="owner-skip",
    )
    reminder_result = service.send_owner_reminder(
        lead=lead,
        business=seeded_business,
        threshold_minutes=15,
        age_minutes=16.0,
        idempotency_key="reminder-skip",
    )

    assert ack_result.skipped is True
    assert owner_result.skipped is True
    assert reminder_result.skipped is True

    skip_events = (
        db_session.query(LeadEvent)
        .filter(
            LeadEvent.lead_id == lead.id,
            LeadEvent.event_type == "notification_dispatch_skipped",
        )
        .all()
    )
    kinds = [event.payload_json.get("notification_kind") for event in skip_events]
    assert "customer_ack" in kinds
    assert "contractor_alert" in kinds
    assert "owner_reminder" in kinds


def test_no_valid_targets_is_skipped_not_failed(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = True
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = None
    seeded_business.notification_email = None
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email="customer@example.com", phone="+13035550111")
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=RecordingEmailProvider(),
        sms_provider=RecordingSMSProvider(),
    )

    result = service.send_owner_notification(lead=lead, business=seeded_business)

    assert result.requested is True
    assert result.attempted is False
    assert result.sent is False
    assert result.skipped is True
    assert result.detail == "No valid enabled notification target found."

    event_types = [
        event.event_type
        for event in db_session.query(LeadEvent).filter(LeadEvent.lead_id == lead.id).all()
    ]
    assert "notification_dispatch_requested" in event_types
    assert "notification_dispatch_skipped" in event_types
    assert "notification_dispatch_failed" not in event_types


def test_contractor_sms_supports_global_e164_number(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = False
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = "+44 20 7123 4567"
    seeded_business.notification_email = None
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email="lead@example.com", phone="+13035550000")
    sms = RecordingSMSProvider()
    email = RecordingEmailProvider()
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=email,
        sms_provider=sms,
    )

    result = service.send_owner_notification(lead=lead, business=seeded_business)

    assert result.sent is True
    assert result.channel == "sms"
    assert len(sms.calls) == 1
    assert sms.calls[0][0] == "+442071234567"
    assert len(email.calls) == 0


def test_scope_mismatch_skips_dispatch_and_records_event(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = True
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = "+13035550122"
    seeded_business.notification_email = "owner@tmfire.example"
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email=None, phone="+13035550111")
    other_business = Business(
        id=str(uuid4()),
        name="Other Contractor",
        notification_phone="+13035550999",
        notification_email="other@example.com",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    sms = RecordingSMSProvider()
    email = RecordingEmailProvider()
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=email,
        sms_provider=sms,
    )

    result = service.send_owner_notification(
        lead=lead,
        business=other_business,
        idempotency_key="scope-mismatch",
    )

    assert result.skipped is True
    assert result.sent is False
    assert result.attempted is False
    assert len(sms.calls) == 0
    assert len(email.calls) == 0

    skip_events = (
        db_session.query(LeadEvent)
        .filter(
            LeadEvent.lead_id == lead.id,
            LeadEvent.event_type == "notification_dispatch_skipped",
        )
        .all()
    )
    assert any(
        event.payload_json.get("reason") == "Lead does not belong to the supplied business context."
        and event.payload_json.get("lead_business_id") == lead.business_id
        and event.payload_json.get("business_id") == other_business.id
        for event in skip_events
    )


def test_duplicate_idempotency_key_suppresses_second_send(db_session, seeded_business) -> None:
    seeded_business.sms_enabled = True
    seeded_business.email_enabled = False
    seeded_business.contractor_alerts_enabled = True
    seeded_business.notification_phone = "+13035550122"
    seeded_business.notification_email = None
    db_session.commit()

    lead = _seed_lead(db_session, seeded_business.id, email="lead@example.com", phone="+13035550111")
    sms = RecordingSMSProvider()
    email = RecordingEmailProvider()
    service = NotificationDispatchService(
        lead_repository=LeadRepository(db_session),
        email_provider=email,
        sms_provider=sms,
    )

    first = service.send_owner_notification(
        lead=lead,
        business=seeded_business,
        idempotency_key="owner-alert:dedupe-1",
    )
    second = service.send_owner_notification(
        lead=lead,
        business=seeded_business,
        idempotency_key="owner-alert:dedupe-1",
    )

    assert first.sent is True
    assert first.skipped is False
    assert second.sent is False
    assert second.skipped is True
    assert second.detail == "Dispatch skipped due to duplicate idempotency key."
    assert len(sms.calls) == 1
    assert len(email.calls) == 0

    skip_events = (
        db_session.query(LeadEvent)
        .filter(
            LeadEvent.lead_id == lead.id,
            LeadEvent.event_type == "notification_dispatch_skipped",
        )
        .all()
    )
    assert any(
        event.payload_json.get("notification_kind") == "contractor_alert"
        and event.payload_json.get("idempotency_key") == "owner-alert:dedupe-1"
        and event.payload_json.get("reason") == "Duplicate idempotency key detected."
        for event in skip_events
    )

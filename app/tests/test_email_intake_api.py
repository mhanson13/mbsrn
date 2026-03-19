from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import TenantContext, get_db, get_notification_service, get_tenant_context
from app.api.routes.intake import router as intake_router
from app.core.time import utc_now
from app.integrations.email_provider import EmailDispatchResult
from app.integrations.sms_provider import SMSDispatchResult
from app.models.lead import LeadSource
from app.models.lead_event import LeadEvent
from app.repositories.lead_repository import LeadRepository
from app.services.notifications import NotificationDispatchService


class _FailingEmailProvider:
    def send_email(self, *, to_address: str, subject: str, body: str) -> EmailDispatchResult:
        _ = to_address, subject, body
        raise RuntimeError("email down")


class _FailingSMSProvider:
    def send_sms(self, *, to_number: str, body: str) -> SMSDispatchResult:
        _ = to_number, body
        raise RuntimeError("sms down")


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id="test-principal",
            auth_source="test",
        )

    return _resolver


def test_email_intake_endpoint_success(db_session, seeded_business) -> None:
    app = FastAPI()
    app.include_router(intake_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(seeded_business.id)
    client = TestClient(app)

    response = client.post(
        "/api/intake/email",
        json={
            "business_id": seeded_business.id,
            "source_ref": "godaddy-msg-1001",
            "received_at": utc_now().isoformat(),
            "from_address": "noreply@notifications.godaddy.com",
            "subject": "New lead from Taylor Reed",
            "body_text": (
                "Name: Taylor Reed\n"
                "Phone: 303-555-0133\n"
                "Email: taylor@example.com\n"
                "Service: Fire Restoration\n"
                "City: Denver\n"
                "Message: Need emergency cleanup tonight."
            ),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["duplicate"] is False
    assert payload["parse_status"] == "parsed"
    assert payload["lead"]["source"] == LeadSource.GODADDY_EMAIL.value
    assert payload["lead"]["customer_acknowledged_at"] is not None
    assert payload["lead"]["owner_notified_at"] is not None

    assert set(payload["events_recorded"]) == {
        "email_received",
        "lead_parsed",
        "lead_created",
        "customer_ack_triggered",
        "contractor_notification_triggered",
    }


def test_email_intake_endpoint_records_parsing_failed_event(db_session, seeded_business) -> None:
    app = FastAPI()
    app.include_router(intake_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(seeded_business.id)
    client = TestClient(app)

    response = client.post(
        "/api/intake/email",
        json={
            "business_id": seeded_business.id,
            "source_ref": "godaddy-msg-1002",
            "received_at": utc_now().isoformat(),
            "subject": "Website message",
            "body_text": "Hello there. Please call me soon.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["parse_status"] == "failed"
    assert payload["duplicate"] is False
    assert "parsing_failed" in payload["events_recorded"]
    assert payload["lead"]["customer_acknowledged_at"] is None

    event_types = list(
        db_session.scalars(select(LeadEvent.event_type).where(LeadEvent.lead_id == payload["lead"]["id"]))
    )
    assert "email_received" in event_types
    assert "parsing_failed" in event_types


def test_email_intake_persists_lead_when_notification_delivery_fails(db_session, seeded_business) -> None:
    app = FastAPI()
    app.include_router(intake_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_notification_service():
        return NotificationDispatchService(
            lead_repository=LeadRepository(db_session),
            email_provider=_FailingEmailProvider(),
            sms_provider=_FailingSMSProvider(),
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_notification_service] = override_notification_service
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(seeded_business.id)
    client = TestClient(app)

    response = client.post(
        "/api/intake/email",
        json={
            "business_id": seeded_business.id,
            "source_ref": "godaddy-msg-failure",
            "received_at": utc_now().isoformat(),
            "subject": "New lead from Alex",
            "normalized_fields": {
                "customer_name": "Alex",
                "phone": "+13035550999",
                "email": "alex@example.com",
                "service_type": "Board up",
                "city": "Denver",
                "message": "Need immediate help",
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["lead"]["id"] is not None
    assert payload["lead"]["customer_acknowledged_at"] is None
    assert payload["lead"]["owner_notified_at"] is None

    event_types = list(
        db_session.scalars(select(LeadEvent.event_type).where(LeadEvent.lead_id == payload["lead"]["id"]))
    )
    assert "notification_dispatch_failed" in event_types

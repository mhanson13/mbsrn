from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.jobs import router as jobs_router
from app.core.time import utc_now
from app.integrations import MockEmailProvider, MockSMSProvider
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_event import ActorType, LeadEvent, LeadEventType
from app.repositories.business_repository import BusinessRepository
from app.repositories.lead_repository import LeadRepository
from app.services.notifications import NotificationService
from app.services.reminder_engine import ReminderEngineService


def _seed_reminder_leads(db_session, business_id: str) -> tuple[str, str, str]:
    now = utc_now()
    lead_16m = Lead(
        id=str(uuid4()),
        business_id=business_id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=now - timedelta(minutes=16),
        customer_name="Lead 16m",
        phone="3035550201",
        status=LeadStatus.NEW,
    )
    lead_130m = Lead(
        id=str(uuid4()),
        business_id=business_id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=now - timedelta(minutes=130),
        customer_name="Lead 130m",
        phone="3035550202",
        status=LeadStatus.NEW,
    )
    lead_5m = Lead(
        id=str(uuid4()),
        business_id=business_id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=now - timedelta(minutes=5),
        customer_name="Lead 5m",
        phone="3035550203",
        status=LeadStatus.NEW,
    )
    db_session.add_all([lead_16m, lead_130m, lead_5m])
    db_session.commit()
    return lead_16m.id, lead_130m.id, lead_5m.id


def test_reminder_engine_eligibility_and_duplicate_suppression(db_session, seeded_business) -> None:
    lead_16m_id, lead_130m_id, _ = _seed_reminder_leads(db_session, seeded_business.id)

    notification_service = NotificationService(
        lead_repository=LeadRepository(db_session),
        email_provider=MockEmailProvider(),
        sms_provider=MockSMSProvider(),
    )
    engine = ReminderEngineService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        lead_repository=LeadRepository(db_session),
        notification_service=notification_service,
    )

    first_run = engine.run_for_business(business_id=seeded_business.id)
    assert first_run.scanned_leads == 3
    assert first_run.reminder_15m_sent == 2
    assert first_run.reminder_2h_sent == 1
    assert first_run.reminders_sent == 3

    event_rows = list(
        db_session.execute(select(LeadEvent.lead_id, LeadEvent.event_type, LeadEvent.business_id)).all()
    )
    lead_16m_events = [event_type for lead_id, event_type, _ in event_rows if lead_id == lead_16m_id]
    lead_130m_events = [event_type for lead_id, event_type, _ in event_rows if lead_id == lead_130m_id]

    assert "reminder_15m_triggered" in lead_16m_events
    assert "reminder_15m_triggered" in lead_130m_events
    assert "reminder_2h_triggered" in lead_130m_events
    assert "notification_dispatch_sent" in lead_16m_events
    assert "notification_dispatch_sent" in lead_130m_events
    assert all(business_id == seeded_business.id for _, _, business_id in event_rows)

    second_run = engine.run_for_business(business_id=seeded_business.id)
    assert second_run.reminders_sent == 0
    assert second_run.reminder_15m_sent == 0
    assert second_run.reminder_2h_sent == 0


def test_manual_reminder_run_endpoint(db_session, seeded_business) -> None:
    _seed_reminder_leads(db_session, seeded_business.id)

    app = FastAPI()
    app.include_router(jobs_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_tenant_context() -> TenantContext:
        return TenantContext(
            business_id=seeded_business.id,
            principal_id="test-principal",
            auth_source="test",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    client = TestClient(app)

    response = client.post(
        "/api/jobs/lead-reminders/run",
        json={"business_id": seeded_business.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["business_id"] == seeded_business.id
    assert payload["scanned_leads"] == 3
    assert payload["reminders_sent"] >= 1


def test_reminder_event_lookup_is_business_scoped(db_session, seeded_business) -> None:
    lead_16m_id, _, _ = _seed_reminder_leads(db_session, seeded_business.id)
    target_lead = db_session.get(Lead, lead_16m_id)
    assert target_lead is not None

    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550199",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.flush()

    # Simulate bad/corrupted cross-tenant event row for same lead_id.
    db_session.add(
        LeadEvent(
            id=str(uuid4()),
            business_id=other_business.id,
            lead_id=lead_16m_id,
            event_type=LeadEventType.REMINDER_15M_TRIGGERED.value,
            actor_type=ActorType.SYSTEM,
            payload_json={"threshold_minutes": 15},
        )
    )
    db_session.commit()

    notification_service = NotificationService(
        lead_repository=LeadRepository(db_session),
        email_provider=MockEmailProvider(),
        sms_provider=MockSMSProvider(),
    )
    engine = ReminderEngineService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        lead_repository=LeadRepository(db_session),
        notification_service=notification_service,
    )

    result = engine.run_for_business(business_id=seeded_business.id)

    # If lookup were not business-scoped, lead_16m reminder would be suppressed incorrectly.
    assert result.reminder_15m_sent >= 1
    assert any(action.lead_id == lead_16m_id for action in result.actions)


def test_reminder_engine_fails_fast_on_business_scope_mismatch(db_session, seeded_business) -> None:
    now = utc_now()
    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550199",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.flush()

    out_of_scope_lead = Lead(
        id=str(uuid4()),
        business_id=other_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=now - timedelta(minutes=30),
        customer_name="Wrong Tenant Lead",
        phone="3035550299",
        status=LeadStatus.NEW,
    )
    db_session.add(out_of_scope_lead)
    db_session.commit()

    notification_service = NotificationService(
        lead_repository=LeadRepository(db_session),
        email_provider=MockEmailProvider(),
        sms_provider=MockSMSProvider(),
    )
    engine = ReminderEngineService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        lead_repository=LeadRepository(db_session),
        notification_service=notification_service,
    )

    engine.lead_repository.list_awaiting_first_response = lambda _business_id: [out_of_scope_lead]

    with pytest.raises(ValueError, match="Lead/business scope mismatch in reminder engine"):
        engine.run_for_business(business_id=seeded_business.id)

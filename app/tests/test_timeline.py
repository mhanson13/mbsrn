from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.leads import router as leads_router
from app.core.time import utc_now
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_event import ActorType, LeadEvent, LeadEventType


def test_timeline_endpoint_returns_events_chronologically(db_session, seeded_business) -> None:
    submitted_at = utc_now() - timedelta(hours=1)
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

    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=submitted_at,
        customer_name="Timeline Lead",
        phone="3035550222",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.flush()

    db_session.add_all(
        [
            LeadEvent(
                id=str(uuid4()),
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.STATUS_CHANGED.value,
                event_timestamp=submitted_at + timedelta(minutes=20),
                actor_type=ActorType.OWNER,
                payload_json={"from": "new", "to": "contacted"},
            ),
            LeadEvent(
                id=str(uuid4()),
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.LEAD_CREATED.value,
                event_timestamp=submitted_at + timedelta(minutes=1),
                actor_type=ActorType.SYSTEM,
                payload_json={},
            ),
            LeadEvent(
                id=str(uuid4()),
                business_id=other_business.id,
                lead_id=lead.id,
                event_type=LeadEventType.NOTE.value,
                event_timestamp=submitted_at + timedelta(minutes=5),
                actor_type=ActorType.SYSTEM,
                payload_json={"note": "cross-tenant event should not appear"},
            ),
            LeadEvent(
                id=str(uuid4()),
                business_id=lead.business_id,
                lead_id=lead.id,
                event_type=LeadEventType.NOTE.value,
                event_timestamp=submitted_at + timedelta(minutes=10),
                actor_type=ActorType.OWNER,
                payload_json={"note": "left voicemail"},
            ),
        ]
    )
    db_session.commit()

    app = FastAPI()
    app.include_router(leads_router)

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

    response = client.get(f"/api/leads/{lead.id}/timeline?business_id={seeded_business.id}")

    assert response.status_code == 200
    payload = response.json()
    event_types = [event["event_type"] for event in payload["events"]]
    assert event_types == ["lead_created", "note", "status_changed"]

    wrong_scope_response = client.get(f"/api/leads/{lead.id}/timeline?business_id={other_business.id}")
    assert wrong_scope_response.status_code == 404

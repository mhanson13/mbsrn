from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.routes.leads import router as leads_router
from app.core.time import utc_now
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus


def test_get_lead_requires_same_business_scope(db_session, seeded_business) -> None:
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
        submitted_at=utc_now() - timedelta(minutes=10),
        customer_name="Scoped Lead",
        phone="3035550123",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    same_scope = client.get(f"/api/leads/{lead.id}", params={"business_id": seeded_business.id})
    assert same_scope.status_code == 200
    assert same_scope.json()["id"] == lead.id
    assert same_scope.json()["business_id"] == seeded_business.id

    wrong_scope = client.get(f"/api/leads/{lead.id}", params={"business_id": other_business.id})
    assert wrong_scope.status_code == 404

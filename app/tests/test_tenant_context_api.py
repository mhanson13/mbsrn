from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.intake import router as intake_router
from app.api.routes.leads import router as leads_router
from app.core.time import utc_now
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(business_id=business_id, auth_source="test")

    return _resolver


def test_same_tenant_lead_fetch_succeeds_and_cross_tenant_fetch_is_blocked(db_session, seeded_business) -> None:
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

    lead_a = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=15),
        customer_name="Tenant A Lead",
        phone="3035550101",
        status=LeadStatus.NEW,
    )
    lead_b = Lead(
        id=str(uuid4()),
        business_id=other_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=10),
        customer_name="Tenant B Lead",
        phone="3035550102",
        status=LeadStatus.NEW,
    )
    db_session.add_all([lead_a, lead_b])
    db_session.commit()

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(seeded_business.id)
    client = TestClient(app)

    same_tenant = client.get(f"/api/leads/{lead_a.id}")
    assert same_tenant.status_code == 200
    assert same_tenant.json()["business_id"] == seeded_business.id

    # Malicious caller tries to force business scope via query param.
    spoofed = client.get(f"/api/leads/{lead_b.id}", params={"business_id": other_business.id})
    assert spoofed.status_code == 404


def test_cross_tenant_status_mutation_spoof_is_blocked(db_session, seeded_business) -> None:
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

    lead_b = Lead(
        id=str(uuid4()),
        business_id=other_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=12),
        customer_name="Tenant B Lead",
        phone="3035550102",
        status=LeadStatus.NEW,
    )
    db_session.add(lead_b)
    db_session.commit()

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(seeded_business.id)
    client = TestClient(app)

    spoofed_patch = client.patch(
        f"/api/leads/{lead_b.id}/status",
        params={"business_id": other_business.id},
        json={"status": "contacted"},
    )
    assert spoofed_patch.status_code == 404

    db_session.refresh(lead_b)
    assert lead_b.status == LeadStatus.NEW


def test_manual_intake_body_business_id_spoof_is_rejected(db_session, seeded_business) -> None:
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
    db_session.commit()

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
        "/api/intake/manual",
        json={
            "business_id": other_business.id,
            "submitted_at": utc_now().isoformat(),
            "customer_name": "Spoof Attempt",
            "phone": "3035550109",
        },
    )
    assert response.status_code == 404

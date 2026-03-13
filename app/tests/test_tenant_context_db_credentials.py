from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.routes.leads import router as leads_router
from app.core.config import get_settings
from app.core.time import utc_now
from app.models.api_credential import APICredential
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.repositories.api_credential_repository import hash_bearer_token


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_env_defaults(monkeypatch: pytest.MonkeyPatch, *, default_business_id: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("API_AUTH_BUSINESS_ID", raising=False)
    monkeypatch.delenv("API_AUTH_PRINCIPALS_JSON", raising=False)


def _make_client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_db_credential_resolves_principal_and_tenant_scope(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        submitted_at=utc_now() - timedelta(minutes=8),
        customer_name="Tenant A Lead",
        phone="3035550101",
        status=LeadStatus.NEW,
    )
    lead_b = Lead(
        id=str(uuid4()),
        business_id=other_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=7),
        customer_name="Tenant B Lead",
        phone="3035550102",
        status=LeadStatus.NEW,
    )
    db_session.add_all([lead_a, lead_b])

    db_session.add(
        APICredential(
            id=str(uuid4()),
            business_id=seeded_business.id,
            principal_id="user-a",
            token_hash=hash_bearer_token("db-tenant-a-token"),
            is_active=True,
            revoked_at=None,
        )
    )
    db_session.commit()

    _set_env_defaults(monkeypatch, default_business_id=other_business.id)
    client = _make_client(db_session)
    headers = {"Authorization": "Bearer db-tenant-a-token"}

    same_tenant = client.get(f"/api/leads/{lead_a.id}", headers=headers)
    assert same_tenant.status_code == 200
    assert same_tenant.json()["business_id"] == seeded_business.id

    spoofed_cross_tenant = client.get(
        f"/api/leads/{lead_b.id}",
        params={"business_id": other_business.id},
        headers=headers,
    )
    assert spoofed_cross_tenant.status_code == 404


def test_inactive_db_credential_is_rejected(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(
        APICredential(
            id=str(uuid4()),
            business_id=seeded_business.id,
            principal_id="user-a",
            token_hash=hash_bearer_token("inactive-token"),
            is_active=False,
            revoked_at=None,
        )
    )
    db_session.commit()

    _set_env_defaults(monkeypatch, default_business_id=seeded_business.id)
    client = _make_client(db_session)
    response = client.get("/api/leads", headers={"Authorization": "Bearer inactive-token"})
    assert response.status_code == 401


def test_revoked_db_credential_is_rejected(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(
        APICredential(
            id=str(uuid4()),
            business_id=seeded_business.id,
            principal_id="user-a",
            token_hash=hash_bearer_token("revoked-token"),
            is_active=True,
            revoked_at=utc_now(),
        )
    )
    db_session.commit()

    _set_env_defaults(monkeypatch, default_business_id=seeded_business.id)
    client = _make_client(db_session)
    response = client.get("/api/leads", headers={"Authorization": "Bearer revoked-token"})
    assert response.status_code == 401


def test_db_credential_lookup_has_priority_over_env_principal_mapping(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        submitted_at=utc_now() - timedelta(minutes=8),
        customer_name="Tenant A Lead",
        phone="3035550101",
        status=LeadStatus.NEW,
    )
    lead_b = Lead(
        id=str(uuid4()),
        business_id=other_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=7),
        customer_name="Tenant B Lead",
        phone="3035550102",
        status=LeadStatus.NEW,
    )
    db_session.add_all([lead_a, lead_b])
    db_session.add(
        APICredential(
            id=str(uuid4()),
            business_id=seeded_business.id,
            principal_id="db-user-a",
            token_hash=hash_bearer_token("shared-token"),
            is_active=True,
            revoked_at=None,
        )
    )
    db_session.commit()

    _set_env_defaults(monkeypatch, default_business_id=other_business.id)
    monkeypatch.setenv(
        "API_AUTH_PRINCIPALS_JSON",
        json.dumps(
            [
                {
                    "token": "shared-token",
                    "principal_id": "env-user-b",
                    "business_id": other_business.id,
                }
            ]
        ),
    )

    client = _make_client(db_session)
    headers = {"Authorization": "Bearer shared-token"}

    same_tenant = client.get(f"/api/leads/{lead_a.id}", headers=headers)
    assert same_tenant.status_code == 200
    assert same_tenant.json()["business_id"] == seeded_business.id

    cross_tenant = client.get(f"/api/leads/{lead_b.id}", headers=headers)
    assert cross_tenant.status_code == 404

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.businesses import router as businesses_router
from app.api.routes.leads import router as leads_router
from app.core.config import get_settings
from app.core.time import utc_now
from app.models.api_credential import APICredential
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.principal import Principal
from app.repositories.api_credential_repository import hash_bearer_token

PROD_PEPPER = "prod-pepper"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_production_auth_defaults(monkeypatch: pytest.MonkeyPatch, *, default_business_id: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)
    monkeypatch.setenv("ALLOW_AUTH_COMPAT_FALLBACK", "false")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", PROD_PEPPER)
    monkeypatch.setenv("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", "false")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("API_AUTH_BUSINESS_ID", raising=False)
    monkeypatch.delenv("API_AUTH_PRINCIPALS_JSON", raising=False)


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-admin:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_management_client(db_session, *, business_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(businesses_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    return TestClient(app)


def _make_leads_client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed_lead(db_session, *, business_id: str) -> Lead:
    lead = Lead(
        id=str(uuid4()),
        business_id=business_id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=6),
        customer_name="Credential Lifecycle Lead",
        phone="3035550107",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


def test_create_credential_returns_token_and_authenticates(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    lead = _seed_lead(db_session, business_id=seeded_business.id)
    management_client = _make_management_client(db_session, business_id=seeded_business.id)

    create_response = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        json={"principal_id": "owner-user-1"},
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    token = create_payload["token"]
    credential_payload = create_payload["credential"]

    assert token
    assert credential_payload["business_id"] == seeded_business.id
    assert credential_payload["principal_id"] == "owner-user-1"
    assert credential_payload["principal_display_name"] == "owner-user-1"
    assert credential_payload["is_active"] is True
    assert "token_hash" not in create_payload
    assert "token_hash" not in credential_payload

    stored_credential = db_session.get(APICredential, credential_payload["id"])
    assert stored_credential is not None
    assert stored_credential.token_hash == hash_bearer_token(token, pepper=PROD_PEPPER)
    stored_principal = db_session.get(Principal, (seeded_business.id, "owner-user-1"))
    assert stored_principal is not None
    assert stored_principal.display_name == "owner-user-1"

    leads_client = _make_leads_client(db_session)
    auth_response = leads_client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_response.status_code == 200
    assert auth_response.json()["business_id"] == seeded_business.id


def test_disabled_credential_is_rejected_for_auth(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    lead = _seed_lead(db_session, business_id=seeded_business.id)
    management_client = _make_management_client(db_session, business_id=seeded_business.id)

    issued = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        json={"principal_id": "owner-user-2"},
    ).json()
    credential_id = issued["credential"]["id"]
    token = issued["token"]

    disable_response = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials/{credential_id}/disable",
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["is_active"] is False
    assert disable_response.json()["revoked_at"] is None

    leads_client = _make_leads_client(db_session)
    auth_response = leads_client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_response.status_code == 401


def test_revoked_credential_is_rejected_for_auth(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    lead = _seed_lead(db_session, business_id=seeded_business.id)
    management_client = _make_management_client(db_session, business_id=seeded_business.id)

    issued = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        json={"principal_id": "owner-user-3"},
    ).json()
    credential_id = issued["credential"]["id"]
    token = issued["token"]

    revoke_response = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials/{credential_id}/revoke",
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["is_active"] is False
    assert revoke_response.json()["revoked_at"] is not None

    leads_client = _make_leads_client(db_session)
    auth_response = leads_client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_response.status_code == 401


def test_rotate_credential_replaces_old_token_and_keeps_tenant_scope(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    lead = _seed_lead(db_session, business_id=seeded_business.id)
    management_client = _make_management_client(db_session, business_id=seeded_business.id)

    issued = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        json={"principal_id": "owner-user-4"},
    ).json()
    old_credential_id = issued["credential"]["id"]
    old_token = issued["token"]

    rotate_response = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials/{old_credential_id}/rotate",
    )
    assert rotate_response.status_code == 201
    rotate_payload = rotate_response.json()
    new_credential_id = rotate_payload["credential"]["id"]
    new_token = rotate_payload["token"]

    assert rotate_payload["replaced_credential_id"] == old_credential_id
    assert new_credential_id != old_credential_id
    assert new_token != old_token

    old_credential = db_session.get(APICredential, old_credential_id)
    new_credential = db_session.get(APICredential, new_credential_id)
    assert old_credential is not None and old_credential.is_active is False
    assert old_credential.revoked_at is not None
    assert new_credential is not None and new_credential.is_active is True
    assert new_credential.revoked_at is None

    leads_client = _make_leads_client(db_session)
    old_auth_response = leads_client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert old_auth_response.status_code == 401

    new_auth_response = leads_client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert new_auth_response.status_code == 200
    assert new_auth_response.json()["business_id"] == seeded_business.id


def test_cross_tenant_credential_management_is_blocked(
    db_session,
    seeded_business,
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
    db_session.commit()

    management_client = _make_management_client(db_session, business_id=seeded_business.id)
    response = management_client.post(
        f"/api/businesses/{other_business.id}/credentials",
        json={"principal_id": "malicious-user"},
    )
    assert response.status_code == 404


def test_create_credential_can_set_principal_display_name(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    management_client = _make_management_client(db_session, business_id=seeded_business.id)

    create_response = management_client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        json={
            "principal_id": "owner-user-5",
            "principal_display_name": "Owner Operator",
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["credential"]["principal_display_name"] == "Owner Operator"

    stored_principal = db_session.get(Principal, (seeded_business.id, "owner-user-5"))
    assert stored_principal is not None
    assert stored_principal.display_name == "Owner Operator"

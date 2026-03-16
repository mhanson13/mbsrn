from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.routes.businesses import router as businesses_router
from app.core.config import get_settings
from app.models.api_credential import APICredential
from app.models.business import Business
from app.models.principal import Principal, PrincipalRole
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
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", PROD_PEPPER)
    monkeypatch.setenv("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", "false")
    monkeypatch.delenv("GOOGLE_AUTH_ENABLED", raising=False)


def _make_client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(businesses_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed_credential(
    db_session,
    *,
    business_id: str,
    principal_id: str,
    role: PrincipalRole,
) -> str:
    principal = db_session.get(Principal, (business_id, principal_id))
    if principal is None:
        principal = Principal(
            business_id=business_id,
            id=principal_id,
            display_name=principal_id,
            role=role,
            is_active=True,
        )
        db_session.add(principal)
    else:
        principal.role = role
        principal.is_active = True

    token = f"token-{principal_id}-{uuid4()}"
    db_session.add(
        APICredential(
            id=str(uuid4()),
            business_id=business_id,
            principal_id=principal_id,
            token_hash=hash_bearer_token(token, pepper=PROD_PEPPER),
            is_active=True,
            revoked_at=None,
        )
    )
    db_session.commit()
    return token


def test_admin_can_manage_principal_identities(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="identity-admin",
        role=PrincipalRole.ADMIN,
    )
    db_session.add(
        Principal(
            business_id=seeded_business.id,
            id="mapped-operator",
            display_name="Mapped Operator",
            role=PrincipalRole.OPERATOR,
            is_active=True,
        )
    )
    db_session.commit()

    client = _make_client(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/principal-identities",
        headers=headers,
        json={
            "provider": "google",
            "provider_subject": "google-sub-123",
            "principal_id": "mapped-operator",
            "email": "Operator@Example.com",
            "email_verified": True,
            "is_active": True,
        },
    )
    assert create_response.status_code == 201
    identity_payload = create_response.json()
    assert identity_payload["provider"] == "google"
    assert identity_payload["provider_subject"] == "google-sub-123"
    assert identity_payload["principal_id"] == "mapped-operator"
    assert identity_payload["email"] == "operator@example.com"
    assert identity_payload["is_active"] is True
    identity_id = identity_payload["id"]

    list_response = client.get(
        f"/api/businesses/{seeded_business.id}/principal-identities",
        headers=headers,
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] >= 1
    listed = next(item for item in list_payload["items"] if item["id"] == identity_id)
    assert listed["provider"] == "google"

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principal-identities/{identity_id}/deactivate",
        headers=headers,
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False

    activate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principal-identities/{identity_id}/activate",
        headers=headers,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True


def test_operator_cannot_manage_principal_identities(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    operator_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="identity-operator",
        role=PrincipalRole.OPERATOR,
    )
    client = _make_client(db_session)
    response = client.get(
        f"/api/businesses/{seeded_business.id}/principal-identities",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 403


def test_cross_tenant_principal_identity_access_is_blocked(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="identity-admin-2",
        role=PrincipalRole.ADMIN,
    )
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

    client = _make_client(db_session)
    response = client.get(
        f"/api/businesses/{other_business.id}/principal-identities",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.routes.businesses import router as businesses_router
from app.api.routes.leads import router as leads_router
from app.core.config import get_settings
from app.core.time import utc_now
from app.models.api_credential import APICredential
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
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


def _make_client(db_session, *, include_leads: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(businesses_router)
    if include_leads:
        app.include_router(leads_router)

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
    is_active: bool = True,
) -> str:
    principal = db_session.get(Principal, (business_id, principal_id))
    if principal is None:
        principal = Principal(
            business_id=business_id,
            id=principal_id,
            display_name=principal_id,
            role=role,
            is_active=is_active,
        )
        db_session.add(principal)
    else:
        principal.role = role
        principal.is_active = is_active

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


def test_admin_can_manage_principals_lifecycle(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-owner",
        role=PrincipalRole.ADMIN,
    )
    client = _make_client(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals",
        headers=headers,
        json={
            "principal_id": "crew-lead-1",
            "display_name": "Crew Lead",
            "role": "operator",
        },
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    assert create_payload["display_name"] == "Crew Lead"
    assert create_payload["role"] == "operator"
    assert create_payload["is_active"] is True
    assert create_payload["created_by_principal_id"] == "admin-owner"
    assert create_payload["updated_by_principal_id"] == "admin-owner"
    assert create_payload["last_authenticated_at"] is None

    update_response = client.patch(
        f"/api/businesses/{seeded_business.id}/principals/crew-lead-1",
        headers=headers,
        json={"display_name": "Crew Captain", "role": "admin"},
    )
    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["display_name"] == "Crew Captain"
    assert update_payload["role"] == "admin"
    assert update_payload["created_by_principal_id"] == "admin-owner"
    assert update_payload["updated_by_principal_id"] == "admin-owner"

    list_response = client.get(
        f"/api/businesses/{seeded_business.id}/principals",
        headers=headers,
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    principal_ids = {item["id"] for item in payload["items"]}
    assert "admin-owner" in principal_ids
    assert "crew-lead-1" in principal_ids
    managed_principal = next(item for item in payload["items"] if item["id"] == "crew-lead-1")
    assert managed_principal["created_by_principal_id"] == "admin-owner"
    assert managed_principal["updated_by_principal_id"] == "admin-owner"
    assert "last_authenticated_at" in managed_principal

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals/crew-lead-1/deactivate",
        headers=headers,
    )
    assert deactivate_response.status_code == 200
    deactivate_payload = deactivate_response.json()
    assert deactivate_payload["is_active"] is False
    assert deactivate_payload["updated_by_principal_id"] == "admin-owner"

    activate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals/crew-lead-1/activate",
        headers=headers,
    )
    assert activate_response.status_code == 200
    activate_payload = activate_response.json()
    assert activate_payload["is_active"] is True
    assert activate_payload["updated_by_principal_id"] == "admin-owner"


def test_operator_cannot_manage_principals(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    operator_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-user",
        role=PrincipalRole.OPERATOR,
    )
    client = _make_client(db_session)

    response = client.get(
        f"/api/businesses/{seeded_business.id}/principals",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 403


def test_inactive_principal_cannot_authenticate_even_with_active_credential(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=8),
        customer_name="Auth Check Lead",
        phone="3035550101",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()

    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-owner-2",
        role=PrincipalRole.ADMIN,
    )
    operator_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-user-2",
        role=PrincipalRole.OPERATOR,
    )

    client = _make_client(db_session, include_leads=True)
    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals/operator-user-2/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False

    auth_response = client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert auth_response.status_code == 401


def test_successful_auth_updates_principal_last_authenticated_at(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=5),
        customer_name="Auth Metadata Lead",
        phone="3035550102",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()

    operator_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-user-usage",
        role=PrincipalRole.OPERATOR,
    )
    principal_before = db_session.get(Principal, (seeded_business.id, "operator-user-usage"))
    assert principal_before is not None
    assert principal_before.last_authenticated_at is None

    client = _make_client(db_session, include_leads=True)
    auth_response = client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert auth_response.status_code == 200

    db_session.expire_all()
    principal_after = db_session.get(Principal, (seeded_business.id, "operator-user-usage"))
    assert principal_after is not None
    assert principal_after.last_authenticated_at is not None


def test_cross_tenant_principal_management_is_blocked(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-owner-3",
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
        f"/api/businesses/{other_business.id}/principals",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


def test_cannot_deactivate_last_active_admin_principal(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="sole-admin",
        role=PrincipalRole.ADMIN,
    )
    client = _make_client(db_session)

    response = client.post(
        f"/api/businesses/{seeded_business.id}/principals/sole-admin/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    assert "last active admin" in response.json()["detail"]

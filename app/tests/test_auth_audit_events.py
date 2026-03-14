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


def _contains_sensitive_keys(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"token", "token_hash"}:
                return True
            if _contains_sensitive_keys(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_keys(item) for item in value)
    return False


def test_principal_admin_actions_create_audit_events(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-audit-user",
        role=PrincipalRole.ADMIN,
    )
    client = _make_client(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals",
        headers=headers,
        json={"principal_id": "crew-audit-1", "display_name": "Crew Audit One", "role": "operator"},
    )
    assert create_response.status_code == 201

    update_response = client.patch(
        f"/api/businesses/{seeded_business.id}/principals/crew-audit-1",
        headers=headers,
        json={"display_name": "Crew Audit Captain", "role": "admin"},
    )
    assert update_response.status_code == 200

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals/crew-audit-1/deactivate",
        headers=headers,
    )
    assert deactivate_response.status_code == 200

    activate_response = client.post(
        f"/api/businesses/{seeded_business.id}/principals/crew-audit-1/activate",
        headers=headers,
    )
    assert activate_response.status_code == 200

    audit_response = client.get(
        f"/api/businesses/{seeded_business.id}/auth-audit-events",
        headers=headers,
        params={"target_type": "principal", "limit": 50},
    )
    assert audit_response.status_code == 200
    payload = audit_response.json()
    principal_events = [item for item in payload["items"] if item["target_id"] == "crew-audit-1"]
    event_types = {event["event_type"] for event in principal_events}
    assert "principal_created" in event_types
    assert "principal_updated" in event_types
    assert "principal_deactivated" in event_types
    assert "principal_activated" in event_types
    for event in principal_events:
        assert event["business_id"] == seeded_business.id
        assert event["actor_principal_id"] == "admin-audit-user"
        assert event["target_type"] == "principal"
        assert _contains_sensitive_keys(event["details_json"]) is False


def test_credential_admin_actions_create_audit_events_without_secrets(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    admin_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-credential-audit",
        role=PrincipalRole.ADMIN,
    )
    client = _make_client(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    created_one = client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        headers=headers,
        json={"principal_id": "owner-audit-1", "credential_label": "Owner Audit One"},
    )
    assert created_one.status_code == 201
    credential_id_one = created_one.json()["credential"]["id"]

    disabled = client.post(
        f"/api/businesses/{seeded_business.id}/credentials/{credential_id_one}/disable",
        headers=headers,
    )
    assert disabled.status_code == 200

    created_two = client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        headers=headers,
        json={"principal_id": "owner-audit-2"},
    )
    assert created_two.status_code == 201
    credential_id_two = created_two.json()["credential"]["id"]

    revoked = client.post(
        f"/api/businesses/{seeded_business.id}/credentials/{credential_id_two}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200

    created_three = client.post(
        f"/api/businesses/{seeded_business.id}/credentials",
        headers=headers,
        json={"principal_id": "owner-audit-3", "credential_label": "Rotate Me"},
    )
    assert created_three.status_code == 201
    credential_id_three = created_three.json()["credential"]["id"]

    rotated = client.post(
        f"/api/businesses/{seeded_business.id}/credentials/{credential_id_three}/rotate",
        headers=headers,
    )
    assert rotated.status_code == 201

    audit_response = client.get(
        f"/api/businesses/{seeded_business.id}/auth-audit-events",
        headers=headers,
        params={"target_type": "api_credential", "limit": 100},
    )
    assert audit_response.status_code == 200
    payload = audit_response.json()
    event_types = {event["event_type"] for event in payload["items"]}
    assert "credential_created" in event_types
    assert "credential_disabled" in event_types
    assert "credential_revoked" in event_types
    assert "credential_rotated" in event_types
    for event in payload["items"]:
        assert event["business_id"] == seeded_business.id
        assert event["target_type"] == "api_credential"
        assert _contains_sensitive_keys(event["details_json"]) is False


def test_audit_events_are_business_scoped_and_cross_tenant_access_is_blocked(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
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

    admin_a = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="tenant-a-admin",
        role=PrincipalRole.ADMIN,
    )
    admin_b = _seed_credential(
        db_session,
        business_id=other_business.id,
        principal_id="tenant-b-admin",
        role=PrincipalRole.ADMIN,
    )
    client = _make_client(db_session)

    create_a = client.post(
        f"/api/businesses/{seeded_business.id}/principals",
        headers={"Authorization": f"Bearer {admin_a}"},
        json={"principal_id": "tenant-a-op", "role": "operator"},
    )
    assert create_a.status_code == 201

    cross_tenant = client.get(
        f"/api/businesses/{seeded_business.id}/auth-audit-events",
        headers={"Authorization": f"Bearer {admin_b}"},
    )
    assert cross_tenant.status_code == 404

    tenant_b_view = client.get(
        f"/api/businesses/{other_business.id}/auth-audit-events",
        headers={"Authorization": f"Bearer {admin_b}"},
    )
    assert tenant_b_view.status_code == 200
    assert all(event["business_id"] == other_business.id for event in tenant_b_view.json()["items"])


def test_operator_principal_cannot_access_admin_audit_view(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_production_auth_defaults(monkeypatch, default_business_id=seeded_business.id)
    operator_token = _seed_credential(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-audit-user",
        role=PrincipalRole.OPERATOR,
    )
    client = _make_client(db_session)

    response = client.get(
        f"/api/businesses/{seeded_business.id}/auth-audit-events",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 403

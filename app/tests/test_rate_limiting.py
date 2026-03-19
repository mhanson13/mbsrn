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
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.principal import Principal, PrincipalRole
from app.repositories.api_credential_repository import hash_bearer_token

PROD_PEPPER = "prod-pepper"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_limit: int,
    admin_limit: int,
    auth_window_seconds: int = 60,
    admin_window_seconds: int = 60,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", PROD_PEPPER)
    monkeypatch.setenv("ALLOW_LEGACY_TOKEN_HASH_FALLBACK", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "inmemory")
    monkeypatch.setenv("AUTH_RATE_LIMIT_REQUESTS", str(auth_limit))
    monkeypatch.setenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", str(auth_window_seconds))
    monkeypatch.setenv("ADMIN_RATE_LIMIT_REQUESTS", str(admin_limit))
    monkeypatch.setenv("ADMIN_RATE_LIMIT_WINDOW_SECONDS", str(admin_window_seconds))


def _make_client(db_session, *, include_businesses: bool = False, include_leads: bool = False) -> TestClient:
    app = FastAPI()
    if include_businesses:
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


def _seed_admin_credential(
    db_session,
    *,
    business_id: str,
    principal_id: str = "admin-rate-limit-user",
) -> str:
    principal = db_session.get(Principal, (business_id, principal_id))
    if principal is None:
        principal = Principal(
            business_id=business_id,
            id=principal_id,
            display_name=principal_id,
            role=PrincipalRole.ADMIN,
            is_active=True,
        )
        db_session.add(principal)
    else:
        principal.role = PrincipalRole.ADMIN
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


def _seed_lead(db_session, *, business_id: str) -> Lead:
    lead = Lead(
        id=str(uuid4()),
        business_id=business_id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=8),
        customer_name="Rate Limit Lead",
        phone="3035550115",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()
    db_session.refresh(lead)
    return lead


def test_auth_requests_are_rate_limited_by_client_ip(
    db_session, seeded_business, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(
        monkeypatch,
        auth_limit=2,
        admin_limit=10,
    )
    client = _make_client(db_session, include_leads=True)
    headers = {"Authorization": "Bearer invalid-token"}

    first = client.get("/api/leads", headers=headers)
    second = client.get("/api/leads", headers=headers)
    third = client.get("/api/leads", headers=headers)

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert third.json()["detail"] == "Rate limit exceeded. Retry later."
    assert third.headers.get("X-RateLimit-Category") == "auth"
    assert "invalid-token" not in third.text


def test_admin_routes_are_stricter_than_authenticated_lead_reads(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        auth_limit=20,
        admin_limit=2,
    )
    token = _seed_admin_credential(db_session, business_id=seeded_business.id)
    _seed_lead(db_session, business_id=seeded_business.id)
    client = _make_client(db_session, include_businesses=True, include_leads=True)
    headers = {"Authorization": f"Bearer {token}"}

    one = client.post(
        f"/api/businesses/{seeded_business.id}/principals",
        headers=headers,
        json={"principal_id": "rl-op-1", "role": "operator"},
    )
    two = client.post(
        f"/api/businesses/{seeded_business.id}/principals",
        headers=headers,
        json={"principal_id": "rl-op-2", "role": "operator"},
    )
    three = client.post(
        f"/api/businesses/{seeded_business.id}/principals",
        headers=headers,
        json={"principal_id": "rl-op-3", "role": "operator"},
    )

    assert one.status_code == 201
    assert two.status_code == 201
    assert three.status_code == 429
    assert three.headers.get("X-RateLimit-Category") == "admin:principal_create"

    lead_read = client.get("/api/leads", headers=headers)
    assert lead_read.status_code == 200

    audit_read = client.get(f"/api/businesses/{seeded_business.id}/auth-audit-events", headers=headers)
    assert audit_read.status_code == 200
    events = audit_read.json()["items"]
    assert any(event["event_type"] == "admin_rate_limit_denied" for event in events)


def test_admin_audit_read_endpoint_is_rate_limited(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        auth_limit=20,
        admin_limit=1,
    )
    token = _seed_admin_credential(db_session, business_id=seeded_business.id, principal_id="audit-admin")
    client = _make_client(db_session, include_businesses=True)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.get(f"/api/businesses/{seeded_business.id}/auth-audit-events", headers=headers)
    second = client.get(f"/api/businesses/{seeded_business.id}/auth-audit-events", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers.get("X-RateLimit-Category") == "admin:auth_audit_read"

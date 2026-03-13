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
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_auth_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    principals: list[dict[str, str]] | None = None,
    legacy_token: str | None = None,
    legacy_business_id: str | None = None,
    allow_auth_compat_fallback: bool | None = None,
    environment: str = "test",
    default_business_id: str,
) -> None:
    if principals is None:
        monkeypatch.delenv("API_AUTH_PRINCIPALS_JSON", raising=False)
    else:
        monkeypatch.setenv("API_AUTH_PRINCIPALS_JSON", json.dumps(principals))

    if legacy_token is None:
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("API_AUTH_TOKEN", legacy_token)

    if legacy_business_id is None:
        monkeypatch.delenv("API_AUTH_BUSINESS_ID", raising=False)
    else:
        monkeypatch.setenv("API_AUTH_BUSINESS_ID", legacy_business_id)

    if allow_auth_compat_fallback is None:
        monkeypatch.delenv("ALLOW_AUTH_COMPAT_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("ALLOW_AUTH_COMPAT_FALLBACK", "true" if allow_auth_compat_fallback else "false")

    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)


def test_principal_token_binds_tenant_scope_not_global_default(
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

    _set_auth_env(
        monkeypatch,
        principals=[
            {
                "token": "tenant-a-token",
                "principal_id": "user-a",
                "business_id": seeded_business.id,
            }
        ],
        allow_auth_compat_fallback=True,
        environment="production",
        default_business_id=other_business.id,
    )

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    headers = {"Authorization": "Bearer tenant-a-token"}
    same_tenant = client.get(f"/api/leads/{lead_a.id}", headers=headers)
    assert same_tenant.status_code == 200
    assert same_tenant.json()["business_id"] == seeded_business.id

    spoofed_cross_tenant = client.get(
        f"/api/leads/{lead_b.id}",
        params={"business_id": other_business.id},
        headers=headers,
    )
    assert spoofed_cross_tenant.status_code == 404


def test_principal_registry_requires_valid_bearer_token(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(
        monkeypatch,
        principals=[
            {
                "token": "tenant-a-token",
                "principal_id": "user-a",
                "business_id": seeded_business.id,
            }
        ],
        allow_auth_compat_fallback=True,
        environment="production",
        default_business_id=seeded_business.id,
    )

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    no_token = client.get("/api/leads")
    assert no_token.status_code == 401

    bad_token = client.get("/api/leads", headers={"Authorization": "Bearer wrong-token"})
    assert bad_token.status_code == 401


def test_legacy_shared_token_compatibility_fallback_still_works(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=5),
        customer_name="Legacy Tenant Lead",
        phone="3035550199",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()

    _set_auth_env(
        monkeypatch,
        principals=None,
        legacy_token="legacy-shared-token",
        legacy_business_id=seeded_business.id,
        allow_auth_compat_fallback=True,
        environment="production",
        default_business_id=str(uuid4()),
    )

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": "Bearer legacy-shared-token"},
    )
    assert response.status_code == 200
    assert response.json()["business_id"] == seeded_business.id


def test_no_auth_config_in_production_is_rejected(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(
        monkeypatch,
        principals=None,
        legacy_token=None,
        legacy_business_id=None,
        environment="production",
        default_business_id=seeded_business.id,
    )

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/api/leads")
    assert response.status_code == 401


def test_env_principal_fallback_is_disabled_in_production_by_default(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=5),
        customer_name="Tenant A Lead",
        phone="3035550198",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    db_session.commit()

    _set_auth_env(
        monkeypatch,
        principals=[
            {
                "token": "tenant-a-token",
                "principal_id": "user-a",
                "business_id": seeded_business.id,
            }
        ],
        allow_auth_compat_fallback=None,
        environment="production",
        default_business_id=seeded_business.id,
    )

    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": "Bearer tenant-a-token"},
    )
    assert response.status_code == 401

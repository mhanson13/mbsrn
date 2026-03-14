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
    environment: str,
    default_business_id: str,
    api_token_hash_pepper: str | None = None,
) -> None:
    if principals is None:
        monkeypatch.delenv("API_AUTH_PRINCIPALS_JSON", raising=False)
    else:
        monkeypatch.setenv("API_AUTH_PRINCIPALS_JSON", json.dumps(principals))

    if api_token_hash_pepper is None:
        monkeypatch.delenv("API_TOKEN_HASH_PEPPER", raising=False)
    else:
        monkeypatch.setenv("API_TOKEN_HASH_PEPPER", api_token_hash_pepper)

    monkeypatch.delenv("ALLOW_AUTH_COMPAT_FALLBACK", raising=False)
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("API_AUTH_BUSINESS_ID", raising=False)
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)


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


def test_env_principal_json_is_ignored_in_test_environment(
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
        environment="test",
        default_business_id=seeded_business.id,
    )

    client = _make_client(db_session)
    response = client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": "Bearer tenant-a-token"},
    )
    assert response.status_code == 401


def test_env_principal_json_is_ignored_in_production_environment(
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
        phone="3035550197",
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
        environment="production",
        default_business_id=seeded_business.id,
        api_token_hash_pepper="prod-pepper",
    )

    client = _make_client(db_session)
    response = client.get(
        f"/api/leads/{lead.id}",
        headers={"Authorization": "Bearer tenant-a-token"},
    )
    assert response.status_code == 401


def test_no_auth_config_in_production_is_rejected(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(
        monkeypatch,
        principals=None,
        environment="production",
        default_business_id=seeded_business.id,
        api_token_hash_pepper="prod-pepper",
    )
    client = _make_client(db_session)
    response = client.get("/api/leads")
    assert response.status_code == 401


def test_test_environment_default_business_fallback_still_works(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(
        monkeypatch,
        principals=None,
        environment="test",
        default_business_id=seeded_business.id,
    )
    client = _make_client(db_session)
    response = client.get("/api/leads")
    assert response.status_code == 200


def test_production_requires_api_token_hash_pepper(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(
        monkeypatch,
        principals=None,
        environment="production",
        default_business_id=seeded_business.id,
        api_token_hash_pepper=None,
    )
    client = _make_client(db_session)
    with pytest.raises(RuntimeError, match="API_TOKEN_HASH_PEPPER is required"):
        client.get("/api/leads", headers={"Authorization": "Bearer some-token"})

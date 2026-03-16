from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db, get_google_oidc_verifier
from app.api.routes.auth import router as auth_router
from app.api.routes.leads import router as leads_router
from app.core.config import get_settings
from app.core.time import utc_now
from app.integrations.google_auth import (
    GoogleIdentityClaims,
    GoogleOIDCVerificationError,
)
from app.models.business import Business
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.principal import Principal, PrincipalRole
from app.models.auth_audit_event import AuthAuditEvent
from app.models.principal_identity import PrincipalIdentity


class _StubGoogleVerifier:
    def __init__(self, mapping: dict[str, GoogleIdentityClaims]) -> None:
        self.mapping = mapping

    def verify_id_token(self, id_token: str) -> GoogleIdentityClaims:
        claims = self.mapping.get(id_token)
        if claims is None:
            raise GoogleOIDCVerificationError("Google token verification failed.")
        return claims


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_auth_env(monkeypatch: pytest.MonkeyPatch, *, default_business_id: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "prod-pepper")
    monkeypatch.setenv("GOOGLE_AUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OIDC_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OIDC_REQUIRE_EMAIL_VERIFIED", "true")
    monkeypatch.setenv("APP_SESSION_SECRET", "app-session-secret")
    monkeypatch.setenv("APP_SESSION_TTL_SECONDS", "3600")
    monkeypatch.setenv("APP_SESSION_REFRESH_TTL_SECONDS", "86400")
    monkeypatch.setenv("SESSION_STATE_BACKEND", "inmemory")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "inmemory")


def _make_client(db_session, *, verifier: _StubGoogleVerifier) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(leads_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_google_oidc_verifier] = lambda: verifier
    return TestClient(app)


def _seed_principal_identity(
    db_session,
    *,
    business_id: str,
    principal_id: str,
    provider_subject: str,
    is_active: bool = True,
) -> PrincipalIdentity:
    principal = Principal(
        business_id=business_id,
        id=principal_id,
        display_name=principal_id,
        role=PrincipalRole.ADMIN,
        is_active=True,
    )
    identity = PrincipalIdentity(
        id=str(uuid4()),
        provider="google",
        provider_subject=provider_subject,
        business_id=business_id,
        principal_id=principal_id,
        email="user@example.com",
        email_verified=True,
        is_active=is_active,
    )
    db_session.add_all([principal, identity])
    db_session.commit()
    return identity


def test_google_exchange_issues_session_token_and_preserves_tenant_scope(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    identity = _seed_principal_identity(
        db_session,
        business_id=seeded_business.id,
        principal_id="google-admin",
        provider_subject="google-sub-a",
    )

    lead = Lead(
        id=str(uuid4()),
        business_id=seeded_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=4),
        customer_name="Tenant A",
        phone="3035550101",
        status=LeadStatus.NEW,
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
    other_lead = Lead(
        id=str(uuid4()),
        business_id=other_business.id,
        source=LeadSource.MANUAL,
        source_ref=None,
        submitted_at=utc_now() - timedelta(minutes=3),
        customer_name="Tenant B",
        phone="3035550102",
        status=LeadStatus.NEW,
    )
    db_session.add_all([lead, other_business, other_lead])
    db_session.commit()

    verifier = _StubGoogleVerifier(
        {
            "valid-google-id-token": GoogleIdentityClaims(
                provider="google",
                subject="google-sub-a",
                email="updated-user@example.com",
                email_verified=True,
                issuer="https://accounts.google.com",
                audience="google-client-id",
                display_name="Google Admin",
            )
        }
    )
    client = _make_client(db_session, verifier=verifier)

    exchange = client.post(
        "/api/auth/google/exchange",
        json={"id_token": "valid-google-id-token"},
    )
    assert exchange.status_code == 200
    payload = exchange.json()
    assert payload["token_type"] == "bearer"
    assert payload["principal"]["business_id"] == seeded_business.id
    access_token = payload["access_token"]
    refresh_token = payload["refresh_token"]
    assert access_token.count(".") == 2
    assert refresh_token.count(".") == 2
    assert payload["refresh_expires_at"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    assert me.json()["principal_id"] == "google-admin"
    assert me.json()["auth_source"] == "google_oidc_session"

    same_tenant = client.get(f"/api/leads/{lead.id}", headers={"Authorization": f"Bearer {access_token}"})
    assert same_tenant.status_code == 200
    assert same_tenant.json()["business_id"] == seeded_business.id

    cross_tenant = client.get(
        f"/api/leads/{other_lead.id}",
        params={"business_id": other_business.id},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert cross_tenant.status_code == 404

    db_session.expire_all()
    refreshed = db_session.get(PrincipalIdentity, identity.id)
    assert refreshed is not None
    assert refreshed.email == "updated-user@example.com"
    assert refreshed.last_authenticated_at is not None

    refreshed_session = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed_session.status_code == 200
    refreshed_payload = refreshed_session.json()
    assert refreshed_payload["access_token"] != access_token
    assert refreshed_payload["refresh_token"] != refresh_token

    me_with_refresh = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert me_with_refresh.status_code == 401

    replay_refresh = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert replay_refresh.status_code == 401
    replay_events = (
        db_session.query(AuthAuditEvent)
        .filter(AuthAuditEvent.business_id == seeded_business.id)
        .filter(AuthAuditEvent.event_type == "session_refresh_replay_detected")
        .all()
    )
    assert replay_events
    assert replay_events[-1].actor_principal_id == "google-admin"
    assert replay_events[-1].target_type == "session"
    assert replay_events[-1].details_json.get("action") == "auth_refresh"


def test_google_exchange_rejects_unmapped_identity(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    verifier = _StubGoogleVerifier(
        {
            "id-token-unmapped": GoogleIdentityClaims(
                provider="google",
                subject="missing-subject",
                email="missing@example.com",
                email_verified=True,
                issuer="https://accounts.google.com",
                audience="google-client-id",
                display_name=None,
            )
        }
    )
    client = _make_client(db_session, verifier=verifier)
    response = client.post("/api/auth/google/exchange", json={"id_token": "id-token-unmapped"})
    assert response.status_code == 403


def test_google_exchange_rejects_inactive_identity_mapping(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal_identity(
        db_session,
        business_id=seeded_business.id,
        principal_id="inactive-user",
        provider_subject="google-sub-inactive",
        is_active=False,
    )
    verifier = _StubGoogleVerifier(
        {
            "id-token-inactive": GoogleIdentityClaims(
                provider="google",
                subject="google-sub-inactive",
                email="inactive@example.com",
                email_verified=True,
                issuer="https://accounts.google.com",
                audience="google-client-id",
                display_name=None,
            )
        }
    )
    client = _make_client(db_session, verifier=verifier)
    response = client.post("/api/auth/google/exchange", json={"id_token": "id-token-inactive"})
    assert response.status_code == 403


def test_refresh_rejects_when_identity_is_deactivated_after_exchange(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    identity = _seed_principal_identity(
        db_session,
        business_id=seeded_business.id,
        principal_id="refresh-user",
        provider_subject="google-sub-refresh",
    )
    verifier = _StubGoogleVerifier(
        {
            "id-token-refresh": GoogleIdentityClaims(
                provider="google",
                subject="google-sub-refresh",
                email="refresh@example.com",
                email_verified=True,
                issuer="https://accounts.google.com",
                audience="google-client-id",
                display_name=None,
            )
        }
    )
    client = _make_client(db_session, verifier=verifier)
    exchange = client.post("/api/auth/google/exchange", json={"id_token": "id-token-refresh"})
    assert exchange.status_code == 200
    refresh_token = exchange.json()["refresh_token"]

    identity.is_active = False
    db_session.add(identity)
    db_session.commit()

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 401


def test_access_token_rejected_after_principal_deactivation(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal_identity(
        db_session,
        business_id=seeded_business.id,
        principal_id="deactivate-user",
        provider_subject="google-sub-deactivate",
    )
    verifier = _StubGoogleVerifier(
        {
            "id-token-deactivate": GoogleIdentityClaims(
                provider="google",
                subject="google-sub-deactivate",
                email="deactivate@example.com",
                email_verified=True,
                issuer="https://accounts.google.com",
                audience="google-client-id",
                display_name=None,
            )
        }
    )
    client = _make_client(db_session, verifier=verifier)
    exchange = client.post("/api/auth/google/exchange", json={"id_token": "id-token-deactivate"})
    assert exchange.status_code == 200
    access_token = exchange.json()["access_token"]

    principal = db_session.get(Principal, (seeded_business.id, "deactivate-user"))
    assert principal is not None
    principal.is_active = False
    db_session.add(principal)
    db_session.commit()

    me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_response.status_code == 401


def test_logout_revokes_current_access_and_refresh_tokens(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal_identity(
        db_session,
        business_id=seeded_business.id,
        principal_id="logout-user",
        provider_subject="google-sub-logout",
    )
    verifier = _StubGoogleVerifier(
        {
            "id-token-logout": GoogleIdentityClaims(
                provider="google",
                subject="google-sub-logout",
                email="logout@example.com",
                email_verified=True,
                issuer="https://accounts.google.com",
                audience="google-client-id",
                display_name=None,
            )
        }
    )
    client = _make_client(db_session, verifier=verifier)
    exchange = client.post("/api/auth/google/exchange", json={"id_token": "id-token-logout"})
    assert exchange.status_code == 200
    access_token = exchange.json()["access_token"]
    refresh_token = exchange.json()["refresh_token"]

    logout_response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout_response.status_code == 200

    me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_response.status_code == 401

    refresh_response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 401

    logout_events = (
        db_session.query(AuthAuditEvent)
        .filter(AuthAuditEvent.business_id == seeded_business.id)
        .filter(AuthAuditEvent.event_type == "session_logout")
        .all()
    )
    assert logout_events
    assert logout_events[-1].actor_principal_id == "logout-user"
    assert logout_events[-1].details_json.get("refresh_revoked") is True

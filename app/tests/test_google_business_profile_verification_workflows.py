from __future__ import annotations

from datetime import timedelta
import json
import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.deps import (
    TenantContext,
    get_authenticated_principal,
    get_db,
    get_google_business_profile_client,
    get_google_oauth_client,
    get_tenant_context,
)
from app.api.routes.integrations import router as integrations_router
from app.core.config import get_settings
from app.core.time import utc_now
from app.core.token_cipher import FernetTokenCipher
from app.integrations.google_business_profile import GoogleBusinessProfileAPIError
from app.integrations.google_oauth import GoogleOAuthError, GoogleOAuthTokenResponse
from app.models.business import Business
from app.models.principal import Principal, PrincipalRole
from app.models.provider_connection import ProviderConnection
from app.services.google_business_profile_verification_observability import (
    verification_observability,
)


class _StubGoogleOAuthClient:
    def __init__(self) -> None:
        self.refresh_map: dict[str, GoogleOAuthTokenResponse | Exception] = {}
        self.refresh_calls: list[str] = []

    def build_auth_url(self, **_: object) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth"

    def exchange_code_for_tokens(self, **_: object) -> GoogleOAuthTokenResponse:
        raise GoogleOAuthError("exchange flow is not used in verification workflow tests")

    def refresh_access_token(self, *, refresh_token: str) -> GoogleOAuthTokenResponse:
        self.refresh_calls.append(refresh_token)
        result = self.refresh_map.get(refresh_token)
        if result is None:
            raise GoogleOAuthError("refresh token is unknown for test stub")
        if isinstance(result, Exception):
            raise result
        return result

    def revoke_token(self, *, token: str) -> bool:
        return bool(token)


class _StubGoogleBusinessProfileClient:
    def __init__(self) -> None:
        self.accounts_payload: dict[str, object] = {"accounts": []}
        self.accounts_by_token: dict[str, dict[str, object]] = {}
        self.locations_by_account: dict[str, dict[str, object] | Exception] = {}
        self.voice_by_location: dict[str, dict[str, object] | Exception] = {}
        self.verifications_by_location: dict[str, dict[str, object] | Exception] = {}
        self.options_by_location: dict[str, dict[str, object] | Exception] = {}
        self.start_by_location: dict[str, dict[str, object] | Exception] = {}
        self.complete_by_verification: dict[str, dict[str, object] | Exception] = {}
        self.start_calls: list[tuple[str, dict[str, object]]] = []
        self.complete_calls: list[tuple[str, str]] = []

    def list_accounts(self, *, access_token: str) -> dict[str, object]:
        by_token = self.accounts_by_token.get(access_token)
        if by_token is not None:
            return by_token
        return self.accounts_payload

    def list_locations(self, *, access_token: str, account_resource_name: str) -> dict[str, object]:
        result = self.locations_by_account.get(account_resource_name, {"locations": []})
        if isinstance(result, Exception):
            raise result
        return result

    def get_voice_of_merchant_state(self, *, access_token: str, location_resource_name: str) -> dict[str, object]:
        result = self.voice_by_location.get(location_resource_name, {"hasVoiceOfMerchant": False})
        if isinstance(result, Exception):
            raise result
        return result

    def list_verifications(self, *, access_token: str, location_resource_name: str) -> dict[str, object]:
        result = self.verifications_by_location.get(location_resource_name, {"verifications": []})
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_verification_options(self, *, access_token: str, location_resource_name: str) -> dict[str, object]:
        result = self.options_by_location.get(location_resource_name, {"verificationOptions": []})
        if isinstance(result, Exception):
            raise result
        return result

    def start_verification(
        self,
        *,
        access_token: str,
        location_resource_name: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        self.start_calls.append((location_resource_name, body))
        result = self.start_by_location.get(location_resource_name)
        if result is None:
            method = str(body.get("method") or "EMAIL")
            generated = {
                "name": f"{location_resource_name}/verifications/generated",
                "verificationMethod": method,
                "state": "PENDING",
            }
            self.verifications_by_location[location_resource_name] = {"verifications": [generated]}
            return generated
        if isinstance(result, Exception):
            raise result
        self.verifications_by_location[location_resource_name] = {"verifications": [result]}
        return result

    def complete_verification(
        self,
        *,
        access_token: str,
        verification_resource_name: str,
        pin: str,
    ) -> dict[str, object]:
        self.complete_calls.append((verification_resource_name, pin))
        result = self.complete_by_verification.get(verification_resource_name)
        if result is None:
            return {
                "name": verification_resource_name,
                "state": "COMPLETED",
            }
        if isinstance(result, Exception):
            raise result
        location_resource_name, _, _ = verification_resource_name.partition("/verifications/")
        self.voice_by_location[location_resource_name] = {"hasVoiceOfMerchant": True}
        self.verifications_by_location[location_resource_name] = {"verifications": [result]}
        return result


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_verification_observability() -> None:
    verification_observability.reset()
    yield
    verification_observability.reset()


def _assert_guidance_contract(guidance: dict[str, object]) -> None:
    assert isinstance(guidance.get("title"), str)
    assert isinstance(guidance.get("summary"), str)
    assert isinstance(guidance.get("instructions"), list)
    assert isinstance(guidance.get("tips"), list)
    assert isinstance(guidance.get("warnings"), list)
    assert isinstance(guidance.get("troubleshooting"), list)
    assert isinstance(guidance.get("cta_type"), str)


def _set_auth_env(monkeypatch: pytest.MonkeyPatch, *, default_business_id: str) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEFAULT_BUSINESS_ID", default_business_id)
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "test-pepper")
    monkeypatch.setenv("GOOGLE_AUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OIDC_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OIDC_REQUIRE_EMAIL_VERIFIED", "true")
    monkeypatch.setenv("APP_SESSION_SECRET", "app-session-secret")
    monkeypatch.setenv("APP_SESSION_TTL_SECONDS", "3600")
    monkeypatch.setenv("APP_SESSION_REFRESH_TTL_SECONDS", "86400")
    monkeypatch.setenv("SESSION_STATE_BACKEND", "inmemory")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "inmemory")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-oauth-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-oauth-client-secret")
    monkeypatch.setenv(
        "GOOGLE_BUSINESS_PROFILE_REDIRECT_URI",
        "https://operator.workboots.example/api/integrations/google/business-profile/connect/callback",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION", "v1")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON",
        json.dumps({"v1": "gbp-token-encryption-secret"}),
    )
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_SKEW_SECONDS", "120")
    monkeypatch.setenv("GOOGLE_BUSINESS_PROFILE_STATE_TTL_SECONDS", "600")


def _seed_principal(
    db_session,
    *,
    business_id: str,
    principal_id: str,
) -> Principal:
    principal = Principal(
        business_id=business_id,
        id=principal_id,
        display_name=principal_id,
        role=PrincipalRole.ADMIN,
        is_active=True,
    )
    db_session.add(principal)
    db_session.commit()
    return principal


def _seed_provider_connection(
    db_session,
    *,
    business_id: str,
    principal_id: str,
    access_token: str,
    refresh_token: str | None,
    expires_in_seconds: int,
    scopes: str = "https://www.googleapis.com/auth/business.manage",
) -> ProviderConnection:
    cipher = FernetTokenCipher(
        active_key_version="v1",
        keyring={"v1": "gbp-token-encryption-secret"},
    )
    now = utc_now()
    connection = ProviderConnection(
        id=str(uuid4()),
        provider="google_business_profile",
        business_id=business_id,
        principal_id=principal_id,
        created_by_principal_id=principal_id,
        updated_by_principal_id=principal_id,
        granted_scopes=scopes,
        token_key_version="v1",
        access_token_encrypted=cipher.encrypt(access_token),
        refresh_token_encrypted=cipher.encrypt(refresh_token) if refresh_token else None,
        access_token_expires_at=now + timedelta(seconds=expires_in_seconds),
        is_active=True,
        connected_at=now,
        last_refreshed_at=now,
    )
    db_session.add(connection)
    db_session.commit()
    return connection


def _make_integrations_client(
    db_session,
    *,
    oauth_client: _StubGoogleOAuthClient,
    gbp_client: _StubGoogleBusinessProfileClient,
    business_id: str,
    principal_id: str,
) -> TestClient:
    app = FastAPI()
    app.include_router(integrations_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_tenant_context() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=principal_id,
            auth_source="test_suite",
            principal_role=PrincipalRole.ADMIN,
        )

    def override_principal() -> Principal:
        principal = db_session.get(Principal, (business_id, principal_id))
        if principal is None:
            raise RuntimeError("principal fixture missing")
        return principal

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_google_oauth_client] = lambda: oauth_client
    app.dependency_overrides[get_google_business_profile_client] = lambda: gbp_client
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    app.dependency_overrides[get_authenticated_principal] = override_principal
    return TestClient(app)


def _seed_location_catalog(gbp_client: _StubGoogleBusinessProfileClient, *, account_id: str, location_id: str) -> None:
    account_resource_name = f"accounts/{account_id}"
    location_resource_name = f"locations/{location_id}"
    gbp_client.accounts_payload = {"accounts": [{"name": account_resource_name, "accountName": "Main"}]}
    gbp_client.locations_by_account[account_resource_name] = {
        "locations": [{"name": location_resource_name, "title": "HQ"}]
    }


def test_verification_options_returns_normalized_methods(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-options-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-options-admin",
        access_token="verify-options-token",
        refresh_token="verify-options-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-1")
    gbp_client.options_by_location["locations/location-1"] = {
        "verificationOptions": [
            {"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"},
            {"verificationMethod": "SMS", "phoneNumber": "+13035551234"},
        ]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-options-admin",
    )

    response = client.get("/api/integrations/google/business-profile/locations/location-1/verification/options")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["location_id"] == "location-1"
    assert payload["current_verification_state"] == "unverified"
    assert len(payload["methods"]) == 2
    assert payload["methods"][0]["method"] == "email"
    assert payload["methods"][1]["method"] == "sms"
    assert payload["guidance"]["recommended_action"] == "choose_method"
    _assert_guidance_contract(payload["guidance"])


def test_verification_summary_response_includes_guidance_contract(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-summary-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-summary-admin",
        access_token="verify-summary-token",
        refresh_token="verify-summary-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-summary")
    gbp_client.options_by_location["locations/location-summary"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-summary-admin",
    )

    response = client.get("/api/integrations/google/business-profile/locations/location-summary/verification")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state_summary"] == "unverified"
    _assert_guidance_contract(payload["guidance"])


def test_verification_status_response_includes_guidance_contract(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-status-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-status-admin",
        access_token="verify-status-token",
        refresh_token="verify-status-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-status")
    gbp_client.verifications_by_location["locations/location-status"] = {
        "verifications": [
            {
                "name": "locations/location-status/verifications/attempt-1",
                "verificationMethod": "EMAIL",
                "state": "PENDING",
            }
        ]
    }
    gbp_client.options_by_location["locations/location-status"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-status-admin",
    )

    response = client.get("/api/integrations/google/business-profile/locations/location-status/verification/status")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["verification_state"] in {"pending", "in_progress"}
    _assert_guidance_contract(payload["guidance"])


def test_verification_status_unknown_provider_state_increments_observability_counter(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-unknown-state-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-unknown-state-admin",
        access_token="verify-unknown-state-token",
        refresh_token="verify-unknown-state-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-unknown-state")
    gbp_client.verifications_by_location["locations/location-unknown-state"] = {
        "verifications": [
            {
                "name": "locations/location-unknown-state/verifications/attempt-1",
                "verificationMethod": "EMAIL",
                "state": "SOMETHING_NEW",
            }
        ]
    }
    gbp_client.options_by_location["locations/location-unknown-state"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-unknown-state-admin",
    )

    response = client.get(
        "/api/integrations/google/business-profile/locations/location-unknown-state/verification/status"
    )
    assert response.status_code == 200, response.text
    assert verification_observability.snapshot().get("provider_state_unmapped", 0) >= 1


def test_start_verification_success_path(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-start-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-start-admin",
        access_token="verify-start-token",
        refresh_token="verify-start-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-start")
    gbp_client.options_by_location["locations/location-start"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }
    gbp_client.start_by_location["locations/location-start"] = {
        "name": "locations/location-start/verifications/attempt-1",
        "verificationMethod": "EMAIL",
        "state": "PENDING",
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-start-admin",
    )

    response = client.post(
        "/api/integrations/google/business-profile/locations/location-start/verification/start",
        json={"selected_method": "email"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["location_id"] == "location-start"
    assert payload["verification_id"] == "attempt-1"
    assert payload["reconnect_required"] is False
    assert payload["status"]["verification_state"] in {"pending", "in_progress"}
    assert payload["guidance"]["recommended_action"] in {"enter_code", "wait_for_code"}
    _assert_guidance_contract(payload["guidance"])
    _assert_guidance_contract(payload["status"]["guidance"])
    assert gbp_client.start_calls


def test_start_verification_with_option_id_uses_backend_revalidation(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-start-option-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-start-option-admin",
        access_token="verify-start-option-token",
        refresh_token="verify-start-option-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-start-option")
    gbp_client.options_by_location["locations/location-start-option"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-start-option-admin",
    )

    options_response = client.get(
        "/api/integrations/google/business-profile/locations/location-start-option/verification/options"
    )
    assert options_response.status_code == 200, options_response.text
    option_id = options_response.json()["methods"][0]["option_id"]
    assert option_id.startswith("method_")

    start_response = client.post(
        "/api/integrations/google/business-profile/locations/location-start-option/verification/start",
        json={"option_id": option_id},
    )
    assert start_response.status_code == 200, start_response.text
    start_payload_body = start_response.json()
    _assert_guidance_contract(start_payload_body["guidance"])
    _assert_guidance_contract(start_payload_body["status"]["guidance"])
    assert gbp_client.start_calls
    _, start_payload = gbp_client.start_calls[-1]
    assert start_payload["method"] == "EMAIL"


def test_start_verification_invalid_option_id_is_rejected_and_logged(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-start-invalid-option-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-start-invalid-option-admin",
        access_token="verify-start-invalid-option-token",
        refresh_token="verify-start-invalid-option-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-invalid-option")
    gbp_client.options_by_location["locations/location-invalid-option"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-start-invalid-option-admin",
    )

    caplog.set_level(logging.WARNING)
    response = client.post(
        "/api/integrations/google/business-profile/locations/location-invalid-option/verification/start",
        json={"option_id": "method_not_a_real_option"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "method_not_available"
    _assert_guidance_contract(detail["guidance"])
    assert "gbp_verification_option_token_invalid" in caplog.text
    assert verification_observability.snapshot().get("option_token_invalid", 0) == 1


def test_complete_verification_success_path(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-complete-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-complete-admin",
        access_token="verify-complete-token",
        refresh_token="verify-complete-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-complete")
    gbp_client.verifications_by_location["locations/location-complete"] = {
        "verifications": [
            {
                "name": "locations/location-complete/verifications/attempt-1",
                "verificationMethod": "EMAIL",
                "state": "PENDING",
            }
        ]
    }
    gbp_client.options_by_location["locations/location-complete"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }
    gbp_client.complete_by_verification["locations/location-complete/verifications/attempt-1"] = {
        "name": "locations/location-complete/verifications/attempt-1",
        "verificationMethod": "EMAIL",
        "state": "COMPLETED",
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-complete-admin",
    )

    response = client.post(
        "/api/integrations/google/business-profile/locations/location-complete/verification/complete",
        json={"verification_id": "attempt-1", "code": "123456"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reconnect_required"] is False
    assert payload["status"]["verification_state"] == "completed"
    assert payload["status"]["action_required"] == "none"
    _assert_guidance_contract(payload["guidance"])
    _assert_guidance_contract(payload["status"]["guidance"])
    assert gbp_client.complete_calls == [("locations/location-complete/verifications/attempt-1", "123456")]


def test_complete_verification_invalid_code_maps_error(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-invalid-code-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-invalid-code-admin",
        access_token="verify-invalid-code-token",
        refresh_token="verify-invalid-code-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-invalid-code")
    gbp_client.verifications_by_location["locations/location-invalid-code"] = {
        "verifications": [
            {
                "name": "locations/location-invalid-code/verifications/attempt-1",
                "verificationMethod": "EMAIL",
                "state": "PENDING",
            }
        ]
    }
    gbp_client.complete_by_verification["locations/location-invalid-code/verifications/attempt-1"] = (
        GoogleBusinessProfileAPIError(
            "invalid pin",
            status_code=400,
            error_status="INVALID_ARGUMENT",
        )
    )

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-invalid-code-admin",
    )

    response = client.post(
        "/api/integrations/google/business-profile/locations/location-invalid-code/verification/complete",
        json={"verification_id": "attempt-1", "code": "bad"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_code"
    _assert_guidance_contract(detail["guidance"])


def test_start_verification_method_not_available_maps_error(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-method-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-method-admin",
        access_token="verify-method-token",
        refresh_token="verify-method-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-method")
    gbp_client.options_by_location["locations/location-method"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-method-admin",
    )

    response = client.post(
        "/api/integrations/google/business-profile/locations/location-method/verification/start",
        json={"selected_method": "sms"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "method_not_available"


def test_retry_verification_uses_existing_attempt_method_when_not_specified(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-retry-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-retry-admin",
        access_token="verify-retry-token",
        refresh_token="verify-retry-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-retry")
    gbp_client.verifications_by_location["locations/location-retry"] = {
        "verifications": [
            {
                "name": "locations/location-retry/verifications/attempt-failed",
                "verificationMethod": "EMAIL",
                "state": "FAILED",
            }
        ]
    }
    gbp_client.options_by_location["locations/location-retry"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-retry-admin",
    )

    response = client.post(
        "/api/integrations/google/business-profile/locations/location-retry/verification/retry",
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reconnect_required"] is False
    _assert_guidance_contract(payload["guidance"])
    _assert_guidance_contract(payload["status"]["guidance"])
    assert gbp_client.start_calls
    location, body = gbp_client.start_calls[0]
    assert location == "locations/location-retry"
    assert body["method"] == "EMAIL"


def test_verification_routes_are_tenant_scoped(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="tenant-a-verify-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="tenant-a-verify-admin",
        access_token="tenant-a-verify-token",
        refresh_token="tenant-a-verify-refresh",
        expires_in_seconds=3600,
    )

    other_business = Business(
        id=str(uuid4()),
        name="Other Verify Business",
        notification_phone="+13035559999",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    db_session.add(other_business)
    db_session.commit()
    _seed_principal(db_session, business_id=other_business.id, principal_id="tenant-b-verify-admin")
    _seed_provider_connection(
        db_session,
        business_id=other_business.id,
        principal_id="tenant-b-verify-admin",
        access_token="tenant-b-verify-token",
        refresh_token="tenant-b-verify-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_by_token["tenant-a-verify-token"] = {"accounts": [{"name": "accounts/a", "accountName": "A"}]}
    gbp_client.accounts_by_token["tenant-b-verify-token"] = {"accounts": [{"name": "accounts/b", "accountName": "B"}]}
    gbp_client.locations_by_account["accounts/a"] = {"locations": [{"name": "locations/shared-location", "title": "A"}]}
    gbp_client.locations_by_account["accounts/b"] = {"locations": [{"name": "locations/shared-location", "title": "B"}]}
    gbp_client.options_by_location["locations/shared-location"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    tenant_a_client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="tenant-a-verify-admin",
    )
    tenant_b_client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=other_business.id,
        principal_id="tenant-b-verify-admin",
    )

    tenant_a_response = tenant_a_client.get(
        "/api/integrations/google/business-profile/locations/shared-location/verification/status"
    )
    tenant_b_response = tenant_b_client.get(
        "/api/integrations/google/business-profile/locations/shared-location/verification/status"
    )
    assert tenant_a_response.status_code == 200
    assert tenant_b_response.status_code == 200


def test_verification_start_fails_closed_when_refresh_fails(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-refresh-fail-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-refresh-fail-admin",
        access_token="expired-access-token",
        refresh_token="refresh-fail-token",
        expires_in_seconds=-60,
    )

    oauth_client = _StubGoogleOAuthClient()
    oauth_client.refresh_map["refresh-fail-token"] = GoogleOAuthError("invalid_grant")
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-refresh-fail")
    gbp_client.options_by_location["locations/location-refresh-fail"] = {
        "verificationOptions": [{"verificationMethod": "EMAIL", "emailAddress": "owner@example.com"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-refresh-fail-admin",
    )

    response = client.post(
        "/api/integrations/google/business-profile/locations/location-refresh-fail/verification/start",
        json={"selected_method": "email"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "reconnect_required"
    assert detail["reconnect_required"] is True
    _assert_guidance_contract(detail["guidance"])


def test_verification_options_reports_insufficient_scope(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_auth_env(monkeypatch, default_business_id=seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="verify-scope-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="verify-scope-admin",
        access_token="scope-access-token",
        refresh_token="scope-refresh-token",
        expires_in_seconds=3600,
        scopes="openid email",
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    _seed_location_catalog(gbp_client, account_id="1", location_id="location-scope")

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="verify-scope-admin",
    )

    response = client.get("/api/integrations/google/business-profile/locations/location-scope/verification/options")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "insufficient_scope"
    assert detail["reconnect_required"] is True
    _assert_guidance_contract(detail["guidance"])

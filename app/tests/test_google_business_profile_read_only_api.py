from __future__ import annotations

from datetime import timedelta
import json
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


class _StubGoogleOAuthClient:
    def __init__(self) -> None:
        self.refresh_map: dict[str, GoogleOAuthTokenResponse | Exception] = {}
        self.refresh_calls: list[str] = []

    def build_auth_url(self, **_: object) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth"

    def exchange_code_for_tokens(self, **_: object) -> GoogleOAuthTokenResponse:
        raise GoogleOAuthError("exchange flow is not used in read-only API tests")

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
        self.accounts_error: Exception | None = None
        self.locations_by_account: dict[str, dict[str, object] | Exception] = {}
        self.voice_by_location: dict[str, dict[str, object] | Exception] = {}
        self.verifications_by_location: dict[str, dict[str, object] | Exception] = {}
        self.options_by_location: dict[str, dict[str, object] | Exception] = {}
        self.list_accounts_calls: list[str] = []
        self.list_locations_calls: list[tuple[str, str]] = []
        self.voice_calls: list[tuple[str, str]] = []
        self.verifications_calls: list[tuple[str, str]] = []
        self.options_calls: list[tuple[str, str]] = []

    def list_accounts(self, *, access_token: str) -> dict[str, object]:
        self.list_accounts_calls.append(access_token)
        if self.accounts_error is not None:
            raise self.accounts_error
        by_token = self.accounts_by_token.get(access_token)
        if by_token is not None:
            return by_token
        return self.accounts_payload

    def list_locations(self, *, access_token: str, account_resource_name: str) -> dict[str, object]:
        self.list_locations_calls.append((access_token, account_resource_name))
        result = self.locations_by_account.get(account_resource_name, {"locations": []})
        if isinstance(result, Exception):
            raise result
        return result

    def get_voice_of_merchant_state(
        self,
        *,
        access_token: str,
        location_resource_name: str,
    ) -> dict[str, object]:
        self.voice_calls.append((access_token, location_resource_name))
        result = self.voice_by_location.get(location_resource_name, {})
        if isinstance(result, Exception):
            raise result
        return result

    def list_verifications(self, *, access_token: str, location_resource_name: str) -> dict[str, object]:
        self.verifications_calls.append((access_token, location_resource_name))
        result = self.verifications_by_location.get(location_resource_name, {"verifications": []})
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_verification_options(self, *, access_token: str, location_resource_name: str) -> dict[str, object]:
        self.options_calls.append((access_token, location_resource_name))
        result = self.options_by_location.get(location_resource_name, {"verificationOptions": []})
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _set_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("APP_ENV", "test")
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


def test_google_business_profile_accounts_mapping_contract(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-admin",
        access_token="usable-access-token",
        refresh_token="usable-refresh-token",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_payload = {
        "accounts": [
            {
                "name": "accounts/12345",
                "accountName": "Main Account",
            }
        ]
    }
    gbp_client.locations_by_account["accounts/12345"] = {
        "locations": [
            {"name": "locations/location-verified", "title": "Verified HQ"},
            {"name": "locations/location-pending", "title": "Pending Branch"},
            {"name": "locations/location-unverified", "title": "New Branch"},
            {"name": "locations/location-access", "title": "Access Issue"},
        ]
    }
    gbp_client.voice_by_location["locations/location-verified"] = {"hasVoiceOfMerchant": True}
    gbp_client.voice_by_location["locations/location-pending"] = {"hasVoiceOfMerchant": False}
    gbp_client.voice_by_location["locations/location-unverified"] = {"hasVoiceOfMerchant": False}
    gbp_client.voice_by_location["locations/location-access"] = GoogleBusinessProfileAPIError(
        "permission denied",
        status_code=403,
        error_status="PERMISSION_DENIED",
    )
    gbp_client.verifications_by_location["locations/location-pending"] = {
        "verifications": [
            {"name": "locations/location-pending/verifications/1", "state": "PENDING", "method": "PHONE_CALL"}
        ]
    }
    gbp_client.verifications_by_location["locations/location-unverified"] = {"verifications": []}
    gbp_client.verifications_by_location["locations/location-access"] = GoogleBusinessProfileAPIError(
        "permission denied",
        status_code=403,
        error_status="PERMISSION_DENIED",
    )
    gbp_client.options_by_location["locations/location-pending"] = {"verificationOptions": [{"method": "PHONE_CALL"}]}
    gbp_client.options_by_location["locations/location-unverified"] = {"verificationOptions": [{"method": "MAIL"}]}
    gbp_client.options_by_location["locations/location-access"] = GoogleBusinessProfileAPIError(
        "permission denied",
        status_code=403,
        error_status="PERMISSION_DENIED",
    )

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-admin",
    )

    response = client.get("/api/integrations/google/business-profile/accounts")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["accounts"]) == 1
    account = payload["accounts"][0]
    assert account["account_id"] == "12345"
    assert account["account_name"] == "Main Account"
    assert len(account["locations"]) == 4

    locations_by_id = {item["location_id"]: item for item in account["locations"]}
    assert locations_by_id["location-verified"]["verification"]["state_summary"] == "verified"
    assert locations_by_id["location-verified"]["verification"]["recommended_next_action"] == "none"
    assert locations_by_id["location-pending"]["verification"]["state_summary"] == "pending"
    assert locations_by_id["location-pending"]["verification"]["recommended_next_action"] == "complete_pending"
    assert locations_by_id["location-unverified"]["verification"]["state_summary"] == "unverified"
    assert locations_by_id["location-unverified"]["verification"]["recommended_next_action"] == "start_verification"
    assert locations_by_id["location-access"]["verification"]["state_summary"] == "unknown"
    assert locations_by_id["location-access"]["verification"]["recommended_next_action"] == "resolve_access"


def test_google_business_profile_accounts_and_locations_handle_empty_data(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-empty")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-empty",
        access_token="empty-token",
        refresh_token="empty-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_payload = {"accounts": []}
    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-empty",
    )

    accounts = client.get("/api/integrations/google/business-profile/accounts")
    assert accounts.status_code == 200
    assert accounts.json() == {"accounts": []}

    locations = client.get("/api/integrations/google/business-profile/locations")
    assert locations.status_code == 200
    assert locations.json() == {"locations": []}


def test_google_business_profile_locations_handles_account_without_locations(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-no-locations")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-no-locations",
        access_token="no-locations-token",
        refresh_token="no-locations-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_payload = {"accounts": [{"name": "accounts/1", "accountName": "Solo"}]}
    gbp_client.locations_by_account["accounts/1"] = {"locations": []}
    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-no-locations",
    )

    locations = client.get("/api/integrations/google/business-profile/locations")
    assert locations.status_code == 200
    assert locations.json() == {"locations": []}


def test_google_business_profile_accounts_permission_error_surfaces_403(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-permission")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-permission",
        access_token="permission-token",
        refresh_token="permission-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_error = GoogleBusinessProfileAPIError(
        "permission denied",
        status_code=403,
        error_status="PERMISSION_DENIED",
    )
    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-permission",
    )

    response = client.get("/api/integrations/google/business-profile/accounts")
    assert response.status_code == 403
    assert "denied" in str(response.json()["detail"]).lower()


def test_google_business_profile_accounts_refreshes_expired_token_before_api_call(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-refresh")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-refresh",
        access_token="expired-access-token",
        refresh_token="refresh-token",
        expires_in_seconds=-60,
    )

    oauth_client = _StubGoogleOAuthClient()
    oauth_client.refresh_map["refresh-token"] = GoogleOAuthTokenResponse(
        access_token="refreshed-access-token",
        token_type="Bearer",
        expires_in=3600,
        refresh_token=None,
        scope="https://www.googleapis.com/auth/business.manage",
        id_token_subject=None,
        id_token_email=None,
    )
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_by_token["refreshed-access-token"] = {
        "accounts": [{"name": "accounts/999", "accountName": "Refreshed"}]
    }
    gbp_client.locations_by_account["accounts/999"] = {"locations": []}

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-refresh",
    )
    response = client.get("/api/integrations/google/business-profile/accounts")
    assert response.status_code == 200, response.text
    assert oauth_client.refresh_calls == ["refresh-token"]
    assert gbp_client.list_accounts_calls == ["refreshed-access-token"]


def test_google_business_profile_accounts_reconnect_required_when_refresh_fails(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-refresh-fail")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-refresh-fail",
        access_token="expired-access-token",
        refresh_token="refresh-token-fail",
        expires_in_seconds=-60,
    )

    oauth_client = _StubGoogleOAuthClient()
    oauth_client.refresh_map["refresh-token-fail"] = GoogleOAuthError("invalid_grant")
    gbp_client = _StubGoogleBusinessProfileClient()
    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-refresh-fail",
    )

    response = client.get("/api/integrations/google/business-profile/accounts")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reconnect_required"] is True
    assert "reconnect" in detail["message"].lower()


def test_google_business_profile_accounts_are_tenant_scoped(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="tenant-a-admin")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="tenant-a-admin",
        access_token="tenant-a-token",
        refresh_token="tenant-a-refresh",
        expires_in_seconds=3600,
    )

    other_business = Business(
        id=str(uuid4()),
        name="Other Business",
        notification_phone="+13035559999",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    db_session.add(other_business)
    db_session.commit()
    _seed_principal(db_session, business_id=other_business.id, principal_id="tenant-b-admin")
    _seed_provider_connection(
        db_session,
        business_id=other_business.id,
        principal_id="tenant-b-admin",
        access_token="tenant-b-token",
        refresh_token="tenant-b-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_by_token["tenant-a-token"] = {"accounts": [{"name": "accounts/a", "accountName": "A"}]}
    gbp_client.accounts_by_token["tenant-b-token"] = {"accounts": [{"name": "accounts/b", "accountName": "B"}]}
    gbp_client.locations_by_account["accounts/a"] = {"locations": []}
    gbp_client.locations_by_account["accounts/b"] = {"locations": []}

    tenant_a_client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="tenant-a-admin",
    )
    tenant_b_client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=other_business.id,
        principal_id="tenant-b-admin",
    )

    tenant_a_response = tenant_a_client.get("/api/integrations/google/business-profile/accounts")
    tenant_b_response = tenant_b_client.get("/api/integrations/google/business-profile/accounts")
    assert tenant_a_response.status_code == 200
    assert tenant_b_response.status_code == 200
    assert tenant_a_response.json()["accounts"][0]["account_id"] == "a"
    assert tenant_b_response.json()["accounts"][0]["account_id"] == "b"


def test_google_business_profile_location_verification_not_found(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="gbp-lookup")
    _seed_provider_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="gbp-lookup",
        access_token="lookup-token",
        refresh_token="lookup-refresh",
        expires_in_seconds=3600,
    )

    oauth_client = _StubGoogleOAuthClient()
    gbp_client = _StubGoogleBusinessProfileClient()
    gbp_client.accounts_payload = {"accounts": [{"name": "accounts/lookup", "accountName": "Lookup"}]}
    gbp_client.locations_by_account["accounts/lookup"] = {
        "locations": [{"name": "locations/known-location", "title": "Known"}]
    }

    client = _make_integrations_client(
        db_session,
        oauth_client=oauth_client,
        gbp_client=gbp_client,
        business_id=seeded_business.id,
        principal_id="gbp-lookup",
    )
    response = client.get("/api/integrations/google/business-profile/locations/missing-location/verification")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert detail["reconnect_required"] is False
    assert isinstance(detail["guidance"], dict)

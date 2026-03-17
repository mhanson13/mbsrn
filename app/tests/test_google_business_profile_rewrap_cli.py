from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest

from app.cli import rewrap_gbp_tokens as rewrap_cli
from app.core.config import get_settings
from app.core.time import utc_now
from app.core.token_cipher import FernetTokenCipher
from app.models.business import Business
from app.models.principal import Principal, PrincipalRole
from app.models.provider_connection import ProviderConnection


class _SessionContext:
    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _patch_cli_session(monkeypatch: pytest.MonkeyPatch, db_session) -> None:
    monkeypatch.setattr(rewrap_cli, "SessionLocal", lambda: _SessionContext(db_session))


def _set_rewrap_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    active_key_version: str,
    keyring: dict[str, str],
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION", active_key_version)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON", json.dumps(keyring))
    monkeypatch.setenv("GOOGLE_BUSINESS_PROFILE_REDIRECT_URI", "https://operator.workboots.example/callback")
    monkeypatch.setenv("GOOGLE_BUSINESS_PROFILE_STATE_TTL_SECONDS", "600")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_SKEW_SECONDS", "120")


def _seed_principal(db_session, *, business_id: str, principal_id: str) -> None:
    db_session.add(
        Principal(
            business_id=business_id,
            id=principal_id,
            display_name=principal_id,
            role=PrincipalRole.ADMIN,
            is_active=True,
        )
    )
    db_session.commit()


def _seed_business(db_session, *, name: str) -> Business:
    business = Business(
        id=str(uuid4()),
        name=name,
        notification_phone="+13035558888",
        notification_email=f"{name.lower().replace(' ', '')}@example.com",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    db_session.add(business)
    db_session.commit()
    return business


def _seed_connection(
    db_session,
    *,
    business_id: str,
    principal_id: str,
    provider_cipher: FernetTokenCipher,
    token_key_version: str,
    access_token: str | None = "access-token",
    refresh_token: str | None = "refresh-token",
    is_active: bool = True,
    disconnected: bool = False,
) -> ProviderConnection:
    now = utc_now()
    connection = ProviderConnection(
        id=str(uuid4()),
        provider="google_business_profile",
        business_id=business_id,
        principal_id=principal_id,
        created_by_principal_id=principal_id,
        updated_by_principal_id=principal_id,
        granted_scopes="https://www.googleapis.com/auth/business.manage",
        token_key_version=token_key_version,
        access_token_encrypted=provider_cipher.encrypt(access_token) if access_token else None,
        refresh_token_encrypted=provider_cipher.encrypt(refresh_token) if refresh_token else None,
        access_token_expires_at=now + timedelta(hours=1),
        is_active=is_active,
        connected_at=now,
        last_refreshed_at=now,
        disconnected_at=now if disconnected else None,
    )
    db_session.add(connection)
    db_session.commit()
    return connection


def test_rewrap_cli_dry_run_all_reports_counts(db_session, seeded_business, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v1": "legacy-key", "v2": "active-key"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-a")
    business_current = _seed_business(db_session, name="Current Key Business")
    _seed_principal(db_session, business_id=business_current.id, principal_id="admin-current")
    business_inactive = _seed_business(db_session, name="Inactive Connection Business")
    _seed_principal(db_session, business_id=business_inactive.id, principal_id="admin-inactive")
    business_empty_tokens = _seed_business(db_session, name="Empty Token Business")
    _seed_principal(db_session, business_id=business_empty_tokens.id, principal_id="admin-empty")
    cipher_v1 = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})
    cipher_v2 = FernetTokenCipher(active_key_version="v2", keyring={"v2": "active-key"})

    _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-a",
        provider_cipher=cipher_v1,
        token_key_version="v1",
    )
    _seed_connection(
        db_session,
        business_id=business_current.id,
        principal_id="admin-current",
        provider_cipher=cipher_v2,
        token_key_version="v2",
    )
    _seed_connection(
        db_session,
        business_id=business_inactive.id,
        principal_id="admin-inactive",
        provider_cipher=cipher_v1,
        token_key_version="v1",
        is_active=False,
    )
    _seed_connection(
        db_session,
        business_id=business_empty_tokens.id,
        principal_id="admin-empty",
        provider_cipher=cipher_v1,
        token_key_version="v1",
        access_token=None,
        refresh_token=None,
    )

    summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=True,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    assert summary["mode"] == "dry_run"
    assert summary["scope"] == "all"
    assert summary["scanned"] == 4
    assert summary["eligible"] == 1
    assert summary["rewrapped"] == 0
    assert summary["already_current"] == 1
    assert summary["skipped"] == 2
    assert summary["failed"] == 0
    assert summary["failures"] == []


def test_rewrap_cli_dry_run_business_scope_filters(
    db_session, seeded_business, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v1": "legacy-key", "v2": "active-key"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-a")
    other_business = _seed_business(db_session, name="Other Business")
    _seed_principal(db_session, business_id=other_business.id, principal_id="admin-b")
    cipher_v1 = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})

    _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-a",
        provider_cipher=cipher_v1,
        token_key_version="v1",
    )
    _seed_connection(
        db_session,
        business_id=other_business.id,
        principal_id="admin-b",
        provider_cipher=cipher_v1,
        token_key_version="v1",
    )

    summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=True,
        all_connections=False,
        business_id=seeded_business.id,
        tenant_id=None,
    )
    assert summary["scope"] == "business"
    assert summary["business_id"] == seeded_business.id
    assert summary["scanned"] == 1
    assert summary["eligible"] == 1

    tenant_summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=True,
        all_connections=False,
        business_id=None,
        tenant_id=seeded_business.id,
    )
    assert tenant_summary["scope"] == "business"
    assert tenant_summary["tenant_id"] == seeded_business.id
    assert tenant_summary["business_id"] == seeded_business.id


def test_rewrap_cli_execute_rewraps_only_outdated_rows(
    db_session, seeded_business, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v1": "legacy-key", "v2": "active-key"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-exec")
    current_business = _seed_business(db_session, name="Current Execute Business")
    _seed_principal(db_session, business_id=current_business.id, principal_id="admin-exec-current")
    cipher_v1 = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})
    cipher_v2 = FernetTokenCipher(active_key_version="v2", keyring={"v2": "active-key"})
    outdated = _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-exec",
        provider_cipher=cipher_v1,
        token_key_version="v1",
        access_token="outdated-access",
        refresh_token="outdated-refresh",
    )
    _seed_connection(
        db_session,
        business_id=current_business.id,
        principal_id="admin-exec-current",
        provider_cipher=cipher_v2,
        token_key_version="v2",
        access_token="current-access",
        refresh_token="current-refresh",
    )

    summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=False,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    assert summary["mode"] == "execute"
    assert summary["rewrapped"] == 1
    assert summary["already_current"] == 1
    assert summary["failed"] == 0

    db_session.expire_all()
    refreshed = db_session.get(ProviderConnection, outdated.id)
    assert refreshed is not None
    assert refreshed.token_key_version == "v2"
    active_cipher = FernetTokenCipher(active_key_version="v2", keyring={"v1": "legacy-key", "v2": "active-key"})
    assert active_cipher.decrypt(refreshed.access_token_encrypted or "", key_version="v2") == "outdated-access"
    assert active_cipher.decrypt(refreshed.refresh_token_encrypted or "", key_version="v2") == "outdated-refresh"


def test_rewrap_cli_reports_missing_legacy_key_version_failure(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v2": "active-key-only"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-missing-key")
    legacy_cipher = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})
    _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-missing-key",
        provider_cipher=legacy_cipher,
        token_key_version="v1",
    )

    summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=True,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    assert summary["eligible"] == 1
    assert summary["failed"] == 1
    failures = summary["failures"]
    assert isinstance(failures, list)
    assert failures[0]["reason"] == "missing_key_version"


def test_rewrap_cli_skips_tombstoned_rows(db_session, seeded_business, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v1": "legacy-key", "v2": "active-key"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-skip")
    cipher_v1 = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})
    _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-skip",
        provider_cipher=cipher_v1,
        token_key_version="v1",
        is_active=False,
        disconnected=True,
    )

    summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=False,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    assert summary["eligible"] == 0
    assert summary["skipped"] == 1
    assert summary["rewrapped"] == 0


def test_rewrap_cli_is_idempotent_on_second_run(db_session, seeded_business, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v1": "legacy-key", "v2": "active-key"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-idempotent")
    cipher_v1 = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})
    _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-idempotent",
        provider_cipher=cipher_v1,
        token_key_version="v1",
    )

    first = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=False,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    second = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=False,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    assert first["rewrapped"] == 1
    assert second["rewrapped"] == 0
    assert second["already_current"] == 1


def test_rewrap_cli_summary_does_not_include_token_material(
    db_session,
    seeded_business,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cli_session(monkeypatch, db_session)
    _set_rewrap_env(
        monkeypatch,
        active_key_version="v2",
        keyring={"v1": "legacy-key", "v2": "active-key"},
    )
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="admin-safe-summary")
    cipher_v1 = FernetTokenCipher(active_key_version="v1", keyring={"v1": "legacy-key"})
    _seed_connection(
        db_session,
        business_id=seeded_business.id,
        principal_id="admin-safe-summary",
        provider_cipher=cipher_v1,
        token_key_version="v1",
        access_token="very-secret-access-token-value",
        refresh_token="very-secret-refresh-token-value",
    )

    summary = rewrap_cli.run_rewrap_gbp_tokens(
        dry_run=True,
        all_connections=True,
        business_id=None,
        tenant_id=None,
    )
    rendered = json.dumps(summary)
    assert "very-secret-access-token-value" not in rendered
    assert "very-secret-refresh-token-value" not in rendered

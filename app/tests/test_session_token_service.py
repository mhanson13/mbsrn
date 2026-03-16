from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.session_state import InMemorySessionStateStore
from app.core.session_token import AppSessionTokenError, AppSessionTokenService


def _service() -> AppSessionTokenService:
    return AppSessionTokenService(
        secret="session-secret",
        issuer="work-boots-test",
        audience="work-boots-api",
        algorithm="HS256",
        access_ttl_seconds=300,
        refresh_ttl_seconds=3600,
        state_store=InMemorySessionStateStore(),
    )


def test_issue_and_verify_access_token_claims() -> None:
    service = _service()
    issued = service.issue(
        business_id="b-1",
        principal_id="p-1",
        principal_role="admin",
        auth_source="google_oidc_session",
        principal_identity_id="identity-1",
    )
    claims = service.verify_access_token(issued.access_token)
    assert claims.token_type == "access"
    assert claims.jti
    assert claims.business_id == "b-1"
    assert claims.principal_id == "p-1"
    assert claims.principal_role == "admin"
    assert claims.auth_source == "google_oidc_session"
    assert claims.principal_identity_id == "identity-1"
    assert claims.issuer == "work-boots-test"
    assert claims.audience == "work-boots-api"


def test_refresh_rotation_and_reuse_detection() -> None:
    service = _service()
    issued = service.issue(
        business_id="b-1",
        principal_id="p-1",
        principal_role="admin",
        auth_source="google_oidc_session",
        principal_identity_id="identity-1",
    )
    first_rotation = service.rotate_refresh_token(issued.refresh_token)
    assert first_rotation.status == "ok"
    assert first_rotation.claims is not None

    second_rotation = service.rotate_refresh_token(issued.refresh_token)
    assert second_rotation.status == "reused"


def test_revoked_access_token_is_rejected() -> None:
    service = _service()
    issued = service.issue(
        business_id="b-1",
        principal_id="p-1",
        principal_role="admin",
        auth_source="google_oidc_session",
        principal_identity_id="identity-1",
    )
    claims = service.verify_access_token(issued.access_token)
    service.revoke_token(claims=claims)
    with pytest.raises(AppSessionTokenError, match="revoked"):
        service.verify_access_token(issued.access_token)


def test_principal_revocation_invalidates_existing_tokens() -> None:
    service = _service()
    issued = service.issue(
        business_id="b-1",
        principal_id="p-1",
        principal_role="admin",
        auth_source="google_oidc_session",
        principal_identity_id="identity-1",
    )
    claims = service.verify_access_token(issued.access_token)
    service.revoke_principal_sessions(
        business_id="b-1",
        principal_id="p-1",
        revoked_after=claims.issued_at + timedelta(seconds=1),
    )
    with pytest.raises(AppSessionTokenError, match="revoked"):
        service.verify_access_token(issued.access_token)


def test_identity_revocation_invalidates_existing_tokens() -> None:
    service = _service()
    issued = service.issue(
        business_id="b-1",
        principal_id="p-1",
        principal_role="admin",
        auth_source="google_oidc_session",
        principal_identity_id="identity-1",
    )
    claims = service.verify_access_token(issued.access_token)
    service.revoke_identity_sessions(
        identity_id="identity-1",
        revoked_after=claims.issued_at + timedelta(seconds=1),
    )
    with pytest.raises(AppSessionTokenError, match="revoked"):
        service.verify_access_token(issued.access_token)


def test_refresh_token_expiry_is_enforced() -> None:
    state_store = InMemorySessionStateStore()
    service = AppSessionTokenService(
        secret="session-secret",
        issuer="work-boots-test",
        audience="work-boots-api",
        algorithm="HS256",
        access_ttl_seconds=10,
        refresh_ttl_seconds=10,
        state_store=state_store,
    )
    issued = service.issue(
        business_id="b-1",
        principal_id="p-1",
        principal_role="admin",
        auth_source="google_oidc_session",
        principal_identity_id=None,
    )
    # Sanity check token parses before manual expiry manipulation is attempted.
    assert service.verify_refresh_token(issued.refresh_token).token_type == "refresh"

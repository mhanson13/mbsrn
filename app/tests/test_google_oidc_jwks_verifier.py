from __future__ import annotations

import pytest

import app.integrations.google_auth as google_auth_module
from app.integrations.google_auth import GoogleOIDCJWKSVerifier, GoogleOIDCVerificationError


def test_jwks_verifier_validates_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = GoogleOIDCJWKSVerifier(
        client_id="google-client-id",
        jwks_url="https://example.test/jwks",
        allowed_issuers=("https://accounts.google.com",),
        require_email_verified=True,
    )

    monkeypatch.setattr(google_auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(
        verifier,
        "_fetch_jwks",
        lambda: {"keys": [{"kid": "kid-1", "kty": "RSA", "n": "abc", "e": "AQAB"}]},
    )
    monkeypatch.setattr(google_auth_module.RSAAlgorithm, "from_jwk", lambda jwk: object())
    monkeypatch.setattr(
        google_auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "iss": "https://accounts.google.com",
            "aud": "google-client-id",
            "sub": "sub-123",
            "email": "USER@example.com",
            "email_verified": True,
            "name": "User",
            "exp": 1893456000,
            "iat": 1893452400,
        },
    )

    claims = verifier.verify_id_token("id-token")
    assert claims.provider == "google"
    assert claims.subject == "sub-123"
    assert claims.email == "user@example.com"
    assert claims.email_verified is True


def test_jwks_verifier_rejects_invalid_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = GoogleOIDCJWKSVerifier(
        client_id="google-client-id",
        allowed_issuers=("https://accounts.google.com",),
    )
    monkeypatch.setattr(google_auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(
        verifier,
        "_fetch_jwks",
        lambda: {"keys": [{"kid": "kid-1", "kty": "RSA", "n": "abc", "e": "AQAB"}]},
    )
    monkeypatch.setattr(google_auth_module.RSAAlgorithm, "from_jwk", lambda jwk: object())
    monkeypatch.setattr(
        google_auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "iss": "https://issuer.example.com",
            "aud": "google-client-id",
            "sub": "sub-123",
            "email_verified": True,
            "exp": 1893456000,
            "iat": 1893452400,
        },
    )
    with pytest.raises(GoogleOIDCVerificationError, match="issuer"):
        verifier.verify_id_token("id-token")


def test_jwks_verifier_rejects_unverified_email_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = GoogleOIDCJWKSVerifier(
        client_id="google-client-id",
        allowed_issuers=("https://accounts.google.com",),
        require_email_verified=True,
    )
    monkeypatch.setattr(google_auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(
        verifier,
        "_fetch_jwks",
        lambda: {"keys": [{"kid": "kid-1", "kty": "RSA", "n": "abc", "e": "AQAB"}]},
    )
    monkeypatch.setattr(google_auth_module.RSAAlgorithm, "from_jwk", lambda jwk: object())
    monkeypatch.setattr(
        google_auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "iss": "https://accounts.google.com",
            "aud": "google-client-id",
            "sub": "sub-123",
            "email_verified": False,
            "exp": 1893456000,
            "iat": 1893452400,
        },
    )
    with pytest.raises(GoogleOIDCVerificationError, match="email is not verified"):
        verifier.verify_id_token("id-token")


def test_jwks_verifier_requires_kid_header(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = GoogleOIDCJWKSVerifier(client_id="google-client-id")
    monkeypatch.setattr(google_auth_module.jwt, "get_unverified_header", lambda token: {})
    with pytest.raises(GoogleOIDCVerificationError, match="key id"):
        verifier.verify_id_token("id-token")

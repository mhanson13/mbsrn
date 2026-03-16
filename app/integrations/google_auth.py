from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import jwt
from jwt import InvalidTokenError

try:
    from jwt.algorithms import RSAAlgorithm
except ImportError:  # pragma: no cover - optional crypto dependency may be missing in some local environments
    class RSAAlgorithm:  # type: ignore[override]
        @staticmethod
        def from_jwk(_jwk: str):
            raise GoogleOIDCVerificationError(
                "Google token verification failed: RSA JWT verification support is unavailable."
            )


class GoogleOIDCVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class GoogleIdentityClaims:
    provider: str
    subject: str
    email: str | None
    email_verified: bool
    issuer: str
    audience: str
    display_name: str | None


class GoogleOIDCJWKSVerifier:
    """Google ID token verification using JWKS signature validation."""

    def __init__(
        self,
        *,
        client_id: str,
        jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs",
        allowed_issuers: tuple[str, ...] = ("https://accounts.google.com", "accounts.google.com"),
        timeout_seconds: int = 5,
        require_email_verified: bool = True,
    ) -> None:
        self.client_id = client_id.strip()
        self.jwks_url = jwks_url.rstrip("/")
        self.allowed_issuers = tuple(issuer.strip() for issuer in allowed_issuers if issuer.strip())
        self.timeout_seconds = timeout_seconds
        self.require_email_verified = require_email_verified
        self._cached_jwks_by_kid: dict[str, dict[str, Any]] = {}

    def verify_id_token(self, id_token: str) -> GoogleIdentityClaims:
        token = id_token.strip()
        if not token:
            raise GoogleOIDCVerificationError("id_token is required.")

        try:
            unverified_header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise GoogleOIDCVerificationError("Invalid Google ID token header.") from exc

        kid = str(unverified_header.get("kid") or "").strip()
        if not kid:
            raise GoogleOIDCVerificationError("Google ID token missing key id.")

        jwk = self._cached_jwks_by_kid.get(kid)
        if jwk is None:
            jwk = self._fetch_jwk_by_kid(kid)

        try:
            public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
            payload = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
        except InvalidTokenError as exc:
            raise GoogleOIDCVerificationError("Google token verification failed.") from exc

        issuer = str(payload.get("iss") or "").strip()
        if issuer not in self.allowed_issuers:
            raise GoogleOIDCVerificationError("Invalid Google token issuer.")

        audience = str(payload.get("aud") or "").strip()
        if audience != self.client_id:
            raise GoogleOIDCVerificationError("Google token audience mismatch.")

        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise GoogleOIDCVerificationError("Google token missing subject claim.")

        email_raw = payload.get("email")
        email = str(email_raw).strip().lower() if email_raw else None
        email_verified = _coerce_bool(payload.get("email_verified"))
        if self.require_email_verified and not email_verified:
            raise GoogleOIDCVerificationError("Google account email is not verified.")

        display_name = str(payload.get("name") or "").strip() or None
        return GoogleIdentityClaims(
            provider="google",
            subject=subject,
            email=email,
            email_verified=email_verified,
            issuer=issuer,
            audience=audience,
            display_name=display_name,
        )

    def _fetch_jwk_by_kid(self, kid: str) -> dict[str, Any]:
        jwks = self._fetch_jwks()
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise GoogleOIDCVerificationError("Google JWKS response missing keys.")
        refreshed: dict[str, dict[str, Any]] = {}
        for item in keys:
            if isinstance(item, dict):
                item_kid = str(item.get("kid") or "").strip()
                if item_kid:
                    refreshed[item_kid] = item
        self._cached_jwks_by_kid = refreshed
        jwk = refreshed.get(kid)
        if jwk is None:
            raise GoogleOIDCVerificationError("Google signing key not found for token.")
        return jwk

    def _fetch_jwks(self) -> dict[str, Any]:
        try:
            with urlopen(self.jwks_url, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GoogleOIDCVerificationError(f"Google JWKS fetch failed: {exc.reason}") from exc
        except URLError as exc:
            raise GoogleOIDCVerificationError(f"Google JWKS unavailable: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GoogleOIDCVerificationError("Google JWKS fetch failed.") from exc
        if not isinstance(payload, dict):
            raise GoogleOIDCVerificationError("Google JWKS response is invalid.")
        return payload


# Backward-compatible alias kept to minimize import churn.
GoogleOIDCTokenInfoVerifier = GoogleOIDCJWKSVerifier


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

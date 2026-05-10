from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from jwt import InvalidTokenError

from app.core.session_state import SessionStateStore


class GoogleLoginStateValidationError(ValueError):
    def __init__(self, message: str, *, error_code: str = "invalid_oauth_state") -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class GoogleLoginStateChallenge:
    state: str
    expires_at: datetime


class GoogleLoginStateService:
    TOKEN_TYPE = "google_login_state"
    FLOW_INTENT = "google_login_exchange"

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        algorithm: str,
        ttl_seconds: int,
        state_store: SessionStateStore,
    ) -> None:
        normalized_secret = (secret or "").strip()
        if not normalized_secret:
            raise GoogleLoginStateValidationError(
                "Google login state configuration is missing.",
                error_code="oauth_state_unavailable",
            )
        if ttl_seconds <= 0:
            raise GoogleLoginStateValidationError(
                "Google login state configuration is invalid.",
                error_code="oauth_state_unavailable",
            )
        self._secret = normalized_secret
        self._issuer = (issuer or "").strip()
        self._audience = (audience or "").strip()
        self._algorithm = (algorithm or "HS256").strip().upper()
        self._ttl_seconds = ttl_seconds
        self._state_store = state_store

    def issue_state(self, *, user_agent_fingerprint: str | None = None) -> GoogleLoginStateChallenge:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        jti = f"{self.TOKEN_TYPE}:{uuid4()}"
        payload: dict[str, object] = {
            "iss": self._issuer,
            "aud": self._audience,
            "typ": self.TOKEN_TYPE,
            "flow": self.FLOW_INTENT,
            "jti": jti,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        if user_agent_fingerprint:
            payload["uaf"] = user_agent_fingerprint
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return GoogleLoginStateChallenge(state=token, expires_at=expires_at)

    def validate_and_consume(
        self,
        *,
        state: str,
        user_agent_fingerprint: str | None = None,
    ) -> None:
        raw_state = (state or "").strip()
        if not raw_state:
            raise GoogleLoginStateValidationError(
                "OAuth state is required.",
                error_code="oauth_state_missing",
            )
        claims = self._decode_state(raw_state)
        token_type = str(claims.get("typ") or "").strip()
        if token_type != self.TOKEN_TYPE:
            raise GoogleLoginStateValidationError(
                "OAuth state is invalid or expired.",
                error_code="oauth_state_mismatch",
            )
        flow = str(claims.get("flow") or "").strip()
        if flow != self.FLOW_INTENT:
            raise GoogleLoginStateValidationError(
                "OAuth state is invalid or expired.",
                error_code="oauth_state_mismatch",
            )

        expected_fingerprint = str(claims.get("uaf") or "").strip() or None
        if expected_fingerprint is not None and user_agent_fingerprint != expected_fingerprint:
            raise GoogleLoginStateValidationError(
                "OAuth state is invalid or expired.",
                error_code="oauth_state_mismatch",
            )

        jti = str(claims.get("jti") or "").strip()
        exp_raw = claims.get("exp")
        if not jti or not isinstance(exp_raw, int):
            raise GoogleLoginStateValidationError(
                "OAuth state is invalid or expired.",
                error_code="oauth_state_invalid",
            )
        if self._state_store.is_jti_revoked(jti=jti):
            raise GoogleLoginStateValidationError(
                "OAuth state was already used.",
                error_code="oauth_state_replayed",
            )
        self._state_store.revoke_jti(jti=jti, expires_at_epoch=exp_raw)

    def _decode_state(self, state: str) -> dict[str, object]:
        try:
            payload = jwt.decode(
                state,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["iss", "aud", "typ", "flow", "jti", "iat", "nbf", "exp"],
                },
            )
        except InvalidTokenError as exc:
            raise GoogleLoginStateValidationError(
                "OAuth state is invalid or expired.",
                error_code="oauth_state_invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise GoogleLoginStateValidationError(
                "OAuth state is invalid or expired.",
                error_code="oauth_state_invalid",
            )
        return payload

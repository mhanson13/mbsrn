from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from jwt import InvalidTokenError

from app.core.session_state import (
    ConsumeRefreshStatus,
    RefreshTokenState,
    SessionStateStore,
    dt_to_epoch_seconds,
)


class AppSessionTokenError(ValueError):
    pass


@dataclass(frozen=True)
class AppSessionClaims:
    token_type: str
    jti: str
    business_id: str
    principal_id: str
    principal_role: str
    auth_source: str
    principal_identity_id: str | None
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    issuer: str
    audience: str


@dataclass(frozen=True)
class IssuedAppSessionTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


@dataclass(frozen=True)
class RefreshRotationResult:
    status: ConsumeRefreshStatus
    claims: AppSessionClaims | None = None


class AppSessionTokenService:
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        algorithm: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        state_store: SessionStateStore,
    ) -> None:
        normalized_secret = secret.strip()
        if not normalized_secret:
            raise AppSessionTokenError("APP_SESSION_SECRET is required for app session token operations.")
        if access_ttl_seconds <= 0:
            raise AppSessionTokenError("APP_SESSION_TTL_SECONDS must be greater than zero.")
        if refresh_ttl_seconds <= 0:
            raise AppSessionTokenError("APP_SESSION_REFRESH_TTL_SECONDS must be greater than zero.")
        self._secret = normalized_secret
        self._issuer = issuer.strip()
        self._audience = audience.strip()
        self._algorithm = algorithm.strip().upper()
        self._access_ttl_seconds = access_ttl_seconds
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._state_store = state_store

    def issue(
        self,
        *,
        business_id: str,
        principal_id: str,
        principal_role: str,
        auth_source: str,
        principal_identity_id: str | None = None,
    ) -> IssuedAppSessionTokens:
        now = datetime.now(timezone.utc)
        access_expires_at = now + timedelta(seconds=self._access_ttl_seconds)
        refresh_expires_at = now + timedelta(seconds=self._refresh_ttl_seconds)

        access_jti = str(uuid4())
        refresh_jti = str(uuid4())
        subject = self._build_subject(business_id=business_id, principal_id=principal_id)

        base_payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": subject,
            "pid": principal_id,
            "bid": business_id,
            "role": principal_role,
            "src": auth_source,
            "iat": dt_to_epoch_seconds(now),
            "nbf": dt_to_epoch_seconds(now),
        }
        if principal_identity_id:
            base_payload["iid"] = principal_identity_id

        access_payload = {
            **base_payload,
            "jti": access_jti,
            "typ": "access",
            "exp": dt_to_epoch_seconds(access_expires_at),
        }
        refresh_payload = {
            **base_payload,
            "jti": refresh_jti,
            "typ": "refresh",
            "exp": dt_to_epoch_seconds(refresh_expires_at),
        }

        access_token = jwt.encode(access_payload, self._secret, algorithm=self._algorithm)
        refresh_token = jwt.encode(refresh_payload, self._secret, algorithm=self._algorithm)
        self._state_store.put_refresh_state(
            RefreshTokenState(
                jti=refresh_jti,
                business_id=business_id,
                principal_id=principal_id,
                principal_identity_id=principal_identity_id,
                expires_at_epoch=dt_to_epoch_seconds(refresh_expires_at),
            )
        )
        return IssuedAppSessionTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )

    def verify_access_token(self, token: str) -> AppSessionClaims:
        claims = self._verify(token=token, expected_type="access")
        self._ensure_not_revoked(claims=claims)
        return claims

    def verify_refresh_token(self, token: str) -> AppSessionClaims:
        claims = self._verify(token=token, expected_type="refresh")
        self._ensure_not_revoked(claims=claims)
        return claims

    def rotate_refresh_token(self, refresh_token: str) -> RefreshRotationResult:
        claims = self._verify(token=refresh_token, expected_type="refresh")
        self._ensure_subject_not_revoked(claims=claims)
        if self._state_store.is_jti_revoked(jti=claims.jti):
            return RefreshRotationResult(status="reused", claims=claims)
        consume = self._state_store.consume_refresh_state(
            jti=claims.jti,
            revoke_until_epoch=dt_to_epoch_seconds(claims.expires_at),
        )
        return RefreshRotationResult(status=consume.status, claims=claims)

    def revoke_token(self, *, claims: AppSessionClaims) -> None:
        self._state_store.revoke_jti(jti=claims.jti, expires_at_epoch=dt_to_epoch_seconds(claims.expires_at))

    def revoke_principal_sessions(
        self, *, business_id: str, principal_id: str, revoked_after: datetime | None = None
    ) -> None:
        cutoff = revoked_after or datetime.now(timezone.utc)
        self._state_store.set_principal_revoked_after(
            business_id=business_id,
            principal_id=principal_id,
            issued_after_epoch=dt_to_epoch_seconds(cutoff),
        )

    def revoke_identity_sessions(self, *, identity_id: str, revoked_after: datetime | None = None) -> None:
        cutoff = revoked_after or datetime.now(timezone.utc)
        self._state_store.set_identity_revoked_after(
            identity_id=identity_id,
            issued_after_epoch=dt_to_epoch_seconds(cutoff),
        )

    def issue_from_refresh(
        self,
        *,
        refresh_claims: AppSessionClaims,
        principal_role: str,
        auth_source: str,
    ) -> IssuedAppSessionTokens:
        return self.issue(
            business_id=refresh_claims.business_id,
            principal_id=refresh_claims.principal_id,
            principal_role=principal_role,
            auth_source=auth_source,
            principal_identity_id=refresh_claims.principal_identity_id,
        )

    def _verify(self, *, token: str, expected_type: str) -> AppSessionClaims:
        raw = token.strip()
        if not raw:
            raise AppSessionTokenError("App session token is required.")
        try:
            payload = jwt.decode(
                raw,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti", "typ", "pid", "bid", "role", "src"],
                },
            )
        except InvalidTokenError as exc:
            raise AppSessionTokenError("Invalid app session token.") from exc

        token_type = str(payload.get("typ") or "").strip().lower()
        if token_type != expected_type:
            raise AppSessionTokenError("Invalid app session token type.")

        principal_identity_id_raw = payload.get("iid")
        principal_identity_id = (
            str(principal_identity_id_raw).strip()
            if principal_identity_id_raw is not None and str(principal_identity_id_raw).strip()
            else None
        )

        try:
            return AppSessionClaims(
                token_type=token_type,
                jti=str(payload["jti"]),
                business_id=str(payload["bid"]),
                principal_id=str(payload["pid"]),
                principal_role=str(payload["role"]),
                auth_source=str(payload["src"]),
                principal_identity_id=principal_identity_id,
                issued_at=_epoch_to_dt(payload["iat"]),
                not_before=_epoch_to_dt(payload["nbf"]),
                expires_at=_epoch_to_dt(payload["exp"]),
                issuer=str(payload["iss"]),
                audience=str(payload["aud"]),
            )
        except Exception as exc:  # noqa: BLE001
            raise AppSessionTokenError("Invalid app session token payload.") from exc

    def _ensure_not_revoked(self, *, claims: AppSessionClaims) -> None:
        if self._state_store.is_jti_revoked(jti=claims.jti):
            raise AppSessionTokenError("App session token revoked.")

        self._ensure_subject_not_revoked(claims=claims)

    def _ensure_subject_not_revoked(self, *, claims: AppSessionClaims) -> None:
        principal_cutoff = self._state_store.get_principal_revoked_after(
            business_id=claims.business_id,
            principal_id=claims.principal_id,
        )
        if principal_cutoff is not None and dt_to_epoch_seconds(claims.issued_at) <= principal_cutoff:
            raise AppSessionTokenError("App session token revoked.")

        if claims.principal_identity_id:
            identity_cutoff = self._state_store.get_identity_revoked_after(identity_id=claims.principal_identity_id)
            if identity_cutoff is not None and dt_to_epoch_seconds(claims.issued_at) <= identity_cutoff:
                raise AppSessionTokenError("App session token revoked.")

    def _build_subject(self, *, business_id: str, principal_id: str) -> str:
        return f"{business_id}:{principal_id}"


def _epoch_to_dt(value: Any) -> datetime:
    if not isinstance(value, int):
        raise AppSessionTokenError("Invalid app session token timestamp.")
    return datetime.fromtimestamp(value, tz=timezone.utc)

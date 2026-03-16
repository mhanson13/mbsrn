from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json


class AppSessionTokenError(ValueError):
    pass


@dataclass(frozen=True)
class AppSessionClaims:
    business_id: str
    principal_id: str
    principal_role: str
    auth_source: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class IssuedAppSessionToken:
    token: str
    expires_at: datetime


class AppSessionTokenService:
    _VERSION_PREFIX = "wb1"

    def __init__(self, *, secret: str, ttl_seconds: int) -> None:
        normalized_secret = secret.strip()
        if not normalized_secret:
            raise AppSessionTokenError("APP_SESSION_SECRET is required for app session token operations.")
        if ttl_seconds <= 0:
            raise AppSessionTokenError("APP_SESSION_TTL_SECONDS must be greater than zero.")
        self._secret = normalized_secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def issue(
        self,
        *,
        business_id: str,
        principal_id: str,
        principal_role: str,
        auth_source: str,
    ) -> IssuedAppSessionToken:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        payload = {
            "bid": business_id,
            "pid": principal_id,
            "role": principal_role,
            "src": auth_source,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = self._b64_encode(payload_bytes)
        signature_b64 = self._sign(payload_b64)
        token = f"{self._VERSION_PREFIX}.{payload_b64}.{signature_b64}"
        return IssuedAppSessionToken(token=token, expires_at=expires_at)

    def verify(self, token: str) -> AppSessionClaims:
        version, payload_b64, signature_b64 = self._split(token)
        if version != self._VERSION_PREFIX:
            raise AppSessionTokenError("Unsupported app session token version.")
        expected_signature = self._sign(payload_b64)
        if not hmac.compare_digest(signature_b64, expected_signature):
            raise AppSessionTokenError("Invalid app session token signature.")
        payload = self._decode_payload(payload_b64)

        business_id = str(payload.get("bid") or "").strip()
        principal_id = str(payload.get("pid") or "").strip()
        principal_role = str(payload.get("role") or "").strip()
        auth_source = str(payload.get("src") or "").strip()
        iat = payload.get("iat")
        exp = payload.get("exp")

        if not business_id or not principal_id or not principal_role or not auth_source:
            raise AppSessionTokenError("Invalid app session token payload.")
        if not isinstance(iat, int) or not isinstance(exp, int):
            raise AppSessionTokenError("Invalid app session token timestamps.")

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if exp <= now_ts:
            raise AppSessionTokenError("App session token expired.")

        return AppSessionClaims(
            business_id=business_id,
            principal_id=principal_id,
            principal_role=principal_role,
            auth_source=auth_source,
            issued_at=datetime.fromtimestamp(iat, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )

    def _split(self, token: str) -> tuple[str, str, str]:
        raw = token.strip()
        if not raw:
            raise AppSessionTokenError("App session token is required.")
        parts = raw.split(".")
        if len(parts) != 3:
            raise AppSessionTokenError("Invalid app session token format.")
        return parts[0], parts[1], parts[2]

    def _decode_payload(self, payload_b64: str) -> dict:
        try:
            payload_bytes = self._b64_decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AppSessionTokenError("Invalid app session token payload encoding.") from exc
        if not isinstance(payload, dict):
            raise AppSessionTokenError("Invalid app session token payload.")
        return payload

    def _sign(self, payload_b64: str) -> str:
        digest = hmac.new(self._secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
        return self._b64_encode(digest)

    def _b64_encode(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")

    def _b64_decode(self, payload: str) -> bytes:
        pad_len = (4 - (len(payload) % 4)) % 4
        return base64.urlsafe_b64decode(payload + ("=" * pad_len))

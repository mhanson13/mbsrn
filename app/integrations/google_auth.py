from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


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


class GoogleOIDCTokenInfoVerifier:
    """Minimal Google ID token verification using the tokeninfo endpoint.

    This keeps runtime dependencies small in the monolith and is sufficient for
    Phase 4 operationalization. It validates issuer, audience, subject, and
    email verification semantics before handing identity to internal auth logic.
    """

    def __init__(
        self,
        *,
        client_id: str,
        tokeninfo_url: str = "https://oauth2.googleapis.com/tokeninfo",
        timeout_seconds: int = 5,
    ) -> None:
        self.client_id = client_id.strip()
        self.tokeninfo_url = tokeninfo_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def verify_id_token(self, id_token: str) -> GoogleIdentityClaims:
        token = id_token.strip()
        if not token:
            raise GoogleOIDCVerificationError("id_token is required.")

        query = urlencode({"id_token": token})
        request_url = f"{self.tokeninfo_url}?{query}"
        try:
            with urlopen(request_url, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GoogleOIDCVerificationError(f"Google token verification failed: {exc.reason}") from exc
        except URLError as exc:
            raise GoogleOIDCVerificationError(f"Google token verification unavailable: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GoogleOIDCVerificationError("Google token verification failed.") from exc

        issuer = str(payload.get("iss") or "").strip()
        if issuer not in {"https://accounts.google.com", "accounts.google.com"}:
            raise GoogleOIDCVerificationError("Invalid Google token issuer.")

        audience = str(payload.get("aud") or "").strip()
        if audience != self.client_id:
            raise GoogleOIDCVerificationError("Google token audience mismatch.")

        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise GoogleOIDCVerificationError("Google token missing subject claim.")

        email_raw = payload.get("email")
        email = str(email_raw).strip().lower() if email_raw else None
        email_verified = str(payload.get("email_verified") or "").strip().lower() == "true"
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

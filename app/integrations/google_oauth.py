from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt


class GoogleOAuthError(ValueError):
    pass


@dataclass(frozen=True)
class GoogleOAuthTokenResponse:
    access_token: str
    token_type: str
    expires_in: int | None
    refresh_token: str | None
    scope: str | None
    id_token_subject: str | None
    id_token_email: str | None


class GoogleOAuthWebClient:
    """Server-side OAuth client for Google API authorization flows."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        authorization_url: str = "https://accounts.google.com/o/oauth2/v2/auth",
        token_url: str = "https://oauth2.googleapis.com/token",
        revoke_url: str = "https://oauth2.googleapis.com/revoke",
        timeout_seconds: int = 10,
    ) -> None:
        normalized_client_id = client_id.strip()
        normalized_client_secret = client_secret.strip()
        if not normalized_client_id:
            raise GoogleOAuthError("Google OAuth client_id is required.")
        if not normalized_client_secret:
            raise GoogleOAuthError("Google OAuth client_secret is required.")

        self.client_id = normalized_client_id
        self.client_secret = normalized_client_secret
        self.authorization_url = authorization_url.rstrip("/")
        self.token_url = token_url.rstrip("/")
        self.revoke_url = revoke_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def build_auth_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        scopes: tuple[str, ...],
        access_type: str = "offline",
        include_granted_scopes: bool = True,
        prompt: str = "consent",
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        normalized_redirect_uri = redirect_uri.strip()
        normalized_state = state.strip()
        if not normalized_redirect_uri:
            raise GoogleOAuthError("redirect_uri is required.")
        if not normalized_state:
            raise GoogleOAuthError("state is required.")

        normalized_scopes = tuple(scope.strip() for scope in scopes if scope.strip())
        if not normalized_scopes:
            raise GoogleOAuthError("At least one OAuth scope is required.")

        query_params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": normalized_redirect_uri,
            "response_type": "code",
            "scope": " ".join(normalized_scopes),
            "state": normalized_state,
            "access_type": access_type,
            "include_granted_scopes": "true" if include_granted_scopes else "false",
            "prompt": prompt,
        }
        normalized_code_challenge = (code_challenge or "").strip()
        normalized_code_challenge_method = (code_challenge_method or "").strip()
        if normalized_code_challenge:
            query_params["code_challenge"] = normalized_code_challenge
            query_params["code_challenge_method"] = normalized_code_challenge_method or "S256"
        query = urlencode(query_params)
        return f"{self.authorization_url}?{query}"

    def exchange_code_for_tokens(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> GoogleOAuthTokenResponse:
        normalized_code = code.strip()
        normalized_redirect_uri = redirect_uri.strip()
        if not normalized_code:
            raise GoogleOAuthError("authorization code is required.")
        if not normalized_redirect_uri:
            raise GoogleOAuthError("redirect_uri is required.")

        form: dict[str, str] = {
            "code": normalized_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": normalized_redirect_uri,
            "grant_type": "authorization_code",
        }
        normalized_code_verifier = (code_verifier or "").strip()
        if normalized_code_verifier:
            form["code_verifier"] = normalized_code_verifier

        payload = self._post_form(
            self.token_url,
            form,
        )
        return self._parse_token_response(payload)

    def refresh_access_token(self, *, refresh_token: str) -> GoogleOAuthTokenResponse:
        normalized_refresh_token = refresh_token.strip()
        if not normalized_refresh_token:
            raise GoogleOAuthError("refresh_token is required.")

        payload = self._post_form(
            self.token_url,
            {
                "refresh_token": normalized_refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            },
        )
        return self._parse_token_response(payload)

    def revoke_token(self, *, token: str) -> bool:
        normalized_token = token.strip()
        if not normalized_token:
            return False
        try:
            self._post_form(
                self.revoke_url,
                {
                    "token": normalized_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            return True
        except GoogleOAuthError:
            return False

    def _post_form(self, url: str, body: dict[str, str]) -> dict[str, Any]:
        encoded = urlencode(body).encode("utf-8")
        request = Request(
            url=url,
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                data = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = self._extract_error_detail(exc)
            raise GoogleOAuthError(f"Google OAuth request failed: {detail}") from exc
        except URLError as exc:
            raise GoogleOAuthError(f"Google OAuth endpoint unavailable: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GoogleOAuthError("Google OAuth request failed.") from exc

        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise GoogleOAuthError("Google OAuth response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise GoogleOAuthError("Google OAuth response payload is invalid.")
        return payload

    def _parse_token_response(self, payload: dict[str, Any]) -> GoogleOAuthTokenResponse:
        access_token = str(payload.get("access_token") or "").strip()
        token_type = str(payload.get("token_type") or "").strip().lower()
        if not access_token:
            error_detail = str(payload.get("error_description") or payload.get("error") or "").strip()
            if error_detail:
                raise GoogleOAuthError(f"Google OAuth token response error: {error_detail}")
            raise GoogleOAuthError("Google OAuth response missing access_token.")
        if not token_type:
            token_type = "bearer"

        expires_in = _coerce_int(payload.get("expires_in"))
        refresh_token_raw = payload.get("refresh_token")
        refresh_token = str(refresh_token_raw).strip() if refresh_token_raw else None
        scope_raw = payload.get("scope")
        scope = str(scope_raw).strip() if scope_raw else None
        id_token_raw = payload.get("id_token")
        subject, email = _decode_id_token(id_token_raw)

        return GoogleOAuthTokenResponse(
            access_token=access_token,
            token_type=token_type,
            expires_in=expires_in,
            refresh_token=refresh_token,
            scope=scope,
            id_token_subject=subject,
            id_token_email=email,
        )

    def _extract_error_detail(self, exc: HTTPError) -> str:
        body = ""
        try:
            if exc.fp is not None:
                body = exc.fp.read().decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            body = ""

        if body:
            try:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    description = str(payload.get("error_description") or "").strip()
                    error = str(payload.get("error") or "").strip()
                    if description and error:
                        return f"{error}: {description}"
                    if description:
                        return description
                    if error:
                        return error
            except Exception:  # noqa: BLE001
                pass
            return body.strip()[:256]
        return str(exc.reason)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _decode_id_token(raw_id_token: Any) -> tuple[str | None, str | None]:
    if not raw_id_token:
        return None, None
    token = str(raw_id_token).strip()
    if not token:
        return None, None
    try:
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "verify_aud": False,
                "verify_iss": False,
                "verify_sub": False,
                "verify_jti": False,
            },
        )
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(payload, dict):
        return None, None
    subject = str(payload.get("sub") or "").strip() or None
    email = str(payload.get("email") or "").strip().lower() or None
    return subject, email

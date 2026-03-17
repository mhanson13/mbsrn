from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import secrets
from typing import Literal, Sequence
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.core.token_cipher import FernetTokenCipher, TokenCipherError
from app.integrations.google_oauth import GoogleOAuthError, GoogleOAuthTokenResponse, GoogleOAuthWebClient
from app.models.provider_connection import ProviderConnection
from app.models.provider_oauth_state import ProviderOAuthState
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_repository import PrincipalRepository
from app.repositories.provider_connection_repository import ProviderConnectionRepository
from app.repositories.provider_oauth_state_repository import ProviderOAuthStateRepository
from app.services.auth_audit import AuthAuditService

TokenUsabilityStatus = Literal["usable", "refresh_required", "reconnect_required", "insufficient_scope"]


class GoogleBusinessProfileConnectionNotFoundError(ValueError):
    pass


class GoogleBusinessProfileConnectionConfigurationError(ValueError):
    pass


class GoogleBusinessProfileConnectionValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 422,
        reconnect_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reconnect_required = reconnect_required


@dataclass(frozen=True)
class GoogleBusinessProfileConnectStartResult:
    authorization_url: str
    state_expires_at: str
    provider: str
    required_scope: str


@dataclass(frozen=True)
class GoogleBusinessProfileConnectionStatusResult:
    provider: str
    connected: bool
    business_id: str
    granted_scopes: tuple[str, ...]
    refresh_token_present: bool
    expires_at: str | None
    connected_at: str | None
    last_refreshed_at: str | None
    reconnect_required: bool
    required_scopes_satisfied: bool
    token_status: TokenUsabilityStatus


@dataclass(frozen=True)
class GoogleBusinessProfileTokenUseResult:
    provider: str
    connected: bool
    business_id: str
    granted_scopes: tuple[str, ...]
    refresh_token_present: bool
    expires_at: str | None
    reconnect_required: bool
    required_scopes_satisfied: bool
    token_status: TokenUsabilityStatus
    access_token: str | None


class GoogleBusinessProfileConnectionService:
    PROVIDER = "google_business_profile"
    BUSINESS_PROFILE_SCOPE = "https://www.googleapis.com/auth/business.manage"

    TOKEN_STATUS_USABLE: TokenUsabilityStatus = "usable"
    TOKEN_STATUS_REFRESH_REQUIRED: TokenUsabilityStatus = "refresh_required"
    TOKEN_STATUS_RECONNECT_REQUIRED: TokenUsabilityStatus = "reconnect_required"
    TOKEN_STATUS_INSUFFICIENT_SCOPE: TokenUsabilityStatus = "insufficient_scope"

    TARGET_TYPE = "integration_connection"
    EVENT_CONNECT_STARTED = "integration_google_business_profile_connect_started"
    EVENT_CONNECT_SUCCEEDED = "integration_google_business_profile_connected"
    EVENT_CONNECT_DENIED = "integration_google_business_profile_connect_denied"
    EVENT_CONNECT_FAILED = "integration_google_business_profile_connect_failed"
    EVENT_DISCONNECTED = "integration_google_business_profile_disconnected"
    EVENT_CALLBACK_REPLAYED = "integration_google_business_profile_callback_replayed"
    EVENT_REWRAPPED = "integration_google_business_profile_tokens_rewrapped"

    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        principal_repository: PrincipalRepository,
        provider_connection_repository: ProviderConnectionRepository,
        provider_oauth_state_repository: ProviderOAuthStateRepository,
        oauth_client: GoogleOAuthWebClient,
        token_cipher: FernetTokenCipher,
        auth_audit_service: AuthAuditService,
        redirect_uri: str,
        state_ttl_seconds: int,
        refresh_skew_seconds: int,
    ) -> None:
        normalized_redirect_uri = redirect_uri.strip()
        if not normalized_redirect_uri:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Google Business Profile redirect URI is not configured."
            )
        if state_ttl_seconds <= 0:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Google Business Profile state TTL must be positive."
            )
        if refresh_skew_seconds < 0:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Google OAuth refresh skew seconds cannot be negative."
            )

        self.session = session
        self.business_repository = business_repository
        self.principal_repository = principal_repository
        self.provider_connection_repository = provider_connection_repository
        self.provider_oauth_state_repository = provider_oauth_state_repository
        self.oauth_client = oauth_client
        self.token_cipher = token_cipher
        self.auth_audit_service = auth_audit_service
        self.redirect_uri = normalized_redirect_uri
        self.state_ttl_seconds = state_ttl_seconds
        self.refresh_skew_seconds = refresh_skew_seconds

    def start_connection(
        self,
        *,
        business_id: str,
        principal_id: str,
    ) -> GoogleBusinessProfileConnectStartResult:
        self._ensure_business_and_active_principal(business_id=business_id, principal_id=principal_id)

        raw_state = secrets.token_urlsafe(32)
        code_verifier = _generate_pkce_code_verifier()
        code_challenge = _build_pkce_code_challenge(code_verifier)
        try:
            code_verifier_encrypted = self.token_cipher.encrypt(code_verifier)
        except TokenCipherError as exc:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Unable to encrypt OAuth PKCE verifier."
            ) from exc

        expires_at = utc_now() + timedelta(seconds=self.state_ttl_seconds)
        oauth_state = ProviderOAuthState(
            id=str(uuid4()),
            provider=self.PROVIDER,
            business_id=business_id,
            principal_id=principal_id,
            state_hash=_hash_state(raw_state),
            code_verifier_encrypted=code_verifier_encrypted,
            code_verifier_key_version=self.token_cipher.active_key_version,
            expires_at=expires_at,
        )
        self.provider_oauth_state_repository.create(oauth_state)

        auth_url = self.build_auth_url(
            state=raw_state,
            code_challenge=code_challenge,
        )
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=principal_id,
            target_type=self.TARGET_TYPE,
            target_id=self.PROVIDER,
            event_type=self.EVENT_CONNECT_STARTED,
            details={
                "provider": self.PROVIDER,
                "scope": self.BUSINESS_PROFILE_SCOPE,
            },
        )
        self.session.commit()
        return GoogleBusinessProfileConnectStartResult(
            authorization_url=auth_url,
            state_expires_at=expires_at.isoformat(),
            provider=self.PROVIDER,
            required_scope=self.BUSINESS_PROFILE_SCOPE,
        )

    def build_auth_url(self, *, state: str, code_challenge: str) -> str:
        return self.oauth_client.build_auth_url(
            redirect_uri=self.redirect_uri,
            state=state,
            scopes=(self.BUSINESS_PROFILE_SCOPE,),
            access_type="offline",
            include_granted_scopes=True,
            prompt="consent",
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )

    def exchange_code_for_tokens(self, *, code: str, code_verifier: str) -> GoogleOAuthTokenResponse:
        return self.oauth_client.exchange_code_for_tokens(
            code=code,
            redirect_uri=self.redirect_uri,
            code_verifier=code_verifier,
        )

    def handle_callback(
        self,
        *,
        state: str | None,
        code: str | None,
        error: str | None,
        error_description: str | None,
    ) -> GoogleBusinessProfileConnectionStatusResult:
        normalized_state = (state or "").strip()
        if not normalized_state:
            raise GoogleBusinessProfileConnectionValidationError("OAuth state is required.", status_code=400)

        oauth_state = self.provider_oauth_state_repository.get_active_by_state_hash(
            provider=self.PROVIDER,
            state_hash=_hash_state(normalized_state),
        )
        if oauth_state is None:
            raise GoogleBusinessProfileConnectionValidationError(
                "OAuth state is invalid or expired.",
                status_code=401,
            )

        consumed = self.provider_oauth_state_repository.mark_consumed_if_active(
            provider=self.PROVIDER,
            oauth_state_id=oauth_state.id,
        )
        if not consumed:
            self.auth_audit_service.record_event(
                business_id=oauth_state.business_id,
                actor_principal_id=oauth_state.principal_id,
                target_type=self.TARGET_TYPE,
                target_id=self.PROVIDER,
                event_type=self.EVENT_CALLBACK_REPLAYED,
                details={
                    "provider": self.PROVIDER,
                    "reason": "state_already_consumed_or_expired",
                },
            )
            self.session.commit()
            raise GoogleBusinessProfileConnectionValidationError(
                "OAuth state is invalid or expired.",
                status_code=401,
            )
        self._ensure_business_and_active_principal(
            business_id=oauth_state.business_id,
            principal_id=oauth_state.principal_id,
        )

        normalized_error = (error or "").strip()
        normalized_error_description = (error_description or "").strip()
        if normalized_error:
            event_type = self.EVENT_CONNECT_DENIED if normalized_error == "access_denied" else self.EVENT_CONNECT_FAILED
            self.auth_audit_service.record_event(
                business_id=oauth_state.business_id,
                actor_principal_id=oauth_state.principal_id,
                target_type=self.TARGET_TYPE,
                target_id=self.PROVIDER,
                event_type=event_type,
                details={
                    "provider": self.PROVIDER,
                    "error": normalized_error,
                    "error_description": normalized_error_description or None,
                },
            )
            self.session.commit()
            if normalized_error == "access_denied":
                raise GoogleBusinessProfileConnectionValidationError(
                    "Google Business Profile authorization was denied.",
                    status_code=400,
                )
            raise GoogleBusinessProfileConnectionValidationError(
                "Google Business Profile authorization failed.",
                status_code=400,
            )

        normalized_code = (code or "").strip()
        if not normalized_code:
            self.auth_audit_service.record_event(
                business_id=oauth_state.business_id,
                actor_principal_id=oauth_state.principal_id,
                target_type=self.TARGET_TYPE,
                target_id=self.PROVIDER,
                event_type=self.EVENT_CONNECT_FAILED,
                details={
                    "provider": self.PROVIDER,
                    "error": "missing_authorization_code",
                },
            )
            self.session.commit()
            raise GoogleBusinessProfileConnectionValidationError(
                "Google authorization code is required.",
                status_code=400,
            )

        code_verifier = self._decrypt_state_code_verifier(oauth_state)
        # Google validates code_verifier against code_challenge (S256) during token exchange.
        # The app must preserve the verifier server-side and send it back on callback.
        try:
            tokens = self.exchange_code_for_tokens(code=normalized_code, code_verifier=code_verifier)
        except GoogleOAuthError as exc:
            self.auth_audit_service.record_event(
                business_id=oauth_state.business_id,
                actor_principal_id=oauth_state.principal_id,
                target_type=self.TARGET_TYPE,
                target_id=self.PROVIDER,
                event_type=self.EVENT_CONNECT_FAILED,
                details={
                    "provider": self.PROVIDER,
                    "error": "token_exchange_failed",
                    "message": str(exc),
                },
            )
            self.session.commit()
            raise GoogleBusinessProfileConnectionValidationError(
                "Google token exchange failed.",
                status_code=400,
            ) from exc

        return self._persist_connection_from_callback(oauth_state=oauth_state, tokens=tokens)

    def get_connection_status(
        self,
        *,
        business_id: str,
        required_scopes: Sequence[str] | None = None,
    ) -> GoogleBusinessProfileConnectionStatusResult:
        self._ensure_business_exists(business_id)
        connection = self.provider_connection_repository.get_for_business_provider(
            business_id=business_id,
            provider=self.PROVIDER,
        )
        normalized_required = self._normalize_required_scopes(required_scopes)
        if connection is None:
            return self._status_without_connection(business_id=business_id, required_scopes=normalized_required)
        return self._status_from_connection(connection, required_scopes=normalized_required)

    def get_access_token_for_use(
        self,
        *,
        business_id: str,
        required_scopes: Sequence[str] | None = None,
    ) -> GoogleBusinessProfileTokenUseResult:
        self._ensure_business_exists(business_id)
        connection = self.provider_connection_repository.get_for_business_provider(
            business_id=business_id,
            provider=self.PROVIDER,
        )
        normalized_required = self._normalize_required_scopes(required_scopes)
        if connection is None:
            status = self._status_without_connection(business_id=business_id, required_scopes=normalized_required)
            return self._token_use_from_status(status=status, access_token=None)

        status = self._status_from_connection(connection, required_scopes=normalized_required)
        if status.token_status == self.TOKEN_STATUS_INSUFFICIENT_SCOPE:
            return self._token_use_from_status(status=status, access_token=None)
        if status.token_status == self.TOKEN_STATUS_RECONNECT_REQUIRED:
            return self._token_use_from_status(status=status, access_token=None)

        try:
            normalized_required = self.ensure_connection_has_scopes(
                connection=connection,
                required_scopes=normalized_required,
            )
        except GoogleBusinessProfileConnectionValidationError:
            insufficient_scope_status = self._status_with_override(
                connection=connection,
                required_scopes=normalized_required,
                token_status=self.TOKEN_STATUS_INSUFFICIENT_SCOPE,
                reconnect_required=True,
            )
            return self._token_use_from_status(status=insufficient_scope_status, access_token=None)

        if status.token_status == self.TOKEN_STATUS_REFRESH_REQUIRED:
            refreshed = self._refresh_connection_tokens(connection=connection, required_scopes=normalized_required)
            if refreshed is None:
                reconnect_status = self._status_with_override(
                    connection=connection,
                    required_scopes=normalized_required,
                    token_status=self.TOKEN_STATUS_RECONNECT_REQUIRED,
                    reconnect_required=True,
                )
                return self._token_use_from_status(status=reconnect_status, access_token=None)
            refreshed_status = self._status_from_connection(connection, required_scopes=normalized_required)
            return self._token_use_from_status(status=refreshed_status, access_token=refreshed)

        try:
            access_token = self.token_cipher.decrypt(
                connection.access_token_encrypted,
                key_version=connection.token_key_version,
            )
        except TokenCipherError:
            reconnect_status = self._status_with_override(
                connection=connection,
                required_scopes=normalized_required,
                token_status=self.TOKEN_STATUS_RECONNECT_REQUIRED,
                reconnect_required=True,
            )
            return self._token_use_from_status(status=reconnect_status, access_token=None)
        return self._token_use_from_status(status=status, access_token=access_token)

    def refresh_access_token(
        self,
        *,
        business_id: str,
    ) -> GoogleBusinessProfileConnectionStatusResult:
        self._ensure_business_exists(business_id)
        connection = self.provider_connection_repository.get_for_business_provider(
            business_id=business_id,
            provider=self.PROVIDER,
        )
        if connection is None or not connection.is_active:
            raise GoogleBusinessProfileConnectionNotFoundError("Google Business Profile connection not found.")
        if not connection.refresh_token_encrypted:
            raise GoogleBusinessProfileConnectionValidationError(
                "Stored Google refresh token is missing.",
                reconnect_required=True,
            )

        refreshed = self._refresh_connection_tokens(
            connection=connection,
            required_scopes=self._normalize_required_scopes((self.BUSINESS_PROFILE_SCOPE,)),
        )
        if refreshed is None:
            raise GoogleBusinessProfileConnectionValidationError(
                "Google access token refresh failed.",
                status_code=401,
                reconnect_required=True,
            )
        return self._status_from_connection(connection)

    def rewrap_tokens_with_active_key(
        self,
        *,
        business_id: str,
        actor_principal_id: str,
    ) -> bool:
        self._ensure_business_and_active_principal(
            business_id=business_id,
            principal_id=actor_principal_id,
        )
        connection = self.provider_connection_repository.get_for_business_provider(
            business_id=business_id,
            provider=self.PROVIDER,
        )
        if connection is None:
            return False
        if connection.token_key_version == self.token_cipher.active_key_version:
            return False

        access_plaintext: str | None = None
        refresh_plaintext: str | None = None
        try:
            if connection.access_token_encrypted:
                access_plaintext = self.token_cipher.decrypt(
                    connection.access_token_encrypted,
                    key_version=connection.token_key_version,
                )
            if connection.refresh_token_encrypted:
                refresh_plaintext = self.token_cipher.decrypt(
                    connection.refresh_token_encrypted,
                    key_version=connection.token_key_version,
                )
            if access_plaintext:
                connection.access_token_encrypted = self.token_cipher.encrypt(access_plaintext)
            if refresh_plaintext:
                connection.refresh_token_encrypted = self.token_cipher.encrypt(refresh_plaintext)
        except TokenCipherError as exc:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Unable to rewrap stored Google provider credentials with active key version."
            ) from exc

        connection.token_key_version = self.token_cipher.active_key_version
        connection.updated_by_principal_id = actor_principal_id
        self.provider_connection_repository.save(connection)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=actor_principal_id,
            target_type=self.TARGET_TYPE,
            target_id=self.PROVIDER,
            event_type=self.EVENT_REWRAPPED,
            details={
                "provider": self.PROVIDER,
                "new_key_version": self.token_cipher.active_key_version,
            },
        )
        self.session.commit()
        return True

    def rewrap_all_tokens_with_active_key(self) -> int:
        connections = self.provider_connection_repository.list_for_provider(provider=self.PROVIDER)
        rewrapped_count = 0
        for connection in connections:
            if connection.token_key_version == self.token_cipher.active_key_version:
                continue

            access_plaintext: str | None = None
            refresh_plaintext: str | None = None
            try:
                if connection.access_token_encrypted:
                    access_plaintext = self.token_cipher.decrypt(
                        connection.access_token_encrypted,
                        key_version=connection.token_key_version,
                    )
                if connection.refresh_token_encrypted:
                    refresh_plaintext = self.token_cipher.decrypt(
                        connection.refresh_token_encrypted,
                        key_version=connection.token_key_version,
                    )
                if access_plaintext:
                    connection.access_token_encrypted = self.token_cipher.encrypt(access_plaintext)
                if refresh_plaintext:
                    connection.refresh_token_encrypted = self.token_cipher.encrypt(refresh_plaintext)
            except TokenCipherError as exc:
                raise GoogleBusinessProfileConnectionConfigurationError(
                    "Unable to rewrap all stored Google provider credentials with active key version."
                ) from exc

            connection.token_key_version = self.token_cipher.active_key_version
            self.provider_connection_repository.save(connection)
            rewrapped_count += 1
        self.session.commit()
        return rewrapped_count

    def revoke_or_disconnect_provider(
        self,
        *,
        business_id: str,
        actor_principal_id: str,
    ) -> bool:
        self._ensure_business_and_active_principal(
            business_id=business_id,
            principal_id=actor_principal_id,
        )
        connection = self.provider_connection_repository.get_for_business_provider(
            business_id=business_id,
            provider=self.PROVIDER,
        )
        if connection is None:
            return False

        token_to_revoke: str | None = None
        try:
            if connection.refresh_token_encrypted:
                token_to_revoke = self.token_cipher.decrypt(
                    connection.refresh_token_encrypted,
                    key_version=connection.token_key_version,
                )
            elif connection.access_token_encrypted:
                token_to_revoke = self.token_cipher.decrypt(
                    connection.access_token_encrypted,
                    key_version=connection.token_key_version,
                )
        except TokenCipherError:
            token_to_revoke = None

        revoked = False
        if token_to_revoke:
            revoked = self.oauth_client.revoke_token(token=token_to_revoke)

        connection.is_active = False
        connection.access_token_encrypted = None
        connection.refresh_token_encrypted = None
        connection.access_token_expires_at = None
        connection.disconnected_at = utc_now()
        connection.updated_by_principal_id = actor_principal_id
        connection.last_error = None if revoked else "Google token revoke was not confirmed."
        self.provider_connection_repository.save(connection)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=actor_principal_id,
            target_type=self.TARGET_TYPE,
            target_id=self.PROVIDER,
            event_type=self.EVENT_DISCONNECTED,
            details={
                "provider": self.PROVIDER,
                "revoked": revoked,
            },
        )
        self.session.commit()
        return True

    def ensure_connection_has_scopes(
        self,
        *,
        connection: ProviderConnection,
        required_scopes: Sequence[str] | None,
    ) -> tuple[str, ...]:
        normalized_required = self._normalize_required_scopes(required_scopes)
        if not normalized_required:
            return ()
        granted = set(self._normalize_scopes(connection.granted_scopes))
        missing = [scope for scope in normalized_required if scope not in granted]
        if missing:
            raise GoogleBusinessProfileConnectionValidationError(
                f"Required scopes are missing: {', '.join(missing)}",
                status_code=403,
                reconnect_required=True,
            )
        return normalized_required

    def _persist_connection_from_callback(
        self,
        *,
        oauth_state: ProviderOAuthState,
        tokens: GoogleOAuthTokenResponse,
    ) -> GoogleBusinessProfileConnectionStatusResult:
        existing = self.provider_connection_repository.get_for_business_provider(
            business_id=oauth_state.business_id,
            provider=self.PROVIDER,
        )
        normalized_scopes = self._normalize_scopes(tokens.scope)
        existing_scopes = self._normalize_scopes(existing.granted_scopes if existing is not None else None)
        effective_scopes = normalized_scopes if normalized_scopes else existing_scopes
        if self.BUSINESS_PROFILE_SCOPE not in effective_scopes:
            self.auth_audit_service.record_event(
                business_id=oauth_state.business_id,
                actor_principal_id=oauth_state.principal_id,
                target_type=self.TARGET_TYPE,
                target_id=self.PROVIDER,
                event_type=self.EVENT_CONNECT_FAILED,
                details={
                    "provider": self.PROVIDER,
                    "error": "missing_scope",
                    "required_scope": self.BUSINESS_PROFILE_SCOPE,
                    "granted_scopes": list(effective_scopes),
                },
            )
            self.session.commit()
            raise GoogleBusinessProfileConnectionValidationError(
                "Google Business Profile scope was not granted.",
                status_code=422,
                reconnect_required=True,
            )

        try:
            access_token_encrypted = self.token_cipher.encrypt(tokens.access_token)
        except TokenCipherError as exc:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Unable to encrypt Google provider tokens."
            ) from exc

        refresh_token_encrypted = self._resolve_refresh_token_encrypted(
            existing=existing,
            received_refresh_token=tokens.refresh_token,
        )
        if not refresh_token_encrypted:
            self.auth_audit_service.record_event(
                business_id=oauth_state.business_id,
                actor_principal_id=oauth_state.principal_id,
                target_type=self.TARGET_TYPE,
                target_id=self.PROVIDER,
                event_type=self.EVENT_CONNECT_FAILED,
                details={
                    "provider": self.PROVIDER,
                    "error": "missing_refresh_token",
                },
            )
            self.session.commit()
            raise GoogleBusinessProfileConnectionValidationError(
                (
                    "Google did not return a refresh token. Disconnect and reconnect with consent "
                    "to grant offline access."
                ),
                status_code=422,
                reconnect_required=True,
            )

        now = utc_now()
        expires_at = now + timedelta(seconds=tokens.expires_in) if tokens.expires_in is not None else None
        if existing is None:
            connection = ProviderConnection(
                id=str(uuid4()),
                provider=self.PROVIDER,
                business_id=oauth_state.business_id,
                principal_id=oauth_state.principal_id,
                created_by_principal_id=oauth_state.principal_id,
                updated_by_principal_id=oauth_state.principal_id,
                granted_scopes=" ".join(effective_scopes),
                token_key_version=self.token_cipher.active_key_version,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                access_token_expires_at=expires_at,
                external_subject=tokens.id_token_subject,
                external_account_email=tokens.id_token_email,
                is_active=True,
                last_error=None,
                connected_at=now,
                last_refreshed_at=now,
                disconnected_at=None,
            )
            self.provider_connection_repository.create(connection)
        else:
            existing.principal_id = oauth_state.principal_id
            existing.updated_by_principal_id = oauth_state.principal_id
            existing.granted_scopes = " ".join(effective_scopes)
            existing.token_key_version = self.token_cipher.active_key_version
            existing.access_token_encrypted = access_token_encrypted
            existing.refresh_token_encrypted = refresh_token_encrypted
            existing.access_token_expires_at = expires_at
            if tokens.id_token_subject:
                existing.external_subject = tokens.id_token_subject
            if tokens.id_token_email:
                existing.external_account_email = tokens.id_token_email
            existing.is_active = True
            existing.last_error = None
            existing.connected_at = now
            existing.last_refreshed_at = now
            existing.disconnected_at = None
            connection = self.provider_connection_repository.save(existing)

        self.auth_audit_service.record_event(
            business_id=oauth_state.business_id,
            actor_principal_id=oauth_state.principal_id,
            target_type=self.TARGET_TYPE,
            target_id=self.PROVIDER,
            event_type=self.EVENT_CONNECT_SUCCEEDED,
            details={
                "provider": self.PROVIDER,
                "granted_scopes": list(effective_scopes),
                "principal_id": oauth_state.principal_id,
            },
        )
        self.session.commit()
        return self._status_from_connection(connection)

    def _refresh_connection_tokens(
        self,
        *,
        connection: ProviderConnection,
        required_scopes: tuple[str, ...],
    ) -> str | None:
        if not connection.refresh_token_encrypted:
            return None
        try:
            refresh_token = self.token_cipher.decrypt(
                connection.refresh_token_encrypted,
                key_version=connection.token_key_version,
            )
        except TokenCipherError:
            return None

        try:
            refreshed = self.oauth_client.refresh_access_token(refresh_token=refresh_token)
        except GoogleOAuthError as exc:
            connection.last_error = str(exc)[:512]
            self.provider_connection_repository.save(connection)
            self.session.commit()
            return None

        refreshed_scopes = self._normalize_scopes(refreshed.scope) or self._normalize_scopes(connection.granted_scopes)
        if required_scopes:
            missing = [scope for scope in required_scopes if scope not in set(refreshed_scopes)]
            if missing:
                connection.last_error = f"Required scopes are missing: {', '.join(missing)}"[:512]
                connection.granted_scopes = " ".join(refreshed_scopes)
                self.provider_connection_repository.save(connection)
                self.session.commit()
                return None

        try:
            access_token_encrypted = self.token_cipher.encrypt(refreshed.access_token)
            refresh_token_encrypted = self.token_cipher.encrypt(refreshed.refresh_token or refresh_token)
        except TokenCipherError as exc:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Unable to encrypt refreshed Google provider tokens."
            ) from exc

        now = utc_now()
        connection.access_token_encrypted = access_token_encrypted
        connection.refresh_token_encrypted = refresh_token_encrypted
        if refreshed.expires_in is not None:
            connection.access_token_expires_at = now + timedelta(seconds=refreshed.expires_in)
        connection.granted_scopes = " ".join(refreshed_scopes)
        connection.token_key_version = self.token_cipher.active_key_version
        connection.updated_by_principal_id = connection.principal_id
        connection.last_refreshed_at = now
        connection.last_error = None
        self.provider_connection_repository.save(connection)
        self.session.commit()
        return refreshed.access_token

    def _resolve_refresh_token_encrypted(
        self,
        *,
        existing: ProviderConnection | None,
        received_refresh_token: str | None,
    ) -> str | None:
        if received_refresh_token:
            try:
                return self.token_cipher.encrypt(received_refresh_token)
            except TokenCipherError as exc:
                raise GoogleBusinessProfileConnectionConfigurationError(
                    "Unable to encrypt Google provider refresh token."
                ) from exc
        if existing is None or not existing.refresh_token_encrypted:
            return None
        try:
            prior_refresh = self.token_cipher.decrypt(
                existing.refresh_token_encrypted,
                key_version=existing.token_key_version,
            )
            return self.token_cipher.encrypt(prior_refresh)
        except TokenCipherError as exc:
            raise GoogleBusinessProfileConnectionConfigurationError(
                "Unable to preserve stored Google provider refresh token."
            ) from exc

    def _decrypt_state_code_verifier(self, oauth_state: ProviderOAuthState) -> str:
        if not oauth_state.code_verifier_encrypted or not oauth_state.code_verifier_key_version:
            raise GoogleBusinessProfileConnectionValidationError(
                "OAuth code verifier is missing. Restart the connection flow.",
                status_code=400,
                reconnect_required=True,
            )
        try:
            return self.token_cipher.decrypt(
                oauth_state.code_verifier_encrypted,
                key_version=oauth_state.code_verifier_key_version,
            )
        except TokenCipherError as exc:
            raise GoogleBusinessProfileConnectionValidationError(
                "OAuth code verifier could not be decrypted. Restart the connection flow.",
                status_code=400,
                reconnect_required=True,
            ) from exc

    def _status_from_connection(
        self,
        connection: ProviderConnection,
        *,
        required_scopes: tuple[str, ...] | None = None,
    ) -> GoogleBusinessProfileConnectionStatusResult:
        required = (
            self._normalize_required_scopes((self.BUSINESS_PROFILE_SCOPE,))
            if required_scopes is None
            else required_scopes
        )
        granted_scopes = self._normalize_scopes(connection.granted_scopes)
        granted_set = set(granted_scopes)
        required_scopes_satisfied = all(scope in granted_set for scope in required)
        refresh_token_present = bool(connection.refresh_token_encrypted)

        reconnect_required = False
        token_status: TokenUsabilityStatus = self.TOKEN_STATUS_USABLE
        if not connection.is_active:
            reconnect_required = True
            token_status = self.TOKEN_STATUS_RECONNECT_REQUIRED
        elif not required_scopes_satisfied:
            reconnect_required = True
            token_status = self.TOKEN_STATUS_INSUFFICIENT_SCOPE
        elif not refresh_token_present:
            reconnect_required = True
            token_status = self.TOKEN_STATUS_RECONNECT_REQUIRED
        elif not connection.access_token_encrypted:
            token_status = self.TOKEN_STATUS_REFRESH_REQUIRED
        elif self._access_token_needs_refresh(connection):
            token_status = self.TOKEN_STATUS_REFRESH_REQUIRED

        return GoogleBusinessProfileConnectionStatusResult(
            provider=connection.provider,
            connected=bool(connection.is_active),
            business_id=connection.business_id,
            granted_scopes=granted_scopes,
            refresh_token_present=refresh_token_present,
            expires_at=connection.access_token_expires_at.isoformat() if connection.access_token_expires_at else None,
            connected_at=connection.connected_at.isoformat() if connection.connected_at else None,
            last_refreshed_at=connection.last_refreshed_at.isoformat() if connection.last_refreshed_at else None,
            reconnect_required=reconnect_required,
            required_scopes_satisfied=required_scopes_satisfied,
            token_status=token_status,
        )

    def _status_without_connection(
        self,
        *,
        business_id: str,
        required_scopes: tuple[str, ...],
    ) -> GoogleBusinessProfileConnectionStatusResult:
        return GoogleBusinessProfileConnectionStatusResult(
            provider=self.PROVIDER,
            connected=False,
            business_id=business_id,
            granted_scopes=(),
            refresh_token_present=False,
            expires_at=None,
            connected_at=None,
            last_refreshed_at=None,
            reconnect_required=True,
            required_scopes_satisfied=not required_scopes,
            token_status=self.TOKEN_STATUS_RECONNECT_REQUIRED,
        )

    def _status_with_override(
        self,
        *,
        connection: ProviderConnection,
        required_scopes: tuple[str, ...],
        token_status: TokenUsabilityStatus,
        reconnect_required: bool,
    ) -> GoogleBusinessProfileConnectionStatusResult:
        base = self._status_from_connection(connection, required_scopes=required_scopes)
        return GoogleBusinessProfileConnectionStatusResult(
            provider=base.provider,
            connected=base.connected,
            business_id=base.business_id,
            granted_scopes=base.granted_scopes,
            refresh_token_present=base.refresh_token_present,
            expires_at=base.expires_at,
            connected_at=base.connected_at,
            last_refreshed_at=base.last_refreshed_at,
            reconnect_required=reconnect_required,
            required_scopes_satisfied=base.required_scopes_satisfied,
            token_status=token_status,
        )

    def _token_use_from_status(
        self,
        *,
        status: GoogleBusinessProfileConnectionStatusResult,
        access_token: str | None,
    ) -> GoogleBusinessProfileTokenUseResult:
        return GoogleBusinessProfileTokenUseResult(
            provider=status.provider,
            connected=status.connected,
            business_id=status.business_id,
            granted_scopes=status.granted_scopes,
            refresh_token_present=status.refresh_token_present,
            expires_at=status.expires_at,
            reconnect_required=status.reconnect_required,
            required_scopes_satisfied=status.required_scopes_satisfied,
            token_status=status.token_status,
            access_token=access_token,
        )

    def _access_token_needs_refresh(self, connection: ProviderConnection) -> bool:
        if connection.access_token_expires_at is None:
            return False
        refresh_at = connection.access_token_expires_at - timedelta(seconds=self.refresh_skew_seconds)
        now = utc_now()
        if refresh_at.tzinfo is None:
            now = now.replace(tzinfo=None)
        return refresh_at <= now

    def _ensure_business_and_active_principal(self, *, business_id: str, principal_id: str) -> None:
        self._ensure_business_exists(business_id)
        principal = self.principal_repository.get_for_business(business_id, principal_id)
        if principal is None:
            raise GoogleBusinessProfileConnectionNotFoundError("Principal not found.")
        if not principal.is_active:
            raise GoogleBusinessProfileConnectionValidationError(
                "Principal is inactive.",
                status_code=403,
            )

    def _ensure_business_exists(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise GoogleBusinessProfileConnectionNotFoundError("Business not found.")

    def _normalize_required_scopes(self, scopes: Sequence[str] | None) -> tuple[str, ...]:
        if scopes is None:
            return (self.BUSINESS_PROFILE_SCOPE,)
        flattened: list[str] = []
        for scope in scopes:
            if not scope:
                continue
            flattened.extend(part for part in scope.split(" ") if part.strip())
        if not flattened:
            return ()
        return tuple(sorted({part.strip() for part in flattened if part.strip()}))

    def _normalize_scopes(self, raw_scope: str | None) -> tuple[str, ...]:
        if not raw_scope:
            return ()
        unique = {scope.strip() for scope in raw_scope.split(" ") if scope.strip()}
        return tuple(sorted(unique))


def _hash_state(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def _generate_pkce_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("utf-8").rstrip("=")


def _build_pkce_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

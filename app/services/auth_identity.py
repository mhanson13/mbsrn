from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.session_token import AppSessionTokenError, AppSessionTokenService, IssuedAppSessionTokens
from app.integrations.google_auth import (
    GoogleIdentityClaims,
    GoogleOIDCJWKSVerifier,
    GoogleOIDCVerificationError,
)
from app.models.principal import Principal
from app.repositories.principal_identity_repository import PrincipalIdentityRepository
from app.repositories.principal_repository import PrincipalRepository
from app.services.auth_audit import AuthAuditService


class AuthIdentityNotFoundError(ValueError):
    pass


class AuthIdentityValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthExchangeResult:
    access_token: str
    refresh_token: str
    expires_at: str
    refresh_expires_at: str
    principal: Principal
    auth_source: str


class AuthIdentityService:
    GOOGLE_PROVIDER = "google"
    AUTH_SOURCE = "google_oidc_session"
    TARGET_SESSION = "session"
    EVENT_REFRESH_REPLAY_DETECTED = "session_refresh_replay_detected"
    EVENT_LOGOUT = "session_logout"

    def __init__(
        self,
        *,
        session: Session,
        principal_repository: PrincipalRepository,
        principal_identity_repository: PrincipalIdentityRepository,
        oidc_verifier: GoogleOIDCJWKSVerifier,
        session_token_service: AppSessionTokenService,
        auth_audit_service: AuthAuditService,
    ) -> None:
        self.session = session
        self.principal_repository = principal_repository
        self.principal_identity_repository = principal_identity_repository
        self.oidc_verifier = oidc_verifier
        self.session_token_service = session_token_service
        self.auth_audit_service = auth_audit_service

    def exchange_google_id_token(self, *, id_token: str) -> AuthExchangeResult:
        try:
            claims = self.oidc_verifier.verify_id_token(id_token)
        except GoogleOIDCVerificationError as exc:
            raise AuthIdentityValidationError(str(exc)) from exc

        identity = self._get_active_identity_from_claims(claims)
        principal = self.principal_repository.get_for_business(identity.business_id, identity.principal_id)
        if principal is None:
            raise AuthIdentityNotFoundError("Principal not found for identity mapping.")
        if not principal.is_active:
            raise AuthIdentityValidationError("Principal is inactive.")

        identity.email = claims.email
        identity.email_verified = claims.email_verified
        self.principal_identity_repository.mark_last_authenticated_for_identity(identity)
        self.principal_repository.mark_last_authenticated(
            business_id=principal.business_id,
            principal_id=principal.id,
        )
        self.session.commit()

        issued: IssuedAppSessionTokens = self.session_token_service.issue(
            business_id=principal.business_id,
            principal_id=principal.id,
            principal_role=principal.role.value,
            auth_source=self.AUTH_SOURCE,
            principal_identity_id=identity.id,
        )
        return AuthExchangeResult(
            access_token=issued.access_token,
            refresh_token=issued.refresh_token,
            expires_at=issued.access_expires_at.isoformat(),
            refresh_expires_at=issued.refresh_expires_at.isoformat(),
            principal=principal,
            auth_source=self.AUTH_SOURCE,
        )

    def refresh_session(self, *, refresh_token: str) -> AuthExchangeResult:
        try:
            rotation = self.session_token_service.rotate_refresh_token(refresh_token)
        except AppSessionTokenError as exc:
            raise AuthIdentityValidationError(str(exc)) from exc

        claims = rotation.claims
        if claims is None:
            raise AuthIdentityValidationError("Invalid refresh token.")

        principal = self.principal_repository.get_for_business(claims.business_id, claims.principal_id)
        if principal is None:
            raise AuthIdentityNotFoundError("Principal not found for identity mapping.")
        if not principal.is_active:
            self.session_token_service.revoke_principal_sessions(
                business_id=claims.business_id,
                principal_id=claims.principal_id,
            )
            self.session.commit()
            raise AuthIdentityValidationError("Principal is inactive.")

        if claims.principal_identity_id:
            identity = self.principal_identity_repository.get_for_business(
                business_id=claims.business_id,
                identity_id=claims.principal_identity_id,
            )
            if identity is None or not identity.is_active:
                self.session_token_service.revoke_identity_sessions(identity_id=claims.principal_identity_id)
                self.session.commit()
                raise AuthIdentityValidationError("Identity mapping is inactive.")
            self.principal_identity_repository.mark_last_authenticated_for_identity(identity)

        if rotation.status == "reused":
            self.session_token_service.revoke_principal_sessions(
                business_id=claims.business_id,
                principal_id=claims.principal_id,
            )
            if claims.principal_identity_id:
                self.session_token_service.revoke_identity_sessions(identity_id=claims.principal_identity_id)
            self.auth_audit_service.record_event(
                business_id=claims.business_id,
                actor_principal_id=claims.principal_id,
                target_type=self.TARGET_SESSION,
                target_id=claims.principal_id,
                event_type=self.EVENT_REFRESH_REPLAY_DETECTED,
                details={
                    "action": "auth_refresh",
                    "principal_identity_id": claims.principal_identity_id,
                    "auth_source": claims.auth_source,
                },
            )
            self.session.commit()
            raise AuthIdentityValidationError("Refresh token replay detected.")
        if rotation.status != "ok":
            raise AuthIdentityValidationError("Invalid refresh token.")

        issued = self.session_token_service.issue_from_refresh(
            refresh_claims=claims,
            principal_role=principal.role.value,
            auth_source=claims.auth_source or self.AUTH_SOURCE,
        )
        self.principal_repository.mark_last_authenticated(
            business_id=principal.business_id,
            principal_id=principal.id,
        )
        self.session.commit()
        return AuthExchangeResult(
            access_token=issued.access_token,
            refresh_token=issued.refresh_token,
            expires_at=issued.access_expires_at.isoformat(),
            refresh_expires_at=issued.refresh_expires_at.isoformat(),
            principal=principal,
            auth_source=claims.auth_source or self.AUTH_SOURCE,
        )

    def logout_session(self, *, access_token: str, refresh_token: str | None = None) -> None:
        try:
            access_claims = self.session_token_service.verify_access_token(access_token)
        except AppSessionTokenError as exc:
            raise AuthIdentityValidationError("Invalid access token.") from exc

        self.session_token_service.revoke_token(claims=access_claims)
        refresh_revoked = False
        if refresh_token:
            try:
                refresh_claims = self.session_token_service.verify_refresh_token(refresh_token)
            except AppSessionTokenError:
                refresh_claims = None
            if refresh_claims is not None:
                if (
                    refresh_claims.business_id != access_claims.business_id
                    or refresh_claims.principal_id != access_claims.principal_id
                ):
                    raise AuthIdentityValidationError("Refresh token scope mismatch.")
                self.session_token_service.revoke_token(claims=refresh_claims)
                refresh_revoked = True

        self.auth_audit_service.record_event(
            business_id=access_claims.business_id,
            actor_principal_id=access_claims.principal_id,
            target_type=self.TARGET_SESSION,
            target_id=access_claims.principal_id,
            event_type=self.EVENT_LOGOUT,
            details={
                "action": "auth_logout",
                "auth_source": access_claims.auth_source,
                "principal_identity_id": access_claims.principal_identity_id,
                "refresh_revoked": refresh_revoked,
            },
        )
        self.session.commit()

    def _get_active_identity_from_claims(self, claims: GoogleIdentityClaims):
        if claims.provider != self.GOOGLE_PROVIDER:
            raise AuthIdentityValidationError("Unsupported identity provider.")

        identity = self.principal_identity_repository.get_active_by_provider_subject(
            provider=claims.provider,
            provider_subject=claims.subject,
        )
        if identity is None:
            raise AuthIdentityNotFoundError("Identity mapping not found.")
        return identity

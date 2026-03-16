from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.session_token import AppSessionTokenService, IssuedAppSessionToken
from app.integrations.google_auth import (
    GoogleIdentityClaims,
    GoogleOIDCTokenInfoVerifier,
    GoogleOIDCVerificationError,
)
from app.models.principal import Principal
from app.repositories.principal_identity_repository import PrincipalIdentityRepository
from app.repositories.principal_repository import PrincipalRepository


class AuthIdentityNotFoundError(ValueError):
    pass


class AuthIdentityValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthExchangeResult:
    access_token: str
    expires_at: str
    principal: Principal
    auth_source: str


class AuthIdentityService:
    GOOGLE_PROVIDER = "google"
    AUTH_SOURCE = "google_oidc_session"

    def __init__(
        self,
        *,
        session: Session,
        principal_repository: PrincipalRepository,
        principal_identity_repository: PrincipalIdentityRepository,
        oidc_verifier: GoogleOIDCTokenInfoVerifier,
        session_token_service: AppSessionTokenService,
    ) -> None:
        self.session = session
        self.principal_repository = principal_repository
        self.principal_identity_repository = principal_identity_repository
        self.oidc_verifier = oidc_verifier
        self.session_token_service = session_token_service

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

        issued: IssuedAppSessionToken = self.session_token_service.issue(
            business_id=principal.business_id,
            principal_id=principal.id,
            principal_role=principal.role.value,
            auth_source=self.AUTH_SOURCE,
        )
        return AuthExchangeResult(
            access_token=issued.token,
            expires_at=issued.expires_at.isoformat(),
            principal=principal,
            auth_source=self.AUTH_SOURCE,
        )

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

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.session_token import AppSessionTokenService
from app.models.principal_identity import PrincipalIdentity
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_identity_repository import PrincipalIdentityRepository
from app.repositories.principal_repository import PrincipalRepository
from app.services.auth_audit import AuthAuditService


class PrincipalIdentityNotFoundError(ValueError):
    pass


class PrincipalIdentityValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PrincipalIdentityCreateInput:
    provider: str
    provider_subject: str
    principal_id: str
    email: str | None
    email_verified: bool
    is_active: bool


class PrincipalIdentityService:
    TARGET_TYPE = "principal_identity"
    EVENT_CREATED = "principal_identity_created"
    EVENT_UPDATED = "principal_identity_updated"
    EVENT_ACTIVATED = "principal_identity_activated"
    EVENT_DEACTIVATED = "principal_identity_deactivated"

    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        principal_repository: PrincipalRepository,
        principal_identity_repository: PrincipalIdentityRepository,
        auth_audit_service: AuthAuditService,
        session_token_service: AppSessionTokenService | None = None,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.principal_repository = principal_repository
        self.principal_identity_repository = principal_identity_repository
        self.auth_audit_service = auth_audit_service
        self.session_token_service = session_token_service

    def list_for_business(self, *, business_id: str) -> list[PrincipalIdentity]:
        self._ensure_business_exists(business_id)
        return self.principal_identity_repository.list_for_business(business_id=business_id)

    def create_identity(
        self,
        *,
        business_id: str,
        payload: PrincipalIdentityCreateInput,
        actor_principal_id: str | None = None,
    ) -> PrincipalIdentity:
        self._ensure_business_exists(business_id)
        principal_id = self._normalize_principal_id(payload.principal_id)
        principal = self.principal_repository.get_for_business(business_id, principal_id)
        if principal is None:
            raise PrincipalIdentityNotFoundError("Principal not found")

        provider = self._normalize_provider(payload.provider)
        provider_subject = self._normalize_provider_subject(payload.provider_subject)
        email = self._normalize_email(payload.email)

        existing = self.principal_identity_repository.get_by_provider_subject(
            provider=provider,
            provider_subject=provider_subject,
        )
        if existing is not None and (
            existing.business_id != business_id or existing.principal_id != principal_id
        ):
            raise PrincipalIdentityValidationError(
                "Identity subject is already mapped to a different principal."
            )

        if existing is not None:
            existing.email = email
            existing.email_verified = payload.email_verified
            existing.is_active = payload.is_active
            if not existing.is_active and self.session_token_service is not None:
                self.session_token_service.revoke_identity_sessions(identity_id=existing.id)
            self.principal_identity_repository.save(existing)
            self.auth_audit_service.record_event(
                business_id=business_id,
                actor_principal_id=actor_principal_id,
                target_type=self.TARGET_TYPE,
                target_id=existing.id,
                event_type=self.EVENT_UPDATED,
                details={
                    "provider": existing.provider,
                    "provider_subject": existing.provider_subject,
                    "principal_id": existing.principal_id,
                    "is_active": existing.is_active,
                },
            )
            self.session.commit()
            self.session.refresh(existing)
            return existing

        identity = PrincipalIdentity(
            id=str(uuid4()),
            provider=provider,
            provider_subject=provider_subject,
            business_id=business_id,
            principal_id=principal.id,
            email=email,
            email_verified=payload.email_verified,
            is_active=payload.is_active,
        )
        try:
            self.principal_identity_repository.create(identity)
        except IntegrityError as exc:
            self.session.rollback()
            raise PrincipalIdentityValidationError("Principal identity mapping already exists.") from exc

        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=actor_principal_id,
            target_type=self.TARGET_TYPE,
            target_id=identity.id,
            event_type=self.EVENT_CREATED,
            details={
                "provider": identity.provider,
                "provider_subject": identity.provider_subject,
                "principal_id": identity.principal_id,
                "is_active": identity.is_active,
            },
        )
        self.session.commit()
        self.session.refresh(identity)
        return identity

    def activate_identity(
        self,
        *,
        business_id: str,
        identity_id: str,
        actor_principal_id: str | None = None,
    ) -> PrincipalIdentity:
        identity = self._get_for_business(business_id=business_id, identity_id=identity_id)
        identity.is_active = True
        self.principal_identity_repository.save(identity)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=actor_principal_id,
            target_type=self.TARGET_TYPE,
            target_id=identity.id,
            event_type=self.EVENT_ACTIVATED,
            details={
                "provider": identity.provider,
                "provider_subject": identity.provider_subject,
                "principal_id": identity.principal_id,
            },
        )
        self.session.commit()
        self.session.refresh(identity)
        return identity

    def deactivate_identity(
        self,
        *,
        business_id: str,
        identity_id: str,
        actor_principal_id: str | None = None,
    ) -> PrincipalIdentity:
        identity = self._get_for_business(business_id=business_id, identity_id=identity_id)
        identity.is_active = False
        if self.session_token_service is not None:
            self.session_token_service.revoke_identity_sessions(identity_id=identity.id)
        self.principal_identity_repository.save(identity)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=actor_principal_id,
            target_type=self.TARGET_TYPE,
            target_id=identity.id,
            event_type=self.EVENT_DEACTIVATED,
            details={
                "provider": identity.provider,
                "provider_subject": identity.provider_subject,
                "principal_id": identity.principal_id,
            },
        )
        self.session.commit()
        self.session.refresh(identity)
        return identity

    def _get_for_business(self, *, business_id: str, identity_id: str) -> PrincipalIdentity:
        self._ensure_business_exists(business_id)
        identity = self.principal_identity_repository.get_for_business(
            business_id=business_id,
            identity_id=identity_id,
        )
        if identity is None:
            raise PrincipalIdentityNotFoundError("Principal identity not found")
        return identity

    def _ensure_business_exists(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise PrincipalIdentityNotFoundError("Business not found")

    def _normalize_provider(self, provider: str) -> str:
        normalized = provider.strip().lower()
        if not normalized:
            raise PrincipalIdentityValidationError("provider is required.")
        if len(normalized) > 32:
            raise PrincipalIdentityValidationError("provider must be 32 characters or fewer.")
        return normalized

    def _normalize_provider_subject(self, provider_subject: str) -> str:
        normalized = provider_subject.strip()
        if not normalized:
            raise PrincipalIdentityValidationError("provider_subject is required.")
        if len(normalized) > 255:
            raise PrincipalIdentityValidationError("provider_subject must be 255 characters or fewer.")
        return normalized

    def _normalize_principal_id(self, principal_id: str) -> str:
        normalized = principal_id.strip()
        if not normalized:
            raise PrincipalIdentityValidationError("principal_id is required.")
        if len(normalized) > 64:
            raise PrincipalIdentityValidationError("principal_id must be 64 characters or fewer.")
        return normalized

    def _normalize_email(self, email: str | None) -> str | None:
        if email is None:
            return None
        normalized = email.strip().lower()
        if not normalized:
            return None
        if len(normalized) > 320:
            raise PrincipalIdentityValidationError("email must be 320 characters or fewer.")
        return normalized

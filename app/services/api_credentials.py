from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.api_credential import APICredential
from app.models.principal import Principal, PrincipalRole
from app.repositories.api_credential_repository import APICredentialRepository
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_repository import PrincipalRepository
from app.services.auth_audit import AuthAuditService


class APICredentialNotFoundError(ValueError):
    pass


class APICredentialValidationError(ValueError):
    pass


@dataclass(frozen=True)
class IssuedAPICredential:
    credential: APICredential
    token: str


class APICredentialService:
    PRINCIPAL_TARGET = "principal"
    CREDENTIAL_TARGET = "api_credential"
    EVENT_PRINCIPAL_CREATED = "principal_created"
    EVENT_PRINCIPAL_UPDATED = "principal_updated"
    EVENT_CREDENTIAL_CREATED = "credential_created"
    EVENT_CREDENTIAL_DISABLED = "credential_disabled"
    EVENT_CREDENTIAL_REVOKED = "credential_revoked"
    EVENT_CREDENTIAL_ROTATED = "credential_rotated"

    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        principal_repository: PrincipalRepository,
        api_credential_repository: APICredentialRepository,
        auth_audit_service: AuthAuditService,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.principal_repository = principal_repository
        self.api_credential_repository = api_credential_repository
        self.auth_audit_service = auth_audit_service

    def list_for_business(self, *, business_id: str) -> list[APICredential]:
        self._ensure_business_exists(business_id)
        return self.api_credential_repository.list_for_business(business_id)

    def create_credential(
        self,
        *,
        business_id: str,
        principal_id: str,
        principal_display_name: str | None = None,
        principal_role: PrincipalRole | None = None,
        credential_label: str | None = None,
        actor_principal_id: str | None = None,
    ) -> IssuedAPICredential:
        self._ensure_business_exists(business_id)
        normalized_principal_id = self._normalize_principal_id(principal_id)
        normalized_credential_label = self._normalize_credential_label(credential_label)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        principal = self._ensure_principal(
            business_id=business_id,
            principal_id=normalized_principal_id,
            principal_display_name=principal_display_name,
            principal_role=principal_role,
            actor_principal_id=normalized_actor_principal_id,
        )
        issued = self._issue_new_credential(
            business_id=business_id,
            principal_id=principal.id,
            credential_label=normalized_credential_label,
        )
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=normalized_actor_principal_id,
            target_type=self.CREDENTIAL_TARGET,
            target_id=issued.credential.id,
            event_type=self.EVENT_CREDENTIAL_CREATED,
            details={
                "principal_id": issued.credential.principal_id,
                "label": issued.credential.label,
            },
        )
        self.session.commit()
        self.session.refresh(issued.credential)
        return issued

    def disable_credential(
        self,
        *,
        business_id: str,
        credential_id: str,
        actor_principal_id: str | None = None,
    ) -> APICredential:
        credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        credential.is_active = False
        self.api_credential_repository.save(credential)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=normalized_actor_principal_id,
            target_type=self.CREDENTIAL_TARGET,
            target_id=credential.id,
            event_type=self.EVENT_CREDENTIAL_DISABLED,
            details={"principal_id": credential.principal_id},
        )
        self.session.commit()
        self.session.refresh(credential)
        return credential

    def revoke_credential(
        self,
        *,
        business_id: str,
        credential_id: str,
        actor_principal_id: str | None = None,
    ) -> APICredential:
        credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        if credential.revoked_at is None:
            credential.revoked_at = utc_now()
        credential.is_active = False
        self.api_credential_repository.save(credential)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=normalized_actor_principal_id,
            target_type=self.CREDENTIAL_TARGET,
            target_id=credential.id,
            event_type=self.EVENT_CREDENTIAL_REVOKED,
            details={"principal_id": credential.principal_id},
        )
        self.session.commit()
        self.session.refresh(credential)
        return credential

    def rotate_credential(
        self,
        *,
        business_id: str,
        credential_id: str,
        actor_principal_id: str | None = None,
    ) -> IssuedAPICredential:
        credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        if credential.revoked_at is not None:
            raise APICredentialValidationError("Credential is already revoked and cannot be rotated.")
        principal = self.principal_repository.get_for_business(business_id, credential.principal_id)
        if principal is None:
            raise APICredentialValidationError("Credential principal is missing.")
        if not principal.is_active:
            raise APICredentialValidationError("Credential principal is inactive and cannot be rotated.")

        for _ in range(3):
            token = secrets.token_urlsafe(32)
            replacement = APICredential(
                id=str(uuid4()),
                business_id=business_id,
                principal_id=principal.id,
                token_hash=self.api_credential_repository.hash_token(token),
                label=credential.label,
                rotated_from_credential_id=credential.id,
                is_active=True,
                revoked_at=None,
            )
            try:
                credential.is_active = False
                credential.revoked_at = utc_now()
                self.api_credential_repository.save(credential)
                self.api_credential_repository.create(replacement)
                self.auth_audit_service.record_event(
                    business_id=business_id,
                    actor_principal_id=normalized_actor_principal_id,
                    target_type=self.CREDENTIAL_TARGET,
                    target_id=replacement.id,
                    event_type=self.EVENT_CREDENTIAL_ROTATED,
                    details={
                        "principal_id": replacement.principal_id,
                        "label": replacement.label,
                        "replaced_credential_id": credential.id,
                    },
                )
                self.session.commit()
                refreshed = self.api_credential_repository.get_for_business(business_id, replacement.id)
                return IssuedAPICredential(credential=refreshed or replacement, token=token)
            except IntegrityError:
                self.session.rollback()
                credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
                if credential.revoked_at is not None:
                    raise APICredentialValidationError("Credential is already revoked and cannot be rotated.")

        raise APICredentialValidationError("Unable to rotate credential token. Retry request.")

    def _issue_new_credential(
        self,
        *,
        business_id: str,
        principal_id: str,
        credential_label: str | None,
    ) -> IssuedAPICredential:
        # Token is generated once and only returned at issue/rotate time.
        for _ in range(3):
            token = secrets.token_urlsafe(32)
            credential = APICredential(
                id=str(uuid4()),
                business_id=business_id,
                principal_id=principal_id,
                token_hash=self.api_credential_repository.hash_token(token),
                label=credential_label,
                is_active=True,
                revoked_at=None,
            )
            try:
                self.api_credential_repository.create(credential)
                refreshed = self.api_credential_repository.get_for_business(business_id, credential.id)
                return IssuedAPICredential(credential=refreshed or credential, token=token)
            except IntegrityError:
                self.session.rollback()
                continue
        raise APICredentialValidationError("Unable to issue credential token. Retry request.")

    def _normalize_principal_id(self, principal_id: str) -> str:
        normalized = principal_id.strip()
        if not normalized:
            raise APICredentialValidationError("principal_id is required.")
        if len(normalized) > 64:
            raise APICredentialValidationError("principal_id must be 64 characters or fewer.")
        return normalized

    def _normalize_credential_label(self, credential_label: str | None) -> str | None:
        if credential_label is None:
            return None
        normalized = credential_label.strip()
        if not normalized:
            return None
        if len(normalized) > 128:
            raise APICredentialValidationError("credential_label must be 128 characters or fewer.")
        return normalized

    def _normalize_principal_display_name(self, principal_display_name: str | None) -> str | None:
        if principal_display_name is None:
            return None
        normalized = principal_display_name.strip()
        if not normalized:
            return None
        if len(normalized) > 255:
            raise APICredentialValidationError("principal_display_name must be 255 characters or fewer.")
        return normalized

    def _ensure_principal(
        self,
        *,
        business_id: str,
        principal_id: str,
        principal_display_name: str | None,
        principal_role: PrincipalRole | None,
        actor_principal_id: str | None,
    ) -> Principal:
        principal = self.principal_repository.get_for_business(business_id, principal_id)
        normalized_display_name = self._normalize_principal_display_name(principal_display_name)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)

        if principal is None:
            principal = Principal(
                business_id=business_id,
                id=principal_id,
                display_name=normalized_display_name or principal_id,
                created_by_principal_id=normalized_actor_principal_id,
                updated_by_principal_id=normalized_actor_principal_id,
                role=principal_role or PrincipalRole.OPERATOR,
                is_active=True,
            )
            self.principal_repository.create(principal)
            self.auth_audit_service.record_event(
                business_id=business_id,
                actor_principal_id=normalized_actor_principal_id,
                target_type=self.PRINCIPAL_TARGET,
                target_id=principal.id,
                event_type=self.EVENT_PRINCIPAL_CREATED,
                details={
                    "role": principal.role.value,
                    "is_active": principal.is_active,
                },
            )
            return principal

        if not principal.is_active:
            raise APICredentialValidationError("Principal is inactive.")

        changed = False
        if normalized_display_name and principal.display_name != normalized_display_name:
            principal.display_name = normalized_display_name
            changed = True
        if principal_role is not None and principal.role != principal_role:
            principal.role = principal_role
            changed = True
        if changed and normalized_actor_principal_id is not None:
            principal.updated_by_principal_id = normalized_actor_principal_id
        if changed:
            self.principal_repository.save(principal)
            updated_fields: list[str] = []
            if normalized_display_name and principal.display_name == normalized_display_name:
                updated_fields.append("display_name")
            if principal_role is not None:
                updated_fields.append("role")
            self.auth_audit_service.record_event(
                business_id=business_id,
                actor_principal_id=normalized_actor_principal_id,
                target_type=self.PRINCIPAL_TARGET,
                target_id=principal.id,
                event_type=self.EVENT_PRINCIPAL_UPDATED,
                details={
                    "updated_fields": sorted(updated_fields),
                    "role": principal.role.value,
                    "is_active": principal.is_active,
                },
            )

        return principal

    def _normalize_actor_principal_id(self, actor_principal_id: str | None) -> str | None:
        if actor_principal_id is None:
            return None
        return self._normalize_principal_id(actor_principal_id)

    def _ensure_business_exists(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise APICredentialNotFoundError("Business not found")

    def _get_for_business(self, *, business_id: str, credential_id: str) -> APICredential:
        self._ensure_business_exists(business_id)
        credential = self.api_credential_repository.get_for_business(business_id, credential_id)
        if credential is None:
            raise APICredentialNotFoundError("API credential not found")
        return credential

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.principal import Principal, PrincipalRole
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_repository import PrincipalRepository
from app.services.auth_audit import AuthAuditService
from app.schemas.principal import PrincipalUpdateRequest


class PrincipalNotFoundError(ValueError):
    pass


class PrincipalValidationError(ValueError):
    pass


class PrincipalService:
    PRINCIPAL_TARGET = "principal"
    EVENT_PRINCIPAL_CREATED = "principal_created"
    EVENT_PRINCIPAL_UPDATED = "principal_updated"
    EVENT_PRINCIPAL_ACTIVATED = "principal_activated"
    EVENT_PRINCIPAL_DEACTIVATED = "principal_deactivated"

    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        principal_repository: PrincipalRepository,
        auth_audit_service: AuthAuditService,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.principal_repository = principal_repository
        self.auth_audit_service = auth_audit_service

    def list_for_business(self, *, business_id: str) -> list[Principal]:
        self._ensure_business_exists(business_id)
        return self.principal_repository.list_for_business(business_id)

    def create_principal(
        self,
        *,
        business_id: str,
        principal_id: str,
        display_name: str | None = None,
        role: PrincipalRole = PrincipalRole.OPERATOR,
        actor_principal_id: str | None = None,
    ) -> Principal:
        self._ensure_business_exists(business_id)
        normalized_principal_id = self._normalize_principal_id(principal_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        existing = self.principal_repository.get_for_business(business_id, normalized_principal_id)
        if existing is not None:
            raise PrincipalValidationError("Principal already exists.")

        principal = Principal(
            business_id=business_id,
            id=normalized_principal_id,
            display_name=self._normalize_display_name(display_name) or normalized_principal_id,
            created_by_principal_id=normalized_actor_principal_id,
            updated_by_principal_id=normalized_actor_principal_id,
            role=role,
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
        self.session.commit()
        self.session.refresh(principal)
        return principal

    def update_principal(
        self,
        *,
        business_id: str,
        principal_id: str,
        payload: PrincipalUpdateRequest,
        actor_principal_id: str | None = None,
    ) -> Principal:
        principal = self._get_for_business(business_id=business_id, principal_id=principal_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return principal

        next_role = updates.get("role", principal.role)
        next_is_active = updates.get("is_active", principal.is_active)
        self._validate_admin_retention(
            business_id=business_id,
            principal=principal,
            next_role=next_role,
            next_is_active=next_is_active,
        )

        if "display_name" in updates:
            principal.display_name = self._normalize_display_name(updates["display_name"]) or principal.id
        if "role" in updates:
            principal.role = updates["role"]
        if "is_active" in updates:
            principal.is_active = bool(updates["is_active"])
        if normalized_actor_principal_id is not None:
            principal.updated_by_principal_id = normalized_actor_principal_id

        self.principal_repository.save(principal)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=normalized_actor_principal_id,
            target_type=self.PRINCIPAL_TARGET,
            target_id=principal.id,
            event_type=self.EVENT_PRINCIPAL_UPDATED,
            details={
                "updated_fields": sorted(list(updates.keys())),
                "role": principal.role.value,
                "is_active": principal.is_active,
            },
        )
        self.session.commit()
        self.session.refresh(principal)
        return principal

    def activate_principal(
        self,
        *,
        business_id: str,
        principal_id: str,
        actor_principal_id: str | None = None,
    ) -> Principal:
        principal = self._get_for_business(business_id=business_id, principal_id=principal_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        if principal.is_active:
            return principal
        principal.is_active = True
        if normalized_actor_principal_id is not None:
            principal.updated_by_principal_id = normalized_actor_principal_id
        self.principal_repository.save(principal)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=normalized_actor_principal_id,
            target_type=self.PRINCIPAL_TARGET,
            target_id=principal.id,
            event_type=self.EVENT_PRINCIPAL_ACTIVATED,
            details={"is_active": True},
        )
        self.session.commit()
        self.session.refresh(principal)
        return principal

    def deactivate_principal(
        self,
        *,
        business_id: str,
        principal_id: str,
        actor_principal_id: str | None = None,
    ) -> Principal:
        principal = self._get_for_business(business_id=business_id, principal_id=principal_id)
        normalized_actor_principal_id = self._normalize_actor_principal_id(actor_principal_id)
        self._validate_admin_retention(
            business_id=business_id,
            principal=principal,
            next_role=principal.role,
            next_is_active=False,
        )
        if not principal.is_active:
            return principal
        principal.is_active = False
        if normalized_actor_principal_id is not None:
            principal.updated_by_principal_id = normalized_actor_principal_id
        self.principal_repository.save(principal)
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=normalized_actor_principal_id,
            target_type=self.PRINCIPAL_TARGET,
            target_id=principal.id,
            event_type=self.EVENT_PRINCIPAL_DEACTIVATED,
            details={"is_active": False},
        )
        self.session.commit()
        self.session.refresh(principal)
        return principal

    def _validate_admin_retention(
        self,
        *,
        business_id: str,
        principal: Principal,
        next_role: PrincipalRole,
        next_is_active: bool,
    ) -> None:
        if principal.role != PrincipalRole.ADMIN or not principal.is_active:
            return
        if next_role == PrincipalRole.ADMIN and next_is_active:
            return
        if self.principal_repository.count_active_admins(business_id) <= 1:
            raise PrincipalValidationError("Cannot deactivate or demote the last active admin principal.")

    def _normalize_principal_id(self, principal_id: str) -> str:
        normalized = principal_id.strip()
        if not normalized:
            raise PrincipalValidationError("principal_id is required.")
        if len(normalized) > 64:
            raise PrincipalValidationError("principal_id must be 64 characters or fewer.")
        return normalized

    def _normalize_display_name(self, display_name: str | None) -> str | None:
        if display_name is None:
            return None
        normalized = display_name.strip()
        if not normalized:
            return None
        if len(normalized) > 255:
            raise PrincipalValidationError("display_name must be 255 characters or fewer.")
        return normalized

    def _normalize_actor_principal_id(self, actor_principal_id: str | None) -> str | None:
        if actor_principal_id is None:
            return None
        return self._normalize_principal_id(actor_principal_id)

    def _ensure_business_exists(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise PrincipalNotFoundError("Business not found")

    def _get_for_business(self, *, business_id: str, principal_id: str) -> Principal:
        self._ensure_business_exists(business_id)
        principal = self.principal_repository.get_for_business(business_id, principal_id)
        if principal is None:
            raise PrincipalNotFoundError("Principal not found")
        return principal

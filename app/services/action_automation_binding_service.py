from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_action_execution_item_repository import SEOActionExecutionItemRepository
from app.repositories.seo_automation_repository import SEOAutomationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.action_chaining import BoundActionAutomationRead


class SEOActionAutomationBindingNotFoundError(ValueError):
    pass


class SEOActionAutomationBindingValidationError(ValueError):
    pass


class SEOActionAutomationBindingConflictError(ValueError):
    pass


@dataclass(frozen=True)
class BoundActionAutomationResult:
    binding: BoundActionAutomationRead


class ActionAutomationBindingService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_action_chain_draft_repository: SEOActionChainDraftRepository,
        seo_action_execution_item_repository: SEOActionExecutionItemRepository,
        seo_automation_repository: SEOAutomationRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_action_chain_draft_repository = seo_action_chain_draft_repository
        self.seo_action_execution_item_repository = seo_action_execution_item_repository
        self.seo_automation_repository = seo_automation_repository

    def bind_activated_action_to_automation(
        self,
        *,
        business_id: str,
        site_id: str,
        action_execution_item_id: str,
        automation_id: str,
        actor_principal_id: str | None,
    ) -> BoundActionAutomationResult:
        del actor_principal_id  # reserved for future audit metadata

        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)

        action_record = self.seo_action_execution_item_repository.get_for_business_site_id(
            business_id=business_id,
            site_id=site_id,
            action_id=action_execution_item_id,
        )
        if action_record is None:
            raise SEOActionAutomationBindingNotFoundError("Action execution item not found")

        if not action_record.automation_ready:
            raise SEOActionAutomationBindingValidationError(
                "Action execution item is not automation-ready and cannot be bound"
            )

        draft_record = self.seo_action_chain_draft_repository.get_for_business_site_id(
            business_id=business_id,
            site_id=site_id,
            draft_id=action_record.source_draft_id,
        )
        if draft_record is None:
            raise SEOActionAutomationBindingValidationError(
                "Source chained draft is missing for action execution item"
            )
        if draft_record.activation_state != "activated" or draft_record.activated_action_id != action_record.id:
            raise SEOActionAutomationBindingValidationError(
                "Action execution item is not linked to an activated chained draft"
            )

        if action_record.automation_binding_state == "bound":
            if action_record.bound_automation_id == automation_id:
                return BoundActionAutomationResult(binding=self._to_binding_read(action_record))
            raise SEOActionAutomationBindingConflictError(
                "Action execution item is already bound to a different automation"
            )

        automation_record = self.seo_automation_repository.get_config_for_business_site_id(
            business_id=business_id,
            site_id=site_id,
            automation_config_id=automation_id,
        )
        if automation_record is None:
            raise SEOActionAutomationBindingNotFoundError("Automation record not found")

        action_record.bound_automation_id = automation_id
        action_record.automation_binding_state = "bound"
        action_record.automation_bound_at = utc_now()
        self.seo_action_execution_item_repository.save(action_record)
        self.session.commit()
        self.session.refresh(action_record)
        return BoundActionAutomationResult(binding=self._to_binding_read(action_record))

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOActionAutomationBindingNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> None:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOActionAutomationBindingNotFoundError("SEO site not found")

    @staticmethod
    def _to_binding_read(record) -> BoundActionAutomationRead:
        return BoundActionAutomationRead(
            action_execution_item_id=record.id,
            automation_binding_state=record.automation_binding_state,
            bound_automation_id=record.bound_automation_id,
            automation_bound_at=record.automation_bound_at,
            automation_ready=bool(record.automation_ready),
            automation_template_key=record.automation_template_key,
        )

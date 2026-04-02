from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_action_execution_item_repository import SEOActionExecutionItemRepository
from app.repositories.seo_automation_repository import SEOAutomationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.action_chaining import RequestedActionAutomationExecutionRead
from app.services.seo_automation import (
    SEOAutomationConflictError,
    SEOAutomationNotFoundError,
    SEOAutomationService,
    SEOAutomationValidationError,
)


logger = logging.getLogger(__name__)


class SEOActionAutomationExecutionNotFoundError(ValueError):
    pass


class SEOActionAutomationExecutionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RequestedActionAutomationExecutionResult:
    execution: RequestedActionAutomationExecutionRead


class ActionAutomationExecutionService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_action_chain_draft_repository: SEOActionChainDraftRepository,
        seo_action_execution_item_repository: SEOActionExecutionItemRepository,
        seo_automation_repository: SEOAutomationRepository,
        seo_automation_service: SEOAutomationService,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_action_chain_draft_repository = seo_action_chain_draft_repository
        self.seo_action_execution_item_repository = seo_action_execution_item_repository
        self.seo_automation_repository = seo_automation_repository
        self.seo_automation_service = seo_automation_service

    def request_bound_action_automation_execution(
        self,
        *,
        business_id: str,
        site_id: str,
        action_execution_item_id: str,
        actor_principal_id: str | None,
    ) -> RequestedActionAutomationExecutionResult:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)

        action_record = self.seo_action_execution_item_repository.get_for_business_site_id(
            business_id=business_id,
            site_id=site_id,
            action_id=action_execution_item_id,
        )
        if action_record is None:
            raise SEOActionAutomationExecutionNotFoundError("Action execution item not found")

        if not action_record.automation_ready:
            raise SEOActionAutomationExecutionValidationError(
                "Action execution item is not automation-ready"
            )
        if action_record.automation_binding_state != "bound" or not action_record.bound_automation_id:
            raise SEOActionAutomationExecutionValidationError(
                "Action execution item is not bound to automation"
            )

        draft_record = self.seo_action_chain_draft_repository.get_for_business_site_id(
            business_id=business_id,
            site_id=site_id,
            draft_id=action_record.source_draft_id,
        )
        if draft_record is None:
            raise SEOActionAutomationExecutionValidationError(
                "Source chained draft is missing for action execution item"
            )
        if draft_record.activation_state != "activated" or draft_record.activated_action_id != action_record.id:
            raise SEOActionAutomationExecutionValidationError(
                "Action execution item is not linked to an activated chained draft"
            )

        automation_config = self.seo_automation_repository.get_config_for_business_site_id(
            business_id=business_id,
            site_id=site_id,
            automation_config_id=action_record.bound_automation_id,
        )
        if automation_config is None:
            raise SEOActionAutomationExecutionNotFoundError("Bound automation record not found")

        now = utc_now()
        active_run = self.seo_automation_repository.get_active_run_for_business_site(
            business_id=business_id,
            site_id=site_id,
        )
        if active_run is not None and active_run.automation_config_id == action_record.bound_automation_id:
            self._apply_run_state(
                action_record=action_record,
                automation_run=active_run,
                requested_at=action_record.automation_execution_requested_at or now,
                requested_by=action_record.automation_execution_requested_by or actor_principal_id,
            )
            self.seo_action_execution_item_repository.save(action_record)
            self.session.commit()
            self.session.refresh(action_record)
            logger.info(
                "action_automation_execution_requested action_execution_item_id=%s bound_automation_id=%s "
                "automation_template_key=%s automation_run_id=%s resulting_execution_state=%s",
                action_record.id,
                action_record.bound_automation_id,
                action_record.automation_template_key,
                active_run.id,
                action_record.automation_execution_state,
            )
            return RequestedActionAutomationExecutionResult(execution=self._to_execution_read(action_record))

        try:
            run = self.seo_automation_service.trigger_manual_run(
                business_id=business_id,
                site_id=site_id,
                created_by_principal_id=actor_principal_id,
            )
        except SEOAutomationConflictError:
            active_run = self.seo_automation_repository.get_active_run_for_business_site(
                business_id=business_id,
                site_id=site_id,
            )
            if active_run is None or active_run.automation_config_id != action_record.bound_automation_id:
                raise SEOActionAutomationExecutionValidationError(
                    "Automation execution is already in progress for this site"
                ) from None
            self._apply_run_state(
                action_record=action_record,
                automation_run=active_run,
                requested_at=action_record.automation_execution_requested_at or now,
                requested_by=action_record.automation_execution_requested_by or actor_principal_id,
            )
            self.seo_action_execution_item_repository.save(action_record)
            self.session.commit()
            self.session.refresh(action_record)
            logger.info(
                "action_automation_execution_requested action_execution_item_id=%s bound_automation_id=%s "
                "automation_template_key=%s automation_run_id=%s resulting_execution_state=%s",
                action_record.id,
                action_record.bound_automation_id,
                action_record.automation_template_key,
                active_run.id,
                action_record.automation_execution_state,
            )
            return RequestedActionAutomationExecutionResult(execution=self._to_execution_read(action_record))
        except (SEOAutomationNotFoundError, SEOAutomationValidationError) as exc:
            raise SEOActionAutomationExecutionValidationError(str(exc)) from exc

        self._apply_run_state(
            action_record=action_record,
            automation_run=run,
            requested_at=now,
            requested_by=actor_principal_id,
        )
        self.seo_action_execution_item_repository.save(action_record)
        self.session.commit()
        self.session.refresh(action_record)
        logger.info(
            "action_automation_execution_requested action_execution_item_id=%s bound_automation_id=%s "
            "automation_template_key=%s automation_run_id=%s resulting_execution_state=%s",
            action_record.id,
            action_record.bound_automation_id,
            action_record.automation_template_key,
            run.id,
            action_record.automation_execution_state,
        )
        return RequestedActionAutomationExecutionResult(execution=self._to_execution_read(action_record))

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOActionAutomationExecutionNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> None:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOActionAutomationExecutionNotFoundError("SEO site not found")

    @staticmethod
    def _apply_run_state(*, action_record, automation_run, requested_at, requested_by) -> None:
        normalized_status = (automation_run.status or "").strip().lower()
        if normalized_status == "queued":
            execution_state = "requested"
        elif normalized_status == "running":
            execution_state = "running"
        elif normalized_status == "failed":
            execution_state = "failed"
        else:
            execution_state = "succeeded"

        action_record.automation_execution_state = execution_state
        action_record.automation_execution_requested_at = requested_at
        action_record.automation_execution_requested_by = requested_by
        action_record.last_automation_run_id = automation_run.id
        if normalized_status in {"completed", "failed", "skipped"}:
            action_record.automation_last_executed_at = automation_run.finished_at or utc_now()

    @staticmethod
    def _to_execution_read(record) -> RequestedActionAutomationExecutionRead:
        return RequestedActionAutomationExecutionRead(
            action_execution_item_id=record.id,
            automation_binding_state=record.automation_binding_state,
            bound_automation_id=record.bound_automation_id,
            automation_bound_at=record.automation_bound_at,
            automation_execution_state=record.automation_execution_state,
            automation_execution_requested_at=record.automation_execution_requested_at,
            last_automation_run_id=record.last_automation_run_id,
            automation_last_executed_at=record.automation_last_executed_at,
            automation_ready=bool(record.automation_ready),
            automation_template_key=record.automation_template_key,
        )


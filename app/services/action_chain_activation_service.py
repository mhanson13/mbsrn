from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_action_execution_item_repository import SEOActionExecutionItemRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.action_chaining import NextActionDraft


class SEOActionChainDraftNotFoundError(ValueError):
    pass


class SEOActionChainActivationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ActivatedActionResult:
    draft: NextActionDraft


class ActionChainActivationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_action_chain_draft_repository: SEOActionChainDraftRepository,
        seo_action_execution_item_repository: SEOActionExecutionItemRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_action_chain_draft_repository = seo_action_chain_draft_repository
        self.seo_action_execution_item_repository = seo_action_execution_item_repository

    def activate_chained_action_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
        draft_id: str,
        actor_principal_id: str | None,
    ) -> ActivatedActionResult:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)

        draft_record = self.seo_action_chain_draft_repository.get_for_business_site_source_action_draft(
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
            draft_id=draft_id,
        )
        if draft_record is None:
            raise SEOActionChainDraftNotFoundError("Chained action draft not found")

        # Idempotent fast-path for previously activated drafts.
        if draft_record.activation_state == "activated" and draft_record.activated_action_id:
            return ActivatedActionResult(draft=self._draft_record_to_schema(draft_record))

        existing_action = self.seo_action_execution_item_repository.get_for_business_site_source_draft(
            business_id=business_id,
            site_id=site_id,
            source_draft_id=draft_record.id,
        )
        if existing_action is None:
            draft_payload = self._draft_record_to_schema(draft_record)
            try:
                existing_action = self.seo_action_execution_item_repository.create_from_chained_draft(
                    business_id=business_id,
                    site_id=site_id,
                    source_action_id=source_action_id,
                    source_draft_id=draft_record.id,
                    draft=draft_payload,
                    created_by_principal_id=actor_principal_id,
                )
            except IntegrityError:
                self.session.rollback()
                existing_action = self.seo_action_execution_item_repository.get_for_business_site_source_draft(
                    business_id=business_id,
                    site_id=site_id,
                    source_draft_id=draft_record.id,
                )
                if existing_action is None:
                    raise SEOActionChainActivationValidationError(
                        "Failed to activate chained action draft due to duplicate write conflict"
                    ) from None
                draft_record = self.seo_action_chain_draft_repository.get_for_business_site_source_action_draft(
                    business_id=business_id,
                    site_id=site_id,
                    source_action_id=source_action_id,
                    draft_id=draft_id,
                )
                if draft_record is None:
                    raise SEOActionChainDraftNotFoundError("Chained action draft not found") from None

        draft_record.activation_state = "activated"
        draft_record.activated_action_id = existing_action.id
        self.seo_action_chain_draft_repository.save(draft_record)
        self.session.commit()
        self.session.refresh(draft_record)
        return ActivatedActionResult(draft=self._draft_record_to_schema(draft_record))

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOActionChainDraftNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> None:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOActionChainDraftNotFoundError("SEO site not found")

    @staticmethod
    def _draft_record_to_schema(record) -> NextActionDraft:
        return NextActionDraft(
            id=record.id,
            action_type=record.action_type,
            title=record.title,
            description=record.description,
            source_action_id=record.source_action_id,
            priority=record.priority,
            activation_state=record.activation_state,
            activated_action_id=record.activated_action_id,
            automation_template_key=record.automation_template_key,
            automation_ready=bool(record.automation_ready),
            metadata=record.metadata_json or {},
        )


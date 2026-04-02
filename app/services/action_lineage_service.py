from __future__ import annotations

from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_action_execution_item_repository import SEOActionExecutionItemRepository
from app.schemas.action_chaining import (
    ActionLineageActivatedAction,
    ActionLineageCounts,
    ActionLineageDraft,
    ActionLineageResponse,
)


class ActionLineageService:
    def __init__(
        self,
        *,
        seo_action_chain_draft_repository: SEOActionChainDraftRepository,
        seo_action_execution_item_repository: SEOActionExecutionItemRepository,
    ) -> None:
        self.seo_action_chain_draft_repository = seo_action_chain_draft_repository
        self.seo_action_execution_item_repository = seo_action_execution_item_repository

    def get_action_lineage(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
    ) -> ActionLineageResponse:
        draft_records = self.seo_action_chain_draft_repository.list_for_business_site_source_action(
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
        )
        action_records = self.seo_action_execution_item_repository.list_for_business_site_source_action(
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
        )

        chained_drafts = [
            ActionLineageDraft(
                id=record.id,
                source_action_id=record.source_action_id,
                action_type=record.action_type,
                title=record.title,
                description=record.description,
                draft_state=record.state,
                activation_state=record.activation_state,
                activated_action_id=record.activated_action_id,
                automation_ready=bool(record.automation_ready),
                automation_template_key=record.automation_template_key,
                created_at=record.created_at,
            )
            for record in draft_records
        ]

        activated_actions = [
            ActionLineageActivatedAction(
                id=record.id,
                source_draft_id=record.source_draft_id,
                source_action_id=record.source_action_id,
                action_type=record.action_type,
                title=record.title,
                description=record.description,
                state=record.state,
                automation_ready=bool(record.automation_ready),
                automation_template_key=record.automation_template_key,
                created_at=record.created_at,
            )
            for record in action_records
        ]

        automation_ready_keys: set[str] = set()
        for draft in chained_drafts:
            if draft.automation_ready:
                automation_ready_keys.add(draft.id)
        for action in activated_actions:
            if action.automation_ready:
                automation_ready_keys.add(action.source_draft_id or action.id)

        return ActionLineageResponse(
            source_action_id=source_action_id,
            chained_drafts=chained_drafts,
            activated_actions=activated_actions,
            counts=ActionLineageCounts(
                chained_draft_count=len(chained_drafts),
                activated_action_count=len(activated_actions),
                automation_ready_count=len(automation_ready_keys),
            ),
        )


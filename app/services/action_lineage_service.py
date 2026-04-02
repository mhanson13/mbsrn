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
        lineage_map = self.list_action_lineage_for_source_actions(
            business_id=business_id,
            site_id=site_id,
            source_action_ids=[source_action_id],
        )
        return lineage_map[source_action_id]

    def list_action_lineage_for_source_actions(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_ids: list[str],
    ) -> dict[str, ActionLineageResponse]:
        normalized_ids = [source_action_id for source_action_id in source_action_ids if source_action_id]
        if not normalized_ids:
            return {}

        unique_ids = list(dict.fromkeys(normalized_ids))
        draft_records = self.seo_action_chain_draft_repository.list_for_business_site_source_action_ids(
            business_id=business_id,
            site_id=site_id,
            source_action_ids=unique_ids,
        )
        action_records = self.seo_action_execution_item_repository.list_for_business_site_source_action_ids(
            business_id=business_id,
            site_id=site_id,
            source_action_ids=unique_ids,
        )

        drafts_by_source_action_id: dict[str, list[ActionLineageDraft]] = {source_action_id: [] for source_action_id in unique_ids}
        for record in draft_records:
            drafts_by_source_action_id.setdefault(record.source_action_id, []).append(
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
            )

        activated_actions_by_source_action_id: dict[str, list[ActionLineageActivatedAction]] = {
            source_action_id: [] for source_action_id in unique_ids
        }
        for record in action_records:
            activated_actions_by_source_action_id.setdefault(record.source_action_id, []).append(
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
                    automation_binding_state=record.automation_binding_state,
                    bound_automation_id=record.bound_automation_id,
                    automation_bound_at=record.automation_bound_at,
                    created_at=record.created_at,
                )
            )

        lineage_map: dict[str, ActionLineageResponse] = {}
        for source_action_id in unique_ids:
            chained_drafts = drafts_by_source_action_id.get(source_action_id, [])
            activated_actions = activated_actions_by_source_action_id.get(source_action_id, [])
            automation_ready_keys: set[str] = set()
            for draft in chained_drafts:
                if draft.automation_ready:
                    automation_ready_keys.add(draft.id)
            for action in activated_actions:
                if action.automation_ready:
                    automation_ready_keys.add(action.source_draft_id or action.id)

            lineage_map[source_action_id] = ActionLineageResponse(
                source_action_id=source_action_id,
                chained_drafts=chained_drafts,
                activated_actions=activated_actions,
                counts=ActionLineageCounts(
                    chained_draft_count=len(chained_drafts),
                    activated_action_count=len(activated_actions),
                    automation_ready_count=len(automation_ready_keys),
                ),
            )
        return lineage_map

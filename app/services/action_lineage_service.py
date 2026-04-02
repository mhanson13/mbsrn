from __future__ import annotations

from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_action_execution_item_repository import SEOActionExecutionItemRepository
from app.repositories.seo_automation_repository import SEOAutomationRepository
from app.schemas.action_chaining import (
    ActionLineageActivatedAction,
    ActionLineageCounts,
    ActionLineageDraft,
    ActionLineageResponse,
)
from app.core.seo_automation_outcome_summary import build_automation_run_outcome_summary


class ActionLineageService:
    def __init__(
        self,
        *,
        seo_action_chain_draft_repository: SEOActionChainDraftRepository,
        seo_action_execution_item_repository: SEOActionExecutionItemRepository,
        seo_automation_repository: SEOAutomationRepository,
    ) -> None:
        self.seo_action_chain_draft_repository = seo_action_chain_draft_repository
        self.seo_action_execution_item_repository = seo_action_execution_item_repository
        self.seo_automation_repository = seo_automation_repository

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
        run_ids = list(
            dict.fromkeys(
                [
                    record.last_automation_run_id
                    for record in action_records
                    if record.last_automation_run_id
                ]
            )
        )
        run_records = self.seo_automation_repository.list_runs_for_business_site_ids(
            business_id=business_id,
            site_id=site_id,
            run_ids=run_ids,
        )
        run_by_id = {run.id: run for run in run_records}

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
            run_record = run_by_id.get(record.last_automation_run_id) if record.last_automation_run_id else None
            effective_execution_state = record.automation_execution_state
            run_status = None
            run_started_at = None
            run_completed_at = None
            run_error_summary = None
            run_outcome_summary = None
            if run_record is not None:
                run_status = (run_record.status or "").strip().lower() or None
                run_started_at = run_record.started_at
                run_completed_at = run_record.finished_at
                run_error_summary = (run_record.error_message or "").strip() or None
                run_outcome_summary = build_automation_run_outcome_summary(
                    run_status=run_record.status,
                    steps=run_record.steps_json or [],
                    run_error_message=run_record.error_message,
                )
                if run_status == "queued":
                    effective_execution_state = "requested"
                elif run_status == "running":
                    effective_execution_state = "running"
                elif run_status == "failed":
                    effective_execution_state = "failed"
                elif run_status in {"completed", "skipped"}:
                    effective_execution_state = "succeeded"
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
                    automation_execution_state=effective_execution_state,
                    automation_execution_requested_at=record.automation_execution_requested_at,
                    last_automation_run_id=record.last_automation_run_id,
                    automation_last_executed_at=record.automation_last_executed_at or run_completed_at,
                    automation_run_status=run_status,
                    automation_run_started_at=run_started_at,
                    automation_run_completed_at=run_completed_at,
                    automation_run_error_summary=run_error_summary,
                    automation_run_terminal_outcome=(
                        run_outcome_summary.get("terminal_outcome") if run_outcome_summary else None
                    ),
                    automation_run_summary_title=(
                        run_outcome_summary.get("summary_title") if run_outcome_summary else None
                    ),
                    automation_run_summary_text=(
                        run_outcome_summary.get("summary_text") if run_outcome_summary else None
                    ),
                    automation_run_steps_completed_count=(
                        run_outcome_summary.get("steps_completed_count") if run_outcome_summary else None
                    ),
                    automation_run_steps_skipped_count=(
                        run_outcome_summary.get("steps_skipped_count") if run_outcome_summary else None
                    ),
                    automation_run_steps_failed_count=(
                        run_outcome_summary.get("steps_failed_count") if run_outcome_summary else None
                    ),
                    automation_run_pages_analyzed_count=(
                        run_outcome_summary.get("pages_analyzed_count") if run_outcome_summary else None
                    ),
                    automation_run_issues_found_count=(
                        run_outcome_summary.get("issues_found_count") if run_outcome_summary else None
                    ),
                    automation_run_recommendations_generated_count=(
                        run_outcome_summary.get("recommendations_generated_count")
                        if run_outcome_summary
                        else None
                    ),
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

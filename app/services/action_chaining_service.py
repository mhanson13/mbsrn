from __future__ import annotations

from app.schemas.action_chaining import ActionExecutionItem, NextActionDraft


def generate_next_actions(action: ActionExecutionItem) -> list[NextActionDraft]:
    normalized_type = (action.action_type or "").strip().lower()
    normalized_state = (action.state or "").strip().lower()

    drafts: list[NextActionDraft] = []

    if normalized_type == "seo_fix" and normalized_state == "accepted":
        drafts.append(
            NextActionDraft(
                action_type="verify_fix",
                title="Verify SEO fix impact",
                description="Confirm the accepted SEO fix is live and functioning as expected.",
                source_action_id=action.action_id,
                priority="medium",
                activation_state="pending",
                automation_ready=False,
                automation_template_key=None,
                metadata={
                    "chaining_rule": "seo_fix_after_accept",
                    "source_state": normalized_state,
                },
            )
        )

    if normalized_type == "publish_content" and normalized_state == "completed":
        drafts.append(
            NextActionDraft(
                action_type="promote_content",
                title="Promote published content",
                description="Share and distribute the completed content to increase local visibility.",
                source_action_id=action.action_id,
                priority="medium",
                activation_state="pending",
                automation_ready=True,
                automation_template_key="content_promotion_followup",
                metadata={
                    "chaining_rule": "publish_content_after_complete",
                    "source_state": normalized_state,
                },
            )
        )

    if normalized_type == "optimize_page" and normalized_state == "completed":
        drafts.append(
            NextActionDraft(
                action_type="measure_performance",
                title="Measure optimization performance",
                description="Review ranking and engagement changes after optimization completed.",
                source_action_id=action.action_id,
                priority="high",
                activation_state="pending",
                automation_ready=True,
                automation_template_key="performance_check_followup",
                metadata={
                    "chaining_rule": "optimize_page_after_complete",
                    "source_state": normalized_state,
                },
            )
        )

    return drafts

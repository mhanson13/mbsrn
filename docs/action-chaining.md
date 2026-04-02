# Action Chaining

## Purpose
Action chaining generates deterministic follow-on actions after an operator-driven action reaches a qualifying state (accepted or completed).  
This layer is additive and non-breaking:

- no AI/provider calls
- no background jobs
- no workflow-engine redesign
- deterministic, hardcoded rules only

## Deterministic Rule System
Rule execution lives in `app/services/action_chaining_service.py`.

Input:
- `ActionExecutionItem` (`action_id`, `action_type`, `state`, metadata)

Output:
- `NextActionDraft[]`

Current rules:
- `seo_fix` + `accepted` -> `verify_fix`
- `publish_content` + `completed` -> `promote_content`
- `optimize_page` + `completed` -> `measure_performance`

Unknown action types or non-matching states return an empty list.

## Persistence Model
Generated follow-on actions are persisted in `seo_action_chain_drafts`.

Storage fields include:
- source action linkage (`source_action_id`)
- deterministic chained `action_type`
- title/description
- optional priority
- metadata json
- state (`pending` by default)
- timestamps

This persistence is idempotent per `(business_id, site_id, source_action_id, action_type)` to prevent duplicate drafts on repeated updates.

## Trigger Path
Trigger point:
- `SEORecommendationService.update_recommendation_workflow(...)`

After a successful recommendation transition:
- transition to `accepted` maps to chained state `accepted`
- transition to `resolved` maps to chained state `completed`
- deterministic chaining rules are evaluated
- generated drafts are persisted additively

Structured observability event:
- `event=action_chaining_generated`
- `source_action_id`
- `generated_count`
- `action_types`

## Chained Draft Lifecycle
Chained drafts now carry an explicit lifecycle:

- `pending`: generated and persisted, not yet promoted to a first-class action
- `activated`: promoted to a first-class action execution item

Persisted fields on each chained draft:
- `activation_state`
- `activated_action_id`
- `automation_ready`
- `automation_template_key`

## Unified Action Lineage Read Model

To avoid stitching state from multiple endpoints, the API now provides one canonical lineage read payload:

`GET /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/lineage`

Payload shape:

- `source_action_id`
- `chained_drafts[]`
- `activated_actions[]`
- `counts`
  - `chained_draft_count`
  - `activated_action_count`
  - `automation_ready_count`

This read model is hydration-only:
- no writes
- no provider calls
- no workflow side effects

UI surfaces should prefer lineage hydration for source-action views instead of inferring activation state from multiple independent calls.

## Canonical Lineage in Operator Read Paths

To reduce frontend stitching, canonical lineage is now also attached additively to recommendation/workspace read payloads as `action_lineage` where next-step context is operator-relevant.

This allows workspace and recommendation surfaces to render:
- pending next-step drafts
- activated draft linkage
- activated action state
- automation readiness hints

from one recommendation payload flow, while still supporting direct lineage endpoint reads when a source-action scoped lookup is needed.

## Activation
Activation is a deterministic, additive API transition:

`POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/next-actions/{draft_id}/activate`

Behavior:
- validates business/site/source-action scope
- promotes the target draft to one first-class action execution item
- sets draft `activation_state=activated`
- sets draft `activated_action_id` to the created action id
- returns the updated draft payload

### Idempotency guarantee
Activation is idempotent per draft:
- first activation creates one action execution item
- repeated activation returns the same `activated_action_id`
- no duplicate first-class actions are created for the same draft

## Automation Linkage Metadata
Automation linkage is metadata-only and deterministic.

Current rule outputs:
- `verify_fix`
  - `automation_ready=false`
  - `automation_template_key=null`
- `promote_content`
  - `automation_ready=true`
  - `automation_template_key="content_promotion_followup"`
- `measure_performance`
  - `automation_ready=true`
  - `automation_template_key="performance_check_followup"`

These fields are hints for future automation orchestration and do **not** execute automation.

## Current Limitation
Activation does not schedule or execute automation.
It only promotes chained drafts into first-class action execution items while preserving deterministic linkage metadata.

## Explicit Automation Binding
Activated actions now support explicit, persisted automation binding.

Binding route:

`POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/execution-items/{execution_item_id}/bind-automation`

Request:
- `automation_id`

Persisted activated-action fields:
- `automation_binding_state` (`unbound` | `bound`)
- `bound_automation_id`
- `automation_bound_at`

Behavior:
- binding is explicit and operator-driven
- rebinding to the same automation is idempotent success
- attempting to bind to a different automation after bound returns conflict
- binding does not execute or schedule automation

Canonical lineage now includes this metadata on activated actions so UI can render automation-ready vs automation-bound without inferring state.

## Manual Execution Gating for Bound Actions

Bound, activated actions can now request automation execution explicitly through an operator-initiated bridge:

`POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/execution-items/{execution_item_id}/run-automation`

Execution is gated by deterministic checks:
- action execution item exists in business/site scope
- source draft is activated and linked correctly
- action is `automation_ready=true`
- action is `automation_binding_state=bound`
- bound automation record exists in scope

Persisted execution fields on activated actions:
- `automation_execution_state` (`not_requested`, `requested`, `running`, `succeeded`, `failed`)
- `automation_execution_requested_at`
- `automation_execution_requested_by`
- `last_automation_run_id`
- `automation_last_executed_at`

Idempotency/duplicate-click behavior:
- if a matching active run already exists for the bound automation, request reuses it
- repeated clicks in in-flight states return current execution metadata without creating duplicate runs

Important boundary:
- this route **requests** execution only
- it does not introduce autonomous scheduling
- it does not auto-run on draft activation or automation bind

Canonical lineage now exposes execution metadata on `activated_actions[]` so workspace/recommendation surfaces can render:
- bound but not requested
- execution requested/running
- last run succeeded/failed

## Execution Status Overlay in Canonical Lineage

Canonical lineage now also hydrates live automation run overlay details for activated actions when `last_automation_run_id` is present:

- `automation_run_status`
- `automation_run_started_at`
- `automation_run_completed_at`
- `automation_run_error_summary`

Read-path behavior:
- read-only hydration (no writes)
- deterministic mapping from run status to execution lifecycle display
- no provider calls and no execution side effects

UI implication:
- operators can immediately see whether "Run automation" moved to requested/running
- terminal outcomes (completed/failed) are surfaced with concise timestamps/error summary
- lightweight in-flight refresh can poll lineage while requested/running, then stop at terminal state

## Example Flow
`recommendation (seo_fix)` -> status patched to `accepted` -> chained draft `verify_fix` persisted as `pending` -> operator activates draft -> first-class action execution item created -> draft marked `activated`.

## Extending Rules Safely
To add new chaining behavior:
1. Add a new deterministic branch in `generate_next_actions`.
2. Keep conditions explicit (`action_type` + `state`).
3. Add unit tests for:
   - matching rule path
   - non-matching safety path
4. Keep outputs deterministic and provider-free.

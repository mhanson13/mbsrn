# Automation Feature Notes

## What "Run automation" Actually Executes

`Run automation` is an internal SEO workflow trigger. It does **not** publish or modify external websites.

Current manual execution path:

1. `POST /.../actions/execution-items/{id}/run-automation` requests execution for a bound activated action.
2. Backend calls `SEOAutomationService.trigger_manual_run(...)`.
3. The service creates an internal `seo_automation_runs` record and executes configured steps.

Current step behavior:

- `audit_run`: crawls the configured site `base_url` over public HTTP(S) and stores audit artifacts internally.
- `audit_summary`: generates/stores an internal summary record.
- `competitor_snapshot_run`: creates a competitor snapshot run record (queued metadata record).
- `comparison_run`: runs only when a completed snapshot output is available; otherwise skipped by dependency guard.
- `competitor_summary`: summarizes completed comparison output when available.
- `recommendation_run`: generates/stores internal recommendation records.
- `recommendation_narrative`: generates/stores a narrative artifact from recommendation output.

Boundary clarification:

- No CMS publisher bridge is executed in this path.
- No GoDaddy/WordPress/Webflow/Squarespace site-content update path is executed here.
- Automation currently orchestrates internal analysis/state and generated artifacts; external site mutation is out of scope.

## Action Control Layer Integration

Automation UI now participates in the shared frontend Action Control Layer so operators can quickly distinguish:

- in-progress automation (trackable, not yet actionable)
- output-ready automation (reviewable now)
- blocked/failed runs (explicit reason)
- completed informational runs

This is read-model/presentation behavior only.

### Where controls are derived

- `frontend/operator-ui/lib/transforms/actionExecution.ts`

### Where controls are rendered

- `frontend/operator-ui/app/automation/page.tsx`
- `frontend/operator-ui/app/sites/[site_id]/page.tsx` (workspace summary automation block)

### Lifecycle and follow-up cues

Controls are generated from existing lifecycle + linkage fields:

- run status (`queued`, `running`, `completed`, `failed`)
- step-level linkage (`steps_json[].linked_output_id`)
- recommendation output readiness

Operator-facing intent:

- **Waiting on automation**: explicit disabled reason and status guidance
- **Output ready**: direct review action for linked recommendation output
- **Failed/blocked**: explicit blocked reason instead of ambiguous no-op states

### Local test strategy

Mock-only tests validate behavior without runtime automation dependency:

- `frontend/operator-ui/app/automation/page.test.tsx`
- `frontend/operator-ui/app/sites/site-workspace-page.test.tsx`
- `frontend/operator-ui/lib/transforms/actionExecution.test.ts`

## Automation Output Review

Automation output-ready states now render a dedicated Output Review surface so operators can capture an explicit decision instead of inferring next steps.

### Decision actions

- Accept
- Reject
- Defer

### Decision-driven state transitions

- Accept -> `completed_acted`
- Reject -> `blocked_unavailable`
- Defer -> `recommendation_only_review`

Outcome and next-step text are updated deterministically from the captured decision.

### Where Output Review is rendered

- Automation page latest-run summary and quick-scan cards: `frontend/operator-ui/app/automation/page.tsx`
- Site workspace automation summary: `frontend/operator-ui/app/sites/[site_id]/page.tsx`

### Persistence model

- Decisions are always reflected locally first for responsiveness and testability.
- No automation execution/orchestration behavior is changed.
- Recommendation-linked accepted/rejected decisions may reuse existing recommendation status mutation paths on recommendation surfaces; automation page decision capture itself is read-model/UI scoped.

### Operator loop closure

This layer closes the operator loop by making output-ready automation states explicitly reviewable and decisionable:

- what happened
- what state the item is currently in
- what decision was captured
- what follow-up should happen next

## Chained Draft Automation Linkage Metadata

Deterministic chained drafts now carry explicit automation linkage metadata used for future automation integration planning:

- `automation_ready` (boolean suitability hint)
- `automation_template_key` (internal deterministic template key)

Current deterministic mapping examples:

- `verify_fix`: `automation_ready=false`, `automation_template_key=null`
- `promote_content`: `automation_ready=true`, `automation_template_key="content_promotion_followup"`
- `measure_performance`: `automation_ready=true`, `automation_template_key="performance_check_followup"`

This metadata is informational for activation/read models only and does not execute or schedule automation.

## Canonical Action Lineage Visibility

Automation-adjacent UI can now consume canonical action lineage from:

- `GET /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/lineage`

This endpoint surfaces:
- chained drafts and activation state
- activated first-class actions
- automation readiness visibility in a single payload

Recommendation/workspace reads also now expose additive canonical lineage per recommendation item (`action_lineage`), so automation-adjacent action status can be rendered without multi-endpoint client inference.

It remains read-only and metadata-only:
- no automation execution
- no scheduling side effects

## Explicit Action-to-Automation Binding

Activated action execution items now support explicit binding to an existing automation record.

Binding endpoint:

`POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/execution-items/{execution_item_id}/bind-automation`

Request:
- `automation_id`

Persisted binding fields on activated actions:
- `automation_binding_state` (`unbound` | `bound`)
- `bound_automation_id`
- `automation_bound_at`

Operator-facing semantics:
- **Automation-ready** means a deterministic template hint exists and binding is allowed.
- **Bound** means the action has an explicit persisted automation linkage.
- Binding is idempotent for the same automation id and conflict-protected for different automation ids.
- Binding does **not** execute or schedule automation.

## Manual Execution Request from Bound Activated Actions

Bound activated actions can now explicitly request automation execution through a guarded API bridge.

Execution request route:

`POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/execution-items/{execution_item_id}/run-automation`

Execution metadata persisted on activated action execution items:
- `automation_execution_state`
- `automation_execution_requested_at`
- `automation_execution_requested_by`
- `last_automation_run_id`
- `automation_last_executed_at`

Lifecycle interpretation:
- `not_requested`: bound but no manual run request yet
- `requested`: run request accepted/queued
- `running`: active run in progress
- `succeeded`: most recent run finished successfully
- `failed`: most recent run finished with failure

Idempotency and duplicate-click protections:
- if an active run already exists for the bound automation, request reuses current run state
- repeated clicks do not create duplicate concurrent runs for the same bound action

Boundary reminder:
- this is operator-initiated only
- no scheduler/background behavior introduced
- no automatic execution on activation or binding

## Execution Observability and Operator Feedback

After "Run automation" is clicked, operator-facing surfaces now show execution lifecycle feedback instead of an idle state.

Lifecycle labels shown in UI:
- `Execution requested`
- `Running`
- `Completed`
- `Failed`

Lineage-backed run overlay fields now surfaced on activated actions:
- `automation_run_status`
- `automation_run_started_at`
- `automation_run_completed_at`
- `automation_run_error_summary`

Operator-visible feedback behavior:
- displays last run id when available
- shows run started/completed timestamps
- shows a short failure signal when the run reports an error message
- keeps status refresh lightweight while in-flight (requested/running) and stops when terminal (succeeded/failed)

Scope reminder:
- observability only
- no changes to execution engine behavior
- no scheduling/autonomous execution added

## Canonical Run Outcome Summary and Step Signals

Automation run reads now expose a deterministic terminal summary and normalized step reasons for operator review.

Run-level fields:
- `outcome_summary.summary_title`
- `outcome_summary.summary_text`
- `outcome_summary.terminal_outcome` (`completed`, `completed_with_skips`, `failed`, `partial`)
- `outcome_summary.steps_completed_count`
- `outcome_summary.steps_skipped_count`
- `outcome_summary.steps_failed_count`
- optional metrics:
  - `pages_analyzed_count`
  - `issues_found_count`
  - `recommendations_generated_count`

Step-level fields:
- `step.status` (`pending`, `running`, `completed`, `skipped`, `failed`)
- `step.reason_summary` (concise skip/failure reason for operators)
- optional metrics where available on completed steps

Known dependency-driven skip clarity:
- competitor comparison can be skipped when competitor snapshot output is queued/not completed
- downstream competitor summary can be skipped when comparison output is not completed
- these conditions are surfaced explicitly in `reason_summary` and reflected in run terminal summary text

Operator-facing guidance:
- completed: review generated recommendation artifacts
- completed with skips: review skipped reasons and rerun once prerequisites are available
- failed: review failed step reason before rerun

Truth boundary:
- this workflow runs SEO analysis/artifact generation
- it does **not** publish changes to live customer websites

## Recommendation Content Targets and Automation Readiness

Recommendation read models can now carry deterministic **content target** metadata (for example: `meta_title`, `heading_h1`, `internal_links`).

Automation notes:

- content targets are evidence-derived and additive
- they are safe to consume as structured hints in operator workflows
- they do not trigger execution by themselves
- they do not change the current non-publishing automation boundary

Recommendation payloads may also include deterministic `action_plan.action_steps` built from those grounded targets.

- action plan steps are operator implementation guidance only
- they are safe metadata inputs for future automation binding
- they do not auto-run or publish changes

## Audit Runs Table (Operator View)

The Audit Runs operator table is intentionally compact and outcome-focused.

Visible columns:
- `Status`
- `Created`
- `Duration`
- `Result`

Design intent:
- remove low-value internal identifiers from the primary scan surface
- emphasize operational outcome and timing

Duration behavior:
- completed run: `completed_at - started_at`
- running run: elapsed since `started_at`
- missing/invalid timestamps: `—`

## Dashboard (Operator Overview)

The dashboard uses an action-first layout:

- top summary strip
- **Do this now** panel
- recent activity panel
- global header navigation (no separate quick-navigation card)

Intent:
- prioritize immediate operator decisions over passive status browsing
- keep deterministic, compact signals visible without requiring deep navigation

## Automation Completeness

Automation surfaces now show a compact completeness signal derived from run outcome and step dependency context:

- `Complete`
- `Complete (limited)`
- `Partial`

Dependency-aware behavior:
- if competitor-dependent steps are skipped/failed due unmet snapshot/comparison prerequisites, runs are labeled as limited/partial
- operator hint is shown: `Competitor data not available at run time; insights may be limited`

This signal is read-model only and does not alter execution behavior.

## Diagnostic Detail Model

Operator diagnostics are intentionally layered:

- summary: terminal outcome + concise run summary
- drill-down: per-step compact details (status, reason summary, key metrics)
- logs: not exposed in operator UI

Per-step drill-down is collapsed by default (`View details`) and includes only:
- `reason_summary` (or safe fallback reason)
- `pages analyzed`
- `issues found`
- `recommendations generated`

Raw stack traces and internal logs are not rendered.

## Non-Publishing Behavior

Automation pages and output-review surfaces now include a persistent boundary reminder:

`This automation analyzes your site and generates recommendations. It does not make changes to your website.`

This reinforces current product behavior:
- analysis + artifact generation only
- no live-site publishing or CMS mutation

## Workflow Site Selector Placement

Workflow pages now use the shared global-header site selector pattern, including Automation.

Operator intent:
- site context is set once in header chrome
- duplicate lower-page selectors are removed
- labels such as `Selected Site` are no longer repeated in section bodies
- changing the header selector updates route/query context and reloads automation content for the selected site

This keeps action surfaces focused while preserving the same business/site-scoped data flow.

### Workspace authority guardrail

- active selector context is constrained to sites inside the authenticated principal business scope
- persisted or requested out-of-scope site ids are reset to an authorized site with inline context warning
- automation pages do not keep a cosmetic cross-business context that backend authorization will reject

Current limitation:
- cross-business workspace switching is not supported end-to-end in automation flows today

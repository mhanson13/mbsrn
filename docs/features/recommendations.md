# Recommendations Feature Notes

## Action Control Layer (Frontend)

The operator UI now derives a compact, deterministic **Action Control Layer** from existing recommendation and automation read-model data.

It is presentation-only and does not change recommendation generation, apply logic, trust semantics, or backend workflow behavior.

### Control model

Frontend controls are derived in:

- `frontend/operator-ui/lib/transforms/actionExecution.ts`

Control types:

- `review_recommendation`
- `run_automation`
- `view_automation_status`
- `review_output`
- `mark_completed`
- `blocked`

### State-to-control mapping

Derived from existing action-state cues:

- `recommendation_only_review`: review recommendation (primary), run automation (secondary when available)
- `waiting_on_automation`: view automation status (disabled, explicit reason)
- `automation_output_ready`: review output (primary), mark completed (secondary)
- `blocked_unavailable`: blocked control with explicit reason
- `completed_acted`: completed muted control, optional review output
- `informational_only`: non-actionable informational/blocked cue

### Operator-visible behavior

Recommendation-facing surfaces now consistently show:

- what happened
- current state
- what to do next
- a compact control set tied to that state

When output linkage exists (`linked_output_id`), `review_output` is surfaced as the primary follow-up path.

### Local test strategy

Tests use mocked payloads only (no provider/runtime dependency):

- `frontend/operator-ui/lib/transforms/actionExecution.test.ts`
- `frontend/operator-ui/app/recommendations/page.test.tsx`
- `frontend/operator-ui/app/recommendations/runs/[run_id]/page.test.tsx`
- `frontend/operator-ui/app/sites/site-workspace-page.test.tsx`

## Automation Output Review + Decision Capture

Recommendation-facing surfaces now support explicit output review decisions for automation-linked items:

- Accept
- Reject
- Defer

This is additive frontend behavior on top of existing recommendation/automation read models.

### Where this appears

- Recommendation queue: `frontend/operator-ui/app/recommendations/page.tsx`
- Recommendation run detail: `frontend/operator-ui/app/recommendations/runs/[run_id]/page.tsx`
- Site workspace recommendation callout: `frontend/operator-ui/app/sites/[site_id]/page.tsx`

### Operator-facing behavior

- `automation_output_ready` shows Output Review as the primary decision surface.
- Accept transitions item presentation to `completed_acted`.
- Reject transitions item presentation to `blocked_unavailable`.
- Defer transitions item presentation to `recommendation_only_review`.
- Outcome + Next Step copy updates deterministically after each decision.

### Persistence behavior

- Local decision state updates immediately in the UI.
- Accepted/rejected recommendation decisions reuse existing `updateRecommendationStatus` mutation where available.
- Deferred remains local presentation state (no new backend workflow endpoint added).
- On persistence failure, UI remains non-destructive and displays explicit error guidance.

### Trust boundary

- Decision capture does not alter recommendation trust semantics.
- Informational trust tiers remain review-first and are not implicitly marked as complete.

## Bulk Action Burst Protection

The recommendations queue now applies a bounded client-side mutation queue for bulk status updates instead of launching one request per selected item in an unbounded parallel burst.

### Processing model

- Bulk mutations are processed with a fixed in-flight concurrency cap (`4`).
- Queue execution is handled by shared utility: `frontend/operator-ui/lib/bulkActionQueue.ts`.
- The queue remains interactive and shows live progress while updates run:
  - total selected
  - processed
  - succeeded
  - failed
- Partial failures are preserved and surfaced explicitly; failed rows are re-selected for follow-up.

### Refresh behavior

- Per-item optimistic state updates remain in place for immediate operator feedback.
- Full list refresh is controlled (single post-batch refresh when at least one update succeeds).
- The UI no longer triggers full data refresh per individual mutation.

### Why this exists

- Production incidents showed large bulk actions (for example, 50+ recommendation updates) could overwhelm API/database connection pools when requests were fired in parallel.
- The bounded queue reduces pool pressure while preserving current recommendation workflow semantics.

## Chained Next-Action Activation

Recommendation workflow chaining now exposes deterministic next-action drafts with activation state and linkage metadata.

### Draft lifecycle

- `pending`: generated from deterministic chain rules but not yet promoted
- `activated`: promoted to a first-class action execution item

### Activation API

- `POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/next-actions/{draft_id}/activate`

### Canonical lineage API

- `GET /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/lineage`

This response provides one read model for:
- chained drafts
- activated actions
- automation readiness counts

Recommendation/workspace surfaces can use this endpoint to hydrate action progression without stitching multiple endpoints.

Response/read payloads for chained drafts now include:

- `activation_state`
- `activated_action_id`
- `automation_ready`
- `automation_template_key`

### Canonical lineage in main recommendation/workspace reads

Recommendation-facing read payloads now carry canonical lineage directly on each recommendation item via additive `action_lineage` data.

This is now hydrated in:

- recommendation queue/list reads
- recommendation run report recommendations
- workspace summary recommendation lists
- individual recommendation reads and status-patch responses

Operator UI surfaces should consume this canonical lineage first for next-step truth instead of stitching activation state from multiple ad hoc sources.

### Idempotency behavior

Activating the same draft repeatedly returns the same `activated_action_id` and does not create duplicate actions.

## Automation Binding Visibility for Activated Next Steps

Recommendation lineage surfaces now distinguish:
- automation-ready (activation metadata says the next step can bind)
- automation-bound (explicit persisted binding to an automation record)

Activated lineage rows include additive fields:
- `automation_binding_state`
- `bound_automation_id`
- `automation_bound_at`

Binding is explicit and operator-driven via:

`POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/execution-items/{execution_item_id}/bind-automation`

Operator behavior:
- unbound + automation-ready -> show bind control
- bound -> show bound automation reference
- no implied execution (binding does not run automation)

## Manual "Run Automation" Execution Gating

Recommendation surfaces now expose a guarded manual execution bridge for eligible activated actions.

Eligibility shown in UI:
- activated next-step action exists
- `automation_ready=true`
- `automation_binding_state=bound`
- execution state is not currently in-flight

Operator control:
- **Run automation**

Execution lifecycle cues now rendered from canonical lineage:
- `not_requested`
- `requested`
- `running`
- `succeeded`
- `failed`

Operator-facing behavior:
- bound + not requested -> run control shown
- requested/running -> in-progress cue shown, run control suppressed
- succeeded/failed -> last run outcome cue shown with run reference when available

Backend bridge:
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/execution-items/{execution_item_id}/run-automation`

Safety boundary:
- manual operator request only
- no automatic execution on activation/bind
- no recommendation generation behavior change

## Automation Outcome Context in Recommendation Surfaces

Recommendation/workspace output-review surfaces now consume canonical lineage run outcome overlays to keep follow-up decisions clear:

- run terminal outcome (`completed`, `completed_with_skips`, `failed`, `partial`)
- concise run summary title/text
- completed/skipped/failed step counts
- optional SEO metrics when available

Operator interpretation:
- **completed**: review generated recommendation artifacts
- **completed with skips**: review skipped-step reasons and rerun after prerequisites are available
- **failed**: inspect failed-step reason before rerun

Copy/intent boundary:
- "Run SEO automation" triggers SEO analysis/artifact generation
- it does not imply live-site CMS publishing or direct website modification

## Recommendation Badge Behavior

Recommendation badges are compact operator signals derived from normalized state/count data.

UI rules:
- badges render as nowrap pills (single-line text by default)
- chip groups are overflow-safe and wrap as groups without distorting individual badges
- large count displays may be capped (for example `99+`) when a capped representation is configured

Purpose:
- provide a fast scan signal for triage and action ordering
- do not replace detailed metric review in expanded/detail surfaces

## Recommendation Table Layout

The recommendations queue table now prioritizes action scanning over record identity metadata.

Changes:
- removed row-level `Site` and `Business` columns
- moved `Priority` immediately after row selection (checkbox) for faster triage
- expanded `Summary` to use reclaimed horizontal space for clearer operator context

Rationale:
- site/business context is already visible in the global workspace header
- queue scanning should foreground execution signals (`priority`, `summary`, `status`, `decisiveness`) before IDs

## Workspace Context Authority

Recommendation surfaces now follow the same authority-bounded workspace context model as the global header selector:

- only sites inside the authenticated principal business scope are selectable as active workspace context
- persisted out-of-scope site ids are reset to an authorized site before recommendation data loads
- route/query `site_id` values outside authorized scope are normalized to authorized context with inline warning

Current limitation:
- cross-business site switching is not supported end-to-end in recommendation workflows today
- UI intentionally avoids showing an active site/business context that backend authorization will reject

## Final UI Ergonomics

### UI Stability and Error Signaling

Recent recommendations/workspace polish adds four operator-facing ergonomics protections:

- **Inline-first bulk error signaling**
  - bulk action failures render inline within recommendation controls, keeping feedback in reading flow
  - inline errors take precedence over global toast surfaces for the same bulk event to avoid duplicate/conflicting signals
  - fixed global toasts remain available for non-inline/system notifications
- **Hydration-safe operator header shell**
  - auth/session context now hydrates after mount so server and first client render keep the same header/nav structure
  - this prevents recommendations/dashboard hydration mismatch overlays and related visual flash in local dev
- **Tighter header context grouping**
  - site selector context IDs (site + business) are grouped inline with the selector row
  - header vertical spacing is reduced to keep the recommendations surface visible sooner
- **Summary-first table balance**
  - title width is constrained
  - summary width is expanded so the actionable rationale is easier to scan at common desktop widths
- **Theme-safe presentation**
  - recommendation surfaces inherit global light/dark theme tokens without changing data or workflows

### Theme Toggle

- A global `Light / Dark` toggle is available in the top navigation shell.
- Preference is persisted locally in browser storage (`operator-ui-theme`).
- Theme choice is client-side presentation only and does not alter recommendation logic, API behavior, or execution flow.

## Sites Workspace Recommendation Surface Cleanup

The site workspace recommendation table no longer renders the legacy metadata header row:

- `Category`
- `Severity`
- `Priority`
- `Status`
- `Why this was suggested`

Recommendation content is still preserved in the card/row body and support rail.

## Content to Update Targeting

Recommendations now include additive structured content targeting metadata so operators can see *what type of content to change*, not only what issue exists.

Read-model fields:

- `recommendation_target_content_types`
  - each entry includes:
    - `type_key`
    - `label`
    - `source_type` (`deterministic_rule`, `audit_signal`, `evidence_mapping`)
    - optional `targeting_strength`
- `recommendation_target_content_summary`

Deterministic derivation order:

1. explicit grounded evidence (`evidence_json.target_content_types`)
2. explicit finding/count signals from audit/comparison evidence
3. deterministic keyword/rule mapping fallback
4. safe empty result when no grounded target is available

UI behavior:

- recommendation surfaces now show **Content to update** when available
- labels are operator-readable (for example: *Main heading*, *Intro paragraph*, *Meta title*)
- internal keys are not rendered directly
- when targets are unavailable, recommendation behavior stays generic and unchanged

Operator intent:

- pair **Pages to update** with **Content to update** so operators can quickly decide:
  - where to make the change
  - what part of content to edit

Additional cleanup:
- recommendation runs/workspace detail now renders as card/list surfaces only
- legacy table/grid shells and metadata column scaffolding are removed from the site workspace recommendation body
- recommendation queue items on the site workspace use compact cards rather than mixed card+table composition
- global header site switching is now canonical, so workspace recommendation content follows the selected site context without manual page refresh

### AI Prompt debug panel behavior

`View AI prompt` is now explicitly user-driven:

- collapsed by default
- does not auto-expand during recommendation generation
- does not auto-expand on polling refresh
- does not auto-expand when a new run is created

## Action Plans

Recommendations now include a deterministic `action_plan` payload that converts grounded recommendation metadata into operator-executable steps.

Purpose:
- make "what to do next" concrete without adding new AI calls
- keep steps machine-readable for future automation targeting
- preserve safe fallback behavior when grounded targets are unavailable

Structure:
- `action_plan.action_steps[]`
  - `step_number`
  - `title`
  - `instruction`
  - `target_type` (`page` or `content`)
  - `target_identifier`
  - `field`
  - `before_example`
  - `after_example`
  - `confidence`

Example:

```json
{
  "action_plan": {
    "action_steps": [
      {
        "step_number": 1,
        "title": "Rewrite meta description",
        "instruction": "On Service pages, rewrite the meta description with service, location, and a direct call to action.",
        "target_type": "page",
        "target_identifier": "Service pages",
        "field": "meta_description",
        "before_example": null,
        "after_example": "Plumbing repair in your area. Call today for a quote.",
        "confidence": 0.92
      }
    ]
  }
}
```

Boundary note:
- action plans prepare operators for implementation and future automation targeting
- this layer does **not** execute site changes

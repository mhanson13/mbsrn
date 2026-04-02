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

### Idempotency behavior

Activating the same draft repeatedly returns the same `activated_action_id` and does not create duplicate actions.

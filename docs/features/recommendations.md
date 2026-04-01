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

# Automation Feature Notes

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

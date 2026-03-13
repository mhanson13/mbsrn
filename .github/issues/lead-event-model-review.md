## Summary

Review the `lead_events` model and usage patterns to confirm it remains a clean audit trail as the system grows.

## Scope

Files to inspect:

- `app/models/lead_event.py`
- `app/repositories/lead_repository.py`
- `app/services/notifications.py`
- `app/services/email_intake.py`
- `app/services/timeline.py`

## Goals

- Confirm current event types are sufficient and coherent.
- Ensure event payloads are structured consistently.
- Identify whether any event names or payload conventions should be standardized.
- Evaluate whether `lead_events` is still enough for delivery tracking or whether a future `notifications` table may be needed.

## Tasks

- [ ] Review event type naming and semantics.
- [ ] Review payload consistency across services.
- [ ] Review timeline ordering and event readability.
- [ ] Document future scaling limits if event volume grows.

## Acceptance Criteria

- Lead events remain a trustworthy audit trail.
- Event semantics are consistent enough for pilot operations.
- Future migration needs, if any, are documented.

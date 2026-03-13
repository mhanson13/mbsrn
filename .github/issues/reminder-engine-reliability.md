## Summary

Harden the reminder engine so stale lead reminders are reliable, repeat-safe, and operationally useful.

## Scope

Files to inspect:

- `app/services/reminder_engine.py`
- `app/jobs/lead_reminders.py`
- `app/services/notifications.py`
- `app/tests/test_reminder_engine.py`

## Goals

- Confirm stale lead detection is correct.
- Prevent duplicate reminder sends for the same threshold.
- Ensure reminder dispatch uses the same notification path as lead alerts.
- Ensure reminder failures are visible in lead events.

## Tasks

- [ ] Review threshold handling (15m, 2h, etc.).
- [ ] Review reminder idempotency behavior.
- [ ] Confirm event recording is complete and ordered correctly.
- [ ] Tighten tests around duplicate suppression and failure paths.

## Acceptance Criteria

- Reminder runs are safe to execute repeatedly.
- Duplicate threshold notifications are suppressed.
- Reminder outcomes are visible in lead timeline/events.

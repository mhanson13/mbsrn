# Notification Dispatch Audit

## Summary

Review and harden the notification dispatch layer so contractor alerts, customer acknowledgments, and reminder notifications behave predictably in pilot environments.

## Scope

Files to inspect:

- `app/services/notifications.py`
- `app/integrations/sms_provider.py`
- `app/integrations/email_provider.py`
- `app/services/reminder_engine.py`
- `app/tests/test_notification_dispatch.py`
- `app/tests/test_reminder_engine.py`

## Goals

- Verify contractor alerts and customer acknowledgments use the correct channels.
- Confirm reminder notifications reuse the same dispatch layer.
- Ensure event recording is consistent across success, fallback, skip, and failure paths.
- Validate idempotency behavior for duplicate sends.
- Confirm no provider failure can break lead persistence.

## Tasks

- [ ] Review `NotificationDispatchService` send paths.
- [ ] Verify channel priority and fallback order.
- [ ] Confirm idempotency suppression is safe and test-covered.
- [ ] Verify delivery events are complete and consistent.
- [ ] Tighten tests if weak spots are found.

## Acceptance Criteria

- Notification dispatch behavior is deterministic and test-covered.
- Lead events clearly show requested, sent, failed, fallback, and skipped cases.
- Reminder notifications use the same dispatch layer without duplicate logic.
- Lead creation/update remains independent from provider delivery success.

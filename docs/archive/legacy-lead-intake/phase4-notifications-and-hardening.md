# Phase 4: Notifications and Hardening

## Overview
Phase 4 makes the Lead Intake Engine pilot-ready by introducing real notification adapter paths, delivery outcome tracking, business-level notification controls, and failure-safe dispatch behavior.

## Goals
- Deliver real contractor alerts and customer acknowledgments when configured.
- Keep lead persistence independent from notification delivery success.
- Record delivery success/failure/fallback outcomes in `lead_events`.
- Let each business control notification behavior with explicit settings.

## Provider Strategy
Notification providers are selected by environment configuration:

- SMS:
  - `mock` -> `MockSMSProvider`
  - `dev` -> `DevSMSProvider`
  - `twilio` -> `TwilioSMSProvider` (falls back to `DevSMSProvider` if required credentials are missing)
- Email:
  - `mock` -> `MockEmailProvider`
  - `dev` -> `DevEmailProvider`
  - `smtp` -> `SMTPEmailProvider` (falls back to `DevEmailProvider` if required SMTP settings are missing)

This keeps local development simple while enabling real delivery in pilot environments.

## Dispatch Layer
`NotificationDispatchService` is the orchestration layer used by:
- email intake flow
- reminder engine

Responsibilities:
- determine candidate channels from business settings
- validate recipient targets
- attempt primary channel and fallback
- catch provider exceptions
- enforce optional idempotency keys to suppress duplicate sends
- write delivery events to `lead_events`

## Business Notification Settings
Business records include:
- `notification_phone`
- `notification_email`
- `sms_enabled`
- `email_enabled`
- `customer_auto_ack_enabled`
- `contractor_alerts_enabled`
- `timezone`

API:
- `GET /api/businesses/{id}`
- `PATCH /api/businesses/{id}/settings`

## Delivery Tracking Events
Delivery outcomes are stored in `lead_events`:
- `notification_dispatch_requested`
- `notification_dispatch_sent`
- `notification_dispatch_failed`
- `notification_fallback_attempted`
- `notification_fallback_sent`
- `notification_dispatch_skipped` (idempotency suppression)

Existing intake/reminder trigger events are preserved for backward compatibility.

## Hardening Rules
- Lead creation/update commits continue even when dispatch fails.
- Invalid or missing targets do not raise API errors; failures are recorded in events.
- Provider exceptions are caught and tracked.
- Idempotency keys can suppress duplicate sends during retries.
- Reminder notifications use the same dispatch layer and tracking events.

## Operational Notes
- For local usage, keep `SMS_PROVIDER=mock` and `EMAIL_PROVIDER=mock` or `dev`.
- For pilot usage, set `SMS_PROVIDER=twilio` and/or `EMAIL_PROVIDER=smtp` with credentials.
- Use lead timeline endpoint to inspect delivery behavior per lead.

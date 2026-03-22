# Lead Intake Flow (Phase 2)

## Overview
Phase 2 adds automatic lead intake from GoDaddy contact-form notification emails.  
The system receives email payloads, parses lead details with rules, deduplicates recent leads, persists the lead, records lead events, and triggers mocked notifications.

## Assumptions
- GoDaddy form submissions arrive as email notifications.
- No deep GoDaddy API integration is required for MVP.
- App remains a single FastAPI monolith with SQLAlchemy models.
- Parsing is rules-based (labels + regex), not AI-based.
- SMS/email providers are mocked behind interfaces.
- One developer should be able to maintain this flow.

## Email-to-Lead Flow
1. Inbox adapter (future) posts payload to `POST /api/intake/email`.
2. `EmailIntakeService` records an `email_received` event.
3. `LeadParserService` extracts and normalizes fields:
`customer_name`, `phone`, `email`, `service_type`, `city`, `message`.
4. `LeadDeduplicationService` checks recent leads:
same phone within 7 days, same email within 7 days, same name+phone same day.
5. If duplicate:
existing lead is enriched (backfill missing fields, append new message) and `duplicate_detected` is recorded.
6. If not duplicate:
new lead is created with source `godaddy_email` and `lead_created` is recorded.
7. Parse outcome event is recorded:
`lead_parsed` or `parsing_failed`.
8. `NotificationService` triggers:
customer acknowledgment and contractor notification (mocked).
9. Notification events are recorded:
`customer_ack_triggered` and `contractor_notification_triggered`.

## Failure Handling
- If business does not exist: request returns `404`.
- If parser cannot identify a customer identifier (name, phone, or email):
`parse_status=failed`, `parsing_failed` event is recorded, and a lead is still created for manual review.
- Missing fields are allowed; parser returns partial data when possible.
- Notification channels can be missing; notification events still record attempted/skipped state.

## Dedupe Behavior
- Dedupe lookback window: last 7 days.
- Rules:
1. `same_name_phone_same_day` (highest confidence)
2. `same_phone_7d`
3. `same_email_7d`
- Duplicate handling:
no new lead record, update existing lead with any missing structured fields and append follow-up message context.

## Notification Behavior
- Customer acknowledgment:
prefer customer email, fall back to customer SMS.
- Contractor notification:
prefer business notification email, fall back to business notification SMS.
- Notifications are mocked but abstracted through provider interfaces for future Twilio/SMTP swap-in.

## Mocked in MVP
- Inbox polling/webhook adapter (external trigger still manual/postman-driven).
- Email/SMS delivery providers (`MockEmailProvider`, `MockSMSProvider`).
- Delivery success is simulated, but events and timestamps are persisted as if sent.

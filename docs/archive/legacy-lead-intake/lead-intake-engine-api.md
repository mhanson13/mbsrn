# Lead Intake Engine API - Phase 1 and Phase 2

Base path: `/api`

## POST `/api/intake/manual`
Purpose: Create a lead from manual entry.

Request body:
```json
{
  "business_id": "11111111-1111-1111-1111-111111111111",
  "submitted_at": "2026-03-12T16:25:00Z",
  "customer_name": "Jane Doe",
  "phone": "+13035550100",
  "email": "jane@example.com",
  "service_type": "fire restoration",
  "city": "Denver",
  "message": "Need estimate",
  "estimated_job_value": 4500
}
```

Response body:
```json
{
  "lead": {
    "id": "uuid",
    "business_id": "uuid",
    "source": "manual",
    "status": "new"
  },
  "message": "Lead captured from manual entry."
}
```

## POST `/api/intake/email`
Purpose: Ingest a GoDaddy-style email notification and create or update a lead.

Supported request modes:

1. Raw email payload (future inbox adapter):
```json
{
  "business_id": "11111111-1111-1111-1111-111111111111",
  "source_ref": "msg-12345",
  "received_at": "2026-03-12T16:25:00Z",
  "from_address": "noreply@notifications.godaddy.com",
  "subject": "New form submission from Jane Doe",
  "body_text": "Name: Jane Doe\nPhone: (303) 555-0100\nEmail: jane@example.com\nMessage: Need estimate."
}
```

2. Normalized mock payload (local testing):
```json
{
  "business_id": "11111111-1111-1111-1111-111111111111",
  "source_ref": "mock-msg-1",
  "received_at": "2026-03-12T16:25:00Z",
  "normalized_fields": {
    "customer_name": "Jane Doe",
    "phone": "+13035550100",
    "email": "jane@example.com",
    "service_type": "fire restoration",
    "city": "Denver",
    "message": "Need estimate."
  }
}
```

Response body:
```json
{
  "lead": {
    "id": "uuid",
    "business_id": "uuid",
    "source": "godaddy_email",
    "status": "new"
  },
  "duplicate": false,
  "parse_status": "parsed",
  "events_recorded": [
    "email_received",
    "lead_parsed",
    "lead_created",
    "customer_ack_triggered",
    "contractor_notification_triggered"
  ],
  "message": "Lead captured from email intake."
}
```

Notes:
- `parse_status` is one of: `parsed`, `normalized`, `failed`.
- `duplicate=true` means no new lead row was created; existing lead was updated.
- `events_recorded` always includes notification trigger events, even when delivery is skipped.

## GET `/api/leads`
Purpose: List leads for one business.

Query params:
- `business_id` (required)
- `status` (optional): `new|contacted|estimate_scheduled|won|lost`

## GET `/api/leads/{id}`
Purpose: Fetch one lead.

## PATCH `/api/leads/{id}/status`
Purpose: Apply lifecycle transition and log a status event.

Request body:
```json
{
  "status": "contacted",
  "actor_type": "owner",
  "actor_id": "owner-1",
  "event_note": "Called and left voicemail"
}
```

## GET `/api/leads/summary`
Purpose: Return simple pipeline + response metrics.

Query params:
- `business_id` (required)
- `window`: `24h|7d|30d` (default `7d`)

Response includes:
- `total_leads`
- `new_leads`
- `leads_awaiting_response`
- `stale_15m_count`
- `stale_2h_count`
- `avg_response_minutes`
- `median_response_minutes`

Backward-compatible fields remain:
- `avg_minutes_to_first_response`
- `uncontacted_over_30_min`

## GET `/api/leads/{id}/timeline`
Purpose: Return lead event timeline in chronological order.

Response shape:
```json
{
  "lead_id": "uuid",
  "events": [
    {
      "event_type": "lead_created",
      "event_timestamp": "2026-03-12T16:25:00Z",
      "actor_type": "system",
      "actor_id": null,
      "payload_json": {}
    }
  ]
}
```

## POST `/api/jobs/lead-reminders/run`
Purpose: Manually run reminder scan for a business.

Request body:
```json
{
  "business_id": "11111111-1111-1111-1111-111111111111"
}
```

## GET `/api/businesses/{id}`
Purpose: Read business notification settings.

## PATCH `/api/businesses/{id}/settings`
Purpose: Update business-level notification controls.

Example payload:
```json
{
  "notification_phone": "+13035550123",
  "notification_email": "owner@tmfire.example",
  "sms_enabled": true,
  "email_enabled": true,
  "customer_auto_ack_enabled": true,
  "contractor_alerts_enabled": true,
  "timezone": "America/Denver"
}
```

## Notification Delivery Event Types
The following events may appear in lead timelines:
- `notification_dispatch_requested`
- `notification_dispatch_sent`
- `notification_dispatch_failed`
- `notification_fallback_attempted`
- `notification_fallback_sent`
- `notification_dispatch_skipped`

Response shape:
```json
{
  "business_id": "11111111-1111-1111-1111-111111111111",
  "scanned_leads": 5,
  "reminders_sent": 3,
  "reminder_15m_sent": 2,
  "reminder_2h_sent": 1,
  "actions": [
    {
      "lead_id": "uuid",
      "threshold_minutes": 15,
      "event_type": "reminder_15m_triggered",
      "notification_sent": true,
      "channel": "email",
      "recipient": "owner@tmfire.example"
    }
  ]
}
```

## Lifecycle Rules
Allowed transitions:
- `new -> contacted`
- `new -> estimate_scheduled`
- `new -> lost`
- `contacted -> estimate_scheduled`
- `contacted -> won`
- `contacted -> lost`
- `estimate_scheduled -> won`
- `estimate_scheduled -> lost`

Terminal statuses:
- `won`
- `lost`

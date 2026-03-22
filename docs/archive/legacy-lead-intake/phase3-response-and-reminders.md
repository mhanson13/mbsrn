# Phase 3: Response Metrics, Stale Detection, and Reminders

## Overview
Phase 3 makes lead intake operationally actionable.  
It adds metrics and reminders so owner-operators can quickly see which leads are waiting and what actions the system already took.

## Goals
- Measure real human response performance.
- Detect stale leads that need attention now.
- Trigger reminders at practical thresholds.
- Expose a full lead event timeline for auditability.

## Core Behaviors

### Response-Time Metrics
- Primary metric: `submitted_at -> first_human_response_at`.
- Fallback metric (for legacy/partial records): earliest `status_changed` event where `to != "new"`.
- `customer_acknowledged_at` is not counted as human response.
- Metrics produced:
  - `avg_response_minutes`
  - `median_response_minutes`
  - `leads_awaiting_response`
  - stale counts (`15m`, `2h`)

### Stale Lead Detection
A lead is stale when all are true:
- `status == "new"`
- `first_human_response_at is null`
- lead age is above threshold

Thresholds:
- stale warning: 15 minutes
- escalation threshold: 2 hours

### Reminder Engine
Manual run endpoint calls the reminder engine.

Rules:
- Thresholds: 15m and 2h.
- No duplicate threshold reminders per lead.
- Reminder events are persisted to `lead_events`:
  - `reminder_15m_triggered`
  - `reminder_2h_triggered`
- Notification send remains mocked through provider interfaces.

### Lead Timeline
`GET /api/leads/{id}/timeline` returns lead events in chronological order:
- `event_type`
- `event_timestamp`
- `actor_type`
- `actor_id`
- `payload_json`

## Flow
1. Lead is captured (manual/email).
2. Owner may or may not respond.
3. Summary metrics identify awaiting/stale leads.
4. `POST /api/jobs/lead-reminders/run` scans eligible leads.
5. Reminder events and mock notification outcomes are recorded.
6. Timeline endpoint shows complete history for each lead.

## Why This Fits MVP
- Monolithic FastAPI app and existing SQLAlchemy models are reused.
- No queues or infrastructure expansion.
- Logic is explicit and testable.
- One developer can maintain and extend thresholds/channels later.

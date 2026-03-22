# Lead Intake Engine - Phase 1

## Goal
Provide a clean baseline for capturing and tracking leads manually with minimal complexity.

## Phase 1 Scope
- FastAPI backend scaffold
- PostgreSQL-ready configuration
- SQLAlchemy models for `businesses`, `leads`, and `lead_events`
- Alembic-ready project structure
- Manual lead intake endpoint
- Lead list endpoint
- Lead detail endpoint
- Lead status update endpoint
- Basic summary endpoint
- Unit tests for manual lead creation and status transitions

## Out of Scope (Phase 2+)
- GoDaddy email parsing and intake automation
- Customer acknowledgment messaging
- Owner SMS/email notifications
- Twilio/SMTP integrations

## Request Flow (Phase 1)
1. Owner enters a lead manually via `POST /api/intake/manual`.
2. Service creates a lead record with status `new`.
3. Service logs a `lead_created` event in `lead_events`.
4. Owner updates status over time (`new -> contacted -> estimate_scheduled -> won/lost`).
5. Summary endpoint returns counts and response-time metrics.

## Design Principles
- Monolithic app, one database.
- Business logic in services.
- Thin route handlers.
- Explicit lifecycle rules.
- Contractor-friendly output focused on leads and job outcomes.

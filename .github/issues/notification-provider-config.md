# Notification Provider Configuration

## Summary

Review and document environment configuration for SMS and email providers so local, dev, and pilot environments are easy to operate.

## Scope

Files to inspect:

- `app/integrations/sms_provider.py`
- `app/integrations/email_provider.py`
- `app/core/config.py`
- `.env.example`
- `README.md`

## Goals

- Make provider selection predictable.
- Document required environment variables for mock, dev, and live providers.
- Ensure safe defaults for local development.

## Tasks

- [ ] Review provider mode selection.
- [ ] Review required environment variables.
- [ ] Update `.env.example` if needed.
- [ ] Document provider configuration in README or docs.

## Acceptance Criteria

- Local dev works with safe defaults.
- Pilot/live configuration is documented clearly.
- Missing provider credentials fail safely and visibly.

## Summary

Audit the current backend for multi-tenant SaaS readiness by verifying that all lead, reminder, notification, and business settings flows are correctly scoped by `business_id`.

## Scope

Files and areas to inspect:

- `app/models/`
- `app/repositories/`
- `app/services/`
- `app/jobs/`
- `app/api/routes/`

## Goals

- Confirm every lead-related operation is scoped to the correct business.
- Confirm notification routing uses business-specific settings only.
- Confirm reminder runs do not cross business boundaries.
- Identify any hidden assumptions that only one business exists.

## Tasks

- [ ] Review lead creation and lookup paths for business scoping.
- [ ] Review reminder engine and jobs for tenant-safe filtering.
- [ ] Review notification dispatch for business-specific settings usage.
- [ ] Review summary/timeline endpoints for tenant-safe behavior.
- [ ] Document any global assumptions that should be removed.

## Acceptance Criteria

- All operational flows are clearly scoped by `business_id`.
- No service assumes a single global business configuration.
- Risks to future multi-tenant SaaS rollout are documented and prioritized.

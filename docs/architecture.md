# Work Boots Console Architecture

## Overview
Work Boots Console is a single FastAPI monolith focused on contractor lead intake and follow-up operations.

## Repository Structure
```text
work-boots/
  app/
    api/
    core/
    db/
    integrations/
    jobs/
    models/
    repositories/
    schemas/
    services/
    tests/
    main.py
  alembic/
  docs/
  frontend/
  infra/
  scripts/
  _archive/
```

## Runtime Flow
1. Intake routes receive manual or email lead payloads.
2. Services parse/normalize/dedupe and persist leads.
3. Lead events are appended for auditability and timeline views.
4. Reminder job scans stale `new` leads and triggers mock notifications.
5. Summary endpoints expose pipeline and response metrics.

## Tenant Context
- Tenant scope is resolved at the API boundary via server-side request context dependency (`get_tenant_context`).
- Tenant-sensitive routes must pass only auth-derived tenant `business_id` into services/repositories.
- Client-supplied `business_id` fields/query params are compatibility-only and are not trusted; mismatches are rejected.
- Service/repository/database tenant checks remain in place as defense in depth.

## Design Principles
- One deployable backend process.
- Explicit service/repository boundaries.
- Thin route handlers.
- Rules-based parsing and reminder logic.
- Mocks behind provider interfaces for external integrations.

## Archived Components
Legacy TypeScript backend scaffolding and deprecated scripts are preserved under `_archive/`.

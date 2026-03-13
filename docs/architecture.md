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
- Primary auth path is persisted API credentials: bearer token -> `api_credentials` lookup -> `principal_id` + `business_id`.
- API credentials are operationally managed via business-scoped endpoints:
  - `POST /api/businesses/{business_id}/credentials` (issue new token)
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/disable`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/revoke`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/rotate`
- Credential tokens are only returned at issue/rotate time; database stores `token_hash` only.
- Tenant-sensitive routes pass only auth-derived tenant `business_id` into services/repositories.
- Client-supplied `business_id` fields/query params are compatibility-only and are not trusted; mismatches are rejected.
- Optional keyed hashing is supported via `API_TOKEN_HASH_PEPPER`; legacy SHA-256 hashes can remain readable during rollout with `ALLOW_LEGACY_TOKEN_HASH_FALLBACK=true`.
- Env principal-token mode (`API_AUTH_PRINCIPALS_JSON`) and legacy shared-token mode are compatibility fallbacks gated by `ALLOW_AUTH_COMPAT_FALLBACK` (off by default in production).
- Dev/test-only fallback uses `DEFAULT_BUSINESS_ID` only when no auth config is present.
- Inactive credentials (`is_active=false`) and revoked credentials (`revoked_at` set) are rejected.
- Service/repository/database tenant checks remain in place as defense in depth.

## Design Principles
- One deployable backend process.
- Explicit service/repository boundaries.
- Thin route handlers.
- Rules-based parsing and reminder logic.
- Mocks behind provider interfaces for external integrations.

## Archived Components
Legacy TypeScript backend scaffolding and deprecated scripts are preserved under `_archive/`.

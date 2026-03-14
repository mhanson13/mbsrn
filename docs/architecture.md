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
- Credentials now bind to persisted principals in `principals` via `(business_id, principal_id)` ownership constraints.
- Principals carry a minimal business-scoped authorization role: `admin` or `operator`.
- API credentials are operationally managed via business-scoped endpoints:
  - `POST /api/businesses/{business_id}/credentials` (issue new token)
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/disable`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/revoke`
  - `POST /api/businesses/{business_id}/credentials/{credential_id}/rotate`
- Principals are now first-class business-scoped entities with admin-only lifecycle endpoints:
  - `GET /api/businesses/{business_id}/principals`
  - `POST /api/businesses/{business_id}/principals`
  - `PATCH /api/businesses/{business_id}/principals/{principal_id}`
  - `POST /api/businesses/{business_id}/principals/{principal_id}/activate`
  - `POST /api/businesses/{business_id}/principals/{principal_id}/deactivate`
- Credential tokens are only returned at issue/rotate time; database stores `token_hash` only.
- Credential metadata includes `label`, `last_used_at`, and `rotated_from_credential_id` for operational auditability.
- Principal metadata includes `created_by_principal_id`, `updated_by_principal_id`, and `last_authenticated_at` for lightweight admin-action visibility.
- Successful DB credential authentication updates `last_used_at`.
- Successful DB credential authentication also updates principal `last_authenticated_at`.
- Tenant-sensitive routes pass only auth-derived tenant `business_id` into services/repositories.
- Client-supplied `business_id` fields/query params are compatibility-only and are not trusted; mismatches are rejected.
- `API_TOKEN_HASH_PEPPER` is required in production so token verification uses keyed hashing.
- Legacy unpeppered SHA-256 verification is disabled by default and only enabled temporarily with `ALLOW_LEGACY_TOKEN_HASH_FALLBACK=true` during migration.
- Legacy shared-token auth (`API_AUTH_TOKEN` / `API_AUTH_BUSINESS_ID`) is no longer used for runtime tenant auth.
- Dev/test-only fallback uses `DEFAULT_BUSINESS_ID` only when no auth config is present.
- Inactive credentials (`is_active=false`) and revoked credentials (`revoked_at` set) are rejected.
- Inactive principals are rejected during auth even when credentials are active.
- Credential-management and principal-management routes require an `admin` principal role.
- Service/repository/database tenant checks remain in place as defense in depth.

## Current Out Of Scope
- Full IAM model (users, roles, memberships, session lifecycle).

## Design Principles
- One deployable backend process.
- Explicit service/repository boundaries.
- Thin route handlers.
- Rules-based parsing and reminder logic.
- Mocks behind provider interfaces for external integrations.

## Archived Components
Legacy TypeScript backend scaffolding and deprecated scripts are preserved under `_archive/`.

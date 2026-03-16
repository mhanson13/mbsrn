# Work Boots Console – Security Architecture Snapshot

## 1) Overview
Work Boots Console implements a multi-tenant SaaS security model centered on `business_id` as the tenant boundary.

The current implementation uses layered protections across:
- API authentication
- request-rate abuse protections
- tenant-scoped authorization
- service-layer validation
- repository scoping
- database integrity constraints
- persisted audit visibility for high-value identity/admin actions

This document is a current-state implementation snapshot after Issue #17, not a future-state IAM design.

## 2) Security Layers
Defense in depth is applied from request entry to persistence:

```text
Client
  ↓
API Authentication (Bearer token)
  - Google OIDC exchange -> app session token, or
  - DB API credential lookup
  ↓
Rate limiting / abuse throttling
  ↓
TenantContext resolution (business_id + principal_id + auth_source)
  ↓
Authorization checks (principal role / active state)
  ↓
Service validation (business ownership + business rules)
  ↓
Repository scoping (business-scoped queries)
  ↓
Database constraints (FK/composite constraints)
```

No single layer is relied on as the only tenant-protection mechanism.

## 3) Tenant Isolation Model
- All tenant-sensitive entities are business-scoped.
- `business_id` is the canonical tenant boundary.
- API handlers enforce tenant scope via `TenantContext` and reject mismatched requested `business_id`.
- Service and repository methods use business-scoped access patterns (`get_for_business`, scoped list methods).
- Database integrity constraints reinforce ownership:
  - `lead_events` includes `business_id` and composite ownership enforcement for lead/event consistency.
  - `api_credentials` binds to principals with composite ownership (`business_id`, `principal_id`).

## 4) Authentication Model
Runtime authentication path:
1. Client sends `Authorization: Bearer <token>`.
2. Token is resolved through one of two runtime paths:
   - app session token issued by `POST /api/auth/google/exchange`, or
   - DB-backed `api_credentials` token hash lookup.
3. For Google exchange:
   - Google ID token is verified with JWKS signature validation (`iss`, `aud`, `sub`) and email verification policy.
   - `principal_identities` mapping (`provider=google`, `provider_subject=sub`) is resolved.
   - mapped principal must be active.
   - internal JWT access/refresh tokens are issued with claims: `iss`, `aud`, `iat`, `nbf`, `exp`, `sub`, `jti`.
   - explicit logout is supported via `POST /api/auth/logout`, revoking the active access token and optionally the current refresh token.
4. For DB credentials:
   - credential must be active and non-revoked.
   - bound principal must be active.
5. `TenantContext` is produced from credential/principal binding.

`TenantContext` is server-derived and used by routes/services for tenant scoping.

Current runtime behavior notes:
- Env-based principal mapping is not part of runtime auth resolution.
- Legacy shared-token auth is not part of runtime auth resolution.
- A dev/test fallback exists when no bearer token is supplied: non-production environments can fall back to `DEFAULT_BUSINESS_ID` for local workflows.
- Application-level rate limiting is enabled by default:
  - auth request throttling keyed by client IP + normalized user-agent bucket
  - stricter admin-route throttling keyed by action + business + principal + client IP + user-agent bucket
  - throttled requests return HTTP 429
- Rate limiting and token/session revocation state support Redis-backed distributed enforcement for multi-pod deployments (with local in-memory fallback for dev/test).
- Redis failure behavior is explicit and configurable:
  - `RATE_LIMIT_FAIL_OPEN`
  - `SESSION_STATE_FAIL_OPEN`
  Production default is fail-closed unless explicitly overridden.

## 5) Credential Security
- Plaintext tokens are not stored in the database.
- `api_credentials.token_hash` is stored; plaintext token is returned only at issuance/rotation response time.
- Normal credential list/read responses do not expose `token_hash`.
- Production requires `API_TOKEN_HASH_PEPPER`; token verification uses peppered hashing.
- Optional legacy unpeppered hash verification exists behind explicit config (`ALLOW_LEGACY_TOKEN_HASH_FALLBACK`) for migration compatibility.

## 6) Principals
Principals are persisted and business-scoped.

Current principal fields include:
- `business_id`
- `id`
- `display_name`
- `role` (`admin` or `operator`)
- `is_active`
- `created_by_principal_id`
- `updated_by_principal_id`
- `last_authenticated_at`
- `created_at`
- `updated_at`

Principals are bound to businesses and used as the authenticated identity behind API credentials.

`principal_identities` provides provider-subject mapping to principals for human login flows (Google OIDC).

## 7) Authorization Model
Current role model is intentionally minimal:
- `admin`
- `operator`

`admin` is required for business-scoped management operations, including:
- business settings updates
- credential management (create/list/disable/revoke/rotate)
- principal management (list/create/update/activate/deactivate)
- auth/admin audit event read endpoint

`operator` principals are authenticated for normal tenant-scoped operations but are blocked from admin-only management routes.

## 8) Principal Lifecycle
Implemented principal lifecycle operations:
- create principal
- update principal (display/role/active-state changes)
- activate principal
- deactivate principal

Behavior:
- Inactive principals are rejected during authentication.
- Inactive principals cannot perform admin actions.
- Role changes apply immediately.
- Last active admin protection is enforced: deactivating/demoting the final active admin principal is rejected.

## 9) Credential Lifecycle
Implemented credential lifecycle operations:
- create credential
- list credentials
- disable credential
- revoke credential
- rotate credential

Credential metadata currently includes:
- `label`
- `last_used_at`
- `rotated_from_credential_id`
- `is_active`
- `revoked_at`
- timestamps

Rotation creates a new credential and retires the prior credential.

## 10) TenantContext
`TenantContext` currently contains:
- `business_id`
- `principal_id`
- `auth_source`
- `principal_role` (optional, populated when available)

## 11) Audit Logging
Work Boots Console now persists lightweight auth/admin audit events for high-value identity/admin actions.

Current audit model (`auth_audit_events`) includes:
- `id`
- `business_id`
- `actor_principal_id` (nullable)
- `target_type` (for example `principal`, `api_credential`)
- `target_id`
- `event_type`
- `details_json` (small non-secret context)
- `created_at`

Captured event coverage includes:
- principal: create/update/activate/deactivate
- credentials: create/disable/revoke/rotate
- session security:
  - refresh replay detection (`session_refresh_replay_detected`)
  - explicit logout (`session_logout`)

Admin read path:
- `GET /api/businesses/{business_id}/auth-audit-events`
- supports simple filters (`target_type`, `event_type`) and bounded `limit`

Audit records are business-scoped and tenant-protected via the same route scoping/authorization model.

## 12) Secret Safety
Current guarantees:
- Plaintext tokens are never persisted.
- `token_hash` is not exposed by normal list/read APIs.
- Plaintext tokens are returned only at issuance/rotation time.
- Audit payload sanitization removes secret-like keys (token/hash/authorization patterns).
- Audit trail is designed for operational context, not secret material.

## 13) Test Coverage
Current automated tests cover:
- tenant isolation and cross-tenant rejection paths
- DB-backed credential authentication behavior
- principal lifecycle and admin/operator authorization boundaries
- credential lifecycle behavior (including rotation/revocation/disable paths)
- inactive principal authentication rejection
- auth/admin audit event persistence and business scoping
- secret-safe API responses and audit payload sanitization

Coverage is focused and regression-oriented, not a formal security certification suite.

## 14) Out of Scope
Intentionally out of scope at this stage:
- full IAM platform
- users/sessions/invites/onboarding
- rich permission matrix / full RBAC
- enterprise audit platform features (retention policies, external sinks, compliance workflows)

## 15) Summary
The current architecture provides a secure incremental identity model for a multi-tenant SaaS backend:
- tenant scope is derived server-side
- authorization is enforced with a minimal, explicit role model
- principal and credential lifecycle operations are operationally manageable
- high-value identity/admin actions are auditable
- data protections are enforced across API, service, repository, and database layers

This is a practical foundation for future IAM evolution without overreaching beyond MVP scope.

# Operator UI And Google Auth

## Overview
Work Boots now includes a standalone operator UI app in `frontend/operator-ui` built with Next.js + React + TypeScript.

The FastAPI monolith remains the system of record. The UI consumes existing business-scoped APIs and does not reimplement backend business logic.

## Authentication and Authorization Model

1. User authenticates with Google (OIDC ID token).
2. UI calls `POST /api/auth/google/exchange`.
3. Backend verifies Google token via JWKS signature + claim validation (`sub`, issuer, audience, email_verified policy).
4. Backend resolves `principal_identities` mapping (`provider=google`, `provider_subject=sub`).
5. Backend validates mapped internal principal is active.
6. Backend issues signed app JWT access + refresh tokens.
7. API authorization remains internal and business-scoped via principal/business role checks.

Key boundary:
- Google answers identity (`who is the user?`).
- Work Boots answers authorization (`what can the user do?`).

## Backend Data Model Additions

`principal_identities`
- Maps external identity providers to internal principals.
- Enforces one provider subject to one principal mapping.
- Includes active state and `last_authenticated_at` tracking.

## Auth Endpoints

- `POST /api/auth/google/exchange`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Business admin identity mapping endpoints:
- `GET /api/businesses/{business_id}/principal-identities`
- `POST /api/businesses/{business_id}/principal-identities`
- `POST /api/businesses/{business_id}/principal-identities/{identity_id}/activate`
- `POST /api/businesses/{business_id}/principal-identities/{identity_id}/deactivate`

## UI Scope (Initial Operator Surface)

Implemented pages:
- Dashboard
- Sites
- Audit runs
- Competitor intelligence sets
- Recommendations
- Automation run history

The UI uses a typed API client and environment-based API configuration:
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`

## Security Notes

- Google identity alone does not grant access.
- Access requires explicit mapping to an internal principal.
- Inactive principal identities are rejected.
- Inactive principals are rejected.
- Tenant/business scope enforcement remains in existing `TenantContext` + repository/service lineage protections.
- Operator UI session storage policy:
  - access token: `sessionStorage`
  - refresh token: in-memory only (not browser-persistent)
  - principal metadata: `sessionStorage`
  - sign-out calls `/api/auth/logout` and clears local session state

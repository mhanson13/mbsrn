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

## Google Login Vs Google Business Profile Authorization

These are two distinct flows and remain intentionally separated:

1. Google sign-in (OIDC) for Work Boots session authentication:
   - UI obtains a Google ID token.
   - API verifies identity and issues Work Boots app session tokens.
   - No Google API resource access is granted by this step.
2. Google Business Profile connection (OAuth authorization code flow):
   - Authenticated Work Boots user explicitly starts a connect flow.
   - API requests `https://www.googleapis.com/auth/business.manage`.
   - API exchanges code server-side and stores provider credentials for future Google API calls.

Why this separation matters:
- OIDC login identifies the user for Work Boots access control.
- OAuth authorization grants delegated Google API access for Business Profile operations.
- Login success alone is not sufficient to call Business Profile APIs.

## Backend Data Model Additions

`principal_identities`
- Maps external identity providers to internal principals.
- Enforces one provider subject to one principal mapping.
- Includes active state and `last_authenticated_at` tracking.

`provider_oauth_states`
- Stores one-time, expiring OAuth `state` hashes for replay-resistant callback handling.
- Stores encrypted PKCE `code_verifier` material bound to the same principal/business scope.

`provider_connections`
- Stores tenant-scoped provider connection metadata and encrypted OAuth tokens for API integrations.

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

Business Profile authorization endpoints:
- `POST /api/integrations/google/business-profile/connect/start`
- `GET /api/integrations/google/business-profile/connect/callback`
- `GET /api/integrations/google/business-profile/connection`
- `POST /api/integrations/google/business-profile/disconnect`

Business Profile read-only integration endpoints:
- `GET /api/integrations/google/business-profile/accounts`
- `GET /api/integrations/google/business-profile/locations`
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification`

## Google Business Profile Connect Flow

1. Authenticated user calls `POST /api/integrations/google/business-profile/connect/start`.
2. API validates tenant/principal context, generates one-time `state`, generates PKCE verifier/challenge, and returns Google authorization URL.
3. User grants consent for `https://www.googleapis.com/auth/business.manage`.
4. Google redirects to configured callback URI with `code` + `state`.
5. API validates `state`, decrypts stored PKCE verifier, exchanges code server-side (with verifier), and persists encrypted provider credentials.
6. API integration calls can later use stored credentials and refresh tokens server-side.

Security controls in this flow:
- one-time state hash persistence with TTL and consume-on-callback behavior
- PKCE (`S256`) challenge on start + verifier replay in callback token exchange
- fixed, server-configured redirect URI
- no access/refresh token exposure in browser API responses
- encrypted token persistence at rest
- token encryption key version persisted with provider credentials for key rotation compatibility
- keyring-based decrypt/encrypt behavior (active encryption key + optional legacy decrypt keys)
- denial/missing-refresh/replay/refresh-failure handling with auth audit events

## UI Scope (Initial Operator Surface)

Implemented pages:
- Dashboard
- Sites
- Audit runs
- Competitor intelligence sets
- Recommendations
- Automation run history
- Google Business Profile (connection state + verification status badges)

The UI uses a typed API client and environment-based API configuration:
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`

## Required Environment Configuration

Authentication (existing Google sign-in):
- `GOOGLE_AUTH_ENABLED`
- `GOOGLE_OIDC_CLIENT_ID`
- `GOOGLE_OIDC_JWKS_URL`
- `GOOGLE_OIDC_REQUIRE_EMAIL_VERIFIED`
- `APP_SESSION_SECRET`

Business Profile authorization (new integration connect flow):
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_BUSINESS_PROFILE_REDIRECT_URI`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_SECRET` (single-key fallback only)
- `GOOGLE_BUSINESS_PROFILE_STATE_TTL_SECONDS`
- `GOOGLE_OAUTH_REFRESH_SKEW_SECONDS`
- `GOOGLE_BUSINESS_PROFILE_ACCOUNT_API_BASE_URL` (optional override)
- `GOOGLE_BUSINESS_PROFILE_BUSINESS_INFORMATION_API_BASE_URL` (optional override)
- `GOOGLE_BUSINESS_PROFILE_VERIFICATIONS_API_BASE_URL` (optional override)
- `GOOGLE_BUSINESS_PROFILE_API_TIMEOUT_SECONDS` (optional override)

`GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` default to the OIDC values when omitted, but dedicated OAuth client credentials are recommended for production clarity.

## Google Cloud Setup Requirements For Business Profile

Before connect flow can succeed in a real environment:
- Enable Business Profile related APIs in the Google Cloud project used by your OAuth client.
- Required APIs:
  - Business Profile Account Management API
  - Business Profile Business Information API
  - Business Profile Verifications API
- Configure OAuth consent screen and app publishing/test-user policy as required by your org and Google policy.
- Ensure OAuth client redirect URI includes:
  - `<API_BASE_URL>/api/integrations/google/business-profile/connect/callback`
- Confirm your Google account/project has required Business Profile API access/approval.

If API access is not enabled/approved, OAuth may succeed but downstream Business Profile API calls will fail.

## Token Lifecycle Hardening

### Keyring-Based Token Encryption

- Provider tokens are encrypted with a symmetric keyring abstraction.
- Config model:
  - `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION`: active write key version.
  - `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`: mapping of `key_version -> key_material`.
- Encryption always uses the active key version.
- Decryption requires `token_key_version` stored with each credential row and fails closed when that key version is not present.
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_SECRET` is a backward-compatible single-key fallback when keyring JSON is not configured.

### PKCE In Connect Flow

- Connect/start generates a PKCE `code_verifier` and derives an `S256` `code_challenge`.
- Authorization URL includes `code_challenge` and `code_challenge_method=S256`.
- The verifier is encrypted in `provider_oauth_states` and bound to the one-time state record.
- Callback decrypts the verifier and includes it in server-side token exchange.
- Google validates verifier/challenge relationship during token exchange.

### Lazy Refresh On Token Use

- Future Google API calls should use `GoogleBusinessProfileConnectionService.get_access_token_for_use(...)`.
- Token use behavior:
  - loads active business-scoped provider connection
  - validates required scopes
  - refreshes synchronously when token is expired or within `GOOGLE_OAUTH_REFRESH_SKEW_SECONDS`
  - persists refreshed token material, expiry, refresh metadata, and active key version
  - returns deterministic `reconnect_required=true` when refresh fails
- Phase 5 GBP read-only service calls this accessor before every Google API request.
- No background refresh worker is required for this stage.

### Runtime Scope Validation

- Scope checks are normalized and order-insensitive.
- Required scopes are validated for every provider token-use decision.
- Missing required scope fails closed with `token_status=insufficient_scope` and `reconnect_required=true`.

### Connection Usability Contract

Internal connection usability payload includes:
- `connected`
- `reconnect_required`
- `refresh_token_present`
- `expires_at`
- `granted_scopes`
- `required_scopes_satisfied`
- `token_status` (`usable | refresh_required | reconnect_required | insufficient_scope`)

### Phase 5 Verification Mapping Contract

- GBP read-only service normalizes Google payloads into account/location objects with verification summary:
  - `verified` when Voice of Merchant confirms verification
  - `pending` when verification state is pending/in-progress
  - `unverified` when no active verification exists
  - `unknown` when Google API responses are ambiguous or error-prone
- Next-action hints:
  - `none`
  - `start_verification`
  - `complete_pending`
  - `resolve_access`
  - `reconnect_google`

## Operator Key Rotation And Rewrap Procedure

### Rotation Procedure

1. Generate a new key material value.
2. Update `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON` to include both old and new key versions.
3. Set `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION` to the new active version.
4. Deploy the config change.
5. Run token rewrap:
   - Per business:
     - `GoogleBusinessProfileConnectionService.rewrap_tokens_with_active_key(business_id=<...>, actor_principal_id=<admin_principal>)`
   - All stored GBP provider tokens:
     - `GoogleBusinessProfileConnectionService.rewrap_all_tokens_with_active_key()`
6. Verify each rotated connection row now has `token_key_version=<new_version>`.
7. After verification window, remove legacy key versions from the keyring JSON.

### Rollback Procedure

1. Keep both key versions available in `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`.
2. Revert `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION` to the previous version.
3. Redeploy configuration.
4. Re-run token rewrap back to the previous active version if required.
5. Do not remove either key version until decryption + token use validates cleanly.

## Security Notes

- Google identity alone does not grant access.
- Access requires explicit mapping to an internal principal.
- Inactive principal identities are rejected.
- Inactive principals are rejected.
- Tenant/business scope enforcement remains in existing `TenantContext` + repository/service lineage protections.
- Business Profile connection credentials are tenant-scoped and server-managed (not browser-managed).
- Refresh tokens are required for durable API access; if Google does not return one, reconnect with consent.
- Refresh token issuance behavior is controlled by Google policy and prior consent history; reconnect may be required.
- Operator UI session storage policy:
  - access token: `sessionStorage`
  - refresh token: in-memory only (not browser-persistent)
  - principal metadata: `sessionStorage`
  - sign-out calls `/api/auth/logout` and clears local session state

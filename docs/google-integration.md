# Google Integration

## Two Separate Flows (Do Not Conflate)

### Google Login (OIDC, Identity Only)
Purpose:
- authenticate operator identity
- map Google subject to internal principal
- issue mbsrn app session tokens

Primary endpoint:
- `POST /api/auth/google/exchange`

Notes:
- Uses Google ID token verification (JWKS).
- Does not grant Google Business Profile API access.

### Google Business Profile Connection (OAuth, Data Access)
Purpose:
- allow an authenticated operator to connect GBP for a business
- request delegated Google API access using OAuth
- persist encrypted provider credentials for server-side API calls

Primary endpoints:
- `POST /api/integrations/google/business-profile/connect/start`
- `GET /api/integrations/google/business-profile/connect/callback`
- `GET /api/integrations/google/business-profile/connection`
- `POST /api/integrations/google/business-profile/disconnect`

Callback completion behavior:
- Browser callback requests (`Accept: text/html` or explicit `response_mode=redirect`) now end with a redirect back into the operator app at `/business-profile` instead of rendering raw JSON.
- API/test callback requests can keep JSON response behavior with `response_mode=json`.
- Redirect targets are derived from trusted server config only (CORS/operator origins + configured callback origin fallback); arbitrary callback return URLs are not accepted.
- Site workspace also surfaces a compact GBP integration state card and action link back to `/business-profile` so operators can see connect/reconnect health without leaving their active workflow.

### Verification Workflow (Operator-Facing)
Current implemented routes:
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification`
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification/options`
- `GET /api/integrations/google/business-profile/locations/{location_id}/verification/status`
- `POST /api/integrations/google/business-profile/locations/{location_id}/verification/start`
- `POST /api/integrations/google/business-profile/locations/{location_id}/verification/complete`
- `POST /api/integrations/google/business-profile/locations/{location_id}/verification/retry`

Behavior notes:
- all actions are business-scoped and token-guarded server-side
- provider availability still controls which methods/actions are usable per location
- mbsrn guidance is deterministic and generated from normalized state (no live LLM dependency)
- `retry` is an app-level convenience over provider-supported start semantics, not a guaranteed provider-native primitive

## Required Scope
Current implementation requires:
- `https://www.googleapis.com/auth/business.manage`

Scope is enforced:
- during callback persistence checks
- during runtime token-use checks

## Google APIs Used By Current Implementation
The backend GBP client currently calls:
- Business Profile Account Management API
  - list accounts
- Business Profile Business Information API
  - list locations
- Business Profile Verifications API
  - voice of merchant state
  - list verifications

Configured via:
- `GOOGLE_BUSINESS_PROFILE_ACCOUNT_API_BASE_URL`
- `GOOGLE_BUSINESS_PROFILE_BUSINESS_INFORMATION_API_BASE_URL`
- `GOOGLE_BUSINESS_PROFILE_VERIFICATIONS_API_BASE_URL`

## Approval Requirement
Even with OAuth correctly configured, GBP data access can still fail unless:
- required APIs are enabled in Google Cloud
- OAuth consent configuration is valid
- Google account/project has required Business Profile API access approval

## Common Failure Modes

### No GBP accounts visible
Possible causes:
- connected Google account has no GBP accounts
- account-level access mismatch
- API response is empty for that principal

What to check:
- connection status is `connected` and not reconnect-required
- Google account used for connect has expected business access

### No locations returned
Possible causes:
- selected GBP account has no locations
- API returned empty location list

What to check:
- `GET /accounts` output first, then `GET /locations`
- account ownership and location visibility in Google UI

### Insufficient scope
Symptoms:
- API responds with 403 and reconnect guidance

Cause:
- stored granted scopes do not include `business.manage`

Fix:
- reconnect and grant required scope

### Reconnect required
Symptoms:
- API responds with 409 and `reconnect_required=true`

Common causes:
- refresh token missing
- token refresh failure (`invalid_grant`, revoked consent)
- encrypted token cannot be decrypted with configured keyring
- disconnected/inactive provider connection

Fix:
- reconnect Google Business Profile for that business
- verify keyring configuration if issue appeared after key rotation

### Permission denied / access issue
Symptoms:
- account/list endpoints can return 403
- per-location verification can normalize to `unknown` with `resolve_access`

Common causes:
- Google account lacks access to that profile/location
- API project/approval mismatch

Fix:
- verify account permissions in Google Business Profile Manager
- verify API enablement and project approval state

### API not enabled or project not approved
Symptoms:
- upstream provider request failures (often surfaced as 502 or permission errors)

Fix:
- enable required APIs
- complete Google approval/onboarding for Business Profile API access
- verify OAuth client and project alignment

### Verification action not available for this location
Current behavior:
- mbsrn can surface start/complete/retry endpoints, but Google may still reject an action for location state/method constraints
- refresh status, use available methods, and follow reconnect/access guidance when returned
- unknown/unmapped provider values degrade to safe normalized fallbacks and are surfaced through structured warning logs for mapping updates

# Google Profile (Sites Setup)

## Purpose
Google setup is site-scoped and now lives under `Sites` in the selected-site setup panel.

Primary setup route:
- `/sites` (Selected Site Setup > Google & Analytics)

Compatibility routes:
- `/google-profile`
- `/business-profile`

Compatibility behavior:
- both legacy routes show a moved notice and redirect to `/sites`
- query params are preserved
- when `site_id` is present, redirect targets include `#selected-site-setup`

## What the selected-site setup panel owns
- Google Profile connect/reconnect/disconnect/refresh state
- Google Business Profile locations/status
- GA4 property setup for the selected site
- compact GA4 property health and next-action guidance
- site-wide migration analytics insertion rules (`enabled`, measurement ID, insertion mode)

## OAuth Return vs Usable GBP Access
- `gbp_connect=success` indicates OAuth returned successfully, not that Google Business Profile access is usable.
- Final operator state is determined from loaded connection/location capability status.
- Status precedence in Selected Site Setup:
  1. connected and usable
  2. connected but GBP access denied / missing permission
  3. OAuth returned and verification still loading
  4. not connected
  5. unavailable/error
- Bounded GBP status classification now distinguishes:
  - `missing_scope`
  - `permission_denied`
  - `no_accounts`
  - `no_locations`
  - `oauth_connected` (linked but verification/reconnect still needed)
  - `usable`
- Bounded provider diagnostic classes are surfaced for denied/unavailable states:
  - `missing_required_scope`
  - `provider_unauthorized`
  - `provider_permission_denied`
  - `provider_api_disabled_or_unavailable`
  - `provider_rate_limited`
  - `provider_quota_or_access_not_granted`
  - `provider_not_found`
  - `provider_unavailable`
  - `provider_unknown`
- HTTP `429` from GBP APIs is treated as rate-limit/quota/resource-exhaustion diagnostics, not generic transient outage:
  - `provider_rate_limited` for `RESOURCE_EXHAUSTED` / `rateLimitExceeded` / too-many-requests style responses
  - `provider_quota_or_access_not_granted` when 429 details indicate quota or project access is not granted
- Sites selected-site setup displays compact diagnostics:
  - provider diagnostic class
  - provider HTTP status (when available)
  - required scope granted (`yes/no/unknown`)
  - bounded next action + diagnostic hint
- Example denied-state message:
  - `Google returned successfully, but Google Business Profile access is denied for this account.`

## Admin Verification Checklist (No Secrets)
When OAuth is linked but GBP remains denied/unavailable, verify:
1. Google Cloud project that owns the OAuth client ID used by MBSRN.
2. APIs & Services -> Enabled APIs includes Business Profile-related APIs used by MBSRN.
3. OAuth consent screen -> Data Access includes Business Profile scope (`https://www.googleapis.com/auth/business.manage`).
4. API quota/access in the OAuth client project:
   - `My Business Account Management API`
   - `My Business Business Information API`
   and confirm project access/approval is granted where required.
5. Connected Google identity in Sites setup matches the expected operator account.

## Boundaries
- setup ownership is `Sites`; Site Workspace remains a command center
- no top-level `Google Profile` nav item
- no secrets or credential values are exposed in UI
- GA4 behavior remains site-scoped and read-only from the operator surface perspective

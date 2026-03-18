# Operator Guide

Audience: operators and admins using the UI.

## Verification Guidance
- Work Boots now provides deterministic, plain-language guidance from normalized verification state.
- Guidance includes a title, short summary, concrete next steps, and a primary CTA.
- Guidance is rule-based today; no live AI service is required for this feature.
- If Google returns an unexpected status or method, Work Boots falls back to safe guidance and may ask you to refresh or reconnect.
- Verification workflow errors also include normalized guidance so the UI can show the same style of next steps in failure states.

## Connection Status Meanings

### Connected
Meaning:
- this business has an active Google Business Profile connection
- Work Boots can use stored provider credentials server-side for read-only GBP calls

Operator action:
- review location status and next-action hints
- reconnect only if advised

### Needs reconnect
Meaning:
- Work Boots cannot safely use current provider credentials

Common causes:
- refresh token missing or revoked
- token refresh failure
- required scope not present
- provider connection was disconnected
- keyring/token decrypt issue after rotation

Operator action:
1. click reconnect/connect in UI
2. complete Google consent flow
3. return and refresh page

### Not connected
Meaning:
- no active GBP connection exists for this business

Operator action:
- click **Connect Google Business Profile** and complete consent

## Location Badge Meanings

### Verified
Meaning:
- verification evidence indicates verified status

Action:
- no action required

### Pending
Meaning:
- verification appears in-progress

Action:
- open **Manage verification** and follow the status action:
  - enter code if prompted
  - otherwise wait for Google to continue processing

### Not verified
Meaning:
- no active verification evidence found

Action:
- open **Manage verification**
- choose an available method
- start verification

### In progress
Meaning:
- Google accepted a verification attempt and additional provider-side processing is underway

Action:
- monitor status in Work Boots
- complete code entry only if prompted by status

### Failed
Meaning:
- the previous verification attempt did not complete successfully

Action:
- open **Manage verification**
- retry with an available method

### Access issue
Meaning:
- Work Boots could not read verification details due to permission/access conditions

Action:
- confirm the connected Google account has access to the GBP location/account
- resolve access in Google UI, then refresh

### Unknown
Meaning:
- verification state is ambiguous or provider responses were not definitive

Action:
- refresh and re-check
- if persistent, validate account access and API enablement

## Next-Action Hint Meanings
- `No action required` -> nothing needed now
- `Verify your business` -> start verification in Google UI
- `Complete verification` -> finish pending verification in Google UI
- `Reconnect Google` -> run connect flow again
- `Resolve access` -> fix account/project permission issues in Google

Current behavior note:
- reconnect is usually shown as connection state (`Needs reconnect`) rather than a location-level next-action value

## What Work Boots Can Do Today
- show GBP connection status per business
- list GBP accounts and locations
- show normalized verification state and next-action hints
- show per-location verification workflow status (`unverified`, `pending`, `in_progress`, `completed`, `failed`, `unknown`)
- list available verification methods for a location
- start, complete, and retry verification attempts (provider-permitted flows)

## What Still Requires Google UI Or Future Work
- broad GBP write/mutation operations beyond verification workflow
- any advanced account remediation still must be done in Google UI

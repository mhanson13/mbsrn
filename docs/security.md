# Security

## Security Model Summary
Work Boots treats security controls as fail-closed by default for production posture.

Key principles:
- authorization is internal (principal/business scoped)
- provider credentials are server-managed and encrypted
- token usability is explicit and deterministic
- missing scope, bad state, and missing key material fail closed

## System Guarantees
These are implementation-level guarantees, not claims that every failure mode is impossible:

- Provider tokens are decrypted only with the row's recorded `token_key_version`.
- Invalid, expired, or otherwise unusable provider tokens fail closed.
- Provider actions are authorized server-side in tenant + business scope.
- OAuth state is short-lived, single-use, and replay-protected.
- Required provider scopes are validated at runtime before provider API calls.
- If any guarantee is not satisfied, requests fail safely and require operator remediation (for example reconnecting the provider).

## Token Encryption Model
Provider OAuth tokens are stored in `provider_connections` as encrypted ciphertext.

Runtime model:
- Active encryption key version from config:
  - `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION`
- Keyring mapping from config:
  - `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`
- Stored per-row key version:
  - `token_key_version`

Behavior:
- Encryption always uses active key version.
- Decryption uses only the row's `token_key_version`.
- If that key version is missing/unavailable, decrypt fails closed.
- No fallback decrypt across other key versions.

## OAuth Hardening

### PKCE Enforcement
GBP connect flow uses PKCE (`S256`):
- generate `code_verifier` at connect start
- send `code_challenge` in auth URL
- store verifier encrypted in one-time state row
- send original verifier during callback token exchange

### OAuth State Replay Protection
State records are:
- short-lived (TTL)
- bound to provider/business/principal context
- single-use
- consumed atomically during callback handling

Reused/expired/invalid state is rejected.

## Runtime Scope Validation
Every GBP token use validates required scopes at runtime.

Required GBP scope:
- `https://www.googleapis.com/auth/business.manage`

If scope is missing:
- token use is blocked
- status is `insufficient_scope`
- reconnect is required

## Lazy Refresh On Use
Before provider API calls:
- load business-scoped connection
- evaluate token status with configurable skew (`GOOGLE_OAUTH_REFRESH_SKEW_SECONDS`)
- refresh synchronously when needed
- persist refreshed token material + metadata

If refresh fails, the connection is treated as reconnect-required.

## Token Usability Contract
Internal connection usability includes:
- `connected`
- `reconnect_required`
- `refresh_token_present`
- `expires_at`
- `granted_scopes`
- `required_scopes_satisfied`
- `token_status`:
  - `usable`
  - `refresh_required`
  - `reconnect_required`
  - `insufficient_scope`

## Fail-Closed Philosophy
Work Boots explicitly fails closed for:
- missing/unusable key versions
- invalid/expired OAuth state
- missing required scopes
- expired/unusable token with no successful refresh
- disconnected or inactive provider connection

## Operational Impact Of Key Loss
If key material for an existing `token_key_version` is lost:
- corresponding provider credentials cannot be decrypted
- token use and rewrap fail for impacted rows
- affected businesses must reconnect to re-establish usable credentials

## High-Level Key Rotation Model
Rotation requires:
1. Add new key version to keyring.
2. Set new active key version.
3. Dry-run token rewrap.
4. Execute token rewrap.
5. Validate counts and token-use health.
6. Remove old key version only after validation window.

Detailed operator procedure: [Token Rotation Runbook](token-rotation.md)

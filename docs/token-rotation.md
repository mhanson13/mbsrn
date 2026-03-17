# Token Rotation Runbook

This runbook rotates Google Business Profile token encryption keys safely.

## Prerequisites
- You have admin access to deployment configuration.
- Existing keyring currently decrypts all active GBP connections.
- New key material is generated and stored securely.
- You understand fail-closed behavior: if a required legacy key is removed too early, affected rows cannot be decrypted.

## Relevant Config
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`

Example keyring during rotation window:

```json
{
  "v2": "new-active-key-material",
  "v1": "legacy-decrypt-key-material"
}
```

## Step 1: Add New Key + Set Active Version
1. Add new key version to `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`.
2. Set `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION` to the new version.
3. Deploy config change.

Encryption behavior after deploy:
- new writes use active key version only
- old rows still decrypt with their stored `token_key_version`

## Step 2: Dry-Run Rewrap (Required)
All businesses:

```bash
python -m app.cli.rewrap_gbp_tokens --dry-run --all
```

Single business:

```bash
python -m app.cli.rewrap_gbp_tokens --dry-run --business-id <BUSINESS_UUID>
```

Optional tenant alias:

```bash
python -m app.cli.rewrap_gbp_tokens --dry-run --tenant-id <TENANT_UUID>
```

Dry-run does not modify DB rows.

## Step 3: Review Dry-Run Summary
Expected output fields:
- `mode`
- `scope`
- `business_id`
- `tenant_id`
- `active_key_version`
- `scanned`
- `eligible`
- `rewrapped`
- `already_current`
- `skipped`
- `failed`
- `failures[]` with operator-safe entries:
  - `connection_id`
  - `reason` (`missing_key_version | decrypt_failed | unexpected_error`)

Security note:
- Summary output must not contain token plaintext or ciphertext.

## Step 4: Execute Rewrap
All businesses:

```bash
python -m app.cli.rewrap_gbp_tokens --all
```

Single business:

```bash
python -m app.cli.rewrap_gbp_tokens --business-id <BUSINESS_UUID>
```

Behavior:
- rewraps only eligible GBP rows not already on active key version
- skips inactive/tombstoned/unusable rows per current connection conventions
- keeps idempotent behavior on repeat runs

## Step 5: Validate Safely
Validate using:
- CLI summary counts (`failed=0` expected)
- application behavior (`/connection`, `/accounts`, `/locations` for representative businesses)
- database checks (if permitted) on `provider_connections.token_key_version`

Do not log token values during validation.

## Step 6: Remove Old Key Version
Only remove legacy key material when all are true:
- dry-run reports no decrypt/key-version failures
- execute run produced expected rewrap counts
- representative GBP token use and refresh calls are healthy

Then:
1. remove legacy version from `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`
2. redeploy config
3. re-run dry-run for confirmation

## Rollback Procedure
If issues occur after key activation:
1. Keep both key versions present in keyring.
2. Set `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY_VERSION` back to prior version.
3. Redeploy config.
4. Dry-run:

```bash
python -m app.cli.rewrap_gbp_tokens --dry-run --all
```

5. If needed, execute rollback rewrap:

```bash
python -m app.cli.rewrap_gbp_tokens --all
```

6. Keep both key versions until validation is clean.

## Fail-Closed Warning
If a row's stored `token_key_version` is missing from keyring:
- decrypt fails
- token use can fail and may require reconnect
- rewrap cannot recover that row without restoring key material

# AI Competitor Profile Generation

## Overview

This feature generates AI competitor profile draft candidates for a site, persists run metadata, and requires explicit operator review before any real competitor entity is created.

It now includes bounded observability for:
- run health (queued/running/completed/failed counts),
- retry lineage behavior,
- normalized failure categories,
- retention cleanup outcomes and last-run visibility.

## Why This Exists

### Problem solved
- AI generation quality and reliability need operational visibility without exposing unsafe internals.
- Retries and failures must be understandable over time.
- Retention cleanup must be auditable (what ran, when, and what was pruned).

### Why this approach was chosen
- Extends the existing SEO competitor generation service/repository/routes instead of introducing a new monitoring platform.
- Preserves current trust and authorization boundaries.
- Uses additive schema changes only (`failure_category` + cleanup execution records) for backward-compatible observability.

## Architecture / Flow

### Generation flow
1. Request:
   - `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs`
2. Processing:
   - Tenant scope is resolved server-side (`TenantContext`, `resolve_tenant_business_id`).
   - Run is queued, then executed asynchronously via background task.
   - Provider output is parsed/validated server-side.
3. Persistence:
   - Run transitions `queued -> running -> completed|failed`.
   - On success: validated drafts persist.
   - On failure: safe `error_summary`, normalized `failure_category`, provider/model/prompt metadata, and bounded raw output persist.
4. Review gating:
   - Drafts remain untrusted until operator edit/accept/reject.
   - Only explicit `accept` creates live competitor records.

### Observability flow
1. Run summary:
   - Service aggregates bounded-window status/failure/retry metrics.
   - Exposed via site-scoped read endpoint.
2. Cleanup outcome:
   - Retention cleanup writes a feature-specific execution record (`completed|failed`, counts, timestamps, safe error summary).
   - Exposed via jobs cleanup-status endpoint.

### Cleanup flow
1. Retention cleanup runs manually (`/api/jobs/.../cleanup`) or via scheduled CLI/CronJob.
2. Service reconciles stale active runs, prunes old raw output, prunes old rejected drafts, and prunes safe old terminal empty runs.
3. Cleanup execution result is persisted for operational visibility.

## API / Interfaces

### Existing generation/review endpoints
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/retry`
- `PATCH /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/reject`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/accept`

### New observability endpoints
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary`
  - bounded lookback summary of run status counts, retry lineage counts, failure category counts, latest timestamps.
- `GET /api/jobs/seo-competitor-profile-generation/cleanup-status`
  - latest cleanup execution and recent success/failure counts for tenant-scoped business/site scope.

### Cleanup endpoint (existing)
- `POST /api/jobs/seo-competitor-profile-generation/cleanup`

## Data Model

### Existing core entities
- `seo_competitor_profile_generation_runs`
- `seo_competitor_profile_drafts`
- live competitor entities (`seo_competitor_sets`, `seo_competitor_domains`) created only on accept

### New/updated observability fields
- `seo_competitor_profile_generation_runs.failure_category` (nullable string)
  - normalized categories:
    - `timeout`
    - `provider_auth`
    - `provider_config`
    - `malformed_output`
    - `schema_validation`
    - `internal_error`
    - `provider_request`
    - `unknown`

### New cleanup outcome table
- `seo_competitor_profile_cleanup_executions`
  - `business_id`, optional `site_id`
  - `status` (`completed|failed`)
  - cleanup counts:
    - `stale_runs_reconciled`
    - `raw_output_pruned_runs`
    - `rejected_drafts_pruned`
    - `runs_pruned`
  - `error_summary` (safe, optional)
  - `started_at`, `completed_at`, `created_at`, `updated_at`

## Key Constraints / Invariants

- AI output is untrusted until validation + operator review.
- Automatic creation of live competitors must never happen.
- Authorization remains tenant/business/site scoped server-side.
- Provider output never directly triggers actions.
- Cleanup must not delete accepted/live competitor entities.
- Cleanup must not delete active queued/running runs.
- Raw provider output and secrets are not exposed through operator-facing observability surfaces.

## Operational Behavior

- Async run execution persists deterministic run lifecycle states.
- Generation execution runs in API `BackgroundTasks`, so provider credentials must exist in the API pod runtime env.
- Failures are normalized to safe summaries and normalized failure categories.
- Retry lineage is preserved via `parent_run_id` and surfaced in summaries.
- Cleanup remains idempotent and now records structured execution outcomes.
- Scheduled retention (Kubernetes CronJob) continues daily cadence; cleanup status endpoint exposes latest outcome and recent success/failure counts.

## Configuration

### AI provider/config
- `AI_PROVIDER_API_KEY` (required secret; no default)
- `AI_PROVIDER_NAME` (default: `openai`)
- `AI_MODEL_NAME` (default: `gpt-4o-mini`)
- `AI_TIMEOUT_VALUE` (default: `30`)
- `AI_PROMPT_TEXT_RECOMMENDATION` (default: empty)
- `OPENAI_API_BASE_URL` (default: `https://api.openai.com/v1`)

Deployment/runtime notes:
- API runtime must inject `AI_PROVIDER_API_KEY` into API pods for provider-backed generation.
- `deploy-prod` wires AI settings via Kubernetes secret `mbsrn-api-auth` and API deployment env refs.
- `deploy-gke` expects `AI_PROVIDER_API_KEY` in Kubernetes secret `work-boots-ai-provider` and uses ConfigMap defaults for non-secret AI vars.
- Non-secret AI values remain deployment-configurable runtime env with safe defaults above.

### Retention/config
- `SEO_COMPETITOR_PROFILE_RAW_OUTPUT_RETENTION_DAYS` (default: `30`)
- `SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS` (default: `180`)
- `SEO_COMPETITOR_PROFILE_REJECTED_DRAFT_RETENTION_DAYS` (default: `90`)

### Infrastructure/runtime
- `DATABASE_URL` (API/CLI/CronJob DB access)

## Failure Modes

- Provider timeout/auth/config/output errors:
  - run marked `failed`,
  - safe `error_summary` returned to operator surfaces,
  - normalized `failure_category` stored for observability.
- Provider misconfiguration (missing API credentials):
  - provider resolves to misconfigured mode,
  - operators see safe message: `AI provider credentials are not configured for competitor profile generation.`,
  - no drafts are persisted.
- Validation/parsing/internal failures:
  - run marked `failed`, no unvalidated draft persistence.
- Cleanup failure:
  - API/CLI returns safe failure behavior,
  - cleanup execution record stores `failed` status and safe error summary.

Operator-visible behavior remains safe and non-diagnostic (no stack traces, no raw provider internals).

## Security Considerations

- Tenant isolation is preserved in summary and cleanup-status endpoints via existing tenant resolution.
- Raw provider output remains backend-only diagnostic data.
- Secrets (API keys, credential material) are not persisted in observability payloads and not exposed in API responses.
- AI provider credentials should be injected only into workloads executing provider calls (API pods), not broadly into unrelated workloads.
- Failure categories are normalized labels, not raw internal exception traces.

## Future Extensions

- Optional admin/global rollups across businesses (if broader admin auth surface is standardized).
- Optional integration with a broader metrics backend if the platform adopts one.
- Optional longer-term cleanup execution history retention controls.

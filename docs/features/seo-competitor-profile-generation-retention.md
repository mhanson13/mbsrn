# SEO Competitor Profile Generation and Retention Cleanup

## 1) Overview

This feature provides AI-assisted competitor profile draft generation for a site, followed by strict human review before any real competitor record is created.  
It also enforces bounded data retention for generation runs/drafts/raw model output through manual and scheduled cleanup paths.

Core outcomes:
- AI generates untrusted draft candidates.
- Operators explicitly edit/accept/reject drafts.
- Only explicit accept creates live competitor entities.
- Retention cleanup prunes stale diagnostic data and rejected transient artifacts.

## 2) Why This Exists

### Problem solved
- Generation runs and raw model output can grow without bound.
- Rejected drafts and empty terminal runs create long-term storage and governance risk.
- Manual-only cleanup is not reliable for production operations.

### Why this approach was chosen
- Reuses the existing service/repository/job stack instead of introducing a new scheduler framework.
- Preserves trust boundaries and tenant authorization semantics already enforced in API/service layers.
- Uses conservative pruning rules (content-first pruning, selective run deletion) to preserve auditability.
- Uses Kubernetes CronJob (daily cadence) because Kubernetes deployment manifests are already the operational deployment pattern in this repo.

## 3) Architecture / Flow

### A. Generation and review flow (existing)
1. Request:
   - `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs`
2. Processing:
   - Route resolves tenant scope via `TenantContext` and `resolve_tenant_business_id`.
   - Service creates a `queued` run.
   - Background task executes provider call asynchronously (`generation_run_executor`).
3. Persistence:
   - Run transitions: `queued -> running -> completed|failed`.
   - On success: validated drafts are persisted.
   - On failure: safe `error_summary` + metadata are persisted; no drafts are created.
4. UI/API read path:
   - Site workspace reads run list/detail and draft statuses.
   - Operator performs edit/reject/accept actions via dedicated endpoints.

### B. Review-gated acceptance flow (existing)
1. Operator accepts a draft (`/drafts/{draft_id}/accept`).
2. Service validates scope + payload and creates/links real competitor domain/set records.
3. Draft is marked accepted with `accepted_competitor_set_id` / `accepted_competitor_domain_id`.

### C. Retention cleanup flow (manual + scheduled)
1. Cleanup logic:
   - `SEOCompetitorProfileGenerationService.cleanup_retention(...)`
2. Manual job endpoint:
   - `POST /api/jobs/seo-competitor-profile-generation/cleanup` (tenant-scoped)
3. Scheduled operational path:
   - `python -m app.cli.seo_competitor_profile_generation_retention_cleanup`
   - Global sweep across all businesses by default, optional `--business-id` and `--site-id`.
4. Scheduling:
   - Kubernetes CronJob runs daily (`0 3 * * *`, UTC), `concurrencyPolicy: Forbid`.

### Async behavior
- Generation execution is asynchronous via FastAPI background tasks.
- Cleanup is asynchronous at operations level via Kubernetes CronJob (out-of-band from operator UI/API).
- Stale queued/running runs are reconciled during list/detail and cleanup operations.

## 4) Data Model

### Primary entities
- `seo_competitor_profile_generation_runs`
- `seo_competitor_profile_drafts`
- live competitor entities (`seo_competitor_sets`, `seo_competitor_domains`) linked on accept

### Important run fields
- `status` (`queued|running|completed|failed`)
- `parent_run_id` (retry lineage)
- `requested_candidate_count`, `generated_draft_count`
- `provider_name`, `model_name`, `prompt_version`
- `raw_output` (bounded diagnostic payload; pruned by retention)
- `error_summary` (safe operator-visible failure summary)
- `completed_at`, `created_at`, `updated_at`

### Important draft fields
- `review_status` (`pending|edited|accepted|rejected`)
- `suggested_name`, `suggested_domain`, `competitor_type`
- `summary`, `why_competitor`, `evidence`, `confidence_score`
- `accepted_competitor_set_id`, `accepted_competitor_domain_id` (lineage to live entities)
- `reviewed_by_principal_id`, `reviewed_at`

## 5) Key Constraints / Invariants

- AI output is untrusted until server-side validation + operator review.
- Live competitor creation must never happen automatically.
- Tenant/business/site scoping is enforced server-side for API paths.
- Cleanup must never delete accepted live competitor entities.
- Cleanup must never delete active `queued`/`running` runs.
- Cleanup preserves audit-intelligible run metadata (provider/model/prompt/status/timestamps/lineage).
- Raw provider output is internal diagnostic data; it is not exposed directly in operator UI.

## 6) Operational Behavior

### Retries and failures
- Only failed runs are retryable; retry creates a new queued child run.
- Provider/runtime failures are normalized to safe run `error_summary` values.
- Invalid/partial model output causes run failure and no draft persistence.

### Cleanup behavior
- Reconciles stale active runs:
  - old `queued` -> `failed`
  - old `running` -> `failed`
- Prunes old `raw_output` from terminal runs.
- Deletes old rejected drafts not linked to accepted entities.
- Deletes old terminal runs only when they are safe to remove (no drafts and not lineage-critical).
- Cleanup is idempotent and safe to run repeatedly.

### Scheduling behavior
- Daily cron execution via Kubernetes CronJob.
- `concurrencyPolicy: Forbid` prevents overlapping cleanup executions.
- Job history is bounded via success/failure history limits.
- CLI logs start, completion, per-business failure, and aggregated cleanup counts.

## 7) Configuration

### AI generation settings
- `AI_PROVIDER_API_KEY` (required for `openai`; no default)
- `AI_PROVIDER_NAME` (default: `openai`)
- `AI_MODEL_NAME` (default: `gpt-4o-mini`)
- `AI_TIMEOUT_VALUE` (default: `30`, seconds)
- `AI_PROMPT_TEXT_COMPETITOR` (default: empty string)
- `AI_PROMPT_TEXT_RECOMMENDATIONS` (default: empty string; used by recommendation narratives)
- `AI_PROMPT_TEXT_RECOMMENDATION` (deprecated legacy fallback when split vars are unset/blank; default: empty string)
- `OPENAI_API_BASE_URL` (default: `https://api.openai.com/v1`)

### Retention settings
- `SEO_COMPETITOR_PROFILE_RAW_OUTPUT_RETENTION_DAYS` (default: `30`)
- `SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS` (default: `180`)
- `SEO_COMPETITOR_PROFILE_REJECTED_DRAFT_RETENTION_DAYS` (default: `90`)

### Runtime settings for operational cleanup
- `DATABASE_URL` (required for API service/CLI/CronJob DB access)

### Cadence
- Cron schedule is currently manifest-defined as daily at `03:00 UTC` (`0 3 * * *`).

## 8) Failure Modes

### Generation failures
- Timeout/provider auth/invalid output/internal errors set run `status=failed` with safe `error_summary`.
- Operators see safe failure text in run detail/list APIs; no stack traces are returned.

### Cleanup failures
- Manual endpoint returns safe `404`/`422` for scope/validation failures.
- Global CLI sweep continues per business; failures are captured in `failures[]` and logged.
- CLI exits non-zero if any business cleanup fails.
- CronJob failure is visible via Kubernetes Job/CronJob status and pod logs.

### Expected operator impact
- Operators may see fewer old rejected drafts and missing old raw diagnostic output after retention thresholds.
- Latest active review workflow remains intact.

## 9) Future Extensions

- Add provider-specific adapters beyond OpenAI behind the existing provider abstraction.
- Add explicit retention cleanup run audit table if stronger historical job auditing is required.
- Add sharded/parallel cleanup execution for very large business counts.
- Make cron cadence configurable via deployment variables if operational policy requires environment-specific schedules.

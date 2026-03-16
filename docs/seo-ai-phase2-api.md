# SEO.ai Phase 2 API (Competitor Intelligence)

Status: Draft  
Owner: Work Boots  
Scope: API design for Phase 2 only

---

## 1. API Design Constraints

- Preserve existing monolith + business-scoped endpoint style.
- Route prefix pattern remains:
  - `/api/businesses/{business_id}/seo/...`
- Tenant scope is server-derived from `TenantContext`; requested `business_id` is validated.
- Deterministic-first:
  - Snapshot/comparison endpoints are deterministic.
  - AI is only for summary endpoints.

---

## 2. Endpoint Families

## 2.1 Competitor Sets

### `GET /api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets`
List competitor sets for a site.

Response:
- `items[]`: set records
- `total`

### `POST /api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets`
Create a competitor set.

Request:
- `name` (required)
- `city` optional
- `state` optional
- `is_active` optional

### `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}`
Get one competitor set.

### `PATCH /api/businesses/{business_id}/seo/competitor-sets/{set_id}`
Partial update for set metadata or active flag.

Out of scope:
- destructive hard-delete endpoint

---

## 2.2 Competitor Domains (Manual)

### `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains`
List domains in a set.

### `POST /api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains`
Add a manual competitor domain.

Request:
- `domain` or `base_url` (required)
- `display_name` optional
- `notes` optional
- `is_active` optional

Validation:
- `http|https` only
- normalized domain uniqueness within set

### `PATCH /api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains/{domain_id}`
Partial update for metadata/active state.

Out of scope:
- automatic competitor discovery

---

## 2.3 Snapshot Runs

### `POST /api/businesses/{business_id}/seo/competitor-sets/{set_id}/snapshot-runs`
Start a snapshot run.

Request:
- `max_domains` default bounded
- `max_pages_per_domain` default bounded
- `max_depth` default bounded

Behavior:
- snapshots homepage first
- captures bounded internal pages per competitor domain
- stores deterministic page features only

### `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}/snapshot-runs`
List snapshot runs for a set.

### `GET /api/businesses/{business_id}/seo/snapshot-runs/{run_id}`
Get run status/diagnostics.

### `GET /api/businesses/{business_id}/seo/snapshot-runs/{run_id}/pages`
List captured snapshot pages for a run.

Out of scope:
- background worker orchestration (phase may run synchronously first)

---

## 2.4 Deterministic Comparison Runs

### `POST /api/businesses/{business_id}/seo/competitor-sets/{set_id}/comparison-runs`
Start deterministic comparison for a completed snapshot run.

Request:
- `snapshot_run_id` (required)

### `GET /api/businesses/{business_id}/seo/competitor-sets/{set_id}/comparison-runs`
List comparison runs.

### `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}`
Get comparison run summary/status.

### `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/findings`
List deterministic comparison findings.

Response includes:
- `items[]`
- `total`
- `by_category`
- `by_severity`

Out of scope:
- AI-generated finding creation

---

## 2.5 AI Competitor Gap Summaries (Manual Trigger)

### `POST /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summarize`
Generate AI summary for completed comparison run.

Rules:
- run must be `completed`
- summary must be grounded in stored deterministic comparison outputs only
  - persisted comparison findings
  - persisted comparison run rollups
- failures persist as failed summary records without invalidating comparison run

### `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries`
List summary history by version.

### `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries/latest`
Get latest summary snapshot.

### `GET /api/businesses/{business_id}/seo/comparison-summaries/{summary_id}`
Get one summary version by summary id.

Out of scope:
- recommendation/content generation endpoints

---

## 3. Response Shapes (Minimum)

## 3.1 Comparison finding
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `comparison_run_id`
- `finding_type`
- `category`
- `severity`
- `title`
- `details`
- `client_value` nullable
- `competitor_value` nullable
- `gap_direction` nullable
- `evidence_json` nullable
- `created_at`

## 3.2 Comparison run summary
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `status`
- `total_findings`
- `critical_findings`
- `warning_findings`
- `info_findings`
- `duration_ms` nullable
- `error_summary` nullable

## 3.3 Gap summary
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `comparison_run_id`
- `version`
- `status`
- `overall_gap_summary`
- `top_gaps_json`
- `plain_english_explanation`
- `provider_name`
- `model_name`
- `prompt_version`
- `error_summary` nullable
- `created_by_principal_id` nullable
- `created_at`
- `updated_at`

---

## 4. Status Codes

- `200` for reads
- `201` for create/run/summarize actions
- `404` for not found or cross-business scope mismatch
- `422` for validation or state violations (e.g., summarize before run completion)

---

## 5. Security and Scoping Rules

- Business scope must be enforced on all endpoints.
- Do not trust client-supplied cross-tenant identifiers.
- Snapshot fetch logic must continue to enforce SSRF protections.
- Do not expose secrets in snapshot/comparison/summary responses.

---

## 6. Explicit Out of Scope (API)

- SERP scraping endpoints
- rank history endpoints
- backlink endpoints
- content generation endpoints
- publishing endpoints

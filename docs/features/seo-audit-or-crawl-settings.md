# SEO Audit Crawl Settings

## Overview

This feature adds a business-scoped, admin-controlled crawl page limit for SEO audits.
The setting controls how many pages an audit crawl is allowed to scan for both manual audits and automation-triggered audits.

## Why This Exists

- The previous default (`25`) was effectively hardcoded in execution paths.
- Businesses need safe control over crawl depth to balance:
  - runtime/cost,
  - crawl coverage,
  - operational consistency across manual and automated runs.
- A DB-backed admin setting was chosen so changes are immediate, tenant-scoped, auditable via existing business settings APIs, and not tied to deploy-time env changes.

## Data Model / Config

### Storage
- Table: `businesses`
- Field: `seo_audit_crawl_max_pages` (`int`, non-null, default `25`)
- Constraint: `5 <= seo_audit_crawl_max_pages <= 250`

### API surface
- Read: `GET /api/businesses/{business_id}`
- Update (admin-only): `PATCH /api/businesses/{business_id}/settings`
- Schema field: `seo_audit_crawl_max_pages`

## Authorization

- Backend remains source of truth.
- Only admin principals can update the setting (`require_credential_manager_principal`).
- Tenant/business scoping is enforced via `TenantContext` + `resolve_tenant_business_id`.

## Operator UI Surface

- Canonical admin route: `/admin`
- Backward-compatible route: `/users` (compatibility alias for existing bookmarks)
- The crawl limit control lives on the Admin page under **SEO Crawl Settings**.

## Related Admin Tuning (AI Competitor Quality)

The same business settings surface also contains bounded AI competitor candidate-quality tuning controls:
- `competitor_candidate_min_relevance_score` (`0..100`, default `35`)
- `competitor_candidate_big_box_penalty` (`0..50`, default `20`)
- `competitor_candidate_directory_penalty` (`0..50`, default `35`)
- `competitor_candidate_local_alignment_bonus` (`0..50`, default `10`)

These settings are business-scoped and admin-only, and are enforced server-side in competitor candidate scoring/exclusion logic. They do not change review gating.

Manual apply path from Site Workspace:
- AI tuning suggestions surfaced in workspace can be manually applied with explicit operator confirmation.
- Apply uses the same canonical endpoint: `PATCH /api/businesses/{business_id}/settings`.
- The workspace sends only targeted tuning fields, optionally with `competitor_tuning_preview_event_id` for preview attribution.
- Backend bounds validation remains authoritative; no automatic settings mutation occurs.

## Runtime Usage

### Manual audit path
- `SEOAuditService.run_audit(...)` resolves effective crawl page limit from the business setting.
- The resolved value is used for crawler execution and persisted on:
  - `seo_audit_runs.max_pages` (legacy field)
  - `seo_audit_runs.crawl_max_pages_used` (explicit observability field)

### Automation path
- `SEOAutomationService` audit step calls `SEOAuditService.run_audit(...)`.
- Automation therefore uses the same business setting automatically (no separate override path).

## Defaults / Bounds

- Default: `25`
- Minimum: `5`
- Maximum: `250`
- If a business does not explicitly update the setting, audits continue using the default value.
- Runtime guard: values outside `5..250` are rejected as invalid configuration.

## Backward Compatibility

- `SEOAuditRunCreateRequest.max_pages` remains in the API payload for compatibility.
- It is deprecated and ignored at runtime.
- Crawl page limit is business-controlled only; per-run overrides are not applied.

## Operational Considerations

- Higher values increase crawl duration and potential load but can improve coverage depth.
- Lower values reduce runtime/cost and can be useful for rapid iteration.
- Because the setting is business-scoped, each tenant can tune crawl depth to its own operational constraints without affecting others.

## Admin Settings Health Indicators

- The Admin page evaluates persisted business settings and shows section-level health warnings when saved values are outside allowed bounds or violate channel requirements.
- Current indicators cover:
  - SEO Crawl Settings
  - AI Competitor Candidate Quality
  - Notification settings channel health
- Warnings are informational only and do not block unrelated section saves.
- Backend validation remains authoritative for all bounds and consistency rules when a section is edited.

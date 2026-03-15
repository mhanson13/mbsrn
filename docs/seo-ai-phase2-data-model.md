# SEO.ai Phase 2 Data Model

Status: Draft  
Owner: Work Boots  
Scope: Competitor intelligence storage for Phase 2 only

---

## 1. Model Principles

- Business-scoped by default: every Phase 2 table includes `business_id`.
- Tenant integrity: repositories and services enforce business scoping.
- Deterministic-first storage: raw snapshot metrics and deterministic gap findings are persisted separately from AI summaries.
- No Phase 3+ entities in this phase.

---

## 2. Proposed Tables

## 2.1 `seo_competitor_sets`

Purpose: group manual competitor domains for a specific client site.

Minimum fields:
- `id` (uuid/string)
- `business_id` (fk -> businesses.id)
- `site_id` (fk -> seo_sites.id)
- `name`
- `city` nullable
- `state` nullable
- `is_active`
- `created_by_principal_id` nullable
- `created_at`
- `updated_at`

Indexes:
- `(business_id, site_id, is_active)`
- `(business_id, created_at)`

---

## 2.2 `seo_competitor_domains`

Purpose: store competitor domains in a set.

Minimum fields:
- `id`
- `business_id` (fk)
- `site_id` (fk)
- `competitor_set_id` (fk -> seo_competitor_sets.id)
- `domain` (normalized host/domain)
- `base_url`
- `display_name` nullable
- `source` (phase 2 default: `manual`)
- `is_active`
- `notes` nullable
- `created_at`
- `updated_at`

Constraints:
- unique per set for active domain identity: `(business_id, competitor_set_id, domain)`

Indexes:
- `(business_id, competitor_set_id, is_active)`
- `(business_id, site_id)`

---

## 2.3 `seo_competitor_snapshot_runs`

Purpose: track lifecycle and diagnostics for snapshot collection.

Minimum fields:
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `status` (`queued|running|completed|failed`)
- `max_domains`
- `max_pages_per_domain`
- `same_domain_only`
- `domains_targeted`
- `domains_completed`
- `pages_attempted`
- `pages_captured`
- `pages_skipped`
- `errors_encountered`
- `started_at` nullable
- `completed_at` nullable
- `duration_ms` nullable
- `error_summary` nullable
- `created_by_principal_id` nullable
- `created_at`
- `updated_at`

Indexes:
- `(business_id, competitor_set_id, created_at desc)`
- `(business_id, status)`

---

## 2.4 `seo_competitor_snapshot_pages`

Purpose: persist captured page snapshot features per competitor domain/run.

Minimum fields:
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `snapshot_run_id` (fk -> seo_competitor_snapshot_runs.id)
- `competitor_domain_id` (fk -> seo_competitor_domains.id)
- `url`
- `status_code`
- `title` nullable
- `meta_description` nullable
- `canonical_url` nullable
- `h1_json` nullable
- `h2_json` nullable
- `word_count` nullable
- `internal_link_count` nullable
- `detected_page_type` nullable (`home|service|faq|process|about|contact|reviews|other`)
- `fetched_at`
- `created_at`
- `updated_at`

Constraints:
- unique within a run/domain for normalized URL: `(business_id, snapshot_run_id, competitor_domain_id, url)`

Indexes:
- `(business_id, snapshot_run_id)`
- `(business_id, competitor_domain_id)`
- `(business_id, detected_page_type)`

---

## 2.5 `seo_competitor_comparison_runs`

Purpose: track deterministic comparison execution and summary stats.

Minimum fields:
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `snapshot_run_id`
- `status` (`queued|running|completed|failed`)
- `total_findings`
- `critical_findings`
- `warning_findings`
- `info_findings`
- `started_at` nullable
- `completed_at` nullable
- `duration_ms` nullable
- `error_summary` nullable
- `created_by_principal_id` nullable
- `created_at`
- `updated_at`

Indexes:
- `(business_id, competitor_set_id, created_at desc)`
- `(business_id, snapshot_run_id)`

---

## 2.6 `seo_competitor_comparison_findings`

Purpose: deterministic competitor gap findings.

Minimum fields:
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `comparison_run_id`
- `finding_type`
- `category` (`SEO|CONTENT|STRUCTURE|TECHNICAL`)
- `severity` (`INFO|WARNING|CRITICAL`)
- `title`
- `details`
- `rule_key`
- `client_value` nullable (string/JSON)
- `competitor_value` nullable (string/JSON)
- `gap_direction` nullable (`client_trails|client_leads|parity`)
- `evidence_json` nullable
- `created_at`
- `updated_at`

Indexes:
- `(business_id, comparison_run_id, created_at)`
- `(business_id, category)`
- `(business_id, severity)`
- `(business_id, finding_type)`

---

## 2.7 `seo_competitor_gap_summaries`

Purpose: AI summaries for completed comparison runs (versioned).

Minimum fields:
- `id`
- `business_id`
- `site_id`
- `competitor_set_id`
- `comparison_run_id`
- `version`
- `status` (`completed|failed`)
- `overall_gap_summary` nullable
- `top_opportunities_json` nullable
- `plain_english_explanation` nullable
- `model_name`
- `prompt_version`
- `error_summary` nullable
- `created_by_principal_id` nullable
- `created_at`
- `updated_at`

Constraints:
- unique `(business_id, comparison_run_id, version)`

Indexes:
- `(business_id, comparison_run_id)`
- `(business_id, competitor_set_id, created_at desc)`

---

## 3. Relationship Map

- `seo_sites 1 -> many seo_competitor_sets`
- `seo_competitor_sets 1 -> many seo_competitor_domains`
- `seo_competitor_sets 1 -> many seo_competitor_snapshot_runs`
- `seo_competitor_snapshot_runs 1 -> many seo_competitor_snapshot_pages`
- `seo_competitor_snapshot_runs 1 -> many seo_competitor_comparison_runs`
- `seo_competitor_comparison_runs 1 -> many seo_competitor_comparison_findings`
- `seo_competitor_comparison_runs 1 -> many seo_competitor_gap_summaries`

All child rows include `business_id` and must match parent business ownership.

---

## 4. Tenant Integrity Requirements

- Repository insert guards must verify parent/child business and site matches.
- Cross-business reads must return empty/not found.
- Route layer must continue using `TenantContext` and `resolve_tenant_business_id`.
- Model design should allow future DB-level composite tenant constraints where practical.

---

## 5. Explicit Out of Scope (Data Model)

- No SERP ranking tables
- No backlink graph tables
- No content generation asset tables for this phase
- No queue/job orchestration tables


# SEO.ai Phase 3C Data Model

## New Table
## `seo_recommendation_narratives`
Purpose:
- stores versioned AI narrative outputs for deterministic recommendation runs
- keeps narrative generation separate from recommendation generation records

Core fields:
- `id`
- `business_id`
- `site_id`
- `recommendation_run_id`
- `version`
- `status` (`completed` | `failed`)
- `narrative_text`
- `top_themes_json`
- `sections_json`
- `provider_name`
- `model_name`
- `prompt_version`
- `error_message`
- `created_by_principal_id`
- `created_at`
- `updated_at`

Integrity:
- unique version per run:
  - `(business_id, recommendation_run_id, version)`
- check constraint for status values
- FK lineage to `businesses`, `seo_sites`, and `seo_recommendation_runs`

Indexes:
- business/run/versioned retrieval
- business/site timeline retrieval
- business/status filtering

Migration:
- Alembic revision `0021_seo_recommendation_narratives`

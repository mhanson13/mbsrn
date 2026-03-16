# SEO.ai Phase 4 Data Model

## New Tables

## `seo_automation_configs`
Business/site-scoped automation configuration.

Key fields:
- `id`
- `business_id`
- `site_id`
- `is_enabled`
- `cadence_type` (`manual` | `interval_minutes`)
- `cadence_minutes` (required when cadence is interval)
- trigger flags:
  - `trigger_audit`
  - `trigger_audit_summary`
  - `trigger_competitor_snapshot`
  - `trigger_comparison`
  - `trigger_competitor_summary`
  - `trigger_recommendations`
  - `trigger_recommendation_narrative`
- `last_run_at`
- `next_run_at`
- `last_status`
- `last_error_message`
- `created_at`
- `updated_at`

Constraints and indexes:
- unique config per business/site
- cadence and cadence-minutes check constraints
- `last_status` check constraint
- indexes for business/site lookup and due-run scanning

## `seo_automation_runs`
Persisted execution history for manual and scheduled automation runs.

Key fields:
- `id`
- `business_id`
- `site_id`
- `automation_config_id`
- `trigger_source` (`manual` | `scheduled`)
- `status` (`queued` | `running` | `completed` | `failed` | `skipped`)
- `started_at`
- `finished_at`
- `error_message`
- `steps_json` (step-level status and lineage)
- `created_at`
- `updated_at`

Constraints and indexes:
- trigger-source and status check constraints
- indexes for business/site history, status filtering, and config/run lineage

## Step Tracking Shape (`steps_json`)
Each run stores a deterministic step list with records shaped as:
- `step_name`
- `status`
- `started_at`
- `finished_at`
- `linked_output_id`
- `error_message`

Step names:
- `audit_run`
- `audit_summary`
- `competitor_snapshot_run`
- `comparison_run`
- `competitor_summary`
- `recommendation_run`
- `recommendation_narrative`

## Multi-Tenant Guarantees
- both tables are business-scoped and site-scoped
- automation run creation enforces config/business/site lineage
- route/service boundaries reject cross-business and cross-site access

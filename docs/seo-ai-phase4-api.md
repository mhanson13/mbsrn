# SEO.ai Phase 4 API

## Business-Scoped Automation Config Endpoints

Base path:
- `/api/businesses/{business_id}/seo/sites/{site_id}`
- compatibility path: `/api/v1/businesses/{business_id}/seo/sites/{site_id}`

Config management:
- `POST /automation-config`
  - create or replace site automation config
- `GET /automation-config`
  - get current site automation config
- `PATCH /automation-config`
  - patch config fields
- `POST /automation-config/enable`
  - enable config
- `POST /automation-config/disable`
  - disable config

Run management:
- `POST /automation-runs`
  - manual trigger for one site config
- `GET /automation-runs`
  - list run history for the site
- `GET /automation-runs/{automation_run_id}`
  - get one run with step-level status

Operational status:
- `GET /automation-status`
  - returns current config + latest run snapshot

## Scheduler-Ready Operational Endpoint

Job trigger:
- `POST /api/jobs/seo-automation/run-due`

Request:
- optional `business_id`
- `limit` (default 25)

Behavior:
- scans due configs (`is_enabled=true` and `next_run_at <= now`)
- triggers scheduled runs
- returns counts for scanned configs, triggered runs, active-run skips, and trigger failures

## Contract Notes
- all SEO automation endpoints are tenant-scoped through `TenantContext`
- route handlers stay thin and delegate to service/repository layers
- run/step status values are explicit and stable
- output lineage is surfaced through `linked_output_id` in `steps_json`

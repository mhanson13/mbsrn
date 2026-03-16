# SEO.ai Phase 2E Summary Contract Hardening

## What was hardened

- Competitor summary API contract is now treated as a stable, explicit shape across:
  - summary list (`GET /comparison-runs/{run_id}/summaries`)
  - latest summary (`GET /comparison-runs/{run_id}/summaries/latest`)
  - summary by id (`GET /comparison-summaries/{summary_id}`)
- Summary records expose explicit traceability fields:
  - `comparison_run_id`
  - `version`
  - `status` (`completed` or `failed`)
  - `provider_name`
  - `model_name`
  - `prompt_version`
  - `created_at` / `updated_at`
  - `error_summary` for failed attempts
- Added persistent provider metadata (`provider_name`) on summary records.

## Grounding guarantees

Competitor summaries are generated from persisted deterministic comparison outputs only:

- `seo_competitor_comparison_findings`
- `seo_competitor_comparison_runs` rollup fields (`metric_rollups_json`, type/category/severity counts)

The summary service does not query crawler/raw snapshot page data to build AI inputs.

## Failure isolation and version semantics

- Summary failures are persisted as separate summary versions with `status="failed"` and `error_summary`.
- Failed attempts do not mutate deterministic comparison findings or rollups.
- Repeated manual attempts increment versions predictably.
- Latest-summary retrieval returns the highest persisted version.

## Test coverage added

- Response contract stability checks (key set and status semantics).
- Version ordering checks on summary list responses.
- Latest-summary semantics checks after mixed success/failure attempts.
- Grounding checks proving provider inputs come from persisted comparison records.
- Cross-tenant access rejection checks for trigger and retrieval endpoints.

## Intentionally deferred

- Recommendation generation
- strategic advice workflows
- weighted scoring/ranking heuristics
- automatic summary execution
- background workers

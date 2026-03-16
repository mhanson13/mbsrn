# SEO.ai Phase 2D Manual Competitor Summaries

## What was added

- Manual-trigger AI summary capability for competitor comparison runs:
  - `POST /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summarize`
- Business-scoped summary persistence in `seo_competitor_comparison_summaries` with:
  - run lineage (`comparison_run_id`)
  - status (`completed` / `failed`)
  - version history per run
  - provider metadata (`model_name`, `prompt_version`)
  - summary content (`overall_gap_summary`, `top_gaps_json`, `plain_english_explanation`)
  - failure details (`error_summary`)
- Retrieval endpoints:
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries`
  - `GET /api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries/latest`
  - `GET /api/businesses/{business_id}/seo/comparison-summaries/{summary_id}`

## Data-source boundary

Competitor summaries are generated only from persisted deterministic comparison outputs:

- `seo_competitor_comparison_runs` rollup fields (`metric_rollups_json`, category/severity/type counts)
- `seo_competitor_comparison_findings`

No crawl reprocessing, no new finding generation, and no recommendation engine behavior is introduced.

## Failure isolation

- Summary generation failures do not modify comparison findings or run rollups.
- Failed attempts are persisted as separate summary versions with `status="failed"` and `error_summary`.
- Repeated manual attempts remain traceable through versioned summary records.

## Intentionally deferred

- Automatic summary execution on comparison run completion
- Recommendation or strategy generation
- Weighted ranking or heuristic scoring layers
- Background worker orchestration

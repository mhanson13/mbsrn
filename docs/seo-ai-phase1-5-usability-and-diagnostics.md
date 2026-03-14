# SEO.ai Phase 1.5 Usability and Diagnostics

This document captures the incremental Phase 1.5 improvements applied to the baseline SEO audit engine.

## Scope

Phase 1.5 stays inside Phase 1 capabilities:

- deterministic crawl and finding generation
- deterministic run summaries and health scoring
- structured API output for findings and run summary
- deterministic JSON report export

Out of scope:

- competitor analysis
- recommendations
- content generation
- keyword or backlink tooling
- queue/worker infrastructure

## Finding Classification

Findings now use normalized classification values:

- categories: `SEO`, `CONTENT`, `STRUCTURE`, `TECHNICAL`
- severity levels: `INFO`, `WARNING`, `CRITICAL`

The classification is deterministic and set by rule definitions in `seo_finding_rules.py`.

## Audit Run Summary Metrics

Run summary output includes:

- `total_pages`
- `total_findings`
- `critical_findings`
- `warning_findings`
- `info_findings`
- `crawl_duration`

These are computed from stored run/pages/findings data and exposed through API summary/report responses.

## Deterministic Health Score

A deterministic score is computed from finding types:

- base score: `100`
- penalties applied for key issues:
  - missing title
  - missing meta description
  - duplicate title
  - duplicate meta description
  - thin content
  - missing canonical
  - missing H1

Score output is clamped to `0..100`.

## API Additions

Business-scoped endpoints:

- `GET /api/businesses/{business_id}/seo/audit-runs/{run_id}/summary`
- `GET /api/businesses/{business_id}/seo/audit-runs/{run_id}/report`

Existing findings endpoint now includes aggregation blocks:

- `by_category`
- `by_severity`

## Deterministic Report Export

Report endpoint returns JSON containing:

- site information
- audit summary metadata
- finding summary counts
- full finding list
- health score

No PDF/export file generation is included.

## Crawl Efficiency Improvements

Crawler behavior remains bounded and deterministic with:

- bounded parallel fetch (`max_workers`)
- queue prioritization by shallow path first
- stronger URL deduplication normalization
- tracking query parameter filtering for dedupe stability (`utm_*`, `gclid`, `fbclid`, `msclkid`)

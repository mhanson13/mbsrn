# SEO.ai Phase 1 Audit Hardening

This document captures the current Phase 1 crawl/audit hardening behavior implemented in Work Boots Console.

## Workflow

1. `POST /api/businesses/{business_id}/seo/sites/{site_id}/audit-runs` creates a run.
2. Run transitions: `queued -> running -> completed|failed`.
3. The crawler performs a bounded, same-domain crawl from the site base URL.
4. Extracted page data is persisted in `seo_audit_pages`.
5. Deterministic findings are generated and persisted in `seo_audit_findings`.
6. Run diagnostics are stored on `seo_audit_runs`.

## Crawler Behavior

The crawler is intentionally conservative for Phase 1:

- HTTP/HTTPS only
- same-domain only during audit runs
- bounded by `max_pages` and `max_depth`
- request timeout defaults
- retry on transient network and upstream failures
- redirect limit enforcement
- response-size limit enforcement
- redirect target validation (SSRF checks still apply after redirect)
- HTML parsing safety: extraction failures are captured and do not crash the run

## URL Normalization Rules

Normalization is deterministic and used for deduplication:

- lowercases scheme and host
- strips fragments
- collapses repeated slashes in paths
- trims trailing slash (except root path)
- normalizes default index paths (`/index.html`, `/index.htm`, `/index.php`, `/default.aspx`) to `/`
- deduplicates repeated query key/value pairs and sorts query params
- applies base-scheme preference (`http`/`https`) for same-host links during same-domain crawls

## Deterministic Finding Rules

Phase 1 findings are rules-based only (no AI findings):

- missing title
- duplicate title
- title too short
- title too long
- missing meta description
- duplicate meta description
- meta description too short
- meta description too long
- missing H1
- multiple H1
- missing H2
- missing canonical
- thin content
- extremely thin content
- missing internal links
- broken internal links

## Audit Diagnostics and Observability

`SEOAuditRun` now tracks run diagnostics used by API responses and logs:

- `pages_discovered`
- `pages_crawled`
- `pages_skipped`
- `errors_encountered`
- `duplicate_urls_skipped`
- `crawl_duration_ms`

Run logs include:

- `business_id`
- `site_id`
- `audit_run_id`
- lifecycle transitions (start/completed/failed)
- page/error context for crawl and extraction failures

## Scope Boundary

This hardening pass does not add Phase 2+ capabilities. It keeps Phase 1 limited to:

- site registration
- deterministic crawl/extraction/findings
- manual AI summary generation on completed runs

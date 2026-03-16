# SEO.ai Phase 1 Hardening and Activation Summary

## What Changed
- Confirmed SEO routes are mounted in the main FastAPI app and added a regression test to ensure key SEO endpoints remain registered.
- Hardened `seo_sites` persistence constraints:
  - Added unique domain constraint per business: `(business_id, normalized_domain)`.
  - Added one-primary-site guard per business with a partial unique index on `business_id` where `is_primary = true`.
  - Added Alembic migration `0014_seo_sites_uniqueness_hardening` with prechecks that fail migration safely if existing duplicate data would violate new constraints.
- Strengthened SEO site service validation and error handling:
  - Pre-validate duplicate domains on create/update.
  - Map DB integrity constraint violations to clear validation errors.
- Tightened crawler SSRF protections:
  - Host validation now fails closed on DNS resolution errors.
  - Blocked all non-public resolved IP targets (`not is_global`) to cover loopback/private/link-local/multicast/reserved/unspecified/documentation ranges.
  - Preserved existing same-domain and crawl-boundary behavior.
- Expanded tests for:
  - main app SEO route availability,
  - SEO site uniqueness/primary DB constraints,
  - additional SSRF blocked-address classes,
  - unresolved-host blocking,
  - summary failure isolation with versioned failed summary persistence.

## Risks Reduced
- Prevents duplicate site registrations for the same business/domain at the database layer.
- Prevents inconsistent multi-primary site state for a single business, even under concurrent writes.
- Reduces SSRF bypass risk by rejecting non-public and unresolved DNS targets before fetch.
- Reduces regression risk for SEO activation and summary-failure handling through explicit tests.

## Follow-up Before Phase 2
- Add periodic operational checks for migration precheck failures in staging/prod upgrade pipelines.
- Consider optional allowlisting controls for SEO crawl targets if customer onboarding broadens beyond straightforward website audits.
- Keep dev/test fallback auth behavior explicit and isolated from production runtime paths.

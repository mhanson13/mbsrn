# Google Analytics (GA4) Platform Audit

Date: 2026-05-07  
Author: Codex audit pass (repo-only, no live Google calls)

## 1) Executive Summary

MBSRN has a solid GA4 foundation for read-only traffic visibility and recommendation context, but the implementation is currently uneven across flows.

Current strengths:
- Clear GA4 integration layer (`ga4_analytics_provider`) and service mapping (`seo_analytics`)
- Stable operator diagnostics (`ga4_status`, `ga4_error_reason`, freshness fields)
- Per-site GA4 onboarding metadata persisted on `seo_sites`
- Strong API/service test coverage for GA4 summary/onboarding error paths
- Frontend surfaces connection health and directional traffic context without dashboard sprawl

Highest-impact gaps:
- **Property scoping mismatch risk**: per-site `ga4_property_id` is validated in some paths, but recommendation enrichment paths can query GA4 without enforcing site property selection.
- **No GA4 provider unit test suite** equivalent to Search Console provider coverage.
- **Limited operator decision depth**: no conversions/events/source-medium/landing-page performance views; top pages are fetched but not surfaced directly.
- **Audit and migration planning do not materially use GA4 metrics** (mostly boolean/context-presence signals).
- **GA4 account discovery endpoint exists but is not used by frontend setup UX**.

Overall maturity: **Moderate (Phase 1-2 level)**. Strong read-only plumbing and diagnostics are present, but operator decision leverage and strict site-level GA4 correctness need hardening before expanding analytics-driven automation.

## 1.1) Phase 0 Follow-Up Status (2026-05-07)

Phase 0 hardening from this audit is now implemented:
- recommendation analytics paths enforce site-scoped GA4 property usage (`site.ga4_property_id`) and fail closed to `not_configured` when missing
- recommendation measurement context no longer falls back to global/default GA4 property for site-scoped reads
- dedicated provider unit tests were added for GA4 auth/error/payload handling and site-scoped property routing
- regression coverage now includes missing-property skip behavior, cross-site property isolation, and graceful GA4 error degradation

## 1.2) Phase 1 Status (2026-05-07)

Phase 1 GA4 connection/property health visibility is now implemented as a compact, site-scoped status layer:
- site analytics summary responses include additive `ga4_health` fields with bounded operator-safe status/message values
- health is derived from the selected site property path only; no global/default GA4 property fallback is used
- Sites selected-site setup and site workspace surfaces show compact per-site GA4 health state + next-step guidance
- recommendation detail surfaces now explicitly show when GA4 measurement context is omitted/unavailable
- GA4 health visibility is additive and does not change recommendation scoring, migration planning logic, or deploy behavior

## 1.3) Phase 2 Status (2026-05-07)

Phase 2 compact GA4 operator insights are now implemented as an additive, site-scoped read model:
- site analytics summary responses include additive `ga4_insights` with bounded status/source/date-range/message fields
- `ga4_insights` includes compact operator summaries for:
  - top landing pages (bounded to top 5 in UI)
  - traffic trend (current vs previous period sessions/active users + bounded hint)
  - engagement trend (engagement-rate/time deltas + bounded hint)
- insights use the selected site property (`site.ga4_property_id`) only; no global/default GA4 property fallback is used
- site workspace renders compact cards (no charts, no dashboard drilldowns)
- recommendation detail surfaces now include a compact GA4 insight availability line when measurement context is available
- GA4 insight availability remains non-blocking for recommendations, audits, migration, and deploy workflows

## 1.4) OAuth Scope Follow-Up (2026-05-07)

Google reconnect + GA4 authorization behavior is now scope-aware:
- GBP connect/reconnect remains least-privilege for Business Profile by default (`business.manage`).
- A targeted reconnect path can now explicitly request GA4 read scope (`https://www.googleapis.com/auth/analytics.readonly`) without requesting Analytics write/edit scopes.
- Connection status now exposes bounded GA4 scope awareness (`ga4_scope_granted`, `required_ga4_scope`) without exposing tokens.
- GA4 health normalization now distinguishes:
  - `missing_oauth_scope`
  - `permission_denied`
  - `invalid_property`
  - `not_configured`
  - `no_data`
  - `unavailable`
- Health payloads also expose bounded GA4 auth mode (`user_oauth`, `service_account`, `adc`, etc.) so operator guidance can clearly separate reconnect-vs-Viewer-access actions.

## 1.5) Phase 3 Status (2026-05-08)

Phase 3 additive recommendation-context wiring is now implemented with deterministic, non-scoring GA4 hints:
- recommendation payloads include bounded GA4 priority context fields (`ga4_priority_context_available`, `ga4_priority_signal`, `ga4_priority_hint`, `ga4_supporting_page_path`, `ga4_supporting_metric_summary`, `ga4_context_source`)
- signal precedence is conservative and noise-controlled:
  1. top landing-page match
  2. traffic decline (sitewide/homepage-oriented recommendations)
  3. engagement decline (content/page-quality-oriented recommendations)
- context is derived from existing site-scoped `ga4_insights` only
- GA4 remains optional/non-blocking; unavailable states fail closed to bounded context-source reasons
- recommendation scoring and ordering are unchanged

## 1.6) Phase 4 Status (2026-05-10)

Phase 4 compact acquisition/source context is now implemented as an additive, site-scoped GA4 layer:
- site analytics summary responses include additive `ga4_acquisition_insights`
- bounded acquisition summaries now include:
  - top channels
  - top source/medium pairs
  - organic/direct/referral/paid compact summaries
  - deterministic operator hints (non-AI, capped)
- acquisition reads use `site.ga4_property_id` only; no global/default GA4 property fallback is used
- missing/unavailable GA4 remains non-blocking and maps to bounded statuses (`not_configured`, `missing_oauth_scope`, `permission_denied`, `invalid_property`, `no_data`, `unavailable`, `unknown`)
- site workspace shows compact acquisition context cards only (no charts, no dashboard drilldown)
- recommendation scoring and ordering remain unchanged in this phase
- GBP diagnostics/remediation remain a separate track and are currently blocked by external Google allowlist/quota approval

## 1.7) Phase 5A Status (2026-05-10)

Phase 5A introduces lightweight, additive GA4 outcome snapshots for recommendation follow-up:
- recommendation payloads can include additive `ga4_outcome_snapshot` when an action anchor exists (for example accepted/completed recommendation timestamps)
- snapshots use deterministic before/after windows (default 14 days before and 14 days after the anchor)
- status remains bounded and non-blocking (`available`, `pending_after_window`, `insufficient_data`, `not_configured`, `missing_scope`, `permission_denied`, `unavailable`)
- operator wording is explicitly observational:
  - "Observed after completion"
  - "Traffic changed after completion"
  - "No clear movement yet"
- snapshots are not attribution and do not claim causation
- recommendation scoring, priority, severity, and ordering remain unchanged
- site-scoped GA4 property enforcement remains mandatory with no global/default fallback

## 1.8) Phase 5B Status (2026-05-10)

Phase 5B adds lightweight, additive GA4 outcome snapshots for migration follow-up:
- migration workspace summary payloads can include additive `ga4_outcome_snapshot` when a successful migration publish/deploy anchor timestamp exists
- anchor precedence is deterministic and non-invasive:
  - prefer `migration_deployed` when a successful deploy timestamp exists
  - fallback to `migration_published` when deploy is not available
- the same deterministic before/after windows are used (14 days before and 14 days after the anchor)
- status remains bounded and non-blocking (`available`, `pending_after_window`, `insufficient_data`, `not_configured`, `missing_scope`, `permission_denied`, `unavailable`)
- operator wording remains explicitly observational:
  - "Observed after deploy"
  - "Observed after publish"
  - "Not enough time has passed"
- this is observational context only, not attribution or causation
- migration publish/deploy execution behavior is unchanged
- recommendation scoring/order behavior remains unchanged

## 2) Current Implementation Inventory

| File | Purpose | GA4 Role | Area | Risk | Notes |
|---|---|---|---|---|---|
| `app/integrations/ga4_analytics_provider.py` | GA4 API client + mock + disabled provider | Core GA4 query/auth logic | Backend | High | Uses `analytics.readonly`, `runReport`, Admin account summaries |
| `app/services/seo_analytics.py` | GA4/Search Console service mapping | Site summary, onboarding, recommendation windows | Backend | High | GA4 status/freshness/error normalization lives here |
| `app/api/routes/seo.py` | SEO routes | GA4 site summary + onboarding + recommendation context attachment | Backend | High | Site-summary and recommendation enrichment enforce site-scoped GA4 property usage |
| `app/api/deps.py` | Dependency wiring | Instantiates GA4 provider from settings | Backend | High | Provider property comes from app settings (`GA4_PROPERTY_ID`) |
| `app/core/config.py` | Runtime config | GA4 env contract | Backend | Medium | Includes mock toggle and API base URL overrides |
| `app/models/seo_site.py` | ORM model | Stores per-site GA4 onboarding fields | Backend | Medium | `ga4_onboarding_status`, account/property/stream/measurement IDs |
| `app/schemas/seo_site.py` | Site API schema | GA4 fields in create/update/read models | Backend | Medium | Admin update contracts include GA4 fields |
| `app/services/seo_sites.py` | Site business logic | Normalizes GA4 fields + derives onboarding status | Backend | Medium | Operator/admin mutation boundary enforced at route layer |
| `app/schemas/seo_analytics.py` | Analytics read models | GA4 summary/freshness/error schema | Backend | Medium | Explicit literals for status/error reasons |
| `app/schemas/seo_recommendation.py` | Recommendation schema | `recommendation_measurement_context` contract | Backend | Medium | Carries GA4 contextual windows/deltas |
| `app/schemas/seo_migration.py` | Migration schema | GA measurement ID config (insertion) | Backend | Low | GA4 measurement id format validation only |
| `app/services/seo_migration.py` | Migration orchestration | `ga4_signals_included` boolean + GA script insertion precedence | Backend | Medium | Does not consume detailed GA4 metrics for planning |
| `app/integrations/seo_migration_artifact_provider.py` | Migration artifact generation mock/provider integration | Analytics placeholder normalization | Backend | Low | Uses GA4 placeholder token, not GA4 reporting data |
| `app/tests/test_seo_analytics_api.py` | API tests | GA4 summary/onboarding/error/freshness cases | Tests | Low | Strong mocked coverage |
| `app/tests/test_seo_recommendations_api.py` | Recommendation API tests | GA4 measurement context in recommendation payloads | Tests | Medium | Validates context rendering paths |
| `app/tests/test_recommendation_effectiveness_confidence.py` | Effectiveness logic tests | GA4+GSC directional confidence behavior | Tests | Low | Deterministic trend confidence checks |
| `app/tests/test_seo_sites_api.py` | Site API auth/validation tests | Admin-only GA4 config writes + role boundaries | Tests | Low | Confirms operator cannot patch GA4 fields |
| `app/tests/test_seo_migration_service.py` | Migration service tests | GA4 signal inclusion + measurement insertion behavior | Tests | Medium | Mostly boolean/context-presence validation |
| `app/tests/test_seo_migration_api.py` | Migration API tests | Analytics config/measurement payload behavior | Tests | Low | No live GA4 calls |
| `app/tests/test_seo_router_mounting.py` | Route contract tests | GA4 endpoint mounting | Tests | Low | Ensures GA4 routes are registered |
| `frontend/operator-ui/lib/api/client.ts` | API client | GA4 endpoints + site analytics fetch | Frontend | Medium | Includes `fetchGA4AccessibleAccounts` but not consumed in UI |
| `frontend/operator-ui/lib/api/types.ts` | TS contracts | GA4 summary/onboarding/account response shapes | Frontend | Medium | Strong typed contracts for GA4 statuses |
| `frontend/operator-ui/app/sites/[site_id]/page.tsx` | Site workspace UI | GA4 trend card, diagnostics, onboarding summary | Frontend | Medium | Actionable but summary-level only |
| `frontend/operator-ui/app/recommendations/page.tsx` | Recommendations UI | Displays GA4 measurement context lines | Frontend | Medium | Directional context in expanded details |
| `frontend/operator-ui/app/business-profile/page.tsx` | Legacy Google setup route | Compatibility surface for full GBP verification workflow | Frontend | Medium | Setup ownership shifted to Sites selected-site setup |
| `frontend/operator-ui/app/google-profile/page.tsx` | Legacy compatibility route | Redirects to Sites selected-site setup | Frontend | Low | Preserves old bookmarks and callback links |
| `frontend/operator-ui/components/MigrationWorkspacePanel.tsx` | Migration UI | Shows `ga4_signals_included` in draft input summary | Frontend | Low | Informational provenance only |
| `frontend/operator-ui/app/sites/site-workspace-page.test.tsx` | Site workspace tests | GA4 summary/onboarding rendering and GA4 panel removal | Tests | Low | Confirms setup links route to Sites selected-site setup |
| `frontend/operator-ui/app/recommendations/page.test.tsx` | Recommendation UI tests | GA4 measurement context rendering behavior | Tests | Low | No-match vs available coverage |
| `frontend/operator-ui/app/business-profile/page.test.tsx` | Google Profile tests | GA4 property save UI behavior | Tests | Low | Mocks API responses |
| `docs/architecture.md` | Architecture doc | GA4 layer design + diagnostics/freshness/onboarding | Docs | Medium | Mostly accurate; references phased model |
| `docs/deployment-gke-cicd.md` | Deployment doc | GA4 runtime secret/env wiring | Docs | Medium | Documents `GA4_CREDENTIALS_JSON`, optional `GA4_PROPERTY_ID` |
| `docs/features/google-profile.md` | Feature doc | Describes legacy/compatibility Google setup route behavior | Docs | Low | Setup ownership now under Sites selected-site setup |
| `docs/features/seo-migration-workspace.md` | Feature doc | Migration GA4 signal + measurement insertion notes | Docs | Low | GA4 used as context/insertion, not analytics scoring |
| `docs/features/recommendations.md` | Feature doc | Recommendation GA4 context description | Docs | Medium | Contains stale wording about in-workspace "Connect GA4" control |
| `.env.example` | Env sample | Search Console env documented; GA4 env missing | Config Docs | Medium | GA4 runtime keys exist in code but not mirrored here |

## 3) Architecture Findings

### 3.1 How GA4 is connected
- GA4 uses `GoogleAnalyticsDataAPIClient` with read-only scope `https://www.googleapis.com/auth/analytics.readonly`.
- Auth path is service account JSON (`GA4_CREDENTIALS_JSON`) or ADC fallback.
- GA4 report calls are direct `runReport` HTTP requests; account discovery uses GA Admin `accountSummaries`.

### 3.2 Property discovery/storage/selection
- Per-site GA4 metadata is persisted on `seo_sites` (`ga4_property_id`, onboarding fields).
- Sites selected-site setup lets operator/admin save numeric GA4 property ID per selected site.
- Account discovery endpoint exists (`/analytics/ga4-accessible-accounts`) but is not consumed by frontend setup UX.

### 3.3 Query model
- Site summary queries users/sessions/pageviews/organic sessions and top pages.
- Recommendation context uses sessions/pageviews and before/after window comparisons.
- No conversion/event-level query model, no source/medium decomposition, no funnel constructs.

### 3.4 Sync/async + caching/storage
- Current GA4 reads are synchronous request-time calls.
- No background refresh worker/caching layer for GA4 summaries.
- Freshness timestamps are generated per successful fetch in response model; not persisted as durable per-site analytics snapshots.

### 3.5 Site/business scoping correctness
- Tenant/business route scoping is strong.
- **Gap**: provider is instantiated with app-level `GA4_PROPERTY_ID`, while service validates site-level `ga4_property_id`. Recommendation routes call `get_site_summary(...)` without passing/enforcing site property, creating potential cross-site/global property use.

### 3.6 Local/test/prod behavior
- Mock provider mode exists (`GA4_USE_MOCK_PROVIDER`) for deterministic local/testing.
- Most tests inject deterministic providers or service overrides; no live GA4 calls required.
- Production deploy docs describe secret wiring for GA4 credentials and optional global property env.

### 3.7 Failure handling
- Bounded reason mapping exists (`not_configured`, `permission_denied`, `property_not_found`, `invalid_property_format`, `no_data`, `unknown_error`).
- Errors are normalized for UI-safe operator messaging.
- Missing finer-grained classifications (quota/rate-limit/transient retry hints) and no retry/backoff strategy.

### 3.8 GA4 vs Search Console parity
- Search Console integration is more mature in diagnostics and provider-level test depth.
- GA4 has strong API/service tests but lacks dedicated provider client tests and has scoping inconsistency risk not present in Search Console path.

## 4) Security and Privacy Findings

### 4.1 OAuth/scopes/tokens boundaries
- GA4 itself does not currently use user OAuth token flows; it uses service-account/ADC runtime auth.
- Scope is minimal for read path (`analytics.readonly`).
- User OAuth token encryption/scope hardening exists for Google Business Profile and is separated from GA4 measurement path.

### 4.2 Token and secret exposure
- No GA4 access tokens are returned in API responses.
- Connection endpoints expose only bounded metadata (`granted_scopes`, `token_status`, refresh token presence boolean).
- Logging generally avoids raw credentials, but provider error text is summarized from remote messages; continue guarding against over-detailed remote payload echo.

### 4.3 Tenant/data isolation risks
- Site/business route scoping exists.
- **Medium/High risk**: shared-credential account discovery can expose broad GA account names/counts if service credential is over-permissioned across tenants.
- Site-scoped GA4 property enforcement for recommendation analytics is now in place; residual risk is limited to future regressions and is covered by regression tests.

### 4.4 Tests and live-call safety
- API/service tests are mock/stub-heavy and deterministic.
- No evidence of required live Google calls in local GA4 test paths.
- Missing dedicated GA4 provider HTTP/auth unit tests increases regression risk in real auth/network failure mapping.

## 5) Operator Value Assessment (What Exists vs Missing)

| Operator question | Current state | Gap |
|---|---|---|
| Which pages get traffic but do not convert? | Not supported | No conversion/event modeling in GA4 usage |
| Which pages have declining engagement? | Partially | Sessions/pageviews deltas available; no engagement-rate/session quality metrics |
| Which landing pages are underperforming? | Partially | Top pages fetched backend, not surfaced as operator-first card/table |
| Which traffic sources produce useful visitors? | Partial | Compact channel/source summaries are now surfaced; no conversion/event quality scoring yet |
| Which recommendations should be prioritized by behavior? | Weak | GA4 context is explanatory, not priority/severity input |
| Which pages should be migrated first? | Weak | Migration does not use page-level GA4 weights for page-map priority |
| Which generated pages need stronger CTAs? | Weak | No conversion/goal signals applied to draft guidance |
| What content must be preserved in migration? | Weak | No GA4 top-page preservation heuristics beyond boolean context signal |
| Is post-deploy performance improving? | Partial | Recommendation before/after context exists; no deploy-linked GA4 outcome loop |

## 6) Recommendation Engine Findings

Current:
- GA4 fields used: sessions/pageviews windows + deltas and matched page path context.
- Combined directional effectiveness context merges GA4 + Search Console signals.
- GA4 absence handled with explicit `measurement_status` fallback states.
- Explanations expose directional context in recommendation detail UI.

Missing:
- GA4 does not currently affect recommendation priority scoring logic.
- No direct use of conversions/events/engagement/session quality in recommendation ranking.
- Missed GA4+GSC combinations for actioning, such as:
  - high impressions + weak engagement
  - high traffic + low conversion/event completion
  - declining traffic + stale/low-quality page signals
  - post-deploy organic and engagement trend deltas tied to release windows

## 7) Audit Run Findings

- SEO audit run services/routes currently do not integrate GA4 metrics into scoring/findings.
- Audit output remains crawl/rule based; GA4 is not used as finding evidence.
- This keeps audit deterministic, but misses operator value in prioritizing technical fixes by business impact.

## 8) Migration Workflow Findings

Current:
- Migration draft input summary includes boolean `ga4_signals_included` only.
- Migration analytics config supports GA measurement ID insertion for publish/deploy artifacts.
- GA4 measurement id precedence and insertion-mode semantics are documented and tested.

Missing:
- GA4 page traffic/engagement does not influence page-map prioritization or structure planning.
- No GA4-based rewrite/consolidation hints for low-performing legacy pages.
- No post-publish/deploy GA4 outcome loop feeding migration follow-up recommendations.
- GA4 in migration is currently provenance-level signal, not planning intelligence.

## 9) Frontend/UI Findings

Current surfaces:
- Site workspace: compact GA4 insight cards (`Top landing pages`, `Traffic trend`, `Engagement trend`) plus GA4 onboarding/health summary.
- Recommendations: page/site traffic context in expanded recommendation details.
- Sites selected-site setup: per-site GA4 property input/save.
- Migration workspace: bounded GA4-included boolean signal in draft context summary.

UX quality:
- GA4 vs Search Console distinction is generally clear.
- Missing GA4 setup is explained with actionable guidance.
- No dashboard bloat; UI remains compact.

Gaps:
- No operator-facing top landing pages component despite backend data availability.
- No source/medium/conversion trend card set.
- GA4 accessible accounts endpoint is not surfaced in setup UX.
- Setup UI is manual-only property input; no verification/picker flow.

Role boundaries:
- Backend enforces admin-only updates for GA4 site fields.
- Sites selected-site setup currently presents save controls but does not visibly role-gate them client-side (relies on backend 403 path).

## 10) Testing Findings

What is covered well:
- GA4 summary route behavior for configured/not-configured/error/no-data/freshness.
- GA4 onboarding/account discovery endpoint contracts and tenant scope checks.
- Recommendation GA4 measurement-context rendering and directional effectiveness confidence behavior.
- Migration GA4 signal-included metadata and measurement insertion controls.

What is missing or weak:
- No dedicated low-level GA4 provider test suite (auth fallback, HTTP error parsing, timeout handling, host filter behavior).
- Recommendation route tests now assert site-level GA4 property enforcement and cross-site isolation.
- Limited explicit tests for quota/rate-limit and malformed partial GA4 response payloads.
- No UI tests for account-discovery-based GA4 property selection flow (because flow is not implemented).

Real-call posture:
- Existing local tests appear mock/provider-stub based and do not require live Google API calls.

## 11) Risk Register

| ID | Severity | Risk | Evidence | Recommendation |
|---|---|---|---|---|
| GA4-R1 | Resolved (monitor) | Recommendation GA4 context may use app-global property instead of site property | Recommendation routes now enforce site-scoped property and tests cover missing-property + cross-site isolation paths | Keep regression coverage in CI and block fallback reintroduction |
| GA4-R2 | High | Shared-credential account discovery may leak broad account metadata across tenants | `/ga4-accessible-accounts` returns service-credential account summaries | Scope/filter account discovery or restrict endpoint visibility to admin + scoped mappings |
| GA4-R3 | Medium | No dedicated GA4 provider tests | No `test_ga4_analytics_provider.py` equivalent to Search Console provider tests | Add provider-level unit tests for auth/timeout/error parsing/filter construction |
| GA4-R4 | Medium | Operator value remains limited beyond compact GA4 summaries | Phase 2 added top landing/traffic/engagement cards, but no conversions/events/source-medium and no prioritization wiring yet | Add phase-3 prioritization hooks + phase-4/5 deeper GA4 outcome usage |
| GA4-R5 | Medium | Docs drift on GA4 setup location | Recommendations doc references in-workspace connect control while setup moved to Sites selected-site setup | Align docs with current UX ownership model |
| GA4-R6 | Medium | GA4 runtime env docs incomplete in `.env.example` | GA4 config keys exist in code but sample env omits them | Add non-secret GA4 env examples and safe comments |

## 12) Recommended Roadmap (Phased)

### Phase 0: Safety/Test Hardening

1. Enforce site-level GA4 property contract in all GA4 read contexts
- Goal: Prevent cross-site/global-property analytics mixing.
- Operator value: Trust that traffic context belongs to the selected site.
- Likely files: `app/api/routes/seo.py`, `app/services/seo_analytics.py`, GA4 recommendation tests.
- Backend impact: Medium.
- Frontend impact: Low (status handling only).
- Docs impact: Low.
- Security: High positive impact (tenant/data correctness).
- Local tests: Add route/service regressions for missing/mismatched site property.
- Production validation: Compare recommendation contexts before/after on multi-site business.

2. Add GA4 provider unit tests
- Goal: Lock auth fallback, timeout/error mapping, and payload parsing behavior.
- Operator value: Fewer silent GA4 regressions.
- Likely files: new `app/tests/test_ga4_analytics_provider.py`.
- Backend impact: Low.
- Frontend impact: None.
- Docs impact: None.
- Security: Medium positive impact (error/sanitization confidence).
- Local tests: provider auth/HTTP classification + safe error summarization.
- Production validation: N/A (test hardening).

### Phase 1: Expose Current GA4 Connection/Property Health

1. Surface account-discovery and property verification in Sites selected-site setup
- Goal: Move from manual-only property entry to guided property confirmation.
- Operator value: Lower setup friction and fewer property mismatch errors.
- Likely files: `frontend/operator-ui/app/sites/page.tsx`, `frontend/operator-ui/app/business-profile/page.tsx`, `frontend/operator-ui/lib/api/client.ts`, tests.
- Backend impact: Low to medium (may need scoped endpoint behavior).
- Frontend impact: Medium.
- Docs impact: Medium.
- Security: Ensure account discovery is tenant-safe and role-gated.
- Local tests: mock account list, property selection, 403 paths.
- Production validation: role-based access checks + scoped account visibility.

2. Add explicit GA4 health state contract checks
- Goal: Distinguish property-configured vs data-readable vs stale.
- Operator value: Faster troubleshooting.
- Likely files: `app/services/seo_analytics.py`, site workspace UI.
- Backend impact: Low.
- Frontend impact: Low.
- Docs impact: Low.
- Security: No additional sensitive data exposure.
- Local tests: status transitions and message mapping.
- Production validation: verify with configured-but-empty and access-denied properties.

### Phase 2: Add Operator-Visible GA4 Insight Cards (No dashboard sprawl)

1. Top landing pages + trend snapshot
- Goal: Make existing top-page data operationally visible.
- Operator value: Better page-level prioritization decisions.
- Likely files: `frontend/operator-ui/app/sites/[site_id]/page.tsx`, API types/tests.
- Backend impact: Low (already available).
- Frontend impact: Medium.
- Docs impact: Medium.
- Security: Keep output bounded and tenant-scoped.
- Local tests: rendering with empty/partial top pages.
- Production validation: compare with GA4 UI for sample sites.

2. Add compact source-medium and engagement summary fields
- Goal: Clarify visitor quality channels without full analytics dashboard.
- Operator value: Better recommendation and content focus.
- Likely files: GA4 provider/service, site workspace UI, schemas/tests.
- Backend impact: Medium.
- Frontend impact: Medium.
- Docs impact: Medium.
- Security: avoid sensitive granular query payload leaks.
- Local tests: mocked channel breakdown and missing-data states.
- Production validation: consistency checks vs GA4 property reports.

### Phase 3: Feed GA4 into Recommendations and Prioritization

1. Behavior-weighted recommendation priority signals
- Goal: Use traffic/engagement/conversion deltas as additive ranking input.
- Operator value: Higher confidence in what to do first.
- Likely files: `app/api/routes/seo.py` priority derivation, recommendation schemas/UI/tests.
- Backend impact: Medium.
- Frontend impact: Low to medium.
- Docs impact: Medium.
- Security: keep directional, avoid causal overclaims.
- Local tests: deterministic fixtures for high-traffic/low-conversion scenarios.
- Production validation: operator acceptance checks on prioritization quality.

2. GSC+GA4 combined heuristics
- Goal: highlight high-impression/low-engagement and high-traffic/low-conversion pages.
- Operator value: clearer recommendation rationale and execution sequence.
- Likely files: recommendation context builders + UI text.
- Backend impact: Medium.
- Frontend impact: Low.
- Docs impact: Medium.
- Security: bounded summaries only.
- Local tests: combined-context edge cases and missing-source fallbacks.
- Production validation: sample recommendation trace audits.

### Phase 4: Feed GA4 into Migration Draft Planning

1. Preserve high-value pages and CTA strength using GA4 signals
- Goal: use measured value signals in migration planning hints.
- Operator value: better preservation and conversion-safe migrations.
- Likely files: `app/services/seo_migration.py`, migration context summary/UI/tests.
- Backend impact: Medium.
- Frontend impact: Low to medium.
- Docs impact: Medium.
- Security: no raw GA payloads in prompt context; bounded summaries only.
- Local tests: mocked GA4 page-value inputs and no-data fallback.
- Production validation: compare migrated page maps against legacy top performers.

2. Explicit migration risk cues for low-performing pages
- Goal: flag rewrite/consolidation candidates with bounded analytics evidence.
- Operator value: less manual triage.
- Likely files: migration context + artifact quality/readiness summaries.
- Backend impact: Medium.
- Frontend impact: Medium.
- Docs impact: Medium.
- Security: preserve sanitization; no URL/token leakage.
- Local tests: deterministic low-performance cue generation.
- Production validation: review with operators on real migrations.

### Phase 5: Post-Publish/Deploy Performance Tracking

1. Release-window outcome tracking tied to deploy/publish events
- Goal: compare before/after traffic/engagement post release.
- Operator value: confirms impact and guides follow-up actions.
- Likely files: deploy summary services, recommendation effectiveness pipeline, workspace UI diagnostics.
- Backend impact: Medium to high.
- Frontend impact: Medium.
- Docs impact: Medium.
- Security: aggregate-only reporting and strict tenant scope.
- Local tests: mocked release timelines + GA4 window deltas.
- Production validation: verify against live GA4 for selected deploys.

2. Operator follow-up queue based on outcome drift
- Goal: trigger compact “needs attention” list when post-launch metrics degrade.
- Operator value: closes loop from deployment to optimization.
- Likely files: recommendation queue generation + workspace cards.
- Backend impact: Medium.
- Frontend impact: Medium.
- Docs impact: Medium.
- Security: avoid noisy/over-alerting; keep bounded evidence.
- Local tests: degradation/improvement threshold tests.
- Production validation: phased rollout with audit logs and operator feedback.

## Appendix: Audit Constraints and Method

- Audit-only pass; no feature implementation changes performed.
- No OAuth scope changes, token-storage changes, DB migrations, CI/CD, or deploy workflow changes.
- Repo-only inspection with static/code/test/doc review.
- No live Google API calls were made.

# Competitor Insights

## Normalization Layer

### Why this exists
AI competitor responses can be incomplete, malformed, or inconsistent. The normalization layer provides a stable response contract before downstream processing so bad model output does not crash competitor insight handling.

### What it guarantees
- Always returns a valid dictionary with:
  - `competitors` (list)
  - `top_opportunities` (list)
  - `summary` (string)
- Competitor entries always include required fields with defaults.
- `visibility_score` and `relevance_score` are always bounded to `1..5`.
- List fields are always lists, never `null`.
- Duplicate competitors are removed by normalized name.
- Empty placeholder competitors are dropped.

### Fallback behavior
If AI output cannot be parsed as JSON, normalization returns:

```json
{
  "competitors": [],
  "top_opportunities": [
    "Improve website clarity",
    "Add trust signals",
    "Clarify services"
  ],
  "summary": "Competitor analysis unavailable, using fallback insights."
}
```

### Limitations
- This layer improves reliability, not quality.
- It does not change prompt/model behavior.
- It does not score or re-rank competitors beyond required field normalization.

## Recommendation Integration (Optional, Bounded)
Normalized competitor output can optionally inform recommendation narrative generation. The recommendation layer only consumes these fields:
- `top_opportunities` (bounded list)
- `summary` (bounded string)
- competitor `name` values (bounded list)

Behavior is intentionally conservative:
- Integration is optional and non-blocking.
- Missing/empty competitor data keeps recommendation behavior unchanged.
- Normalizer fallback payloads are treated as no-signal to avoid injecting generic noise.
- Raw malformed competitor output is never passed directly to recommendation prompts.
- When competitor context is used, recommendation narrative responses may include a bounded
  `competitor_influence` rationale payload for operator visibility (`used`, `summary`,
  `top_opportunities`, `competitor_names`).
- Recommendation narrative responses may also include a separate optional `action_summary`
  payload that focuses on operator next steps; this remains distinct from
  `competitor_influence`.
- Recommendation narrative responses may include optional `signal_summary` framing where
  competitor context is one bounded evidence source among site/references/themes signals.
- Workspace recommendation rows may include deterministic
  `recommendation_evidence_summary` text where competitor-backed support is one possible
  evidence source (alongside EEAT/site evidence metadata).
- Workspace recommendation summaries may include optional deterministic `eeat_gap_summary`
  metadata where competitor-supported signals contribute to visible Experience/Expertise/
  Authoritativeness/Trustworthiness gap framing.
- Workspace recommendation summaries may include deterministic recommendation themes/groups
  where competitor-backed gaps can surface under operator-facing buckets such as
  `authority_and_visibility` or `trust_and_legitimacy`, depending on existing structured
  recommendation metadata.
- Site workspace now exposes a direct `Generate Recommendations` action so operators can
  create recommendation runs from the same page used for competitor investigation.

## Prompt Preview (Debug / Inspection)

Workspace summary responses may include an optional `competitor_prompt_preview` object so operators can inspect the final competitor-generation prompt payload used for AI calls.

### What is shown
- prompt type (`competitor`)
- model label (when available)
- operator-facing prompt identity label (`prompt_label`, for competitor previews this is `resolved competitor prompt`)
- legacy prompt template identifier (`prompt_version`) when provided
  - compatibility/template metadata only
  - not the operator-facing effective prompt identity
- prompt source (`admin_config`, `env`, `default`)
- bounded prompt metrics (character counts) for debug sizing, including:
  - total prompt chars
  - context JSON chars
- final system prompt text
- final user prompt text
- truncation flag when bounded output clipping is applied

### What is intentionally not shown
- provider credentials
- API keys
- auth headers
- environment/secret dumps

### Safety behavior
- Preview is read-only and optional.
- Prompt text is sanitized for control characters and bounded for UI-safe rendering.
- Prompt assembly applies deterministic context trimming when context payload size exceeds budget:
  - existing/excluded domain lists are capped
  - service-area/non-competitor-hint arrays are capped
  - context JSON is reduced conservatively without changing core prompt contract
- When preview data is unavailable, no prompt preview block is rendered.

## Admin-Managed Prompt Overrides

Competitor prompt override text can now be managed in persisted admin settings via:

- `ai_prompt_text_competitor` (business-scoped admin override)

Persistence scope:
- stored on the `businesses` table as a business-level override value
- does not create global/shared prompt state across businesses

Effective prompt resolution order is deterministic:

1. persisted admin override (`ai_prompt_text_competitor`) when non-empty
2. deployment env fallback (`AI_PROMPT_TEXT_COMPETITOR`) when configured
3. existing default/empty fallback behavior when no override or env fallback exists

Behavior notes:
- Prompt edits apply to future runs and previews only.
- Clearing the admin override returns behavior to deployment fallback when configured, otherwise built-in default behavior.
- Whitespace-only overrides are treated as unset and fall back safely.
- Admin override text replaces the legacy/default competitor instruction body when present (exclusive source selection).
- Assembled competitor prompts contain exactly one instruction body:
  - admin override body, or
  - default template body when no override is set.
- Admin override text is used as instruction text only and appears once in assembled competitor prompts.
- Minimal platform constraints may still wrap instruction bodies (JSON-only output, hostname-only domain formatting, context-as-data safety).
- Structured prompt context blocks remain data-only:
  - `SITE_CONTEXT_JSON` is appended once and includes trusted site/business data only.
  - Prompt text is never embedded into structured context payload fields.
- Admin override instruction text supports the same site/context placeholders as the default competitor prompt assembly (for example `{site_display_name}`, `{site_location_context}`, `{site_industry_context}`, `{service_focus_terms}`, `{target_customer_context}`).
- Placeholder interpolation is applied before preview/export/runtime assembly so all operator-visible and runtime prompts stay in sync.
- Prompt preview/debug now includes `source` attribution (`admin_config`, `env`, `default`) so operators can verify which configuration path is active.
- Prompt fallback baselines are captured from configured deployment defaults and resolved immutably per request; runtime provider mutation does not become the fallback source of truth.
- The same immutable-baseline guardrail is applied to both competitor and recommendation prompt resolvers to prevent cross-path drift regressions.

## Web Search Enabled Competitor Discovery

Competitor generation now uses OpenAI `/responses` as the primary path with `web_search` enabled.

- Primary request path: `/responses`
- Tooling: `tools: [{"type":"web_search"}]`
- Input shape: system + user prompt in the `input` array
- Model compatibility:
  - `gpt-5-mini` request payload omits unsupported sampling fields (for example `temperature`, `top_p`)

Safe fallback behavior:
- `/responses` with `web_search` is the authoritative discovery path for competitor generation.
- Fallback to `/chat/completions` is only used when the provider explicitly rejects `web_search` for the request/model.
- Timeouts, malformed outputs, and non-search request failures stay on the `/responses` path and are surfaced directly.
- This keeps prompt/runtime capability alignment explicit: search-backed when available, explicitly downgraded only on provider-declared `web_search` incompatibility.

## Google Places Seed Layer (Dynamic, Minimal)

Google Places is used as a **dynamic seed source only** before AI enrichment. It is not the final competitor intelligence layer.

Runtime behavior:
- For each competitor generation run, service/location context builds local-intent Places text queries.
- Places results are normalized into minimal seed records and injected into `SITE_CONTEXT_JSON` as `google_places_seed_candidates`.
- AI competitor generation then uses these seeds as hypotheses to enrich/validate (website, positioning, overlap), alongside existing context.

Seed fields (minimal):
- `source` (`google_places`)
- `place_id`
- `name`
- `formatted_address`
- `locality` (when derivable)
- `primary_type`
- `types`
- `website_domain` (only when cheaply available from Places response)

Cost/latency controls:
- query count is bounded
- seed count is bounded
- initial Places field mask is minimal (`id`, `displayName`, `formattedAddress`, `primaryType`, `types`, `websiteUri`)
- when Places is unavailable or not configured, pipeline falls back to existing competitor generation behavior

## Structured Output Hardening

Competitor generation now applies stricter structured-output handling with deterministic recovery:

- `/responses` requests include explicit JSON schema format constraints, matching the structured-output contract used for chat fallback.
- The same structured-output contract is used for both:
  - standard attempt
  - degraded timeout-retry attempt
- Parser recovery handles narrow, safe cases:
  - JSON wrapped in markdown fences
  - JSON wrapped in extra prose, when a single unambiguous JSON object/array can be extracted

Partial-salvage behavior:

- If a payload includes multiple candidates and some entries are malformed, valid entries are preserved.
- Runs prefer fewer valid candidates over whole-run failure when safe recovery is possible.
- Whole-run malformed-output failure is reserved for unrecoverable payloads (no safe usable candidate payload).

Recoverable schema-drift behavior:

- Candidate-entry type drift is now classified separately from full malformed-output failures.
- When at least one valid candidate is preserved, schema-drift diagnostics are logged as recoverable (`WARNING`) instead of pipeline failure (`ERROR`).
- When no valid candidates remain, diagnostics are logged as non-recoverable (`ERROR`) and downstream behavior remains unchanged.
- Structured diagnostics event: `competitor_candidate_schema_diagnostics` with bounded fields:
  - `valid_candidate_count`
  - `invalid_candidate_count`
  - `invalid_field_type_count` (type mismatches only)
  - `invalid_candidate_indexes`
  - `invalid_fields[]` entries containing:
    - `candidate_index`
    - `field_name`
    - `expected_type`
    - `actual_type`
    - `discard_reason`
    - `required_or_optional`
  - `discard_reason` values are semantic where applicable:
    - `invalid_string_value` / `invalid_numeric_value` for content-invalid values with otherwise valid primitive types
    - `invalid_string_type` / `invalid_numeric_type` for true type mismatches
    - `missing_required_field` for omitted required fields

Deterministic normalization:

- `confidence_score` now accepts deterministic single-value wrappers during candidate parsing:
  - single-item array (for example `["0.73"]`)
  - object wrappers with common score keys (`confidence_score`, `confidence`, `score`, `value`)
- This narrows recurring field-type drift without changing provider contracts or prompt shape.
- Normalization is intentionally narrow at schema-intake only for `confidence_score`; no broad cross-field coercion is applied.

### Production triage: schema diagnostics

Event:
- `event=competitor_candidate_schema_diagnostics`

Trigger/level semantics:
- `valid_candidate_count > 0` => recoverable schema drift (`WARNING`)
- `valid_candidate_count == 0` => non-recoverable schema drift (`ERROR`)

First fields to inspect:
- `valid_candidate_count`
- `invalid_candidate_count`
- `invalid_field_type_count` (true type mismatches only)
- `invalid_candidate_indexes`
- `invalid_fields[].field_name`
- `invalid_fields[].actual_type`
- `invalid_fields[].discard_reason`
- `recoverable`

Cloud Logging filters:
- recoverable warnings:
  - `jsonPayload.event="competitor_candidate_schema_diagnostics" AND severity=WARNING`
- non-recoverable errors:
  - `jsonPayload.event="competitor_candidate_schema_diagnostics" AND severity=ERROR`
- confidence-score-specific type drift:
  - `jsonPayload.event="competitor_candidate_schema_diagnostics" AND jsonPayload.invalid_fields.field_name="confidence_score"`

## Operator Outcome Summary

Competitor run detail responses now include a compact operator-facing `outcome_summary` object:

- `status_level`: `normal` | `recovered` | `degraded` | `failed`
- `message`: short operator-safe summary text
- `used_synthetic_fallback`: `true` when deterministic local-context fallback placeholders were used
- `used_timeout_recovery`: `true` when provider timeout recovery succeeded
- `had_schema_repair_or_discard`: `true` when provider candidate payload repair/discard occurred
- `used_google_places_seeds`: `true` when nearby-business discovery seeds were used in this run before AI enrichment

Status mapping:
- `normal`: provider-backed completion with no recovery path needed
- `recovered`: completion after provider instability/retry recovery
- `degraded`: synthetic fallback output was used (review required before accept)
- `failed`: terminal run failure

Synthetic fallback behavior:
- Fallback candidates are deterministic placeholders derived from local service/location context.
- They are returned to avoid empty operator output and should be reviewed before acceptance.

Source provenance behavior:
- Google Places is a **seed discovery** layer only. It contributes nearby-business hypotheses (`used_google_places_seeds=true`).
- AI enrichment still performs deeper analysis, validation, and competitive rationale.
- Synthetic fallback remains distinct from Places seeding:
  - `used_synthetic_fallback=true` means deterministic placeholders were returned.
  - `used_google_places_seeds=true` means nearby-business seeds were available/used before enrichment.

### Per-competitor provenance (operator-visible)

Each competitor draft now includes a per-item provenance classification and deterministic explanation:

- `provenance_classification`
  - `places_ai_enriched`: discovered via nearby-business seed data, then AI-enriched
  - `ai_only`: discovered from AI flow without Places seed participation
  - `synthetic_fallback`: generated by deterministic local fallback when reliable discovery was unavailable
- `provenance_explanation`
  - backend-authored, fixed explanation text for the classification
  - not model-generated free text

Notes:
- Run-level provenance (`outcome_summary.used_google_places_seeds`) and per-competitor provenance are complementary:
  - run-level field answers whether Places seeds were used at all in the run
  - per-competitor field explains each draft's origin class
- Historical runs may not contain per-competitor provenance fields; UI must handle missing values safely.

## Provider Error Visibility

Competitor provider failures now emit bounded backend log metadata to improve debugging:

- HTTP status (when available)
- provider name
- model name
- provider error type/code (when provided by provider response)
- bounded provider error message
- bounded request-debug metadata for timeout triage:
  - endpoint path (`/responses` or fallback `/chat/completions`)
  - prompt char counts
  - context char counts
  - prompt size risk bucket (`normal`, `elevated`, `high`)
- bounded failure kind in debug payload:
  - `timeout`: provider call timed out
  - `provider_request`: provider returned/raised a non-timeout request failure

Competitor provider request lifecycle logs are also emitted as structured events for Cloud Logging correlation:

- `competitor_provider_request_start`
- `competitor_provider_request_complete`
- `competitor_provider_request_error`

Admins can query these events directly from the in-app admin panel (`GCP Logs Query`) without granting end users direct GCP project access. The tool uses backend proxying with runtime ADC and fixed project scope.

Deployment prerequisite note:
- API runtime must expose project-id env `GCP_PROJECT_ID` and run with Workload Identity-enabled `mbsrn-api` KSA mapped to a GSA with Cloud Logging read access.

These structured events include bounded correlation/runtime fields such as:

- `run_id`
- `attempt_number`
- `endpoint_path`
- `web_search_enabled`
- `degraded_mode`
- `reduced_context_mode`
- `failure_kind`
- `malformed_output_reason` (when applicable)
- `duration_ms`

Safety:
- no secrets, auth headers, or key material are logged
- no raw environment dumps are logged
- no raw prompt body is logged
- no raw model response body is logged

Operator interpretation guidance:
- `timeout` with `high`/`elevated` prompt-size risk usually indicates latency pressure; rerun is safe and context trimming is already applied.
- `provider_request` indicates a provider-side request failure (for example invalid or rejected request payload) and should be investigated with the bounded error code/message metadata.

## Timeout Retry Hardening

Competitor generation now applies a bounded timeout-only retry at the service layer:

- first provider attempt uses the requested candidate count
- retry triggers only when the first attempt is classified as `timeout`
- exactly one retry is allowed
- second attempt runs in deterministic degraded mode with a lower candidate-count target
- second attempt also enables deterministic `reduced_context_mode` so optional prompt context is trimmed
- non-timeout failures (`provider_request`, auth/config, malformed output) do not retry

Timeout outcome semantics are explicit:
- `final_outcome=success`: timeout occurred but a non-degraded retry recovered
- `final_outcome=degraded_success`: timeout occurred and degraded retry recovered
- `final_outcome=failure`: timeout path exhausted without recovery

Structured timeout outcome event:
- `event=competitor_timeout_outcome`
- includes bounded runtime context such as:
  - `attempt_number`
  - `attempt_count`
  - `max_attempts`
  - `endpoint_path`
  - `provider_call_type`
  - `provider_name`
  - `model_name`
  - `timeout_type` (`read`, `connect`, `overall`, `unknown`)
  - `elapsed_ms`
  - `total_elapsed_ms`
  - `prompt_total_chars`
  - `context_json_chars`
  - `prompt_size_risk`
  - `recovered_after_timeout`
  - `recovery_path` (`retry_success`, `fallback_success`, `degraded_success`, `synthetic_fallback`, `none`)
  - `final_outcome`

### Last-Resort Synthetic Fallback

To prevent empty operator output in worst-case runs, competitor generation now applies a final deterministic local fallback when either condition is true:

- all provider attempts exhausted on timeout
- provider attempts complete, but zero usable drafts remain after validation/filtering

Behavior:

- generates `3..5` schema-valid draft candidates from local site/business context only
- uses deterministic service/location naming patterns (no external calls)
- does not claim provider verification or web-search evidence
- marks output as degraded fallback in run metadata:
  - provider attempt `execution_mode=fallback`
  - `degraded_mode=true`
  - `recovery_path=synthetic_fallback`
  - `final_outcome=degraded_success`
  - draft `source=ai_forced_fallback`

Safety intent:

- keep operator review moving when provider output is unavailable or unusable
- preserve bounded runtime and deterministic behavior
- avoid silently presenting synthetic output as provider-verified discovery

Degraded retry intent:
- reduce request cost under provider/web-search latency
- preserve core business/location/service context while trimming optional context
- avoid duplicate run artifacts or duplicate draft persistence

Retry reduced-context behavior:
- preserves business identity, service/trade context, and location/service-area context
- trims optional context blocks such as oversized domain lists and non-essential hint arrays
- is retry-only; first attempt behavior is unchanged

## Business-Scoped Competitor Timeout Settings

Competitor generation timeout behavior is now tunable per business from admin settings with two persisted fields:

- `competitor_primary_timeout_seconds`
- `competitor_degraded_timeout_seconds`

Behavior:

- `competitor_primary_timeout_seconds` controls the first full search-backed attempt timeout.
- `competitor_degraded_timeout_seconds` controls the reduced-context degraded retry timeout.
- Allowed range for each setting: `10..90` seconds.
- When a setting is unset (`null`), competitor generation keeps deployment/provider default timeout behavior for that attempt type.

This change is scoped only to competitor profile generation and does not alter recommendation timeout behavior.

## Provider Attempt Debug Metadata

Competitor run detail debug payloads can include bounded provider-attempt telemetry:

- `provider_attempt_count`
- `provider_degraded_retry_used`
- `provider_attempts[]` with compact fields such as:
  - `attempt_number`
  - `max_attempts`
  - `degraded_mode`
  - `reduced_context_mode`
  - `requested_candidate_count`
  - `outcome` / `failure_kind`
  - `timeout_type`
  - `request_duration_ms`
  - `timeout_seconds`
  - `endpoint_path`
  - `web_search_enabled`
  - `prompt_size_risk`
  - `prompt_total_chars`
  - `context_json_chars`
  - `user_prompt_chars`
  - `recovered_after_timeout`
  - `recovery_path`
  - `final_outcome`

This metadata is debug-oriented only and does not change ranking/scoring behavior.

Operator-facing interpretation:
- `endpoint_path`: the exact endpoint used for that attempt (`/responses` or `/chat/completions`).
- `web_search_enabled`: whether search tooling was enabled on that attempt.
- `degraded_mode`: `true` means timeout retry mode was used for that attempt.
- `reduced_context_mode`: `true` means optional context was trimmed to reduce prompt size during retry.
- service-focus derivation debug metrics in prompt preview payloads:
  - `service_focus_source_site_content`
  - `service_focus_source_structured_metadata`
  - `service_focus_source_domain_hints`
  - `service_focus_source_explicit_industry`
  - `service_focus_source_fallback`
  - `service_focus_terms_dropped_count`

## Workspace Run Quality Summary

The workspace competitor panel now shows a compact run-quality summary for terminal runs:

- proposed candidate count
- returned candidate count
- rejected candidate count
- degraded mode used (`yes`/`no`)
- search-backed discovery (`yes`/`no`)

Low-result behavior:

- when `returned <= 2`, the panel adds concise run notes
- when `returned <= 1`, the panel adds a safety message with likely causes derived from real run telemetry only:
  - strict validation filtered weak candidates
  - search-backed discovery unavailable
  - degraded retry occurred

This message is operator-facing guidance only and does not alter ranking, filtering, or persistence.

## Discovery vs Filtering Stages

Competitor generation uses a two-stage yield model:

1. Discovery stage (provider output):
   - runtime may request a slightly larger candidate pool than the final run request
   - this improves odds that enough valid candidates survive strict filtering
2. Filtering stage (deterministic validation + eligibility + tuning):
   - invalid/malformed/low-relevance candidates are removed
   - final output is still capped to the run `requested_candidate_count`

Why returned candidates can be lower than discovered candidates:

- strict domain/business validation rejects malformed entries
- eligibility filters remove non-substitutable or low-usefulness candidates
- tuning and deduplication remove weak or duplicate candidates
- final run limit truncates any excess survivors above requested count

Operator telemetry now distinguishes stage counts in logs:

- `discovery_candidate_count`
- `post_parse_candidate_count`
- `post_filter_candidate_count`

## Competitor Prompt Context Hardening

Competitor prompt context now prefers structured business/site metadata before any heuristic fallback.

### Context source order
1. Existing crawl/audit-derived site metadata already stored in-platform (`title`, `meta_description`, `h1`, `h2`, and URL path labels from latest completed audit pages)
2. Explicit site/business metadata (`industry`, `primary_location`, `service_areas_json`, display/business names)
3. Operator-entered location/service-area/category fields already persisted on the site/business records
4. Deterministic identity hints from site metadata (for example domain labels) only when stronger sources are missing

### Location context behavior
- Uses a shared deterministic location-context builder (`build_location_context(site)`) so prompt and workspace use the same source/strength logic.
- Provenance is tracked as one of:
  - `explicit_location`
  - `service_area`
  - `zip_capture`
  - `fallback`
- Falls back to:
  - `Location not yet established from available business/site data.`
- Does not fabricate geography.
- Does not call external geocoding APIs.

### Industry context behavior
- Uses explicit structured `industry` when present.
- Otherwise uses deterministic service inference from existing website/crawl metadata when available.
- Falls back to cautious deterministic inference from available business/site identity text only when site content is thin.
- Falls back to:
  - `Industry not yet confidently classified from available structured data.`
- Repoint safety for new vendors/sites:
  - when a site domain is changed to a different domain, stale explicit `industry` is cleared unless a new industry is provided in the same update.
  - audit-derived service/industry inference only uses audit pages that match the current site domain (old-domain pages are ignored).
  - structured display-name inference ignores embedded domain text when it does not match the current site domain.

### Service focus term behavior
- Prefers website-derived service cues from existing crawl metadata (titles, headings, service-page URL segments).
- Then uses structured category/service hints.
- Filters navigation/domain noise tokens (`home`, `about`, `contact`, `com`, `www`, TLD fragments).
- Uses domain-derived hints only as last resort.
- Keeps output compact and relevant for substitutable service intent.
- Service-focus precedence is deterministic:
  - primary source order: `site_content` -> `structured_metadata` -> `domain_hints` -> `fallback`
  - explicit `site.industry` is not blindly merged when strong current site-content signals contradict it
  - contradictory explicit industry terms are dropped from `service_focus_terms` instead of unioned
- Deterministic service hints include digital-service categories such as:
  - `seo`
  - `digital marketing`
  - `web design`
  - `web hosting`
  - `managed it services`

### Weak-context safety behavior
- If location and/or industry context is weak, prompt contract explicitly biases toward fewer high-confidence candidates instead of speculative broad matches.

## Primary Business ZIP Capture (Weak Location Context)

When location context is weak, operators can now provide a primary business ZIP code from the site workspace.

Behavior:
- ZIP capture is optional and non-blocking.
- ZIP is stored through existing site metadata update flow.
- ZIP is used only for local context enrichment in analysis (not shared externally).

Context effect:
- Saved ZIP is normalized into deterministic location text (`Serving area around ZIP code <ZIP>`).
- Competitor prompt trusted context is upgraded from weak to strong when ZIP is present.
- Prompt trusted context now also includes `site_location_context_source` so provenance can be surfaced in workspace metadata.
- This improves local competitor relevance without adding external geocoding dependencies.

## Workspace Competitor Context Health

Workspace summaries now include a deterministic `competitor_context_health` block for operator/debug visibility.

- Status values: `strong`, `mixed`, `weak`
- Check keys:
  - `location_context`
  - `industry_context`
  - `service_focus`
  - `target_customer_context`

This signal indicates how grounded competitor input context is before model execution.
It does **not** score model outputs and does not change competitor generation behavior.

## Two-Stage Candidate Quality Control

Competitor draft candidate quality now runs in two deterministic stages:

1. Eligibility gate (hard filter)
2. Admin tuning/scoring (existing settings)

### Stage 1: Deterministic eligibility gate

Before relevance scoring, candidates are filtered for obvious invalidity using deterministic checks.

Hard ineligibility reasons (internal):
- `parked_domain`
- `no_live_site`
- `weak_business_identity`
- `out_of_market`
- `excluded_domain_pattern`
- `insufficient_overlap_evidence`
- `missing_domain`
- `malformed_url`
- `missing_business_name`
- `unsupported_type`
- `invalid_confidence_score`
- `low_usefulness_unknown`

Examples:
- parked/for-sale domain pages are rejected
- probe failures or non-live landing pages are rejected
- clearly weak/no-business-identity shells are rejected
- clearly out-of-market candidates are rejected when local context is strong
- malformed/empty candidate domains are rejected with specific invalid-candidate reasons
- unsupported competitor types are rejected instead of silently accepted as high-confidence unknowns
- low-value unknown placeholders are rejected unless they meet a minimum usefulness threshold

### Stage 2: Existing admin tuning/scoring

Only eligible candidates proceed to existing business-admin tuning controls:
- minimum relevance score
- big-box mismatch penalty
- directory/aggregator penalty
- local alignment bonus

These settings still govern ranking and thresholding among plausible candidates.

Operator-facing guidance for these controls is now shown directly in the Admin panel with plain-English descriptions and “when to adjust” hints:
- raise minimum relevance if competitors look unrelated
- raise big-box mismatch penalty if large national brands dominate
- raise directory/aggregator penalty if listing sites dominate
- raise local alignment bonus if results are not local enough

### Operational behavior

- Invalid candidates are excluded before operator review lists and downstream competitor-informed flows.
- The system may return fewer candidates when viable competitors are limited.
- No external geocoding APIs are used.
- No provider/model architecture changes were introduced by this quality gate.

## Rejected Candidate Debug Visibility

For admin/debug support workflows, competitor run detail payloads can now include bounded rejected-candidate metadata:

- `rejected_candidate_count`
- `rejected_candidates[]` with:
  - `domain`
  - `reasons[]` (deterministic ineligibility taxonomy)
  - `summary` (short bounded candidate context, when available)

This visibility is additive and debug-oriented:
- it does not change eligibility decisions
- it does not change admin tuning semantics
- it does not expose raw page dumps or large fetch payloads
- it explains why fewer candidates may be returned when invalid domains are filtered out

## Candidate Pipeline Stage Telemetry (Debug)

Competitor run detail payloads can also include bounded pipeline stage counts in
`candidate_pipeline_summary`:

- `proposed_candidate_count`
- `rejected_by_eligibility_count`
- `eligible_candidate_count`
- `rejected_by_tuning_count`
- `survived_tuning_count`
- `removed_by_existing_domain_match_count`
- `removed_by_deduplication_count`
- `removed_by_final_limit_count`
- `final_candidate_count`

Stage meanings:
- `proposed_candidate_count`: normalized AI candidates before deterministic eligibility checks
- `rejected_by_eligibility_count`: removed by deterministic eligibility rules
- `eligible_candidate_count`: candidates passed into admin-tuned scoring
- `rejected_by_tuning_count`: removed by current admin tuning/threshold settings
- `survived_tuning_count`: candidates remaining after tuning exclusions, before downstream drops
- `removed_by_existing_domain_match_count`: removed because the domain already exists in known competitors
- `removed_by_deduplication_count`: removed as deterministic in-run duplicates
- `removed_by_final_limit_count`: removed only because the run requested fewer final candidates than survived
- `final_candidate_count`: actual candidates returned as reviewable drafts (matches visible draft rows)

This telemetry is a support/tuning aid only. It does not change ranking, scoring,
or competitor review workflow semantics.

## Tuning Exclusion Reason Telemetry (Debug)

Competitor run detail payloads may also include bounded tuning-stage exclusion telemetry for
candidates that passed eligibility but were removed by admin tuning/threshold behavior:

- `tuning_rejected_candidate_count`
- `tuning_rejected_candidates[]` with:
  - `domain`
  - `reasons[]`
  - optional `final_score`
  - short `summary`
- `tuning_rejection_reason_counts`

Deterministic reason codes:
- `below_minimum_relevance_score`
- `directory_or_aggregator_penalty`
- `big_box_mismatch_penalty`
- `insufficient_local_alignment`

Interpretation:
- this explains *why eligible candidates were removed by tuning*
- it does not change scoring formulas
- it does not change eligibility logic
- it is an admin/debug aid, not an end-user ranking feature

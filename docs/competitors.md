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

## Prompt Preview (Debug / Inspection)

Workspace summary responses may include an optional `competitor_prompt_preview` object so operators can inspect the final competitor-generation prompt payload used for AI calls.

### What is shown
- prompt type (`competitor`)
- model label (when available)
- prompt version (when available)
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
- When preview data is unavailable, no prompt preview block is rendered.

## Provider Request Compatibility (gpt-5-mini)

Competitor generation provider requests now apply a small model-compatibility sanitization step at the provider boundary.

- Endpoint remains `/chat/completions`.
- For `gpt-5-mini`, unsupported request parameters are removed before sending.
  - Current compatibility behavior removes `temperature`.
- For other models, existing request behavior is preserved.
- Structured `response_format` remains enabled on the current path.

## Provider Error Visibility

Competitor provider failures now emit bounded backend log metadata to improve debugging:

- HTTP status (when available)
- provider name
- model name
- provider error type/code (when provided by provider response)
- bounded provider error message

Safety:
- no secrets, auth headers, or key material are logged
- no raw environment dumps are logged

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

### Service focus term behavior
- Prefers website-derived service cues from existing crawl metadata (titles, headings, service-page URL segments).
- Then uses structured category/service hints.
- Filters navigation/domain noise tokens (`home`, `about`, `contact`, `com`, `www`, TLD fragments).
- Uses domain-derived hints only as last resort.
- Keeps output compact and relevant for substitutable service intent.

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

Examples:
- parked/for-sale domain pages are rejected
- probe failures or non-live landing pages are rejected
- clearly weak/no-business-identity shells are rejected
- clearly out-of-market candidates are rejected when local context is strong

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

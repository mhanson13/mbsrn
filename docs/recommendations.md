# Recommendations

## Optional Competitor Signal Integration

Recommendation narrative generation can consume an optional, bounded competitor context signal. This is additive and does not change deterministic recommendation artifacts or provider/model architecture.

### Competitor Fields Used
Only normalized competitor output is consumed:
- `top_opportunities` (deduped, bounded list)
- `summary` (bounded string)
- competitor `name` values (deduped, bounded list)

### Integration Rules
- Competitor signal is optional.
- If competitor data is missing or empty, recommendation generation continues with existing behavior.
- If competitor payload is malformed, no exception is raised and no competitor signal is injected.
- Normalizer fallback payloads are treated as no-signal for recommendations.

### Prompt/Context Behavior
- Competitor context is injected as a small, structured context block.
- The model is instructed to use provided competitor gaps to improve specificity.
- The model is also instructed not to invent competitor facts beyond provided context.
- Upstream competitor prompt context now prioritizes existing crawl/audit-derived site metadata (titles/headings/service-page labels) plus structured site/business metadata for location/industry/service intent, with domain-token heuristics used only as a last-resort fallback.
- Upstream competitor candidate quality now uses a deterministic eligibility gate before admin tuning/scoring, so obviously invalid parked/dead/out-of-market domains are filtered before recommendation-facing competitor context is derived.

## Admin-Managed Prompt Overrides (With Deployment Fallback)

Recommendation narrative prompt supplemental text can now be managed in persisted admin settings via:

- `ai_prompt_text_recommendations` (business-scoped admin override)

Persistence scope:
- stored on the `businesses` table as a business-level override value
- independent per business (not global/shared)

Effective prompt resolution order:

1. persisted admin override (`ai_prompt_text_recommendations`) when non-empty
2. deployment env fallback (`AI_PROMPT_TEXT_RECOMMENDATIONS`, with legacy fallback compatibility preserved)
3. existing default/empty fallback behavior

Notes:
- Admin edits affect future narrative runs and prompt previews only.
- Clearing the override reverts to deployment/default fallback behavior.
- Whitespace-only overrides are treated as unset and revert to fallback behavior.
- Prompt preview payloads now include `source` attribution (`admin_config`, `env`, `default`) for operator/debug visibility.
- Deployment manifests no longer wire deprecated legacy `AI_PROMPT_TEXT_RECOMMENDATION`; production recommendation prompt control should use persisted admin settings (and split env fallbacks only where explicitly configured by runtime).

## Admin Competitor Candidate Quality Controls (Operator Guidance)

The Admin panel includes plain-English helper guidance for the four competitor candidate tuning controls.

- `Minimum Relevance Score`:
  - Controls how closely a competitor must match your business to be included.
  - Higher values mean stricter, more relevant matches.
  - Raise this if competitors feel unrelated. Lower it if you are getting too few results.
- `Big-Box Mismatch Penalty`:
  - Reduces the chance that large national or big-box companies appear as competitors.
  - Raise this if large companies dominate your results.
- `Directory/Aggregator Penalty`:
  - Reduces listings from directories or lead sites (for example Yelp, Angi).
  - Raise this if you see too many directory or listing sites.
- `Local Alignment Bonus`:
  - Boosts competitors that are located in or serve your area.
  - Raise this if competitors are not local enough.

These controls tune ranking/thresholding among plausible candidates only. They do not override deterministic eligibility filtering.

For debugging/tuning support, competitor run-detail responses may also include bounded rejected-candidate visibility (`rejected_candidate_count`, `rejected_candidates[]` with domain + deterministic reasons + short summary). This is diagnostic only and does not affect recommendation ranking behavior.
Competitor debug payloads may also include `candidate_pipeline_summary` stage counts to show where candidates were removed:
- proposed by AI
- rejected by deterministic eligibility
- passed to tuning
- removed by tuning
- survived tuning
- removed by existing-domain suppression
- removed by deduplication
- removed by final requested-count limit
- final returned
Competitor debug payloads may also include deterministic tuning-stage exclusion reason telemetry for eligible candidates removed by tuning:
- `below_minimum_relevance_score`
- `directory_or_aggregator_penalty`
- `big_box_mismatch_penalty`
- `insufficient_local_alignment`

## Deterministic EEAT Classification (Additive)

Recommendation payloads now include deterministic EEAT metadata:

- `eeat_categories` (list)
- `primary_eeat_category` (nullable)

EEAT meaning in this product context:
- `experience`: proof of real work and outcomes
- `expertise`: visible methods, capability, and process quality
- `authoritativeness`: third-party recognition/validation
- `trustworthiness`: verifiable business legitimacy

### Classification Rules
- Classification is deterministic and additive.
- Mapping uses structured signal labels/types only (for example rule keys and structured evidence labels).
- Ambiguous/unsupported signals are omitted instead of guessed.
- No new AI calls are used for EEAT classification.

## Operator-Visible Competitor Influence

Recommendation narrative API responses now include an optional top-level field:

- `competitor_influence` (object or `null`)

When competitor signal was used, the payload shape is:

```json
{
  "used": true,
  "summary": "Recommendation specificity used normalized competitor context: ...",
  "top_opportunities": ["..."],
  "competitor_names": ["..."]
}
```

### Appearance Rules
- Present only when usable normalized competitor context exists.
- `null` when competitor context is missing/empty/no-signal fallback.
- Values are bounded, deduplicated, and safe for UI rendering.
- Content comes from normalized competitor context only (never raw malformed model output).

### Reliability Boundaries
- No new database schema or endpoint is introduced.
- No competitor parsing failure can block recommendation generation.
- Recommendations consume normalized competitor output only, never raw malformed AI text.

## Operator-Visible Action Summary

Recommendation narrative API responses now include an optional top-level field:

- `action_summary` (object or `null`)

When narrative content is strong enough, the payload shape is:

```json
{
  "primary_action": "Publish emergency service page updates for top service categories.",
  "why_it_matters": "This addresses the strongest local conversion and visibility gaps first.",
  "evidence": [
    "Emergency service pages are weaker than nearby competitors.",
    "Linked recommendation: rec-2"
  ],
  "first_step": "Publish emergency service page updates for top service categories."
}
```

### Purpose
- `action_summary` gives operators a deterministic, bounded “what to do next” view from existing narrative content.
- It does not add new AI calls and does not change recommendation generation behavior.
- It is additive and safe for existing clients.

### Appearance Rules
- Present only when narrative content has enough usable signal.
- `null` for sparse/malformed narrative sections where a safe summary cannot be derived.
- `evidence` is bounded and deduplicated (max 4 items).

### Relationship to `competitor_influence`
- `competitor_influence` explains whether competitor context influenced narrative specificity.
- `action_summary` explains the immediate operator action path.
- The two fields are separate and may coexist.

## Recommendation Signal Summary

Recommendation narrative API responses now include an optional top-level field:

- `signal_summary` (object or `null`)

Shape:

```json
{
  "support_level": "medium",
  "evidence_sources": ["site", "competitors", "references", "themes"],
  "competitor_signal_used": true,
  "site_signal_used": true,
  "reference_signal_used": true
}
```

### Deterministic Derivation
`signal_summary` is derived from existing narrative payload content only, including:
- `sections_json.summary`
- `sections_json.priority_rationale`
- `sections_json.next_actions`
- `sections_json.recommendation_references`
- `top_themes_json`
- `narrative_text`
- `competitor_influence`

No additional AI/provider calls are made.

### Support-Level Heuristic
- `high`: broad support from multiple evidence sources with rich recommendation content.
- `medium`: useful grounding from multiple signals, but not broad/rich enough for high.
- `low`: minimal usable grounding.

### Safety and Boundaries
- `signal_summary` is `null` when narrative content is too sparse/malformed to infer safely.
- `evidence_sources` is bounded, deduplicated, and uses fixed values only.
- This is additive response shaping; no persistence, schema migration, or workflow changes.

## Workspace Apply Outcome

Workspace summary responses now include an optional top-level field:

- `apply_outcome` (object or `null`)

Shape:

```json
{
  "applied": true,
  "applied_at": "2026-03-21T01:40:00Z",
  "applied_recommendation_id": "rec-123",
  "applied_recommendation_title": "Fix title tags",
  "applied_change_summary": "Minimum relevance score was updated from 35 to 30.",
  "applied_preview_summary": "Estimated increase of 2 included candidates over the last 30 days of telemetry.",
  "next_refresh_expectation": "The next completed recommendation or competitor generation run should reflect this change.",
  "recommendation_label": "Fix title tags",
  "expected_change": "Estimated increase of 2 included candidates over the last 30 days of telemetry.",
  "reflected_on_next_run": "The next completed recommendation or competitor generation run should reflect this change.",
  "source": "recommendation"
}
```

### When It Appears
- Present when a recent tuning preview event has been applied for the site.
- `null` when no applied preview metadata is available.

### Fallback Behavior
- If linkage metadata is partial, values are populated conservatively from bounded preview fields.
- If safe derivation is not possible, `apply_outcome` remains `null`.
- This is deterministic response shaping from existing data; no new AI calls, persistence, or schema changes.

### Operator-visible meaning
- `applied_recommendation_id`: linked recommendation id when deterministic linkage exists.
- `applied_recommendation_title`: recommendation title associated with the apply action.
- `applied_change_summary`: backend-authored summary of what concrete tuning change was applied.
- `applied_preview_summary`: backend-authored summary of the preview/estimated impact associated with apply.
- `next_refresh_expectation`: backend-authored message describing when operators should expect refreshed runs to reflect the change.

Backward compatibility:
- Legacy fields (`recommendation_label`, `expected_change`, `reflected_on_next_run`) remain populated for existing clients.
- Older historical payloads may omit new additive fields; UI should render safely and fall back to legacy fields.

Workspace trust roll-up:
- Workspace summary may also include `workspace_trust_summary` (see `docs/dashboard.md`), which reuses apply outcome fields alongside competitor outcome/provenance signals for a compact operator-visible trust/status strip.

## Workspace Analysis Freshness

Workspace summary responses now include an additive `analysis_freshness` object so operators can tell whether currently displayed analysis reflects the latest applied tuning changes.

Shape:

```json
{
  "status": "fresh",
  "analysis_generated_at": "2026-03-21T00:30:00Z",
  "last_apply_at": "2026-03-21T00:25:00Z",
  "message": "Analysis is up to date with the latest applied changes."
}
```

### Deterministic Status Logic
- `fresh`:
  - analysis timestamp exists, and
  - no apply timestamp exists, or analysis timestamp is newer than/equal to apply timestamp.
- `pending_refresh`:
  - analysis timestamp exists, and
  - apply timestamp exists and is newer than analysis timestamp.
- `unknown`:
  - insufficient timestamp data for safe determination.

### Timestamp Sources
- analysis timestamp: latest completed recommendation run `completed_at`
- apply timestamp: latest applied tuning preview event `applied_at`

No AI calls, thresholds, or fuzzy inference are used.

## Recommendation Progress Status (Deterministic)

Workspace recommendation rows now include additive deterministic progress metadata:

- `recommendation_progress_status`
- `recommendation_progress_summary`

Status values:
- `suggested`
- `applied_pending_refresh`
- `reflected_in_latest_analysis`

### Derivation Rules
- `suggested`:
  - no deterministic apply linkage is available for the recommendation, or
  - freshness data is unknown/insufficient for a safe reflected claim.
- `applied_pending_refresh`:
  - deterministic apply linkage exists, and
  - workspace `analysis_freshness.status == pending_refresh`.
- `reflected_in_latest_analysis`:
  - deterministic apply linkage exists, and
  - workspace `analysis_freshness.status == fresh`, and
  - `analysis_generated_at >= last_apply_at`.

This uses existing apply + freshness timestamps and linked tuning-suggestion metadata only.
No AI calls, scoring, or workflow-state persistence is added.

### Relationship to Apply Outcome + Freshness
- `apply_outcome` answers what changed at the latest apply event.
- `analysis_freshness` answers whether the latest analysis is newer than the latest apply.
- `recommendation_progress_status` applies that shared freshness truth at recommendation-row level when linkage is deterministic.

## Recommendation Lifecycle State (Deterministic, Additive)

Workspace recommendation rows now include additive lifecycle metadata:

- `recommendation_lifecycle_state`
- `recommendation_lifecycle_summary`

Lifecycle values:
- `active`
- `applied_waiting_validation`
- `reflected_still_relevant`
- `likely_resolved`

Derivation (deterministic, conservative):
- `active`:
  - recommendation is still a suggested/current action.
- `applied_waiting_validation`:
  - recommendation is applied and analysis is still pending refresh.
- `reflected_still_relevant`:
  - recommendation was reflected in fresh analysis and still has meaningful current gap/evidence signals.
- `likely_resolved`:
  - recommendation was reflected in fresh analysis and meaningful current gap/evidence signals are not present.

Notes:
- lifecycle is operator guidance only, not a workflow engine/state machine.
- `likely_resolved` is intentionally conservative and only used when deterministic support exists.

## Recommendation Action Specificity (Deterministic)

Recommendation rows now include additive deterministic action-specificity fields:

- `recommendation_action_clarity`
- `recommendation_expected_outcome`
- `recommendation_observed_gap_summary`
- `recommendation_evidence_trace`

### What They Provide
- `recommendation_action_clarity`: compact, operator-facing action wording that clarifies what to do and where it applies.
- `recommendation_expected_outcome`: compact, operator-facing wording for the likely type of improvement.
- `recommendation_observed_gap_summary`: compact deterministic summary of what the system currently sees as weak/missing.
- `recommendation_evidence_trace`: compact deterministic causal breadcrumb (evidence type, gap type, likely area).

### Derivation Rules
- Derived from existing recommendation metadata only (no new AI calls), using available fields such as:
  - `recommendation_evidence_summary`
  - `eeat_categories`
  - `priority_reasons`
  - deterministic theme metadata
  - existing recommendation title/rationale context
- Bounded and conservative (no numeric guarantees, no score language).
- Additive only; does not change recommendation generation/order semantics.
- If metadata is sparse, values fall back conservatively or are omitted.
- Observed-gap summaries are deterministic from existing recommendation/audit metadata (rule key, rationale, target context, EEAT/priority/theme, existing evidence summary) and do not use AI generation.
- Evidence trace tokens are deterministic, bounded, and deduplicated (for example: `Competitor-backed`, `Trust/verification gap`, `Contact/About`).

## Recommendation Target Context (Deterministic)

Recommendation rows now include an additive deterministic target-context field:

- `recommendation_target_context`

Bounded values:
- `homepage`
- `service_pages`
- `contact_about`
- `location_pages`
- `sitewide`
- `general`

Derivation:
- deterministic only, from existing metadata (for example `rule_key`, title/rationale, action/evidence metadata, theme/EEAT context)
- no AI page selection
- no new crawling behavior

Operator intent:
- show where a recommendation most likely applies in a compact form
- provide guidance, not a guaranteed page-level map or editing workflow

## Recommendation Target Page Hints (Deterministic)

Recommendation rows now include an additive bounded page-hint field:

- `recommendation_target_page_hints` (max 3)

Examples:
- `Homepage`
- `/services`
- `/about`
- `/contact`
- `/locations/loveland`

Derivation:
- deterministic only, from existing persisted audit page inventory plus existing `recommendation_target_context`
- no AI page selection
- no new crawling jobs
- no page-editing workflow changes

Behavior:
- hints are optional guidance, not guaranteed exact edit targets
- when audit inventory is thin or ambiguous, hints are intentionally omitted

## Recommendation Evidence Summary (Deterministic)

Recommendation rows now include additive deterministic evidence clarity metadata:

- `recommendation_evidence_summary`

### What It Is
- A short, bounded sentence that explains why a recommendation matters using existing structured metadata.
- It is deterministic and additive.
- It is not AI-generated prose and does not change ranking/order behavior.

### Derivation Order
1. competitor-backed support (`competitor_gap`, comparison/mixed evidence sources)
2. EEAT-aligned signals (`eeat_categories`)
3. structured site evidence (`audit` evidence source)
4. clear-action fallback (`high_clarity_action`) when available
5. omitted when metadata is too sparse

### Operator Intent
- Provide faster trust/readability at row level before opening recommendation detail.
- Keep copy compact and conservative (no overclaiming).

## Competitor Context Health (Deterministic)

Workspace summary responses now include additive `competitor_context_health` metadata that describes whether competitor prompt inputs are sufficiently grounded.

Shape:

```json
{
  "status": "mixed",
  "checks": [
    {"key": "location_context", "label": "Location context", "status": "weak", "detail": "..."},
    {"key": "industry_context", "label": "Industry context", "status": "strong", "detail": "..."},
    {"key": "service_focus", "label": "Service focus", "status": "strong", "detail": "..."},
    {"key": "target_customer_context", "label": "Target customer context", "status": "weak", "detail": "..."}
  ],
  "message": "Competitor matching has partial business context; results may be narrower or more conservative."
}
```

Key points:
- Deterministic and additive only (no AI generation, no scoring engine).
- Reflects **input context quality**, not model output quality.
- Uses current structured context fields (location, industry context strength, service focus terms, target customer context).
- `weak` or `mixed` means competitor results may be conservative/incomplete until location/industry/service context improves.
- ZIP/location capture continues to improve local matching context and can move health toward `strong`.

## Weak Location Context ZIP Enrichment

Workspace summary responses now include additive location-context metadata used for operator prompting:

- `site_location_context`
- `site_primary_location`
- `site_primary_business_zip`
- `site_location_context_strength` (`strong | weak | unknown`)
- `site_location_context_source` (`explicit_location | service_area | zip_capture | fallback`)

When location context is weak and no ZIP is known, the operator UI can prompt for a primary business ZIP.

Rules:
- ZIP capture is optional and non-blocking.
- ZIP is used only for deterministic local-context enrichment.
- No external geocoding or third-party location APIs are called in this step.
- Location context is assembled by a shared deterministic builder used by both competitor prompt context and workspace summary responses.

## Deterministic Priority Reasons (Additive)

Recommendation payloads now include additive deterministic ordering-clarity metadata:

- `priority_reasons` (list)
- `primary_priority_reason` (nullable)

Reason taxonomy:
- `competitor_gap`
- `trust_gap`
- `authority_gap`
- `experience_gap`
- `expertise_gap`
- `high_clarity_action`
- `pending_refresh_context` (workspace context only)
- `general` (reserved)

### Derivation Rules
- Derived from existing deterministic metadata only (no AI calls, no scoring engine).
- Examples:
  - comparison-backed evidence -> `competitor_gap`
  - EEAT categories -> matching EEAT gap reason (`trust_gap`, `authority_gap`, etc.)
  - clear imperative action title + rationale -> `high_clarity_action`
- If there is not enough safe metadata, `priority_reasons` remains empty.

These are explanation signals for operators, not numeric ranking scores.

## Workspace Ordering Explanation

Workspace summary payloads now include optional additive ordering metadata:

- `ordering_explanation`
  - `message` (short deterministic explanation)
  - `context_reasons` (bounded deterministic reason tags)

This explains why recommendations are surfaced prominently using existing deterministic metadata.
It does not introduce weighted scoring or AI prioritization.

## Deterministic Start Here (Theme Helper)

Workspace summary payloads now include an optional additive `start_here` object:

- `theme`
- `theme_label`
- `recommendation_id`
- `title`
- `reason`
- `context_flags`

Selection is deterministic and metadata-driven:
- Uses existing grouped recommendation themes when available.
- Chooses the first populated theme in deterministic theme order.
- Chooses the first recommendation in that theme while preserving existing list order.
- Falls back to flat recommendation metadata if grouped data is unavailable.

This is a guidance helper, not a score/ranking model.
No numeric weighting, AI prioritization, or persistence is added.

If `analysis_freshness.status == pending_refresh`, the helper may include contextual pending-refresh flagging, but this does not change the underlying deterministic selection.

## Deterministic Recommendation Themes and Grouping

Workspace recommendations now include additive deterministic theme metadata for operator clarity.

Recommendation-level fields:
- `theme`
- `theme_label`

Workspace-level additive grouping field:
- `grouped_recommendations`
  - `theme`
  - `label`
  - `count`
  - `recommendation_ids`

### Theme Taxonomy
- `trust_and_legitimacy`
- `experience_and_proof`
- `authority_and_visibility`
- `expertise_and_process`
- `general_site_improvement`

### Deterministic Derivation Rules
Theme assignment uses existing metadata only, in this order:
1. EEAT categories (`eeat_categories`)
2. Priority reasons (`priority_reasons`)
3. Existing deterministic text/rule metadata (bounded keyword fallback)
4. Fallback: `general_site_improvement`

No new AI calls or numeric scoring are used.

### Grouping Behavior
- Existing flat `recommendations.items` ordering is preserved.
- `grouped_recommendations` is additive and presentation-oriented only.
- Recommendation order is preserved within each theme group.
- Workspace rendering uses lightweight theme headers for the main recommendation list when multiple groups are present.
- Each grouped theme can include a deterministic summary line explaining why that theme matters before row-level actions.
- `start_here` remains compatible with grouped layouts by targeting stable recommendation IDs in the same deterministic list.
- Group sections are emitted in a stable deterministic order:
  1. Trust & legitimacy
  2. Experience & proof
  3. Authority & visibility
  4. Expertise & process
  5. General site improvement

Theme summary lines are explanatory only. They do not change recommendation ranking, scoring, or apply semantics.

## Workspace EEAT Gap Summary

Workspace summary responses may include optional `eeat_gap_summary` metadata when deterministic support exists:

```json
{
  "top_gap_categories": ["trustworthiness", "experience"],
  "supporting_signals": [
    "Recommendation: Publish license and insurance proof",
    "Competitor signal: Add verified review badges"
  ],
  "message": "Visible EEAT gaps: Trustworthiness, Experience. Competitor signals suggest these areas are weaker on the site."
}
```

Behavior:
- Derived from existing structured recommendation and competitor signal metadata only.
- Highlights visible EEAT areas that appear weaker on the site versus competitor-informed signals.
- Omitted when evidence is insufficient for deterministic classification.
- Not a numeric score and not a ranking engine.

## Prompt Preview (Debug / Inspection)

Workspace summary responses may include optional prompt-inspection metadata:

- `recommendation_prompt_preview` (recommendation narrative prompt)
- `competitor_prompt_preview` (competitor generation prompt)

Shape:

```json
{
  "available": true,
  "prompt_type": "recommendation",
  "system_prompt": "...",
  "user_prompt": "...",
  "model": "gpt-4o-mini",
  "prompt_version": "seo-recommendation-narrative-v2",
  "truncated": false
}
```

### Behavior
- Additive/read-only: no workflow or provider behavior changes.
- Uses the final constructed prompt content for inspection.
- Prompt text is sanitized and bounded for safe response/UI handling.
- If prompt preview cannot be built safely, the field is `null`/absent.

### Operator actions
- Workspace supports prompt inspection via `View AI prompt`.
- Prompt content can be copied or downloaded as `.txt`.
- Copy/download uses the same bounded safe content returned by the API.

## Recommendation Diversity and De-duplication

Recommendation narrative shaping now applies a small deterministic diversity pass to `sections.next_actions` before persistence:

- exact and near-duplicate actions are reduced
- when overlap is high, the more specific action variant is kept
- distinct action themes are preferred first, then remaining actions are filled in bounded order

### High-level Selection Behavior

- Normalize action text (trim/collapse whitespace, bounded length)
- Detect overlap with token-based near-duplicate checks
- Prefer concrete, operator-ready variants over generic phrasing
- Keep bounded output (`next_actions` remains capped and schema-compatible)

This is a clarity improvement for operators, not a confidence score or ranking engine.
No model/provider changes, schema changes, or new AI calls are introduced.

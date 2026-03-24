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
- Upstream competitor prompt context now prioritizes structured site/business metadata for location/industry/service intent, with domain-token heuristics used only as a last-resort fallback.

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
- Group sections are emitted in a stable deterministic order:
  1. Trust & legitimacy
  2. Experience & proof
  3. Authority & visibility
  4. Expertise & process
  5. General site improvement

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

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

## Competitor Prompt Context Hardening

Competitor prompt context now prefers structured business/site metadata before any heuristic fallback.

### Context source order
1. Explicit site/business metadata (`industry`, `primary_location`, `service_areas_json`, display/business names)
2. Operator-entered location/service-area/category fields already persisted on the site/business records
3. Deterministic identity hints from site metadata (for example domain labels) only when structured fields are missing

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
- Otherwise uses cautious deterministic inference from available business/site identity text.
- Falls back to:
  - `Industry not yet confidently classified from available structured data.`

### Service focus term behavior
- Prefers structured category/service hints.
- Filters domain noise tokens (`com`, `www`, TLD fragments).
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

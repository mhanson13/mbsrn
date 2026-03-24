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

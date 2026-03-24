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

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

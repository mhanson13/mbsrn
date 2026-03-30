Visibility → Leads → Jobs → Revenue

## Competitor Confidence Notes

Competitor runs now aim to return a fuller review set (up to 10) and explicitly label confidence/source:

- High confidence candidates are the primary direct competitors.
- Medium confidence candidates are secondary/adjacent competitors.
- Low confidence candidates are fallback or synthetic review items when live discovery is sparse.

Operators should treat lower-confidence entries as review-needed signals, not confirmed competitor intelligence.

## Recommendation Specificity from Competitor Evidence

Recommendation rows can now include compact competitor linkage metadata:

- `competitor_linkage_summary` (short observed gap/advantage context)
- `competitor_evidence_links` (1–3 linked competitors when available)

This makes recommendation reasoning more specific when competitor evidence exists, while sparse-market cases safely fall back to generic deterministic wording.

## From Evidence to Action Delta

When linkage quality is sufficient, recommendations include a deterministic action-delta block:

- observed competitor pattern
- observed site gap
- recommended operator action
- evidence strength

This keeps recommendations explicit and operator-actionable without introducing long AI narratives.

## Priority-first operator execution

Recommendations now expose deterministic priority metadata so operators can execute in order:

- `high`: do first (strong evidence and clear action)
- `medium`: do next (moderate evidence/actionability)
- `low`: queue for later (limited evidence or broad improvement scope)

`effort_hint` helps operators choose between quick wins and larger changes without requiring additional narrative.

## Freshness and pending-refresh interpretation

Workspace section-state indicators are deterministic and section-specific:

- competitors can be `fresh` while recommendations are `pending_refresh` (or the reverse)
- `refresh_expected=true` means a near-term completed run should materially update the displayed section
- `possibly_outdated` means data is usable for review but should be refreshed before high-confidence execution

Operators should use these states to decide whether to execute immediately or trigger a new run first.

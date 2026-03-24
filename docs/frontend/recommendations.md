# Recommendations UX

## AI Recommendations UX Layer

The site workspace surfaces recommendation data with a strict separation of concerns:

- **Deterministic recommendations** remain authoritative and are rendered in the existing deterministic recommendations table.
- **AI opportunities** are an advisory overlay rendered from existing workspace summary payload fields only.

The `AI Opportunities` section is shown only when AI-backed signals exist in the current payload, using:

- recommendation `source === "ai"` when present in payload data, or
- AI narrative/tuning fields already returned in the workspace summary (`latest_narrative`, `tuning_suggestions`).

The UI does not generate new AI text client-side and does not mutate backend workflows.

### Card Behavior

Each AI opportunity card shows:

- title
- `AI Suggested` badge
- `Why this matters` (existing narrative/suggestion text)
- `Expected outcome` derived from deterministic recommendation fields

Cards use progressive disclosure:

- collapsed: short narrative snippet + one-line expected outcome
- expanded: full narrative context + supporting signals when present

### Authority Boundary

- AI suggestions are advisory and must be reviewed.
- Deterministic recommendation artifacts remain canonical.
- No auto-apply behavior is introduced in this layer.

## Competitor Influence Visibility

When available in API payloads, recommendation narratives include an optional
`competitor_influence` object that indicates whether normalized competitor
context influenced recommendation specificity.

- This is informational and bounded for operator readability.
- It is absent/`null` when no usable competitor signal exists.
- It must not be interpreted as raw model output.

## Action Summary Visibility

Recommendation narrative payloads may also include an optional `action_summary` object:

- `primary_action`
- `why_it_matters`
- `evidence` (bounded list)
- `first_step`

Frontend guidance:
- Treat this as optional additive data.
- Emphasize `primary_action` and `first_step` visually when present.
- Keep `competitor_influence` separate from `action_summary` in presentation:
  - `competitor_influence` = context/rationale source
  - `action_summary` = concrete operator-next-step summary
- Handle sparse responses safely (`action_summary: null`) without breaking narrative rendering.

## Signal Summary Visibility

Recommendation narrative payloads may include an optional `signal_summary` object:

- `support_level`: `low | medium | high`
- `evidence_sources`: compact bounded list from `site`, `competitors`, `references`, `themes`
- `competitor_signal_used`
- `site_signal_used`
- `reference_signal_used`

Frontend guidance:
- Render this as compact framing metadata (chips/tags + small support-level badge).
- Do not overstate `support_level` as model certainty; it is deterministic grounding metadata.
- Keep it separate from:
  - `competitor_influence` (context source explanation)
  - `action_summary` (operator next-step summary)

## AI -> Action Bridge

The workspace now links AI opportunities directly to the deterministic tuning/apply loop when linkage data exists.

- **AI insight layer:** `AI Opportunities` cards
- **Action layer:** linked tuning suggestion cards
- **Validation layer:** deterministic preview output
- **Execution layer:** manual `Apply Suggestion`
- **Outcome layer:** workspace `Recent Changes` entries

### Linkage Behavior

- If an AI opportunity has a linked tuning suggestion, the card shows:
  - `Backed by tuning suggestion`
  - `View Recommended Action` to focus the linked tuning card
- Focus uses a temporary highlight so operators can see the exact action target quickly.
- If no linked tuning suggestion exists, the card remains advisory and shows:
  - `No direct action available yet.`

### Preview + Apply Traceability

- If preview data exists for a linked suggestion, the card shows:
  - `Expected impact (from preview)` summary
  - `View Preview` to jump to the linked tuning preview context
- If no preview exists yet, the card shows:
  - `Impact will be reflected in next run.`

### Frontend-only Attribution

- When an operator reaches apply through an AI opportunity linkage, the resulting local recent-change entry is tagged:
  - `From AI Recommendation`
- Attribution is frontend-session state only (non-persistent) and does not change backend contracts.

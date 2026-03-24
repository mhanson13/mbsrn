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

## Workspace Narrative Presentation

In the site workspace `AI Narrative Overlay`, render optional narrative context in this order:

1. `action_summary` as the primary operator block:
   - `Next best move` (`primary_action`)
   - `Why this matters` (`why_it_matters`)
   - `Start here` (`first_step`)
   - compact evidence chips (`evidence`)
2. `competitor_influence` as secondary rationale:
   - `Competitor-informed` label
   - short summary
   - bounded opportunities and competitor names
3. `signal_summary` as compact support framing:
   - support level
   - evidence-source tags
   - simple signal check (`site`, `competitors`, `references`)

Fallback rules:
- If optional fields are missing/null, do not render empty blocks.
- Keep legacy `narrative_text` rendering intact.
- Keep the UI concise and operator-oriented; avoid technical backend terminology.

## Prompt Inspection UX

The workspace can render optional debug prompt-inspection panels when API payloads include:

- `competitor_prompt_preview`
- `recommendation_prompt_preview`

Placement guidance:
- keep prompt inspection secondary/debug-oriented
- render near existing competitor and AI narrative metadata blocks
- hide entirely when preview payloads are absent

Interaction guidance:
- use an explicit affordance (`View AI prompt`) to reveal prompt text
- expose separate system/user prompt sections
- support:
  - `Copy Prompt`
  - `Download Prompt (.txt)`

Safety and fallback:
- treat prompt preview as read-only diagnostic data
- do not render empty placeholder containers when unavailable
- use bounded/sanitized text from the backend only
- do not expose provider secrets or environment values in UI copy

## Apply Outcome Visibility

Workspace summary payloads may include optional `apply_outcome` metadata to show what changed after manual tuning apply.

Recommended rendering:
- Show a compact secondary block near narrative/tuning context.
- Include:
  - applied state (`Applied`)
  - recommendation label (when available)
  - expected change (one sentence)
  - next-run reflection timing (one sentence)
  - applied timestamp

Rules:
- Treat `apply_outcome` as optional additive data.
- Do not render an empty container when `apply_outcome` is missing/null.
- Keep this separate from recommendation rationale fields:
  - rationale/explanation: `action_summary`, `competitor_influence`, `signal_summary`
  - post-action feedback: `apply_outcome`
- Keep copy concise and operator-friendly.

## Analysis Freshness Indicator

Workspace summary payloads can include optional `analysis_freshness` metadata:

- `status`: `fresh | pending_refresh | unknown`
- `analysis_generated_at`
- `last_apply_at`
- `message`

Rendering guidance:
- show a compact status block near recommendation apply outcome/narrative context
- keep the indicator visible but secondary (badge + short message)
- avoid large banners or modal treatment
- render timestamps only when present

State intent:
- `fresh`: current analysis reflects latest applied changes
- `pending_refresh`: changes were applied after current analysis; rerun/refresh is needed to reflect them
- `unknown`: insufficient timestamp data for safe determination

Fallback rules:
- if `analysis_freshness` is missing/null, do not render an empty placeholder
- never infer `fresh` client-side when status is absent

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

## Diversity Expectation

Recommendation narrative `next_actions` now come through a deterministic backend diversity/de-duplication pass.
Frontend rendering contracts are unchanged, but operators should generally see:

- fewer overlapping action variants
- clearer separation of distinct next moves
- preserved compatibility for `action_summary`, `competitor_influence`, and `signal_summary`

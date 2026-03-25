# Recommendations UX

## AI Recommendations UX Layer

The site workspace surfaces recommendation data with a strict separation of concerns:

- **Deterministic recommendations** remain authoritative and are rendered in the existing deterministic recommendations table.
- **AI opportunities** are an advisory overlay rendered from existing workspace summary payload fields only.

The `AI Opportunities` section is shown only when AI-backed signals exist in the current payload, using:

- recommendation `source === "ai"` when present in payload data, or
- AI narrative/tuning fields already returned in the workspace summary (`latest_narrative`, `tuning_suggestions`).

The UI does not generate new AI text client-side and does not mutate backend workflows.

## Admin Tuning Copy

The Admin page (`/admin`, with `/users` compatibility routing) now renders visible plain-English helper text under each AI competitor quality tuning field:

- Minimum Relevance Score
- Big-Box Mismatch Penalty
- Directory/Aggregator Penalty
- Local Alignment Bonus

Frontend guidance:
- Keep helper text visible (not tooltip-only).
- Keep copy concise and operator-focused.
- Preserve existing validation/saving behavior.
- Keep a clear note in operator-facing docs that these controls tune eligible-candidate ranking only and do not bypass deterministic eligibility filtering.

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

## EEAT Metadata Presentation

Recommendation/workspace payloads may include additive deterministic EEAT metadata:

- recommendation-level: `eeat_categories`, `primary_eeat_category`
- workspace-level: `eeat_gap_summary`

Frontend guidance:
- Render recommendation `eeat_categories` as compact chips near recommendation metadata.
- Render `eeat_gap_summary` as a compact secondary panel near narrative/apply/freshness context.
- Keep EEAT copy operator-friendly and non-numeric (no score treatment).
- Do not render empty EEAT containers when fields are absent/null.
- Keep existing recommendation layout intact; this is additive context only.

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
- when `site_location_context_source` is present, render a subtle provenance line such as
  `Location source: ZIP provided` inside the same compact metadata area

## Recommendation Progress Status Rendering

Recommendation rows can include additive progress metadata:

- `recommendation_progress_status`
- `recommendation_progress_summary`

Recommended row treatment:
- render a compact `Progress` line per recommendation
- show a subtle status badge:
  - `Suggested`
  - `Applied, pending refresh`
  - `Reflected in latest analysis`
- show a one-line bounded summary beneath/next to the badge

Fallback rules:
- if progress fields are missing, safely fall back to `Suggested` copy
- do not infer reflected state from UI-only heuristics
- rely on backend-provided deterministic status, which is aligned to workspace `analysis_freshness`

## Recommendation Evidence Summary Rendering

Recommendation rows can include optional additive evidence clarity text:

- `recommendation_evidence_summary`

Rendering guidance:
- display as a compact row-level line (for example, `Why this matters: ...`)
- keep it subtle and near existing row metadata (`Why surfaced`, `Progress`, EEAT chips)
- render only when present; no empty placeholders

Behavior guidance:
- treat this as deterministic metadata derived from existing structured fields
- do not treat it as a score or confidence metric
- keep grouped layout, start-here behavior, and apply controls unchanged

## Recommendation Action Specificity Rendering

Recommendation rows may include additive deterministic operator-guidance fields:

- `recommendation_action_clarity`
- `recommendation_expected_outcome`
- `recommendation_observed_gap_summary`

Rendering guidance:
- render as compact row-level lines:
  - `Observed gap: ...`
  - `Action: ...`
  - `Expected outcome: ...`
- keep them near existing row metadata (`Why surfaced`, `Progress`, `Why this matters`, EEAT chips)
- keep copy concise and operator-friendly
- do not treat these lines as guarantees or score/confidence output

Fallback rules:
- if optional action/outcome/observed-gap fields are missing/null, hide them cleanly
- if observed-gap text exactly duplicates `recommendation_evidence_summary`, suppress the duplicate line to avoid row noise
- avoid empty placeholders
- preserve grouped layout, start-here behavior, and apply controls

## Recommendation Target Context Rendering

Recommendation rows may include additive deterministic target context:

- `recommendation_target_context`

Supported values:
- `homepage`
- `service_pages`
- `contact_about`
- `location_pages`
- `sitewide`
- `general`

Rendering guidance:
- display as a compact row-level line, for example `Where: Service pages`
- keep it subtle and near action/outcome/evidence metadata
- hide cleanly when field is missing/null

Notes:
- target context is operator guidance only
- it is deterministic metadata, not AI-selected page mapping
- it does not introduce editing workflow or page-level task orchestration

## Recommendation Target Page Hint Rendering

Recommendation rows may include additive deterministic page hints:

- `recommendation_target_page_hints` (bounded list, max 3)

Rendering guidance:
- display as a compact row-level line, for example `Likely pages: Homepage, /services`
- keep it subtle and near `Where`, `Action`, and `Expected outcome`
- render only when hints are present

Notes:
- hints are derived from existing persisted audit inventory and target context metadata
- hints are operator guidance only, not guaranteed exact page mappings
- when inventory is sparse/ambiguous, omit the line instead of guessing

## Competitor Context Health Indicator

Workspace summary payloads can include optional `competitor_context_health` metadata:

- `status`: `strong | mixed | weak`
- `checks[]`:
  - `location_context`
  - `industry_context`
  - `service_focus`
  - `target_customer_context`
- `message`: short deterministic summary

Rendering guidance:
- show as a compact secondary block near analysis/apply metadata
- display overall status + per-check status/details
- keep tone operator-friendly and diagnostic, not alarming
- hide the block entirely if metadata is absent

Interpretation guidance:
- this reflects input context quality for competitor matching, not model certainty or scoring
- `weak`/`mixed` indicates results may be conservative until location/industry/service context is improved

## Rejected Competitor Candidates (Debug)

When competitor run detail payloads include rejected-candidate metadata, the workspace can render a compact debug block in the AI Competitor Profiles area:

- total rejected candidate count
- bounded rows with domain
- deterministic reason badges
- short summary text

Rendering rules:
- hide the block entirely when rejected-candidate debug metadata is absent or empty
- keep the block secondary/debug-oriented (not a primary operator alert)
- cap displayed rows and show `showing X of Y` when payload count exceeds rendered rows

## Candidate Pipeline Stage Counts (Debug)

When `candidate_pipeline_summary` is present on competitor run detail payloads, the
workspace can render a compact debug block with:

- proposed candidates
- rejected by eligibility
- eligible after filtering
- removed by tuning
- survived tuning
- removed by existing-domain match
- removed by deduplication
- removed by final limit
- final returned

Rendering rules:
- keep this in the existing debug area near rejected-candidate details
- hide the block when summary data is missing
- treat counts as observability/support data only (not ranking or scoring UX)

## Tuning Exclusion Reasons (Debug)

When competitor run detail payloads include tuning-stage exclusion telemetry, the workspace can render a compact debug block for candidates that passed eligibility but were removed by tuning.

Recommended elements:
- `Removed by tuning (debug)` count
- reason-count summary chips/text
- bounded candidate rows (domain, deterministic reason badges, optional final score, short summary)

Deterministic reason codes:
- `below_minimum_relevance_score`
- `directory_or_aggregator_penalty`
- `big_box_mismatch_penalty`
- `insufficient_local_alignment`

Rendering rules:
- keep this in the same debug area as rejected candidates and pipeline summary
- hide when tuning telemetry is absent/empty
- cap displayed rows and show `showing X of Y` when payload count exceeds rendered rows
- treat this as tuning/support telemetry only (not operator ranking guidance)

## Weak Location Context ZIP Prompt

When workspace summary metadata indicates weak location context and no stored ZIP:

- `site_location_context_strength === "weak"`
- `site_primary_business_zip` is empty/null

the site workspace can show a compact, non-blocking ZIP prompt modal:

- title: `Where do you primarily do business?`
- input: 5-digit ZIP
- actions:
  - `Save` (patches site metadata)
  - `Skip for now` (dismisses for the current session)

Rendering/behavior guidance:
- show once per session per site unless saved
- hide when ZIP exists or context is no longer weak
- keep failures non-blocking with retry/skip
- location provenance labels should stay subtle and hidden when source metadata is absent

## Deterministic Priority Reason Visibility

Recommendation rows can include additive deterministic reason chips from:

- `priority_reasons`
- `primary_priority_reason`

Display guidance:
- render as compact “Why surfaced” chips near existing recommendation metadata
- keep this secondary to title/rationale
- hide the block entirely when no reasons are present
- treat reasons as explanation signals, not scores

## Deterministic Theme Grouping

Workspace summary payloads may include additive grouped recommendation metadata:

- `grouped_recommendations[]`
  - `theme`
  - `label`
  - `count`
  - `recommendation_ids[]`

Recommendation rows can also include:
- `theme`
- `theme_label`

Rendering guidance:
- Keep the existing recommendation list semantics intact.
- Use lightweight section headers when there are multiple groups.
- Show compact label + count (`Trust & legitimacy`, `Experience & proof`, etc.).
- Show one concise deterministic summary line under each theme header to explain theme intent before row-level actions.
- Preserve row ordering within each group based on incoming flat recommendation order.
- If grouped metadata is absent or only yields a trivial single section, avoid noisy wrappers.
- Keep stable recommendation row IDs so `Start here` jump-to actions still focus the correct row in grouped sections.
- Treat grouping as operator clarity metadata only, not ranking/scoring.

## Workspace Ordering Explanation

Workspace summary payloads can include optional:

- `ordering_explanation.message`
- `ordering_explanation.context_reasons`

Display guidance:
- show a compact “Why this order” block near latest-run metadata
- keep copy short and deterministic
- avoid empty placeholders when field is null/absent
- avoid language that implies weighted/AI scoring

## Deterministic Start Here (Theme Helper)

Workspace summary payloads may include optional `start_here` metadata for a compact operator helper:

- `theme`, `theme_label`
- `recommendation_id`, `title`
- `reason`
- optional `context_flags`

Rendering guidance:
- show as a compact secondary helper near Top Insights
- keep it additive and non-banner-like
- use it as “where to begin” guidance, not a ranking score
- allow a simple jump-to-recommendation action when practical
- hide the block entirely when `start_here` is missing/null

Behavior notes:
- helper selection is deterministic from existing grouping/order metadata
- pending-refresh context may be shown via subtle badges/labels when present in `context_flags`
- grouped recommendation rendering and `Start here` jump behavior are designed to work together without changing recommendation order semantics

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

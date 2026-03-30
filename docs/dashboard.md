## Operator Shell v4

The workspace now uses an Operator Shell v4 presentation pass inspired by compact admin-console patterns.
This is a UI/readability enhancement only. Backend behavior, API contracts, trust semantics, and workflows are unchanged.

### Visual changes
- Compact top summary strip (`Workspace Snapshot`) with quick status cards for competitor state, recommendation state, actionable count, and readiness context.
- Workspace snapshot now also includes Google Business Profile integration visibility (`Connected and usable`, `Action needed`, `Not connected`, or `Status unavailable`) with a direct link to `/business-profile`.
- Standardized section header treatment for major workspace sections with:
  - title + subtitle rhythm
  - compact metadata
  - right-aligned primary actions where relevant
- Visual-token normalization across the workspace for:
  - spacing rhythm
  - typography hierarchy
  - section/card/table density
  - badge/status family consistency
- Denser table/list rhythm for faster scanability in operator workflows.
- More consistent badge/chip emphasis for trust, freshness, and warning states.
- Tighter toolbar layout above generation/review surfaces, including the synthetic scaffold filter row.
- Improved section-to-section visual balance so summary, insights, and detail areas feel related without changing behavior.
- Workflow emphasis updates:
  - a primary operator-focus zone near the top of the workspace
  - stronger “what changed recently” visibility
  - clearer “what to do next” emphasis in action-oriented sections
  - de-emphasized historical/reference sections while preserving readability

### Behavior guarantees
- No filtering, trust, acceptance, or generation logic changed by this pass.
- `Hide synthetic scaffolds` remains visibility-only and never removes data from API/state.
- Recommendation apply outcome and trust/freshness indicators remain authoritative and deterministic.
- Google Business Profile state visibility is presentation-only in the workspace and reuses existing integration connection semantics (no OAuth/token behavior changes).
- Recommendations now include a compact **Recently applied recommendation** outcome block that surfaces what changed, current apply visibility state (`Applied / completed` or `Needs review / pending`), and expected impact timing.

## Recommendation Presentation v1

Recommendation rows now include a compact presentation layer focused on operator action state clarity.

### Bucketed recommendation view
- `Ready to act`
- `Applied / completed`
- `Needs review / pending`
- `Informational`

These are deterministic UI buckets derived from existing recommendation status/progress/lifecycle/priority fields.
They do not change backend recommendation scoring, generation, or persistence semantics.

### Action-state clarity
- Each bucket row now surfaces:
  - recommendation title
  - short action/rationale cue
  - explicit state badge
  - progress/lifecycle/priority badges
- Applied recommendations stay visible but are visually separated from “do this now” items.
- Informational recommendations remain visible with lighter emphasis.

## Recommendation Detail Clarity v2

Recommendation rows and bucket cards now render a compact deterministic detail block to improve actionability at a glance.

### Per-item clarity structure
- `Observed pattern`
- `Gap to close`
- `Recommended action`
- `Supporting context`

These fields are derived from existing deterministic recommendation metadata (`recommendation_action_delta`, evidence summary/trace, target context, and expected outcome). No recommendation generation or scoring behavior changes.

### Presentation behavior
- `Recommended action` is visually emphasized inside each item for faster operator scanning.
- Applied/completed items remain visible but with lower-emphasis clarity styling than “ready to act” items.
- When structured clarity metadata is absent, the UI falls back to existing grounded recommendation summaries.
- The deterministic recommendation table/list remains intact for full detail access.

## Workspace Copy + Label Tuning v1

Workspace recommendation copy now uses more operator-natural language while preserving all existing trust/status semantics and deterministic behavior.

### What changed
- Recommendation section heading is now `Recommendations`.
- Bucket copy was tuned for faster scanning:
  - `Ready now`
  - `Applied / completed`
  - `Needs review / pending`
  - `Informational`
- Detail-clarity labels were tuned to operator language:
  - `What we observed`
  - `What needs improvement`
  - `What to do next`
  - `Why this is recommended`
- Focus-zone and helper copy were tuned for direct action phrasing (for example, `Operator Focus`, `Next best step`, `Latest change`).

### Behavior guarantees
- This is presentation-only copy tuning.
- Recommendation generation, scoring, status semantics, trust tiers, and API contracts are unchanged.

## Recommendation Apply Outcome Visibility v1

The recommendations section now surfaces a compact, operator-facing apply outcome card when apply metadata is available.

It highlights:
- which recommendation was applied
- what changed
- whether the change is `Applied / completed` or `Needs review / pending`
- when visibility is expected to update (`Expected visibility: ...`)

If no apply metadata exists, the card is hidden (no placeholder noise). This is a presentation-only enhancement and does not change apply semantics.

## Workspace Trust Summary

The site workspace now includes a compact trust/status strip that rolls up the latest operator-relevant signals across competitor generation and recommendation apply actions.

### Purpose
- Show what happened most recently without opening debug sections.
- Make fallback/recovery behavior visible and explicit.
- Surface whether nearby seed discovery contributed to the latest competitor run.
- Confirm recent recommendation apply context and expected refresh timing.

### Fields shown to operators
- `latest_competitor_status` (`normal` | `recovered` | `degraded` | `failed`)
- `used_google_places_seeds` (`true`/`false` when known)
- `used_synthetic_fallback` (`true`/`false` when known)
- `latest_recommendation_apply_title`
- `latest_recommendation_apply_change_summary`
- `next_refresh_expectation`
- `freshness_note`

### Composition rules
- Uses backend-authored deterministic mappings only.
- Reuses existing competitor outcome summary and recommendation apply outcome data.
- Does not expose provider/debug internals.
- Renders partially when only some fields are available.
- Stays hidden when no meaningful trust fields are present.

## Section Freshness Indicators

Workspace responses also include compact section-level freshness indicators so operators can quickly judge whether each area is current:

- `competitor_section_freshness`
- `recommendation_section_freshness`

Each object includes:
- `state`: `fresh` | `pending_refresh` | `running` | `stale`
- `message`: short deterministic backend-authored explanation
- `state_code`: `fresh` | `pending_refresh` | `running` | `stale` | `possibly_outdated`
- `state_label`: operator-ready label
- `state_reason`: concise deterministic reason
- `evaluated_at`: timestamp used for this section-state evaluation (when available)
- `refresh_expected`: whether a near-term run is expected to update the section

### Meaning
- `fresh`: section reflects the latest completed signals for that workflow.
- `pending_refresh`: newer applied changes exist and next completed run should reflect them.
- `running`: a run is currently in progress for that section.
- `stale`: no completed run is available yet, a recent failure/degraded result needs refresh, or freshness cannot be confirmed safely.
- `possibly_outdated`: section may be showing older results and should be refreshed soon.

These indicators complement `workspace_trust_summary`:
- `workspace_trust_summary` = compact cross-workspace trust roll-up
- section freshness = per-section “is this current right now?” signal

## Competitor Confidence Tiers

Competitor generation now targets up to 10 candidates with tiered operator labels:

- `confidence_level=high`: strongest direct/near-direct competitors.
- `confidence_level=medium`: adjacent or lower-signal competitors worth review.
- `confidence_level=low`: fallback/synthetic review candidates used to avoid sparse output.

Each competitor also includes `source_type`:

- `search`: provider-discovered candidates
- `places`: nearby-business seeded and AI-enriched candidates
- `fallback`: deterministic fallback candidates derived from candidate overflow
- `synthetic`: deterministic local-context synthetic placeholders

Synthetic presentation notes:
- Synthetic rows are review scaffolds, not verified discovered businesses.
- Placeholder domains are intentionally non-real and may render as "No verified website (review scaffold)" in the workspace.
- Synthetic rows require explicit operator confirmation before acceptance.
- Workspace includes a `Hide synthetic scaffolds` toggle in the AI Competitor Profiles table.
- The toggle defaults ON when at least 5 non-synthetic drafts exist for the current run, otherwise defaults OFF.
- This is a visibility filter only; synthetic rows remain available and can be shown again instantly.
- Synthetic rows support two explicit promotion paths:
  - `Accept` (verified): requires a verified website/domain.
  - `Accept as unverified (no website)`: promotes scaffold with an unverified marker.
- Accepted unverified scaffolds are labeled in the draft table as **Accepted as unverified competitor**.
- When duplicate/low-value synthetic variants are suppressed, synthetic fallback may return fewer rows than the target count.

## Competitor Evidence + Recommendation Linkage

Workspace now surfaces lightweight competitor evidence in two places:

- Per competitor draft:
  - confidence/source badges (`confidence_level`, `source_type`)
  - deterministic `operator_evidence_summary` line
- Per recommendation:
  - optional `competitor_linkage_summary`
  - optional `competitor_evidence_links` (up to 3 linked competitors)

This keeps recommendation rationale compact and evidence-based without exposing raw provider/debug payloads.

Trust boundary note:
- Website-backed downstream evidence uses verified competitors only (`verification_status=verified`).
- Accepted competitors marked `unverified` remain visible to operators in management flows but are excluded from trusted recommendation-linkage evidence.
- Recommendation linkage rows now expose explicit trust tiers via `competitor_evidence_links[].trust_tier`:
  - `trusted_verified`
  - `informational_unverified`
  - `informational_candidate`
- Workspace labels map these to compact operator wording:
  - `Verified competitor`
  - `Unverified competitor`
  - `Candidate competitor`

## Recommendation Action Delta

When competitor linkage is strong enough, recommendation rows now include a compact deterministic
`recommendation_action_delta` summary:

- `observed_competitor_pattern`
- `observed_site_gap`
- `recommended_operator_action`
- `evidence_strength` (`high` | `medium` | `low`)

This complements (not replaces) competitor linkage lines. Sparse/low-signal rows omit action-delta instead of over-claiming.

## Recommendation Priority Tier

Workspace recommendation rows now include deterministic `recommendation_priority` metadata:

- `priority_level` (`high` | `medium` | `low`)
- `priority_reason` (short operator-facing rationale)
- `effort_hint` (`quick_win` | `moderate` | `larger_change`)

UI uses this tier as a compact “what to do first” signal and can sort rows by tier while preserving stable order inside each tier.

TOP ROW
-------
Leads Today
Avg Response Time
Jobs Won This Month
Revenue From Marketing

PANEL 1 - LEADS
---------------
New Leads
Leads Awaiting Response
Appointments Scheduled
Lead Aging

PANEL 2 - VISIBILITY
--------------------
Google Reviews
Rating
Top Search Terms
AI / Answer Readiness Score

PANEL 3 - COMPETITION
---------------------
Top 3 Competitors
Review Gap
Rating Gap
Visibility Gap

PANEL 4 - BUSINESS MATH
-----------------------
Marketing Spend
Leads Generated
Jobs Won
Average Job Value
Cost Per Job
Return on Marketing

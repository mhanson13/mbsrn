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

## Operator Shell v4

The workspace now uses an Operator Shell v4 presentation pass inspired by compact admin-console patterns.
This is a UI/readability enhancement only. Backend behavior, API contracts, trust semantics, and workflows are unchanged.

## Shared Role-Aware Shell Uplift

The dashboard shell treatment now applies across admin, operator, and user-facing workspace entry surfaces.
This uplift is frontend-only and reuses the existing CSS/component system.

Shared grammar now includes:
- role-aware dashboard landing surfaces (`role-dashboard-landing`, `role-dashboard-hero`)
- reusable panel hierarchy via `SectionCard` variants (`primary`, `summary`, `support`, `emphasis`)
- reusable heading hierarchy via `SectionHeader` variants (`hero`, `focus`, `support`)
- summary strips with elevated status cards via `SummaryStatCard` variants
- consistent badge/state presentation across admin/operator/user pages

Role behavior remains unchanged:
- admin pages remain supervisory/management focused
- operator pages remain workflow/action focused
- user-facing task pages remain simpler and status-oriented

## Phase-2 Cross-Route Consistency

The shared shell language now extends beyond primary landing/workspace routes into high-traffic secondary operator routes:
- `audits`
- `automation`
- `competitors`
- `recommendations`

These routes now reuse the same shared hero/header/panel/stat primitives and support-state treatment.

### Standardized support states

Loading, error, empty/no-site, and no-data states on the upgraded secondary routes now use consistent support-surface framing:
- concise heading + subtitle structure via shared section headers
- calmer panel treatment matching role-dashboard surfaces
- compact action guidance copy where appropriate

This remains a presentation-only pass; route behavior and backend semantics are unchanged.

## Phase-3 Detail-Route Consistency

The shared shell/panel/header language now extends into deeper, high-traffic detail routes so the experience stays consistent after navigating past list pages.

Primary detail routes uplifted in this pass:
- `audits/[run_id]`
- `competitors/[set_id]`
- `competitors/snapshot-runs/[run_id]`
- `competitors/comparison-runs/[run_id]`
- `recommendations/[id]`

### What was standardized
- top-of-page detail hero framing now uses shared `SectionHeader` + summary-stat strip patterns
- detail pages use stronger summary-before-detail composition
- loading/error/missing-id entry states use shared support-surface framing
- cross-role secondary surfaces (`dashboard`, `business-profile`) now use the same support-state panel treatment

This remains presentation-only. No backend behavior, trust semantics, or workflow logic changed.

## Phase-4 Recommendation Run + Narrative Route Consistency

Recommendation-run workflow detail routes now use the same upgraded shared shell language already applied to primary workspace and detail pages:
- `recommendations/runs/[run_id]`
- `recommendations/runs/[run_id]/narratives`
- `recommendations/runs/[run_id]/narratives/[narrative_id]`

### What was standardized
- shared hero framing with summary-before-detail context
- elevated summary strips for run/narrative context cues
- consistent support-state panels for loading, tenant-context errors, missing identifiers, and no-data branches
- stronger visual continuity between recommendation queue, run detail, narrative history, and narrative detail pages

This remains a presentation-only pass. Recommendation generation, lineage semantics, and apply behavior are unchanged.

## Workflow Context + Cross-Route Navigation Clarity

Deep workflow routes now include a consistent context panel so operators can immediately see:
- where they are in the workflow hierarchy
- which parent run/set/detail surface they came from
- the most relevant adjacent next step

Updated deep-route flows include:
- `audits/[run_id]`
- `competitors/[set_id]`
- `competitors/snapshot-runs/[run_id]`
- `competitors/comparison-runs/[run_id]`
- `recommendations/[id]`
- `recommendations/runs/[run_id]`
- `recommendations/runs/[run_id]/narratives`
- `recommendations/runs/[run_id]/narratives/[narrative_id]`

### Operator-visible behavior
- each route now presents compact, workflow-context back links near the top
- parent/child lineage is explicit before deep detail sections
- a concise next-step cue is included when deterministic route context supports it

This is a navigation/context continuity improvement only. Route behavior, backend APIs, and workflow semantics are unchanged.

## Detail Density + Scanability Refinement

Deep recommendation and competitor detail routes now include a compact summary-first focus block between workflow context and full-detail sections.

### What operators see
- a short **top takeaway** before dense tables/metadata
- a clear **likely next action** with direct route context
- a concise **where detail lives** cue to orient scanning

### Where it applies
- recommendation detail and recommendation run/narrative detail routes
- competitor set, snapshot-run, and comparison-run detail routes

This remains presentation-only. No trust semantics, recommendation/competitor logic, or API behavior changed.

### Shared visual system uplift
The operator shell now applies a stronger shared admin-console frame across workspace surfaces using the existing CSS/component system:
- upgraded shell/page chrome layering via shared `NavShell` + main container framing
- reusable `SectionCard` variants (`primary`, `summary`, `support`, `emphasis`) for consistent panel hierarchy
- reusable `SectionHeader` variants (`focus`, `support`, `hero`) for clearer title/subtitle/meta rhythm
- reusable `SummaryStatCard` variants (`elevated`, `focus`) for top-strip status readability
- tighter badge/state consistency and refined panel depth treatment for clearer scanability

These are presentation-only upgrades. No workflow logic, trust semantics, or backend behavior changed.

### Operator Focus priority order
The top-of-workspace **Operator Focus** block now shows a single deterministic next step using existing workspace state:
1. Google Business Profile not connected
2. Google Business Profile action/reconnect required
3. High-value recommendation in `Ready now`
4. Recently applied recommendation pending visibility
5. Freshness review needed (stale/possibly outdated/status unavailable)
6. No immediate action needed

Operator Focus always includes:
- one primary action title
- one concise reason
- one direct action control (navigate or focus)

### Visual changes
- Compact top summary strip (`Workspace Snapshot`) with quick status cards for competitor state, recommendation state, actionable count, and readiness context.
- Workspace snapshot now also includes Google Business Profile integration visibility (`Connected and usable`, `Action needed`, `Not connected`, or `Status unavailable`) with a direct link to `/business-profile`.
- Workspace snapshot now includes compact automation visibility (`workspace-summary-automation`) showing latest lifecycle status, trigger source, and outcome cue from existing automation read endpoints.
- Summary tab also includes a compact automation outcome block (`Automation status and outcomes`) with deterministic "what happened" and "what next" signals, plus links to:
  - automation run history (`/automation`)
  - linked recommendation run/narrative output when output ids are present
- Recommendation and automation sections now align on compact operator action-state cues:
  - one action-state badge
  - one outcome cue
  - one next-step cue
  - deterministic wording based on existing read-model data only
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
- Automation visibility is presentation-only and read-model based; it does not change automation execution/orchestration semantics.
- Recommendations now include a compact **Recently applied recommendation** outcome block that surfaces what changed, current apply visibility state (`Applied / completed` or `Needs review / pending`), and expected impact timing.

## Workspace Content Tabs

The site workspace now uses lightweight sub-tabs to keep the default page focused on decisions/actions:
- `Summary` (default): operator focus + compact audit/competitor status signals.
- `Recommendations`: recommendation queue and recommendation run/narrative decision surfaces.
- `Activity`: full operational history surfaces including **Site Activity Timeline**, **Recent Audit Runs**, and detailed competitor readiness history tables.

This is a placement/priority update only. Timeline data, filtering, and rendering semantics are unchanged.

## AI Competitor Profiles Structured Review

The AI Competitor Profiles workspace section now uses the same structured rhythm as recommendation surfaces:
- compact summary strip (candidate totals/state counts)
- primary candidate pipeline table (`Stage`, `Count`, `Description`)
- competitor draft review table
- secondary debug/details region for prompt inspection, provider attempts, and rejected candidate diagnostics

This is a presentation/layout update only. Competitor generation behavior and trust semantics are unchanged.

## Shared Operational Item Pattern + Layout Width Modes

Operator data-dense pages now share a compact operational item pattern for faster scanability:
- summary-first card header (item identity + status chips)
- short why-it-matters line
- visible primary action
- optional expandable detail for deeper evidence/timestamps/debug context

This pattern is now used on:
- recommendations (queue quick scan)
- competitors (set quick scan)
- audits (run quick scan)
- automation (run quick scan)

Layout width is now explicitly controlled with frontend container modes:
- `default`: existing baseline width
- `wide`: reduced side margins for dense list/table pages
- `full`: near edge-to-edge (with safe padding) for highest-density workspace pages

Current usage:
- recommendations, competitors, audits, automation: `wide`
- site workspace (`/sites/[site_id]`): `full`
- dashboard remains `default` for concise landing readability
- business profile and admin now follow the same `wide` operator-shell convention
- future operator-shell pages default to `wide` unless explicitly marked `default` or `full`

### Site workspace dense-row cleanup
- Recommendation rows in the site workspace detailed tables now use a bounded two-area layout:
  - left: primary narrative/action context
  - right: grouped support metadata/status rail
- The support rail keeps progress/lifecycle/priority/context chips visually connected to the row instead of floating in long text blocks.
- This is presentation-only; recommendation semantics and trust logic are unchanged.

This remains presentation-only and does not change trust semantics, business logic, or API behavior.

## UI Consistency Cleanup Rules (Frontend-Only)

The operator workspace now enforces three shared presentation rules across recommendations, competitors, audits/activity, automation, and site workspace surfaces:

1. Expanded detail rendering rule
- Compact summary rows stay inside tables/grids.
- Expanded detail must render in a full-width bounded panel outside row/column constraints.
- Use the existing bounded panel/card treatment for expanded content.

2. Left vs right content rule
- Left side carries narrative/action explanation.
- Right side is signals-only (status chips, compact metadata, IDs/counts).
- Avoid duplicating or restating left-side natural-language rationale in the right rail.

3. Dropdown/select standardization rule
- Use one consistent select style/behavior pattern for operator pages.
- Keep full-width alignment, consistent control height/padding/border/focus treatment, and safe layering behavior.
- Apply the shared pattern consistently across dense operator surfaces (sites workspace, recommendations, competitors, audits/activity, automation) and related admin/business-profile controls when they use the same shell.
- Option-row hover/selected highlighting now fills the intended menu row width more consistently across shared `operator-select` controls.

4. Site inventory action affordance rule
- Primary workspace navigation from site inventory should use the same inline button treatment as other operator actions.
- `Open Workspace` now follows the shared button-action family used by controls like `Run Audit Again`.

This is a presentation-only refinement and does not alter backend APIs, trust semantics, or business logic.

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

## Recommendation Queue Scanability (Progressive Disclosure)

Recommendation queue rows now prioritize quick operator decisions in the collapsed view:
- actionability, effort, and blocker badges
- one-line `Why now` summary

Deeper rationale (full why-now, blocking detail, after-action timing, evidence/support cue, and revisit guidance) moves into per-row `View details` expansion.

This is a presentation-only density reduction. Recommendation logic and API semantics are unchanged.

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

## Recommendation Outcome Auditability + Scanability

Recommendation-facing pages now use a consistent summary-first outcome snapshot so operators can quickly answer:
- was this applied
- what changed
- does anything still require me
- when should I expect visibility
- where do I go next

Updated surfaces:
- `dashboard` (outcome visibility guidance)
- `recommendations` queue (outcome snapshot before queue controls)
- `recommendations/[id]` detail (recommendation outcome snapshot)
- `recommendations/runs/[run_id]` detail (run outcome snapshot)

Decisiveness cues are now aligned across dashboard and recommendations:
- `High-value next step`
- `Ready now`
- `Waiting on visibility`
- `Manual follow-up required`
- `Review before applying`

Queue rows and summary snapshots now also surface:
- why this recommendation is emphasized now
- whether action can be taken now
- what is currently blocking progress (if anything)
- comparative choice support (`Best immediate move`, `Quick win`, `More involved`, `Lower-immediacy background item`)
- lifecycle-stage visibility (`Needs review / pending`, `Applied / completed`, `Background item / revisit later`)
- compact revisit guidance (`Revisit now`, `Revisit after visibility refresh`, or `Ignore for now unless context changes`)
- freshness/review posture (`Fresh enough to act`, `Review soon`, `Pending refresh`, `Possibly outdated`)
- refresh check guidance (`No refresh required before acting`, `Refresh likely needed before acting`, or deferred refresh guidance)
- the next operator action
- what happens after action / expected visibility timing
- one compact evidence preview line with trust-safe support wording

This is presentation-only. Recommendation generation, apply behavior, trust semantics, and API contracts are unchanged.

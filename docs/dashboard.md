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

### Meaning
- `fresh`: section reflects the latest completed signals for that workflow.
- `pending_refresh`: newer applied changes exist and next completed run should reflect them.
- `running`: a run is currently in progress for that section.
- `stale`: no completed run is available yet, a recent failure/degraded result needs refresh, or freshness cannot be confirmed safely.

These indicators complement `workspace_trust_summary`:
- `workspace_trust_summary` = compact cross-workspace trust roll-up
- section freshness = per-section “is this current right now?” signal

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

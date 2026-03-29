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

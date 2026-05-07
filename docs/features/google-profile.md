# Google Profile (Operator Surface)

## Purpose
Google Profile is the consolidated operator surface for Google integrations.

Primary route:
- `/google-profile`

Compatibility route:
- `/business-profile` (label compatibility only; user-facing naming is Google Profile)
- Compatibility route behavior:
  - `/business-profile` remains bookmark-safe
  - top navigation and workspace labels still resolve to `Google Profile`

## What lives here
- Google Profile connection/reconnect state
- location verification workflow state
- GA4 property setup for the selected site
- compact GA4 property health for the selected site
- site-wide migration analytics insertion rules (`enabled`, measurement id, insertion mode)

GA4 setup and analytics insertion rules were intentionally moved out of the site workspace/migration route so execution surfaces stay focused on migration and recommendation actions.

## GA4 Property Health (Phase 1)

Google Profile now shows a compact, site-scoped GA4 health strip for the currently selected site.

Health states are bounded and operator-safe:
- Not configured
- Configured
- Reachable
- No recent data
- Permission issue
- Invalid property
- Temporarily unavailable
- Unknown

Operator guidance is shown inline with short next actions (for example, add a property ID, verify GA4 read access, or retry when temporarily unavailable).

Permission failures are normalized as `permission_denied` with operator-safe messaging.

Boundary:
- health is derived from the selected site property only
- no global/default GA4 property fallback is used for site health
- no tokens/credentials/raw Google error payloads are exposed

## Boundary
- No secrets or credential values are exposed in UI.
- Connection/auth semantics are unchanged; this is placement + labeling consolidation.
- Site workspace links to Google Profile for integration setup instead of embedding GA4 connect controls.

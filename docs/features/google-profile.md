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

GA4 setup was intentionally moved out of the site workspace so migration/recommendation workflow surfaces stay focused on execution.

## Boundary
- No secrets or credential values are exposed in UI.
- Connection/auth semantics are unchanged; this is placement + labeling consolidation.
- Site workspace links to Google Profile for integration setup instead of embedding GA4 connect controls.

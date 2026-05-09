# Google Profile (Sites Setup)

## Purpose
Google setup is site-scoped and now lives under `Sites` in the selected-site setup panel.

Primary setup route:
- `/sites` (Selected Site Setup > Google & Analytics)

Compatibility routes:
- `/google-profile`
- `/business-profile`

Compatibility behavior:
- both legacy routes show a moved notice and redirect to `/sites`
- query params are preserved
- when `site_id` is present, redirect targets include `#selected-site-setup`

## What the selected-site setup panel owns
- Google Profile connect/reconnect/disconnect/refresh state
- Google Business Profile locations/status
- GA4 property setup for the selected site
- compact GA4 property health and next-action guidance
- site-wide migration analytics insertion rules (`enabled`, measurement ID, insertion mode)

## Boundaries
- setup ownership is `Sites`; Site Workspace remains a command center
- no top-level `Google Profile` nav item
- no secrets or credential values are exposed in UI
- GA4 behavior remains site-scoped and read-only from the operator surface perspective

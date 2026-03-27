# UI Workspace

## Prompt Preview vs Last Run

Prompt preview and run history are different concepts:

- Prompt preview: current assembled prompt payload returned by workspace summary preview fields.
- Last run: historical execution metadata from previously completed/failed runs.

Rules:

- Workspace prompt panel must render only preview payload prompt text.
- Last-run metadata must never be concatenated into preview prompt text.
- If preview is unavailable, hide the preview panel rather than falling back to run prompt content.

## No Merging Rule

- Do not combine `latest_run` data with `*_prompt_preview.user_prompt` or `*_prompt_preview.system_prompt`.
- Do not preserve prior prompt body text across site changes or refreshes when new preview payload is received.

## Site Repoint Context Behavior

When a site is repointed to a different domain/vendor:

- workspace competitor context is derived against the current `site_normalized_domain`
- old-domain audit page signals are excluded from context inference
- stale explicit site industry is cleared unless a new industry value is provided during the same domain update

If no current-domain audit signals are available yet, competitor context health may temporarily show weak industry/service context until a fresh audit is completed.

Service-focus provenance is available in `competitor_prompt_preview.prompt_metrics` for debug workflows:

- `service_focus_source_site_content`
- `service_focus_source_structured_metadata`
- `service_focus_source_domain_hints`
- `service_focus_source_explicit_industry`
- `service_focus_source_fallback`
- `service_focus_terms_dropped_count`

These fields are intended for diagnostics and API-level inspection.

## Competitor Run Quality States

The workspace competitor panel includes a compact terminal-run quality summary line:

- proposed
- returned
- rejected
- degraded mode (`yes`/`no`)
- search-backed (`yes`/`no`)

Operator-facing notes are shown when telemetry indicates risk:

- low returned volume (`<= 2`)
- high validation rejection volume
- degraded retry used
- search-backed discovery unavailable

For very low outcomes (`<= 1` returned), the panel renders a concise explanatory message using only observed run metadata and does not invent remediation steps.

## Competitor Generation UI Behavior

The `Generate Competitor Profiles` flow refreshes automatically after run creation.

Behavior:

- After `Generate Competitor Profiles` (or `Retry`), the workspace starts bounded polling against the latest run id.
- Poll cadence: every `3` seconds.
- Safety bound: polling stops after `30` attempts (about `90` seconds) or when the run reaches `completed`/`failed`.
- Polling refreshes both:
  - competitor run status/history
  - latest run detail payload (drafts, rejection/debug counts, provider attempt telemetry)
- On terminal status, the workspace updates action messaging and clears in-progress polling state.
- No manual page refresh is required for completed-run draft visibility.

## Recommendation Generation Action

The workspace recommendations area now includes a primary `Generate Recommendations` action.

Behavior:

- The action creates a recommendation run via `POST /api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs`.
- The workspace passes the latest completed audit/comparison run lineage IDs when available.
- If no completed audit or comparison input exists, the action remains visible and the UI shows a prerequisite message instead of hiding the control.
- On success, the workspace refreshes recommendation queue/run/summary sections and shows a concise run-status message (`queued`, `running`, `completed`, or `failed`).

## Admin Competitor Timeout Controls

Admin settings include two competitor-generation timeout controls:

- `Competitor Primary Timeout Seconds`
- `Competitor Degraded Retry Timeout Seconds`

Control semantics:

- Primary timeout applies to the first full search-backed attempt.
- Degraded retry timeout applies to reduced-context timeout recovery attempts.
- Allowed range: `10-90` seconds.
- Blank value keeps deployment/provider default timeout behavior.

## Admin GCP Logs Query Controls

Admin tab includes a compact `GCP Logs Query` panel for Cloud Logging troubleshooting without direct GCP console access.

Controls:

- multiline Logs Explorer filter input
- bounded page size selector (`10`, `25`, `50`, `100`)
- `Run Query` action
- `Next Page` action when backend returns `next_page_token`
- sample filter list with `Use` buttons

Result display:

- compact table rows with timestamp, severity, log name, resource, insert id, and payload summary
- scope/order line showing effective backend settings (`projects/<configured-project>`, `timestamp desc`)
- explicit loading, empty, invalid-query, permission, and timeout states

Backend behavior remains admin-only and uses runtime ADC via attached service account.

Configuration prerequisites:

- backend project scope env var: `GCP_PROJECT_ID`
- value should be a valid project id (for example `my-prod-project-123`)
- runtime service account must have Cloud Logging read permission on that project
- API deployment must run as `serviceAccountName: mbsrn-api` with Workload Identity mapping annotation on KSA:
  - `iam.gke.io/gcp-service-account=<runtime-gsa>@<project>.iam.gserviceaccount.com`
- preflight verification helper:
  - `python scripts/verify_gcp_logs_wiring.py`
  - `python scripts/verify_gcp_logs_wiring.py --cluster --project-id <PROJECT_ID> --gsa-email <RUNTIME_GSA_EMAIL>`

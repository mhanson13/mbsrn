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

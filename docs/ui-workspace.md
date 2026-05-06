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

## Site SEO Migration Workspace IA (2026-05)

The dedicated migration route (`/sites/[site_id]/migration`) keeps primary operator workflow and diagnostics separated:

- Top Summary / Next Action (single owner for migration state scanability):
  - site name
  - migration state
  - next action
  - selected/latest draft summary
  - one highest-priority blocker/warning line only
- A. Source + Requirements:
  - source ingest action + source snapshot summary
  - operator requirements (source of truth) + optional AI suggestion drafts
- B. Media / Images (single source of truth for media):
  - Site Images state (`Discovered Source Images`, `Imported Images`, `Uploaded Images`, `Selected Images`)
  - image counts and image actions
  - media-required readiness cue
- C. Draft Readiness + Generate:
  - readiness summary + generate action
  - provider compatibility gate (`Pass|Warning|Blocking`)
  - compact media-required warning when relevant
- D. Draft Artifact Review:
  - single `Draft Artifact Review` surface
  - artifact selector near top, then one action row (`Preview Draft`, `Approve Selected Draft`, `Delete Selected Draft`)
  - `Artifact Quality Summary` directly under the action row
  - approval notes are not shown in the primary review UI
- E. Approval / Publish / Deploy:
  - compact two-surface layout for publish + deploy
  - publish surface: summary/readiness on left, GitHub target config + publish actions on right
  - deploy surface: target/readiness on left, deploy availability + deploy actions on right
  - concise readiness state + one action/blocker line
- F. Advanced Diagnostics & History:
  - draft/provider execution metadata
  - media diagnostics
  - publish/deploy attempt history + full failure diagnostics
  - full destination/runtime/config evidence

Deduplication rules:
- Migration state should not be repeated across multiple primary cards; top summary owns it.
- Media counts should not be repeated outside `B. Media / Images`.
- Draft Inputs / AI Context is provenance-focused, not a duplicate media/provider dashboard.
- Provider request/execution details and destination runtime/policy details are hidden by default and surfaced through disclosure in Advanced Diagnostics.
- When readiness is `Ready: Yes`, stale historical failure traces should not be shown as primary warnings.
- Loading/guest/auth support states should render simple support shells and must not flash authenticated diagnostics surfaces.

Compact informational-summary defaults:
- Reused MBSRN Context renders as compact inline status tiles (`Audit`, `Recommendations`, `Competitors`) with availability status and last-run text.
- Draft Inputs / AI Context renders a compact summary-first layout:
  - `Context Signals` dense key/value summary
  - `Bounded Provenance` dense key/value summary
  - long recommendation-title text is truncated in default view and disclosed through `Show full recommendation titles`
- these sections are informational summaries, not operator action surfaces.

Advanced diagnostics normalization defaults:
- Advanced Diagnostics subsection panels use a consistent shell pattern based on `Draft / Provider Diagnostics`:
  - section heading
  - optional helper text directly under heading
  - bordered/rounded subsection shell
  - consistent disclosure/content spacing
- Publish Diagnostics and Deploy Diagnostics render normalized compact cards by default:
  - status
  - selected-attempt/latest-summary context
  - concise reason
  - concise next action
- raw workflow/failure/remediation fields remain available behind per-card disclosure.
- Publish/Deploy history defaults to latest attempts plus grouped repeated-failure summaries.
- full per-attempt publish/deploy history remains available under `Show full publish history` / `Show full deploy history`.
- Deploy consistency renders as grouped status checks (operator-readable labels), while raw snake_case fields remain under `Show raw deploy consistency fields`.
- Destination / Config diagnostics render grouped categories (artifact, repository/workflow, runtime, domain, preview/deployment evidence) with nested details for lower-priority fields.

Operator Requirements simplification and suggestion scratchpads:
- `Operator Requirements` is the only operator-owned control surface for draft intent.
- standalone `Enriched Replacement Content` is no longer rendered as a primary workflow section.
- existing enriched content remains backward-compatible as supporting context and is not removed from storage in this pass.
- each supported requirements field includes an `AI suggestion draft` scratchpad:
  - `Business objectives`
  - `Requested pages`
  - `Must include`
  - `Must avoid`
  - `Tone`
  - `Calls to action`
- scratchpad actions are explicit:
  - `Suggest requirement text`
  - `Copy`
  - `Append to field`
  - `Replace field`
  - `Dismiss`
- scratchpad text is optional, editable, and not auto-applied.
- suggestions do not affect draft generation until operator moves text into the operator field and saves requirements.
- local tests mock provider/suggestion responses; suggestion UI/API tests do not require live provider calls.
- suggestion API does not require live Google OAuth/API calls.

Suggestion reason codes:
- `requirements_suggestion_completed`
- `requirements_suggestion_not_available`
- `requirements_suggestion_provider_unavailable`
- `requirements_suggestion_provider_invalid`
- `requirements_suggestion_context_unavailable`
- `requirements_suggestion_field_unsupported`
- `requirements_suggestion_budget_rejected`

Google auth/integration operator cue:
- reconnect-required Google integration states are shown as targeted integration guidance in draft diagnostics
- operator app-session expiration guidance remains distinct from integration reconnect guidance

Deterministic draft reason-code guidance (migration diagnostics):
- `app_auth_required` / `session_expired`:
  - show MBSRN sign-in guidance (app session)
- `google_reconnect_required`:
  - show Google Search Console / Analytics reconnect guidance
- `google_integration_unavailable`:
  - show retry-first integration-state warning with reconnect fallback guidance
- `draft_generation_context_unavailable`:
  - show retry/support guidance for context assembly failure

Draft preflight/readiness UI behavior:
- readiness endpoint is lightweight and does not call the AI provider
- readiness endpoint does not force Google OAuth redirect
- blocking reason codes prevent `Generate Draft`; warning reason codes keep draft generation available with guidance text
- Google reconnect may appear as warning-only when live Google fetch is not required for draft generation

Draft-generate error envelope (422 detail) fields surfaced in UI workflows:
- `message`
- `reason_code`
- `error_code`
- `retryable`
- `operator_action`
- optional `reconnect_target`
- optional bounded `diagnostic_context`

Media UX note:
- discovered source-site images and operator uploads are both visible in migration media sections
- Site Images render in a compact responsive image-card grid:
  - desktop: up to 4 columns
  - tablet: 2 columns
  - mobile: 1 column
- card defaults are compact (thumbnail/preview placeholder, short name, source/status badges, one primary action)
- verbose metadata (full URL, provenance detail, suggestion/candidate diagnostics) is behind per-image `Image details`
- per-image preview is available from an explicit `Preview` trigger (hover/focus + click toggle fallback)
- preview is bounded (`object-fit: contain`) and does not imply import/selection state change
- when no safe preview URL is available, UI shows deterministic reason cues:
  - `preview_url_missing`
  - `preview_url_unsafe`
  - `image_not_imported`
  - `unsupported_image_type`
  - `storage_preview_not_available`
- selected discovered-image import is available behind feature flag `SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED` (default disabled)
- when disabled, import action shows deterministic `remote_image_import_disabled` guidance
- discovered remote-only images show import-required guidance before draft selection or AI suggestion can run
- discovered remote-only lifecycle gating:
  - primary action is import (`Import image` or marked `Import Selected Source Images`)
  - `Select for Draft`, `Analyze image`, and `Apply suggestions` are not active until import completes
  - edit action is labeled as discovery-notes editing while still unimported
- no hotlink fallback is used for this workflow; images must be imported into workspace control before analysis/use
- diagnostics should surface safe import rejection reason codes without exposing storage paths or raw bytes
- AI suggestions are editable and are stored separately from operator-authored metadata until explicitly applied
- image acquisition controls stay visible at top of Media / Images:
  - `Upload images` (compact disclosure)
  - `Import Selected Source Images`
  - `Discover / Refresh Source Images` (reuses existing ingest path)
- each image card exposes an operator-safe reference token (for example `@image(backflow-4)`):
  - `Copy reference`
  - `Insert into requirements` (local operator field update only)
- helper examples are shown in UI:
  - `Use @image(backflow-4) on the Services page hero.`
  - `Use @image(backflow-4) on the Fire Sprinkler Services page near the backflow prevention section.`
- image references affect draft generation only after operators save the updated Operator Requirements.
- lifecycle/status labels are rendered per asset to clarify state transitions:
  - `Discovered`
  - `Uploaded`
  - `Imported`
  - `Selected for Draft`
  - `AI Suggested`
  - `Applied`
  - `Not Available` / `Rejected`
- low-value/rejected discovered candidates are hidden/de-emphasized by default and can be revealed explicitly
- lightweight local media filters are available (`All`, `Needs import`, `Selected`, `Uploaded/imported`, `Suggestions available`, `Low-value/rejected`)
- batch suggestion feedback is rendered with per-asset status/reason summaries:
  - `batch_status` (`Completed`, `Partial success`, `Failed`)
  - `completed_count`, `failed_count`, `skipped_count`
- discovered-image import feedback is rendered with per-asset status/reason summaries:
  - `status` (`Imported`, `Skipped`, `Failed`, `Disabled`)
  - `imported_count`, `failed_count`, `skipped_count`, `disabled_count`
- draft generation still uses selected media metadata only; raw image bytes are not sent into text draft context

Media suggestion reason-code cues in UI:
- `image_metadata_suggested`: suggestion ready to review/apply
- `image_not_imported`: import required before AI suggestion
- `media_asset_not_imported`: import before draft/suggestion actions
- `media_asset_not_available`: asset unavailable in current lifecycle state
- `media_asset_low_value`: low-value candidate excluded from draft/suggestion actions
- `media_asset_rejected`: rejected candidate excluded from draft/suggestion actions
- `media_action_not_allowed_for_state`: generic lifecycle-state guard
- `image_analysis_not_available`: provider/runtime cannot analyze this asset in current mode
- `unsupported_image_type`: file type rejected for suggestion
- `image_too_large`: file exceeds current bounded suggestion size budget
- `provider_unavailable` / `provider_response_invalid`: provider-side failure surfaced in subordinate diagnostics text
- `media_asset_not_authorized`: asset does not belong to the active site workspace scope
- `media_suggestion_batch_limit_reached`: selected batch is above allowed asset count and must be reduced
- `placeholder_image_detected` / `tracking_pixel_detected` / `layout_asset_detected` / `non_image_candidate_detected`:
  - candidate-quality classifier reasons used for low-value/rejected source discovery filtering and lifecycle gating

Media import reason-code cues in UI:
- `remote_image_import_disabled`: runtime feature flag is off
- `remote_image_imported`: import completed (or asset already imported)
- `image_not_found_in_source_snapshot`: requested id/url is not in current discovered snapshot
- `image_import_unsafe_url`: URL failed scheme/format safety validation
- `image_import_private_address_blocked`: hostname/IP blocked by SSRF safety controls
- `unsupported_image_type`: source response is not an allowed image MIME
- `image_too_large`: source response exceeded bounded size limits
- `image_fetch_timeout` / `image_fetch_failed`: bounded fetch failure surfaced without sensitive URL detail
- `image_content_type_mismatch`: declared vs sniffed type mismatch
- `media_import_count_limit_reached`: request/workspace import limit reached

Media-required readiness/quality cues:
- draft readiness shows warning `media_required_but_not_selected` when operator requirements request real/existing media and no usable selected media exists
- readiness remains generate-able in this case (warning, not hard block, unless broader workspace blockers exist)
- Media / Images section shows a compact "Media needed for this draft" callout with operator action guidance
- Artifact Quality Summary surfaces `required_media_missing` when required media is absent and placeholder-heavy output is detected

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

## Competitor Generation State Model

The competitor panel treats backend run data as the single source of truth on each load.

Behavior:

- On workspace load, the UI fetches run history, selects the latest run by `created_at` (with `id` as a tiebreaker), then fetches run detail for that exact run id.
- Drafts, run status, and debug payloads are rendered from that run-detail response, not from prior in-memory polling state.
- If latest run status is `running`/`queued`, polling starts as an enhancement.
- If latest run status is `completed`/`failed`, polling is not required and terminal state renders immediately.
- Stale local running indicators are cleared whenever backend run detail reports a terminal status.

## Competitor Review Clarity

The workspace now surfaces concise operator-facing competitor review context above debug details:

- each draft row shows a labeled `Why this competitor` explanation using existing run reasoning fields
- terminal run summary includes a compact filtering line:
  - proposed
  - filtered out
  - duplicates removed
  - final returned
- when search escalation is used after an initial zero-result pass, the panel shows:
  - `Expanded search was used after the initial pass returned no usable competitors.`
- when relaxed local-service matching was applied, the panel shows:
  - `Some competitors were included under relaxed local-service matching rules.`

These notes are informational trust signals and do not replace existing debug telemetry.

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

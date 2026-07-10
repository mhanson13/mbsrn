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

## Site Workspace Boundaries (Command Center)

The Site Workspace (`/sites/[site_id]`) is now a compact site-level launchpad, not a full execution surface.

Primary Site Workspace surfaces:
- site hero / identity and "What matters now"
- compact workspace snapshot and setup checklist
- workflow launchers (Recommendations, Competitors, Migration, Sites setup)
- compact latest-activity summary

## Operator UI Build-Mismatch Recovery

- Long-lived operator workflows use client-side API calls rather than first-party Next Server Actions.
- If a stale tab submits an old action payload after deployment, operator-ui classifies it as `stale_server_action_build_mismatch`.
- Recovery path is deterministic: refresh/reload the tab, then retry the action.
- Runtime diagnostics remain bounded and include safe route/app-version context only.
- Controlled stale-action rejects are expected deploy/client skew signals and should log at INFO (or WARN only with explicit rate context), not ERROR.
- Cloud Logging triage: controlled stale-action rejects should not page; native Next `Failed to find Server Action` errors should be investigated.

Workflow ownership boundaries:
- Site Analysis (`/automation`) is the primary analysis workflow surface. It orchestrates repeatable multi-step runs.
- Audit Evidence (`/audits`) owns audit execution (when needed), crawl findings evidence, and run history.
- Recommendations page owns a single filterable recommendation queue surface, run history, narratives, and apply execution.
  - default queue scope is open recommendations when no explicit status filter is provided
  - open queue defaults to grouped current work (one representative row per repeated issue)
  - queue controls include `Queue view` toggle: grouped current work vs all rows/history
  - top-of-page `Recommendation Queue Snapshot` gives compact triage context and quick launch actions
  - queue controls own filter/sort/refresh
  - queue rows integrate quick-scan context directly (`Why it matters`, `Next step`, readiness/status badges)
  - queue rows keep source context bounded:
    - source badges (`Audit`, `Comparison`, `Competitors`, `GA4`, `Search`, `GBP`)
    - compact competitor/GA4/GBP signal summaries when available
    - run IDs are de-emphasized from primary row scan content
  - each row exposes consistent actions: `Open`, `Review`, `Mark Complete`, `Show Details`
  - bulk actions are explicit and eligibility-scoped:
    - `Accept Selected` and `Dismiss Selected` target selected open/in-progress rows only
    - row checkbox interactions do not trigger row navigation
    - partial bulk failures report succeeded/failed counts without falsely marking all rows complete
  - recommendation detail view is decision-first (`What to do`, `Why it matters`, `First step`, `Success signal`, `Evidence used`)
  - recommendation detail keeps run lineage/tenant scope in `Advanced Diagnostics` disclosure
  - recommendation run detail is explicitly diagnostic; operators should return to queue for recommendation decisions
 - Competitors page is a list-first human-in-the-loop review surface, with a primary site-scoped `Suggest competitors` / `Refresh competitor suggestions` action.
  - primary summary is operator-facing: total, accepted/useful, needs review, excluded, manual seeds, latest suggestion status
  - primary table rows are review decisions (`Mark accepted/useful`, `Mark not useful`, `Exclude`, `Restore/reconsider`)
  - generation outputs become reviewable competitor rows (`generated_suggestion` / `needs_review`), not auto-accepted competitors
  - set/snapshot/comparison internals are de-emphasized under an `Advanced diagnostics` disclosure
  - Admin remains the configuration/governance owner for competitor generation tuning:
    - minimum relevance score
    - big-box mismatch penalty
    - directory/aggregator penalty
    - local alignment bonus
    - primary/degraded competitor timeouts
    - competitor prompt overrides
  - action lifecycle is operator-visible: pending state while request is in flight, bounded success/failure feedback, and automatic inventory/readiness refetch after run creation
  - successful action indicates run creation/queueing; completed competitor results can arrive later when backend run processing finishes

Operator workflow path:
1. Run site analysis.
2. Review grouped recommendations.
3. Open audit evidence only when crawl/finding detail is needed.
4. Tune workflow and governance settings separately in Admin.
  - operator correction loop is site-scoped and summary-first:
    - mark competitor domains as `Useful`, `Not useful`, or `Excluded`
    - add `Manual seed` competitor domains for future generation context
    - correction updates use bounded backend endpoints and refresh page inventory/readiness after mutation
    - excluded/manual-seeded/useful/not-useful domain context is used for future generation guidance without direct frontend provider calls
  - latest generation run quality is shown with bounded trust status:
    - `Ready`
    - `Partial`
    - `Blocked`
  - generation summary is compact and operator-facing:
    - suggestions returned
    - accepted/useful
    - needs review
    - excluded
    - rejected by quality gate
    - local seeds considered
    - latest generation status/reason
  - generation summary explicitly states that candidate suggestions are governed by Admin-configured relevance, local
    alignment, exclusion, timeout, and prompt-governance rules
  - configuration-blocked quality states are surfaced explicitly and not conflated with no-candidate outcomes:
    - `provider_schema_invalid` (local structured-output schema configuration issue)
    - `prompt_override_contract_invalid` (active Admin competitor prompt override contract mismatch)
  - when Admin override text uses legacy alias shape (`name` / `reasoning`), Admin prompt governance shows a compact compatibility warning while backend canonical schema enforcement remains authoritative
  - quality diagnostics remain bounded (accepted/rejected counts + top reason), and raw provider payloads are not shown
- Migration workflow remains on `/sites/[site_id]/migration`.
- Prompt/provider debug details stay in dedicated workflow/diagnostics surfaces, not inline in the primary Site Workspace.
- Google Profile / GA4 / analytics insertion setup now lives under `Sites` in the selected-site setup panel.
- `/google-profile` and `/business-profile` remain compatibility routes that redirect operators to `Sites` setup.
- OAuth return params (for example `gbp_connect=success`) are treated as callback provenance only; final GBP usability status is derived from loaded connection/location access state.
- Selected-site GBP status is classified with bounded states (`usable`, `missing_scope`, `permission_denied`, `no_accounts`, `no_locations`, `oauth_connected`, `not_connected`, `unavailable`) and operator-safe next actions.
- For denied/unavailable GBP states, selected-site setup exposes bounded provider diagnostics only:
  - provider error class
  - provider HTTP status (when available)
  - required scope granted status
  - bounded diagnostic hint / next action
- GBP API HTTP `429` is classified as rate-limit/quota diagnostics (for example `provider_rate_limited` or `provider_quota_or_access_not_granted`), with guidance to check quota/access in the OAuth client project for:
  - `My Business Account Management API`
  - `My Business Business Information API`
  - if quota is blank/unavailable, request Business Profile API access/allowlist approval first
  - after approval, request quota increase:
    - `https://support.google.com/business/contact/api_default`
- OAuth callback success is never treated as final usable GBP state without backend confirmation.

Accessibility/DOM contract:
- Site Workspace keeps unique tab/panel ids for launchpad content.
- duplicate recommendation panel ids are not rendered concurrently.

## Site Workspace GA4 Health + Insights (Phases 2-4)

The site workspace now exposes compact, site-scoped GA4 health plus insight summaries (still no dashboard sprawl).

Behavior:
- GA4 health is derived from the selected site property only.
- No global/default GA4 property fallback is used for site-level health/readiness context.
- Missing or unavailable GA4 context does not block workspace loading or recommendation rendering.
- Null/partial GA4 health or insight payloads degrade to bounded fallback labels/messages (`Unknown`, `Not available`, `GA4 unavailable`) instead of breaking workspace rendering.
- Recommendation detail surfaces now show explicit GA4-context omission/unavailable messaging instead of silent absence.
- Recommendation detail surfaces also show compact additive GA4 priority hints when available (for example top landing-page match, traffic decline, engagement decline), without changing recommendation scoring/order.
- Recommendation detail surfaces now also support compact additive GA4 outcome snapshots for accepted/completed actions:
  - observational wording only (`Observed after action`)
  - bounded before/after windows and directional status (`improved`, `declined`, `mixed`, `no_clear_change`, `insufficient_data`)
  - `pending_after_window` when not enough post-action time has elapsed
  - no attribution/causation claims and no scoring/order changes
- Workspace Snapshot now includes compact GA4 insight cards:
  - `Top landing pages` (bounded to top 5 shown)
  - `Traffic trend` (sessions/active users directional summary)
  - `Engagement trend` (engagement-rate/time directional summary)
  - `Acquisition top channel`
  - `Acquisition top source`
  - `Acquisition mix` (organic/direct/referral/paid compact summary)
- Insight cards are summary-only:
  - no charts
  - no dashboard drilldowns
  - no conversion/event dashboards
  - no scoring/prioritization changes from these cards in this phase
- Acquisition context remains additive and site-scoped:
  - derived from `ga4_acquisition_insights`
  - GA4 remains optional and non-blocking
  - missing/unavailable states degrade to bounded labels/messages without breaking workspace render
- GBP diagnostics and remediation are separate from GA4 insight cards and currently depend on external Google allowlist/quota approval for blocked projects.

Operator-safe status labels:
- `Not configured`
- `Configured`
- `Reachable`
- `No recent data`
- `GA4 authorization missing`
- `Permission issue`
- `Invalid property`
- `Temporarily unavailable`
- `Unknown`

Guidance distinction:
- `GA4 authorization missing`: reconnect Google with GA4 read-only scope (`analytics.readonly`) when OAuth auth mode is used.
- `Permission issue`: scope exists, but the connected account/service account/runtime identity lacks Viewer access to the GA4 property.

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
  - Site Images state (`Discovered Source Images`, `Imported Images`, `Uploaded Images`, `Images included in draft`)
  - image counts and image actions
  - media-required readiness cue
- C. Draft Readiness + Generate:
  - readiness summary + generate action
  - provider compatibility gate (`Pass|Warning|Blocking`)
  - compact media-required warning when relevant
- D. Draft Artifact Review:
  - single `Draft Artifact Review` surface
  - artifact selector near top, then one action row (`Show preview` / `Hide preview`, `Approve Selected Draft`, `Delete Selected Draft`)
  - `Artifact Quality Summary` directly under the action row
  - approval notes are not shown in the primary review UI
  - one consolidated preview surface only:
    - left page/file selector rail (`~15-20%` width on desktop)
    - right sandboxed web preview iframe (`~80-85%` width on desktop)
    - selector entries use title-first text with compact muted filename/path secondary text
    - mobile/tablet stack: selector above iframe
- E. Approval / Publish / Deploy:
  - compact two-surface layout for publish + deploy
  - publish surface: summary/readiness on left, GitHub target config + publish actions on right
  - deploy surface: target/readiness on left, deploy availability + deploy actions on right
  - concise readiness state + one action/blocker line
  - optional GA4 outcome snapshot (Phase 5B) appears as compact observational context only:
    - `Observed after deploy` when a successful deploy timestamp exists
    - `Observed after publish` when publish exists and deploy does not
    - deterministic before/after metrics and bounded statuses (`pending_after_window`, `insufficient_data`, etc.)
    - no attribution claims and no scoring/order changes
  - deploy evidence state can show `Confirmed Live` when current live HTTPS probe evidence is healthy
  - `Refresh Deploy Status` is scoped to the route site id; when selected artifact history is missing it can still refresh current-live evidence from the latest deploy record for that site

Managed-site boundary cues (generic):
- source/current live URL, preview hostname, publish repo/branch, deploy namespace/workflow, and future cutover domain are configuration-derived per site
- publish and deploy are separate gates for all managed sites
- publish readiness validates artifact/repo/branch/credentials/media requirements
- deploy readiness validates workflow/static-IP/TLS/runtime requirements
- deploy workflow provisioning issues can appear as publish warnings but are deploy blockers, not publish blockers
- when selected approved artifacts have stale media diagnostics, publish readiness/preparation can deterministically re-materialize selected media and normalize image paths; unresolved referenced media remains a publish blocker
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
  - recommendation budget summary surfaces included-vs-available counts and trim state (for example `Recommendation context: 10 of 81 included`, `Context trimmed: Yes`)
  - recommendations are presented as interpreted audit context; raw audit findings may be summarized/omitted for budget control and shown as secondary diagnostics context
  - long recommendation-title text is truncated in default view and disclosed through `Show full recommendation titles`
- these sections are informational summaries, not operator action surfaces.

Advanced diagnostics normalization defaults:
- Advanced Diagnostics subsection panels use a consistent shell pattern based on `Draft / Provider Diagnostics`:
  - section heading
  - optional helper text directly under heading
  - bordered/rounded subsection shell
  - consistent disclosure/content spacing
- Operator/admin surfaces use vendor-neutral observability language only (for example `runtime diagnostics`, `deployment telemetry`, `platform logs`).
- Observability vendor implementation details are infrastructure-scoped and are not exposed as product labels in workspace/admin UX.
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
- deploy HTTPS diagnostics preserve bounded probe evidence (`https_probe_error_summary`) and control-plane-ready probe-failure reason codes (`https_probe_failed_after_control_plane_ready`, `https_probe_timeout`, `https_probe_empty_reply`, `https_probe_not_attempted`) without exposing raw unsafe curl output.
- deploy diagnostics separates selected workflow attempt outcome from current runtime evidence:
  - selected attempt status/failure remains visible as selected-attempt/historical context
  - `Current Live Runtime Evidence` card shows the current probe-backed runtime state (`HTTPS Ready`, host reachability, scheme, live URL, cert identity, checked-at, source)
  - when selected workflow evidence collection failed but current runtime is healthy, UI note states:
    - `Selected deploy workflow failed during evidence collection, but current live HTTPS evidence is healthy.`
- deploy runtime evidence precedence:
  1. `current_live_probe`
  2. successful `workflow_output`
  3. selected attempt diagnostics
  4. latest summary fallback
  5. historical failure detail

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
- source discovery is bounded and same-site:
  - homepage + prioritized internal image-bearing pages (for example projects/services/process/gallery/work/about)
  - `Pages scanned` count is shown in migration media image counts
- Site Images render in a compact responsive image-card grid:
  - desktop: up to 4 columns
  - tablet: 2 columns
  - mobile: 1 column
- card defaults are compact (thumbnail/preview placeholder, short name, source/status badges, one primary action)
- verbose metadata (full URL, provenance detail, suggestion/candidate diagnostics) is behind per-image native `Image details` disclosure
- uploaded/imported assets use authenticated preview URLs on same-origin media routes when local storage preview is available
- selected discovered-image import is controlled by runtime flag `SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED` (default enabled)
- when disabled, import action shows deterministic `remote_import_disabled` guidance
- image acquisition controls stay visible at top of Media / Images:
  - `Upload images` (compact disclosure)
  - `Discover / Refresh Source Images`
  - `Use checked images in draft` (bulk action)
- checkbox semantics are operator-first:
  - checked means `Use in draft`
  - unchecked means leave out of the next draft
  - unsafe rejected rows keep checkbox disabled
- bulk action behavior (`Use checked images in draft`):
  1. import checked safe discovered images when needed
  2. mark them included in draft (`selected_for_draft` backend flag)
  3. run metadata suggestion analysis where runtime support exists
  4. apply safe suggestions when supported; otherwise keep staged suggestion state
- per-image primary action mirrors the bulk flow:
  - `Use in draft`
  - `Use in draft anyway` for low-value but safe discovered images
- low-value is a quality warning only; it is not a hard operator block
- unsafe rejected is the hard block and stays non-importable/non-usable
- removed controls:
  - `Insert into requirements`
  - per-card `Preview`
  - per-card `View details`
  - `Show low-value/rejected` toggles
- lifecycle/status labels are rendered per asset to clarify state transitions:
  - `Discovered`
  - `Uploaded`
  - `Imported`
  - `Included in draft`
  - `AI Suggested`
  - `Applied`
  - `Not Available` / `Rejected`
- low-value safe candidates can use explicit override action (`Use in draft anyway`) when validation/safety checks pass
- safety-rejected candidates remain non-importable and show bounded reason diagnostics only
- lifecycle actions are explicit:
  - discovered/not-imported candidates: `Ignore`
  - uploaded/imported candidates: `Remove image` / `Remove from workspace`
  - lifecycle actions clear `Included in draft` when removal/ignore is applied
- non-image routes discovered during crawl-like extraction (for example `/m` or other HTML routes) are classified as rejected and are not shown as normal importable candidates
- lightweight local media filters are available (`All usable images`, `Discovered`, `Uploaded/imported`, `Unsafe rejected`)
- batch suggestion feedback is rendered with per-asset status/reason summaries:
  - `batch_status` (`Completed`, `Partial success`, `Failed`)
  - `completed_count`, `failed_count`, `skipped_count`
- discovered-image import feedback is rendered with per-asset status/reason summaries:
  - `status` (`Imported`, `Skipped`, `Failed`, `Disabled`)
  - `imported_count`, `failed_count`, `skipped_count`, `disabled_count`
- migration draft context summary includes bounded budget cues:
  - recommendation included vs available counts
  - recommendation basis (`interpreted_audit_context`)
  - `Draft context trimmed` status and largest included block when available
  - read-only effective generation budget (`profile`, `variation`, `context budget chars`, `page/file limits`)
  - read-only effective generation safety (`provider timeout`, `preflight mode`, `max final chars`, `max difficulty`, `compact fallback`, `compact fallback attempted`, `budget capped`)
  - blocked-before-provider state is explicit and actionable (`migration_generation_preflight_too_large`) without exposing raw prompt/payload data
  - blocked reason text aligns to the active blocker (`difficulty score`, `final input chars`, or both) instead of always defaulting to context-budget overflow wording
  - local preflight/provider-skipped failures are labeled as blocked before request; provider-rejection wording is reserved for real remote-provider rejections
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
- `remote_import_disabled`: runtime feature flag is off
- `candidate_not_validated`: candidate is missing required validation evidence
- `blocked_private_network`: hostname/IP blocked by SSRF safety controls
- `unsupported_content_type`: source response is not an allowed image MIME
- `file_too_large`: source response exceeded bounded size limits
- `fetch_timeout`: bounded fetch timeout
- `unsafe_redirect`: redirect target failed safety validation
- `storage_write_failed`: workspace storage write failed

Media-required readiness/quality cues:
- draft readiness shows warning `media_required_but_not_selected` when operator requirements request real/existing media and no usable selected media exists
- readiness remains generate-able in this case (warning, not hard block, unless broader workspace blockers exist)
- Media / Images section shows a compact "Media needed for this draft" callout with operator action guidance
- when useful source images were discovered but none are imported/selected yet, warning copy is explicit:
  - `Useful source images were discovered. Import and select images before approving the draft.`
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

## Admin IA Boundaries

Admin (`/admin`) is a governance/configuration surface. It does not execute workflow operations directly.

Admin ownership groups:
- Overview: business-level admin posture and configuration navigation.
- Audit & Crawl Settings: crawl depth and audit evidence collection defaults.
- Competitor Generation Settings: deterministic candidate quality and generation timeout tuning.
- AI Provider & Prompt Governance: default AI model governance used when runs do not provide explicit model overrides.
- AI Prompt Overrides: business-scoped competitor/recommendation prompt overrides and fallback controls.
- Publish & Deployment Configuration: GitHub target, managed GKE target, and managed deploy secret controls.
- Migration AI Budget: migration context/generation limits, depth profile, and variation controls.
- Migration Generation Safety: provider timeout and preflight guardrails (`compact_fallback` vs `block_before_provider`) with hard backend caps.
  - timeout source of truth is Migration Generation Safety provider timeout (`60-600` seconds, default `300`)
  - default bounded safety/budget profile: `max_final_input_chars=32000`, `max_difficulty_score=18`, `context_budget_chars=90000`, generated page/file `20/16`, compact limits `6/5/8`
  - hard caps remain bounded: `max_final_input_chars<=64000`, `max_difficulty_score<=24`, `context_budget_chars<=150000`, generated pages/files `<=30/24`
  - synchronous provider timeout is hard-capped at effective `600` seconds (10 minutes)
  - Admin UI no longer silently clamps migration safety/budget numeric fields before submit; backend policy is authoritative for effective values.
  - Admin preview shows requested vs effective values, capped status, and cap reasons for migration generation controls.
- Managed Namespace Policy: ResourceQuota, LimitRange, and NetworkPolicy defaults for managed site namespaces.
- Site Registry Management: site records and destructive site delete controls.
- Diagnostics & Logs: read-only Cloud Logging investigation.

Execution ownership remains on dedicated routes:
- Site Analysis (`/automation`): orchestrated analysis runs and workflow configuration.
- Audit Evidence (`/audits`): findings/evidence/history and optional audit-only execution.
- Recommendations: operator decisioning and queue execution.
- Competitors: competitor generation/review workflow.
- Site Workspace: command-center routing and compact state.

Admin settings help UX:
- Admin forms use compact info icons/tooltips for per-setting guidance.
- Tooltip guidance standard:
  - what the setting controls
  - what changing it does
  - key tradeoff/risk (for example latency/cost/quality/contract compatibility)
- Migration generation safety/budget settings surface both recommended ranges and backend hard-cap ranges.
- Always-visible inline text is reserved for section summaries, high-risk warnings, destructive actions, and save/error states.
- GitHub publish config save status semantics:
  - successful save clears prior failed-save UI errors
  - successful save can still show independent settings-health warnings when saved values need review
  - only true request/save failures should show `Failed to save GitHub publish configuration.`

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
- upload supports selecting multiple images in one action; shared metadata fields apply across the selected file batch
- upload completion reports uploaded/failed/skipped counts and preserves successful uploads when one file fails

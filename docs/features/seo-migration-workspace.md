# SEO Migration Workspace (Phase 1-7)

## Intent
The migration workspace is a controlled operator workflow for replacing weak incumbent SMB websites with reviewable, structured, AI-assisted static artifacts.

The incumbent site is a signal source, not a canonical source of truth. The migration workspace becomes canonical by combining:
- imported source-site facts/signals
- operator requirements and requested changes (source of truth)
- optional AI suggestion drafts that operators can apply into requirements
- stored enriched context as lower-priority supporting context (backward compatibility)
- existing MBSRN audit/recommendation/competitor summaries

## Trust Boundary and Lifecycle
Authoritative boundary:

`AI generation -> draft artifacts -> operator approval -> explicit publish -> explicit deploy`

Lifecycle states are tracked independently:
- Draft generated (`migration_status=draft_generated`)
- Draft approved (`migration_status=draft_approved`)
- Published to GitHub (`migration_status=published_to_github`)
- Deploy requested (`migration_status=deploy_requested`)

No auto-publish or auto-deploy behavior exists in this feature.

Preview identity contract (2026-08-28):
- a site may configure one globally unique `preview_slug`
- the resolved draft hostname is `<preview_slug>.site.mbsrn.com`
- source domain and GitHub repository name do not define preview identity
- the slug is editable until the first preview infrastructure mutation, then locked
- existing sites remain unconfigured until an operator confirms a slug; migration `0062_site_preview_identity` does not create infrastructure

State/order invariants:
- publish is blocked until the selected artifact version is approved and publish target readiness is valid
- deploy is blocked until the selected artifact version has a successful publish and deploy target readiness is valid
- failed publish attempts do not mark deploy-ready state
- failed deploy attempts do not mutate last successful publish metadata (artifact id/commit/timestamp)
- UI readiness indicators are derived from persisted workspace/artifact state returned by backend summary/readiness payloads

## Optional asynchronous source capture (Phase 7)

Every site can choose one of two parameterized ingestion modes; Platfire is only the first acceptance example:

- `analyze_rebuild` is the default bounded source analysis used to create a redesigned site.
- `faithful_snapshot` renders authorized public pages in Chromium, freezes first-party pages/assets as a baseline, and then supplies bounded excerpts to draft generation.

Faithful capture requires an explicit authorization acknowledgment. It does not reproduce server-side behavior. Detected forms, authentication, commerce, uploads, iframes, streaming media, WebSockets, and dynamic APIs are returned as concise replacement-required limitations.

Capture API:

- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/source-capture-runs` queues a run and returns `202`.
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/source-capture-runs` lists recent runs.
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/source-capture-runs/{capture_id}` supports polling.

Requests include a business-scoped idempotency key. Reusing the key returns the same run only when site and capture parameters match. Run states are `queued`, `running`, `completed`, and `failed`.

A dedicated database-polling worker owns browser execution. It runs non-root in GKE Sandbox, explicitly enables Chromium's sandbox, blocks private/credentialed URLs, pins public DNS resolution, restricts navigation to the exact host and `www` equivalent, blocks external resources, and enforces page/asset/resource/total/time bounds.

Objects use `source-captures/{business_id}/{site_id}/{capture_id}/attempt-{n}/...` in the private versioned migration-media bucket. The worker verifies byte length and SHA-256 after each write, records the GCS generation, and writes `manifest.json` last. An older run can complete for audit history but cannot replace a newer run as the workspace baseline.

Draft generation consumes bounded rendered text/provenance from the completed baseline. It never edits the stored capture or manifest. Internal storage keys and complete captured contents are not exposed by the capture-run API or normal diagnostics.

## Operator Workflow
Primary workflow now runs on the dedicated route:

`/sites/[site_id]/migration`

The main site workspace remains recommendation-first and provides a migration status + launch CTA.

Migration workflow on the dedicated page:
1. Create/manage workspace and set `source_url`.
2. Run bounded source ingest.
3. Capture operator requirements and optionally use per-field AI suggestion drafts.
4. Review preflight draft readiness (blocking vs warning-only signals).
5. Generate and review draft artifacts.
6. Confirm and save the site's canonical `<preview_slug>.site.mbsrn.com` identity.
7. Run **Approve & Create Preview** for the selected artifact.
8. Continue the displayed GitHub, self-managed certificate, DNS, deployment, and verification gates in order.
9. Open the verified preview URL.

The route is keyed by business and site. Workspace loads also capture both that scope and a monotonically increasing request generation; any late summary, TLS, media, history, preview-release, or source-capture response is ignored after navigation or a newer refresh. This prevents one site's data from appearing in another site's operator workflow.

Draft files and selected media are frozen together during generation. Approval returns `draft_package_incomplete` when selected bytes are missing or generated pages contain unresolved/non-deployable media references. The normal UI disables approval and preview creation when that incomplete state is already known and directs the operator to repair or re-import media, then generate a new draft. Publish never repairs or mutates an approved artifact.

The certificate gate uses API-side **Ensure, Vault & Publish** semantics. A readiness response proves that the Google Cloud project and workload credentials are configured but leaves provider permissions in `operation_required` state until the actual Secret Manager or Compute request runs. The real operation supplies the authoritative result. Retries reuse a valid published certificate or resume matching vaulted material after a partial Compute failure, rather than generating another certificate. Normal operator output shows only the failed service step and next action; bounded provider status metadata remains in administrator diagnostics.

Artifact publication and managed deploy-workflow provisioning are separate stages. A successful artifact commit remains published when subsequent workflow verification fails; Deploy Readiness records `workflow_provisioning_failed` and blocks dispatch until workflow verification succeeds. Re-running Publish for the same artifact invokes duplicate-artifact workflow repair without rewriting artifact files. Existing marker-missing repositories remain blocked pending explicit adoption; only repositories created during the controlled MBSRN bootstrap receive their matching management marker automatically.

Important operator cue:
- GitHub publish is not production deployment.

## Operator UI Layout (Dashboard Pass)
Operator UI now uses a tighter dashboard hierarchy for migration review without changing workflow behavior:
- global header branding adds a left-aligned MBSRN logo anchor linked to `/dashboard`
- global header context identifiers (`Site ID` and `Business ID`) are bound to the currently active site context; switching site context updates both values together and avoids stale/global fallback leakage
- dedicated migration route starts with a compact summary band for:
  - migration state
  - next action
  - latest draft version/status
  - artifact quality status
- migration route sections are presented in this order:
  1. `Top Summary / Next Action`
  2. `A. Source + Requirements`
  3. `B. Media / Images`
  4. `C. Draft Readiness + Generate`
  5. `D. Draft Review + Quality`
  6. `E. Approval / Publish / Deploy`
  7. `F. Advanced Diagnostics & History`

Section ownership/deduplication rules:
- Top Summary is the single source of truth for migration state + next action scanability (site, migration state, next action, selected draft summary, one highest-priority warning only)
- Source + Requirements owns source ingest/snapshot and operator replacement requirements with optional AI suggestion scratchpads
- Media / Images is the single source of truth for media counts and media actions
- Draft Readiness + Generate owns readiness and provider compatibility gate (`Pass|Warning|Blocking`) for generation only
- Draft Review + Quality owns artifact selection, quality findings, preview, approval, and delete
- Approval / Publish / Deploy owns concise readiness and concise destination/action controls only
- Advanced Diagnostics owns verbose/troubleshooting details (provider execution metadata, destination/runtime evidence, history, reason-code diagnostics)

Purpose:
- improve <10-second scanability for operators
- surface next action and draft quality earlier
- keep advanced diagnostics available but lower-priority

Current workflow boundaries:
- media completeness is a hard approval and preview-release gate
- publish and deploy consume the exact approved artifact package
- artifact quality remains advisory only

Site operator page information architecture update:
- the site operator route now keeps a smaller, decision-first structure:
  - summary/hero
  - recommendation workflow area
  - supporting snapshot/activity
  - migration launch surface
- embedded migration workflow content was removed from the main site workspace.
- migration now opens in its own dedicated workflow route (`/sites/[site_id]/migration`).
- GA4 setup was moved out of the site workspace and into `Sites` selected-site setup (`Google & Analytics`).
- analytics insertion rules were also moved out of migration and into `Sites` selected-site setup because they are site-wide controls.
- this is presentation and information-hierarchy only; migration workflow semantics are unchanged.
- site workspace hero actions use a shared route-level action cluster pattern:
  - secondary navigation actions (sites/audits)
  - contextual shortcuts (competitor workspace/recommendation queue)
  - migration workflow launch
  - this keeps migration discoverability strong while aligning action framing with other upgraded operator routes.

Second-pass polish refinements:
- summary band cards now use consistent label/value hierarchy and spacing, with a stronger visual emphasis on `Next action`
- section rhythm was tightened with compact subtitles and clearer spacing between major migration sections
- artifact quality issues render as readable issue rows (type + description) with top issues first and full list expandable
- advanced diagnostics remain available but visually de-emphasized below operator action surfaces
- header logo integration was tuned for shell consistency and small-screen behavior (text label collapses on narrow widths)
- frontend `useEffect` dependency cleanup in site workspace page removed a non-functional lint warning only; workflow semantics are unchanged
- site workspace companion panels (`Competitor Readiness`, `AI Competitor Profiles`, `Recommendation Queue`, `Recommendation Runs`) now use the same summary-strip and status-callout rhythm so migration is not the only polished workspace surface
- implementation maintainability update: the large site workspace page container was decomposed into focused panel modules for competitor/recommendation surfaces without changing operator workflow semantics or backend/API behavior

TailAdmin-inspired visual-system pass (inspiration only; no template import):
- strengthened section-card rhythm across migration phases (`workspace-section-block`) to improve scan hierarchy from summary -> action -> detail
- standardized action grouping with shared action-bar patterns (`workspace-action-bar-primary` and `workspace-action-bar-secondary`)
- normalized inline feedback into compact status stacks (`workspace-message-stack`) so warning/success/error states are visually consistent
- promoted clearer empty states with bounded card treatment (`workspace-empty-state`) instead of floating muted text
- introduced compact metadata grids for migration execution diagnostics (`workspace-metadata-grid`) to reduce long-line density
- de-emphasized troubleshooting-only areas with a consistent collapsible shell (`workspace-details-shell`)
- standardized reusable workspace presentational primitives were introduced and adopted in migration surfaces:
  - `WorkspaceActionBar`
  - `WorkspaceMessageStack`
  - `WorkspaceEmptyStateCard`
  - `WorkspaceMetadataGrid` / `WorkspaceMetadataItem`

Operator impact:
- faster section scanning and clearer primary-vs-secondary content separation
- no workflow semantic changes (approval/publish/deploy and generation gates are unchanged)

Destination, readiness, and diagnostics IA refinements:
- Section E now keeps destination display concise:
  - publish destination: repository, branch, artifact root, state, expected URL
  - deploy destination: repository/ref, environment, preview URL, deploy-evidence state
  - one-line blocker text stays visible when publish/deploy are not ready
- Section E layout is compacted into two responsive two-column surfaces:
  - publish surface:
    - left: destination summary + publish readiness
    - right: GitHub publish target config + publish actions
  - deploy surface:
    - left: GKE deploy target details + deploy readiness
    - right: deploy availability controls + deploy actions
- verbose destination/runtime/config evidence is no longer primary-path content:
  - namespace and managed policy alignment
  - workflow/path/source metadata
  - URL source/detail and runtime confirmation context
  - these live under `Advanced Diagnostics & History` -> `Show full destination diagnostics`
- readiness cards in Section E are intentionally compact:
  - show `Ready: Yes/No`
  - show one primary operator action/blocker line
  - stale/old failure detail lines are not shown as primary warnings when readiness is `Ready: Yes`
- full troubleshooting remains available and grouped in Advanced Diagnostics:
  - Draft / Provider
  - Media
  - Publish
  - Deploy / Runtime
  - Destination / Config
- diagnostics are run-bound, not floating snapshot-only:
  - publish/deploy diagnostics can be scoped to selected history attempts
- selected-attempt reason/status fields never fall back across attempt boundaries
  - current endpoint and current live evidence are rendered separately from historical attempts

Deployment provenance is separate from migration evidence. The Operator HTML `mbsrn-ui-version` marker identifies the frontend commit; API `/health` returns safe `build_sha` and `image_tag` metadata. If these do not match the intended release, treat the page as a stale deployment/cache investigation rather than a current migration-readiness result.
  - publish/deploy history remains collapsible under Advanced Diagnostics
- URL confirmation semantics are unchanged:
  - `deterministic_target_config` is expected guidance (not confirmed live evidence)
  - confirmed live evidence comes from explicit deploy/workflow result metadata or current refresh probe metadata (`deploy_result`, `workflow_output`, `current_live_probe`)
- workflow-attempt vs current-runtime separation:
  - selected workflow attempt status/failure remains visible in deploy diagnostics/history as selected-attempt context
  - current runtime state is evaluated separately and can be marked healthy from bounded live HTTPS probe evidence
  - when selected workflow evidence collection failed but current live HTTPS probe succeeds, the operator-facing note is:
    - `Selected deploy workflow failed during evidence collection, but current live HTTPS evidence is healthy.`
- deploy evidence precedence for current runtime state:
  1. current live HTTPS probe evidence
  2. successful workflow output evidence
  3. selected attempt diagnostics
  4. latest summary fallback
  5. historical failure detail
- stale selected-attempt static IP failures (for example legacy `managed_site_static_ip_address_missing` or current `static_ip_address_missing_after_retry`) remain in selected/history diagnostics and do not override current runtime live status when current live HTTPS evidence is healthy.
- manual follow-up capture remains available through `Refresh Deploy Status`
  - refresh evaluates the route/workspace site id and can fall back to the latest deploy record for that site when the currently selected artifact has no deploy record, so current-live probe fields can still be populated.

Summary and diagnostics compaction (2026-05):
- Reused MBSRN Context is compact by default:
  - Audit, Recommendations, and Competitors render as inline status tiles (`Available|Missing|Stale`) with last-run timestamps.
  - verbose per-source context text is available through `Show context detail`.
- Draft Inputs / AI Context is compact and summary-first:
  - `Context Signals` and `Bounded Provenance` render as dense key/value summary blocks.
  - long recommendation-title lists are truncated in primary view and available through disclosure.
  - this section remains informational provenance only, not an operator action surface.
- Advanced Diagnostics is compact by default while preserving full data:
  - subsection shells are visually normalized to the `Draft / Provider Diagnostics` pattern (title, helper text, consistent bordered/rounded shell, aligned disclosure/content spacing)
  - Publish/Deploy diagnostics show normalized status + selected-attempt scope + concise reason + next action.
  - Deploy diagnostics include a compact `Current Live Runtime Evidence` card (HTTPS ready, host reachability, scheme, live URL, cert identity, checked-at, source, bounded probe summary on failure).
  - raw failure/workflow/remediation fields remain under explicit `Show raw ... diagnostics fields` disclosures.
  - publish/deploy history defaults to latest attempts plus grouped repeated failure reasons; full per-attempt history remains available under disclosure.
  - deploy consistency defaults to grouped operator-readable status checks; raw snake_case evidence fields remain under `Show raw deploy consistency fields`.
  - destination/config diagnostics are grouped by category (artifact, repository/workflow, runtime, domain, preview/deployment evidence) with nested details.

Draft review and preview behavior:
- Section D is a single `Draft Artifact Review` surface that groups artifact selection, draft actions, and quality review in one compact flow.
- action ordering in Section D:
  - selected artifact version
  - action row (`Show preview` / `Hide preview`, `Approve Selected Draft`, `Delete Selected Draft`)
  - `Artifact Quality Summary`
- approval notes are not part of the primary Section D UI.
- Section D owns preview + review actions (`Show preview` / `Hide preview`, `Approve Selected Draft`, `Delete Selected Draft`)
- preview remains sandboxed and draft-only (`not published`, `not deployed`)
- one unified draft preview surface is used (no duplicate preview iframe surfaces)
- generated artifact images and migration-media thumbnails are fetched through the authenticated API client with the operator bearer token
- protected media and artifact API URLs are never assigned directly to `img.src` or embedded iframe markup; fetched blobs are rendered as local data URLs and revoked/discarded with component state
- a failed authenticated image fetch produces bounded preview-unavailable guidance and does not fall back to an unauthenticated request
- preview layout is two-column on desktop:
  - left rail (`~15-20%`) for page/file selection
  - right pane (`~80-85%`) for sandboxed web iframe preview
- selector rail display uses:
  - page title as primary text when available
  - filename/path as secondary muted text on a separate line
  - compact typography so long lists stay scannable
- preview layout stacks on smaller screens:
  - selector rail above preview pane
- draft deletion eligibility and history-protection invariants are unchanged

## Draft Input Provenance and AI Context Summary (2026-05)
Draft generation now persists and returns a bounded, operator-safe provenance summary at:
- `context_summary.draft_input_summary`

Purpose:
- make draft input coverage inspectable without exposing secrets or oversized payloads
- show what context classes were included, not raw source payloads

Current summary fields include:
- recommendation coverage:
  - `recommendations_available_count`
  - `recommendations_included_count`
  - `recommendations_context_trimmed`
  - `recommendations_context_basis`
  - `recommendation_categories_included`
  - `top_recommendation_titles`
- analytics/competitor/audit/operator coverage:
  - `gsc_signals_included`
  - `ga4_signals_included`
  - `competitor_profiles_included_count`
  - `operator_requirements_included`
  - `requirement_suggestions_available_count`
  - `requirement_suggestions_applied_count`
  - `context_sources_used_for_requirement_suggestions`
  - `enriched_business_context_included`
  - `raw_audit_findings_included_count`
  - `raw_audit_findings_included`
  - `raw_audit_findings_note`
- media coverage:
  - `source_site_images_discovered_count`
  - `source_site_images_imported_count`
  - `operator_uploaded_images_count`
  - `selected_media_assets_count`
  - `media_asset_categories`
  - `media_context_included`
  - `media_context_trimmed`
- AI request-shape summary:
  - `ai_context_source_count`
  - `ai_context_trimmed`
  - `ai_context_trimmed_bytes`
  - `provider_source`
  - `mocked_source`
  - `generation_safety_profile`
  - `generation_preflight_mode`
  - `generation_max_final_input_chars`
  - `generation_max_difficulty_score`
  - `generation_compact_fallback_enabled`
  - `generation_compact_fallback_attempted`
  - `generation_budget_capped`
  - `generation_preflight_blocked`
  - `generation_preflight_block_reason`

Interpretation:
- this is bounded metadata for trust and debugging, not a full prompt dump
- values represent context presence/counts and budget behavior, not guaranteed quality of source data
- recommendations are the primary interpreted audit context in draft inputs; raw audit findings may be summarized or omitted in primary context to control request size
- `ga4_signals_included` is derived from site-scoped GA4 configuration only and does not use global/default GA4 property fallback
- missing GA4 does not block migration drafts; GA4-driven context is simply omitted/marked unavailable
- in the primary workflow UI, this section is provenance-only:
  - media counts/actions belong to `B. Media / Images` (single source of truth)
  - provider execution/request metadata belongs to `F. Advanced Diagnostics & History`
- provider recommender outputs and SEO recommendations remain advisory; operator review is still required before approval/publish/deploy
- recommendation queue bulk actions are eligibility-scoped:
  - `Accept Selected` and `Dismiss Selected` apply to selected open/in-progress rows
  - bulk action results report succeeded/failed counts; partial failures do not falsely mark all rows accepted

## Operator Requirements + AI Suggestion Scratchpads (2026-05)

Primary model:
- Operator Requirements are the only operator-owned source of truth for draft intent.
- Standalone `Enriched Replacement Content` is removed from the primary workflow surface.
- Existing enriched content remains stored and available as lower-priority supporting context for backward compatibility.

Field-level suggestion support:
- `business_objectives`
- `requested_pages`
- `must_include`
- `must_avoid`
- `tone`
- `calls_to_action`
- `additional_notes` (Additional requirements)

Scratchpad behavior:
- each field has an operator-owned textarea plus an `AI suggestion draft` scratchpad
- scratchpad is empty by default and populated only after `Suggest requirement text`
- scratchpad text is editable by operators
- scratchpad text is never auto-applied and never auto-saved
- explicit actions:
  - `Copy`
  - `Append to field`
  - `Replace field`
  - `Dismiss`
- draft generation uses saved operator requirements only
- unapplied scratchpad text does not affect draft generation

Suggestion API:
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/requirements/suggest`
- request:
  - `field`
  - optional `current_value`
  - optional `force_refresh`
- response:
  - `field`
  - `suggestion_status` (`completed|failed|not_available`)
  - `suggested_value`
  - `reason_code`
  - `context_sources_used`
  - `retryable`
  - `generated_at`
  - optional `model_diagnostics` (`task_alias`, `source`, `model`, `fallback_used`, `validation_status`, compatibility flags, optional safe message)

Stable reason codes:
- `requirements_suggestion_completed`
- `requirements_suggestion_not_available`
- `requirements_suggestion_provider_unavailable`
- `requirements_suggestion_provider_invalid`
- `requirements_suggestion_model_incompatible`
- `requirements_suggestion_context_unavailable`
- `requirements_suggestion_field_unsupported`
- `requirements_suggestion_budget_rejected`

Suggestion safety constraints:
- bounded context only (source snapshot, operator requirements, recommendation/audit/competitor summaries, selected media summary, business/site context, optional stored enrichment support)
- no live Google API calls required
- no forced Google OAuth reconnect for suggestion requests
- no secrets/tokens/storage keys/raw media bytes/base64 in suggestion responses
- requirements suggestions now resolve through task alias `requirements_helper`; default runtime behavior remains compatibility-mapped to the shared legacy model chain until helper-specific model choices are configured
- local tests mock provider behavior; no real provider calls are required for test runs

Operator requirements import/export:
- Export control downloads operator requirements as JSON:
  - schema: `mbsrn.operator_requirements.v1`
  - payload keys: `schema`, `exported_at`, `site_id`, `business_id`, `requirements`
- Import control accepts the same schema and updates matching operator requirement fields in the editor.
- Import does not auto-save, auto-generate, auto-publish, or auto-deploy.
- Unknown fields are ignored safely.
- Export/import payloads exclude secrets, credentials, deploy config, diagnostics, raw prompts/provider payloads, and media bytes.

## Media Discovery, Upload, and Safety Boundaries (2026-05)
Source-site media discovery:
- source ingest now captures bounded discovered image metadata under:
  - `source_snapshot.discovered_images`
- source image discovery now scans a bounded set of source pages (default max 8):
  - homepage always
  - prioritized same-site navigation/pages such as `/projects`, `/project`, `/gallery`, `/work`, `/portfolio`, `/services`, `/process`, `/about`
  - discovery does not crawl arbitrary external sites
- each discovered candidate includes bounded source provenance:
  - `source_page_url`
  - `pages_scanned_count`
  - `pages_scanned`
- discovery sources include:
  - `img[src]`
  - `img[data-src]`
  - `img[data-lazy-src]`
  - `img[data-original]`
  - `img[srcset]`
  - `img[data-srcset]`
  - `picture/source[srcset]`
  - inline `style="background-image:url(...)"` when present
  - OpenGraph/Twitter image meta tags
- GoDaddy/wsimg media URLs (for example `img1.wsimg.com/isteam/...`) are normalized with canonical dedupe keys so crop/resize variants do not inflate counts
- candidate validation is bounded and content-type aware:
  - HEAD-first probe, bounded GET fallback when needed
  - accepts image content types only (`image/jpeg`, `image/png`, `image/webp`, `image/gif`, `image/avif`)
  - HTML/text route URLs (for example `/m`, `/projects`, `/services`) are rejected as non-image candidates
- normalized URLs are deduplicated and query strings are stripped from normalized metadata fields
- discovery diagnostics remain bounded:
  - no raw source HTML dumps
  - no raw media bytes exposed in operator payloads

Workspace media APIs:
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}/preview`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload`
- `PATCH /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}/lifecycle`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}/suggest-metadata`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/suggest-metadata`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import`

Workspace/site scoping contract:
- media list/upload/update operations are scoped by both tenant business and `site_id`
- assets from one site workspace are not visible in another site workspace, even within the same tenant
- cross-site update/select attempts return not-found behavior rather than mutating another workspace
- late frontend requests are discarded when their captured business/site scope or request generation is no longer current

Media / Images compact browser behavior:
- migration media UI now uses compact Site Image cards in a responsive grid instead of verbose stacked rows
- default card content is intentionally minimal:
  - short image name
  - thumbnail preview (or compact preview-unavailable placeholder)
  - source/status badges (`Uploaded`, `Discovered`, `Imported`, `Included in draft`)
  - one primary next action
  - optional compact reason label
- grid density:
  - desktop: up to 4 columns
  - tablet: 2 columns
  - mobile: 1 column
- acquisition controls are visible at the top of the section:
  - `Upload images` (disclosure)
  - `Discover / Refresh Source Images` (reuses existing ingest path)
  - `Use checked images in draft` (bulk action)
- checkbox semantics are explicit:
  - checked means `Use in draft`
  - unchecked means do not include in next draft
  - unsafe rejected rows keep checkbox disabled
- verbose metadata remains available, but is disclosure-only per image:
  - full URL
  - provenance details
  - suggestion and candidate-quality diagnostics
- primary actions are simplified:
  - per-image: `Use in draft` (or `Use in draft anyway` for low-value safe candidates)
  - bulk: `Use checked images in draft`
  - unsafe rejected images have no import/use action
- combined use-in-draft behavior:
  1. import checked/per-image safe discovered assets if needed
  2. mark included in draft (`selected_for_draft=true`)
  3. run metadata suggestion analysis when available
  4. apply safe suggestions when supported, otherwise stage suggestions
- quality vs safety boundary:
  - low-value is a quality warning only
  - unsafe rejected is a hard block
- simplified local filters:
  - `All usable images`
  - `Discovered`
  - `Uploaded/imported`
  - `Unsafe rejected`
- removed/retired controls:
  - `Insert into requirements`
  - per-card `Preview`
  - per-card `View details`
  - `Show low-value/rejected` toggles

Operator uploads:
- uploads are stored as workspace-scoped media assets with provenance `operator_upload`
- upload UI supports selecting multiple images in one action; shared metadata fields apply to all selected files in that batch
- validation enforces:
  - allowed MIME: `image/jpeg`, `image/png`, `image/webp`, `image/gif`
  - extension checks
  - max upload bytes (`8 MiB`)
  - max upload count per workspace (`80`)
- uploaded media metadata is bounded and includes safe fields (id, filename, type, size, dimensions, category, alt/description/usage, page assignment, provenance)
- local/internal storage keys are not returned in operator-facing API payloads
- uploaded/imported preview behavior:
  - active workspace assets with local storage receive a bounded same-origin authenticated `preview_url`
  - toggling `Use in draft` (`selected_for_draft=true`) must preserve preview metadata for that asset; selection state updates should not blank preview thumbnails for still-active assets
  - preview bytes are served only through `GET .../migration/media/assets/{asset_id}/preview`
  - preview route enforces site/workspace authorization, image content-type validation, max preview size, and safe storage-root path checks
  - preview failures return bounded reasons (`storage_preview_not_available`, `unsupported_content_type`, `file_too_large`)

AI-assisted media metadata suggestions (2026-05):
- suggestion fields are stored separately from operator-authored fields under `metadata_suggestion`:
  - `suggested_category`
  - `suggested_alt_text`
  - `suggested_description`
  - `suggested_usage_note`
  - `suggested_page_assignment`
  - optional `confidence`
  - `suggestion_source` (`ai_image_recognition`)
  - `suggestion_status` (`pending|completed|failed|not_available`)
  - optional `reason_code`
  - optional `generated_at`
  - optional `model_diagnostics` (`task_alias`, `source`, `model`, `fallback_used`, `validation_status`, compatibility flags, optional safe message)
- operator-authored values are never overwritten automatically
- operator can explicitly apply a completed suggestion via media update payload:
  - `apply_suggested_metadata: true`
- batch suggestion (selected assets) is available through:
  - `POST .../migration/media/assets/suggest-metadata`
  - request: `asset_ids: string[]`, optional `force_refresh: boolean`
  - per-asset processing is independent; one asset failure does not fail the entire batch
  - response includes:
    - `batch_status` (`completed|partial_success|failed`)
    - `results[]` per asset (`asset_id`, `suggestion_status`, `reason_code`, `retryable`, optional `metadata_suggestion`)
    - `completed_count`, `failed_count`, `skipped_count`
  - max batch size is enforced with deterministic validation reason:
    - `media_suggestion_batch_limit_reached`
- remote discovered images that are not imported/controlled return staged not-available guidance:
  - `image_not_imported`
  - no raw remote URL handoff to provider in this pass
- suggestion response payloads remain metadata-only:
  - no local file paths
  - no storage keys
  - no raw bytes/base64
  - no auth tokens/headers/cookies
- media metadata suggestions now resolve through task alias `media_metadata_helper`; default runtime behavior remains compatibility-mapped to the shared legacy model chain until helper-specific model choices are configured
- local automated tests for this capability mock provider responses; no real provider calls are required for test runs

Error contract highlights:
- unsupported MIME -> `unsupported_mime_type`
- payload/declared MIME mismatch -> `media_upload_content_type_mismatch`
- file too large -> `file_too_large`
- workspace max upload count reached -> `workspace_media_upload_limit_reached`
- missing/invalid media asset id in update route -> `media_asset_id_required`

Draft generation media contract:
- only selected media metadata is included in AI context (`migration_context.media_assets.selected_assets`)
- discovered-but-not-selected source images are summarized in counts/provenance only and are not expanded into full draft media context
- selected media context is trimmed to a bounded count when necessary
- raw image bytes/base64 are not sent to the AI provider
- draft context uses effective metadata precedence:
  - operator-authored/applied metadata first
  - AI suggestion metadata only as bounded fallback when suggestion status is completed
- when no media is selected, generation should rely on placeholders and must not invent approved media assets

Draft input summary media suggestion counters:
- `media_assets_with_ai_suggestions_count`
- `media_assets_with_operator_applied_metadata_count`
- `media_suggestion_failures_count`

Suggestion reason codes:
- `image_metadata_suggested`
- `image_analysis_not_available`
- `image_not_imported`
- `unsupported_image_type`
- `image_too_large`
- `provider_unavailable`
- `provider_response_invalid`
- `image_metadata_model_incompatible`
- `media_asset_not_found`
- `media_asset_not_authorized`
- `media_suggestion_batch_limit_reached`

Selected discovered-image import (runtime-gated, 2026-05):
- runtime flag: `SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED`
  - default: `true` (enabled unless explicitly disabled in runtime config)
- when disabled:
  - discovered import endpoint returns per-asset `status=disabled` with reason `remote_import_disabled`
  - metadata suggestion for remote-only discovered assets still returns `image_not_imported`
- imports are operator-selected only:
  - endpoint accepts discovered ids/URLs already present in `source_snapshot.discovered_images`
  - no arbitrary new remote URLs are accepted
  - no auto-import of all discovered images
  - no hotlink fallback in generated artifacts
- imported assets are stored as workspace media assets under source provenance (`source_site_import`) and become eligible for:
  - per-asset metadata suggestion
  - batch metadata suggestion
  - selected-media draft context (metadata only)
- import response contract is per-asset and bounded:
  - `status`: `imported|skipped|failed|disabled`
  - `reason_code`: deterministic import reason
  - optional sanitized `media_asset` (no storage key, no local path, no raw bytes/base64)
- import controls are explicit and lifecycle-safe:
  - per-card combined action (`Use in draft` / `Use in draft anyway`) provides pending/success/failure feedback
  - bulk action (`Use checked images in draft`) processes only checked safe images
  - unchecked assets are never auto-imported or auto-included

Import safety controls:
- only `http`/`https` schemes
- URL must already exist in discovered snapshot metadata
- DNS/IP safety checks before fetch (private/loopback/link-local/multicast/reserved blocked)
- cloud metadata endpoints blocked (including `169.254.169.254`/`metadata.google.internal`)
- redirect escape prevention (redirect target is re-validated)
- bounded timeout and response-size limits
- allowed image MIME types match upload policy (`jpeg/png/webp/gif`)
- SVG remains disallowed in this pass
- content-type mismatch is rejected

Production storage contract (2026-08-28):
- imported and uploaded source bytes use the injected migration media storage contract
- production uses a private, versioned GCS bucket; local filesystem storage is development/test only
- persisted private metadata includes object generation, byte length, and SHA-256 digest
- generation-pinned reads verify byte length and digest before preview analysis or artifact materialization
- bucket/object coordinates and checksums are omitted from operator API responses
- storage configuration and recovery procedures are documented in `docs/runbooks/migration-media-storage.md`

Import reason codes:
- `remote_import_disabled`
- `candidate_not_validated`
- `blocked_private_network`
- `unsupported_content_type`
- `file_too_large`
- `fetch_timeout`
- `unsafe_redirect`
- `storage_write_failed`

Low-value override import semantics:
- low-value candidates that pass safety and validation checks can be imported only through explicit operator override (`allow_quality_override=true`)
- safety-rejected candidates remain non-importable
- non-image routes/HTML responses (for example `/m`) remain non-importable even with override
- import remains explicit operator action only (no auto-import and no auto-select)

Media lifecycle action rules (coherence pass, 2026-05):
- discovered remote source assets are not draft-usable by default (`import_status=discovered`)
- use-in-draft operator flow:
  - primary actions are `Use in draft` (per-image) and `Use checked images in draft` (bulk)
  - discovered assets are imported as part of that combined action when validation/safety checks pass
- uploaded/imported assets:
  - can be included in draft immediately and analyzed in the same combined action
- low-value/rejected discovered candidates:
  - low-value safe candidates can be used via explicit operator override (`Use in draft anyway` / `allow_quality_override=true`)
  - safety-rejected candidates are excluded from import, draft selection, and AI suggestion actions
  - remain visible for diagnostics under `Unsafe rejected` filter with blocked status

Media remove/ignore semantics:
- discovered (not imported):
  - `Ignore` hides candidate from default usable workflows and clears draft inclusion
  - source discovery evidence is preserved in workspace diagnostics/history
- imported source assets:
  - `Remove from workspace` clears draft inclusion and marks workspace lifecycle as removed
  - does not delete the original source-site URL
- uploaded assets:
  - `Remove image` clears draft inclusion and marks/removes the workspace asset safely
- lifecycle result reasons are bounded:
  - `removed`
  - `ignored`
  - `already_removed`
  - `not_found`
  - `not_authorized`
  - `unsafe_delete_blocked`
  - `storage_delete_failed`

Low-value discovered-image classification (bounded heuristic, no remote fetch):
- classifier emits:
  - `candidate_quality`: `useful|low_value|rejected`
  - `quality_reason`: deterministic reason code when applicable
- examples:
  - `placeholder_image_detected` (placeholder/spacer/transparent-loader style URL/name)
  - `tracking_pixel_detected` (tracking/beacon/pixel style URL/name)
  - `layout_asset_detected` (logo/icon/sprite/chrome imagery)
  - `non_image_candidate_detected` (HTML/page-like or non-image extension)
- when uncertain, classification defaults to `useful`
- low-value/rejected discovered candidates do not improve media-readiness quality counts

Media lifecycle enforcement reason codes:
- `media_asset_not_imported`
- `media_asset_not_available`
- `media_asset_low_value`
- `media_asset_rejected`
- `media_action_not_allowed_for_state`
- `placeholder_image_detected`
- `tracking_pixel_detected`
- `layout_asset_detected`
- `non_image_candidate_detected`

Migration operator flow (streamlined):
1. Ingest source.
2. Discover source images.
3. Check images to use in draft (safe discovered + uploaded/imported).
4. Use checked images in draft (`Use in draft anyway` is available only for safe low-value candidates).
5. Generate draft with bounded context.
7. Review, approve, publish, and deploy explicitly.

Draft-context budget/operator diagnostics:
- migration draft input summary shows bounded context coverage and trim behavior:
  - recommendation included vs available counts
  - recommendation basis (`interpreted_audit_context` when recommendations are used as the audit-derived layer)
  - draft context trimmed state
  - largest included block when available
- selected media only:
  - discovered-but-not-imported assets are summarized but not expanded into selected media context
  - selected/imported asset metadata is included; raw media bytes are never included

Admin-configured migration generation budget:
- migration generation limits are admin-governed via:
  - `namespace_isolation_defaults.migration_generation_budget`
- supported controls:
  - `migration_context_budget_chars`
  - `migration_recommendation_limit`
  - `migration_competitor_limit`
  - `migration_source_page_summary_limit`
  - `migration_media_asset_limit`
  - `migration_generated_page_limit`
  - `migration_generated_file_limit`
  - `migration_generation_depth` (`compact|standard|expanded`)
  - `migration_variation_level` (`conservative|balanced|differentiated`)
  - `migration_require_page_variety`
  - `migration_require_design_variation`
- default bounded values when admin config is absent:
  - `migration_context_budget_chars=90000`
  - `migration_generated_page_limit=20`
  - `migration_generated_file_limit=16`
  - `migration_media_asset_limit=16`
- server-side validation enforces bounded min/max ranges.
- effective values flow into context shaping/trimming and provider request budget enforcement.
- migration workspace exposes read-only effective budget summary in Draft Inputs / AI Context (profile, variation, context chars, page/file limits); editing remains admin-only.
- optional runtime overrides are supported for controlled operations:
  - `MIGRATION_AI_CONTEXT_BUDGET_CHARS`
  - `MIGRATION_AI_PAGE_LIMIT`
  - `MIGRATION_AI_MEDIA_LIMIT`
  - `MIGRATION_AI_MAX_FINAL_INPUT_CHARS`
  - `MIGRATION_AI_MAX_DIFFICULTY_SCORE`
  - `MIGRATION_AI_COMPACT_PAGE_LIMIT`
  - `MIGRATION_AI_COMPACT_MEDIA_LIMIT`
  - `MIGRATION_AI_COMPACT_RECOMMENDATION_LIMIT`
  - values are always clamped to backend hard caps.

## Site SEO Workspace Grouping and Diagnostics (2026-05)
Migration route grouping in the UI now explicitly separates:
- Operator Actions:
  - generate/approve/publish/deploy/refresh/delete + media upload/select/edit actions
- Draft Inputs / AI Context:
  - recommendation/operator/enriched/competitor/analytics/audit/media provenance summary
- Media / Images:
  - discovered source images
  - operator uploads
  - selected assets used for draft context
  - media lifecycle labels for operator clarity:
    - `Discovered`
    - `Uploaded`
    - `Imported` (when import/selection state indicates controlled availability)
    - `Included in Draft`
    - `AI Suggested`
    - `Applied`
    - `Not Available` / `Rejected`
  - batch suggestion action for selected assets with per-asset result feedback
- Metrics:
  - readiness/AI execution/runtime metrics in primary workflow cards
- Diagnostics / Debug Output:
  - advanced troubleshooting and history under `F. Advanced Diagnostics & History`
  - media safety/import rejection reasons are shown in `Media Diagnostics`, not in the primary media action cards

## Google Integration Reconnect vs Operator Session
Draft diagnostics now surfaces targeted guidance distinguishing:
- Google integration reconnect requirements (analytics/integration scope)
- operator app session/auth expiration

Deterministic draft-generation reason codes:
- `app_auth_required`: app bearer/session auth is missing or invalid; sign back into MBSRN
- `session_expired`: app session token is expired/invalid; sign back into MBSRN
- `google_reconnect_required`: Google consent/token state requires reconnect before live Google signals can be used
- `google_integration_unavailable`: Google integration state could not be read reliably; retry then reconnect if persistent
- `draft_generation_context_unavailable`: non-auth context assembly failure; retry and escalate if persistent

Operator rule:
- Google reconnect-required states are integration warnings and should not be interpreted as automatic operator logout.
- expired/revoked integration consent should surface reconnect guidance, while preserving existing app-session behavior.

Draft-generation error envelope (`POST .../generate-draft-artifacts`, HTTP 422 detail payload):
- `message`
- `reason_code`
- `error_code`
- `retryable`
- `operator_action`
- optional `reconnect_target`
- optional bounded `diagnostic_context` (no secrets/tokens/raw payloads)

The route preserves existing HTTP semantics and keeps prior diagnostic fields (`failure_category`, `failure_reason`, correlation/version/provider metadata) for operator/debug workflows.

## Reused Context Availability Semantics
Migration reused-context cards use best-available signal, not strict completeness.

Definition:
- `Available` means usable site data exists for that context in current system records.
- `Not yet available` means no usable signal was found.
- Migration does not require migration-specific snapshots, approved artifacts, or perfect summary coverage before marking context available.

Fallback rules:
- Audit: available when any successful audit run exists (`latest_successful_run`).
- Recommendations: available when generated recommendation content exists (latest generated recommendation records and/or completed recommendation runs).
- Competitors: available when usable competitor run/domain signal exists (latest usable comparison run or active competitor domain candidates).

Operational note:
- Reused context cards can show `Available` even when `existing_context_summaries.*` entries are null, because summaries are not the only source-of-truth signal for availability.

## Draft Generation Preflight Readiness
Migration readiness can be read from two surfaces:
- summary-derived readiness: `context_summary.draft_generation_readiness`
- lightweight endpoint: `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/draft-readiness`

`draft-readiness` endpoint behavior:
- does not invoke the AI provider
- does not force Google OAuth redirect
- returns bounded operator-safe state only (no tokens, headers, cookies, secret values, or raw media bytes)
- inspects stored workspace/context signals and returns blocking vs warning reason codes

Payload shape:
- `status`: `ready` | `ready_with_warnings` | `not_ready`
- `score`: deterministic 0-100 readiness score
- `hard_blocked`: true when generation must be blocked
- `summary`: short operator-safe guidance
- `reasons`: structured entries with `code`, `severity` (`blocking` or `warning`), and operator-safe `message`
- `signals`:
  - `source_site_ingested`
  - `operator_requirements_present`
  - `enriched_content_present`
  - `audit_available`
  - `recommendations_available`
  - `competitors_available`
  - `draft_provider_configured`

Draft-readiness endpoint fields (operator preflight contract):
- `ready`
- `blocking_reason_codes`
- `warning_reason_codes`
- `app_auth_ready`
- `google_integration_ready` (`true`/`false`/`null`)
- `google_reconnect_required`
- `live_google_data_required`
- `draft_context_ready`
- `recommendations_available_count`
- `competitor_profiles_available_count`
- `selected_media_assets_count`
- `source_site_images_discovered_count`
- `media_required_by_operator`
- `media_requirement_sources`
- `usable_media_assets_count`
- `useful_discovered_images_count`
- `low_value_discovered_images_count`
- `rejected_discovered_images_count`
- `selected_usable_media_assets_count`
- `media_requirement_satisfied`
- `media_requirement_warning_reason`
- `operator_action`

Scoring weights:
- source site ingested: +15
- operator requirements present: +25
- enriched content present: +25
- audit available: +10
- recommendations available: +10
- competitors available: +10
- completeness bonus (all above true): +5

Decision behavior:
- `not_ready` when one or more blocking signals are present
- `ready` when no blockers and score >= 80
- `ready_with_warnings` when no blockers and score < 80

Blocking signals (generation disabled):
- source ingest missing
- operator requirements missing
- enriched replacement content missing
- known provider misconfiguration for draft generation

Warning-only signals (generation still allowed):
- missing audit/recommendation/competitor reused context
- sparse enriched content
- explicit media requirement exists but no usable selected/imported/uploaded media is present (`media_required_but_not_selected`)

Runtime behavior:
- generate draft endpoint performs this preflight check first
- if `hard_blocked=true`, provider is not called and API returns a sanitized validation error
- readiness evaluations emit structured logs: `event=seo_migration_readiness_evaluation`
- routine readiness outcomes (including expected operator blockers such as missing ingest or requirements) are logged as non-error telemetry; error severity is reserved for unexpected runtime/platform failures
- when live Google fetch is not required for draft generation, Google reconnect can surface as warning-only readiness guidance instead of a hard block

## Draft Provider Compatibility Preflight
Workspace readiness and provider compatibility are separate controls:
- Workspace readiness answers: "Do we have enough migration inputs/context to proceed?"
- Provider compatibility answers: "Does the currently configured AI provider/model/request shape support migration draft generation?"

Compatibility is evaluated after readiness and before any outbound provider request.
Compatibility decisions are now request-shape matrix driven (migration-specific), using:
- model family/pattern
- endpoint path
- execution mode
- response format mode
- request body construction mode

Resolved migration model precedence before compatibility evaluation and provider invocation:
1. explicit/requested model (when provided by current workflow)
2. Admin task override for the current task alias (`businesses.ai_model_overrides`)
3. business admin legacy/global fallback (`businesses.default_ai_model`)
4. deployment env bootstrap/shared fallback (`AI_MODEL_NAME`)
5. provider/runtime fallback

Phase 1 AI task registry notes:
- migration draft generation resolves through the `migration_site_generation` task alias;
- migration planning/repair/explainer paths resolve through `migration_site_plan`, `migration_section_repair`, `validation_explainer`, `migration_live_contract_validation`, and `maintenance_cleanup` when those flows execute;
- requirements suggestion helper resolves through `requirements_helper`;
- media metadata suggestion helper resolves through `media_metadata_helper`;
- Admin can set per-task values from the `AI Task Model Routing` section without changing deploy manifests;
- `default_ai_model` remains the legacy/global fallback field and `AI_MODEL_NAME` remains bootstrap fallback only;
- task aliases exist centrally, but current runtime behavior remains compatibility-mapped to the shared legacy model path until a later cutover phase unless an Admin task override is set;
- deprecated or blocked raw model strings are rejected for new explicit/admin updates, while legacy stored/admin/env/provider defaults can continue under compatibility mapping until they are migrated.

Operational implication:
- changing a task override can change one migration task alias immediately without changing other aliases;
- changing the legacy/global fallback can still affect migration compatibility/readiness for aliases that inherit it.

### Admin AI task routing for migration
- Relevant migration/admin aliases include `requirements_helper`, `media_metadata_helper`, `migration_site_plan`, `migration_site_generation`, `migration_section_repair`, `validation_explainer`, `migration_live_contract_validation`, and `maintenance_cleanup`.
- Practical starting points when you choose to override manually:
  - `requirements_helper`, `validation_explainer`: `gpt-5.6-luna`
  - `media_metadata_helper`, `migration_site_plan`, `migration_section_repair`: `gpt-5.6-terra`
  - `migration_site_generation`: `gpt-5.6`
- Clearing a row in Admin rolls that alias back to the legacy/global fallback chain.
- Routing changes affect model selection and readiness diagnostics only; they do not train, fine-tune, or locally host a model.

Compatibility payload (in `context_summary.draft_provider_compatibility`):
- `supported`
- `reason_code`
- `operator_message`
- `retryable`
- `provider_name`
- `model_name`
- `endpoint_path`
- `execution_mode`
- `web_search_enabled`
- `degraded_mode`
- `response_format_mode`
- `request_body_mode`
- `admin_summary` (sanitized short admin hint)

Common compatibility reason codes:
- `provider_not_configured`
- `unsupported_model_configuration`
- `unsupported_request_shape`
- `unsupported_endpoint_mode`
- `tools_required_but_unavailable`
- `degraded_mode_not_allowed`
- `unknown_provider_capability`

Known supported request shape (current allowlist example):
- `model=gpt-5*` with `endpoint_path=/responses`, `execution_mode=full`, `response_format_mode=json_schema`, and `request_body_mode=responses_text_format_json_schema`.
- current Admin starting point for `migration_site_generation` remains `gpt-5.6`; resolved `gpt-5.6*` task models use this same `/responses` structured-output profile.

Migration `/responses` request contract is now locked to a known-good structured-output shape:
- top-level keys: `model`, `input`, `text`
- `input` must be a single non-empty string (not array/object/message-style input)
- no legacy chat keys in `/responses` payloads (`messages`, `response_format`)
- `text.format.type=json_schema`
- `text.format.name=seo_migration_artifact_response`
- `text.format.strict=true`
- migration schema object nodes require `additionalProperties=false`
- migration strict-schema object nodes require full `required` coverage for declared properties (optional fields are represented with nullable types rather than omitted `required` entries)

Runtime contract guard:
- `event=seo_migration_draft_provider_request_contract_guard` is emitted before provider invocation when the request fingerprint is evaluated.
- warning-only drift (for example short input text) is logged and allowed.
- blocking drift (for example non-string `input`, extra top-level keys, text-format/schema strictness drift) is blocked locally with `unsupported_request_shape_contract_drift` before outbound provider call.

Known unsupported request shapes (blocked locally):
- `model=gpt-5*` with `endpoint_path=/chat/completions`, `execution_mode=full`, `response_format_mode=json_schema`, and `request_body_mode=chat_json_schema` is treated as `unsupported_request_shape`.
- fallback/default model paths (for example `gpt-4o-mini` using migration chat/json_schema request construction) are blocked unless that exact request shape is explicitly allowlisted and validated.

Unknown/unlisted model/request-shape combinations default to local block (`unsupported_model_configuration`) so parseable-but-unsupported shapes do not reach provider execution.

Admin model-routing compatibility notes:
- task/model compatibility is validated before outbound draft generation.
- GPT-5-family non-tool structured-output requests prefer the modern `/responses` JSON-schema contract.
- when a request shape is auto-adjusted for compatibility, logs expose only sanitized markers (`request_shape_adjusted`, `request_shape_adjustment_reason`) and never raw prompt text.

Behavior:
- if compatibility is unsupported, draft generation fails fast locally
- outbound provider request is not attempted
- failure is persisted using existing draft-failure diagnostics (`failure_category`, `failure_reason`, `error_code`, `retryable`, correlation id)
- operator receives a concise sanitized message (for example, unsupported model/request-shape guidance)

### Shared AI reliability substrate (migration adapter)
Migration draft generation now runs through the same synchronous reliability core used by recommendation and competitor AI paths:
- bounded timeout + retry policy
- normalized failure taxonomy
- request budgeting (optional context trimmed before required context)
- workflow-specific validation entrypoint
- structured, secret-safe execution telemetry

Migration-specific degraded behavior remains strict:
- no fake draft artifacts are created on provider failure
- failed runs persist explicit diagnostics and retryability metadata
- artifact trust boundaries are unchanged (approval/publish/deploy gates remain explicit)
- unchanged oversized/complex timeout payloads are not blindly retried (`request_too_large_or_complex`)

Operator-visible AI diagnostics summary:
- migration summary now exposes a bounded AI diagnostics block at:
  - `context_summary.migration_diagnostics.last_draft_ai_diagnostics_summary`
- surfaced fields:
  - `failure_category`
  - `failure_reason`
  - `failure_source`
  - `retryable`
  - `hint`
  - `budget_outcome`
  - `retry_suppressed`
  - `trimming_pass_count`
  - `difficulty_bucket`
  - `input_size_bucket`
  - `degraded_state`
- this summary is intentionally bounded for operators/admins; full provider/request telemetry remains log-only.
- shared hint semantics now align with recommendation/competitor surfaces:
  - `Input too large`
  - `Provider timeout`
  - `Invalid provider response`
  - `Configuration issue`
  - `Try again later` (transport/rate-limit availability cases)

Structured logging:
- shared execution-core lifecycle emits:
  - `event=ai_execution_preflight`
  - `event=ai_execution_precall_rejected`
  - `event=ai_execution_retry_suppressed`
  - `event=ai_execution_completed`
  - `event=ai_execution_failed`
- migration adapter budget summary emits:
  - `event=seo_migration_draft_request_budget`
  - `budget_outcome=precall_rejected|provider_submission`
  - `dropped_optional_blocks` (trim order evidence)
- compatibility evaluation emits `event=seo_migration_provider_compatibility_evaluation`
- includes identifiers and request-shape metadata (`business_id`, `site_id`, `workspace_id`, `provider_name`, `model`, `endpoint_path`, `execution_mode`, `web_search_enabled`, `degraded_mode`, `response_format_mode`, `request_body_mode`, `supported`, `reason_code`, `retryable`)
- request-shape logs also include `task_alias`, `request_shape_adjusted`, and `request_shape_adjustment_reason` so Admin routing changes are traceable without exposing raw payloads
- migration summary diagnostics also expose `draft_provider_compatibility_admin_summary` (sanitized admin hint from compatibility decision) for operator/admin troubleshooting
- compatibility logs include `decision`:
  - `blocked_local_preflight` for local preflight block
  - `allowed` when the request shape is compatible
- remote provider rejections use provider request-failure logs (`event=seo_migration_draft_provider_request_failure`) with `failure_source=remote_provider`
- provider request start/failure logs include a sanitized request-contract fingerprint:
  - `request_fingerprint_model`
  - `request_fingerprint_endpoint_path`
  - `request_fingerprint_request_body_mode`
  - `request_fingerprint_has_text_format`
  - `request_fingerprint_text_format_type`
  - `request_fingerprint_schema_name`
  - `request_fingerprint_strict_enabled`
  - `request_fingerprint_top_level_keys`
  - `request_fingerprint_text_top_level_keys`
  - `request_fingerprint_text_format_keys`
  - `request_fingerprint_schema_top_level_keys`
  - `request_fingerprint_input_mode`
  - `request_fingerprint_input_length_chars`

Maintainer tuning guidance:
- adapter budget knobs are defined in `app/integrations/seo_migration_artifact_provider.py`:
  - `_MIGRATION_CONTEXT_BUDGET_CHARS`
  - `_MIGRATION_DRAFT_MAX_TOTAL_INPUT_SIZE`
  - `_MIGRATION_REQUIRED_CONTEXT_KEYS`
  - `_MIGRATION_OPTIONAL_TRIM_ORDER`
- change budget constants only with test updates that prove required context blocks remain retained and optional trim order stays deterministic.
- tune budgets based on telemetry trends (`budget_outcome`, `retry_suppressed`, `difficulty_bucket`, `input_size_bucket`) rather than one-off failures.
  - `request_fingerprint_has_null_optional_fields`
  - `request_fingerprint_has_extra_request_options`
  - `request_fingerprint_contains_tools`
  - `request_fingerprint_contains_response_format_legacy`
  - `request_fingerprint_contains_messages_legacy`
  - `request_fingerprint_schema_object_nodes_total`
  - `request_fingerprint_schema_object_nodes_non_false_additional_properties`
  - `request_fingerprint_schema_object_nodes_missing_required`
  - for supported migration `/responses` requests, `request_fingerprint_input_mode=string` is required
  - for supported migration `/responses` requests, `request_fingerprint_has_extra_request_options=false` and `request_fingerprint_has_null_optional_fields=false` are expected

Payload drift debugging:
- use provider redacted payload snapshot helpers to compare the app-emitted payload shape to the known-good curl contract without exposing raw prompt text
- compare fingerprint + snapshot together when diagnosing remote `unsupported_configuration` responses

Local live-validation harness:
- Script: `scripts/live_validate_seo_migration_responses.py`
- Purpose: execute one real migration `/responses` request with the production request builder and emit only safe diagnostics.
- Input: `AI_API_KEY` from env (or `.env` local file), mapped to runtime provider config without persisting secrets.
- Safe output fields:
  - `execution.model_used`
  - `execution.endpoint_path`
  - `execution.request_body_mode`
  - `execution.compatibility_decision`
  - `execution.request_contract_status`
  - `execution.provider_execution_status`
  - `execution.artifact_status`
  - `execution.artifact_result`
  - `execution.duration_ms`
  - `request_fingerprint.*` (sanitized)
  - `redacted_request_snapshot_overview`
- Expected success indicators:
  - `status=succeeded`
  - `execution.provider_execution_status=accepted`
  - `execution.artifact_result=succeeded`
  - `known_good_contract_diff=[]`

## Draft AI Execution Visibility
Migration summary now includes a compact execution slice in `context_summary.ai_execution`:
- `model_requested`
- `model_resolved`
- `model_used`
- `endpoint_path`
- `request_body_mode`
- `compatibility_decision`
- `request_contract_status`
- `provider_execution_status`
- `artifact_status`
- `artifact_result`
- `duration_ms`
- `timeout_seconds`
- `timeout_source` (`admin` or `default`)

Field meanings:
- `model_requested`: explicit model override requested by workflow input (null when not used).
- `model_resolved`: model chosen after precedence resolution.
- `model_used`: model reported by the execution attempt/output.
- `request_body_mode`: sanitized request-construction profile key (for example `responses_text_format_json_schema`).
- `compatibility_decision`: whether the request shape was allowed or locally blocked (`allowed` or `blocked_local_preflight`).
- `request_contract_status`: compact contract outcome (`accepted`, `accepted_with_warnings`, `blocked`, `rejected`).
- `provider_execution_status`: provider call outcome (`accepted`, `rejected`, `not_called`, `unknown`).
- `artifact_status` / `artifact_result`: persisted artifact outcome for latest draft generation (`completed`/`succeeded`, `partial`, `failed`).
- `duration_ms`: end-to-end draft generation duration for the recorded execution.

Failure-source visibility:
- `context_summary.migration_diagnostics.last_draft_failure_source=local_preflight` means generation was blocked before provider invocation.
- `context_summary.migration_diagnostics.last_draft_failure_source=remote_provider` means the outbound request was attempted and rejected remotely.

Success-path contract verification:
- `request_contract_status=accepted` and `provider_execution_status=accepted` with `artifact_result=succeeded` indicates the request contract was allowed locally, accepted by provider, and completed successfully.
- `request_contract_status=accepted_with_warnings` indicates partial/salvaged completion.

## Admin Migration Generation Safety
Migration draft timeout and preflight risk controls are now governed by Admin namespace isolation settings:

- `migration_provider_timeout_seconds` (range `60-600`, default `300`)
- `migration_preflight_mode` (`compact_fallback` or `block_before_provider`)
- `migration_max_final_input_chars` (range `3000-64000`, default `32000`)
- `migration_max_difficulty_score` (range `5-24`, default `18`)
- `migration_compact_fallback_enabled` (`true|false`, default `true`)
- `migration_compact_page_limit` (range `1-10`, default `6`)
- `migration_compact_media_asset_limit` (range `0-8`, default `5`)
- `migration_compact_recommendation_limit` (range `0-12`, default `8`)
- generation-budget hard caps used by backend preflight:
  - `migration_context_budget_chars <= 150000`
  - `migration_generated_page_limit <= 30`
  - `migration_generated_file_limit <= 24`
  - `migration_media_asset_limit <= 24`

Admin configurability behavior:
- Admin UI accepts requested numeric values for migration budget/safety without silent frontend clamping.
- Backend policy remains the source of truth for effective hard caps used at runtime.
- Save outcomes are explicit:
  - valid value within cap: persisted
  - above-cap or below-floor numeric value: persisted as requested and surfaced with effective bounded value + cap reason
  - invalid/non-numeric structure: rejected with field-specific backend validation feedback
- Admin effective preview shows requested vs effective values and cap reasons for migration generation controls.

Behavior:
- Backend preflight computes bounded request metrics before provider invocation:
  - `original_input_size`
  - `final_input_size`
  - `difficulty_score`
  - `trimming_pass_count`
  - dropped optional blocks
- difficulty scoring is derived from final/compacted payload characteristics rather than stale raw pre-trim context
- selected media metadata remains bounded and should not, by itself, block normal drafts when final input stays within configured caps
- If thresholds are exceeded:
  - `compact_fallback` mode attempts one compact context build using compact limits.
  - `block_before_provider` mode blocks without calling provider.
- If compact fallback still exceeds effective thresholds, generation is blocked before provider call with:
  - `reason_code=migration_generation_preflight_too_large`
  - `failure_source=local_preflight`
- timeout source of truth is `migration_generation_safety.migration_provider_timeout_seconds`
  - legacy business-level migration draft timeout settings are compatibility-only and not the primary control path
- synchronous runtime timeout remains hard-capped at `600` seconds effective
  - higher requested values are preserved for operator/admin intent but clamped to effective `600` at runtime
  - requests that require longer execution should move to async/background architecture

Timeout and preflight diagnostics are surfaced in bounded form:
- `context_summary.migration_diagnostics.draft_timeout_seconds`
- `context_summary.migration_diagnostics.draft_timeout_source`
- `context_summary.migration_diagnostics.last_draft_failure_timeout_seconds`
- `context_summary.migration_diagnostics.last_draft_failure_timeout_source`
- `context_summary.ai_execution.timeout_seconds`
- `context_summary.ai_execution.timeout_source`
- `context_summary.ai_execution.preflight_mode`
- `context_summary.ai_execution.max_final_input_chars`
- `context_summary.ai_execution.max_difficulty_score`
- `context_summary.ai_execution.compact_fallback_attempted`
- `context_summary.ai_execution.preflight_blocked`
- `context_summary.ai_execution.preflight_block_reason`

Operator troubleshooting cues:
- remote timeout: provider was called and timed out (for example `failure_reason=timeout`)
- local preflight block: provider was not called; reduce generation budget or keep compact fallback enabled
- preflight block diagnostics now include blocked setting, actual final input chars, configured cap, largest included block, compact fallback attempted, and explicit provider-call skipped state
- blocked diagnostics copy maps to the true blocker (`migration_max_difficulty_score`, `migration_max_final_input_chars`, or both) instead of always reporting context-budget overflow
- increasing timeout alone does not resolve oversized/overly-complex requests; use preflight/compact fallback and budget limits
- all diagnostics remain sanitized (no raw prompts, request bodies, response bodies, HTML, or media bytes)

## Unified Draft Generation State
Migration summary now includes a compact derived top-level state in `context_summary.draft_generation_state` so operator status remains coherent across reloads:

- `ready`
- `ready_with_warnings`
- `blocked_by_workspace`
- `blocked_by_provider`
- `generation_failed`
- `generation_partial`
- `generation_succeeded`

Derivation order (deterministic):
1. workspace readiness hard blockers -> `blocked_by_workspace`
2. provider compatibility unsupported -> `blocked_by_provider`
3. latest persisted draft generation outcome:
   - `failed` -> `generation_failed`
   - `partial` -> `generation_partial`
   - `completed` -> `generation_succeeded`
4. otherwise readiness status:
   - `ready_with_warnings`
   - `ready`

Operational use:
- this top-level state is presentation/control-plane summary only
- readiness/compatibility/diagnostic detail payloads remain the source fields for root-cause analysis
- generate action remains blocked for workspace blockers and provider incompatibility

## Source Ingest Limits and Safety
Homepage ingest remains intentionally bounded:
- HTTP(S) only
- timeout/redirect/size limits
- HTML/XHTML content-type validation
- shallow extraction only (not a broad crawler)

Normalized extraction includes:
- title/meta/canonical
- headings
- phone/email/address/contact signals
- bounded same-origin links
- service-like blocks
- static asset reference metadata
- cleaned text blocks for context assembly

## Draft Artifact Contract
Draft generation uses existing provider patterns (`mock`, `openai`, misconfigured-safe fallback) and requires structured JSON.

Guardrails:
- bounded file count and payload size
- strict static-file path/extension boundaries
- rejection of backend/runtime/infra files
- analytics snippet normalization to placeholders
- partial salvage only for valid fragments
- tolerant provider payload extraction supports:
  - raw JSON
  - markdown-fenced JSON
  - JSON wrapped with leading/trailing prose
- when a payload is partially malformed, valid generated file entries are retained and malformed entries are discarded

## Artifact Quality Evaluation (Advisory)
After draft artifact generation completes, migration now runs a deterministic, non-AI artifact quality evaluator before persistence.

Purpose:
- give operators a fast, structured quality readout before approval
- surface obvious completeness/grounding/generic-content gaps
- preserve deterministic behavior (no extra provider calls)

Stored field:
- `seo_migration_artifact_versions.artifact_quality_evaluation_json`

API exposure:
- `artifact_quality_evaluation` is included in artifact version payloads (list/get/latest summary artifact)
- `artifact_quality_evaluation_json` is also returned for backward compatibility with existing clients

Evaluation output shape:
- `quality_status`: `high` | `medium` | `low`
- `issues`: list of `{type, severity, description}` entries
- `signals`: deterministic booleans/lists (for example business/location/service signal presence, placeholder detection, missing sections)
- `operator_summary`: short human-readable summary

What is evaluated:
- content completeness:
  - required artifact file presence (`index.html`)
  - missing expected sections (services/contact)
- generic/placeholder detection:
  - known placeholder phrases (for example "Lorem ipsum", "Your business here", "We are a leading provider")
  - empty heading tags
  - repeated generic paragraph blocks
- business grounding signals:
  - business name present in generated HTML
  - location context present in generated HTML
  - expected service terms present in generated HTML
- structural sanity:
  - index HTML size bounds
  - generated HTML page count breadth
  - obvious near-duplicate page content
- operator-required media coherence:
  - if operator requirements request real/existing media and selected usable media count is zero, evaluator adds `required_media_missing`
  - if placeholder markers appear while required media is missing (for example `Project Photo Placeholder`, `Draft gallery slot`, `Replace with real`, `image-placeholder`), evaluator records warning evidence
  - quality summary avoids "No quality issues detected" messaging in this scenario

Operator guidance:
- this quality summary is advisory only in current phase
- approval, publish, and deploy gates are unchanged
- operators should treat `medium`/`low` as a review signal to improve draft artifacts before approval

### Draft Generation Failure Diagnostics
Draft generation failures are normalized and surfaced as structured diagnostics (API + persisted migration state) instead of context-free provider errors.

Failure categories:
- `provider_error`
- `artifact_invalid`
- `config_missing`
- `unknown_error`

Failure reasons (machine-readable):
- `timeout`
- `authentication_failed`
- `rate_limited`
- `malformed_response`
- `malformed_output`
- `empty_response`
- `unsupported_configuration`
- `transport_error`
- `validation_failed`
- `unknown`

Reason semantics:
- `malformed_response`: provider envelope could not be parsed (for example non-JSON transport body).
- `malformed_output`: assistant content payload was present but malformed/truncated/wrapped and required tolerant recovery handling.
- `validation_failed`: payload parsed but failed structured validation and no salvageable artifact files remained.

Operator-visible behavior:
- API failure payload includes structured fields: `message`, `failure_category`, `failure_reason`, `error_code`, `retryable`, and correlation identifiers when available.
- UI renders the sanitized backend message and a short hint (retryable/config/payload-validation) when determinable.
- failed generation attempts persist as `failed` artifact versions, and summary diagnostics expose latest draft-generation failure fields for later review.

Safety:
- operator-visible payloads exclude raw provider bodies, raw prompts, stack traces, and secrets.
- internal/provider diagnostics stay in structured logs only.

### Post-Parse Response Contract Evaluation
After provider parsing/salvage and static artifact path validation, migration draft output passes a deterministic response-contract evaluator before persistence.

Evaluation statuses:
- `accepted`: required artifact contract and minimum quality checks passed
- `accepted_with_warnings`: usable output with bounded quality warnings
- `salvaged`: usable output after dropping invalid/unsafe components
- `rejected`: parseable output failed minimum operational contract checks

Representative migration reason/warning codes:
- `empty_artifact_package`
- `missing_required_artifact_files`
- `invalid_artifact_structure`
- `insufficient_content_density`
- `partial_artifact_only`

Required migration artifact file contract (current):
- `index.html` is required.
- generated file paths are normalized before validation (including bounded handling for absolute URL paths and leading `/` paths).
- if normalization drops all candidates or no normalized file resolves to `index.html`, the evaluator rejects with `missing_required_artifact_files`.

`insufficient_content_density` meaning:
- evaluator computes per-file content length on normalized artifact files.
- low-content HTML/content files can trigger `insufficient_content_density` even when structural files are present.
- this is a deterministic contract check, not a provider transport error.

Draft rejection diagnostics now include bounded counts and file-level clues:
- `candidate_item_count`
- `normalized_item_count`
- `dropped_item_count`
- `required_artifact_files_expected`
- `required_artifact_files_present`
- `missing_required_artifact_files`
- `content_density_failures_by_file`
- `parser_rejection_reason_counts`
- `artifact_primary_file_detected`
- `retry_likelihood`

Operator/API behavior:
- only `accepted`, `accepted_with_warnings`, and `salvaged` draft outputs are persisted as successful draft versions
- `rejected` outputs persist as failed draft generations with normalized failure fields
- operator-visible errors stay sanitized; raw provider payloads and prompts remain hidden
- operator UI surfaces a compact quality indicator for partial/salvaged output (`Partial draft generated.`)
- internal reason/warning code arrays stay in logs/diagnostics, not operator-facing debug dumps

Retry guidance:
- `retry_likelihood=likely_useful` (for example `empty_artifact_package`) means a retry may recover transient generation gaps.
- `retry_likelihood=conditionally_useful` means retry may help, but content quality/shape should be reviewed.
- `retry_likelihood=unlikely_without_contract_fix` (for example structural missing required files) means retries alone are unlikely to succeed without prompt/contract/parser alignment.

Operational examples:
- Parser false-negative path issue:
  - signals: high `dropped_item_count`, populated `parser_rejection_reason_counts`, `normalized_item_count=0`
  - operator/admin action: do not spam retries; inspect parser/path diagnostics first, then retry after correction.
- Real missing required files:
  - signals: `missing_required_artifact_files` includes `index.html`
  - operator/admin action: treat as contract/prompt/normalization mismatch; fix generation shape before retry.
- Density-only rejection:
  - signals: `content_density_failures_by_file` populated with required files present
  - operator/admin action: improve generated content depth; retry is conditionally useful once content shape is improved.

## Preview release workflow (2026-08)

`POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/preview-release`
approves the selected artifact when necessary and creates or resumes its preview release. Repeating the request returns the same release; it does not create another release or treat the existing approval as an error.

The canonical site `preview_slug` is a precondition. The operator workflow exposes an editable confirmation gate until infrastructure locks the value. A repository name may seed a suggestion but cannot substitute for the saved site identity. The API validates this prerequisite before approval; a missing or invalid identity returns `preview_slug_required` without changing artifact approval state.

The response is intentionally operator-focused: release identity, current operation, canonical preview hostname, and the eight ordered gates. Provider payloads and gate `details_json` are not included in this standard response.

Release inspection endpoints are:

- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/preview-releases`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/preview-releases/{release_id}`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/preview-releases/{release_id}/reconcile`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/preview-releases/{release_id}/advance`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/diagnostics/collect` (administrator only)

Reconciliation advances a gate only when evidence belongs to the release's exact artifact, commit, certificate binding, and fingerprint. `advance` executes exactly one pending external gate. A failed gate records a stable reason and support ID and can be retried without repeating successful gates. A selected certificate is immutable for that release.

The certificate step always reconciles the deployment workflow and certificate manifest, including when the exact artifact commit was published previously. A verified duplicate is therefore an idempotent success for the release. A failure after Compute certificate publication is reported as certificate-manifest publication failure so the operator can retry the same release without generating another certificate.

The DNS action is labeled **Continue: DNS & deployment**. Selecting it is explicit, release-scoped authorization to ensure DNS and dispatch deployment. This path can override a disabled legacy manual-deploy flag for that operation only; it does not update the stored site setting, and direct manual deployment continues to enforce that setting.

The normal workspace shows this gate list and one next action. Compatibility publish/certificate/deploy controls are collapsed under advanced manual controls. Raw history stays under Advanced Diagnostics. Administrators must explicitly choose **Collect Debug Output** to build a bounded, sanitized bundle with a support ID and seven-day expiry. Preview-release and diagnostic results are rendered beside the action that produced them. Missing preview identity or certificate prerequisites appear inside the diagnostic bundle as bounded `collection_error` evidence and do not cause diagnostic collection itself to fail.

## Publish Workflow (GitHub)

Approved artifact files are published as one Git object transaction: blobs, base-tree overlay, exact path/blob verification, one commit, then one non-forced branch update. HTML/CSS/JavaScript and referenced binary media therefore become visible together under one commit SHA. Repository ownership-marker and baseline checks remain prerequisites.
GitHub publish target configuration is split across Admin + workspace ownership:

Admin-owned baseline (global):
- `owner` (GitHub account/org)
- `default_branch` (fallback when workspace branch override is empty)
- `base_path`
- `github_repository_auto_create_enabled` (admin policy gate for creating missing target repos)
- `enabled`

Workspace-owned destination (site-scoped):
- `repo_name` (repository name only, no owner segment)
- optional `branch` override
- `artifact_root`

Effective publish target is merged at action/readiness time:
- account/owner from Admin config
- repository + optional branch override from workspace config
- branch falls back to Admin `default_branch` when override is blank

Managed-site target contract (configuration-driven for every site):
- source/current live URL is site configuration
- preview hostname is site configuration
- publish repository/branch/artifact root is site/admin configuration
- deploy namespace/workflow routing is site/admin configuration
- dogfooding example sites can use this same contract (including the platform public site), with no hard-coded domain/repo logic
- app/control-plane source code is never copied into generated public artifact repositories

Publish behavior:
- explicit operator-triggered action only
- approved artifact required
- bounded file/path validation before publish
- publish performs target repository existence verification before workflow bootstrap and content writes
- if target repository is missing:
  - when `github_repository_auto_create_enabled=true`, publish attempts repository creation under the configured admin owner and then continues
  - when disabled, publish/readiness fails with a clear admin-policy blocker (repository auto-create disabled)
- managed repository ownership is now enforced with a semaphore file at repo root: `mbsrn.key`
  - `mbsrn.key` content is JSON and includes at minimum:
    - `managed_by` (`"mbsrn"`)
    - `business_id`
    - `site_id`
    - adoption writes also include:
      - `adopted_at`
      - `adopted_by` (principal id when available)
  - managed baseline contract for MBSRN-owned repos also requires root files:
    - `README.md`
    - `.gitignore`
    - `LICENSE`
  - new repos initialized by managed publish bootstrap write `mbsrn.key` in the first commit
  - new or empty repos initialized by managed publish bootstrap create the full baseline in the first commit:
    - `mbsrn.key`
    - `README.md`
    - `.gitignore`
    - `LICENSE`
  - existing non-empty repos without `mbsrn.key` are blocked from managed overwrite/update publish
  - existing repo adoption is explicit (not silent in publish):
    - readiness/preflight returns `github_repo_adoption_required`
    - operator/admin can run `Adopt repository` to write `mbsrn.key`
    - after adoption succeeds, normal managed publish/reconciliation is allowed
  - existing repos with `mbsrn.key` are publishable only when marker values match the current workspace business/site
  - invalid/unparseable marker content is treated as a hard blocker
- existing managed repos are reconciled additively:
  - missing `README.md` / `.gitignore` / `LICENSE` files are added
  - existing customized versions are preserved (no overwrite)

### Repository Initialization Phase
- if target repository exists but target ref is uninitialized (no commit history yet), publish bootstrap initializes the managed branch before workflow/manifest writes
- repository initialization now runs as an explicit phase before workflow provisioning for both:
  - newly created repos
  - existing repos that are reachable but still empty/uninitialized
- initialization is deterministic and idempotent:
  - initialized repos no-op
  - empty repos are bootstrapped once with the managed baseline first commit
  - ref resolution is re-checked after bootstrap before workflow write continues
- initialization observability events:
  - `repo_initialization_started`
  - `repo_initialization_completed`
  - `repo_initialization_failed`
  - failure logs include `step_failed` (`blob`, `tree`, `commit`, `ref`) for precise bootstrap-stage diagnosis
  - paired decision trace:
    - `event=seo_migration_workflow_provisioning_operation`
    - `operation_kind=repo_bootstrap_decision`
    - includes `bootstrap_allowed` and `will_attempt_bootstrap` so dry-run/repair-disabled paths are explicit
- runtime repository auto-create uses private repository visibility by default (`private=true`) to avoid accidental public exposure
- dry-run never creates repositories; readiness and publish diagnostics report whether a live publish would auto-create the missing repository
- publish and deploy are separate gates:
  - publish commits approved static artifacts to the configured GitHub target
  - deploy handles workflow/static IP/TLS/runtime provisioning checks
- deploy-workflow provisioning findings can be surfaced during publish preflight as warnings, but they do not block artifact publish when repository-content writes are authorized
- deploy workflow provisioning/verification remains a deploy-readiness concern and can block deploy independently
- no writes outside configured artifact root
- dry-run supported
- history captured with status/result metadata
- duplicate non-dry-run publish attempts for the same artifact+target are rejected with operator-readable validation errors
- duplicate artifact protection remains in place for file writes, but no longer short-circuits workflow bootstrap
- if artifact content is already published and workflow is missing, a follow-up publish can repair workflow bootstrap without re-writing artifact files (`duplicate_publish_repair`)
- duplicate publish handling now always attempts managed workflow remediation before duplicate rejection (`workflow_remediation_attempted=true` in publish diagnostics/log target fields)
- publish/readiness diagnostics include a normalized `repo_ensure_outcome` field for repo-provisioning auditability:
  - `exists`
  - `created`
  - `would_create_on_publish`
  - `skipped_policy_disabled`
  - `failed_not_authorized`
  - `failed_invalid_name`
  - `failed_owner_mismatch`
  - `failed_conflict`
  - `failed_runtime_unavailable`
- publish now performs a deterministic non-mutating GitHub target preflight before live write steps and surfaces preflight state in readiness and action payloads:
  - `preflight_status`: `ready`, `ready_with_actions`, or `blocked`
  - `preflight_blocker_code`: precise blocker when deterministically known (for example `github_workflow_write_not_authorized`, `github_contents_write_not_authorized`, `repo_auto_create_disabled`)
  - capability/state fields:
    - `target_ref`
    - `target_ref_exists`
    - `repo_initialized`
    - `can_read_contents`
    - `can_write_contents`
    - `can_write_workflows`
    - `would_auto_create_repo`
    - `would_bootstrap_branch`
    - `repo_management_status`
    - `repo_management_marker_present`
    - `repo_management_marker_valid`
    - `repo_management_marker_matches_site`
    - `repo_management_marker_source_ref`
    - `repo_visibility_target`
    - `repo_visibility_observed`
    - `repo_baseline_required`
    - `repo_baseline_reconciliation_needed`
    - `readme_present`
    - `gitignore_present`
    - `license_present`
- dry-run remains non-mutating and includes truthful preflight findings:
  - if repo is missing and auto-create is enabled, dry-run reports `would_auto_create_repo=true` and `preflight_status=ready_with_actions`
  - if repo is missing and auto-create is disabled, readiness/preflight is blocked before live publish
  - `preflight_status=ready_with_actions` can also indicate additive managed-baseline reconciliation for an already managed repo (missing `README.md` / `.gitignore` / `LICENSE`)
- duplicate publish diagnostics now also emit `workflow_remediation_outcome`:
  - `remediation_upgraded_managed_placeholder`: managed scaffold/legacy workflow was replaced with current production template content
  - `remediation_already_current`: managed workflow already matched current contract; no write needed
  - `remediation_preserved_custom`: custom/non-managed workflow was intentionally preserved
  - `remediation_write_failed`: remediation attempt failed due to GitHub write/provision error
- `remediation_not_attempted`: remediation path was not invoked (for example non-duplicate publish)
- workflow/bootstrap provisioning now emits operation-level diagnostics (`event=seo_migration_workflow_provisioning_operation`) with:
  - `operation_kind` (`ref_check`, `repo_bootstrap`, `file_upsert`, etc.)
  - `operation_status` (`started`, `succeeded`, `failed`)
  - target metadata (`repo_owner`, `repo_name`, `ref`, `path`)
  - safe failure detail (`http_status_code`, `github_error_code`, sanitized `github_error_message`)
- workflow/bootstrap failure codes are now more precise for new-repo and permission edge cases:
  - `github_branch_not_found_or_uninitialized`
  - `github_repo_initialization_failed`
  - `github_workflow_write_not_authorized`
  - `github_contents_write_not_authorized`
  - `github_workflow_provisioning_failed`
  - `github_repo_management_marker_missing`
  - `github_repo_management_marker_mismatch`
  - `github_repo_management_marker_invalid`
  - `github_repo_bootstrap_marker_write_failed`
  - `github_repo_baseline_reconciliation_failed`
- retry after a failed publish is supported and recorded as a new history event
- dry-run publish records history but does not overwrite prior successful publish commit metadata
- workflow provisioning is idempotent for deploy-capable managed workflows and preserves unknown custom workflows
- managed placeholder workflow signatures are auto-upgraded during publish provisioning to the current real production template
- unknown custom/non-managed workflows are not overwritten and remain visible through conformance diagnostics
- deploy remains blocked as `workflow_not_production_ready` until a deploy-capable workflow contract is present and verified
- platform-managed workflow content is generated centrally from `app/integrations/seo_migration_github_publisher.py` (`_render_managed_deploy_workflow_yaml`)
- minimum managed workflow contract:
  - dispatch trigger: `on.workflow_dispatch`
  - real deploy steps: GCP auth, GKE credentials, `kubectl apply -f k8s/`, rollout verification, ingress-based URL resolution
  - explicit evidence outputs: `resolved_live_url` (preferred), plus `live_url` and `deployed_url`
- publish-time managed workflow conformance guard now validates the rendered template YAML before any repo write:
  - YAML must parse successfully.
  - `on.workflow_dispatch` must be present.
  - `jobs.deploy` must exist.
  - `jobs.deploy.outputs` must include deploy evidence outputs:
    - `live_url`, `resolved_live_url`, `deployed_url`
    - `dns_record_matches_ingress`, `dns_expected_ip`, `dns_observed_ip`
    - `expected_static_ip_address`, `static_ip_status`, `static_ip_users`
    - `tls_certificate_status`, `tls_domain_status`
    - `ingress_status_ip`, `ingress_status_ip_matches_static_ip`, `static_ip_bound_to_expected_forwarding_rule`
    - `ingress_ip`, `ingress_conflict_detected`, `cert_identity_valid`, `deploy_https_ready`
  - deploy job must include step `Resolve live URL from ingress status`.
  - validation failure blocks publish-time workflow provisioning with reason code `managed_workflow_template_invalid` before workflow file write.
- publish-time workflow provisioning now resolves workflow identity using the same precedence used by deploy dispatch candidate selection (`site_specific_workflow` → `publish_history_workflow` → workspace/default fallback) before writing.
- deploy readiness/dispatch then validates the same resolved workflow file path on the same resolved ref.

### GitHub Publish Configuration (Admin)
Migration publish now depends on an admin-managed GitHub target baseline:
- endpoint: `GET /api/admin/github-publish-config`
- endpoint: `PUT /api/admin/github-publish-config`
- fields:
  - `owner` (`account/org`, for example `mhanson13`)
  - `default_branch`
  - `base_path` (`/` for repo root, optional subpath like `/site`)
  - `github_repository_auto_create_enabled` (admin-controlled policy for missing-repository auto-create)
  - `enabled`
  - `deploy_workflow_mode` (`site_repo_template_v1` currently supported)
  - `target_environment_key` (admin-owned environment mapping key, for example `gke_prod`)
  - `target_environment_source` (`admin_config`, read-only provenance marker)

Operational behavior:
- this config is metadata only; no secrets are stored in the database
- site workspace migration panel does not expose editable Admin-owned owner/base-path controls
- site workspace exposes Operator-owned `repo_name` + optional `branch` override for publish destination selection
- site workspace shows merged effective target summary/readiness (Admin owner + workspace repo/branch)
- site workspace does not expose editable raw deploy workflow routing controls (`repo_owner`, `repo_name`, `workflow_id`, `ref`, `inputs`) for operators
- migration workspace keeps deploy routing values visible as read-only diagnostics and only allows bounded deploy availability toggle at workspace level
- each site target repo receives a site-specific workflow file path (`.github/workflows/<workflow_id>`) provisioned from an MBSRN-managed template mode
- template variable/environment mapping for that workflow is sourced from Admin-owned deploy metadata (`deploy_workflow_mode`, `target_environment_key`, `target_environment_source`) and is not operator-editable
- each site target repo now receives deterministic namespace isolation for platform-managed GKE manifests/workflow:
  - namespace is platform-derived (not operator freeform) from trusted target metadata
  - examples: `tnmfire` -> `tnmfire`, `lars-construction` -> `lars-construction`
  - namespace source is recorded (`repo_name` or `site_id` fallback) for diagnostics/traceability
- admin UI now validates obvious issues before save:
  - owner must match GitHub account/org shape
  - default branch is required/validated when enabled
  - base path is normalized/validated (`/` or `/subpath`)
  - deploy workflow mode is constrained to approved template modes
  - target environment key is normalized/validated and persisted as admin-owned metadata
- admin UI shows an effective target preview with normalized values:
  - owner
  - default branch
  - normalized base path
  - repository auto-create policy state
  - deploy workflow mode
  - target environment key
  - target environment source
- admin save feedback semantics:
  - successful save shows `GitHub publish configuration saved.` and clears prior failed-save messages
  - notification health warnings can still appear after a successful save when saved notification values need review
  - generic failed-save copy is reserved for true save request failures
- admin UI help text explicitly warns that enabling repository auto-create allows the runtime GitHub token to create missing repositories under the configured owner boundary only
- migration publish/deploy readiness includes admin config prerequisites (`admin_publish_config_*`)
- publish/deploy readiness reasons now call out the required actor/action more explicitly:
  - `Admin must configure a GitHub publish target before publish is available.`
  - `Admin has disabled GitHub publishing.`
  - `An approved artifact is required before publish.`
  - `A published artifact is required before deploy.`
- existing site-scoped publish settings remain supported; admin config provides the owner/fallback baseline while workspace settings provide repo + branch override
- config updates emit lightweight structured audit logs (`event=admin_github_publish_config_updated`) including timestamp, actor ids (when available), and changed non-secret fields

Security constraints:
- no GitHub token storage in migration rows
- no token values returned by API
- no token values logged
- GitHub credential/token remains runtime/environment managed; no token input is exposed in workspace surfaces

## Required Runtime Configuration
Migration publish/deploy runtime configuration is environment-driven:
- `GIT_TOKEN`
- `MIGRATION_GITHUB_API_BASE_URL`
- `MIGRATION_GITHUB_TIMEOUT_SECONDS`
- `MIGRATION_PUBLISH_COMMIT_MESSAGE_PREFIX`
- `MIGRATION_PUBLISH_COMMITTER_NAME`
- `MIGRATION_PUBLISH_COMMITTER_EMAIL`
- `MIGRATION_DEPLOY_DEFAULT_WORKFLOW_ID`
- `MIGRATION_DEPLOY_DEFAULT_REF`

Notes:
- token is only read from runtime environment, never persisted in workspace rows
- production deployment wiring injects `GIT_TOKEN` into `mbsrn-api` from the `mbsrn-api-auth` Kubernetes secret (`secretKeyRef` key `GIT_TOKEN`)
- optional local GitHub control-plane validation should use `GIT_TOKEN` (with a local test token value if needed); this keeps local/test/runtime naming consistent while remaining a non-production credential input
- `GIT_TOKEN` is a GitHub token used for both GitHub API publish/deploy operations and GHCR pull-secret provisioning; required capabilities include repository API access plus `read:packages`
- per-site publish/deploy target details are stored in workspace config JSON fields
- runtime config is validated at action/readiness time for migration publish/deploy (feature-scoped validation); unrelated app features continue running when migration config is missing
- publish readiness now distinguishes metadata readiness from runtime publisher capability:
  - Admin/workspace target metadata can be valid while runtime publisher capability is still blocked
  - example runtime blockers:
    - `Platform runtime action required: GitHub publishing credential is unavailable.`
    - `Platform runtime action required: GitHub publishing runtime configuration is invalid.`
    - `Platform runtime action required: GitHub publishing integration is unavailable.`
- deploy readiness now uses explicit blocker classes so operators can distinguish prerequisite type quickly:
  - `published_artifact_missing`
  - `deploy_configuration_missing`
  - `deploy_configuration_invalid`
  - `deploy_runtime_unavailable`
  - `deploy_integration_unavailable`
  - UI messaging maps these classes to role-aware guidance (Operator action vs Platform/Admin action).

## Deploy Workflow (GKE Path)
Deploy target ownership is split for safety:
- Admin-owned deploy routing controls:
  - `repo_owner`, `repo_name`
  - `workflow_id`, `ref`
  - bounded workflow `inputs`
  - `deploy_workflow_mode`
  - `target_environment_key`
  - `target_environment_source`
- Operator workspace controls:
  - `enabled` toggle only
  - read-only effective deploy target diagnostics (repo/ref/workflow identity + staged readiness/traceability)

Deploy behavior:
- explicit operator-triggered action only
- approved + published artifact required
- readiness/state tracked separately from publish state
- platform-managed namespace isolation is part of the deploy contract:
  - deterministic namespace derivation (`kubernetes_namespace`) from trusted target metadata
  - platform-managed workflow + manifests must align on the same namespace
  - namespace is not operator-authored YAML input
- deploy target readiness is explicit for managed bootstrap targets (repo/ref/workflow):
  - repo must exist
  - target ref must exist
  - workflow file must exist on the target ref
  - workflow must be dispatch-ready on the target ref (file presence alone is insufficient)
- deploy workflow dispatch target now resolves with precedence:
  1. authoritative publish-history workflow identity for the same artifact + repo/ref (`deploy_workflow_id` / `deploy_workflow_path`) when available
  2. workspace deploy config `workflow_id`
  3. platform default workflow id
- deploy dispatch now records both requested and used workflow identifiers for traceability:
  - `workflow_identifier_requested` / `workflow_identifier_type_requested`
  - `workflow_identifier_used` / `workflow_identifier_type_used`
  - `workflow_dispatch_resolution_source` (`workflow_id`, `workflow_file_path`, `workflow_id_path_normalized`)
  - outward workflow identifier types are normalized to `workflow_id` or `workflow_file_path`; legacy stored `workflow_numeric_id` is read compatibly and surfaced as `workflow_id`
  - when publish history contains a verified workflow file path, dispatch prefers the file-derived workflow identifier to avoid stale id drift
- readiness/diagnostics include namespace model alignment metadata for managed templates:
  - `kubernetes_namespace`
  - `namespace_source`
  - `namespace_model_status` (`aligned`, `misaligned`, `unknown`)
  - `workflow_namespace_aligned`
  - `manifest_namespace_aligned`
- admin now controls namespace isolation defaults for platform-managed deploy targets using structured fields (no raw YAML):
  - `namespace_isolation_defaults.resource_quota`
  - `namespace_isolation_defaults.limit_range`
  - `namespace_isolation_defaults.network_policy`
- default enablement is conservative:
  - ResourceQuota: disabled by default
  - LimitRange: disabled by default
  - NetworkPolicy: disabled by default (`mode=default_deny_ingress` when enabled)
- when enabled by Admin, publish provisions additional managed files in target repos:
  - `k8s/resourcequota.yaml`
  - `k8s/limitrange.yaml`
  - `k8s/networkpolicy.yaml`
- managed-file verification/readiness now tracks namespace policy presence/alignment explicitly:
  - `managed_resource_quota_expected` / `managed_resource_quota_present`
  - `managed_limit_range_expected` / `managed_limit_range_present`
  - `managed_network_policy_expected` / `managed_network_policy_present`
  - `managed_namespace_policies_aligned`
- deployment history captured with status/result metadata
- publish/deploy diagnostics include bounded deploy-secret propagation fields:
  - `deploy_secret_propagation_attempted`
  - `deploy_secret_propagation_status` (`not_attempted`, `created`, `updated`, `skipped_guardrail`, `failed`)
  - `deploy_secret_propagation_reason`
- duplicate non-dry-run deploy requests are blocked only when the same artifact+target+inputs already has an active in-flight deploy attempt
  - active blockers include confirmed non-terminal run states such as `workflow_run_pending`, `workflow_run_in_progress`, and `workflow_run_observed` (run-id backed)
  - run-backed active blockers are freshness-bound (30-minute stale window based on newest activity timestamp: `refreshed_at` -> `dispatched_at` -> `occurred_at` -> `timestamp`)
  - unverified dispatch states without run evidence (`dispatch_accepted_no_run` / `dispatch_unverified_no_run`) are weak blockers with a short 2-minute stale window
  - for run-backed blockers older than 12 minutes (but still inside the 30-minute active freshness window), control plane refreshes workflow run evidence from GitHub before returning `duplicate_request`
  - if refresh confirms terminal run state, the prior attempt is normalized to terminal and retry proceeds
  - if refresh confirms the run is still active, duplicate blocking remains in place with refreshed blocker metadata
  - if refresh fails while blocker evidence is still inside the active freshness window, deploy fails closed with `deploy_blocker_reconciliation_failed` (operator must refresh status and retry)
  - if refresh fails after blocker evidence is beyond the 30-minute active window but below the hard stale window (2 hours), deploy fails with `stale_deploy_blocker_requires_refresh` (operator must refresh status and confirm terminal state)
  - hard stale safety bound for run-backed blockers is 2 hours; once exceeded, control plane performs one final GitHub reconciliation and:
    - keeps blocking only when GitHub explicitly confirms the prior run is still active
    - otherwise supersedes the stale blocker and allows retry
  - superseded stale blockers are normalized to terminal history with `workflow_run_failure_reason_code=stale_deploy_blocker_superseded`, and reconciliation metadata records `deploy_blocker_superseded_after_stale_threshold`
  - control plane emits `seo_migration_deploy_stale_blocker_superseded` when this automatic stale-clearance path is used
  - stale unverified-dispatch blockers continue to reconcile to terminal timeout (`workflow_run_failure_reason_code=workflow_reconciliation_timeout`) after the 2-minute no-run threshold
  - if refresh hits `workflow_not_found` after dispatch was attempted, control plane marks the attempt terminal with `workflow_run_failure_reason_code=workflow_run_tracking_lost` so retries are not deadlocked
  - terminal/stale historical records (`workflow_run_failed`, `workflow_run_succeeded_without_live_url`, `workflow_run_succeeded_with_live_url`, cancelled/completed non-active, or stale no-run records) do not block a new deploy retry
  - stale no-run detection uses deterministic activity precedence: `refreshed_at` -> `dispatched_at` -> `occurred_at` -> `timestamp` with a 2-minute threshold for unverified dispatch records
- retry after a failed deploy is supported and recorded as a new history event
- deploy dry-run records history but does not overwrite prior successful deploy request markers
- platform-managed deploy workflow now performs a real GKE apply/rollout path for managed site workloads:
  - authenticate to GCP using repository secret JSON credentials (`google-github-actions/auth` with `credentials_json`)
  - fetch GKE credentials (`google-github-actions/get-gke-credentials`)
  - apply namespace first (`kubectl apply -f k8s/namespace.yaml`)
  - default managed runtime image mode is private GHCR with control-plane-provisioned namespace pull credentials:
    - control plane provisions namespace-scoped GHCR pull secret (`ghcr-pull-secret`) before target deploy dispatch
    - managed `site-web` deployment template references `imagePullSecrets: [{name: ghcr-pull-secret}]`
    - requires control-plane runtime `GIT_USERID` (production value: `mhanson13`)
    - requires control-plane runtime `GIT_EMAIL` (production value: `mhanson13@gmail.com`)
    - requires control-plane runtime `GIT_TOKEN` (personal access token; never logged or surfaced)
    - these are resolved only from the mbsrn control-plane runtime/admin deployment configuration (not target site repositories)
    - GitHub Actions repository secrets alone are not sufficient until `deploy-prod` projects them into `mbsrn-api-auth` and API runtime env (`GIT_USERID`, `GIT_EMAIL`, `GIT_TOKEN`)
  - optional public-image mode (admin/runtime override) can disable private pull-secret requirements when explicitly intended
  - apply managed manifests (`kubectl apply -f k8s/`)
  - verify rollout (`kubectl rollout status deployment/site-web --namespace <derived-namespace>`)
  - managed `site-web` runtime image repository is deterministic and site-scoped:
    - `ghcr.io/<target-repo-owner>/<target-repo-name>-site-web`
    - examples:
      - `sc-mechanical.site.mbsrn.com` -> `ghcr.io/mhanson13/scmechanical-site-web`
      - `tnmfire.site.mbsrn.com` -> `ghcr.io/mhanson13/tnmfire-site-web`
      - `lars-construction.site.mbsrn.com` -> `ghcr.io/mhanson13/lars-construction-site-web`
  - managed `site-web` deployment template pins runtime serving env for health-check parity:
    - `HOSTNAME=0.0.0.0`
    - `PORT=8080`
    - this ensures root-path probes and direct pod checks (`curl http://127.0.0.1:8080/`) hit a valid HTTP listener
  - deploy-time image selection order for managed site workloads:
    1. immutable SHA tag from `MBSRN_SITE_WEB_IMAGE_TAG` / `SITE_WEB_IMAGE_TAG` (vars first, then secrets) when the tag exists in GHCR
    2. safe fallback to `:latest`
  - controlled rollout pinning example:
    - set `MBSRN_SITE_WEB_IMAGE_TAG=3f2c9e7d8a6b4c1e9f0a1234567890abcdef1234` (or legacy alias `SITE_WEB_IMAGE_TAG=...`) before deploy
    - verify `site_runtime_image_selection_mode=immutable_sha`; if tag is missing/invalid/unavailable, mode falls back to `fallback_latest`
    - see `docs/runbooks/gcp-logging.md` for the step-by-step operator procedure
  - managed workflow emits and logs the selected runtime image metadata:
    - `site_runtime_image_reference`
    - `site_runtime_image_selection_mode` (`immutable_sha` or `fallback_latest`)
  - managed deploy workflow builds and pushes site runtime content from the target repository itself on each deploy run:
    - `ghcr.io/<owner>/<repo>-site-web:latest`
    - `ghcr.io/<owner>/<repo>-site-web:<git-sha>`
    - this prevents cross-site content identity drift caused by shared generic runtime artifacts.
  - deploy readiness surfaces `dispatch_service_reason_code=deployed_content_identity_mismatch` when rendered deployment image identity does not match the selected repo owner/name tuple.
  - deploy readiness also surfaces managed-site rollout safety state for post-fix rollout tracking:
    - `managed_workflow_not_yet_republished`
    - `workflow_republished_but_deploy_not_rerun`
    - `deploy_running_old_generic_image`
    - `deploy_running_expected_site_scoped_image`
  - if rollout times out, workflow emits bounded namespace-scoped diagnostics (`get deployment/rs/pods`, `describe deployment/pods`, recent `site-web` logs) plus concise likely-blocker hints (image pull, private registry auth, crash/probe, config/secret reference, scheduling/resource)
    - hint precedence is describe-event-first: image-pull blockers suppress crash/probe hints unless direct current describe evidence shows a started container failure
  - verify service/ingress presence

Post-fix rollout for existing managed sites:
- Existing sites created before the site-scoped runtime image fix must run this sequence:
  1. publish (non-dry-run) to republish managed workflow/manifests
  2. deploy (non-dry-run) to apply the republished workflow and image identity
  3. refresh deploy status to capture observed runtime image evidence
- Do not treat the fix as active until observed deployment evidence matches expected image repository:
  - expected: `ghcr.io/<owner>/<repo>-site-web:<sha-or-latest>`
  - legacy generic examples to treat as not fixed:
    - `ghcr.io/mhanson13/site-web:latest`
    - `ghcr.io/<owner>/site-web:latest`
- Operator diagnostics map:
  - `managed_workflow_not_yet_republished`: republish first
  - `workflow_republished_but_deploy_not_rerun`: redeploy after republish
  - `deploy_running_old_generic_image`: redeploy is still on legacy generic image
  - `deploy_running_expected_site_scoped_image`: fix is active
- Optional scoped fresh redeploy path:
  - Deploy controls include `Replace existing managed-site runtime before deploy` for a single deploy attempt.
  - This is intended for legacy-runtime cleanup during endpoint-mode/runtime transitions.
  - Managed deploy treats endpoint prerequisites separately from runtime resources:
    - `endpoint_prerequisite_resource`: preview `ManagedCertificate`, deterministic preview static IP, preview DNS record
    - `runtime_resource`: `ingress/site-web`, `service/site-web`, `deployment/site-web`, `backendconfig`, `frontendconfig`, site-scoped `networkpolicy`
    - `frontendconfig` stays runtime-managed so ingress/runtime resets remain coherent
  - Workflow order is: ensure namespace → verify endpoint prerequisites → optional runtime replace → apply runtime resources → verify service/endpoints/certificate/ingress → wait for DNS/TLS readiness.
  - When selected, workflow performs scoped namespace/site cleanup before apply and emits:
    - `managed_site_runtime_replace_requested`
    - `managed_site_runtime_replace_completed`
    - `managed_site_runtime_replace_failed`
  - Preview `ManagedCertificate` is a long-lived endpoint prerequisite:
    - if missing, deploy instructs the operator to use `Provision TLS Certificate`; deploy never creates it from the managed manifest bundle
    - if present with verified MBSRN ownership labels and the expected hostname, deploy reuses it
    - if present but ownership is ambiguous, deploy blocks with `managed_certificate_ownership_unverified`
    - if present but `spec.domains` does not match the expected preview hostname, deploy blocks with `certificate_domain_mismatch`
  - After apply and before ingress/TLS readiness loops, workflow verifies required runtime resources exist:
    - `deployment/site-web`, `service/site-web`
    - plus rendered/referenced ingress resources (`ingress`, `ManagedCertificate`, `FrontendConfig`, `BackendConfig`)
  - managed runtime apply order is explicit for runtime-managed ingress dependencies: `BackendConfig` → `Service` → `Deployment` → `FrontendConfig` → `Ingress`.
  - explicit missing-resource codes:
    - `runtime_deployment_missing_after_apply`
    - `runtime_service_missing_after_apply`
    - `runtime_ingress_missing_after_apply`
    - `runtime_managed_certificate_missing_after_apply`
    - `runtime_frontend_config_missing_after_apply`
    - `runtime_backend_config_missing_after_apply`
    - `runtime_service_endpoints_missing_after_apply`
  - missing ManagedCertificate object after apply is treated as manifest/apply failure; wrong-domain certs surface `certificate_domain_mismatch`; stale/incorrect identity surfaces `stale_managed_certificate_present`; ownership ambiguity surfaces `managed_certificate_ownership_unverified`; `PROVISIONING` is treated as TLS pending only after required objects exist.
  - if `service/site-web` exists but ingress still reports a stale Translate event, deploy favors current Service/Endpoint evidence and bounded convergence checks rather than failing on stale event history alone.
  - Readiness can surface `legacy_runtime_replacement_required` when stale legacy runtime evidence is detected and replace-runtime was not requested.
  - Cleanup scope is limited to managed runtime resources (`site-web` ingress/service/deployment, frontend/backend config resources, site-scoped networkpolicy) and does not delete the preview `ManagedCertificate`, artifacts/media/GitHub content/business data.
  - Publish readiness is unchanged; this is deploy-only behavior.
- Admin Site Registry permanent delete is separate from this deploy-only cleanup path:
  - deactivation/archive keeps the site and migration history intact
  - permanent delete removes the site and site-owned control-plane records
  - admin permanent delete always requires a delete plan, explicit acknowledgements, an exact confirmation phrase, and an explicit execute request
  - external cleanup options default off and are opt-in for:
    - generated GitHub repo delete
    - verified managed GKE/runtime resource delete
    - verified managed DNS/static-IP/certificate delete
  - external delete safety checks:
    - repo delete is blocked for unmanaged/ambiguous repos and for the protected control-plane repo configured by `MBSRN_CONTROL_PLANE_REPOSITORY`
    - runtime delete only targets site-labeled managed resources
    - DNS delete requires exact expected record/value match
    - the delete plan reports static-IP ownership as `verified`, `unverified`, `shared`, `in_use`, `conflicting_reference`, or `not_found`
    - static-IP delete proceeds only after verified site ownership; label proof is preferred and legacy DNS/name fallback is used only when exact signals agree
    - shared, in-use, conflicting, and unverified static IPs are intentionally skipped rather than deleted
    - ManagedCertificate delete requires exact namespace/name plus site ownership verification
  - the protected control-plane repo guard uses a config-driven `owner/repo` identity with compatibility fallback; malformed values fail closed before destructive cleanup can run
  - admin permanent delete never auto-deletes the original customer/source website, arbitrary customer repos, unrelated cluster resources, or secret/raw prompt/raw media/private preview data
  - if DB delete fails after external cleanup has already changed state, result code `site_delete_db_failed_after_external_cleanup` is returned for manual remediation
  - runbook for `site_delete_db_failed_after_external_cleanup`:
    - review `external_resources`, `blockers`, and `warnings` first; they show what changed before the DB failure
    - verify each reported GitHub/GKE/DNS/static-IP/certificate state in the provider before retrying cleanup
    - clear the remaining DB-side blocker, then rerun delete only for unfinished safe targets or reconcile the site manually
- required managed deploy configuration contract for real deploy execution:
  - admin-owned managed GKE settings in MBSRN GitHub publish configuration:
    - `managed_gke_cluster_name`
    - `managed_gke_cluster_location`
    - `managed_gke_project_id`
  - `GCP_DEPLOY_KEY` (full JSON service account key with Kubernetes Engine Admin-equivalent scoped access to target cluster/project)
  - optional control-plane impersonation config:
    - `GCP_MANAGED_DEPLOY=<service-account-email>`
    - this value is an email only (not JSON and not private key material)
    - when set, control-plane static-IP and DNS ensure operations impersonate this service account
    - when unset, control plane keeps existing ADC/Workload Identity behavior
    - IAM contract when enabled:
      - control-plane runtime principal (`gcp_principal_email`) requires `roles/iam.serviceAccountTokenCreator` on `GCP_MANAGED_DEPLOY`
      - impersonated service account (`gcp_impersonated_service_account_email`) requires static-IP and DNS permissions in the managed project/zone
  - managed workflow resolves GKE inputs from admin config first; repo vars/secrets are legacy fallback only:
    - `GKE_CLUSTER_NAME = <admin managed_gke_cluster_name>` when present, otherwise `vars.KUBERNETES_CLUSTER_NAME || secrets.KUBERNETES_CLUSTER_NAME`
    - `GKE_CLUSTER_LOCATION = <admin managed_gke_cluster_location>` when present, otherwise `vars.KUBERNETES_CLUSTER_LOCATION || secrets.KUBERNETES_CLUSTER_LOCATION`
    - `GKE_PROJECT_ID = <admin managed_gke_project_id>` when present, otherwise `vars.GCP_PROJECT_ID || secrets.GCP_PROJECT_ID`
  - workflow pre-checks fail fast before `get-gke-credentials` (legacy fallback checks when admin values are absent):
    - `Missing GCP_DEPLOY_KEY secret`
    - `Missing KUBERNETES_CLUSTER_NAME variable/secret`
    - `Missing KUBERNETES_CLUSTER_LOCATION variable/secret`
    - `Missing GCP_PROJECT_ID variable/secret`
  - deploy readiness can now surface explicit configuration reasons:
    - `dispatch_service_reason_code=missing_cluster_name`
    - `dispatch_service_reason_code=missing_cluster_location`
    - `dispatch_service_reason_code=missing_gcp_project_id`
    - `dispatch_service_reason_code=image_pull_secret_missing` (private-image auth mode only)
    - `dispatch_service_reason_code=image_pull_secret_not_referenced` (private-image auth mode only)
  - readiness and dispatch now share the same managed GKE config resolution path so deploy cannot report `dispatch_service_availability=available` and then fail later with missing cluster/location/project for the same target tuple.
  - migration workspace deploy readiness/diagnostics now surface concise operator guidance for these cases:
    - `missing_cluster_name` -> set managed GKE cluster name in MBSRN admin deployment settings
    - `missing_cluster_location` -> set managed GKE cluster location in MBSRN admin deployment settings
    - `missing_gcp_project_id` -> set managed GCP project ID in MBSRN admin deployment settings
    - `image_pull_secret_missing` -> configure `GIT_USERID`, `GIT_EMAIL`, `GIT_TOKEN` in **mbsrn control-plane** deployment settings and verify `deploy-prod` projected them into runtime before retry (private-image auth mode only)
    - `image_pull_secret_not_referenced` -> republish managed deploy manifests so deployment references `ghcr-pull-secret` (private-image auth mode only)
  - GHCR pull credentials are evaluated from control-plane runtime configuration and used to provision namespace-scoped Kubernetes pull secrets; target site repositories must not store `GIT_USERID`/`GIT_EMAIL`/`GIT_TOKEN` credentials.
  - configuration source expectation is explicit in UI copy:
    - managed deploy resolves admin platform config first; repo vars/secrets are legacy fallback only
  - troubleshooting precedence:
    - treat `missing_cluster_*` / `missing_gcp_project_id` as admin-owned managed target configuration blockers first, even if generic deploy failure summaries are also present
    - correct admin deployment settings and retry deploy from the workspace before escalating to runtime workflow troubleshooting
    - GitHub Actions run/job logs become the primary source only after readiness no longer reports missing managed target configuration
  - blocker ownership model:
    - `missing_cluster_name`, `missing_cluster_location`, `missing_gcp_project_id`:
      admin-owned managed target configuration blockers (MBSRN admin configuration is source of truth; repo vars/secrets are legacy fallback only)
    - `runtime_credential_missing` with `secret_name=GCP_DEPLOY_KEY`:
      admin/runtime credential-source blocker for deploy-secret propagation (separate from managed cluster vars)
    - `duplicate_request`:
      operator-visible concurrency/history blocker; does not replace configuration ownership blockers
    - `deploy_blocker_reconciliation_failed`:
      aged duplicate blocker could not be refreshed from GitHub while still potentially active
    - `stale_deploy_blocker_requires_refresh`:
      stale duplicate blocker requires manual refresh confirmation before safe retry
    - `deploy_blocker_superseded_after_stale_threshold`:
      stale duplicate blocker exceeded the hard stale threshold and was auto-superseded so retry can proceed
  - readiness normalization now prefers managed GKE configuration blockers before dispatch so deploy does not appear dispatchable when required cluster config is incomplete
  - after applying missing config values, retry deploy from the migration workspace (no workflow template change required)
- hybrid deploy-secret propagation (bridge model):
  - `GCP_DEPLOY_KEY` is admin-owned and managed through MBSRN admin GitHub publish configuration.
  - admin UI/API treat secret material as write-only; status metadata only (`configured`, `updated_at`) is returned after save.
  - publish resolves deploy secret from the admin-managed source first and can propagate `GCP_DEPLOY_KEY` into target repo Actions secrets so managed site-repo workflows can execute deploy.
  - runtime env fallback is retained only for controlled legacy compatibility paths and is surfaced explicitly in diagnostics.
  - propagation is guardrailed and allowed only when all conditions pass:
    - deploy target is enabled for the workspace
    - admin publish target is configured and enabled
    - target repo owner matches the approved admin owner boundary
    - managed deploy tuple aligns to the publish/deploy tuple being provisioned (`owner/repo/ref`)
  - if guardrails fail, propagation is skipped with explicit status/reason (`skipped_guardrail`).
  - if propagation write fails, artifact publish history still records publish outcome while exposing deploy-secret propagation failure for follow-up.
  - deploy diagnostics include `deploy_secret_propagation_source` (`admin_managed_secret` or `runtime_env_fallback`) for ownership clarity.
  - secret contents are never returned in API payloads, logs, or UI surfaces.
  - this is intentionally a bridge model and can later be replaced by centralized deploy execution or OIDC-based federation.
  - explicit deploy evidence contract for live URL confirmation:
  - managed-site ingress generation now follows the proven platform GKE ingress wiring for external address provisioning:
    - `k8s/service.yaml` includes `cloud.google.com/neg: {"ingress": true}`
    - `k8s/service.yaml` includes `cloud.google.com/backend-config: {"default":"site-web-backend-config-<normalized-site>"}`
    - `k8s/backendconfig.yaml` is generated with:
      - `kind: BackendConfig`
      - `metadata.name: site-web-backend-config-<normalized-site>`
      - `healthCheck.requestPath: /`
      - `healthCheck.port: 8080`
    - `k8s/ingress.yaml` includes:
      - `kubernetes.io/ingress.class: gce`
      - `networking.gke.io/v1beta1.FrontendConfig: site-web-frontend-config-<normalized-site>`
    - `k8s/frontendconfig.yaml` is generated with `networking.gke.io/v1beta1` and `redirectToHttps.enabled: true`
      - `metadata.name: site-web-frontend-config-<normalized-site>`
  - this ingress contract is generated by MBSRN-managed templates (not operator-authored), and missing/misaligned managed ingress files can leave ingress `ADDRESS` empty even when workload rollout is healthy or produce HTTP 502 when GCLB backend health checks are not aligned.
  - default backend health-check contract probes `/` on port `8080`; `/healthz` should be used only when explicit runtime support is guaranteed.
  - workflow resolves URL from ingress status (`.status.loadBalancer.ingress[0].hostname|ip`) and also evaluates reserved static-IP binding metadata for DNS source-of-truth selection
  - managed site ingress now includes a host-specific preview rule and certificate wiring:
    - preview host: `<normalized-site>.site.mbsrn.com`
    - managed certificate resource: `k8s/managedcertificate.yaml`
    - managed certificate name: `site-web-preview-cert-<normalized-site>`
    - ingress annotation: `networking.gke.io/managed-certificates: site-web-preview-cert-<normalized-site>`
    - ingress static-IP binding is endpoint-mode driven:
      - `preview_shared_gateway` (default for managed preview hosts like `<normalized-site>.site.mbsrn.com` when configured):
        - ingress annotation uses the configured shared preview static-IP name
        - control plane validates shared preview gateway config before dispatch
        - per-site static-IP ensure is not required in this mode
      - `dedicated_static_ip` (live/cutover or explicitly selected dedicated endpoint mode):
        - annotation: `kubernetes.io/ingress.global-static-ip-name: site-web-preview-ip-<normalized-site>` (or configured expected dedicated name)
        - control plane ensures the expected global address exists before workflow dispatch using admin-managed deploy credentials
        - newly created per-site addresses are labeled at create time with GCP-safe ownership labels: `mbsrn-managed-by=mbsrn`, `mbsrn-site-id=<normalized site id>`, `mbsrn-preview-hostname=<label-safe preview hostname>`, `mbsrn-repo=<label-safe repo>`
        - existing addresses are left unchanged; labels are not backfilled onto already-reserved IPs
      - `auto` mode resolves to `preview_shared_gateway` for `*.site.mbsrn.com` when shared preview static-IP config is present; otherwise it falls back to `dedicated_static_ip`
      - prerequisite chain remains ordered and fail-closed for the active endpoint mode:
        - static-IP/gateway validation -> DNS ensure (when applicable) -> DNS propagation gate -> workflow dispatch
      - generated target workflow validates expected preview ingress static-IP presence as drift safety using the resolved expected static-IP name
      - when ingress static-IP annotation matches expected name, workflow fetches static-IP metadata (`address`, `status`, `users`) and treats reserved `address` as `dns_expected_ip`
      - if static IP is `IN_USE` and `users` indicate expected forwarding-rule binding, ingress status IP mismatch is advisory only (`ingress_status_ip_stale_or_mismatched`)
      - if static IP metadata does not show expected binding evidence, deploy remains blocked with `expected_static_ip_not_bound_to_ingress`
      - workflow outputs additional network-binding diagnostics:
        - `expected_static_ip_address`
        - `static_ip_status`
        - `static_ip_users`
        - `ingress_status_ip`
        - `ingress_status_ip_matches_static_ip`
        - `static_ip_bound_to_expected_forwarding_rule`
      - endpoint-mode configuration blockers:
        - `shared_preview_gateway_missing`
        - `shared_preview_gateway_hostname_missing`
      - `managed_site_static_ip_config_missing` blocks dispatch when control-plane static-IP ensure is missing required project/deploy-key config
      - `managed_deploy_impersonation_config_invalid` blocks dispatch when `GCP_MANAGED_DEPLOY` is not a valid service-account email
      - `managed_deploy_impersonation_permission_denied` blocks dispatch when control-plane principal cannot impersonate `GCP_MANAGED_DEPLOY`
      - dedicated static-IP ensure failures are classified before dispatch with operator-safe reason codes:
        - `managed_site_static_ip_permission_denied` (control-plane identity lacks `compute.globalAddresses.get/create`)
        - `managed_site_static_ip_api_disabled` (Compute Engine API disabled for managed project)
        - `managed_site_static_ip_quota_exceeded` (global static-address quota exhausted)
        - `managed_site_static_ip_project_not_found` (invalid/inaccessible managed project)
        - `managed_site_static_ip_conflict` (named address conflict that could not be reconciled)
        - `static_ip_address_missing_after_retry` (ensure completed but no usable address was returned after bounded describe retry and list fallback; DNS ensure is not attempted with null IP)
        - fallback: `managed_site_static_ip_provisioning_failed`
      - static-IP ensure diagnostics include effective credential metadata for IAM remediation:
        - `static_ip_gcp_credential_source` (`service_account_json`, `managed_deploy_impersonation`, `adc_metadata_server`, `unknown`)
        - `static_ip_gcp_principal_email` (safe principal identity; never includes private keys/tokens)
        - `static_ip_gcp_impersonated_service_account_email` (when impersonation is configured)
      - permission-denied remediation must target the effective principal reported in `static_ip_gcp_principal_email` (not a hard-coded assumed service account)
    - preview DNS A record is control-plane managed before dispatch:
      - hostname: `<normalized-site>.site.mbsrn.com`
      - managed zone default: `sites`
      - DNS project default: effective managed deploy/static-IP project
      - exact-hostname scope only: control plane manages only the `A` record for this preview hostname
      - after DNS ensure succeeds, control plane performs a bounded propagation gate (max `120s`, sleep `10s`) and only dispatches once resolver-observed `A` matches the expected per-site static IP
      - generated target workflow still validates DNS/ingress parity as deploy-contract evidence
      - `managed_site_dns_config_missing`, `managed_site_dns_provisioning_failed`, `managed_site_dns_conflicting_record`, `managed_site_dns_permission_denied`, `managed_site_dns_transaction_conflict`, `managed_site_dns_propagation_pending` block dispatch before workflow run
      - DNS ensure diagnostics also surface credential metadata:
        - `dns_gcp_credential_source`
        - `dns_gcp_principal_email`
        - `dns_gcp_impersonated_service_account_email`
      - permission-denied DNS remediation must grant IAM to the principal reported in `dns_gcp_principal_email`
    - generated manifests must not include `ingress.gcp.kubernetes.io/pre-shared-cert`; `ManagedCertificate` remains the desired-state certificate binding source
    - GKE may still add `ingress.gcp.kubernetes.io/pre-shared-cert` at runtime as controller metadata
    - certificate domain and ingress host must match the same site-specific preview hostname.
    - mismatch classifications:
      - `tls_certificate_bound_to_wrong_site` when ingress host/certificate domain disagree
      - `ingress_certificate_annotation_mismatch` when ingress annotation references the wrong certificate name
      - `managed_certificate_identity_mismatch` when ingress annotation includes stale cross-site certificate names
      - `managed_site_static_ip_missing` when the expected dedicated global static IP does not exist in GCP
      - `expected_static_ip_not_bound_to_ingress` when ingress is missing the expected static-IP annotation binding for the active endpoint mode
      - `ingress_static_ip_conflict` when ingress static-IP annotation does not match the expected name for the active endpoint mode
      - `pre_shared_cert_metadata_mismatch` when controller-generated pre-shared certificate metadata differs from expected managed-certificate name (advisory; non-blocking by itself)
      - `stale_pre_shared_cert_binding_detected` only when stale/cross-site pre-shared metadata is corroborated by desired-state annotation/domain mismatch or HTTPS/TLS identity mismatch
      - `managed_certificate_failed_not_visible` when certificate visibility checks fail for the expected hostname
    - stale certificate resources are never auto-deleted; readiness/diagnostics provide manual cleanup guidance.
  - ingress address resolution uses a bounded wait loop (10-minute max: `40 x 15s`) because GKE load balancer provisioning can lag successful rollout
  - workflow URL resolution now short-circuits when the expected preview hostname is already reachable even if ingress status address lags:
    - `ingress_address_pending_but_hostname_reachable` indicates address propagation lag while host is reachable
    - `reachable_but_tls_certificate_mismatch` indicates the host responds but serves the wrong certificate identity
    - `ingress_backend_502` indicates preview hostname is reachable but returns HTTP 502; diagnostics now distinguish:
      - ingress/LB edge convergence (`gce_backend_health_status=HEALTHY`, service/endpoint probes `ok`, preview still `502`)
      - app runtime response failure (service/endpoint probes also `502`)
      - pod runtime instability (`pod_restart_detected=true` with restart/crash evidence)
  - in-cluster service probing now classifies cluster-local connectivity independently of external ingress/LB convergence:
    - first probe failures emit `service_probe_waiting_for_convergence`
    - cluster-local probe timeouts emit:
      - `in_cluster_service_probe_timeout`
      - `network_policy_may_block_service_probe`
    - in-cluster probe loop does not emit `ingress_neg_convergence_pending` for `site-web.<namespace>.svc.cluster.local` failures
    - bounded probe-failure diagnostics now include:
      - `kubectl get/describe networkpolicy`
      - latest `site-web` pod labels (`kubectl get pod ... --show-labels`)
      - `kubectl get service site-web -o jsonpath` selector/ports summary
      - `kubectl get endpoints` and `kubectl get endpointslice`
    - workflow retries probes in a bounded loop and still emits terminal evidence:
      - `in_cluster_service_curl_failed_after_retries`
      - `in_cluster_service_curl_failed`
  - external ingress/LB readiness checks remain convergence-aware:
    - `ingress_neg_convergence_pending` is reserved for external ingress/NEG/load-balancer convergence evidence
  - workflow emits all three output keys on success:
    - `live_url`
    - `resolved_live_url`
    - `deployed_url`
  - no URL output is emitted when ingress status has no concrete endpoint; workflow fails after bounded wait and emits ingress-specific diagnostics (`get/describe ingress`, `get service`, `get endpoints`, optional `managedcertificate` / `frontendconfig`)
  - deploy image digest metadata is optional in diagnostics/history:
    - if digest is unavailable, UI shows `Digest not reported`
    - image repository/tag/source commit remain valid traceability evidence
- post-dispatch workflow run diagnostics now distinguish execution-stage failures:
  - `workflow_run_failure_reason_code`
  - `workflow_run_failure_stage`
  - `workflow_run_failure_step`
  - `workflow_run_failure_hint`
  - examples include `gcp_auth_failed`, `gke_credentials_failed`, `kubectl_apply_failed`, `rollout_verification_failed`, `service_ingress_verification_failed`, and `ingress_endpoint_not_ready`
  - `ingress_endpoint_not_ready` indicates ingress exists but external hostname/IP evidence was not assigned before bounded timeout (workflow logs include `deploy_runtime_reason_code=ingress_address_pending` marker for troubleshooting)
  - additional runtime reason codes now surface backend-vs-TLS-vs-address lag explicitly:
    - `service_has_no_ready_endpoints`
    - `service_endpoint_missing`
    - `service_endpoint_unhealthy`
    - `in_cluster_service_probe_timeout`
    - `network_policy_may_block_service_probe`
    - `service_probe_waiting_for_convergence`
    - `ingress_neg_convergence_pending`
    - `in_cluster_service_curl_failed_after_retries`
    - `in_cluster_service_curl_failed`
    - `pod_ready_but_ingress_backend_unhealthy`
    - `ingress_backend_unhealthy_after_rollout`
    - `backend_config_healthcheck_unhealthy`
    - `ingress_backend_502`
    - `ingress_address_pending_but_hostname_reachable`
    - `reachable_but_tls_certificate_mismatch`
  - rollout-time diagnostics now include explicit quota-rejection hints when Kubernetes reports `FailedCreate` / `exceeded quota` for `site-web` (for example `requested: requests.memory` greater than namespace `site-resources` limits)
  - Cloud SQL migration-startup failures are surfaced distinctly when run logs contain known proxy signatures:
    - `cloudsql_instance_inspection_failed`
    - `cloudsql_instance_invalid_state`
    - `cloudsql_proxy_ephemeral_cert_failed`
    - `cloudsql_proxy_connection_failed`
  - `cloudsql_instance_inspection_failed` indicates Cloud SQL instance inspection itself failed (for example permission denied, instance/project mismatch, API unavailable, or empty describe output); verify Cloud SQL identity/permissions/API access before retry.
  - `cloudsql_instance_invalid_state` indicates the instance was not ready to issue ephemeral certs; verify instance state is `RUNNABLE` and retry deploy.
  - these Cloud SQL-specific codes are expected only for workflows intentionally configured for `DB_CONNECTION_MODE=cloudsql_proxy`; direct cloud-native Postgres workflows should not enter Cloud SQL preflight.

Current deployment model is reused via workflow dispatch conventions; platform deployment architecture is not redesigned by this feature.

### First-Time Deploy Availability Refresh

- migration publish/deploy config save now triggers a full workspace summary/readiness refresh in the same action cycle.
- operators should no longer need to save twice to see first-time deploy availability after successful publish-target/deploy-target configuration updates.
- if deploy readiness still appears stale after one save, use explicit `Refresh Deploy Status` and inspect `seo_migration_target_readiness_check` for cached upstream blockers.

### Namespace Isolation Defaults (Admin-Owned)

These controls are platform-managed defaults applied to each derived site namespace during publish provisioning:

- ResourceQuota defaults
  - `enabled`
  - `requests.cpu`, `requests.memory`
  - `limits.cpu`, `limits.memory`
  - `pods`, `services`, `configmaps`, `secrets`, `persistentvolumeclaims`
- LimitRange defaults
  - `enabled`
  - `default` CPU/memory
  - `defaultRequest` CPU/memory
  - `min` CPU/memory
  - `max` CPU/memory
- NetworkPolicy defaults
  - `enabled`
  - bounded mode set (currently `default_deny_ingress`)
  - rendered baseline includes:
    - namespace-wide default deny ingress
    - targeted allow ingress to `site-web` pods on app port `8080` from same-namespace pods
    - bounded GKE/GCE health-check CIDRs for ingress health checks (`35.191.0.0/16`, `130.211.0.0/22`)

Safety/ownership rules:
- these policies are generated from vetted platform templates, not model output
- operators do not hand-author these controls in normal workflow
- unknown custom repo files are not blindly overwritten
- policy values are schema-validated and normalized before rendering
- namespace isolation controls are platform-managed and should be paired with namespace-scoped RBAC/service-account guardrails in target clusters.

### Future Hardening (Not Required for Current Contract)

Namespace isolation is now in place; additional hardening can be layered later without changing the current publish/deploy contract:
- per-namespace `ResourceQuota` tuning by environment class
- per-namespace `LimitRange` tightening by workload profile
- optional baseline `NetworkPolicy` expansion once ingress/egress expectations are fully validated
- namespace-scoped RBAC/service-account hardening

## Analytics Insertion Rules
Analytics is controlled by platform logic, not model snippets.

Fields:
- `analytics_config_json.enabled`
- `analytics_config_json.ga_measurement_id`
- `analytics_config_json.insertion_mode` (`publish_only` or `publish_and_deploy`)

Rules:
- model-emitted analytics scripts are normalized to placeholders
- measurement id insertion precedence:
1. publish request override id (publish only)
2. workspace analytics config id
3. site GA4 measurement id
- analytics insertion settings saved in workspace (`enabled`, `ga_measurement_id`, `insertion_mode`) persist and are re-hydrated from authoritative summary state after save/reload
- when workspace GA measurement id is empty, migration workspace hydrates from authoritative site GA measurement id surfaced in migration readiness payloads
- `publish_only` mode omits GA measurement input from deploy dispatch
- placeholder normalization is deterministic (duplicate placeholders collapse to a single insertion point)
- repeated publish/deploy actions do not duplicate analytics insertion in generated output payloads
- insertion is restricted to allowed static artifact files and controlled modes only

## GA4 Outcome Snapshot (Phase 5B)

Migration workspace summary now supports an additive, optional `ga4_outcome_snapshot` for post-publish/deploy observational context.

Behavior:
- anchor selection uses existing successful workspace timestamps only:
  1. `migration_deployed` from `last_deployed_at` (preferred)
  2. `migration_published` from `last_published_at` when deploy timestamp is absent
- deterministic before/after windows:
  - 14 days before anchor
  - 14 days after anchor (bounded by available data)
- if fewer than 7 days have elapsed since anchor:
  - status is `pending_after_window`
  - operator hint indicates more time is needed
- GA4 remains optional and non-blocking:
  - statuses remain bounded (`available`, `pending_after_window`, `insufficient_data`, `not_configured`, `missing_scope`, `permission_denied`, `unavailable`)
  - migration publish/deploy execution behavior is unchanged

Operator wording is intentionally non-causal:
- `Observed after deploy`
- `Observed after publish`
- `No clear movement yet`

The snapshot is observational context only and does not claim attribution/causation.

## Failure Categories and Operator Next Steps
Migration publish/deploy paths normalize failures into stable categories:
- `config_missing`
  - Missing/invalid migration runtime config (most commonly GitHub publisher configuration).
  - Operator/Admin action: verify ownership-level metadata first (Admin owner + workspace repo/branch), then platform/runtime wiring (`GIT_TOKEN` plus `GIT_USERID`/`GIT_EMAIL` when private-image auth mode is enabled) if metadata is valid but runtime capability is blocked.
- `target_invalid`
  - Publish/deploy target repo/branch/root/workflow/ref/inputs failed validation.
  - Operator action: fix site workspace target config and retry.
  - Deploy dispatch failures now include specific non-secret reason codes for target resolution:
    - `repo_not_found`
    - `workflow_not_found`
    - `workflow_file_missing`
    - `branch_not_found_or_ref_invalid`
    - `workflow_disabled`
    - `workflow_dispatch_missing`
    - `workflow_not_dispatchable`
    - `workflow_dispatch_not_supported`
    - `workflow_dispatch_rejected`
  - Publish repository auto-create/control-plane reason codes:
    - `repo_auto_create_disabled`
    - `repo_auto_create_not_authorized`
    - `repo_create_failed_invalid_name`
    - `repo_create_failed_owner_mismatch`
    - `repo_create_failed_conflict`
    - `repo_create_failed_runtime_unavailable`
  - Managed repository ownership marker reason codes:
    - `github_repo_management_marker_missing`
    - `github_repo_management_marker_mismatch`
    - `github_repo_management_marker_invalid`
    - `github_repo_bootstrap_marker_write_failed`
    - `github_repo_baseline_reconciliation_failed`
- `approval_required`
  - Attempted publish/deploy before required approval/publish prerequisites were satisfied.
  - Operator action: approve artifact first; deploy only after successful publish.
- `duplicate_request`
  - Duplicate publish/deploy request for same artifact + equivalent target context.
  - Deploy duplicate blocking now applies to active in-flight attempts only, not all historical records.
  - Operator action: if blocked, refresh deploy status and retry after the prior attempt reaches a terminal state.
- `deploy_blocker_reconciliation_failed`
  - Control plane could not refresh GitHub run evidence for an aged duplicate deploy blocker that still appears active.
  - Operator action: run `Refresh Deploy Status`, confirm the prior workflow run state, then retry deploy.
- `stale_deploy_blocker_requires_refresh`
  - Control plane could not safely reconcile an old duplicate deploy blocker and requires manual status refresh confirmation.
  - Operator action: refresh deploy status, confirm prior run is terminal, then retry deploy.
- `deploy_blocker_superseded_after_stale_threshold`
  - Control plane auto-superseded an over-age duplicate blocker after hard stale threshold reconciliation.
  - Operator action: retry deploy; inspect GitHub Actions history only if an orphan run is suspected.
- `artifact_invalid`
  - Selected artifact files were not publishable under bounded static-file rules.
  - Operator action: regenerate/re-approve a valid artifact version.
- `provider_error`
  - Publish execution failed in provider call path.
  - Operator action: inspect publish history + external provider status and retry.
- `deploy_error`
  - Deploy dispatch failed in provider call path.
  - Operator action: inspect deploy history + workflow execution status and retry.
- `unknown_error`
  - Fallback category when no more specific category is available.

These categories are exposed through migration readiness/history payload fields for operator diagnostics.

## History Record Contract
Publish/deploy history entries are append-only, bounded lists and include:
- `action` (`publish` or `deploy`)
- `status` (`dry_run`, `published`, `deploy_requested`, `failed`)
- `timestamp`
- artifact identifiers (`artifact_version_id`, `artifact_version`)
- target metadata relevant to the action (repo/branch/root or repo/workflow/ref/inputs)
- analytics metadata (`analytics_measurement_id`, `analytics_insertion_mode`, plus `analytics_applied` when available)
- result identifiers when available (`latest_commit_sha`, `commit_shas`, `published_at`, `dispatched_at`)
- normalized failure category (`failure_category`) on error paths
- normalized deploy failure reason code (`failure_reason`) and stage (`failure_stage`) on deploy failure paths when available
- sanitized failure summary (`error_summary`) on error paths
- deploy workflow resolution trace fields (`resolved_workflow_source`, and `workflow_path` when known)

## Deploy Path Stage Model
Deploy diagnostics now track explicit staged evidence:
1. `artifact`
2. `publish_target`
3. `workflow_identity`
4. `dispatch_service_availability`
5. `workflow_dispatch` attempt/result
6. `workflow_run_evidence`
7. `resolved_live_url_evidence`

Post-dispatch evidence fields are now explicitly tracked so transport acceptance and execution evidence are not collapsed:
- `dispatch_ref_sent`
- `workflow_inputs_configured_keys`
- `workflow_inputs_sent_keys`
- `workflow_run_lookup_attempted`
- `workflow_run_found`
- `workflow_job_failure_detected`
- `post_dispatch_state` (for example `dispatch_not_attempted`, `dispatch_accepted_no_run`, `dispatch_unverified_no_run`, `workflow_run_pending`, `workflow_run_in_progress`, `workflow_run_failed`, `workflow_run_succeeded_without_live_url`, `workflow_run_succeeded_with_live_url`)
- `post_conformance_stage` (normalized post-conformance stage classification)
- `post_conformance_reason_text` (operator-safe explanation for the normalized stage)

This keeps trigger-level and service-level readiness distinct:
- workflow trigger support: `workflow_dispatch_supported`, `workflow_trigger_types`
- workflow conformance support: `workflow_conformance_checked`, `workflow_conformance_status`, `workflow_conformance_reasons`
- deployment-side service/function availability: `dispatch_service_availability`, `dispatch_service_reason_code`
- dispatch outcome evidence: `dispatch_attempted`, `dispatch_result_stage`, `workflow_run_id`

Post-conformance stage values are normalized and additive (existing structured reason codes/stages remain authoritative):
- `workflow_conformance_failed`
- `workflow_dispatch_blocked`
- `workflow_dispatch_attempted`
- `workflow_dispatch_failed`
- `workflow_dispatch_succeeded_waiting_for_run`
- `workflow_run_failed`
- `rollout_failed`
- `live_url_evidence_missing`
- `deploy_succeeded`

Workflow conformance semantics:
- `conformant`: workflow content is dispatchable and includes managed deploy contract markers
- `workflow_dispatch_missing`: workflow content is readable but missing `workflow_dispatch`
- `workflow_placeholder_detected`: workflow content matches placeholder/example markers
- `workflow_contract_incomplete`: workflow is dispatchable but missing required managed deploy contract markers
- `workflow_unreadable`: workflow file exists but content could not be decoded/read for conformance checks
- `workflow_missing`: workflow payload was unavailable during conformance evaluation

Deploy-failure reason additions:
- `workflow_not_production_ready`: workflow identity resolved and trigger support exists, but workflow content still matches scaffold/placeholder deploy behavior.

## Target Repo Deploy Contract
MBSRN now distinguishes control-plane success from target-repo deploy confirmation using an explicit deploy evidence contract.

Required explicit evidence paths for confirmed live deployment:
- `workflow_output` evidence that includes a live URL key from:
  - `resolved_live_url`
  - `live_url`
  - `deployed_url`
- `deploy_result` evidence that explicitly includes `live_url`

Workflow-output key precedence is deterministic:
1. `resolved_live_url`
2. `live_url`
3. `deployed_url`
4. `deploy_result.live_url` fallback (when workflow-output URL keys are absent)

Both site-specific and fallback target-repo workflows are expected to emit the same GitHub Pages evidence contract keys.

Advisory-only contract fields surfaced in deploy readiness/history/diagnostics:
- `expected_workflow_outputs`
- `deploy_evidence_contract_status`
- `deploy_evidence_contract_reasons`
- `workflow_contract_advisory`

Contract status meanings:
- `confirmed_live_evidence`: explicit URL evidence captured from `workflow_output` or `deploy_result`
- `workflow_placeholder_advisory`: workflow appears placeholder/non-deploying
- `workflow_contract_incomplete_advisory`: workflow dispatches but misses managed deploy contract markers
- `workflow_succeeded_without_explicit_evidence`: run succeeded but emitted no explicit live URL evidence
- `workflow_run_failed_without_explicit_evidence`: run failed before explicit evidence was captured
- `evidence_pending`: dispatch accepted, run evidence still pending
- `evidence_not_attempted`: dispatch was blocked/not attempted
- `unknown`: insufficient evidence to classify

Important boundary:
- `expected_publish_url` is guidance only.
- `resolved_live_url` is confirmed only from explicit evidence (`workflow_output` or `deploy_result`).
- repo/branch/domain naming or operator request inputs never confirm live deployment.

Safety boundary:
- workflow conformance diagnostics are deterministic and content-based.
- expected vs confirmed URL evidence rules are unchanged: `resolved_live_url` only comes from explicit deploy evidence (`workflow_output` or `deploy_result`), never from workflow selection or operator input.

Scope note:
- `dispatch_service_availability` is a control-plane readiness signal (runtime publisher wiring + target tuple validity + target enabled).
- it does **not** prove downstream GitHub Actions environment readiness inside the target repo (for example missing deploy workflow implementation details, missing Actions secrets/variables, or missing GCP/GKE permissions).

## Structured Logging
Migration control-plane actions emit structured logs (`event=seo_migration_control_plane_action`) for:
- approval requested/completed/failed
- publish requested/completed/failed
- deploy requested/completed/failed
- deploy workflow source resolution (`event=seo_migration_deploy_workflow_resolution`) when publish-history workflow identity is used
- deploy target readiness preflight (`event=seo_migration_target_readiness_check`) with repo/ref/workflow/dispatch-ready booleans
- deploy dispatch failure diagnostics (`event=seo_migration_deploy_dispatch_failed`)
- deploy secret propagation audit (`event=seo_migration_deploy_secret_propagation`) for guardrailed `GCP_DEPLOY_KEY` create/update/skip/failure outcomes

Draft generation also emits structured logs:
- service-level lifecycle (`event=seo_migration_draft_generation`) with requested/completed/partial/failed states
- provider request lifecycle (`event=seo_migration_draft_provider_request_start|complete|failure`)
- provider response parse lifecycle (`event=seo_migration_draft_provider_response_parse`)
- runtime publish/deploy capability diagnostics when unavailable (`event=seo_migration_runtime_publisher_readiness`)

Logged fields are safe metadata only:
- `business_id`, `site_id`, `workspace_id`
- `artifact_version_id`, `artifact_version`
- `action`, `status`, `dry_run`, `duration_ms`
- sanitized target summary (repo/branch/root or workflow/ref)
- `failure_category` and sanitized `failure_reason` on failures
- deploy failure logs include non-secret dispatch diagnostics (`failure_reason_code`, `failure_stage`) and workflow source (`resolved_workflow_source`)
- deploy target readiness logs include:
  - `requested_ref`, `resolved_ref`, `ref_source`
  - `repo_exists`, `ref_exists`, `workflow_exists`, `workflow_dispatch_ready`
  - `workflow_dispatch_supported`, `workflow_trigger_types`, `dispatch_identifier_type` (`workflow_id` or `workflow_file_path`; legacy `workflow_numeric_id` is normalized on read)
  - `workflow_conformance_checked`, `workflow_conformance_status`, `workflow_conformance_reasons`, `workflow_conformance_evidence_summary`
  - `workflow_identifier_requested`, `workflow_identifier_used`
  - `workflow_identifier_type_requested`, `workflow_identifier_type_used`
  - `workflow_dispatch_resolution_source`, `workflow_file_path`, `workflow_name`
  - `dispatch_service_availability`, `dispatch_service_reason_code`
  - `deploy_trace_id`
  - `remediation_mode`
- draft-generation fields include `draft_run_id`, provider/model/prompt version, retryability, and correlation id when available
- draft-generation fields include `model_requested`, `model_resolved`, `model_used`, request-shape metadata (`endpoint_path`, `execution_mode`, `response_format_mode`, `request_body_mode`), and `failure_source` (`local_preflight` vs `remote_provider`) for request-path traceability
- provider parse logs include `raw_length`, `parsed_candidate_count`, `salvaged_candidate_count`, and `malformed_output_reason` (when present)
- runtime publisher diagnostics include `runtime_publisher_reason_code` plus ownership-level booleans (`admin_publish_configured`, `admin_publish_config_enabled`, `operator_repository_configured`)
- deploy secret propagation diagnostics include:
  - `secret_name` (name only; value never logged)
  - `attempted`
  - `status` (`created`, `updated`, `skipped_guardrail`, `failed`)
  - `reason`
  - `action` (`created`/`updated` when applicable)

Not logged:
- tokens/secrets
- full generated artifact contents
- raw provider stack traces in operator-facing surfaces

## API Surface (Phase 1-4)
Core workspace:
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/summary`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/prompt-preview`

Inputs/ingest:
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/source-ingest`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/operator-requirements`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/enriched-content`

Draft artifacts:
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/file-preview?path=...`

Publish/deploy controls:
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/publish-config`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-config`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/analytics-config`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/approve`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/publish`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy/refresh-status`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/publish-history`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-history`

## Operator Runbook
1. Confirm source ingest is complete and reviewed.
2. Confirm requirements and enriched content override weak incumbent content where needed.
3. Review preflight readiness card.
4. If `not_ready`, fix blocking reasons before generation.
5. If `ready_with_warnings`, decide whether to proceed or improve warning signals first.
6. Generate draft artifacts and review files.
7. Approve the chosen artifact version.
8. Confirm Admin publish target readiness and run publish dry-run.
9. Run publish (non-dry-run) after dry-run checks pass.
10. Confirm deploy is enabled for the workspace and run deploy dry-run.
11. Submit deploy request.
12. Validate deployment externally and coordinate DNS cutover separately.

### Deploy Verification Cues (UI)

In the Deploy Readiness traceability grid, use these fields for production verification:
- `Deploy trace ID`: correlation handle for control-plane and refresh logs.
- `Workflow identifier (requested vs used)`, `Ref / branch`, `Workflow source`: confirms which workflow target was requested, what was dispatched, and why.
- `Dispatch ref sent`, `Workflow input keys (configured)`, `Workflow input keys (sent)`: confirms payload key-set truth for dispatch contract validation.
- `Trigger support` and `Service/function availability`: separates workflow trigger compatibility from runtime service readiness.
- `Dispatch result stage`, `Workflow run lookup attempted`, `Workflow run found`, `Workflow job failure detected`, and `Post-dispatch state`: separates accepted-no-run eventual consistency from run-failed and run-in-progress outcomes.
- `Workflow run ID` and `Workflow run state`: confirms when run evidence exists.
- `Expected URL` vs `Confirmed live URL`: expected URL is guidance; confirmed URL appears only from explicit deploy/workflow evidence.

In **Advanced Diagnostics -> Deploy Diagnostics**, the default card is compact and operator-first:
- normalized status (`Success|Pending|Blocked|Failed|Unknown`)
- selected-attempt (or latest-summary fallback) context line
- one concise reason summary
- one concise next-action summary

Verbose evidence remains available in `Show raw deploy diagnostics fields`:
- deploy failure category/reason/stage
- requested workflow identifier and resolved workflow path
- workflow existence (`Yes` / `No`) and workflow resolution source
- dispatch service reason code
- remediation hint (`deploy_failure_remediation_hint`) derived deterministically from failure reason/stage evidence when a known mapping applies
- post-conformance stage (`post_conformance_stage`) and reason text (`post_conformance_reason_text`)
- concise post-conformance next-step guidance (`post_conformance_remediation_message`) to distinguish refresh/retry/log-inspection actions
- operator UI should prefer backend remediation/guidance fields first and only fall back to local reason-code copy for older history records or missing backend hints

Use this block to diagnose workflow-lookup failures without relying only on coarse `target invalid` category labels.

In **Advanced Diagnostics -> Publish Diagnostics**, the default card is compact and operator-first:
- normalized status (`Success|Pending|Blocked|Failed|Unknown`)
- selected-attempt (or latest-summary fallback) context line
- one concise reason summary
- one concise next-action summary

Workflow remediation visibility remains explicit in `Show raw publish diagnostics fields`:
- `workflow_remediation_attempted` (`Yes` / `No`)
- `workflow_remediation_outcome` (attempt result classification)
- concise next-step guidance based on remediation outcome

Use publish remediation outcome before retrying blindly:
- `remediation_upgraded_managed_placeholder`: retry deploy/readiness
- `remediation_already_current`: move to next blocker domain
- `remediation_preserved_custom`: manual custom workflow correction required
- `remediation_write_failed`: inspect integration/provisioning failure details first

Deploy history and latest failure summary preserve the same deploy truth model:
- latest failure summary (`deploy_readiness.last_failure_*`) carries reason/stage plus requested vs resolved workflow evidence when available
- deploy history failed entries include the same fields and may include a remediation hint
- if no deterministic mapping applies, remediation hint is omitted rather than guessed

If dispatch was accepted but run evidence is not yet present, the workspace shows a no-run-yet message and instructs operators to use **Refresh deploy status** after eventual consistency delay.

### Managed Per-Site Deploy Contract

Managed-site deploy validation is site-isolated and evaluated per deploy attempt, per site hostname (`<repo>.site.mbsrn.com`).

Managed-site deploy auth is configuration-driven and generic for all sites:
- `target_repo_actions_secret`: site-repo workflow authenticates with target-repo Actions secret (`GCP_DEPLOY_KEY`).
  - deploy readiness blocks before dispatch when the secret is required but missing (`target_repo_deploy_secret_missing`).
  - workflow-run failures with the same root cause are classified explicitly (`generated_workflow_requires_missing_gcp_deploy_key`) instead of generic provisioning failure text.
- `control_plane_managed` / `github_oidc_workload_identity`: target-repo deploy secret is not required by the workflow contract.
- readiness and diagnostics expose:
  - `deploy_auth_mode`
  - `target_repo_deploy_secret_required`
  - `target_repo_deploy_secret_name`
  - `target_repo_deploy_secret_present`

Deploy is not considered HTTPS-ready unless all runtime checks agree:
- DNS A record matches expected deploy DNS target IP (`dns_record_matches_ingress=true`, `dns_expected_ip == dns_observed_ip`)
  - for managed per-site static-IP ingress, `dns_expected_ip` is the reserved static IP address when metadata is available/bound
  - ingress status IP may lag and is advisory when static-IP binding evidence is healthy
- managed certificate identity matches the site hostname (`cert_identity_valid=true`)
- certificate domain status is active (`tls_certificate_status=ACTIVE`, `tls_domain_status=ACTIVE`)
- no ingress/static-ip or certificate cross-site conflict (`ingress_conflict_detected=false`)
- explicit HTTPS live URL evidence is present (`deploy_https_ready=true` and `resolved_live_url` starts with `https://`)

TLS/certificate readiness is exposed separately from runtime rollout status:
- `certificate_readiness_state` values:
  - `certificate_missing`
  - `certificate_visibility_pending`
  - `certificate_provisioning_pending`
  - `certificate_active`
  - `certificate_failed_not_visible`
  - `certificate_domain_mismatch`
  - `certificate_ownership_unverified`
  - `certificate_status_unknown`
  - `certificate_stale_or_legacy`
- `Provision TLS Certificate` is a separate, idempotent control-plane action. It creates or verifies the deterministic ManagedCertificate and refuses cross-site/domain-mismatched resources.
- `runtime_ready_tls_pending=true` means ingress/load-balancer/runtime evidence exists, but cert/HTTPS are still converging.
- `PROVISIONING` is an issuance wait-state, not a pre-dispatch blocker. Deploy validates the resource and attaches ingress; refresh deploy status follows TLS convergence.
- Firefox preview failures such as `PR_END_OF_FILE_ERROR` usually indicate missing/unready `ManagedCertificate` or ingress TLS convergence, not a selected-media or publish/readiness regression.
- `https_ready=true` is only emitted when HTTPS probe and certificate readiness are both satisfied.

Resolve-live-url failure diagnostics are evidence-first:
- workflow gathers ingress status, reserved static-IP metadata, DNS A-record observation, and ManagedCertificate domain/status evidence before terminal failure classification.
- failure-state trap fields (`resolve_live_url_state_*`) should include populated `expected_static_ip_address`, `dns_expected_ip`, `dns_observed_ip`, and ManagedCertificate status/domain fields when that evidence is available from cluster/GCP APIs.
- empty trap fields now primarily indicate upstream evidence is genuinely unavailable (for example missing ingress/static-IP/hostname), not premature early exit ordering.
- when `deploy_https_ready=false`, probe evidence is expected to remain populated via bounded `https_probe_error_summary` unless no probe was attempted (`https_probe_not_attempted`).
- `deploy_https_ready=false` with blank `https_probe_error_summary` is treated as a diagnostics regression.
- managed deploy workflow failures are expected to emit final reason summary fields before exit:
  - `deploy_runtime_reason_code`
  - `deploy_runtime_reason_message`
  - `deploy_runtime_failure_stage`
  - plus bounded final runtime-state evidence (`runtime_ready`, `ingress_address_resolved`, `service_exists`, `endpoints_ready`, `managed_certificate_exists`, `managed_certificate_status`, `https_ready`, `runtime_ready_tls_pending`, and replace-runtime requested/performed fields).
- if GitHub UI only shows `Process completed with exit code 1` and logs do not include `deploy_runtime_reason_code`, workspace guidance falls back to:
  - `runtime_readiness_unknown_failure` when managed template marker evidence exists
  - `managed_deploy_workflow_template_stale` when managed template markers are missing (reprovision workflow/template from publish).
- `mbsrn_managed_deploy_template_version` is diagnostics-only metadata and is not a publish/deploy execution gate by itself.
- control-plane-ready but host-unreachable states are explicitly classified:
  - `certificate_provisioning_pending` when static IP + ingress binding are aligned but ManagedCertificate is still `PROVISIONING`
    - legacy workflow-log/history aliases (`managed_certificate_provisioning`, `tls_certificate_provisioning`, `managed_certificate_pending`, `runtime_ready_tls_pending`) remain read-compatible
  - `https_probe_failed_after_control_plane_ready`
  - `https_probe_timeout`
  - `https_probe_empty_reply`
  - `https_probe_not_attempted`
- `ingress_backend_502` remains a distinct classification when HTTPS reaches ingress and backend returns 502.
  - deploy does not pass on backend health alone; preview HTTPS must return non-5xx.
  - advanced deploy diagnostics expose bounded fields: preview status, backend health status, k8s endpoint readiness, in-cluster service/endpoint probe results, and runtime probe classification.

Operator verification commands for control-plane-ready / HTTPS-not-ready:
- `kubectl -n <namespace> get ingress`
- `kubectl -n <namespace> get service site-web -o wide`
- `kubectl -n <namespace> get endpoints site-web`
- `kubectl -n <namespace> get pods -l app=site-web`
- `kubectl -n <namespace> describe ingress site-web`
- `kubectl -n mbsrn-www describe managedcertificate site-web-preview-cert-mbsrn-www`
- `kubectl -n mbsrn-www describe ingress site-web`
- `gcloud compute addresses describe site-web-preview-ip-mbsrn-www --global`
- `kubectl -n <namespace> describe backendconfig site-web-backend-config-<site>`
- `curl -Iv https://<preview-host>/`

Blocking reason-code examples:
- workflow diagnostics fallback:
  - `runtime_readiness_unknown_failure`
  - `managed_deploy_workflow_template_stale`
- DNS mismatch:
  - `dns_record_mismatch`
  - `dns_points_to_old_ingress_ip`
  - `ingress_ip_assigned_but_dns_not_updated`
  - `ingress_status_ip_stale_or_mismatched` (advisory/non-blocking when DNS already matches reserved static IP)
  - after control-plane DNS ensure, these typically indicate propagation delay, resolver visibility lag, or out-of-band DNS mutation
- TLS/certificate:
  - `certificate_provisioning_pending` (current outward wait-state when certificate/domain status is still `PROVISIONING`)
    - legacy workflow-log/history aliases may still appear internally: `managed_certificate_provisioning`, `tls_certificate_provisioning`, `managed_certificate_pending`, `runtime_ready_tls_pending`
  - `managed_certificate_failed_not_visible` (missing certificate object or visibility mismatch for the expected deterministic name; distinct from provisioning wait-state)
  - `managed_certificate_metadata_unavailable` (advisory: cluster metadata read failed/empty; if ingress annotation, DNS, and HTTPS cert identity checks pass, this alone does not block success)
  - `pre_shared_cert_metadata_mismatch` is advisory controller metadata only and does not override desired-state ManagedCertificate identity checks.
  - `certificate_domain_mismatch` (blocking: existing ManagedCertificate `spec.domains` does not match the expected preview hostname)
  - `stale_managed_certificate_present` (blocking: ManagedCertificate identity evidence is stale or cross-site)
  - `managed_certificate_ownership_unverified` (blocking: ownership labels/metadata do not verify this site)
  - `tls_certificate_bound_to_wrong_site`
- Ingress isolation:
  - `shared_preview_gateway_missing`
  - `shared_preview_gateway_hostname_missing`
  - `managed_site_static_ip_config_missing`
  - `managed_site_static_ip_permission_denied`
  - `managed_site_static_ip_api_disabled`
  - `managed_site_static_ip_quota_exceeded`
  - `managed_site_static_ip_project_not_found`
  - `managed_site_static_ip_conflict`
  - `static_ip_address_missing_after_retry` (legacy history entries may still show `managed_site_static_ip_address_missing`)
  - `managed_site_static_ip_provisioning_failed`
  - `managed_site_dns_config_missing`
  - `managed_site_dns_provisioning_failed`
  - `managed_site_dns_conflicting_record`
  - `managed_site_dns_permission_denied`
  - `managed_site_dns_transaction_conflict`
  - `managed_site_dns_propagation_pending`
  - `managed_site_static_ip_missing`
  - `expected_static_ip_not_bound_to_ingress`
  - `ingress_static_ip_conflict` (legacy histories may still show `shared_static_ip_not_allowed_for_per_site_ingress`)
  - `stale_pre_shared_cert_binding_detected`

Isolation rules:
- Endpoint mode controls static-IP expectations:
  - `preview_shared_gateway`: ingress must bind to configured shared preview static-IP name.
  - `dedicated_static_ip`: ingress must bind to expected dedicated static-IP name (`site-web-preview-ip-<normalized-site>` unless configured otherwise).
- Shared ingress static-IP binding is allowed only when endpoint mode resolves to `preview_shared_gateway`.
- After changing `managed_preview_endpoint` admin defaults, rerun publish/workflow provisioning and then rerun deploy so the generated target-repo workflow/manifests pick up the new mode.
- Cross-site certificate bindings are blocked.
- Control plane ensures expected static-IP/gateway prerequisites before dispatch; target workflow validates presence as a runtime safety check.
- Admin permanent-delete static-IP verification now recognizes creation-time GCP-safe ownership labels on newly created dedicated IPs before considering legacy DNS/name fallback.
- Legacy unlabeled or unverified IPs can still be skipped for manual review; shared preview gateway IPs are never treated as per-site delete candidates.
- Admin delete-plan/result diagnostics now surface concise static-IP verification states:
  - `Verified by labels.` means delete ownership proof came from exact managed address labels.
  - `Verified by DNS/name fallback.` means labels were absent and legacy DNS/name evidence matched exactly.
  - `Skipped: ownership unverified.`, `Skipped: shared preview gateway.`, `Skipped: IP is in use.`, and `Skipped: referenced by another site/config.` are safe operator-facing skip reasons.
  - `Not found.` means no matching address was present in the expected project/name scope.
  - `Delete failed.` means ownership verified, revalidation passed, but the delete operation itself failed.
- Control plane ensures preview-host DNS `A` record (`<normalized-site>.site.mbsrn.com`) before dispatch and updates only that exact hostname/type when DNS management is enabled for that mode.
- Target repositories do not create or mutate Cloud DNS records.
- Conflicting DNS record types at the same hostname (for example CNAME) block deploy before dispatch.
- `ingress.gcp.kubernetes.io/pre-shared-cert` is controller metadata and does not block deploy readiness by itself (including single-value name mismatch or multiple values).
- blocking cert-identity decisions rely on desired-state managed-certificate annotation, ManagedCertificate domain/status, and HTTPS/TLS probe identity evidence.
- `tls_certificate_bound_to_wrong_site` requires positive mismatch evidence (wrong ingress annotation/cert resource identity, non-empty mismatched ManagedCertificate domain evidence, or HTTPS TLS hostname mismatch); empty metadata alone is not treated as cross-site proof when HTTPS certificate identity is valid.
- when ingress annotation already references the expected deterministic ManagedCertificate resource name, workflow may safely repair domain drift by deleting/recreating only that ManagedCertificate and re-checking bounded status/domain convergence before allowing success.
- `replace_existing_runtime=true` does not treat TLS provisioning as runtime-replace failure: replacement status and TLS pending status are reported separately (`runtime_ready_tls_pending` / certificate state).

Managed deploy troubleshooting reason codes:
- `repo_adoption_required` / `github_repo_adoption_required`:
  - target repo exists but is not yet adopted/marked as managed for this site.
  - publish/deploy behavior follows the configured adoption policy; deploy workflow provisioning remains blocked until adoption is resolved.
- `workflow_provisioning_failed`:
  - managed workflow/bootstrap verification did not converge; inspect workflow provisioning diagnostics fields for failed stage and remediation mode.
- `target_repo_deploy_secret_missing`:
  - deploy auth mode requires target-repo secret `GCP_DEPLOY_KEY`, and readiness blocked before dispatch because it is missing.
- `generated_workflow_requires_missing_gcp_deploy_key`:
  - workflow run reached repo execution but failed the credential pre-check because required secret `GCP_DEPLOY_KEY` was not available.
- `SITE_WEB_IMAGE_TAG` empty handling:
  - empty `SITE_WEB_IMAGE_TAG` is allowed; managed workflow falls back to `${GITHUB_SHA}` and emits explicit diagnostics (`site_runtime_image_tag_source=github_sha_fallback`).
  - configured SHA-like values are used directly (`site_runtime_image_tag_source=configured_sha`).
  - `latest` or non-SHA values resolve to `:latest` fallback with explicit diagnostics.
- `static_ip_address_missing_after_retry`:
  - static IP ensure completed but bounded describe/list resolution never returned a usable address value.
  - list fallback is fail-closed: zero matches, multiple matches, or a match without `address` all remain blocked until a single exact name match resolves with a concrete address.
  - related diagnostics:
    - `address_not_found_after_retry`: no exact-name match found after bounded retry/list fallback.
    - `address_ambiguous_after_retry`: multiple exact-name matches were returned; deploy stays blocked.
    - `address_value_missing_after_retry`: exact-name match exists but has no usable numeric `address` value yet.
- `workflow_run_failed_without_live_url_evidence`:
  - workflow failed before usable live URL evidence was captured; use deploy history + workflow logs for stage-specific failure data.

### Deploy Consistency Block (Operator UI)

`Advanced Diagnostics -> Deploy Diagnostics` includes a compact **Deploy consistency** block for per-site deploy contract visibility.

Grouped checks:
- `Deployment rollout`
- `Service endpoints`
- `Backend health`
- `DNS`
- `Managed certificate`
- `HTTPS`
- `Workflow integrity`
- `Static IP / ingress policy`

Primary statuses render one of:
- `Pass`
- `Blocked`
- `Pending`
- `Unknown`

Workflow integrity gate renders:
- `Pass` (`workflow_integrity_status=match`)
- `Warning` (`workflow_integrity_status=mismatch`)
- `Unknown` (`workflow_integrity_status=missing` or unavailable)

Rendering model and precedence:
- selected deploy-attempt fields are authoritative when present
- latest deploy summary backfills only missing selected-attempt values
- existing diagnostics fallback note remains the operator cue when summary backfill is used
- shared-root-cause warnings may group related checks (for example DNS mismatch causing TLS/HTTPS failures)
- raw network/TLS/runtime fields are preserved under `Show raw deploy consistency fields`
- raw fields remain null-safe in disclosure (`dns_record_matches_ingress`, `dns_expected_ip`, `dns_observed_ip`, `expected_static_ip_address`, `static_ip_status`, `static_ip_users`, `ingress_status_ip`, `ingress_status_ip_matches_static_ip`, `static_ip_bound_to_expected_forwarding_rule`, `tls_certificate_status`, `tls_domain_status`, `ingress_ip`, `ingress_conflict_detected`, `cert_identity_valid`, `host_reachable`, `host_reachability_scheme`, `https_probe_error_summary`, `deploy_https_ready`)
- workflow integrity fields are null-safe and surfaced with the same selected-attempt-first precedence (`workflow_integrity_status`, `workflow_integrity_reason_code`)

Blocked-state operator remediation text surfaced in UI:
- DNS mismatch: update DNS A record to the observed ingress IP
- `FAILED_NOT_VISIBLE`: DNS is not visible to Google certificate validation yet
- cert bound to wrong site: certificate identity mismatch or stale binding
- ingress conflict: static IP or ingress ownership conflict detected
- HTTPS not ready: wait for DNS/TLS/LB convergence or inspect deploy evidence
- workflow integrity mismatch: workflow has been modified outside the managed template; behavior may differ from expected deploy contract

Backend runtime dependency note:
- `PyYAML` is required in backend runtime and CI environments for managed workflow conformance validation and workflow signature drift detection.

## Controlled Production Exercise Checklist
Use this checklist for a bounded real-world migration exercise:
1. Confirm migration runtime config is present (`GIT_TOKEN`, `GIT_USERID`, `GIT_EMAIL`) for private managed-image mode (default).
2. Confirm the target site repository uses GitHub Pages with **Source = GitHub Actions** for the selected deploy workflow path.
3. Confirm selected workflow contract emits explicit deploy evidence keys (`resolved_live_url`, `live_url`, `deployed_url`) on successful deploy.
4. Confirm publish target repo/branch/artifact-root is intentional for this site workspace.
5. Confirm preflight readiness is `ready` or `ready_with_warnings` and `hard_blocked=false`.
6. If warnings exist, confirm operator accepts quality tradeoff before generation.
7. Confirm the selected artifact version is explicitly approved.
8. Confirm analytics insertion mode (`publish_only` vs `publish_and_deploy`) and measurement id are intentional.
9. Run publish, then verify summary/readiness state and latest publish history entry (`status`, target, commit identifiers).
10. Run deploy, then verify summary/readiness state and latest deploy history entry (`status`, workflow/ref, dispatch timestamp).
11. Confirm diagnostics fields report expected values after each action (`last_publish_status`, `last_publish_failure_category/message`, `last_deploy_status`, `last_deploy_failure_category/message`).
12. For migration draft generation, confirm `context_summary.ai_execution.request_contract_status`, `provider_execution_status`, `artifact_result`, and `duration_ms` align with the expected run outcome.
13. Confirm traceability fields are present across logs/history (`business_id`, `site_id`, `workspace_id`, `artifact_version_id`, action/status, target summary, failure category, timestamp).
14. Confirm `resolved_live_url` is shown only when explicit deploy evidence exists and that URL loads successfully in-browser.
15. Confirm DNS/A-record cutover remains manual and outside the app.
16. Confirm rollback path: select prior stable artifact, re-approve, then explicitly re-publish and re-deploy.

## Production Shakeout Checklist (Bounded)
Use this short checklist for the first production shakeout cycle:
1. Publish completed successfully for the selected approved artifact.
2. Managed workflow file is present and marked as platform-managed.
3. Managed manifests are present and namespace-aligned for the derived site namespace.
4. Required GitHub repository secrets/variables for deploy are configured.
5. Deploy request starts and records a GitHub workflow run id.
6. Deploy stage classification is interpretable from diagnostics:
   - `gcp_auth`
   - `cluster_credentials`
   - `manifest_apply`
   - `rollout_verify`
   - `ingress_verify`
   - `ingress_evidence`
7. Duplicate blocker interpretation is correct:
   - run-backed active blocker = block
   - aged run-backed blocker (>=12 minutes) = reconcile with GitHub before final duplicate decision
   - unverified dispatch blocker = short 2-minute TTL
   - terminal prior run after reconciliation = retry allowed
   - reconciliation failure reason codes:
     - `deploy_blocker_reconciliation_failed`
     - `stale_deploy_blocker_requires_refresh`
   - hard-stale supersede evidence:
     - `deploy_blocker_superseded_after_stale_threshold`
     - prior history item `workflow_run_failure_reason_code=stale_deploy_blocker_superseded`
8. `resolved_live_url` is confirmed only when explicit deploy evidence is present (`workflow_output` or `deploy_result`).

## First Production Deploy (Operator Path)
Before clicking deploy:
1. Confirm the selected artifact is approved and published.
2. Confirm destination summary values (repo, ref, workflow, namespace) match intent.
3. Confirm required deploy secrets/variables are set for the target repository.

After clicking deploy:
1. Capture `deploy_trace_id`.
2. Confirm dispatch attempted and workflow run creation (`workflow_run_id`).
3. Confirm stage progression and run conclusion from diagnostics/refresh.

If no run appears:
1. Use **Refresh Deploy Status**.
2. Treat `dispatch_accepted_no_run` / `dispatch_unverified_no_run` as short-lived uncertainty.
3. If dispatch is explicitly rejected (`workflow_dispatch_rejected`, `workflow_dispatch_not_supported`, `workflow_disabled`, `workflow_dispatch_missing`), treat it as a dispatch-blocked target issue rather than a no-run uncertainty state.
4. Retry once no-run state becomes stale (2-minute TTL) or the prior attempt reaches terminal state.

If ingress evidence does not appear:
1. Check `workflow_run_failure_stage` and `workflow_run_failure_reason_code` for `ingress_verify` or `ingress_evidence`.
2. Confirm ingress endpoint readiness in target runtime and rerun refresh.
3. Do not treat expected URL guidance as live confirmation without explicit `resolved_live_url` evidence.

## Troubleshooting and Rollback
Publish failures:
- verify target repo/branch/root config
- verify artifact approval status and readiness reasons
- check path-boundary rejections in publish warnings/history
- if duplicate publish is reported, either select a different approved artifact or change target config intentionally
- if repository UI shows "Get started with GitHub Actions" after publish, inspect workflow provisioning logs/history:
  - `event=seo_migration_workflow_provisioning`
  - statuses: `created`, `already_exists`, `verified`, `failed`
  - remediation modes: `bootstrap`, `already_present`, `duplicate_publish_repair`
  - `workflow_remediation_attempted=true` means publish attempted managed workflow verification/upgrade even when artifact publish was duplicate-skipped
  - `workflow_remediation_outcome` interpretation:
    - `remediation_upgraded_managed_placeholder` -> retry deploy readiness (managed workflow was updated)
    - `remediation_already_current` -> investigate next blocker domain (workflow was already current)
    - `remediation_preserved_custom` -> custom workflow must be fixed intentionally outside managed auto-upgrade
    - `remediation_write_failed` -> inspect GitHub provisioning failure and retry publish once write issue is resolved
  - managed placeholder signatures (for example `Placeholder deploy` with `Deploy step not yet implemented`, `provisioned in mode`, or `customize before production rollout`) are auto-upgraded during publish provisioning
  - unknown custom workflows are preserved and may stay non-production-ready until replaced intentionally
  - remediation for older repos with scaffold workflows: run a non-dry-run publish for an approved artifact to trigger managed workflow verification/upgrade; if workflow remains non-production-ready and is custom/non-managed, replace it intentionally with a deploy-capable workflow contract
  - confirm publish/readiness path/ref alignment in logs:
    - `seo_migration_publish_workflow_resolution` (`workflow_id`, `workflow_path`, `ref`, `resolved_workflow_source`)
    - `seo_migration_publish_workflow_file_inspected` / `..._upsert_decision` (managed-vs-custom classification and write/preserve decision)
    - `seo_migration_deploy_workflow_readiness_source` (`workflow_path`, `requested_ref`, conformance status/reasons)
    - `seo_migration_workflow_candidate_alignment` (`publish_resolved_*` vs `readiness_resolved_*`, with `workflow_candidate_alignment_exact=true` expected after successful republish)
  - managed workflow provisioning outcomes:
    - `managed_workflow_created`
    - `managed_workflow_upgraded`
    - `managed_workflow_already_current`
    - `managed_workflow_preserved_custom`

Deploy failures:
- verify publish completed for selected artifact
- verify deploy target enabled/workflow/ref values
- inspect deploy history inputs and workflow execution status
- if duplicate deploy is reported, verify whether the prior deploy request already covers the same artifact+target+inputs
  - duplicate blocking means an active in-flight attempt exists; completed/failed/cancelled/stale historical attempts should not block retry
  - run-backed blockers older than 12 minutes are reconciled against GitHub run state before final duplicate rejection
  - use reason codes to route action:
    - `duplicate_request` -> prior run still active
    - `deploy_blocker_reconciliation_failed` -> refresh failed while blocker may still be active
    - `stale_deploy_blocker_requires_refresh` -> stale blocker could not be safely reconciled automatically
    - `deploy_blocker_superseded_after_stale_threshold` -> blocker was auto-cleared after hard stale threshold; retry is allowed
- if readiness is blocked, use deploy blocker class + message to identify the owning actor:
  - `published_artifact_missing` -> Operator must publish first
  - `deploy_configuration_missing` / `deploy_configuration_invalid` -> Operator/Admin must fix target config
  - `deploy_runtime_unavailable` / `deploy_integration_unavailable` -> Platform/runtime wiring action required
- for repo/ref/workflow bootstrap target issues, inspect `seo_migration_target_readiness_check`:
  - `workflow_exists=false` means workflow bootstrap/repair did not verify on target ref
  - `workflow_dispatch_ready=false` means workflow metadata exists but is not dispatchable on target ref
  - `workflow_dispatch_supported=false` means trigger-level dispatch support is missing/invalid for the target ref
  - `workflow_conformance_status=workflow_placeholder_detected` now maps to deploy-stage blocker `workflow_not_production_ready` (scaffold workflow detected)
  - `workflow_contract_incomplete` remains advisory quality signal unless other dispatch/readiness blockers are present
  - mismatched `requested_ref` vs `resolved_ref` indicates ref resolution drift
  - dispatch payload inputs are taken from explicit `deploy_config.inputs` only (no implicit auto-injected workflow inputs), keeping GitHub `workflow_dispatch` input contracts deterministic

Verification checklist:
- publish success:
  - migration summary shows publish status/readiness aligned with latest action
  - publish history latest entry includes `status=published`, target metadata, and commit identifiers when available
- deploy success:
  - migration summary shows deploy status/readiness aligned with latest action
  - deploy history latest entry includes `status=deploy_requested`, workflow/ref, and dispatch timestamp

Rollback pattern:
- select and re-approve an older stable artifact version
- re-publish and re-deploy explicitly
- no automatic rollback orchestration is performed in this phase
- DNS/A-record cutover remains an external operator task and is not automated by this feature

## Artifact Media Materialization Contract (2026-05)
Selected media is only deploy-ready when it is materialized into artifact files and referenced by deployable static paths.

Required behavior:
- MBSRN source/import/upload storage is the pre-publish source of truth for referenced media; GitHub is the publish destination, not the pre-publish media source of truth
- selected/imported/uploaded media used by a generated draft is exported into artifact output under stable relative paths (for example `assets/images/...`)
- selected usable media marked `included in draft` is materialized automatically during draft generation, even when the provider does not reference every selected image
- provider context supplies canonical `artifact_path` values for selected media, and generated output is normalized to that path convention
- generated image references like `assets/<filename>` and matching CSS `url(...)` references are normalized to canonical `assets/images/<filename>` when they match selected media
- approved artifacts with stale media diagnostics can be repaired deterministically during publish preparation (materialize selected media + normalize references) when bytes are still available; operator should not need manual filename mapping or manual GitHub image copy/rename steps
- generated output must reference deployable artifact paths, not internal media IDs (`upl-...`), unresolved `@image(...)` placeholders, app/control-plane preview URLs, or storage/signed media URLs
- publish payloads include both generated HTML/CSS and the materialized image files, and referenced image files are overwritten in GitHub on every publish
- artifact read payloads remain bounded and do not expose raw base64 media blobs directly in API JSON responses

Readiness/cutover blockers now include:
- generated output references image paths that MBSRN cannot resolve to approved/source media (`generated_media_source_missing`)
- generated output references image paths whose approved/source bytes are unavailable for materialization (`generated_media_source_bytes_missing`)
- unresolved internal media references remain in generated output (`src=\"upl-...\"`) or unresolved `@image(...)` references remain (`generated_media_reference_unresolved`)
- generated output references private app/control-plane preview/media URLs, storage/signed media URLs, or other unsafe local/private paths
- generated output references image assets that cannot be included in the local GitHub publish payload (`generated_media_publish_payload_missing`)

Pending-generation status (non-blocking in draft preflight):
- if selected usable images were added after the currently selected artifact snapshot, draft input summary may show `selected_media_pending_generation`
- operator copy should read: `X selected images will be included when you generate the next draft package.`
- this pending-generation state is not treated as a post-generation materialization failure
- selected-but-unused (`selected_media_unused_by_generated_pages`) or changed-after-generation (`selected_media_changed_after_generation`) media is advisory only; generate a new draft package when you want those changes reflected in generated output
- selected media not yet present in the selected artifact package is advisory only unless generated output references missing image paths
- legacy advisory codes (`selected_media_available_not_referenced`, `selected_media_not_materialized`) remain read-compatible and are normalized to the current advisory set in API/UI output
- media blockers are driven by broken generated output references and publish-payload materialization failures, not by GitHub remote image presence
- private generated-output URLs are redacted in API/UI diagnostics; readiness surfaces expose blocker categories and remediation text, not raw private URLs

Readiness evidence notes:
- media readiness is artifact-version-specific and includes selected-media IDs, expected artifact paths, matched artifact paths, and missing artifact paths
- when GitHub asset evidence is unavailable, diagnostics explicitly report `github_asset_check_status=not_checked` instead of implying absence
- duplicate publish requests do not republish content for an already published artifact version; media changes require a newly generated/approved artifact version
- stale UI/server-action build mismatch should be resolved by refreshing the app before trusting publish/media state

Warnings (non-blocking):
- selected media exists but is unused by generated pages
- weak/missing alt text coverage

Operator expectation before publish/deploy/cutover:
1. `Images included in draft` count is non-zero when real media is required.
2. Artifact media readiness reports no blockers.
3. Preview renders referenced images from artifact-relative paths.
4. Published repository contains matching HTML and `assets/images/*` files.
5. No additional manual GitHub image management is required for selected migration media.

## Known Limitations
- bounded ingest scope (homepage-first, shallow extraction)
- no background worker pipeline introduced
- no external asset proxying
- no infrastructure/runtime file generation by model
- deploy request tracks intent/history; production validation remains an operator responsibility


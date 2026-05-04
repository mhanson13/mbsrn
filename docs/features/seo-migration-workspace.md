# SEO Migration Workspace (Phase 1-4)

## Intent
The migration workspace is a controlled operator workflow for replacing weak incumbent SMB websites with reviewable, structured, AI-assisted static artifacts.

The incumbent site is a signal source, not a canonical source of truth. The migration workspace becomes canonical by combining:
- imported source-site facts/signals
- operator requirements and requested changes
- enriched replacement content notes
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

State/order invariants:
- publish is blocked until the selected artifact version is approved and publish target readiness is valid
- deploy is blocked until the selected artifact version has a successful publish and deploy target readiness is valid
- failed publish attempts do not mark deploy-ready state
- failed deploy attempts do not mutate last successful publish metadata (artifact id/commit/timestamp)
- UI readiness indicators are derived from persisted workspace/artifact state returned by backend summary/readiness payloads

## Operator Workflow
Primary workflow now runs on the dedicated route:

`/sites/[site_id]/migration`

The main site workspace remains recommendation-first and provides a migration status + launch CTA.

Migration workflow on the dedicated page:
1. Create/manage workspace and set `source_url`.
2. Run bounded source ingest.
3. Capture requirements and enriched replacement content.
4. Review preflight draft readiness (blocking vs warning-only signals).
5. Generate and review draft artifacts.
6. Approve an artifact version.
7. Confirm Admin-managed GitHub publish target readiness and run publish dry-run.
8. Publish approved artifact to target repository.
9. Review Admin-owned deploy target diagnostics, set workspace deploy availability if needed, and run deploy dry-run.
10. Submit explicit deploy request to GKE deployment workflow.

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
  1. `A. Migration Overview`
  2. `B. Draft / Version Status`
  3. `C. Artifact Quality Summary`
  4. `D. Artifact Review`
  5. `E. Approval / Publish / Deploy`
  6. `F. Advanced Diagnostics & History`

Purpose:
- improve <10-second scanability for operators
- surface next action and draft quality earlier
- keep advanced diagnostics available but lower-priority

No workflow changes:
- approval/publish/deploy rules are unchanged
- backend/API behavior and gating are unchanged
- artifact quality remains advisory only

Site operator page information architecture update:
- the site operator route now keeps a smaller, decision-first structure:
  - summary/hero
  - recommendation workflow area
  - supporting snapshot/activity
  - migration launch surface
- embedded migration workflow content was removed from the main site workspace.
- migration now opens in its own dedicated workflow route (`/sites/[site_id]/migration`).
- GA4 setup was moved out of the site workspace and into Google Profile.
- analytics insertion rules were also moved out of migration and into Google Profile because they are site-wide controls.
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

Destination and preview trust additions:
- migration workspace now includes an `Effective Publish/Deploy Destinations` section that separates:
  - draft preview availability
  - expected publish destination (owner/repo/branch/path and derived repository tree URL when determinable)
  - platform-owned preview destination (`<site-slug>.site.mbsrn.com`) used for managed deploy validation with TLS
  - customer production domain target (`expected_publish_url`) as a separate cutover state
  - expected published site URL (`expected_publish_url`) when deterministic from target config
  - resolved live URL (`resolved_live_url`) when deploy metadata/runtime result provides a concrete URL
- destination summary scanability is grouped into compact blocks:
  - Admin-controlled destination
  - Operator-controlled destination
  - Derived URLs / publish target
  - Runtime / evidence state
  - lower-value troubleshooting metadata is available under `Show additional destination diagnostics`
- blocker visibility rule:
  - publish/deploy blockers stay visible without expansion
  - degraded-state blocker rows show compact failure identifiers (`category`, `reason`, `stage`) when available
  - readiness cards remain concise and point back to the destination summary for authoritative destination/runtime metadata
- URL source metadata now uses stable values:
  - `deterministic_target_config` (derived from configured deploy target inputs)
  - `workflow_output` (explicit URL captured from GitHub workflow completion metadata)
  - `deploy_result` (explicit URL surfaced by deploy dispatch result metadata)
  - `unknown` (not determinable from current config/history)
- confirmation semantics:
  - `deterministic_target_config` remains expected/not-confirmed destination guidance
  - only `deploy_result` and `workflow_output` sources are treated as confirmed live URL sources
  - preview deployment and customer-domain activation are intentionally separated:
    - preview URL can be confirmed from managed deploy evidence
    - customer production domain remains pending until explicit cutover and matching live evidence exist
  - deploy request inputs are never treated as confirmed live evidence; only explicit deploy-result/workflow output metadata can confirm live URL state
  - post-dispatch capture is best-effort and synchronous: the deploy action attempts to resolve the dispatched workflow run and reads explicit run-correlated completion metadata (for example deployment `environment_url`) when available
  - if completion metadata is not yet available immediately after dispatch, URL remains unconfirmed until a later deploy result includes explicit live URL evidence
- manual follow-up capture is available through `Refresh Deploy Status` in the migration workspace:
  - operator/admin can re-check stored workflow-run metadata without re-dispatching deploy
  - refresh updates workflow run status/conclusion when the run progresses
  - confirmed live URL is promoted only when new explicit workflow completion evidence is found
  - common no-op states are surfaced explicitly (`workflow_run_metadata_missing`, `deploy_record_missing`, `deploy_target_metadata_missing`)
- destination values are labeled as configured/expected/live/unknown; URLs are only shown when derivable from existing config or recorded deploy metadata
- diagnostics are run-bound, not floating snapshot-only:
  - publish diagnostics can be viewed for a selected publish attempt
  - deploy diagnostics can be viewed for a selected deploy attempt
  - draft diagnostics are scoped to the selected artifact version when available
  - labels indicate whether diagnostics are from selected context vs latest summary fallback
  - precedence is field-level and deterministic:
    - selected attempt fields are authoritative when present
    - latest summary fields only fill truly missing values
  - fallback usage is explicitly called out in diagnostics when selected-attempt fields are incomplete so operators do not mistake summary values for selected-attempt evidence
  - when no publish/deploy attempt is selected, diagnostics intentionally use latest summary context
  - publish/deploy history now appears under `Advanced Diagnostics & History` as collapsible troubleshooting sections
- draft website preview is available before publish/deploy from the selected artifact version:
  - rendered in a sandboxed, read-only iframe
  - explicitly labeled as draft-only (`not published`, `not deployed`)
  - supports whole-site preview across generated HTML pages via a page selector when multiple pages exist
  - preserves operator-session preview context by blocking external/app-auth links inside iframe preview; blocked links are shown as auth-context guidance instead of forcing re-auth loops
  - unavailable state is explicit when artifact HTML is missing
- Section D now owns review-stage draft actions:
  - `Preview Draft`
  - `Approve Selected Draft`
  - `Delete Selected Draft` (eligibility rules unchanged)
  - this keeps Section E focused on publish/deploy execution controls
- page map, generated files, and selected-file preview are presented in one combined inspection surface
- artifact file preview now supports explicit hide/show controls so operators can collapse preview content without losing selected file context
- draft lifecycle cleanup now includes single-draft deletion:
  - eligible unpublished drafts can be deleted from the migration workflow
  - deletion is blocked for published artifacts and for artifacts referenced by publish/deploy history
  - blocked deletes surface deterministic operator-safe reasons (for example: referenced by publish history)
  - deletion recalculates workspace pointers/readiness and keeps history integrity intact

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
Migration summary payload now includes `context_summary.draft_generation_readiness` before draft generation.

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

Runtime behavior:
- generate draft endpoint performs this preflight check first
- if `hard_blocked=true`, provider is not called and API returns a sanitized validation error
- readiness evaluations emit structured logs: `event=seo_migration_readiness_evaluation`

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
2. business admin default (`businesses.default_ai_model`)
3. deployment env default (`AI_MODEL_NAME`)
4. provider/runtime fallback

Operational implication:
- changing the admin default model can immediately change compatibility outcomes for migration draft generation without changing provider routing.

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
- `model=gpt-5.1*` with `endpoint_path=/responses`, `execution_mode=full`, `response_format_mode=json_schema`, and `request_body_mode=responses_text_format_json_schema`.

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
- `model=gpt-5.1*` with `endpoint_path=/chat/completions`, `execution_mode=full`, `response_format_mode=json_schema`, and `request_body_mode=chat_json_schema` is treated as `unsupported_request_shape`.
- fallback/default model paths (for example `gpt-4o-mini` using migration chat/json_schema request construction) are blocked unless that exact request shape is explicitly allowlisted and validated.

Unknown/unlisted model/request-shape combinations default to local block (`unsupported_model_configuration`) so parseable-but-unsupported shapes do not reach provider execution.

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

## AI Draft Generation Timeout
Migration draft generation timeout is admin-configurable through business settings:
- setting key: `migration_draft_timeout_seconds`
- runtime-safe range: 60-900 seconds
- default fallback when unset: 120 seconds

Operational guidance:
- typical range: 60-300 seconds
- larger draft payloads may require 300+ seconds
- prefer reducing generated output size/verbosity when possible instead of only increasing timeout
- values below the safe floor are treated as invalid at runtime and fall back to the default timeout (`120`).

Resolution precedence for timeout:
1. business admin setting (`migration_draft_timeout_seconds`)
2. migration default fallback (`120`)

Diagnostics surfaces:
- `context_summary.migration_diagnostics.draft_timeout_seconds`
- `context_summary.migration_diagnostics.draft_timeout_source`
- `context_summary.migration_diagnostics.last_draft_failure_timeout_seconds`
- `context_summary.migration_diagnostics.last_draft_failure_timeout_source`
- `context_summary.ai_execution.timeout_seconds`
- `context_summary.ai_execution.timeout_source`

Timeout failure behavior:
- category remains `config_missing` for draft-timeout contract compatibility
- `failure_reason=timeout`
- `last_draft_failure_source=remote_provider`
- `retryable=true`
- operator message remains sanitized (no raw provider payloads)

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
- `issues`: list of `{type, description}` entries
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

## Publish Workflow (GitHub)
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
- publish always runs deploy-workflow bootstrap verification against the target branch (`.github/workflows/{workflow_id}`) before returning success for non-dry-run publish
- generated/target repos are treated as workflow-missing by default until verified
- if workflow is missing, publish provisions it and verifies presence before marking publish as valid/deploy-ready
- provisioned workflow contract is explicitly dispatchable (`on: workflow_dispatch`) so deploy dispatch is a first-class bootstrap guarantee
- if workflow provisioning cannot be created or verified, publish fails (`workflow_provisioning_failed`) and is not marked successful
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
    - ingress requires deterministic per-site static IP binding:
      - annotation: `kubernetes.io/ingress.global-static-ip-name: site-web-preview-ip-<normalized-site>`
      - static IP names are site-scoped and must not be shared across sites
      - control plane ensures the expected global address exists before workflow dispatch using admin-managed deploy credentials
      - prerequisite chain is single-request and ordered: static-IP ensure -> DNS ensure (with the same in-request static IP address) -> DNS propagation gate -> workflow dispatch
      - generated target workflow still performs a preflight existence check (`gcloud compute addresses describe site-web-preview-ip-<normalized-site> --global --project "$GKE_PROJECT_ID"`) as a drift safety check
      - when ingress static-IP annotation matches expected per-site name, workflow fetches static-IP metadata (`address`, `status`, `users`) and treats reserved `address` as `dns_expected_ip`
      - if static IP is `IN_USE` and `users` indicate expected site forwarding-rule binding, ingress status IP mismatch is advisory only (`ingress_status_ip_stale_or_mismatched`)
      - if static IP metadata does not show expected binding evidence, deploy remains blocked with `expected_static_ip_not_bound_to_ingress`
      - workflow outputs additional network-binding diagnostics:
        - `expected_static_ip_address`
        - `static_ip_status`
        - `static_ip_users`
        - `ingress_status_ip`
        - `ingress_status_ip_matches_static_ip`
        - `static_ip_bound_to_expected_forwarding_rule`
      - `managed_site_static_ip_config_missing` blocks dispatch when control-plane static IP ensure is missing required project/deploy-key config
      - `managed_deploy_impersonation_config_invalid` blocks dispatch when `GCP_MANAGED_DEPLOY` is not a valid service-account email
      - `managed_deploy_impersonation_permission_denied` blocks dispatch when control-plane principal cannot impersonate `GCP_MANAGED_DEPLOY`
      - static IP ensure failures are classified before dispatch with operator-safe reason codes:
        - `managed_site_static_ip_permission_denied` (control-plane identity lacks `compute.globalAddresses.get/create`)
        - `managed_site_static_ip_api_disabled` (Compute Engine API disabled for managed project)
        - `managed_site_static_ip_quota_exceeded` (global static-address quota exhausted)
        - `managed_site_static_ip_project_not_found` (invalid/inaccessible managed project)
        - `managed_site_static_ip_conflict` (named address conflict that could not be reconciled)
        - `managed_site_static_ip_address_missing` (ensure succeeded but no usable address was returned after refresh; DNS ensure is not attempted with null IP)
        - fallback: `managed_site_static_ip_provisioning_failed`
      - static IP ensure diagnostics include effective credential metadata for IAM remediation:
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
      - `managed_site_static_ip_missing` when the expected per-site global static IP does not exist in GCP
      - `expected_static_ip_not_bound_to_ingress` when ingress is missing the expected per-site static IP annotation binding
      - `shared_static_ip_not_allowed_for_per_site_ingress` when ingress static IP annotation is present but does not match the expected per-site static IP name
      - `pre_shared_cert_metadata_mismatch` when controller-generated pre-shared certificate metadata differs from expected managed-certificate name (advisory; non-blocking by itself)
      - `stale_pre_shared_cert_binding_detected` only when stale/cross-site pre-shared metadata is corroborated by desired-state annotation/domain mismatch or HTTPS/TLS identity mismatch
      - `managed_certificate_failed_not_visible` when certificate visibility checks fail for the expected hostname
    - stale certificate resources are never auto-deleted; readiness/diagnostics provide manual cleanup guidance.
  - ingress address resolution uses a bounded wait loop (10-minute max: `40 x 15s`) because GKE load balancer provisioning can lag successful rollout
  - workflow URL resolution now short-circuits when the expected preview hostname is already reachable even if ingress status address lags:
    - `ingress_address_pending_but_hostname_reachable` indicates address propagation lag while host is reachable
    - `reachable_but_tls_certificate_mismatch` indicates the host responds but serves the wrong certificate identity
    - `ingress_backend_502` indicates ingress path is reachable but backend service is unhealthy
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
    - `branch_not_found_or_ref_invalid`
    - `workflow_not_dispatchable`
    - `workflow_dispatch_not_supported`
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
  - `workflow_dispatch_supported`, `workflow_trigger_types`, `dispatch_identifier_type`
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

In **Advanced Diagnostics -> Deploy Diagnostics**, operator-safe failure evidence is shown directly when available:
- deploy failure category/reason/stage
- requested workflow identifier and resolved workflow path
- workflow existence (`Yes` / `No`) at the selected target
- workflow resolution source
- dispatch service reason code
- remediation hint (`deploy_failure_remediation_hint`) derived deterministically from failure reason/stage evidence when a known mapping applies
- post-conformance stage (`post_conformance_stage`) and reason text (`post_conformance_reason_text`)
- concise post-conformance next-step guidance (`post_conformance_remediation_message`) to distinguish refresh/retry/log-inspection actions

Use this block to diagnose workflow-lookup failures without relying only on coarse `target invalid` category labels.

In **Advanced Diagnostics -> Publish Diagnostics**, workflow remediation visibility is now explicit:
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

Deploy is not considered HTTPS-ready unless all runtime checks agree:
- DNS A record matches expected deploy DNS target IP (`dns_record_matches_ingress=true`, `dns_expected_ip == dns_observed_ip`)
  - for managed per-site static-IP ingress, `dns_expected_ip` is the reserved static IP address when metadata is available/bound
  - ingress status IP may lag and is advisory when static-IP binding evidence is healthy
- managed certificate identity matches the site hostname (`cert_identity_valid=true`)
- certificate domain status is active (`tls_certificate_status=ACTIVE`, `tls_domain_status=ACTIVE`)
- no ingress/static-ip or certificate cross-site conflict (`ingress_conflict_detected=false`)
- explicit HTTPS live URL evidence is present (`deploy_https_ready=true` and `resolved_live_url` starts with `https://`)

Resolve-live-url failure diagnostics are evidence-first:
- workflow gathers ingress status, reserved static-IP metadata, DNS A-record observation, and ManagedCertificate domain/status evidence before terminal failure classification.
- failure-state trap fields (`resolve_live_url_state_*`) should include populated `expected_static_ip_address`, `dns_expected_ip`, `dns_observed_ip`, and ManagedCertificate status/domain fields when that evidence is available from cluster/GCP APIs.
- empty trap fields now primarily indicate upstream evidence is genuinely unavailable (for example missing ingress/static-IP/hostname), not premature early exit ordering.

Blocking reason-code examples:
- DNS mismatch:
  - `dns_record_mismatch`
  - `dns_points_to_old_ingress_ip`
  - `ingress_ip_assigned_but_dns_not_updated`
  - `ingress_status_ip_stale_or_mismatched` (advisory/non-blocking when DNS already matches reserved static IP)
  - after control-plane DNS ensure, these typically indicate propagation delay, resolver visibility lag, or out-of-band DNS mutation
- TLS/certificate:
  - `tls_certificate_provisioning`
  - `managed_certificate_failed_not_visible` (usually DNS/LB visibility mismatch)
  - `managed_certificate_metadata_unavailable` (advisory: cluster metadata read failed/empty; if ingress annotation, DNS, and HTTPS cert identity checks pass, this alone does not block success)
  - `managed_certificate_domain_drift_repaired` (advisory: expected ManagedCertificate name had stale `spec.domains`; workflow attempted safe delete/recreate repair)
  - `managed_certificate_domain_drift_repair_failed` (blocking: domain drift persisted or repair could not converge)
  - `tls_certificate_bound_to_wrong_site`
- Ingress isolation:
  - `managed_site_static_ip_config_missing`
  - `managed_site_static_ip_permission_denied`
  - `managed_site_static_ip_api_disabled`
  - `managed_site_static_ip_quota_exceeded`
  - `managed_site_static_ip_project_not_found`
  - `managed_site_static_ip_conflict`
  - `managed_site_static_ip_address_missing`
  - `managed_site_static_ip_provisioning_failed`
  - `managed_site_dns_config_missing`
  - `managed_site_dns_provisioning_failed`
  - `managed_site_dns_conflicting_record`
  - `managed_site_dns_permission_denied`
  - `managed_site_dns_transaction_conflict`
  - `managed_site_dns_propagation_pending`
  - `managed_site_static_ip_missing`
  - `expected_static_ip_not_bound_to_ingress`
  - `shared_static_ip_not_allowed_for_per_site_ingress`
  - `stale_pre_shared_cert_binding_detected`

Isolation rules:
- Per-site ingress must bind only its deterministic static IP name (`site-web-preview-ip-<normalized-site>`).
- Shared ingress static IP binding across sites is blocked.
- Cross-site certificate bindings are blocked.
- Control plane ensures per-site global static IP existence before dispatch; target workflow validates presence as a runtime safety check.
- Control plane ensures preview-host DNS `A` record (`<normalized-site>.site.mbsrn.com`) before dispatch and updates only that exact hostname/type.
- Target repositories do not create or mutate Cloud DNS records.
- Conflicting DNS record types at the same hostname (for example CNAME) block deploy before dispatch.
- `ingress.gcp.kubernetes.io/pre-shared-cert` is controller metadata and does not block deploy readiness by itself (including single-value name mismatch or multiple values).
- blocking cert-identity decisions rely on desired-state managed-certificate annotation, ManagedCertificate domain/status, and HTTPS/TLS probe identity evidence.
- `tls_certificate_bound_to_wrong_site` requires positive mismatch evidence (wrong ingress annotation/cert resource identity, non-empty mismatched ManagedCertificate domain evidence, or HTTPS TLS hostname mismatch); empty metadata alone is not treated as cross-site proof when HTTPS certificate identity is valid.
- when ingress annotation already references the expected deterministic ManagedCertificate resource name, workflow may safely repair domain drift by deleting/recreating only that ManagedCertificate and re-checking bounded status/domain convergence before allowing success.

### Deploy Consistency Block (Operator UI)

`Advanced Diagnostics -> Deploy Diagnostics` includes a compact **Deploy consistency** block for per-site deploy contract visibility.

Gate labels and status model:
- `Deployment rollout`
- `Service endpoints`
- `Backend health`
- `DNS matches expected target IP`
- `Managed certificate active`
- `Certificate identity valid`
- `Ingress/static IP conflict check`
- `HTTPS probe`
- `Workflow integrity`

Primary runtime gates render one of:
- `Pass`
- `Blocked`
- `Pending`
- `Unknown`

Workflow integrity gate renders:
- `Pass` (`workflow_integrity_status=match`)
- `Warning` (`workflow_integrity_status=mismatch`)
- `Unknown` (`workflow_integrity_status=missing` or unavailable)

Field rendering and precedence:
- selected deploy-attempt fields are authoritative when present
- latest deploy summary backfills only missing selected-attempt values
- existing diagnostics fallback note remains the operator cue when summary backfill is used
- network/TLS fields are always null-safe in UI (`dns_record_matches_ingress`, `dns_expected_ip`, `dns_observed_ip`, `expected_static_ip_address`, `static_ip_status`, `static_ip_users`, `ingress_status_ip`, `ingress_status_ip_matches_static_ip`, `static_ip_bound_to_expected_forwarding_rule`, `tls_certificate_status`, `tls_domain_status`, `ingress_ip`, `ingress_conflict_detected`, `cert_identity_valid`, `deploy_https_ready`)
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
3. Retry once no-run state becomes stale (2-minute TTL) or the prior attempt reaches terminal state.

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

## Known Limitations
- bounded ingest scope (homepage-first, shallow extraction)
- no background worker pipeline introduced
- no external asset proxying
- no infrastructure/runtime file generation by model
- deploy request tracks intent/history; production validation remains an operator responsibility


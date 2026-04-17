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

### GitHub Publish Configuration (Admin)
Migration publish now depends on an admin-managed GitHub target baseline:
- endpoint: `GET /api/admin/github-publish-config`
- endpoint: `PUT /api/admin/github-publish-config`
- fields:
  - `owner` (`account/org`, for example `mhanson13`)
  - `default_branch`
  - `base_path` (`/` for repo root, optional subpath like `/site`)
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
  - deploy workflow mode
  - target environment key
  - target environment source
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
- `MIGRATION_GITHUB_TOKEN`
- `MIGRATION_GITHUB_API_BASE_URL`
- `MIGRATION_GITHUB_TIMEOUT_SECONDS`
- `MIGRATION_PUBLISH_COMMIT_MESSAGE_PREFIX`
- `MIGRATION_PUBLISH_COMMITTER_NAME`
- `MIGRATION_PUBLISH_COMMITTER_EMAIL`
- `MIGRATION_DEPLOY_DEFAULT_WORKFLOW_ID`
- `MIGRATION_DEPLOY_DEFAULT_REF`

Notes:
- token is only read from runtime environment, never persisted in workspace rows
- production deployment wiring injects `MIGRATION_GITHUB_TOKEN` into `mbsrn-api` from the `mbsrn-api-auth` Kubernetes secret (`secretKeyRef` key `MIGRATION_GITHUB_TOKEN`)
- optional local GitHub control-plane validation should use `MIGRATION_GITHUB_TOKEN` (with a local test token value if needed); this keeps local/test/runtime naming consistent while remaining a non-production credential input
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
- duplicate non-dry-run deploy requests are blocked only when the same artifact+target+inputs already has an active in-flight deploy attempt
  - active blockers include confirmed non-terminal run states such as `workflow_run_pending`, `workflow_run_in_progress`, and `workflow_run_observed` (run-id backed)
  - run-backed active blockers are freshness-bound (30-minute stale window based on newest activity timestamp: `refreshed_at` -> `dispatched_at` -> `occurred_at` -> `timestamp`)
  - unverified dispatch states without run evidence (`dispatch_accepted_no_run` / `dispatch_unverified_no_run`) are weak blockers with a short 2-minute stale window
  - terminal/stale historical records (`workflow_run_failed`, `workflow_run_succeeded_without_live_url`, `workflow_run_succeeded_with_live_url`, cancelled/completed non-active, or stale no-run records) do not block a new deploy retry
  - stale no-run detection uses deterministic activity precedence: `refreshed_at` -> `dispatched_at` -> `occurred_at` -> `timestamp` with a 2-minute threshold for unverified dispatch records
- retry after a failed deploy is supported and recorded as a new history event
- deploy dry-run records history but does not overwrite prior successful deploy request markers
- platform-managed deploy workflow now performs a real GKE apply/rollout path for managed site workloads:
  - authenticate to GCP via Workload Identity (`google-github-actions/auth`)
  - fetch GKE credentials (`google-github-actions/get-gke-credentials`)
  - apply namespace first (`kubectl apply -f k8s/namespace.yaml`)
  - apply managed manifests (`kubectl apply -f k8s/`)
  - verify rollout (`kubectl rollout status deployment/site-web --namespace <derived-namespace>`)
  - verify service/ingress presence
- required GitHub Actions secret/variable contract for real deploy execution:
  - `OIDC_WORKLOAD_IDENTITY_PROVIDER`
  - `DEPLOY_SERVICE_ACCOUNT`
  - `KUBERNETES_CLUSTER_NAME`
  - `KUBERNETES_CLUSTER_LOCATION`
  - `GCP_PROJECT_ID`
- explicit deploy evidence contract for live URL confirmation:
  - workflow resolves URL from ingress status (`.status.loadBalancer.ingress[0].hostname|ip`)
  - workflow emits all three output keys on success:
    - `live_url`
    - `resolved_live_url`
    - `deployed_url`
  - no URL output is emitted when ingress status has no concrete endpoint; workflow fails instead
- post-dispatch workflow run diagnostics now distinguish execution-stage failures:
  - `workflow_run_failure_reason_code`
  - `workflow_run_failure_stage`
  - `workflow_run_failure_step`
  - `workflow_run_failure_hint`
  - examples include `gcp_auth_failed`, `gke_credentials_failed`, `kubectl_apply_failed`, `rollout_verification_failed`, `service_ingress_verification_failed`, and `ingress_endpoint_not_ready`

Current deployment model is reused via workflow dispatch conventions; platform deployment architecture is not redesigned by this feature.

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

Safety/ownership rules:
- these policies are generated from vetted platform templates, not model output
- operators do not hand-author these controls in normal workflow
- unknown custom repo files are not blindly overwritten
- policy values are schema-validated and normalized before rendering

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
  - Operator/Admin action: verify ownership-level metadata first (Admin owner + workspace repo/branch), then platform/runtime wiring (`MIGRATION_*`) if metadata is valid but runtime capability is blocked.
- `target_invalid`
  - Publish/deploy target repo/branch/root/workflow/ref/inputs failed validation.
  - Operator action: fix site workspace target config and retry.
  - Deploy dispatch failures now include specific non-secret reason codes for target resolution:
    - `repo_not_found`
    - `workflow_not_found`
    - `branch_not_found_or_ref_invalid`
    - `workflow_not_dispatchable`
    - `workflow_dispatch_not_supported`
- `approval_required`
  - Attempted publish/deploy before required approval/publish prerequisites were satisfied.
  - Operator action: approve artifact first; deploy only after successful publish.
- `duplicate_request`
  - Duplicate publish/deploy request for same artifact + equivalent target context.
  - Deploy duplicate blocking now applies to active in-flight attempts only, not all historical records.
  - Operator action: if blocked, refresh deploy status and retry after the prior attempt reaches a terminal/stale state.
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

This keeps trigger-level and service-level readiness distinct:
- workflow trigger support: `workflow_dispatch_supported`, `workflow_trigger_types`
- workflow conformance support: `workflow_conformance_checked`, `workflow_conformance_status`, `workflow_conformance_reasons`
- deployment-side service/function availability: `dispatch_service_availability`, `dispatch_service_reason_code`
- dispatch outcome evidence: `dispatch_attempted`, `dispatch_result_stage`, `workflow_run_id`

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

Use this block to diagnose workflow-lookup failures without relying only on coarse `target invalid` category labels.

Deploy history and latest failure summary preserve the same deploy truth model:
- latest failure summary (`deploy_readiness.last_failure_*`) carries reason/stage plus requested vs resolved workflow evidence when available
- deploy history failed entries include the same fields and may include a remediation hint
- if no deterministic mapping applies, remediation hint is omitted rather than guessed

If dispatch was accepted but run evidence is not yet present, the workspace shows a no-run-yet message and instructs operators to use **Refresh deploy status** after eventual consistency delay.

## Controlled Production Exercise Checklist
Use this checklist for a bounded real-world migration exercise:
1. Confirm migration runtime config is present (`MIGRATION_GITHUB_TOKEN` and related `MIGRATION_*` values).
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
   - unverified dispatch blocker = short 2-minute TTL
   - stale/terminal records = retry allowed
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
  - managed placeholder signatures (for example `Placeholder deploy` with `Deploy step not yet implemented`, `provisioned in mode`, or `customize before production rollout`) are auto-upgraded during publish provisioning
  - unknown custom workflows are preserved and may stay non-production-ready until replaced intentionally
  - remediation for older repos with scaffold workflows: run a non-dry-run publish for an approved artifact to trigger managed workflow verification/upgrade; if workflow remains non-production-ready and is custom/non-managed, replace it intentionally with a deploy-capable workflow contract

Deploy failures:
- verify publish completed for selected artifact
- verify deploy target enabled/workflow/ref values
- inspect deploy history inputs and workflow execution status
- if duplicate deploy is reported, verify whether the prior deploy request already covers the same artifact+target+inputs
  - duplicate blocking means an active in-flight attempt exists; completed/failed/cancelled/stale historical attempts should not block retry
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

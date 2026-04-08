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
Primary workflow in site workspace `Migration` tab:
1. Create/manage workspace and set `source_url`.
2. Run bounded source ingest.
3. Capture requirements and enriched replacement content.
4. Review preflight draft readiness (blocking vs warning-only signals).
5. Generate and review draft artifacts.
6. Approve an artifact version.
7. Configure publish target and run publish dry-run.
8. Publish approved artifact to target repository.
9. Configure deploy target and run deploy dry-run.
10. Submit explicit deploy request to GKE deployment workflow.

Important operator cue:
- GitHub publish is not production deployment.

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
- `admin_summary` (sanitized short admin hint)

Common compatibility reason codes:
- `provider_not_configured`
- `unsupported_model_configuration`
- `unsupported_request_shape`
- `unsupported_endpoint_mode`
- `tools_required_but_unavailable`
- `degraded_mode_not_allowed`
- `unknown_provider_capability`

Known unsupported request shape (blocked locally):
- `model=gpt-5.1` with `endpoint_path=/chat/completions` and `response_format_mode=json_schema` is treated as `unsupported_request_shape`.
- Migration draft generation is blocked by compatibility preflight before any outbound provider request.

Behavior:
- if compatibility is unsupported, draft generation fails fast locally
- outbound provider request is not attempted
- failure is persisted using existing draft-failure diagnostics (`failure_category`, `failure_reason`, `error_code`, `retryable`, correlation id)
- operator receives a concise sanitized message (for example, unsupported model/request-shape guidance)

Structured logging:
- compatibility evaluation emits `event=seo_migration_provider_compatibility_evaluation`
- includes identifiers and request-shape metadata (`business_id`, `site_id`, `workspace_id`, `provider_name`, `model`, `endpoint_path`, `execution_mode`, `web_search_enabled`, `degraded_mode`, `response_format_mode`, `supported`, `reason_code`, `retryable`)
- compatibility logs include `decision`:
  - `blocked_local_preflight` for local preflight block
  - `allowed` when the request shape is compatible
- remote provider rejections use provider request-failure logs (`event=seo_migration_draft_provider_request_failure`) with `failure_source=remote_provider`

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

Operator/API behavior:
- only `accepted`, `accepted_with_warnings`, and `salvaged` draft outputs are persisted as successful draft versions
- `rejected` outputs persist as failed draft generations with normalized failure fields
- operator-visible errors stay sanitized; raw provider payloads and prompts remain hidden
- operator UI surfaces a compact quality indicator for partial/salvaged output (`Partial draft generated.`)
- internal reason/warning code arrays stay in logs/diagnostics, not operator-facing debug dumps

## Publish Workflow (GitHub)
Publish target is site-scoped configuration:
- `repo_owner`
- `repo_name`
- `branch`
- `artifact_root`
- `enabled`

Publish behavior:
- explicit operator-triggered action only
- approved artifact required
- bounded file/path validation before publish
- no writes outside configured artifact root
- dry-run supported
- history captured with status/result metadata
- duplicate non-dry-run publish attempts for the same artifact+target are rejected with operator-readable validation errors
- retry after a failed publish is supported and recorded as a new history event
- dry-run publish records history but does not overwrite prior successful publish commit metadata

Security constraints:
- no GitHub token storage in migration rows
- no token values returned by API
- no token values logged

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
- per-site publish/deploy target details are stored in workspace config JSON fields
- runtime config is validated at action/readiness time for migration publish/deploy (feature-scoped validation); unrelated app features continue running when migration config is missing

## Deploy Workflow (GKE Path)
Deploy target is site-scoped configuration:
- optional repo override (`repo_owner`, `repo_name`)
- workflow id/ref (`workflow_id`, `ref`)
- bounded workflow `inputs`
- `enabled`

Deploy behavior:
- explicit operator-triggered action only
- approved + published artifact required
- readiness/state tracked separately from publish state
- deployment history captured with status/result metadata
- duplicate non-dry-run deploy requests for the same artifact+target+inputs are rejected with operator-readable validation errors
- retry after a failed deploy is supported and recorded as a new history event
- deploy dry-run records history but does not overwrite prior successful deploy request markers

Current deployment model is reused via workflow dispatch conventions; platform deployment architecture is not redesigned by this feature.

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
- `publish_only` mode omits GA measurement input from deploy dispatch
- placeholder normalization is deterministic (duplicate placeholders collapse to a single insertion point)
- repeated publish/deploy actions do not duplicate analytics insertion in generated output payloads
- insertion is restricted to allowed static artifact files and controlled modes only

## Failure Categories and Operator Next Steps
Migration publish/deploy paths normalize failures into stable categories:
- `config_missing`
  - Missing/invalid migration runtime config (most commonly GitHub publisher configuration).
  - Operator action: verify runtime env wiring (`MIGRATION_*`) and redeploy API if needed.
- `target_invalid`
  - Publish/deploy target repo/branch/root/workflow/ref/inputs failed validation.
  - Operator action: fix site workspace target config and retry.
- `approval_required`
  - Attempted publish/deploy before required approval/publish prerequisites were satisfied.
  - Operator action: approve artifact first; deploy only after successful publish.
- `duplicate_request`
  - Duplicate publish/deploy request for same artifact + equivalent target context.
  - Operator action: verify prior request outcome before resubmitting.
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
- sanitized failure summary (`error_summary`) on error paths

## Structured Logging
Migration control-plane actions emit structured logs (`event=seo_migration_control_plane_action`) for:
- approval requested/completed/failed
- publish requested/completed/failed
- deploy requested/completed/failed

Draft generation also emits structured logs:
- service-level lifecycle (`event=seo_migration_draft_generation`) with requested/completed/partial/failed states
- provider request lifecycle (`event=seo_migration_draft_provider_request_start|complete|failure`)
- provider response parse lifecycle (`event=seo_migration_draft_provider_response_parse`)

Logged fields are safe metadata only:
- `business_id`, `site_id`, `workspace_id`
- `artifact_version_id`, `artifact_version`
- `action`, `status`, `dry_run`, `duration_ms`
- sanitized target summary (repo/branch/root or workflow/ref)
- `failure_category` and sanitized `failure_reason` on failures
- draft-generation fields include `draft_run_id`, provider/model/prompt version, retryability, and correlation id when available
- provider parse logs include `raw_length`, `parsed_candidate_count`, `salvaged_candidate_count`, and `malformed_output_reason` (when present)

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
8. Save publish target config and run publish dry-run.
9. Run publish (non-dry-run) after dry-run checks pass.
10. Save deploy target config and run deploy dry-run.
11. Submit deploy request.
12. Validate deployment externally and coordinate DNS cutover separately.

## Controlled Production Exercise Checklist
Use this checklist for a bounded real-world migration exercise:
1. Confirm migration runtime config is present (`MIGRATION_GITHUB_TOKEN` and related `MIGRATION_*` values).
2. Confirm publish target repo/branch/artifact-root is intentional for this site workspace.
3. Confirm preflight readiness is `ready` or `ready_with_warnings` and `hard_blocked=false`.
4. If warnings exist, confirm operator accepts quality tradeoff before generation.
5. Confirm the selected artifact version is explicitly approved.
6. Confirm analytics insertion mode (`publish_only` vs `publish_and_deploy`) and measurement id are intentional.
7. Run publish, then verify summary/readiness state and latest publish history entry (`status`, target, commit identifiers).
8. Run deploy, then verify summary/readiness state and latest deploy history entry (`status`, workflow/ref, dispatch timestamp).
9. Confirm diagnostics fields report expected values after each action (`last_publish_status`, `last_publish_failure_category/message`, `last_deploy_status`, `last_deploy_failure_category/message`).
10. Confirm traceability fields are present across logs/history (`business_id`, `site_id`, `workspace_id`, `artifact_version_id`, action/status, target summary, failure category, timestamp).
11. Confirm DNS/A-record cutover remains manual and outside the app.
12. Confirm rollback path: select prior stable artifact, re-approve, then explicitly re-publish and re-deploy.

## Troubleshooting and Rollback
Publish failures:
- verify target repo/branch/root config
- verify artifact approval status and readiness reasons
- check path-boundary rejections in publish warnings/history
- if duplicate publish is reported, either select a different approved artifact or change target config intentionally

Deploy failures:
- verify publish completed for selected artifact
- verify deploy target enabled/workflow/ref values
- inspect deploy history inputs and workflow execution status
- if duplicate deploy is reported, verify whether the prior deploy request already covers the same artifact+target+inputs

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

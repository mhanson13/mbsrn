# GCP Logging Runbook

## Time Filtering Behavior

The admin `GCP Logs Query` tool always sends an explicit time constraint to Cloud Logging:

- If `Start Time` / `End Time` are both blank, the backend applies a visible default window of the last 24 hours.
- If `Start Time` is provided, the query includes `timestamp >= "<start_time>"`.
- If `End Time` is provided, the query includes `timestamp <= "<end_time>"`.
- If both are provided, both constraints are applied.

The backend response includes `effective_filter`, and the UI displays it so operators can confirm the exact filter sent to `entries.list`.
When either `Start Time` or `End Time` is supplied, `default_time_range_applied` is `false` and the default 24-hour window is not used.

## Override The Default Window

To search outside the default 24-hour window:

1. Set `Start Time (UTC, optional)` and/or `End Time (UTC, optional)` in ISO-8601 format.
2. Run the query.
3. Confirm the rendered `Effective Filter` line includes your timestamp bounds.

Example UTC values:

- `2026-03-20T00:00:00Z`
- `2026-03-27T12:30:00Z`

## Debug Missing Logs

If expected logs are missing:

1. Check the UI `Effective Filter` value first.
2. Verify whether the default 24-hour window was applied.
3. Expand the time range explicitly (for example, set `Start Time` to 7 days ago).
4. Re-run and confirm updated timestamp clauses are reflected in `effective_filter`.

## Guardrail

Time constraints must be operator-visible. Hidden timestamp filtering should never be added.

## AI Response-Contract Event Queries

For post-provider quality-gate troubleshooting, query these structured events:

- Migration draft artifacts:
  - `jsonPayload.event="seo_migration_draft_contract_evaluation"`
- Competitor generation:
  - `jsonPayload.event="competitor_response_contract_evaluation"`
- Recommendation narratives:
  - `jsonPayload.event="seo_recommendation_response_contract_evaluation"`

Useful fields:
- `evaluation_status` (`accepted`, `accepted_with_warnings`, `salvaged`, `rejected`)
- `evaluation_score`
- `reason_codes`
- `warning_codes`
- scoped identifiers (`business_id`, `site_id`, run/workspace ids)

## Migration Provider Compatibility Queries

For migration draft preflight compatibility troubleshooting:

- `jsonPayload.event="seo_migration_provider_compatibility_evaluation"`
- `jsonPayload.event="seo_migration_draft_provider_request_contract_guard"` (runtime request-fingerprint guard)

Useful fields:
- `supported`
- `reason_code`
- `decision`
- `provider_name`
- `model`
- `endpoint_path`
- `execution_mode`
- `web_search_enabled`
- `degraded_mode`
- `response_format_mode`
- `request_body_mode`
- request fingerprint fields:
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
  - `request_fingerprint_has_null_optional_fields`
  - `request_fingerprint_has_extra_request_options`
  - `request_fingerprint_contains_tools`
  - `request_fingerprint_contains_response_format_legacy`
  - `request_fingerprint_contains_messages_legacy`
  - `request_fingerprint_schema_object_nodes_total`
  - `request_fingerprint_schema_object_nodes_non_false_additional_properties`
  - `request_fingerprint_schema_object_nodes_missing_required`
- scoped identifiers (`business_id`, `site_id`, `workspace_id`)

Interpretation:
- `supported=false` with `decision=blocked_local_preflight` means migration draft generation was blocked locally before outbound provider invocation.
- `reason_code` identifies the stable compatibility failure class (for example `unsupported_model_configuration`).
- inspect `model`, `endpoint_path`, `execution_mode`, `response_format_mode`, and `request_body_mode` together as the effective request-shape key.
- for summary payload troubleshooting, also inspect `context_summary.migration_diagnostics.draft_provider_compatibility_admin_summary` for sanitized matrix decision detail.
- model resolution precedence for compatibility checks is: explicit/requested -> business admin default (`default_ai_model`) -> env fallback (`AI_MODEL_NAME`) -> provider fallback.

Current migration request-shape examples:
- supported: `gpt-5.1*` + `/responses` + `full` + `json_schema` + `responses_text_format_json_schema`
- blocked locally: `gpt-5.1*` + `/chat/completions` + `full` + `json_schema` + `chat_json_schema`
- blocked locally: fallback chat/json_schema shapes unless explicitly allowlisted
- blocked locally: `/responses` + `responses_text_format_json_schema` when request `input` is array/object instead of string
- contract drift indicator: `request_fingerprint_schema_object_nodes_non_false_additional_properties>0` indicates schema strictness drift versus the known-good migration `/responses` contract.
- contract drift indicator: `request_fingerprint_input_mode!=string` indicates invalid migration `/responses` input transport shape.
- contract drift indicator: `request_fingerprint_schema_object_nodes_missing_required>0` indicates strict-schema object required coverage drift.
- contract drift indicator: `request_fingerprint_has_extra_request_options=true` indicates unexpected top-level request options were added.
- contract drift indicator: `request_fingerprint_has_null_optional_fields=true` indicates null-valued request fields leaked into payload.
- runtime guard event interpretation:
  - `seo_migration_draft_provider_request_contract_guard` with `blocking_codes=[]` and non-empty `warning_codes` means request was allowed with warnings.
  - non-empty `blocking_codes` means the request was blocked locally before provider invocation.

## Local Block vs Remote Rejection

Use these events together:

- Local compatibility block:
  - `jsonPayload.event="seo_migration_provider_compatibility_evaluation"`
  - `jsonPayload.supported=false`
  - `jsonPayload.decision="blocked_local_preflight"`
- Remote provider rejection:
  - `jsonPayload.event="seo_migration_draft_provider_request_failure"`
  - `jsonPayload.failure_source="remote_provider"`
  - inspect `jsonPayload.http_status` and `jsonPayload.failure_reason`

For API/UI correlation, also inspect migration summary payload fields:
- `context_summary.ai_execution.model_requested`
- `context_summary.ai_execution.model_resolved`
- `context_summary.ai_execution.model_used`
- `context_summary.ai_execution.endpoint_path`
- `context_summary.ai_execution.request_body_mode`
- `context_summary.ai_execution.compatibility_decision`
- `context_summary.ai_execution.request_contract_status`
- `context_summary.ai_execution.provider_execution_status`
- `context_summary.ai_execution.artifact_status`
- `context_summary.ai_execution.artifact_result`
- `context_summary.ai_execution.duration_ms`
- `context_summary.ai_execution.timeout_seconds`
- `context_summary.ai_execution.timeout_source`
- `context_summary.migration_diagnostics.last_draft_failure_source`

Operator wording mapping:
- `last_draft_failure_source=local_preflight` -> "Blocked before provider call"
- `last_draft_failure_source=remote_provider` -> "AI provider rejected request"

Success-path validation quick check:
1. Confirm compatibility evaluation log shows `supported=true` and `decision=allowed`.
2. Confirm provider request lifecycle logs include start and complete events (no failure event for the same `draft_run_id`).
3. Confirm summary `context_summary.ai_execution` reports:
   - `request_contract_status=accepted`
   - `provider_execution_status=accepted`
   - `artifact_result=succeeded`
   - non-null `duration_ms`

## Migration Timeout Troubleshooting

To isolate migration draft timeout failures, query:

- `jsonPayload.event="seo_migration_draft_generation" jsonPayload.failure_reason="timeout"`
- `jsonPayload.event="seo_migration_draft_provider_request_failure" jsonPayload.failure_reason="timeout"`

Useful fields:
- `timeout_seconds`
- `timeout_source`
- `failure_reason`
- `failure_source`
- `retryable`
- scoped identifiers (`business_id`, `site_id`, `workspace_id`, `draft_run_id`)

Interpretation:
- `failure_reason=timeout` with `failure_source=remote_provider` means the provider call exceeded the configured timeout.
- timeout failures currently retain `failure_category=config_missing` for migration draft error-contract compatibility.
- compare `timeout_seconds` and `timeout_source` to verify whether admin override or default timeout was active.
- migration runtime enforces a safe timeout floor of `60` seconds; values below floor fall back to default `120`.
- if timeout settings are sane but remote `unsupported_configuration` occurs quickly, compare request fingerprint fields first; contract drift is usually visible in top-level/text-format/schema fingerprint fields before model/latency tuning.
- for field-by-field drift checks, use the migration provider redacted payload snapshot helper in tests/debug tooling and compare against the known-good curl contract shape (input text remains redacted by design).

## Migration State Coherence Quick Check

When validating operator-visible migration state from backend payloads:

1. Check `context_summary.draft_generation_state.status` for top-level state.
2. Confirm it aligns with:
   - `context_summary.draft_generation_readiness`
   - `context_summary.draft_provider_compatibility`
   - `context_summary.migration_diagnostics.last_draft_generation_status`
3. Expected precedence:
   - workspace blockers
   - provider compatibility blockers
   - latest persisted generation outcome (`failed` / `partial` / `completed`)

## Migration Deploy Dispatch Troubleshooting

When migration deploy fails after publish, query these structured events:

- `jsonPayload.event="seo_migration_control_plane_action"` with `jsonPayload.action="deploy"`
- `jsonPayload.event="seo_migration_deploy_dispatch_failed"`
- `jsonPayload.event="seo_migration_deploy_workflow_resolution"` (emitted when deploy uses publish-history workflow identity)
- `jsonPayload.event="seo_migration_target_readiness_check"` (repo/ref/workflow dispatch preflight)
- `jsonPayload.event="seo_migration_workflow_provisioning"` (publish-time workflow bootstrap/verification)
- `jsonPayload.event="seo_migration_deploy_dispatch_accepted"`
- `jsonPayload.event="seo_migration_workflow_run_lookup_attempted"`
- `jsonPayload.event="seo_migration_workflow_run_result_captured"`
- `jsonPayload.event="seo_migration_workflow_output_url_captured"`
- `jsonPayload.event="seo_migration_deploy_status_refresh_requested"`
- `jsonPayload.event="seo_migration_workflow_run_refresh_lookup_attempted"`
- `jsonPayload.event="seo_migration_workflow_run_refresh_result_captured"`
- `jsonPayload.event="seo_migration_workflow_output_url_captured_via_refresh"`
- `jsonPayload.event="seo_migration_deploy_status_refresh_completed"`
- `jsonPayload.event="seo_migration_deploy_status_refresh_no_change"`

Stage model to follow during triage:
1. `artifact`
2. `publish_target`
3. `workflow_identity`
4. `dispatch_service_availability`
5. `workflow_dispatch`
6. `workflow_run_evidence`
7. `resolved_live_url_evidence`

Key non-secret fields:

- `target.resolved_workflow_source` (`publish_history_workflow`, `workspace_config_workflow`, `default_workflow`)
- `failure_reason_code` / `target.failure_reason_code`
- `failure_stage` (`repo_lookup`, `ref_lookup`, `workflow_lookup`, `workflow_dispatch`)
- `failure_remediation_hint` (deterministic advisory summary derived from failure reason/stage evidence)
- `workflow_id`, optional `workflow_path`, `ref`, `repo_owner`, `repo_name`
- `workflow_identifier_requested`, `workflow_identifier_used`
- `workflow_identifier_type_requested`, `workflow_identifier_type_used`
- `workflow_dispatch_resolution_source`, `workflow_file_path`, `workflow_name`
- `actual_dispatch_identifier_sent`, `actual_dispatch_identifier_type_sent`
- `workflow_conformance_checked`, `workflow_conformance_status`
- `workflow_conformance_reasons`, `workflow_conformance_evidence_summary`
- `workflow_run_id`, `workflow_run_status`, `workflow_run_conclusion`
- `resolved_live_url`, `url_source`, `url_source_detail`
- readiness check fields:
  - `requested_ref`, `resolved_ref`, `ref_source`
  - `repo_exists`, `ref_exists`, `workflow_exists`, `workflow_dispatch_ready`
  - `workflow_dispatch_supported`, `workflow_trigger_types`, `dispatch_identifier_type`
  - `workflow_identifier_requested`, `workflow_identifier_used`
  - `workflow_identifier_type_requested`, `workflow_identifier_type_used`
  - `workflow_dispatch_resolution_source`, `workflow_file_path`, `workflow_name`
  - `dispatch_service_availability`, `dispatch_service_reason_code`
  - `deploy_trace_id`
  - `remediation_mode`
- workflow provisioning fields:
  - `status` (`created`, `already_exists`, `verified`, `failed`)
  - `remediation_mode` (`bootstrap`, `already_present`, `duplicate_publish_repair`)
  - `workflow_id`, `workflow_path`, `ref`, `repo_owner`, `repo_name`
  - optional `error_code` / `error_message` on failed provisioning

Workflow lookup failure quick triage:
- when `failure_stage=workflow_lookup`, compare:
  - `failure_reason_code`
  - `dispatch_service_reason_code`
  - `workflow_identifier_requested`
  - `workflow_identifier_used`
  - `workflow_file_path`
  - `workflow_exists`
- common interpretation:
  - `failure_reason_code=workflow_not_dispatchable` with `dispatch_service_reason_code=target_configuration_invalid` means the selected workflow identity resolved, but the workflow is not deploy-dispatchable for the managed path.
  - `workflow_exists=false` means lookup failed for the selected identifier/path on the target ref.
  - `workflow_identifier_requested=deploy-www-prod.yml` while a site-specific workflow should be used indicates workflow-selection/target-mapping drift that should be corrected before retry.
  - `failure_remediation_hint` is advisory only and deterministic; it summarizes existing staged evidence and does not represent an additional runtime probe.

Reason-code guidance:

- `repo_not_found`: repository lookup failed for owner/repo.
- `workflow_not_found`: repository exists, but requested workflow id/path was not found.
- `branch_not_found_or_ref_invalid`: dispatch ref is invalid or missing in target repo.
- `workflow_not_dispatchable`: workflow exists but is not in a dispatch-ready state for target ref.
- `workflow_dispatch_not_supported`: workflow exists but does not expose `workflow_dispatch`.
- `token_not_authorized`: runtime token lacks required repository/workflow permissions.
- `workflow_provisioning_failed`: publish could not verify workflow file presence after provisioning attempt.

Workflow conformance status guidance:
- `conformant`: workflow content includes `workflow_dispatch` and managed deploy contract markers.
- `workflow_dispatch_missing`: workflow content was readable but missing `workflow_dispatch`.
- `workflow_placeholder_detected`: workflow appears to be placeholder/example content.
- `workflow_contract_incomplete`: workflow is dispatchable but missing required managed deploy contract markers.
- `workflow_unreadable`: workflow file existed but content could not be decoded/read safely for conformance checks.
- `workflow_missing`: workflow file payload was unavailable during conformance evaluation.

Dispatch-stage interpretation note:
- if target-readiness preflight already logged `repo_exists=true`, `ref_exists=true`, `workflow_exists=true`, and a later `workflow_dispatch` call fails, prefer workflow dispatchability troubleshooting before assuming branch/ref drift.
- if `workflow_dispatch_supported=true` but `dispatch_service_availability=false`, treat this as service/function readiness unavailability (not workflow identity/trigger mismatch).
- if `workflow_dispatch_supported=true` and `dispatch_service_availability=true`, this still only proves control-plane dispatch readiness; it does not by itself prove that target-repo GitHub Actions has all required GKE deploy prerequisites (workflow logic/secrets/permissions/cluster access).

### Production Verification Checklist (TnM Fire)

Use this sequence for one bounded production deploy validation:

1. In the migration workspace, choose the latest published artifact for `mhanson13/tnmfire` (`ref=main`).
2. Submit deploy and capture `Deploy trace ID` from the Deploy Readiness traceability grid.
3. Query deploy control-plane events using trace id correlation:
   - `jsonPayload.event="seo_migration_control_plane_action"`
   - `jsonPayload.action="deploy"`
   - `jsonPayload.target.deploy_trace_id="<trace-id>"`
4. Confirm staged evidence progression in logs:
   - readiness/preflight fields (`workflow_identifier`, `workflow_identifier_requested`, `workflow_identifier_used`, `workflow_dispatch_supported`, `dispatch_service_availability`)
   - dispatch attempt fields (`dispatch_attempted=true`, `dispatch_result_stage`)
   - run evidence fields (`workflow_run_id`, `workflow_run_status`, `workflow_run_conclusion`) when available
   - identifier-resolution fields (`workflow_dispatch_resolution_source`, `workflow_identifier_type_used`) show selected/provenance workflow identity.
   - outbound dispatch fields (`actual_dispatch_identifier_sent`, `actual_dispatch_identifier_type_sent`) show the exact identifier value/type sent to the GitHub dispatch API.
   - conformance fields (`workflow_conformance_status`, `workflow_conformance_reasons`) indicate whether selected workflow content is deploy-capable for managed migration deploy.
5. If UI shows `Dispatch was accepted, but no workflow run evidence is available yet`, wait for eventual consistency and run **Refresh deploy status**.
6. Re-query refresh events by trace id:
   - `jsonPayload.event="seo_migration_deploy_status_refresh_requested"`
   - `jsonPayload.event="seo_migration_workflow_run_refresh_result_captured"`
   - `jsonPayload.event="seo_migration_deploy_status_refresh_completed"`
7. Confirm URL evidence contract:
   - `expected_publish_url` may be present as guidance
   - `resolved_live_url` is only confirmed when explicit evidence is present with `url_source=workflow_output` or `url_source=deploy_result`
8. If deploy still fails, route by `failure_stage` + `failure_reason_code` without guessing at hidden causes.

### TnM Fire Outcome Decision Tree

Use the latest `deploy_trace_id` from the workspace traceability grid and evaluate outcomes in this order:

1. **Run created successfully**
   - Signals:
     - `dispatch_attempted=true`
     - `workflow_run_id` is present
   - Interpretation:
     - Dispatch succeeded and run evidence exists.
   - Next check:
     - Wait for completion evidence (`workflow_run_status`, `workflow_run_conclusion`) and optional `resolved_live_url`.

2. **Dispatch attempted but rejected**
   - Signals:
     - `dispatch_attempted=true`
     - deploy action status is failed
     - `failure_stage=workflow_dispatch`
   - Interpretation:
     - Target preflight passed but GitHub dispatch failed.
     - Compare selected vs sent identifiers:
       - `workflow_identifier_used` can remain full workflow path provenance (for example `.github/workflows/deploy-tnmfire-www-prod.yml`)
       - `actual_dispatch_identifier_sent` is the normalized identifier sent to GitHub (for example `deploy-tnmfire-www-prod.yml`)
   - Route by reason code:
     - `workflow_not_dispatchable`
     - `workflow_dispatch_not_supported`
     - `branch_not_found_or_ref_invalid`
     - `token_not_authorized`

3. **Dispatch accepted but no run discovered yet**
   - Signals:
     - `dispatch_attempted=true`
     - deploy action completed
     - `workflow_run_id` absent
     - workspace hint: `Dispatch was accepted, but no workflow run evidence is available yet`
   - Interpretation:
     - Eventual-consistency window; run lookup has not found evidence yet.
   - Action:
     - Wait briefly, then run **Refresh deploy status** and re-check `workflow_run_id/status/conclusion`.

4. **Run discovered but no confirmed live URL yet**
   - Signals:
     - `workflow_run_id` present
     - `resolved_live_url` absent
   - Interpretation:
     - Run evidence exists, but no explicit URL evidence has been captured yet.
   - Contract reminder:
     - `expected_publish_url` is guidance only.
   - Confirmed live URL appears only when explicit evidence sets `resolved_live_url` with `url_source=workflow_output` or `url_source=deploy_result`.

5. **Dispatch succeeds but deployment still does not reach GKE**
   - Signals:
     - `dispatch_attempted=true`
     - workflow run exists (`workflow_run_id` present)
     - repo/ref/workflow preflight passed
     - no successful deployment-side evidence (and/or workflow run fails downstream)
   - Interpretation:
     - Control plane is ready, but target-repo GitHub Actions runtime prerequisites are incomplete or failing.
   - Verify in target repository/workflow:
     - required workflow implementation is present (not placeholder-only)
     - required GitHub Actions secrets/variables exist
     - GCP/GKE auth and cluster permissions are valid for the workflow identity

Live URL confirmation guidance:

- `url_source=deploy_result` or `url_source=workflow_output` indicates confirmed live URL evidence from deploy/runtime metadata.
- `url_source=deterministic_target_config` remains expected guidance only and should not be treated as confirmed live state.
- deploy request inputs (for example `site_url`) are not confirmed-live evidence.
- workflow-output URL confirmation requires run-correlated completion metadata (for example deployment status `environment_url` linked to the dispatched workflow run id).
- refresh no-op reasons:
  - `workflow_run_metadata_missing`: deploy record exists but run id/status correlation is not available yet.
  - `deploy_record_missing`: no non-dry-run deploy history entry exists for the selected artifact.
  - `deploy_target_metadata_missing`: deploy target repo/workflow/ref metadata is incomplete for refresh lookup.

Local-only validation note:

- For optional local verification against GitHub APIs, use `MIGRATION_GITHUB_TOKEN` with a local test token value in local environment only.
- Never print/log/commit token values. Production runtime should continue using infrastructure-managed `MIGRATION_GITHUB_TOKEN` wiring.

## Local Live Validation (Migration /responses)

Use this local-only harness to validate the end-to-end migration request contract against live provider behavior:

1. Ensure `.env` (or process env) contains `AI_API_KEY`.
2. Run from repo root:
   - `PYTHONPATH=. python scripts/live_validate_seo_migration_responses.py`
   - PowerShell:
     - `$env:PYTHONPATH='.'; python scripts/live_validate_seo_migration_responses.py`
3. Inspect safe JSON output only (no raw prompts/schemas/secrets).

Expected success signals:
- `status=succeeded`
- `execution.compatibility_decision=allowed`
- `execution.provider_execution_status=accepted`
- `execution.artifact_result=succeeded`
- `known_good_contract_diff=[]`

If failure occurs:
- compare `request_fingerprint` fields and `redacted_request_snapshot_overview` against known-good contract expectations.
- prioritize concrete differences in:
  - `top_level_keys`
  - `text_top_level_keys`
  - `text_format_keys`
  - `input_mode`
  - `has_extra_request_options`
  - `has_null_optional_fields`
  - `schema_object_nodes_non_false_additional_properties`
  - `schema_object_nodes_missing_required`

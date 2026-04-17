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
- scoped identifiers (`business_id`, `site_id`, run/workspace ids)

Draft contract interpretation:
- `missing_required_artifact_files` means normalized artifact output did not contain required files (currently `index.html`).
- `insufficient_content_density` means normalized files were present but failed minimum content density checks.
- high `dropped_item_count` plus populated `parser_rejection_reason_counts` usually indicates parser/normalizer rejection (path/content/safety rules), not provider transport rejection.
- `retry_likelihood=unlikely_without_contract_fix` means blind retries are typically low-value until contract/parser alignment is fixed.
- `retry_likelihood=likely_useful` means retry may recover transient generation gaps.

Quick triage examples:
- parser/path normalization issue:
  - pattern: `normalized_item_count=0`, high `dropped_item_count`, non-empty `parser_rejection_reason_counts`
  - action: fix contract/parser/path assumptions first, then retry.
- real missing required files:
  - pattern: `missing_required_artifact_files=["index.html"]`
  - action: fix prompt/contract alignment for required file presence before retrying.
- density-only weakness:
  - pattern: required files present, `content_density_failures_by_file` populated
  - action: improve draft content depth; retry can be conditionally useful.

## Shared AI Reliability Telemetry (Migration / Recommendations / Competitors)

All synchronous AI paths now emit a normalized reliability envelope. Use this to distinguish provider transport failures from local validation/configuration failures consistently across feature areas.

Key fields to inspect (event-specific availability):
- `normalized_failure_category`
- `normalized_failure_reason`
- `normalized_failure_source`
- `normalized_retryable`
- `attempt_count` (or feature-specific attempt count field)
- calibration event names:
  - `ai_execution_preflight`
  - `ai_execution_precall_rejected`
  - `ai_execution_retry_suppressed`
  - `ai_execution_completed`
  - `ai_execution_failed`
  - `seo_migration_draft_request_budget`
  - `recommendation_narrative_request_budget`
  - `competitor_request_budget`
- request-budget metadata:
  - `request_fingerprint_context_budget_initial_size_chars`
  - `request_fingerprint_context_budget_final_size_chars`
  - `request_fingerprint_context_budget_dropped_optional_blocks`
  - `request_fingerprint_context_budget_overflow`
  - `original_input_size`
  - `final_input_size`
  - `trimmed_bytes`
  - `trimming_pass_count`
  - `difficulty_score`
  - `budget_outcome` (`precall_rejected` | `provider_submission`)

Normalized category meanings:
- `remote_timeout`: provider timeout boundary
- `remote_unavailable`: transport/unavailable upstream boundary
- `remote_rate_limited`: provider rate-limit boundary
- `remote_invalid_response`: provider returned malformed/invalid payload
- `local_validation_failure`: response failed local schema/contract validation
- `configuration_missing`: required local/provider configuration is missing
- `configuration_invalid`: local/provider authentication/configuration is invalid

Operator/admin guidance:
- retry only when the normalized category/reason indicates retryable remote conditions.
- avoid blind retries for `configuration_*` and `local_validation_failure` until configuration or contract issues are corrected.

Timeout vs request-too-large interpretation:
- `normalized_failure_category=remote_timeout` + `normalized_failure_reason=provider_timeout`
  - provider timed out under normal budget assumptions
  - retry can be useful when marked retryable.
- `normalized_failure_reason=request_too_large_or_complex`
  - timeout retry was suppressed because the payload size/complexity did not change
  - fix by reducing optional context (adapter budget trimming) before retrying.
- `normalized_failure_category=local_validation_failure` + `normalized_failure_reason=request_too_large` (or `request_too_large_or_complex`)
  - request was rejected before provider call due to synchronous budget guardrails
  - retry is not useful until request size/shape is reduced.

Calibration queries (safe counters):
- "How often did each workflow trim?"
  - filter on `event in {"seo_migration_draft_request_budget","recommendation_narrative_request_budget","competitor_request_budget"}` and `trimming_pass_count>0`
- "How often did trimming still submit to provider?"
  - same events with `budget_outcome="provider_submission"` and `trimming_pass_count>0`
- "How often were requests rejected pre-call?"
  - `event="ai_execution_precall_rejected"` OR adapter budget events with `budget_outcome="precall_rejected"`
- "How often did timeout retries get suppressed?"
  - `event="ai_execution_retry_suppressed"` and inspect `reason=request_too_large_or_complex`

Production tuning filters by workflow (`feature_area`):
- migration drafts:
  - shared core events with `feature_area="migration_draft"`
  - adapter budget events: `event="seo_migration_draft_request_budget"`
- recommendation narratives:
  - shared core events with `feature_area="recommendation_ai"`
  - adapter budget events: `event="recommendation_narrative_request_budget"`
- competitor AI:
  - shared core events with `feature_area="competitor_ai"`
  - adapter budget events: `event="competitor_request_budget"`

Concrete monitoring slices:
- pre-call rejection rate by workflow:
  - `event="ai_execution_precall_rejected"` grouped by `feature_area`
- retry suppression rate by workflow:
  - `event="ai_execution_retry_suppressed"` grouped by `feature_area`
- budget outcome distribution by workflow:
  - adapter budget events grouped by `event` + `budget_outcome`
- failure breakdown by workflow:
  - shared failure events grouped by `feature_area`, `normalized_failure_category`, `normalized_failure_reason`
- difficulty/input distribution by workflow:
  - summarize `difficulty_bucket` and `input_size_bucket` from surfaced diagnostics payloads and shared execution events

Tuning-first checklist (maintainer):
1. Watch these fields first in production: `budget_outcome`, `retry_suppressed`, `failure_category`, `failure_reason`, `difficulty_bucket`, `input_size_bucket`.
2. Tune adapter budgets when:
   - pre-call rejection and retry-suppressed rates are high for one workflow, and
   - failures cluster around `request_too_large` / `request_too_large_or_complex`.
3. Improve workflow-specific prompt/context quality when:
   - failures are dominated by `remote_invalid_response` or `local_validation_failure` with low trim pressure.
4. Do not tune from single failures; use at least several deploy/draft/narrative cycles of telemetry before changing budget constants.

Trim-order tuning guidance:
- check `dropped_optional_blocks` over time per feature area before changing budgets.
- do not promote optional context blocks to required without adapter test updates proving required-content safety and bounded request size.

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
- `jsonPayload.event="seo_migration_publish_workflow_resolution"` (publish-time resolved workflow candidate used for provisioning)
- `jsonPayload.event="seo_migration_publish_workflow_file_inspected"` (publish-time managed/custom classification for the resolved workflow file)
- `jsonPayload.event="seo_migration_publish_workflow_file_upsert_decision"` (publish-time write/preserve decision for the resolved workflow file)
- `jsonPayload.event="seo_migration_deploy_workflow_readiness_source"` (deploy-time conformance classification for the workflow file being validated)
- `jsonPayload.event="seo_migration_workflow_candidate_alignment"` (explicit publish-candidate vs readiness-candidate id/path/ref match signal)
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
- duplicate-blocker context (when `failure_category=duplicate_request`):
  - `target.blocking_post_dispatch_state`
  - `target.blocking_dispatch_result_stage`
  - `target.blocking_workflow_run_id`
  - `target.blocking_workflow_run_status`
  - `target.blocking_workflow_run_conclusion`
  - `target.blocking_deploy_trace_id`
  - `target.blocking_timestamp`
  - `target.blocking_dispatched_at`
  - `target.blocking_refreshed_at`
- `workflow_id`, optional `workflow_path`, `ref`, `repo_owner`, `repo_name`
- `workflow_identifier_requested`, `workflow_identifier_used`
- `workflow_identifier_type_requested`, `workflow_identifier_type_used`
- `workflow_dispatch_resolution_source`, `workflow_file_path`, `workflow_name`
- `actual_dispatch_identifier_sent`, `actual_dispatch_identifier_type_sent`
- `dispatch_ref_sent`
- `workflow_inputs_configured_keys`, `workflow_inputs_sent_keys`
- `workflow_conformance_checked`, `workflow_conformance_status`
- `workflow_conformance_reasons`, `workflow_conformance_evidence_summary`
- namespace isolation/readiness fields:
  - `kubernetes_namespace`
  - `namespace_source`
  - `namespace_model_status`
  - `workflow_namespace_aligned`
  - `manifest_namespace_aligned`
  - `managed_resource_quota_expected`
  - `managed_resource_quota_present`
  - `managed_limit_range_expected`
  - `managed_limit_range_present`
  - `managed_network_policy_expected`
  - `managed_network_policy_present`
  - `managed_namespace_policies_aligned`
- `workflow_run_lookup_attempted`, `workflow_run_found`, `workflow_job_failure_detected`
- `post_dispatch_state`
- `post_conformance_stage`, `post_conformance_reason_text`
- `expected_workflow_outputs`
- `deploy_evidence_contract_status`, `deploy_evidence_contract_reasons`
- `workflow_contract_advisory`
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
  - `kubernetes_namespace`, `namespace_source`
  - `namespace_model_status`, `workflow_namespace_aligned`, `manifest_namespace_aligned`
  - `deploy_trace_id`
  - `remediation_mode`
- workflow provisioning fields:
  - `status` (`created`, `already_exists`, `verified`, `failed`)
  - `remediation_mode` (`bootstrap`, `already_present`, `duplicate_publish_repair`)
  - `workflow_remediation_attempted` (publish attempted managed workflow verification/upgrade even when artifact write was duplicate-skipped)
  - `workflow_remediation_outcome`
    - `remediation_upgraded_managed_placeholder`: managed scaffold was updated to current production workflow contract
    - `remediation_already_current`: managed workflow already current; no update needed
    - `remediation_preserved_custom`: custom/non-managed workflow preserved intentionally
    - `remediation_write_failed`: publish remediation attempted but write/provision failed
    - `remediation_not_attempted`: remediation path not invoked on that publish action
  - `workflow_id`, `workflow_path`, `ref`, `repo_owner`, `repo_name`
  - optional `error_code` / `error_message` on failed provisioning
  - managed placeholder workflow signatures are eligible for publish-time upgrade to the current production template
  - upgrade signatures include scaffold patterns such as `Placeholder deploy` + `Deploy step not yet implemented`, `provisioned in mode`, or `customize before production rollout`
  - unknown custom/non-managed workflows are preserved and surfaced via conformance diagnostics rather than overwritten
  - `managed_workflow_outcome` emitted on upsert decision:
    - `managed_workflow_created`
    - `managed_workflow_upgraded`
    - `managed_workflow_already_current`
    - `managed_workflow_preserved_custom`
  - publish/readiness path/ref alignment check:
    - compare `seo_migration_publish_workflow_resolution` (`workflow_id`, `workflow_path`, `ref`, `resolved_workflow_source`)
    - with `seo_migration_deploy_workflow_readiness_source` (`workflow_id`, `workflow_path`, `requested_ref`)
    - and `seo_migration_target_readiness_check` (`workflow_identifier_requested`, `workflow_identifier_used`, `requested_ref`, `resolved_ref`)
    - and confirm `seo_migration_workflow_candidate_alignment.workflow_candidate_alignment_exact=true`

Managed workflow contract quick check:
- `workflow_dispatch` trigger present
- production deploy markers present (`google-github-actions/auth`, `google-github-actions/get-gke-credentials`, `kubectl apply`, `kubectl rollout`)
- explicit evidence outputs emitted (`resolved_live_url`, `live_url`, `deployed_url`)
- if missing, deploy remains blocked as `workflow_not_production_ready`

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
- `workflow_not_production_ready`: workflow exists and is dispatchable, but is still scaffold/placeholder content and is blocked before dispatch.
- `token_not_authorized`: runtime token lacks required repository/workflow permissions.
- `workflow_provisioning_failed`: publish could not verify workflow file presence after provisioning attempt.

Workflow conformance status guidance:
- `conformant`: workflow content includes `workflow_dispatch` and managed deploy contract markers.
- `workflow_dispatch_missing`: workflow content was readable but missing `workflow_dispatch`.
- `workflow_placeholder_detected`: workflow appears to be placeholder/example content.
- `workflow_contract_incomplete`: workflow is dispatchable but missing required managed deploy contract markers.
- `workflow_unreadable`: workflow file existed but content could not be decoded/read safely for conformance checks.
- `workflow_missing`: workflow file payload was unavailable during conformance evaluation.

Dispatch-support interpretation:
- `workflow_exists=true` with `workflow_dispatch_supported=false` means the selected workflow file resolved, but trigger-level manual dispatch support could not be confirmed (for example `workflow_dispatch` missing).
- `workflow_conformance_status=workflow_placeholder_detected` is treated as a deploy blocker (`workflow_not_production_ready`) for scaffold workflows.
- `workflow_contract_incomplete` remains advisory for managed-deploy quality and is surfaced separately from trigger-level dispatch support.
- Dispatch payload contract is bounded to explicitly configured deploy inputs (`deploy_config.inputs`) to avoid GitHub `workflow_dispatch` input-contract rejections from undeclared implicit fields.

Post-dispatch state interpretation:
- `post_dispatch_state=dispatch_not_attempted` means readiness/preflight blocked dispatch.
- `post_dispatch_state=dispatch_accepted_no_run` means dispatch transport accepted but no workflow run evidence is available yet.
- `post_dispatch_state=dispatch_unverified_no_run` means refresh rechecked dispatch metadata and still found no workflow run evidence.
- `post_dispatch_state=workflow_run_pending` or `workflow_run_in_progress` means run evidence exists and execution is not terminal.
- `post_dispatch_state=workflow_run_failed` means run evidence exists with non-success terminal conclusion.
- `post_dispatch_state=workflow_run_succeeded_without_live_url` means run completed successfully but no explicit live URL evidence has been captured.
- `post_dispatch_state=workflow_run_succeeded_with_live_url` means explicit live URL evidence is present.

Post-conformance stage interpretation (`post_conformance_stage`):
- `workflow_conformance_failed`: conformance checks failed before dispatch.
- `workflow_dispatch_blocked`: dispatch did not proceed past readiness/preflight checks.
- `workflow_dispatch_attempted`: dispatch attempt was issued and run evidence is not yet confirmed.
- `workflow_dispatch_failed`: GitHub dispatch API rejected the request.
- `workflow_dispatch_succeeded_waiting_for_run`: dispatch accepted, run evidence pending/not terminal yet.
- `workflow_run_failed`: run reached terminal failure outside rollout verification.
- `rollout_failed`: run reached rollout verification but rollout failed/timed out.
- `live_url_evidence_missing`: run completed, but no explicit `resolved_live_url` evidence.
- `deploy_succeeded`: explicit live URL evidence captured.

Use `post_conformance_reason_text` as the concise operator-safe explanation for the current stage.

Duplicate deploy blocking interpretation:
- `failure_category=duplicate_request` on deploy means a prior active in-flight deploy attempt for the same artifact+target+inputs was detected.
- this is intentionally narrow concurrency protection; it is not a blanket "history exists" block.
- retries are expected to be allowed once prior attempts become terminal/stale.
- stale no-run evaluation is deterministic and uses this timestamp precedence:
  - `refreshed_at` (if present)
  - else `dispatched_at`
  - else `occurred_at`
  - else `timestamp`
  - run-backed active blockers (`workflow_run_pending`, `workflow_run_in_progress`, `workflow_run_observed`, and active run statuses) use a 30-minute stale window
  - with a 2-minute stale threshold for unverified dispatch blockers (`dispatch_accepted_no_run` / `dispatch_unverified_no_run`)
- quick triage:
  - use `target.blocking_post_dispatch_state` and blocker run fields to confirm whether the prior attempt is still active.
  - use `target.blocking_stale_reference_field`, `target.blocking_stale_reference_at`, `target.blocking_stale_age_seconds`, `target.blocking_stale_threshold_seconds`, `target.blocking_stale_evaluated`, `target.blocking_stale_is_stale`, and `target.blocking_treated_as_stale` to validate stale classification.
  - if blocker state is `dispatch_accepted_no_run` or `dispatch_unverified_no_run`, run **Refresh Deploy Status** and retry after status transitions to terminal/stale.
  - if blocker state is run-backed (`workflow_run_pending` / `workflow_run_in_progress` / `workflow_run_observed`) and stale fields show old activity with no recent refresh evidence, retry is expected to become available.
  - observe unverified-dispatch reconciliation events:
    - `dispatch_attempted_without_run`
    - `no_run_observed_after_refresh`
    - `downgrade_to_stale_unverified_dispatch`
  - observe stale active-blocker reconciliation event:
    - `downgrade_to_stale_active_deploy_blocker`

Deploy evidence contract interpretation:
- `deploy_evidence_contract_status=confirmed_live_evidence` means explicit deploy evidence set `resolved_live_url`.
- `workflow_placeholder_advisory` means selected workflow appears placeholder/non-deploying.
- `workflow_contract_incomplete_advisory` means workflow is dispatchable but missing managed contract markers for explicit evidence capture.
- `workflow_succeeded_without_explicit_evidence` means run succeeded but did not emit expected explicit URL output evidence.
- `workflow_run_failed_without_explicit_evidence` means run failed before explicit evidence capture.
- `evidence_pending` means dispatch/run evidence is still pending.
- `evidence_not_attempted` means dispatch was blocked/not attempted.
- `expected_workflow_outputs` lists currently supported explicit workflow output keys (`resolved_live_url`, `live_url`, `deployed_url`).
- URL evidence precedence is deterministic:
  1. `resolved_live_url`
  2. `live_url`
  3. `deployed_url`
  4. `deploy_result.live_url` fallback
- Site-specific and fallback workflows are expected to emit the same explicit Pages evidence keys.

Dispatch-stage interpretation note:
- if target-readiness preflight already logged `repo_exists=true`, `ref_exists=true`, `workflow_exists=true`, and a later `workflow_dispatch` call fails, prefer workflow dispatchability troubleshooting before assuming branch/ref drift.
- if `workflow_dispatch_supported=true` but `dispatch_service_availability=false`, treat this as service/function readiness unavailability (not workflow identity/trigger mismatch).
- if `workflow_dispatch_supported=true` and `dispatch_service_availability=true`, this still only proves control-plane dispatch readiness; it does not by itself prove that target-repo GitHub Actions has all required GKE deploy prerequisites (workflow logic/secrets/permissions/cluster access).
- if `namespace_model_status=misaligned`, managed workflow/manifests no longer agree on the derived namespace; treat this as `target_configuration_invalid` and re-run managed workflow provisioning from publish before retrying deploy.
- if `managed_*_expected=true` but matching `managed_*_present=false`, publish did not verify all expected policy manifests for this namespace model; re-run publish/provision and inspect managed file verification logs.
- `managed_namespace_policies_aligned=false` means at least one expected policy file is missing or namespace-misaligned for the current derived namespace.
- NetworkPolicy defaults are intentionally bounded and may be disabled by default; absence is only a blocker when `managed_network_policy_expected=true`.

### Production Verification Checklist (TnM Fire)

Use this sequence for one bounded production deploy validation:

1. Confirm target repository Pages setting is **Source = GitHub Actions** and selected workflow emits explicit output evidence keys (`resolved_live_url`, `live_url`, `deployed_url`) on successful deploy.
2. In the migration workspace, choose the latest published artifact for `mhanson13/tnmfire` (`ref=main`).
3. Submit deploy and capture `Deploy trace ID` from the Deploy Readiness traceability grid.
4. Query deploy control-plane events using trace id correlation:
   - `jsonPayload.event="seo_migration_control_plane_action"`
   - `jsonPayload.action="deploy"`
   - `jsonPayload.target.deploy_trace_id="<trace-id>"`
5. Confirm staged evidence progression in logs:
   - readiness/preflight fields (`workflow_identifier`, `workflow_identifier_requested`, `workflow_identifier_used`, `workflow_dispatch_supported`, `dispatch_service_availability`)
   - dispatch attempt fields (`dispatch_attempted=true`, `dispatch_result_stage`)
   - run evidence fields (`workflow_run_id`, `workflow_run_status`, `workflow_run_conclusion`) when available
   - identifier-resolution fields (`workflow_dispatch_resolution_source`, `workflow_identifier_type_used`) show selected/provenance workflow identity.
   - outbound dispatch fields (`actual_dispatch_identifier_sent`, `actual_dispatch_identifier_type_sent`) show the exact identifier value/type sent to the GitHub dispatch API.
   - conformance fields (`workflow_conformance_status`, `workflow_conformance_reasons`) indicate whether selected workflow content is deploy-capable for managed migration deploy.
6. If UI shows `Dispatch was accepted, but no workflow run evidence is available yet`, wait for eventual consistency and run **Refresh deploy status**.
7. Re-query refresh events by trace id:
   - `jsonPayload.event="seo_migration_deploy_status_refresh_requested"`
   - `jsonPayload.event="seo_migration_workflow_run_refresh_result_captured"`
   - `jsonPayload.event="seo_migration_deploy_status_refresh_completed"`
8. Confirm URL evidence contract:
   - `expected_publish_url` may be present as guidance
   - `resolved_live_url` is only confirmed when explicit evidence is present with `url_source=workflow_output` or `url_source=deploy_result`
9. If deploy still fails, route by `failure_stage` + `failure_reason_code` without guessing at hidden causes.
10. When `resolved_live_url` is present with explicit evidence source, open it and confirm the deployed site loads successfully.

### Production Shakeout Checklist (Short)
Use this bounded checklist for first production exercises:
1. Publish succeeded for the selected approved artifact.
2. Managed workflow is present and platform-managed.
3. Managed manifests are present and namespace-aligned.
4. Required deploy secrets/variables are configured in the target repository.
5. Deploy started and a workflow run was created.
6. Stage classification is clear:
   - `gcp_auth`
   - `cluster_credentials`
   - `manifest_apply`
   - `rollout_verify`
   - `ingress_verify`
   - `ingress_evidence`
7. Duplicate blocker interpretation:
   - run-backed active blocker: keep blocked
   - unverified dispatch blocker (`dispatch_accepted_no_run` / `dispatch_unverified_no_run`): short 2-minute TTL
   - stale/terminal attempts: retry allowed
8. `resolved_live_url` is only confirmed when explicit evidence exists (`url_source=workflow_output` or `url_source=deploy_result`).

### First Production Deploy Quick Path
Before deploy:
1. Verify approved + published artifact selection.
2. Verify destination tuple (`repo`, `ref`, `workflow`, `namespace`).
3. Verify target repo deploy prerequisites/secrets are configured.

After deploy click:
1. Capture `deploy_trace_id`.
2. Confirm dispatch attempted and workflow run id appears.
3. Use refresh to reconcile post-dispatch state to run evidence.

If no run appears:
1. Refresh deploy status.
2. Treat no-run states as unverified dispatch uncertainty.
3. Retry only after stale transition (2-minute TTL) or terminal prior state.

If ingress evidence does not appear:
1. Inspect `workflow_run_failure_stage` / `workflow_run_failure_reason_code`.
2. Prioritize ingress readiness troubleshooting for `ingress_verify` / `ingress_evidence`.
3. Do not treat `expected_publish_url` as deploy confirmation.

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
      - `deploy_evidence_contract_status` and `workflow_contract_advisory` explain whether run success still lacks required explicit evidence.
      - `post_conformance_stage` should read `live_url_evidence_missing` until explicit evidence is captured.
      - compare workflow output payload keys against `expected_workflow_outputs`.
   - Confirmed live URL appears only when explicit evidence sets `resolved_live_url` with `url_source=workflow_output` or `url_source=deploy_result`.

Explicit evidence troubleshooting quick guide:
- Explicit evidence found:
  - `resolved_live_url` present and `url_source=workflow_output` (or `deploy_result`) means confirmed live deployment evidence.
- Workflow succeeded but evidence absent:
  - `post_dispatch_state=workflow_run_succeeded_without_live_url` with `resolved_live_url` absent means run success did not emit required evidence keys.
- Fallback workflow handling:
  - if fallback workflow is selected, evidence handling is identical; `resolved_live_url` is still confirmed only from explicit evidence keys.

Managed workflow deploy evidence notes:
- The managed GKE deploy workflow resolves live URL evidence from ingress status (`status.loadBalancer.ingress[0].hostname|ip`).
- On successful evidence capture, workflow outputs include:
  - `resolved_live_url`
  - `live_url`
  - `deployed_url`
- If rollout succeeds but ingress status has no concrete endpoint, workflow fails and no explicit live URL evidence is emitted.

Managed real-deploy prerequisites (GitHub Actions secrets):
- `GCP_DEPLOY_KEY` (full JSON service account key with Kubernetes Engine Admin-equivalent scoped access to the target cluster/project)
- `KUBERNETES_CLUSTER_NAME`
- `KUBERNETES_CLUSTER_LOCATION`
- `GCP_PROJECT_ID`

Required credential note:
- `google-github-actions/auth@v2` uses:
  - `credentials_json: ${{ secrets.GCP_DEPLOY_KEY }}`
  - `create_credentials_file: true`
  - `export_environment_variables: true`
- workflow includes a fast-fail pre-check step that exits with `Missing GCP_DEPLOY_KEY secret` if absent.

Post-dispatch workflow run failure diagnostics:
- `workflow_run_failure_reason_code`
- `workflow_run_failure_stage`
- `workflow_run_failure_step`
- `workflow_run_failure_hint`

Common stage-aware interpretations:
- `gcp_auth_failed` / `gcp_auth`: GCP auth step failed (missing/invalid `GCP_DEPLOY_KEY` or key permissions issue).
- `gke_credentials_failed` / `cluster_credentials`: `get-gke-credentials` step failed.
- `kubectl_apply_failed` / `manifest_apply`: managed manifest apply failed.
- `rollout_verification_failed` / `rollout_verify`: deployment rollout timed out/failed.
- `service_ingress_verification_failed` / `ingress_verify`: service or ingress verification failed.
- `ingress_endpoint_not_ready` / `ingress_evidence`: deployment ran but ingress endpoint did not become available before workflow evidence timeout.

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
- `resolved_live_url` remains null when only deterministic guidance is available; successful dispatch/run without explicit URL evidence is not treated as confirmed live deploy.
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

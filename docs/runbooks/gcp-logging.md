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
- `jsonPayload.event="seo_migration_deploy_secret_propagation"` (publish-time guarded `GCP_DEPLOY_KEY` propagation to approved managed repos)
- `jsonPayload.event="seo_migration_managed_site_static_ip_ensure"` (pre-dispatch control-plane ensure of deterministic per-site global static IP)
- `jsonPayload.event="seo_migration_managed_site_dns_ensure"` (pre-dispatch control-plane ensure of preview-host DNS A record)
- `jsonPayload.event="seo_migration_managed_site_dns_propagation_check"` (bounded resolver propagation gate before dispatch)
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

Per-site success gate (managed ingress deploys):
- treat deploy as successful only when all are true for the same site hostname:
  - `dns_record_matches_ingress=true`
  - `tls_certificate_status=ACTIVE` and `tls_domain_status=ACTIVE`
  - `cert_identity_valid=true`
  - `ingress_conflict_detected=false`
  - `deploy_https_ready=true` and `resolved_live_url` uses `https://`
- managed workflow signature drift detection is non-blocking and reported separately through `workflow_integrity_status` (`match`/`mismatch`/`missing`).
- `managed_certificate_failed_not_visible` should be triaged as DNS/LB visibility mismatch first.
- pre-dispatch static IP ensure blockers (control-plane phase):
  - `managed_site_static_ip_config_missing`
  - `managed_site_static_ip_permission_denied`
  - `managed_site_static_ip_api_disabled`
  - `managed_site_static_ip_quota_exceeded`
  - `managed_site_static_ip_project_not_found`
  - `managed_site_static_ip_conflict`
  - `managed_site_static_ip_provisioning_failed`
- pre-dispatch DNS ensure blockers (control-plane phase):
  - `managed_site_dns_config_missing`
  - `managed_site_dns_provisioning_failed`
  - `managed_site_dns_conflicting_record`
  - `managed_site_dns_permission_denied`
  - `managed_site_dns_transaction_conflict`
  - `managed_site_dns_propagation_pending`
- per-site ingress isolation blockers:
  - `managed_site_static_ip_missing`
  - `expected_static_ip_not_bound_to_ingress`
  - `shared_static_ip_not_allowed_for_per_site_ingress`
  - `stale_pre_shared_cert_binding_detected` (confirmed stale/cross-site cert evidence)
- advisory cert metadata signal:
  - `pre_shared_cert_metadata_mismatch` (controller metadata mismatch only; non-blocking by itself)
- workflow template validation coverage now includes YAML parsing of rendered managed deploy workflows so embedded diagnostics scripts (including ManagedCertificate evaluation) remain inside the `run` script block.

UI-to-log troubleshooting mapping (Deploy consistency block):
- `DNS matches ingress IP` (Blocked/Pending):
  - UI fields: `dns_record_matches_ingress`, `dns_expected_ip`, `dns_observed_ip`, `ingress_ip`
  - reason codes: `dns_record_mismatch`, `dns_points_to_old_ingress_ip`, `ingress_ip_assigned_but_dns_not_updated`
  - logs: `seo_migration_target_readiness_check`, `seo_migration_workflow_run_result_captured`, deploy failure entries with the same reason code
- `Managed certificate active` and `Certificate identity valid`:
  - UI fields: `tls_certificate_status`, `tls_domain_status`, `cert_identity_valid`
  - reason codes: `tls_certificate_provisioning`, `managed_certificate_failed_not_visible`, `tls_certificate_bound_to_wrong_site`, `managed_certificate_identity_mismatch`, `ingress_certificate_mismatch`
  - logs: `seo_migration_target_readiness_check`, ingress-evidence failure records, `dispatch_service_reason_code`
- `Ingress/static IP conflict check`:
  - UI field: `ingress_conflict_detected`
  - reason codes: `managed_site_static_ip_config_missing`, `managed_site_static_ip_permission_denied`, `managed_site_static_ip_api_disabled`, `managed_site_static_ip_quota_exceeded`, `managed_site_static_ip_project_not_found`, `managed_site_static_ip_conflict`, `managed_site_static_ip_provisioning_failed`, `managed_site_dns_config_missing`, `managed_site_dns_provisioning_failed`, `managed_site_dns_conflicting_record`, `managed_site_dns_permission_denied`, `managed_site_dns_transaction_conflict`, `managed_site_dns_propagation_pending`, `ingress_static_ip_conflict`, `shared_static_ip_not_allowed_for_per_site_ingress`, `managed_site_static_ip_missing`, `expected_static_ip_not_bound_to_ingress`, `stale_pre_shared_cert_binding_detected`
  - logs: target-readiness and dispatch failure records with matching `dispatch_service_reason_code`
- `Managed certificate active` / metadata diagnostics:
  - advisory reason code: `pre_shared_cert_metadata_mismatch`
  - interpretation: controller-generated `ingress.gcp.kubernetes.io/pre-shared-cert` differs from expected managed certificate name, but hard-failure decisions still come from managed-certificate annotation/domain/TLS identity checks
  - logs: ingress-evidence run-failure records and workflow diagnostic lines with managed certificate annotation/domain context
- `HTTPS probe`:
  - UI field: `deploy_https_ready`
  - requires DNS/TLS/ingress convergence and explicit HTTPS-ready evidence for `Pass`
  - logs: `seo_migration_workflow_output_url_captured`, `seo_migration_workflow_output_url_captured_via_refresh`, and workflow run capture events
- `Workflow integrity`:
  - UI fields: `workflow_integrity_status`, `workflow_integrity_reason_code`
  - reason codes: `managed_workflow_signature_missing`, `managed_workflow_signature_mismatch`
  - logs: `seo_migration_managed_workflow_signature_validation` with `integrity_status`, `expected_signature` (truncated), `observed_signature` (truncated), `site_id`, `workflow_path`
  - mismatch is non-blocking but should be treated as contract drift risk before relying on deploy diagnostics
- `Deployment rollout`, `Service endpoints`, `Backend health`:
  - triage via run failure stage/reason:
    - rollout: `workflow_run_failure_stage=rollout_verify`, `rollout_verification_failed`
    - service endpoints/in-cluster probe: `service_has_no_ready_endpoints`, `service_endpoint_missing`, `service_endpoint_unhealthy`, `in_cluster_service_probe_timeout`, `network_policy_may_block_service_probe`, `in_cluster_service_curl_failed_after_retries`, `in_cluster_service_curl_failed`
    - backend/ingress health: `backendconfig_health_check_mismatch`, `backend_config_healthcheck_unhealthy`, `ingress_backend_unhealthy`, `ingress_backend_502`, `ingress_backend_unhealthy_after_rollout`, `ingress_neg_convergence_pending`
  - logs: `seo_migration_workflow_run_result_captured` and deploy failure history entries

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
  - `target.blocking_workflow_run_url`
  - `target.blocking_deploy_trace_id`
  - `target.blocking_timestamp`
  - `target.blocking_dispatched_at`
  - `target.blocking_refreshed_at`
  - `target.blocking_reconciliation_attempted`
  - `target.blocking_reconciliation_result`
  - `target.blocking_reconciliation_reason_code`
  - `target.blocking_reconciliation_prior_state`
  - `target.blocking_reconciliation_refreshed_state`
- `workflow_id`, optional `workflow_path`, `ref`, `repo_owner`, `repo_name`
- `workflow_identifier_requested`, `workflow_identifier_used`
- `workflow_identifier_type_requested`, `workflow_identifier_type_used`
- `workflow_dispatch_resolution_source`, `workflow_file_path`, `workflow_name`
- `actual_dispatch_identifier_sent`, `actual_dispatch_identifier_type_sent`
- `dispatch_ref_sent`
- `workflow_inputs_configured_keys`, `workflow_inputs_sent_keys`
- pre-dispatch static IP/DNS ensure fields:
  - `expected_static_ip_name`, `expected_static_ip_address`, `static_ip_created`, `static_ip_project_id`, `static_ip_ensure_result`
  - static IP ensure diagnostics (safe/operator-facing): `static_ip_operation`, `static_ip_error_category`, `static_ip_error_code`, `static_ip_error_summary`, `static_ip_exit_code`, `static_ip_permission_hint`
  - `expected_dns_hostname`, `expected_dns_managed_zone`, `expected_dns_project_id`, `expected_dns_ip`, `dns_record_created`, `dns_record_updated`, `dns_previous_ips`, `dns_ttl`, `dns_ensure_result`
  - `dns_propagation_result`, `dns_propagation_observed_ips`, `observed_dns_ips`, `dns_propagation_wait_seconds`, `dns_propagation_attempts`
- `seo_migration_managed_site_dns_ensure` event fields:
  - `preview_hostname`, `dns_record_name`, `dns_managed_zone`, `dns_project_id`, `dns_expected_ip`, `dns_previous_ips`, `dns_created`, `dns_updated`, `dns_ttl`, `result`, optional `reason_code`
- `seo_migration_managed_site_dns_propagation_check` event fields:
  - `preview_hostname`, `dns_record_name`, `dns_managed_zone`, `dns_project_id`, `dns_expected_ip`, `dns_observed_ips`, `observed_dns_ips`, `dns_ensure_result`, `max_wait_seconds`, `sleep_seconds`, `wait_elapsed_seconds`, `attempt_count`, `result`
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
- per-site network/TLS readiness fields:
  - `dns_record_matches_ingress`, `dns_expected_ip`, `dns_observed_ip`
  - `tls_certificate_status`, `tls_domain_status`
  - `ingress_ip`, `ingress_conflict_detected`, `cert_identity_valid`, `deploy_https_ready`
- workflow integrity fields:
  - `workflow_integrity_status` (`match`, `mismatch`, `missing`)
  - `workflow_integrity_reason_code` (`managed_workflow_signature_missing`, `managed_workflow_signature_mismatch`)
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
- deploy-secret propagation fields:
  - `attempted`
  - `status` (`not_attempted`, `created`, `updated`, `skipped_guardrail`, `failed`)
  - `reason`
  - `action` (`created` / `updated` when write occurs)
  - `secret_name` (name only; value is never logged)
  - guardrail failures (`status=skipped_guardrail`) indicate propagation was intentionally denied for non-approved tuple/owner/config state.
  - write failures (`status=failed`) mean publish may have succeeded but deploy is likely blocked until secret propagation succeeds.

Managed workflow contract quick check:
- `workflow_dispatch` trigger present

Dependency troubleshooting:
- `ModuleNotFoundError: No module named 'yaml'` indicates backend dependency installation drift (missing `PyYAML`) in runtime/CI image setup.
- This is a backend environment dependency issue, not a managed deploy DNS/TLS/HTTPS contract failure.
- production deploy markers present (`google-github-actions/auth`, `google-github-actions/get-gke-credentials`, `kubectl apply`, `kubectl rollout`)
- explicit evidence outputs emitted (`resolved_live_url`, `live_url`, `deployed_url`)
- if missing, deploy remains blocked as `workflow_not_production_ready`

Hybrid deploy-secret propagation quick check:
- `seo_migration_deploy_secret_propagation.status=created|updated` -> secret propagation succeeded for approved managed repo.
- `status=skipped_guardrail` -> propagation denied by policy boundary (review owner/tuple/admin enablement).
- `status=failed` -> propagation attempted but GitHub write failed; inspect `reason` and retry publish/remediation flow.

Approved vs denied propagation verification:
1. Run publish against an approved managed repo tuple.
   - Expect `attempted=true` and `status=created|updated`.
2. Run publish against a denied tuple/owner case.
   - Expect `attempted=false`, `status=skipped_guardrail`, and a deterministic `reason` (for example `repo_owner_not_approved` or `target_tuple_mismatch`).
3. If publish succeeds but propagation reports `failed`, treat deploy as not ready until propagation succeeds.

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
- `repo_auto_create_disabled`: target repository is missing and admin policy does not allow runtime repository creation.
- `repo_auto_create_not_authorized`: runtime GitHub token could not create repository under configured owner.
- `repo_create_failed_invalid_name`: configured repository name failed validation for auto-create.
- `repo_create_failed_owner_mismatch`: configured owner is outside the admin-owned target boundary.
- `repo_create_failed_conflict`: repository create returned conflict (already exists or owner/repo conflict).
- `repo_create_failed_runtime_unavailable`: repository auto-create failed due to temporary runtime/API availability issues.
- `github_repo_adoption_required`: existing repository is not marked as MBSRN-managed; publish is blocked until explicit adoption writes `mbsrn.key`.
- `github_repo_adoption_failed`: explicit repository adoption action failed.
- `github_repo_management_marker_written`: explicit adoption wrote `mbsrn.key` successfully.
- `github_repo_management_marker_missing`: existing repository is missing `mbsrn.key`; managed publish blocks to avoid overwriting unrelated content.
- `github_repo_management_marker_mismatch`: existing repository marker points to a different business/site.
- `github_repo_management_marker_invalid`: `mbsrn.key` exists but is invalid/unparseable.
- `github_repo_bootstrap_marker_write_failed`: bootstrap could not write the required `mbsrn.key` ownership marker.
- `github_repo_baseline_reconciliation_failed`: managed baseline file reconciliation (`README.md`, `.gitignore`, `LICENSE`) failed after marker validation.
- `github_branch_not_found_or_uninitialized`: target branch/ref exists in config but GitHub repo state has no initialized commit/ref tree for provisioning writes.
- `github_repo_state_invalid_for_bootstrap`: repository initialization/bootstrap could not complete safely.
- `github_repo_initialization_failed`: explicit repository initialization phase failed before workflow provisioning could continue.
- `github_workflow_write_not_authorized`: token can access repo metadata but lacks workflow-path write permission for `.github/workflows/*`.
- `github_contents_write_not_authorized`: token lacks repository contents write permission for managed manifest/content files.
- `github_workflow_provisioning_failed`: workflow bootstrap request failed with non-specific provider error after request classification.
- `workflow_not_found`: repository exists, but requested workflow id/path was not found.
- `branch_not_found_or_ref_invalid`: dispatch ref is invalid or missing in target repo.
- `workflow_not_dispatchable`: workflow exists but is not in a dispatch-ready state for target ref.
- `workflow_dispatch_not_supported`: workflow exists but does not expose `workflow_dispatch`.
- `workflow_not_production_ready`: workflow exists and is dispatchable, but is still scaffold/placeholder content and is blocked before dispatch.
- `token_not_authorized`: runtime token lacks required repository/workflow permissions.
- `workflow_provisioning_failed`: publish could not verify workflow file presence after provisioning attempt.
- `managed_workflow_template_invalid`: publish-time managed workflow template conformance validation failed before workflow write (YAML parse/contract mismatch such as missing required deploy outputs or missing `Resolve live URL from ingress status` step).

Repository auto-create observability (publish path):
- compare publish events:
  - `seo_migration_repo_ensure_started`
  - `seo_migration_repo_ensure_result`
  - `seo_migration_repo_auto_create_attempted`
  - `seo_migration_repo_auto_create_succeeded` / `seo_migration_repo_auto_create_failed`
- key fields:
  - `repo_owner`
  - `repo_name`
  - `auto_create_enabled`
  - `create_if_missing`
  - `auto_create_attempted`
  - `auto_create_created`
  - `outcome`
  - `skipped_reason`
  - `private_by_default` (create attempts use private repository visibility)
  - `repo_ensure_outcome` (normalized control-plane summary)

Publish preflight observability (before live content/workflow writes):
- event:
  - `seo_migration_publish_preflight`
- core fields:
  - `repo_owner`
  - `repo_name`
  - `target_ref`
  - `repo_exists`
  - `repo_ensure_outcome`
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
  - `preflight_status`
  - `preflight_blocker_code`
- interpretation:
  - `preflight_status=ready`: target is usable as-is.
  - `preflight_status=ready_with_actions`: publish can proceed but must perform bounded setup (for example repo auto-create or branch bootstrap).
  - `preflight_status=blocked`: deterministic blocker exists; remediate before retrying live publish.
  - `can_write_contents=true` with `can_write_workflows=false` indicates token scope mismatch for `.github/workflows/*` writes.
  - `would_auto_create_repo=true` appears in readiness/dry-run when repo is missing and admin auto-create policy is enabled; dry-run still performs no mutation.
  - `repo_management_status=managed_marker_match` is the expected steady-state for managed publish/update on existing repos.
  - `repo_management_status=marker_missing|marker_mismatch|marker_invalid` means managed publish is intentionally blocked before any content/workflow overwrite.
  - `repo_baseline_required=true` with `preflight_status=ready_with_actions` means publish will add only missing managed baseline files (`README.md`, `.gitignore`, `LICENSE`) for an already managed repo.

Workflow bootstrap observability (publish path):
- compare:
  - `seo_migration_workflow_provisioning` (service-level control-plane event)
  - `seo_migration_workflow_provisioning_operation` (publisher operation trace)
  - `seo_migration_managed_workflow_template_validation` (publisher template conformance guard before workflow write)
- template-validation event fields:
  - `template_name`
  - `workflow_path`
  - `site_id`
  - `reason_code` (`managed_workflow_template_invalid` on failure)
  - `validation_errors` (operator-safe contract failure diagnostics)

Repository Initialization Phase:
- repository initialization phase (always before workflow write/ref provisioning):
  - `repo_initialization_started`
  - `repo_initialization_completed`
  - `repo_initialization_failed`
  - decision trace remains in `seo_migration_workflow_provisioning_operation` with:
    - `operation_kind=repo_bootstrap_decision`
    - `bootstrap_decision_source`
    - `bootstrap_allowed`
    - `will_attempt_bootstrap`
    - `bootstrap_blocked_reason` (when bootstrap is intentionally disabled, e.g. dry-run)
  - `repo_initialization_failed` includes `step_failed` so failures are attributable to Git Data API stage:
    - `blob`
    - `tree`
    - `commit`
    - `ref`
- key operation fields:
  - `operation_kind`
  - `operation_status`
  - `repo_owner`, `repo_name`, `ref`
  - `path` (for file operations)
  - `http_status_code`
  - `github_error_code`
  - `github_error_message` (sanitized)
  - `repo_bootstrap_required`
  - `repo_bootstrap_completed`
  - `repo_bootstrap_state`

Managed marker observability:
- marker check event:
  - `seo_migration_repo_management_marker_check`
- explicit adoption events:
  - `seo_migration_github_repo_adoption` (`status=started|completed|failed`)
  - `repo_adoption_started`
  - `repo_adoption_completed`
  - `repo_adoption_failed`
- key fields:
  - `repo_management_status`
  - `repo_management_marker_present`
  - `repo_management_marker_valid`
  - `repo_management_marker_matches_site`
  - `repo_management_marker_source_ref`
  - `repo_management_blocker_code`
- expected behavior:
  - new/empty repos: bootstrap writes `mbsrn.key` before managed workflow/manifest/content updates
  - empty repos now always emit `repo_initialization_*` events before workflow provisioning continues
  - existing managed repos: marker must be present/valid/matching
  - existing non-managed repos: marker blocker prevents overwrite until explicit adoption

Managed baseline reconciliation observability:
- event:
  - `seo_migration_repo_baseline_reconciliation`
- key fields:
  - `repo_baseline_required`
  - `repo_baseline_reconciled`
  - `readme_present`
  - `gitignore_present`
  - `license_present`
  - `repo_visibility_target`
- interpretation:
  - `repo_baseline_required=true` and `repo_baseline_reconciled=true`: missing baseline files were added successfully.
  - `repo_baseline_required=true` and `repo_baseline_reconciled=false` in non-dry-run paths is unexpected; inspect publish failure code (`github_repo_baseline_reconciliation_failed`).
  - existing files are additive-only and preserved; reconciliation writes only missing baseline files.

Token capability minimums for publish bootstrap:
- repository auto-create: token must create repositories under the configured owner namespace.
- managed workflow provisioning: token must write `.github/workflows/*`.
- managed manifest provisioning: token must write repository contents under `k8s/*`.

`repo_ensure_outcome` interpretation:
- `exists`: target repo already existed (or existed by the time ensure completed).
- `created`: runtime created the missing repo successfully.
- `would_create_on_publish`: readiness/dry-run observed missing repo with auto-create policy enabled.
- `skipped_policy_disabled`: repo missing but admin policy disallows auto-create.
- `failed_not_authorized`: runtime token could not create repos under configured owner.
- `failed_invalid_name`: repo name failed validation.
- `failed_owner_mismatch`: owner was outside admin-owned boundary.
- `failed_conflict`: create conflict (for example, created in a concurrent race).
- `failed_runtime_unavailable`: transient GitHub API/runtime failure during create.

Race-note:
- if a create call returns conflict but a follow-up repo lookup confirms existence, publish treats that as idempotent success (`outcome=repo_exists`, `skipped_reason=created_during_race`) and continues.

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
- stale/activity evaluation is deterministic and uses this timestamp precedence:
  - `refreshed_at` (if present)
  - else `dispatched_at`
  - else `occurred_at`
  - else `timestamp`
  - run-backed active blockers (`workflow_run_pending`, `workflow_run_in_progress`, `workflow_run_observed`, and active run statuses) use a 30-minute active freshness window
  - unverified dispatch blockers (`dispatch_accepted_no_run` / `dispatch_unverified_no_run`) use a 2-minute weak-blocker window
- run-backed blockers that are older than 12 minutes are reconciled against GitHub run status before final duplicate rejection.
- run-backed blockers use a hard stale safety threshold of 2 hours for automated stale-blocker supersede decisions.
- reconciliation outcomes:
  - `reconciliation_result=terminal_cleared`: prior run reached terminal state, blocker cleared, retry can proceed
  - `reconciliation_result=active`: prior run still active, duplicate blocking remains
  - `reconciliation_result=refresh_failed` with reason `deploy_blocker_reconciliation_failed`: refresh failed while blocker still appears active (fail closed)
  - `reconciliation_result=stale_requires_manual_refresh` with reason `stale_deploy_blocker_requires_refresh`: refresh failed for a stale blocker below the hard stale threshold; manual status refresh required
  - `reconciliation_result=superseded_after_stale_threshold` with reason `deploy_blocker_superseded_after_stale_threshold`: blocker exceeded hard stale threshold and could not be confirmed active; prior entry is superseded and retry proceeds
- quick triage:
  - use `target.blocking_post_dispatch_state` and blocker run fields to confirm whether the prior attempt is still active.
  - use `target.blocking_stale_reference_field`, `target.blocking_stale_reference_at`, `target.blocking_stale_age_seconds`, `target.blocking_stale_threshold_seconds`, `target.blocking_stale_evaluated`, `target.blocking_stale_is_stale`, and `target.blocking_treated_as_stale` to validate stale classification.
  - if blocker state is run-backed and old enough for reconciliation, run **Refresh Deploy Status** (or retry deploy) to force GitHub reconciliation evidence capture.
  - if reason code is `duplicate_request`, wait for terminal state or cancel/complete the run externally.
  - if reason code is `deploy_blocker_reconciliation_failed`, retry refresh and validate GitHub Actions/API health before reattempting deploy.
  - if reason code is `stale_deploy_blocker_requires_refresh`, perform manual status refresh and confirm terminal evidence before retrying.
  - if reason code is `deploy_blocker_superseded_after_stale_threshold`, retry deploy and inspect GitHub Actions only if an orphan workflow run is suspected.
  - observe unverified-dispatch reconciliation events:
    - `dispatch_attempted_without_run`
    - `no_run_observed_after_refresh`
    - `downgrade_to_stale_unverified_dispatch`
  - if refresh hits `failure_reason_code=workflow_not_found` after dispatch was attempted, control plane marks tracking as terminal/retryable with:
    - `post_dispatch_state=workflow_run_failed`
    - `workflow_run_failure_reason_code=workflow_run_tracking_lost`
    - `no_change_reason=workflow_run_tracking_lost`
  - observe stale active-blocker reconciliation event:
    - `downgrade_to_stale_active_deploy_blocker`
    - followed by `seo_migration_deploy_duplicate_blocker_reconciliation`
  - observe stale supersede event when hard-stale clearance is used:
    - `seo_migration_deploy_stale_blocker_superseded`
    - prior history item updates to `workflow_run_failure_reason_code=stale_deploy_blocker_superseded`

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
4. Required deploy/runtime configuration is in place:
   - control-plane runtime secrets projected by `deploy-prod` (`GIT_USERID`, `GIT_EMAIL`, `GIT_TOKEN`) for namespace GHCR pull-secret provisioning
   - target repo deploy prerequisites required by your managed workflow implementation
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
   - aged run-backed blocker (>=12 minutes): reconcile against GitHub before final duplicate decision
   - unverified dispatch blocker (`dispatch_accepted_no_run` / `dispatch_unverified_no_run`): short 2-minute TTL
   - terminal reconciled blocker: retry allowed
   - reconciliation failure reason codes:
     - `deploy_blocker_reconciliation_failed`
     - `stale_deploy_blocker_requires_refresh`
   - hard-stale supersede evidence:
     - `deploy_blocker_superseded_after_stale_threshold`
     - prior history item `workflow_run_failure_reason_code=stale_deploy_blocker_superseded`
8. `resolved_live_url` is only confirmed when explicit evidence exists (`url_source=workflow_output` or `url_source=deploy_result`).

### First Production Deploy Quick Path
Before deploy:
1. Verify approved + published artifact selection.
2. Verify destination tuple (`repo`, `ref`, `workflow`, `namespace`).
3. Verify control-plane deploy runtime credentials are configured (`GIT_USERID`, `GIT_EMAIL`, `GIT_TOKEN`) and target repo deploy prerequisites are present.

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
- Ingress evidence uses a bounded wait loop (10-minute max: `40 x 15s`) to account for normal GKE load balancer provisioning lag.
- On successful evidence capture, workflow outputs include:
  - `resolved_live_url`
  - `live_url`
  - `deployed_url`
- If rollout succeeds but ingress status still has no concrete endpoint after bounded wait, workflow fails and no explicit live URL evidence is emitted.
- In that failure mode, inspect ingress-focused diagnostics emitted by the workflow step:
  - `kubectl get ingress site-web -o wide`
  - `kubectl describe ingress site-web`
  - `kubectl get service site-web -o wide`
  - `kubectl get endpoints site-web -o wide`
  - optional checks: `kubectl get managedcertificate`, `kubectl get frontendconfig`
- Workflow logs include troubleshooting marker `deploy_runtime_reason_code=ingress_address_pending` for this condition.

Managed-site ingress resource contract (generated by MBSRN templates):
- `k8s/service.yaml` must include NEG ingress wiring:
  - `metadata.annotations["cloud.google.com/neg"]={"ingress": true}`
  - `metadata.annotations["cloud.google.com/backend-config"]={"default":"site-web-backend-config-<normalized-site>"}`
- `k8s/backendconfig.yaml` must exist and define GCLB health checks aligned to the runtime container:
  - `kind: BackendConfig`
  - `metadata.name: site-web-backend-config-<normalized-site>`
  - `spec.healthCheck.requestPath: /`
  - `spec.healthCheck.port: 8080`
- `k8s/ingress.yaml` must include GKE ingress annotations:
  - `kubernetes.io/ingress.class: gce`
  - `kubernetes.io/ingress.global-static-ip-name: site-web-preview-ip-<normalized-site>`
  - `networking.gke.io/managed-certificates: site-web-preview-cert-<normalized-site>`
  - `networking.gke.io/v1beta1.FrontendConfig: site-web-frontend-config-<normalized-site>`
  - do not render `ingress.gcp.kubernetes.io/pre-shared-cert` in managed templates
  - do not reuse a single shared `kubernetes.io/ingress.global-static-ip-name` value for per-site ingresses
  - expected global static IP name is deterministic per site: `site-web-preview-ip-<normalized-site>`
  - mbsrn control plane ensures this static IP exists before workflow dispatch using admin-managed GCP deploy credentials
  - generated target workflow still verifies static IP existence before apply (`gcloud compute addresses describe site-web-preview-ip-<normalized-site> --global --project <project-id>`) as a drift safety check
  - mbsrn control plane ensures preview-host DNS A record before workflow dispatch:
    - managed zone default: `sites`
    - record name: `<normalized-site>.site.mbsrn.com.`
    - update scope: exact hostname + type `A` only
    - target workflow still verifies public DNS against ingress/static IP as deploy-contract evidence
  - target repositories/workflows do not create or modify Cloud DNS records
- `k8s/managedcertificate.yaml` must exist and include the platform preview host:
  - `metadata.name: site-web-preview-cert-<normalized-site>`
  - `<normalized-site>.site.mbsrn.com`
- preview and production domain interpretation:
  - preview URL is platform-owned and used for deploy evidence (`preview_url`, `preview_state`)
  - customer production domain remains separate (`customer_domain_url`, `customer_domain_state`) and should stay `pending_cutover` until explicit DNS/cutover steps are complete
- `k8s/frontendconfig.yaml` must be present and referenced:
  - `apiVersion: networking.gke.io/v1beta1`
  - `kind: FrontendConfig`
  - `metadata.name: site-web-frontend-config-<normalized-site>`

If rollout is healthy but ingress `ADDRESS` stays blank:
1. Confirm generated repo manifests include all required ingress resources above.
2. Confirm ingress annotation references an existing `FrontendConfig` in the same namespace.
3. Re-run publish (non-dry-run) to refresh managed manifests before retrying deploy.

If browser TLS fails with `SSL_ERROR_BAD_CERT_DOMAIN` for preview host:
1. Compare requested host, ingress host rule, and managed certificate domain in the same namespace.
2. Verify ingress annotation references the site-scoped managed certificate:
   - `networking.gke.io/managed-certificates: site-web-preview-cert-<normalized-site>`
3. Verify certificate domain matches the requested preview host:
   - `kubectl get managedcertificate -n <site-namespace>`
   - `kubectl describe managedcertificate site-web-preview-cert-<normalized-site> -n <site-namespace>`
   - `kubectl describe ingress site-web -n <site-namespace>`
4. If annotation/domain points at another site hostname, republish + redeploy the site so managed ingress/certificate resources are regenerated for the correct host.

Managed certificate mismatch reason-code interpretation:
- `dispatch_service_reason_code=tls_certificate_bound_to_wrong_site`
  - ingress host and managed certificate domain disagree for the expected preview host.
- `dispatch_service_reason_code=ingress_certificate_annotation_mismatch`
  - ingress managed-certificate annotation does not match the expected site-scoped certificate name.
- `dispatch_service_reason_code=managed_certificate_identity_mismatch`
  - ingress annotation references multiple certificates and includes stale cross-site names.
  - check and remove stale certificates after confirming only one site-scoped certificate should remain attached.
- `workflow_run_failure_reason_code=managed_site_static_ip_missing`
  - workflow-time safety check could not find expected deterministic per-site global static IP in GCP.
  - treat as drift/inconsistency after control-plane ensure; inspect `seo_migration_managed_site_static_ip_ensure` event and static-IP admin permissions, then retry deploy.
- `dispatch_service_reason_code=managed_site_static_ip_config_missing`
  - control-plane static IP ensure is missing required managed deploy config (typically `managed_gke_project_id` or deploy credential).
  - fix admin managed deploy configuration in mbsrn control plane before retry.
- `dispatch_service_reason_code=managed_site_static_ip_permission_denied`
  - control-plane identity is not authorized to describe/create global static addresses in the managed project.
  - required permissions include `compute.globalAddresses.get` and `compute.globalAddresses.create`.
  - inspect `seo_migration_managed_site_static_ip_ensure` for `static_ip_operation`, `static_ip_error_code`, `static_ip_error_summary`, and `static_ip_permission_hint`.
- `dispatch_service_reason_code=managed_site_static_ip_api_disabled`
  - Compute Engine API is disabled or not yet enabled for the managed project.
  - enable API for the project, then retry deploy.
- `dispatch_service_reason_code=managed_site_static_ip_quota_exceeded`
  - global static-address quota is exhausted in the managed project.
  - increase quota or delete unused global static addresses, then retry deploy.
- `dispatch_service_reason_code=managed_site_static_ip_project_not_found`
  - configured managed deploy project id is invalid/inaccessible.
  - verify admin managed deploy project configuration and identity scope.
- `dispatch_service_reason_code=managed_site_static_ip_conflict`
  - expected deterministic static IP name conflicted with unreconciled address state.
  - inspect the named global address ownership/scope and reconcile before retry.
- `dispatch_service_reason_code=managed_site_static_ip_provisioning_failed`
  - control-plane static IP describe/create failed with an unclassified provisioning error.
  - inspect `seo_migration_managed_site_static_ip_ensure` structured event for `reason_code`, `static_ip_name`, `static_ip_project_id`, and static-IP diagnostic fields (`static_ip_operation`, `static_ip_error_category`, `static_ip_error_code`, `static_ip_error_summary`) then remediate and retry.
  - admin verification commands:
    - `gcloud compute addresses describe site-web-preview-ip-tnmfire --global --project mbsrn-prod`
    - `gcloud compute addresses create site-web-preview-ip-tnmfire --global --project mbsrn-prod`
- `dispatch_service_reason_code=managed_site_dns_config_missing`
  - control-plane DNS ensure is missing required DNS config (managed zone/project mapping or deploy credential).
  - fix admin managed deploy DNS configuration before retry.
- `dispatch_service_reason_code=managed_site_dns_provisioning_failed`
  - control-plane DNS describe/change call failed.
  - inspect `seo_migration_managed_site_dns_ensure` structured event for `reason_code`, `preview_hostname`, `dns_managed_zone`, `dns_project_id`, and `dns_expected_ip`.
- `dispatch_service_reason_code=managed_site_dns_conflicting_record`
  - preview hostname already has a conflicting non-A record (for example CNAME).
  - remove the conflicting record type for that exact hostname before retry.
- `dispatch_service_reason_code=managed_site_dns_permission_denied`
  - control-plane credential lacks required Cloud DNS permissions on configured project/zone.
  - grant DNS permissions and retry.
- `dispatch_service_reason_code=managed_site_dns_transaction_conflict`
  - DNS transaction/update conflict occurred while applying the exact-hostname A record.
  - retry after concurrent DNS writer contention clears.
- `dispatch_service_reason_code=managed_site_dns_propagation_pending`
  - control-plane DNS ensure succeeded, but bounded resolver checks still do not see the expected `A` value.
  - inspect `seo_migration_managed_site_dns_propagation_check` for `preview_hostname`, `dns_expected_ip`, and `observed_dns_ips`; wait for propagation and retry deploy.
- `workflow_run_failure_reason_code=expected_static_ip_not_bound_to_ingress`
  - ingress is missing expected per-site static IP annotation binding.
  - republish managed ingress manifests so `kubernetes.io/ingress.global-static-ip-name` equals `site-web-preview-ip-<normalized-site>`.
- `dispatch_service_reason_code=shared_static_ip_not_allowed_for_per_site_ingress` or `ingress_static_ip_conflict`
  - ingress static IP annotation is present but does not match this site's deterministic per-site static IP name.
  - republish managed ingress manifests with the expected per-site static IP annotation.
- `workflow_run_failure_reason_code=pre_shared_cert_metadata_mismatch`
  - controller-generated pre-shared certificate metadata does not match expected managed-certificate name.
  - advisory by itself; confirm desired-state annotation, ManagedCertificate domain/status, and HTTPS/TLS identity before treating as blocking.
- `dispatch_service_reason_code=stale_pre_shared_cert_binding_detected`
  - confirmed stale/cross-site certificate evidence (metadata mismatch plus desired-state annotation/domain mismatch or TLS identity mismatch).
  - republish and verify site-scoped managed certificate/domain alignment before retry.
- `dispatch_service_reason_code=managed_certificate_failed_not_visible`
  - managed certificate visibility failed for the expected hostname (`FailedNotVisible`).
- `workflow_run_failure_reason_code=dns_record_mismatch` / `dns_points_to_old_ingress_ip` / `ingress_ip_assigned_but_dns_not_updated`
  - workflow-level DNS verification failed even after control-plane DNS ensure.
  - treat as propagation delay, resolver visibility lag, or out-of-band DNS mutation; compare `dns_expected_ip`, `dns_observed_ip`, `ingress_ip`, and latest `seo_migration_managed_site_dns_ensure` event.

Safe namespace-scoped verification commands:
- `kubectl get managedcertificate -n <site-namespace>`
- `kubectl describe managedcertificate <expected-or-stale-cert-name> -n <site-namespace>`
- `kubectl describe ingress site-web -n <site-namespace>`

Safe cleanup command (manual admin action, never automatic):
- `kubectl delete managedcertificate <old-cert-name> -n <site-namespace>`

If TLS is valid but preview URL returns HTTP 502:
1. Confirm `BackendConfig` exists in the namespace:
   - `kubectl get backendconfig -n <namespace>`
   - `kubectl describe backendconfig site-web-backend-config -n <namespace>`
2. Confirm service annotation points to backend config:
   - `cloud.google.com/backend-config: {"default":"site-web-backend-config"}`
3. Confirm health check target matches runtime contract (`/` on port `8080` by default).
4. Verify runtime response directly via port-forward:
   - `kubectl port-forward deployment/site-web 8080:8080 -n <namespace>`
   - `curl -I http://127.0.0.1:8080/`
5. Remember: Kubernetes pod readiness and GCLB backend health are separate checks; pods can be `Ready` while GCLB backends remain `UNHEALTHY` if backend health-check wiring is missing/misaligned.
6. Validate service connectivity from inside the namespace:
   - `kubectl get endpoints site-web -n <namespace> -o yaml`
   - `kubectl get endpointslice -n <namespace> -l kubernetes.io/service-name=site-web -o yaml`
   - `kubectl run tmp-curl --rm -i --restart=Never --image=curlimages/curl:8.10.1 -n <namespace> -- sh -c "curl -sS -f http://site-web.<namespace>.svc.cluster.local:80/"`
7. Inspect network policy and selector/label alignment when in-cluster curl fails:
   - `kubectl get networkpolicy -n <namespace> -o yaml`
   - `kubectl describe networkpolicy -n <namespace>`
   - `kubectl get pods -n <namespace> -l app.kubernetes.io/name=site-web --sort-by=.metadata.creationTimestamp --show-labels`
   - `kubectl get service site-web -n <namespace> -o jsonpath='selector={.spec.selector}{"\n"}ports={range .spec.ports[*]}{.name}:{.port}->{.targetPort}{"\n"}{end}'`
8. Note: the managed deploy workflow retries the in-cluster service curl check for a bounded window (about 5 minutes). Timeouts to `site-web.<namespace>.svc.cluster.local:80` are in-cluster service/connectivity issues (NetworkPolicy, selector/port mismatch, readiness/listener), not external NEG/LB convergence.
9. External ingress/NEG convergence is evaluated separately during ingress address/backend readiness checks and can emit `ingress_neg_convergence_pending` there.

Runtime reason-code hints for 502/backend-health classes:
- `service_has_no_ready_endpoints`: service selector/endpoints are not ready for ingress traffic.
- `service_endpoint_missing`: no endpoint addresses were available after rollout verification.
- `service_endpoint_unhealthy`: endpoint exists but health remained unhealthy after rollout.
- `in_cluster_service_probe_timeout`: cluster-local curl probe timed out reaching `site-web.<namespace>.svc.cluster.local`.
- `network_policy_may_block_service_probe`: NetworkPolicy may be blocking same-namespace probe traffic to `site-web` pod port `8080`.
- `service_probe_waiting_for_convergence`: first in-cluster probe failed and workflow is waiting for convergence retries.
- `in_cluster_service_curl_failed_after_retries`: in-cluster curl still failed after bounded retry budget.
- `in_cluster_service_curl_failed`: in-cluster curl check to service failed after rollout (terminal evidence code retained).
- `ingress_neg_convergence_pending`: ingress/NEG convergence evidence was observed during external ingress/LB readiness checks.
- `pod_ready_but_ingress_backend_unhealthy`: pod probes pass but GCLB backend still fails health checks.
- `ingress_backend_unhealthy_after_rollout`: ingress backend remained unhealthy after successful deployment rollout.
- `ingress_backend_502`: ingress host is reachable but returns backend 502.
- `backend_config_healthcheck_unhealthy`: BackendConfig health-check wiring/path/port is unhealthy for this backend.

Quick namespace-scoped verification commands:
- `kubectl get ingress,svc,deploy,pods -n <namespace> -o wide`
- `kubectl describe ingress site-web -n <namespace>`
- `kubectl describe svc site-web -n <namespace>`
- `kubectl get endpoints site-web -n <namespace> -o yaml`
- `kubectl get endpointslice -n <namespace> -l kubernetes.io/service-name=site-web -o yaml`
- `kubectl get networkpolicy -n <namespace> -o yaml`
- `kubectl describe networkpolicy -n <namespace>`
- `kubectl get pods -n <namespace> -l app.kubernetes.io/name=site-web --sort-by=.metadata.creationTimestamp --show-labels`
- `kubectl get service site-web -n <namespace> -o jsonpath='selector={.spec.selector}{"\n"}ports={range .spec.ports[*]}{.name}:{.port}->{.targetPort}{"\n"}{end}'`
- `kubectl get backendconfig -n <namespace> -o yaml`
- `kubectl logs -n <namespace> deploy/site-web --tail=200`

Managed real-deploy prerequisites:
- Admin-managed GKE target values in MBSRN GitHub publish config:
  - `managed_gke_cluster_name`
  - `managed_gke_cluster_location`
  - `managed_gke_project_id`
- Admin-managed deploy secret in MBSRN GitHub publish config:
  - `GCP_DEPLOY_KEY` (full JSON service account key with Kubernetes Engine Admin-equivalent scoped access to the target cluster/project)
  - write-only in admin UI/API; reads return status metadata only (`configured`, `updated_at`)

Managed workflow input mapping (rendered centrally by MBSRN):
- `cluster_name: ${{ env.GKE_CLUSTER_NAME }}`
- `location: ${{ env.GKE_CLUSTER_LOCATION }}`
- `project_id: ${{ env.GKE_PROJECT_ID }}`
- where:
  - `GKE_CLUSTER_NAME` resolves from admin `managed_gke_cluster_name` first, then `vars.KUBERNETES_CLUSTER_NAME || secrets.KUBERNETES_CLUSTER_NAME` (legacy fallback)
  - `GKE_CLUSTER_LOCATION` resolves from admin `managed_gke_cluster_location` first, then `vars.KUBERNETES_CLUSTER_LOCATION || secrets.KUBERNETES_CLUSTER_LOCATION` (legacy fallback)
  - `GKE_PROJECT_ID` resolves from admin `managed_gke_project_id` first, then `vars.GCP_PROJECT_ID || secrets.GCP_PROJECT_ID` (legacy fallback)

Required credential note:
- `google-github-actions/auth@v2` uses:
  - `credentials_json: ${{ secrets.GCP_DEPLOY_KEY }}`
  - `create_credentials_file: true`
  - `export_environment_variables: true`
- workflow includes a fast-fail pre-check step that exits with `Missing GCP_DEPLOY_KEY secret` if absent.
- workflow includes `Validate GKE environment config` pre-check and fails early for legacy fallback variable/secret gaps when admin-managed values are not set:
  - `Missing KUBERNETES_CLUSTER_NAME variable/secret`
  - `Missing KUBERNETES_CLUSTER_LOCATION variable/secret`
  - `Missing GCP_PROJECT_ID variable/secret`
- default managed runtime image mode is private GHCR and provisions `ghcr-pull-secret` in the target namespace before deploy dispatch.
- optional public-image mode can disable this requirement only when explicitly configured.
- private-image auth mode credential contract:
  - `GIT_USERID` (production: `mhanson13`)
  - `GIT_EMAIL` (production: `mhanson13@gmail.com`)
  - `GIT_TOKEN` (PAT never logged/surfaced)
  - `GIT_TOKEN` must include repository/API publish permissions and `read:packages` for GHCR pulls
  - these are resolved from the mbsrn control-plane runtime/admin deployment configuration, not from target site repositories.
  - GitHub repository secrets must be projected into control-plane runtime by `deploy-prod` (`mbsrn-api-auth` + API env). Repository-secret presence by itself does not satisfy readiness.
- deploy readiness diagnostics can surface missing managed GKE config before dispatch via:
  - `dispatch_service_reason_code=missing_cluster_name`
  - `dispatch_service_reason_code=missing_cluster_location`
  - `dispatch_service_reason_code=missing_gcp_project_id`
  - `dispatch_service_reason_code=image_pull_secret_missing` (private-image auth mode)
  - `dispatch_service_reason_code=image_pull_secret_not_referenced` (private-image auth mode)
- dispatch emits `event=seo_migration_dispatch_managed_gke_config_presence` with:
  - `effective_cluster_name_present`
  - `effective_cluster_location_present`
  - `effective_project_id_present`
  - `gke_config_resolution_source`
  to confirm the same effective managed GKE config view used by readiness is also used at dispatch time.
- ownership/remediation interpretation:
  - `missing_cluster_*` / `missing_gcp_project_id`:
    admin-owned managed target configuration blockers (fix MBSRN admin deployment settings first; repo vars/secrets are legacy fallback only)
  - `image_pull_secret_missing`:
    admin/runtime deployment-credential blocker in private-image auth mode (configure `GIT_USERID`, `GIT_EMAIL`, `GIT_TOKEN` in mbsrn control-plane deployment settings and verify `deploy-prod` projected them into runtime)
  - `image_pull_secret_not_referenced`:
    managed-manifest alignment blocker in private-image auth mode (republish managed manifests so deployment references `ghcr-pull-secret`)
  - `runtime_credential_missing` with `secret_name=GCP_DEPLOY_KEY`:
    admin-owned managed deploy secret blocker (configure/rotate secret in MBSRN Admin first, then republish to propagate)
  - `managed_site_static_ip_config_missing`:
    admin-owned static IP ensure configuration blocker before workflow dispatch (managed project id and/or deploy key missing for control-plane ensure path)
  - `managed_site_static_ip_permission_denied`:
    admin-owned IAM blocker; control-plane identity cannot describe/create global static addresses in configured project
  - `managed_site_static_ip_api_disabled`:
    admin-owned project-service blocker; Compute Engine API disabled for configured managed project
  - `managed_site_static_ip_quota_exceeded`:
    admin-owned quota blocker; global static-address quota exhausted in configured managed project
  - `managed_site_static_ip_project_not_found`:
    admin-owned project-configuration blocker; configured managed deploy project id invalid/inaccessible
  - `managed_site_static_ip_conflict`:
    admin-owned static IP ownership/scope conflict for deterministic per-site address name
  - `managed_site_static_ip_provisioning_failed`:
    admin-owned static IP provisioning blocker before workflow dispatch (unclassified Google API/runtime failure during ensure path)
  - `managed_site_dns_config_missing`:
    admin-owned DNS ensure configuration blocker before workflow dispatch (managed zone/project mapping or deploy key missing)
  - `managed_site_dns_provisioning_failed`:
    admin-owned DNS provisioning blocker before workflow dispatch (Cloud DNS API/runtime failure)
  - `managed_site_dns_conflicting_record`:
    admin-owned DNS record-shape blocker (conflicting non-A record exists at preview hostname)
  - `managed_site_dns_permission_denied`:
    admin-owned DNS IAM blocker for configured project/zone
  - `managed_site_dns_transaction_conflict`:
    DNS transaction contention blocker; retry after concurrent writer contention clears
  - `managed_site_dns_propagation_pending`:
    control-plane DNS ensure completed but bounded resolver propagation check did not yet observe the expected static-IP `A` record; wait for propagation and retry
  - `duplicate_request`:
    prior workflow run is still active for the selected deploy tuple
  - `deploy_blocker_reconciliation_failed`:
    GitHub reconciliation for an aged active blocker failed; run status must be refreshed/verified
  - `stale_deploy_blocker_requires_refresh`:
    stale blocker could not be reconciled automatically; manual refresh confirmation required
  - `deploy_blocker_superseded_after_stale_threshold`:
    stale blocker exceeded hard stale threshold and was auto-superseded because no reliable active-run evidence remained
- readiness precedence:
  - when `missing_cluster_*`/`missing_gcp_project_id` is present, treat that as the authoritative blocker before dispatch/workflow troubleshooting
  - only move to GitHub workflow runtime diagnostics after readiness reports managed target configuration blockers cleared

Deploy-secret propagation diagnostics:
- publish/deploy diagnostics include:
  - `deploy_secret_propagation_attempted`
  - `deploy_secret_propagation_status`
  - `deploy_secret_propagation_reason`
  - `deploy_secret_propagation_source` (`admin_managed_secret` or `runtime_env_fallback`)
- expected managed-path behavior is `deploy_secret_propagation_source=admin_managed_secret`; `runtime_env_fallback` should be treated as compatibility mode and remediated to admin-managed secret configuration.

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
  - managed workflow emits bounded namespace-scoped diagnostics on timeout:
    - `kubectl get deployment site-web -n <namespace> -o wide`
    - `kubectl get rs -n <namespace> -o wide`
    - `kubectl get pods -n <namespace> -o wide`
    - `kubectl describe deployment site-web -n <namespace>`
    - `kubectl describe pods -n <namespace> -l app.kubernetes.io/name=site-web`
    - tail logs for recent `site-web` pods (`--tail=200`)
  - workflow output includes heuristic blocker hints when signatures are detected:
    - image pull failure
    - private registry authentication failure (`failed to fetch anonymous token`, `403 Forbidden`, `unauthorized`)
    - container image not found in registry (`manifest unknown`, `name unknown`, `...: not found`)
    - pod crash/startup failure
    - probe failure
      - if probe events show `connection refused`, confirm managed site runtime port wiring is aligned (`containerPort=8080`, probe port `8080`, service `targetPort=8080`)
      - if probe events are green but `curl -i http://127.0.0.1:8080/` inside the pod returns `Empty reply from server`, treat this as app/runtime serving failure (not ingress wiring). Managed template now sets `HOSTNAME=0.0.0.0` and `PORT=8080` explicitly so root-path HTTP responses are health-checkable.
    - config/secret reference failure
    - namespace ResourceQuota rejection (`FailedCreate`, `exceeded quota`, `requested` > `limited`)
    - scheduling/resource pressure
  - blocker-hint precedence is describe-event-first:
    - image pull signatures (`ImagePullBackOff`, `ErrImagePull`, pull denied/not found) are treated as primary for the current diagnostic pass
    - when image pull blockers are detected, crash/probe hints are suppressed unless direct current describe evidence shows a started container failure
    - recent pod logs are supplemental context only; primary blocker hints come from namespace-scoped `kubectl describe` evidence
  - if output includes image-pull signatures (`image pull backoff`, `image pull forbidden`, `public image pull failed`, `private image pull forbidden`, `image pull secret missing`, `image pull secret not referenced`):
    - for default public-image mode:
      - verify image path/tag exists in GHCR for the owner-scoped runtime image reference
      - no `imagePullSecrets` should be required
    - for private-image auth mode:
      - confirm control-plane pull-secret provisioning step succeeded before dispatch
      - confirm deployment pod template references `imagePullSecrets: [{name: ghcr-pull-secret}]`
      - confirm the namespace-scoped secret exists:
        - `kubectl get secret ghcr-pull-secret -n <namespace>`
      - confirm required mbsrn control-plane runtime secrets are configured:
        - `GIT_USERID` (production: `mhanson13`)
        - `GIT_EMAIL` (production: `mhanson13@gmail.com`)
        - `GIT_TOKEN` (PAT value must never be printed in logs)
    - confirm the selected runtime image is owner+repo scoped to the exact target:
      - `site_runtime_image_reference` should match `ghcr.io/<target-repo-owner>/<target-repo-name>-site-web:<tag>`
      - owner mismatch can produce GHCR 403/unauthorized signals even when pull-secret wiring exists
    - if managed workflow/template was recently updated, run a non-dry-run publish first so the target repo receives the latest workflow/manifests before retrying deploy
  - managed runtime image selection telemetry:
    - workflow logs `Managed site runtime image selected: <image-ref> (mode=<mode>)`
    - workflow outputs include:
      - `site_runtime_image_reference`
      - `site_runtime_image_selection_mode` (`immutable_sha` or `fallback_latest`)
    - selection behavior:
      - `immutable_sha` when configured SHA tag exists in GHCR
      - `fallback_latest` when immutable SHA metadata is missing/invalid/unavailable

Controlled runtime image rollouts (managed site runtime image):
- supported tag controls:
  - `MBSRN_SITE_WEB_IMAGE_TAG` (preferred)
  - `SITE_WEB_IMAGE_TAG` (legacy alias fallback)
- copy/paste examples (SHA-like tags supported: 7-64 hex chars):
  - `MBSRN_SITE_WEB_IMAGE_TAG=3f2c9e7d8a6b4c1e9f0a1234567890abcdef1234`
  - `SITE_WEB_IMAGE_TAG=3f2c9e7d8a6b4c1e9f0a1234567890abcdef1234`
- effective selection order:
  1. configured SHA-like tag exists in GHCR -> `site_runtime_image_selection_mode=immutable_sha`
  2. otherwise -> `site_runtime_image_selection_mode=fallback_latest` (`ghcr.io/<target-repo-owner>/<target-repo-name>-site-web:latest`)
  - operator/admin procedure:
  1. ensure target repo content has been published for the intended site revision.
  2. set `MBSRN_SITE_WEB_IMAGE_TAG` (or `SITE_WEB_IMAGE_TAG`) in the controlling GitHub Actions vars/secrets context.
  3. run managed deploy.
  4. verify workflow outputs/logs:
     - `site_runtime_image_reference`
     - `site_runtime_image_selection_mode`
     - `site_runtime_image_repository`
     - `site_runtime_source_commit`
  5. confirm controlled pinning by checking `site_runtime_image_selection_mode=immutable_sha`.
- fallback interpretation:
  - if configured tag is missing, invalid, or unavailable in GHCR, deploy intentionally falls back to `:latest` (`fallback_latest`).
  - inspect workflow output `site_runtime_image_selection_mode` and runtime-image log line first before debugging rollout.
- safety note:
  - use immutable SHA pinning for controlled rollouts and staged production validation; `:latest` is backward-compatible but less deterministic.

    - if output includes `dispatch_service_reason_code=deployed_content_identity_mismatch`:
      - rendered deployment image identity does not match the selected site repo tuple.
      - republish managed files and redeploy so deployment image repository resolves to `ghcr.io/<owner>/<repo>-site-web`.
    - if output includes `container image not found in registry`:
      - confirm selected image exists (`site_runtime_image_reference`), or check fallback image:
        - `docker pull ghcr.io/<target-repo-owner>/<target-repo-name>-site-web:latest`
      - confirm target repo deploy workflow successfully completed a runtime build+push for the same repo/sha.
      - if SHA mode is intended, set `MBSRN_SITE_WEB_IMAGE_TAG`/`SITE_WEB_IMAGE_TAG` to a known published SHA and retry deploy
    - if publish succeeds only with SHA tags, verify `latest` tag publication/retention policy before retrying deploy
    - if rollout repeatedly attempts the wrong/stale image, delete and recreate `site-web` to clear stale Deployment state:
      - `kubectl delete deployment site-web -n <namespace> --ignore-not-found`
      - `kubectl apply -f k8s/deployment.yaml`

Post-fix rollout for existing managed sites:
- For sites published before the site-scoped runtime image fix:
  1. run non-dry-run publish (republish managed workflow/manifests)
  2. run non-dry-run deploy
  3. run deploy refresh/status and verify runtime image evidence
- Verify readiness/diagnostics rollout state:
  - `managed_workflow_not_yet_republished`: managed files still legacy; republish required
  - `workflow_republished_but_deploy_not_rerun`: republished but not yet redeployed
  - `deploy_running_old_generic_image`: observed deploy still on legacy generic image
  - `deploy_running_expected_site_scoped_image`: fix active
- Treat these as legacy generic image indicators:
  - `ghcr.io/mhanson13/site-web:latest`
  - `ghcr.io/<owner>/site-web:latest`
- Treat this as expected post-fix pattern:
  - `ghcr.io/<owner>/<repo>-site-web:<sha-or-latest>`
- First-time config-save behavior:
  - after publish/deploy target save, workspace now performs a full readiness refresh in the same action cycle.
  - deploy availability should appear after one save/provision pass; if not, run explicit refresh and inspect target-readiness logs before repeating saves.
  - if output includes quota signatures such as `exceeded quota: site-resources` or `requested: requests.memory ... limited: requests.memory ...`:
    - inspect quota + workload requests in the same namespace:
      - `kubectl describe resourcequota site-resources -n <namespace>`
      - `kubectl get deployment site-web -n <namespace> -o yaml`
    - remediate by aligning managed workload requests with namespace quota defaults (do not remove quota protections).
- `service_ingress_verification_failed` / `ingress_verify`: service or ingress verification failed.
- `ingress_endpoint_not_ready` / `ingress_evidence`: deployment ran but ingress endpoint did not become available before bounded workflow evidence timeout (ingress/load balancer provisioning still in progress is a common cause).
- `ingress_address_pending_but_hostname_reachable` / `ingress_evidence`: expected hostname responds before ingress status reports external address; treat as address propagation lag, not immediate workload failure.
- `reachable_but_tls_certificate_mismatch` / `ingress_evidence`: expected hostname is reachable but serving a mismatched certificate; verify ingress annotation + ManagedCertificate domain identity.
- `production_db_mode_invalid` / `manifest_apply`: production deploy DB mode is not aligned to the direct cloud-native Postgres contract (`DB_CONNECTION_MODE` must be `direct` for `deploy-prod.yml`).
- `Invalid production DATABASE_URL: localhost/loopback target is not allowed for deploy-prod` / `manifest_apply`: production `DATABASE_URL` still resolves to loopback while running direct mode. Update the GitHub repo `DATABASE_URL` secret to a non-loopback cluster/service hostname or managed Postgres endpoint, then redeploy.
- `cloudsql_instance_inspection_failed` / `manifest_apply`: Cloud SQL preflight could not inspect instance state (for example permission denied, not found/project mismatch, API unavailable, or empty describe output). This is expected only on intentionally proxy-backed paths.
- `cloudsql_instance_invalid_state` / `manifest_apply`: Cloud SQL proxy hit `invalidState` while fetching ephemeral certs during migration job startup. This is expected only on intentionally proxy-backed paths.
- `cloudsql_proxy_ephemeral_cert_failed` / `manifest_apply`: Cloud SQL proxy could not fetch ephemeral certs.
- `cloudsql_proxy_connection_failed` / `manifest_apply`: migration app container lost localhost DB connection through proxy.

Production DB mode contract (`deploy-prod.yml`):
- `DB_CONNECTION_MODE=direct`
- `DATABASE_URL` from `mbsrn-api-auth.DATABASE_URL`
- no Cloud SQL instance inspection preflight in the direct production branch
- no `cloud-sql-proxy` sidecar dependency in production API/migration manifests

Cloud SQL reason codes remain available for optional proxy-backed workflows only.

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
  - `workflow_run_tracking_lost`: dispatch was recorded but workflow run evidence was not recoverable (`workflow_not_found`); control plane marks the prior attempt terminal so retry can proceed.

Draft preview auth context guidance:
- if migration preview shows `draft_preview_route_requires_operator_session` or `draft_preview_auth_context_missing`, the preview iframe blocked an app-auth/external navigation target.
- this is expected for safety: iframe preview keeps operator-session content sandboxed and does not follow app-auth redirects inside the draft renderer.
- use in-app operator routes for authenticated navigation; use draft preview only for generated artifact HTML inspection.

Local-only validation note:

- For optional local verification against GitHub APIs, use `GIT_TOKEN` with a local test token value in local environment only.
- Never print/log/commit token values. Production runtime should continue using infrastructure-managed `GIT_TOKEN` wiring.

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


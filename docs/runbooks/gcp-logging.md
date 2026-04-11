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

Key non-secret fields:

- `target.resolved_workflow_source` (`publish_history_workflow`, `workspace_config_workflow`, `default_workflow`)
- `failure_reason_code` / `target.failure_reason_code`
- `failure_stage` (`repo_lookup`, `workflow_lookup`, `workflow_dispatch`)
- `workflow_id`, optional `workflow_path`, `ref`, `repo_owner`, `repo_name`

Reason-code guidance:

- `repo_not_found`: repository lookup failed for owner/repo.
- `workflow_not_found`: repository exists, but requested workflow id/path was not found.
- `branch_not_found_or_ref_invalid`: dispatch ref is invalid or missing in target repo.
- `workflow_dispatch_not_supported`: workflow exists but does not expose `workflow_dispatch`.
- `token_not_authorized`: runtime token lacks required repository/workflow permissions.

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

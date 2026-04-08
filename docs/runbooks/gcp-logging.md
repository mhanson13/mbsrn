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
- scoped identifiers (`business_id`, `site_id`, `workspace_id`)

Interpretation:
- `supported=false` with `decision=blocked_local_preflight` means migration draft generation was blocked locally before outbound provider invocation.
- `reason_code` identifies the stable compatibility failure class (for example `unsupported_model_configuration`).
- inspect `model`, `endpoint_path`, `execution_mode`, and `response_format_mode` together as the effective request-shape key.
- for summary payload troubleshooting, also inspect `context_summary.migration_diagnostics.draft_provider_compatibility_admin_summary` for sanitized matrix decision detail.
- model resolution precedence for compatibility checks is: explicit/requested -> business admin default (`default_ai_model`) -> env fallback (`AI_MODEL_NAME`) -> provider fallback.

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

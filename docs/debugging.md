# Debugging

## Detecting Stale Prompt Rendering

Symptoms:

- Preview body contains sections from an older prompt revision.
- `prompt_version` label does not match `PROMPT_VERSION:` inside prompt text.
- Duplicate sections such as repeated `PLATFORM_CONSTRAINTS` blocks.

Checks:

1. Inspect raw workspace summary JSON for `competitor_prompt_preview` / `recommendation_prompt_preview`.
2. Verify UI renders `*_prompt_preview.user_prompt` exactly as returned.
3. Confirm no fallback/merge from `latest_run` fields into preview prompt text.

## Verifying Prompt Source Fields

For each preview object, validate:

- `prompt_type`
- `system_prompt`
- `user_prompt`
- `prompt_version`
- `prompt_label`
- `source`
- `truncated`

Expected behavior:

- Prompt body comes only from `system_prompt` + `user_prompt`.
- `prompt_version` is metadata and should align with the effective prompt marker when present.
- `truncated` must reflect actual payload truncation.

## Verifying Recommendation Run Creation From Workspace

When operators use `Generate Recommendations` in the site workspace:

1. Confirm the recommendation sections show a status message after click (`queued`, `running`, `completed`, or `failed`).
2. Confirm a new row appears in `Recommendation Runs and Narratives` with the expected run ID/status.
3. Confirm queue counts and latest workspace summary refresh after run creation.

If generation is blocked, the workspace should show one of:

- prerequisite warning: no completed audit/comparison input is available
- actionable API validation error returned by the backend (HTTP 422 detail)

## Competitor Runtime Debug Fields

When diagnosing competitor-generation quality, use run-detail provider attempt metadata as runtime truth:

- `endpoint_path`: actual endpoint used for the attempt.
- `web_search_enabled`: whether search tooling was enabled.
- `degraded_mode`: whether the attempt ran in timeout retry mode.
- `reduced_context_mode`: whether optional context was trimmed for retry safety.
- `request_duration_ms` and `timeout_seconds`: timeout pressure indicators.

Common interpretations:

- `/responses` + `web_search_enabled=true`: search-backed discovery path.
- `/chat/completions` + `web_search_enabled=false`: explicit capability downgrade (web search unsupported for request/model).
- `degraded_mode=true` and `reduced_context_mode=true`: timeout retry path was used.

Timeout tuning notes:

- `timeout_seconds` reflects the effective timeout used for that attempt.
- Primary attempts use `competitor_primary_timeout_seconds` when configured.
- Degraded retry attempts use `competitor_degraded_timeout_seconds` when configured.
- If a timeout setting is unset, runtime falls back to deployment/provider default timeout behavior.

Pattern checks:

- repeated first-attempt timeout with quick degraded recovery usually indicates primary timeout is too low.
- repeated timeout on both attempts usually indicates network/provider latency pressure; consider raising both timeout settings within the allowed range.

## Troubleshooting Incorrect Industry/Service Context

If workspace competitor prompts show the wrong trade context (for example stale roofing context on a newly repointed site):

1. Verify the site URL/domain was updated on the site record (`base_url`, `normalized_domain`).
2. Check whether `industry` is explicitly set on the site:
   - explicit `industry` is treated as strong context.
   - when domain changes, stale explicit `industry` is now cleared unless a replacement value is supplied in the same update.
3. Verify audit coverage for the current domain:
   - competitor context inference now only uses audit pages whose host matches the current site domain.
   - old-domain audit pages are ignored for context derivation.
4. Regenerate workspace summary and inspect `competitor_prompt_preview` -> `SITE_CONTEXT_JSON` to confirm:
   - `site_normalized_domain` matches the intended site/vendor.
   - `site_industry_context` and `service_focus_terms` align with current-domain data.
5. Inspect `competitor_prompt_preview.prompt_metrics` for service-focus provenance:
   - `service_focus_source_site_content`
   - `service_focus_source_structured_metadata`
   - `service_focus_source_domain_hints`
   - `service_focus_source_explicit_industry`
   - `service_focus_source_fallback`
   - `service_focus_terms_dropped_count`

Interpretation for contaminated `service_focus_terms`:

- `service_focus_source_site_content=1` with `service_focus_terms_dropped_count>0` indicates contradictory fallback/explicit terms were filtered.
- `service_focus_source_explicit_industry=1` with no site-content source indicates service focus is currently driven by explicit industry/fallback signals (verify if this is intentional).
- `service_focus_source_domain_hints=1` means only low-confidence identity hints were available; run a fresh audit for stronger grounding.

When no matching current-domain signals exist, context intentionally degrades to weak/unknown instead of preserving stale strong classifications.

## Invalid Candidate Diagnostics

Rejected competitor debug reasons now include specific invalid-input classifications:

- `missing_domain`
- `malformed_url`
- `missing_business_name`
- `unsupported_type`
- `invalid_confidence_score`
- `low_usefulness_unknown`

Use these to distinguish malformed model output from normal relevance/tuning exclusions.

## Competitor Outcome Message Mapping

Workspace competitor outcome messages map directly to run-detail telemetry:

- `Run quality: proposed/returned/rejected...`
  - `proposed`: `candidate_pipeline_summary.proposed_candidate_count` (fallback: `run.requested_candidate_count`)
  - `returned`: `candidate_pipeline_summary.final_candidate_count` (fallback: `drafts.length`)
  - `rejected`: `proposed - returned`
- `degraded mode yes`
  - `provider_degraded_retry_used=true` or any `provider_attempts[].degraded_mode=true`
- `search-backed no`
  - provider attempts include `web_search_enabled=false` and no attempt with `web_search_enabled=true`
- low-result warning (`Only 0/1 valid competitor remained...`)
  - terminal completed run with `returned <= 1`
  - likely-cause clauses appear only when matching telemetry supports them

## Malformed Output Reason Codes

When a competitor run fails with `failure_category=malformed_output`, provider-attempt debug may include:

- `failure_kind=malformed_output`
- `malformed_output_reason` with one of:
  - `json_decode_error`
  - `wrapped_in_markdown`
  - `missing_candidates_array`
  - `invalid_top_level_shape`
  - `partial_json`
  - `invalid_field_types`

Interpretation:

- `json_decode_error` / `partial_json`: no safe JSON payload could be recovered.
- `wrapped_in_markdown`: model response was wrapped and could not be safely recovered as valid payload.
- `missing_candidates_array` / `invalid_top_level_shape`: payload shape did not match the required top-level candidate contract.
- `invalid_field_types`: payload structure existed but candidate entries failed required field typing/coercion safety.

Failure vs salvage rule:

- If at least one safe candidate can be recovered, generation proceeds with partial salvage.
- If no safe usable candidate payload can be recovered, the run fails as malformed output.

## Cloud Logging Queries (Competitor Provider)

Competitor provider attempts now emit structured request lifecycle events:

- `competitor_provider_request_start`
- `competitor_provider_request_complete`
- `competitor_provider_request_error`

Primary structured fields:

- `event`
- `run_id`
- `attempt_number`
- `endpoint_path`
- `model`
- `web_search_enabled`
- `degraded_mode`
- `reduced_context_mode`
- `failure_kind` (error events)
- `malformed_output_reason` (malformed-output errors)
- `duration_ms`

Safety notes:

- raw prompt text is never logged
- raw model response text is never logged
- credentials/headers are never logged

Sample Logs Explorer queries:

- `jsonPayload.event="competitor_provider_request_start"`
- `jsonPayload.event="competitor_provider_request_complete"`
- `jsonPayload.event="competitor_provider_request_error"`
- `jsonPayload.event="competitor_provider_request_error" AND jsonPayload.failure_kind="malformed_output"`
- `jsonPayload.event="competitor_provider_request_error" AND jsonPayload.endpoint_path="/responses"`
- `jsonPayload.event="competitor_provider_request_error" AND jsonPayload.run_id="<run_id>"`

## In-App GCP Logs Query (Admin Tab)

The admin tab now includes a `GCP Logs Query` tool that proxies Cloud Logging `entries.list` through the backend.

Auth and runtime model:

- app user must be an admin principal (non-admins are denied)
- backend authenticates to GCP with Application Default Credentials from the runtime attached service account
- no user OAuth scopes and no browser-side GCP credentials are required

Required backend project configuration:

- `GCP_PROJECT_ID`
- value format: GCP project id string, for example `my-prod-project-123`

If project configuration is missing, the API returns a 503 with an actionable message naming the expected env vars.

Scope and paging limits:

- query scope is fixed to the configured project: `projects/<configured-project>`
- order is fixed to `timestamp desc`
- page size is bounded to `1..100` (UI options: 10, 25, 50, 100)
- pagination uses Cloud Logging `nextPageToken` via the `Next Page` action

Runtime IAM requirement:

- deployed runtime service account must have Cloud Logging read permission on the configured project (for example `logging.logEntries.list`, commonly provided by Logs Viewer or equivalent custom role)

Deployment prerequisites (Workload Identity + env wiring):

- GKE cluster has Workload Identity enabled (`workloadIdentityConfig.workloadPool` is set).
- API deployment uses Kubernetes service account `mbsrn-api`.
- KSA `mbsrn-api` is annotated with runtime GSA:
  - `iam.gke.io/gcp-service-account=<runtime-gsa>@<project>.iam.gserviceaccount.com`
- Runtime GSA policy includes:
  - `roles/iam.workloadIdentityUser` for `serviceAccount:<project>.svc.id.goog[mbsrn/mbsrn-api]`
  - `roles/logging.viewer` (or approved equivalent) on the logging project
- API pod env includes project id:
  - `GCP_PROJECT_ID`

Repo/cluster preflight helper (read-only):

- `python scripts/verify_gcp_logs_wiring.py`
- `python scripts/verify_gcp_logs_wiring.py --cluster --project-id <PROJECT_ID> --gsa-email <RUNTIME_GSA_EMAIL>`

Manual cluster verification commands:

```bash
# API deployment must use expected KSA
kubectl -n mbsrn get deploy mbsrn-api -o jsonpath='{.spec.template.spec.serviceAccountName}{"\n"}'

# KSA must be mapped to a GSA
kubectl -n mbsrn get sa mbsrn-api -o jsonpath='{.metadata.annotations.iam\.gke\.io/gcp-service-account}{"\n"}'

# Workload Identity must be enabled on cluster
gcloud container clusters describe <CLUSTER_NAME> --location <CLUSTER_LOCATION> \
  --project <PROJECT_ID> \
  --format='value(workloadIdentityConfig.workloadPool)'

# Runtime env wiring in pod
kubectl -n mbsrn exec deploy/mbsrn-api -- sh -c \
  'env | egrep "GCP_PROJECT_ID"'
```

Manual setup commands (no automatic IAM mutation in app deploy):

```bash
# Annotate KSA -> GSA mapping
kubectl -n mbsrn annotate sa mbsrn-api \
  iam.gke.io/gcp-service-account=<RUNTIME_GSA_EMAIL> \
  --overwrite

# Allow KSA to impersonate GSA via Workload Identity
gcloud iam service-accounts add-iam-policy-binding <RUNTIME_GSA_EMAIL> \
  --project <PROJECT_ID> \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:<PROJECT_ID>.svc.id.goog[mbsrn/mbsrn-api]"

# Grant Cloud Logging read access to runtime GSA
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member "serviceAccount:<RUNTIME_GSA_EMAIL>" \
  --role roles/logging.viewer

# Restart API so refreshed identity/env are picked up
kubectl -n mbsrn rollout restart deployment/mbsrn-api
kubectl -n mbsrn rollout status deployment/mbsrn-api --timeout=300s
```

Returned rows are sanitized and compact:

- `timestamp`, `severity`, `log_name`, `resource_type`, `insert_id`
- bounded `labels` / `resource_labels`
- bounded payload summaries (`textPayload`, `jsonPayload`, `protoPayload`)

Sample filters (copy into the admin query box):

- `jsonPayload.event="competitor_provider_request_start"`
- `jsonPayload.event="competitor_provider_request_complete"`
- `jsonPayload.event="competitor_provider_request_error"`
- `jsonPayload.event="competitor_provider_request_error" AND jsonPayload.failure_kind="malformed_output"`
- `jsonPayload.failure_kind="malformed_output" AND jsonPayload.malformed_output_reason:*`
- `jsonPayload.event="competitor_provider_request_error" AND jsonPayload.endpoint_path="/responses"`
- `jsonPayload.event="competitor_provider_request_start" AND jsonPayload.run_id="<run_id>"`
- `jsonPayload.event="competitor_provider_request_complete" AND jsonPayload.run_id="<run_id>"`

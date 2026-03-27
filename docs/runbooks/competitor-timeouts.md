# Competitor Timeouts Runbook

## Purpose
Use this runbook to diagnose competitor generation timeout patterns and verify execution-mode routing.

## Expected Routing
Per run attempt:

- `execution_mode=fast_path` -> `provider_call_type=non_tool` -> `web_search_enabled=false`
- `execution_mode=full` -> `provider_call_type=tool_enabled` -> `web_search_enabled=true`
- `execution_mode=degraded` -> `provider_call_type=non_tool` -> `web_search_enabled=false`

`full` is the only mode that should use tooling/web search.

## How To Identify Tool Misuse
Check structured provider logs for mismatches:

- Invalid: `execution_mode=fast_path` with `provider_call_type=tool_enabled`
- Invalid: `execution_mode=degraded` with `provider_call_type=tool_enabled`
- Invalid: `execution_mode=degraded` with `web_search_enabled=true`

If any invalid combination appears, treat as a routing bug and block rollout.

## Cloud Logging Queries
Use these filters in Logs Explorer:

- `jsonPayload.event="competitor_provider_request_start"`
- `jsonPayload.event="competitor_provider_request_complete"`
- `jsonPayload.event="competitor_provider_request_error"`
- `jsonPayload.event="competitor_provider_request_start" AND jsonPayload.execution_mode="fast_path"`
- `jsonPayload.event="competitor_provider_request_start" AND jsonPayload.execution_mode="full"`
- `jsonPayload.event="competitor_provider_request_start" AND jsonPayload.execution_mode="degraded"`
- `jsonPayload.event="competitor_provider_request_error" AND jsonPayload.failure_kind="timeout"`

## Timeout Diagnosis Flow
1. Find all provider attempts for a run id.
2. Confirm attempt sequence and routing:
   - attempt `0` fast_path non_tool
   - attempt `1` full tool_enabled
   - attempt `2` degraded non_tool only when full timed out
3. Compare `duration_ms` vs `timeout_seconds_used`.
4. If repeated full-attempt timeouts occur with degraded recoveries, tune timeout settings.
5. If full and degraded both time out repeatedly, investigate provider/network latency and prompt size pressure.

## Verification Checklist
- Fast path uses non-tool provider call.
- Full attempt is the only tool-enabled call.
- Degraded retry uses non-tool provider call and no web search.
- No repeated timeout loops beyond the designed attempt sequence.
- If fast_path returns zero valid candidates, a full search-backed attempt should follow with
  `provider_attempts[0].search_escalation_triggered=true` and
  `provider_attempts[0].escalation_reason="zero_valid_competitors"`.

## Candidate Filtering Checklist
If competitor volume is low, inspect candidate pipeline observability before changing prompts or timeouts.

1. Query `jsonPayload.event="competitor_candidate_rejection_summary"` for the run id.
2. Compare:
   - `raw_count` vs `valid_count` (provider-side candidate quality)
   - `rejected_by_eligibility`
   - `removed_by_existing_domain_match`
   - `removed_by_deduplication`
   - `removed_by_final_limit`
3. Query `jsonPayload.event="competitor_candidate_rejected"` for candidate-level reason samples.

Interpretation guide:
- `raw_count=0` and `valid_count=0`: provider returned an empty candidate set (valid empty outcome).
- `valid_count>0` and `final_count=0`: candidates were filtered out post-provider; check rejection reasons before retrying.
- High `raw_count` with low `valid_count`: provider returned mostly unusable candidates.
- High `rejected_by_eligibility`: local eligibility rules filtered many candidates.
- High `removed_by_existing_domain_match`: many candidates already exist in the site competitor set.
- High `removed_by_deduplication`: many near-duplicate domains were collapsed.
- High `removed_by_final_limit`: discovery produced more viable candidates than requested; no failure implied.

### Regression Indicators
- Any `fast_path` or `degraded` event with `provider_call_type="tool_enabled"`.
- Any `fast_path` or `degraded` event with `web_search_enabled=true`.
- Missing `execution_mode` or `provider_call_type` on provider start/complete/error events.
- Missing `duration_ms` on provider complete/error events.

### Inspect First If Timeouts Recur
- `competitor_provider_request_start`/`complete`/`error` events for the same `run_id`.
- Attempt ordering (`attempt_number` 0 -> 1 -> 2) and routing mode per attempt.
- `duration_ms` vs `timeout_seconds_used` to confirm true timeout pressure vs routing regression.

## TODO
- Formalize provider abstraction with explicit `tool_enabled` and `non_tool` interfaces.

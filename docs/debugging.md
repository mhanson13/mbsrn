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

## Invalid Candidate Diagnostics

Rejected competitor debug reasons now include specific invalid-input classifications:

- `missing_domain`
- `malformed_url`
- `missing_business_name`
- `unsupported_type`
- `invalid_confidence_score`
- `low_usefulness_unknown`

Use these to distinguish malformed model output from normal relevance/tuning exclusions.

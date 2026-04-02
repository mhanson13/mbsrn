from __future__ import annotations

from typing import Any, Mapping, Sequence


TERMINAL_AUTOMATION_RUN_STATUSES = {"completed", "failed", "skipped"}


def normalize_automation_status(value: Any) -> str:
    return str(value or "").strip().lower()


def compact_automation_reason(value: Any, *, max_length: int = 220) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    single_line = " ".join(raw.splitlines()).strip()
    if len(single_line) <= max_length:
        return single_line
    return f"{single_line[: max_length - 1].rstrip()}…"


def summarize_automation_step_reason(
    *,
    step_name: str | None,
    status: str | None,
    error_message: str | None,
) -> str | None:
    normalized_status = normalize_automation_status(status)
    normalized_step_name = str(step_name or "").strip().lower()
    normalized_error = compact_automation_reason(error_message)
    if normalized_status not in {"skipped", "failed"}:
        return None
    if normalized_error is None:
        if normalized_status == "skipped":
            return "Skipped because prerequisites were not met."
        return "Failed without a detailed reason."

    lowered_error = normalized_error.lower()

    if normalized_status == "skipped":
        if "disabled by config" in lowered_error:
            return "Skipped because this step is disabled in automation configuration."
        if "snapshot run is not completed" in lowered_error:
            return "Skipped because competitor snapshot output was not completed."
        if "missing competitor_snapshot_run output" in lowered_error:
            return "Skipped because competitor snapshot output was unavailable."
        if "missing completed comparison_run output" in lowered_error:
            return "Skipped because competitor comparison output was not completed."
        if "missing completed recommendation_run output" in lowered_error:
            return "Skipped because recommendation output was not completed."
        if "missing completed audit_run output" in lowered_error:
            return "Skipped because audit output was not completed."
        if "requires audit_run and/or comparison_run output" in lowered_error:
            return "Skipped because required audit or comparison output was unavailable."
        return f"Skipped: {normalized_error}"

    if normalized_step_name == "audit_run" and (
        "crawl" in lowered_error or "fetch" in lowered_error or "http" in lowered_error
    ):
        return "Failed because crawl could not fetch the site base URL."
    if normalized_step_name == "recommendation_narrative":
        if "timeout" in lowered_error:
            return "Failed because narrative generation timed out."
        if "invalid" in lowered_error or "malformed" in lowered_error or "schema" in lowered_error:
            return "Failed because narrative generation returned invalid output."

    return f"Failed: {normalized_error}"


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_metric(steps: Sequence[Mapping[str, Any]], metric_key: str) -> int | None:
    for step in steps:
        metrics = step.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        metric_value = _coerce_int(metrics.get(metric_key))
        if metric_value is not None:
            return metric_value
    return None


def build_automation_run_outcome_summary(
    *,
    run_status: str | None,
    steps: Sequence[Mapping[str, Any]] | None,
    run_error_message: str | None = None,
) -> dict[str, Any] | None:
    normalized_run_status = normalize_automation_status(run_status)
    if normalized_run_status not in TERMINAL_AUTOMATION_RUN_STATUSES:
        return None

    normalized_steps = [step for step in (steps or []) if isinstance(step, Mapping)]
    step_statuses = [normalize_automation_status(step.get("status")) for step in normalized_steps]

    completed_count = sum(1 for step_status in step_statuses if step_status == "completed")
    skipped_count = sum(1 for step_status in step_statuses if step_status == "skipped")
    failed_count = sum(1 for step_status in step_statuses if step_status == "failed")

    if normalized_run_status == "failed" or failed_count > 0:
        terminal_outcome = "failed"
    elif normalized_run_status == "completed" and skipped_count > 0:
        terminal_outcome = "completed_with_skips"
    elif normalized_run_status == "completed":
        terminal_outcome = "completed"
    else:
        terminal_outcome = "partial"

    pages_analyzed_count = _extract_metric(normalized_steps, "pages_analyzed_count")
    issues_found_count = _extract_metric(normalized_steps, "issues_found_count")
    recommendations_generated_count = _extract_metric(
        normalized_steps,
        "recommendations_generated_count",
    )

    metric_parts: list[str] = []
    if pages_analyzed_count is not None:
        metric_parts.append(f"{pages_analyzed_count} pages analyzed")
    if issues_found_count is not None:
        metric_parts.append(f"{issues_found_count} issues found")
    if recommendations_generated_count is not None:
        metric_parts.append(f"{recommendations_generated_count} recommendations generated")

    if terminal_outcome == "completed":
        summary_title = "Automation completed"
    elif terminal_outcome == "completed_with_skips":
        summary_title = "Automation completed with skips"
    elif terminal_outcome == "failed":
        summary_title = "Automation failed"
    else:
        summary_title = "Automation completed partially"

    summary_segments: list[str] = [summary_title]
    if metric_parts:
        summary_segments.append(f"{', '.join(metric_parts)}.")
    summary_segments.append(
        f"{completed_count} completed, {skipped_count} skipped, {failed_count} failed."
    )

    failure_reason = None
    skip_reason = None
    for step in normalized_steps:
        reason_summary = summarize_automation_step_reason(
            step_name=str(step.get("step_name") or ""),
            status=str(step.get("status") or ""),
            error_message=step.get("error_message"),
        )
        if not reason_summary:
            continue
        step_status = normalize_automation_status(step.get("status"))
        if step_status == "failed" and failure_reason is None:
            failure_reason = reason_summary
        elif step_status == "skipped" and skip_reason is None:
            skip_reason = reason_summary
        if failure_reason and skip_reason:
            break

    if terminal_outcome == "failed":
        if failure_reason:
            summary_segments.append(f"Failure signal: {failure_reason}")
        elif compact_automation_reason(run_error_message):
            summary_segments.append(f"Failure signal: {compact_automation_reason(run_error_message)}")
    elif terminal_outcome == "completed_with_skips" and skip_reason:
        summary_segments.append(f"Skipped step signal: {skip_reason}")
    elif terminal_outcome == "partial" and (skip_reason or failure_reason):
        summary_segments.append(f"Partial-result signal: {failure_reason or skip_reason}")

    summary_text = " ".join(summary_segments).strip()

    return {
        "summary_title": summary_title,
        "summary_text": summary_text,
        "pages_analyzed_count": pages_analyzed_count,
        "issues_found_count": issues_found_count,
        "recommendations_generated_count": recommendations_generated_count,
        "steps_completed_count": completed_count,
        "steps_skipped_count": skipped_count,
        "steps_failed_count": failed_count,
        "terminal_outcome": terminal_outcome,
    }

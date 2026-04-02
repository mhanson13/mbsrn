from __future__ import annotations

from app.core.seo_automation_outcome_summary import (
    build_automation_run_outcome_summary,
    summarize_automation_step_reason,
)


def test_build_automation_run_outcome_summary_completed_success() -> None:
    summary = build_automation_run_outcome_summary(
        run_status="completed",
        steps=[
            {
                "step_name": "audit_run",
                "status": "completed",
                "metrics": {
                    "pages_analyzed_count": 42,
                    "issues_found_count": 12,
                },
            },
            {
                "step_name": "recommendation_run",
                "status": "completed",
                "metrics": {
                    "recommendations_generated_count": 5,
                },
            },
        ],
    )

    assert summary is not None
    assert summary["terminal_outcome"] == "completed"
    assert summary["pages_analyzed_count"] == 42
    assert summary["issues_found_count"] == 12
    assert summary["recommendations_generated_count"] == 5
    assert summary["steps_completed_count"] == 2
    assert summary["steps_skipped_count"] == 0
    assert summary["steps_failed_count"] == 0


def test_build_automation_run_outcome_summary_completed_with_skips() -> None:
    summary = build_automation_run_outcome_summary(
        run_status="completed",
        steps=[
            {"step_name": "audit_run", "status": "completed"},
            {
                "step_name": "comparison_run",
                "status": "skipped",
                "error_message": "Snapshot run is not completed; comparison step skipped",
            },
        ],
    )

    assert summary is not None
    assert summary["terminal_outcome"] == "completed_with_skips"
    assert summary["steps_completed_count"] == 1
    assert summary["steps_skipped_count"] == 1
    assert summary["steps_failed_count"] == 0
    assert "Skipped because competitor snapshot output was not completed." in summary["summary_text"]


def test_build_automation_run_outcome_summary_failed() -> None:
    summary = build_automation_run_outcome_summary(
        run_status="failed",
        steps=[
            {"step_name": "audit_run", "status": "completed"},
            {
                "step_name": "recommendation_narrative",
                "status": "failed",
                "error_message": "provider returned malformed schema output",
            },
        ],
    )

    assert summary is not None
    assert summary["terminal_outcome"] == "failed"
    assert summary["steps_failed_count"] == 1
    assert "Failure signal" in summary["summary_text"]


def test_summarize_automation_step_reason_for_audit_fetch_failure() -> None:
    reason = summarize_automation_step_reason(
        step_name="audit_run",
        status="failed",
        error_message="HTTP fetch timeout while crawling the base URL",
    )

    assert reason == "Failed because crawl could not fetch the site base URL."

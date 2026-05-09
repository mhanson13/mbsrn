from __future__ import annotations

from app.core.cloudsql_instance_preflight import classify_cloudsql_instance_inspection


def test_classify_cloudsql_instance_preflight_runnable() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=0,
        instance_state="RUNNABLE",
        stderr_text="",
    )

    assert classification.reason_code is None
    assert classification.message is None
    assert classification.retryable is False
    assert classification.detail is None


def test_classify_cloudsql_instance_preflight_runnable_mixed_case_state() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=0,
        instance_state="rUnNaBlE",
        stderr_text="",
    )

    assert classification.reason_code is None
    assert classification.retryable is False


def test_classify_cloudsql_instance_preflight_non_runnable_state() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=0,
        instance_state="STOPPED",
        stderr_text="",
    )

    assert classification.reason_code == "cloudsql_instance_invalid_state"
    assert classification.retryable is True
    assert classification.detail == "state_stopped"


def test_classify_cloudsql_instance_preflight_unexpected_state_output() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=0,
        instance_state="?? bad-state ??",
        stderr_text="",
    )

    assert classification.reason_code == "cloudsql_instance_invalid_state"
    assert classification.retryable is True
    assert classification.detail == "state_unexpected_output"


def test_classify_cloudsql_instance_preflight_permission_denied() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=1,
        instance_state="",
        stderr_text="ERROR: (gcloud.sql.instances.describe) PERMISSION_DENIED: Permission denied on resource.",
    )

    assert classification.reason_code == "cloudsql_instance_inspection_failed"
    assert classification.retryable is False
    assert classification.detail == "permission_denied"
    assert classification.stderr_summary is not None


def test_classify_cloudsql_instance_preflight_nonzero_without_stderr() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=1,
        instance_state="",
        stderr_text=None,
    )

    assert classification.reason_code == "cloudsql_instance_inspection_failed"
    assert classification.retryable is True
    assert classification.detail == "empty_error_output"
    assert classification.stderr_summary is None


def test_classify_cloudsql_instance_preflight_not_found() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=1,
        instance_state="",
        stderr_text="ERROR: (gcloud.sql.instances.describe) HTTPError 404: The Cloud SQL instance was not found.",
    )

    assert classification.reason_code == "cloudsql_instance_inspection_failed"
    assert classification.retryable is False
    assert classification.detail == "instance_not_found"


def test_classify_cloudsql_instance_preflight_empty_output() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=0,
        instance_state="",
        stderr_text="",
    )

    assert classification.reason_code == "cloudsql_instance_inspection_failed"
    assert classification.retryable is True
    assert classification.detail == "empty_state_output"


def test_classify_cloudsql_instance_preflight_sanitizes_stderr_summary() -> None:
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=1,
        instance_state="",
        stderr_text=("ERROR token=/home/runner/work/_temp/creds.json " "for project:region:instance permission denied"),
    )

    assert classification.reason_code == "cloudsql_instance_inspection_failed"
    assert classification.stderr_summary == "sensitive content redacted"

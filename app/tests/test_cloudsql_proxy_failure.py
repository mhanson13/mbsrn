from __future__ import annotations

from app.core.cloudsql_proxy_failure import classify_cloudsql_proxy_failure


def test_classify_cloudsql_proxy_failure_invalid_state() -> None:
    classification = classify_cloudsql_proxy_failure(
        proxy_log_text=(
            "cloud-sql-proxy: fetch ephemeral cert failed for instance "
            "project:us-central1:mbsrn-prod: Error 409 invalidState"
        ),
        app_log_text=None,
    )
    assert classification.reason_code == "cloudsql_instance_invalid_state"
    assert classification.retryable is True


def test_classify_cloudsql_proxy_failure_ephemeral_cert_failure() -> None:
    classification = classify_cloudsql_proxy_failure(
        proxy_log_text="cloud-sql-proxy: fetch ephemeral cert failed for instance project:region:db",
        app_log_text=None,
    )
    assert classification.reason_code == "cloudsql_proxy_ephemeral_cert_failed"
    assert classification.retryable is True


def test_classify_cloudsql_proxy_failure_connection_closed() -> None:
    classification = classify_cloudsql_proxy_failure(
        proxy_log_text=(
            "cloud-sql-proxy accepted connection from 127.0.0.1\n"
            "postgresql server: connection closed unexpectedly"
        ),
        app_log_text="DATABASE_URL=postgresql://...@localhost:5432/mbsrn connection closed unexpectedly",
    )
    assert classification.reason_code == "cloudsql_proxy_connection_failed"
    assert classification.retryable is False


def test_classify_cloudsql_proxy_failure_returns_none_for_unrelated_logs() -> None:
    classification = classify_cloudsql_proxy_failure(
        proxy_log_text="rollout succeeded",
        app_log_text="application healthy",
    )
    assert classification.reason_code is None
    assert classification.message is None
    assert classification.retryable is False

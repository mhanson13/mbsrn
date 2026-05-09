from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CloudSQLProxyFailureClassification:
    reason_code: str | None
    message: str | None
    retryable: bool


def classify_cloudsql_proxy_failure(
    *,
    proxy_log_text: str | None,
    app_log_text: str | None = None,
) -> CloudSQLProxyFailureClassification:
    proxy_text = str(proxy_log_text or "")
    app_text = str(app_log_text or "")
    normalized = f"{proxy_text}\n{app_text}".lower()

    if not normalized.strip():
        return CloudSQLProxyFailureClassification(
            reason_code=None,
            message=None,
            retryable=False,
        )

    has_invalid_state = "invalidstate" in normalized
    has_ephemeral_cert_failure = "fetch ephemeral cert failed" in normalized
    has_proxy_marker = "cloud-sql-proxy" in normalized or "cloud sql proxy" in normalized
    has_connection_failure = (
        "connection closed unexpectedly" in normalized
        or "connection reset by peer" in normalized
        or "connection refused" in normalized
        or "dial tcp 127.0.0.1:5432" in normalized
        or "dial tcp localhost:5432" in normalized
    )

    if has_invalid_state and has_ephemeral_cert_failure:
        return CloudSQLProxyFailureClassification(
            reason_code="cloudsql_instance_invalid_state",
            message=(
                "Cloud SQL instance rejected ephemeral certificate issuance with invalidState. "
                "Confirm instance is RUNNABLE and retry."
            ),
            retryable=True,
        )
    if has_ephemeral_cert_failure:
        return CloudSQLProxyFailureClassification(
            reason_code="cloudsql_proxy_ephemeral_cert_failed",
            message=(
                "Cloud SQL proxy failed while fetching an ephemeral certificate. "
                "Check Cloud SQL availability/permissions and retry."
            ),
            retryable=True,
        )
    if has_proxy_marker and has_connection_failure:
        return CloudSQLProxyFailureClassification(
            reason_code="cloudsql_proxy_connection_failed",
            message=("Migration container could not keep a localhost database connection through cloud-sql-proxy."),
            retryable=False,
        )

    return CloudSQLProxyFailureClassification(
        reason_code=None,
        message=None,
        retryable=False,
    )

from __future__ import annotations

from dataclasses import dataclass
import re


_MAX_STDERR_SUMMARY_LENGTH = 220
_SENSITIVE_TOKEN_PATTERN = re.compile(
    r"(?i)\b(password|token|secret|authorization|private[_-]?key|client[_-]?email|database_url)\b"
)
_CREDENTIAL_PATH_PATTERN = re.compile(r"(?i)(?:[A-Za-z]:\\|/)[^\s\"']+\.json")
_CLOUDSQL_CONNECTION_NAME_PATTERN = re.compile(
    r"\b[a-z][a-z0-9-]{1,62}:[a-z][a-z0-9-]{1,62}:[a-z][a-z0-9-]{1,62}\b",
    re.IGNORECASE,
)
_VALID_STATE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(frozen=True)
class CloudSQLInstanceInspectionClassification:
    reason_code: str | None
    message: str | None
    retryable: bool
    detail: str | None
    stderr_summary: str | None


def _sanitize_stderr_summary(stderr_text: str | None) -> str | None:
    normalized = str(stderr_text or "").strip()
    if not normalized:
        return None
    collapsed = re.sub(r"\s+", " ", normalized)
    collapsed = _CREDENTIAL_PATH_PATTERN.sub("[path]", collapsed)
    collapsed = _CLOUDSQL_CONNECTION_NAME_PATTERN.sub("[instance-connection-name]", collapsed)
    if _SENSITIVE_TOKEN_PATTERN.search(collapsed):
        return "sensitive content redacted"
    if len(collapsed) <= _MAX_STDERR_SUMMARY_LENGTH:
        return collapsed
    return f"{collapsed[:_MAX_STDERR_SUMMARY_LENGTH - 1]}..."


def _normalize_instance_state(value: str | None) -> str:
    candidate = str(value or "").strip().upper()
    if not candidate:
        return ""
    if _VALID_STATE_PATTERN.fullmatch(candidate):
        return candidate
    return "UNEXPECTED_OUTPUT"


def _classify_inspection_failure_detail(stderr_text: str | None) -> str:
    normalized = str(stderr_text or "").lower()
    if not normalized.strip():
        return "empty_error_output"
    if "permission denied" in normalized or "does not have permission" in normalized:
        return "permission_denied"
    if "not found" in normalized or "was not found" in normalized:
        return "instance_not_found"
    if "api" in normalized and ("not enabled" in normalized or "has not been used" in normalized):
        return "api_unavailable"
    if "unavailable" in normalized or "deadline exceeded" in normalized or "timeout" in normalized:
        return "transient_unavailable"
    return "gcloud_describe_failed"


def _inspection_failure_retryable(detail: str) -> bool:
    if detail in {"permission_denied", "instance_not_found"}:
        return False
    return True


def classify_cloudsql_instance_inspection(
    *,
    describe_exit_code: int,
    instance_state: str | None,
    stderr_text: str | None,
) -> CloudSQLInstanceInspectionClassification:
    state = _normalize_instance_state(instance_state)
    stderr_summary = _sanitize_stderr_summary(stderr_text)

    if describe_exit_code == 0 and state == "RUNNABLE":
        return CloudSQLInstanceInspectionClassification(
            reason_code=None,
            message=None,
            retryable=False,
            detail=None,
            stderr_summary=stderr_summary,
        )

    if describe_exit_code == 0 and state:
        return CloudSQLInstanceInspectionClassification(
            reason_code="cloudsql_instance_invalid_state",
            message=f"Cloud SQL instance state {state} is not RUNNABLE.",
            retryable=True,
            detail=f"state_{state.lower()}",
            stderr_summary=stderr_summary,
        )

    if describe_exit_code == 0 and not state:
        return CloudSQLInstanceInspectionClassification(
            reason_code="cloudsql_instance_inspection_failed",
            message="Cloud SQL instance inspection returned empty state output.",
            retryable=True,
            detail="empty_state_output",
            stderr_summary=stderr_summary,
        )

    detail = _classify_inspection_failure_detail(stderr_text)
    return CloudSQLInstanceInspectionClassification(
        reason_code="cloudsql_instance_inspection_failed",
        message=f"Cloud SQL instance inspection failed ({detail}).",
        retryable=_inspection_failure_retryable(detail),
        detail=detail,
        stderr_summary=stderr_summary,
    )

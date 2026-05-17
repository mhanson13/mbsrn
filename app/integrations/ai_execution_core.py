from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import socket
import time
import urllib.error
import urllib.request

from app.core.log_sanitizer import sanitize_log_payload

_DEFAULT_MAX_ATTEMPTS = 1
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.0
_INPUT_SIZE_BUCKET_SMALL_MAX = 20_000
_INPUT_SIZE_BUCKET_MEDIUM_MAX = 60_000
_INPUT_SIZE_BUCKET_LARGE_MAX = 120_000
_DIFFICULTY_BUCKET_LOW_MAX = 34
_DIFFICULTY_BUCKET_MEDIUM_MAX = 69

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AINormalizedFailure:
    category: str
    reason: str
    source: str
    retryable: bool
    http_status: int | None = None
    timeout_type: str | None = None


@dataclass(frozen=True)
class AIExecutionError(RuntimeError):
    safe_message: str
    normalized_failure: AINormalizedFailure
    raw_response_text: str | None = None
    correlation_id: str | None = None
    duration_ms: int | None = None
    attempt_count: int = 1
    original_input_size: int | None = None
    final_input_size: int | None = None
    trimmed_bytes: int | None = None
    trimming_pass_count: int | None = None
    difficulty_score: int | None = None

    def __str__(self) -> str:
        return self.safe_message


@dataclass(frozen=True)
class AIExecutionResponse:
    body_text: str
    duration_ms: int
    attempt_count: int
    correlation_id: str | None = None
    original_input_size: int | None = None
    final_input_size: int | None = None
    trimmed_bytes: int | None = None
    trimming_pass_count: int | None = None
    difficulty_score: int | None = None


@dataclass(frozen=True)
class AIExecutionPolicy:
    feature_area: str
    timeout_seconds: int
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS
    max_input_size: int | None = None
    original_input_size: int | None = None
    final_input_size: int | None = None
    trimming_pass_count: int = 0
    section_count: int | None = None
    schema_complexity_flag: bool = False
    suppress_timeout_retry_without_size_change: bool = True

    def normalized_timeout_seconds(self) -> int:
        return max(1, int(self.timeout_seconds))

    def normalized_max_attempts(self) -> int:
        return max(1, int(self.max_attempts))

    def normalized_max_input_size(self) -> int | None:
        if self.max_input_size is None:
            return None
        try:
            parsed = int(self.max_input_size)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return parsed


@dataclass(frozen=True)
class AIContextBlock:
    name: str
    value: object
    required: bool
    trim_priority: int = 0


@dataclass(frozen=True)
class AIRequestBudgetResult:
    initial_size_chars: int
    final_size_chars: int
    initial_size_bytes: int
    final_size_bytes: int
    budget_size_chars: int
    dropped_optional_blocks: tuple[str, ...]
    dropped_duplicate_blocks: tuple[str, ...]
    required_blocks_retained: tuple[str, ...]
    optional_blocks_retained: tuple[str, ...]
    trimmed_bytes: int
    trimming_pass_count: int
    section_count: int
    overflow: bool


@dataclass(frozen=True)
class AIRequestBudgetDecision:
    retained_blocks: dict[str, object]
    result: AIRequestBudgetResult


def apply_request_budget(
    *,
    blocks: list[AIContextBlock],
    budget_size_chars: int,
) -> AIRequestBudgetDecision:
    normalized_budget = max(1, int(budget_size_chars))

    required_blocks = [block for block in blocks if block.required]
    optional_blocks = [block for block in blocks if not block.required]
    optional_blocks = sorted(optional_blocks, key=lambda item: item.trim_priority, reverse=True)

    serialized_cache: dict[str, str] = {}
    dropped_duplicate_blocks: list[str] = []
    seen_serialized: set[str] = set()
    deduped_optional_blocks: list[AIContextBlock] = []
    for block in optional_blocks:
        serialized = _serialize_for_budget(block.value)
        serialized_cache[block.name] = serialized
        if serialized in seen_serialized:
            dropped_duplicate_blocks.append(block.name)
            continue
        seen_serialized.add(serialized)
        deduped_optional_blocks.append(block)

    for block in required_blocks:
        serialized_cache[block.name] = _serialize_for_budget(block.value)

    retained_optional_blocks = list(deduped_optional_blocks)
    dropped_optional_blocks: list[str] = []
    initial_size_chars, initial_size_bytes = _combined_budget_size(
        required_blocks=required_blocks,
        optional_blocks=deduped_optional_blocks,
        serialized_cache=serialized_cache,
    )
    final_size_chars = initial_size_chars
    final_size_bytes = initial_size_bytes

    while retained_optional_blocks and final_size_chars > normalized_budget:
        removed = retained_optional_blocks.pop(0)
        dropped_optional_blocks.append(removed.name)
        final_size_chars, final_size_bytes = _combined_budget_size(
            required_blocks=required_blocks,
            optional_blocks=retained_optional_blocks,
            serialized_cache=serialized_cache,
        )

    retained: dict[str, object] = {}
    for block in required_blocks:
        retained[block.name] = block.value
    for block in retained_optional_blocks:
        retained[block.name] = block.value

    overflow = final_size_chars > normalized_budget
    result = AIRequestBudgetResult(
        initial_size_chars=initial_size_chars,
        final_size_chars=final_size_chars,
        initial_size_bytes=initial_size_bytes,
        final_size_bytes=final_size_bytes,
        budget_size_chars=normalized_budget,
        dropped_optional_blocks=tuple(dropped_optional_blocks),
        dropped_duplicate_blocks=tuple(dropped_duplicate_blocks),
        required_blocks_retained=tuple(block.name for block in required_blocks),
        optional_blocks_retained=tuple(block.name for block in retained_optional_blocks),
        trimmed_bytes=max(0, initial_size_bytes - final_size_bytes),
        trimming_pass_count=len(dropped_optional_blocks),
        section_count=len(required_blocks) + len(retained_optional_blocks),
        overflow=overflow,
    )
    return AIRequestBudgetDecision(retained_blocks=retained, result=result)


def execute_json_request(
    *,
    request: urllib.request.Request,
    policy: AIExecutionPolicy,
    extract_correlation_id=None,
) -> AIExecutionResponse:
    timeout_seconds = policy.normalized_timeout_seconds()
    max_attempts = policy.normalized_max_attempts()
    max_input_size = policy.normalized_max_input_size()
    retry_backoff_seconds = max(0.0, float(policy.retry_backoff_seconds))
    request_payload_size = _request_payload_size(request=request)
    original_input_size = _coerce_non_negative_int(policy.original_input_size, fallback=request_payload_size)
    final_input_size = _coerce_non_negative_int(policy.final_input_size, fallback=request_payload_size)
    final_input_size = max(final_input_size, request_payload_size)
    original_input_size = max(original_input_size, final_input_size)
    trimmed_bytes = max(0, original_input_size - final_input_size)
    trimming_pass_count = max(0, int(policy.trimming_pass_count))
    section_count = (
        _coerce_non_negative_int(policy.section_count, fallback=0) if policy.section_count is not None else None
    )
    difficulty_score = _derive_difficulty_score(
        final_input_size=final_input_size,
        section_count=section_count,
        schema_complexity_flag=bool(policy.schema_complexity_flag),
        max_input_size=max_input_size,
    )
    _log_core_event(
        level=logging.INFO,
        event="ai_execution_preflight",
        payload={
            "feature_area": policy.feature_area,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
            "max_input_size": max_input_size,
            "request_payload_size": request_payload_size,
            "original_input_size": original_input_size,
            "final_input_size": final_input_size,
            "trimmed_bytes": trimmed_bytes,
            "trimming_pass_count": trimming_pass_count,
            "section_count": section_count,
            "difficulty_score": difficulty_score,
        },
    )

    if max_input_size is not None and final_input_size > max_input_size:
        _log_core_event(
            level=logging.WARNING,
            event="ai_execution_precall_rejected",
            payload={
                "feature_area": policy.feature_area,
                "reason": "request_too_large",
                "max_input_size": max_input_size,
                "request_payload_size": request_payload_size,
                "original_input_size": original_input_size,
                "final_input_size": final_input_size,
                "trimmed_bytes": trimmed_bytes,
                "trimming_pass_count": trimming_pass_count,
                "section_count": section_count,
                "difficulty_score": difficulty_score,
                "provider_call_attempted": False,
            },
        )
        failure = AINormalizedFailure(
            category="local_validation_failure",
            reason="request_too_large",
            source="local_validation",
            retryable=False,
        )
        raise AIExecutionError(
            safe_message="AI request exceeds synchronous execution size budget.",
            normalized_failure=failure,
            raw_response_text=None,
            correlation_id=None,
            duration_ms=None,
            attempt_count=1,
            original_input_size=original_input_size,
            final_input_size=final_input_size,
            trimmed_bytes=trimmed_bytes,
            trimming_pass_count=trimming_pass_count,
            difficulty_score=difficulty_score,
        )
    last_error: AIExecutionError | None = None

    for attempt in range(1, max_attempts + 1):
        started_at = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body_text = response.read().decode("utf-8", errors="replace")
                duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
                correlation_id = None
                if callable(extract_correlation_id):
                    correlation_id = extract_correlation_id(getattr(response, "headers", None))
                _log_core_event(
                    level=logging.INFO,
                    event="ai_execution_completed",
                    payload={
                        "feature_area": policy.feature_area,
                        "attempt_count": attempt,
                        "duration_ms": duration_ms,
                        "original_input_size": original_input_size,
                        "final_input_size": final_input_size,
                        "trimmed_bytes": trimmed_bytes,
                        "trimming_pass_count": trimming_pass_count,
                        "difficulty_score": difficulty_score,
                        "provider_call_attempted": True,
                    },
                )
                return AIExecutionResponse(
                    body_text=body_text,
                    duration_ms=duration_ms,
                    attempt_count=attempt,
                    correlation_id=correlation_id,
                    original_input_size=original_input_size,
                    final_input_size=final_input_size,
                    trimmed_bytes=trimmed_bytes,
                    trimming_pass_count=trimming_pass_count,
                    difficulty_score=difficulty_score,
                )
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            correlation_id = None
            if callable(extract_correlation_id):
                correlation_id = extract_correlation_id(getattr(exc, "headers", None))
            failure = _normalize_http_failure(http_status=exc.code)
            last_error = AIExecutionError(
                safe_message=_default_safe_message_for_failure(failure=failure),
                normalized_failure=failure,
                raw_response_text=body_text,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                attempt_count=attempt,
                original_input_size=original_input_size,
                final_input_size=final_input_size,
                trimmed_bytes=trimmed_bytes,
                trimming_pass_count=trimming_pass_count,
                difficulty_score=difficulty_score,
            )
        except (TimeoutError, socket.timeout) as exc:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            failure = AINormalizedFailure(
                category="remote_timeout",
                reason="provider_timeout",
                source="remote_provider",
                retryable=True,
                timeout_type=_infer_timeout_type(str(exc)),
            )
            last_error = AIExecutionError(
                safe_message=_default_safe_message_for_failure(failure=failure),
                normalized_failure=failure,
                raw_response_text=None,
                correlation_id=None,
                duration_ms=duration_ms,
                attempt_count=attempt,
                original_input_size=original_input_size,
                final_input_size=final_input_size,
                trimmed_bytes=trimmed_bytes,
                trimming_pass_count=trimming_pass_count,
                difficulty_score=difficulty_score,
            )
        except urllib.error.URLError as exc:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                failure = AINormalizedFailure(
                    category="remote_timeout",
                    reason="provider_timeout",
                    source="remote_provider",
                    retryable=True,
                    timeout_type=_infer_timeout_type(str(exc.reason)),
                )
            else:
                failure = AINormalizedFailure(
                    category="remote_unavailable",
                    reason="provider_transport_error",
                    source="remote_provider",
                    retryable=True,
                )
            last_error = AIExecutionError(
                safe_message=_default_safe_message_for_failure(failure=failure),
                normalized_failure=failure,
                raw_response_text=None,
                correlation_id=None,
                duration_ms=duration_ms,
                attempt_count=attempt,
                original_input_size=original_input_size,
                final_input_size=final_input_size,
                trimmed_bytes=trimmed_bytes,
                trimming_pass_count=trimming_pass_count,
                difficulty_score=difficulty_score,
            )
        except Exception:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            failure = AINormalizedFailure(
                category="remote_unavailable",
                reason="unexpected_provider_error",
                source="remote_provider",
                retryable=False,
            )
            last_error = AIExecutionError(
                safe_message=_default_safe_message_for_failure(failure=failure),
                normalized_failure=failure,
                raw_response_text=None,
                correlation_id=None,
                duration_ms=duration_ms,
                attempt_count=attempt,
                original_input_size=original_input_size,
                final_input_size=final_input_size,
                trimmed_bytes=trimmed_bytes,
                trimming_pass_count=trimming_pass_count,
                difficulty_score=difficulty_score,
            )

        assert last_error is not None
        should_retry = bool(last_error.normalized_failure.retryable) and attempt < max_attempts
        if (
            should_retry
            and policy.suppress_timeout_retry_without_size_change
            and last_error.normalized_failure.category == "remote_timeout"
        ):
            _log_core_event(
                level=logging.WARNING,
                event="ai_execution_retry_suppressed",
                payload={
                    "feature_area": policy.feature_area,
                    "attempt_count": attempt,
                    "max_attempts": max_attempts,
                    "reason": "request_too_large_or_complex",
                    "original_input_size": original_input_size,
                    "final_input_size": final_input_size,
                    "trimmed_bytes": trimmed_bytes,
                    "trimming_pass_count": trimming_pass_count,
                    "difficulty_score": difficulty_score,
                    "provider_call_attempted": True,
                },
            )
            last_error = AIExecutionError(
                safe_message="AI request timed out and retry was suppressed because request size did not change.",
                normalized_failure=AINormalizedFailure(
                    category="remote_timeout",
                    reason="request_too_large_or_complex",
                    source="remote_provider",
                    retryable=False,
                    timeout_type=last_error.normalized_failure.timeout_type,
                ),
                raw_response_text=last_error.raw_response_text,
                correlation_id=last_error.correlation_id,
                duration_ms=last_error.duration_ms,
                attempt_count=last_error.attempt_count,
                original_input_size=original_input_size,
                final_input_size=final_input_size,
                trimmed_bytes=trimmed_bytes,
                trimming_pass_count=trimming_pass_count,
                difficulty_score=difficulty_score,
            )
            should_retry = False
        if not should_retry:
            _log_core_event(
                level=logging.WARNING,
                event="ai_execution_failed",
                payload={
                    "feature_area": policy.feature_area,
                    "attempt_count": last_error.attempt_count,
                    "max_attempts": max_attempts,
                    "failure_category": last_error.normalized_failure.category,
                    "failure_reason": last_error.normalized_failure.reason,
                    "failure_source": last_error.normalized_failure.source,
                    "retryable": bool(last_error.normalized_failure.retryable),
                    "http_status": last_error.normalized_failure.http_status,
                    "timeout_type": last_error.normalized_failure.timeout_type,
                    "original_input_size": original_input_size,
                    "final_input_size": final_input_size,
                    "trimmed_bytes": trimmed_bytes,
                    "trimming_pass_count": trimming_pass_count,
                    "difficulty_score": difficulty_score,
                    "provider_call_attempted": True,
                },
            )
            raise last_error
        if retry_backoff_seconds > 0:
            time.sleep(retry_backoff_seconds)

    if last_error is None:
        failure = AINormalizedFailure(
            category="remote_unavailable",
            reason="unexpected_provider_error",
            source="remote_provider",
            retryable=False,
        )
        raise AIExecutionError(
            safe_message="AI provider request failed.",
            normalized_failure=failure,
            attempt_count=max_attempts,
            original_input_size=original_input_size,
            final_input_size=final_input_size,
            trimmed_bytes=trimmed_bytes,
            trimming_pass_count=trimming_pass_count,
            difficulty_score=difficulty_score,
        )
    raise last_error


def normalize_provider_failure(
    *,
    code: str | None,
) -> AINormalizedFailure:
    normalized_code = _normalize_code(code)
    if normalized_code in {"request_too_large", "request_too_large_or_complex"}:
        return AINormalizedFailure(
            category="local_validation_failure",
            reason="request_too_large_or_complex",
            source="local_validation",
            retryable=False,
        )
    if normalized_code in {"timeout", "provider_timeout"}:
        return AINormalizedFailure(
            category="remote_timeout",
            reason="provider_timeout",
            source="remote_provider",
            retryable=True,
        )
    if normalized_code in {"rate_limited", "provider_rate_limited"}:
        return AINormalizedFailure(
            category="remote_rate_limited",
            reason="provider_rate_limited",
            source="remote_provider",
            retryable=True,
        )
    if normalized_code in {"provider_auth_config", "authentication_failed", "unsupported_configuration"}:
        return AINormalizedFailure(
            category="configuration_invalid",
            reason="provider_auth_or_configuration_invalid",
            source="local_configuration",
            retryable=False,
        )
    if normalized_code in {"provider_request", "transport_error"}:
        return AINormalizedFailure(
            category="remote_unavailable",
            reason="provider_transport_error",
            source="remote_provider",
            retryable=True,
        )
    if normalized_code in {
        "invalid_output",
        "malformed_response",
        "malformed_output",
        "empty_response",
        "parsing_error",
    }:
        return AINormalizedFailure(
            category="remote_invalid_response",
            reason="provider_invalid_response",
            source="remote_provider",
            retryable=True,
        )
    if normalized_code in {"schema_validation", "validation_failed"}:
        return AINormalizedFailure(
            category="local_validation_failure",
            reason="response_schema_validation_failed",
            source="local_validation",
            retryable=False,
        )
    if normalized_code in {"configuration_missing"}:
        return AINormalizedFailure(
            category="configuration_missing",
            reason="provider_configuration_missing",
            source="local_configuration",
            retryable=False,
        )
    return AINormalizedFailure(
        category="remote_unavailable",
        reason="unexpected_provider_error",
        source="remote_provider",
        retryable=False,
    )


def build_ai_diagnostics_summary(
    *,
    failure_category: str | None = None,
    failure_reason: str | None = None,
    failure_source: str | None = None,
    retryable: bool | None = None,
    hint: str | None = None,
    budget_outcome: str | None = None,
    retry_suppressed: bool | None = None,
    trimming_pass_count: int | None = None,
    difficulty_score: int | None = None,
    original_input_size: int | None = None,
    final_input_size: int | None = None,
    trimmed_bytes: int | None = None,
    degraded_state: str | None = None,
) -> dict[str, object]:
    normalized_failure_category = _clean_optional_value(failure_category)
    normalized_failure_reason = _clean_optional_value(failure_reason)
    normalized_failure_source = _clean_optional_value(failure_source)
    normalized_hint = _clean_optional_value(hint)
    normalized_degraded_state = _clean_optional_value(degraded_state)

    retryable_value = retryable if isinstance(retryable, bool) else None
    original_input_size_value = _coerce_optional_non_negative_int(original_input_size)
    final_input_size_value = _coerce_optional_non_negative_int(final_input_size)
    trimmed_bytes_value = _coerce_optional_non_negative_int(trimmed_bytes)
    trimming_pass_count_value = _coerce_optional_non_negative_int(trimming_pass_count)
    difficulty_score_value = _coerce_optional_non_negative_int(difficulty_score)
    if isinstance(difficulty_score_value, int):
        difficulty_score_value = max(0, min(100, difficulty_score_value))

    retry_suppressed_value = (
        bool(retry_suppressed)
        if isinstance(retry_suppressed, bool)
        else normalized_failure_reason == "request_too_large_or_complex"
    )
    normalized_budget_outcome = _normalize_budget_outcome(
        budget_outcome=budget_outcome,
        retry_suppressed=retry_suppressed_value,
        failure_reason=normalized_failure_reason,
        trimming_pass_count=trimming_pass_count_value,
        trimmed_bytes=trimmed_bytes_value,
        final_input_size=final_input_size_value,
    )
    input_size_bucket = _bucket_input_size(
        final_input_size_value if isinstance(final_input_size_value, int) else original_input_size_value
    )
    difficulty_bucket = _bucket_difficulty(difficulty_score_value)

    payload: dict[str, object] = {
        "failure_category": normalized_failure_category,
        "failure_reason": normalized_failure_reason,
        "failure_source": normalized_failure_source,
        "retryable": retryable_value,
        "hint": normalized_hint,
        "budget_outcome": normalized_budget_outcome,
        "retry_suppressed": retry_suppressed_value,
        "trimming_pass_count": trimming_pass_count_value,
        "difficulty_bucket": difficulty_bucket,
        "input_size_bucket": input_size_bucket,
        "degraded_state": normalized_degraded_state,
    }
    return payload


def build_ai_failure_hint(
    *,
    failure_category: str | None = None,
    failure_reason: str | None = None,
) -> str | None:
    normalized_category = _clean_optional_value(failure_category)
    normalized_reason = _clean_optional_value(failure_reason)

    if normalized_reason in {"request_too_large", "request_too_large_or_complex"}:
        return "Input too large"
    if normalized_category == "remote_timeout" or normalized_reason in {"provider_timeout", "timeout"}:
        return "Provider timeout"
    if normalized_category in {"configuration_missing", "configuration_invalid"} or normalized_reason in {
        "provider_auth_or_configuration_invalid",
        "authentication_failed",
        "unsupported_configuration",
    }:
        return "Configuration issue"
    if normalized_category == "remote_invalid_response" or normalized_reason in {
        "provider_invalid_response",
        "response_schema_validation_failed",
        "malformed_response",
        "malformed_output",
        "validation_failed",
    }:
        return "Invalid provider response"
    if normalized_category in {"remote_unavailable", "remote_rate_limited"}:
        return "Try again later"
    return None


def _normalize_http_failure(*, http_status: int) -> AINormalizedFailure:
    if http_status in {401, 403}:
        return AINormalizedFailure(
            category="configuration_invalid",
            reason="provider_auth_or_configuration_invalid",
            source="local_configuration",
            retryable=False,
            http_status=http_status,
        )
    if http_status == 429:
        return AINormalizedFailure(
            category="remote_rate_limited",
            reason="provider_rate_limited",
            source="remote_provider",
            retryable=True,
            http_status=http_status,
        )
    if http_status in {408, 504}:
        return AINormalizedFailure(
            category="remote_timeout",
            reason="provider_timeout",
            source="remote_provider",
            retryable=True,
            http_status=http_status,
            timeout_type="overall",
        )
    if http_status in {400, 404, 422}:
        return AINormalizedFailure(
            category="configuration_invalid",
            reason="provider_auth_or_configuration_invalid",
            source="local_configuration",
            retryable=False,
            http_status=http_status,
        )
    return AINormalizedFailure(
        category="remote_unavailable",
        reason="provider_transport_error",
        source="remote_provider",
        retryable=True,
        http_status=http_status,
    )


def _normalize_budget_outcome(
    *,
    budget_outcome: str | None,
    retry_suppressed: bool,
    failure_reason: str | None,
    trimming_pass_count: int | None,
    trimmed_bytes: int | None,
    final_input_size: int | None,
) -> str | None:
    normalized = _clean_optional_value(budget_outcome)
    if normalized:
        return normalized
    if retry_suppressed:
        return "retry_suppressed"
    if failure_reason == "request_too_large":
        return "precall_rejected"
    if isinstance(final_input_size, int):
        if (isinstance(trimming_pass_count, int) and trimming_pass_count > 0) or (
            isinstance(trimmed_bytes, int) and trimmed_bytes > 0
        ):
            return "trimmed_provider_submission"
        return "provider_submission"
    return None


def _bucket_input_size(value: int | None) -> str | None:
    if not isinstance(value, int):
        return None
    normalized = max(0, value)
    if normalized <= _INPUT_SIZE_BUCKET_SMALL_MAX:
        return "small"
    if normalized <= _INPUT_SIZE_BUCKET_MEDIUM_MAX:
        return "medium"
    if normalized <= _INPUT_SIZE_BUCKET_LARGE_MAX:
        return "large"
    return "very_large"


def _bucket_difficulty(value: int | None) -> str | None:
    if not isinstance(value, int):
        return None
    normalized = max(0, min(100, value))
    if normalized <= _DIFFICULTY_BUCKET_LOW_MAX:
        return "low"
    if normalized <= _DIFFICULTY_BUCKET_MEDIUM_MAX:
        return "medium"
    return "high"


def _default_safe_message_for_failure(*, failure: AINormalizedFailure) -> str:
    if failure.reason in {"request_too_large", "request_too_large_or_complex"}:
        return "AI request is too large or complex for synchronous execution."
    if failure.category == "remote_timeout":
        return "AI provider request timed out."
    if failure.category == "remote_rate_limited":
        return "AI provider request was rate-limited."
    if failure.category in {"configuration_missing", "configuration_invalid"}:
        return "AI provider configuration is invalid."
    if failure.category == "remote_invalid_response":
        return "AI provider returned an invalid response."
    if failure.category == "local_validation_failure":
        return "AI response failed local validation."
    return "AI provider request failed."


def _serialize_for_budget(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _combined_budget_size(
    *,
    required_blocks: list[AIContextBlock],
    optional_blocks: list[AIContextBlock],
    serialized_cache: dict[str, str],
) -> tuple[int, int]:
    total_chars = 0
    total_bytes = 0
    for block in required_blocks:
        serialized = serialized_cache.get(block.name, "")
        total_chars += len(serialized)
        total_bytes += len(serialized.encode("utf-8", errors="ignore"))
    for block in optional_blocks:
        serialized = serialized_cache.get(block.name, "")
        total_chars += len(serialized)
        total_bytes += len(serialized.encode("utf-8", errors="ignore"))
    return total_chars, total_bytes


def _coerce_non_negative_int(value: object, *, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(0, int(fallback))
    return max(0, parsed)


def _coerce_optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _request_payload_size(*, request: urllib.request.Request) -> int:
    data = getattr(request, "data", None)
    if isinstance(data, bytes):
        return max(0, len(data))
    if isinstance(data, str):
        return max(0, len(data.encode("utf-8", errors="ignore")))
    return 0


def _derive_difficulty_score(
    *,
    final_input_size: int,
    section_count: int | None,
    schema_complexity_flag: bool,
    max_input_size: int | None,
) -> int:
    if max_input_size and max_input_size > 0:
        size_ratio = min(1.0, max(0.0, float(final_input_size) / float(max_input_size)))
    else:
        size_ratio = min(1.0, max(0.0, float(final_input_size) / 120_000.0))
    size_component = int(size_ratio * 70)
    sections_component = 0
    if isinstance(section_count, int):
        sections_component = min(20, max(0, section_count) * 2)
    schema_component = 10 if schema_complexity_flag else 0
    return min(100, max(0, size_component + sections_component + schema_component))


def _normalize_code(value: str | None) -> str:
    return str(value or "").strip().lower()


def _clean_optional_value(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _infer_timeout_type(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return "unknown"
    if "read operation timed out" in normalized or "read timed out" in normalized:
        return "read"
    if "connect timeout" in normalized or "connect timed out" in normalized:
        return "connect"
    if "timed out" in normalized or "timeout" in normalized:
        return "overall"
    return "unknown"


def _log_core_event(*, level: int, event: str, payload: dict[str, object]) -> None:
    data = {"event": event}
    data.update(payload)
    safe_payload = {key: value for key, value in data.items() if value is not None}
    safe_payload = sanitize_log_payload(safe_payload)
    if not isinstance(safe_payload, dict):
        logger.log(level, event)
        return
    try:
        serialized = json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        serialized = event
    logger.log(level, serialized, extra={"json_fields": safe_payload})

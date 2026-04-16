from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from app.integrations.ai_execution_core import (
    AIContextBlock,
    AIExecutionError,
    AIExecutionPolicy,
    apply_request_budget,
    build_ai_diagnostics_summary,
    execute_json_request,
    normalize_provider_failure,
)


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def read(self) -> bytes:
        return self._body


def test_apply_request_budget_trims_optional_before_required_blocks() -> None:
    decision = apply_request_budget(
        blocks=[
            AIContextBlock(name="required_primary", value="A" * 50, required=True, trim_priority=0),
            AIContextBlock(name="optional_low", value="B" * 30, required=False, trim_priority=1),
            AIContextBlock(name="optional_high", value="C" * 30, required=False, trim_priority=5),
        ],
        budget_size_chars=84,
    )

    assert "required_primary" in decision.retained_blocks
    assert decision.result.dropped_optional_blocks == ("optional_high",)
    assert decision.result.required_blocks_retained == ("required_primary",)
    assert decision.result.final_size_chars <= 84


def test_execute_json_request_retries_retryable_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        calls.append(1)
        if len(calls) == 1:
            raise socket.timeout("timed out")
        return _FakeResponse('{"ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    with pytest.raises(AIExecutionError) as exc_info:
        execute_json_request(
            request=urllib.request.Request(
                url="https://example.test",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            policy=AIExecutionPolicy(
                feature_area="test",
                timeout_seconds=3,
                max_attempts=2,
                retry_backoff_seconds=0,
            ),
        )

    assert exc_info.value.normalized_failure.category == "remote_timeout"
    assert exc_info.value.normalized_failure.reason == "request_too_large_or_complex"
    assert exc_info.value.normalized_failure.retryable is False
    assert calls == [1]


def test_execute_json_request_does_not_retry_non_retryable_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://example.test",
            code=401,
            msg="unauthorized",
            hdrs={},
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    with pytest.raises(AIExecutionError) as exc_info:
        execute_json_request(
            request=urllib.request.Request(
                url="https://example.test",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            policy=AIExecutionPolicy(
                feature_area="test",
                timeout_seconds=3,
                max_attempts=3,
                retry_backoff_seconds=0,
            ),
        )

    assert exc_info.value.normalized_failure.category == "configuration_invalid"
    assert exc_info.value.attempt_count == 1


def test_execute_json_request_fails_early_when_payload_exceeds_max_input_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise AssertionError("provider should not be called for oversized requests")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    with pytest.raises(AIExecutionError) as exc_info:
        execute_json_request(
            request=urllib.request.Request(
                url="https://example.test",
                data=("X" * 256).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            policy=AIExecutionPolicy(
                feature_area="test",
                timeout_seconds=3,
                max_attempts=2,
                max_input_size=128,
                original_input_size=300,
                final_input_size=256,
                trimming_pass_count=2,
                section_count=4,
                schema_complexity_flag=True,
                retry_backoff_seconds=0,
            ),
        )

    assert exc_info.value.normalized_failure.category == "local_validation_failure"
    assert exc_info.value.normalized_failure.reason == "request_too_large"
    assert exc_info.value.normalized_failure.retryable is False
    assert exc_info.value.original_input_size == 300
    assert exc_info.value.final_input_size == 256
    assert exc_info.value.trimmed_bytes == 44
    assert exc_info.value.trimming_pass_count == 2
    assert isinstance(exc_info.value.difficulty_score, int)


def test_execute_json_request_precall_rejection_emits_calibration_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise AssertionError("provider should not be called")

    caplog.set_level("INFO", logger="app.integrations.ai_execution_core")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    with pytest.raises(AIExecutionError):
        execute_json_request(
            request=urllib.request.Request(
                url="https://example.test",
                data=("X" * 300).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            policy=AIExecutionPolicy(
                feature_area="migration_draft",
                timeout_seconds=3,
                max_attempts=2,
                max_input_size=256,
                original_input_size=350,
                final_input_size=300,
                trimming_pass_count=1,
                section_count=3,
            ),
        )

    precall_events = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "ai_execution_precall_rejected"
    ]
    assert precall_events
    latest = precall_events[-1]
    assert latest.get("feature_area") == "migration_draft"
    assert latest.get("reason") == "request_too_large"
    assert latest.get("provider_call_attempted") is False
    assert latest.get("final_input_size") == 300
    assert latest.get("trimmed_bytes") == 50


def test_execute_json_request_retry_suppression_emits_calibration_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        calls.append(1)
        raise socket.timeout("timed out")

    caplog.set_level("INFO", logger="app.integrations.ai_execution_core")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    with pytest.raises(AIExecutionError) as exc_info:
        execute_json_request(
            request=urllib.request.Request(
                url="https://example.test",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            policy=AIExecutionPolicy(
                feature_area="recommendation_ai",
                timeout_seconds=3,
                max_attempts=2,
                retry_backoff_seconds=0,
            ),
        )

    assert exc_info.value.normalized_failure.reason == "request_too_large_or_complex"
    assert calls == [1]
    suppression_events = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "ai_execution_retry_suppressed"
    ]
    assert suppression_events
    latest = suppression_events[-1]
    assert latest.get("feature_area") == "recommendation_ai"
    assert latest.get("reason") == "request_too_large_or_complex"
    assert latest.get("provider_call_attempted") is True


@pytest.mark.parametrize(
    ("code", "expected_category"),
    [
        ("timeout", "remote_timeout"),
        ("provider_rate_limited", "remote_rate_limited"),
        ("provider_auth_config", "configuration_invalid"),
        ("provider_request", "remote_unavailable"),
        ("invalid_output", "remote_invalid_response"),
        ("schema_validation", "local_validation_failure"),
        ("configuration_missing", "configuration_missing"),
    ],
)
def test_normalize_provider_failure_maps_to_shared_taxonomy(
    code: str,
    expected_category: str,
) -> None:
    failure = normalize_provider_failure(code=code)
    assert failure.category == expected_category


def test_build_ai_diagnostics_summary_maps_size_and_difficulty_buckets() -> None:
    summary = build_ai_diagnostics_summary(
        failure_category="remote_timeout",
        failure_reason="provider_timeout",
        failure_source="remote_provider",
        retryable=True,
        hint="Try again later",
        original_input_size=100_000,
        final_input_size=58_000,
        trimmed_bytes=42_000,
        trimming_pass_count=3,
        difficulty_score=82,
    )

    assert summary["failure_category"] == "remote_timeout"
    assert summary["retryable"] is True
    assert summary["budget_outcome"] == "trimmed_provider_submission"
    assert summary["input_size_bucket"] == "medium"
    assert summary["difficulty_bucket"] == "high"
    assert summary["retry_suppressed"] is False


def test_build_ai_diagnostics_summary_marks_retry_suppressed_timeouts() -> None:
    summary = build_ai_diagnostics_summary(
        failure_category="local_validation_failure",
        failure_reason="request_too_large_or_complex",
        failure_source="local_validation",
        retryable=False,
        hint="Input too large",
    )

    assert summary["budget_outcome"] == "retry_suppressed"
    assert summary["retry_suppressed"] is True

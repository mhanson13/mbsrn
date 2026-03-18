from __future__ import annotations

import logging

import pytest

from app.services.google_business_profile_verification_observability import (
    verification_observability,
)
from app.services.google_business_profile_verification_mapping import (
    build_method_option_token,
    determine_state_summary,
    determine_workflow_state,
    extract_voice_of_merchant,
    map_provider_api_error,
    map_provider_verification_state,
    normalize_provider_method,
)


@pytest.fixture(autouse=True)
def _reset_observability() -> None:
    verification_observability.reset()
    yield
    verification_observability.reset()


def test_map_provider_verification_state_exact_and_marker_cases() -> None:
    assert map_provider_verification_state("PENDING", context="test") == "pending"
    assert map_provider_verification_state("IN_REVIEW", context="test") == "in_progress"
    assert map_provider_verification_state("VOICE_OF_MERCHANT", context="test") == "completed"
    assert map_provider_verification_state("FAILED", context="test") == "failed"


def test_map_provider_verification_state_unknown_logs_warning(caplog) -> None:
    caplog.set_level(logging.WARNING)
    mapped = map_provider_verification_state("SOMETHING_NEW", context="status location_id=abc")
    assert mapped == "unknown"
    assert "gbp_verification_state_unmapped" in caplog.text
    assert "SOMETHING_NEW" in caplog.text
    assert verification_observability.snapshot().get("provider_state_unmapped", 0) == 1


def test_normalize_provider_method_known_and_unknown(caplog) -> None:
    caplog.set_level(logging.WARNING)
    method, provider_method = normalize_provider_method("EMAIL", context="method_test")
    assert method == "email"
    assert provider_method == "EMAIL"

    unknown_method, unknown_provider_method = normalize_provider_method("FAX_MACHINE", context="method_test")
    assert unknown_method == "other"
    assert unknown_provider_method == "FAX_MACHINE"
    assert "gbp_verification_method_unmapped" in caplog.text
    assert verification_observability.snapshot().get("provider_method_unmapped", 0) == 1


def test_workflow_and_summary_degrade_safely_for_unknown_states() -> None:
    state = determine_workflow_state(
        has_voice_of_merchant=None,
        provider_states=["SOMETHING_NEW"],
        has_verifications=True,
        context="workflow location_id=loc-1",
    )
    summary = determine_state_summary(
        has_voice_of_merchant=None,
        provider_states=["SOMETHING_NEW"],
        has_verifications=True,
        context="summary location_id=loc-1",
    )
    assert state == "unknown"
    assert summary == "unknown"


def test_extract_voice_of_merchant_handles_common_shapes() -> None:
    assert extract_voice_of_merchant({"hasVoiceOfMerchant": True}) is True
    assert extract_voice_of_merchant({"verificationState": "VOICE_OF_MERCHANT"}) is True
    assert extract_voice_of_merchant({"state": "NOT_VERIFIED"}) is False
    assert extract_voice_of_merchant({"state": "SOMETHING_ELSE"}) is None


def test_map_provider_api_error_invalid_code_mapping() -> None:
    mapped = map_provider_api_error(
        action="complete",
        status_code=400,
        error_status="INVALID_ARGUMENT",
        message="invalid pin code",
        is_permission_denied=False,
    )
    assert mapped.status_code == 422
    assert mapped.error_code == "invalid_code"


def test_map_provider_api_error_fallback_logs_warning(caplog) -> None:
    caplog.set_level(logging.WARNING)
    mapped = map_provider_api_error(
        action="options",
        status_code=500,
        error_status="SOMETHING_NEW",
        message="provider returned unknown error",
        is_permission_denied=False,
    )
    assert mapped.status_code == 502
    assert mapped.error_code == "provider_error"
    assert "gbp_provider_error_fallback" in caplog.text
    assert verification_observability.snapshot().get("provider_error_fallback", 0) == 1


def test_build_method_option_token_is_deterministic_and_sensitive_to_identity_fields() -> None:
    token_a = build_method_option_token(
        provider_method="EMAIL",
        destination="owner@example.com",
        requires_code=True,
        language_code="en",
    )
    token_b = build_method_option_token(
        provider_method="email",
        destination="owner@example.com",
        requires_code=True,
        language_code="EN",
    )
    token_c = build_method_option_token(
        provider_method="EMAIL",
        destination="other@example.com",
        requires_code=True,
        language_code="en",
    )
    assert token_a == token_b
    assert token_a.startswith("method_")
    assert token_a != token_c

from __future__ import annotations

from app.services.verification_guidance_service import (
    VerificationGuidanceMethodOptionInput,
    VerificationGuidanceService,
)


def test_guidance_verified_no_action_needed() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="verified",
        action_required="none",
    )
    assert result.recommended_action == "no_action_needed"
    assert result.title == "Your business is verified"
    assert result.cta_type == "none"


def test_guidance_unverified_with_methods_choose_method() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unverified",
        action_required="choose_method",
        available_methods=(
            VerificationGuidanceMethodOptionInput(
                method="email",
                label="Email",
                destination="owner@example.com",
                requires_code=True,
            ),
            VerificationGuidanceMethodOptionInput(
                method="postcard",
                label="Postcard",
                destination="123 Main St",
                requires_code=True,
            ),
        ),
    )
    assert result.recommended_action == "choose_method"
    assert result.recommended_method == "email"
    assert result.recommendation_reason is not None
    assert result.cta_type == "choose_method"


def test_guidance_pending_code_required_enters_code() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="pending",
        action_required="enter_code",
        current_method="email",
        code_required=True,
        available_methods=(
            VerificationGuidanceMethodOptionInput(
                method="email",
                label="Email",
                destination="owner@example.com",
                requires_code=True,
            ),
        ),
    )
    assert result.recommended_action == "enter_code"
    assert result.cta_type == "submit_code"
    assert "code" in result.title.lower()


def test_guidance_postcard_pending_wait_for_code() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="pending",
        action_required="enter_code",
        current_method="postcard",
        code_required=True,
    )
    assert result.recommended_action == "wait_for_code"
    assert result.cta_type == "refresh_status"


def test_guidance_reconnect_required_maps_to_reconnect_google() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unknown",
        action_required="resolve_access",
        reconnect_required=True,
    )
    assert result.recommended_action == "reconnect_google"
    assert result.priority == "high"
    assert result.cta_type == "reconnect"


def test_guidance_insufficient_scope_maps_to_reconnect_google() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unknown",
        action_required="resolve_access",
        error_code="insufficient_scope",
    )
    assert result.recommended_action == "reconnect_google"
    assert result.cta_type == "reconnect"


def test_guidance_permission_denied_maps_to_access_guidance() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unknown",
        action_required="resolve_access",
        error_code="permission_denied",
    )
    assert result.recommended_action == "check_business_access"
    assert result.cta_type == "refresh_status"


def test_guidance_unverified_with_no_methods_safe_fallback() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unverified",
        action_required="resolve_access",
        available_methods=(),
    )
    assert result.recommended_action == "review_business_details"
    assert result.cta_type == "refresh_status"


def test_guidance_failed_state_recommends_retry() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="failed",
        action_required="retry",
        available_methods=(
            VerificationGuidanceMethodOptionInput(
                method="sms",
                label="SMS",
                destination="+13035551212",
                requires_code=True,
            ),
        ),
    )
    assert result.recommended_action == "retry_verification"
    assert result.cta_type == "retry"


def test_guidance_recommendation_is_deterministic_with_multiple_methods() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unverified",
        action_required="choose_method",
        available_methods=(
            VerificationGuidanceMethodOptionInput(
                method="postcard",
                label="Postcard",
                destination="123 Main St",
                requires_code=True,
            ),
            VerificationGuidanceMethodOptionInput(
                method="sms",
                label="SMS",
                destination="+13035550000",
                requires_code=True,
            ),
            VerificationGuidanceMethodOptionInput(
                method="email",
                label="Email",
                destination="owner@example.com",
                requires_code=True,
            ),
        ),
    )
    assert result.recommended_action == "choose_method"
    assert result.recommended_method == "email"


def test_guidance_unknown_state_safe_fallback() -> None:
    service = VerificationGuidanceService()
    result = service.generate_guidance(
        verification_state="unknown",
        action_required="resolve_access",
    )
    assert result.recommended_action == "unknown"
    assert result.cta_type == "refresh_status"

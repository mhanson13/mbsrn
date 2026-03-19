from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from app.services.google_business_profile_verification_observability import (
    record_gbp_verification_observation,
)

VerificationGuidanceState = Literal[
    "verified",
    "unverified",
    "pending",
    "unknown",
    "in_progress",
    "completed",
    "failed",
]

VerificationGuidanceAction = Literal[
    "verify_business",
    "choose_method",
    "enter_code",
    "wait_for_code",
    "retry_verification",
    "reconnect_google",
    "contact_support",
    "no_action_needed",
    "check_business_access",
    "review_business_details",
    "unknown",
]

VerificationGuidancePriority = Literal["high", "medium", "low", "info"]
VerificationGuidanceCtaType = Literal[
    "start_verification",
    "choose_method",
    "submit_code",
    "reconnect",
    "retry",
    "refresh_status",
    "none",
]
VerificationGuidanceMethod = Literal[
    "postcard",
    "phone",
    "sms",
    "email",
    "live_call",
    "video",
    "vetted_partner",
    "address",
    "other",
    "unknown",
]
VerificationGuidanceActionRequired = Literal[
    "none",
    "choose_method",
    "enter_code",
    "wait",
    "retry",
    "reconnect_google",
    "resolve_access",
]
VerificationGuidanceErrorCode = Literal[
    "reconnect_required",
    "insufficient_scope",
    "permission_denied",
    "verification_not_supported",
    "method_not_available",
    "invalid_verification_state",
    "invalid_code",
    "provider_conflict",
    "provider_error",
    "not_found",
]


@dataclass(frozen=True)
class VerificationGuidanceMethodOptionInput:
    method: VerificationGuidanceMethod
    label: str
    destination: str | None
    requires_code: bool
    eligible: bool = True


@dataclass(frozen=True)
class VerificationGuidanceResult:
    verification_state: VerificationGuidanceState
    recommended_action: VerificationGuidanceAction
    priority: VerificationGuidancePriority
    title: str
    summary: str
    instructions: tuple[str, ...]
    tips: tuple[str, ...]
    warnings: tuple[str, ...]
    troubleshooting: tuple[str, ...]
    estimated_time: str | None
    cta_label: str | None
    cta_type: VerificationGuidanceCtaType
    recommended_method: VerificationGuidanceMethod | None = None
    recommendation_reason: str | None = None


class VerificationGuidanceService:
    """Deterministic operator guidance over normalized verification state."""

    def generate_guidance(
        self,
        *,
        verification_state: VerificationGuidanceState,
        action_required: VerificationGuidanceActionRequired | None = None,
        available_methods: Sequence[VerificationGuidanceMethodOptionInput] = (),
        reconnect_required: bool = False,
        error_code: VerificationGuidanceErrorCode | None = None,
        current_method: VerificationGuidanceMethod | None = None,
        code_required: bool | None = None,
    ) -> VerificationGuidanceResult:
        eligible_methods = tuple(method for method in available_methods if method.eligible)

        if reconnect_required or error_code == "reconnect_required":
            return self._reconnect_guidance(verification_state=verification_state)

        if error_code == "insufficient_scope":
            return VerificationGuidanceResult(
                verification_state=verification_state,
                recommended_action="reconnect_google",
                priority="high",
                title="Google access needs to be updated",
                summary="Reconnect your Google account so Work Boots can continue verification checks.",
                instructions=(
                    "Open Google Business Profile connection settings.",
                    "Reconnect the same Google account you use for this business.",
                    "Return here and refresh verification status.",
                ),
                tips=("Use an account that can manage this business profile.",),
                warnings=(),
                troubleshooting=(
                    "If reconnect keeps failing, confirm this Google account can access the business in Google Business Profile.",
                ),
                estimated_time="2-3 minutes",
                cta_label="Reconnect Google",
                cta_type="reconnect",
            )

        if error_code == "permission_denied":
            return VerificationGuidanceResult(
                verification_state=verification_state,
                recommended_action="check_business_access",
                priority="high",
                title="Google account access needs attention",
                summary="The connected Google account may not have permission for this location.",
                instructions=(
                    "Confirm the connected Google account can manage this business location.",
                    "If needed, switch accounts and reconnect Google.",
                    "Refresh status after access is updated.",
                ),
                tips=("Use the same Google account your team uses in Business Profile Manager.",),
                warnings=(),
                troubleshooting=(
                    "If access is correct but errors continue, check that Business Profile APIs are enabled for this project.",
                ),
                estimated_time="3-5 minutes",
                cta_label="Refresh status",
                cta_type="refresh_status",
            )

        if verification_state in {"verified", "completed"}:
            return VerificationGuidanceResult(
                verification_state=verification_state,
                recommended_action="no_action_needed",
                priority="info",
                title="Your business is verified",
                summary="No action is needed right now.",
                instructions=(),
                tips=("Check status again only if business details change.",),
                warnings=(),
                troubleshooting=(),
                estimated_time=None,
                cta_label=None,
                cta_type="none",
            )

        if verification_state in {"pending", "in_progress"}:
            if current_method == "postcard":
                return VerificationGuidanceResult(
                    verification_state=verification_state,
                    recommended_action="wait_for_code",
                    priority="medium",
                    title="Wait for your postcard code",
                    summary="Google is sending a postcard code to your business address.",
                    instructions=(
                        "Check your business mailbox regularly.",
                        "When the postcard arrives, enter the code in Work Boots.",
                        "Avoid starting another request unless Google says to retry.",
                    ),
                    tips=("Keep your business name and address consistent while waiting for the code.",),
                    warnings=("Postcard delivery can take multiple days depending on your area.",),
                    troubleshooting=(
                        "If no postcard arrives after the expected window, refresh status and try a different method if available.",
                    ),
                    estimated_time="5-14 days",
                    cta_label="Refresh status",
                    cta_type="refresh_status",
                )

            if action_required == "enter_code" or bool(code_required):
                destination_hint = self._destination_hint(current_method=current_method, methods=eligible_methods)
                tips: tuple[str, ...] = ()
                if destination_hint:
                    tips = (destination_hint,)
                return VerificationGuidanceResult(
                    verification_state=verification_state,
                    recommended_action="enter_code",
                    priority="high",
                    title="Enter your verification code",
                    summary="Google sent a code. Enter it to finish verification.",
                    instructions=(
                        "Find the latest code sent by Google.",
                        "Enter the code exactly as shown.",
                        "Submit and refresh status.",
                    ),
                    tips=tips,
                    warnings=(),
                    troubleshooting=("If code entry fails, request a new code or retry verification.",),
                    estimated_time="1-3 minutes",
                    cta_label="Enter code",
                    cta_type="submit_code",
                )

            return VerificationGuidanceResult(
                verification_state=verification_state,
                recommended_action="wait_for_code",
                priority="medium",
                title="Verification is in progress",
                summary="Google is still processing this verification request.",
                instructions=(
                    "Wait a short period, then refresh status.",
                    "Follow any next step shown after refresh.",
                ),
                tips=(),
                warnings=(),
                troubleshooting=(
                    "If this does not change for a long time, retry verification with another method if available.",
                ),
                estimated_time="a few minutes to a few days",
                cta_label="Refresh status",
                cta_type="refresh_status",
            )

        if verification_state == "failed":
            recommended_method, recommendation_reason = self.recommend_method(eligible_methods)
            if eligible_methods:
                tips = (recommendation_reason,) if recommendation_reason else ()
                return VerificationGuidanceResult(
                    verification_state=verification_state,
                    recommended_action="retry_verification",
                    priority="high",
                    title="Verification did not complete",
                    summary="Retry verification with an available method.",
                    instructions=(
                        "Choose a verification method.",
                        "Start a new verification attempt.",
                        "Complete the next step Google asks for.",
                    ),
                    tips=tips,
                    warnings=(),
                    troubleshooting=(
                        "If retries keep failing, confirm your Google account has access to this location.",
                    ),
                    estimated_time="2-10 minutes",
                    cta_label="Retry verification",
                    cta_type="retry",
                    recommended_method=recommended_method,
                    recommendation_reason=recommendation_reason,
                )
            return VerificationGuidanceResult(
                verification_state=verification_state,
                recommended_action="review_business_details",
                priority="high",
                title="Verification failed and needs review",
                summary="No retry method is available right now.",
                instructions=(
                    "Check business profile details in Google.",
                    "Refresh status in Work Boots.",
                    "Reconnect Google if access looks out of date.",
                ),
                tips=(),
                warnings=(),
                troubleshooting=("If this persists, contact support with the location id and recent error details.",),
                estimated_time="5-10 minutes",
                cta_label="Refresh status",
                cta_type="refresh_status",
            )

        if verification_state == "unverified":
            if eligible_methods:
                recommended_method, recommendation_reason = self.recommend_method(eligible_methods)
                tips = (recommendation_reason,) if recommendation_reason else ()
                return VerificationGuidanceResult(
                    verification_state=verification_state,
                    recommended_action="choose_method",
                    priority="medium",
                    title="Choose how to get your verification code",
                    summary="Pick the best available method to verify this location.",
                    instructions=(
                        "Pick a method you can access right now.",
                        "Start verification.",
                        "Complete the next step Google provides.",
                    ),
                    tips=tips,
                    warnings=(),
                    troubleshooting=("If a method fails, switch to another available method and retry.",),
                    estimated_time="2-10 minutes",
                    cta_label="Pick method",
                    cta_type="choose_method",
                    recommended_method=recommended_method,
                    recommendation_reason=recommendation_reason,
                )
            return VerificationGuidanceResult(
                verification_state=verification_state,
                recommended_action="review_business_details",
                priority="medium",
                title="Verification options are not available right now",
                summary="Google is not offering a verification method for this location yet.",
                instructions=(
                    "Review business details in Google Business Profile.",
                    "Confirm the connected Google account can manage this location.",
                    "Refresh status and check again later.",
                ),
                tips=(),
                warnings=(),
                troubleshooting=("If options remain unavailable, reconnect Google and retry.",),
                estimated_time="5-15 minutes",
                cta_label="Refresh status",
                cta_type="refresh_status",
            )

        record_gbp_verification_observation("guidance_fallback_unknown")
        return VerificationGuidanceResult(
            verification_state=verification_state,
            recommended_action="unknown",
            priority="info",
            title="Verification status needs review",
            summary="Work Boots cannot determine the next safe step yet.",
            instructions=(
                "Refresh status.",
                "If this keeps happening, reconnect Google and try again.",
            ),
            tips=(),
            warnings=(),
            troubleshooting=("If the status stays unknown, contact support with the location id and timestamp.",),
            estimated_time=None,
            cta_label="Refresh status",
            cta_type="refresh_status",
        )

    def recommend_method(
        self,
        methods: Sequence[VerificationGuidanceMethodOptionInput],
    ) -> tuple[VerificationGuidanceMethod | None, str | None]:
        if not methods:
            return None, None

        ordered_methods: tuple[VerificationGuidanceMethod, ...] = (
            "email",
            "sms",
            "phone",
            "live_call",
            "video",
            "address",
            "postcard",
            "vetted_partner",
            "other",
            "unknown",
        )
        for candidate in ordered_methods:
            for method in methods:
                if method.method != candidate:
                    continue
                reason = self._method_recommendation_reason(method.method)
                return method.method, reason
        return None, None

    def _method_recommendation_reason(self, method: VerificationGuidanceMethod) -> str | None:
        if method == "email":
            return "Fast option if you can access this email right now."
        if method in {"sms", "phone"}:
            return "Fast option if you can access this phone right now."
        if method == "postcard":
            return "Use this when faster options are not available."
        if method == "address":
            return "Useful when mail delivery is more reliable for your location."
        return None

    def _destination_hint(
        self,
        *,
        current_method: VerificationGuidanceMethod | None,
        methods: Sequence[VerificationGuidanceMethodOptionInput],
    ) -> str | None:
        if current_method is None:
            return None
        for method in methods:
            if method.method != current_method:
                continue
            if method.destination:
                if current_method == "email":
                    return f"Check {method.destination} for the latest Google code."
                if current_method in {"sms", "phone"}:
                    return f"Check {method.destination} for the latest Google code."
                if current_method in {"postcard", "address"}:
                    return f"Check this destination for your code: {method.destination}."
            break
        return None

    def _reconnect_guidance(self, *, verification_state: VerificationGuidanceState) -> VerificationGuidanceResult:
        return VerificationGuidanceResult(
            verification_state=verification_state,
            recommended_action="reconnect_google",
            priority="high",
            title="Reconnect Google to continue",
            summary="Google access has expired or changed for this business.",
            instructions=(
                "Open Google Business Profile connection settings.",
                "Reconnect the correct Google account.",
                "Return here and refresh status.",
            ),
            tips=("Use the same account that manages the business location in Google.",),
            warnings=(),
            troubleshooting=("If reconnect fails, confirm your account has business access before trying again.",),
            estimated_time="2-3 minutes",
            cta_label="Reconnect Google",
            cta_type="reconnect",
        )

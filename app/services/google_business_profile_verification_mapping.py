from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.services.google_business_profile_verification_observability import (
    record_gbp_verification_observation,
)

VerificationStateSummary = Literal["verified", "unverified", "pending", "unknown"]
VerificationNextAction = Literal["none", "start_verification", "complete_pending", "resolve_access", "reconnect_google"]
VerificationWorkflowState = Literal["unverified", "pending", "in_progress", "completed", "failed", "unknown"]
VerificationActionRequired = Literal[
    "none",
    "choose_method",
    "enter_code",
    "wait",
    "retry",
    "reconnect_google",
    "resolve_access",
]
VerificationMethod = Literal[
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
VerificationErrorCode = Literal[
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
ProviderErrorAction = Literal["start", "complete", "status", "options"]

logger = logging.getLogger(__name__)

_PROVIDER_METHOD_MAP: dict[str, VerificationMethod] = {
    "MAIL": "postcard",
    "POSTCARD": "postcard",
    "PHONE_CALL": "phone",
    "SMS": "sms",
    "EMAIL": "email",
    "LIVE_CALL": "live_call",
    "VIDEO": "video",
    "LIVE_VIDEO_CALL": "video",
    "VETTED_PARTNER": "vetted_partner",
    "ADDRESS": "address",
    "AUTO": "other",
}

_METHOD_LABELS: dict[VerificationMethod, str] = {
    "postcard": "Postcard",
    "phone": "Phone Call",
    "sms": "SMS",
    "email": "Email",
    "live_call": "Live Call",
    "video": "Video",
    "vetted_partner": "Vetted Partner",
    "address": "Address",
    "other": "Other",
    "unknown": "Unknown",
}

_METHODS_REQUIRING_CODE: frozenset[str] = frozenset({"PHONE_CALL", "SMS", "EMAIL", "ADDRESS", "MAIL", "POSTCARD"})

_PROVIDER_STATE_EXACT_MAP: dict[str, VerificationWorkflowState] = {
    "PENDING": "pending",
    "IN_PROGRESS": "in_progress",
    "INPROGRESS": "in_progress",
    "PROCESSING": "in_progress",
    "IN_REVIEW": "in_progress",
    "REQUESTED": "in_progress",
    "STARTED": "in_progress",
    "VERIFIED": "completed",
    "SUCCESS": "completed",
    "COMPLETED": "completed",
    "APPROVED": "completed",
    "VOICE_OF_MERCHANT": "completed",
    "FAILED": "failed",
    "FAILURE": "failed",
    "REJECTED": "failed",
    "EXPIRED": "failed",
    "CANCELLED": "failed",
    "DENIED": "failed",
    "NOT_VERIFIED": "failed",
}

_PROVIDER_STATE_PENDING_MARKERS: tuple[str, ...] = ("PENDING",)
_PROVIDER_STATE_IN_PROGRESS_MARKERS: tuple[str, ...] = (
    "IN_PROGRESS",
    "INPROGRESS",
    "PROCESSING",
    "IN_REVIEW",
    "REQUESTED",
    "STARTED",
)
_PROVIDER_STATE_COMPLETED_MARKERS: tuple[str, ...] = (
    "VERIFIED",
    "SUCCESS",
    "COMPLETE",
    "APPROVED",
    "VOICE_OF_MERCHANT",
)
_PROVIDER_STATE_FAILED_MARKERS: tuple[str, ...] = (
    "FAILED",
    "FAILURE",
    "REJECTED",
    "EXPIRED",
    "CANCELLED",
    "DENIED",
    "NOT_VERIFIED",
)


@dataclass(frozen=True)
class ProviderErrorMappingResult:
    status_code: int
    error_code: VerificationErrorCode
    message: str


def normalize_provider_method(
    provider_method: str | None,
    *,
    context: str,
) -> tuple[VerificationMethod, str]:
    normalized_provider_method = _normalized_str(provider_method).upper()
    if not normalized_provider_method:
        record_gbp_verification_observation("provider_method_missing")
        logger.warning("gbp_verification_method_missing context=%s", context)
        return "unknown", "UNKNOWN"

    method = _PROVIDER_METHOD_MAP.get(normalized_provider_method)
    if method is not None:
        return method, normalized_provider_method

    record_gbp_verification_observation("provider_method_unmapped")
    logger.warning(
        "gbp_verification_method_unmapped context=%s provider_method=%s",
        context,
        normalized_provider_method,
    )
    return "other", normalized_provider_method


def verification_method_label(method: VerificationMethod) -> str:
    return _METHOD_LABELS.get(method, "Unknown")


def provider_method_requires_code(provider_method: str) -> bool:
    normalized_provider_method = _normalized_str(provider_method).upper()
    return normalized_provider_method in _METHODS_REQUIRING_CODE


def map_provider_verification_state(
    provider_state: str | None,
    *,
    context: str,
) -> VerificationWorkflowState | None:
    normalized_state = _normalized_str(provider_state).upper()
    if not normalized_state:
        return None

    exact = _PROVIDER_STATE_EXACT_MAP.get(normalized_state)
    if exact is not None:
        return exact

    if any(marker in normalized_state for marker in _PROVIDER_STATE_PENDING_MARKERS):
        return "pending"
    if any(marker in normalized_state for marker in _PROVIDER_STATE_IN_PROGRESS_MARKERS):
        return "in_progress"
    if any(marker in normalized_state for marker in _PROVIDER_STATE_COMPLETED_MARKERS):
        return "completed"
    if any(marker in normalized_state for marker in _PROVIDER_STATE_FAILED_MARKERS):
        return "failed"

    record_gbp_verification_observation("provider_state_unmapped")
    logger.warning(
        "gbp_verification_state_unmapped context=%s provider_state=%s",
        context,
        normalized_state,
    )
    return "unknown"


def determine_workflow_state(
    *,
    has_voice_of_merchant: bool | None,
    provider_states: Sequence[str | None],
    has_verifications: bool,
    context: str = "workflow",
) -> VerificationWorkflowState:
    if has_voice_of_merchant is True:
        return "completed"

    mapped_states: list[VerificationWorkflowState] = []
    for state in provider_states:
        mapped = map_provider_verification_state(state, context=context)
        if mapped is not None:
            mapped_states.append(mapped)

    if mapped_states:
        primary = mapped_states[0]
        if primary != "unknown":
            return primary
        non_unknown = [state for state in mapped_states if state != "unknown"]
        if non_unknown and all(state == "failed" for state in non_unknown):
            return "failed"

    if not has_verifications:
        return "unverified"
    return "unknown"


def determine_state_summary(
    *,
    has_voice_of_merchant: bool | None,
    provider_states: Sequence[str | None],
    has_verifications: bool,
    context: str = "summary",
) -> VerificationStateSummary:
    if has_voice_of_merchant is True:
        return "verified"

    mapped_states: list[VerificationWorkflowState] = []
    for state in provider_states:
        mapped = map_provider_verification_state(state, context=context)
        if mapped is not None:
            mapped_states.append(mapped)

    if any(state in {"pending", "in_progress"} for state in mapped_states):
        return "pending"
    if any(state == "completed" for state in mapped_states):
        return "verified"
    if not has_verifications:
        return "unverified"
    non_unknown = [state for state in mapped_states if state != "unknown"]
    if non_unknown and all(state == "failed" for state in non_unknown):
        return "unverified"
    return "unknown"


def determine_next_action(state_summary: VerificationStateSummary) -> VerificationNextAction:
    if state_summary == "verified":
        return "none"
    if state_summary == "pending":
        return "complete_pending"
    if state_summary == "unverified":
        return "start_verification"
    return "resolve_access"


def determine_summary_action_required(
    *,
    state_summary: VerificationStateSummary,
    current_provider_method: str | None,
    has_available_methods: bool,
) -> VerificationActionRequired:
    if state_summary == "verified":
        return "none"
    if state_summary == "pending":
        if current_provider_method and provider_method_requires_code(current_provider_method):
            return "enter_code"
        return "wait"
    if state_summary == "unverified":
        if has_available_methods:
            return "choose_method"
        return "resolve_access"
    return "resolve_access"


def determine_workflow_action(
    *,
    verification_state: VerificationWorkflowState,
    current_provider_method: str | None,
    has_available_methods: bool,
) -> tuple[VerificationActionRequired, str]:
    if verification_state == "completed":
        return "none", "No action required."
    if verification_state == "pending":
        if current_provider_method and provider_method_requires_code(current_provider_method):
            return "enter_code", "Enter the verification code to complete verification."
        return "wait", "Verification is pending. Wait for Google to update status."
    if verification_state == "in_progress":
        return "wait", "Verification is in progress. Wait for Google to update status."
    if verification_state == "failed":
        if has_available_methods:
            return "retry", "Verification failed. Retry with an available verification method."
        return "resolve_access", "Verification failed and no retry method is currently available."
    if verification_state == "unverified":
        if has_available_methods:
            return "choose_method", "Choose a verification method to start verification."
        return "resolve_access", "No verification methods are currently available for this location."
    return "resolve_access", "Verification status is unavailable. Confirm Google access and reconnect if needed."


def build_method_option_token(
    *,
    provider_method: str,
    destination: str | None,
    requires_code: bool,
    language_code: str | None = None,
) -> str:
    canonical = {
        "provider_method": _normalized_str(provider_method).upper(),
        "destination": _normalized_str(destination).lower(),
        "requires_code": bool(requires_code),
        "language_code": _normalized_str(language_code).lower(),
    }
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"method_{digest}"


def extract_verification_option_destination(option: dict[str, Any]) -> str | None:
    phone = _none_if_empty(option.get("phoneNumber"))
    if phone:
        return phone
    email = _none_if_empty(option.get("emailAddress"))
    if email:
        return email
    address_data = option.get("addressData")
    if isinstance(address_data, dict):
        formatted_address = format_storefront_address(address_data)
        if formatted_address:
            return formatted_address
    announcement = _none_if_empty(option.get("announcement"))
    if announcement:
        return announcement
    return None


def extract_voice_of_merchant(payload: dict[str, Any]) -> bool | None:
    explicit_bool = payload.get("hasVoiceOfMerchant")
    if isinstance(explicit_bool, bool):
        return explicit_bool
    for candidate in (
        payload.get("voiceOfMerchantState"),
        payload.get("state"),
        payload.get("verificationState"),
    ):
        normalized = _normalized_str(candidate).lower()
        if not normalized:
            continue
        if normalized in {"not_verified", "false", "unverified"} or "not_verified" in normalized:
            return False
        if "voice_of_merchant" in normalized or "verified" in normalized:
            return True
    return None


def format_storefront_address(raw_address: Any) -> str | None:
    if not isinstance(raw_address, dict):
        return None
    parts: list[str] = []
    address_lines = raw_address.get("addressLines")
    if isinstance(address_lines, list):
        parts.extend(str(item).strip() for item in address_lines if str(item).strip())
    for field in ("locality", "administrativeArea", "postalCode", "regionCode"):
        value = _normalized_str(raw_address.get(field))
        if value:
            parts.append(value)
    if not parts:
        return None
    unique_parts: list[str] = []
    for part in parts:
        if part not in unique_parts:
            unique_parts.append(part)
    return ", ".join(unique_parts)


def map_provider_api_error(
    *,
    action: ProviderErrorAction,
    status_code: int | None,
    error_status: str | None,
    message: str,
    is_permission_denied: bool,
) -> ProviderErrorMappingResult:
    normalized_status = (error_status or "").strip().upper()
    message_lower = message.lower()
    response_status = status_code or 502

    if is_permission_denied:
        return ProviderErrorMappingResult(
            status_code=403,
            error_code="permission_denied",
            message="Google Business Profile access is denied for this Google account.",
        )
    if response_status == 404 or normalized_status == "NOT_FOUND":
        return ProviderErrorMappingResult(
            status_code=404,
            error_code="not_found",
            message="Google Business Profile location or verification attempt was not found.",
        )
    if normalized_status == "INVALID_ARGUMENT":
        if action == "complete" and ("pin" in message_lower or "code" in message_lower):
            return ProviderErrorMappingResult(
                status_code=422,
                error_code="invalid_code",
                message="Verification code is invalid or expired.",
            )
        if action in {"start", "options"} and ("method" in message_lower or "option" in message_lower):
            return ProviderErrorMappingResult(
                status_code=409,
                error_code="method_not_available",
                message="Selected verification method is not available for this location.",
            )
        return ProviderErrorMappingResult(
            status_code=422,
            error_code="invalid_verification_state",
            message="Google rejected the verification request for this location state.",
        )
    if response_status == 409 or normalized_status in {"ABORTED", "ALREADY_EXISTS", "FAILED_PRECONDITION", "CONFLICT"}:
        return ProviderErrorMappingResult(
            status_code=409,
            error_code="provider_conflict",
            message="Google reported a verification state conflict. Refresh status and retry if appropriate.",
        )

    record_gbp_verification_observation("provider_error_fallback")
    logger.warning(
        "gbp_provider_error_fallback action=%s status_code=%s error_status=%s",
        action,
        response_status,
        normalized_status or "UNKNOWN",
    )
    return ProviderErrorMappingResult(
        status_code=502,
        error_code="provider_error",
        message="Google Business Profile API request failed.",
    )


def _normalized_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _none_if_empty(value: Any) -> str | None:
    normalized = _normalized_str(value)
    return normalized or None

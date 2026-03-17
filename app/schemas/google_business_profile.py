from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GoogleBusinessProfileConnectStartResponse(BaseModel):
    authorization_url: str = Field(min_length=1)
    state_expires_at: str
    provider: str
    required_scope: str


class GoogleBusinessProfileConnectionStatusResponse(BaseModel):
    provider: str
    connected: bool
    business_id: str
    granted_scopes: list[str]
    refresh_token_present: bool
    expires_at: str | None
    connected_at: str | None
    last_refreshed_at: str | None
    reconnect_required: bool
    required_scopes_satisfied: bool
    token_status: Literal["usable", "refresh_required", "reconnect_required", "insufficient_scope"]


class GoogleBusinessProfileDisconnectResponse(BaseModel):
    status: str
    connection: GoogleBusinessProfileConnectionStatusResponse


class GoogleBusinessProfileVerificationRecordResponse(BaseModel):
    name: str | None
    method: str | None
    state: str | None
    create_time: str | None
    complete_time: str | None


class GoogleBusinessProfileVerificationGuidanceResponse(BaseModel):
    verification_state: GoogleBusinessProfileGuidanceVerificationState
    recommended_action: GoogleBusinessProfileGuidanceRecommendedAction
    priority: GoogleBusinessProfileGuidancePriority
    title: str
    summary: str
    instructions: list[str]
    tips: list[str]
    warnings: list[str]
    troubleshooting: list[str]
    estimated_time: str | None
    cta_label: str | None
    cta_type: GoogleBusinessProfileGuidanceCtaType
    recommended_method: GoogleBusinessProfileVerificationMethod | None
    recommendation_reason: str | None


class GoogleBusinessProfileLocationVerificationResponse(BaseModel):
    has_voice_of_merchant: bool | None
    state_summary: Literal["verified", "unverified", "pending", "unknown"]
    verification_methods: list[str]
    verifications: list[GoogleBusinessProfileVerificationRecordResponse]
    recommended_next_action: Literal[
        "none",
        "start_verification",
        "complete_pending",
        "resolve_access",
        "reconnect_google",
    ]
    guidance: "GoogleBusinessProfileVerificationGuidanceResponse"


class GoogleBusinessProfileLocationResponse(BaseModel):
    location_id: str
    title: str
    address: str | None
    verification: GoogleBusinessProfileLocationVerificationResponse


class GoogleBusinessProfileAccountResponse(BaseModel):
    account_id: str
    account_name: str
    locations: list[GoogleBusinessProfileLocationResponse]


class GoogleBusinessProfileAccountsResponse(BaseModel):
    accounts: list[GoogleBusinessProfileAccountResponse]


class GoogleBusinessProfileFlatLocationResponse(BaseModel):
    account_id: str
    account_name: str
    location_id: str
    title: str
    address: str | None
    verification: GoogleBusinessProfileLocationVerificationResponse


class GoogleBusinessProfileLocationsResponse(BaseModel):
    locations: list[GoogleBusinessProfileFlatLocationResponse]


GoogleBusinessProfileVerificationWorkflowState = Literal[
    "unverified",
    "pending",
    "in_progress",
    "completed",
    "failed",
    "unknown",
]

GoogleBusinessProfileGuidanceVerificationState = Literal[
    "verified",
    "unverified",
    "pending",
    "unknown",
    "in_progress",
    "completed",
    "failed",
]

GoogleBusinessProfileGuidanceRecommendedAction = Literal[
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

GoogleBusinessProfileGuidancePriority = Literal["high", "medium", "low", "info"]
GoogleBusinessProfileGuidanceCtaType = Literal[
    "start_verification",
    "choose_method",
    "submit_code",
    "reconnect",
    "retry",
    "refresh_status",
    "none",
]

GoogleBusinessProfileVerificationMethod = Literal[
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

GoogleBusinessProfileVerificationActionRequired = Literal[
    "none",
    "choose_method",
    "enter_code",
    "wait",
    "retry",
    "reconnect_google",
    "resolve_access",
]

GoogleBusinessProfileVerificationErrorCode = Literal[
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


class GoogleBusinessProfileVerificationMethodOptionResponse(BaseModel):
    option_id: str
    method: GoogleBusinessProfileVerificationMethod
    provider_method: str
    label: str
    description: str | None
    destination: str | None
    requires_code: bool
    eligible: bool


class GoogleBusinessProfileVerificationStatusCurrentResponse(BaseModel):
    verification_id: str
    provider_state: str | None
    method: GoogleBusinessProfileVerificationMethod
    provider_method: str
    create_time: str | None
    complete_time: str | None
    expires_at: str | None


class GoogleBusinessProfileVerificationStatusResponse(BaseModel):
    location_id: str
    verification_state: GoogleBusinessProfileVerificationWorkflowState
    action_required: GoogleBusinessProfileVerificationActionRequired
    message: str
    reconnect_required: bool
    current_verification: GoogleBusinessProfileVerificationStatusCurrentResponse | None
    available_methods: list[GoogleBusinessProfileVerificationMethodOptionResponse]
    guidance: GoogleBusinessProfileVerificationGuidanceResponse


class GoogleBusinessProfileVerificationOptionsResponse(BaseModel):
    location_id: str
    current_verification_state: GoogleBusinessProfileVerificationWorkflowState
    methods: list[GoogleBusinessProfileVerificationMethodOptionResponse]
    guidance: GoogleBusinessProfileVerificationGuidanceResponse


class GoogleBusinessProfileStartVerificationRequest(BaseModel):
    option_id: str | None = None
    selected_method: GoogleBusinessProfileVerificationMethod | None = None
    provider_method: str | None = None
    destination: str | None = None
    language_code: str | None = None
    mailer_contact: str | None = None
    vetted_partner_token: str | None = None


class GoogleBusinessProfileStartVerificationResponse(BaseModel):
    location_id: str
    verification_state: GoogleBusinessProfileVerificationWorkflowState
    verification_id: str | None
    action_required: GoogleBusinessProfileVerificationActionRequired
    message: str
    expires_at: str | None
    status: GoogleBusinessProfileVerificationStatusResponse
    guidance: GoogleBusinessProfileVerificationGuidanceResponse


class GoogleBusinessProfileCompleteVerificationRequest(BaseModel):
    verification_id: str | None = None
    code: str = Field(min_length=1, max_length=64)


class GoogleBusinessProfileCompleteVerificationResponse(BaseModel):
    location_id: str
    verification_state: GoogleBusinessProfileVerificationWorkflowState
    verification_id: str | None
    action_required: GoogleBusinessProfileVerificationActionRequired
    message: str
    expires_at: str | None
    status: GoogleBusinessProfileVerificationStatusResponse
    guidance: GoogleBusinessProfileVerificationGuidanceResponse


class GoogleBusinessProfileRetryVerificationRequest(BaseModel):
    option_id: str | None = None
    selected_method: GoogleBusinessProfileVerificationMethod | None = None
    provider_method: str | None = None
    destination: str | None = None
    language_code: str | None = None
    mailer_contact: str | None = None
    vetted_partner_token: str | None = None


class GoogleBusinessProfileRetryVerificationResponse(BaseModel):
    location_id: str
    verification_state: GoogleBusinessProfileVerificationWorkflowState
    verification_id: str | None
    action_required: GoogleBusinessProfileVerificationActionRequired
    message: str
    expires_at: str | None
    status: GoogleBusinessProfileVerificationStatusResponse
    guidance: GoogleBusinessProfileVerificationGuidanceResponse

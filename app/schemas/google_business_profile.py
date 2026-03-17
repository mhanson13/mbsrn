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

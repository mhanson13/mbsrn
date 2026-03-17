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

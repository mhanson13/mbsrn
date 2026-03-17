from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    TenantContext,
    get_authenticated_principal,
    get_google_business_profile_connection_service,
    get_google_business_profile_service,
    get_tenant_context,
)
from app.models.principal import Principal
from app.schemas.google_business_profile import (
    GoogleBusinessProfileAccountsResponse,
    GoogleBusinessProfileAccountResponse,
    GoogleBusinessProfileConnectionStatusResponse,
    GoogleBusinessProfileConnectStartResponse,
    GoogleBusinessProfileDisconnectResponse,
    GoogleBusinessProfileFlatLocationResponse,
    GoogleBusinessProfileLocationResponse,
    GoogleBusinessProfileLocationsResponse,
    GoogleBusinessProfileLocationVerificationResponse,
    GoogleBusinessProfileVerificationRecordResponse,
)
from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionConfigurationError,
    GoogleBusinessProfileConnectionNotFoundError,
    GoogleBusinessProfileConnectionService,
    GoogleBusinessProfileConnectionStatusResult,
    GoogleBusinessProfileConnectionValidationError,
)
from app.services.google_business_profile_service import (
    GoogleBusinessProfileAccountResult,
    GoogleBusinessProfileAccountsResult,
    GoogleBusinessProfileFlatLocationResult,
    GoogleBusinessProfileLocationResult,
    GoogleBusinessProfileLocationsResult,
    GoogleBusinessProfileService,
    GoogleBusinessProfileServiceError,
    GoogleBusinessProfileVerificationRecordResult,
    GoogleBusinessProfileVerificationResult,
)

router = APIRouter(prefix="/api/integrations/google/business-profile", tags=["integrations"])


@router.post("/connect/start", response_model=GoogleBusinessProfileConnectStartResponse)
def start_google_business_profile_connect(
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileConnectStartResponse:
    try:
        result = service.start_connection(
            business_id=tenant_context.business_id,
            principal_id=principal.id,
        )
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return GoogleBusinessProfileConnectStartResponse(
        authorization_url=result.authorization_url,
        state_expires_at=result.state_expires_at,
        provider=result.provider,
        required_scope=result.required_scope,
    )


@router.get("/connect/callback", response_model=GoogleBusinessProfileConnectionStatusResponse)
def google_business_profile_connect_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileConnectionStatusResponse:
    try:
        result = service.handle_callback(
            state=state,
            code=code,
            error=error,
            error_description=error_description,
        )
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionValidationError as exc:
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return _to_connection_response(result)


@router.get("/connection", response_model=GoogleBusinessProfileConnectionStatusResponse)
def get_google_business_profile_connection(
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileConnectionStatusResponse:
    try:
        result = service.get_connection_status(business_id=tenant_context.business_id)
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return _to_connection_response(result)


@router.post("/disconnect", response_model=GoogleBusinessProfileDisconnectResponse)
def disconnect_google_business_profile(
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileDisconnectResponse:
    try:
        disconnected = service.revoke_or_disconnect_provider(
            business_id=tenant_context.business_id,
            actor_principal_id=principal.id,
        )
        current = service.get_connection_status(business_id=tenant_context.business_id)
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return GoogleBusinessProfileDisconnectResponse(
        status="disconnected" if disconnected else "not_connected",
        connection=_to_connection_response(current),
    )


@router.get("/accounts", response_model=GoogleBusinessProfileAccountsResponse)
def list_google_business_profile_accounts(
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileAccountsResponse:
    try:
        result = service.list_accounts(business_id=tenant_context.business_id)
    except GoogleBusinessProfileServiceError as exc:
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return _to_accounts_response(result)


@router.get("/locations", response_model=GoogleBusinessProfileLocationsResponse)
def list_google_business_profile_locations(
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileLocationsResponse:
    try:
        result = service.list_locations(business_id=tenant_context.business_id)
    except GoogleBusinessProfileServiceError as exc:
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return _to_locations_response(result)


@router.get("/locations/{location_id}/verification", response_model=GoogleBusinessProfileLocationVerificationResponse)
def get_google_business_profile_location_verification(
    location_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileLocationVerificationResponse:
    try:
        result = service.get_location_verification(
            business_id=tenant_context.business_id,
            location_id=location_id,
        )
    except GoogleBusinessProfileServiceError as exc:
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return _to_verification_response(result)


def _to_connection_response(
    result: GoogleBusinessProfileConnectionStatusResult,
) -> GoogleBusinessProfileConnectionStatusResponse:
    return GoogleBusinessProfileConnectionStatusResponse(
        provider=result.provider,
        connected=result.connected,
        business_id=result.business_id,
        granted_scopes=list(result.granted_scopes),
        refresh_token_present=result.refresh_token_present,
        expires_at=result.expires_at,
        connected_at=result.connected_at,
        last_refreshed_at=result.last_refreshed_at,
        reconnect_required=result.reconnect_required,
        required_scopes_satisfied=result.required_scopes_satisfied,
        token_status=result.token_status,
    )


def _to_accounts_response(result: GoogleBusinessProfileAccountsResult) -> GoogleBusinessProfileAccountsResponse:
    return GoogleBusinessProfileAccountsResponse(
        accounts=[
            _to_account_response(account)
            for account in result.accounts
        ]
    )


def _to_account_response(result: GoogleBusinessProfileAccountResult) -> GoogleBusinessProfileAccountResponse:
    return GoogleBusinessProfileAccountResponse(
        account_id=result.account_id,
        account_name=result.account_name,
        locations=[
            _to_location_response(location)
            for location in result.locations
        ],
    )


def _to_location_response(result: GoogleBusinessProfileLocationResult) -> GoogleBusinessProfileLocationResponse:
    return GoogleBusinessProfileLocationResponse(
        location_id=result.location_id,
        title=result.title,
        address=result.address,
        verification=_to_verification_response(result.verification),
    )


def _to_locations_response(result: GoogleBusinessProfileLocationsResult) -> GoogleBusinessProfileLocationsResponse:
    return GoogleBusinessProfileLocationsResponse(
        locations=[
            _to_flat_location_response(location)
            for location in result.locations
        ]
    )


def _to_flat_location_response(result: GoogleBusinessProfileFlatLocationResult) -> GoogleBusinessProfileFlatLocationResponse:
    return GoogleBusinessProfileFlatLocationResponse(
        account_id=result.account_id,
        account_name=result.account_name,
        location_id=result.location_id,
        title=result.title,
        address=result.address,
        verification=_to_verification_response(result.verification),
    )


def _to_verification_response(
    result: GoogleBusinessProfileVerificationResult,
) -> GoogleBusinessProfileLocationVerificationResponse:
    return GoogleBusinessProfileLocationVerificationResponse(
        has_voice_of_merchant=result.has_voice_of_merchant,
        state_summary=result.state_summary,
        verification_methods=list(result.verification_methods),
        verifications=[
            _to_verification_record_response(item)
            for item in result.verifications
        ],
        recommended_next_action=result.recommended_next_action,
    )


def _to_verification_record_response(
    result: GoogleBusinessProfileVerificationRecordResult,
) -> GoogleBusinessProfileVerificationRecordResponse:
    return GoogleBusinessProfileVerificationRecordResponse(
        name=result.name,
        method=result.method,
        state=result.state,
        create_time=result.create_time,
        complete_time=result.complete_time,
    )

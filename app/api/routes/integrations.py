from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    TenantContext,
    get_authenticated_principal,
    get_google_business_profile_connection_service,
    get_tenant_context,
)
from app.models.principal import Principal
from app.schemas.google_business_profile import (
    GoogleBusinessProfileConnectionStatusResponse,
    GoogleBusinessProfileConnectStartResponse,
    GoogleBusinessProfileDisconnectResponse,
)
from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionConfigurationError,
    GoogleBusinessProfileConnectionNotFoundError,
    GoogleBusinessProfileConnectionService,
    GoogleBusinessProfileConnectionStatusResult,
    GoogleBusinessProfileConnectionValidationError,
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

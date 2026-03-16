from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    TenantContext,
    get_auth_identity_service,
    get_authenticated_principal,
    get_tenant_context,
)
from app.schemas.auth import AuthExchangeResponse, AuthMeResponse, AuthPrincipalRead, GoogleAuthExchangeRequest
from app.services.auth_identity import (
    AuthIdentityNotFoundError,
    AuthIdentityService,
    AuthIdentityValidationError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/google/exchange", response_model=AuthExchangeResponse)
def exchange_google_id_token(
    payload: GoogleAuthExchangeRequest,
    auth_identity_service: AuthIdentityService = Depends(get_auth_identity_service),
) -> AuthExchangeResponse:
    try:
        result = auth_identity_service.exchange_google_id_token(id_token=payload.id_token)
    except AuthIdentityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AuthIdentityValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return AuthExchangeResponse(
        access_token=result.access_token,
        token_type="bearer",
        expires_at=result.expires_at,
        auth_source=result.auth_source,
        principal=AuthPrincipalRead(
            business_id=result.principal.business_id,
            principal_id=result.principal.id,
            display_name=result.principal.display_name,
            role=result.principal.role,
            is_active=result.principal.is_active,
        ),
    )


@router.get("/me", response_model=AuthMeResponse)
def get_auth_me(
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal=Depends(get_authenticated_principal),
) -> AuthMeResponse:
    return AuthMeResponse(
        business_id=principal.business_id,
        principal_id=principal.id,
        display_name=principal.display_name,
        role=principal.role,
        auth_source=tenant_context.auth_source,
    )

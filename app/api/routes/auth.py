from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import (
    TenantContext,
    get_auth_identity_service,
    get_authenticated_principal,
    get_tenant_context,
)
from app.schemas.auth import (
    AuthExchangeResponse,
    AuthMeResponse,
    AuthLogoutRequest,
    AuthPrincipalRead,
    AuthRefreshRequest,
    AuthRefreshResponse,
    GoogleAuthExchangeRequest,
)
from app.services.auth_identity import (
    AuthIdentityNotFoundError,
    AuthIdentityService,
    AuthIdentityValidationError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _parse_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")
    return token.strip()


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
        refresh_token=result.refresh_token,
        token_type="bearer",
        expires_at=result.expires_at,
        refresh_expires_at=result.refresh_expires_at,
        auth_source=result.auth_source,
        principal=AuthPrincipalRead(
            business_id=result.principal.business_id,
            principal_id=result.principal.id,
            display_name=result.principal.display_name,
            role=result.principal.role,
            is_active=result.principal.is_active,
        ),
    )


@router.post("/refresh", response_model=AuthRefreshResponse)
def refresh_app_session(
    payload: AuthRefreshRequest,
    auth_identity_service: AuthIdentityService = Depends(get_auth_identity_service),
) -> AuthRefreshResponse:
    try:
        result = auth_identity_service.refresh_session(refresh_token=payload.refresh_token)
    except AuthIdentityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AuthIdentityValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return AuthRefreshResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type="bearer",
        expires_at=result.expires_at,
        refresh_expires_at=result.refresh_expires_at,
        auth_source=result.auth_source,
        principal=AuthPrincipalRead(
            business_id=result.principal.business_id,
            principal_id=result.principal.id,
            display_name=result.principal.display_name,
            role=result.principal.role,
            is_active=result.principal.is_active,
        ),
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout_app_session(
    payload: AuthLogoutRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    auth_identity_service: AuthIdentityService = Depends(get_auth_identity_service),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    del tenant_context  # scoped by existing dependency enforcement
    access_token = _parse_bearer_token(authorization)
    try:
        auth_identity_service.logout_session(
            access_token=access_token,
            refresh_token=payload.refresh_token,
        )
    except AuthIdentityValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return {"status": "ok"}


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

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_api_credential_service,
    get_business_settings_service,
    require_credential_manager_principal,
    get_tenant_context,
    resolve_tenant_business_id,
    TenantContext,
)
from app.models.principal import Principal
from app.schemas.api_credential import (
    APICredentialCreateRequest,
    APICredentialIssueResponse,
    APICredentialListResponse,
    APICredentialRead,
    APICredentialRotateResponse,
)
from app.schemas.business import BusinessSettingsRead, BusinessSettingsUpdateRequest
from app.services.api_credentials import (
    APICredentialNotFoundError,
    APICredentialService,
    APICredentialValidationError,
)
from app.services.business_settings import (
    BusinessSettingsNotFoundError,
    BusinessSettingsService,
    BusinessSettingsValidationError,
)

router = APIRouter(prefix="/api/businesses", tags=["businesses"])


@router.get("/{business_id}", response_model=BusinessSettingsRead)
def get_business(
    business_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    business_settings_service: BusinessSettingsService = Depends(get_business_settings_service),
) -> BusinessSettingsRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        business = business_settings_service.get(business_id=scoped_business_id)
    except BusinessSettingsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BusinessSettingsRead.model_validate(business)


@router.patch("/{business_id}/settings", response_model=BusinessSettingsRead)
def patch_business_settings(
    business_id: str,
    payload: BusinessSettingsUpdateRequest,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    business_settings_service: BusinessSettingsService = Depends(get_business_settings_service),
) -> BusinessSettingsRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        business = business_settings_service.update_settings(business_id=scoped_business_id, payload=payload)
    except BusinessSettingsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BusinessSettingsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return BusinessSettingsRead.model_validate(business)


@router.get("/{business_id}/credentials", response_model=APICredentialListResponse)
def list_api_credentials(
    business_id: str,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    api_credential_service: APICredentialService = Depends(get_api_credential_service),
) -> APICredentialListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        credentials = api_credential_service.list_for_business(business_id=scoped_business_id)
    except APICredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return APICredentialListResponse(
        items=[APICredentialRead.model_validate(credential) for credential in credentials],
        total=len(credentials),
    )


@router.post(
    "/{business_id}/credentials",
    response_model=APICredentialIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_api_credential(
    business_id: str,
    payload: APICredentialCreateRequest,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    api_credential_service: APICredentialService = Depends(get_api_credential_service),
) -> APICredentialIssueResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        issued = api_credential_service.create_credential(
            business_id=scoped_business_id,
            principal_id=payload.principal_id,
            principal_display_name=payload.principal_display_name,
            principal_role=payload.principal_role,
            credential_label=payload.credential_label,
        )
    except APICredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except APICredentialValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return APICredentialIssueResponse(
        credential=APICredentialRead.model_validate(issued.credential),
        token=issued.token,
    )


@router.post(
    "/{business_id}/credentials/{credential_id}/disable",
    response_model=APICredentialRead,
)
def disable_api_credential(
    business_id: str,
    credential_id: str,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    api_credential_service: APICredentialService = Depends(get_api_credential_service),
) -> APICredentialRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        credential = api_credential_service.disable_credential(
            business_id=scoped_business_id,
            credential_id=credential_id,
        )
    except APICredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return APICredentialRead.model_validate(credential)


@router.post(
    "/{business_id}/credentials/{credential_id}/revoke",
    response_model=APICredentialRead,
)
def revoke_api_credential(
    business_id: str,
    credential_id: str,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    api_credential_service: APICredentialService = Depends(get_api_credential_service),
) -> APICredentialRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        credential = api_credential_service.revoke_credential(
            business_id=scoped_business_id,
            credential_id=credential_id,
        )
    except APICredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return APICredentialRead.model_validate(credential)


@router.post(
    "/{business_id}/credentials/{credential_id}/rotate",
    response_model=APICredentialRotateResponse,
    status_code=status.HTTP_201_CREATED,
)
def rotate_api_credential(
    business_id: str,
    credential_id: str,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    api_credential_service: APICredentialService = Depends(get_api_credential_service),
) -> APICredentialRotateResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        issued = api_credential_service.rotate_credential(
            business_id=scoped_business_id,
            credential_id=credential_id,
        )
    except APICredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except APICredentialValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return APICredentialRotateResponse(
        replaced_credential_id=credential_id,
        credential=APICredentialRead.model_validate(issued.credential),
        token=issued.token,
    )

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_business_settings_service,
    get_tenant_context,
    resolve_tenant_business_id,
    TenantContext,
)
from app.schemas.business import BusinessSettingsRead, BusinessSettingsUpdateRequest
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

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_business_settings_service
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
    business_settings_service: BusinessSettingsService = Depends(get_business_settings_service),
) -> BusinessSettingsRead:
    try:
        business = business_settings_service.get(business_id=business_id)
    except BusinessSettingsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BusinessSettingsRead.model_validate(business)


@router.patch("/{business_id}/settings", response_model=BusinessSettingsRead)
def patch_business_settings(
    business_id: str,
    payload: BusinessSettingsUpdateRequest,
    business_settings_service: BusinessSettingsService = Depends(get_business_settings_service),
) -> BusinessSettingsRead:
    try:
        business = business_settings_service.update_settings(business_id=business_id, payload=payload)
    except BusinessSettingsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BusinessSettingsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return BusinessSettingsRead.model_validate(business)

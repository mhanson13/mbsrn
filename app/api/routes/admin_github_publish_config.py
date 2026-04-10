from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    TenantContext,
    get_github_publish_config_service,
    get_tenant_context,
    require_admin_rate_limit,
    require_credential_manager_principal,
)
from app.models.principal import Principal
from app.schemas.github_publish_config import (
    GitHubPublishConfigRead,
    GitHubPublishConfigUpdateRequest,
)
from app.services.github_publish_config import (
    GitHubPublishConfigService,
    GitHubPublishConfigValidationError,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/github-publish-config", response_model=GitHubPublishConfigRead)
def get_github_publish_config(
    _: None = Depends(require_admin_rate_limit("github_publish_config_read")),
    __: Principal = Depends(require_credential_manager_principal),
    ___: TenantContext = Depends(get_tenant_context),
    service: GitHubPublishConfigService = Depends(get_github_publish_config_service),
) -> GitHubPublishConfigRead:
    return GitHubPublishConfigRead.model_validate(service.get())


@router.put("/github-publish-config", response_model=GitHubPublishConfigRead)
def update_github_publish_config(
    payload: GitHubPublishConfigUpdateRequest,
    _: None = Depends(require_admin_rate_limit("github_publish_config_update")),
    principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    service: GitHubPublishConfigService = Depends(get_github_publish_config_service),
) -> GitHubPublishConfigRead:
    try:
        config = service.update(
            payload=payload,
            actor_principal_id=principal.id,
            actor_business_id=tenant_context.business_id,
        )
    except GitHubPublishConfigValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return GitHubPublishConfigRead.model_validate(config)

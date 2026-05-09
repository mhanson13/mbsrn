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
    normalize_namespace_isolation_defaults,
)
from app.services.github_publish_config import (
    GitHubPublishConfigService,
    GitHubPublishConfigValidationError,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _to_github_publish_config_read(config) -> GitHubPublishConfigRead:  # noqa: ANN001
    repository_value = getattr(config, "repository", None) or ""
    owner_value = repository_value.split("/", 1)[0].strip() if repository_value else ""
    return GitHubPublishConfigRead(
        id=getattr(config, "id", None),
        owner=owner_value,
        repository=owner_value,
        default_branch=getattr(config, "default_branch", "main") or "main",
        base_path=getattr(config, "base_path", "/") or "/",
        deploy_workflow_mode=(
            getattr(config, "deploy_workflow_mode", "site_repo_template_v1") or "site_repo_template_v1"
        ),
        target_environment_key=(getattr(config, "target_environment_key", "gke_prod") or "gke_prod"),
        target_environment_source=(getattr(config, "target_environment_source", "admin_config") or "admin_config"),
        github_repository_auto_create_enabled=bool(getattr(config, "github_repository_auto_create_enabled", False)),
        managed_gke_cluster_name=(getattr(config, "managed_gke_cluster_name", None) or None),
        managed_gke_cluster_location=(getattr(config, "managed_gke_cluster_location", None) or None),
        managed_gke_project_id=(getattr(config, "managed_gke_project_id", None) or None),
        managed_gcp_deploy_key_configured=bool(
            str(getattr(config, "managed_gcp_deploy_key_encrypted", "") or "").strip()
            and str(getattr(config, "managed_gcp_deploy_key_key_version", "") or "").strip()
        ),
        managed_gcp_deploy_key_updated_at=getattr(config, "managed_gcp_deploy_key_updated_at", None),
        namespace_isolation_defaults=normalize_namespace_isolation_defaults(
            getattr(config, "namespace_isolation_defaults_json", None)
        ),
        enabled=bool(getattr(config, "enabled", False)),
        created_at=getattr(config, "created_at", None),
        updated_at=getattr(config, "updated_at", None),
    )


@router.get("/github-publish-config", response_model=GitHubPublishConfigRead)
def get_github_publish_config(
    _: None = Depends(require_admin_rate_limit("github_publish_config_read")),
    __: Principal = Depends(require_credential_manager_principal),
    ___: TenantContext = Depends(get_tenant_context),
    service: GitHubPublishConfigService = Depends(get_github_publish_config_service),
) -> GitHubPublishConfigRead:
    return _to_github_publish_config_read(service.get())


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
    return _to_github_publish_config_read(config)

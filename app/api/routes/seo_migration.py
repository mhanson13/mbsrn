from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    TenantContext,
    get_seo_migration_service,
    get_tenant_context,
    resolve_tenant_business_id,
)
from app.schemas.seo_migration import (
    SEOMigrationAnalyticsConfigUpdateRequest,
    SEOMigrationArtifactApproveRequest,
    SEOMigrationArtifactFilePreviewRead,
    SEOMigrationArtifactVersionListResponse,
    SEOMigrationArtifactVersionRead,
    SEOMigrationDeployActionRead,
    SEOMigrationDeployConfigUpdateRequest,
    SEOMigrationDeployRequest,
    SEOMigrationDraftGenerateRequest,
    SEOMigrationEnrichedContentUpdateRequest,
    SEOMigrationHistoryListRead,
    SEOMigrationPublishActionRead,
    SEOMigrationPublishConfigUpdateRequest,
    SEOMigrationPublishRequest,
    SEOMigrationPromptPreviewRead,
    SEOMigrationRequirementsUpdateRequest,
    SEOMigrationSourceIngestRequest,
    SEOMigrationSourceSnapshotRead,
    SEOMigrationWorkspaceCreateOrUpdateRequest,
    SEOMigrationWorkspaceRead,
    SEOMigrationWorkspaceSummaryRead,
)
from app.services.seo_migration import (
    SEOMigrationNotFoundError,
    SEOMigrationService,
    SEOMigrationValidationError,
)


router = APIRouter(prefix="/api/businesses/{business_id}/seo", tags=["seo"])

_DRAFT_ONLY_NOTICE = (
    "Draft artifacts only. Nothing is published or deployed automatically. "
    "Approval, GitHub publish, and GKE deploy remain explicit operator-triggered steps."
)


def _to_workspace_read(workspace) -> SEOMigrationWorkspaceRead:  # noqa: ANN001
    return SEOMigrationWorkspaceRead.model_validate(workspace)


def _to_artifact_read(artifact) -> SEOMigrationArtifactVersionRead:  # noqa: ANN001
    return SEOMigrationArtifactVersionRead.model_validate(artifact)


def _validation_error_detail(exc: SEOMigrationValidationError) -> str | dict[str, object]:
    detail = exc.to_error_detail()
    if isinstance(detail, dict) and (
        detail.get("failure_category")
        or detail.get("failure_reason")
        or detail.get("error_code")
        or detail.get("retryable") is not None
    ):
        return detail
    return str(exc)


@router.put("/sites/{site_id}/migration/workspace", response_model=SEOMigrationWorkspaceRead)
def upsert_seo_migration_workspace(
    business_id: str,
    site_id: str,
    payload: SEOMigrationWorkspaceCreateOrUpdateRequest | None = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    normalized_payload = payload or SEOMigrationWorkspaceCreateOrUpdateRequest()
    try:
        workspace = migration_service.create_or_update_workspace(
            business_id=scoped_business_id,
            site_id=site_id,
            source_url=normalized_payload.source_url,
            operator_requirements=(
                normalized_payload.operator_requirements.model_dump(mode="json")
                if normalized_payload.operator_requirements
                else None
            ),
            enriched_content_notes=(
                normalized_payload.enriched_content_notes.model_dump(mode="json")
                if normalized_payload.enriched_content_notes
                else None
            ),
            publish_config=(
                normalized_payload.publish_config.model_dump(mode="json") if normalized_payload.publish_config else None
            ),
            deploy_config=(
                normalized_payload.deploy_config.model_dump(mode="json") if normalized_payload.deploy_config else None
            ),
            analytics_config=(
                normalized_payload.analytics_config.model_dump(mode="json")
                if normalized_payload.analytics_config
                else None
            ),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.get("/sites/{site_id}/migration/workspace", response_model=SEOMigrationWorkspaceRead)
def get_seo_migration_workspace(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.get_workspace(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.post("/sites/{site_id}/migration/source-ingest", response_model=SEOMigrationWorkspaceRead)
def ingest_seo_migration_source(
    business_id: str,
    site_id: str,
    payload: SEOMigrationSourceIngestRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.ingest_source_snapshot(
            business_id=scoped_business_id,
            site_id=site_id,
            source_url=payload.source_url,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/operator-requirements", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_operator_requirements(
    business_id: str,
    site_id: str,
    payload: SEOMigrationRequirementsUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_operator_requirements(
            business_id=scoped_business_id,
            site_id=site_id,
            operator_requirements=payload.operator_requirements.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/enriched-content", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_enriched_content_notes(
    business_id: str,
    site_id: str,
    payload: SEOMigrationEnrichedContentUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_enriched_content_notes(
            business_id=scoped_business_id,
            site_id=site_id,
            enriched_content_notes=payload.enriched_content_notes.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/publish-config", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_publish_config(
    business_id: str,
    site_id: str,
    payload: SEOMigrationPublishConfigUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_publish_config(
            business_id=scoped_business_id,
            site_id=site_id,
            publish_config=payload.publish_config.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/deploy-config", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_deploy_config(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDeployConfigUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_deploy_config(
            business_id=scoped_business_id,
            site_id=site_id,
            deploy_config=payload.deploy_config.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/analytics-config", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_analytics_config(
    business_id: str,
    site_id: str,
    payload: SEOMigrationAnalyticsConfigUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_analytics_config(
            business_id=scoped_business_id,
            site_id=site_id,
            analytics_config=payload.analytics_config.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.get("/sites/{site_id}/migration/summary", response_model=SEOMigrationWorkspaceSummaryRead)
def get_seo_migration_workspace_summary(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = migration_service.get_workspace_summary(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    source_snapshot = (
        SEOMigrationSourceSnapshotRead.model_validate(summary.source_snapshot) if summary.source_snapshot else None
    )
    latest_artifact = _to_artifact_read(summary.latest_artifact) if summary.latest_artifact else None
    return SEOMigrationWorkspaceSummaryRead(
        workspace=_to_workspace_read(summary.workspace),
        source_snapshot=source_snapshot,
        context_summary=summary.context_summary,
        latest_artifact=latest_artifact,
        publish_readiness=summary.publish_readiness,
        deploy_readiness=summary.deploy_readiness,
        publish_history=summary.publish_history,
        deploy_history=summary.deploy_history,
        draft_only_notice=_DRAFT_ONLY_NOTICE,
    )


@router.get("/sites/{site_id}/migration/prompt-preview", response_model=SEOMigrationPromptPreviewRead)
def get_seo_migration_prompt_preview(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationPromptPreviewRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        preview = migration_service.get_prompt_preview(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationPromptPreviewRead(
        provider_name=preview.provider_name,
        model_name=preview.model_name,
        prompt_version=preview.prompt_version,
        context_json=preview.context_json,
        system_prompt=preview.system_prompt,
        user_prompt=preview.user_prompt,
    )


@router.post(
    "/sites/{site_id}/migration/generate-draft-artifacts",
    response_model=SEOMigrationArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_seo_migration_draft_artifacts(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDraftGenerateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionRead:
    del payload.force_new_version
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        artifact = migration_service.generate_draft_artifacts(
            business_id=scoped_business_id,
            site_id=site_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_validation_error_detail(exc),
        ) from exc
    return _to_artifact_read(artifact)


@router.get("/sites/{site_id}/migration/artifact-versions", response_model=SEOMigrationArtifactVersionListResponse)
def list_seo_migration_artifact_versions(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        versions = migration_service.list_artifact_versions(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationArtifactVersionListResponse(
        items=[_to_artifact_read(item) for item in versions],
        total=len(versions),
    )


@router.get(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}",
    response_model=SEOMigrationArtifactVersionRead,
)
def get_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        artifact = migration_service.get_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_artifact_read(artifact)


@router.post(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/approve",
    response_model=SEOMigrationArtifactVersionRead,
)
def approve_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    payload: SEOMigrationArtifactApproveRequest | None = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    normalized_payload = payload or SEOMigrationArtifactApproveRequest()
    try:
        artifact = migration_service.approve_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
            approval_notes=normalized_payload.approval_notes,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_artifact_read(artifact)


@router.post("/sites/{site_id}/migration/publish", response_model=SEOMigrationPublishActionRead)
def publish_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    payload: SEOMigrationPublishRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationPublishActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.publish_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=payload.artifact_version_id,
            dry_run=payload.dry_run,
            commit_message=payload.commit_message,
            analytics_measurement_id=payload.analytics_measurement_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationPublishActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        artifact=_to_artifact_read(action_result.artifact),
        readiness=action_result.readiness,
        result=action_result.result,
    )


@router.post("/sites/{site_id}/migration/deploy", response_model=SEOMigrationDeployActionRead)
def deploy_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDeployRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationDeployActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.deploy_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=payload.artifact_version_id,
            dry_run=payload.dry_run,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationDeployActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        artifact=_to_artifact_read(action_result.artifact),
        readiness=action_result.readiness,
        result=action_result.result,
    )


@router.get("/sites/{site_id}/migration/publish-history", response_model=SEOMigrationHistoryListRead)
def list_seo_migration_publish_history(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationHistoryListRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        history = migration_service.list_publish_history(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationHistoryListRead(items=history, total=len(history))


@router.get("/sites/{site_id}/migration/deploy-history", response_model=SEOMigrationHistoryListRead)
def list_seo_migration_deploy_history(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationHistoryListRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        history = migration_service.list_deploy_history(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationHistoryListRead(items=history, total=len(history))


@router.get(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/file-preview",
    response_model=SEOMigrationArtifactFilePreviewRead,
)
def preview_seo_migration_artifact_file(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    path: str = Query(min_length=1, max_length=160),
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactFilePreviewRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        media_type, content = migration_service.preview_artifact_file(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
            path=path,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationArtifactFilePreviewRead(
        artifact_version_id=artifact_version_id,
        path=path,
        media_type=media_type,
        content=content,
    )

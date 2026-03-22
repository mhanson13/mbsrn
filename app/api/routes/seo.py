from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

from app.api.deps import (
    TenantContext,
    SEOCompetitorProfileGenerationRunExecutor,
    get_seo_audit_service,
    get_seo_automation_service,
    get_seo_competitor_comparison_service,
    get_seo_competitor_profile_generation_run_executor,
    get_seo_competitor_profile_generation_service,
    get_seo_competitor_summary_service,
    get_seo_recommendation_narrative_service,
    get_seo_competitor_service,
    get_seo_recommendation_service,
    get_seo_site_service,
    get_seo_summary_service,
    require_admin_rate_limit,
    require_credential_manager_principal,
    get_tenant_context,
    resolve_tenant_business_id,
)
from app.models.principal import Principal, PrincipalRole
from app.schemas.seo_audit import (
    SEOAuditFindingListResponse,
    SEOAuditFindingRead,
    SEOAuditReportRead,
    SEOAuditReportSiteRead,
    SEOAuditRunCreateRequest,
    SEOAuditRunListResponse,
    SEOAuditRunRead,
    SEOAuditRunSummaryRead,
)
from app.schemas.seo_site import (
    SEOSiteCreateRequest,
    SEOSiteListResponse,
    SEOSiteRead,
    SEOSiteUpdateRequest,
)
from app.schemas.seo_competitor import (
    SEOCompetitorComparisonFindingListResponse,
    SEOCompetitorComparisonFindingRead,
    SEOCompetitorComparisonMetricRollupRead,
    SEOCompetitorComparisonReportRead,
    SEOCompetitorComparisonSummaryListResponse,
    SEOCompetitorComparisonSummaryRead,
    SEOCompetitorComparisonRunRollupsRead,
    SEOCompetitorComparisonRunCreateRequest,
    SEOCompetitorComparisonRunSiteCreateRequest,
    SEOCompetitorComparisonRunListResponse,
    SEOCompetitorComparisonRunRead,
    SEOCompetitorProfileDraftAcceptRequest,
    SEOCompetitorProfileDraftEditRequest,
    SEOCompetitorProfileDraftRead,
    SEOCompetitorProfileDraftRejectRequest,
    SEOCompetitorProfileGenerationRunCreateRequest,
    SEOCompetitorProfileGenerationRunDetailRead,
    SEOCompetitorProfileGenerationRunListResponse,
    SEOCompetitorProfileGenerationObservabilitySummaryRead,
    SEOCompetitorProfileGenerationRunRead,
    SEOCompetitorDomainCreateRequest,
    SEOCompetitorDomainListResponse,
    SEOCompetitorDomainRead,
    SEOCompetitorSetCreateRequest,
    SEOCompetitorSetListResponse,
    SEOCompetitorSetRead,
    SEOCompetitorSetUpdateRequest,
    SEOCompetitorSnapshotRunCreateRequest,
    SEOCompetitorSnapshotPageListResponse,
    SEOCompetitorSnapshotPageRead,
    SEOCompetitorSnapshotRunListResponse,
    SEOCompetitorSnapshotRunRead,
)
from app.schemas.seo_recommendation import (
    SEORecommendationBacklogRead,
    SEORecommendationFilteredSummary,
    SEORecommendationListQuery,
    SEORecommendationListResponse,
    SEORecommendationPrioritizedReportRead,
    SEORecommendationRead,
    SEORecommendationNarrativeListResponse,
    SEORecommendationNarrativeRead,
    SEORecommendationRunCreateRequest,
    SEORecommendationRunListResponse,
    SEORecommendationRunRead,
    SEORecommendationRunReportRead,
    SEORecommendationWorkflowUpdateRequest,
)
from app.schemas.seo_automation import (
    SEOAutomationConfigPatchRequest,
    SEOAutomationConfigRead,
    SEOAutomationConfigUpsertRequest,
    SEOAutomationRunListResponse,
    SEOAutomationRunRead,
    SEOAutomationStatusRead,
)
from app.services.seo_audit import SEOAuditNotFoundError, SEOAuditService, SEOAuditValidationError
from app.services.seo_automation import (
    SEOAutomationConflictError,
    SEOAutomationNotFoundError,
    SEOAutomationService,
    SEOAutomationValidationError,
)
from app.services.seo_competitor_comparison import (
    SEOCompetitorComparisonNotFoundError,
    SEOCompetitorComparisonService,
    SEOCompetitorComparisonValidationError,
)
from app.services.seo_competitor_profile_generation import (
    SEOCompetitorProfileGenerationNotFoundError,
    SEOCompetitorProfileGenerationService,
    SEOCompetitorProfileGenerationValidationError,
)
from app.services.seo_competitor_summary import (
    SEOCompetitorSummaryNotFoundError,
    SEOCompetitorSummaryService,
    SEOCompetitorSummaryValidationError,
)
from app.services.seo_recommendations import (
    SEORecommendationNotFoundError,
    SEORecommendationService,
    SEORecommendationValidationError,
)
from app.services.seo_recommendation_narratives import (
    SEORecommendationNarrativeNotFoundError,
    SEORecommendationNarrativeService,
    SEORecommendationNarrativeValidationError,
)
from app.services.seo_competitors import (
    SEOCompetitorNotFoundError,
    SEOCompetitorService,
    SEOCompetitorValidationError,
)
from app.services.seo_sites import SEOSiteNotFoundError, SEOSiteService, SEOSiteValidationError
from app.services.seo_summary import SEOSummaryNotFoundError, SEOSummaryService, SEOSummaryValidationError
from app.schemas.seo_summary import SEOAuditSummaryRead

router = APIRouter(prefix="/api/businesses/{business_id}/seo", tags=["seo"])
router_v1 = APIRouter(prefix="/api/v1/businesses/{business_id}/seo", tags=["seo"])


def _assert_site_match(*, expected_site_id: str, actual_site_id: str, detail: str) -> None:
    if actual_site_id != expected_site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _summarize_recommendation_items(
    items: list[SEORecommendationRead],
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_effort_bucket: dict[str, int] = {}
    by_priority_band: dict[str, int] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_category[item.category] = by_category.get(item.category, 0) + 1
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        by_effort_bucket[item.effort_bucket] = by_effort_bucket.get(item.effort_bucket, 0) + 1
        by_priority_band[item.priority_band] = by_priority_band.get(item.priority_band, 0) + 1
    return (
        dict(sorted(by_status.items())),
        dict(sorted(by_category.items())),
        dict(sorted(by_severity.items())),
        dict(sorted(by_effort_bucket.items())),
        dict(sorted(by_priority_band.items())),
    )


@router.get("/sites", response_model=SEOSiteListResponse)
def list_seo_sites(
    business_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_site_service.list_sites(business_id=scoped_business_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOSiteListResponse(items=[SEOSiteRead.model_validate(site) for site in items], total=len(items))


@router.post("/sites", response_model=SEOSiteRead, status_code=status.HTTP_201_CREATED)
def create_seo_site(
    business_id: str,
    payload: SEOSiteCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.create_site(business_id=scoped_business_id, payload=payload)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.get("/sites/{site_id}", response_model=SEOSiteRead)
def get_seo_site(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.patch("/sites/{site_id}", response_model=SEOSiteRead)
def patch_seo_site(
    business_id: str,
    site_id: str,
    payload: SEOSiteUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    if payload.is_active is not None and tenant_context.principal_role != PrincipalRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin principals can update site activation.",
        )
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.post("/sites/{site_id}/deactivate", response_model=SEOSiteRead)
def deactivate_seo_site(
    business_id: str,
    site_id: str,
    _: None = Depends(require_admin_rate_limit("seo_site_deactivate")),
    _admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=SEOSiteUpdateRequest(is_active=False),
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.post("/sites/{site_id}/activate", response_model=SEOSiteRead)
def activate_seo_site(
    business_id: str,
    site_id: str,
    _: None = Depends(require_admin_rate_limit("seo_site_activate")),
    _admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=SEOSiteUpdateRequest(is_active=True),
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.post("/sites/{site_id}/audit-runs", response_model=SEOAuditRunRead, status_code=status.HTTP_201_CREATED)
def create_seo_audit_run(
    business_id: str,
    site_id: str,
    payload: SEOAuditRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = seo_audit_service.run_audit(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAuditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAuditRunRead.model_validate(result.run)


@router.get("/sites/{site_id}/audit-runs", response_model=SEOAuditRunListResponse)
def list_seo_audit_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        runs = seo_audit_service.list_runs_for_site(business_id=scoped_business_id, site_id=site_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditRunListResponse(
        items=[SEOAuditRunRead.model_validate(run) for run in runs],
        total=len(runs),
    )


@router.get("/audit-runs/{run_id}", response_model=SEOAuditRunRead)
def get_seo_audit_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        run = seo_audit_service.get_run(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditRunRead.model_validate(run)


@router.get("/audit-runs/{run_id}/findings", response_model=SEOAuditFindingListResponse)
def list_seo_audit_run_findings(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditFindingListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        findings = seo_audit_service.list_findings_for_run(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    by_category, by_severity = seo_audit_service.summarize_findings(findings=findings)
    return SEOAuditFindingListResponse(
        items=[SEOAuditFindingRead.model_validate(item) for item in findings],
        total=len(findings),
        by_category=by_category,
        by_severity=by_severity,
    )


@router.get("/audit-runs/{run_id}/summary", response_model=SEOAuditRunSummaryRead)
def get_seo_audit_run_summary(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = seo_audit_service.get_run_summary(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditRunSummaryRead(
        run_id=summary.run.id,
        business_id=summary.run.business_id,
        site_id=summary.run.site_id,
        status=summary.run.status,
        total_pages=summary.total_pages,
        total_findings=summary.total_findings,
        critical_findings=summary.critical_findings,
        warning_findings=summary.warning_findings,
        info_findings=summary.info_findings,
        crawl_duration=summary.crawl_duration,
        health_score=summary.health_score,
        by_category=summary.by_category,
        by_severity=summary.by_severity,
    )


@router.get("/audit-runs/{run_id}/report", response_model=SEOAuditReportRead)
def get_seo_audit_run_report(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        report = seo_audit_service.get_run_report(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditReportRead(
        site=SEOAuditReportSiteRead(
            id=report.site.id,
            display_name=report.site.display_name,
            base_url=report.site.base_url,
            normalized_domain=report.site.normalized_domain,
        ),
        audit=SEOAuditRunSummaryRead(
            run_id=report.summary.run.id,
            business_id=report.summary.run.business_id,
            site_id=report.summary.run.site_id,
            status=report.summary.run.status,
            total_pages=report.summary.total_pages,
            total_findings=report.summary.total_findings,
            critical_findings=report.summary.critical_findings,
            warning_findings=report.summary.warning_findings,
            info_findings=report.summary.info_findings,
            crawl_duration=report.summary.crawl_duration,
            health_score=report.summary.health_score,
            by_category=report.summary.by_category,
            by_severity=report.summary.by_severity,
        ),
        findings=SEOAuditFindingListResponse(
            items=[SEOAuditFindingRead.model_validate(item) for item in report.findings],
            total=len(report.findings),
            by_category=report.summary.by_category,
            by_severity=report.summary.by_severity,
        ),
    )


@router.post("/audit-runs/{run_id}/summarize", response_model=SEOAuditSummaryRead, status_code=status.HTTP_201_CREATED)
def summarize_seo_audit_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_summary_service: SEOSummaryService = Depends(get_seo_summary_service),
) -> SEOAuditSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = seo_summary_service.summarize_run(
            business_id=scoped_business_id,
            run_id=run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSummaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAuditSummaryRead.model_validate(result.summary)


@router.post(
    "/sites/{site_id}/recommendation-runs",
    response_model=SEORecommendationRunRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/recommendation-runs",
    response_model=SEORecommendationRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_seo_recommendation_run(
    business_id: str,
    site_id: str,
    payload: SEORecommendationRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = recommendation_service.run_recommendations(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEORecommendationRunRead.model_validate(result.run)


@router.get("/sites/{site_id}/recommendation-runs", response_model=SEORecommendationRunListResponse)
@router_v1.get("/sites/{site_id}/recommendation-runs", response_model=SEORecommendationRunListResponse)
def list_seo_recommendation_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = recommendation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationRunListResponse(
        items=[SEORecommendationRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}",
    response_model=SEORecommendationRunRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}",
    response_model=SEORecommendationRunRead,
)
def get_seo_recommendation_run(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = recommendation_service.get_run(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="SEO recommendation run not found",
    )
    return SEORecommendationRunRead.model_validate(run)


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations",
    response_model=SEORecommendationListResponse,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations",
    response_model=SEORecommendationListResponse,
)
def list_seo_recommendations_for_run(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = recommendation_service.get_run(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
        items = recommendation_service.list_recommendations(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="SEO recommendation run not found",
    )
    serialized_items = [SEORecommendationRead.model_validate(item) for item in items]
    by_status, by_category, by_severity, by_effort_bucket, by_priority_band = _summarize_recommendation_items(
        serialized_items
    )
    return SEORecommendationListResponse(
        items=serialized_items,
        total=len(serialized_items),
        by_status=by_status,
        by_category=by_category,
        by_severity=by_severity,
        by_effort_bucket=by_effort_bucket,
        by_priority_band=by_priority_band,
    )


@router.get("/sites/{site_id}/recommendations", response_model=SEORecommendationListResponse)
@router_v1.get("/sites/{site_id}/recommendations", response_model=SEORecommendationListResponse)
def list_seo_recommendations(
    business_id: str,
    site_id: str,
    query: SEORecommendationListQuery = Depends(),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        page_result = recommendation_service.list_site_recommendations(
            business_id=scoped_business_id,
            site_id=site_id,
            query=query,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    serialized_items = [SEORecommendationRead.model_validate(item) for item in page_result.items]
    filtered_summary = SEORecommendationFilteredSummary(
        total=page_result.total,
        open=page_result.by_status.get("open", 0),
        accepted=page_result.by_status.get("accepted", 0),
        dismissed=page_result.by_status.get("dismissed", 0),
        high_priority=page_result.by_priority_band.get("high", 0) + page_result.by_priority_band.get("critical", 0),
    )
    return SEORecommendationListResponse(
        items=serialized_items,
        total=page_result.total,
        filtered_summary=filtered_summary,
        by_status=page_result.by_status,
        by_category=page_result.by_category,
        by_severity=page_result.by_severity,
        by_effort_bucket=page_result.by_effort_bucket,
        by_priority_band=page_result.by_priority_band,
    )


@router.patch("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
@router_v1.patch("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
def patch_seo_recommendation(
    business_id: str,
    site_id: str,
    recommendation_id: str,
    payload: SEORecommendationWorkflowUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        recommendation = recommendation_service.update_recommendation_workflow(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_id=recommendation_id,
            payload=payload,
            updated_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEORecommendationRead.model_validate(recommendation)


@router.get("/sites/{site_id}/recommendations/backlog", response_model=SEORecommendationBacklogRead)
@router_v1.get("/sites/{site_id}/recommendations/backlog", response_model=SEORecommendationBacklogRead)
def get_seo_recommendation_backlog(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationBacklogRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        backlog = recommendation_service.get_backlog(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationBacklogRead(
        business_id=backlog.business_id,
        site_id=backlog.site_id,
        total_actionable=len(backlog.items),
        items=[SEORecommendationRead.model_validate(item) for item in backlog.items],
    )


@router.get(
    "/sites/{site_id}/recommendations/prioritized-report", response_model=SEORecommendationPrioritizedReportRead
)
@router_v1.get(
    "/sites/{site_id}/recommendations/prioritized-report",
    response_model=SEORecommendationPrioritizedReportRead,
)
def get_seo_recommendation_prioritized_report(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationPrioritizedReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        report = recommendation_service.get_prioritized_report(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    backlog_items = [SEORecommendationRead.model_validate(item) for item in report.backlog_items]
    backlog_by_status, backlog_by_category, backlog_by_severity, backlog_by_effort, backlog_by_priority = (
        _summarize_recommendation_items(backlog_items)
    )
    return SEORecommendationPrioritizedReportRead(
        business_id=report.business_id,
        site_id=report.site_id,
        generated_at=report.generated_at,
        total_recommendations=report.total_recommendations,
        backlog_total=len(backlog_items),
        by_status=report.by_status,
        by_category=report.by_category,
        by_severity=report.by_severity,
        by_effort_bucket=report.by_effort_bucket,
        by_priority_band=report.by_priority_band,
        backlog=SEORecommendationListResponse(
            items=backlog_items,
            total=len(backlog_items),
            by_status=backlog_by_status,
            by_category=backlog_by_category,
            by_severity=backlog_by_severity,
            by_effort_bucket=backlog_by_effort,
            by_priority_band=backlog_by_priority,
        ),
    )


@router.get("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
@router_v1.get("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
def get_seo_recommendation(
    business_id: str,
    site_id: str,
    recommendation_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        recommendation = recommendation_service.get_recommendation(
            business_id=scoped_business_id,
            recommendation_id=recommendation_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=recommendation.site_id,
        detail="SEO recommendation not found",
    )
    return SEORecommendationRead.model_validate(recommendation)


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report",
    response_model=SEORecommendationRunReportRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report",
    response_model=SEORecommendationRunReportRead,
)
def get_seo_recommendation_run_report(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        report = recommendation_service.get_report(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=report.run.site_id,
        detail="SEO recommendation run not found",
    )
    serialized_items = [SEORecommendationRead.model_validate(item) for item in report.recommendations]
    by_status, by_category, by_severity, by_effort_bucket, by_priority_band = _summarize_recommendation_items(
        serialized_items
    )
    return SEORecommendationRunReportRead(
        recommendation_run=SEORecommendationRunRead.model_validate(report.run),
        rollups={
            "by_category": report.by_category,
            "by_severity": report.by_severity,
            "by_effort_bucket": report.by_effort_bucket,
        },
        recommendations=SEORecommendationListResponse(
            items=serialized_items,
            total=len(serialized_items),
            by_status=by_status,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort_bucket,
            by_priority_band=by_priority_band,
        ),
    )


@router.post(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_seo_recommendation_narrative(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = recommendation_narrative_service.summarize_run(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationNarrativeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEORecommendationNarrativeRead.model_validate(result.narrative)


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeListResponse,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeListResponse,
)
def list_seo_recommendation_narratives(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = recommendation_narrative_service.list_narratives(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationNarrativeListResponse(
        items=[SEORecommendationNarrativeRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest",
    response_model=SEORecommendationNarrativeRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest",
    response_model=SEORecommendationNarrativeRead,
)
def get_latest_seo_recommendation_narrative(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        narrative = recommendation_narrative_service.get_latest_narrative(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationNarrativeRead.model_validate(narrative)


@router.get(
    "/sites/{site_id}/recommendation-narratives/{narrative_id}",
    response_model=SEORecommendationNarrativeRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-narratives/{narrative_id}",
    response_model=SEORecommendationNarrativeRead,
)
def get_seo_recommendation_narrative(
    business_id: str,
    site_id: str,
    narrative_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        narrative = recommendation_narrative_service.get_narrative(
            business_id=scoped_business_id,
            site_id=site_id,
            narrative_id=narrative_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationNarrativeRead.model_validate(narrative)


@router.post(
    "/sites/{site_id}/automation-config",
    response_model=SEOAutomationConfigRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/automation-config",
    response_model=SEOAutomationConfigRead,
    status_code=status.HTTP_201_CREATED,
)
def create_or_replace_seo_automation_config(
    business_id: str,
    site_id: str,
    payload: SEOAutomationConfigUpsertRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.create_or_replace_config(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.get("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
@router_v1.get("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
def get_seo_automation_config(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.get_config(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.patch("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
@router_v1.patch("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
def patch_seo_automation_config(
    business_id: str,
    site_id: str,
    payload: SEOAutomationConfigPatchRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.update_config(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.post("/sites/{site_id}/automation-config/enable", response_model=SEOAutomationConfigRead)
@router_v1.post("/sites/{site_id}/automation-config/enable", response_model=SEOAutomationConfigRead)
def enable_seo_automation_config(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.set_config_enabled(
            business_id=scoped_business_id,
            site_id=site_id,
            is_enabled=True,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.post("/sites/{site_id}/automation-config/disable", response_model=SEOAutomationConfigRead)
@router_v1.post("/sites/{site_id}/automation-config/disable", response_model=SEOAutomationConfigRead)
def disable_seo_automation_config(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.set_config_enabled(
            business_id=scoped_business_id,
            site_id=site_id,
            is_enabled=False,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.post(
    "/sites/{site_id}/automation-runs",
    response_model=SEOAutomationRunRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/automation-runs",
    response_model=SEOAutomationRunRead,
    status_code=status.HTTP_201_CREATED,
)
def trigger_seo_automation_run(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = automation_service.trigger_manual_run(
            business_id=scoped_business_id,
            site_id=site_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationRunRead.model_validate(run)


@router.get("/sites/{site_id}/automation-runs", response_model=SEOAutomationRunListResponse)
@router_v1.get("/sites/{site_id}/automation-runs", response_model=SEOAutomationRunListResponse)
def list_seo_automation_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = automation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationRunListResponse(
        items=[SEOAutomationRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/sites/{site_id}/automation-runs/{automation_run_id}", response_model=SEOAutomationRunRead)
@router_v1.get("/sites/{site_id}/automation-runs/{automation_run_id}", response_model=SEOAutomationRunRead)
def get_seo_automation_run(
    business_id: str,
    site_id: str,
    automation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = automation_service.get_run(
            business_id=scoped_business_id,
            site_id=site_id,
            automation_run_id=automation_run_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationRunRead.model_validate(run)


@router.get("/sites/{site_id}/automation-status", response_model=SEOAutomationStatusRead)
@router_v1.get("/sites/{site_id}/automation-status", response_model=SEOAutomationStatusRead)
def get_seo_automation_status(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config, latest_run = automation_service.get_status(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationStatusRead(
        business_id=scoped_business_id,
        site_id=site_id,
        config=SEOAutomationConfigRead.model_validate(config),
        latest_run=SEOAutomationRunRead.model_validate(latest_run) if latest_run is not None else None,
    )


@router.get("/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetListResponse)
@router_v1.get("/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetListResponse)
def list_competitor_sets(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_sets(business_id=scoped_business_id, site_id=site_id)
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSetListResponse(
        items=[SEOCompetitorSetRead.model_validate(item) for item in items],
        total=len(items),
    )


def _to_competitor_profile_generation_run_detail_response(
    *,
    run,
    drafts,
) -> SEOCompetitorProfileGenerationRunDetailRead:
    serialized_drafts = [SEOCompetitorProfileDraftRead.model_validate(item) for item in drafts]
    return SEOCompetitorProfileGenerationRunDetailRead(
        run=SEOCompetitorProfileGenerationRunRead.model_validate(run),
        drafts=serialized_drafts,
        total_drafts=len(serialized_drafts),
    )


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_profile_generation_run(
    business_id: str,
    site_id: str,
    payload: SEOCompetitorProfileGenerationRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
    generation_run_executor: SEOCompetitorProfileGenerationRunExecutor = Depends(
        get_seo_competitor_profile_generation_run_executor
    ),
) -> SEOCompetitorProfileGenerationRunDetailRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = generation_service.create_run(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    background_tasks.add_task(
        generation_run_executor,
        scoped_business_id,
        site_id,
        result.run.id,
    )
    return _to_competitor_profile_generation_run_detail_response(
        run=result.run,
        drafts=result.drafts,
    )


@router.get(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunListResponse,
)
@router_v1.get(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunListResponse,
)
def list_competitor_profile_generation_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
) -> SEOCompetitorProfileGenerationRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = generation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorProfileGenerationRunListResponse(
        items=[SEOCompetitorProfileGenerationRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/sites/{site_id}/competitor-profile-generation-runs/summary",
    response_model=SEOCompetitorProfileGenerationObservabilitySummaryRead,
)
@router_v1.get(
    "/sites/{site_id}/competitor-profile-generation-runs/summary",
    response_model=SEOCompetitorProfileGenerationObservabilitySummaryRead,
)
def get_competitor_profile_generation_runs_summary(
    business_id: str,
    site_id: str,
    lookback_days: int | None = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
) -> SEOCompetitorProfileGenerationObservabilitySummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        summary = generation_service.get_observability_summary(
            business_id=scoped_business_id,
            site_id=site_id,
            lookback_days=lookback_days,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return SEOCompetitorProfileGenerationObservabilitySummaryRead(
        business_id=scoped_business_id,
        site_id=site_id,
        lookback_days=summary.lookback_days,
        window_start=summary.window_start,
        window_end=summary.window_end,
        queued_count=summary.queued_count,
        running_count=summary.running_count,
        completed_count=summary.completed_count,
        failed_count=summary.failed_count,
        retry_child_runs=summary.retry_child_runs,
        retried_parent_runs=summary.retried_parent_runs,
        failed_runs_retried=summary.failed_runs_retried,
        failure_category_counts=summary.failure_category_counts,
        latest_run_created_at=summary.latest_run_created_at,
        latest_run_completed_at=summary.latest_run_completed_at,
        latest_completed_run_completed_at=summary.latest_completed_run_completed_at,
        latest_failed_run_completed_at=summary.latest_failed_run_completed_at,
    )


@router.get(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
)
@router_v1.get(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
)
def get_competitor_profile_generation_run_detail(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
) -> SEOCompetitorProfileGenerationRunDetailRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        detail = generation_service.get_run_detail(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_competitor_profile_generation_run_detail_response(
        run=detail.run,
        drafts=detail.drafts,
    )


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/retry",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/retry",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def retry_competitor_profile_generation_run(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    background_tasks: BackgroundTasks,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
    generation_run_executor: SEOCompetitorProfileGenerationRunExecutor = Depends(
        get_seo_competitor_profile_generation_run_executor
    ),
) -> SEOCompetitorProfileGenerationRunDetailRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = generation_service.retry_failed_run(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    background_tasks.add_task(
        generation_run_executor,
        scoped_business_id,
        site_id,
        result.run.id,
    )
    return _to_competitor_profile_generation_run_detail_response(
        run=result.run,
        drafts=result.drafts,
    )


@router.patch(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}",
    response_model=SEOCompetitorProfileDraftRead,
)
@router_v1.patch(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}",
    response_model=SEOCompetitorProfileDraftRead,
)
def edit_competitor_profile_generation_draft(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    draft_id: str,
    payload: SEOCompetitorProfileDraftEditRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
) -> SEOCompetitorProfileDraftRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        draft = generation_service.edit_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
            payload=payload,
            reviewed_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorProfileDraftRead.model_validate(draft)


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/reject",
    response_model=SEOCompetitorProfileDraftRead,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/reject",
    response_model=SEOCompetitorProfileDraftRead,
)
def reject_competitor_profile_generation_draft(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    draft_id: str,
    payload: SEOCompetitorProfileDraftRejectRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
) -> SEOCompetitorProfileDraftRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        draft = generation_service.reject_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
            payload=payload,
            reviewed_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorProfileDraftRead.model_validate(draft)


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/accept",
    response_model=SEOCompetitorProfileDraftRead,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/accept",
    response_model=SEOCompetitorProfileDraftRead,
)
def accept_competitor_profile_generation_draft(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    draft_id: str,
    payload: SEOCompetitorProfileDraftAcceptRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(
        get_seo_competitor_profile_generation_service
    ),
) -> SEOCompetitorProfileDraftRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = generation_service.accept_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
            payload=payload,
            reviewed_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorProfileDraftRead.model_validate(result.draft)


@router.post(
    "/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetRead, status_code=status.HTTP_201_CREATED
)
@router_v1.post(
    "/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetRead, status_code=status.HTTP_201_CREATED
)
def create_competitor_set(
    business_id: str,
    site_id: str,
    payload: SEOCompetitorSetCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_set = seo_competitor_service.create_set(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router.get("/competitor-sets/{set_id}", response_model=SEOCompetitorSetRead)
def get_competitor_set(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router.patch("/competitor-sets/{set_id}", response_model=SEOCompetitorSetRead)
def patch_competitor_set(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorSetUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_set = seo_competitor_service.update_set(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router.get("/competitor-sets/{set_id}/domains", response_model=SEOCompetitorDomainListResponse)
def list_competitor_domains(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_domains(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorDomainListResponse(
        items=[SEOCompetitorDomainRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/competitor-sets/{set_id}/domains", response_model=SEOCompetitorDomainRead, status_code=status.HTTP_201_CREATED
)
def add_competitor_domain(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorDomainCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_domain = seo_competitor_service.add_domain(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorDomainRead.model_validate(competitor_domain)


@router.delete(
    "/competitor-sets/{set_id}/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def remove_competitor_domain(
    business_id: str,
    set_id: str,
    domain_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> Response:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_competitor_service.remove_domain(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            domain_id=domain_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/competitor-sets/{set_id}/snapshot-runs",
    response_model=SEOCompetitorSnapshotRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_snapshot_run(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorSnapshotRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        snapshot_run = seo_competitor_service.create_snapshot_run(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router.get("/competitor-sets/{set_id}/snapshot-runs", response_model=SEOCompetitorSnapshotRunListResponse)
def list_competitor_snapshot_runs(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_snapshot_runs(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSnapshotRunListResponse(
        items=[SEOCompetitorSnapshotRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/snapshot-runs/{run_id}", response_model=SEOCompetitorSnapshotRunRead)
def get_competitor_snapshot_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        snapshot_run = seo_competitor_service.get_snapshot_run(
            business_id=scoped_business_id,
            snapshot_run_id=run_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router.get("/snapshot-runs/{run_id}/pages", response_model=SEOCompetitorSnapshotPageListResponse)
def list_competitor_snapshot_pages(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotPageListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_snapshot_pages(
            business_id=scoped_business_id,
            snapshot_run_id=run_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSnapshotPageListResponse(
        items=[SEOCompetitorSnapshotPageRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/competitor-sets/{set_id}/comparison-runs",
    response_model=SEOCompetitorComparisonRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_comparison_run(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorComparisonRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = comparison_service.run_comparison(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorComparisonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunRead.model_validate(result.run)


@router.get("/competitor-sets/{set_id}/comparison-runs", response_model=SEOCompetitorComparisonRunListResponse)
def list_competitor_comparison_runs(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = comparison_service.list_runs(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunListResponse(
        items=[SEOCompetitorComparisonRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/comparison-runs/{run_id}", response_model=SEOCompetitorComparisonRunRead)
def get_competitor_comparison_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunRead.model_validate(run)


@router.get("/comparison-runs/{run_id}/findings", response_model=SEOCompetitorComparisonFindingListResponse)
def list_competitor_comparison_findings(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonFindingListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        findings = comparison_service.list_findings(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    by_category, by_severity = comparison_service.summarize_findings(findings=findings)
    return SEOCompetitorComparisonFindingListResponse(
        items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in findings],
        total=len(findings),
        by_category=by_category,
        by_severity=by_severity,
    )


@router.get("/comparison-runs/{run_id}/report", response_model=SEOCompetitorComparisonReportRead)
def get_competitor_comparison_report(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        report = comparison_service.get_report(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    metric_rollups = []
    for metric_key in sorted(report.metric_rollups):
        metric = report.metric_rollups[metric_key]
        metric_rollups.append(
            SEOCompetitorComparisonMetricRollupRead(
                key=metric_key,
                title=str(metric.get("title", metric_key)),
                category=str(metric.get("category", "TECHNICAL")),
                unit=str(metric.get("unit", "count")),
                higher_is_better=bool(metric.get("higher_is_better", False)),
                client_value=int(metric.get("client_value", 0)),
                competitor_value=int(metric.get("competitor_value", 0)),
                delta=int(metric.get("delta", 0)),
                severity=str(metric.get("severity", "INFO")),
                gap_direction=str(metric.get("gap_direction", "unknown")),
            )
        )
    return SEOCompetitorComparisonReportRead(
        run=SEOCompetitorComparisonRunRead.model_validate(report.run),
        rollups=SEOCompetitorComparisonRunRollupsRead(
            client_pages_analyzed=report.run.client_pages_analyzed,
            competitor_pages_analyzed=report.run.competitor_pages_analyzed,
            findings_by_type=report.findings_by_type,
            findings_by_category=report.findings_by_category,
            findings_by_severity=report.findings_by_severity,
            metric_rollups=metric_rollups,
        ),
        findings=SEOCompetitorComparisonFindingListResponse(
            items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in report.findings],
            total=len(report.findings),
            by_category=report.findings_by_category,
            by_severity=report.findings_by_severity,
        ),
    )


@router.post(
    "/comparison-runs/{run_id}/summarize",
    response_model=SEOCompetitorComparisonSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def summarize_competitor_comparison_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = summary_service.summarize_run(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorSummaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryRead.model_validate(result.summary)


@router.get(
    "/comparison-runs/{run_id}/summaries",
    response_model=SEOCompetitorComparisonSummaryListResponse,
)
def list_competitor_comparison_summaries(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = summary_service.list_summaries(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryListResponse(
        items=[SEOCompetitorComparisonSummaryRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/comparison-runs/{run_id}/summaries/latest",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_latest_competitor_comparison_summary(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = summary_service.get_latest_summary(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)


@router.get(
    "/comparison-summaries/{summary_id}",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_competitor_comparison_summary(
    business_id: str,
    summary_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = summary_service.get_summary(
            business_id=scoped_business_id,
            summary_id=summary_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)


@router_v1.get("/sites/{site_id}/competitor-sets/{competitor_set_id}", response_model=SEOCompetitorSetRead)
def get_competitor_set_for_site_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router_v1.get(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/domains",
    response_model=SEOCompetitorDomainListResponse,
)
def list_competitor_domains_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        items = seo_competitor_service.list_domains(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorDomainListResponse(
        items=[SEOCompetitorDomainRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.post(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/domains",
    response_model=SEOCompetitorDomainRead,
    status_code=status.HTTP_201_CREATED,
)
def add_competitor_domain_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    payload: SEOCompetitorDomainCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        competitor_domain = seo_competitor_service.add_domain(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
            payload=payload,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorDomainRead.model_validate(competitor_domain)


@router_v1.post(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/snapshot-runs",
    response_model=SEOCompetitorSnapshotRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_snapshot_run_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    payload: SEOCompetitorSnapshotRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        snapshot_run = seo_competitor_service.create_snapshot_run(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router_v1.get(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/snapshot-runs",
    response_model=SEOCompetitorSnapshotRunListResponse,
)
def list_competitor_snapshot_runs_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        items = seo_competitor_service.list_snapshot_runs(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorSnapshotRunListResponse(
        items=[SEOCompetitorSnapshotRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.get(
    "/sites/{site_id}/competitor-snapshot-runs/{snapshot_run_id}",
    response_model=SEOCompetitorSnapshotRunRead,
)
def get_competitor_snapshot_run_v1(
    business_id: str,
    site_id: str,
    snapshot_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        snapshot_run = seo_competitor_service.get_snapshot_run(
            business_id=scoped_business_id,
            snapshot_run_id=snapshot_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=snapshot_run.site_id,
        detail="Competitor snapshot run not found",
    )
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router_v1.get(
    "/sites/{site_id}/competitor-snapshot-runs/{snapshot_run_id}/pages",
    response_model=SEOCompetitorSnapshotPageListResponse,
)
def list_competitor_snapshot_pages_v1(
    business_id: str,
    site_id: str,
    snapshot_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotPageListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        snapshot_run = seo_competitor_service.get_snapshot_run(
            business_id=scoped_business_id,
            snapshot_run_id=snapshot_run_id,
        )
        items = seo_competitor_service.list_snapshot_pages(
            business_id=scoped_business_id,
            snapshot_run_id=snapshot_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=snapshot_run.site_id,
        detail="Competitor snapshot run not found",
    )
    return SEOCompetitorSnapshotPageListResponse(
        items=[SEOCompetitorSnapshotPageRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.post(
    "/sites/{site_id}/competitor-comparison-runs",
    response_model=SEOCompetitorComparisonRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_comparison_run_v1(
    business_id: str,
    site_id: str,
    payload: SEOCompetitorComparisonRunSiteCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=payload.competitor_set_id,
        )
        _assert_site_match(
            expected_site_id=site_id,
            actual_site_id=competitor_set.site_id,
            detail="Competitor set not found",
        )
        result = comparison_service.run_comparison(
            business_id=scoped_business_id,
            competitor_set_id=payload.competitor_set_id,
            payload=SEOCompetitorComparisonRunCreateRequest(
                snapshot_run_id=payload.snapshot_run_id,
                baseline_audit_run_id=payload.baseline_audit_run_id,
            ),
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorComparisonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=result.run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonRunRead.model_validate(result.run)


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs",
    response_model=SEOCompetitorComparisonRunListResponse,
)
def list_competitor_comparison_runs_v1(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = comparison_service.list_runs_for_site(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunListResponse(
        items=[SEOCompetitorComparisonRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}",
    response_model=SEOCompetitorComparisonRunRead,
)
def get_competitor_comparison_run_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonRunRead.model_validate(run)


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/findings",
    response_model=SEOCompetitorComparisonFindingListResponse,
)
def list_competitor_comparison_findings_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonFindingListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        findings = comparison_service.list_findings(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    by_category, by_severity = comparison_service.summarize_findings(findings=findings)
    return SEOCompetitorComparisonFindingListResponse(
        items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in findings],
        total=len(findings),
        by_category=by_category,
        by_severity=by_severity,
    )


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/report",
    response_model=SEOCompetitorComparisonReportRead,
)
def get_competitor_comparison_report_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        report = comparison_service.get_report(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=report.run.site_id,
        detail="Competitor comparison run not found",
    )
    metric_rollups = []
    for metric_key in sorted(report.metric_rollups):
        metric = report.metric_rollups[metric_key]
        metric_rollups.append(
            SEOCompetitorComparisonMetricRollupRead(
                key=metric_key,
                title=str(metric.get("title", metric_key)),
                category=str(metric.get("category", "TECHNICAL")),
                unit=str(metric.get("unit", "count")),
                higher_is_better=bool(metric.get("higher_is_better", False)),
                client_value=int(metric.get("client_value", 0)),
                competitor_value=int(metric.get("competitor_value", 0)),
                delta=int(metric.get("delta", 0)),
                severity=str(metric.get("severity", "INFO")),
                gap_direction=str(metric.get("gap_direction", "unknown")),
            )
        )
    return SEOCompetitorComparisonReportRead(
        run=SEOCompetitorComparisonRunRead.model_validate(report.run),
        rollups=SEOCompetitorComparisonRunRollupsRead(
            client_pages_analyzed=report.run.client_pages_analyzed,
            competitor_pages_analyzed=report.run.competitor_pages_analyzed,
            findings_by_type=report.findings_by_type,
            findings_by_category=report.findings_by_category,
            findings_by_severity=report.findings_by_severity,
            metric_rollups=metric_rollups,
        ),
        findings=SEOCompetitorComparisonFindingListResponse(
            items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in report.findings],
            total=len(report.findings),
            by_category=report.findings_by_category,
            by_severity=report.findings_by_severity,
        ),
    )


@router_v1.post(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries",
    response_model=SEOCompetitorComparisonSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def summarize_competitor_comparison_run_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        result = summary_service.summarize_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorComparisonNotFoundError,
        SEOCompetitorSummaryNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorSummaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonSummaryRead.model_validate(result.summary)


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries",
    response_model=SEOCompetitorComparisonSummaryListResponse,
)
def list_competitor_comparison_summaries_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        items = summary_service.list_summaries(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorComparisonNotFoundError,
        SEOCompetitorSummaryNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonSummaryListResponse(
        items=[SEOCompetitorComparisonSummaryRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries/latest",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_latest_competitor_comparison_summary_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        summary = summary_service.get_latest_summary(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorComparisonNotFoundError,
        SEOCompetitorSummaryNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)


@router_v1.get(
    "/sites/{site_id}/competitor-summaries/{summary_id}",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_competitor_comparison_summary_v1(
    business_id: str,
    site_id: str,
    summary_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        summary = summary_service.get_summary(
            business_id=scoped_business_id,
            summary_id=summary_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorSummaryNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=summary.site_id,
        detail="Competitor summary not found",
    )
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)

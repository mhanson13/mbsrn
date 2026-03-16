from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import (
    TenantContext,
    get_seo_audit_service,
    get_seo_competitor_comparison_service,
    get_seo_competitor_service,
    get_seo_site_service,
    get_seo_summary_service,
    get_tenant_context,
    resolve_tenant_business_id,
)
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
    SEOCompetitorComparisonRunRollupsRead,
    SEOCompetitorComparisonRunCreateRequest,
    SEOCompetitorComparisonRunListResponse,
    SEOCompetitorComparisonRunRead,
    SEOCompetitorDomainCreateRequest,
    SEOCompetitorDomainListResponse,
    SEOCompetitorDomainRead,
    SEOCompetitorSetCreateRequest,
    SEOCompetitorSetListResponse,
    SEOCompetitorSetRead,
    SEOCompetitorSetUpdateRequest,
    SEOCompetitorSnapshotRunCreateRequest,
    SEOCompetitorSnapshotRunListResponse,
    SEOCompetitorSnapshotRunRead,
)
from app.services.seo_audit import SEOAuditNotFoundError, SEOAuditService, SEOAuditValidationError
from app.services.seo_competitor_comparison import (
    SEOCompetitorComparisonNotFoundError,
    SEOCompetitorComparisonService,
    SEOCompetitorComparisonValidationError,
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


@router.get("/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetListResponse)
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


@router.post("/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetRead, status_code=status.HTTP_201_CREATED)
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


@router.post("/competitor-sets/{set_id}/domains", response_model=SEOCompetitorDomainRead, status_code=status.HTTP_201_CREATED)
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

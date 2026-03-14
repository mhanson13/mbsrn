from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    TenantContext,
    get_seo_audit_service,
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
from app.services.seo_audit import SEOAuditNotFoundError, SEOAuditService, SEOAuditValidationError
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

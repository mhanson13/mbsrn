from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    TenantContext,
    get_tenant_context,
    get_tls_certificate_service,
    resolve_tenant_business_id,
)
from app.models.tls_certificate import SiteTLSCertificateBinding, TLSCertificateAsset
from app.schemas.tls_certificate import (
    SiteTLSCertificateBindingRead,
    SiteTLSCertificateStatusRead,
    TLSCertificateAdoptRequest,
    TLSCertificateCapabilityCheckRead,
    TLSCertificateCapabilityStatusRead,
    TLSCertificateAssetListRead,
    TLSCertificateAssetRead,
    TLSCertificateGenerateRequest,
    TLSCertificateImportRequest,
)
from app.services.tls_certificates import (
    SiteTLSCertificateStatus,
    TLSCertificateConfigurationError,
    TLSCertificateNotFoundError,
    TLSCertificateService,
    TLSCertificateValidationError,
)


router = APIRouter(prefix="/api/businesses/{business_id}/tls", tags=["tls-certificates"])


def _asset_read(asset: TLSCertificateAsset) -> TLSCertificateAssetRead:
    return TLSCertificateAssetRead(
        id=asset.id,
        hostname=asset.hostname,
        display_name=asset.display_name,
        source=asset.source,
        custody=asset.custody,
        certificate_kind=asset.certificate_kind,
        key_algorithm=asset.key_algorithm,
        fingerprint_sha256=asset.fingerprint_sha256,
        serial_number=asset.serial_number,
        subject=asset.subject,
        issuer=asset.issuer,
        san_dns_names=list(asset.san_dns_names_json or []),
        not_valid_before=asset.not_valid_before,
        not_valid_after=asset.not_valid_after,
        gcp_project_id=asset.gcp_project_id,
        gcp_resource_name=asset.gcp_resource_name,
        gcp_resource_scope=asset.gcp_resource_scope,
        status=asset.status,
        failure_reason_code=asset.failure_reason_code,
        failure_message=asset.failure_message,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _binding_read(binding: SiteTLSCertificateBinding) -> SiteTLSCertificateBindingRead:
    return SiteTLSCertificateBindingRead(
        id=binding.id,
        certificate_asset_id=binding.certificate_asset_id,
        is_active=binding.is_active,
        manifest_state=binding.manifest_state,
        serving_state=binding.serving_state,
        observed_fingerprint_sha256=binding.observed_fingerprint_sha256,
        last_verified_at=binding.last_verified_at,
    )


def _status_read(value: SiteTLSCertificateStatus) -> SiteTLSCertificateStatusRead:
    return SiteTLSCertificateStatusRead(
        hostname=value.hostname,
        asset=(_asset_read(value.asset) if value.asset is not None else None),
        binding=(_binding_read(value.binding) if value.binding is not None else None),
        vaulted=value.vaulted,
        published=value.published,
        selected_for_ingress=value.selected_for_ingress,
        manifest_state=value.manifest_state,
        serving_state=value.serving_state,
    )


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, TLSCertificateNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, TLSCertificateConfigurationError):
        next_action = exc.next_action
        if not next_action:
            next_action = (
                "Grant the listed permissions to the API workload identity, then retry."
                if exc.missing_permissions
                else "Collect administrator diagnostics and retry the certificate operation."
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "reason_code": exc.reason_code,
                "message": str(exc),
                "missing_permissions": list(exc.missing_permissions),
                "provider_service": exc.provider_service,
                "provider_operation": exc.provider_operation,
                "provider_http_status": exc.provider_http_status,
                "provider_status": exc.provider_status,
                "retryable": exc.retryable,
                "next_action": next_action,
            },
        ) from exc
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/certificates", response_model=TLSCertificateAssetListRead)
def list_tls_certificates(
    business_id: str,
    site_id: str | None = Query(default=None),
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> TLSCertificateAssetListRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        assets = certificate_service.list_assets(business_id=scoped_business_id, site_id=site_id)
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return TLSCertificateAssetListRead(items=[_asset_read(asset) for asset in assets])


@router.get("/capabilities", response_model=TLSCertificateCapabilityStatusRead)
def get_tls_certificate_capabilities(
    business_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> TLSCertificateCapabilityStatusRead:
    resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    capability_status = certificate_service.get_capabilities()
    checks = [
        TLSCertificateCapabilityCheckRead(
            component=check.component,
            ready=check.ready,
            verification_state=check.verification_state,
            required_permissions=list(check.required_permissions),
            missing_permissions=list(check.missing_permissions),
        )
        for check in capability_status.checks
    ]
    return TLSCertificateCapabilityStatusRead(
        project_id=capability_status.project_id,
        ready=capability_status.ready,
        reason_code=capability_status.reason_code,
        message=capability_status.message,
        next_action=(
            None
            if capability_status.ready
            else "Resolve the displayed configuration or credential problem, then retry the capability check."
        ),
        checks=checks,
    )


@router.get("/sites/{site_id}/status", response_model=SiteTLSCertificateStatusRead)
def get_site_tls_certificate_status(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.get_site_status(business_id=scoped_business_id, site_id=site_id)
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)


@router.post("/sites/{site_id}/certificates/generate", response_model=SiteTLSCertificateStatusRead)
def generate_site_tls_certificate(
    business_id: str,
    site_id: str,
    payload: TLSCertificateGenerateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.generate_for_site(
            business_id=scoped_business_id,
            site_id=site_id,
            principal_id=tenant_context.principal_id,
            display_name=payload.display_name,
            validity_days=payload.validity_days,
            key_algorithm=payload.key_algorithm,
        )
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)


@router.post("/sites/{site_id}/certificates/ensure", response_model=SiteTLSCertificateStatusRead)
def ensure_site_tls_certificate(
    business_id: str,
    site_id: str,
    payload: TLSCertificateGenerateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.ensure_for_site(
            business_id=scoped_business_id,
            site_id=site_id,
            principal_id=tenant_context.principal_id,
            display_name=payload.display_name,
            validity_days=payload.validity_days,
            key_algorithm=payload.key_algorithm,
        )
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)


@router.post("/sites/{site_id}/certificates/import", response_model=SiteTLSCertificateStatusRead)
def import_site_tls_certificate(
    business_id: str,
    site_id: str,
    payload: TLSCertificateImportRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.import_for_site(
            business_id=scoped_business_id,
            site_id=site_id,
            certificate_pem=payload.certificate_pem,
            private_key_pem=payload.private_key_pem.get_secret_value(),
            principal_id=tenant_context.principal_id,
            display_name=payload.display_name,
        )
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)


@router.post("/sites/{site_id}/certificates/adopt", response_model=SiteTLSCertificateStatusRead)
def adopt_site_tls_certificate(
    business_id: str,
    site_id: str,
    payload: TLSCertificateAdoptRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.adopt_for_site(
            business_id=scoped_business_id,
            site_id=site_id,
            resource_name=payload.gcp_resource_name,
            principal_id=tenant_context.principal_id,
            display_name=payload.display_name,
        )
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)


@router.post("/sites/{site_id}/certificates/{asset_id}/bind", response_model=SiteTLSCertificateStatusRead)
def bind_site_tls_certificate(
    business_id: str,
    site_id: str,
    asset_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.bind_existing_asset(
            business_id=scoped_business_id,
            site_id=site_id,
            asset_id=asset_id,
            principal_id=tenant_context.principal_id,
        )
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)


@router.post("/sites/{site_id}/verify", response_model=SiteTLSCertificateStatusRead)
def verify_site_tls_certificate(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    certificate_service: TLSCertificateService = Depends(get_tls_certificate_service),
) -> SiteTLSCertificateStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        certificate_status = certificate_service.verify_site_endpoint(
            business_id=scoped_business_id,
            site_id=site_id,
            principal_id=tenant_context.principal_id,
        )
    except (TLSCertificateNotFoundError, TLSCertificateValidationError, TLSCertificateConfigurationError) as exc:
        _raise_http_error(exc)
    return _status_read(certificate_status)

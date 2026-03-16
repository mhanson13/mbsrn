from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_api_credential_service,
    get_principal_identity_service,
    get_auth_audit_service,
    get_business_settings_service,
    get_principal_service,
    require_admin_rate_limit,
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
from app.schemas.auth_audit import AuthAuditEventListResponse, AuthAuditEventRead
from app.schemas.business import BusinessSettingsRead, BusinessSettingsUpdateRequest
from app.schemas.principal import (
    PrincipalCreateRequest,
    PrincipalListResponse,
    PrincipalRead,
    PrincipalUpdateRequest,
)
from app.schemas.principal_identity import (
    PrincipalIdentityCreateRequest,
    PrincipalIdentityListResponse,
    PrincipalIdentityRead,
)
from app.services.api_credentials import (
    APICredentialNotFoundError,
    APICredentialService,
    APICredentialValidationError,
)
from app.services.auth_audit import AuthAuditNotFoundError, AuthAuditService
from app.services.business_settings import (
    BusinessSettingsNotFoundError,
    BusinessSettingsService,
    BusinessSettingsValidationError,
)
from app.services.principals import PrincipalNotFoundError, PrincipalService, PrincipalValidationError
from app.services.principal_identities import (
    PrincipalIdentityNotFoundError,
    PrincipalIdentityService,
    PrincipalIdentityValidationError,
    PrincipalIdentityCreateInput,
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
    _: None = Depends(require_admin_rate_limit("credential_create")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
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
            actor_principal_id=admin_principal.id,
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
    _: None = Depends(require_admin_rate_limit("credential_disable")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
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
            actor_principal_id=admin_principal.id,
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
    _: None = Depends(require_admin_rate_limit("credential_revoke")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
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
            actor_principal_id=admin_principal.id,
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
    _: None = Depends(require_admin_rate_limit("credential_rotate")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
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
            actor_principal_id=admin_principal.id,
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


@router.get("/{business_id}/principals", response_model=PrincipalListResponse)
def list_principals(
    business_id: str,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_service: PrincipalService = Depends(get_principal_service),
) -> PrincipalListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        principals = principal_service.list_for_business(business_id=scoped_business_id)
    except PrincipalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PrincipalListResponse(
        items=[PrincipalRead.model_validate(principal) for principal in principals],
        total=len(principals),
    )


@router.post(
    "/{business_id}/principals",
    response_model=PrincipalRead,
    status_code=status.HTTP_201_CREATED,
)
def create_principal(
    business_id: str,
    payload: PrincipalCreateRequest,
    _: None = Depends(require_admin_rate_limit("principal_create")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_service: PrincipalService = Depends(get_principal_service),
) -> PrincipalRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        principal = principal_service.create_principal(
            business_id=scoped_business_id,
            principal_id=payload.principal_id,
            display_name=payload.display_name,
            role=payload.role,
            actor_principal_id=admin_principal.id,
        )
    except PrincipalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PrincipalValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return PrincipalRead.model_validate(principal)


@router.patch(
    "/{business_id}/principals/{principal_id}",
    response_model=PrincipalRead,
)
def patch_principal(
    business_id: str,
    principal_id: str,
    payload: PrincipalUpdateRequest,
    _: None = Depends(require_admin_rate_limit("principal_update")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_service: PrincipalService = Depends(get_principal_service),
) -> PrincipalRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        principal = principal_service.update_principal(
            business_id=scoped_business_id,
            principal_id=principal_id,
            payload=payload,
            actor_principal_id=admin_principal.id,
        )
    except PrincipalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PrincipalValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return PrincipalRead.model_validate(principal)


@router.post(
    "/{business_id}/principals/{principal_id}/activate",
    response_model=PrincipalRead,
)
def activate_principal(
    business_id: str,
    principal_id: str,
    _: None = Depends(require_admin_rate_limit("principal_activate")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_service: PrincipalService = Depends(get_principal_service),
) -> PrincipalRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        principal = principal_service.activate_principal(
            business_id=scoped_business_id,
            principal_id=principal_id,
            actor_principal_id=admin_principal.id,
        )
    except PrincipalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PrincipalRead.model_validate(principal)


@router.post(
    "/{business_id}/principals/{principal_id}/deactivate",
    response_model=PrincipalRead,
)
def deactivate_principal(
    business_id: str,
    principal_id: str,
    _: None = Depends(require_admin_rate_limit("principal_deactivate")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_service: PrincipalService = Depends(get_principal_service),
) -> PrincipalRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        principal = principal_service.deactivate_principal(
            business_id=scoped_business_id,
            principal_id=principal_id,
            actor_principal_id=admin_principal.id,
        )
    except PrincipalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PrincipalValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return PrincipalRead.model_validate(principal)


@router.get("/{business_id}/principal-identities", response_model=PrincipalIdentityListResponse)
def list_principal_identities(
    business_id: str,
    _: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_identity_service: PrincipalIdentityService = Depends(get_principal_identity_service),
) -> PrincipalIdentityListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = principal_identity_service.list_for_business(business_id=scoped_business_id)
    except PrincipalIdentityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PrincipalIdentityListResponse(
        items=[PrincipalIdentityRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/{business_id}/principal-identities",
    response_model=PrincipalIdentityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_principal_identity(
    business_id: str,
    payload: PrincipalIdentityCreateRequest,
    _: None = Depends(require_admin_rate_limit("principal_identity_create")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_identity_service: PrincipalIdentityService = Depends(get_principal_identity_service),
) -> PrincipalIdentityRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        identity = principal_identity_service.create_identity(
            business_id=scoped_business_id,
            payload=PrincipalIdentityCreateInput(
                provider=payload.provider,
                provider_subject=payload.provider_subject,
                principal_id=payload.principal_id,
                email=payload.email,
                email_verified=payload.email_verified,
                is_active=payload.is_active,
            ),
            actor_principal_id=admin_principal.id,
        )
    except PrincipalIdentityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PrincipalIdentityValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return PrincipalIdentityRead.model_validate(identity)


@router.post(
    "/{business_id}/principal-identities/{identity_id}/activate",
    response_model=PrincipalIdentityRead,
)
def activate_principal_identity(
    business_id: str,
    identity_id: str,
    _: None = Depends(require_admin_rate_limit("principal_identity_activate")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_identity_service: PrincipalIdentityService = Depends(get_principal_identity_service),
) -> PrincipalIdentityRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        identity = principal_identity_service.activate_identity(
            business_id=scoped_business_id,
            identity_id=identity_id,
            actor_principal_id=admin_principal.id,
        )
    except PrincipalIdentityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PrincipalIdentityRead.model_validate(identity)


@router.post(
    "/{business_id}/principal-identities/{identity_id}/deactivate",
    response_model=PrincipalIdentityRead,
)
def deactivate_principal_identity(
    business_id: str,
    identity_id: str,
    _: None = Depends(require_admin_rate_limit("principal_identity_deactivate")),
    admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal_identity_service: PrincipalIdentityService = Depends(get_principal_identity_service),
) -> PrincipalIdentityRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        identity = principal_identity_service.deactivate_identity(
            business_id=scoped_business_id,
            identity_id=identity_id,
            actor_principal_id=admin_principal.id,
        )
    except PrincipalIdentityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PrincipalIdentityRead.model_validate(identity)


@router.get("/{business_id}/auth-audit-events", response_model=AuthAuditEventListResponse)
def list_auth_audit_events(
    business_id: str,
    target_type: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
    _rate_limit: None = Depends(require_admin_rate_limit("auth_audit_read")),
    _principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    auth_audit_service: AuthAuditService = Depends(get_auth_audit_service),
) -> AuthAuditEventListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        events = auth_audit_service.list_for_business(
            business_id=scoped_business_id,
            target_type=target_type,
            event_type=event_type,
            limit=limit,
        )
    except AuthAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return AuthAuditEventListResponse(
        items=[AuthAuditEventRead.model_validate(event) for event in events],
        total=len(events),
    )

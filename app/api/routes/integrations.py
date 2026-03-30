from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import (
    TenantContext,
    get_authenticated_principal,
    get_google_business_profile_connection_service,
    get_google_business_profile_service,
    get_tenant_context,
    require_credential_manager_principal,
)
from app.core.config import Settings, get_settings
from app.models.principal import Principal
from app.schemas.google_business_profile import (
    GoogleBusinessProfileAccountsResponse,
    GoogleBusinessProfileAccountResponse,
    GoogleBusinessProfileCompleteVerificationRequest,
    GoogleBusinessProfileCompleteVerificationResponse,
    GoogleBusinessProfileConnectionStatusResponse,
    GoogleBusinessProfileConnectStartResponse,
    GoogleBusinessProfileDisconnectResponse,
    GoogleBusinessProfileFlatLocationResponse,
    GoogleBusinessProfileLocationResponse,
    GoogleBusinessProfileLocationsResponse,
    GoogleBusinessProfileRetryVerificationRequest,
    GoogleBusinessProfileRetryVerificationResponse,
    GoogleBusinessProfileStartVerificationRequest,
    GoogleBusinessProfileStartVerificationResponse,
    GoogleBusinessProfileLocationVerificationResponse,
    GoogleBusinessProfileVerificationMethodOptionResponse,
    GoogleBusinessProfileVerificationOptionsResponse,
    GoogleBusinessProfileVerificationRecordResponse,
    GoogleBusinessProfileVerificationGuidanceResponse,
    GoogleBusinessProfileVerificationErrorDetailResponse,
    GoogleBusinessProfileVerificationStatusCurrentResponse,
    GoogleBusinessProfileVerificationObservabilityCountersResponse,
    GoogleBusinessProfileVerificationStatusResponse,
)
from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionConfigurationError,
    GoogleBusinessProfileConnectionNotFoundError,
    GoogleBusinessProfileConnectionService,
    GoogleBusinessProfileConnectionStatusResult,
    GoogleBusinessProfileConnectionValidationError,
)
from app.services.google_business_profile_service import (
    GoogleBusinessProfileAccountResult,
    GoogleBusinessProfileVerificationActionResult,
    GoogleBusinessProfileVerificationMethodOptionResult,
    GoogleBusinessProfileVerificationOptionsResult,
    GoogleBusinessProfileVerificationStatusCurrentResult,
    GoogleBusinessProfileVerificationStatusResult,
    GoogleBusinessProfileAccountsResult,
    GoogleBusinessProfileFlatLocationResult,
    GoogleBusinessProfileLocationResult,
    GoogleBusinessProfileLocationsResult,
    GoogleBusinessProfileService,
    GoogleBusinessProfileServiceError,
    GoogleBusinessProfileVerificationRecordResult,
    GoogleBusinessProfileVerificationResult,
    VerificationGuidanceResult,
)
from app.services.google_business_profile_verification_observability import export_gbp_verification_counters
from app.services.verification_guidance_service import VerificationGuidanceService

router = APIRouter(prefix="/api/integrations/google/business-profile", tags=["integrations"])
_verification_guidance_service = VerificationGuidanceService()


@router.post("/connect/start", response_model=GoogleBusinessProfileConnectStartResponse)
def start_google_business_profile_connect(
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileConnectStartResponse:
    try:
        result = service.start_connection(
            business_id=tenant_context.business_id,
            principal_id=principal.id,
        )
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return GoogleBusinessProfileConnectStartResponse(
        authorization_url=result.authorization_url,
        state_expires_at=result.state_expires_at,
        provider=result.provider,
        required_scope=result.required_scope,
    )


@router.get("/connect/callback", response_model=GoogleBusinessProfileConnectionStatusResponse)
def google_business_profile_connect_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    response_mode: Literal["auto", "json", "redirect"] = "auto",
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileConnectionStatusResponse | RedirectResponse:
    browser_redirect = _callback_should_redirect_to_app(
        request=request,
        response_mode=response_mode,
    )

    try:
        result = service.handle_callback(
            state=state,
            code=code,
            error=error,
            error_description=error_description,
        )
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        if browser_redirect:
            return RedirectResponse(
                url=_build_connect_callback_redirect_url(
                    request=request,
                    success=False,
                    error_code="not_found",
                    reconnect_required=False,
                ),
                status_code=status.HTTP_303_SEE_OTHER,
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        if browser_redirect:
            return RedirectResponse(
                url=_build_connect_callback_redirect_url(
                    request=request,
                    success=False,
                    error_code="configuration",
                    reconnect_required=False,
                ),
                status_code=status.HTTP_303_SEE_OTHER,
            )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionValidationError as exc:
        if browser_redirect:
            return RedirectResponse(
                url=_build_connect_callback_redirect_url(
                    request=request,
                    success=False,
                    error_code="validation",
                    reconnect_required=exc.reconnect_required,
                ),
                status_code=status.HTTP_303_SEE_OTHER,
            )
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    if browser_redirect:
        return RedirectResponse(
            url=_build_connect_callback_redirect_url(
                request=request,
                success=True,
                error_code=None,
                reconnect_required=False,
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return _to_connection_response(result)


@router.get("/connection", response_model=GoogleBusinessProfileConnectionStatusResponse)
def get_google_business_profile_connection(
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileConnectionStatusResponse:
    try:
        result = service.get_connection_status(business_id=tenant_context.business_id)
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return _to_connection_response(result)


@router.post("/disconnect", response_model=GoogleBusinessProfileDisconnectResponse)
def disconnect_google_business_profile(
    tenant_context: TenantContext = Depends(get_tenant_context),
    principal: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileConnectionService = Depends(get_google_business_profile_connection_service),
) -> GoogleBusinessProfileDisconnectResponse:
    try:
        disconnected = service.revoke_or_disconnect_provider(
            business_id=tenant_context.business_id,
            actor_principal_id=principal.id,
        )
        current = service.get_connection_status(business_id=tenant_context.business_id)
    except GoogleBusinessProfileConnectionConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoogleBusinessProfileConnectionValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return GoogleBusinessProfileDisconnectResponse(
        status="disconnected" if disconnected else "not_connected",
        connection=_to_connection_response(current),
    )


@router.get("/accounts", response_model=GoogleBusinessProfileAccountsResponse)
def list_google_business_profile_accounts(
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileAccountsResponse:
    try:
        result = service.list_accounts(business_id=tenant_context.business_id)
    except GoogleBusinessProfileServiceError as exc:
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return _to_accounts_response(result)


@router.get("/locations", response_model=GoogleBusinessProfileLocationsResponse)
def list_google_business_profile_locations(
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileLocationsResponse:
    try:
        result = service.list_locations(business_id=tenant_context.business_id)
    except GoogleBusinessProfileServiceError as exc:
        detail: str | dict[str, object] = str(exc)
        if exc.reconnect_required:
            detail = {
                "message": str(exc),
                "reconnect_required": True,
            }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return _to_locations_response(result)


@router.get("/locations/{location_id}/verification", response_model=GoogleBusinessProfileLocationVerificationResponse)
def get_google_business_profile_location_verification(
    location_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileLocationVerificationResponse:
    try:
        result = service.get_location_verification(
            business_id=tenant_context.business_id,
            location_id=location_id,
        )
    except GoogleBusinessProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_service_error_detail(exc)) from exc
    return _to_verification_response(result)


@router.get(
    "/locations/{location_id}/verification/options", response_model=GoogleBusinessProfileVerificationOptionsResponse
)
def get_google_business_profile_location_verification_options(
    location_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileVerificationOptionsResponse:
    try:
        result = service.get_location_verification_options(
            business_id=tenant_context.business_id,
            location_id=location_id,
        )
    except GoogleBusinessProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_service_error_detail(exc)) from exc
    return _to_verification_options_response(result)


@router.get(
    "/locations/{location_id}/verification/status", response_model=GoogleBusinessProfileVerificationStatusResponse
)
def get_google_business_profile_location_verification_status(
    location_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileVerificationStatusResponse:
    try:
        result = service.get_location_verification_status(
            business_id=tenant_context.business_id,
            location_id=location_id,
        )
    except GoogleBusinessProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_service_error_detail(exc)) from exc
    return _to_verification_status_response(result)


@router.post(
    "/locations/{location_id}/verification/start", response_model=GoogleBusinessProfileStartVerificationResponse
)
def start_google_business_profile_location_verification(
    location_id: str,
    payload: GoogleBusinessProfileStartVerificationRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileStartVerificationResponse:
    try:
        result = service.start_location_verification(
            business_id=tenant_context.business_id,
            location_id=location_id,
            option_id=payload.option_id,
            selected_method=payload.selected_method,
            provider_method=payload.provider_method,
            destination=payload.destination,
            language_code=payload.language_code,
            mailer_contact=payload.mailer_contact,
            vetted_partner_token=payload.vetted_partner_token,
        )
    except GoogleBusinessProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_service_error_detail(exc)) from exc
    return _to_start_verification_response(result)


@router.post(
    "/locations/{location_id}/verification/complete", response_model=GoogleBusinessProfileCompleteVerificationResponse
)
def complete_google_business_profile_location_verification(
    location_id: str,
    payload: GoogleBusinessProfileCompleteVerificationRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileCompleteVerificationResponse:
    try:
        result = service.complete_location_verification(
            business_id=tenant_context.business_id,
            location_id=location_id,
            verification_id=payload.verification_id,
            code=payload.code,
        )
    except GoogleBusinessProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_service_error_detail(exc)) from exc
    return _to_complete_verification_response(result)


@router.post(
    "/locations/{location_id}/verification/retry", response_model=GoogleBusinessProfileRetryVerificationResponse
)
def retry_google_business_profile_location_verification(
    location_id: str,
    payload: GoogleBusinessProfileRetryVerificationRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    _: Principal = Depends(get_authenticated_principal),
    service: GoogleBusinessProfileService = Depends(get_google_business_profile_service),
) -> GoogleBusinessProfileRetryVerificationResponse:
    try:
        result = service.retry_location_verification(
            business_id=tenant_context.business_id,
            location_id=location_id,
            option_id=payload.option_id,
            selected_method=payload.selected_method,
            provider_method=payload.provider_method,
            destination=payload.destination,
            language_code=payload.language_code,
            mailer_contact=payload.mailer_contact,
            vetted_partner_token=payload.vetted_partner_token,
        )
    except GoogleBusinessProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_service_error_detail(exc)) from exc
    return _to_retry_verification_response(result)


@router.get(
    "/verification/observability/counters",
    response_model=GoogleBusinessProfileVerificationObservabilityCountersResponse,
)
def get_google_business_profile_verification_observability_counters(
    _: TenantContext = Depends(get_tenant_context),
    __: Principal = Depends(require_credential_manager_principal),
) -> GoogleBusinessProfileVerificationObservabilityCountersResponse:
    return GoogleBusinessProfileVerificationObservabilityCountersResponse(
        **export_gbp_verification_counters(),
    )


def _to_connection_response(
    result: GoogleBusinessProfileConnectionStatusResult,
) -> GoogleBusinessProfileConnectionStatusResponse:
    return GoogleBusinessProfileConnectionStatusResponse(
        provider=result.provider,
        connected=result.connected,
        business_id=result.business_id,
        granted_scopes=list(result.granted_scopes),
        refresh_token_present=result.refresh_token_present,
        expires_at=result.expires_at,
        connected_at=result.connected_at,
        last_refreshed_at=result.last_refreshed_at,
        reconnect_required=result.reconnect_required,
        required_scopes_satisfied=result.required_scopes_satisfied,
        token_status=result.token_status,
    )


def _callback_should_redirect_to_app(
    *,
    request: Request,
    response_mode: Literal["auto", "json", "redirect"],
) -> bool:
    if response_mode == "json":
        return False
    if response_mode == "redirect":
        return True

    accept = (request.headers.get("accept") or "").lower()
    sec_fetch_dest = (request.headers.get("sec-fetch-dest") or "").lower()
    return ("text/html" in accept) or (sec_fetch_dest == "document")


def _build_connect_callback_redirect_url(
    *,
    request: Request,
    success: bool,
    error_code: str | None,
    reconnect_required: bool,
) -> str:
    settings = get_settings()
    base_url = _resolve_connect_callback_return_base_url(
        request=request,
        settings=settings,
    )

    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    existing_params["gbp_connect"] = ["success" if success else "error"]
    if not success and error_code:
        existing_params["gbp_connect_error"] = [error_code]
    if reconnect_required:
        existing_params["gbp_reconnect_required"] = ["true"]

    query = urlencode(existing_params, doseq=True)
    return urlunparse(parsed._replace(query=query))


def _resolve_connect_callback_return_base_url(
    *,
    request: Request,
    settings: Settings,
) -> str:
    preferred = _preferred_operator_origin(settings=settings)
    if preferred:
        return f"{preferred.rstrip('/')}/business-profile"

    request_origin = _normalize_origin(str(request.base_url))
    if request_origin:
        return f"{request_origin.rstrip('/')}/business-profile"

    return "http://localhost:3000/business-profile"


def _preferred_operator_origin(*, settings: Settings) -> str | None:
    cors_origins = tuple(settings.api_cors_allowed_origins or ())
    non_loopback = (
        origin
        for origin in cors_origins
        if (_normalize_origin(origin) and not _origin_is_loopback(origin))
    )
    first_non_loopback = next(non_loopback, None)
    if first_non_loopback:
        return _normalize_origin(first_non_loopback)

    redirect_origin = _normalize_origin(settings.google_business_profile_redirect_uri or "")
    if redirect_origin:
        return redirect_origin

    first_cors = next((origin for origin in cors_origins if _normalize_origin(origin)), None)
    if first_cors:
        return _normalize_origin(first_cors)

    return None


def _normalize_origin(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{hostname}{port}"


def _origin_is_loopback(value: str) -> bool:
    normalized = _normalize_origin(value)
    if not normalized:
        return False
    hostname = (urlparse(normalized).hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _to_accounts_response(result: GoogleBusinessProfileAccountsResult) -> GoogleBusinessProfileAccountsResponse:
    return GoogleBusinessProfileAccountsResponse(
        accounts=[_to_account_response(account) for account in result.accounts]
    )


def _to_account_response(result: GoogleBusinessProfileAccountResult) -> GoogleBusinessProfileAccountResponse:
    return GoogleBusinessProfileAccountResponse(
        account_id=result.account_id,
        account_name=result.account_name,
        locations=[_to_location_response(location) for location in result.locations],
    )


def _to_location_response(result: GoogleBusinessProfileLocationResult) -> GoogleBusinessProfileLocationResponse:
    return GoogleBusinessProfileLocationResponse(
        location_id=result.location_id,
        title=result.title,
        address=result.address,
        verification=_to_verification_response(result.verification),
    )


def _to_locations_response(result: GoogleBusinessProfileLocationsResult) -> GoogleBusinessProfileLocationsResponse:
    return GoogleBusinessProfileLocationsResponse(
        locations=[_to_flat_location_response(location) for location in result.locations]
    )


def _to_flat_location_response(
    result: GoogleBusinessProfileFlatLocationResult,
) -> GoogleBusinessProfileFlatLocationResponse:
    return GoogleBusinessProfileFlatLocationResponse(
        account_id=result.account_id,
        account_name=result.account_name,
        location_id=result.location_id,
        title=result.title,
        address=result.address,
        verification=_to_verification_response(result.verification),
    )


def _to_verification_response(
    result: GoogleBusinessProfileVerificationResult,
) -> GoogleBusinessProfileLocationVerificationResponse:
    return GoogleBusinessProfileLocationVerificationResponse(
        has_voice_of_merchant=result.has_voice_of_merchant,
        state_summary=result.state_summary,
        verification_methods=list(result.verification_methods),
        verifications=[_to_verification_record_response(item) for item in result.verifications],
        recommended_next_action=result.recommended_next_action,
        guidance=_to_verification_guidance_response(result.guidance),
    )


def _to_verification_record_response(
    result: GoogleBusinessProfileVerificationRecordResult,
) -> GoogleBusinessProfileVerificationRecordResponse:
    return GoogleBusinessProfileVerificationRecordResponse(
        name=result.name,
        method=result.method,
        state=result.state,
        create_time=result.create_time,
        complete_time=result.complete_time,
    )


def _to_verification_options_response(
    result: GoogleBusinessProfileVerificationOptionsResult,
) -> GoogleBusinessProfileVerificationOptionsResponse:
    return GoogleBusinessProfileVerificationOptionsResponse(
        location_id=result.location_id,
        current_verification_state=result.current_verification_state,
        methods=[_to_verification_method_option_response(item) for item in result.methods],
        guidance=_to_verification_guidance_response(result.guidance),
    )


def _to_verification_status_response(
    result: GoogleBusinessProfileVerificationStatusResult,
) -> GoogleBusinessProfileVerificationStatusResponse:
    return GoogleBusinessProfileVerificationStatusResponse(
        location_id=result.location_id,
        verification_state=result.verification_state,
        action_required=result.action_required,
        message=result.message,
        reconnect_required=result.reconnect_required,
        current_verification=(
            _to_verification_status_current_response(result.current_verification)
            if result.current_verification is not None
            else None
        ),
        available_methods=[_to_verification_method_option_response(item) for item in result.available_methods],
        guidance=_to_verification_guidance_response(result.guidance),
    )


def _to_start_verification_response(
    result: GoogleBusinessProfileVerificationActionResult,
) -> GoogleBusinessProfileStartVerificationResponse:
    return GoogleBusinessProfileStartVerificationResponse(
        location_id=result.location_id,
        verification_state=result.verification_state,
        verification_id=result.verification_id,
        action_required=result.action_required,
        message=result.message,
        reconnect_required=result.status.reconnect_required,
        expires_at=result.expires_at,
        status=_to_verification_status_response(result.status),
        guidance=_to_verification_guidance_response(result.guidance),
    )


def _to_complete_verification_response(
    result: GoogleBusinessProfileVerificationActionResult,
) -> GoogleBusinessProfileCompleteVerificationResponse:
    return GoogleBusinessProfileCompleteVerificationResponse(
        location_id=result.location_id,
        verification_state=result.verification_state,
        verification_id=result.verification_id,
        action_required=result.action_required,
        message=result.message,
        reconnect_required=result.status.reconnect_required,
        expires_at=result.expires_at,
        status=_to_verification_status_response(result.status),
        guidance=_to_verification_guidance_response(result.guidance),
    )


def _to_retry_verification_response(
    result: GoogleBusinessProfileVerificationActionResult,
) -> GoogleBusinessProfileRetryVerificationResponse:
    return GoogleBusinessProfileRetryVerificationResponse(
        location_id=result.location_id,
        verification_state=result.verification_state,
        verification_id=result.verification_id,
        action_required=result.action_required,
        message=result.message,
        reconnect_required=result.status.reconnect_required,
        expires_at=result.expires_at,
        status=_to_verification_status_response(result.status),
        guidance=_to_verification_guidance_response(result.guidance),
    )


def _to_verification_method_option_response(
    result: GoogleBusinessProfileVerificationMethodOptionResult,
) -> GoogleBusinessProfileVerificationMethodOptionResponse:
    return GoogleBusinessProfileVerificationMethodOptionResponse(
        option_id=result.option_id,
        method=result.method,
        provider_method=result.provider_method,
        label=result.label,
        description=result.description,
        destination=result.destination,
        requires_code=result.requires_code,
        eligible=result.eligible,
    )


def _to_verification_status_current_response(
    result: GoogleBusinessProfileVerificationStatusCurrentResult,
) -> GoogleBusinessProfileVerificationStatusCurrentResponse:
    return GoogleBusinessProfileVerificationStatusCurrentResponse(
        verification_id=result.verification_id,
        provider_state=result.provider_state,
        method=result.method,
        provider_method=result.provider_method,
        create_time=result.create_time,
        complete_time=result.complete_time,
        expires_at=result.expires_at,
    )


def _to_verification_guidance_response(
    result: VerificationGuidanceResult,
) -> GoogleBusinessProfileVerificationGuidanceResponse:
    return GoogleBusinessProfileVerificationGuidanceResponse(
        verification_state=result.verification_state,
        recommended_action=result.recommended_action,
        priority=result.priority,
        title=result.title,
        summary=result.summary,
        instructions=list(result.instructions),
        tips=list(result.tips),
        warnings=list(result.warnings),
        troubleshooting=list(result.troubleshooting),
        estimated_time=result.estimated_time,
        cta_label=result.cta_label,
        cta_type=result.cta_type,
        recommended_method=result.recommended_method,
        recommendation_reason=result.recommendation_reason,
    )


def _service_error_detail(exc: GoogleBusinessProfileServiceError) -> dict[str, object]:
    guidance = _error_guidance_for_service_error(exc)
    detail = GoogleBusinessProfileVerificationErrorDetailResponse(
        code=exc.error_code,
        message=str(exc),
        reconnect_required=exc.reconnect_required,
        guidance=(_to_verification_guidance_response(guidance) if guidance is not None else None),
    )
    return detail.model_dump()


def _error_guidance_for_service_error(exc: GoogleBusinessProfileServiceError) -> VerificationGuidanceResult | None:
    verification_state = "unknown"
    action_required = "resolve_access"
    guidance_error_code = exc.error_code
    reconnect_required = exc.reconnect_required

    if exc.error_code == "method_not_available":
        verification_state = "unverified"
        action_required = "choose_method"
        guidance_error_code = None
    elif exc.error_code == "invalid_code":
        verification_state = "pending"
        action_required = "enter_code"
        guidance_error_code = None
    elif exc.error_code == "verification_not_supported":
        verification_state = "unverified"
        action_required = "resolve_access"
    elif exc.error_code == "invalid_verification_state":
        verification_state = "unknown"
        action_required = "resolve_access"
    elif exc.error_code == "reconnect_required":
        verification_state = "unknown"
        action_required = "reconnect_google"
        reconnect_required = True

    return _verification_guidance_service.generate_guidance(
        verification_state=verification_state,
        action_required=action_required,
        reconnect_required=reconnect_required,
        error_code=guidance_error_code,
    )

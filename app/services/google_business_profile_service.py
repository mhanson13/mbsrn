from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from app.integrations.google_business_profile import GoogleBusinessProfileAPIError, GoogleBusinessProfileClient
from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionService,
)
from app.services.google_business_profile_verification_observability import (
    record_gbp_verification_observation,
)
from app.services.google_business_profile_verification_mapping import (
    VerificationActionRequired,
    VerificationErrorCode,
    VerificationMethod,
    VerificationNextAction,
    VerificationStateSummary,
    VerificationWorkflowState,
    build_method_option_token,
    determine_next_action,
    determine_state_summary,
    determine_summary_action_required,
    determine_workflow_action,
    determine_workflow_state,
    extract_voice_of_merchant,
    extract_verification_option_destination,
    format_storefront_address,
    map_provider_api_error,
    normalize_provider_method,
    provider_method_requires_code,
    verification_method_label,
)
from app.services.verification_guidance_service import (
    VerificationGuidanceErrorCode,
    VerificationGuidanceMethodOptionInput,
    VerificationGuidanceResult,
    VerificationGuidanceState,
    VerificationGuidanceService,
)

logger = logging.getLogger(__name__)


class GoogleBusinessProfileServiceError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        reconnect_required: bool = False,
        error_code: str = "provider_error",
        provider_error_class: str = "none",
        provider_http_status: int | None = None,
        diagnostic_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reconnect_required = reconnect_required
        self.error_code = error_code
        self.provider_error_class = provider_error_class
        self.provider_http_status = provider_http_status
        self.diagnostic_hint = diagnostic_hint


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationRecordResult:
    name: str | None
    method: str | None
    state: str | None
    create_time: str | None
    complete_time: str | None
    expires_at: str | None


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationResult:
    has_voice_of_merchant: bool | None
    state_summary: VerificationStateSummary
    verification_methods: tuple[str, ...]
    verifications: tuple[GoogleBusinessProfileVerificationRecordResult, ...]
    recommended_next_action: VerificationNextAction
    guidance: VerificationGuidanceResult


@dataclass(frozen=True)
class GoogleBusinessProfileLocationResult:
    location_id: str
    title: str
    address: str | None
    verification: GoogleBusinessProfileVerificationResult


@dataclass(frozen=True)
class GoogleBusinessProfileAccountResult:
    account_id: str
    account_name: str
    locations: tuple[GoogleBusinessProfileLocationResult, ...]


@dataclass(frozen=True)
class GoogleBusinessProfileAccountsResult:
    accounts: tuple[GoogleBusinessProfileAccountResult, ...]


@dataclass(frozen=True)
class GoogleBusinessProfileFlatLocationResult:
    account_id: str
    account_name: str
    location_id: str
    title: str
    address: str | None
    verification: GoogleBusinessProfileVerificationResult


@dataclass(frozen=True)
class GoogleBusinessProfileLocationsResult:
    locations: tuple[GoogleBusinessProfileFlatLocationResult, ...]


GoogleBusinessProfileConnectionState = Literal[
    "not_connected",
    "oauth_connected",
    "usable",
    "missing_scope",
    "permission_denied",
    "no_accounts",
    "no_locations",
    "location_not_mapped",
    "unavailable",
    "unknown",
]

GoogleBusinessProfileProviderErrorClass = Literal[
    "none",
    "token_refresh_failed",
    "missing_required_scope",
    "provider_unauthorized",
    "provider_permission_denied",
    "provider_api_disabled_or_unavailable",
    "provider_rate_limited",
    "provider_quota_or_access_not_granted",
    "provider_not_found",
    "provider_unavailable",
    "provider_unknown",
]


@dataclass(frozen=True)
class GoogleBusinessProfileConnectionDiagnosticsResult:
    gbp_connection_state: GoogleBusinessProfileConnectionState
    gbp_required_scope: str | None
    gbp_required_scope_granted: bool | None
    gbp_accounts_count: int | None
    gbp_locations_count: int | None
    gbp_selected_location_present: bool | None
    gbp_status_reason: str
    gbp_next_action: str
    gbp_provider_error_class: GoogleBusinessProfileProviderErrorClass
    gbp_provider_http_status: int | None
    gbp_diagnostic_hint: str | None


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationMethodOptionResult:
    option_id: str
    method: VerificationMethod
    provider_method: str
    label: str
    description: str | None
    destination: str | None
    requires_code: bool
    eligible: bool


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationStatusCurrentResult:
    verification_id: str
    provider_state: str | None
    method: VerificationMethod
    provider_method: str
    create_time: str | None
    complete_time: str | None
    expires_at: str | None


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationStatusResult:
    location_id: str
    verification_state: VerificationWorkflowState
    action_required: VerificationActionRequired
    message: str
    reconnect_required: bool
    current_verification: GoogleBusinessProfileVerificationStatusCurrentResult | None
    available_methods: tuple[GoogleBusinessProfileVerificationMethodOptionResult, ...]
    guidance: VerificationGuidanceResult


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationOptionsResult:
    location_id: str
    current_verification_state: VerificationWorkflowState
    methods: tuple[GoogleBusinessProfileVerificationMethodOptionResult, ...]
    guidance: VerificationGuidanceResult


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationActionResult:
    location_id: str
    verification_state: VerificationWorkflowState
    verification_id: str | None
    action_required: VerificationActionRequired
    message: str
    expires_at: str | None
    status: GoogleBusinessProfileVerificationStatusResult
    guidance: VerificationGuidanceResult


@dataclass(frozen=True)
class _GoogleBusinessProfileLocationContext:
    location_id: str
    location_resource_name: str
    account_id: str
    account_name: str
    title: str
    address: str | None


class GoogleBusinessProfileService:
    def __init__(
        self,
        *,
        connection_service: GoogleBusinessProfileConnectionService,
        client: GoogleBusinessProfileClient,
        guidance_service: VerificationGuidanceService | None = None,
    ) -> None:
        self.connection_service = connection_service
        self.client = client
        self.guidance_service = guidance_service or VerificationGuidanceService()

    def list_accounts(self, *, business_id: str) -> GoogleBusinessProfileAccountsResult:
        accounts_payload = self._call_google_api(
            business_id=business_id,
            callback=lambda access_token: self.client.list_accounts(access_token=access_token),
        )
        raw_accounts = _extract_list(accounts_payload, "accounts")
        accounts: list[GoogleBusinessProfileAccountResult] = []
        for raw_account in raw_accounts:
            account_resource_name = _normalized_str(raw_account.get("name"))
            if not account_resource_name:
                continue
            account_id = _resource_id(account_resource_name, "accounts/")
            account_name = _normalized_str(raw_account.get("accountName")) or account_id
            locations_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token, account_resource_name=account_resource_name: self.client.list_locations(
                    access_token=access_token,
                    account_resource_name=account_resource_name,
                ),
            )
            raw_locations = _extract_list(locations_payload, "locations")
            locations: list[GoogleBusinessProfileLocationResult] = []
            for raw_location in raw_locations:
                normalized = self._normalize_location(
                    business_id=business_id,
                    raw_location=raw_location,
                )
                if normalized is None:
                    continue
                locations.append(normalized)
            accounts.append(
                GoogleBusinessProfileAccountResult(
                    account_id=account_id,
                    account_name=account_name,
                    locations=tuple(locations),
                )
            )
        return GoogleBusinessProfileAccountsResult(accounts=tuple(accounts))

    def list_locations(self, *, business_id: str) -> GoogleBusinessProfileLocationsResult:
        accounts = self.list_accounts(business_id=business_id)
        flattened: list[GoogleBusinessProfileFlatLocationResult] = []
        for account in accounts.accounts:
            for location in account.locations:
                flattened.append(
                    GoogleBusinessProfileFlatLocationResult(
                        account_id=account.account_id,
                        account_name=account.account_name,
                        location_id=location.location_id,
                        title=location.title,
                        address=location.address,
                        verification=location.verification,
                    )
                )
        return GoogleBusinessProfileLocationsResult(locations=tuple(flattened))

    def evaluate_connection_diagnostics(
        self,
        *,
        business_id: str,
    ) -> GoogleBusinessProfileConnectionDiagnosticsResult:
        connection = self.connection_service.get_connection_status(
            business_id=business_id,
            required_scopes=(self.connection_service.BUSINESS_PROFILE_SCOPE,),
        )

        if not connection.connected:
            result = GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="not_connected",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=None,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="not_connected",
                gbp_next_action="Connect Google Profile for this business before loading Business Profile locations.",
                gbp_provider_error_class="none",
                gbp_provider_http_status=None,
                gbp_diagnostic_hint="Connect Google Profile, then refresh status.",
            )
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        if not connection.required_scopes_satisfied or connection.token_status == "insufficient_scope":
            result = GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="missing_scope",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=False,
                gbp_accounts_count=None,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="missing_scope",
                gbp_next_action="Reconnect Google Profile to grant the required Business Profile scope.",
                gbp_provider_error_class="missing_required_scope",
                gbp_provider_http_status=403,
                gbp_diagnostic_hint="Reconnect with the required Business Profile scope and retry.",
            )
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        if connection.reconnect_required or connection.token_status == "reconnect_required":
            result = GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="oauth_connected",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=connection.required_scopes_satisfied,
                gbp_accounts_count=None,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="oauth_connected_reconnect_required",
                gbp_next_action="Refresh or reconnect Google Profile before loading Business Profile accounts.",
                gbp_provider_error_class="none",
                gbp_provider_http_status=None,
                gbp_diagnostic_hint="Reconnect or refresh token state before retrying account discovery.",
            )
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        try:
            accounts_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token: self.client.list_accounts(access_token=access_token),
            )
        except GoogleBusinessProfileServiceError as exc:
            result = self._diagnostics_from_service_error(exc)
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        raw_accounts = _extract_list(accounts_payload, "accounts")
        accounts_count = len(raw_accounts)
        if accounts_count == 0:
            result = GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="no_accounts",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=True,
                gbp_accounts_count=0,
                gbp_locations_count=0,
                gbp_selected_location_present=None,
                gbp_status_reason="no_accounts",
                gbp_next_action="Confirm the connected Google identity has access to at least one Business Profile account.",
                gbp_provider_error_class="none",
                gbp_provider_http_status=None,
                gbp_diagnostic_hint="Check the connected Google identity and Business Profile account membership.",
            )
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        locations_count = 0
        try:
            for raw_account in raw_accounts:
                account_resource_name = _normalized_str(raw_account.get("name"))
                if not account_resource_name:
                    continue
                locations_payload = self._call_google_api(
                    business_id=business_id,
                    callback=lambda access_token, account_resource_name=account_resource_name: self.client.list_locations(
                        access_token=access_token,
                        account_resource_name=account_resource_name,
                    ),
                )
                locations_count += len(_extract_list(locations_payload, "locations"))
        except GoogleBusinessProfileServiceError as exc:
            result = self._diagnostics_from_service_error(
                exc,
                accounts_count=accounts_count,
            )
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        if locations_count == 0:
            result = GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="no_locations",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=True,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=0,
                gbp_selected_location_present=None,
                gbp_status_reason="no_locations",
                gbp_next_action="Confirm the connected Google account can access one or more Business Profile locations.",
                gbp_provider_error_class="none",
                gbp_provider_http_status=None,
                gbp_diagnostic_hint="Check location visibility in Business Profile Manager for the connected identity.",
            )
            self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
            return result

        result = GoogleBusinessProfileConnectionDiagnosticsResult(
            gbp_connection_state="usable",
            gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
            gbp_required_scope_granted=True,
            gbp_accounts_count=accounts_count,
            gbp_locations_count=locations_count,
            gbp_selected_location_present=None,
            gbp_status_reason="usable",
            gbp_next_action="Google Business Profile access is usable for this business.",
            gbp_provider_error_class="none",
            gbp_provider_http_status=None,
            gbp_diagnostic_hint="Business Profile API is reachable for this connection.",
        )
        self._log_connection_diagnostics(business_id=business_id, diagnostics=result)
        return result

    def get_location_verification(
        self,
        *,
        business_id: str,
        location_id: str,
    ) -> GoogleBusinessProfileVerificationResult:
        normalized_location_id = location_id.strip()
        if not normalized_location_id:
            raise GoogleBusinessProfileServiceError(
                "Location id is required.",
                status_code=400,
                error_code="not_found",
            )

        locations = self.list_locations(business_id=business_id)
        for location in locations.locations:
            if location.location_id == normalized_location_id:
                return location.verification
        raise GoogleBusinessProfileServiceError(
            "Google Business Profile location not found for this business.",
            status_code=404,
            error_code="not_found",
        )

    def get_location_verification_options(
        self,
        *,
        business_id: str,
        location_id: str,
    ) -> GoogleBusinessProfileVerificationOptionsResult:
        context = self._resolve_location_context(
            business_id=business_id,
            location_id=location_id,
        )
        status = self._build_verification_workflow_status(
            business_id=business_id,
            context=context,
        )
        return GoogleBusinessProfileVerificationOptionsResult(
            location_id=context.location_id,
            current_verification_state=status.verification_state,
            methods=status.available_methods,
            guidance=status.guidance,
        )

    def get_location_verification_status(
        self,
        *,
        business_id: str,
        location_id: str,
    ) -> GoogleBusinessProfileVerificationStatusResult:
        context = self._resolve_location_context(
            business_id=business_id,
            location_id=location_id,
        )
        return self._build_verification_workflow_status(
            business_id=business_id,
            context=context,
        )

    def start_location_verification(
        self,
        *,
        business_id: str,
        location_id: str,
        option_id: str | None = None,
        selected_method: VerificationMethod | None = None,
        provider_method: str | None = None,
        destination: str | None = None,
        language_code: str | None = None,
        mailer_contact: str | None = None,
        vetted_partner_token: str | None = None,
    ) -> GoogleBusinessProfileVerificationActionResult:
        context = self._resolve_location_context(
            business_id=business_id,
            location_id=location_id,
        )
        current_status = self._build_verification_workflow_status(
            business_id=business_id,
            context=context,
        )
        if current_status.verification_state == "completed":
            raise GoogleBusinessProfileServiceError(
                "This location is already verified.",
                status_code=409,
                error_code="invalid_verification_state",
            )
        if not current_status.available_methods:
            raise GoogleBusinessProfileServiceError(
                "Verification methods are not currently available for this location.",
                status_code=409,
                error_code="verification_not_supported",
            )

        chosen_option = self._choose_verification_option(
            options=current_status.available_methods,
            option_id=option_id,
            selected_method=selected_method,
            provider_method=provider_method,
            destination=destination,
            fallback_to_first_single_option=True,
            location_id=context.location_id,
        )
        if chosen_option is None:
            raise GoogleBusinessProfileServiceError(
                "Selected verification method is not available for this location.",
                status_code=409,
                error_code="method_not_available",
            )

        verify_payload = self._build_start_verification_payload(
            option=chosen_option,
            destination=destination,
            language_code=language_code,
            mailer_contact=mailer_contact,
            vetted_partner_token=vetted_partner_token,
        )
        try:
            verification_result = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token: self.client.start_verification(
                    access_token=access_token,
                    location_resource_name=context.location_resource_name,
                    body=verify_payload,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            raise self._map_provider_error(exc, action="start") from exc

        verification_record = _normalize_single_verification_record(
            verification_result,
            context=f"start_verification location_id={context.location_id}",
        )
        if verification_record is None:
            logger.warning(
                "gbp_verification_start_missing_fields location_id=%s",
                context.location_id,
            )
        refreshed_status = self._build_verification_workflow_status(
            business_id=business_id,
            context=context,
        )
        message = "Verification started."
        if refreshed_status.action_required == "enter_code":
            message = "Verification started. Enter the verification code when you receive it."
        elif refreshed_status.action_required == "wait":
            message = "Verification started. Wait for Google to update verification progress."

        return GoogleBusinessProfileVerificationActionResult(
            location_id=context.location_id,
            verification_state=refreshed_status.verification_state,
            verification_id=(
                _verification_id_from_resource_name(verification_record.name)
                if verification_record and verification_record.name
                else (
                    refreshed_status.current_verification.verification_id
                    if refreshed_status.current_verification is not None
                    else None
                )
            ),
            action_required=refreshed_status.action_required,
            message=message,
            expires_at=(
                verification_record.expires_at
                if verification_record is not None
                else (
                    refreshed_status.current_verification.expires_at
                    if refreshed_status.current_verification is not None
                    else None
                )
            ),
            status=refreshed_status,
            guidance=refreshed_status.guidance,
        )

    def complete_location_verification(
        self,
        *,
        business_id: str,
        location_id: str,
        code: str,
        verification_id: str | None = None,
    ) -> GoogleBusinessProfileVerificationActionResult:
        normalized_code = code.strip()
        if not normalized_code:
            raise GoogleBusinessProfileServiceError(
                "Verification code is required.",
                status_code=400,
                error_code="invalid_code",
            )

        context = self._resolve_location_context(
            business_id=business_id,
            location_id=location_id,
        )
        current_status = self._build_verification_workflow_status(
            business_id=business_id,
            context=context,
        )
        if current_status.verification_state == "completed":
            raise GoogleBusinessProfileServiceError(
                "This location is already verified.",
                status_code=409,
                error_code="invalid_verification_state",
            )

        verification_resource_name = self._resolve_verification_resource_name(
            location_resource_name=context.location_resource_name,
            verification_id=verification_id,
            current=current_status.current_verification,
        )
        if not verification_resource_name:
            raise GoogleBusinessProfileServiceError(
                "No pending verification attempt was found for this location.",
                status_code=409,
                error_code="invalid_verification_state",
            )

        try:
            completion_result = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token: self.client.complete_verification(
                    access_token=access_token,
                    verification_resource_name=verification_resource_name,
                    pin=normalized_code,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            raise self._map_provider_error(exc, action="complete") from exc

        completion_record = _normalize_single_verification_record(
            completion_result,
            context=f"complete_verification location_id={context.location_id}",
        )
        if completion_record is None:
            logger.warning(
                "gbp_verification_complete_missing_fields location_id=%s",
                context.location_id,
            )
        refreshed_status = self._build_verification_workflow_status(
            business_id=business_id,
            context=context,
        )
        completion_message = "Verification completion submitted."
        if refreshed_status.verification_state == "completed":
            completion_message = "Location verification completed."

        return GoogleBusinessProfileVerificationActionResult(
            location_id=context.location_id,
            verification_state=refreshed_status.verification_state,
            verification_id=(
                _verification_id_from_resource_name(completion_record.name)
                if completion_record and completion_record.name
                else (
                    refreshed_status.current_verification.verification_id
                    if refreshed_status.current_verification is not None
                    else None
                )
            ),
            action_required=refreshed_status.action_required,
            message=completion_message,
            expires_at=(
                completion_record.expires_at
                if completion_record is not None
                else (
                    refreshed_status.current_verification.expires_at
                    if refreshed_status.current_verification is not None
                    else None
                )
            ),
            status=refreshed_status,
            guidance=refreshed_status.guidance,
        )

    def retry_location_verification(
        self,
        *,
        business_id: str,
        location_id: str,
        option_id: str | None = None,
        selected_method: VerificationMethod | None = None,
        provider_method: str | None = None,
        destination: str | None = None,
        language_code: str | None = None,
        mailer_contact: str | None = None,
        vetted_partner_token: str | None = None,
    ) -> GoogleBusinessProfileVerificationActionResult:
        status = self.get_location_verification_status(
            business_id=business_id,
            location_id=location_id,
        )
        if status.verification_state == "completed":
            raise GoogleBusinessProfileServiceError(
                "This location is already verified.",
                status_code=409,
                error_code="invalid_verification_state",
            )

        resolved_method = selected_method
        resolved_provider_method = provider_method
        if (
            option_id is None
            and selected_method is None
            and provider_method is None
            and status.current_verification is not None
        ):
            resolved_method = status.current_verification.method
            resolved_provider_method = status.current_verification.provider_method

        result = self.start_location_verification(
            business_id=business_id,
            location_id=location_id,
            option_id=option_id,
            selected_method=resolved_method,
            provider_method=resolved_provider_method,
            destination=destination,
            language_code=language_code,
            mailer_contact=mailer_contact,
            vetted_partner_token=vetted_partner_token,
        )
        return GoogleBusinessProfileVerificationActionResult(
            location_id=result.location_id,
            verification_state=result.verification_state,
            verification_id=result.verification_id,
            action_required=result.action_required,
            message="Verification retry started.",
            expires_at=result.expires_at,
            status=result.status,
            guidance=result.guidance,
        )

    def _normalize_location(
        self,
        *,
        business_id: str,
        raw_location: dict[str, Any],
    ) -> GoogleBusinessProfileLocationResult | None:
        location_resource_name = _normalized_str(raw_location.get("name"))
        if not location_resource_name:
            return None
        location_id = _resource_id(location_resource_name, "locations/")
        title = _normalized_str(raw_location.get("title")) or location_id
        address = format_storefront_address(raw_location.get("storefrontAddress"))
        verification = self._build_location_verification(
            business_id=business_id,
            location_resource_name=location_resource_name,
        )
        return GoogleBusinessProfileLocationResult(
            location_id=location_id,
            title=title,
            address=address,
            verification=verification,
        )

    def _build_location_verification(
        self,
        *,
        business_id: str,
        location_resource_name: str,
    ) -> GoogleBusinessProfileVerificationResult:
        permission_error = False
        ambiguous_error = False
        voice_payload: dict[str, Any] | None = None
        verifications_payload: dict[str, Any] | None = None
        verification_options_payload: dict[str, Any] | None = None

        try:
            voice_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token, location_resource_name=location_resource_name: self.client.get_voice_of_merchant_state(
                    access_token=access_token,
                    location_resource_name=location_resource_name,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            if exc.status_code == 404:
                voice_payload = None
            elif exc.is_permission_denied:
                permission_error = True
            else:
                ambiguous_error = True

        try:
            verifications_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token, location_resource_name=location_resource_name: self.client.list_verifications(
                    access_token=access_token,
                    location_resource_name=location_resource_name,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            if exc.status_code == 404:
                verifications_payload = None
            elif exc.is_permission_denied:
                permission_error = True
            else:
                ambiguous_error = True

        try:
            verification_options_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token, location_resource_name=location_resource_name: self.client.fetch_verification_options(
                    access_token=access_token,
                    location_resource_name=location_resource_name,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            if exc.status_code == 404:
                verification_options_payload = None
            elif exc.is_permission_denied:
                permission_error = True
            else:
                ambiguous_error = True

        has_voice_of_merchant = extract_voice_of_merchant(voice_payload) if voice_payload is not None else None
        verifications = _normalize_verifications(verifications_payload)
        verification_methods = _normalize_verification_methods(
            verification_options_payload,
            context=f"verification_methods location_id={_resource_id(location_resource_name, 'locations/')}",
        )
        method_options = _normalize_verification_method_options(
            verification_options_payload,
            context=f"verification_options location_id={_resource_id(location_resource_name, 'locations/')}",
        )
        current_verification = _current_verification_status(
            verifications,
            context=f"current_verification location_id={_resource_id(location_resource_name, 'locations/')}",
        )

        if permission_error:
            state_summary: VerificationStateSummary = "unknown"
            recommended_next_action: VerificationNextAction = "resolve_access"
            action_required = "resolve_access"
            error_code: VerificationErrorCode | None = "permission_denied"
        elif ambiguous_error:
            state_summary = "unknown"
            recommended_next_action = "resolve_access"
            action_required = "resolve_access"
            error_code = "provider_error"
        else:
            state_summary = determine_state_summary(
                has_voice_of_merchant=has_voice_of_merchant,
                provider_states=[entry.state for entry in verifications],
                has_verifications=bool(verifications),
                context=f"location_verification_summary location_id={_resource_id(location_resource_name, 'locations/')}",
            )
            recommended_next_action = determine_next_action(state_summary)
            action_required = determine_summary_action_required(
                state_summary=state_summary,
                current_provider_method=(
                    current_verification.provider_method if current_verification is not None else None
                ),
                has_available_methods=bool(method_options),
            )
            error_code = None

        guidance = self._build_guidance(
            verification_state=state_summary,
            action_required=action_required,
            current_verification=current_verification,
            available_methods=method_options,
            reconnect_required=False,
            error_code=error_code,
        )

        return GoogleBusinessProfileVerificationResult(
            has_voice_of_merchant=has_voice_of_merchant,
            state_summary=state_summary,
            verification_methods=tuple(verification_methods),
            verifications=tuple(verifications),
            recommended_next_action=recommended_next_action,
            guidance=guidance,
        )

    def _resolve_location_context(
        self,
        *,
        business_id: str,
        location_id: str,
    ) -> _GoogleBusinessProfileLocationContext:
        normalized_location_id = location_id.strip()
        if not normalized_location_id:
            raise GoogleBusinessProfileServiceError(
                "Location id is required.",
                status_code=400,
                error_code="not_found",
            )

        accounts_payload = self._call_google_api(
            business_id=business_id,
            callback=lambda access_token: self.client.list_accounts(access_token=access_token),
        )
        raw_accounts = _extract_list(accounts_payload, "accounts")
        for raw_account in raw_accounts:
            account_resource_name = _normalized_str(raw_account.get("name"))
            if not account_resource_name:
                continue
            account_id = _resource_id(account_resource_name, "accounts/")
            account_name = _normalized_str(raw_account.get("accountName")) or account_id
            locations_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token, account_resource_name=account_resource_name: self.client.list_locations(
                    access_token=access_token,
                    account_resource_name=account_resource_name,
                ),
            )
            raw_locations = _extract_list(locations_payload, "locations")
            for raw_location in raw_locations:
                location_resource_name = _normalized_str(raw_location.get("name"))
                if not location_resource_name:
                    continue
                candidate_id = _resource_id(location_resource_name, "locations/")
                if candidate_id != normalized_location_id:
                    continue
                title = _normalized_str(raw_location.get("title")) or candidate_id
                address = format_storefront_address(raw_location.get("storefrontAddress"))
                return _GoogleBusinessProfileLocationContext(
                    location_id=candidate_id,
                    location_resource_name=location_resource_name,
                    account_id=account_id,
                    account_name=account_name,
                    title=title,
                    address=address,
                )
        raise GoogleBusinessProfileServiceError(
            "Google Business Profile location not found for this business.",
            status_code=404,
            error_code="not_found",
        )

    def _build_verification_workflow_status(
        self,
        *,
        business_id: str,
        context: _GoogleBusinessProfileLocationContext,
    ) -> GoogleBusinessProfileVerificationStatusResult:
        permission_error = False
        ambiguous_error = False
        voice_payload: dict[str, Any] | None = None
        verifications_payload: dict[str, Any] | None = None
        options_payload: dict[str, Any] | None = None

        try:
            voice_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token: self.client.get_voice_of_merchant_state(
                    access_token=access_token,
                    location_resource_name=context.location_resource_name,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            if exc.status_code == 404:
                voice_payload = None
            elif exc.is_permission_denied:
                permission_error = True
            else:
                ambiguous_error = True

        try:
            verifications_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token: self.client.list_verifications(
                    access_token=access_token,
                    location_resource_name=context.location_resource_name,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            if exc.status_code == 404:
                verifications_payload = None
            elif exc.is_permission_denied:
                permission_error = True
            else:
                ambiguous_error = True

        try:
            options_payload = self._call_google_api(
                business_id=business_id,
                callback=lambda access_token: self.client.fetch_verification_options(
                    access_token=access_token,
                    location_resource_name=context.location_resource_name,
                ),
                passthrough_api_errors=True,
            )
        except GoogleBusinessProfileAPIError as exc:
            if exc.status_code == 404:
                options_payload = None
            elif exc.is_permission_denied:
                permission_error = True
            else:
                ambiguous_error = True

        has_voice_of_merchant = extract_voice_of_merchant(voice_payload) if voice_payload is not None else None
        verifications = _normalize_verifications(verifications_payload)
        available_methods = _normalize_verification_method_options(
            options_payload,
            context=f"workflow_options location_id={context.location_id}",
        )
        current_verification = _current_verification_status(
            verifications,
            context=f"workflow_current_verification location_id={context.location_id}",
        )

        if permission_error:
            guidance = self._build_guidance(
                verification_state="unknown",
                action_required="resolve_access",
                current_verification=current_verification,
                available_methods=tuple(),
                reconnect_required=False,
                error_code="permission_denied",
            )
            return GoogleBusinessProfileVerificationStatusResult(
                location_id=context.location_id,
                verification_state="unknown",
                action_required="resolve_access",
                message="Google Business Profile access is denied for this location.",
                reconnect_required=False,
                current_verification=current_verification,
                available_methods=tuple(),
                guidance=guidance,
            )
        if ambiguous_error:
            guidance = self._build_guidance(
                verification_state="unknown",
                action_required="resolve_access",
                current_verification=current_verification,
                available_methods=available_methods,
                reconnect_required=False,
                error_code="provider_error",
            )
            return GoogleBusinessProfileVerificationStatusResult(
                location_id=context.location_id,
                verification_state="unknown",
                action_required="resolve_access",
                message="Google verification status is currently unavailable for this location.",
                reconnect_required=False,
                current_verification=current_verification,
                available_methods=available_methods,
                guidance=guidance,
            )

        verification_state = determine_workflow_state(
            has_voice_of_merchant=has_voice_of_merchant,
            provider_states=[entry.state for entry in verifications],
            has_verifications=bool(verifications),
            context=f"workflow_state location_id={context.location_id}",
        )
        action_required, message = determine_workflow_action(
            verification_state=verification_state,
            current_provider_method=(
                current_verification.provider_method if current_verification is not None else None
            ),
            has_available_methods=bool(available_methods),
        )
        guidance = self._build_guidance(
            verification_state=verification_state,
            action_required=action_required,
            current_verification=current_verification,
            available_methods=available_methods,
            reconnect_required=False,
            error_code=None,
        )
        return GoogleBusinessProfileVerificationStatusResult(
            location_id=context.location_id,
            verification_state=verification_state,
            action_required=action_required,
            message=message,
            reconnect_required=False,
            current_verification=current_verification,
            available_methods=available_methods,
            guidance=guidance,
        )

    def _choose_verification_option(
        self,
        *,
        options: Sequence[GoogleBusinessProfileVerificationMethodOptionResult],
        option_id: str | None,
        selected_method: VerificationMethod | None,
        provider_method: str | None,
        destination: str | None,
        fallback_to_first_single_option: bool,
        location_id: str,
    ) -> GoogleBusinessProfileVerificationMethodOptionResult | None:
        if not options:
            return None

        normalized_option_id = (option_id or "").strip()
        if normalized_option_id:
            for option in options:
                if option.option_id == normalized_option_id:
                    return option
            logger.warning(
                "gbp_verification_option_token_invalid location_id=%s option_id=%s available_option_count=%s",
                location_id,
                normalized_option_id,
                len(options),
            )
            record_gbp_verification_observation("option_token_invalid")

        normalized_provider_method = (provider_method or "").strip().upper()
        if normalized_provider_method:
            for option in options:
                if option.provider_method.upper() == normalized_provider_method:
                    return option
            logger.warning(
                "gbp_verification_provider_method_not_available location_id=%s provider_method=%s available_option_count=%s",
                location_id,
                normalized_provider_method,
                len(options),
            )
            record_gbp_verification_observation("option_provider_method_unavailable")

        normalized_destination = (destination or "").strip().lower()
        if selected_method is not None:
            candidates = [option for option in options if option.method == selected_method]
            if normalized_destination:
                for option in candidates:
                    if (option.destination or "").strip().lower() == normalized_destination:
                        return option
                logger.warning(
                    "gbp_verification_destination_not_available location_id=%s selected_method=%s destination=%s available_option_count=%s",
                    location_id,
                    selected_method,
                    normalized_destination,
                    len(candidates),
                )
                record_gbp_verification_observation("option_destination_unavailable")
            if candidates:
                return candidates[0]
            logger.warning(
                "gbp_verification_selected_method_not_available location_id=%s selected_method=%s available_option_count=%s",
                location_id,
                selected_method,
                len(options),
            )
            record_gbp_verification_observation("option_selected_method_unavailable")

        if (
            fallback_to_first_single_option
            and len(options) == 1
            and not normalized_option_id
            and not normalized_provider_method
            and selected_method is None
        ):
            return options[0]
        return None

    def _build_start_verification_payload(
        self,
        *,
        option: GoogleBusinessProfileVerificationMethodOptionResult,
        destination: str | None,
        language_code: str | None,
        mailer_contact: str | None,
        vetted_partner_token: str | None,
    ) -> dict[str, Any]:
        provider_method = option.provider_method.upper()
        payload: dict[str, Any] = {"method": provider_method}
        normalized_language_code = (language_code or "").strip()
        if normalized_language_code:
            payload["languageCode"] = normalized_language_code

        chosen_destination = (destination or "").strip()
        if not chosen_destination:
            chosen_destination = option.destination or ""

        if provider_method == "EMAIL" and chosen_destination:
            payload["emailAddress"] = chosen_destination
        elif provider_method in {"PHONE_CALL", "SMS"} and chosen_destination:
            payload["phoneNumber"] = chosen_destination
        elif provider_method in {"ADDRESS", "MAIL", "POSTCARD"}:
            normalized_mailer_contact = (mailer_contact or "").strip()
            if normalized_mailer_contact:
                payload["mailerContact"] = normalized_mailer_contact
        elif provider_method == "VETTED_PARTNER":
            normalized_partner_token = (vetted_partner_token or "").strip()
            if normalized_partner_token:
                payload["token"] = {"tokenString": normalized_partner_token}
        return payload

    def _resolve_verification_resource_name(
        self,
        *,
        location_resource_name: str,
        verification_id: str | None,
        current: GoogleBusinessProfileVerificationStatusCurrentResult | None,
    ) -> str | None:
        normalized_verification_id = (verification_id or "").strip()
        if normalized_verification_id:
            if normalized_verification_id.startswith("locations/"):
                return normalized_verification_id
            return f"{location_resource_name}/verifications/{normalized_verification_id}"

        if current is None:
            return None
        if current.verification_id.startswith("locations/"):
            return current.verification_id
        return f"{location_resource_name}/verifications/{current.verification_id}"

    def _build_guidance(
        self,
        *,
        verification_state: VerificationGuidanceState,
        action_required: VerificationActionRequired,
        current_verification: GoogleBusinessProfileVerificationStatusCurrentResult | None,
        available_methods: Sequence[GoogleBusinessProfileVerificationMethodOptionResult],
        reconnect_required: bool,
        error_code: VerificationErrorCode | None,
    ) -> VerificationGuidanceResult:
        guidance_methods = self._to_guidance_method_inputs(available_methods)
        guidance_error: VerificationGuidanceErrorCode | None = error_code
        return self.guidance_service.generate_guidance(
            verification_state=verification_state,
            action_required=action_required,
            available_methods=guidance_methods,
            reconnect_required=reconnect_required,
            error_code=guidance_error,
            current_method=(
                self._to_guidance_method(current_verification.method) if current_verification is not None else None
            ),
            code_required=(
                provider_method_requires_code(current_verification.provider_method)
                if current_verification is not None
                else None
            ),
        )

    def _to_guidance_method_inputs(
        self,
        available_methods: Sequence[GoogleBusinessProfileVerificationMethodOptionResult],
    ) -> tuple[VerificationGuidanceMethodOptionInput, ...]:
        return tuple(
            VerificationGuidanceMethodOptionInput(
                method=self._to_guidance_method(item.method),
                label=item.label,
                destination=item.destination,
                requires_code=item.requires_code,
                eligible=item.eligible,
            )
            for item in available_methods
        )

    def _to_guidance_method(self, method: VerificationMethod) -> Literal[
        "postcard",
        "phone",
        "sms",
        "email",
        "live_call",
        "video",
        "vetted_partner",
        "address",
        "other",
        "unknown",
    ]:
        return method

    def _map_provider_error(
        self,
        exc: GoogleBusinessProfileAPIError,
        *,
        action: Literal["start", "complete", "status", "options"],
    ) -> GoogleBusinessProfileServiceError:
        mapped = map_provider_api_error(
            action=action,
            status_code=exc.status_code,
            error_status=exc.error_status,
            message=str(exc),
            is_permission_denied=exc.is_permission_denied,
        )
        return GoogleBusinessProfileServiceError(
            mapped.message,
            status_code=mapped.status_code,
            error_code=mapped.error_code,
        )

    def _diagnostics_from_service_error(
        self,
        exc: GoogleBusinessProfileServiceError,
        *,
        accounts_count: int | None = None,
    ) -> GoogleBusinessProfileConnectionDiagnosticsResult:
        if exc.error_code == "insufficient_scope":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="missing_scope",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=False,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="missing_scope",
                gbp_next_action="Reconnect Google Profile to grant the required Business Profile scope.",
                gbp_provider_error_class="missing_required_scope",
                gbp_provider_http_status=exc.provider_http_status or 403,
                gbp_diagnostic_hint=exc.diagnostic_hint or "Reconnect with required scope and refresh status.",
            )
        if exc.error_code == "missing_required_scope":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="missing_scope",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=False,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="missing_scope",
                gbp_next_action="Reconnect Google Profile to grant the required Business Profile scope.",
                gbp_provider_error_class="missing_required_scope",
                gbp_provider_http_status=exc.provider_http_status or 403,
                gbp_diagnostic_hint=exc.diagnostic_hint or "Reconnect with required scope and refresh status.",
            )
        if exc.error_code in {"permission_denied", "provider_permission_denied"}:
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="permission_denied",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=True,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="permission_denied",
                gbp_next_action=(
                    "Google account is linked, but Business Profile API access is denied. "
                    "Confirm this connected account has Business Profile access."
                ),
                gbp_provider_error_class="provider_permission_denied",
                gbp_provider_http_status=exc.provider_http_status or 403,
                gbp_diagnostic_hint=exc.diagnostic_hint
                or "Verify Business Profile access for the connected Google identity.",
            )
        if exc.error_code == "provider_unauthorized":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="oauth_connected",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="provider_unauthorized",
                gbp_next_action="Google authorization is no longer valid. Reconnect Google Profile and refresh status.",
                gbp_provider_error_class="provider_unauthorized",
                gbp_provider_http_status=exc.provider_http_status or 401,
                gbp_diagnostic_hint=exc.diagnostic_hint or "Reconnect Google Profile for this business and retry.",
            )
        if exc.error_code == "provider_api_disabled_or_unavailable":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="unavailable",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="provider_api_disabled_or_unavailable",
                gbp_next_action=(
                    "Google account is linked, but Business Profile API access appears disabled or unavailable "
                    "for this OAuth project."
                ),
                gbp_provider_error_class="provider_api_disabled_or_unavailable",
                gbp_provider_http_status=exc.provider_http_status or 403,
                gbp_diagnostic_hint=exc.diagnostic_hint
                or "Check enabled APIs and project-level Business Profile API availability.",
            )
        if exc.error_code == "provider_rate_limited":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="unavailable",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="provider_rate_limited",
                gbp_next_action=(
                    "Business Profile API returned 429. Check API quota/access for the Google Cloud project "
                    "that owns the OAuth client."
                ),
                gbp_provider_error_class="provider_rate_limited",
                gbp_provider_http_status=exc.provider_http_status or 429,
                gbp_diagnostic_hint=exc.diagnostic_hint
                or (
                    "Business Profile API returned 429. Check API quota/access for the Google Cloud project "
                    "that owns the OAuth client, especially My Business Account Management and Business "
                    "Information APIs."
                ),
            )
        if exc.error_code == "provider_quota_or_access_not_granted":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="unavailable",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="provider_quota_or_access_not_granted",
                gbp_next_action=(
                    "Google account is linked, but Business Profile API quota or project access is not granted."
                ),
                gbp_provider_error_class="provider_quota_or_access_not_granted",
                gbp_provider_http_status=exc.provider_http_status or 403,
                gbp_diagnostic_hint=exc.diagnostic_hint
                or (
                    "Check API quota/access for the Google Cloud project that owns the OAuth client "
                    "(My Business Account Management and Business Information APIs). If quota is blank/"
                    "unavailable, request Business Profile API access/allowlist first. After approval, "
                    "request a quota increase."
                ),
            )
        if exc.error_code == "provider_not_found":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="unavailable",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="provider_not_found",
                gbp_next_action="Business Profile API returned not found for this request. Refresh and retry.",
                gbp_provider_error_class="provider_not_found",
                gbp_provider_http_status=exc.provider_http_status or 404,
                gbp_diagnostic_hint=exc.diagnostic_hint or "Verify account/location resources returned by Google APIs.",
            )
        if exc.error_code == "token_refresh_failed":
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="oauth_connected",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="token_refresh_failed",
                gbp_next_action="Google token refresh failed. Reconnect Google Profile and retry.",
                gbp_provider_error_class="token_refresh_failed",
                gbp_provider_http_status=exc.provider_http_status,
                gbp_diagnostic_hint=exc.diagnostic_hint or "Reconnect Google Profile to issue a fresh token.",
            )
        if exc.error_code == "reconnect_required":
            if exc.provider_error_class == "token_refresh_failed":
                return GoogleBusinessProfileConnectionDiagnosticsResult(
                    gbp_connection_state="oauth_connected",
                    gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                    gbp_required_scope_granted=None,
                    gbp_accounts_count=accounts_count,
                    gbp_locations_count=None,
                    gbp_selected_location_present=None,
                    gbp_status_reason="token_refresh_failed",
                    gbp_next_action="Google token refresh failed. Reconnect Google Profile and retry.",
                    gbp_provider_error_class="token_refresh_failed",
                    gbp_provider_http_status=exc.provider_http_status or 401,
                    gbp_diagnostic_hint=exc.diagnostic_hint or "Reconnect Google Profile to issue a fresh token.",
                )
            return GoogleBusinessProfileConnectionDiagnosticsResult(
                gbp_connection_state="oauth_connected",
                gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
                gbp_required_scope_granted=None,
                gbp_accounts_count=accounts_count,
                gbp_locations_count=None,
                gbp_selected_location_present=None,
                gbp_status_reason="oauth_connected_reconnect_required",
                gbp_next_action="Reconnect Google Profile before loading Business Profile accounts.",
                gbp_provider_error_class="none",
                gbp_provider_http_status=exc.provider_http_status,
                gbp_diagnostic_hint=exc.diagnostic_hint or "Reconnect and refresh before retrying account discovery.",
            )
        return GoogleBusinessProfileConnectionDiagnosticsResult(
            gbp_connection_state="unavailable",
            gbp_required_scope=self.connection_service.BUSINESS_PROFILE_SCOPE,
            gbp_required_scope_granted=None,
            gbp_accounts_count=accounts_count,
            gbp_locations_count=None,
            gbp_selected_location_present=None,
            gbp_status_reason="provider_unavailable",
            gbp_next_action="Google Business Profile status is temporarily unavailable. Refresh and retry.",
            gbp_provider_error_class=(
                exc.provider_error_class
                if exc.provider_error_class
                in {
                    "provider_rate_limited",
                    "provider_unavailable",
                    "provider_unknown",
                }
                else "provider_unavailable"
            ),
            gbp_provider_http_status=exc.provider_http_status,
            gbp_diagnostic_hint=exc.diagnostic_hint
            or "Retry shortly. If this persists, verify Google API availability.",
        )

    def _log_connection_diagnostics(
        self,
        *,
        business_id: str,
        diagnostics: GoogleBusinessProfileConnectionDiagnosticsResult,
    ) -> None:
        logger.info(
            "google_business_profile_status_checked business_id=%s status=%s reason=%s provider_error_class=%s provider_http_status=%s required_scope=%s required_scope_granted=%s accounts_count=%s locations_count=%s selected_location_present=%s",
            business_id,
            diagnostics.gbp_connection_state,
            diagnostics.gbp_status_reason,
            diagnostics.gbp_provider_error_class,
            diagnostics.gbp_provider_http_status,
            diagnostics.gbp_required_scope,
            diagnostics.gbp_required_scope_granted,
            diagnostics.gbp_accounts_count,
            diagnostics.gbp_locations_count,
            diagnostics.gbp_selected_location_present,
        )

    def _classify_provider_api_error(
        self,
        exc: GoogleBusinessProfileAPIError,
    ) -> tuple[GoogleBusinessProfileProviderErrorClass, int | None, str]:
        status_code = exc.status_code if isinstance(exc.status_code, int) else None
        normalized_status = (exc.error_status or "").strip().upper()
        normalized_reason = (exc.error_reason or "").strip().lower()
        message_lower = str(exc).lower()

        if status_code == 401 or normalized_status == "UNAUTHENTICATED":
            return (
                "provider_unauthorized",
                status_code or 401,
                "Google authorization appears expired or invalid. Reconnect Google Profile.",
            )

        if status_code == 404 or normalized_status == "NOT_FOUND":
            return (
                "provider_not_found",
                status_code or 404,
                "Google Business Profile API returned not found. Refresh and retry.",
            )

        if status_code == 403:
            missing_scope_markers = (
                "insufficientauthenticationscopes",
                "insufficient_scope",
                "insufficient scope",
                "insufficient authentication scopes",
                "request had insufficient authentication scopes",
            )
            api_disabled_markers = (
                "service_disabled",
                "accessnotconfigured",
                "api_not_enabled",
                "api_disabled",
                "servicenotenabled",
                "api has not been used",
                "has not been used in project",
                "access not configured",
                "is not enabled",
                "service is disabled",
            )
            quota_or_access_markers = (
                "quotaexceeded",
                "ratelimitexceeded",
                "dailylimitexceeded",
                "resource_exhausted",
                "billingdisabled",
                "project_denied",
                "access not granted",
                "access has not been granted",
                "not approved",
                "quota",
                "rate limit",
            )

            if self._text_contains_any(normalized_reason, missing_scope_markers) or self._text_contains_any(
                message_lower,
                missing_scope_markers,
            ):
                return (
                    "missing_required_scope",
                    403,
                    "Reconnect Google Profile to grant the required Business Profile scope.",
                )

            if self._text_contains_any(normalized_reason, api_disabled_markers) or self._text_contains_any(
                message_lower,
                api_disabled_markers,
            ):
                return (
                    "provider_api_disabled_or_unavailable",
                    403,
                    "Business Profile API appears disabled or unavailable for this OAuth project.",
                )

            if self._text_contains_any(normalized_reason, quota_or_access_markers) or self._text_contains_any(
                message_lower,
                quota_or_access_markers,
            ):
                return (
                    "provider_quota_or_access_not_granted",
                    403,
                    (
                        "Business Profile API quota or project access is not granted. Check API quota/access "
                        "for the Google Cloud project that owns the OAuth client (My Business Account Management "
                        "and Business Information APIs). If quota is blank/unavailable, request Business Profile "
                        "API access/allowlist first. After approval, request a quota increase."
                    ),
                )

            return (
                "provider_permission_denied",
                403,
                "Connected identity does not have Business Profile API permission for this request.",
            )

        if status_code == 429:
            rate_limited_markers = (
                "ratelimitexceeded",
                "userratelimitexceeded",
                "resource_exhausted",
                "too many requests",
                "too_many_requests",
                "rate limit",
                "rate_limit",
            )
            quota_or_access_markers = (
                "quotaexceeded",
                "dailylimitexceeded",
                "billingdisabled",
                "project_denied",
                "quota unavailable",
                "quota is 0",
                "quota has been exhausted",
                "access not granted",
                "access has not been granted",
                "not approved",
                "api access not configured",
                "api access is not configured",
                "quota",
            )

            if self._text_contains_any(normalized_reason, quota_or_access_markers) or self._text_contains_any(
                message_lower,
                quota_or_access_markers,
            ):
                return (
                    "provider_quota_or_access_not_granted",
                    429,
                    (
                        "Business Profile API returned 429. Check API quota/access for the Google Cloud project "
                        "that owns the OAuth client (My Business Account Management and Business Information APIs). "
                        "If quota is blank/unavailable, request Business Profile API access/allowlist first. "
                        "After approval, request a quota increase."
                    ),
                )
            if (
                normalized_status == "RESOURCE_EXHAUSTED"
                or self._text_contains_any(normalized_reason, rate_limited_markers)
                or self._text_contains_any(message_lower, rate_limited_markers)
            ):
                return (
                    "provider_rate_limited",
                    429,
                    (
                        "Business Profile API returned 429. Check API quota/access for the Google Cloud project "
                        "that owns the OAuth client, especially My Business Account Management and Business "
                        "Information APIs."
                    ),
                )
            return (
                "provider_rate_limited",
                429,
                (
                    "Business Profile API returned 429. Check API quota/access for the Google Cloud project "
                    "that owns the OAuth client, especially My Business Account Management and Business "
                    "Information APIs."
                ),
            )

        if status_code in {500, 502, 503, 504}:
            return (
                "provider_unavailable",
                status_code,
                "Google Business Profile API is temporarily unavailable. Retry shortly.",
            )

        if exc.is_permission_denied:
            return (
                "provider_permission_denied",
                status_code,
                "Connected identity does not have Business Profile API permission for this request.",
            )

        return (
            "provider_unknown",
            status_code,
            "Google Business Profile API request failed for an unknown reason. Refresh and retry.",
        )

    @staticmethod
    def _text_contains_any(value: str, candidates: tuple[str, ...]) -> bool:
        return any(candidate in value for candidate in candidates)

    def _call_google_api(
        self,
        *,
        business_id: str,
        callback: Callable[[str], dict[str, Any]],
        passthrough_api_errors: bool = False,
    ) -> dict[str, Any]:
        token_result = self.connection_service.get_access_token_for_use(
            business_id=business_id,
            required_scopes=(self.connection_service.BUSINESS_PROFILE_SCOPE,),
        )
        if not token_result.connected:
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile is not connected for this business.",
                status_code=409,
                reconnect_required=True,
                error_code="reconnect_required",
                provider_error_class="none",
                provider_http_status=None,
                diagnostic_hint="Connect Google Profile for this business before loading status.",
            )
        if not token_result.required_scopes_satisfied or token_result.token_status == "insufficient_scope":
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile scope is missing. Reconnect Google to grant required scopes.",
                status_code=403,
                reconnect_required=True,
                error_code="insufficient_scope",
                provider_error_class="missing_required_scope",
                provider_http_status=403,
                diagnostic_hint="Reconnect Google Profile with the required Business Profile scope.",
            )
        if token_result.reconnect_required or token_result.token_status == "reconnect_required":
            token_refresh_failed = (
                token_result.connected and token_result.required_scopes_satisfied and token_result.refresh_token_present
            )
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile connection requires reconnect.",
                status_code=409,
                reconnect_required=True,
                error_code="reconnect_required",
                provider_error_class="token_refresh_failed" if token_refresh_failed else "none",
                provider_http_status=401 if token_refresh_failed else None,
                diagnostic_hint=(
                    "Google token refresh failed. Reconnect Google Profile to continue."
                    if token_refresh_failed
                    else "Reconnect Google Profile before retrying."
                ),
            )
        access_token = (token_result.access_token or "").strip()
        if not access_token:
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile connection requires reconnect.",
                status_code=409,
                reconnect_required=True,
                error_code="reconnect_required",
                provider_error_class="none",
                provider_http_status=None,
                diagnostic_hint="Reconnect Google Profile before retrying.",
            )
        try:
            return callback(access_token)
        except GoogleBusinessProfileAPIError as exc:
            if passthrough_api_errors:
                raise
            provider_error_class, provider_http_status, diagnostic_hint = self._classify_provider_api_error(exc)
            if provider_error_class == "missing_required_scope":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile scope is missing. Reconnect Google to grant required scopes.",
                    status_code=403,
                    reconnect_required=True,
                    error_code="missing_required_scope",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            if provider_error_class == "provider_unauthorized":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile authorization is no longer valid.",
                    status_code=401,
                    reconnect_required=True,
                    error_code="provider_unauthorized",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            if provider_error_class == "provider_api_disabled_or_unavailable":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile API appears disabled or unavailable for this OAuth project.",
                    status_code=403,
                    error_code="provider_api_disabled_or_unavailable",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            if provider_error_class == "provider_rate_limited":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile API returned 429 rate limit/resource exhaustion.",
                    status_code=429,
                    error_code="provider_rate_limited",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            if provider_error_class == "provider_quota_or_access_not_granted":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile API quota or project access is not granted.",
                    status_code=429 if provider_http_status == 429 else 403,
                    error_code="provider_quota_or_access_not_granted",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            if provider_error_class == "provider_permission_denied":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile access is denied for this Google account.",
                    status_code=403,
                    error_code="provider_permission_denied",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            if provider_error_class == "provider_not_found":
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile resource was not found.",
                    status_code=404,
                    error_code="provider_not_found",
                    provider_error_class=provider_error_class,
                    provider_http_status=provider_http_status,
                    diagnostic_hint=diagnostic_hint,
                ) from exc
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile API request failed.",
                status_code=502,
                error_code="provider_error",
                provider_error_class=provider_error_class,
                provider_http_status=provider_http_status,
                diagnostic_hint=diagnostic_hint,
            ) from exc


def _extract_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = payload.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _normalized_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _resource_id(resource_name: str, prefix: str) -> str:
    normalized = _normalized_str(resource_name)
    if normalized.startswith(prefix):
        return normalized[len(prefix) :].strip()
    return normalized


def _normalize_verifications(payload: dict[str, Any] | None) -> list[GoogleBusinessProfileVerificationRecordResult]:
    if not payload:
        return []
    raw_items = _extract_list(payload, "verifications")
    normalized: list[GoogleBusinessProfileVerificationRecordResult] = []
    for item in raw_items:
        normalized.append(
            GoogleBusinessProfileVerificationRecordResult(
                name=_none_if_empty(item.get("name")),
                method=_none_if_empty(item.get("method") or item.get("verificationMethod")),
                state=_none_if_empty(item.get("state") or item.get("verificationState")),
                create_time=_none_if_empty(item.get("createTime") or item.get("createdTime")),
                complete_time=_none_if_empty(item.get("completeTime") or item.get("completedTime")),
                expires_at=_none_if_empty(item.get("expireTime") or item.get("expirationTime")),
            )
        )
    return normalized


def _normalize_verification_methods(
    payload: dict[str, Any] | None,
    *,
    context: str,
) -> list[str]:
    if not payload:
        return []
    options = _extract_list(payload, "verificationOptions")
    methods: list[str] = []
    for option in options:
        method, provider_method = normalize_provider_method(
            option.get("method") or option.get("verificationMethod"),
            context=context,
        )
        if provider_method == "UNKNOWN":
            continue
        normalized = method
        if normalized not in methods:
            methods.append(normalized)
    return methods


def _normalize_single_verification_record(
    payload: dict[str, Any] | None,
    *,
    context: str,
) -> GoogleBusinessProfileVerificationRecordResult | None:
    if not payload:
        return None
    name = _none_if_empty(payload.get("name"))
    method = _none_if_empty(payload.get("method") or payload.get("verificationMethod"))
    state = _none_if_empty(payload.get("state") or payload.get("verificationState"))
    if not any((name, method, state)):
        logger.warning("gbp_verification_record_missing_expected_fields context=%s", context)
        record_gbp_verification_observation("verification_record_missing_fields")
        return None
    return GoogleBusinessProfileVerificationRecordResult(
        name=name,
        method=method,
        state=state,
        create_time=_none_if_empty(payload.get("createTime") or payload.get("createdTime")),
        complete_time=_none_if_empty(payload.get("completeTime") or payload.get("completedTime")),
        expires_at=_none_if_empty(payload.get("expireTime") or payload.get("expirationTime")),
    )


def _normalize_verification_method_options(
    payload: dict[str, Any] | None,
    *,
    context: str,
) -> tuple[GoogleBusinessProfileVerificationMethodOptionResult, ...]:
    if not payload:
        return tuple()
    options = _extract_list(payload, "verificationOptions")
    normalized: list[GoogleBusinessProfileVerificationMethodOptionResult] = []
    for option in options:
        method, provider_method = normalize_provider_method(
            option.get("method") or option.get("verificationMethod"),
            context=context,
        )
        if provider_method == "UNKNOWN":
            continue
        label = verification_method_label(method)
        destination = extract_verification_option_destination(option)
        requires_code = provider_method_requires_code(provider_method)
        option_id = build_method_option_token(
            provider_method=provider_method,
            destination=destination,
            requires_code=requires_code,
            language_code=_none_if_empty(option.get("languageCode")),
        )
        description = destination if destination else f"Use {label.lower()} verification."
        normalized.append(
            GoogleBusinessProfileVerificationMethodOptionResult(
                option_id=option_id,
                method=method,
                provider_method=provider_method,
                label=label,
                description=description,
                destination=destination,
                requires_code=requires_code,
                eligible=True,
            )
        )
    return tuple(normalized)


def _current_verification_status(
    verifications: Sequence[GoogleBusinessProfileVerificationRecordResult],
    *,
    context: str,
) -> GoogleBusinessProfileVerificationStatusCurrentResult | None:
    if not verifications:
        return None
    current = verifications[0]
    method, provider_method = normalize_provider_method(current.method, context=context)
    return GoogleBusinessProfileVerificationStatusCurrentResult(
        verification_id=_verification_id_from_resource_name(current.name),
        provider_state=current.state,
        method=method,
        provider_method=provider_method,
        create_time=current.create_time,
        complete_time=current.complete_time,
        expires_at=current.expires_at,
    )


def _verification_id_from_resource_name(resource_name: str | None) -> str:
    normalized = _normalized_str(resource_name)
    if not normalized:
        return ""
    marker = "/verifications/"
    if marker in normalized:
        return normalized.split(marker, 1)[1].strip()
    return normalized


def _none_if_empty(value: Any) -> str | None:
    normalized = _normalized_str(value)
    return normalized or None

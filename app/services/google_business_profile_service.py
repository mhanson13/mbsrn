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
        error_code: VerificationErrorCode = "provider_error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reconnect_required = reconnect_required
        self.error_code = error_code


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
                self._to_guidance_method(current_verification.method)
                if current_verification is not None
                else None
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
            )
        if not token_result.required_scopes_satisfied or token_result.token_status == "insufficient_scope":
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile scope is missing. Reconnect Google to grant required scopes.",
                status_code=403,
                reconnect_required=True,
                error_code="insufficient_scope",
            )
        if token_result.reconnect_required or token_result.token_status == "reconnect_required":
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile connection requires reconnect.",
                status_code=409,
                reconnect_required=True,
                error_code="reconnect_required",
            )
        access_token = (token_result.access_token or "").strip()
        if not access_token:
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile connection requires reconnect.",
                status_code=409,
                reconnect_required=True,
                error_code="reconnect_required",
            )
        try:
            return callback(access_token)
        except GoogleBusinessProfileAPIError as exc:
            if passthrough_api_errors:
                raise
            if exc.is_permission_denied:
                raise GoogleBusinessProfileServiceError(
                    "Google Business Profile access is denied for this Google account.",
                    status_code=403,
                    error_code="permission_denied",
                ) from exc
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile API request failed.",
                status_code=502,
                error_code="provider_error",
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

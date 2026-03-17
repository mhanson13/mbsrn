from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.integrations.google_business_profile import GoogleBusinessProfileAPIError, GoogleBusinessProfileClient
from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionService,
)

VerificationStateSummary = Literal["verified", "unverified", "pending", "unknown"]
VerificationNextAction = Literal["none", "start_verification", "complete_pending", "resolve_access", "reconnect_google"]


class GoogleBusinessProfileServiceError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        reconnect_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reconnect_required = reconnect_required


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationRecordResult:
    name: str | None
    method: str | None
    state: str | None
    create_time: str | None
    complete_time: str | None


@dataclass(frozen=True)
class GoogleBusinessProfileVerificationResult:
    has_voice_of_merchant: bool | None
    state_summary: VerificationStateSummary
    verification_methods: tuple[str, ...]
    verifications: tuple[GoogleBusinessProfileVerificationRecordResult, ...]
    recommended_next_action: VerificationNextAction


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


class GoogleBusinessProfileService:
    def __init__(
        self,
        *,
        connection_service: GoogleBusinessProfileConnectionService,
        client: GoogleBusinessProfileClient,
    ) -> None:
        self.connection_service = connection_service
        self.client = client

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
            )

        locations = self.list_locations(business_id=business_id)
        for location in locations.locations:
            if location.location_id == normalized_location_id:
                return location.verification
        raise GoogleBusinessProfileServiceError(
            "Google Business Profile location not found for this business.",
            status_code=404,
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
        address = _format_storefront_address(raw_location.get("storefrontAddress"))
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

        has_voice_of_merchant = _extract_voice_of_merchant(voice_payload) if voice_payload is not None else None
        verifications = _normalize_verifications(verifications_payload)
        verification_methods = _normalize_verification_methods(verification_options_payload)

        if permission_error:
            state_summary: VerificationStateSummary = "unknown"
            recommended_next_action: VerificationNextAction = "resolve_access"
        elif ambiguous_error:
            state_summary = "unknown"
            recommended_next_action = "resolve_access"
        else:
            state_summary = _determine_state_summary(
                has_voice_of_merchant=has_voice_of_merchant,
                verifications=verifications,
            )
            recommended_next_action = _determine_next_action(state_summary)

        return GoogleBusinessProfileVerificationResult(
            has_voice_of_merchant=has_voice_of_merchant,
            state_summary=state_summary,
            verification_methods=tuple(verification_methods),
            verifications=tuple(verifications),
            recommended_next_action=recommended_next_action,
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
            )
        if not token_result.required_scopes_satisfied or token_result.token_status == "insufficient_scope":
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile scope is missing. Reconnect Google to grant required scopes.",
                status_code=403,
                reconnect_required=True,
            )
        if token_result.reconnect_required or token_result.token_status == "reconnect_required":
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile connection requires reconnect.",
                status_code=409,
                reconnect_required=True,
            )
        access_token = (token_result.access_token or "").strip()
        if not access_token:
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile connection requires reconnect.",
                status_code=409,
                reconnect_required=True,
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
                ) from exc
            raise GoogleBusinessProfileServiceError(
                "Google Business Profile API request failed.",
                status_code=502,
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


def _format_storefront_address(raw_address: Any) -> str | None:
    if not isinstance(raw_address, dict):
        return None
    parts: list[str] = []
    address_lines = raw_address.get("addressLines")
    if isinstance(address_lines, list):
        parts.extend(str(item).strip() for item in address_lines if str(item).strip())
    for field in ("locality", "administrativeArea", "postalCode", "regionCode"):
        value = _normalized_str(raw_address.get(field))
        if value:
            parts.append(value)
    if not parts:
        return None
    unique_parts: list[str] = []
    for part in parts:
        if part not in unique_parts:
            unique_parts.append(part)
    return ", ".join(unique_parts)


def _extract_voice_of_merchant(payload: dict[str, Any]) -> bool | None:
    explicit_bool = payload.get("hasVoiceOfMerchant")
    if isinstance(explicit_bool, bool):
        return explicit_bool
    for candidate in (
        payload.get("voiceOfMerchantState"),
        payload.get("state"),
        payload.get("verificationState"),
    ):
        normalized = _normalized_str(candidate).lower()
        if not normalized:
            continue
        if "voice_of_merchant" in normalized or "verified" in normalized:
            return True
        if normalized in {"not_verified", "false"}:
            return False
    return None


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
            )
        )
    return normalized


def _normalize_verification_methods(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return []
    options = _extract_list(payload, "verificationOptions")
    methods: list[str] = []
    for option in options:
        raw_method = _normalized_str(option.get("method") or option.get("verificationMethod"))
        if not raw_method:
            continue
        normalized = raw_method.lower()
        if normalized not in methods:
            methods.append(normalized)
    return methods


def _determine_state_summary(
    *,
    has_voice_of_merchant: bool | None,
    verifications: list[GoogleBusinessProfileVerificationRecordResult],
) -> VerificationStateSummary:
    if has_voice_of_merchant is True:
        return "verified"
    states = [(_normalized_str(entry.state)).lower() for entry in verifications if _normalized_str(entry.state)]
    if any(_is_pending_state(state) for state in states):
        return "pending"
    if any(_is_verified_state(state) for state in states):
        return "verified"
    if not verifications:
        return "unverified"
    if states and all(_is_unverified_state(state) for state in states):
        return "unverified"
    return "unknown"


def _determine_next_action(state_summary: VerificationStateSummary) -> VerificationNextAction:
    if state_summary == "verified":
        return "none"
    if state_summary == "pending":
        return "complete_pending"
    if state_summary == "unverified":
        return "start_verification"
    return "resolve_access"


def _is_pending_state(state: str) -> bool:
    return any(
        marker in state
        for marker in (
            "pending",
            "in_progress",
            "inprogress",
            "processing",
            "in_review",
            "requested",
        )
    )


def _is_verified_state(state: str) -> bool:
    return any(
        marker in state
        for marker in (
            "verified",
            "success",
            "complete",
            "completed",
            "approved",
            "voice_of_merchant",
        )
    )


def _is_unverified_state(state: str) -> bool:
    return any(
        marker in state
        for marker in (
            "failed",
            "failure",
            "unverified",
            "rejected",
            "expired",
            "cancelled",
            "denied",
            "not_verified",
        )
    )


def _none_if_empty(value: Any) -> str | None:
    normalized = _normalized_str(value)
    return normalized or None


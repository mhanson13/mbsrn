from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GoogleBusinessProfileAPIError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_status = error_status

    @property
    def is_permission_denied(self) -> bool:
        return self.status_code in {401, 403} or (self.error_status or "").upper() in {
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
        }


@dataclass(frozen=True)
class _GoogleErrorDetail:
    message: str
    status_code: int | None
    error_status: str | None


class GoogleBusinessProfileClient:
    def __init__(
        self,
        *,
        account_api_base_url: str = "https://mybusinessaccountmanagement.googleapis.com",
        business_information_api_base_url: str = "https://mybusinessbusinessinformation.googleapis.com",
        verifications_api_base_url: str = "https://mybusinessverifications.googleapis.com",
        timeout_seconds: int = 10,
    ) -> None:
        self.account_api_base_url = account_api_base_url.rstrip("/")
        self.business_information_api_base_url = business_information_api_base_url.rstrip("/")
        self.verifications_api_base_url = verifications_api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def list_accounts(self, *, access_token: str) -> dict[str, Any]:
        return self._request_json(
            method="GET",
            url=f"{self.account_api_base_url}/v1/accounts",
            access_token=access_token,
        )

    def list_locations(self, *, access_token: str, account_resource_name: str) -> dict[str, Any]:
        normalized_account = _normalize_resource_name(account_resource_name, "accounts/")
        encoded_account = quote(normalized_account, safe="/")
        return self._request_json(
            method="GET",
            url=f"{self.business_information_api_base_url}/v1/{encoded_account}/locations",
            access_token=access_token,
        )

    def get_voice_of_merchant_state(self, *, access_token: str, location_resource_name: str) -> dict[str, Any]:
        normalized_location = _normalize_resource_name(location_resource_name, "locations/")
        encoded_location = quote(normalized_location, safe="/")
        return self._request_json(
            method="GET",
            url=f"{self.verifications_api_base_url}/v1/{encoded_location}/VoiceOfMerchantState",
            access_token=access_token,
        )

    def list_verifications(self, *, access_token: str, location_resource_name: str) -> dict[str, Any]:
        normalized_location = _normalize_resource_name(location_resource_name, "locations/")
        encoded_location = quote(normalized_location, safe="/")
        return self._request_json(
            method="GET",
            url=f"{self.verifications_api_base_url}/v1/{encoded_location}/verifications",
            access_token=access_token,
        )

    def fetch_verification_options(self, *, access_token: str, location_resource_name: str) -> dict[str, Any]:
        normalized_location = _normalize_resource_name(location_resource_name, "locations/")
        encoded_location = quote(normalized_location, safe="/")
        return self._request_json(
            method="POST",
            url=f"{self.verifications_api_base_url}/v1/{encoded_location}:fetchVerificationOptions",
            access_token=access_token,
            body={},
        )

    def start_verification(
        self,
        *,
        access_token: str,
        location_resource_name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_location = _normalize_resource_name(location_resource_name, "locations/")
        encoded_location = quote(normalized_location, safe="/")
        return self._request_json(
            method="POST",
            url=f"{self.verifications_api_base_url}/v1/{encoded_location}:verify",
            access_token=access_token,
            body=body,
        )

    def complete_verification(
        self,
        *,
        access_token: str,
        verification_resource_name: str,
        pin: str,
    ) -> dict[str, Any]:
        normalized_verification = _normalize_resource_name(verification_resource_name, "locations/")
        encoded_verification = quote(normalized_verification, safe="/")
        return self._request_json(
            method="POST",
            url=f"{self.verifications_api_base_url}/v1/{encoded_verification}:complete",
            access_token=access_token,
            body={"pin": pin},
        )

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        access_token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_token = access_token.strip()
        if not normalized_token:
            raise GoogleBusinessProfileAPIError("Google access token is required.")

        payload: bytes | None = None
        headers = {
            "Authorization": f"Bearer {normalized_token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")

        request = Request(
            url=url,
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _extract_error_detail(exc)
            raise GoogleBusinessProfileAPIError(
                f"Google Business Profile request failed: {detail.message}",
                status_code=detail.status_code,
                error_status=detail.error_status,
            ) from exc
        except URLError as exc:
            raise GoogleBusinessProfileAPIError(f"Google Business Profile endpoint unavailable: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise GoogleBusinessProfileAPIError("Google Business Profile request failed.") from exc

        if not raw.strip():
            return {}
        try:
            payload_obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleBusinessProfileAPIError("Google Business Profile response is not valid JSON.") from exc
        if not isinstance(payload_obj, dict):
            raise GoogleBusinessProfileAPIError("Google Business Profile response payload is invalid.")
        return payload_obj


def _normalize_resource_name(value: str, prefix: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise GoogleBusinessProfileAPIError(f"Google resource name with prefix '{prefix}' is required.")
    if normalized.startswith(prefix):
        return normalized
    return f"{prefix}{normalized}"


def _extract_error_detail(exc: HTTPError) -> _GoogleErrorDetail:
    status_code = exc.code if isinstance(exc.code, int) else None
    message = str(exc.reason or "request failed")
    error_status: str | None = None
    try:
        if exc.fp is None:
            return _GoogleErrorDetail(message=message, status_code=status_code, error_status=error_status)
        body = exc.fp.read().decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return _GoogleErrorDetail(message=message, status_code=status_code, error_status=error_status)

    if not body.strip():
        return _GoogleErrorDetail(message=message, status_code=status_code, error_status=error_status)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _GoogleErrorDetail(message=body.strip()[:256], status_code=status_code, error_status=error_status)
    if not isinstance(payload, dict):
        return _GoogleErrorDetail(message=message, status_code=status_code, error_status=error_status)

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        code = error_payload.get("code")
        if isinstance(code, int):
            status_code = code
        parsed_message = str(error_payload.get("message") or "").strip()
        if parsed_message:
            message = parsed_message
        parsed_status = str(error_payload.get("status") or "").strip()
        if parsed_status:
            error_status = parsed_status
    else:
        parsed_message = str(payload.get("error_description") or payload.get("message") or "").strip()
        if parsed_message:
            message = parsed_message
    return _GoogleErrorDetail(message=message, status_code=status_code, error_status=error_status)

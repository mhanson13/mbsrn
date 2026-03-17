from __future__ import annotations

from typing import Any

from app.integrations.google_business_profile import GoogleBusinessProfileClient


class _CaptureGoogleBusinessProfileClient(GoogleBusinessProfileClient):
    def __init__(self) -> None:
        super().__init__(
            account_api_base_url="https://accounts.example",
            business_information_api_base_url="https://business.example",
            verifications_api_base_url="https://verifications.example",
            timeout_seconds=5,
        )
        self.last_call: dict[str, Any] | None = None

    def _request_json(  # type: ignore[override]
        self,
        *,
        method: str,
        url: str,
        access_token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_call = {
            "method": method,
            "url": url,
            "access_token": access_token,
            "body": body,
        }
        return {}


def test_start_verification_uses_verify_endpoint_and_request_body() -> None:
    client = _CaptureGoogleBusinessProfileClient()
    payload = {"method": "EMAIL", "emailAddress": "owner@example.com"}

    client.start_verification(
        access_token="token-value",
        location_resource_name="locations/location-1",
        body=payload,
    )

    assert client.last_call is not None
    assert client.last_call["method"] == "POST"
    assert client.last_call["url"] == "https://verifications.example/v1/locations/location-1:verify"
    assert client.last_call["body"] == payload


def test_complete_verification_uses_complete_endpoint_and_pin_body() -> None:
    client = _CaptureGoogleBusinessProfileClient()

    client.complete_verification(
        access_token="token-value",
        verification_resource_name="locations/location-1/verifications/attempt-1",
        pin="123456",
    )

    assert client.last_call is not None
    assert client.last_call["method"] == "POST"
    assert (
        client.last_call["url"]
        == "https://verifications.example/v1/locations/location-1/verifications/attempt-1:complete"
    )
    assert client.last_call["body"] == {"pin": "123456"}


def test_verification_methods_accept_short_resource_ids() -> None:
    client = _CaptureGoogleBusinessProfileClient()

    client.start_verification(
        access_token="token-value",
        location_resource_name="location-2",
        body={"method": "SMS"},
    )
    assert client.last_call is not None
    assert client.last_call["url"] == "https://verifications.example/v1/locations/location-2:verify"

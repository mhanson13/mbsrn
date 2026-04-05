from __future__ import annotations

import sys
import types

import pytest

from app.integrations.search_console_analytics_provider import (
    GoogleSearchConsoleAPIClient,
    SearchConsoleAnalyticsProviderConfigurationError,
    _classify_search_console_http_error,
)


def _install_fake_google_auth_modules(monkeypatch: pytest.MonkeyPatch, *, adc_calls: dict[str, bool]) -> None:
    class _FakeCredentials:
        def __init__(self) -> None:
            self.valid = True
            self.token = "fake-token"

        def refresh(self, request: object) -> None:
            del request
            self.valid = True

    class _FakeServiceAccountCredentials:
        @staticmethod
        def from_service_account_info(info: dict[str, object], scopes: list[str] | None = None) -> _FakeCredentials:
            del info, scopes
            adc_calls["service_account"] = True
            return _FakeCredentials()

    def _fake_google_auth_default(*, scopes: list[str] | None = None) -> tuple[_FakeCredentials, str]:
        del scopes
        adc_calls["adc"] = True
        return _FakeCredentials(), "test-project"

    class _FakeAuthRequest:
        pass

    google_module = types.ModuleType("google")
    google_auth_module = types.ModuleType("google.auth")
    google_auth_module.default = _fake_google_auth_default
    google_auth_transport_module = types.ModuleType("google.auth.transport")
    google_auth_transport_requests_module = types.ModuleType("google.auth.transport.requests")
    google_auth_transport_requests_module.Request = _FakeAuthRequest
    google_oauth2_module = types.ModuleType("google.oauth2")
    google_oauth2_module.service_account = types.SimpleNamespace(Credentials=_FakeServiceAccountCredentials)

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.auth", google_auth_module)
    monkeypatch.setitem(sys.modules, "google.auth.transport", google_auth_transport_module)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", google_auth_transport_requests_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", google_oauth2_module)


def test_google_search_console_client_uses_adc_when_credentials_json_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"adc": False, "service_account": False}
    _install_fake_google_auth_modules(monkeypatch, adc_calls=calls)
    client = GoogleSearchConsoleAPIClient(credentials_json=None)

    credentials = client._get_credentials()

    assert credentials is not None
    assert calls["adc"] is True
    assert calls["service_account"] is False


def test_google_search_console_client_invalid_credentials_json_returns_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"adc": False, "service_account": False}
    _install_fake_google_auth_modules(monkeypatch, adc_calls=calls)
    client = GoogleSearchConsoleAPIClient(
        credentials_json="{invalid-json",
    )

    with pytest.raises(SearchConsoleAnalyticsProviderConfigurationError) as exc_info:
        client._get_credentials()

    assert getattr(exc_info.value, "diagnostic_status", None) == "invalid_credentials"
    assert calls["adc"] is False
    assert calls["service_account"] is False


def test_search_console_http_403_site_permission_maps_property_not_accessible() -> None:
    assert (
        _classify_search_console_http_error(403, "User does not have sufficient permission for site sc-domain:example.com")
        == "property_not_accessible"
    )


def test_search_console_http_403_generic_forbidden_maps_access_denied() -> None:
    assert _classify_search_console_http_error(403, "forbidden") == "access_denied"

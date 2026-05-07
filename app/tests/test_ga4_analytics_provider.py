from __future__ import annotations

from io import BytesIO
import json
import socket
from urllib.error import HTTPError, URLError

import pytest

import app.integrations.ga4_analytics_provider as ga4_provider_module
from app.integrations.ga4_analytics_provider import (
    GA4AnalyticsProviderConfigurationError,
    GA4AnalyticsProviderError,
    GoogleAnalyticsDataAPIClient,
)


def test_google_ga4_client_uses_site_scoped_property_for_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GoogleAnalyticsDataAPIClient(property_id="999999999")
    captured_calls: list[tuple[str, str, dict[str, object] | None]] = []

    def _request_json(*, url: str, method: str, body: dict[str, object] | None) -> dict[str, object]:
        captured_calls.append((url, method, body))
        assert body is not None
        metrics = [str((metric or {}).get("name") or "") for metric in (body.get("metrics") or [])]
        dimensions = [str((dimension or {}).get("name") or "") for dimension in (body.get("dimensions") or [])]
        if dimensions == ["pagePath"]:
            return {
                "rows": [
                    {
                        "dimensionValues": [{"value": "/"}],
                        "metricValues": [{"value": "120"}, {"value": "80"}],
                    }
                ]
            }
        if metrics == ["sessions"]:
            return {"rows": [{"metricValues": [{"value": "62"}]}]}
        if metrics == ["totalUsers", "sessions", "screenPageViews"]:
            return {"rows": [{"metricValues": [{"value": "100"}, {"value": "140"}, {"value": "220"}]}]}
        return {}

    monkeypatch.setattr(client, "_request_json", _request_json)

    result = client.fetch_site_metrics(
        site_domain="example.com",
        period_days=7,
        top_pages_limit=2,
        ga4_property_id="2000000002",
    )

    assert result.current_period.users == 100
    assert result.current_period.sessions == 140
    assert result.current_period.pageviews == 220
    assert result.current_period.organic_search_sessions == 62
    assert result.top_pages
    assert result.data_source == "ga4"
    assert captured_calls
    assert all("/properties/2000000002:runReport" in url for url, _, _ in captured_calls)
    assert all("/properties/999999999:runReport" not in url for url, _, _ in captured_calls)


def test_google_ga4_client_handles_empty_and_partial_report_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GoogleAnalyticsDataAPIClient(property_id="2000000002")
    request_count = {"value": 0}

    def _request_json(*, url: str, method: str, body: dict[str, object] | None) -> dict[str, object]:
        del url, method
        request_count["value"] += 1
        if request_count["value"] == 1:
            return {"rows": [{"metricValues": [{"value": "80"}]}]}
        if request_count["value"] == 2:
            return {}
        if request_count["value"] == 3:
            return {"rows": []}
        if request_count["value"] == 4:
            return {}
        if request_count["value"] == 5:
            assert body is not None
            return {
                "rows": [
                    {
                        "dimensionValues": [{"value": "/services"}],
                        "metricValues": [{"value": "17"}],
                    }
                ]
            }
        return {}

    monkeypatch.setattr(client, "_request_json", _request_json)

    result = client.fetch_site_metrics(
        site_domain="example.com",
        period_days=7,
        top_pages_limit=3,
        ga4_property_id="2000000002",
    )

    assert result.current_period.users == 80
    assert result.current_period.sessions == 0
    assert result.current_period.pageviews == 0
    assert result.current_period.organic_search_sessions == 0
    assert result.previous_period.users == 0
    assert result.top_pages
    assert result.top_pages[0].current_pageviews == 17
    assert result.top_pages[0].current_sessions == 0


def test_google_ga4_client_rejects_malformed_property_id() -> None:
    client = GoogleAnalyticsDataAPIClient(property_id="2000000002")

    with pytest.raises(GA4AnalyticsProviderConfigurationError) as exc_info:
        client.fetch_window_metrics(
            site_domain="example.com",
            start_date="2026-01-01",
            end_date="2026-01-07",
            ga4_property_id="property/not-valid",
        )

    assert "format is invalid" in str(exc_info.value).lower()


def test_google_ga4_client_request_json_maps_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GoogleAnalyticsDataAPIClient(property_id="2000000002")
    monkeypatch.setattr(client, "_resolve_access_token", lambda: "fake-token")

    def _raise_timeout(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise URLError(socket.timeout("timed out"))

    monkeypatch.setattr(ga4_provider_module, "urlopen", _raise_timeout)

    with pytest.raises(GA4AnalyticsProviderError) as exc_info:
        client._request_json(url="https://example.invalid", method="POST", body={"foo": "bar"})

    assert str(exc_info.value) == "GA4 request timed out."


def test_google_ga4_client_request_json_maps_http_errors_without_token_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GoogleAnalyticsDataAPIClient(property_id="2000000002")
    monkeypatch.setattr(client, "_resolve_access_token", lambda: "fake-token-value")
    error_payload = {"error": {"message": "PERMISSION_DENIED: property access blocked"}}

    def _raise_http_error(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise HTTPError(
            url="https://analyticsdata.googleapis.com/v1beta/properties/2000000002:runReport",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(json.dumps(error_payload).encode("utf-8")),
        )

    monkeypatch.setattr(ga4_provider_module, "urlopen", _raise_http_error)

    with pytest.raises(GA4AnalyticsProviderError) as exc_info:
        client._request_json(url="https://example.invalid", method="POST", body={"foo": "bar"})

    message = str(exc_info.value)
    assert "permission_denied" in message.lower()
    assert "fake-token-value" not in message
    assert "bearer" not in message.lower()


def test_google_ga4_client_request_json_surfaces_rate_limit_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GoogleAnalyticsDataAPIClient(property_id="2000000002")
    monkeypatch.setattr(client, "_resolve_access_token", lambda: "fake-token")
    error_payload = {"error": {"message": "Resource exhausted: quota exceeded"}}

    def _raise_http_error(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        raise HTTPError(
            url="https://analyticsdata.googleapis.com/v1beta/properties/2000000002:runReport",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=BytesIO(json.dumps(error_payload).encode("utf-8")),
        )

    monkeypatch.setattr(ga4_provider_module, "urlopen", _raise_http_error)

    with pytest.raises(GA4AnalyticsProviderError) as exc_info:
        client._request_json(url="https://example.invalid", method="POST", body={"foo": "bar"})

    assert "quota exceeded" in str(exc_info.value).lower()

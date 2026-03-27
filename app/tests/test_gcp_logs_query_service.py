from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.google_cloud_logging import GoogleCloudLoggingADCError, GoogleCloudLoggingAPIError
from app.schemas.admin_logs import GCPLogsQueryRequest
from app.services.gcp_logs_query import (
    GCPLogsQueryConfigurationError,
    GCPLogsQueryPermissionError,
    GCPLogsQueryService,
    GCPLogsQueryValidationError,
)


class _FakeCloudLoggingClient:
    def __init__(self, *, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[dict[str, object]] = []

    def list_entries(
        self,
        *,
        project_id: str,
        filter_text: str,
        page_size: int,
        page_token: str | None = None,
        order_by: str = "timestamp desc",
    ) -> dict:
        self.calls.append(
            {
                "project_id": project_id,
                "filter_text": filter_text,
                "page_size": page_size,
                "page_token": page_token,
                "order_by": order_by,
            }
        )
        if self.error is not None:
            raise self.error
        return self.payload


def test_gcp_logs_query_service_sanitizes_and_bounds_log_entries() -> None:
    oversized_text = "x" * 1200
    fake_client = _FakeCloudLoggingClient(
        payload={
            "entries": [
                {
                    "timestamp": "2026-03-26T12:00:00Z",
                    "severity": "INFO",
                    "logName": "projects/test-project/logs/stdout",
                    "resource": {
                        "type": "cloud_run_revision",
                        "labels": {f"resource_{index}": f"value_{index}" for index in range(20)},
                    },
                    "labels": {f"label_{index}": f"value_{index}" for index in range(20)},
                    "insertId": "entry-1",
                    "textPayload": oversized_text,
                }
            ],
            "nextPageToken": "next-token",
        }
    )
    service = GCPLogsQueryService(client=fake_client, project_id="test-project")

    response = service.query_logs(payload=GCPLogsQueryRequest(filter="severity>=ERROR", page_size=25))

    assert response.page_size == 25
    assert response.order_by == "timestamp desc"
    assert response.resource_scope == ["projects/test-project"]
    assert "severity>=ERROR" in response.effective_filter
    assert response.next_page_token == "next-token"
    assert len(response.entries) == 1
    entry = response.entries[0]
    assert entry.timestamp == "2026-03-26T12:00:00Z"
    assert entry.log_name == "projects/test-project/logs/stdout"
    assert entry.text_payload_summary is not None
    assert len(entry.text_payload_summary) <= 900
    assert entry.text_payload_summary.endswith("...")
    assert entry.labels is not None
    assert len(entry.labels) == 12
    assert entry.resource_labels is not None
    assert len(entry.resource_labels) == 12
    assert fake_client.calls[0]["project_id"] == "test-project"
    assert fake_client.calls[0]["order_by"] == "timestamp desc"
    assert isinstance(fake_client.calls[0]["filter_text"], str)
    assert "timestamp >=" in str(fake_client.calls[0]["filter_text"])


def test_gcp_logs_query_service_applies_visible_default_24h_time_window(monkeypatch) -> None:
    fixed_now = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.services.gcp_logs_query.utc_now", lambda: fixed_now)
    fake_client = _FakeCloudLoggingClient(payload={"entries": []})
    service = GCPLogsQueryService(client=fake_client, project_id="test-project")

    response = service.query_logs(payload=GCPLogsQueryRequest(filter='severity="ERROR"'))

    expected_start = "2026-03-26T12:00:00Z"
    assert response.default_time_range_applied is True
    assert f'timestamp >= "{expected_start}"' in response.effective_filter
    assert fake_client.calls[0]["filter_text"] == response.effective_filter


def test_gcp_logs_query_service_respects_explicit_time_range_without_default(monkeypatch) -> None:
    fixed_now = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.services.gcp_logs_query.utc_now", lambda: fixed_now)
    fake_client = _FakeCloudLoggingClient(payload={"entries": []})
    service = GCPLogsQueryService(client=fake_client, project_id="test-project")

    response = service.query_logs(
        payload=GCPLogsQueryRequest(
            filter='severity="ERROR"',
            start_time="2026-03-20T00:00:00Z",
            end_time="2026-03-27T00:00:00Z",
        )
    )

    assert response.default_time_range_applied is False
    assert 'timestamp >= "2026-03-20T00:00:00Z"' in response.effective_filter
    assert 'timestamp <= "2026-03-27T00:00:00Z"' in response.effective_filter
    assert fake_client.calls[0]["filter_text"] == response.effective_filter


def test_gcp_logs_query_service_start_time_only_disables_default_window(monkeypatch) -> None:
    fixed_now = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.services.gcp_logs_query.utc_now", lambda: fixed_now)
    fake_client = _FakeCloudLoggingClient(payload={"entries": []})
    service = GCPLogsQueryService(client=fake_client, project_id="test-project")

    response = service.query_logs(
        payload=GCPLogsQueryRequest(
            filter='severity="ERROR"',
            start_time="2026-03-20T00:00:00Z",
        )
    )

    assert response.default_time_range_applied is False
    assert 'timestamp >= "2026-03-20T00:00:00Z"' in response.effective_filter
    assert "timestamp <=" not in response.effective_filter
    assert fake_client.calls[0]["filter_text"] == response.effective_filter


def test_gcp_logs_query_service_end_time_only_disables_default_window(monkeypatch) -> None:
    fixed_now = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.services.gcp_logs_query.utc_now", lambda: fixed_now)
    fake_client = _FakeCloudLoggingClient(payload={"entries": []})
    service = GCPLogsQueryService(client=fake_client, project_id="test-project")

    response = service.query_logs(
        payload=GCPLogsQueryRequest(
            filter='severity="ERROR"',
            end_time="2026-03-27T00:00:00Z",
        )
    )

    assert response.default_time_range_applied is False
    assert 'timestamp <= "2026-03-27T00:00:00Z"' in response.effective_filter
    assert "timestamp >=" not in response.effective_filter
    assert fake_client.calls[0]["filter_text"] == response.effective_filter


def test_gcp_logs_query_service_rejects_invalid_time_range_order() -> None:
    service = GCPLogsQueryService(client=_FakeCloudLoggingClient(), project_id="test-project")

    try:
        service.query_logs(
            payload=GCPLogsQueryRequest(
                filter='severity="ERROR"',
                start_time="2026-03-27T00:00:00Z",
                end_time="2026-03-20T00:00:00Z",
            )
        )
    except GCPLogsQueryValidationError as exc:
        assert "earlier than or equal to end_time" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryValidationError")


def test_gcp_logs_query_service_rejects_invalid_iso_timestamp() -> None:
    service = GCPLogsQueryService(client=_FakeCloudLoggingClient(), project_id="test-project")

    try:
        service.query_logs(
            payload=GCPLogsQueryRequest(
                filter='severity="ERROR"',
                start_time="not-a-timestamp",
            )
        )
    except GCPLogsQueryValidationError as exc:
        assert "start_time must be a valid ISO-8601 timestamp" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryValidationError")


def test_gcp_logs_query_service_requires_configured_project() -> None:
    service = GCPLogsQueryService(client=_FakeCloudLoggingClient(), project_id=None)

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter="severity>=ERROR"))
    except GCPLogsQueryConfigurationError as exc:
        message = str(exc)
        assert message == "Cloud Logging query is not configured: missing GCP project id. Set GCP_PROJECT_ID."
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryConfigurationError")


def test_gcp_logs_query_service_surfaces_adc_unavailable_as_configuration_error() -> None:
    service = GCPLogsQueryService(
        client=_FakeCloudLoggingClient(error=GoogleCloudLoggingADCError("adc unavailable")),
        project_id="test-project",
    )

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter="severity>=ERROR"))
    except GCPLogsQueryConfigurationError as exc:
        message = str(exc).lower()
        assert "application default credentials" in message
        assert "service account" in message
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryConfigurationError")


def test_gcp_logs_query_service_maps_adc_dependency_missing_to_configuration_error() -> None:
    service = GCPLogsQueryService(
        client=_FakeCloudLoggingClient(
            error=GoogleCloudLoggingADCError(
                "google-auth transport dependency is unavailable for Cloud Logging ADC access.",
                phase="dependency_missing",
                cause_class="ImportError",
            )
        ),
        project_id="test-project",
    )

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter="severity>=ERROR"))
    except GCPLogsQueryConfigurationError as exc:
        message = str(exc).lower()
        assert "runtime is misconfigured" in message
        assert "google-auth transport dependency" in message
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryConfigurationError")


def test_gcp_logs_query_service_maps_adc_token_refresh_failure_to_configuration_error() -> None:
    service = GCPLogsQueryService(
        client=_FakeCloudLoggingClient(
            error=GoogleCloudLoggingADCError(
                "Unable to refresh Application Default Credentials access token.",
                phase="token_refresh_failure",
                cause_class="RefreshError",
            )
        ),
        project_id="test-project",
    )

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter="severity>=ERROR"))
    except GCPLogsQueryConfigurationError as exc:
        message = str(exc).lower()
        assert "could not refresh runtime adc access token" in message
        assert "workload identity token exchange" in message
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryConfigurationError")


def test_gcp_logs_query_service_maps_invalid_request_errors() -> None:
    service = GCPLogsQueryService(
        client=_FakeCloudLoggingClient(
            error=GoogleCloudLoggingAPIError(
                "invalid filter",
                status_code=400,
                error_status="INVALID_ARGUMENT",
            )
        ),
        project_id="test-project",
    )

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter="bad-filter"))
    except GCPLogsQueryValidationError as exc:
        assert "invalid" in str(exc).lower()
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryValidationError")


def test_gcp_logs_query_service_maps_permission_denied_errors() -> None:
    service = GCPLogsQueryService(
        client=_FakeCloudLoggingClient(
            error=GoogleCloudLoggingAPIError(
                "permission denied",
                status_code=403,
                error_status="PERMISSION_DENIED",
            )
        ),
        project_id="test-project",
    )

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter='severity="ERROR"'))
    except GCPLogsQueryPermissionError as exc:
        message = str(exc).lower()
        assert "permission denied" in message
        assert "roles/logging.viewer" in message
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryPermissionError")


def test_gcp_logs_query_service_maps_invalid_project_scope_to_configuration_error() -> None:
    service = GCPLogsQueryService(
        client=_FakeCloudLoggingClient(
            error=GoogleCloudLoggingAPIError(
                "Cloud Logging request failed: Invalid resource name in resourceNames: projects/not-a-project",
                status_code=400,
                error_status="INVALID_ARGUMENT",
            )
        ),
        project_id="not-a-project",
    )

    try:
        service.query_logs(payload=GCPLogsQueryRequest(filter='severity="ERROR"'))
    except GCPLogsQueryConfigurationError as exc:
        message = str(exc)
        assert "GCP_PROJECT_ID is invalid for Cloud Logging resource scope" in message
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected GCPLogsQueryConfigurationError")

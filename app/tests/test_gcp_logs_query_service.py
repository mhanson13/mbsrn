from __future__ import annotations

from app.integrations.google_cloud_logging import GoogleCloudLoggingADCError, GoogleCloudLoggingAPIError
from app.schemas.admin_logs import GCPLogsQueryRequest
from app.services.gcp_logs_query import (
    GCPLogsQueryConfigurationError,
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

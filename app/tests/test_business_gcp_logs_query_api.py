from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    TenantContext,
    get_db,
    get_gcp_logs_query_service,
    get_tenant_context,
)
from app.api.routes.businesses import router as businesses_router
from app.models.principal import Principal, PrincipalRole
from app.schemas.admin_logs import GCPLogEntryRead, GCPLogsQueryRequest, GCPLogsQueryResponse
from app.services.gcp_logs_query import (
    GCPLogsQueryConfigurationError,
    GCPLogsQueryPermissionError,
    GCPLogsQueryProviderError,
)


class _StubGCPLogsQueryService:
    def __init__(self, response: GCPLogsQueryResponse | None = None) -> None:
        self.response = response or GCPLogsQueryResponse(
            entries=[],
            next_page_token=None,
            page_size=25,
            order_by="timestamp desc",
            resource_scope=["projects/test-project"],
            effective_filter='(severity>=ERROR) AND timestamp >= "2026-03-26T00:00:00Z"',
            default_time_range_applied=True,
        )
        self.calls: list[GCPLogsQueryRequest] = []
        self.error: Exception | None = None

    def query_logs(self, *, payload: GCPLogsQueryRequest) -> GCPLogsQueryResponse:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.response


def _make_client(
    db_session,
    *,
    business_id: str,
    principal_id: str = "admin-1",
    principal_role: PrincipalRole = PrincipalRole.ADMIN,
    gcp_logs_service: _StubGCPLogsQueryService | None = None,
) -> TestClient:
    principal = db_session.get(Principal, (business_id, principal_id))
    if principal is None:
        db_session.add(
            Principal(
                business_id=business_id,
                id=principal_id,
                display_name=principal_id,
                role=principal_role,
                is_active=True,
            )
        )
    else:
        principal.role = principal_role
        principal.is_active = True
    db_session.commit()

    app = FastAPI()
    app.include_router(businesses_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_tenant_context() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=principal_id,
            auth_source="test",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    if gcp_logs_service is not None:
        app.dependency_overrides[get_gcp_logs_query_service] = lambda: gcp_logs_service
    return TestClient(app)


def test_gcp_logs_query_requires_admin_principal(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-1",
        principal_role=PrincipalRole.OPERATOR,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={"filter": 'jsonPayload.event="competitor_provider_request_start"'},
    )

    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]
    assert stub_service.calls == []


def test_gcp_logs_query_rejects_empty_filter(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={"filter": "   "},
    )

    assert response.status_code == 422
    assert stub_service.calls == []


def test_gcp_logs_query_rejects_page_size_above_maximum(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={
            "filter": 'jsonPayload.event="competitor_provider_request_start"',
            "page_size": 101,
        },
    )

    assert response.status_code == 422
    assert stub_service.calls == []


def test_gcp_logs_query_returns_sanitized_results(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService(
        response=GCPLogsQueryResponse(
            entries=[
                GCPLogEntryRead(
                    timestamp="2026-03-26T15:01:02Z",
                    severity="INFO",
                    log_name="projects/test-project/logs/stdout",
                    resource_type="cloud_run_revision",
                    labels={"event": "competitor_provider_request_start"},
                    resource_labels={"service_name": "api"},
                    insert_id="entry-1",
                    text_payload_summary="request started",
                    json_payload_summary=None,
                    proto_payload_summary=None,
                )
            ],
            next_page_token="token-2",
            page_size=25,
            order_by="timestamp desc",
            resource_scope=["projects/test-project"],
            effective_filter='(jsonPayload.event="competitor_provider_request_start") AND timestamp >= "2026-03-26T00:00:00Z"',
            default_time_range_applied=True,
        )
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={
            "filter": '  jsonPayload.event="competitor_provider_request_start"  ',
            "page_size": 25,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page_size"] == 25
    assert payload["order_by"] == "timestamp desc"
    assert payload["resource_scope"] == ["projects/test-project"]
    assert "effective_filter" in payload
    assert payload["default_time_range_applied"] is True
    assert payload["next_page_token"] == "token-2"
    assert payload["entries"][0]["severity"] == "INFO"
    assert stub_service.calls[0].filter == 'jsonPayload.event="competitor_provider_request_start"'
    assert stub_service.calls[0].page_size == 25


def test_gcp_logs_query_round_trips_pagination_token(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService(
        response=GCPLogsQueryResponse(
            entries=[],
            next_page_token="next-token",
            page_size=10,
            order_by="timestamp desc",
            resource_scope=["projects/test-project"],
            effective_filter='(jsonPayload.event="competitor_provider_request_complete") AND timestamp >= "2026-03-26T00:00:00Z"',
            default_time_range_applied=True,
        )
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={
            "filter": 'jsonPayload.event="competitor_provider_request_complete"',
            "page_size": 10,
            "page_token": "token-1",
        },
    )

    assert response.status_code == 200
    assert stub_service.calls[0].page_token == "token-1"
    assert response.json()["next_page_token"] == "next-token"


def test_gcp_logs_query_round_trips_optional_time_range_fields(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService(
        response=GCPLogsQueryResponse(
            entries=[],
            next_page_token=None,
            page_size=25,
            order_by="timestamp desc",
            resource_scope=["projects/test-project"],
            effective_filter=(
                '(jsonPayload.event="competitor_provider_request_complete") '
                'AND timestamp >= "2026-03-20T00:00:00Z" '
                'AND timestamp <= "2026-03-27T00:00:00Z"'
            ),
            default_time_range_applied=False,
        )
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={
            "filter": 'jsonPayload.event="competitor_provider_request_complete"',
            "start_time": "2026-03-20T00:00:00Z",
            "end_time": "2026-03-27T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert stub_service.calls[0].start_time == "2026-03-20T00:00:00Z"
    assert stub_service.calls[0].end_time == "2026-03-27T00:00:00Z"
    payload = response.json()
    assert payload["default_time_range_applied"] is False
    assert 'timestamp >= "2026-03-20T00:00:00Z"' in payload["effective_filter"]
    assert 'timestamp <= "2026-03-27T00:00:00Z"' in payload["effective_filter"]


def test_gcp_logs_query_handles_provider_error_with_sanitized_message(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    stub_service.error = GCPLogsQueryProviderError("raw upstream payload with sensitive fragments")
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={"filter": 'jsonPayload.event="competitor_provider_request_error"'},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Cloud Logging query failed."


def test_gcp_logs_query_surfaces_actionable_missing_project_configuration_error(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    stub_service.error = GCPLogsQueryConfigurationError(
        "Cloud Logging query is not configured: missing GCP project id. "
        "Set GCP_PROJECT_ID."
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={"filter": 'jsonPayload.event="competitor_provider_request_start"'},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == "Cloud Logging query is not configured: missing GCP project id. Set GCP_PROJECT_ID."


def test_gcp_logs_query_surfaces_runtime_dependency_configuration_error(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    stub_service.error = GCPLogsQueryConfigurationError(
        "Cloud Logging query runtime is misconfigured: google-auth transport dependency is unavailable in the API image."
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={"filter": 'jsonPayload.event="competitor_provider_request_start"'},
    )

    assert response.status_code == 503
    detail = response.json()["detail"].lower()
    assert "runtime is misconfigured" in detail
    assert "google-auth transport dependency" in detail


def test_gcp_logs_query_surfaces_permission_denied_error_with_actionable_detail(db_session, seeded_business) -> None:
    stub_service = _StubGCPLogsQueryService()
    stub_service.error = GCPLogsQueryPermissionError(
        "Cloud Logging permission denied for runtime service account. Verify roles/logging.viewer on GCP_PROJECT_ID."
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        gcp_logs_service=stub_service,
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/gcp/logs/query",
        json={"filter": 'jsonPayload.event="competitor_provider_request_error"'},
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "permission denied" in detail.lower()
    assert "roles/logging.viewer" in detail

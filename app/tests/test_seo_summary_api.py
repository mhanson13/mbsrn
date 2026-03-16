from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_crawler,
    get_seo_summary_provider,
    get_tenant_context,
)
from app.api.routes.seo import router as seo_router
from app.integrations.seo_summary_provider import SEOAuditSummaryProvider
from app.models.business import Business
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_audit_summary import SEOAuditSummary
from app.services.seo_crawler import FetchResponse, SEOCrawler


class _FakeCrawler(SEOCrawler):
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        super().__init__(timeout_seconds=1)
        self.pages = pages

    def _fetch(self, url: str) -> FetchResponse:  # type: ignore[override]
        return self.pages[url]


class _FailingSummaryProvider:
    def generate_summary(self, *, run, findings):  # noqa: ANN001, ANN202
        raise RuntimeError("provider unavailable")


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(db_session, *, business_id: str, summary_provider: SEOAuditSummaryProvider | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    fake_crawler = _FakeCrawler(
        pages={
            "https://example.com/": FetchResponse(
                final_url="https://example.com/",
                status_code=200,
                body='<html><body><a href="/service">service</a></body></html>',
            ),
            "https://example.com/service": FetchResponse(
                final_url="https://example.com/service",
                status_code=200,
                body="<html><body>service page</body></html>",
            ),
        }
    )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    app.dependency_overrides[get_seo_crawler] = lambda: fake_crawler
    if summary_provider is not None:
        app.dependency_overrides[get_seo_summary_provider] = lambda: summary_provider
    return TestClient(app)


def test_summary_generation_is_manual_trigger_and_versioned(db_session, seeded_business) -> None:
    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550199",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.commit()

    client = _make_client(db_session, business_id=seeded_business.id)
    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/audit-runs",
        json={"max_pages": 10, "max_depth": 2},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    # Manual-trigger only: no summaries should exist until summarize endpoint is called.
    assert db_session.query(SEOAuditSummary).count() == 0

    first_summary = client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}/summarize")
    assert first_summary.status_code == 201
    payload = first_summary.json()
    assert payload["status"] == "completed"
    assert payload["version"] == 1
    assert isinstance(payload["overall_health_summary"], str)
    assert isinstance(payload["top_issues_json"], list)
    assert isinstance(payload["top_priorities_json"], list)
    assert isinstance(payload["plain_english_explanation"], str)

    second_summary = client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}/summarize")
    assert second_summary.status_code == 201
    assert second_summary.json()["version"] == 2

    cross_tenant = client.post(f"/api/businesses/{other_business.id}/seo/audit-runs/{run_id}/summarize")
    assert cross_tenant.status_code == 404


def test_summary_failure_does_not_change_completed_run_state(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        summary_provider=_FailingSummaryProvider(),
    )
    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/audit-runs",
        json={"max_pages": 10, "max_depth": 2},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]
    assert run_response.json()["status"] == "completed"

    summarize = client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}/summarize")
    assert summarize.status_code == 422

    run_after = client.get(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}")
    assert run_after.status_code == 200
    assert run_after.json()["status"] == "completed"

    failed_summary = db_session.query(SEOAuditSummary).filter(SEOAuditSummary.audit_run_id == run_id).one()
    assert failed_summary.status == "failed"


def test_summary_requires_completed_run(db_session, seeded_business) -> None:
    run = SEOAuditRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=str(uuid4()),
        status="queued",
        max_pages=10,
        max_depth=2,
    )
    db_session.add(run)
    db_session.commit()

    client = _make_client(db_session, business_id=seeded_business.id)
    response = client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run.id}/summarize")
    assert response.status_code == 422


def test_summary_generation_is_stable_with_zero_findings(db_session, seeded_business) -> None:
    run = SEOAuditRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=str(uuid4()),
        status="completed",
        max_pages=10,
        max_depth=2,
        pages_discovered=0,
        pages_crawled=0,
    )
    db_session.add(run)
    db_session.commit()

    client = _make_client(db_session, business_id=seeded_business.id)
    response = client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run.id}/summarize")
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["top_issues_json"] == []
    assert len(payload["top_priorities_json"]) == 3


def test_summary_failure_persists_failed_version_after_previous_success(db_session, seeded_business) -> None:
    success_client = _make_client(db_session, business_id=seeded_business.id)
    create_site = success_client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    run_response = success_client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/audit-runs",
        json={"max_pages": 10, "max_depth": 2},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    first_summary = success_client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}/summarize")
    assert first_summary.status_code == 201
    assert first_summary.json()["version"] == 1

    failing_client = _make_client(
        db_session,
        business_id=seeded_business.id,
        summary_provider=_FailingSummaryProvider(),
    )
    failed_summary = failing_client.post(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}/summarize")
    assert failed_summary.status_code == 422

    summaries = (
        db_session.query(SEOAuditSummary)
        .filter(SEOAuditSummary.audit_run_id == run_id)
        .order_by(SEOAuditSummary.version.asc())
        .all()
    )
    assert [item.version for item in summaries] == [1, 2]
    assert [item.status for item in summaries] == ["completed", "failed"]
    assert summaries[1].error_summary is not None

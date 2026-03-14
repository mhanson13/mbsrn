from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_seo_crawler, get_tenant_context
from app.api.routes.seo import router as seo_router
from app.models.business import Business
from app.services.seo_crawler import FetchResponse, SEOCrawler


class _FakeCrawler(SEOCrawler):
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        super().__init__(timeout_seconds=1)
        self.pages = pages

    def _fetch(self, url: str) -> FetchResponse:  # type: ignore[override]
        return self.pages[url]


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(db_session, *, business_id: str) -> TestClient:
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
    return TestClient(app)


def test_audit_run_endpoints_persist_and_retrieve_findings(db_session, seeded_business) -> None:
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
    run_payload = run_response.json()
    assert run_payload["status"] == "completed"
    assert run_payload["pages_crawled"] >= 1
    assert run_payload["pages_skipped"] >= 0
    assert run_payload["errors_encountered"] >= 0
    assert run_payload["duplicate_urls_skipped"] >= 0
    assert run_payload["crawl_duration_ms"] is not None
    run_id = run_payload["id"]

    list_runs = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/audit-runs")
    assert list_runs.status_code == 200
    assert list_runs.json()["total"] >= 1

    findings = client.get(f"/api/businesses/{seeded_business.id}/seo/audit-runs/{run_id}/findings")
    assert findings.status_code == 200
    assert findings.json()["total"] >= 1

    cross_tenant = client.get(f"/api/businesses/{other_business.id}/seo/audit-runs/{run_id}/findings")
    assert cross_tenant.status_code == 404

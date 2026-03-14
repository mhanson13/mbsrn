from __future__ import annotations

from uuid import uuid4

from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_audit import SEOAuditRunCreateRequest
from app.services.seo_audit import SEOAuditService
from app.services.seo_crawler import FetchResponse, SEOCrawler
from app.services.seo_extractor import SEOExtractor
from app.services.seo_finding_rules import SEOFindingRules


class _FakeCrawler(SEOCrawler):
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        super().__init__(timeout_seconds=1)
        self.pages = pages

    def _fetch(self, url: str) -> FetchResponse:  # type: ignore[override]
        return self.pages[url]


def test_audit_service_persists_pages_findings_and_run_status(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Main Site",
        base_url="https://example.com/",
        normalized_domain="example.com",
        is_active=True,
        is_primary=True,
    )
    db_session.add(site)
    db_session.commit()

    crawler = _FakeCrawler(
        pages={
            "https://example.com/": FetchResponse(
                final_url="https://example.com/",
                status_code=200,
                body=(
                    "<html><body>short"
                    '<a href="/service">service</a>'
                    '<a href="/broken">broken</a>'
                    "</body></html>"
                ),
            ),
            "https://example.com/service": FetchResponse(
                final_url="https://example.com/service",
                status_code=200,
                body=(
                    "<html><head><title>Service</title>"
                    '<meta name="description" content="Service page"></head>'
                    '<body><h1>Service</h1><link rel="canonical" href="https://example.com/service" />'
                    "Service content here."
                    "</body></html>"
                ),
            ),
            "https://example.com/broken": FetchResponse(
                final_url="https://example.com/broken",
                status_code=404,
                body="Not found",
            ),
        }
    )
    service = SEOAuditService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_audit_repository=SEOAuditRepository(db_session),
        crawler=crawler,
        extractor=SEOExtractor(),
        finding_rules=SEOFindingRules(thin_content_min_words=20),
    )

    result = service.run_audit(
        business_id=seeded_business.id,
        site_id=site.id,
        payload=SEOAuditRunCreateRequest(max_pages=10, max_depth=2),
        created_by_principal_id="test-principal",
    )

    assert result.run.status == "completed"
    assert result.run.pages_discovered >= 2
    assert result.run.pages_crawled >= 2
    assert result.run.pages_skipped >= 0
    assert result.run.errors_encountered >= 0
    assert result.run.duplicate_urls_skipped >= 0
    assert result.run.crawl_duration_ms is not None
    assert len(result.pages) >= 2
    assert len(result.findings) > 0

    finding_types = {f.finding_type for f in result.findings}
    assert "missing_title" in finding_types
    assert "missing_meta_description" in finding_types
    assert "missing_h1" in finding_types
    assert "missing_h2" in finding_types
    assert "missing_canonical" in finding_types
    assert "thin_content" in finding_types
    assert "missing_internal_links" in finding_types
    assert "broken_internal_links" in finding_types

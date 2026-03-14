from __future__ import annotations

import logging
from uuid import uuid4

from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_audit import SEOAuditRunCreateRequest
from app.services.seo_audit import SEOAuditService
from app.services.seo_crawler import FetchResponse, SEOCrawler, SEOCrawlerValidationError
from app.services.seo_extractor import SEOExtractor
from app.services.seo_finding_rules import SEOFindingRules


class _FakeCrawler(SEOCrawler):
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        super().__init__(timeout_seconds=1)
        self.pages = pages

    def _fetch(self, url: str) -> FetchResponse:  # type: ignore[override]
        return self.pages[url]


class _FailingCrawler(SEOCrawler):
    def crawl(self, *, base_url: str, max_pages: int, max_depth: int, same_domain_only: bool = True):  # type: ignore[override]
        raise SEOCrawlerValidationError("blocked host")


def _build_service(db_session, crawler: SEOCrawler) -> SEOAuditService:
    return SEOAuditService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_audit_repository=SEOAuditRepository(db_session),
        crawler=crawler,
        extractor=SEOExtractor(),
        finding_rules=SEOFindingRules(thin_content_min_words=20),
    )


def test_audit_logs_include_business_site_run_and_state_transitions(db_session, seeded_business, caplog) -> None:
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
                body="<html><body>ok</body></html>",
            )
        }
    )
    service = _build_service(db_session, crawler)

    caplog.set_level(logging.INFO)
    result = service.run_audit(
        business_id=seeded_business.id,
        site_id=site.id,
        payload=SEOAuditRunCreateRequest(max_pages=5, max_depth=1),
        created_by_principal_id="logger-principal",
    )

    assert result.run.status == "completed"
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "SEO audit run started" in joined
    assert "SEO audit run completed" in joined
    assert f"business_id={seeded_business.id}" in joined
    assert f"site_id={site.id}" in joined
    assert f"audit_run_id={result.run.id}" in joined


def test_audit_failure_logs_include_reason(db_session, seeded_business, caplog) -> None:
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

    service = _build_service(db_session, _FailingCrawler(timeout_seconds=1))
    caplog.set_level(logging.WARNING)
    result = service.run_audit(
        business_id=seeded_business.id,
        site_id=site.id,
        payload=SEOAuditRunCreateRequest(max_pages=5, max_depth=1),
        created_by_principal_id="logger-principal",
    )

    assert result.run.status == "failed"
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "SEO audit run failed" in joined
    assert f"business_id={seeded_business.id}" in joined
    assert f"site_id={site.id}" in joined
    assert f"audit_run_id={result.run.id}" in joined
    assert "reason=blocked host" in joined

from __future__ import annotations

from uuid import uuid4

from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.seo_audit import SEOAuditService
from app.services.seo_crawler import SEOCrawler
from app.services.seo_extractor import SEOExtractor
from app.services.seo_finding_rules import SEOFindingRules


def test_audit_run_summary_and_health_score_are_deterministic(db_session, seeded_business) -> None:
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
    db_session.flush()

    run = SEOAuditRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        max_pages=10,
        max_depth=2,
        pages_discovered=1,
        pages_crawled=1,
        crawl_duration_ms=1234,
    )
    db_session.add(run)
    db_session.flush()

    page = SEOAuditPage(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        audit_run_id=run.id,
        url="https://example.com/",
        status_code=200,
    )
    db_session.add(page)
    db_session.flush()

    finding_types = [
        "missing_title",
        "missing_meta_description",
        "duplicate_title",
        "duplicate_meta_description",
        "thin_content",
        "missing_canonical",
        "missing_h1",
    ]
    for finding_type in finding_types:
        db_session.add(
            SEOAuditFinding(
                id=str(uuid4()),
                business_id=seeded_business.id,
                site_id=site.id,
                audit_run_id=run.id,
                page_id=page.id,
                finding_type=finding_type,
                category="SEO",
                severity="WARNING",
                title=finding_type,
                details=finding_type,
                rule_key=finding_type,
            )
        )
    db_session.commit()

    service = SEOAuditService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_audit_repository=SEOAuditRepository(db_session),
        crawler=SEOCrawler(),
        extractor=SEOExtractor(),
        finding_rules=SEOFindingRules(),
    )
    summary = service.get_run_summary(business_id=seeded_business.id, run_id=run.id)

    assert summary.total_pages == 1
    assert summary.total_findings == 7
    assert summary.warning_findings == 7
    assert summary.critical_findings == 0
    assert summary.info_findings == 0
    assert summary.crawl_duration == 1234
    assert summary.health_score == 50

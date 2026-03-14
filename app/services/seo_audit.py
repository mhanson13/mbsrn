from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun, SEOAuditRunStatus
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_audit import SEOAuditRunCreateRequest
from app.services.seo_crawler import CrawlPageResult, CrawlStats, SEOCrawler, SEOCrawlerValidationError
from app.services.seo_extractor import SEOExtractor
from app.services.seo_finding_rules import SEOFindingRules


logger = logging.getLogger(__name__)

SEVERITY_LEVELS = ("CRITICAL", "WARNING", "INFO")
CATEGORY_LEVELS = ("SEO", "CONTENT", "STRUCTURE", "TECHNICAL")
HEALTH_SCORE_BASE = 100
HEALTH_SCORE_PENALTIES = {
    "missing_title": 12,
    "missing_meta_description": 8,
    "duplicate_title": 6,
    "duplicate_meta_description": 5,
    "thin_content": 5,
    "missing_canonical": 4,
    "missing_h1": 10,
}


class SEOAuditNotFoundError(ValueError):
    pass


class SEOAuditValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AuditRunResult:
    run: SEOAuditRun
    pages: list[SEOAuditPage]
    findings: list[SEOAuditFinding]


@dataclass(frozen=True)
class AuditRunSummary:
    run: SEOAuditRun
    total_pages: int
    total_findings: int
    critical_findings: int
    warning_findings: int
    info_findings: int
    crawl_duration: int | None
    health_score: int
    by_category: dict[str, int]
    by_severity: dict[str, int]


@dataclass(frozen=True)
class AuditRunReport:
    site: SEOSite
    summary: AuditRunSummary
    findings: list[SEOAuditFinding]


class SEOAuditService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_audit_repository: SEOAuditRepository,
        crawler: SEOCrawler,
        extractor: SEOExtractor,
        finding_rules: SEOFindingRules,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_audit_repository = seo_audit_repository
        self.crawler = crawler
        self.extractor = extractor
        self.finding_rules = finding_rules

    def run_audit(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOAuditRunCreateRequest,
        created_by_principal_id: str | None,
    ) -> AuditRunResult:
        self._require_business(business_id)
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOAuditNotFoundError("SEO site not found")

        run = SEOAuditRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            status=SEOAuditRunStatus.QUEUED.value,
            max_pages=payload.max_pages,
            max_depth=payload.max_depth,
            created_by_principal_id=created_by_principal_id,
        )
        self.seo_audit_repository.create_run(run)
        self.session.commit()

        started_monotonic = time.monotonic()
        started_at = utc_now()
        run.status = SEOAuditRunStatus.RUNNING.value
        run.started_at = started_at
        self.seo_audit_repository.save_run(run)
        self.session.commit()
        logger.info(
            "SEO audit run started business_id=%s site_id=%s audit_run_id=%s status=%s max_pages=%s max_depth=%s",
            business_id,
            site_id,
            run.id,
            run.status,
            payload.max_pages,
            payload.max_depth,
        )

        try:
            crawl_pages = self.crawler.crawl(
                base_url=site.base_url,
                max_pages=payload.max_pages,
                max_depth=payload.max_depth,
                same_domain_only=True,
            )
            crawl_stats = self.crawler.last_crawl_stats or CrawlStats(
                pages_discovered=len(crawl_pages),
                pages_skipped=0,
                duplicate_urls_skipped=0,
                errors_encountered=0,
            )
            persisted_pages, broken_links_by_page_id, extraction_errors = self._persist_pages(
                run=run,
                crawl_pages=crawl_pages,
            )
            persisted_findings = self._persist_findings(
                run=run,
                pages=persisted_pages,
                broken_links_by_page_id=broken_links_by_page_id,
            )

            run.pages_discovered = crawl_stats.pages_discovered
            run.pages_crawled = len(persisted_pages)
            run.pages_skipped = crawl_stats.pages_skipped
            run.errors_encountered = crawl_stats.errors_encountered + extraction_errors
            run.duplicate_urls_skipped = crawl_stats.duplicate_urls_skipped
            run.status = SEOAuditRunStatus.COMPLETED.value
            run.completed_at = utc_now()
            run.crawl_duration_ms = int((time.monotonic() - started_monotonic) * 1000)
            run.error_summary = None
            self.seo_audit_repository.save_run(run)
            self.session.commit()
            logger.info(
                (
                    "SEO audit run completed business_id=%s site_id=%s audit_run_id=%s status=%s "
                    "pages_discovered=%s pages_crawled=%s pages_skipped=%s duplicate_urls_skipped=%s "
                    "errors_encountered=%s crawl_duration_ms=%s findings=%s"
                ),
                business_id,
                site_id,
                run.id,
                run.status,
                run.pages_discovered,
                run.pages_crawled,
                run.pages_skipped,
                run.duplicate_urls_skipped,
                run.errors_encountered,
                run.crawl_duration_ms,
                len(persisted_findings),
            )
            return AuditRunResult(run=run, pages=persisted_pages, findings=persisted_findings)
        except SEOCrawlerValidationError as exc:
            return self._fail_run(run=run, reason=str(exc), started_monotonic=started_monotonic)
        except Exception as exc:  # noqa: BLE001
            return self._fail_run(run=run, reason=str(exc), started_monotonic=started_monotonic)

    def get_run(self, *, business_id: str, run_id: str) -> SEOAuditRun:
        self._require_business(business_id)
        run = self.seo_audit_repository.get_run_for_business(business_id, run_id)
        if run is None:
            raise SEOAuditNotFoundError("SEO audit run not found")
        return run

    def list_runs_for_site(self, *, business_id: str, site_id: str) -> list[SEOAuditRun]:
        self._require_business(business_id)
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOAuditNotFoundError("SEO site not found")
        return self.seo_audit_repository.list_runs_for_business_site(business_id, site_id)

    def list_findings_for_run(self, *, business_id: str, run_id: str) -> list[SEOAuditFinding]:
        self._require_business(business_id)
        run = self.seo_audit_repository.get_run_for_business(business_id, run_id)
        if run is None:
            raise SEOAuditNotFoundError("SEO audit run not found")
        return self.seo_audit_repository.list_findings_for_business_run(business_id, run_id)

    def get_run_summary(self, *, business_id: str, run_id: str) -> AuditRunSummary:
        self._require_business(business_id)
        run = self.seo_audit_repository.get_run_for_business(business_id, run_id)
        if run is None:
            raise SEOAuditNotFoundError("SEO audit run not found")

        findings = self.seo_audit_repository.list_findings_for_business_run(business_id, run_id)
        pages = self.seo_audit_repository.list_pages_for_business_run(business_id, run_id)
        by_category, by_severity = self.summarize_findings(findings=findings)
        return AuditRunSummary(
            run=run,
            total_pages=len(pages),
            total_findings=len(findings),
            critical_findings=by_severity["CRITICAL"],
            warning_findings=by_severity["WARNING"],
            info_findings=by_severity["INFO"],
            crawl_duration=run.crawl_duration_ms,
            health_score=self.calculate_health_score(findings=findings),
            by_category=by_category,
            by_severity=by_severity,
        )

    def get_run_report(self, *, business_id: str, run_id: str) -> AuditRunReport:
        summary = self.get_run_summary(business_id=business_id, run_id=run_id)
        site = self.seo_site_repository.get_for_business(business_id, summary.run.site_id)
        if site is None:
            raise SEOAuditNotFoundError("SEO site not found")
        findings = self.seo_audit_repository.list_findings_for_business_run(business_id, run_id)
        return AuditRunReport(site=site, summary=summary, findings=findings)

    def summarize_findings(self, *, findings: list[SEOAuditFinding]) -> tuple[dict[str, int], dict[str, int]]:
        by_category = {key: 0 for key in CATEGORY_LEVELS}
        by_severity = {key: 0 for key in SEVERITY_LEVELS}
        for finding in findings:
            category = (finding.category or "").strip().upper()
            severity = (finding.severity or "").strip().upper()
            if category not in by_category:
                category = "TECHNICAL"
            if severity not in by_severity:
                severity = "INFO"
            by_category[category] += 1
            by_severity[severity] += 1
        return by_category, by_severity

    def calculate_health_score(self, *, findings: list[SEOAuditFinding]) -> int:
        penalty = 0
        for finding in findings:
            penalty += HEALTH_SCORE_PENALTIES.get((finding.finding_type or "").strip().lower(), 0)
        score = HEALTH_SCORE_BASE - penalty
        if score < 0:
            return 0
        if score > 100:
            return 100
        return score

    def _persist_pages(
        self,
        *,
        run: SEOAuditRun,
        crawl_pages: list[CrawlPageResult],
    ) -> tuple[list[SEOAuditPage], dict[str, int], int]:
        status_by_url: dict[str, int] = {page.final_url: page.status_code for page in crawl_pages}
        persisted_pages: list[SEOAuditPage] = []
        broken_links_by_page_id: dict[str, int] = {}
        extraction_errors = 0

        for crawl_page in crawl_pages:
            extracted = None
            if crawl_page.body_text is not None:
                try:
                    extracted = self.extractor.extract(crawl_page.body_text)
                except Exception as exc:  # noqa: BLE001
                    extraction_errors += 1
                    logger.warning(
                        "SEO extractor failed business_id=%s site_id=%s audit_run_id=%s url=%s reason=%s",
                        run.business_id,
                        run.site_id,
                        run.id,
                        crawl_page.final_url,
                        str(exc),
                    )
            page = SEOAuditPage(
                id=str(uuid4()),
                business_id=run.business_id,
                site_id=run.site_id,
                audit_run_id=run.id,
                url=crawl_page.final_url,
                status_code=crawl_page.status_code,
                title=extracted.title if extracted else None,
                meta_description=extracted.meta_description if extracted else None,
                canonical_url=extracted.canonical_url if extracted else None,
                h1_json=extracted.h1_list if extracted else [],
                h2_json=extracted.h2_list if extracted else [],
                word_count=extracted.word_count if extracted else 0,
                internal_link_count=len(crawl_page.outgoing_internal_links),
                image_count=extracted.image_count if extracted else 0,
                missing_alt_count=extracted.missing_alt_count if extracted else 0,
                fetched_at=utc_now(),
            )
            self.seo_audit_repository.add_page(page)
            persisted_pages.append(page)
            if crawl_page.fetch_error:
                logger.warning(
                    "SEO crawl page fetch error business_id=%s site_id=%s audit_run_id=%s url=%s reason=%s",
                    run.business_id,
                    run.site_id,
                    run.id,
                    crawl_page.final_url,
                    crawl_page.fetch_error,
                )

            broken = 0
            for target in crawl_page.outgoing_internal_links:
                if status_by_url.get(target, 200) >= 400:
                    broken += 1
            broken_links_by_page_id[page.id] = broken

        self.session.flush()
        return persisted_pages, broken_links_by_page_id, extraction_errors

    def _persist_findings(
        self,
        *,
        run: SEOAuditRun,
        pages: list[SEOAuditPage],
        broken_links_by_page_id: dict[str, int],
    ) -> list[SEOAuditFinding]:
        finding_drafts = self.finding_rules.evaluate(
            pages=pages,
            broken_internal_links_by_page_id=broken_links_by_page_id,
        )
        persisted: list[SEOAuditFinding] = []
        for finding in finding_drafts:
            item = SEOAuditFinding(
                id=str(uuid4()),
                business_id=run.business_id,
                site_id=run.site_id,
                audit_run_id=run.id,
                page_id=finding.page_id,
                finding_type=finding.finding_type,
                category=finding.category,
                severity=finding.severity,
                title=finding.title,
                details=finding.details,
                rule_key=finding.rule_key,
                suggested_fix=finding.suggested_fix,
            )
            self.seo_audit_repository.add_finding(item)
            persisted.append(item)
        self.session.flush()
        return persisted

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOAuditNotFoundError("Business not found")

    def _fail_run(
        self,
        *,
        run: SEOAuditRun,
        reason: str,
        started_monotonic: float | None = None,
    ) -> AuditRunResult:
        logger.warning(
            "SEO audit run failed business_id=%s site_id=%s audit_run_id=%s status=failed reason=%s",
            run.business_id,
            run.site_id,
            run.id,
            reason,
        )
        run.status = SEOAuditRunStatus.FAILED.value
        run.completed_at = utc_now()
        if started_monotonic is not None:
            run.crawl_duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        run.error_summary = reason[:1000]
        self.seo_audit_repository.save_run(run)
        self.session.commit()
        return AuditRunResult(run=run, pages=[], findings=[])

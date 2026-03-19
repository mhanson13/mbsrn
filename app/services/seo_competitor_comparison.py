from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.schemas.seo_competitor import SEOCompetitorComparisonRunCreateRequest
from app.services.seo_finding_rules import FindingCategory, FindingSeverity

THIN_CONTENT_MIN_WORDS = 150


class SEOCompetitorComparisonNotFoundError(ValueError):
    pass


class SEOCompetitorComparisonValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEOCompetitorComparisonResult:
    run: SEOCompetitorComparisonRun
    findings: list[SEOCompetitorComparisonFinding]


@dataclass(frozen=True)
class SEOCompetitorComparisonReport:
    run: SEOCompetitorComparisonRun
    findings: list[SEOCompetitorComparisonFinding]
    findings_by_type: dict[str, int]
    findings_by_category: dict[str, int]
    findings_by_severity: dict[str, int]
    metric_rollups: dict[str, dict[str, object]]


@dataclass(frozen=True)
class _PageQualityStats:
    total_pages: int
    missing_title: int
    missing_meta_description: int
    missing_h1: int
    thin_content: int
    missing_canonical: int
    missing_internal_links: int


@dataclass(frozen=True)
class _ComparisonMetric:
    key: str
    title: str
    category: str
    higher_is_better: bool
    client_value: int
    competitor_value: int
    warning_delta_threshold: int
    critical_delta_threshold: int
    unit: str


@dataclass(frozen=True)
class _MetricResult:
    metric: _ComparisonMetric
    severity: str
    gap_direction: str
    delta: int


@dataclass(frozen=True)
class _GeneratedComparisonData:
    findings: list[SEOCompetitorComparisonFinding]
    metric_rollups: dict[str, dict[str, object]]
    client_pages_analyzed: int
    competitor_pages_analyzed: int


class SEOCompetitorComparisonService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_audit_repository: SEOAuditRepository,
        seo_competitor_repository: SEOCompetitorRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_audit_repository = seo_audit_repository
        self.seo_competitor_repository = seo_competitor_repository

    def run_comparison(
        self,
        *,
        business_id: str,
        competitor_set_id: str,
        payload: SEOCompetitorComparisonRunCreateRequest,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorComparisonResult:
        self._require_business(business_id)
        competitor_set = self.seo_competitor_repository.get_set_for_business(business_id, competitor_set_id)
        if competitor_set is None:
            raise SEOCompetitorComparisonNotFoundError("Competitor set not found")

        snapshot_run = self.seo_competitor_repository.get_snapshot_run_for_business(
            business_id,
            payload.snapshot_run_id,
        )
        if snapshot_run is None:
            raise SEOCompetitorComparisonNotFoundError("Competitor snapshot run not found")
        if snapshot_run.competitor_set_id != competitor_set.id:
            raise SEOCompetitorComparisonValidationError("Snapshot run does not belong to the target competitor set")
        if snapshot_run.site_id != competitor_set.site_id:
            raise SEOCompetitorComparisonValidationError("Snapshot run site does not match competitor set site")
        if snapshot_run.status != "completed":
            raise SEOCompetitorComparisonValidationError("Snapshot run must be completed before comparison")

        baseline_run = self._resolve_baseline_run(
            business_id=business_id,
            site_id=competitor_set.site_id,
            explicit_baseline_run_id=payload.baseline_audit_run_id,
            snapshot_client_run_id=snapshot_run.client_audit_run_id,
        )
        baseline_run_id = baseline_run.id if baseline_run is not None else None

        run = SEOCompetitorComparisonRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=competitor_set.site_id,
            competitor_set_id=competitor_set.id,
            snapshot_run_id=snapshot_run.id,
            baseline_audit_run_id=baseline_run_id,
            status="queued",
            total_findings=0,
            critical_findings=0,
            warning_findings=0,
            info_findings=0,
            client_pages_analyzed=0,
            competitor_pages_analyzed=0,
            metric_rollups_json={},
            finding_type_counts_json={},
            category_counts_json={},
            severity_counts_json={},
            created_by_principal_id=created_by_principal_id,
        )
        try:
            self.seo_competitor_repository.create_comparison_run(run)
            self.session.commit()
        except ValueError as exc:
            self.session.rollback()
            raise SEOCompetitorComparisonValidationError(str(exc)) from exc

        started = time.monotonic()
        run.status = "running"
        run.started_at = utc_now()
        self.seo_competitor_repository.save_comparison_run(run)
        self.session.commit()

        try:
            generated = self._generate_findings(
                business_id=business_id,
                run=run,
                baseline_run=baseline_run,
            )
            for finding in generated.findings:
                self.seo_competitor_repository.add_comparison_finding(finding)

            run.total_findings = len(generated.findings)
            run.critical_findings = sum(1 for item in generated.findings if item.severity == FindingSeverity.CRITICAL)
            run.warning_findings = sum(1 for item in generated.findings if item.severity == FindingSeverity.WARNING)
            run.info_findings = sum(1 for item in generated.findings if item.severity == FindingSeverity.INFO)
            run.client_pages_analyzed = generated.client_pages_analyzed
            run.competitor_pages_analyzed = generated.competitor_pages_analyzed
            run.metric_rollups_json = generated.metric_rollups
            run.finding_type_counts_json = self._count_findings_by_type(generated.findings)
            by_category, by_severity = self.summarize_findings(findings=generated.findings)
            run.category_counts_json = by_category
            run.severity_counts_json = by_severity
            run.status = "completed"
            run.completed_at = utc_now()
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.error_summary = None
            self.seo_competitor_repository.save_comparison_run(run)
            self.session.commit()
            self.session.refresh(run)
            return SEOCompetitorComparisonResult(run=run, findings=generated.findings)
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            run.status = "failed"
            run.completed_at = utc_now()
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.error_summary = str(exc)[:1000]
            self.seo_competitor_repository.save_comparison_run(run)
            self.session.commit()
            raise SEOCompetitorComparisonValidationError("Deterministic comparison run failed") from exc

    def list_runs(self, *, business_id: str, competitor_set_id: str) -> list[SEOCompetitorComparisonRun]:
        self._require_business(business_id)
        competitor_set = self.seo_competitor_repository.get_set_for_business(business_id, competitor_set_id)
        if competitor_set is None:
            raise SEOCompetitorComparisonNotFoundError("Competitor set not found")
        return self.seo_competitor_repository.list_comparison_runs_for_business_set(
            business_id,
            competitor_set_id,
        )

    def list_runs_for_site(self, *, business_id: str, site_id: str) -> list[SEOCompetitorComparisonRun]:
        self._require_business(business_id)
        return self.seo_competitor_repository.list_comparison_runs_for_business_site(
            business_id,
            site_id,
        )

    def get_run(self, *, business_id: str, comparison_run_id: str) -> SEOCompetitorComparisonRun:
        self._require_business(business_id)
        run = self.seo_competitor_repository.get_comparison_run_for_business(business_id, comparison_run_id)
        if run is None:
            raise SEOCompetitorComparisonNotFoundError("Competitor comparison run not found")
        return run

    def list_findings(
        self,
        *,
        business_id: str,
        comparison_run_id: str,
    ) -> list[SEOCompetitorComparisonFinding]:
        self.get_run(business_id=business_id, comparison_run_id=comparison_run_id)
        return self.seo_competitor_repository.list_comparison_findings_for_business_run(
            business_id,
            comparison_run_id,
        )

    def summarize_findings(
        self,
        *,
        findings: list[SEOCompetitorComparisonFinding],
    ) -> tuple[dict[str, int], dict[str, int]]:
        by_category = {
            FindingCategory.SEO: 0,
            FindingCategory.CONTENT: 0,
            FindingCategory.STRUCTURE: 0,
            FindingCategory.TECHNICAL: 0,
        }
        by_severity = {
            FindingSeverity.CRITICAL: 0,
            FindingSeverity.WARNING: 0,
            FindingSeverity.INFO: 0,
        }
        for finding in findings:
            category = finding.category.strip().upper()
            severity = finding.severity.strip().upper()
            if category not in by_category:
                category = FindingCategory.TECHNICAL
            if severity not in by_severity:
                severity = FindingSeverity.INFO
            by_category[category] += 1
            by_severity[severity] += 1
        return by_category, by_severity

    def get_report(
        self,
        *,
        business_id: str,
        comparison_run_id: str,
    ) -> SEOCompetitorComparisonReport:
        run = self.get_run(business_id=business_id, comparison_run_id=comparison_run_id)
        findings = self.list_findings(business_id=business_id, comparison_run_id=comparison_run_id)

        by_category = self._normalize_int_map(run.category_counts_json)
        by_severity = self._normalize_int_map(run.severity_counts_json)
        if not by_category or not by_severity:
            by_category, by_severity = self.summarize_findings(findings=findings)

        by_type = self._normalize_int_map(run.finding_type_counts_json)
        if not by_type:
            by_type = self._count_findings_by_type(findings)

        metric_rollups = self._normalize_metric_rollups(run.metric_rollups_json)

        return SEOCompetitorComparisonReport(
            run=run,
            findings=findings,
            findings_by_type=by_type,
            findings_by_category=by_category,
            findings_by_severity=by_severity,
            metric_rollups=metric_rollups,
        )

    def _generate_findings(
        self,
        *,
        business_id: str,
        run: SEOCompetitorComparisonRun,
        baseline_run: SEOAuditRun | None,
    ) -> _GeneratedComparisonData:
        snapshot_pages = self.seo_competitor_repository.list_snapshot_pages_for_business_run(
            business_id,
            run.snapshot_run_id,
        )
        client_pages: list[SEOAuditPage] = []
        if baseline_run is not None:
            client_pages = self.seo_audit_repository.list_pages_for_business_run(
                business_id,
                baseline_run.id,
            )

        client_stats = self._build_audit_page_stats(client_pages)
        competitor_stats = self._build_snapshot_page_stats(snapshot_pages)

        findings: list[SEOCompetitorComparisonFinding] = []
        metric_rollups: dict[str, dict[str, object]] = {}

        metrics: list[_ComparisonMetric] = []
        if baseline_run is not None:
            metrics = self._build_metrics(client_stats=client_stats, competitor_stats=competitor_stats)

        for metric in metrics:
            metric_result = self._evaluate_metric(metric)
            details = (
                f"Client={metric.client_value}, competitors={metric.competitor_value}, delta={metric_result.delta}."
            )
            findings.append(
                SEOCompetitorComparisonFinding(
                    id=str(uuid4()),
                    business_id=run.business_id,
                    site_id=run.site_id,
                    competitor_set_id=run.competitor_set_id,
                    comparison_run_id=run.id,
                    finding_type=f"{metric.key}_gap",
                    category=metric.category,
                    severity=metric_result.severity,
                    title=metric.title,
                    details=details,
                    rule_key=f"comparison_{metric.key}",
                    client_value=str(metric.client_value),
                    competitor_value=str(metric.competitor_value),
                    gap_direction=metric_result.gap_direction,
                    evidence_json={
                        "client": metric.client_value,
                        "competitor": metric.competitor_value,
                        "delta": metric_result.delta,
                    },
                )
            )
            metric_rollups[metric.key] = {
                "title": metric.title,
                "category": metric.category,
                "unit": metric.unit,
                "higher_is_better": metric.higher_is_better,
                "client_value": metric.client_value,
                "competitor_value": metric.competitor_value,
                "delta": metric_result.delta,
                "severity": metric_result.severity,
                "gap_direction": metric_result.gap_direction,
            }

        if baseline_run is None:
            findings.append(
                SEOCompetitorComparisonFinding(
                    id=str(uuid4()),
                    business_id=run.business_id,
                    site_id=run.site_id,
                    competitor_set_id=run.competitor_set_id,
                    comparison_run_id=run.id,
                    finding_type="missing_client_baseline",
                    category=FindingCategory.TECHNICAL,
                    severity=FindingSeverity.WARNING,
                    title="Missing client baseline audit",
                    details="No completed first-party audit run was available for baseline comparison.",
                    rule_key="comparison_missing_client_baseline",
                    client_value=None,
                    competitor_value=str(len(snapshot_pages)),
                    gap_direction="unknown",
                    evidence_json={"snapshot_page_count": len(snapshot_pages)},
                )
            )

        if not snapshot_pages:
            findings.append(
                SEOCompetitorComparisonFinding(
                    id=str(uuid4()),
                    business_id=run.business_id,
                    site_id=run.site_id,
                    competitor_set_id=run.competitor_set_id,
                    comparison_run_id=run.id,
                    finding_type="empty_competitor_snapshot",
                    category=FindingCategory.TECHNICAL,
                    severity=FindingSeverity.WARNING,
                    title="Competitor snapshot has no captured pages",
                    details="Snapshot run exists but no competitor pages were captured.",
                    rule_key="comparison_empty_snapshot",
                    client_value=str(len(client_pages)),
                    competitor_value="0",
                    gap_direction="unknown",
                    evidence_json={"client_page_count": len(client_pages)},
                )
            )

        return _GeneratedComparisonData(
            findings=findings,
            metric_rollups=metric_rollups,
            client_pages_analyzed=client_stats.total_pages,
            competitor_pages_analyzed=competitor_stats.total_pages,
        )

    def _build_metrics(
        self,
        *,
        client_stats: _PageQualityStats,
        competitor_stats: _PageQualityStats,
    ) -> list[_ComparisonMetric]:
        return [
            _ComparisonMetric(
                key="page_count",
                title="Page coverage gap",
                category=FindingCategory.STRUCTURE,
                higher_is_better=True,
                client_value=client_stats.total_pages,
                competitor_value=competitor_stats.total_pages,
                warning_delta_threshold=1,
                critical_delta_threshold=5,
                unit="count",
            ),
            _ComparisonMetric(
                key="missing_title_count",
                title="Missing title count gap",
                category=FindingCategory.SEO,
                higher_is_better=False,
                client_value=client_stats.missing_title,
                competitor_value=competitor_stats.missing_title,
                warning_delta_threshold=1,
                critical_delta_threshold=3,
                unit="count",
            ),
            _ComparisonMetric(
                key="missing_meta_description_count",
                title="Missing meta description count gap",
                category=FindingCategory.SEO,
                higher_is_better=False,
                client_value=client_stats.missing_meta_description,
                competitor_value=competitor_stats.missing_meta_description,
                warning_delta_threshold=1,
                critical_delta_threshold=3,
                unit="count",
            ),
            _ComparisonMetric(
                key="missing_h1_count",
                title="Missing H1 count gap",
                category=FindingCategory.STRUCTURE,
                higher_is_better=False,
                client_value=client_stats.missing_h1,
                competitor_value=competitor_stats.missing_h1,
                warning_delta_threshold=1,
                critical_delta_threshold=3,
                unit="count",
            ),
            _ComparisonMetric(
                key="thin_content_count",
                title="Thin content count gap",
                category=FindingCategory.CONTENT,
                higher_is_better=False,
                client_value=client_stats.thin_content,
                competitor_value=competitor_stats.thin_content,
                warning_delta_threshold=1,
                critical_delta_threshold=3,
                unit="count",
            ),
            _ComparisonMetric(
                key="missing_canonical_count",
                title="Missing canonical count gap",
                category=FindingCategory.TECHNICAL,
                higher_is_better=False,
                client_value=client_stats.missing_canonical,
                competitor_value=competitor_stats.missing_canonical,
                warning_delta_threshold=1,
                critical_delta_threshold=2,
                unit="count",
            ),
            _ComparisonMetric(
                key="missing_internal_links_count",
                title="Missing internal links count gap",
                category=FindingCategory.STRUCTURE,
                higher_is_better=False,
                client_value=client_stats.missing_internal_links,
                competitor_value=competitor_stats.missing_internal_links,
                warning_delta_threshold=1,
                critical_delta_threshold=3,
                unit="count",
            ),
            _ComparisonMetric(
                key="title_coverage_percent",
                title="Title coverage delta",
                category=FindingCategory.SEO,
                higher_is_better=True,
                client_value=self._coverage_percent(client_stats.total_pages, client_stats.missing_title),
                competitor_value=self._coverage_percent(
                    competitor_stats.total_pages,
                    competitor_stats.missing_title,
                ),
                warning_delta_threshold=5,
                critical_delta_threshold=15,
                unit="percent",
            ),
            _ComparisonMetric(
                key="meta_description_coverage_percent",
                title="Meta description coverage delta",
                category=FindingCategory.SEO,
                higher_is_better=True,
                client_value=self._coverage_percent(
                    client_stats.total_pages,
                    client_stats.missing_meta_description,
                ),
                competitor_value=self._coverage_percent(
                    competitor_stats.total_pages,
                    competitor_stats.missing_meta_description,
                ),
                warning_delta_threshold=5,
                critical_delta_threshold=15,
                unit="percent",
            ),
            _ComparisonMetric(
                key="h1_coverage_percent",
                title="H1 coverage delta",
                category=FindingCategory.STRUCTURE,
                higher_is_better=True,
                client_value=self._coverage_percent(client_stats.total_pages, client_stats.missing_h1),
                competitor_value=self._coverage_percent(
                    competitor_stats.total_pages,
                    competitor_stats.missing_h1,
                ),
                warning_delta_threshold=5,
                critical_delta_threshold=15,
                unit="percent",
            ),
            _ComparisonMetric(
                key="canonical_coverage_percent",
                title="Canonical coverage delta",
                category=FindingCategory.TECHNICAL,
                higher_is_better=True,
                client_value=self._coverage_percent(client_stats.total_pages, client_stats.missing_canonical),
                competitor_value=self._coverage_percent(
                    competitor_stats.total_pages,
                    competitor_stats.missing_canonical,
                ),
                warning_delta_threshold=5,
                critical_delta_threshold=15,
                unit="percent",
            ),
            _ComparisonMetric(
                key="internal_link_coverage_percent",
                title="Internal link coverage delta",
                category=FindingCategory.STRUCTURE,
                higher_is_better=True,
                client_value=self._coverage_percent(
                    client_stats.total_pages,
                    client_stats.missing_internal_links,
                ),
                competitor_value=self._coverage_percent(
                    competitor_stats.total_pages,
                    competitor_stats.missing_internal_links,
                ),
                warning_delta_threshold=5,
                critical_delta_threshold=15,
                unit="percent",
            ),
        ]

    def _evaluate_metric(self, metric: _ComparisonMetric) -> _MetricResult:
        delta = metric.client_value - metric.competitor_value
        if metric.higher_is_better:
            if delta > 0:
                return _MetricResult(
                    metric=metric,
                    severity=FindingSeverity.INFO,
                    gap_direction="client_leads",
                    delta=delta,
                )
            if delta < 0:
                trailing = abs(delta)
                if trailing >= metric.critical_delta_threshold:
                    severity = FindingSeverity.CRITICAL
                elif trailing >= metric.warning_delta_threshold:
                    severity = FindingSeverity.WARNING
                else:
                    severity = FindingSeverity.INFO
                return _MetricResult(
                    metric=metric,
                    severity=severity,
                    gap_direction="client_trails",
                    delta=delta,
                )
            return _MetricResult(
                metric=metric,
                severity=FindingSeverity.INFO,
                gap_direction="parity",
                delta=delta,
            )

        # Lower is better for defect counts.
        if delta < 0:
            return _MetricResult(
                metric=metric,
                severity=FindingSeverity.INFO,
                gap_direction="client_leads",
                delta=delta,
            )
        if delta > 0:
            if delta >= metric.critical_delta_threshold:
                severity = FindingSeverity.CRITICAL
            elif delta >= metric.warning_delta_threshold:
                severity = FindingSeverity.WARNING
            else:
                severity = FindingSeverity.INFO
            return _MetricResult(
                metric=metric,
                severity=severity,
                gap_direction="client_trails",
                delta=delta,
            )
        return _MetricResult(
            metric=metric,
            severity=FindingSeverity.INFO,
            gap_direction="parity",
            delta=delta,
        )

    def _build_audit_page_stats(self, pages: list[SEOAuditPage]) -> _PageQualityStats:
        total_pages = len(pages)
        return _PageQualityStats(
            total_pages=total_pages,
            missing_title=sum(1 for page in pages if not (page.title or "").strip()),
            missing_meta_description=sum(1 for page in pages if not (page.meta_description or "").strip()),
            missing_h1=sum(1 for page in pages if len(page.h1_json or []) == 0),
            thin_content=sum(1 for page in pages if (page.word_count or 0) < THIN_CONTENT_MIN_WORDS),
            missing_canonical=sum(1 for page in pages if not (page.canonical_url or "").strip()),
            missing_internal_links=sum(1 for page in pages if (page.internal_link_count or 0) <= 0),
        )

    def _build_snapshot_page_stats(self, pages: list[SEOCompetitorSnapshotPage]) -> _PageQualityStats:
        total_pages = len(pages)
        return _PageQualityStats(
            total_pages=total_pages,
            missing_title=sum(1 for page in pages if not (page.title or "").strip()),
            missing_meta_description=sum(1 for page in pages if not (page.meta_description or "").strip()),
            missing_h1=sum(1 for page in pages if len(page.h1_json or []) == 0),
            thin_content=sum(1 for page in pages if (page.word_count or 0) < THIN_CONTENT_MIN_WORDS),
            missing_canonical=sum(1 for page in pages if not (page.canonical_url or "").strip()),
            missing_internal_links=sum(1 for page in pages if (page.internal_link_count or 0) <= 0),
        )

    def _resolve_baseline_run(
        self,
        *,
        business_id: str,
        site_id: str,
        explicit_baseline_run_id: str | None,
        snapshot_client_run_id: str | None,
    ) -> SEOAuditRun | None:
        selected_id = explicit_baseline_run_id or snapshot_client_run_id
        if selected_id is not None:
            run = self.seo_audit_repository.get_run_for_business(business_id, selected_id)
            if run is None:
                raise SEOCompetitorComparisonValidationError("Baseline audit run not found")
            if run.site_id != site_id:
                raise SEOCompetitorComparisonValidationError("Baseline audit run does not match competitor set site")
            if run.status != "completed":
                raise SEOCompetitorComparisonValidationError("Baseline audit run must be completed")
            return run

        return self.seo_audit_repository.get_latest_completed_run_for_business_site(business_id, site_id)

    def _count_findings_by_type(self, findings: list[SEOCompetitorComparisonFinding]) -> dict[str, int]:
        counts = Counter()
        for finding in findings:
            counts[finding.finding_type] += 1
        return dict(sorted(counts.items()))

    def _normalize_int_map(self, raw: dict[str, object] | None) -> dict[str, int]:
        if not raw:
            return {}
        normalized: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError):
                continue
        return normalized

    def _normalize_metric_rollups(
        self,
        raw: dict[str, object] | None,
    ) -> dict[str, dict[str, object]]:
        if not raw:
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            normalized[key] = dict(value)
        return normalized

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorComparisonNotFoundError("Business not found")

    def _coverage_percent(self, total_pages: int, missing_count: int) -> int:
        if total_pages <= 0:
            return 0
        covered = total_pages - missing_count
        if covered <= 0:
            return 0
        return round((covered / total_pages) * 100)

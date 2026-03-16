from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun


@dataclass(frozen=True)
class SEOAuditSummaryOutput:
    overall_health_summary: str
    top_issues: list[str]
    top_priorities: list[str]
    plain_english_explanation: str
    model_name: str
    prompt_version: str


class SEOAuditSummaryProvider(Protocol):
    def generate_summary(self, *, run: SEOAuditRun, findings: list[SEOAuditFinding]) -> SEOAuditSummaryOutput:
        ...


@dataclass(frozen=True)
class SEOCompetitorComparisonSummaryOutput:
    overall_gap_summary: str
    top_gaps: list[str]
    plain_english_explanation: str
    model_name: str
    prompt_version: str


class SEOCompetitorComparisonSummaryProvider(Protocol):
    def generate_summary(
        self,
        *,
        run: SEOCompetitorComparisonRun,
        findings: list[SEOCompetitorComparisonFinding],
        metric_rollups: dict[str, dict[str, object]],
        findings_by_type: dict[str, int],
        findings_by_category: dict[str, int],
        findings_by_severity: dict[str, int],
    ) -> SEOCompetitorComparisonSummaryOutput:
        ...


class MockSEOAuditSummaryProvider:
    def __init__(self, *, model_name: str = "mock-seo-summary-v1", prompt_version: str = "seo-summary-v1") -> None:
        self.model_name = model_name
        self.prompt_version = prompt_version

    def generate_summary(self, *, run: SEOAuditRun, findings: list[SEOAuditFinding]) -> SEOAuditSummaryOutput:
        by_severity: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for finding in findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
            by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1

        severity_summary = ", ".join(f"{k}:{v}" for k, v in sorted(by_severity.items()))
        overall = (
            f"Audit run {run.id} scanned {run.pages_crawled} pages and found {len(findings)} issues. "
            f"Severity mix: {severity_summary or 'none'}."
        )
        ranked_types = sorted(by_type.items(), key=lambda item: item[1], reverse=True)
        top_issues = [f"{item[0]} ({item[1]})" for item in ranked_types[:3]]
        top_priorities = [
            "Fix high-severity metadata and technical issues first.",
            "Address missing titles/meta descriptions on key pages.",
            "Resolve thin content and broken internal links on service pages.",
        ]
        plain_english = (
            "Your site has clear SEO gaps that can be fixed in a prioritized order. "
            "Start with technical and metadata blockers, then improve page depth."
        )
        return SEOAuditSummaryOutput(
            overall_health_summary=overall,
            top_issues=top_issues,
            top_priorities=top_priorities,
            plain_english_explanation=plain_english,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )


class MockSEOCompetitorComparisonSummaryProvider:
    def __init__(
        self,
        *,
        model_name: str = "mock-seo-competitor-summary-v1",
        prompt_version: str = "seo-competitor-summary-v1",
    ) -> None:
        self.model_name = model_name
        self.prompt_version = prompt_version

    def generate_summary(
        self,
        *,
        run: SEOCompetitorComparisonRun,
        findings: list[SEOCompetitorComparisonFinding],
        metric_rollups: dict[str, dict[str, object]],
        findings_by_type: dict[str, int],
        findings_by_category: dict[str, int],
        findings_by_severity: dict[str, int],
    ) -> SEOCompetitorComparisonSummaryOutput:
        severity_summary = ", ".join(f"{k}:{v}" for k, v in sorted(findings_by_severity.items()) if v > 0) or "none"
        overall = (
            f"Comparison run {run.id} processed {run.client_pages_analyzed} client pages and "
            f"{run.competitor_pages_analyzed} competitor pages. Findings: {len(findings)} "
            f"across {len(metric_rollups)} deterministic metrics. Severity mix: {severity_summary}."
        )

        ranked_types = sorted(findings_by_type.items(), key=lambda item: item[1], reverse=True)
        top_gaps = [f"{item[0]} ({item[1]})" for item in ranked_types[:3]]

        strongest_categories = sorted(
            findings_by_category.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        category_text = ", ".join(f"{k}:{v}" for k, v in strongest_categories if v > 0) or "none"
        plain_english = (
            "This summary reflects deterministic comparison evidence only. "
            f"Most concentrated gap categories are {category_text}."
        )

        return SEOCompetitorComparisonSummaryOutput(
            overall_gap_summary=overall,
            top_gaps=top_gaps,
            plain_english_explanation=plain_english,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite


@dataclass(frozen=True)
class SEOAuditSummaryOutput:
    overall_health_summary: str
    top_issues: list[str]
    top_priorities: list[str]
    plain_english_explanation: str
    model_name: str
    prompt_version: str


class SEOAuditSummaryProvider(Protocol):
    def generate_summary(self, *, run: SEOAuditRun, findings: list[SEOAuditFinding]) -> SEOAuditSummaryOutput: ...


@dataclass(frozen=True)
class SEOCompetitorComparisonSummaryOutput:
    overall_gap_summary: str
    top_gaps: list[str]
    plain_english_explanation: str
    provider_name: str
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
    ) -> SEOCompetitorComparisonSummaryOutput: ...


@dataclass(frozen=True)
class SEOCompetitorProfileDraftCandidateOutput:
    suggested_name: str
    suggested_domain: str
    competitor_type: str
    summary: str | None
    why_competitor: str | None
    evidence: str | None
    confidence_score: float


@dataclass(frozen=True)
class SEOCompetitorProfileGenerationOutput:
    candidates: list[SEOCompetitorProfileDraftCandidateOutput]
    provider_name: str
    model_name: str
    prompt_version: str
    raw_response: str | None = None
    provider_call_type: str | None = None
    endpoint_path: str | None = None
    web_search_enabled: bool | None = None
    request_duration_ms: int | None = None
    had_schema_repair_or_discard: bool = False
    schema_invalid_candidate_count: int = 0
    schema_invalid_field_type_count: int = 0
    google_places_seed_count: int = 0


class SEOCompetitorProfileGenerationProvider(Protocol):
    def generate_competitor_profiles(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
        reduced_context_mode: bool = False,
        seed_candidates: list[dict[str, object]] | None = None,
    ) -> SEOCompetitorProfileGenerationOutput: ...


@dataclass(frozen=True)
class SEORecommendationNarrativeOutput:
    narrative_text: str
    top_themes: list[str]
    sections: dict[str, object] | None
    provider_name: str
    model_name: str
    prompt_version: str


class SEORecommendationNarrativeProvider(Protocol):
    def generate_narrative(
        self,
        *,
        run: SEORecommendationRun,
        recommendations: list[SEORecommendation],
        by_status: dict[str, int],
        by_category: dict[str, int],
        by_severity: dict[str, int],
        by_effort_bucket: dict[str, int],
        by_priority_band: dict[str, int],
        backlog: list[SEORecommendation],
        competitor_telemetry_summary: dict[str, object],
        current_tuning_values: dict[str, int],
        competitor_context: dict[str, object] | None = None,
    ) -> SEORecommendationNarrativeOutput: ...


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
        provider_name: str = "mock",
        model_name: str = "mock-seo-competitor-summary-v1",
        prompt_version: str = "seo-competitor-summary-v1",
    ) -> None:
        self.provider_name = provider_name
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
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )


class MockSEOCompetitorProfileGenerationProvider:
    def __init__(
        self,
        *,
        provider_name: str = "mock",
        model_name: str = "mock-seo-competitor-profile-v1",
        prompt_version: str = "seo-competitor-profile-v1",
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.prompt_version = prompt_version

    def generate_competitor_profiles(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
        reduced_context_mode: bool = False,
        seed_candidates: list[dict[str, object]] | None = None,
    ) -> SEOCompetitorProfileGenerationOutput:
        del reduced_context_mode, seed_candidates
        existing = {item.strip().lower() for item in existing_domains if item.strip()}
        normalized_domain = (site.normalized_domain or "").strip().lower() or "example.com"
        root = normalized_domain.split(".")[0] or "example"
        seed_candidates: list[SEOCompetitorProfileDraftCandidateOutput] = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name=f"{site.display_name} Alternatives",
                suggested_domain=f"{root}-alternatives.com",
                competitor_type="direct",
                summary=f"Likely local alternative to {site.display_name} with overlapping service intent.",
                why_competitor="Competes for high-intent searches around core service terms.",
                evidence=f"Domain pattern and naming indicate direct overlap with {normalized_domain}.",
                confidence_score=0.86,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name=f"{site.display_name} Regional",
                suggested_domain=f"{root}regional.com",
                competitor_type="local",
                summary="Regional competitor likely targeting the same location-driven queries.",
                why_competitor="Regional players often overlap in local-pack and service-area SERPs.",
                evidence="Heuristic generation based on site naming + location-oriented positioning.",
                confidence_score=0.74,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name=f"{site.display_name} Marketplace",
                suggested_domain=f"{root}marketplace.com",
                competitor_type="marketplace",
                summary="Marketplace-style competitor aggregating similar services.",
                why_competitor="Marketplace aggregators can displace direct providers in non-branded queries.",
                evidence="Common marketplace naming pattern for this service category.",
                confidence_score=0.62,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name=f"{site.display_name} Insights",
                suggested_domain=f"{root}insights.com",
                competitor_type="informational",
                summary="Informational publisher that may compete for discovery-stage SEO traffic.",
                why_competitor="Informational domains can capture top-of-funnel terms and reduce site visibility.",
                evidence="Keyword and intent overlap at research-oriented query stages.",
                confidence_score=0.55,
            ),
        ]
        filtered = [candidate for candidate in seed_candidates if candidate.suggested_domain.lower() not in existing]
        candidates = filtered[: max(1, candidate_count)]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )


class MockSEORecommendationNarrativeProvider:
    def __init__(
        self,
        *,
        provider_name: str = "mock",
        model_name: str = "mock-seo-recommendation-narrative-v1",
        prompt_version: str = "seo-recommendation-narrative-v2",
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.prompt_version = prompt_version

    def generate_narrative(
        self,
        *,
        run: SEORecommendationRun,
        recommendations: list[SEORecommendation],
        by_status: dict[str, int],
        by_category: dict[str, int],
        by_severity: dict[str, int],
        by_effort_bucket: dict[str, int],
        by_priority_band: dict[str, int],
        backlog: list[SEORecommendation],
        competitor_telemetry_summary: dict[str, object],
        current_tuning_values: dict[str, int],
        competitor_context: dict[str, object] | None = None,
    ) -> SEORecommendationNarrativeOutput:
        del competitor_telemetry_summary, competitor_context, current_tuning_values
        total = len(recommendations)
        backlog_total = len(backlog)
        dominant_category = max(by_category.items(), key=lambda item: item[1])[0] if by_category else "TECHNICAL"
        dominant_severity = max(by_severity.items(), key=lambda item: item[1])[0] if by_severity else "INFO"
        highest_priority_open = backlog[0].title if backlog else "No actionable recommendations currently open."

        narrative = (
            f"Recommendation run {run.id} contains {total} deterministic recommendations. "
            f"Current actionable backlog is {backlog_total}. "
            f"Most concentrated category is {dominant_category} and most common severity is {dominant_severity}. "
            f"Top backlog focus: {highest_priority_open}"
        )
        top_themes = [
            f"Backlog items: {backlog_total}",
            f"Dominant category: {dominant_category}",
            f"Dominant severity: {dominant_severity}",
        ]
        sections: dict[str, object] = {
            "status_rollup": by_status,
            "category_rollup": by_category,
            "severity_rollup": by_severity,
            "effort_rollup": by_effort_bucket,
            "priority_band_rollup": by_priority_band,
            "backlog_rule_keys": [item.rule_key for item in backlog[:10]],
            "tuning_suggestions": [],
        }
        return SEORecommendationNarrativeOutput(
            narrative_text=narrative,
            top_themes=top_themes,
            sections=sections,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )

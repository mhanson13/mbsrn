from __future__ import annotations

from dataclasses import dataclass
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.integrations.seo_summary_provider import SEOCompetitorComparisonSummaryProvider
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_competitor_summary_repository import SEOCompetitorSummaryRepository


logger = logging.getLogger(__name__)


class SEOCompetitorSummaryNotFoundError(ValueError):
    pass


class SEOCompetitorSummaryValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEOCompetitorSummaryResult:
    summary: SEOCompetitorComparisonSummary


class SEOCompetitorSummaryService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_competitor_repository: SEOCompetitorRepository,
        seo_competitor_summary_repository: SEOCompetitorSummaryRepository,
        provider: SEOCompetitorComparisonSummaryProvider,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_competitor_repository = seo_competitor_repository
        self.seo_competitor_summary_repository = seo_competitor_summary_repository
        self.provider = provider

    def summarize_run(
        self,
        *,
        business_id: str,
        comparison_run_id: str,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorSummaryResult:
        self._require_business(business_id)
        run = self._get_run_for_business(business_id=business_id, comparison_run_id=comparison_run_id)
        if run.status != "completed":
            raise SEOCompetitorSummaryValidationError("Comparison run must be completed before summarization")

        findings = self.seo_competitor_repository.list_comparison_findings_for_business_run(
            business_id,
            comparison_run_id,
        )
        version = self.seo_competitor_summary_repository.next_version(business_id, comparison_run_id)
        metric_rollups = self._normalize_metric_rollups(run.metric_rollups_json)
        findings_by_type = self._normalize_int_map(run.finding_type_counts_json)
        findings_by_category = self._normalize_int_map(run.category_counts_json)
        findings_by_severity = self._normalize_int_map(run.severity_counts_json)

        try:
            output = self.provider.generate_summary(
                run=run,
                findings=findings,
                metric_rollups=metric_rollups,
                findings_by_type=findings_by_type,
                findings_by_category=findings_by_category,
                findings_by_severity=findings_by_severity,
            )
            summary = SEOCompetitorComparisonSummary(
                id=str(uuid4()),
                business_id=business_id,
                site_id=run.site_id,
                competitor_set_id=run.competitor_set_id,
                comparison_run_id=run.id,
                version=version,
                status="completed",
                overall_gap_summary=output.overall_gap_summary,
                top_gaps_json=output.top_gaps,
                plain_english_explanation=output.plain_english_explanation,
                model_name=output.model_name,
                prompt_version=output.prompt_version,
                error_summary=None,
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_competitor_summary_repository.create(summary)
            self.session.commit()
            self.session.refresh(summary)
            return SEOCompetitorSummaryResult(summary=summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SEO competitor summary generation failed business_id=%s comparison_run_id=%s reason=%s",
                business_id,
                comparison_run_id,
                str(exc),
            )
            failed = SEOCompetitorComparisonSummary(
                id=str(uuid4()),
                business_id=business_id,
                site_id=run.site_id,
                competitor_set_id=run.competitor_set_id,
                comparison_run_id=run.id,
                version=version,
                status="failed",
                overall_gap_summary=None,
                top_gaps_json=[],
                plain_english_explanation=None,
                model_name="summary-provider-error",
                prompt_version="seo-competitor-summary-v1",
                error_summary=str(exc),
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_competitor_summary_repository.create(failed)
            self.session.commit()
            raise SEOCompetitorSummaryValidationError("Competitor summary generation failed") from exc

    def list_summaries(
        self,
        *,
        business_id: str,
        comparison_run_id: str,
    ) -> list[SEOCompetitorComparisonSummary]:
        self._require_business(business_id)
        self._get_run_for_business(business_id=business_id, comparison_run_id=comparison_run_id)
        return self.seo_competitor_summary_repository.list_for_business_run(business_id, comparison_run_id)

    def get_latest_summary(
        self,
        *,
        business_id: str,
        comparison_run_id: str,
    ) -> SEOCompetitorComparisonSummary:
        self._require_business(business_id)
        self._get_run_for_business(business_id=business_id, comparison_run_id=comparison_run_id)
        summary = self.seo_competitor_summary_repository.get_latest_for_business_run(
            business_id,
            comparison_run_id,
        )
        if summary is None:
            raise SEOCompetitorSummaryNotFoundError("Competitor summary not found")
        return summary

    def get_summary(
        self,
        *,
        business_id: str,
        summary_id: str,
    ) -> SEOCompetitorComparisonSummary:
        self._require_business(business_id)
        summary = self.seo_competitor_summary_repository.get_for_business(business_id, summary_id)
        if summary is None:
            raise SEOCompetitorSummaryNotFoundError("Competitor summary not found")
        return summary

    def _get_run_for_business(self, *, business_id: str, comparison_run_id: str):
        run = self.seo_competitor_repository.get_comparison_run_for_business(business_id, comparison_run_id)
        if run is None:
            raise SEOCompetitorSummaryNotFoundError("Competitor comparison run not found")
        return run

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorSummaryNotFoundError("Business not found")

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

    def _normalize_metric_rollups(self, raw: dict[str, object] | None) -> dict[str, dict[str, object]]:
        if not raw:
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized[key] = dict(value)
        return normalized

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary


class SEOCompetitorSummaryRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, summary: SEOCompetitorComparisonSummary) -> SEOCompetitorComparisonSummary:
        self.session.add(summary)
        self.session.flush()
        return summary

    def list_for_business_run(self, business_id: str, comparison_run_id: str) -> list[SEOCompetitorComparisonSummary]:
        stmt: Select[tuple[SEOCompetitorComparisonSummary]] = (
            select(SEOCompetitorComparisonSummary)
            .where(SEOCompetitorComparisonSummary.business_id == business_id)
            .where(SEOCompetitorComparisonSummary.comparison_run_id == comparison_run_id)
            .order_by(SEOCompetitorComparisonSummary.version.asc(), SEOCompetitorComparisonSummary.created_at.asc())
        )
        return list(self.session.scalars(stmt))

    def get_latest_for_business_run(
        self,
        business_id: str,
        comparison_run_id: str,
    ) -> SEOCompetitorComparisonSummary | None:
        stmt: Select[tuple[SEOCompetitorComparisonSummary]] = (
            select(SEOCompetitorComparisonSummary)
            .where(SEOCompetitorComparisonSummary.business_id == business_id)
            .where(SEOCompetitorComparisonSummary.comparison_run_id == comparison_run_id)
            .order_by(SEOCompetitorComparisonSummary.version.desc(), SEOCompetitorComparisonSummary.created_at.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_for_business(self, business_id: str, summary_id: str) -> SEOCompetitorComparisonSummary | None:
        stmt: Select[tuple[SEOCompetitorComparisonSummary]] = (
            select(SEOCompetitorComparisonSummary)
            .where(SEOCompetitorComparisonSummary.business_id == business_id)
            .where(SEOCompetitorComparisonSummary.id == summary_id)
        )
        return self.session.scalar(stmt)

    def next_version(self, business_id: str, comparison_run_id: str) -> int:
        stmt = (
            select(func.max(SEOCompetitorComparisonSummary.version))
            .where(SEOCompetitorComparisonSummary.business_id == business_id)
            .where(SEOCompetitorComparisonSummary.comparison_run_id == comparison_run_id)
        )
        max_version = self.session.scalar(stmt)
        return int(max_version or 0) + 1

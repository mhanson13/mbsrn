from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.seo_recommendation_narrative import SEORecommendationNarrative


class SEORecommendationNarrativeRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, narrative: SEORecommendationNarrative) -> SEORecommendationNarrative:
        self.session.add(narrative)
        self.session.flush()
        return narrative

    def list_for_business_run(
        self,
        business_id: str,
        recommendation_run_id: str,
    ) -> list[SEORecommendationNarrative]:
        stmt: Select[tuple[SEORecommendationNarrative]] = (
            select(SEORecommendationNarrative)
            .where(SEORecommendationNarrative.business_id == business_id)
            .where(SEORecommendationNarrative.recommendation_run_id == recommendation_run_id)
            .order_by(SEORecommendationNarrative.version.asc(), SEORecommendationNarrative.created_at.asc())
        )
        return list(self.session.scalars(stmt))

    def get_latest_for_business_run(
        self,
        business_id: str,
        recommendation_run_id: str,
    ) -> SEORecommendationNarrative | None:
        stmt: Select[tuple[SEORecommendationNarrative]] = (
            select(SEORecommendationNarrative)
            .where(SEORecommendationNarrative.business_id == business_id)
            .where(SEORecommendationNarrative.recommendation_run_id == recommendation_run_id)
            .order_by(SEORecommendationNarrative.version.desc(), SEORecommendationNarrative.created_at.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_for_business(self, business_id: str, narrative_id: str) -> SEORecommendationNarrative | None:
        stmt: Select[tuple[SEORecommendationNarrative]] = (
            select(SEORecommendationNarrative)
            .where(SEORecommendationNarrative.business_id == business_id)
            .where(SEORecommendationNarrative.id == narrative_id)
        )
        return self.session.scalar(stmt)

    def next_version(self, business_id: str, recommendation_run_id: str) -> int:
        stmt = (
            select(func.max(SEORecommendationNarrative.version))
            .where(SEORecommendationNarrative.business_id == business_id)
            .where(SEORecommendationNarrative.recommendation_run_id == recommendation_run_id)
        )
        max_version = self.session.scalar(stmt)
        return int(max_version or 0) + 1

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.integrations.seo_summary_provider import SEORecommendationNarrativeProvider
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_recommendation_narrative_repository import SEORecommendationNarrativeRepository
from app.repositories.seo_recommendation_repository import SEORecommendationRepository


logger = logging.getLogger(__name__)


class SEORecommendationNarrativeNotFoundError(ValueError):
    pass


class SEORecommendationNarrativeValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEORecommendationNarrativeResult:
    narrative: SEORecommendationNarrative


class SEORecommendationNarrativeService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_recommendation_repository: SEORecommendationRepository,
        seo_recommendation_narrative_repository: SEORecommendationNarrativeRepository,
        provider: SEORecommendationNarrativeProvider,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_recommendation_repository = seo_recommendation_repository
        self.seo_recommendation_narrative_repository = seo_recommendation_narrative_repository
        self.provider = provider

    def summarize_run(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
        created_by_principal_id: str | None,
    ) -> SEORecommendationNarrativeResult:
        self._require_business(business_id)
        run = self._get_run_for_business(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
        if run.status != "completed":
            raise SEORecommendationNarrativeValidationError(
                "Recommendation run must be completed before narrative generation"
            )

        recommendations = self.seo_recommendation_repository.list_recommendations_for_business_run(
            business_id,
            recommendation_run_id,
        )
        by_status, by_category, by_severity, by_effort_bucket, by_priority_band = self._summarize(recommendations)
        backlog = self._build_backlog(recommendations)

        version = self.seo_recommendation_narrative_repository.next_version(
            business_id,
            recommendation_run_id,
        )

        try:
            output = self.provider.generate_narrative(
                run=run,
                recommendations=recommendations,
                by_status=by_status,
                by_category=by_category,
                by_severity=by_severity,
                by_effort_bucket=by_effort_bucket,
                by_priority_band=by_priority_band,
                backlog=backlog,
            )
            narrative = SEORecommendationNarrative(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                recommendation_run_id=recommendation_run_id,
                version=version,
                status="completed",
                narrative_text=output.narrative_text,
                top_themes_json=output.top_themes,
                sections_json=output.sections,
                provider_name=output.provider_name,
                model_name=output.model_name,
                prompt_version=output.prompt_version,
                error_message=None,
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_recommendation_narrative_repository.create(narrative)
            self.session.commit()
            self.session.refresh(narrative)
            return SEORecommendationNarrativeResult(narrative=narrative)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SEO recommendation narrative generation failed business_id=%s site_id=%s recommendation_run_id=%s reason=%s",
                business_id,
                site_id,
                recommendation_run_id,
                str(exc),
            )
            failed = SEORecommendationNarrative(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                recommendation_run_id=recommendation_run_id,
                version=version,
                status="failed",
                narrative_text=None,
                top_themes_json=[],
                sections_json=None,
                provider_name="narrative-provider-error",
                model_name="narrative-provider-error",
                prompt_version="seo-recommendation-narrative-v1",
                error_message=str(exc),
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_recommendation_narrative_repository.create(failed)
            self.session.commit()
            raise SEORecommendationNarrativeValidationError("Recommendation narrative generation failed") from exc

    def list_narratives(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
    ) -> list[SEORecommendationNarrative]:
        self._require_business(business_id)
        self._get_run_for_business(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
        return self.seo_recommendation_narrative_repository.list_for_business_run(
            business_id,
            recommendation_run_id,
        )

    def get_latest_narrative(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
    ) -> SEORecommendationNarrative:
        self._require_business(business_id)
        self._get_run_for_business(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
        narrative = self.seo_recommendation_narrative_repository.get_latest_for_business_run(
            business_id,
            recommendation_run_id,
        )
        if narrative is None:
            raise SEORecommendationNarrativeNotFoundError("Recommendation narrative not found")
        return narrative

    def get_narrative(
        self,
        *,
        business_id: str,
        site_id: str,
        narrative_id: str,
    ) -> SEORecommendationNarrative:
        self._require_business(business_id)
        narrative = self.seo_recommendation_narrative_repository.get_for_business(business_id, narrative_id)
        if narrative is None or narrative.site_id != site_id:
            raise SEORecommendationNarrativeNotFoundError("Recommendation narrative not found")
        return narrative

    def _get_run_for_business(self, *, business_id: str, site_id: str, recommendation_run_id: str):
        run = self.seo_recommendation_repository.get_run_for_business(business_id, recommendation_run_id)
        if run is None or run.site_id != site_id:
            raise SEORecommendationNarrativeNotFoundError("SEO recommendation run not found")
        return run

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEORecommendationNarrativeNotFoundError("Business not found")

    def _summarize(
        self,
        recommendations: list[SEORecommendation],
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
        by_status = Counter()
        by_category = Counter()
        by_severity = Counter()
        by_effort_bucket = Counter()
        by_priority_band = Counter()
        for item in recommendations:
            by_status[(item.status or "").strip().lower() or "open"] += 1
            by_category[(item.category or "").strip().upper() or "TECHNICAL"] += 1
            by_severity[(item.severity or "").strip().upper() or "INFO"] += 1
            by_effort_bucket[(item.effort_bucket or "").strip().upper() or "MEDIUM"] += 1
            by_priority_band[(item.priority_band or "").strip().lower() or "medium"] += 1
        return (
            dict(sorted(by_status.items())),
            dict(sorted(by_category.items())),
            dict(sorted(by_severity.items())),
            dict(sorted(by_effort_bucket.items())),
            dict(sorted(by_priority_band.items())),
        )

    def _build_backlog(self, recommendations: list[SEORecommendation]) -> list[SEORecommendation]:
        actionable = [
            item
            for item in recommendations
            if (item.status or "").strip().lower() in {"open", "in_progress", "accepted"}
        ]
        return sorted(
            actionable,
            key=lambda rec: (
                -int(rec.priority_score or 0),
                (rec.created_at.isoformat() if rec.created_at is not None else ""),
                rec.id,
            ),
        )

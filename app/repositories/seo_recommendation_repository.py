from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, asc, case, desc, or_, select
from sqlalchemy.orm import Session

from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite


class SEORecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(self, run: SEORecommendationRun) -> SEORecommendationRun:
        site = self.session.scalar(
            select(SEOSite.id).where(SEOSite.business_id == run.business_id).where(SEOSite.id == run.site_id)
        )
        if site is None:
            raise ValueError("SEO site not found for business")

        if run.audit_run_id is not None:
            audit_run = self.session.scalar(select(SEOAuditRun).where(SEOAuditRun.id == run.audit_run_id))
            if audit_run is None:
                raise ValueError("Audit run not found")
            if audit_run.business_id != run.business_id or audit_run.site_id != run.site_id:
                raise ValueError("Audit run scope mismatch")

        if run.comparison_run_id is not None:
            comparison_run = self.session.scalar(
                select(SEOCompetitorComparisonRun).where(SEOCompetitorComparisonRun.id == run.comparison_run_id)
            )
            if comparison_run is None:
                raise ValueError("Comparison run not found")
            if comparison_run.business_id != run.business_id or comparison_run.site_id != run.site_id:
                raise ValueError("Comparison run scope mismatch")

        self.session.add(run)
        self.session.flush()
        return run

    def save_run(self, run: SEORecommendationRun) -> SEORecommendationRun:
        self.session.add(run)
        self.session.flush()
        return run

    def get_run_for_business(self, business_id: str, recommendation_run_id: str) -> SEORecommendationRun | None:
        stmt: Select[tuple[SEORecommendationRun]] = (
            select(SEORecommendationRun)
            .where(SEORecommendationRun.business_id == business_id)
            .where(SEORecommendationRun.id == recommendation_run_id)
        )
        return self.session.scalar(stmt)

    def list_runs_for_business_site(self, business_id: str, site_id: str) -> list[SEORecommendationRun]:
        stmt: Select[tuple[SEORecommendationRun]] = (
            select(SEORecommendationRun)
            .where(SEORecommendationRun.business_id == business_id)
            .where(SEORecommendationRun.site_id == site_id)
            .order_by(SEORecommendationRun.created_at.desc(), SEORecommendationRun.id.desc())
        )
        return list(self.session.scalars(stmt))

    def add_recommendation(self, recommendation: SEORecommendation) -> SEORecommendation:
        run = self.session.scalar(
            select(SEORecommendationRun).where(SEORecommendationRun.id == recommendation.recommendation_run_id)
        )
        if run is None:
            raise ValueError("Recommendation run not found")
        if run.business_id != recommendation.business_id or run.site_id != recommendation.site_id:
            raise ValueError("Recommendation scope mismatch")

        if run.audit_run_id is not None and recommendation.audit_run_id != run.audit_run_id:
            raise ValueError("Recommendation audit run mismatch")
        if run.comparison_run_id is not None and recommendation.comparison_run_id != run.comparison_run_id:
            raise ValueError("Recommendation comparison run mismatch")

        self.session.add(recommendation)
        self.session.flush()
        return recommendation

    def list_recommendations_for_business_run(
        self,
        business_id: str,
        recommendation_run_id: str,
    ) -> list[SEORecommendation]:
        stmt: Select[tuple[SEORecommendation]] = (
            select(SEORecommendation)
            .where(SEORecommendation.business_id == business_id)
            .where(SEORecommendation.recommendation_run_id == recommendation_run_id)
            .order_by(
                SEORecommendation.priority_score.desc(),
                SEORecommendation.created_at.asc(),
                SEORecommendation.id.asc(),
            )
        )
        return list(self.session.scalars(stmt))

    def get_recommendation_for_business(self, business_id: str, recommendation_id: str) -> SEORecommendation | None:
        stmt: Select[tuple[SEORecommendation]] = (
            select(SEORecommendation)
            .where(SEORecommendation.business_id == business_id)
            .where(SEORecommendation.id == recommendation_id)
        )
        return self.session.scalar(stmt)

    def save_recommendation(self, recommendation: SEORecommendation) -> SEORecommendation:
        self.session.add(recommendation)
        self.session.flush()
        return recommendation

    def list_recommendations_for_business_site(
        self,
        *,
        business_id: str,
        site_id: str,
        status: str | None = None,
        status_in: list[str] | None = None,
        category: str | None = None,
        severity: str | None = None,
        effort_bucket: str | None = None,
        priority_band: str | None = None,
        assigned_principal_id: str | None = None,
        source_type: str | None = None,
        recommendation_run_id: str | None = None,
        sort_by: str = "priority_score",
        sort_order: str = "desc",
    ) -> list[SEORecommendation]:
        stmt: Select[tuple[SEORecommendation]] = (
            select(SEORecommendation)
            .where(SEORecommendation.business_id == business_id)
            .where(SEORecommendation.site_id == site_id)
        )

        if status is not None:
            stmt = stmt.where(SEORecommendation.status == status)
        if status_in:
            stmt = stmt.where(SEORecommendation.status.in_(status_in))
        if category is not None:
            stmt = stmt.where(SEORecommendation.category == category)
        if severity is not None:
            stmt = stmt.where(SEORecommendation.severity == severity)
        if effort_bucket is not None:
            stmt = stmt.where(SEORecommendation.effort_bucket == effort_bucket)
        if priority_band is not None:
            stmt = stmt.where(SEORecommendation.priority_band == priority_band)
        if assigned_principal_id is not None:
            stmt = stmt.where(SEORecommendation.assigned_principal_id == assigned_principal_id)
        if recommendation_run_id is not None:
            stmt = stmt.where(SEORecommendation.recommendation_run_id == recommendation_run_id)

        if source_type == "audit":
            stmt = stmt.where(SEORecommendation.audit_run_id.is_not(None)).where(
                SEORecommendation.comparison_run_id.is_(None)
            )
        elif source_type == "comparison":
            stmt = stmt.where(SEORecommendation.comparison_run_id.is_not(None)).where(
                SEORecommendation.audit_run_id.is_(None)
            )
        elif source_type == "mixed":
            stmt = stmt.where(SEORecommendation.audit_run_id.is_not(None)).where(
                SEORecommendation.comparison_run_id.is_not(None)
            )

        order_column = self._resolve_sort_column(sort_by)
        order_fn = asc if sort_order.lower() == "asc" else desc
        stmt = stmt.order_by(
            order_fn(order_column),
            desc(SEORecommendation.priority_score),
            asc(SEORecommendation.created_at),
            asc(SEORecommendation.id),
        )
        return list(self.session.scalars(stmt))

    def list_actionable_recommendations_for_business_site(
        self,
        *,
        business_id: str,
        site_id: str,
        now: datetime,
    ) -> list[SEORecommendation]:
        severity_rank = case(
            (SEORecommendation.severity == "CRITICAL", 3),
            (SEORecommendation.severity == "WARNING", 2),
            else_=1,
        )
        stmt: Select[tuple[SEORecommendation]] = (
            select(SEORecommendation)
            .where(SEORecommendation.business_id == business_id)
            .where(SEORecommendation.site_id == site_id)
            .where(
                or_(
                    SEORecommendation.status.in_(["open", "in_progress", "accepted"]),
                    and_(
                        SEORecommendation.status == "snoozed",
                        SEORecommendation.snoozed_until.is_not(None),
                        SEORecommendation.snoozed_until <= now,
                    ),
                )
            )
            .order_by(
                desc(SEORecommendation.priority_score),
                desc(severity_rank),
                asc(SEORecommendation.due_at),
                asc(SEORecommendation.created_at),
                asc(SEORecommendation.id),
            )
        )
        return list(self.session.scalars(stmt))

    def _resolve_sort_column(self, sort_by: str):
        if sort_by == "severity":
            return case(
                (SEORecommendation.severity == "CRITICAL", 3),
                (SEORecommendation.severity == "WARNING", 2),
                else_=1,
            )
        if sort_by == "priority_band":
            return case(
                (SEORecommendation.priority_band == "critical", 4),
                (SEORecommendation.priority_band == "high", 3),
                (SEORecommendation.priority_band == "medium", 2),
                else_=1,
            )
        if sort_by == "created_at":
            return SEORecommendation.created_at
        if sort_by == "updated_at":
            return SEORecommendation.updated_at
        if sort_by == "due_at":
            return SEORecommendation.due_at
        return SEORecommendation.priority_score

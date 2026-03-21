from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun


class SEOCompetitorProfileGenerationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(
        self,
        run: SEOCompetitorProfileGenerationRun,
    ) -> SEOCompetitorProfileGenerationRun:
        self.session.add(run)
        self.session.flush()
        return run

    def save_run(
        self,
        run: SEOCompetitorProfileGenerationRun,
    ) -> SEOCompetitorProfileGenerationRun:
        self.session.add(run)
        self.session.flush()
        return run

    def list_runs_for_business_site(
        self,
        business_id: str,
        site_id: str,
    ) -> list[SEOCompetitorProfileGenerationRun]:
        stmt: Select[tuple[SEOCompetitorProfileGenerationRun]] = (
            select(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .order_by(
                SEOCompetitorProfileGenerationRun.created_at.desc(),
                SEOCompetitorProfileGenerationRun.id.desc(),
            )
        )
        return list(self.session.scalars(stmt))

    def get_run_for_business(
        self,
        business_id: str,
        generation_run_id: str,
    ) -> SEOCompetitorProfileGenerationRun | None:
        stmt: Select[tuple[SEOCompetitorProfileGenerationRun]] = (
            select(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.id == generation_run_id)
        )
        return self.session.scalar(stmt)

    def create_draft(self, draft: SEOCompetitorProfileDraft) -> SEOCompetitorProfileDraft:
        self.session.add(draft)
        self.session.flush()
        return draft

    def save_draft(self, draft: SEOCompetitorProfileDraft) -> SEOCompetitorProfileDraft:
        self.session.add(draft)
        self.session.flush()
        return draft

    def list_drafts_for_business_run(
        self,
        business_id: str,
        generation_run_id: str,
    ) -> list[SEOCompetitorProfileDraft]:
        stmt: Select[tuple[SEOCompetitorProfileDraft]] = (
            select(SEOCompetitorProfileDraft)
            .where(SEOCompetitorProfileDraft.business_id == business_id)
            .where(SEOCompetitorProfileDraft.generation_run_id == generation_run_id)
            .order_by(
                SEOCompetitorProfileDraft.confidence_score.desc(),
                SEOCompetitorProfileDraft.created_at.asc(),
                SEOCompetitorProfileDraft.id.asc(),
            )
        )
        return list(self.session.scalars(stmt))

    def get_draft_for_business_run(
        self,
        business_id: str,
        generation_run_id: str,
        draft_id: str,
    ) -> SEOCompetitorProfileDraft | None:
        stmt: Select[tuple[SEOCompetitorProfileDraft]] = (
            select(SEOCompetitorProfileDraft)
            .where(SEOCompetitorProfileDraft.business_id == business_id)
            .where(SEOCompetitorProfileDraft.generation_run_id == generation_run_id)
            .where(SEOCompetitorProfileDraft.id == draft_id)
        )
        return self.session.scalar(stmt)

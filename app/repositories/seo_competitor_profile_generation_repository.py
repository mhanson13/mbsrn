from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, case, delete, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.core.time import utc_now
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
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

    def list_runs_for_business_site_created_after(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> list[SEOCompetitorProfileGenerationRun]:
        stmt: Select[tuple[SEOCompetitorProfileGenerationRun]] = (
            select(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .where(SEOCompetitorProfileGenerationRun.created_at >= created_after)
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

    def claim_run_for_execution(
        self,
        business_id: str,
        generation_run_id: str,
    ) -> bool:
        stmt = (
            update(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.id == generation_run_id)
            .where(SEOCompetitorProfileGenerationRun.status == "queued")
            .values(
                status="running",
                generated_draft_count=0,
                raw_candidate_count=0,
                included_candidate_count=0,
                excluded_candidate_count=0,
                exclusion_counts_by_reason={},
                error_summary=None,
                failure_category=None,
                raw_output=None,
                completed_at=None,
                updated_at=utc_now(),
            )
        )
        result = self.session.execute(stmt)
        return bool(result.rowcount)

    def list_stale_runs_for_business_site(
        self,
        business_id: str,
        site_id: str,
        *,
        status: str,
        updated_before: datetime,
    ) -> list[SEOCompetitorProfileGenerationRun]:
        stmt: Select[tuple[SEOCompetitorProfileGenerationRun]] = (
            select(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .where(SEOCompetitorProfileGenerationRun.status == status)
            .where(SEOCompetitorProfileGenerationRun.updated_at < updated_before)
            .order_by(
                SEOCompetitorProfileGenerationRun.updated_at.asc(),
                SEOCompetitorProfileGenerationRun.id.asc(),
            )
        )
        return list(self.session.scalars(stmt))

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
                SEOCompetitorProfileDraft.relevance_score.desc(),
                SEOCompetitorProfileDraft.suggested_name.asc(),
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

    def summarize_run_status_counts(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> dict[str, int]:
        stmt = (
            select(
                SEOCompetitorProfileGenerationRun.status,
                func.count(SEOCompetitorProfileGenerationRun.id),
            )
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .where(SEOCompetitorProfileGenerationRun.created_at >= created_after)
            .group_by(SEOCompetitorProfileGenerationRun.status)
        )
        rows = self.session.execute(stmt).all()
        return {str(status): int(count) for status, count in rows}

    def summarize_failure_category_counts(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> dict[str, int]:
        stmt = (
            select(
                SEOCompetitorProfileGenerationRun.failure_category,
                func.count(SEOCompetitorProfileGenerationRun.id),
            )
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .where(SEOCompetitorProfileGenerationRun.created_at >= created_after)
            .where(SEOCompetitorProfileGenerationRun.status == "failed")
            .where(SEOCompetitorProfileGenerationRun.failure_category.is_not(None))
            .group_by(SEOCompetitorProfileGenerationRun.failure_category)
        )
        rows = self.session.execute(stmt).all()
        return {
            str(failure_category): int(count)
            for failure_category, count in rows
            if failure_category is not None
        }

    def count_retry_child_runs(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> int:
        stmt = (
            select(func.count(SEOCompetitorProfileGenerationRun.id))
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .where(SEOCompetitorProfileGenerationRun.created_at >= created_after)
            .where(SEOCompetitorProfileGenerationRun.parent_run_id.is_not(None))
        )
        return int(self.session.scalar(stmt) or 0)

    def count_distinct_retry_parents(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> int:
        stmt = (
            select(func.count(func.distinct(SEOCompetitorProfileGenerationRun.parent_run_id)))
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.site_id == site_id)
            .where(SEOCompetitorProfileGenerationRun.created_at >= created_after)
            .where(SEOCompetitorProfileGenerationRun.parent_run_id.is_not(None))
        )
        return int(self.session.scalar(stmt) or 0)

    def count_failed_runs_retried(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> int:
        parent_run = aliased(SEOCompetitorProfileGenerationRun)
        child_run = aliased(SEOCompetitorProfileGenerationRun)
        stmt = (
            select(func.count(func.distinct(parent_run.id)))
            .select_from(parent_run)
            .join(
                child_run,
                and_(
                    child_run.business_id == parent_run.business_id,
                    child_run.parent_run_id == parent_run.id,
                ),
            )
            .where(parent_run.business_id == business_id)
            .where(parent_run.site_id == site_id)
            .where(parent_run.status == "failed")
            .where(child_run.site_id == site_id)
            .where(child_run.created_at >= created_after)
        )
        return int(self.session.scalar(stmt) or 0)

    def summarize_run_latest_timestamps(
        self,
        *,
        business_id: str,
        site_id: str,
        created_after: datetime,
    ) -> tuple[datetime | None, datetime | None, datetime | None, datetime | None]:
        stmt = select(
            func.max(SEOCompetitorProfileGenerationRun.created_at),
            func.max(SEOCompetitorProfileGenerationRun.completed_at),
            func.max(
                case(
                    (SEOCompetitorProfileGenerationRun.status == "completed", SEOCompetitorProfileGenerationRun.completed_at),
                    else_=None,
                )
            ),
            func.max(
                case(
                    (SEOCompetitorProfileGenerationRun.status == "failed", SEOCompetitorProfileGenerationRun.completed_at),
                    else_=None,
                )
            ),
        ).where(
            SEOCompetitorProfileGenerationRun.business_id == business_id,
            SEOCompetitorProfileGenerationRun.site_id == site_id,
            SEOCompetitorProfileGenerationRun.created_at >= created_after,
        )
        row = self.session.execute(stmt).one()
        return (
            row[0],
            row[1],
            row[2],
            row[3],
        )

    def create_cleanup_execution(
        self,
        execution: SEOCompetitorProfileCleanupExecution,
    ) -> SEOCompetitorProfileCleanupExecution:
        self.session.add(execution)
        self.session.flush()
        return execution

    def save_cleanup_execution(
        self,
        execution: SEOCompetitorProfileCleanupExecution,
    ) -> SEOCompetitorProfileCleanupExecution:
        self.session.add(execution)
        self.session.flush()
        return execution

    def get_latest_cleanup_execution_for_business_scope(
        self,
        *,
        business_id: str,
        site_id: str | None,
    ) -> SEOCompetitorProfileCleanupExecution | None:
        stmt = select(SEOCompetitorProfileCleanupExecution).where(
            SEOCompetitorProfileCleanupExecution.business_id == business_id
        )
        if site_id is None:
            stmt = stmt.where(SEOCompetitorProfileCleanupExecution.site_id.is_(None))
        else:
            stmt = stmt.where(SEOCompetitorProfileCleanupExecution.site_id == site_id)
        stmt = stmt.order_by(
            SEOCompetitorProfileCleanupExecution.started_at.desc(),
            SEOCompetitorProfileCleanupExecution.id.desc(),
        )
        return self.session.scalar(stmt)

    def count_cleanup_executions_by_status(
        self,
        *,
        business_id: str,
        site_id: str | None,
        started_after: datetime,
    ) -> dict[str, int]:
        stmt = (
            select(
                SEOCompetitorProfileCleanupExecution.status,
                func.count(SEOCompetitorProfileCleanupExecution.id),
            )
            .where(SEOCompetitorProfileCleanupExecution.business_id == business_id)
            .where(SEOCompetitorProfileCleanupExecution.started_at >= started_after)
            .group_by(SEOCompetitorProfileCleanupExecution.status)
        )
        if site_id is None:
            stmt = stmt.where(SEOCompetitorProfileCleanupExecution.site_id.is_(None))
        else:
            stmt = stmt.where(SEOCompetitorProfileCleanupExecution.site_id == site_id)
        rows = self.session.execute(stmt).all()
        return {str(status): int(count) for status, count in rows}

    def prune_raw_output_for_terminal_runs(
        self,
        *,
        business_id: str,
        completed_before: datetime,
        site_id: str | None = None,
    ) -> int:
        terminal_completed_before = or_(
            SEOCompetitorProfileGenerationRun.completed_at < completed_before,
            and_(
                SEOCompetitorProfileGenerationRun.completed_at.is_(None),
                SEOCompetitorProfileGenerationRun.updated_at < completed_before,
            ),
        )
        stmt = (
            update(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.status.in_(["completed", "failed"]))
            .where(SEOCompetitorProfileGenerationRun.raw_output.is_not(None))
            .where(terminal_completed_before)
            .values(raw_output=None, updated_at=utc_now())
        )
        if site_id:
            stmt = stmt.where(SEOCompetitorProfileGenerationRun.site_id == site_id)
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def prune_rejected_drafts(
        self,
        *,
        business_id: str,
        reviewed_before: datetime,
        site_id: str | None = None,
    ) -> int:
        terminal_runs_stmt = (
            select(SEOCompetitorProfileGenerationRun.id)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.status.in_(["completed", "failed"]))
        )
        if site_id:
            terminal_runs_stmt = terminal_runs_stmt.where(SEOCompetitorProfileGenerationRun.site_id == site_id)

        reviewed_before_condition = or_(
            SEOCompetitorProfileDraft.reviewed_at < reviewed_before,
            and_(
                SEOCompetitorProfileDraft.reviewed_at.is_(None),
                SEOCompetitorProfileDraft.updated_at < reviewed_before,
            ),
        )
        stmt = (
            delete(SEOCompetitorProfileDraft)
            .where(SEOCompetitorProfileDraft.business_id == business_id)
            .where(SEOCompetitorProfileDraft.review_status == "rejected")
            .where(SEOCompetitorProfileDraft.accepted_competitor_set_id.is_(None))
            .where(SEOCompetitorProfileDraft.accepted_competitor_domain_id.is_(None))
            .where(reviewed_before_condition)
            .where(SEOCompetitorProfileDraft.generation_run_id.in_(terminal_runs_stmt))
        )
        if site_id:
            stmt = stmt.where(SEOCompetitorProfileDraft.site_id == site_id)
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def prune_terminal_runs_without_drafts(
        self,
        *,
        business_id: str,
        updated_before: datetime,
        site_id: str | None = None,
    ) -> int:
        candidates_stmt = (
            select(SEOCompetitorProfileGenerationRun.id)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.status.in_(["completed", "failed"]))
            .where(SEOCompetitorProfileGenerationRun.generated_draft_count == 0)
            .where(SEOCompetitorProfileGenerationRun.updated_at < updated_before)
        )
        if site_id:
            candidates_stmt = candidates_stmt.where(SEOCompetitorProfileGenerationRun.site_id == site_id)
        candidate_ids = list(self.session.scalars(candidates_stmt))
        if not candidate_ids:
            return 0

        draft_run_ids = set(
            self.session.scalars(
                select(SEOCompetitorProfileDraft.generation_run_id)
                .where(SEOCompetitorProfileDraft.business_id == business_id)
                .where(SEOCompetitorProfileDraft.generation_run_id.in_(candidate_ids))
            )
        )
        parent_run_ids = set(
            item
            for item in self.session.scalars(
                select(SEOCompetitorProfileGenerationRun.parent_run_id)
                .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
                .where(SEOCompetitorProfileGenerationRun.parent_run_id.in_(candidate_ids))
            )
            if item is not None
        )
        deletable_ids = [run_id for run_id in candidate_ids if run_id not in draft_run_ids and run_id not in parent_run_ids]
        if not deletable_ids:
            return 0

        stmt = (
            delete(SEOCompetitorProfileGenerationRun)
            .where(SEOCompetitorProfileGenerationRun.business_id == business_id)
            .where(SEOCompetitorProfileGenerationRun.id.in_(deletable_ids))
        )
        if site_id:
            stmt = stmt.where(SEOCompetitorProfileGenerationRun.site_id == site_id)
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

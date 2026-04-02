from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.seo_automation_config import SEOAutomationConfig
from app.models.seo_automation_run import SEOAutomationRun
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_automation_repository import SEOAutomationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_audit import SEOAuditRunCreateRequest
from app.schemas.seo_automation import SEOAutomationConfigPatchRequest, SEOAutomationConfigUpsertRequest
from app.schemas.seo_competitor import SEOCompetitorComparisonRunCreateRequest, SEOCompetitorSnapshotRunCreateRequest
from app.schemas.seo_recommendation import SEORecommendationRunCreateRequest
from app.services.seo_audit import SEOAuditNotFoundError, SEOAuditService, SEOAuditValidationError
from app.services.seo_competitor_comparison import (
    SEOCompetitorComparisonNotFoundError,
    SEOCompetitorComparisonService,
    SEOCompetitorComparisonValidationError,
)
from app.services.seo_competitor_summary import (
    SEOCompetitorSummaryNotFoundError,
    SEOCompetitorSummaryService,
    SEOCompetitorSummaryValidationError,
)
from app.services.seo_competitors import SEOCompetitorNotFoundError, SEOCompetitorService, SEOCompetitorValidationError
from app.services.seo_recommendation_narratives import (
    SEORecommendationNarrativeNotFoundError,
    SEORecommendationNarrativeService,
    SEORecommendationNarrativeValidationError,
)
from app.services.seo_recommendations import (
    SEORecommendationNotFoundError,
    SEORecommendationService,
    SEORecommendationValidationError,
)
from app.services.seo_summary import SEOSummaryNotFoundError, SEOSummaryService, SEOSummaryValidationError


logger = logging.getLogger(__name__)


STEP_AUDIT_RUN = "audit_run"
STEP_AUDIT_SUMMARY = "audit_summary"
STEP_COMPETITOR_SNAPSHOT_RUN = "competitor_snapshot_run"
STEP_COMPARISON_RUN = "comparison_run"
STEP_COMPETITOR_SUMMARY = "competitor_summary"
STEP_RECOMMENDATION_RUN = "recommendation_run"
STEP_RECOMMENDATION_NARRATIVE = "recommendation_narrative"

ACTIVE_RUN_STATUSES = {"queued", "running"}
FAILED_STEP_STATUS = "failed"
COMPLETED_STEP_STATUS = "completed"
SKIPPED_STEP_STATUS = "skipped"


class SEOAutomationNotFoundError(ValueError):
    pass


class SEOAutomationValidationError(ValueError):
    pass


class SEOAutomationConflictError(ValueError):
    pass


@dataclass(frozen=True)
class SEOAutomationDueRunSummary:
    scanned_configs: int
    triggered_runs: int
    skipped_active_runs: int
    failed_triggers: int


class SEOAutomationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_automation_repository: SEOAutomationRepository,
        seo_audit_service: SEOAuditService,
        seo_summary_service: SEOSummaryService,
        seo_competitor_service: SEOCompetitorService,
        seo_competitor_comparison_service: SEOCompetitorComparisonService,
        seo_competitor_summary_service: SEOCompetitorSummaryService,
        seo_recommendation_service: SEORecommendationService,
        seo_recommendation_narrative_service: SEORecommendationNarrativeService,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_automation_repository = seo_automation_repository
        self.seo_audit_service = seo_audit_service
        self.seo_summary_service = seo_summary_service
        self.seo_competitor_service = seo_competitor_service
        self.seo_competitor_comparison_service = seo_competitor_comparison_service
        self.seo_competitor_summary_service = seo_competitor_summary_service
        self.seo_recommendation_service = seo_recommendation_service
        self.seo_recommendation_narrative_service = seo_recommendation_narrative_service

    def create_or_replace_config(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOAutomationConfigUpsertRequest,
    ) -> SEOAutomationConfig:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)

        config = self.seo_automation_repository.get_config_for_business_site(business_id, site_id)
        now = utc_now()
        if config is None:
            config = SEOAutomationConfig(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                is_enabled=payload.is_enabled,
                cadence_type=payload.cadence_type,
                cadence_minutes=payload.cadence_minutes,
                trigger_audit=payload.trigger_audit,
                trigger_audit_summary=payload.trigger_audit_summary,
                trigger_competitor_snapshot=payload.trigger_competitor_snapshot,
                trigger_comparison=payload.trigger_comparison,
                trigger_competitor_summary=payload.trigger_competitor_summary,
                trigger_recommendations=payload.trigger_recommendations,
                trigger_recommendation_narrative=payload.trigger_recommendation_narrative,
                next_run_at=self._calculate_next_run_at(
                    now=now,
                    is_enabled=payload.is_enabled,
                    cadence_type=payload.cadence_type,
                    cadence_minutes=payload.cadence_minutes,
                ),
            )
            try:
                self.seo_automation_repository.create_config(config)
                self.session.commit()
            except Exception as exc:  # noqa: BLE001
                self.session.rollback()
                raise SEOAutomationValidationError("Failed to create automation config") from exc
        else:
            config.is_enabled = payload.is_enabled
            config.cadence_type = payload.cadence_type
            config.cadence_minutes = payload.cadence_minutes
            config.trigger_audit = payload.trigger_audit
            config.trigger_audit_summary = payload.trigger_audit_summary
            config.trigger_competitor_snapshot = payload.trigger_competitor_snapshot
            config.trigger_comparison = payload.trigger_comparison
            config.trigger_competitor_summary = payload.trigger_competitor_summary
            config.trigger_recommendations = payload.trigger_recommendations
            config.trigger_recommendation_narrative = payload.trigger_recommendation_narrative
            config.next_run_at = self._calculate_next_run_at(
                now=now,
                is_enabled=config.is_enabled,
                cadence_type=config.cadence_type,
                cadence_minutes=config.cadence_minutes,
            )
            try:
                self.seo_automation_repository.save_config(config)
                self.session.commit()
            except Exception as exc:  # noqa: BLE001
                self.session.rollback()
                raise SEOAutomationValidationError("Failed to update automation config") from exc

        self.session.refresh(config)
        return config

    def get_config(self, *, business_id: str, site_id: str) -> SEOAutomationConfig:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        config = self.seo_automation_repository.get_config_for_business_site(business_id, site_id)
        if config is None:
            raise SEOAutomationNotFoundError("SEO automation config not found")
        return config

    def update_config(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOAutomationConfigPatchRequest,
    ) -> SEOAutomationConfig:
        config = self.get_config(business_id=business_id, site_id=site_id)
        updates = payload.model_dump(exclude_unset=True)
        now = utc_now()

        cadence_changed = False
        enabled_changed = False
        for key, value in updates.items():
            setattr(config, key, value)
            if key in {"cadence_type", "cadence_minutes"}:
                cadence_changed = True
            if key == "is_enabled":
                enabled_changed = True

        self._validate_effective_config(config)

        if not config.is_enabled:
            config.next_run_at = None
        elif config.cadence_type == "interval_minutes":
            if enabled_changed or cadence_changed or config.next_run_at is None:
                config.next_run_at = now + timedelta(minutes=int(config.cadence_minutes or 0))
        else:
            config.next_run_at = None

        try:
            self.seo_automation_repository.save_config(config)
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            raise SEOAutomationValidationError("Failed to update automation config") from exc

        self.session.refresh(config)
        return config

    def set_config_enabled(
        self,
        *,
        business_id: str,
        site_id: str,
        is_enabled: bool,
    ) -> SEOAutomationConfig:
        patch = SEOAutomationConfigPatchRequest(is_enabled=is_enabled)
        return self.update_config(business_id=business_id, site_id=site_id, payload=patch)

    def trigger_manual_run(
        self,
        *,
        business_id: str,
        site_id: str,
        created_by_principal_id: str | None,
    ) -> SEOAutomationRun:
        config = self.get_config(business_id=business_id, site_id=site_id)
        return self._start_run(config=config, trigger_source="manual", created_by_principal_id=created_by_principal_id)

    def list_runs(self, *, business_id: str, site_id: str) -> list[SEOAutomationRun]:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        return self.seo_automation_repository.list_runs_for_business_site(business_id, site_id)

    def get_run(self, *, business_id: str, site_id: str, automation_run_id: str) -> SEOAutomationRun:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        run = self.seo_automation_repository.get_run_for_business_site(business_id, site_id, automation_run_id)
        if run is None:
            raise SEOAutomationNotFoundError("SEO automation run not found")
        return run

    def get_status(self, *, business_id: str, site_id: str) -> tuple[SEOAutomationConfig, SEOAutomationRun | None]:
        config = self.get_config(business_id=business_id, site_id=site_id)
        runs = self.seo_automation_repository.list_runs_for_business_site(business_id, site_id)
        latest_run = runs[0] if runs else None
        return config, latest_run

    def run_due_configs(self, *, limit: int = 25, business_id: str | None = None) -> SEOAutomationDueRunSummary:
        now = utc_now()
        if business_id is not None:
            self._require_business(business_id)
        configs = self.seo_automation_repository.list_due_configs(
            now=now,
            limit=limit,
            business_id=business_id,
        )
        triggered_runs = 0
        skipped_active_runs = 0
        failed_triggers = 0

        for config in configs:
            active = self.seo_automation_repository.get_active_run_for_business_site(config.business_id, config.site_id)
            if active is not None:
                skipped_active_runs += 1
                continue
            try:
                self._start_run(config=config, trigger_source="scheduled", created_by_principal_id=None)
                triggered_runs += 1
            except SEOAutomationConflictError:
                skipped_active_runs += 1
            except Exception:  # noqa: BLE001
                failed_triggers += 1

        return SEOAutomationDueRunSummary(
            scanned_configs=len(configs),
            triggered_runs=triggered_runs,
            skipped_active_runs=skipped_active_runs,
            failed_triggers=failed_triggers,
        )

    def _start_run(
        self,
        *,
        config: SEOAutomationConfig,
        trigger_source: str,
        created_by_principal_id: str | None,
    ) -> SEOAutomationRun:
        self._ensure_no_active_run(config.business_id, config.site_id)

        run = SEOAutomationRun(
            id=str(uuid4()),
            business_id=config.business_id,
            site_id=config.site_id,
            automation_config_id=config.id,
            trigger_source=trigger_source,
            status="queued",
            steps_json=self._initial_steps(),
        )
        try:
            self.seo_automation_repository.create_run(run)
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            raise SEOAutomationValidationError("Failed to create automation run") from exc

        logger.info(
            "SEO automation run queued business_id=%s site_id=%s automation_run_id=%s trigger_source=%s",
            config.business_id,
            config.site_id,
            run.id,
            trigger_source,
        )

        return self._execute_run(run=run, config=config, created_by_principal_id=created_by_principal_id)

    def _execute_run(
        self,
        *,
        run: SEOAutomationRun,
        config: SEOAutomationConfig,
        created_by_principal_id: str | None,
    ) -> SEOAutomationRun:
        run.status = "running"
        run.started_at = utc_now()
        run.error_message = None
        self.seo_automation_repository.save_run(run)
        self.session.commit()

        logger.info(
            "SEO automation run started business_id=%s site_id=%s automation_run_id=%s",
            run.business_id,
            run.site_id,
            run.id,
        )

        context: dict[str, str] = {}

        audit_run_id = self._run_step(
            run=run,
            step_name=STEP_AUDIT_RUN,
            enabled=config.trigger_audit,
            disabled_reason="Audit step disabled by config",
            action=lambda: self._execute_audit_step(
                business_id=run.business_id,
                site_id=run.site_id,
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if audit_run_id is not None:
            context["audit_run_id"] = audit_run_id

        audit_summary_id = self._run_step(
            run=run,
            step_name=STEP_AUDIT_SUMMARY,
            enabled=config.trigger_audit_summary,
            disabled_reason="Audit summary step disabled by config",
            dependency_error=(
                None if context.get("audit_run_id") is not None else "Missing completed audit_run output"
            ),
            action=lambda: self._execute_audit_summary_step(
                business_id=run.business_id,
                audit_run_id=context["audit_run_id"],
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if audit_summary_id is not None:
            context["audit_summary_id"] = audit_summary_id

        snapshot_step = self._run_step(
            run=run,
            step_name=STEP_COMPETITOR_SNAPSHOT_RUN,
            enabled=config.trigger_competitor_snapshot,
            disabled_reason="Competitor snapshot step disabled by config",
            action=lambda: self._execute_snapshot_step(
                business_id=run.business_id,
                site_id=run.site_id,
                audit_run_id=context.get("audit_run_id"),
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if snapshot_step is not None:
            snapshot_run_id, snapshot_status, competitor_set_id = snapshot_step
            context["snapshot_run_id"] = snapshot_run_id
            context["snapshot_run_status"] = snapshot_status
            context["competitor_set_id"] = competitor_set_id

        comparison_dependency: str | None = None
        if context.get("snapshot_run_id") is None:
            comparison_dependency = "Missing competitor_snapshot_run output"
        elif context.get("snapshot_run_status") != "completed":
            comparison_dependency = "Snapshot run is not completed; comparison step skipped"

        comparison_run_id = self._run_step(
            run=run,
            step_name=STEP_COMPARISON_RUN,
            enabled=config.trigger_comparison,
            disabled_reason="Comparison step disabled by config",
            dependency_error=comparison_dependency,
            action=lambda: self._execute_comparison_step(
                business_id=run.business_id,
                competitor_set_id=context["competitor_set_id"],
                snapshot_run_id=context["snapshot_run_id"],
                audit_run_id=context.get("audit_run_id"),
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if comparison_run_id is not None:
            context["comparison_run_id"] = comparison_run_id

        competitor_summary_id = self._run_step(
            run=run,
            step_name=STEP_COMPETITOR_SUMMARY,
            enabled=config.trigger_competitor_summary,
            disabled_reason="Competitor summary step disabled by config",
            dependency_error=(
                None if context.get("comparison_run_id") is not None else "Missing completed comparison_run output"
            ),
            action=lambda: self._execute_competitor_summary_step(
                business_id=run.business_id,
                comparison_run_id=context["comparison_run_id"],
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if competitor_summary_id is not None:
            context["competitor_summary_id"] = competitor_summary_id

        recommendation_dependency: str | None = None
        if context.get("audit_run_id") is None and context.get("comparison_run_id") is None:
            recommendation_dependency = "Recommendation step requires audit_run and/or comparison_run output"

        recommendation_run_id = self._run_step(
            run=run,
            step_name=STEP_RECOMMENDATION_RUN,
            enabled=config.trigger_recommendations,
            disabled_reason="Recommendation step disabled by config",
            dependency_error=recommendation_dependency,
            action=lambda: self._execute_recommendation_step(
                business_id=run.business_id,
                site_id=run.site_id,
                audit_run_id=context.get("audit_run_id"),
                comparison_run_id=context.get("comparison_run_id"),
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if recommendation_run_id is not None:
            context["recommendation_run_id"] = recommendation_run_id

        recommendation_narrative_id = self._run_step(
            run=run,
            step_name=STEP_RECOMMENDATION_NARRATIVE,
            enabled=config.trigger_recommendation_narrative,
            disabled_reason="Recommendation narrative step disabled by config",
            dependency_error=(
                None
                if context.get("recommendation_run_id") is not None
                else "Missing completed recommendation_run output"
            ),
            action=lambda: self._execute_recommendation_narrative_step(
                business_id=run.business_id,
                site_id=run.site_id,
                recommendation_run_id=context["recommendation_run_id"],
                created_by_principal_id=created_by_principal_id,
            ),
        )
        if recommendation_narrative_id is not None:
            context["recommendation_narrative_id"] = recommendation_narrative_id

        first_error: str | None = None
        for step in run.steps_json or []:
            if step.get("status") == FAILED_STEP_STATUS:
                first_error = str(step.get("error_message") or "Step failed")
                break

        run.finished_at = utc_now()
        run.error_message = first_error
        run.status = self._resolve_run_status(run.steps_json or [])
        self.seo_automation_repository.save_run(run)

        config.last_run_at = run.finished_at
        config.last_status = run.status
        config.last_error_message = run.error_message
        config.next_run_at = self._calculate_next_run_at(
            now=run.finished_at,
            is_enabled=config.is_enabled,
            cadence_type=config.cadence_type,
            cadence_minutes=config.cadence_minutes,
        )
        self.seo_automation_repository.save_config(config)
        self.session.commit()
        self.session.refresh(run)

        logger.info(
            "SEO automation run finished business_id=%s site_id=%s automation_run_id=%s status=%s",
            run.business_id,
            run.site_id,
            run.id,
            run.status,
        )
        return run

    def _execute_audit_step(
        self,
        *,
        business_id: str,
        site_id: str,
        created_by_principal_id: str | None,
    ) -> str:
        result = self.seo_audit_service.run_audit(
            business_id=business_id,
            site_id=site_id,
            payload=SEOAuditRunCreateRequest(max_depth=2),
            created_by_principal_id=created_by_principal_id,
        )
        if result.run.status != "completed":
            raise SEOAutomationValidationError("Audit step did not complete")
        return result.run.id

    def _execute_audit_summary_step(
        self,
        *,
        business_id: str,
        audit_run_id: str,
        created_by_principal_id: str | None,
    ) -> str:
        result = self.seo_summary_service.summarize_run(
            business_id=business_id,
            run_id=audit_run_id,
            created_by_principal_id=created_by_principal_id,
        )
        return result.summary.id

    def _execute_snapshot_step(
        self,
        *,
        business_id: str,
        site_id: str,
        audit_run_id: str | None,
        created_by_principal_id: str | None,
    ) -> tuple[str, str, str]:
        competitor_set_id = self._resolve_active_competitor_set_id(business_id=business_id, site_id=site_id)
        snapshot_run = self.seo_competitor_service.create_snapshot_run(
            business_id=business_id,
            competitor_set_id=competitor_set_id,
            payload=SEOCompetitorSnapshotRunCreateRequest(
                client_audit_run_id=audit_run_id,
                max_domains=10,
                max_pages_per_domain=5,
                max_depth=1,
                same_domain_only=True,
            ),
            created_by_principal_id=created_by_principal_id,
        )
        return snapshot_run.id, snapshot_run.status, competitor_set_id

    def _execute_comparison_step(
        self,
        *,
        business_id: str,
        competitor_set_id: str,
        snapshot_run_id: str,
        audit_run_id: str | None,
        created_by_principal_id: str | None,
    ) -> str:
        result = self.seo_competitor_comparison_service.run_comparison(
            business_id=business_id,
            competitor_set_id=competitor_set_id,
            payload=SEOCompetitorComparisonRunCreateRequest(
                snapshot_run_id=snapshot_run_id,
                baseline_audit_run_id=audit_run_id,
            ),
            created_by_principal_id=created_by_principal_id,
        )
        if result.run.status != "completed":
            raise SEOAutomationValidationError("Comparison step did not complete")
        return result.run.id

    def _execute_competitor_summary_step(
        self,
        *,
        business_id: str,
        comparison_run_id: str,
        created_by_principal_id: str | None,
    ) -> str:
        result = self.seo_competitor_summary_service.summarize_run(
            business_id=business_id,
            comparison_run_id=comparison_run_id,
            created_by_principal_id=created_by_principal_id,
        )
        return result.summary.id

    def _execute_recommendation_step(
        self,
        *,
        business_id: str,
        site_id: str,
        audit_run_id: str | None,
        comparison_run_id: str | None,
        created_by_principal_id: str | None,
    ) -> str:
        result = self.seo_recommendation_service.run_recommendations(
            business_id=business_id,
            site_id=site_id,
            payload=SEORecommendationRunCreateRequest(
                audit_run_id=audit_run_id,
                comparison_run_id=comparison_run_id,
            ),
            created_by_principal_id=created_by_principal_id,
        )
        if result.run.status != "completed":
            raise SEOAutomationValidationError("Recommendation step did not complete")
        return result.run.id

    def _execute_recommendation_narrative_step(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
        created_by_principal_id: str | None,
    ) -> str:
        result = self.seo_recommendation_narrative_service.summarize_run(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
            created_by_principal_id=created_by_principal_id,
        )
        return result.narrative.id

    def _run_step(
        self,
        *,
        run: SEOAutomationRun,
        step_name: str,
        enabled: bool,
        disabled_reason: str,
        action,
        dependency_error: str | None = None,
    ):
        if not enabled:
            self._set_step_status(
                run=run,
                step_name=step_name,
                status=SKIPPED_STEP_STATUS,
                error_message=disabled_reason,
            )
            return None

        if dependency_error is not None:
            self._set_step_status(
                run=run,
                step_name=step_name,
                status=SKIPPED_STEP_STATUS,
                error_message=dependency_error,
            )
            return None

        started_at = utc_now()
        self._set_step_status(
            run=run,
            step_name=step_name,
            status="running",
            started_at=started_at,
            error_message=None,
        )

        try:
            result = action()
            linked_output_id = result[0] if isinstance(result, tuple) else result
            step_metrics = self._derive_step_metrics(
                business_id=run.business_id,
                step_name=step_name,
                linked_output_id=str(linked_output_id) if linked_output_id is not None else None,
            )
            self._set_step_status(
                run=run,
                step_name=step_name,
                status=COMPLETED_STEP_STATUS,
                started_at=started_at,
                finished_at=utc_now(),
                linked_output_id=str(linked_output_id) if linked_output_id is not None else None,
                error_message=None,
                metrics=step_metrics,
            )
            return result
        except (
            SEOAuditNotFoundError,
            SEOAuditValidationError,
            SEOSummaryNotFoundError,
            SEOSummaryValidationError,
            SEOCompetitorNotFoundError,
            SEOCompetitorValidationError,
            SEOCompetitorComparisonNotFoundError,
            SEOCompetitorComparisonValidationError,
            SEOCompetitorSummaryNotFoundError,
            SEOCompetitorSummaryValidationError,
            SEORecommendationNotFoundError,
            SEORecommendationValidationError,
            SEORecommendationNarrativeNotFoundError,
            SEORecommendationNarrativeValidationError,
            SEOAutomationValidationError,
        ) as exc:
            self._set_step_status(
                run=run,
                step_name=step_name,
                status=FAILED_STEP_STATUS,
                started_at=started_at,
                finished_at=utc_now(),
                error_message=str(exc),
            )
            return None
        except Exception as exc:  # noqa: BLE001
            self._set_step_status(
                run=run,
                step_name=step_name,
                status=FAILED_STEP_STATUS,
                started_at=started_at,
                finished_at=utc_now(),
                error_message=str(exc),
            )
            return None

    def _set_step_status(
        self,
        *,
        run: SEOAutomationRun,
        step_name: str,
        status: str,
        started_at=None,
        finished_at=None,
        linked_output_id: str | None = None,
        error_message: str | None = None,
        metrics: dict[str, int | None] | None = None,
    ) -> None:
        steps = [dict(step) for step in (run.steps_json or self._initial_steps())]
        for step in steps:
            if step.get("step_name") != step_name:
                continue
            step["status"] = status
            if started_at is not None:
                step["started_at"] = started_at.isoformat()
            elif status == "running" and step.get("started_at") is None:
                step["started_at"] = utc_now().isoformat()

            if finished_at is not None:
                step["finished_at"] = finished_at.isoformat()
            elif (
                status in {COMPLETED_STEP_STATUS, FAILED_STEP_STATUS, SKIPPED_STEP_STATUS}
                and step.get("finished_at") is None
            ):
                step["finished_at"] = utc_now().isoformat()

            if linked_output_id is not None:
                step["linked_output_id"] = linked_output_id
            elif status in {FAILED_STEP_STATUS, SKIPPED_STEP_STATUS}:
                step["linked_output_id"] = None

            if metrics is not None:
                step["metrics"] = metrics
            elif status in {FAILED_STEP_STATUS, SKIPPED_STEP_STATUS}:
                step["metrics"] = None

            step["error_message"] = error_message
            break

        run.steps_json = steps
        self.seo_automation_repository.save_run(run)
        self.session.commit()

    def _initial_steps(self) -> list[dict[str, object]]:
        return [
            self._empty_step(STEP_AUDIT_RUN),
            self._empty_step(STEP_AUDIT_SUMMARY),
            self._empty_step(STEP_COMPETITOR_SNAPSHOT_RUN),
            self._empty_step(STEP_COMPARISON_RUN),
            self._empty_step(STEP_COMPETITOR_SUMMARY),
            self._empty_step(STEP_RECOMMENDATION_RUN),
            self._empty_step(STEP_RECOMMENDATION_NARRATIVE),
        ]

    def _empty_step(self, step_name: str) -> dict[str, object]:
        return {
            "step_name": step_name,
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "linked_output_id": None,
            "error_message": None,
            "metrics": None,
        }

    def _resolve_run_status(self, steps: list[dict[str, object]]) -> str:
        statuses = [str(step.get("status") or "") for step in steps]
        if any(status == FAILED_STEP_STATUS for status in statuses):
            return "failed"
        if any(status == COMPLETED_STEP_STATUS for status in statuses):
            return "completed"
        return "skipped"

    def _resolve_active_competitor_set_id(self, *, business_id: str, site_id: str) -> str:
        sets = self.seo_competitor_service.list_sets(business_id=business_id, site_id=site_id)
        for item in sets:
            if item.is_active:
                return item.id
        raise SEOAutomationValidationError("No active competitor set found for site")

    def _ensure_no_active_run(self, business_id: str, site_id: str) -> None:
        active = self.seo_automation_repository.get_active_run_for_business_site(business_id, site_id)
        if active is not None and active.status in ACTIVE_RUN_STATUSES:
            raise SEOAutomationConflictError("An automation run is already active for this site")

    def _validate_effective_config(self, config: SEOAutomationConfig) -> None:
        if config.cadence_type == "manual" and config.cadence_minutes is not None:
            raise SEOAutomationValidationError("cadence_minutes must be null when cadence_type=manual")
        if config.cadence_type == "interval_minutes":
            if config.cadence_minutes is None or int(config.cadence_minutes) < 5:
                raise SEOAutomationValidationError("cadence_minutes must be >= 5 when cadence_type=interval_minutes")

        flags = [
            config.trigger_audit,
            config.trigger_audit_summary,
            config.trigger_competitor_snapshot,
            config.trigger_comparison,
            config.trigger_competitor_summary,
            config.trigger_recommendations,
            config.trigger_recommendation_narrative,
        ]
        if not any(flags):
            raise SEOAutomationValidationError("At least one automation trigger must be enabled")

    def _calculate_next_run_at(
        self,
        *,
        now,
        is_enabled: bool,
        cadence_type: str,
        cadence_minutes: int | None,
    ):
        if not is_enabled:
            return None
        if cadence_type == "interval_minutes" and cadence_minutes is not None:
            return now + timedelta(minutes=int(cadence_minutes))
        return None

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOAutomationNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> None:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOAutomationNotFoundError("SEO site not found")

    def _derive_step_metrics(
        self,
        *,
        business_id: str,
        step_name: str,
        linked_output_id: str | None,
    ) -> dict[str, int | None] | None:
        if not linked_output_id:
            return None
        try:
            if step_name == STEP_AUDIT_RUN:
                audit_summary = self.seo_audit_service.get_run_summary(
                    business_id=business_id,
                    run_id=linked_output_id,
                )
                return {
                    "pages_analyzed_count": audit_summary.total_pages,
                    "issues_found_count": audit_summary.total_findings,
                }
            if step_name == STEP_RECOMMENDATION_RUN:
                recommendation_run = self.seo_recommendation_service.get_run(
                    business_id=business_id,
                    recommendation_run_id=linked_output_id,
                )
                return {
                    "recommendations_generated_count": recommendation_run.total_recommendations,
                }
        except Exception:  # noqa: BLE001
            logger.warning(
                "SEO automation step metrics unavailable business_id=%s step_name=%s linked_output_id=%s",
                business_id,
                step_name,
                linked_output_id,
                exc_info=True,
            )
        return None

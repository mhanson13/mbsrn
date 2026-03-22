from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.seo_competitor_profile_generation_provider import SEOCompetitorProfileProviderError
from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationProvider,
)
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_competitor import (
    SEOCompetitorProfileDraftAcceptRequest,
    SEOCompetitorProfileDraftEditRequest,
    SEOCompetitorProfileDraftRejectRequest,
    SEOCompetitorProfileGenerationRunCreateRequest,
)
from app.services.seo_competitor_profile_candidate_quality import (
    BIG_BOX_PENALTY_MAX,
    BIG_BOX_PENALTY_MIN,
    DIRECTORY_PENALTY_MAX,
    DIRECTORY_PENALTY_MIN,
    LOCAL_ALIGNMENT_BONUS_MAX,
    LOCAL_ALIGNMENT_BONUS_MIN,
    MIN_RELEVANCE_SCORE_MAX,
    MIN_RELEVANCE_SCORE_MIN,
    CompetitorCandidateQualityTuning,
    CompetitorCandidateInput,
    DEFAULT_BIG_BOX_PENALTY,
    DEFAULT_DIRECTORY_PENALTY,
    DEFAULT_LOCAL_ALIGNMENT_BONUS,
    DEFAULT_MIN_RELEVANCE_SCORE,
    EXCLUSION_REASON_KEYS,
    default_exclusion_reason_counts,
    process_competitor_candidates,
)
from app.services.seo_competitor_profile_prompt import SEO_COMPETITOR_PROFILE_PROMPT_VERSION


logger = logging.getLogger(__name__)

_ALLOWED_COMPETITOR_TYPES = {"direct", "indirect", "local", "marketplace", "informational", "unknown"}
STALE_QUEUED_RUN_TIMEOUT = timedelta(minutes=15)
STALE_RUNNING_RUN_TIMEOUT = timedelta(minutes=45)
STALE_QUEUED_RUN_ERROR_SUMMARY = (
    "Competitor profile generation did not start in time. Start a new generation run to retry."
)
STALE_RUNNING_RUN_ERROR_SUMMARY = (
    "Competitor profile generation timed out before completion. Start a new generation run to retry."
)
PROVIDER_TIMEOUT_ERROR_SUMMARY = (
    "Competitor profile generation timed out while contacting the AI provider. Start a new generation run to retry."
)
PROVIDER_AUTH_CONFIG_ERROR_SUMMARY = (
    "AI provider credentials are not configured for competitor profile generation."
)
INVALID_OUTPUT_ERROR_SUMMARY = (
    "Competitor profile generation returned invalid structured output. Start a new generation run to retry."
)
GENERIC_PROVIDER_ERROR_SUMMARY = "Competitor profile generation failed due to a provider error."
GENERIC_INTERNAL_ERROR_SUMMARY = "Competitor profile generation failed"
INVALID_QUALITY_TUNING_ERROR_SUMMARY = "Competitor profile generation failed due to invalid candidate quality settings."
RUN_RAW_OUTPUT_MAX_CHARS = 12000
DEFAULT_RAW_OUTPUT_RETENTION_DAYS = 30
DEFAULT_RUN_RETENTION_DAYS = 180
DEFAULT_REJECTED_DRAFT_RETENTION_DAYS = 90
DEFAULT_OBSERVABILITY_LOOKBACK_DAYS = 30

FAILURE_CATEGORY_TIMEOUT = "timeout"
FAILURE_CATEGORY_PROVIDER_AUTH = "provider_auth"
FAILURE_CATEGORY_PROVIDER_CONFIG = "provider_config"
FAILURE_CATEGORY_MALFORMED_OUTPUT = "malformed_output"
FAILURE_CATEGORY_SCHEMA_VALIDATION = "schema_validation"
FAILURE_CATEGORY_INTERNAL = "internal_error"
FAILURE_CATEGORY_PROVIDER_REQUEST = "provider_request"
FAILURE_CATEGORY_UNKNOWN = "unknown"

_ALLOWED_FAILURE_CATEGORIES = {
    FAILURE_CATEGORY_TIMEOUT,
    FAILURE_CATEGORY_PROVIDER_AUTH,
    FAILURE_CATEGORY_PROVIDER_CONFIG,
    FAILURE_CATEGORY_MALFORMED_OUTPUT,
    FAILURE_CATEGORY_SCHEMA_VALIDATION,
    FAILURE_CATEGORY_INTERNAL,
    FAILURE_CATEGORY_PROVIDER_REQUEST,
    FAILURE_CATEGORY_UNKNOWN,
}


class SEOCompetitorProfileGenerationNotFoundError(ValueError):
    pass


class SEOCompetitorProfileGenerationValidationError(ValueError):
    pass


class SEOCompetitorProfileGenerationConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class SEOCompetitorProfileRetentionPolicy:
    raw_output_retention_days: int = DEFAULT_RAW_OUTPUT_RETENTION_DAYS
    run_retention_days: int = DEFAULT_RUN_RETENTION_DAYS
    rejected_draft_retention_days: int = DEFAULT_REJECTED_DRAFT_RETENTION_DAYS

    def __post_init__(self) -> None:
        if self.raw_output_retention_days < 1:
            raise ValueError("raw_output_retention_days must be >= 1")
        if self.run_retention_days < 1:
            raise ValueError("run_retention_days must be >= 1")
        if self.rejected_draft_retention_days < 1:
            raise ValueError("rejected_draft_retention_days must be >= 1")


@dataclass(frozen=True)
class SEOCompetitorProfileGenerationRunDetail:
    run: SEOCompetitorProfileGenerationRun
    drafts: list[SEOCompetitorProfileDraft]


@dataclass(frozen=True)
class SEOCompetitorProfileDraftAcceptanceResult:
    draft: SEOCompetitorProfileDraft
    competitor_domain: SEOCompetitorDomain


@dataclass(frozen=True)
class SEOCompetitorProfileRetentionCleanupSummary:
    stale_runs_reconciled: int
    raw_output_pruned_runs: int
    rejected_drafts_pruned: int
    runs_pruned: int


@dataclass(frozen=True)
class SEOCompetitorProfileDraftBuildResult:
    drafts: list[SEOCompetitorProfileDraft]
    raw_candidate_count: int
    included_candidate_count: int
    deduped_candidate_count: int
    excluded_candidate_count: int
    exclusion_counts_by_reason: dict[str, int]


@dataclass(frozen=True)
class SEOCompetitorProfileGenerationObservabilitySummary:
    business_id: str
    site_id: str
    lookback_days: int
    window_start: datetime
    window_end: datetime
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int
    retry_child_runs: int
    retried_parent_runs: int
    failed_runs_retried: int
    failure_category_counts: dict[str, int]
    total_runs: int
    total_raw_candidate_count: int
    total_included_candidate_count: int
    total_excluded_candidate_count: int
    exclusion_counts_by_reason: dict[str, int]
    latest_run_created_at: datetime | None
    latest_run_completed_at: datetime | None
    latest_completed_run_completed_at: datetime | None
    latest_failed_run_completed_at: datetime | None


@dataclass(frozen=True)
class SEOCompetitorProfileRetentionCleanupStatus:
    latest_execution: SEOCompetitorProfileCleanupExecution | None
    recent_success_count: int
    recent_failure_count: int
    lookback_days: int
    window_start: datetime
    window_end: datetime


class SEOCompetitorProfileGenerationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_competitor_repository: SEOCompetitorRepository,
        seo_competitor_profile_generation_repository: SEOCompetitorProfileGenerationRepository,
        provider: SEOCompetitorProfileGenerationProvider,
        retention_policy: SEOCompetitorProfileRetentionPolicy = SEOCompetitorProfileRetentionPolicy(),
        observability_lookback_days: int = DEFAULT_OBSERVABILITY_LOOKBACK_DAYS,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_competitor_repository = seo_competitor_repository
        self.seo_competitor_profile_generation_repository = seo_competitor_profile_generation_repository
        self.provider = provider
        self.retention_policy = retention_policy
        self.observability_lookback_days = max(1, int(observability_lookback_days))

    def create_run(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOCompetitorProfileGenerationRunCreateRequest,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorProfileGenerationRunDetail:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        return self._queue_run(
            business_id=business_id,
            site_id=site_id,
            candidate_count=payload.candidate_count,
            prompt_version=self._default_prompt_version(),
            parent_run_id=None,
            created_by_principal_id=created_by_principal_id,
        )

    def retry_failed_run(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorProfileGenerationRunDetail:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._reconcile_stale_runs_for_site(business_id=business_id, site_id=site_id)
        failed_run = self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        if failed_run.status != "failed":
            raise SEOCompetitorProfileGenerationValidationError(
                "Only failed competitor profile generation runs can be retried"
            )
        return self._queue_run(
            business_id=business_id,
            site_id=site_id,
            candidate_count=failed_run.requested_candidate_count,
            prompt_version=failed_run.prompt_version or self._default_prompt_version(),
            parent_run_id=failed_run.id,
            created_by_principal_id=created_by_principal_id,
        )

    def _queue_run(
        self,
        *,
        business_id: str,
        site_id: str,
        candidate_count: int,
        prompt_version: str,
        parent_run_id: str | None,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorProfileGenerationRunDetail:
        run = SEOCompetitorProfileGenerationRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            parent_run_id=parent_run_id,
            status="queued",
            requested_candidate_count=candidate_count,
            generated_draft_count=0,
            raw_candidate_count=0,
            included_candidate_count=0,
            excluded_candidate_count=0,
            exclusion_counts_by_reason=default_exclusion_reason_counts(),
            provider_name=self._default_provider_name(),
            model_name=self._default_model_name(),
            prompt_version=prompt_version,
            failure_category=None,
            raw_output=None,
            error_summary=None,
            completed_at=None,
            created_by_principal_id=created_by_principal_id,
        )
        try:
            self.seo_competitor_profile_generation_repository.create_run(run)
            self.session.commit()
            self.session.refresh(run)
            logger.info(
                (
                    "SEO competitor profile generation run queued business_id=%s site_id=%s run_id=%s "
                    "parent_run_id=%s candidate_count=%s"
                ),
                business_id,
                site_id,
                run.id,
                parent_run_id,
                candidate_count,
            )
            return SEOCompetitorProfileGenerationRunDetail(run=run, drafts=[])
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            raise SEOCompetitorProfileGenerationValidationError("Failed to queue competitor profile generation run") from exc

    def execute_queued_run(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
    ) -> SEOCompetitorProfileGenerationRunDetail | None:
        self._require_business(business_id)
        site = self._require_site(business_id=business_id, site_id=site_id)

        existing_run = self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        claimed = self.seo_competitor_profile_generation_repository.claim_run_for_execution(
            business_id,
            generation_run_id,
        )
        if not claimed:
            self.session.rollback()
            logger.info(
                "SEO competitor profile generation run execution skipped business_id=%s site_id=%s run_id=%s status=%s",
                business_id,
                site_id,
                generation_run_id,
                existing_run.status,
            )
            return None

        self.session.commit()
        run = self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        logger.info(
            "SEO competitor profile generation run started business_id=%s site_id=%s run_id=%s",
            business_id,
            site_id,
            run.id,
        )

        provider_name = run.provider_name
        model_name = run.model_name
        prompt_version = run.prompt_version or self._default_prompt_version()
        failure_category: str | None = None
        raw_output: str | None = None
        draft_result: SEOCompetitorProfileDraftBuildResult | None = None

        try:
            existing_domains = [
                item.domain
                for item in self.seo_competitor_repository.list_domains_for_business_site(
                    business_id,
                    site_id,
                )
            ]
            output = self.provider.generate_competitor_profiles(
                site=site,
                existing_domains=existing_domains,
                candidate_count=run.requested_candidate_count,
            )
            provider_name = self._clean_required_value(output.provider_name, field_name="provider_name")
            model_name = self._clean_required_value(output.model_name, field_name="model_name")
            prompt_version = self._clean_required_value(output.prompt_version, field_name="prompt_version")
            raw_output = self._sanitize_raw_output(output.raw_response)

            draft_result = self._build_drafts(
                site=site,
                existing_domains=existing_domains,
                run=run,
                raw_candidates=output.candidates,
            )
            drafts = draft_result.drafts
            if not drafts:
                raise SEOCompetitorProfileGenerationValidationError(
                    "No valid competitor profile drafts were generated"
                )

            run.status = "completed"
            run.generated_draft_count = len(drafts)
            run.raw_candidate_count = draft_result.raw_candidate_count
            run.included_candidate_count = draft_result.included_candidate_count
            run.excluded_candidate_count = draft_result.excluded_candidate_count
            run.exclusion_counts_by_reason = self._normalize_exclusion_counts_by_reason(
                draft_result.exclusion_counts_by_reason
            )
            run.provider_name = provider_name
            run.model_name = model_name
            run.prompt_version = prompt_version
            run.failure_category = None
            run.raw_output = raw_output
            run.error_summary = None
            run.completed_at = utc_now()
            self.seo_competitor_profile_generation_repository.save_run(run)
            for draft in drafts:
                self.seo_competitor_profile_generation_repository.create_draft(draft)
            self.session.commit()
            self.session.refresh(run)
            logger.info(
                "SEO competitor profile generation run completed business_id=%s site_id=%s run_id=%s drafts=%s",
                business_id,
                site_id,
                run.id,
                len(drafts),
            )
            logger.info(
                (
                    "SEO competitor profile candidate processing run_id=%s raw_candidates=%s "
                    "deduped_candidates=%s excluded_candidates=%s included_candidates=%s"
                ),
                run.id,
                draft_result.raw_candidate_count,
                draft_result.deduped_candidate_count,
                draft_result.excluded_candidate_count,
                len(drafts),
            )
            logger.info(
                "SEO competitor profile exclusion telemetry run_id=%s exclusion_counts_by_reason=%s",
                run.id,
                run.exclusion_counts_by_reason,
            )
            return SEOCompetitorProfileGenerationRunDetail(run=run, drafts=drafts)
        except SEOCompetitorProfileProviderError as exc:
            self.session.rollback()
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=self._provider_error_summary(exc),
                provider_name=exc.provider_name,
                model_name=exc.model_name,
                prompt_version=exc.prompt_version,
                failure_category=self._provider_failure_category(exc),
                raw_output=exc.raw_output,
            )
            return None
        except SEOCompetitorProfileGenerationConfigurationError as exc:
            self.session.rollback()
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=INVALID_QUALITY_TUNING_ERROR_SUMMARY,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
                failure_category=FAILURE_CATEGORY_INTERNAL,
                raw_output=raw_output,
                raw_candidate_count=draft_result.raw_candidate_count if draft_result else None,
                included_candidate_count=draft_result.included_candidate_count if draft_result else None,
                excluded_candidate_count=draft_result.excluded_candidate_count if draft_result else None,
                exclusion_counts_by_reason=draft_result.exclusion_counts_by_reason if draft_result else None,
            )
            return None
        except SEOCompetitorProfileGenerationValidationError as exc:
            self.session.rollback()
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=INVALID_OUTPUT_ERROR_SUMMARY,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
                failure_category=FAILURE_CATEGORY_MALFORMED_OUTPUT,
                raw_output=raw_output,
                raw_candidate_count=draft_result.raw_candidate_count if draft_result else None,
                included_candidate_count=draft_result.included_candidate_count if draft_result else None,
                excluded_candidate_count=draft_result.excluded_candidate_count if draft_result else None,
                exclusion_counts_by_reason=draft_result.exclusion_counts_by_reason if draft_result else None,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=GENERIC_INTERNAL_ERROR_SUMMARY,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
                failure_category=failure_category or FAILURE_CATEGORY_INTERNAL,
                raw_output=raw_output,
                raw_candidate_count=draft_result.raw_candidate_count if draft_result else None,
                included_candidate_count=draft_result.included_candidate_count if draft_result else None,
                excluded_candidate_count=draft_result.excluded_candidate_count if draft_result else None,
                exclusion_counts_by_reason=draft_result.exclusion_counts_by_reason if draft_result else None,
            )
            return None

    def list_runs(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> list[SEOCompetitorProfileGenerationRun]:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._reconcile_stale_runs_for_site(business_id=business_id, site_id=site_id)
        return self.seo_competitor_profile_generation_repository.list_runs_for_business_site(
            business_id,
            site_id,
        )

    def get_run_detail(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
    ) -> SEOCompetitorProfileGenerationRunDetail:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._reconcile_stale_runs_for_site(business_id=business_id, site_id=site_id)
        run = self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        drafts = self.seo_competitor_profile_generation_repository.list_drafts_for_business_run(
            business_id,
            generation_run_id,
        )
        return SEOCompetitorProfileGenerationRunDetail(run=run, drafts=drafts)

    def get_observability_summary(
        self,
        *,
        business_id: str,
        site_id: str,
        lookback_days: int | None = None,
    ) -> SEOCompetitorProfileGenerationObservabilitySummary:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._reconcile_stale_runs_for_site(business_id=business_id, site_id=site_id)

        effective_lookback_days = self._effective_lookback_days(lookback_days)
        window_end = utc_now()
        window_start = window_end - timedelta(days=effective_lookback_days)

        status_counts = self.seo_competitor_profile_generation_repository.summarize_run_status_counts(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        failure_category_counts = self.seo_competitor_profile_generation_repository.summarize_failure_category_counts(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        failed_count = int(status_counts.get("failed", 0))
        categorized_failed_count = sum(failure_category_counts.values())
        if failed_count > categorized_failed_count:
            failure_category_counts[FAILURE_CATEGORY_UNKNOWN] = failed_count - categorized_failed_count

        retry_child_runs = self.seo_competitor_profile_generation_repository.count_retry_child_runs(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        retried_parent_runs = self.seo_competitor_profile_generation_repository.count_distinct_retry_parents(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        failed_runs_retried = self.seo_competitor_profile_generation_repository.count_failed_runs_retried(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        (
            latest_run_created_at,
            latest_run_completed_at,
            latest_completed_run_completed_at,
            latest_failed_run_completed_at,
        ) = self.seo_competitor_profile_generation_repository.summarize_run_latest_timestamps(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        runs_in_window = self.seo_competitor_profile_generation_repository.list_runs_for_business_site_created_after(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        total_runs = len(runs_in_window)
        total_raw_candidate_count = sum(max(0, int(item.raw_candidate_count or 0)) for item in runs_in_window)
        total_included_candidate_count = sum(max(0, int(item.included_candidate_count or 0)) for item in runs_in_window)
        total_excluded_candidate_count = sum(max(0, int(item.excluded_candidate_count or 0)) for item in runs_in_window)

        exclusion_counts_by_reason = default_exclusion_reason_counts()
        for run in runs_in_window:
            normalized_counts = self._normalize_exclusion_counts_by_reason(run.exclusion_counts_by_reason)
            for reason in EXCLUSION_REASON_KEYS:
                exclusion_counts_by_reason[reason] += normalized_counts[reason]

        return SEOCompetitorProfileGenerationObservabilitySummary(
            business_id=business_id,
            site_id=site_id,
            lookback_days=effective_lookback_days,
            window_start=window_start,
            window_end=window_end,
            queued_count=int(status_counts.get("queued", 0)),
            running_count=int(status_counts.get("running", 0)),
            completed_count=int(status_counts.get("completed", 0)),
            failed_count=failed_count,
            retry_child_runs=retry_child_runs,
            retried_parent_runs=retried_parent_runs,
            failed_runs_retried=failed_runs_retried,
            failure_category_counts=dict(sorted(failure_category_counts.items())),
            total_runs=total_runs,
            total_raw_candidate_count=total_raw_candidate_count,
            total_included_candidate_count=total_included_candidate_count,
            total_excluded_candidate_count=total_excluded_candidate_count,
            exclusion_counts_by_reason=dict(sorted(exclusion_counts_by_reason.items())),
            latest_run_created_at=latest_run_created_at,
            latest_run_completed_at=latest_run_completed_at,
            latest_completed_run_completed_at=latest_completed_run_completed_at,
            latest_failed_run_completed_at=latest_failed_run_completed_at,
        )

    def get_cleanup_observability_status(
        self,
        *,
        business_id: str,
        site_id: str | None,
        lookback_days: int | None = None,
    ) -> SEOCompetitorProfileRetentionCleanupStatus:
        self._require_business(business_id)
        if site_id:
            self._require_site(business_id=business_id, site_id=site_id)

        effective_lookback_days = self._effective_lookback_days(lookback_days)
        window_end = utc_now()
        window_start = window_end - timedelta(days=effective_lookback_days)

        latest_execution = self.seo_competitor_profile_generation_repository.get_latest_cleanup_execution_for_business_scope(
            business_id=business_id,
            site_id=site_id,
        )
        status_counts = self.seo_competitor_profile_generation_repository.count_cleanup_executions_by_status(
            business_id=business_id,
            site_id=site_id,
            started_after=window_start,
        )
        return SEOCompetitorProfileRetentionCleanupStatus(
            latest_execution=latest_execution,
            recent_success_count=int(status_counts.get("completed", 0)),
            recent_failure_count=int(status_counts.get("failed", 0)),
            lookback_days=effective_lookback_days,
            window_start=window_start,
            window_end=window_end,
        )

    def edit_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
        payload: SEOCompetitorProfileDraftEditRequest,
        reviewed_by_principal_id: str | None,
    ) -> SEOCompetitorProfileDraft:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        draft = self._get_draft_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
        )
        if draft.review_status == "accepted":
            raise SEOCompetitorProfileGenerationValidationError("Accepted drafts cannot be edited")
        if draft.review_status == "rejected":
            raise SEOCompetitorProfileGenerationValidationError("Rejected drafts cannot be edited")

        updates = payload.model_dump(exclude_unset=True)
        changed_fields = self._apply_draft_updates(
            draft=draft,
            updates=updates,
        )
        if draft.review_status == "pending":
            draft.review_status = "edited"
        draft.edited_fields_json = changed_fields or draft.edited_fields_json
        draft.reviewed_by_principal_id = reviewed_by_principal_id
        draft.reviewed_at = utc_now()
        self.seo_competitor_profile_generation_repository.save_draft(draft)
        self._commit_with_constraint_handling()
        self.session.refresh(draft)
        return draft

    def reject_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
        payload: SEOCompetitorProfileDraftRejectRequest,
        reviewed_by_principal_id: str | None,
    ) -> SEOCompetitorProfileDraft:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        draft = self._get_draft_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
        )
        if draft.review_status == "accepted":
            raise SEOCompetitorProfileGenerationValidationError("Accepted drafts cannot be rejected")
        draft.review_status = "rejected"
        draft.review_notes = self._clean_optional(payload.reason)
        draft.reviewed_by_principal_id = reviewed_by_principal_id
        draft.reviewed_at = utc_now()
        self.seo_competitor_profile_generation_repository.save_draft(draft)
        self._commit_with_constraint_handling()
        self.session.refresh(draft)
        return draft

    def accept_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
        payload: SEOCompetitorProfileDraftAcceptRequest,
        reviewed_by_principal_id: str | None,
    ) -> SEOCompetitorProfileDraftAcceptanceResult:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        draft = self._get_draft_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
        )
        if draft.review_status == "accepted":
            raise SEOCompetitorProfileGenerationValidationError("Draft has already been accepted")
        if draft.review_status == "rejected":
            raise SEOCompetitorProfileGenerationValidationError("Rejected drafts cannot be accepted")

        updates = payload.model_dump(exclude_unset=True, exclude={"competitor_set_id", "review_notes"})
        changed_fields = self._apply_draft_updates(draft=draft, updates=updates)

        normalized_domain = self._normalize_domain_value(draft.suggested_domain)
        existing_domain = self.seo_competitor_repository.get_domain_for_business_site_domain(
            business_id,
            site_id,
            normalized_domain,
        )
        if existing_domain is not None:
            raise SEOCompetitorProfileGenerationValidationError(
                "A competitor domain with this host already exists for the site"
            )

        target_set = self._resolve_target_set(
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=payload.competitor_set_id,
            created_by_principal_id=reviewed_by_principal_id,
        )
        competitor_domain = SEOCompetitorDomain(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=target_set.id,
            domain=normalized_domain,
            base_url=f"https://{normalized_domain}/",
            display_name=draft.suggested_name,
            source="ai_generated",
            is_active=True,
            notes=self._build_domain_notes_from_draft(draft),
        )
        self.seo_competitor_repository.create_domain(competitor_domain)

        draft.review_status = "accepted"
        draft.review_notes = self._clean_optional(payload.review_notes)
        draft.reviewed_by_principal_id = reviewed_by_principal_id
        draft.reviewed_at = utc_now()
        draft.accepted_competitor_set_id = target_set.id
        draft.accepted_competitor_domain_id = competitor_domain.id
        draft.edited_fields_json = changed_fields or draft.edited_fields_json
        self.seo_competitor_profile_generation_repository.save_draft(draft)
        self._commit_with_constraint_handling()
        self.session.refresh(draft)
        self.session.refresh(competitor_domain)
        return SEOCompetitorProfileDraftAcceptanceResult(
            draft=draft,
            competitor_domain=competitor_domain,
        )

    def _build_drafts(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        run: SEOCompetitorProfileGenerationRun,
        raw_candidates: list[SEOCompetitorProfileDraftCandidateOutput],
    ) -> SEOCompetitorProfileDraftBuildResult:
        prepared_candidates: list[CompetitorCandidateInput] = []
        for index, candidate in enumerate(raw_candidates):
            suggested_name = self._clean_required_value(candidate.suggested_name, field_name="suggested_name")
            suggested_domain = self._normalize_domain_value(candidate.suggested_domain)
            competitor_type = self._normalize_competitor_type(candidate.competitor_type)
            confidence_score = self._normalize_confidence_score(candidate.confidence_score)
            prepared_candidates.append(
                CompetitorCandidateInput(
                    suggested_name=suggested_name,
                    suggested_domain=suggested_domain,
                    competitor_type=competitor_type,
                    summary=self._clean_optional(candidate.summary),
                    why_competitor=self._clean_optional(candidate.why_competitor),
                    evidence=self._clean_optional(candidate.evidence),
                    confidence_score=confidence_score,
                    source_index=index,
                )
            )

        quality_tuning = self._resolve_candidate_quality_tuning(business_id=run.business_id)
        candidate_processing = process_competitor_candidates(
            site=site,
            candidates=prepared_candidates,
            existing_domains=existing_domains,
            quality_tuning=quality_tuning,
        )
        drafts: list[SEOCompetitorProfileDraft] = []
        for candidate in candidate_processing.included_candidates:
            draft = SEOCompetitorProfileDraft(
                id=str(uuid4()),
                business_id=run.business_id,
                site_id=run.site_id,
                generation_run_id=run.id,
                suggested_name=candidate.suggested_name,
                suggested_domain=candidate.canonical_domain,
                competitor_type=candidate.competitor_type,
                summary=candidate.summary,
                why_competitor=candidate.why_competitor,
                evidence=candidate.evidence,
                confidence_score=candidate.confidence_score,
                relevance_score=candidate.relevance_score,
                source="ai_generated",
                review_status="pending",
            )
            drafts.append(draft)
        return SEOCompetitorProfileDraftBuildResult(
            drafts=drafts,
            raw_candidate_count=candidate_processing.raw_candidate_count,
            included_candidate_count=len(drafts),
            deduped_candidate_count=candidate_processing.deduped_candidate_count,
            excluded_candidate_count=candidate_processing.excluded_candidate_count,
            exclusion_counts_by_reason=self._normalize_exclusion_counts_by_reason(
                candidate_processing.exclusion_counts_by_reason
            ),
        )

    def _apply_draft_updates(
        self,
        *,
        draft: SEOCompetitorProfileDraft,
        updates: dict[str, object],
    ) -> dict[str, object]:
        changed_fields: dict[str, object] = {}
        if "suggested_name" in updates:
            suggested_name = self._clean_required_value(str(updates["suggested_name"]), field_name="suggested_name")
            if suggested_name != draft.suggested_name:
                draft.suggested_name = suggested_name
                changed_fields["suggested_name"] = suggested_name
        if "suggested_domain" in updates:
            suggested_domain = self._normalize_domain_value(str(updates["suggested_domain"]))
            if suggested_domain != draft.suggested_domain:
                draft.suggested_domain = suggested_domain
                changed_fields["suggested_domain"] = suggested_domain
        if "competitor_type" in updates:
            competitor_type = self._normalize_competitor_type(str(updates["competitor_type"]))
            if competitor_type != draft.competitor_type:
                draft.competitor_type = competitor_type
                changed_fields["competitor_type"] = competitor_type
        if "summary" in updates:
            summary = self._clean_optional(str(updates["summary"]) if updates["summary"] is not None else None)
            if summary != draft.summary:
                draft.summary = summary
                changed_fields["summary"] = summary
        if "why_competitor" in updates:
            why_competitor = self._clean_optional(
                str(updates["why_competitor"]) if updates["why_competitor"] is not None else None
            )
            if why_competitor != draft.why_competitor:
                draft.why_competitor = why_competitor
                changed_fields["why_competitor"] = why_competitor
        if "evidence" in updates:
            evidence = self._clean_optional(str(updates["evidence"]) if updates["evidence"] is not None else None)
            if evidence != draft.evidence:
                draft.evidence = evidence
                changed_fields["evidence"] = evidence
        if "confidence_score" in updates:
            confidence_score = self._normalize_confidence_score(float(updates["confidence_score"]))
            if confidence_score != draft.confidence_score:
                draft.confidence_score = confidence_score
                changed_fields["confidence_score"] = confidence_score
        return changed_fields

    def _resolve_target_set(
        self,
        *,
        business_id: str,
        site_id: str,
        competitor_set_id: str | None,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorSet:
        if competitor_set_id:
            competitor_set = self.seo_competitor_repository.get_set_for_business(
                business_id,
                competitor_set_id,
            )
            if competitor_set is None or competitor_set.site_id != site_id:
                raise SEOCompetitorProfileGenerationNotFoundError("Competitor set not found")
            return competitor_set

        sets = self.seo_competitor_repository.list_sets_for_business_site(business_id, site_id)
        if sets:
            active_set = next((item for item in sets if item.is_active), None)
            return active_set or sets[0]

        generated_set = SEOCompetitorSet(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            name=f"AI Generated Competitors ({utc_now().date().isoformat()})",
            city=None,
            state=None,
            is_active=True,
            created_by_principal_id=created_by_principal_id,
        )
        self.seo_competitor_repository.create_set(generated_set)
        return generated_set

    def _build_domain_notes_from_draft(self, draft: SEOCompetitorProfileDraft) -> str | None:
        parts = [
            "Added from AI-generated competitor profile draft.",
            f"Type: {draft.competitor_type}",
            f"Confidence: {draft.confidence_score:.2f}",
        ]
        if draft.summary:
            parts.append(f"Summary: {draft.summary}")
        if draft.why_competitor:
            parts.append(f"Rationale: {draft.why_competitor}")
        if draft.evidence:
            parts.append(f"Evidence: {draft.evidence}")
        combined = " ".join(parts).strip()
        if len(combined) > 2000:
            return combined[:1997] + "..."
        return combined or None

    def _get_run_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
    ) -> SEOCompetitorProfileGenerationRun:
        run = self.seo_competitor_profile_generation_repository.get_run_for_business(
            business_id,
            generation_run_id,
        )
        if run is None or run.site_id != site_id:
            raise SEOCompetitorProfileGenerationNotFoundError("Competitor profile generation run not found")
        return run

    def _get_draft_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
    ) -> SEOCompetitorProfileDraft:
        draft = self.seo_competitor_profile_generation_repository.get_draft_for_business_run(
            business_id,
            generation_run_id,
            draft_id,
        )
        if draft is None or draft.site_id != site_id:
            raise SEOCompetitorProfileGenerationNotFoundError("Competitor profile draft not found")
        return draft

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorProfileGenerationNotFoundError("Business not found")

    def _resolve_candidate_quality_tuning(self, *, business_id: str) -> CompetitorCandidateQualityTuning:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorProfileGenerationNotFoundError("Business not found")

        min_relevance_score = (
            int(business.competitor_candidate_min_relevance_score)
            if business.competitor_candidate_min_relevance_score is not None
            else DEFAULT_MIN_RELEVANCE_SCORE
        )
        big_box_penalty = (
            int(business.competitor_candidate_big_box_penalty)
            if business.competitor_candidate_big_box_penalty is not None
            else DEFAULT_BIG_BOX_PENALTY
        )
        directory_penalty = (
            int(business.competitor_candidate_directory_penalty)
            if business.competitor_candidate_directory_penalty is not None
            else DEFAULT_DIRECTORY_PENALTY
        )
        local_alignment_bonus = (
            int(business.competitor_candidate_local_alignment_bonus)
            if business.competitor_candidate_local_alignment_bonus is not None
            else DEFAULT_LOCAL_ALIGNMENT_BONUS
        )

        if min_relevance_score < MIN_RELEVANCE_SCORE_MIN or min_relevance_score > MIN_RELEVANCE_SCORE_MAX:
            raise SEOCompetitorProfileGenerationConfigurationError(
                (
                    "competitor_candidate_min_relevance_score must be between "
                    f"{MIN_RELEVANCE_SCORE_MIN} and {MIN_RELEVANCE_SCORE_MAX}"
                )
            )
        if big_box_penalty < BIG_BOX_PENALTY_MIN or big_box_penalty > BIG_BOX_PENALTY_MAX:
            raise SEOCompetitorProfileGenerationConfigurationError(
                f"competitor_candidate_big_box_penalty must be between {BIG_BOX_PENALTY_MIN} and {BIG_BOX_PENALTY_MAX}"
            )
        if directory_penalty < DIRECTORY_PENALTY_MIN or directory_penalty > DIRECTORY_PENALTY_MAX:
            raise SEOCompetitorProfileGenerationConfigurationError(
                (
                    "competitor_candidate_directory_penalty must be between "
                    f"{DIRECTORY_PENALTY_MIN} and {DIRECTORY_PENALTY_MAX}"
                )
            )
        if local_alignment_bonus < LOCAL_ALIGNMENT_BONUS_MIN or local_alignment_bonus > LOCAL_ALIGNMENT_BONUS_MAX:
            raise SEOCompetitorProfileGenerationConfigurationError(
                (
                    "competitor_candidate_local_alignment_bonus must be between "
                    f"{LOCAL_ALIGNMENT_BONUS_MIN} and {LOCAL_ALIGNMENT_BONUS_MAX}"
                )
            )

        return CompetitorCandidateQualityTuning(
            minimum_relevance_score=min_relevance_score,
            big_box_penalty=big_box_penalty,
            directory_penalty=directory_penalty,
            local_alignment_bonus=local_alignment_bonus,
        )

    def _require_site(self, *, business_id: str, site_id: str):
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOCompetitorProfileGenerationNotFoundError("SEO site not found")
        return site

    def _normalize_domain_value(self, raw_domain: str) -> str:
        candidate = raw_domain.strip().lower()
        if not candidate:
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain is required")
        if "://" in candidate:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").lower()
        else:
            parsed = urlsplit(f"https://{candidate}")
            host = (parsed.hostname or "").lower()
        if not host:
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain must be valid")
        cleaned = host.strip(".")
        if not cleaned or "." not in cleaned:
            raise SEOCompetitorProfileGenerationValidationError(
                "suggested_domain must include a top-level domain"
            )
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-." for ch in cleaned):
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain contains invalid characters")
        return cleaned

    def _normalize_competitor_type(self, raw: str) -> str:
        normalized = (raw or "").strip().lower()
        if not normalized:
            return "unknown"
        if normalized not in _ALLOWED_COMPETITOR_TYPES:
            return "unknown"
        return normalized

    def _normalize_confidence_score(self, raw: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise SEOCompetitorProfileGenerationValidationError("confidence_score must be a number") from exc
        if value < 0 or value > 1:
            raise SEOCompetitorProfileGenerationValidationError("confidence_score must be between 0 and 1")
        return value

    def _clean_required_value(self, raw: str, *, field_name: str) -> str:
        cleaned = (raw or "").strip()
        if not cleaned:
            raise SEOCompetitorProfileGenerationValidationError(f"{field_name} is required")
        return cleaned

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _default_provider_name(self) -> str:
        provider_name = self._clean_optional(str(getattr(self.provider, "provider_name", "") or ""))
        return provider_name or "pending"

    def _default_model_name(self) -> str:
        model_name = self._clean_optional(str(getattr(self.provider, "model_name", "") or ""))
        return model_name or "pending"

    def _default_prompt_version(self) -> str:
        prompt_version = self._clean_optional(str(getattr(self.provider, "prompt_version", "") or ""))
        return prompt_version or SEO_COMPETITOR_PROFILE_PROMPT_VERSION

    def _effective_lookback_days(self, lookback_days: int | None) -> int:
        if lookback_days is None:
            return self.observability_lookback_days
        return max(1, int(lookback_days))

    def _provider_error_summary(self, error: SEOCompetitorProfileProviderError) -> str:
        if error.code == "timeout":
            return PROVIDER_TIMEOUT_ERROR_SUMMARY
        if error.code in {"provider_auth", "provider_auth_config"}:
            return PROVIDER_AUTH_CONFIG_ERROR_SUMMARY
        if error.code in {"invalid_output", "schema_validation", "parsing_error"}:
            return INVALID_OUTPUT_ERROR_SUMMARY
        return GENERIC_PROVIDER_ERROR_SUMMARY

    def _provider_failure_category(self, error: SEOCompetitorProfileProviderError) -> str:
        if error.code == "timeout":
            return FAILURE_CATEGORY_TIMEOUT
        if error.code == "provider_auth":
            return FAILURE_CATEGORY_PROVIDER_AUTH
        if error.code == "provider_auth_config":
            return FAILURE_CATEGORY_PROVIDER_CONFIG
        if error.code in {"invalid_output", "parsing_error"}:
            return FAILURE_CATEGORY_MALFORMED_OUTPUT
        if error.code == "schema_validation":
            return FAILURE_CATEGORY_SCHEMA_VALIDATION
        if error.code == "provider_request":
            return FAILURE_CATEGORY_PROVIDER_REQUEST
        return FAILURE_CATEGORY_INTERNAL

    def _normalize_failure_category(self, value: str | None) -> str | None:
        normalized = (value or "").strip().lower()
        if not normalized:
            return None
        if normalized not in _ALLOWED_FAILURE_CATEGORIES:
            return FAILURE_CATEGORY_UNKNOWN
        return normalized

    def _normalize_exclusion_counts_by_reason(
        self,
        value: dict[str, int] | None,
    ) -> dict[str, int]:
        normalized = default_exclusion_reason_counts()
        if not value:
            return normalized
        for reason in EXCLUSION_REASON_KEYS:
            raw_count = value.get(reason, 0)
            try:
                normalized[reason] = max(0, int(raw_count))
            except (TypeError, ValueError):
                normalized[reason] = 0
        return normalized

    def _sanitize_raw_output(self, raw_output: str | object | None) -> str | None:
        if raw_output is None:
            return None
        if isinstance(raw_output, str):
            raw_text = raw_output
        else:
            raw_text = json.dumps(raw_output, ensure_ascii=True, sort_keys=True, default=str)
        if not raw_text:
            return None

        filtered = []
        for char in raw_text:
            if char in {"\n", "\r", "\t"} or ord(char) >= 32:
                filtered.append(char)
        normalized = "".join(filtered).strip()
        if not normalized:
            return None
        if len(normalized) > RUN_RAW_OUTPUT_MAX_CHARS:
            return normalized[: RUN_RAW_OUTPUT_MAX_CHARS - 3] + "..."
        return normalized

    def cleanup_retention(
        self,
        *,
        business_id: str,
        site_id: str | None = None,
    ) -> SEOCompetitorProfileRetentionCleanupSummary:
        self._require_business(business_id)
        site_ids = self._target_site_ids_for_cleanup(business_id=business_id, site_id=site_id)
        stale_runs_reconciled = 0
        for target_site_id in site_ids:
            stale_runs_reconciled += self._reconcile_stale_runs_for_site(
                business_id=business_id,
                site_id=target_site_id,
            )

        started_at = utc_now()
        now = started_at
        raw_output_before = now - timedelta(days=self.retention_policy.raw_output_retention_days)
        rejected_draft_before = now - timedelta(days=self.retention_policy.rejected_draft_retention_days)
        run_before = now - timedelta(days=self.retention_policy.run_retention_days)

        try:
            raw_output_pruned_runs = (
                self.seo_competitor_profile_generation_repository.prune_raw_output_for_terminal_runs(
                    business_id=business_id,
                    completed_before=raw_output_before,
                    site_id=site_id,
                )
            )
            rejected_drafts_pruned = self.seo_competitor_profile_generation_repository.prune_rejected_drafts(
                business_id=business_id,
                reviewed_before=rejected_draft_before,
                site_id=site_id,
            )
            runs_pruned = self.seo_competitor_profile_generation_repository.prune_terminal_runs_without_drafts(
                business_id=business_id,
                updated_before=run_before,
                site_id=site_id,
            )
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            self._record_cleanup_execution(
                business_id=business_id,
                site_id=site_id,
                status="failed",
                started_at=started_at,
                completed_at=utc_now(),
                stale_runs_reconciled=stale_runs_reconciled,
                raw_output_pruned_runs=0,
                rejected_drafts_pruned=0,
                runs_pruned=0,
                error_summary="Failed to run competitor profile retention cleanup",
            )
            raise SEOCompetitorProfileGenerationValidationError(
                "Failed to run competitor profile retention cleanup"
            ) from exc

        summary = SEOCompetitorProfileRetentionCleanupSummary(
            stale_runs_reconciled=stale_runs_reconciled,
            raw_output_pruned_runs=raw_output_pruned_runs,
            rejected_drafts_pruned=rejected_drafts_pruned,
            runs_pruned=runs_pruned,
        )
        self._record_cleanup_execution(
            business_id=business_id,
            site_id=site_id,
            status="completed",
            started_at=started_at,
            completed_at=utc_now(),
            stale_runs_reconciled=summary.stale_runs_reconciled,
            raw_output_pruned_runs=summary.raw_output_pruned_runs,
            rejected_drafts_pruned=summary.rejected_drafts_pruned,
            runs_pruned=summary.runs_pruned,
            error_summary=None,
        )

        logger.info(
            (
                "SEO competitor profile retention cleanup completed business_id=%s site_id=%s "
                "stale_runs_reconciled=%s raw_output_pruned_runs=%s rejected_drafts_pruned=%s runs_pruned=%s"
            ),
            business_id,
            site_id or "all",
            summary.stale_runs_reconciled,
            summary.raw_output_pruned_runs,
            summary.rejected_drafts_pruned,
            summary.runs_pruned,
        )

        return summary

    def _record_cleanup_execution(
        self,
        *,
        business_id: str,
        site_id: str | None,
        status: str,
        started_at: datetime,
        completed_at: datetime,
        stale_runs_reconciled: int,
        raw_output_pruned_runs: int,
        rejected_drafts_pruned: int,
        runs_pruned: int,
        error_summary: str | None,
    ) -> None:
        execution = SEOCompetitorProfileCleanupExecution(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            status=status,
            stale_runs_reconciled=stale_runs_reconciled,
            raw_output_pruned_runs=raw_output_pruned_runs,
            rejected_drafts_pruned=rejected_drafts_pruned,
            runs_pruned=runs_pruned,
            error_summary=error_summary,
            started_at=started_at,
            completed_at=completed_at,
        )
        try:
            self.seo_competitor_profile_generation_repository.create_cleanup_execution(execution)
            self.session.commit()
        except Exception:  # noqa: BLE001
            self.session.rollback()
            logger.exception(
                "Failed to persist competitor profile cleanup execution business_id=%s site_id=%s status=%s",
                business_id,
                site_id or "all",
                status,
            )

    def _target_site_ids_for_cleanup(self, *, business_id: str, site_id: str | None) -> list[str]:
        if site_id:
            self._require_site(business_id=business_id, site_id=site_id)
            return [site_id]
        return [item.id for item in self.seo_site_repository.list_for_business(business_id)]

    def reconcile_stale_runs(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> int:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        return self._reconcile_stale_runs_for_site(business_id=business_id, site_id=site_id)

    def _reconcile_stale_runs_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> int:
        now = utc_now()
        stale_queued_runs = self.seo_competitor_profile_generation_repository.list_stale_runs_for_business_site(
            business_id,
            site_id,
            status="queued",
            updated_before=now - STALE_QUEUED_RUN_TIMEOUT,
        )
        stale_running_runs = self.seo_competitor_profile_generation_repository.list_stale_runs_for_business_site(
            business_id,
            site_id,
            status="running",
            updated_before=now - STALE_RUNNING_RUN_TIMEOUT,
        )
        if not stale_queued_runs and not stale_running_runs:
            return 0

        for run in stale_queued_runs:
            self._set_run_failed(
                run,
                error_summary=STALE_QUEUED_RUN_ERROR_SUMMARY,
                failure_category=FAILURE_CATEGORY_TIMEOUT,
            )
            logger.warning(
                "SEO competitor profile generation stale queued run marked failed business_id=%s site_id=%s run_id=%s",
                business_id,
                site_id,
                run.id,
            )
        for run in stale_running_runs:
            self._set_run_failed(
                run,
                error_summary=STALE_RUNNING_RUN_ERROR_SUMMARY,
                failure_category=FAILURE_CATEGORY_TIMEOUT,
            )
            logger.warning(
                "SEO competitor profile generation stale running run marked failed business_id=%s site_id=%s run_id=%s",
                business_id,
                site_id,
                run.id,
            )
        self.session.commit()
        return len(stale_queued_runs) + len(stale_running_runs)

    def _set_run_failed(
        self,
        run: SEOCompetitorProfileGenerationRun,
        *,
        error_summary: str,
        provider_name: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        failure_category: str | None = None,
        raw_output: str | object | None = None,
        raw_candidate_count: int | None = None,
        included_candidate_count: int | None = None,
        excluded_candidate_count: int | None = None,
        exclusion_counts_by_reason: dict[str, int] | None = None,
    ) -> None:
        run.status = "failed"
        run.generated_draft_count = 0
        if raw_candidate_count is not None:
            run.raw_candidate_count = max(0, int(raw_candidate_count))
        if included_candidate_count is not None:
            run.included_candidate_count = max(0, int(included_candidate_count))
        else:
            run.included_candidate_count = 0
        if excluded_candidate_count is not None:
            run.excluded_candidate_count = max(0, int(excluded_candidate_count))
        if exclusion_counts_by_reason is not None:
            run.exclusion_counts_by_reason = self._normalize_exclusion_counts_by_reason(exclusion_counts_by_reason)
        elif not run.exclusion_counts_by_reason:
            run.exclusion_counts_by_reason = default_exclusion_reason_counts()
        run.error_summary = error_summary
        run.failure_category = self._normalize_failure_category(failure_category) or FAILURE_CATEGORY_UNKNOWN
        if provider_name:
            run.provider_name = provider_name
        if model_name:
            run.model_name = model_name
        if prompt_version:
            run.prompt_version = prompt_version
        if raw_output is not None:
            run.raw_output = self._sanitize_raw_output(raw_output)
        run.completed_at = utc_now()
        self.seo_competitor_profile_generation_repository.save_run(run)

    def _mark_run_failed(
        self,
        *,
        business_id: str,
        generation_run_id: str,
        reason: Exception,
        error_summary: str,
        provider_name: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        failure_category: str | None = None,
        raw_output: str | object | None = None,
        raw_candidate_count: int | None = None,
        included_candidate_count: int | None = None,
        excluded_candidate_count: int | None = None,
        exclusion_counts_by_reason: dict[str, int] | None = None,
    ) -> None:
        logger.warning(
            "SEO competitor profile generation run failed business_id=%s run_id=%s failure_category=%s reason=%s",
            business_id,
            generation_run_id,
            failure_category or FAILURE_CATEGORY_UNKNOWN,
            str(reason),
        )
        run = self.seo_competitor_profile_generation_repository.get_run_for_business(
            business_id,
            generation_run_id,
        )
        if run is None:
            return
        self._set_run_failed(
            run,
            error_summary=error_summary,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
            failure_category=failure_category,
            raw_output=raw_output,
            raw_candidate_count=raw_candidate_count,
            included_candidate_count=included_candidate_count,
            excluded_candidate_count=excluded_candidate_count,
            exclusion_counts_by_reason=exclusion_counts_by_reason,
        )
        self.session.commit()

    def _commit_with_constraint_handling(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)

    def _raise_constraint_validation_error(self, exc: IntegrityError) -> None:
        self.session.rollback()
        error_text = str(exc).lower()
        if "uq_seo_competitor_domains_business_set_domain" in error_text:
            raise SEOCompetitorProfileGenerationValidationError(
                "A competitor domain with this host already exists in the set"
            ) from exc
        if "uq_seo_competitor_profile_drafts_business_run_domain" in error_text:
            raise SEOCompetitorProfileGenerationValidationError(
                "Duplicate suggested domain generated for this run"
            ) from exc
        if "uq_seo_competitor_sets_business_site_name" in error_text:
            raise SEOCompetitorProfileGenerationValidationError(
                "Generated competitor set name conflicts with an existing set"
            ) from exc
        raise SEOCompetitorProfileGenerationValidationError(
            "Competitor profile generation data violated a database constraint"
        ) from exc

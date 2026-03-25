from __future__ import annotations

from dataclasses import dataclass, field
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
from app.models.business import Business
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
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
    CompetitorCandidateDomainProbe,
    CompetitorCandidateDomainProbeResult,
    CompetitorCandidateEligibilityDecision,
    CompetitorCandidateTuningRejection,
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
    INELIGIBILITY_REASON_KEYS,
    TUNING_EXCLUSION_REASON_KEYS,
    filter_eligible_competitor_candidates,
    default_exclusion_reason_counts,
    process_competitor_candidates,
)
from app.services.seo_competitor_profile_prompt import SEO_COMPETITOR_PROFILE_PROMPT_VERSION
from app.services.seo_competitor_profile_prompt import (
    SEO_COMPETITOR_PROFILE_PROMPT_LABEL,
    build_seo_competitor_profile_prompt,
)
from app.services.ai_prompt_settings import ResolvedAIPromptText, resolve_ai_prompt_text
from app.services.seo_crawler import SEOCrawler


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
DEFAULT_PREVIEW_ACCURACY_LAST_N = 10
COMPETITOR_DOMAIN_PROBE_TIMEOUT_SECONDS = 4
COMPETITOR_DOMAIN_PROBE_MAX_RESPONSE_BYTES = 200_000
COMPETITOR_DOMAIN_PROBE_MAX_REDIRECTS = 3
COMPETITOR_DOMAIN_PROBE_TEST_TLDS = (".example", ".invalid", ".test", ".localhost")
REJECTED_CANDIDATE_DEBUG_MAX_ITEMS = 20
REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS = 240
_REJECTED_CANDIDATE_DEBUG_KEY = "rejected_candidates_debug"
_REJECTED_CANDIDATE_DEBUG_COUNT_KEY = "rejected_candidate_count"
_TUNING_REJECTED_CANDIDATE_DEBUG_KEY = "tuning_rejected_candidates_debug"
_TUNING_REJECTED_CANDIDATE_DEBUG_COUNT_KEY = "tuning_rejected_candidate_count"
_TUNING_REJECTION_REASON_COUNTS_KEY = "tuning_rejection_reason_counts"
_CANDIDATE_PIPELINE_SUMMARY_KEY = "candidate_pipeline_summary_debug"
_SITE_CONTENT_SIGNALS_ATTR = "_seo_site_content_signals"
_MAX_SITE_CONTENT_SIGNAL_PAGES = 40
_MAX_SITE_CONTENT_SIGNALS = 120
_MAX_SITE_CONTENT_SIGNAL_LENGTH = 200

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
    rejected_candidate_count: int = 0
    rejected_candidates: list["SEOCompetitorProfileRejectedCandidateDebug"] = field(default_factory=list)
    tuning_rejected_candidate_count: int = 0
    tuning_rejected_candidates: list["SEOCompetitorProfileTuningRejectedCandidateDebug"] = field(default_factory=list)
    tuning_rejection_reason_counts: dict[str, int] = field(default_factory=dict)
    candidate_pipeline_summary: "SEOCompetitorProfileCandidatePipelineSummary | None" = None


@dataclass(frozen=True)
class SEOCompetitorPromptPreview:
    system_prompt: str
    user_prompt: str
    model_name: str | None
    prompt_version: str
    prompt_label: str | None
    prompt_source: str | None
    trusted_site_context: dict[str, object]
    prompt_metrics: dict[str, int]


@dataclass(frozen=True)
class SEOCompetitorProfileRejectedCandidateDebug:
    domain: str
    reasons: tuple[str, ...]
    summary: str | None


@dataclass(frozen=True)
class SEOCompetitorProfileTuningRejectedCandidateDebug:
    domain: str
    reasons: tuple[str, ...]
    final_score: int | None
    summary: str | None


@dataclass(frozen=True)
class SEOCompetitorProfileCandidatePipelineSummary:
    proposed_candidate_count: int
    rejected_by_eligibility_count: int
    eligible_candidate_count: int
    rejected_by_tuning_count: int
    survived_tuning_count: int
    removed_by_existing_domain_match_count: int
    removed_by_deduplication_count: int
    removed_by_final_limit_count: int
    final_candidate_count: int


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
    ineligible_candidate_count: int
    excluded_candidate_count: int
    exclusion_counts_by_reason: dict[str, int]
    ineligibility_counts_by_reason: dict[str, int]
    rejected_candidates: list[SEOCompetitorProfileRejectedCandidateDebug]
    tuning_rejected_candidates: list[SEOCompetitorProfileTuningRejectedCandidateDebug]
    tuning_rejection_reason_counts: dict[str, int]
    candidate_pipeline_summary: SEOCompetitorProfileCandidatePipelineSummary


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
    preview_accuracy_rate: float | None
    avg_error_margin: float | None
    last_n_preview_accuracy: dict[str, float | int | None]
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


def build_default_competitor_candidate_domain_probe() -> CompetitorCandidateDomainProbe:
    crawler = SEOCrawler(
        timeout_seconds=COMPETITOR_DOMAIN_PROBE_TIMEOUT_SECONDS,
        max_retries=0,
        max_redirects=COMPETITOR_DOMAIN_PROBE_MAX_REDIRECTS,
        max_response_bytes=COMPETITOR_DOMAIN_PROBE_MAX_RESPONSE_BYTES,
        max_workers=1,
    )

    def _probe(domain: str) -> CompetitorCandidateDomainProbeResult | None:
        normalized = (domain or "").strip().lower().strip(".")
        if not normalized:
            return None
        if any(normalized.endswith(tld) for tld in COMPETITOR_DOMAIN_PROBE_TEST_TLDS):
            return None
        try:
            pages = crawler.crawl(
                base_url=f"https://{normalized}/",
                max_pages=1,
                max_depth=0,
                same_domain_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            return CompetitorCandidateDomainProbeResult(
                status_code=None,
                body_text=None,
                fetch_error=str(exc),
            )
        if not pages:
            return CompetitorCandidateDomainProbeResult(
                status_code=None,
                body_text=None,
                fetch_error="empty_probe_result",
            )
        page = pages[0]
        return CompetitorCandidateDomainProbeResult(
            status_code=page.status_code if page.status_code > 0 else None,
            body_text=page.body_text,
            fetch_error=page.fetch_error,
        )

    return _probe


class SEOCompetitorProfileGenerationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_audit_repository: SEOAuditRepository | None = None,
        seo_competitor_repository: SEOCompetitorRepository,
        seo_competitor_profile_generation_repository: SEOCompetitorProfileGenerationRepository,
        provider: SEOCompetitorProfileGenerationProvider,
        candidate_domain_probe: CompetitorCandidateDomainProbe | None = None,
        retention_policy: SEOCompetitorProfileRetentionPolicy = SEOCompetitorProfileRetentionPolicy(),
        observability_lookback_days: int = DEFAULT_OBSERVABILITY_LOOKBACK_DAYS,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_audit_repository = seo_audit_repository
        self.seo_competitor_repository = seo_competitor_repository
        self.seo_competitor_profile_generation_repository = seo_competitor_profile_generation_repository
        self.provider = provider
        self.candidate_domain_probe = candidate_domain_probe
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
        business = self._require_business(business_id)
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
            self._attach_site_content_signals(site=site, business_id=business_id, site_id=site_id)
            self._apply_resolved_competitor_prompt_settings(business)
            output = self.provider.generate_competitor_profiles(
                site=site,
                existing_domains=existing_domains,
                candidate_count=run.requested_candidate_count,
            )
            provider_name = self._clean_required_value(output.provider_name, field_name="provider_name")
            model_name = self._clean_required_value(output.model_name, field_name="model_name")
            prompt_version = self._clean_required_value(output.prompt_version, field_name="prompt_version")
            raw_output = output.raw_response

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
            raw_output = self._embed_competitor_debug_in_raw_output(
                raw_output=raw_output,
                rejected_candidates=draft_result.rejected_candidates,
                tuning_rejected_candidates=draft_result.tuning_rejected_candidates,
                tuning_rejection_reason_counts=draft_result.tuning_rejection_reason_counts,
                candidate_pipeline_summary=draft_result.candidate_pipeline_summary,
            )
            raw_output = self._sanitize_raw_output(raw_output)
            run.raw_output = raw_output
            run.error_summary = None
            run.completed_at = utc_now()
            self.seo_competitor_profile_generation_repository.save_run(run)
            for draft in drafts:
                self.seo_competitor_profile_generation_repository.create_draft(draft)
            try:
                self._evaluate_pending_preview_accuracy_for_completed_run(
                    business_id=business_id,
                    site_id=site_id,
                    run=run,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    (
                        "SEO competitor profile preview accuracy evaluation failed "
                        "business_id=%s site_id=%s run_id=%s reason=%s"
                    ),
                    business_id,
                    site_id,
                    run.id,
                    str(exc),
                )
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
                    "deduped_candidates=%s ineligible_candidates=%s excluded_candidates=%s included_candidates=%s"
                ),
                run.id,
                draft_result.raw_candidate_count,
                draft_result.deduped_candidate_count,
                draft_result.ineligible_candidate_count,
                draft_result.excluded_candidate_count,
                len(drafts),
            )
            logger.info(
                "SEO competitor profile exclusion telemetry run_id=%s exclusion_counts_by_reason=%s",
                run.id,
                run.exclusion_counts_by_reason,
            )
            if draft_result.ineligible_candidate_count > 0:
                logger.info(
                    "SEO competitor profile ineligibility telemetry run_id=%s ineligibility_counts_by_reason=%s",
                    run.id,
                    draft_result.ineligibility_counts_by_reason,
                )
            return SEOCompetitorProfileGenerationRunDetail(
                run=run,
                drafts=drafts,
                rejected_candidate_count=max(0, len(draft_result.rejected_candidates)),
                rejected_candidates=draft_result.rejected_candidates,
                tuning_rejected_candidate_count=max(0, len(draft_result.tuning_rejected_candidates)),
                tuning_rejected_candidates=draft_result.tuning_rejected_candidates,
                tuning_rejection_reason_counts=draft_result.tuning_rejection_reason_counts,
                candidate_pipeline_summary=draft_result.candidate_pipeline_summary,
            )
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
            failure_raw_output = raw_output
            if draft_result is not None:
                failure_raw_output = self._embed_competitor_debug_in_raw_output(
                    raw_output=raw_output,
                    rejected_candidates=draft_result.rejected_candidates,
                    tuning_rejected_candidates=draft_result.tuning_rejected_candidates,
                    tuning_rejection_reason_counts=draft_result.tuning_rejection_reason_counts,
                    candidate_pipeline_summary=draft_result.candidate_pipeline_summary,
                )
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=INVALID_QUALITY_TUNING_ERROR_SUMMARY,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
                failure_category=FAILURE_CATEGORY_INTERNAL,
                raw_output=failure_raw_output,
                raw_candidate_count=draft_result.raw_candidate_count if draft_result else None,
                included_candidate_count=draft_result.included_candidate_count if draft_result else None,
                excluded_candidate_count=draft_result.excluded_candidate_count if draft_result else None,
                exclusion_counts_by_reason=draft_result.exclusion_counts_by_reason if draft_result else None,
            )
            return None
        except SEOCompetitorProfileGenerationValidationError as exc:
            self.session.rollback()
            failure_raw_output = raw_output
            if draft_result is not None:
                failure_raw_output = self._embed_competitor_debug_in_raw_output(
                    raw_output=raw_output,
                    rejected_candidates=draft_result.rejected_candidates,
                    tuning_rejected_candidates=draft_result.tuning_rejected_candidates,
                    tuning_rejection_reason_counts=draft_result.tuning_rejection_reason_counts,
                    candidate_pipeline_summary=draft_result.candidate_pipeline_summary,
                )
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=INVALID_OUTPUT_ERROR_SUMMARY,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
                failure_category=FAILURE_CATEGORY_MALFORMED_OUTPUT,
                raw_output=failure_raw_output,
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
        rejected_candidate_count, rejected_candidates = self._extract_rejected_candidates_debug_from_raw_output(
            run.raw_output
        )
        tuning_rejected_candidate_count, tuning_rejected_candidates, tuning_rejection_reason_counts = (
            self._extract_tuning_rejected_candidates_debug_from_raw_output(run.raw_output)
        )
        candidate_pipeline_summary = self._extract_candidate_pipeline_summary_from_raw_output(run.raw_output)
        if candidate_pipeline_summary is None:
            candidate_pipeline_summary = self._derive_candidate_pipeline_summary_from_run(run)
        return SEOCompetitorProfileGenerationRunDetail(
            run=run,
            drafts=drafts,
            rejected_candidate_count=rejected_candidate_count,
            rejected_candidates=rejected_candidates,
            tuning_rejected_candidate_count=tuning_rejected_candidate_count,
            tuning_rejected_candidates=tuning_rejected_candidates,
            tuning_rejection_reason_counts=tuning_rejection_reason_counts,
            candidate_pipeline_summary=candidate_pipeline_summary,
        )

    def build_prompt_preview(
        self,
        *,
        business_id: str,
        site_id: str,
        candidate_count: int,
        prompt_version: str | None = None,
    ) -> SEOCompetitorPromptPreview | None:
        try:
            business = self._require_business(business_id)
            site = self._require_site(business_id=business_id, site_id=site_id)
        except SEOCompetitorProfileGenerationNotFoundError:
            return None

        bounded_candidate_count = max(1, int(candidate_count))
        resolved_prompt_version = (
            self._clean_optional(prompt_version) or self._default_prompt_version()
        )
        resolved_prompt = self._resolve_competitor_prompt_settings(business)
        self._attach_site_content_signals(site=site, business_id=business_id, site_id=site_id)
        prompt = build_seo_competitor_profile_prompt(
            site=site,
            existing_domains=[
                item.domain
                for item in self.seo_competitor_repository.list_domains_for_business_site(
                    business_id,
                    site_id,
                )
            ],
            candidate_count=bounded_candidate_count,
            prompt_version=resolved_prompt_version,
            prompt_text_competitor=resolved_prompt.prompt_text,
        )
        return SEOCompetitorPromptPreview(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            model_name=self._clean_optional(self._default_model_name()),
            prompt_version=prompt.prompt_version,
            prompt_label=SEO_COMPETITOR_PROFILE_PROMPT_LABEL,
            prompt_source=resolved_prompt.prompt_source,
            trusted_site_context=prompt.trusted_site_context,
            prompt_metrics=prompt.prompt_telemetry,
        )

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
        (
            total_runs,
            total_raw_candidate_count,
            total_included_candidate_count,
            total_excluded_candidate_count,
        ) = self.seo_competitor_profile_generation_repository.summarize_candidate_telemetry_totals(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        exclusion_reason_counts = (
            self.seo_competitor_profile_generation_repository.list_exclusion_reason_counts_for_business_site_created_after(
                business_id=business_id,
                site_id=site_id,
                created_after=window_start,
            )
        )

        exclusion_counts_by_reason = default_exclusion_reason_counts()
        for raw_counts in exclusion_reason_counts:
            normalized_counts = self._normalize_exclusion_counts_by_reason(raw_counts)
            for reason in EXCLUSION_REASON_KEYS:
                exclusion_counts_by_reason[reason] += normalized_counts[reason]

        evaluated_preview_count, evaluated_direction_correct_count, avg_error_margin = (
            self.seo_competitor_profile_generation_repository.summarize_preview_accuracy_metrics(
                business_id=business_id,
                site_id=site_id,
                evaluated_after=window_start,
            )
        )
        preview_accuracy_rate = None
        if evaluated_preview_count > 0:
            preview_accuracy_rate = evaluated_direction_correct_count / evaluated_preview_count
        (
            last_n_sample_size,
            last_n_direction_correct_count,
            last_n_avg_error_margin,
        ) = self.seo_competitor_profile_generation_repository.summarize_last_n_preview_accuracy(
            business_id=business_id,
            site_id=site_id,
            limit=DEFAULT_PREVIEW_ACCURACY_LAST_N,
        )
        last_n_accuracy_rate = None
        if last_n_sample_size > 0:
            last_n_accuracy_rate = last_n_direction_correct_count / last_n_sample_size

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
            preview_accuracy_rate=preview_accuracy_rate,
            avg_error_margin=avg_error_margin,
            last_n_preview_accuracy={
                "window_size": DEFAULT_PREVIEW_ACCURACY_LAST_N,
                "sample_size": last_n_sample_size,
                "direction_correct_count": last_n_direction_correct_count,
                "accuracy_rate": last_n_accuracy_rate,
                "avg_error_margin": last_n_avg_error_margin,
            },
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

        eligibility_result = filter_eligible_competitor_candidates(
            site=site,
            candidates=prepared_candidates,
            domain_probe=self.candidate_domain_probe,
        )
        rejected_candidates = self._build_rejected_candidate_debug(
            decisions=eligibility_result.decisions,
        )
        quality_tuning = self._resolve_candidate_quality_tuning(business_id=run.business_id)
        candidate_processing = process_competitor_candidates(
            site=site,
            candidates=eligibility_result.eligible_candidates,
            existing_domains=existing_domains,
            quality_tuning=quality_tuning,
        )
        tuning_rejected_candidates = self._build_tuning_rejected_candidate_debug(
            rejections=candidate_processing.tuning_rejected_candidates,
        )
        tuning_rejection_reason_counts = self._normalize_tuning_rejection_reason_counts(
            candidate_processing.tuning_rejection_reason_counts
        )
        exclusion_counts_by_reason = self._normalize_exclusion_counts_by_reason(
            candidate_processing.exclusion_counts_by_reason
        )
        exclusion_counts_by_reason["invalid_candidate"] = (
            int(exclusion_counts_by_reason.get("invalid_candidate", 0))
            + eligibility_result.ineligible_candidate_count
        )

        proposed_candidate_count = len(prepared_candidates)
        rejected_by_eligibility_count = eligibility_result.ineligible_candidate_count
        eligible_candidate_count = len(eligibility_result.eligible_candidates)
        rejected_by_tuning_count = max(0, len(candidate_processing.tuning_rejected_candidates))
        survived_tuning_count = max(0, eligible_candidate_count - rejected_by_tuning_count)
        removed_by_existing_domain_match_count = max(
            0,
            self._coerce_int(candidate_processing.exclusion_counts_by_reason.get("existing_domain_match"), default=0),
        )
        removed_by_deduplication_count = max(
            0,
            self._coerce_int(candidate_processing.exclusion_counts_by_reason.get("duplicate"), default=0),
        )
        bounded_requested_candidate_count = max(1, int(run.requested_candidate_count or 1))
        final_candidates = candidate_processing.included_candidates[:bounded_requested_candidate_count]
        removed_by_final_limit_count = max(
            0,
            len(candidate_processing.included_candidates) - len(final_candidates),
        )

        drafts: list[SEOCompetitorProfileDraft] = []
        for candidate in final_candidates:
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
            raw_candidate_count=proposed_candidate_count,
            included_candidate_count=len(drafts),
            deduped_candidate_count=candidate_processing.deduped_candidate_count,
            ineligible_candidate_count=eligibility_result.ineligible_candidate_count,
            excluded_candidate_count=(
                candidate_processing.excluded_candidate_count
                + eligibility_result.ineligible_candidate_count
                + removed_by_final_limit_count
            ),
            exclusion_counts_by_reason=exclusion_counts_by_reason,
            ineligibility_counts_by_reason=eligibility_result.ineligibility_counts_by_reason,
            rejected_candidates=rejected_candidates,
            tuning_rejected_candidates=tuning_rejected_candidates,
            tuning_rejection_reason_counts=tuning_rejection_reason_counts,
            candidate_pipeline_summary=SEOCompetitorProfileCandidatePipelineSummary(
                proposed_candidate_count=proposed_candidate_count,
                rejected_by_eligibility_count=rejected_by_eligibility_count,
                eligible_candidate_count=eligible_candidate_count,
                rejected_by_tuning_count=rejected_by_tuning_count,
                survived_tuning_count=survived_tuning_count,
                removed_by_existing_domain_match_count=removed_by_existing_domain_match_count,
                removed_by_deduplication_count=removed_by_deduplication_count,
                removed_by_final_limit_count=removed_by_final_limit_count,
                final_candidate_count=len(drafts),
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

    def _require_business(self, business_id: str) -> Business:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorProfileGenerationNotFoundError("Business not found")
        return business

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

    def _provider_prompt_text_competitor(self) -> str:
        prompt_text = getattr(self.provider, "prompt_text_competitor", None)
        if prompt_text is None:
            prompt_text = getattr(self.provider, "prompt_text_recommendation", "")
        cleaned = self._clean_optional(str(prompt_text or ""))
        return cleaned or ""

    def _provider_prompt_legacy_config_used(self) -> bool:
        return bool(getattr(self.provider, "legacy_config_used", False))

    def _resolve_competitor_prompt_settings(self, business: Business) -> ResolvedAIPromptText:
        return resolve_ai_prompt_text(
            admin_prompt_text=getattr(business, "ai_prompt_text_competitor", None),
            env_prompt_text=self._provider_prompt_text_competitor(),
            env_legacy_config_used=self._provider_prompt_legacy_config_used(),
        )

    def _apply_resolved_competitor_prompt_settings(self, business: Business) -> None:
        resolved = self._resolve_competitor_prompt_settings(business)
        if hasattr(self.provider, "prompt_text_competitor"):
            setattr(self.provider, "prompt_text_competitor", resolved.prompt_text)
        # DEPRECATED: maintain backward compatibility for legacy prompt-text access.
        if hasattr(self.provider, "prompt_text_recommendation"):
            setattr(self.provider, "prompt_text_recommendation", resolved.prompt_text)
        if hasattr(self.provider, "prompt_source"):
            setattr(self.provider, "prompt_source", resolved.prompt_source)
        if hasattr(self.provider, "legacy_config_used"):
            setattr(self.provider, "legacy_config_used", resolved.legacy_config_used)

    def _attach_site_content_signals(self, *, site: SEOSite, business_id: str, site_id: str) -> None:
        signals = self._load_site_content_signals(business_id=business_id, site_id=site_id)
        setattr(site, _SITE_CONTENT_SIGNALS_ATTR, signals)

    def _load_site_content_signals(self, *, business_id: str, site_id: str) -> list[str]:
        if self.seo_audit_repository is None:
            return []
        latest_completed_run = self.seo_audit_repository.get_latest_completed_run_for_business_site(
            business_id,
            site_id,
        )
        if latest_completed_run is None:
            return []
        pages = self.seo_audit_repository.list_pages_for_business_run(
            business_id,
            latest_completed_run.id,
        )
        if not pages:
            return []
        return self._extract_site_content_signals_from_pages(pages[:_MAX_SITE_CONTENT_SIGNAL_PAGES])

    def _extract_site_content_signals_from_pages(self, pages: list[SEOAuditPage]) -> list[str]:
        signals: list[str] = []
        seen: set[str] = set()

        def add_signal(raw: str | None) -> None:
            if len(signals) >= _MAX_SITE_CONTENT_SIGNALS:
                return
            cleaned = self._clean_optional(raw)
            if cleaned is None:
                return
            if len(cleaned) > _MAX_SITE_CONTENT_SIGNAL_LENGTH:
                cleaned = cleaned[:_MAX_SITE_CONTENT_SIGNAL_LENGTH]
            lowered = cleaned.lower()
            if lowered in seen:
                return
            seen.add(lowered)
            signals.append(cleaned)

        for page in pages:
            add_signal(page.title)
            add_signal(page.meta_description)
            if isinstance(page.h1_json, list):
                for item in page.h1_json[:4]:
                    add_signal(str(item) if item is not None else None)
            if isinstance(page.h2_json, list):
                for item in page.h2_json[:6]:
                    add_signal(str(item) if item is not None else None)
            for path_phrase in self._extract_path_phrases(page.url):
                add_signal(path_phrase)

        return signals

    def _extract_path_phrases(self, url: str | None) -> list[str]:
        if not url:
            return []
        try:
            parsed = urlsplit(url)
        except ValueError:
            return []
        path = (parsed.path or "").strip("/")
        if not path:
            return []
        phrases: list[str] = []
        for segment in path.split("/"):
            normalized = segment.replace("-", " ").replace("_", " ")
            normalized = " ".join(normalized.split()).strip()
            if not normalized:
                continue
            if normalized.lower() in {"about", "contact", "home", "services"}:
                continue
            phrases.append(normalized)
        return phrases

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

    def _normalize_tuning_rejection_reason_counts(
        self,
        value: dict[str, int] | None,
    ) -> dict[str, int]:
        normalized = {reason: 0 for reason in TUNING_EXCLUSION_REASON_KEYS}
        if not value:
            return normalized
        for reason in TUNING_EXCLUSION_REASON_KEYS:
            raw_count = value.get(reason, 0)
            try:
                normalized[reason] = max(0, int(raw_count))
            except (TypeError, ValueError):
                normalized[reason] = 0
        return normalized

    def _derive_candidate_pipeline_summary_from_run(
        self,
        run: SEOCompetitorProfileGenerationRun,
    ) -> SEOCompetitorProfileCandidatePipelineSummary | None:
        proposed_candidate_count = max(0, int(run.raw_candidate_count or 0))
        final_candidate_count = max(0, int(run.included_candidate_count or 0))
        excluded_candidate_count = max(0, int(run.excluded_candidate_count or 0))
        if proposed_candidate_count <= 0 and final_candidate_count <= 0 and excluded_candidate_count <= 0:
            return None

        exclusion_counts_by_reason = (
            run.exclusion_counts_by_reason if isinstance(run.exclusion_counts_by_reason, dict) else {}
        )
        rejected_by_eligibility_count = max(
            0,
            self._coerce_int(exclusion_counts_by_reason.get("invalid_candidate"), default=0),
        )
        eligible_candidate_count = max(0, proposed_candidate_count - rejected_by_eligibility_count)
        removed_by_existing_domain_match_count = max(
            0,
            self._coerce_int(exclusion_counts_by_reason.get("existing_domain_match"), default=0),
        )
        removed_by_deduplication_count = max(
            0,
            self._coerce_int(exclusion_counts_by_reason.get("duplicate"), default=0),
        )
        rejected_by_tuning_count = max(
            0,
            excluded_candidate_count
            - rejected_by_eligibility_count
            - removed_by_existing_domain_match_count
            - removed_by_deduplication_count,
        )
        survived_tuning_count = max(0, eligible_candidate_count - rejected_by_tuning_count)
        included_before_final_limit_count = max(
            0,
            survived_tuning_count - removed_by_existing_domain_match_count - removed_by_deduplication_count,
        )
        removed_by_final_limit_count = max(0, included_before_final_limit_count - final_candidate_count)

        return SEOCompetitorProfileCandidatePipelineSummary(
            proposed_candidate_count=proposed_candidate_count,
            rejected_by_eligibility_count=rejected_by_eligibility_count,
            eligible_candidate_count=eligible_candidate_count,
            rejected_by_tuning_count=rejected_by_tuning_count,
            survived_tuning_count=survived_tuning_count,
            removed_by_existing_domain_match_count=removed_by_existing_domain_match_count,
            removed_by_deduplication_count=removed_by_deduplication_count,
            removed_by_final_limit_count=removed_by_final_limit_count,
            final_candidate_count=final_candidate_count,
        )

    def _build_rejected_candidate_debug(
        self,
        *,
        decisions: list[CompetitorCandidateEligibilityDecision],
    ) -> list[SEOCompetitorProfileRejectedCandidateDebug]:
        rejected: list[SEOCompetitorProfileRejectedCandidateDebug] = []
        for decision in decisions:
            if decision.is_eligible:
                continue
            domain = self._clean_optional(decision.candidate.suggested_domain)
            if domain is None:
                continue
            reasons = self._normalize_rejected_candidate_reasons(decision.ineligibility_reasons)
            if not reasons:
                continue
            rejected.append(
                SEOCompetitorProfileRejectedCandidateDebug(
                    domain=domain,
                    reasons=reasons,
                    summary=self._build_rejected_candidate_summary(decision.candidate),
                )
            )
            if len(rejected) >= REJECTED_CANDIDATE_DEBUG_MAX_ITEMS:
                break
        return rejected

    def _build_tuning_rejected_candidate_debug(
        self,
        *,
        rejections: list[CompetitorCandidateTuningRejection],
    ) -> list[SEOCompetitorProfileTuningRejectedCandidateDebug]:
        rejected: list[SEOCompetitorProfileTuningRejectedCandidateDebug] = []
        for rejection in rejections:
            domain = self._clean_optional(rejection.suggested_domain)
            if domain is None:
                continue
            reasons = self._normalize_tuning_rejection_reasons(rejection.reasons)
            if not reasons:
                continue
            final_score = None
            if rejection.final_score is not None:
                try:
                    final_score = max(0, int(rejection.final_score))
                except (TypeError, ValueError):
                    final_score = None
            summary = self._clean_optional(rejection.summary)
            if summary and len(summary) > REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS:
                summary = summary[: REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS - 3] + "..."
            rejected.append(
                SEOCompetitorProfileTuningRejectedCandidateDebug(
                    domain=domain,
                    reasons=reasons,
                    final_score=final_score,
                    summary=summary,
                )
            )
            if len(rejected) >= REJECTED_CANDIDATE_DEBUG_MAX_ITEMS:
                break
        return rejected

    @staticmethod
    def _normalize_rejected_candidate_reasons(raw_reasons: tuple[str, ...] | list[str] | object) -> tuple[str, ...]:
        if not isinstance(raw_reasons, (list, tuple)):
            return tuple()
        allowed = set(INELIGIBILITY_REASON_KEYS)
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_reason in raw_reasons:
            reason = str(raw_reason or "").strip().lower()
            if not reason or reason not in allowed or reason in seen:
                continue
            seen.add(reason)
            normalized.append(reason)
        return tuple(normalized)

    @staticmethod
    def _normalize_tuning_rejection_reasons(raw_reasons: tuple[str, ...] | list[str] | object) -> tuple[str, ...]:
        if not isinstance(raw_reasons, (list, tuple)):
            return tuple()
        allowed = set(TUNING_EXCLUSION_REASON_KEYS)
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_reason in raw_reasons:
            reason = str(raw_reason or "").strip().lower()
            if not reason or reason not in allowed or reason in seen:
                continue
            seen.add(reason)
            normalized.append(reason)
        return tuple(normalized)

    def _build_rejected_candidate_summary(self, candidate: CompetitorCandidateInput) -> str | None:
        for raw_value in (candidate.why_competitor, candidate.summary, candidate.evidence):
            cleaned = self._clean_optional(raw_value)
            if not cleaned:
                continue
            if len(cleaned) <= REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS:
                return cleaned
            return cleaned[: REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS - 3] + "..."
        return None

    def _embed_competitor_debug_in_raw_output(
        self,
        *,
        raw_output: str | None,
        rejected_candidates: list[SEOCompetitorProfileRejectedCandidateDebug],
        tuning_rejected_candidates: list[SEOCompetitorProfileTuningRejectedCandidateDebug],
        tuning_rejection_reason_counts: dict[str, int],
        candidate_pipeline_summary: SEOCompetitorProfileCandidatePipelineSummary | None,
    ) -> str | None:
        if (
            not raw_output
            or (
                not rejected_candidates
                and not tuning_rejected_candidates
                and not any(value > 0 for value in tuning_rejection_reason_counts.values())
                and candidate_pipeline_summary is None
            )
        ):
            return raw_output
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return raw_output
        if not isinstance(parsed, dict):
            return raw_output

        if rejected_candidates:
            serialized_rejected: list[dict[str, object]] = []
            for item in rejected_candidates[:REJECTED_CANDIDATE_DEBUG_MAX_ITEMS]:
                serialized_rejected.append(
                    {
                        "domain": item.domain,
                        "reasons": list(item.reasons),
                        "summary": item.summary,
                    }
                )
            parsed[_REJECTED_CANDIDATE_DEBUG_COUNT_KEY] = max(0, len(rejected_candidates))
            parsed[_REJECTED_CANDIDATE_DEBUG_KEY] = serialized_rejected

        if tuning_rejected_candidates:
            serialized_tuning_rejected: list[dict[str, object]] = []
            for item in tuning_rejected_candidates[:REJECTED_CANDIDATE_DEBUG_MAX_ITEMS]:
                serialized_tuning_rejected.append(
                    {
                        "domain": item.domain,
                        "reasons": list(item.reasons),
                        "final_score": item.final_score,
                        "summary": item.summary,
                    }
                )
            parsed[_TUNING_REJECTED_CANDIDATE_DEBUG_COUNT_KEY] = max(0, len(tuning_rejected_candidates))
            parsed[_TUNING_REJECTED_CANDIDATE_DEBUG_KEY] = serialized_tuning_rejected

        normalized_reason_counts = self._normalize_tuning_rejection_reason_counts(
            tuning_rejection_reason_counts
        )
        if any(value > 0 for value in normalized_reason_counts.values()):
            parsed[_TUNING_REJECTION_REASON_COUNTS_KEY] = normalized_reason_counts
        if candidate_pipeline_summary is not None:
            parsed[_CANDIDATE_PIPELINE_SUMMARY_KEY] = {
                "proposed_candidate_count": max(0, int(candidate_pipeline_summary.proposed_candidate_count)),
                "rejected_by_eligibility_count": max(0, int(candidate_pipeline_summary.rejected_by_eligibility_count)),
                "eligible_candidate_count": max(0, int(candidate_pipeline_summary.eligible_candidate_count)),
                "rejected_by_tuning_count": max(0, int(candidate_pipeline_summary.rejected_by_tuning_count)),
                "survived_tuning_count": max(0, int(candidate_pipeline_summary.survived_tuning_count)),
                "removed_by_existing_domain_match_count": max(
                    0,
                    int(candidate_pipeline_summary.removed_by_existing_domain_match_count),
                ),
                "removed_by_deduplication_count": max(
                    0,
                    int(candidate_pipeline_summary.removed_by_deduplication_count),
                ),
                "removed_by_final_limit_count": max(0, int(candidate_pipeline_summary.removed_by_final_limit_count)),
                "final_candidate_count": max(0, int(candidate_pipeline_summary.final_candidate_count)),
            }
        try:
            return json.dumps(parsed, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            return raw_output

    def _extract_rejected_candidates_debug_from_raw_output(
        self,
        raw_output: str | None,
    ) -> tuple[int, list[SEOCompetitorProfileRejectedCandidateDebug]]:
        if not raw_output:
            return 0, []
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0, []
        if not isinstance(parsed, dict):
            return 0, []

        raw_candidates = parsed.get(_REJECTED_CANDIDATE_DEBUG_KEY)
        if not isinstance(raw_candidates, list):
            return 0, []

        rejected_candidates: list[SEOCompetitorProfileRejectedCandidateDebug] = []
        for raw_item in raw_candidates[:REJECTED_CANDIDATE_DEBUG_MAX_ITEMS]:
            if not isinstance(raw_item, dict):
                continue
            domain = self._clean_optional(
                str(raw_item.get("domain") or "")
            )
            if domain is None:
                continue
            reasons = self._normalize_rejected_candidate_reasons(raw_item.get("reasons"))
            if not reasons:
                continue
            summary = self._clean_optional(str(raw_item.get("summary") or "")) if raw_item.get("summary") else None
            if summary and len(summary) > REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS:
                summary = summary[: REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS - 3] + "..."
            rejected_candidates.append(
                SEOCompetitorProfileRejectedCandidateDebug(
                    domain=domain,
                    reasons=reasons,
                    summary=summary,
                )
            )

        raw_count = parsed.get(_REJECTED_CANDIDATE_DEBUG_COUNT_KEY)
        try:
            rejected_candidate_count = max(0, int(raw_count))
        except (TypeError, ValueError):
            rejected_candidate_count = len(rejected_candidates)
        rejected_candidate_count = max(rejected_candidate_count, len(rejected_candidates))
        return rejected_candidate_count, rejected_candidates

    def _extract_tuning_rejected_candidates_debug_from_raw_output(
        self,
        raw_output: str | None,
    ) -> tuple[int, list[SEOCompetitorProfileTuningRejectedCandidateDebug], dict[str, int]]:
        empty_reason_counts = self._normalize_tuning_rejection_reason_counts(None)
        if not raw_output:
            return 0, [], empty_reason_counts
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0, [], empty_reason_counts
        if not isinstance(parsed, dict):
            return 0, [], empty_reason_counts

        raw_candidates = parsed.get(_TUNING_REJECTED_CANDIDATE_DEBUG_KEY)
        if not isinstance(raw_candidates, list):
            raw_candidates = []

        tuning_rejected_candidates: list[SEOCompetitorProfileTuningRejectedCandidateDebug] = []
        for raw_item in raw_candidates[:REJECTED_CANDIDATE_DEBUG_MAX_ITEMS]:
            if not isinstance(raw_item, dict):
                continue
            domain = self._clean_optional(str(raw_item.get("domain") or ""))
            if domain is None:
                continue
            reasons = self._normalize_tuning_rejection_reasons(raw_item.get("reasons"))
            if not reasons:
                continue
            final_score: int | None = None
            raw_final_score = raw_item.get("final_score")
            if raw_final_score is not None:
                try:
                    final_score = max(0, int(raw_final_score))
                except (TypeError, ValueError):
                    final_score = None
            summary = self._clean_optional(str(raw_item.get("summary") or "")) if raw_item.get("summary") else None
            if summary and len(summary) > REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS:
                summary = summary[: REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS - 3] + "..."
            tuning_rejected_candidates.append(
                SEOCompetitorProfileTuningRejectedCandidateDebug(
                    domain=domain,
                    reasons=reasons,
                    final_score=final_score,
                    summary=summary,
                )
            )

        raw_count = parsed.get(_TUNING_REJECTED_CANDIDATE_DEBUG_COUNT_KEY)
        try:
            tuning_rejected_candidate_count = max(0, int(raw_count))
        except (TypeError, ValueError):
            tuning_rejected_candidate_count = len(tuning_rejected_candidates)
        tuning_rejected_candidate_count = max(tuning_rejected_candidate_count, len(tuning_rejected_candidates))
        reason_counts = self._normalize_tuning_rejection_reason_counts(
            parsed.get(_TUNING_REJECTION_REASON_COUNTS_KEY)
            if isinstance(parsed.get(_TUNING_REJECTION_REASON_COUNTS_KEY), dict)
            else None
        )
        return tuning_rejected_candidate_count, tuning_rejected_candidates, reason_counts

    def _extract_candidate_pipeline_summary_from_raw_output(
        self,
        raw_output: str | None,
    ) -> SEOCompetitorProfileCandidatePipelineSummary | None:
        if not raw_output:
            return None
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None

        raw_summary = parsed.get(_CANDIDATE_PIPELINE_SUMMARY_KEY)
        if not isinstance(raw_summary, dict):
            return None

        proposed_candidate_count = max(0, self._coerce_int(raw_summary.get("proposed_candidate_count"), default=0))
        rejected_by_eligibility_count = max(
            0,
            self._coerce_int(raw_summary.get("rejected_by_eligibility_count"), default=0),
        )
        eligible_candidate_count = max(0, self._coerce_int(raw_summary.get("eligible_candidate_count"), default=0))
        rejected_by_tuning_count = max(0, self._coerce_int(raw_summary.get("rejected_by_tuning_count"), default=0))
        survived_tuning_count = max(0, self._coerce_int(raw_summary.get("survived_tuning_count"), default=0))
        removed_by_existing_domain_match_count = max(
            0,
            self._coerce_int(raw_summary.get("removed_by_existing_domain_match_count"), default=0),
        )
        removed_by_deduplication_count = max(
            0,
            self._coerce_int(raw_summary.get("removed_by_deduplication_count"), default=0),
        )
        removed_by_final_limit_count = max(
            0,
            self._coerce_int(raw_summary.get("removed_by_final_limit_count"), default=0),
        )
        final_candidate_count = max(0, self._coerce_int(raw_summary.get("final_candidate_count"), default=0))

        if (
            proposed_candidate_count <= 0
            and rejected_by_eligibility_count <= 0
            and eligible_candidate_count <= 0
            and rejected_by_tuning_count <= 0
            and survived_tuning_count <= 0
            and removed_by_existing_domain_match_count <= 0
            and removed_by_deduplication_count <= 0
            and removed_by_final_limit_count <= 0
            and final_candidate_count <= 0
        ):
            return None

        return SEOCompetitorProfileCandidatePipelineSummary(
            proposed_candidate_count=proposed_candidate_count,
            rejected_by_eligibility_count=rejected_by_eligibility_count,
            eligible_candidate_count=eligible_candidate_count,
            rejected_by_tuning_count=rejected_by_tuning_count,
            survived_tuning_count=survived_tuning_count,
            removed_by_existing_domain_match_count=removed_by_existing_domain_match_count,
            removed_by_deduplication_count=removed_by_deduplication_count,
            removed_by_final_limit_count=removed_by_final_limit_count,
            final_candidate_count=final_candidate_count,
        )

    def _evaluate_pending_preview_accuracy_for_completed_run(
        self,
        *,
        business_id: str,
        site_id: str,
        run: SEOCompetitorProfileGenerationRun,
    ) -> None:
        completed_at = run.completed_at or utc_now()
        pending_events = (
            self.seo_competitor_profile_generation_repository.list_pending_applied_preview_events_for_business_site(
                business_id=business_id,
                site_id=site_id,
                applied_before=completed_at,
            )
        )
        if not pending_events:
            return

        for event in pending_events:
            preview_response = event.preview_response if isinstance(event.preview_response, dict) else {}
            telemetry_window = (
                preview_response.get("telemetry_window")
                if isinstance(preview_response.get("telemetry_window"), dict)
                else {}
            )
            estimated_impact = (
                preview_response.get("estimated_impact")
                if isinstance(preview_response.get("estimated_impact"), dict)
                else {}
            )
            baseline_run_count = max(0, self._coerce_int(telemetry_window.get("total_runs"), default=0))
            baseline_included_total = max(
                0,
                self._coerce_int(telemetry_window.get("total_included_candidate_count"), default=0),
            )
            estimated_window_delta = self._coerce_int(
                estimated_impact.get("estimated_included_candidate_delta"),
                default=0,
            )
            divisor = max(1, baseline_run_count)
            baseline_included_per_run = int(round(baseline_included_total / divisor))
            estimated_included_delta = int(round(estimated_window_delta / divisor))
            actual_included_delta = int(run.included_candidate_count) - baseline_included_per_run
            error_margin = abs(actual_included_delta - estimated_included_delta)
            direction_correct = (
                self._delta_direction(estimated_included_delta)
                == self._delta_direction(actual_included_delta)
            )

            event.evaluated_generation_run_id = run.id
            event.evaluated_at = completed_at
            event.estimated_included_delta = estimated_included_delta
            event.actual_included_delta = actual_included_delta
            event.error_margin = error_margin
            event.direction_correct = direction_correct
            self.seo_competitor_profile_generation_repository.save_tuning_preview_event(event)

    @staticmethod
    def _coerce_int(value: object, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _delta_direction(value: int) -> int:
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

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

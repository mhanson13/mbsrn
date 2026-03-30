from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import inspect
import json
import logging
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.seo_competitor_profile_generation_provider import SEOCompetitorProfileProviderError
from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
    SEOCompetitorProfileGenerationProvider,
)
from app.integrations.google_places import (
    GooglePlacesSeedCandidate,
    GooglePlacesSeedDiscoveryClient,
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
PROVIDER_AUTH_CONFIG_ERROR_SUMMARY = "AI provider credentials are not configured for competitor profile generation."
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
COMPETITOR_TIMEOUT_SECONDS_MIN = 10
COMPETITOR_TIMEOUT_SECONDS_MAX = 90
COMPETITOR_DOMAIN_PROBE_TEST_TLDS = (".example", ".invalid", ".test", ".localhost")
REJECTED_CANDIDATE_DEBUG_MAX_ITEMS = 20
REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS = 240
_REJECTED_CANDIDATE_DEBUG_KEY = "rejected_candidates_debug"
_REJECTED_CANDIDATE_DEBUG_COUNT_KEY = "rejected_candidate_count"
_TUNING_REJECTED_CANDIDATE_DEBUG_KEY = "tuning_rejected_candidates_debug"
_TUNING_REJECTED_CANDIDATE_DEBUG_COUNT_KEY = "tuning_rejected_candidate_count"
_TUNING_REJECTION_REASON_COUNTS_KEY = "tuning_rejection_reason_counts"
_CANDIDATE_PIPELINE_SUMMARY_KEY = "candidate_pipeline_summary_debug"
_SCHEMA_DIAGNOSTICS_SUMMARY_KEY = "schema_diagnostics_summary"
_PROVIDER_ATTEMPTS_DEBUG_KEY = "provider_attempts_debug"
_PROVIDER_ATTEMPT_COUNT_KEY = "provider_attempt_count"
_PROVIDER_DEGRADED_RETRY_USED_KEY = "provider_degraded_retry_used"
_EXECUTION_MODES = {"fast_path", "full", "degraded", "fallback"}
_EXECUTION_MODE_FAST_PATH = "fast_path"
_EXECUTION_MODE_FULL = "full"
_EXECUTION_MODE_DEGRADED = "degraded"
_EXECUTION_MODE_FALLBACK = "fallback"
_PROVIDER_CALL_TYPE_TOOL_ENABLED = "tool_enabled"
_PROVIDER_CALL_TYPE_NON_TOOL = "non_tool"
_PROVIDER_CALL_TYPES = {_PROVIDER_CALL_TYPE_TOOL_ENABLED, _PROVIDER_CALL_TYPE_NON_TOOL}
# Fast path (0), full (1), degraded (2).
_MAX_PROVIDER_TIMEOUT_ATTEMPTS = 3
_TIMEOUT_TYPE_VALUES = {"read", "connect", "overall", "unknown"}
_TIMEOUT_RECOVERY_PATHS = {"retry_success", "fallback_success", "degraded_success", "synthetic_fallback", "none"}
_TIMEOUT_FINAL_OUTCOMES = {"success", "degraded_success", "failure"}
# TODO: formalize provider abstraction with explicit tool/no-tool interfaces.
_SITE_CONTENT_SIGNALS_ATTR = "_seo_site_content_signals"
_MAX_SITE_CONTENT_SIGNAL_PAGES = 40
_MAX_SITE_CONTENT_SIGNALS = 120
_MAX_SITE_CONTENT_SIGNAL_LENGTH = 200
_MAX_PROVIDER_ATTEMPTS_DEBUG_ITEMS = 3
_TIMEOUT_RETRY_BACKOFF_SECONDS = 0.2
TARGET_COMPETITOR_COUNT = 10
_DISCOVERY_CANDIDATE_BUFFER = 2
_MAX_DISCOVERY_CANDIDATE_COUNT = 20
_MIN_DEGRADED_DISCOVERY_CANDIDATE_COUNT = 2
_CANDIDATE_REJECTION_LOG_MAX_ITEMS = 12
_GOOGLE_PLACES_SEED_MAX_CANDIDATES = 8
_GOOGLE_PLACES_SEED_MIN_CANDIDATES = 3
_GOOGLE_PLACES_SEED_QUERY_LIMIT = 5
_GOOGLE_PLACES_QUERY_MAX_LENGTH = 120
_GOOGLE_PLACES_SEED_MAX_NAME_LENGTH = 140
_GOOGLE_PLACES_SEED_MAX_ADDRESS_LENGTH = 220
_GOOGLE_PLACES_SEED_MAX_LOCALITY_LENGTH = 100
_GOOGLE_PLACES_SEED_MAX_TYPE_LENGTH = 64
_GOOGLE_PLACES_SEED_MAX_TYPES = 8
_FORCED_OUTPUT_REASON_NO_VALID_DRAFTS = "no_valid_drafts_after_filtering"
_FORCED_OUTPUT_REASON_TARGET_GAP_FILL = "target_count_gap_fill"
_FORCED_DRAFT_SOURCE = "ai_forced_fallback"
_PLACES_ENRICHED_DRAFT_SOURCE = "ai_places_enriched"
_FORCED_DRAFT_MIN_COUNT = 3
_FORCED_DRAFT_MAX_COUNT = TARGET_COMPETITOR_COUNT
_SYNTHETIC_FALLBACK_RECOVERY_PATH = "synthetic_fallback"
_SYNTHETIC_FALLBACK_REASON_TIMEOUT_EXHAUSTED = "provider_timeout_exhausted"
_SYNTHETIC_FALLBACK_REASON_ZERO_USABLE_CANDIDATES = "zero_usable_candidates_after_validation"
_SYNTHETIC_FALLBACK_DOMAIN_SUFFIX = "mbsrn-fallback.local"
_SYNTHETIC_FALLBACK_MIN_CONFIDENCE = 0.28
_PROMPT_VERSION_MARKER_PATTERN = re.compile(r"(?mi)^\s*PROMPT_VERSION:\s*([^\r\n]+)\s*$")
_UNKNOWN_NAME_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")
_UNKNOWN_PLACEHOLDER_NAME_TOKENS = {
    "business",
    "company",
    "competitor",
    "example",
    "generic",
    "na",
    "none",
    "placeholder",
    "unknown",
}
_UNKNOWN_MIN_CONFIDENCE_FLOOR = 0.35
_UNKNOWN_MIN_DETAIL_CHARS = 40
_OUTCOME_STATUS_NORMAL = "normal"
_OUTCOME_STATUS_RECOVERED = "recovered"
_OUTCOME_STATUS_DEGRADED = "degraded"
_OUTCOME_STATUS_FAILED = "failed"

INELIGIBILITY_REASON_MISSING_DOMAIN = "missing_domain"
INELIGIBILITY_REASON_MALFORMED_URL = "malformed_url"
INELIGIBILITY_REASON_MISSING_BUSINESS_NAME = "missing_business_name"
INELIGIBILITY_REASON_UNSUPPORTED_TYPE = "unsupported_type"
INELIGIBILITY_REASON_INVALID_CONFIDENCE_SCORE = "invalid_confidence_score"
INELIGIBILITY_REASON_LOW_USEFULNESS_UNKNOWN = "low_usefulness_unknown"
_INVALID_INPUT_REASON_KEYS: tuple[str, ...] = (
    INELIGIBILITY_REASON_MISSING_DOMAIN,
    INELIGIBILITY_REASON_MALFORMED_URL,
    INELIGIBILITY_REASON_MISSING_BUSINESS_NAME,
    INELIGIBILITY_REASON_UNSUPPORTED_TYPE,
    INELIGIBILITY_REASON_INVALID_CONFIDENCE_SCORE,
    INELIGIBILITY_REASON_LOW_USEFULNESS_UNKNOWN,
)
_REJECTED_CANDIDATE_REASON_KEYS: tuple[str, ...] = tuple(
    dict.fromkeys([*INELIGIBILITY_REASON_KEYS, *_INVALID_INPUT_REASON_KEYS])
)
_REJECTION_SUMMARY_REASON_KEYS: tuple[str, ...] = (
    "missing_domain",
    "missing_name",
    "excluded_domain",
    "non_competitor_hint",
    "duplicate_domain",
    "invalid_candidate",
    "other",
)

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
    provider_attempt_count: int = 0
    provider_degraded_retry_used: bool = False
    provider_attempts: list["SEOCompetitorProfileProviderAttemptDebug"] = field(default_factory=list)
    outcome_summary: "SEOCompetitorProfileOutcomeSummary | None" = None


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
    relaxed_filtering_applied: bool = False


@dataclass(frozen=True)
class SEOCompetitorProfileProviderAttemptDebug:
    attempt_number: int
    execution_mode: str
    provider_call_type: str | None
    degraded_mode: bool
    reduced_context_mode: bool
    requested_candidate_count: int
    outcome: str
    failure_kind: str | None
    malformed_output_reason: str | None
    request_duration_ms: int | None
    timeout_seconds: int | None
    web_search_enabled: bool | None
    prompt_size_risk: str | None
    prompt_total_chars: int | None
    context_json_chars: int | None
    user_prompt_chars: int | None
    endpoint_path: str | None
    max_attempts: int | None = None
    timeout_type: str | None = None
    recovered_after_timeout: bool | None = None
    recovery_path: str | None = None
    final_outcome: str | None = None
    search_escalation_triggered: bool = False
    escalation_reason: str | None = None
    google_places_seed_count: int = 0


@dataclass(frozen=True)
class SEOCompetitorProfileOutcomeSummary:
    status_level: str
    message: str
    used_synthetic_fallback: bool
    used_timeout_recovery: bool
    had_schema_repair_or_discard: bool
    used_google_places_seeds: bool


@dataclass(frozen=True)
class _ProviderAttemptPromptMetrics:
    reduced_context_mode: bool
    prompt_total_chars: int | None
    context_json_chars: int | None
    user_prompt_chars: int | None


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
    forced_draft_count: int
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
        google_places_seed_client: GooglePlacesSeedDiscoveryClient | None = None,
        google_places_seed_max_candidates: int = _GOOGLE_PLACES_SEED_MAX_CANDIDATES,
        google_places_seed_query_limit: int = _GOOGLE_PLACES_SEED_QUERY_LIMIT,
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
        # Capture deployment-configured prompt fallback once. Provider prompt fields
        # are later mutated with business overrides at runtime, so resolver fallback
        # must never read the mutable provider state.
        configured_prompt_text = getattr(self.provider, "prompt_text_competitor", None)
        if configured_prompt_text is None:
            configured_prompt_text = getattr(self.provider, "prompt_text_recommendation", "")
        self._configured_prompt_text_competitor = self._clean_optional(str(configured_prompt_text or "")) or ""
        self._configured_prompt_legacy_config_used = bool(getattr(self.provider, "legacy_config_used", False))
        self.candidate_domain_probe = candidate_domain_probe
        self.google_places_seed_client = google_places_seed_client
        self.google_places_seed_max_candidates = max(
            _GOOGLE_PLACES_SEED_MIN_CANDIDATES,
            min(_GOOGLE_PLACES_SEED_MAX_CANDIDATES, int(google_places_seed_max_candidates)),
        )
        self.google_places_seed_query_limit = max(
            1, min(_GOOGLE_PLACES_SEED_QUERY_LIMIT, int(google_places_seed_query_limit))
        )
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
            raise SEOCompetitorProfileGenerationValidationError(
                "Failed to queue competitor profile generation run"
            ) from exc

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
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug] = []

        try:
            existing_domains = [
                item.domain
                for item in self.seo_competitor_repository.list_domains_for_business_site(
                    business_id,
                    site_id,
                )
            ]
            self._attach_site_content_signals(site=site, business_id=business_id, site_id=site_id)
            resolved_prompt = self._apply_resolved_competitor_prompt_settings(business)
            google_places_seed_candidates = self._discover_google_places_seed_candidates(
                site=site,
                existing_domains=existing_domains,
                requested_candidate_count=run.requested_candidate_count,
                prompt_text_competitor=resolved_prompt.prompt_text,
                run_id=run.id,
            )
            output = self._generate_competitor_profiles_with_timeout_retry(
                business=business,
                site=site,
                existing_domains=existing_domains,
                run_id=run.id,
                requested_candidate_count=run.requested_candidate_count,
                provider_attempts=provider_attempts,
                prompt_text_competitor=resolved_prompt.prompt_text,
                google_places_seed_candidates=google_places_seed_candidates,
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
                used_google_places_seeds=bool(google_places_seed_candidates),
            )
            if not draft_result.drafts:
                synthetic_fallback_result = self._build_synthetic_fallback_draft_result(
                    site=site,
                    run=run,
                    existing_domains=existing_domains,
                    fallback_reason=_SYNTHETIC_FALLBACK_REASON_ZERO_USABLE_CANDIDATES,
                    baseline_result=draft_result,
                )
                if synthetic_fallback_result is not None:
                    draft_result = synthetic_fallback_result
                    self._apply_synthetic_fallback_attempt_metadata(
                        provider_attempts=provider_attempts,
                        run_id=run.id,
                        site=site,
                        requested_candidate_count=run.requested_candidate_count,
                        fallback_reason=_SYNTHETIC_FALLBACK_REASON_ZERO_USABLE_CANDIDATES,
                    )
            self._log_discovery_pipeline_telemetry(
                run=run,
                draft_result=draft_result,
                parsed_candidate_count=len(output.candidates),
            )
            drafts = draft_result.drafts
            if not drafts and draft_result.raw_candidate_count > 0 and draft_result.forced_draft_count <= 0:
                raise SEOCompetitorProfileGenerationValidationError(
                    "No viable competitor candidates were available for draft output"
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
                provider_attempts=provider_attempts,
                schema_had_repair_or_discard=(True if bool(output.had_schema_repair_or_discard) else None),
                schema_invalid_candidate_count=(
                    max(0, int(output.schema_invalid_candidate_count))
                    if int(output.schema_invalid_candidate_count) > 0
                    else None
                ),
                schema_invalid_field_type_count=(
                    max(0, int(output.schema_invalid_field_type_count))
                    if int(output.schema_invalid_field_type_count) > 0
                    else None
                ),
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
            outcome_summary = self._build_operator_outcome_summary(
                run=run,
                provider_attempts=provider_attempts,
                had_schema_repair_or_discard=bool(output.had_schema_repair_or_discard),
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
                provider_attempt_count=max(0, len(provider_attempts)),
                provider_degraded_retry_used=any(item.degraded_mode for item in provider_attempts),
                provider_attempts=provider_attempts,
                outcome_summary=outcome_summary,
            )
        except SEOCompetitorProfileProviderError as exc:
            self.session.rollback()
            if exc.code == "timeout":
                timeout_fallback_detail = self._complete_run_with_synthetic_fallback(
                    business_id=business_id,
                    site=site,
                    run_id=generation_run_id,
                    provider_name=exc.provider_name,
                    model_name=exc.model_name,
                    prompt_version=exc.prompt_version,
                    raw_output=exc.raw_output,
                    provider_attempts=provider_attempts,
                    fallback_reason=_SYNTHETIC_FALLBACK_REASON_TIMEOUT_EXHAUSTED,
                )
                if timeout_fallback_detail is not None:
                    return timeout_fallback_detail
            failure_raw_output = self._embed_competitor_debug_in_raw_output(
                raw_output=exc.raw_output,
                rejected_candidates=[],
                tuning_rejected_candidates=[],
                tuning_rejection_reason_counts={},
                candidate_pipeline_summary=None,
                provider_attempts=provider_attempts,
            )
            self._mark_run_failed(
                business_id=business_id,
                generation_run_id=generation_run_id,
                reason=exc,
                error_summary=self._provider_error_summary(exc),
                provider_name=exc.provider_name,
                model_name=exc.model_name,
                prompt_version=exc.prompt_version,
                failure_category=self._provider_failure_category(exc),
                raw_output=failure_raw_output,
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
                    provider_attempts=provider_attempts,
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
                    provider_attempts=provider_attempts,
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
                raw_output=self._embed_competitor_debug_in_raw_output(
                    raw_output=raw_output,
                    rejected_candidates=draft_result.rejected_candidates if draft_result is not None else [],
                    tuning_rejected_candidates=(
                        draft_result.tuning_rejected_candidates if draft_result is not None else []
                    ),
                    tuning_rejection_reason_counts=(
                        draft_result.tuning_rejection_reason_counts if draft_result is not None else {}
                    ),
                    candidate_pipeline_summary=(
                        draft_result.candidate_pipeline_summary if draft_result is not None else None
                    ),
                    provider_attempts=provider_attempts,
                ),
                raw_candidate_count=draft_result.raw_candidate_count if draft_result else None,
                included_candidate_count=draft_result.included_candidate_count if draft_result else None,
                excluded_candidate_count=draft_result.excluded_candidate_count if draft_result else None,
                exclusion_counts_by_reason=draft_result.exclusion_counts_by_reason if draft_result else None,
            )
            return None

    def _log_discovery_pipeline_telemetry(
        self,
        *,
        run: SEOCompetitorProfileGenerationRun,
        draft_result: SEOCompetitorProfileDraftBuildResult,
        parsed_candidate_count: int,
    ) -> None:
        pipeline_summary = draft_result.candidate_pipeline_summary
        post_filter_candidate_count = max(
            0,
            int(pipeline_summary.final_candidate_count) + int(pipeline_summary.removed_by_final_limit_count),
        )
        discovery_payload = {
            "event": "competitor_discovery_pipeline_counts",
            "run_id": run.id,
            "business_id": run.business_id,
            "site_id": run.site_id,
            "requested_candidate_count": max(1, int(run.requested_candidate_count or 1)),
            "discovery_candidate_count": max(0, int(draft_result.raw_candidate_count)),
            "post_parse_candidate_count": max(0, int(parsed_candidate_count)),
            "post_filter_candidate_count": post_filter_candidate_count,
            "final_candidate_count": max(0, len(draft_result.drafts)),
        }
        self._emit_structured_service_log(
            payload=discovery_payload,
            fallback_message="competitor_discovery_pipeline_counts",
        )
        reason_histogram, raw_reason_counts = self._build_candidate_rejection_reason_histogram(draft_result)
        total_rejected_candidates = max(
            0,
            len(draft_result.rejected_candidates) + len(draft_result.tuning_rejected_candidates),
        )
        rejection_events_emitted = min(total_rejected_candidates, _CANDIDATE_REJECTION_LOG_MAX_ITEMS)
        rejection_summary_payload = {
            "event": "competitor_candidate_rejection_summary",
            "run_id": run.id,
            "business_id": run.business_id,
            "site_id": run.site_id,
            "requested_candidate_count": max(1, int(run.requested_candidate_count or 1)),
            "raw_count": max(0, int(draft_result.raw_candidate_count)),
            "valid_count": max(0, int(parsed_candidate_count)),
            "rejected_by_eligibility": max(0, int(pipeline_summary.rejected_by_eligibility_count)),
            "removed_by_existing_domain_match": max(0, int(pipeline_summary.removed_by_existing_domain_match_count)),
            "removed_by_deduplication": max(0, int(pipeline_summary.removed_by_deduplication_count)),
            "removed_by_final_limit": max(0, int(pipeline_summary.removed_by_final_limit_count)),
            "final_count": max(0, int(pipeline_summary.final_candidate_count)),
            "reason_histogram": reason_histogram,
            "raw_reason_counts": raw_reason_counts,
            "rejection_event_cap": _CANDIDATE_REJECTION_LOG_MAX_ITEMS,
            "rejection_events_emitted": rejection_events_emitted,
            "rejection_events_truncated": max(0, total_rejected_candidates - rejection_events_emitted),
        }
        self._emit_structured_service_log(
            payload=rejection_summary_payload,
            fallback_message="competitor_candidate_rejection_summary",
        )
        self._log_candidate_rejection_events(
            run=run,
            draft_result=draft_result,
        )

    def _emit_structured_service_log(
        self,
        *,
        payload: dict[str, object],
        fallback_message: str,
    ) -> None:
        try:
            message = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            message = fallback_message
        logger.info(message, extra={"json_fields": payload})

    def _build_candidate_rejection_reason_histogram(
        self,
        draft_result: SEOCompetitorProfileDraftBuildResult,
    ) -> tuple[dict[str, int], dict[str, int]]:
        raw_reason_counts: dict[str, int] = {}

        for reason, count in draft_result.ineligibility_counts_by_reason.items():
            normalized_reason = self._clean_optional(reason)
            if normalized_reason is None:
                continue
            raw_reason_counts[normalized_reason] = raw_reason_counts.get(normalized_reason, 0) + max(
                0, self._coerce_int(count, default=0)
            )

        for reason, count in draft_result.exclusion_counts_by_reason.items():
            normalized_reason = self._clean_optional(reason)
            if normalized_reason is None:
                continue
            raw_reason_counts[normalized_reason] = raw_reason_counts.get(normalized_reason, 0) + max(
                0, self._coerce_int(count, default=0)
            )

        for candidate in draft_result.rejected_candidates:
            for reason in candidate.reasons:
                normalized_reason = self._clean_optional(reason)
                if normalized_reason is None or normalized_reason not in _INVALID_INPUT_REASON_KEYS:
                    continue
                raw_reason_counts[normalized_reason] = raw_reason_counts.get(normalized_reason, 0) + 1

        histogram = {reason: 0 for reason in _REJECTION_SUMMARY_REASON_KEYS}
        for reason, count in raw_reason_counts.items():
            normalized_count = max(0, self._coerce_int(count, default=0))
            if normalized_count <= 0:
                continue
            mapped_reasons = self._map_reason_for_rejection_summary(reason)
            if not mapped_reasons:
                histogram["other"] += normalized_count
                continue
            for mapped_reason in mapped_reasons:
                histogram[mapped_reason] = histogram.get(mapped_reason, 0) + normalized_count

        return histogram, dict(sorted(raw_reason_counts.items()))

    @staticmethod
    def _map_reason_for_rejection_summary(reason: str) -> tuple[str, ...]:
        normalized_reason = str(reason or "").strip().lower()
        if normalized_reason == INELIGIBILITY_REASON_MISSING_DOMAIN:
            return ("missing_domain",)
        if normalized_reason == INELIGIBILITY_REASON_MISSING_BUSINESS_NAME:
            return ("missing_name",)
        if normalized_reason == "excluded_domain_pattern":
            return ("excluded_domain", "non_competitor_hint")
        if normalized_reason == "duplicate":
            return ("duplicate_domain",)
        if normalized_reason == "invalid_candidate":
            return ("invalid_candidate",)
        return tuple()

    def _log_candidate_rejection_events(
        self,
        *,
        run: SEOCompetitorProfileGenerationRun,
        draft_result: SEOCompetitorProfileDraftBuildResult,
    ) -> None:
        emitted = 0

        for candidate in draft_result.rejected_candidates:
            if emitted >= _CANDIDATE_REJECTION_LOG_MAX_ITEMS:
                return
            rejection_reason = candidate.reasons[0] if candidate.reasons else "other"
            payload = {
                "event": "competitor_candidate_rejected",
                "run_id": run.id,
                "business_id": run.business_id,
                "site_id": run.site_id,
                "rejection_stage": "eligibility",
                "rejection_reason": rejection_reason,
                "candidate_name_preview": self._candidate_name_preview(candidate.domain),
                "candidate_domain_preview": self._candidate_domain_preview(candidate.domain),
            }
            self._emit_structured_service_log(
                payload=payload,
                fallback_message="competitor_candidate_rejected",
            )
            emitted += 1

        for candidate in draft_result.tuning_rejected_candidates:
            if emitted >= _CANDIDATE_REJECTION_LOG_MAX_ITEMS:
                return
            rejection_reason = candidate.reasons[0] if candidate.reasons else "other"
            payload = {
                "event": "competitor_candidate_rejected",
                "run_id": run.id,
                "business_id": run.business_id,
                "site_id": run.site_id,
                "rejection_stage": "tuning",
                "rejection_reason": rejection_reason,
                "candidate_name_preview": self._candidate_name_preview(candidate.domain),
                "candidate_domain_preview": self._candidate_domain_preview(candidate.domain),
            }
            self._emit_structured_service_log(
                payload=payload,
                fallback_message="competitor_candidate_rejected",
            )
            emitted += 1

    def _candidate_name_preview(self, domain: str | None) -> str | None:
        normalized_domain = self._clean_optional(domain)
        if normalized_domain is None:
            return None
        root = normalized_domain.split(".", 1)[0].strip()
        if not root:
            return None
        compact = root.replace("-", " ").replace("_", " ").strip()
        if not compact:
            return None
        if len(compact) > 60:
            compact = compact[:57] + "..."
        return compact

    def _candidate_domain_preview(self, domain: str | None) -> str | None:
        normalized_domain = self._clean_optional(domain)
        if normalized_domain is None:
            return None
        if len(normalized_domain) <= 120:
            return normalized_domain
        return normalized_domain[:117] + "..."

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
        provider_attempt_count, provider_degraded_retry_used, provider_attempts = (
            self._extract_provider_attempts_debug_from_raw_output(run.raw_output)
        )
        had_schema_repair_or_discard = self._extract_schema_repair_flag_from_raw_output(run.raw_output)
        if candidate_pipeline_summary is None:
            candidate_pipeline_summary = self._derive_candidate_pipeline_summary_from_run(run)
        outcome_summary = self._build_operator_outcome_summary(
            run=run,
            provider_attempts=provider_attempts,
            had_schema_repair_or_discard=had_schema_repair_or_discard,
        )
        return SEOCompetitorProfileGenerationRunDetail(
            run=run,
            drafts=drafts,
            rejected_candidate_count=rejected_candidate_count,
            rejected_candidates=rejected_candidates,
            tuning_rejected_candidate_count=tuning_rejected_candidate_count,
            tuning_rejected_candidates=tuning_rejected_candidates,
            tuning_rejection_reason_counts=tuning_rejection_reason_counts,
            candidate_pipeline_summary=candidate_pipeline_summary,
            provider_attempt_count=provider_attempt_count,
            provider_degraded_retry_used=provider_degraded_retry_used,
            provider_attempts=provider_attempts,
            outcome_summary=outcome_summary,
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
        resolved_prompt_version = self._clean_optional(prompt_version) or self._default_prompt_version()
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
        preview_prompt_version = (
            self._extract_prompt_version_from_user_prompt(prompt.user_prompt) or prompt.prompt_version
        )
        return SEOCompetitorPromptPreview(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            model_name=self._clean_optional(self._default_model_name()),
            prompt_version=preview_prompt_version,
            prompt_label=SEO_COMPETITOR_PROFILE_PROMPT_LABEL,
            prompt_source=resolved_prompt.prompt_source,
            trusted_site_context=prompt.trusted_site_context,
            prompt_metrics=prompt.prompt_telemetry,
        )

    def _extract_prompt_version_from_user_prompt(self, user_prompt: str) -> str | None:
        if not user_prompt:
            return None
        match = _PROMPT_VERSION_MARKER_PATTERN.search(user_prompt)
        if not match:
            return None
        return self._clean_optional(match.group(1))

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
        exclusion_reason_counts = self.seo_competitor_profile_generation_repository.list_exclusion_reason_counts_for_business_site_created_after(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
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

        latest_execution = (
            self.seo_competitor_profile_generation_repository.get_latest_cleanup_execution_for_business_scope(
                business_id=business_id,
                site_id=site_id,
            )
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
        used_google_places_seeds: bool = False,
    ) -> SEOCompetitorProfileDraftBuildResult:
        # Pipeline stages after provider parsing:
        # 1) normalize/prepare candidate input, 2) eligibility filter,
        # 3) quality tuning and pruning, 4) existing-domain exclusion + deduplication,
        # 5) final requested-count trim.
        prepared_candidates: list[CompetitorCandidateInput] = []
        invalid_input_rejected_candidates: list[SEOCompetitorProfileRejectedCandidateDebug] = []
        for index, candidate in enumerate(raw_candidates):
            prepared_candidate, rejected_candidate = self._prepare_candidate_input_for_pipeline(
                candidate=candidate,
                source_index=index,
            )
            if prepared_candidate is not None:
                prepared_candidates.append(prepared_candidate)
                continue
            if rejected_candidate is not None:
                invalid_input_rejected_candidates.append(rejected_candidate)

        eligibility_result = filter_eligible_competitor_candidates(
            site=site,
            candidates=prepared_candidates,
            domain_probe=self.candidate_domain_probe,
        )
        eligibility_rejected_candidates = self._build_rejected_candidate_debug(
            decisions=eligibility_result.decisions,
        )
        rejected_candidates = self._merge_rejected_candidate_debug(
            primary=invalid_input_rejected_candidates,
            secondary=eligibility_rejected_candidates,
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
        invalid_candidate_input_count = len(invalid_input_rejected_candidates)
        exclusion_counts_by_reason["invalid_candidate"] = (
            int(exclusion_counts_by_reason.get("invalid_candidate", 0))
            + eligibility_result.ineligible_candidate_count
            + invalid_candidate_input_count
        )

        proposed_candidate_count = len(raw_candidates)
        rejected_by_eligibility_count = eligibility_result.ineligible_candidate_count + invalid_candidate_input_count
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
        target_candidate_count = max(
            1,
            min(
                TARGET_COMPETITOR_COUNT,
                int(run.requested_candidate_count or TARGET_COMPETITOR_COUNT),
            ),
        )
        enable_tiered_fill = target_candidate_count >= TARGET_COMPETITOR_COUNT
        final_candidates = candidate_processing.included_candidates[:target_candidate_count]
        forced_fallback_candidates: list[CompetitorCandidateInput] = []
        if (
            (enable_tiered_fill and len(final_candidates) < target_candidate_count)
            or (not enable_tiered_fill and not final_candidates)
        ) and proposed_candidate_count > 0:
            forced_candidate_pool = self._select_forced_fallback_candidates(
                prepared_candidates=prepared_candidates,
                eligible_candidates=eligibility_result.eligible_candidates,
                requested_candidate_count=target_candidate_count,
            )
            if forced_candidate_pool:
                seen_forced_keys = {
                    (
                        (candidate.suggested_name or "").strip().lower(),
                        candidate.canonical_domain.strip().lower(),
                    )
                    for candidate in final_candidates
                }
                needed_forced = max(0, target_candidate_count - len(final_candidates))
                for candidate in forced_candidate_pool:
                    if needed_forced <= 0:
                        break
                    forced_key = (
                        (candidate.suggested_name or "").strip().lower(),
                        (candidate.suggested_domain or "").strip().lower(),
                    )
                    if not forced_key[0]:
                        continue
                    if forced_key in seen_forced_keys:
                        continue
                    seen_forced_keys.add(forced_key)
                    forced_fallback_candidates.append(candidate)
                    needed_forced -= 1
            if forced_fallback_candidates:
                forced_reason = (
                    _FORCED_OUTPUT_REASON_NO_VALID_DRAFTS
                    if not final_candidates
                    else _FORCED_OUTPUT_REASON_TARGET_GAP_FILL
                )
                self._emit_structured_service_log(
                    payload={
                        "event": "competitor_forced_output",
                        "run_id": run.id,
                        "business_id": run.business_id,
                        "site_id": run.site_id,
                        "raw_candidates": proposed_candidate_count,
                        "forced_drafts": len(forced_fallback_candidates),
                        "target_candidate_count": target_candidate_count,
                        "forced_reason": forced_reason,
                    },
                    fallback_message="competitor_forced_output",
                )
        removed_by_final_limit_count = max(0, len(candidate_processing.included_candidates) - target_candidate_count)
        unsupported_type_allowed_count = sum(
            1 for candidate in final_candidates if bool(candidate.classification_mismatch)
        )
        no_domain_allowed_count = sum(1 for candidate in final_candidates if bool(candidate.weak_or_missing_domain))
        if (
            eligibility_result.relaxed_filtering_applied
            or unsupported_type_allowed_count > 0
            or no_domain_allowed_count > 0
        ):
            self._emit_structured_service_log(
                payload={
                    "event": "competitor_filtering_relaxation",
                    "run_id": run.id,
                    "business_id": run.business_id,
                    "site_id": run.site_id,
                    "relaxed_filtering_applied": bool(eligibility_result.relaxed_filtering_applied),
                    "unsupported_type_allowed": unsupported_type_allowed_count,
                    "no_domain_allowed": no_domain_allowed_count,
                },
                fallback_message="competitor_filtering_relaxation",
            )

        drafts: list[SEOCompetitorProfileDraft] = []
        ai_draft_source = _PLACES_ENRICHED_DRAFT_SOURCE if used_google_places_seeds else "ai_generated"
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
                source=ai_draft_source,
                review_status="pending",
            )
            drafts.append(draft)
        for candidate in forced_fallback_candidates:
            forced_domain = self._forced_fallback_domain(
                domain=candidate.suggested_domain,
                source_index=candidate.source_index,
            )
            forced_relevance = max(0, min(100, int(round(candidate.confidence_score * 100))))
            forced_draft_source = (
                "ai_tier2_fallback" if enable_tiered_fill and len(final_candidates) > 0 else _FORCED_DRAFT_SOURCE
            )
            draft = SEOCompetitorProfileDraft(
                id=str(uuid4()),
                business_id=run.business_id,
                site_id=run.site_id,
                generation_run_id=run.id,
                suggested_name=candidate.suggested_name,
                suggested_domain=forced_domain,
                competitor_type=candidate.competitor_type,
                summary=candidate.summary,
                why_competitor=candidate.why_competitor,
                evidence=candidate.evidence,
                confidence_score=candidate.confidence_score,
                relevance_score=forced_relevance,
                source=forced_draft_source,
                review_status="pending",
            )
            drafts.append(draft)
        synthetic_gap_fill_count = 0
        if enable_tiered_fill and len(drafts) < target_candidate_count:
            synthetic_candidates = self._build_synthetic_fallback_candidates(
                site=site,
                requested_candidate_count=target_candidate_count,
                existing_domains=existing_domains,
            )
            if synthetic_candidates:
                seen_synthetic_domains = {
                    (self._normalize_optional_domain_value(draft.suggested_domain) or "").lower() for draft in drafts
                }
                seen_synthetic_names = {(draft.suggested_name or "").strip().lower() for draft in drafts}
                for synthetic_candidate in synthetic_candidates:
                    if len(drafts) >= target_candidate_count:
                        break
                    suggested_name = self._clean_optional(
                        str(synthetic_candidate.get("suggested_name"))
                        if synthetic_candidate.get("suggested_name") is not None
                        else None
                    )
                    if not suggested_name:
                        continue
                    suggested_domain = self._normalize_optional_domain_value(
                        synthetic_candidate.get("suggested_domain")
                    ) or self._build_synthetic_fallback_domain(seed_name=suggested_name, location_label=site.id)
                    synthetic_domain_key = suggested_domain.lower()
                    synthetic_name_key = suggested_name.strip().lower()
                    if synthetic_domain_key in seen_synthetic_domains or synthetic_name_key in seen_synthetic_names:
                        continue
                    seen_synthetic_domains.add(synthetic_domain_key)
                    seen_synthetic_names.add(synthetic_name_key)
                    confidence_score = max(
                        0.0,
                        min(1.0, self._coerce_float(synthetic_candidate.get("confidence_score"), default=0.3)),
                    )
                    relevance_score = max(0, min(100, int(round(confidence_score * 100))))
                    drafts.append(
                        SEOCompetitorProfileDraft(
                            id=str(uuid4()),
                            business_id=run.business_id,
                            site_id=run.site_id,
                            generation_run_id=run.id,
                            suggested_name=suggested_name,
                            suggested_domain=suggested_domain,
                            competitor_type=self._normalize_competitor_type(synthetic_candidate.get("competitor_type")),
                            summary=self._clean_optional(
                                str(synthetic_candidate.get("summary"))
                                if synthetic_candidate.get("summary") is not None
                                else None
                            ),
                            why_competitor=self._clean_optional(
                                str(synthetic_candidate.get("why_competitor"))
                                if synthetic_candidate.get("why_competitor") is not None
                                else None
                            ),
                            evidence=self._clean_optional(
                                str(synthetic_candidate.get("evidence"))
                                if synthetic_candidate.get("evidence") is not None
                                else None
                            ),
                            confidence_score=confidence_score,
                            relevance_score=relevance_score,
                            source="synthetic_fallback",
                            review_status="pending",
                        )
                    )
                    synthetic_gap_fill_count += 1
        if synthetic_gap_fill_count > 0:
            self._emit_structured_service_log(
                payload={
                    "event": "competitor_tiered_gap_fill",
                    "run_id": run.id,
                    "business_id": run.business_id,
                    "site_id": run.site_id,
                    "target_candidate_count": target_candidate_count,
                    "tier1_count": len(final_candidates),
                    "tier2_count": len(forced_fallback_candidates),
                    "tier3_count": synthetic_gap_fill_count,
                    "final_count": len(drafts),
                },
                fallback_message="competitor_tiered_gap_fill",
            )
        included_count = len(drafts)
        excluded_count = (
            max(0, proposed_candidate_count - included_count)
            if forced_fallback_candidates
            else (
                candidate_processing.excluded_candidate_count
                + rejected_by_eligibility_count
                + removed_by_final_limit_count
            )
        )
        return SEOCompetitorProfileDraftBuildResult(
            drafts=drafts,
            forced_draft_count=len(forced_fallback_candidates),
            raw_candidate_count=proposed_candidate_count,
            included_candidate_count=included_count,
            deduped_candidate_count=candidate_processing.deduped_candidate_count,
            ineligible_candidate_count=rejected_by_eligibility_count,
            excluded_candidate_count=excluded_count,
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
                final_candidate_count=included_count,
                relaxed_filtering_applied=bool(eligibility_result.relaxed_filtering_applied),
            ),
        )

    def _select_forced_fallback_candidates(
        self,
        *,
        prepared_candidates: list[CompetitorCandidateInput],
        eligible_candidates: list[CompetitorCandidateInput],
        requested_candidate_count: int,
    ) -> list[CompetitorCandidateInput]:
        forced_limit = min(
            _FORCED_DRAFT_MAX_COUNT,
            max(_FORCED_DRAFT_MIN_COUNT, max(1, int(requested_candidate_count))),
        )
        if forced_limit <= 0:
            return []

        eligible_ids = {id(candidate) for candidate in eligible_candidates}
        overflow_candidates = [candidate for candidate in prepared_candidates if id(candidate) not in eligible_ids]
        candidate_pool = [*eligible_candidates, *overflow_candidates]
        if not candidate_pool:
            return []

        sorted_pool = sorted(
            candidate_pool,
            key=lambda candidate: (-float(candidate.confidence_score), int(candidate.source_index)),
        )
        forced_candidates: list[CompetitorCandidateInput] = []
        seen: set[tuple[str, str]] = set()
        for candidate in sorted_pool:
            normalized_name = (candidate.suggested_name or "").strip().lower()
            if not normalized_name:
                continue
            normalized_domain = (candidate.suggested_domain or "").strip().lower()
            dedupe_key = (
                normalized_name,
                normalized_domain or f"unknown-domain-{max(0, int(candidate.source_index))}",
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            forced_candidates.append(candidate)
            if len(forced_candidates) >= forced_limit:
                break
        return forced_candidates

    def _forced_fallback_domain(self, *, domain: str, source_index: int) -> str:
        cleaned = self._clean_optional(domain)
        if cleaned:
            return cleaned.lower()
        return f"unknown-domain-{max(0, int(source_index)) + 1}"

    def _build_synthetic_fallback_draft_result(
        self,
        *,
        site: SEOSite,
        run: SEOCompetitorProfileGenerationRun,
        existing_domains: list[str],
        fallback_reason: str,
        baseline_result: SEOCompetitorProfileDraftBuildResult | None = None,
    ) -> SEOCompetitorProfileDraftBuildResult | None:
        fallback_candidates = self._build_synthetic_fallback_candidates(
            site=site,
            requested_candidate_count=run.requested_candidate_count,
            existing_domains=existing_domains,
        )
        if not fallback_candidates:
            return None

        drafts: list[SEOCompetitorProfileDraft] = []
        for index, candidate in enumerate(fallback_candidates):
            confidence_score = max(0.0, min(1.0, float(candidate["confidence_score"])))
            relevance_score = max(0, min(100, int(round(confidence_score * 100))))
            drafts.append(
                SEOCompetitorProfileDraft(
                    id=str(uuid4()),
                    business_id=run.business_id,
                    site_id=run.site_id,
                    generation_run_id=run.id,
                    suggested_name=str(candidate["suggested_name"]),
                    suggested_domain=str(candidate["suggested_domain"]),
                    competitor_type=str(candidate["competitor_type"]),
                    summary=self._clean_optional(str(candidate["summary"])),
                    why_competitor=self._clean_optional(str(candidate["why_competitor"])),
                    evidence=self._clean_optional(str(candidate["evidence"])),
                    confidence_score=confidence_score,
                    relevance_score=relevance_score,
                    source=_FORCED_DRAFT_SOURCE,
                    review_status="pending",
                )
            )
            if index >= _FORCED_DRAFT_MAX_COUNT:
                break

        draft_count = len(drafts)
        if draft_count <= 0:
            return None
        self._emit_structured_service_log(
            payload={
                "event": "competitor_synthetic_fallback",
                "run_id": run.id,
                "business_id": run.business_id,
                "site_id": run.site_id,
                "fallback_reason": fallback_reason,
                "fallback_candidate_count": draft_count,
                "provider_raw_candidate_count": (
                    int(baseline_result.raw_candidate_count) if baseline_result is not None else 0
                ),
            },
            fallback_message="competitor_synthetic_fallback",
        )
        if baseline_result is not None:
            summary = baseline_result.candidate_pipeline_summary
            return SEOCompetitorProfileDraftBuildResult(
                drafts=drafts,
                forced_draft_count=draft_count,
                raw_candidate_count=baseline_result.raw_candidate_count,
                included_candidate_count=draft_count,
                deduped_candidate_count=baseline_result.deduped_candidate_count,
                ineligible_candidate_count=baseline_result.ineligible_candidate_count,
                excluded_candidate_count=baseline_result.excluded_candidate_count,
                exclusion_counts_by_reason=baseline_result.exclusion_counts_by_reason,
                ineligibility_counts_by_reason=baseline_result.ineligibility_counts_by_reason,
                rejected_candidates=baseline_result.rejected_candidates,
                tuning_rejected_candidates=baseline_result.tuning_rejected_candidates,
                tuning_rejection_reason_counts=baseline_result.tuning_rejection_reason_counts,
                candidate_pipeline_summary=SEOCompetitorProfileCandidatePipelineSummary(
                    proposed_candidate_count=summary.proposed_candidate_count,
                    rejected_by_eligibility_count=summary.rejected_by_eligibility_count,
                    eligible_candidate_count=summary.eligible_candidate_count,
                    rejected_by_tuning_count=summary.rejected_by_tuning_count,
                    survived_tuning_count=summary.survived_tuning_count,
                    removed_by_existing_domain_match_count=summary.removed_by_existing_domain_match_count,
                    removed_by_deduplication_count=summary.removed_by_deduplication_count,
                    removed_by_final_limit_count=summary.removed_by_final_limit_count,
                    final_candidate_count=draft_count,
                    relaxed_filtering_applied=summary.relaxed_filtering_applied,
                ),
            )
        return SEOCompetitorProfileDraftBuildResult(
            drafts=drafts,
            forced_draft_count=draft_count,
            raw_candidate_count=0,
            included_candidate_count=draft_count,
            deduped_candidate_count=0,
            ineligible_candidate_count=0,
            excluded_candidate_count=0,
            exclusion_counts_by_reason=self._normalize_exclusion_counts_by_reason(default_exclusion_reason_counts()),
            ineligibility_counts_by_reason={reason: 0 for reason in INELIGIBILITY_REASON_KEYS},
            rejected_candidates=[],
            tuning_rejected_candidates=[],
            tuning_rejection_reason_counts=self._normalize_tuning_rejection_reason_counts({}),
            candidate_pipeline_summary=SEOCompetitorProfileCandidatePipelineSummary(
                proposed_candidate_count=0,
                rejected_by_eligibility_count=0,
                eligible_candidate_count=0,
                rejected_by_tuning_count=0,
                survived_tuning_count=0,
                removed_by_existing_domain_match_count=0,
                removed_by_deduplication_count=0,
                removed_by_final_limit_count=0,
                final_candidate_count=draft_count,
                relaxed_filtering_applied=False,
            ),
        )

    def _build_synthetic_fallback_candidates(
        self,
        *,
        site: SEOSite,
        requested_candidate_count: int,
        existing_domains: list[str],
    ) -> list[dict[str, object]]:
        target_count = min(
            _FORCED_DRAFT_MAX_COUNT,
            max(_FORCED_DRAFT_MIN_COUNT, max(1, int(requested_candidate_count or 1))),
        )
        if target_count <= 0:
            return []

        context: dict[str, object] = {}
        try:
            context = build_seo_competitor_profile_prompt(
                site=site,
                existing_domains=existing_domains,
                candidate_count=target_count,
                reduced_context_mode=True,
            ).trusted_site_context
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to build trusted site context for synthetic competitor fallback site_id=%s reason=%s",
                site.id,
                str(exc),
            )

        location_label = (
            self._clean_optional(
                str(context.get("site_location_context")) if context.get("site_location_context") is not None else None
            )
            or self._clean_optional(site.primary_location)
            or "local area"
        )
        if "unspecified" in location_label.lower():
            location_label = self._clean_optional(site.primary_location) or "local area"

        business_name = (
            self._clean_optional(
                str(context.get("site_business_name")) if context.get("site_business_name") is not None else None
            )
            or self._clean_optional(site.display_name)
            or "Local Business"
        )
        industry_context = (
            self._clean_optional(
                str(context.get("site_industry_context")) if context.get("site_industry_context") is not None else None
            )
            or self._clean_optional(site.industry)
            or "local services"
        )
        service_terms_raw = context.get("service_focus_terms")
        service_terms: list[str] = []
        if isinstance(service_terms_raw, list):
            for item in service_terms_raw:
                cleaned = self._clean_optional(str(item) if item is not None else None)
                if cleaned and cleaned.lower() not in {term.lower() for term in service_terms}:
                    service_terms.append(cleaned)
        if not service_terms:
            service_terms.append(industry_context)
        service_terms = service_terms[:3]

        reserved_domains = {
            normalized
            for raw in [*existing_domains, site.normalized_domain]
            for normalized in [self._clean_optional(raw)]
            if normalized
        }
        generated: list[dict[str, object]] = []
        templates = (
            "{service} in {location}",
            "{service} near {location}",
            "{service} company {location}",
            "{location} {service} services",
            "{service} specialists {location}",
        )
        for service in service_terms:
            title_service = service.title()
            for template in templates:
                if len(generated) >= target_count:
                    break
                suggested_name = template.format(service=title_service, location=location_label).strip()
                suggested_domain = self._build_synthetic_fallback_domain(
                    seed_name=suggested_name,
                    reserved_domains=reserved_domains,
                    sequence=len(generated) + 1,
                )
                generated.append(
                    self._build_synthetic_fallback_candidate_payload(
                        suggested_name=suggested_name,
                        suggested_domain=suggested_domain,
                        business_name=business_name,
                        location_label=location_label,
                        service_term=service,
                    )
                )
                reserved_domains.add(suggested_domain.lower())
            if len(generated) >= target_count:
                break

        sequence = len(generated) + 1
        while len(generated) < target_count:
            fallback_service = service_terms[(sequence - 1) % len(service_terms)]
            fallback_name = f"{fallback_service.title()} provider {location_label} {sequence}"
            fallback_domain = self._build_synthetic_fallback_domain(
                seed_name=fallback_name,
                reserved_domains=reserved_domains,
                sequence=sequence,
            )
            generated.append(
                self._build_synthetic_fallback_candidate_payload(
                    suggested_name=fallback_name,
                    suggested_domain=fallback_domain,
                    business_name=business_name,
                    location_label=location_label,
                    service_term=fallback_service,
                )
            )
            reserved_domains.add(fallback_domain.lower())
            sequence += 1
        return generated[:target_count]

    def _build_synthetic_fallback_candidate_payload(
        self,
        *,
        suggested_name: str,
        suggested_domain: str,
        business_name: str,
        location_label: str,
        service_term: str,
    ) -> dict[str, object]:
        clean_name = self._clean_required_value(suggested_name, field_name="synthetic_suggested_name")
        clean_domain = self._normalize_domain_value(suggested_domain)
        normalized_service = self._clean_optional(service_term) or "local services"
        summary = (
            "Deterministic fallback candidate generated from local site context "
            "after provider attempts returned no usable competitors."
        )
        why_competitor = f"Fallback pattern '{normalized_service}' in '{location_label}' was used for operator review."
        evidence = f"Synthetic fallback result for {business_name}; manually verify business fit and live website."
        return {
            "suggested_name": clean_name,
            "suggested_domain": clean_domain,
            "competitor_type": "local",
            "summary": summary,
            "why_competitor": why_competitor,
            "evidence": evidence,
            "confidence_score": _SYNTHETIC_FALLBACK_MIN_CONFIDENCE,
        }

    def _build_synthetic_fallback_domain(
        self,
        *,
        seed_name: str,
        reserved_domains: set[str],
        sequence: int,
    ) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", seed_name.lower()).strip("-")
        if not slug:
            slug = f"local-competitor-{max(1, int(sequence))}"
        slug = slug[:48]
        if not slug:
            slug = f"local-competitor-{max(1, int(sequence))}"

        candidate = f"{slug}.{_SYNTHETIC_FALLBACK_DOMAIN_SUFFIX}"
        if candidate.lower() not in reserved_domains:
            return candidate
        counter = 2
        while True:
            suffix = f"-{counter}"
            truncated = slug[: max(1, 48 - len(suffix))]
            candidate = f"{truncated}{suffix}.{_SYNTHETIC_FALLBACK_DOMAIN_SUFFIX}"
            if candidate.lower() not in reserved_domains:
                return candidate
            counter += 1

    def _apply_synthetic_fallback_attempt_metadata(
        self,
        *,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug],
        run_id: str,
        site: SEOSite,
        requested_candidate_count: int,
        fallback_reason: str,
    ) -> None:
        timeout_observed = any(item.failure_kind == "timeout" for item in provider_attempts)
        max_attempts = max(_MAX_PROVIDER_TIMEOUT_ATTEMPTS, len(provider_attempts) + 1)

        if timeout_observed:
            self._finalize_provider_attempt_timeout_outcome(
                provider_attempts=provider_attempts,
                final_outcome="degraded_success",
                recovery_path=_SYNTHETIC_FALLBACK_RECOVERY_PATH,
                max_attempts=max_attempts,
            )
            self._emit_timeout_outcome_summary_log(
                run_id=run_id,
                site=site,
                provider_attempts=provider_attempts,
                final_outcome="degraded_success",
                recovery_path=_SYNTHETIC_FALLBACK_RECOVERY_PATH,
                max_attempts=max_attempts,
            )
        else:
            for index, attempt in enumerate(provider_attempts):
                provider_attempts[index] = replace(
                    attempt,
                    max_attempts=attempt.max_attempts or max(1, len(provider_attempts)),
                    recovered_after_timeout=False,
                    recovery_path=_SYNTHETIC_FALLBACK_RECOVERY_PATH,
                    final_outcome="degraded_success",
                )

        provider_attempts.append(
            SEOCompetitorProfileProviderAttemptDebug(
                attempt_number=max(0, len(provider_attempts)),
                execution_mode=_EXECUTION_MODE_FALLBACK,
                provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                degraded_mode=True,
                reduced_context_mode=True,
                requested_candidate_count=max(1, int(requested_candidate_count or 1)),
                outcome="success",
                failure_kind=None,
                malformed_output_reason=None,
                request_duration_ms=0,
                timeout_seconds=None,
                web_search_enabled=False,
                prompt_size_risk="normal",
                prompt_total_chars=None,
                context_json_chars=None,
                user_prompt_chars=None,
                endpoint_path=None,
                max_attempts=max_attempts,
                timeout_type=None,
                recovered_after_timeout=bool(timeout_observed),
                recovery_path=_SYNTHETIC_FALLBACK_RECOVERY_PATH,
                final_outcome="degraded_success",
                search_escalation_triggered=False,
                escalation_reason=fallback_reason,
            )
        )
        self._emit_structured_service_log(
            payload={
                "event": "competitor_synthetic_fallback_applied",
                "run_id": run_id,
                "business_id": site.business_id,
                "site_id": site.id,
                "timeout_observed": timeout_observed,
                "fallback_reason": fallback_reason,
                "provider_attempt_count": len(provider_attempts),
                "recovery_path": _SYNTHETIC_FALLBACK_RECOVERY_PATH,
                "final_outcome": "degraded_success",
            },
            fallback_message="competitor_synthetic_fallback_applied",
        )

    def _complete_run_with_synthetic_fallback(
        self,
        *,
        business_id: str,
        site: SEOSite,
        run_id: str,
        provider_name: str,
        model_name: str,
        prompt_version: str,
        raw_output: str | None,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug],
        fallback_reason: str,
    ) -> SEOCompetitorProfileGenerationRunDetail | None:
        run = self._get_run_for_site(
            business_id=business_id,
            site_id=site.id,
            generation_run_id=run_id,
        )
        existing_domains = [
            item.domain
            for item in self.seo_competitor_repository.list_domains_for_business_site(
                business_id,
                site.id,
            )
        ]
        draft_result = self._build_synthetic_fallback_draft_result(
            site=site,
            run=run,
            existing_domains=existing_domains,
            fallback_reason=fallback_reason,
        )
        if draft_result is None:
            return None

        self._apply_synthetic_fallback_attempt_metadata(
            provider_attempts=provider_attempts,
            run_id=run.id,
            site=site,
            requested_candidate_count=run.requested_candidate_count,
            fallback_reason=fallback_reason,
        )
        self._log_discovery_pipeline_telemetry(
            run=run,
            draft_result=draft_result,
            parsed_candidate_count=0,
        )
        run.status = "completed"
        run.generated_draft_count = len(draft_result.drafts)
        run.raw_candidate_count = draft_result.raw_candidate_count
        run.included_candidate_count = draft_result.included_candidate_count
        run.excluded_candidate_count = draft_result.excluded_candidate_count
        run.exclusion_counts_by_reason = self._normalize_exclusion_counts_by_reason(
            draft_result.exclusion_counts_by_reason
        )
        run.provider_name = self._clean_required_value(provider_name, field_name="provider_name")
        run.model_name = self._clean_required_value(model_name, field_name="model_name")
        run.prompt_version = self._clean_required_value(prompt_version, field_name="prompt_version")
        run.failure_category = None
        run.error_summary = None
        run.completed_at = utc_now()
        run.raw_output = self._sanitize_raw_output(
            self._embed_competitor_debug_in_raw_output(
                raw_output=raw_output,
                rejected_candidates=draft_result.rejected_candidates,
                tuning_rejected_candidates=draft_result.tuning_rejected_candidates,
                tuning_rejection_reason_counts=draft_result.tuning_rejection_reason_counts,
                candidate_pipeline_summary=draft_result.candidate_pipeline_summary,
                provider_attempts=provider_attempts,
            )
        )
        self.seo_competitor_profile_generation_repository.save_run(run)
        for draft in draft_result.drafts:
            self.seo_competitor_profile_generation_repository.create_draft(draft)
        self.session.commit()
        self.session.refresh(run)
        logger.warning(
            "SEO competitor profile generation run completed via synthetic fallback business_id=%s site_id=%s run_id=%s drafts=%s reason=%s",
            business_id,
            site.id,
            run.id,
            len(draft_result.drafts),
            fallback_reason,
        )
        outcome_summary = self._build_operator_outcome_summary(
            run=run,
            provider_attempts=provider_attempts,
            had_schema_repair_or_discard=False,
        )
        return SEOCompetitorProfileGenerationRunDetail(
            run=run,
            drafts=draft_result.drafts,
            rejected_candidate_count=max(0, len(draft_result.rejected_candidates)),
            rejected_candidates=draft_result.rejected_candidates,
            tuning_rejected_candidate_count=max(0, len(draft_result.tuning_rejected_candidates)),
            tuning_rejected_candidates=draft_result.tuning_rejected_candidates,
            tuning_rejection_reason_counts=draft_result.tuning_rejection_reason_counts,
            candidate_pipeline_summary=draft_result.candidate_pipeline_summary,
            provider_attempt_count=max(0, len(provider_attempts)),
            provider_degraded_retry_used=any(item.degraded_mode for item in provider_attempts),
            provider_attempts=provider_attempts,
            outcome_summary=outcome_summary,
        )

    def _prepare_candidate_input_for_pipeline(
        self,
        *,
        candidate: SEOCompetitorProfileDraftCandidateOutput,
        source_index: int,
    ) -> tuple[CompetitorCandidateInput | None, SEOCompetitorProfileRejectedCandidateDebug | None]:
        reasons: list[str] = []
        suggested_name = self._clean_optional(candidate.suggested_name)
        raw_domain = self._clean_optional(candidate.suggested_domain)
        suggested_domain = ""
        weak_or_missing_domain = False

        if suggested_name is None:
            reasons.append(INELIGIBILITY_REASON_MISSING_BUSINESS_NAME)

        if raw_domain is None:
            weak_or_missing_domain = True
        else:
            try:
                suggested_domain = self._normalize_domain_value(raw_domain)
            except SEOCompetitorProfileGenerationValidationError:
                weak_or_missing_domain = True

        raw_competitor_type = self._clean_optional(candidate.competitor_type)
        competitor_type = self._normalize_competitor_type(raw_competitor_type or "")
        classification_mismatch = False
        if (
            raw_competitor_type is not None
            and competitor_type == "unknown"
            and raw_competitor_type.lower() not in _ALLOWED_COMPETITOR_TYPES
        ):
            classification_mismatch = True

        summary = self._clean_optional(candidate.summary)
        why_competitor = self._clean_optional(candidate.why_competitor)
        evidence = self._clean_optional(candidate.evidence)

        confidence_score: float | None = None
        try:
            confidence_score = self._normalize_confidence_score(candidate.confidence_score)
        except SEOCompetitorProfileGenerationValidationError:
            reasons.append(INELIGIBILITY_REASON_INVALID_CONFIDENCE_SCORE)
        if confidence_score is not None and weak_or_missing_domain:
            confidence_score = min(confidence_score, 0.6)

        if (
            not reasons
            and competitor_type == "unknown"
            and suggested_name is not None
            and confidence_score is not None
            and not self._meets_unknown_usefulness_threshold(
                suggested_name=suggested_name,
                summary=summary,
                why_competitor=why_competitor,
                evidence=evidence,
                confidence_score=confidence_score,
            )
        ):
            reasons.append(INELIGIBILITY_REASON_LOW_USEFULNESS_UNKNOWN)

        if reasons:
            debug_domain = suggested_domain or raw_domain or "unknown-domain"
            return (
                None,
                SEOCompetitorProfileRejectedCandidateDebug(
                    domain=debug_domain,
                    reasons=self._normalize_rejected_candidate_reasons(reasons),
                    summary=self._build_rejected_candidate_summary_from_values(
                        summary=summary,
                        why_competitor=why_competitor,
                        evidence=evidence,
                    ),
                ),
            )

        if suggested_name is None or confidence_score is None:
            return None, None

        return (
            CompetitorCandidateInput(
                suggested_name=suggested_name,
                suggested_domain=suggested_domain,
                competitor_type=competitor_type,
                summary=summary,
                why_competitor=why_competitor,
                evidence=evidence,
                confidence_score=confidence_score,
                source_index=source_index,
                classification_mismatch=classification_mismatch,
                weak_or_missing_domain=weak_or_missing_domain,
            ),
            None,
        )

    def _merge_rejected_candidate_debug(
        self,
        *,
        primary: list[SEOCompetitorProfileRejectedCandidateDebug],
        secondary: list[SEOCompetitorProfileRejectedCandidateDebug],
    ) -> list[SEOCompetitorProfileRejectedCandidateDebug]:
        merged: list[SEOCompetitorProfileRejectedCandidateDebug] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for item in [*primary, *secondary]:
            if not item.reasons:
                continue
            normalized_domain = self._clean_optional(item.domain)
            if normalized_domain is None:
                continue
            key = (normalized_domain.lower(), tuple(item.reasons))
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                SEOCompetitorProfileRejectedCandidateDebug(
                    domain=normalized_domain,
                    reasons=tuple(item.reasons),
                    summary=item.summary,
                )
            )
            if len(merged) >= REJECTED_CANDIDATE_DEBUG_MAX_ITEMS:
                break
        return merged

    def _meets_unknown_usefulness_threshold(
        self,
        *,
        suggested_name: str,
        summary: str | None,
        why_competitor: str | None,
        evidence: str | None,
        confidence_score: float,
    ) -> bool:
        tokens = self._tokenize_name_for_usefulness(suggested_name)
        if not tokens:
            return False
        if all(token in _UNKNOWN_PLACEHOLDER_NAME_TOKENS for token in tokens):
            return False
        if confidence_score < _UNKNOWN_MIN_CONFIDENCE_FLOOR:
            return False

        detail_values = [value for value in [summary, why_competitor, evidence] if value]
        detail_chars = sum(len(value) for value in detail_values)
        if detail_chars >= _UNKNOWN_MIN_DETAIL_CHARS:
            return True
        if len(detail_values) >= 2 and any(len(value) >= 20 for value in detail_values):
            return True
        return False

    @staticmethod
    def _tokenize_name_for_usefulness(value: str) -> list[str]:
        normalized = _UNKNOWN_NAME_TOKEN_PATTERN.sub(" ", value.lower())
        return [token for token in normalized.split(" ") if token]

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

    def _normalize_domain_value(self, raw_domain: object | None) -> str:
        candidate = self._clean_optional(raw_domain)
        if candidate is None:
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain is required")
        candidate = candidate.lower()
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
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain must include a top-level domain")
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-." for ch in cleaned):
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain contains invalid characters")
        return cleaned

    def _normalize_optional_domain_value(self, raw_domain: object | None) -> str | None:
        normalized = self._clean_optional(raw_domain)
        if normalized is None:
            return None
        try:
            return self._normalize_domain_value(normalized)
        except SEOCompetitorProfileGenerationValidationError:
            return None

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
    def _clean_optional(value: object | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        if isinstance(value, (list, tuple, dict, set)):
            return None
        if not value:
            return None
        cleaned = str(value).strip()
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
        # Resolver fallback must use the immutable configured baseline captured in
        # __init__, not mutable provider prompt fields that are overwritten per run.
        return self._configured_prompt_text_competitor

    def _provider_prompt_legacy_config_used(self) -> bool:
        # Keep legacy fallback attribution aligned to the immutable configured
        # baseline captured at service construction time.
        return self._configured_prompt_legacy_config_used

    def _resolve_competitor_prompt_settings(self, business: Business) -> ResolvedAIPromptText:
        return resolve_ai_prompt_text(
            admin_prompt_text=getattr(business, "ai_prompt_text_competitor", None),
            env_prompt_text=self._provider_prompt_text_competitor(),
            env_legacy_config_used=self._provider_prompt_legacy_config_used(),
        )

    def _apply_resolved_competitor_prompt_settings(self, business: Business) -> ResolvedAIPromptText:
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
        return resolved

    def _attach_site_content_signals(self, *, site: SEOSite, business_id: str, site_id: str) -> None:
        signals = self._load_site_content_signals(
            business_id=business_id,
            site_id=site_id,
            site_normalized_domain=site.normalized_domain,
        )
        setattr(site, _SITE_CONTENT_SIGNALS_ATTR, signals)

    def _load_site_content_signals(
        self,
        *,
        business_id: str,
        site_id: str,
        site_normalized_domain: str | None,
    ) -> list[str]:
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
        filtered_pages = self._filter_site_content_pages_by_domain(
            pages=pages,
            site_normalized_domain=site_normalized_domain,
        )
        if not filtered_pages:
            return []
        return self._extract_site_content_signals_from_pages(filtered_pages[:_MAX_SITE_CONTENT_SIGNAL_PAGES])

    def _filter_site_content_pages_by_domain(
        self,
        *,
        pages: list[SEOAuditPage],
        site_normalized_domain: str | None,
    ) -> list[SEOAuditPage]:
        normalized_site_domain = self._extract_hostname_for_domain_match(site_normalized_domain)
        if normalized_site_domain is None:
            return pages
        matched_pages: list[SEOAuditPage] = []
        for page in pages:
            page_url_host = self._extract_hostname_for_domain_match(page.url)
            canonical_url_host = self._extract_hostname_for_domain_match(page.canonical_url)
            if self._domain_matches_site(page_url_host, normalized_site_domain) or self._domain_matches_site(
                canonical_url_host,
                normalized_site_domain,
            ):
                matched_pages.append(page)
        return matched_pages

    def _extract_hostname_for_domain_match(self, raw: str | None) -> str | None:
        if raw is None:
            return None
        cleaned = self._clean_optional(raw)
        if not cleaned:
            return None
        parsed_value = cleaned if "://" in cleaned else f"https://{cleaned}"
        try:
            parsed = urlsplit(parsed_value)
        except ValueError:
            return None
        host = (parsed.hostname or "").strip().lower().strip(".")
        if not host:
            return None
        if host.startswith("www."):
            host = host[4:]
        return host or None

    @staticmethod
    def _domain_matches_site(page_host: str | None, site_domain: str) -> bool:
        if page_host is None:
            return False
        if page_host == site_domain:
            return True
        return page_host.endswith(f".{site_domain}")

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
                domain = f"unknown-domain-{max(0, int(decision.candidate.source_index))}"
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
        allowed = set(_REJECTED_CANDIDATE_REASON_KEYS)
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
        return self._build_rejected_candidate_summary_from_values(
            summary=candidate.summary,
            why_competitor=candidate.why_competitor,
            evidence=candidate.evidence,
        )

    def _build_rejected_candidate_summary_from_values(
        self,
        *,
        summary: str | None,
        why_competitor: str | None,
        evidence: str | None,
    ) -> str | None:
        for raw_value in (why_competitor, summary, evidence):
            cleaned = self._clean_optional(raw_value)
            if not cleaned:
                continue
            if len(cleaned) <= REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS:
                return cleaned
                return cleaned[: REJECTED_CANDIDATE_DEBUG_SUMMARY_MAX_CHARS - 3] + "..."
        return None

    def _discover_google_places_seed_candidates(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        requested_candidate_count: int,
        prompt_text_competitor: str,
        run_id: str,
    ) -> list[dict[str, object]]:
        if self.google_places_seed_client is None:
            return []

        try:
            prompt = build_seo_competitor_profile_prompt(
                site=site,
                existing_domains=existing_domains,
                candidate_count=max(1, int(requested_candidate_count)),
                reduced_context_mode=False,
                prompt_version=self._default_prompt_version(),
                prompt_text_competitor=prompt_text_competitor,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SEO competitor Google Places seed discovery skipped run_id=%s site_id=%s reason=prompt_context_build_failed detail=%s",
                run_id,
                site.id,
                str(exc),
            )
            return []

        queries = self._build_google_places_seed_queries(context=prompt.trusted_site_context)
        if not queries:
            return []

        seed_target = min(
            self.google_places_seed_max_candidates,
            max(_GOOGLE_PLACES_SEED_MIN_CANDIDATES, int(requested_candidate_count or 1)),
        )
        try:
            discovered = self.google_places_seed_client.discover_seed_candidates(
                queries=queries,
                max_results=seed_target,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SEO competitor Google Places seed discovery failed run_id=%s site_id=%s reason=client_error detail=%s",
                run_id,
                site.id,
                str(exc),
            )
            return []

        normalized = self._normalize_google_places_seed_candidates(
            candidates=discovered,
            existing_domains=existing_domains,
            site_domain=site.normalized_domain,
            max_results=seed_target,
        )
        self._emit_structured_service_log(
            payload={
                "event": "competitor_google_places_seed_discovery",
                "run_id": run_id,
                "business_id": site.business_id,
                "site_id": site.id,
                "query_count": len(queries),
                "seed_target": seed_target,
                "discovered_count": len(discovered),
                "normalized_seed_count": len(normalized),
                "seed_source": "google_places",
            },
            fallback_message="competitor_google_places_seed_discovery",
        )
        return normalized

    def _build_google_places_seed_queries(self, *, context: dict[str, object]) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()

        raw_hints = context.get("competitor_search_hints")
        if isinstance(raw_hints, list):
            for raw_hint in raw_hints:
                cleaned = self._clean_optional(str(raw_hint) if raw_hint is not None else None)
                if not cleaned:
                    continue
                normalized = cleaned[:_GOOGLE_PLACES_QUERY_MAX_LENGTH]
                lowered = normalized.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                queries.append(normalized)
                if len(queries) >= self.google_places_seed_query_limit:
                    return queries

        service_terms: list[str] = []
        raw_terms = context.get("service_focus_terms")
        if isinstance(raw_terms, list):
            for raw_term in raw_terms:
                cleaned = self._clean_optional(str(raw_term) if raw_term is not None else None)
                if not cleaned:
                    continue
                if "." in cleaned:
                    continue
                lowered = cleaned.lower()
                if lowered in {item.lower() for item in service_terms}:
                    continue
                service_terms.append(cleaned)
                if len(service_terms) >= 3:
                    break

        if not service_terms:
            industry_context = self._clean_optional(
                str(context.get("site_industry_context")) if context.get("site_industry_context") is not None else None
            )
            if industry_context:
                service_terms.append(industry_context)

        expanded_service_terms: list[str] = []
        expanded_seen: set[str] = set()
        for service_term in service_terms:
            normalized_service = self._clean_optional(service_term)
            if not normalized_service:
                continue
            lowered_service = normalized_service.lower()
            if lowered_service not in expanded_seen:
                expanded_seen.add(lowered_service)
                expanded_service_terms.append(normalized_service)
            stripped_suffix = normalized_service.removesuffix(" services").removesuffix(" service").strip()
            if stripped_suffix:
                stripped_lower = stripped_suffix.lower()
                if stripped_lower not in expanded_seen:
                    expanded_seen.add(stripped_lower)
                    expanded_service_terms.append(stripped_suffix)
        if expanded_service_terms:
            service_terms = expanded_service_terms

        location_phrase = self._derive_google_places_query_location(context=context)
        if not service_terms or not location_phrase:
            return queries

        for service_term in service_terms:
            for template in (
                "{service} near {location}",
                "{service} in {location}",
                "{service} company {location}",
                "{service} contractors near {location}",
                "{service} specialists in {location}",
                "{service} providers {location}",
            ):
                candidate = template.format(service=service_term, location=location_phrase).strip()
                cleaned = self._clean_optional(candidate)
                if not cleaned:
                    continue
                normalized = cleaned[:_GOOGLE_PLACES_QUERY_MAX_LENGTH]
                lowered = normalized.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                queries.append(normalized)
                if len(queries) >= self.google_places_seed_query_limit:
                    return queries
        return queries

    def _derive_google_places_query_location(self, *, context: dict[str, object]) -> str | None:
        zip_code = self._clean_optional(
            str(context.get("site_primary_business_zip"))
            if context.get("site_primary_business_zip") is not None
            else None
        )
        if zip_code and len(zip_code) == 5 and zip_code.isdigit():
            return zip_code

        raw_location = self._clean_optional(
            str(context.get("site_primary_location")) if context.get("site_primary_location") is not None else None
        )
        if not raw_location:
            raw_location = self._clean_optional(
                str(context.get("site_location_context")) if context.get("site_location_context") is not None else None
            )
        if not raw_location:
            return None

        lowered = raw_location.lower()
        for marker in (" and nearby service areas", " and service areas", " serving "):
            marker_index = lowered.find(marker)
            if marker_index > 0:
                raw_location = raw_location[:marker_index].strip()
                break
        if raw_location.lower().startswith("serves "):
            raw_location = raw_location[7:].strip()
        cleaned = self._clean_optional(raw_location)
        if not cleaned:
            return None
        return cleaned[:_GOOGLE_PLACES_QUERY_MAX_LENGTH]

    def _normalize_google_places_seed_candidates(
        self,
        *,
        candidates: list[GooglePlacesSeedCandidate],
        existing_domains: list[str],
        site_domain: str | None,
        max_results: int,
    ) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        seen_place_ids: set[str] = set()
        known_domains = {
            candidate_domain
            for raw_domain in [*(existing_domains or []), site_domain]
            for candidate_domain in [self._normalize_optional_domain_value(raw_domain)]
            if candidate_domain
        }
        bounded_max_results = max(1, min(_GOOGLE_PLACES_SEED_MAX_CANDIDATES, int(max_results)))
        bounded_max_results = min(bounded_max_results, self.google_places_seed_max_candidates)

        for candidate in candidates:
            place_id = self._clean_optional(candidate.place_id)
            name = self._clean_optional(candidate.name)
            if not place_id or not name:
                continue
            place_key = place_id.lower()
            if place_key in seen_place_ids:
                continue
            seen_place_ids.add(place_key)

            website_domain = self._normalize_optional_domain_value(candidate.website_domain)
            if website_domain and website_domain in known_domains:
                continue

            types: list[str] = []
            seen_types: set[str] = set()
            for raw_type in candidate.types:
                cleaned_type = self._clean_optional(raw_type)
                if not cleaned_type:
                    continue
                lowered = cleaned_type.lower()
                if lowered in seen_types:
                    continue
                seen_types.add(lowered)
                types.append(lowered[:_GOOGLE_PLACES_SEED_MAX_TYPE_LENGTH])
                if len(types) >= _GOOGLE_PLACES_SEED_MAX_TYPES:
                    break

            normalized.append(
                {
                    "source": "google_places",
                    "place_id": place_id[:255],
                    "name": name[:_GOOGLE_PLACES_SEED_MAX_NAME_LENGTH],
                    "formatted_address": (self._clean_optional(candidate.formatted_address) or "")[
                        :_GOOGLE_PLACES_SEED_MAX_ADDRESS_LENGTH
                    ],
                    "locality": (self._clean_optional(candidate.locality) or "")[
                        :_GOOGLE_PLACES_SEED_MAX_LOCALITY_LENGTH
                    ],
                    "primary_type": (self._clean_optional(candidate.primary_type) or "")[
                        :_GOOGLE_PLACES_SEED_MAX_TYPE_LENGTH
                    ],
                    "types": types,
                    "website_domain": website_domain or "",
                }
            )
            if len(normalized) >= bounded_max_results:
                break
        return normalized

    def _generate_competitor_profiles_with_timeout_retry(
        self,
        *,
        business: Business,
        site: SEOSite,
        existing_domains: list[str],
        run_id: str,
        requested_candidate_count: int,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug],
        prompt_text_competitor: str,
        google_places_seed_candidates: list[dict[str, object]] | None = None,
    ) -> SEOCompetitorProfileGenerationOutput:
        normalized_google_places_seed_candidates = list(google_places_seed_candidates or [])
        effective_requested_count = max(1, int(requested_candidate_count))
        discovery_candidate_count = self._discovery_candidate_count(effective_requested_count)
        max_attempts = _MAX_PROVIDER_TIMEOUT_ATTEMPTS

        def _recovery_path_for_success_attempt(
            attempt: SEOCompetitorProfileProviderAttemptDebug,
        ) -> str:
            if attempt.execution_mode == _EXECUTION_MODE_DEGRADED:
                return "degraded_success"
            if (
                attempt.execution_mode == _EXECUTION_MODE_FULL
                and attempt.provider_call_type == _PROVIDER_CALL_TYPE_NON_TOOL
            ):
                return "fallback_success"
            return "retry_success"

        def _finalize_timeout_outcome(
            *,
            final_outcome: str,
            recovery_path: str = "none",
        ) -> None:
            self._finalize_provider_attempt_timeout_outcome(
                provider_attempts=provider_attempts,
                final_outcome=final_outcome,
                recovery_path=recovery_path,
                max_attempts=max_attempts,
            )
            self._emit_timeout_outcome_summary_log(
                run_id=run_id,
                site=site,
                provider_attempts=provider_attempts,
                final_outcome=final_outcome,
                recovery_path=recovery_path,
                max_attempts=max_attempts,
            )

        primary_timeout_seconds = self._resolve_competitor_attempt_timeout_seconds(
            business=business,
            degraded_mode=False,
        )
        fast_path_prompt_metrics = self._build_provider_attempt_prompt_metrics(
            site=site,
            existing_domains=existing_domains,
            candidate_count=discovery_candidate_count,
            reduced_context_mode=True,
            prompt_text_competitor=prompt_text_competitor,
            google_places_seed_candidates=normalized_google_places_seed_candidates,
        )
        fast_path_attempt_start = time.perf_counter()
        try:
            output = self._invoke_provider_generate_competitor_profiles(
                site=site,
                existing_domains=existing_domains,
                candidate_count=discovery_candidate_count,
                reduced_context_mode=True,
                run_id=run_id,
                attempt_number=0,
                degraded_mode=False,
                execution_mode=_EXECUTION_MODE_FAST_PATH,
                provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                attempt_timeout_seconds=primary_timeout_seconds,
                seed_candidates=normalized_google_places_seed_candidates,
            )
            fast_path_duration_ms = max(0, int((time.perf_counter() - fast_path_attempt_start) * 1000))
            provider_attempts.append(
                self._build_provider_attempt_debug(
                    attempt_number=0,
                    execution_mode=_EXECUTION_MODE_FAST_PATH,
                    provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                    degraded_mode=False,
                    prompt_metrics=fast_path_prompt_metrics,
                    requested_candidate_count=discovery_candidate_count,
                    fallback_google_places_seed_count=len(normalized_google_places_seed_candidates),
                    fallback_duration_ms=fast_path_duration_ms,
                    fallback_timeout_seconds=primary_timeout_seconds,
                    provider_output=output,
                    provider_error=None,
                    max_attempts=max_attempts,
                )
            )
            if len(output.candidates) > 0:
                _finalize_timeout_outcome(final_outcome="success")
                return output
            provider_attempts[-1] = replace(
                provider_attempts[-1],
                search_escalation_triggered=True,
                escalation_reason="zero_valid_competitors",
            )
            self._emit_structured_service_log(
                payload={
                    "event": "competitor_search_escalation",
                    "run_id": run_id,
                    "business_id": site.business_id,
                    "site_id": site.id,
                    "attempt_number": 0,
                    "execution_mode": _EXECUTION_MODE_FAST_PATH,
                    "provider_call_type": _PROVIDER_CALL_TYPE_NON_TOOL,
                    "web_search_enabled": False,
                    "search_escalation_triggered": True,
                    "escalation_reason": "zero_valid_competitors",
                    "candidate_count": len(output.candidates),
                },
                fallback_message="competitor_search_escalation",
            )
        except SEOCompetitorProfileProviderError as fast_path_exc:
            fast_path_duration_ms = max(0, int((time.perf_counter() - fast_path_attempt_start) * 1000))
            fast_path_attempt_debug = self._build_provider_attempt_debug(
                attempt_number=0,
                execution_mode=_EXECUTION_MODE_FAST_PATH,
                provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                degraded_mode=False,
                prompt_metrics=fast_path_prompt_metrics,
                requested_candidate_count=discovery_candidate_count,
                fallback_google_places_seed_count=len(normalized_google_places_seed_candidates),
                fallback_duration_ms=fast_path_duration_ms,
                fallback_timeout_seconds=primary_timeout_seconds,
                provider_output=None,
                provider_error=fast_path_exc,
                max_attempts=max_attempts,
            )
            provider_attempts.append(fast_path_attempt_debug)
            if fast_path_exc.code == "provider_auth_config":
                raise fast_path_exc

        full_prompt_metrics = self._build_provider_attempt_prompt_metrics(
            site=site,
            existing_domains=existing_domains,
            candidate_count=discovery_candidate_count,
            reduced_context_mode=False,
            prompt_text_competitor=prompt_text_competitor,
            google_places_seed_candidates=normalized_google_places_seed_candidates,
        )
        full_attempt_start = time.perf_counter()
        try:
            output = self._invoke_provider_generate_competitor_profiles(
                site=site,
                existing_domains=existing_domains,
                candidate_count=discovery_candidate_count,
                reduced_context_mode=False,
                run_id=run_id,
                attempt_number=1,
                degraded_mode=False,
                execution_mode=_EXECUTION_MODE_FULL,
                provider_call_type=_PROVIDER_CALL_TYPE_TOOL_ENABLED,
                attempt_timeout_seconds=primary_timeout_seconds,
                seed_candidates=normalized_google_places_seed_candidates,
            )
            full_duration_ms = max(0, int((time.perf_counter() - full_attempt_start) * 1000))
            provider_attempts.append(
                self._build_provider_attempt_debug(
                    attempt_number=1,
                    execution_mode=_EXECUTION_MODE_FULL,
                    provider_call_type=_PROVIDER_CALL_TYPE_TOOL_ENABLED,
                    degraded_mode=False,
                    prompt_metrics=full_prompt_metrics,
                    requested_candidate_count=discovery_candidate_count,
                    fallback_google_places_seed_count=len(normalized_google_places_seed_candidates),
                    fallback_duration_ms=full_duration_ms,
                    fallback_timeout_seconds=primary_timeout_seconds,
                    provider_output=output,
                    provider_error=None,
                    max_attempts=max_attempts,
                )
            )
            if any(item.failure_kind == "timeout" for item in provider_attempts):
                _finalize_timeout_outcome(
                    final_outcome="success",
                    recovery_path=_recovery_path_for_success_attempt(provider_attempts[-1]),
                )
            else:
                _finalize_timeout_outcome(final_outcome="success")
            return output
        except SEOCompetitorProfileProviderError as full_exc:
            full_duration_ms = max(0, int((time.perf_counter() - full_attempt_start) * 1000))
            full_attempt_debug = self._build_provider_attempt_debug(
                attempt_number=1,
                execution_mode=_EXECUTION_MODE_FULL,
                provider_call_type=_PROVIDER_CALL_TYPE_TOOL_ENABLED,
                degraded_mode=False,
                prompt_metrics=full_prompt_metrics,
                requested_candidate_count=discovery_candidate_count,
                fallback_google_places_seed_count=len(normalized_google_places_seed_candidates),
                fallback_duration_ms=full_duration_ms,
                fallback_timeout_seconds=primary_timeout_seconds,
                provider_output=None,
                provider_error=full_exc,
                max_attempts=max_attempts,
            )
            provider_attempts.append(full_attempt_debug)
            if full_attempt_debug.failure_kind != "timeout":
                _finalize_timeout_outcome(final_outcome="failure")
                raise full_exc

        degraded_candidate_count = self._degraded_retry_candidate_count(
            requested_candidate_count=effective_requested_count,
            initial_discovery_candidate_count=discovery_candidate_count,
        )
        degraded_timeout_seconds = self._resolve_competitor_attempt_timeout_seconds(
            business=business,
            degraded_mode=True,
        )
        degraded_prompt_metrics = self._build_provider_attempt_prompt_metrics(
            site=site,
            existing_domains=existing_domains,
            candidate_count=degraded_candidate_count,
            reduced_context_mode=True,
            prompt_text_competitor=prompt_text_competitor,
            google_places_seed_candidates=normalized_google_places_seed_candidates,
        )
        if _TIMEOUT_RETRY_BACKOFF_SECONDS > 0:
            time.sleep(_TIMEOUT_RETRY_BACKOFF_SECONDS)
        degraded_attempt_start = time.perf_counter()
        try:
            output = self._invoke_provider_generate_competitor_profiles(
                site=site,
                existing_domains=existing_domains,
                candidate_count=degraded_candidate_count,
                reduced_context_mode=True,
                run_id=run_id,
                attempt_number=2,
                degraded_mode=True,
                execution_mode=_EXECUTION_MODE_DEGRADED,
                provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                attempt_timeout_seconds=degraded_timeout_seconds,
                seed_candidates=normalized_google_places_seed_candidates,
            )
        except SEOCompetitorProfileProviderError as degraded_exc:
            degraded_duration_ms = max(0, int((time.perf_counter() - degraded_attempt_start) * 1000))
            provider_attempts.append(
                self._build_provider_attempt_debug(
                    attempt_number=2,
                    execution_mode=_EXECUTION_MODE_DEGRADED,
                    provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                    degraded_mode=True,
                    prompt_metrics=degraded_prompt_metrics,
                    requested_candidate_count=degraded_candidate_count,
                    fallback_google_places_seed_count=len(normalized_google_places_seed_candidates),
                    fallback_duration_ms=degraded_duration_ms,
                    fallback_timeout_seconds=degraded_timeout_seconds,
                    provider_output=None,
                    provider_error=degraded_exc,
                    max_attempts=max_attempts,
                )
            )
            _finalize_timeout_outcome(final_outcome="failure")
            raise degraded_exc

        degraded_duration_ms = max(0, int((time.perf_counter() - degraded_attempt_start) * 1000))
        provider_attempts.append(
            self._build_provider_attempt_debug(
                attempt_number=2,
                execution_mode=_EXECUTION_MODE_DEGRADED,
                provider_call_type=_PROVIDER_CALL_TYPE_NON_TOOL,
                degraded_mode=True,
                prompt_metrics=degraded_prompt_metrics,
                requested_candidate_count=degraded_candidate_count,
                fallback_google_places_seed_count=len(normalized_google_places_seed_candidates),
                fallback_duration_ms=degraded_duration_ms,
                fallback_timeout_seconds=degraded_timeout_seconds,
                provider_output=output,
                provider_error=None,
                max_attempts=max_attempts,
            )
        )
        _finalize_timeout_outcome(
            final_outcome="degraded_success",
            recovery_path="degraded_success",
        )
        logger.info(
            (
                "SEO competitor timeout retry recovered business_id=%s site_id=%s "
                "attempts=%s full_discovery_candidate_count=%s degraded_candidate_count=%s "
                "full_attempt_duration_ms=%s degraded_attempt_duration_ms=%s"
            ),
            site.business_id,
            site.id,
            3,
            discovery_candidate_count,
            degraded_candidate_count,
            provider_attempts[-2].request_duration_ms if len(provider_attempts) > 1 else None,
            provider_attempts[-1].request_duration_ms,
        )
        return output

    def _invoke_provider_generate_competitor_profiles(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
        reduced_context_mode: bool,
        seed_candidates: list[dict[str, object]] | None = None,
        run_id: str | None = None,
        attempt_number: int | None = None,
        degraded_mode: bool = False,
        execution_mode: str = _EXECUTION_MODE_FULL,
        provider_call_type: str = _PROVIDER_CALL_TYPE_TOOL_ENABLED,
        attempt_timeout_seconds: int | None = None,
    ) -> SEOCompetitorProfileGenerationOutput:
        normalized_execution_mode = execution_mode if execution_mode in _EXECUTION_MODES else _EXECUTION_MODE_FULL
        normalized_provider_call_type = (
            provider_call_type if provider_call_type in _PROVIDER_CALL_TYPES else _PROVIDER_CALL_TYPE_TOOL_ENABLED
        )
        if (
            normalized_execution_mode in {_EXECUTION_MODE_FAST_PATH, _EXECUTION_MODE_DEGRADED}
            and normalized_provider_call_type != _PROVIDER_CALL_TYPE_NON_TOOL
        ):
            raise SEOCompetitorProfileGenerationValidationError(
                "Non-tool provider call is required for fast_path and degraded execution modes."
            )
        provider_method = self.provider.generate_competitor_profiles
        try:
            signature = inspect.signature(provider_method)
        except (TypeError, ValueError):
            signature = None
        kwargs: dict[str, object] = {
            "site": site,
            "existing_domains": existing_domains,
            "candidate_count": candidate_count,
        }
        if signature is not None:
            parameters = signature.parameters
            if "reduced_context_mode" in parameters:
                kwargs["reduced_context_mode"] = reduced_context_mode
            if "run_id" in parameters:
                kwargs["run_id"] = run_id
            if "attempt_number" in parameters:
                kwargs["attempt_number"] = attempt_number
            if "degraded_mode" in parameters:
                kwargs["degraded_mode"] = degraded_mode
            if "execution_mode" in parameters:
                kwargs["execution_mode"] = normalized_execution_mode
            if "provider_call_type" in parameters:
                kwargs["provider_call_type"] = normalized_provider_call_type
            if "web_search_enabled" in parameters:
                kwargs["web_search_enabled"] = normalized_provider_call_type == _PROVIDER_CALL_TYPE_TOOL_ENABLED
            if "seed_candidates" in parameters:
                kwargs["seed_candidates"] = list(seed_candidates or [])
            if "timeout_seconds" in parameters and attempt_timeout_seconds is not None:
                kwargs["timeout_seconds"] = attempt_timeout_seconds
            return provider_method(**kwargs)
        return provider_method(**kwargs)

    def _build_provider_attempt_prompt_metrics(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
        reduced_context_mode: bool,
        prompt_text_competitor: str,
        google_places_seed_candidates: list[dict[str, object]] | None = None,
    ) -> _ProviderAttemptPromptMetrics:
        try:
            prompt = build_seo_competitor_profile_prompt(
                site=site,
                existing_domains=existing_domains,
                candidate_count=max(1, int(candidate_count)),
                reduced_context_mode=bool(reduced_context_mode),
                prompt_version=self._default_prompt_version(),
                prompt_text_competitor=prompt_text_competitor,
                seed_candidates=list(google_places_seed_candidates or []),
            )
        except Exception:  # noqa: BLE001
            return _ProviderAttemptPromptMetrics(
                reduced_context_mode=bool(reduced_context_mode),
                prompt_total_chars=None,
                context_json_chars=None,
                user_prompt_chars=None,
            )
        telemetry = prompt.prompt_telemetry or {}
        return _ProviderAttemptPromptMetrics(
            reduced_context_mode=bool(reduced_context_mode),
            prompt_total_chars=self._coerce_non_negative_int(telemetry.get("total_prompt_chars")),
            context_json_chars=self._coerce_non_negative_int(telemetry.get("context_json_chars")),
            user_prompt_chars=self._coerce_non_negative_int(telemetry.get("user_prompt_chars")),
        )

    @staticmethod
    def _coerce_non_negative_int(value: object) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, parsed)

    @staticmethod
    def _discovery_candidate_count(requested_candidate_count: int) -> int:
        normalized = max(1, int(requested_candidate_count))
        boosted = normalized + _DISCOVERY_CANDIDATE_BUFFER
        return max(1, min(_MAX_DISCOVERY_CANDIDATE_COUNT, boosted))

    @staticmethod
    def _degraded_retry_candidate_count(
        *,
        requested_candidate_count: int,
        initial_discovery_candidate_count: int,
    ) -> int:
        requested = max(1, int(requested_candidate_count))
        initial_discovery = max(requested, int(initial_discovery_candidate_count))
        degraded_target = max(requested, initial_discovery - 1)
        if requested <= 1:
            degraded_target = max(_MIN_DEGRADED_DISCOVERY_CANDIDATE_COUNT, degraded_target)
        return max(1, min(_MAX_DISCOVERY_CANDIDATE_COUNT, degraded_target))

    def _resolve_competitor_attempt_timeout_seconds(self, *, business: Business, degraded_mode: bool) -> int | None:
        configured_timeout_raw: object | None
        if degraded_mode:
            configured_timeout_raw = business.competitor_degraded_timeout_seconds
        else:
            configured_timeout_raw = business.competitor_primary_timeout_seconds

        configured_timeout_seconds = self._coerce_competitor_timeout_seconds(configured_timeout_raw)
        if configured_timeout_seconds is not None:
            return configured_timeout_seconds

        return self._coerce_competitor_timeout_seconds(getattr(self.provider, "timeout_seconds", None))

    @staticmethod
    def _coerce_competitor_timeout_seconds(value: object) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed < COMPETITOR_TIMEOUT_SECONDS_MIN or parsed > COMPETITOR_TIMEOUT_SECONDS_MAX:
            return None
        return parsed

    def _build_provider_attempt_debug(
        self,
        *,
        attempt_number: int,
        execution_mode: str,
        provider_call_type: str,
        degraded_mode: bool,
        prompt_metrics: _ProviderAttemptPromptMetrics,
        requested_candidate_count: int,
        fallback_google_places_seed_count: int,
        fallback_duration_ms: int,
        fallback_timeout_seconds: int | None,
        provider_output: SEOCompetitorProfileGenerationOutput | None,
        provider_error: SEOCompetitorProfileProviderError | None,
        max_attempts: int | None = None,
    ) -> SEOCompetitorProfileProviderAttemptDebug:
        failure_kind = "unknown"
        malformed_output_reason: str | None = None
        endpoint_path: str | None = None
        prompt_size_risk: str | None = None
        timeout_seconds: int | None = None
        timeout_type: str | None = None
        web_search_enabled: bool | None = None
        resolved_provider_call_type: str | None = (
            provider_call_type if provider_call_type in _PROVIDER_CALL_TYPES else None
        )
        resolved_execution_mode = execution_mode if execution_mode in _EXECUTION_MODES else _EXECUTION_MODE_FULL
        request_duration_ms: int | None = max(0, int(fallback_duration_ms))
        outcome = "success"
        reduced_context_mode = bool(prompt_metrics.reduced_context_mode)
        prompt_total_chars = prompt_metrics.prompt_total_chars
        context_json_chars = prompt_metrics.context_json_chars
        user_prompt_chars = prompt_metrics.user_prompt_chars
        google_places_seed_count = max(0, int(fallback_google_places_seed_count))

        if provider_error is not None:
            if provider_error.code == "timeout":
                failure_kind = "timeout"
            elif provider_error.code == "provider_request":
                failure_kind = "provider_request"
            elif provider_error.code in {"invalid_output", "schema_validation", "parsing_error"}:
                failure_kind = "malformed_output"
            provider_debug = self._extract_provider_failure_debug(provider_error.raw_output)
            if provider_debug is not None:
                if provider_debug.failure_kind in {"timeout", "provider_request", "malformed_output"}:
                    failure_kind = provider_debug.failure_kind
                if provider_debug.malformed_output_reason:
                    malformed_output_reason = provider_debug.malformed_output_reason
                endpoint_path = provider_debug.endpoint_path
                prompt_size_risk = provider_debug.prompt_size_risk
                timeout_seconds = provider_debug.timeout_seconds
                timeout_type = provider_debug.timeout_type
                web_search_enabled = provider_debug.web_search_enabled
                if provider_debug.provider_call_type in _PROVIDER_CALL_TYPES:
                    resolved_provider_call_type = provider_debug.provider_call_type
                if provider_debug.reduced_context_mode is not None:
                    reduced_context_mode = provider_debug.reduced_context_mode
                if provider_debug.prompt_total_chars is not None:
                    prompt_total_chars = provider_debug.prompt_total_chars
                if provider_debug.context_json_chars is not None:
                    context_json_chars = provider_debug.context_json_chars
                if provider_debug.user_prompt_chars is not None:
                    user_prompt_chars = provider_debug.user_prompt_chars
                if provider_debug.request_duration_ms is not None:
                    request_duration_ms = provider_debug.request_duration_ms
                if provider_debug.google_places_seed_count is not None:
                    google_places_seed_count = max(
                        google_places_seed_count,
                        max(0, int(provider_debug.google_places_seed_count)),
                    )
            outcome = failure_kind
        elif provider_output is not None:
            output_endpoint_path = self._clean_optional(provider_output.endpoint_path)
            if output_endpoint_path:
                endpoint_path = output_endpoint_path
            if isinstance(provider_output.web_search_enabled, bool):
                web_search_enabled = provider_output.web_search_enabled
            output_provider_call_type = self._clean_optional(provider_output.provider_call_type)
            if output_provider_call_type in _PROVIDER_CALL_TYPES:
                resolved_provider_call_type = output_provider_call_type
            if provider_output.request_duration_ms is not None:
                request_duration_ms = max(0, int(provider_output.request_duration_ms))
            google_places_seed_count = max(
                google_places_seed_count,
                max(0, int(getattr(provider_output, "google_places_seed_count", 0) or 0)),
            )
        if timeout_seconds is None and fallback_timeout_seconds is not None:
            timeout_seconds = max(1, int(fallback_timeout_seconds))
        if resolved_provider_call_type is None and isinstance(web_search_enabled, bool):
            resolved_provider_call_type = (
                _PROVIDER_CALL_TYPE_TOOL_ENABLED if web_search_enabled else _PROVIDER_CALL_TYPE_NON_TOOL
            )
        if resolved_provider_call_type is None:
            resolved_provider_call_type = _PROVIDER_CALL_TYPE_TOOL_ENABLED
        if web_search_enabled is None:
            web_search_enabled = resolved_provider_call_type == _PROVIDER_CALL_TYPE_TOOL_ENABLED
        if resolved_execution_mode in {_EXECUTION_MODE_FAST_PATH, _EXECUTION_MODE_DEGRADED}:
            resolved_provider_call_type = _PROVIDER_CALL_TYPE_NON_TOOL
            web_search_enabled = False
        normalized_max_attempts: int | None = None
        if max_attempts is not None:
            try:
                normalized_max_attempts = max(1, int(max_attempts))
            except (TypeError, ValueError):
                normalized_max_attempts = None
        if timeout_type not in _TIMEOUT_TYPE_VALUES:
            timeout_type = None
        return SEOCompetitorProfileProviderAttemptDebug(
            attempt_number=max(0, int(attempt_number)),
            execution_mode=resolved_execution_mode,
            provider_call_type=resolved_provider_call_type,
            degraded_mode=bool(degraded_mode),
            reduced_context_mode=reduced_context_mode,
            requested_candidate_count=max(1, int(requested_candidate_count)),
            outcome=outcome,
            failure_kind=None if provider_error is None else failure_kind,
            malformed_output_reason=malformed_output_reason,
            request_duration_ms=request_duration_ms,
            timeout_seconds=timeout_seconds,
            web_search_enabled=web_search_enabled,
            prompt_size_risk=prompt_size_risk,
            prompt_total_chars=prompt_total_chars,
            context_json_chars=context_json_chars,
            user_prompt_chars=user_prompt_chars,
            endpoint_path=endpoint_path,
            max_attempts=normalized_max_attempts,
            timeout_type=timeout_type,
            google_places_seed_count=google_places_seed_count,
        )

    @dataclass(frozen=True)
    class _ProviderFailureDebug:
        failure_kind: str
        malformed_output_reason: str | None
        endpoint_path: str | None
        provider_call_type: str | None
        prompt_size_risk: str | None
        timeout_seconds: int | None
        timeout_type: str | None
        web_search_enabled: bool | None
        reduced_context_mode: bool | None
        prompt_total_chars: int | None
        context_json_chars: int | None
        user_prompt_chars: int | None
        request_duration_ms: int | None
        google_places_seed_count: int | None

    def _extract_provider_failure_debug(self, raw_output: str | None) -> _ProviderFailureDebug | None:
        if not raw_output:
            return None
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        raw_failure_kind = self._clean_optional(str(parsed.get("failure_kind") or "")) or "unknown"
        if raw_failure_kind not in {"timeout", "provider_request", "malformed_output"}:
            raw_failure_kind = "unknown"
        malformed_output_reason = self._clean_optional(str(parsed.get("malformed_output_reason") or ""))
        if malformed_output_reason and len(malformed_output_reason) > 64:
            malformed_output_reason = malformed_output_reason[:64]
        timeout_type = self._clean_optional(str(parsed.get("timeout_type") or ""))
        if timeout_type not in _TIMEOUT_TYPE_VALUES:
            timeout_type = None
        endpoint_path = self._clean_optional(str(parsed.get("endpoint_path") or ""))
        request_debug = parsed.get("request_debug") if isinstance(parsed.get("request_debug"), dict) else {}
        provider_call_type = None
        prompt_size_risk = self._clean_optional(str(request_debug.get("prompt_size_risk") or ""))
        if prompt_size_risk not in {"normal", "elevated", "high"}:
            prompt_size_risk = None
        timeout_seconds = None
        request_duration_ms = None
        web_search_enabled = None
        reduced_context_mode = None
        prompt_total_chars = None
        context_json_chars = None
        user_prompt_chars = None
        google_places_seed_count = None
        if isinstance(request_debug, dict):
            raw_provider_call_type = self._clean_optional(str(request_debug.get("provider_call_type") or ""))
            if raw_provider_call_type in _PROVIDER_CALL_TYPES:
                provider_call_type = raw_provider_call_type
            try:
                timeout_seconds = max(1, int(request_debug.get("timeout_seconds")))
            except (TypeError, ValueError):
                timeout_seconds = None
            try:
                request_duration_ms = max(0, int(request_debug.get("request_duration_ms")))
            except (TypeError, ValueError):
                request_duration_ms = None
            raw_web_search_enabled = request_debug.get("web_search_enabled")
            if isinstance(raw_web_search_enabled, bool):
                web_search_enabled = raw_web_search_enabled
            raw_reduced_context_mode = request_debug.get("reduced_context_mode")
            if isinstance(raw_reduced_context_mode, bool):
                reduced_context_mode = raw_reduced_context_mode
            try:
                if request_debug.get("prompt_total_chars") is not None:
                    prompt_total_chars = max(0, int(request_debug.get("prompt_total_chars")))
            except (TypeError, ValueError):
                prompt_total_chars = None
            try:
                if request_debug.get("context_json_chars") is not None:
                    context_json_chars = max(0, int(request_debug.get("context_json_chars")))
            except (TypeError, ValueError):
                context_json_chars = None
            try:
                if request_debug.get("user_prompt_chars") is not None:
                    user_prompt_chars = max(0, int(request_debug.get("user_prompt_chars")))
            except (TypeError, ValueError):
                user_prompt_chars = None
            try:
                if request_debug.get("google_places_seed_count") is not None:
                    google_places_seed_count = max(0, int(request_debug.get("google_places_seed_count")))
            except (TypeError, ValueError):
                google_places_seed_count = None
        return self._ProviderFailureDebug(
            failure_kind=raw_failure_kind,
            malformed_output_reason=malformed_output_reason,
            endpoint_path=endpoint_path,
            provider_call_type=provider_call_type,
            prompt_size_risk=prompt_size_risk,
            timeout_seconds=timeout_seconds,
            timeout_type=timeout_type,
            web_search_enabled=web_search_enabled,
            reduced_context_mode=reduced_context_mode,
            prompt_total_chars=prompt_total_chars,
            context_json_chars=context_json_chars,
            user_prompt_chars=user_prompt_chars,
            request_duration_ms=request_duration_ms,
            google_places_seed_count=google_places_seed_count,
        )

    def _finalize_provider_attempt_timeout_outcome(
        self,
        *,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug],
        final_outcome: str,
        recovery_path: str,
        max_attempts: int,
    ) -> None:
        if not provider_attempts:
            return
        normalized_final_outcome = final_outcome if final_outcome in _TIMEOUT_FINAL_OUTCOMES else "failure"
        normalized_recovery_path = recovery_path if recovery_path in _TIMEOUT_RECOVERY_PATHS else "none"
        timeout_observed = any(item.failure_kind == "timeout" for item in provider_attempts)
        recovered_after_timeout = bool(
            timeout_observed
            and normalized_final_outcome in {"success", "degraded_success"}
            and normalized_recovery_path
            in {"retry_success", "fallback_success", "degraded_success", _SYNTHETIC_FALLBACK_RECOVERY_PATH}
        )
        normalized_max_attempts = max(1, int(max_attempts))
        for index, attempt in enumerate(provider_attempts):
            provider_attempts[index] = replace(
                attempt,
                max_attempts=normalized_max_attempts,
                recovered_after_timeout=(recovered_after_timeout if timeout_observed else False),
                recovery_path=(normalized_recovery_path if timeout_observed else "none"),
                final_outcome=normalized_final_outcome,
            )

    def _emit_timeout_outcome_summary_log(
        self,
        *,
        run_id: str,
        site: SEOSite,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug],
        final_outcome: str,
        recovery_path: str,
        max_attempts: int,
    ) -> None:
        timeout_attempts = [item for item in provider_attempts if item.failure_kind == "timeout"]
        if not timeout_attempts:
            return
        normalized_final_outcome = final_outcome if final_outcome in _TIMEOUT_FINAL_OUTCOMES else "failure"
        normalized_recovery_path = recovery_path if recovery_path in _TIMEOUT_RECOVERY_PATHS else "none"
        recovered_after_timeout = bool(
            normalized_final_outcome in {"success", "degraded_success"}
            and normalized_recovery_path
            in {"retry_success", "fallback_success", "degraded_success", _SYNTHETIC_FALLBACK_RECOVERY_PATH}
        )
        latest_attempt = provider_attempts[-1]
        latest_timeout_attempt = timeout_attempts[-1]
        total_elapsed_ms = 0
        for item in provider_attempts:
            if item.request_duration_ms is not None:
                total_elapsed_ms += max(0, int(item.request_duration_ms))
        if normalized_final_outcome == "failure":
            level = logging.ERROR
        elif normalized_final_outcome == "degraded_success":
            level = logging.WARNING
        else:
            level = logging.INFO
        payload: dict[str, object] = {
            "event": "competitor_timeout_outcome",
            "run_id": run_id,
            "business_id": site.business_id,
            "site_id": site.id,
            "attempt_number": latest_attempt.attempt_number,
            "attempt_count": len(provider_attempts),
            "max_attempts": max(1, int(max_attempts)),
            "provider_name": self._clean_optional(getattr(self.provider, "provider_name", None)),
            "model_name": self._clean_optional(getattr(self.provider, "model_name", None)),
            "endpoint_path": latest_attempt.endpoint_path,
            "provider_call_type": latest_attempt.provider_call_type,
            "web_search_enabled": latest_attempt.web_search_enabled,
            "timeout_type": latest_timeout_attempt.timeout_type or "unknown",
            "elapsed_ms": latest_attempt.request_duration_ms,
            "total_elapsed_ms": total_elapsed_ms,
            "prompt_total_chars": latest_attempt.prompt_total_chars,
            "context_json_chars": latest_attempt.context_json_chars,
            "prompt_size_risk": latest_attempt.prompt_size_risk,
            "recovered_after_timeout": recovered_after_timeout,
            "recovery_path": normalized_recovery_path,
            "final_outcome": normalized_final_outcome,
        }
        try:
            message = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            message = "competitor_timeout_outcome"
        logger.log(level, message, extra={"json_fields": payload})

    def _serialize_provider_attempts_for_debug(
        self,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug] | None,
    ) -> list[dict[str, object]]:
        if not provider_attempts:
            return []
        serialized: list[dict[str, object]] = []
        for item in provider_attempts[-_MAX_PROVIDER_ATTEMPTS_DEBUG_ITEMS:]:
            payload: dict[str, object] = {
                "attempt_number": max(0, int(item.attempt_number)),
                "execution_mode": self._clean_optional(item.execution_mode) or _EXECUTION_MODE_FULL,
                "provider_call_type": (
                    self._clean_optional(item.provider_call_type) or _PROVIDER_CALL_TYPE_TOOL_ENABLED
                ),
                "degraded_mode": bool(item.degraded_mode),
                "reduced_context_mode": bool(item.reduced_context_mode),
                "requested_candidate_count": max(1, int(item.requested_candidate_count)),
                "outcome": self._clean_optional(item.outcome) or "success",
            }
            if item.failure_kind:
                payload["failure_kind"] = item.failure_kind
            if item.malformed_output_reason:
                payload["malformed_output_reason"] = item.malformed_output_reason
            if item.request_duration_ms is not None:
                payload["request_duration_ms"] = max(0, int(item.request_duration_ms))
            if item.timeout_seconds is not None:
                payload["timeout_seconds"] = max(1, int(item.timeout_seconds))
            if item.web_search_enabled is not None:
                payload["web_search_enabled"] = bool(item.web_search_enabled)
            if item.prompt_size_risk:
                payload["prompt_size_risk"] = item.prompt_size_risk
            if item.prompt_total_chars is not None:
                payload["prompt_total_chars"] = max(0, int(item.prompt_total_chars))
            if item.context_json_chars is not None:
                payload["context_json_chars"] = max(0, int(item.context_json_chars))
            if item.user_prompt_chars is not None:
                payload["user_prompt_chars"] = max(0, int(item.user_prompt_chars))
            if item.endpoint_path:
                payload["endpoint_path"] = item.endpoint_path
            if item.max_attempts is not None:
                payload["max_attempts"] = max(1, int(item.max_attempts))
            if item.timeout_type in _TIMEOUT_TYPE_VALUES:
                payload["timeout_type"] = item.timeout_type
            if item.recovered_after_timeout is not None:
                payload["recovered_after_timeout"] = bool(item.recovered_after_timeout)
            if item.recovery_path in _TIMEOUT_RECOVERY_PATHS:
                payload["recovery_path"] = item.recovery_path
            if item.final_outcome in _TIMEOUT_FINAL_OUTCOMES:
                payload["final_outcome"] = item.final_outcome
            if item.search_escalation_triggered:
                payload["search_escalation_triggered"] = True
            if item.escalation_reason:
                payload["escalation_reason"] = item.escalation_reason
            if item.google_places_seed_count > 0:
                payload["google_places_seed_count"] = max(0, int(item.google_places_seed_count))
            serialized.append(payload)
        return serialized

    def _extract_provider_attempts_debug_from_raw_output(
        self,
        raw_output: str | None,
    ) -> tuple[int, bool, list[SEOCompetitorProfileProviderAttemptDebug]]:
        if not raw_output:
            return 0, False, []
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0, False, []
        if not isinstance(parsed, dict):
            return 0, False, []

        raw_items = parsed.get(_PROVIDER_ATTEMPTS_DEBUG_KEY)
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug] = []
        if isinstance(raw_items, list):
            for raw_item in raw_items[:_MAX_PROVIDER_ATTEMPTS_DEBUG_ITEMS]:
                if not isinstance(raw_item, dict):
                    continue
                attempt_number = max(0, self._coerce_int(raw_item.get("attempt_number"), default=0))
                execution_mode = self._clean_optional(str(raw_item.get("execution_mode") or ""))
                if execution_mode not in _EXECUTION_MODES:
                    execution_mode = (
                        _EXECUTION_MODE_DEGRADED if bool(raw_item.get("degraded_mode")) else _EXECUTION_MODE_FULL
                    )
                provider_call_type = self._clean_optional(str(raw_item.get("provider_call_type") or ""))
                if provider_call_type not in _PROVIDER_CALL_TYPES:
                    provider_call_type = None
                degraded_mode = bool(raw_item.get("degraded_mode"))
                reduced_context_mode = bool(raw_item.get("reduced_context_mode"))
                requested_candidate_count = max(
                    1,
                    self._coerce_int(raw_item.get("requested_candidate_count"), default=1),
                )
                google_places_seed_count = max(
                    0,
                    self._coerce_int(raw_item.get("google_places_seed_count"), default=0),
                )
                outcome = self._clean_optional(str(raw_item.get("outcome") or "")) or "success"
                failure_kind = self._clean_optional(str(raw_item.get("failure_kind") or ""))
                if failure_kind not in {"timeout", "provider_request", "malformed_output", "unknown"}:
                    failure_kind = None
                malformed_output_reason = self._clean_optional(str(raw_item.get("malformed_output_reason") or ""))
                if malformed_output_reason and len(malformed_output_reason) > 64:
                    malformed_output_reason = malformed_output_reason[:64]
                request_duration_ms: int | None = None
                timeout_seconds: int | None = None
                max_attempts: int | None = None
                try:
                    if raw_item.get("request_duration_ms") is not None:
                        request_duration_ms = max(0, int(raw_item.get("request_duration_ms")))
                except (TypeError, ValueError):
                    request_duration_ms = None
                try:
                    if raw_item.get("timeout_seconds") is not None:
                        timeout_seconds = max(1, int(raw_item.get("timeout_seconds")))
                except (TypeError, ValueError):
                    timeout_seconds = None
                try:
                    if raw_item.get("max_attempts") is not None:
                        max_attempts = max(1, int(raw_item.get("max_attempts")))
                except (TypeError, ValueError):
                    max_attempts = None
                web_search_enabled = raw_item.get("web_search_enabled")
                if not isinstance(web_search_enabled, bool):
                    web_search_enabled = None
                prompt_total_chars: int | None = None
                context_json_chars: int | None = None
                user_prompt_chars: int | None = None
                try:
                    if raw_item.get("prompt_total_chars") is not None:
                        prompt_total_chars = max(0, int(raw_item.get("prompt_total_chars")))
                except (TypeError, ValueError):
                    prompt_total_chars = None
                try:
                    if raw_item.get("context_json_chars") is not None:
                        context_json_chars = max(0, int(raw_item.get("context_json_chars")))
                except (TypeError, ValueError):
                    context_json_chars = None
                try:
                    if raw_item.get("user_prompt_chars") is not None:
                        user_prompt_chars = max(0, int(raw_item.get("user_prompt_chars")))
                except (TypeError, ValueError):
                    user_prompt_chars = None
                prompt_size_risk = self._clean_optional(str(raw_item.get("prompt_size_risk") or ""))
                if prompt_size_risk not in {"normal", "elevated", "high"}:
                    prompt_size_risk = None
                timeout_type = self._clean_optional(str(raw_item.get("timeout_type") or ""))
                if timeout_type not in _TIMEOUT_TYPE_VALUES:
                    timeout_type = None
                recovered_after_timeout = raw_item.get("recovered_after_timeout")
                if not isinstance(recovered_after_timeout, bool):
                    recovered_after_timeout = None
                recovery_path = self._clean_optional(str(raw_item.get("recovery_path") or ""))
                if recovery_path not in _TIMEOUT_RECOVERY_PATHS:
                    recovery_path = None
                final_outcome = self._clean_optional(str(raw_item.get("final_outcome") or ""))
                if final_outcome not in _TIMEOUT_FINAL_OUTCOMES:
                    final_outcome = None
                endpoint_path = self._clean_optional(str(raw_item.get("endpoint_path") or ""))
                search_escalation_triggered = bool(raw_item.get("search_escalation_triggered"))
                escalation_reason = self._clean_optional(str(raw_item.get("escalation_reason") or ""))
                if escalation_reason and len(escalation_reason) > 64:
                    escalation_reason = escalation_reason[:64]
                provider_attempts.append(
                    SEOCompetitorProfileProviderAttemptDebug(
                        attempt_number=attempt_number,
                        execution_mode=execution_mode,
                        provider_call_type=provider_call_type,
                        degraded_mode=degraded_mode,
                        reduced_context_mode=reduced_context_mode,
                        requested_candidate_count=requested_candidate_count,
                        outcome=outcome,
                        failure_kind=failure_kind,
                        malformed_output_reason=malformed_output_reason,
                        request_duration_ms=request_duration_ms,
                        timeout_seconds=timeout_seconds,
                        web_search_enabled=web_search_enabled,
                        prompt_size_risk=prompt_size_risk,
                        prompt_total_chars=prompt_total_chars,
                        context_json_chars=context_json_chars,
                        user_prompt_chars=user_prompt_chars,
                        endpoint_path=endpoint_path,
                        max_attempts=max_attempts,
                        timeout_type=timeout_type,
                        recovered_after_timeout=recovered_after_timeout,
                        recovery_path=recovery_path,
                        final_outcome=final_outcome,
                        search_escalation_triggered=search_escalation_triggered,
                        escalation_reason=escalation_reason,
                        google_places_seed_count=google_places_seed_count,
                    )
                )

        raw_attempt_count = parsed.get(_PROVIDER_ATTEMPT_COUNT_KEY)
        try:
            provider_attempt_count = max(0, int(raw_attempt_count))
        except (TypeError, ValueError):
            provider_attempt_count = len(provider_attempts)
        provider_attempt_count = max(provider_attempt_count, len(provider_attempts))
        provider_degraded_retry_used = bool(parsed.get(_PROVIDER_DEGRADED_RETRY_USED_KEY))
        if not provider_degraded_retry_used:
            provider_degraded_retry_used = any(item.degraded_mode for item in provider_attempts)
        return provider_attempt_count, provider_degraded_retry_used, provider_attempts

    def _extract_schema_repair_flag_from_raw_output(self, raw_output: str | None) -> bool:
        if not raw_output:
            return False
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(parsed, dict):
            return False
        raw_summary = parsed.get(_SCHEMA_DIAGNOSTICS_SUMMARY_KEY)
        if not isinstance(raw_summary, dict):
            invalid_candidate_count = max(0, self._coerce_int(parsed.get("invalid_candidate_count"), default=0))
            invalid_field_type_count = max(0, self._coerce_int(parsed.get("invalid_field_type_count"), default=0))
            return bool(invalid_candidate_count > 0 or invalid_field_type_count > 0)
        if bool(raw_summary.get("had_schema_repair_or_discard")):
            return True
        invalid_candidate_count = max(0, self._coerce_int(raw_summary.get("invalid_candidate_count"), default=0))
        invalid_field_type_count = max(0, self._coerce_int(raw_summary.get("invalid_field_type_count"), default=0))
        return bool(invalid_candidate_count > 0 or invalid_field_type_count > 0)

    def _build_operator_outcome_summary(
        self,
        *,
        run: SEOCompetitorProfileGenerationRun,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug],
        had_schema_repair_or_discard: bool,
    ) -> SEOCompetitorProfileOutcomeSummary | None:
        if run.status not in {"completed", "failed"}:
            return None

        used_synthetic_fallback = any(
            (item.recovery_path == _SYNTHETIC_FALLBACK_RECOVERY_PATH or item.execution_mode == _EXECUTION_MODE_FALLBACK)
            for item in provider_attempts
        )
        used_timeout_recovery = any(item.recovered_after_timeout is True for item in provider_attempts)
        if not used_timeout_recovery:
            timeout_observed = any(item.failure_kind == "timeout" for item in provider_attempts)
            successful_outcome_observed = any(
                (item.final_outcome in {"success", "degraded_success"} or (item.outcome or "").lower() == "success")
                for item in provider_attempts
            )
            used_timeout_recovery = bool(timeout_observed and successful_outcome_observed and run.status == "completed")

        used_provider_recovery = bool(
            run.status == "completed"
            and any(item.failure_kind for item in provider_attempts)
            and any((item.outcome or "").lower() == "success" for item in provider_attempts)
        )
        used_google_places_seeds = any(item.google_places_seed_count > 0 for item in provider_attempts)

        if run.status == "failed":
            status_level = _OUTCOME_STATUS_FAILED
            message = "Competitor generation failed. Start a new run to continue."
        elif used_synthetic_fallback:
            status_level = _OUTCOME_STATUS_DEGRADED
            message = "Fallback placeholders were generated from local context. " "Review and confirm before accepting."
        elif used_provider_recovery or used_timeout_recovery:
            status_level = _OUTCOME_STATUS_RECOVERED
            message = "Competitor generation recovered after provider instability."
        else:
            status_level = _OUTCOME_STATUS_NORMAL
            message = "Competitor generation completed normally with provider output."

        return SEOCompetitorProfileOutcomeSummary(
            status_level=status_level,
            message=message,
            used_synthetic_fallback=used_synthetic_fallback,
            used_timeout_recovery=used_timeout_recovery,
            had_schema_repair_or_discard=bool(had_schema_repair_or_discard),
            used_google_places_seeds=used_google_places_seeds,
        )

    def _embed_competitor_debug_in_raw_output(
        self,
        *,
        raw_output: str | None,
        rejected_candidates: list[SEOCompetitorProfileRejectedCandidateDebug],
        tuning_rejected_candidates: list[SEOCompetitorProfileTuningRejectedCandidateDebug],
        tuning_rejection_reason_counts: dict[str, int],
        candidate_pipeline_summary: SEOCompetitorProfileCandidatePipelineSummary | None,
        provider_attempts: list[SEOCompetitorProfileProviderAttemptDebug] | None = None,
        schema_had_repair_or_discard: bool | None = None,
        schema_invalid_candidate_count: int | None = None,
        schema_invalid_field_type_count: int | None = None,
    ) -> str | None:
        serialized_provider_attempts = self._serialize_provider_attempts_for_debug(provider_attempts)
        if (
            not rejected_candidates
            and not tuning_rejected_candidates
            and not any(value > 0 for value in tuning_rejection_reason_counts.values())
            and candidate_pipeline_summary is None
            and not serialized_provider_attempts
            and schema_had_repair_or_discard is None
            and schema_invalid_candidate_count is None
            and schema_invalid_field_type_count is None
        ):
            return raw_output
        if raw_output:
            try:
                parsed = json.loads(raw_output)
            except (TypeError, ValueError, json.JSONDecodeError):
                return raw_output
            if not isinstance(parsed, dict):
                return raw_output
        else:
            parsed = {}

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

        normalized_reason_counts = self._normalize_tuning_rejection_reason_counts(tuning_rejection_reason_counts)
        if any(value > 0 for value in normalized_reason_counts.values()):
            parsed[_TUNING_REJECTION_REASON_COUNTS_KEY] = normalized_reason_counts
        if serialized_provider_attempts:
            parsed[_PROVIDER_ATTEMPT_COUNT_KEY] = max(0, len(provider_attempts or []))
            parsed[_PROVIDER_DEGRADED_RETRY_USED_KEY] = any(
                item["degraded_mode"] for item in serialized_provider_attempts
            )
            parsed[_PROVIDER_ATTEMPTS_DEBUG_KEY] = serialized_provider_attempts
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
                "relaxed_filtering_applied": bool(candidate_pipeline_summary.relaxed_filtering_applied),
            }
        if (
            schema_had_repair_or_discard is not None
            or schema_invalid_candidate_count is not None
            or schema_invalid_field_type_count is not None
        ):
            parsed[_SCHEMA_DIAGNOSTICS_SUMMARY_KEY] = {
                "had_schema_repair_or_discard": bool(schema_had_repair_or_discard),
                "invalid_candidate_count": max(0, self._coerce_int(schema_invalid_candidate_count, default=0)),
                "invalid_field_type_count": max(0, self._coerce_int(schema_invalid_field_type_count, default=0)),
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
            domain = self._clean_optional(str(raw_item.get("domain") or ""))
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
        relaxed_filtering_applied = bool(raw_summary.get("relaxed_filtering_applied"))

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
            and not relaxed_filtering_applied
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
            relaxed_filtering_applied=relaxed_filtering_applied,
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
            direction_correct = self._delta_direction(estimated_included_delta) == self._delta_direction(
                actual_included_delta
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
    def _coerce_float(value: object, *, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

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

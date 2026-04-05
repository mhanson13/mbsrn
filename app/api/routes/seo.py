from __future__ import annotations

from datetime import date, datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
import logging
import re
from urllib.parse import urlparse

from app.api.deps import (
    get_action_automation_binding_service,
    get_action_automation_execution_service,
    get_action_chain_activation_service,
    get_action_lineage_service,
    TenantContext,
    SEOCompetitorProfileGenerationRunExecutor,
    get_seo_audit_repository,
    get_seo_audit_service,
    get_seo_automation_service,
    get_seo_competitor_comparison_service,
    get_seo_competitor_profile_generation_repository,
    get_seo_competitor_profile_generation_run_executor,
    get_seo_competitor_profile_generation_service,
    get_seo_competitor_repository,
    get_seo_competitor_summary_service,
    get_seo_recommendation_narrative_service,
    get_seo_competitor_service,
    get_seo_recommendation_service,
    get_seo_analytics_service,
    get_seo_site_service,
    get_seo_summary_service,
    require_admin_rate_limit,
    require_credential_manager_principal,
    get_tenant_context,
    resolve_tenant_business_id,
)
from app.models.principal import Principal, PrincipalRole
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.schemas.seo_audit import (
    SEOAuditFindingListResponse,
    SEOAuditFindingRead,
    SEOAuditReportRead,
    SEOAuditReportSiteRead,
    SEOAuditRunCreateRequest,
    SEOAuditRunListResponse,
    SEOAuditRunRead,
    SEOAuditRunSummaryRead,
)
from app.schemas.seo_site import (
    SEOSiteAdminUpdateRequest,
    SEOSiteCreateRequest,
    SEOSiteListResponse,
    SEOSiteRead,
    SEOSiteUpdateRequest,
)
from app.schemas.seo_competitor import (
    SEOCompetitorProfileCandidatePipelineSummaryRead,
    SEOCompetitorComparisonFindingListResponse,
    SEOCompetitorComparisonFindingRead,
    SEOCompetitorComparisonMetricRollupRead,
    SEOCompetitorComparisonReportRead,
    SEOCompetitorComparisonSummaryListResponse,
    SEOCompetitorComparisonSummaryRead,
    SEOCompetitorComparisonRunRollupsRead,
    SEOCompetitorComparisonRunCreateRequest,
    SEOCompetitorComparisonRunSiteCreateRequest,
    SEOCompetitorComparisonRunListResponse,
    SEOCompetitorComparisonRunRead,
    SEOCompetitorProfileDraftAcceptRequest,
    SEOCompetitorProfileDraftEditRequest,
    SEOCompetitorProfileDraftRead,
    SEOCompetitorProfileDraftRejectRequest,
    SEOCompetitorProfileGenerationRunCreateRequest,
    SEOCompetitorProfileGenerationRunDetailRead,
    SEOCompetitorProfileGenerationRunListResponse,
    SEOCompetitorProfileGenerationObservabilitySummaryRead,
    SEOCompetitorProfileGenerationRunRead,
    SEOCompetitorProfileOutcomeSummaryRead,
    SEOCompetitorProfileRejectedCandidateRead,
    SEOCompetitorProfileTuningRejectedCandidateRead,
    SEOCompetitorDomainCreateRequest,
    SEOCompetitorDomainListResponse,
    SEOCompetitorDomainRead,
    SEOCompetitorSetCreateRequest,
    SEOCompetitorSetListResponse,
    SEOCompetitorSetRead,
    SEOCompetitorSetUpdateRequest,
    SEOCompetitorSnapshotRunCreateRequest,
    SEOCompetitorSnapshotPageListResponse,
    SEOCompetitorSnapshotPageRead,
    SEOCompetitorSnapshotRunListResponse,
    SEOCompetitorSnapshotRunRead,
)
from app.schemas.ai_prompt import build_ai_prompt_preview_read
from app.schemas.action_chaining import (
    ActionLineageResponse,
    BindActionAutomationRequest,
    BoundActionAutomationRead,
    NextActionDraft,
    RequestedActionAutomationExecutionRead,
)
from app.schemas.seo_recommendation import (
    SEOCompetitorContextHealthCheckRead,
    SEOCompetitorContextHealthRead,
    SEORecommendationActionDeltaRead,
    SEORecommendationCompetitorEvidenceLinkRead,
    SEORecommendationEEATCategory,
    SEORecommendationEEATGapSummaryRead,
    SEORecommendationAnalysisFreshnessRead,
    SEORecommendationApplyOutcomeRead,
    SEORecommendationBacklogRead,
    SEORecommendationFilteredSummary,
    SEORecommendationListQuery,
    SEORecommendationListResponse,
    SEORecommendationOrderingExplanationRead,
    SEORecommendationPriorityRead,
    SEORecommendationStartHereRead,
    SEORecommendationMeasurementContextRead,
    SEORecommendationMeasurementDeltaSummaryRead,
    SEORecommendationMeasurementMetricWindowRead,
    SEORecommendationMeasurementWindowSummaryRead,
    SEORecommendationSearchConsoleContextRead,
    SEORecommendationSearchConsoleDeltaSummaryRead,
    SEORecommendationSearchConsoleTopQueryRead,
    SEORecommendationSearchConsoleWindowSummaryRead,
    SEORecommendationEffectivenessContextRead,
    SEORecommendationThemeGroupRead,
    SEOWorkspaceSectionFreshnessRead,
    SEORecommendationWorkspaceTrustSummaryRead,
    SEORecommendationWorkspaceSummaryRead,
    SEORecommendationTuningImpactPreviewRead,
    SEORecommendationTuningImpactPreviewRequest,
    SEORecommendationPrioritizedReportRead,
    SEORecommendationRead,
    SEORecommendationNarrativeListResponse,
    SEORecommendationNarrativeRead,
    SEORecommendationRunCreateRequest,
    SEORecommendationRunListResponse,
    SEORecommendationRunRead,
    SEORecommendationRunReportRead,
    SEORecommendationTuningSuggestionRead,
    SEORecommendationWorkflowUpdateRequest,
    format_recommendation_theme_label,
    infer_eeat_categories_from_signals,
)
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.schemas.seo_automation import (
    SEOAutomationConfigPatchRequest,
    SEOAutomationConfigRead,
    SEOAutomationConfigUpsertRequest,
    SEOAutomationRunListResponse,
    SEOAutomationRunRead,
    SEOAutomationStatusRead,
)
from app.services.seo_audit import SEOAuditNotFoundError, SEOAuditService, SEOAuditValidationError
from app.services.seo_automation import (
    SEOAutomationConflictError,
    SEOAutomationNotFoundError,
    SEOAutomationService,
    SEOAutomationValidationError,
)
from app.services.seo_competitor_comparison import (
    SEOCompetitorComparisonNotFoundError,
    SEOCompetitorComparisonService,
    SEOCompetitorComparisonValidationError,
)
from app.services.seo_competitor_profile_generation import (
    SEOCompetitorProfileGenerationNotFoundError,
    SEOCompetitorProfileGenerationService,
    SEOCompetitorProfileGenerationValidationError,
)
from app.services.seo_competitor_summary import (
    SEOCompetitorSummaryNotFoundError,
    SEOCompetitorSummaryService,
    SEOCompetitorSummaryValidationError,
)
from app.services.seo_recommendations import (
    SEORecommendationNotFoundError,
    SEORecommendationService,
    SEORecommendationValidationError,
    classify_competitor_evidence_link,
)
from app.services.action_chain_activation_service import (
    ActionChainActivationService,
    SEOActionChainActivationValidationError,
    SEOActionChainDraftNotFoundError,
)
from app.services.action_automation_binding_service import (
    ActionAutomationBindingService,
    SEOActionAutomationBindingConflictError,
    SEOActionAutomationBindingNotFoundError,
    SEOActionAutomationBindingValidationError,
)
from app.services.action_automation_execution_service import (
    ActionAutomationExecutionService,
    SEOActionAutomationExecutionNotFoundError,
    SEOActionAutomationExecutionValidationError,
)
from app.services.action_lineage_service import ActionLineageService
from app.services.seo_recommendation_narratives import (
    SEORecommendationNarrativeNotFoundError,
    SEORecommendationNarrativeService,
    SEORecommendationNarrativeValidationError,
)
from app.services.seo_competitors import (
    SEOCompetitorNotFoundError,
    SEOCompetitorService,
    SEOCompetitorValidationError,
)
from app.services.seo_sites import (
    SEOSiteNotFoundError,
    SEOSiteService,
    SEOSiteValidationError,
    build_location_context,
)
from app.services.seo_summary import SEOSummaryNotFoundError, SEOSummaryService, SEOSummaryValidationError
from app.services.seo_analytics import SEOAnalyticsService
from app.schemas.seo_summary import SEOAuditSummaryRead
from app.schemas.seo_analytics import (
    SEOAnalyticsSiteSummaryRead,
    SEOSearchConsoleSiteSummaryRead,
)

router = APIRouter(prefix="/api/businesses/{business_id}/seo", tags=["seo"])
router_v1 = APIRouter(prefix="/api/v1/businesses/{business_id}/seo", tags=["seo"])
_WORKSPACE_MAX_TUNING_SUGGESTIONS = 4
_WORKSPACE_ALLOWED_TUNING_SETTINGS = {
    "competitor_candidate_min_relevance_score",
    "competitor_candidate_big_box_penalty",
    "competitor_candidate_directory_penalty",
    "competitor_candidate_local_alignment_bonus",
}
_WORKSPACE_TUNING_SETTING_ORDER = (
    "competitor_candidate_min_relevance_score",
    "competitor_candidate_big_box_penalty",
    "competitor_candidate_directory_penalty",
    "competitor_candidate_local_alignment_bonus",
)
_WORKSPACE_ALLOWED_TUNING_CONFIDENCE = {"low", "medium", "high"}
_WORKSPACE_SETTING_LABELS = {
    "competitor_candidate_min_relevance_score": "Minimum relevance score",
    "competitor_candidate_big_box_penalty": "Big-box mismatch penalty",
    "competitor_candidate_directory_penalty": "Directory/aggregator penalty",
    "competitor_candidate_local_alignment_bonus": "Local alignment bonus",
}
_WORKSPACE_APPLY_OUTCOME_LABEL_MAX_CHARS = 180
_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS = 260
_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS = 220
_WORKSPACE_COMPETITOR_EVIDENCE_LINK_MAX_ITEMS = 3
_WORKSPACE_COMPETITOR_EVIDENCE_TEXT_MAX_CHARS = 220
_WORKSPACE_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS = 240
_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS = 220
_WORKSPACE_COMPETITOR_VERIFICATION_STATUS_VERIFIED = "verified"
_WORKSPACE_COMPETITOR_VERIFICATION_STATUS_UNVERIFIED = "unverified"
_WORKSPACE_EEAT_GAP_MAX_SIGNALS = 6
_WORKSPACE_EEAT_GAP_SIGNAL_MAX_CHARS = 140
_WORKSPACE_COMPETITOR_CONTEXT_HEALTH_DETAIL_MAX_CHARS = 220
_WORKSPACE_RECOMMENDATION_THEME_ORDER = (
    "trust_and_legitimacy",
    "experience_and_proof",
    "authority_and_visibility",
    "expertise_and_process",
    "general_site_improvement",
)
_WORKSPACE_LOCATION_CONTEXT_MAX_CHARS = 220
_WORKSPACE_PRIMARY_LOCATION_MAX_CHARS = 255
_WORKSPACE_START_HERE_REASON_MAX_CHARS = 320
_WORKSPACE_CONTEXT_HEALTH_CHECK_ORDER = (
    "location_context",
    "industry_context",
    "service_focus",
    "target_customer_context",
)
_WORKSPACE_CONTEXT_HEALTH_CHECK_LABELS = {
    "location_context": "Location context",
    "industry_context": "Industry context",
    "service_focus": "Service focus",
    "target_customer_context": "Target customer context",
}
_WORKSPACE_CONTEXT_HEALTH_SERVICE_FOCUS_THIN_TERMS = {
    "service",
    "services",
    "home service",
    "home services",
    "business",
    "company",
    "local services",
}
_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_ITEMS = 3
_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_CHARS = 120
_WORKSPACE_RECOMMENDATION_TARGET_HINT_TOKEN_NOISE = {
    "home",
    "index",
    "page",
    "pages",
}
_WORKSPACE_RECOMMENDATION_TARGET_CONTACT_ABOUT_KEYWORDS = (
    "about",
    "contact",
    "team",
    "license",
    "licenses",
    "insurance",
    "review",
    "reviews",
    "testimonial",
    "testimonials",
    "bbb",
)
_WORKSPACE_RECOMMENDATION_TARGET_SERVICE_KEYWORDS = (
    "service",
    "services",
    "installation",
    "install",
    "repair",
    "remodel",
    "renovation",
    "contractor",
    "construction",
    "flooring",
    "roofing",
    "plumbing",
    "electrical",
    "hvac",
)
_WORKSPACE_RECOMMENDATION_TARGET_LOCATION_KEYWORDS = (
    "location",
    "locations",
    "area",
    "areas",
    "city",
    "cities",
    "service area",
    "service areas",
    "areas we serve",
    "cities we serve",
)
_WORKSPACE_RECOMMENDATION_TARGET_ALLOWED_CONTEXTS = {
    "homepage",
    "service_pages",
    "contact_about",
    "location_pages",
    "sitewide",
    "general",
}
logger = logging.getLogger(__name__)


def _assert_site_match(*, expected_site_id: str, actual_site_id: str, detail: str) -> None:
    if actual_site_id != expected_site_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _summarize_recommendation_items(
    items: list[SEORecommendationRead],
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_effort_bucket: dict[str, int] = {}
    by_priority_band: dict[str, int] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_category[item.category] = by_category.get(item.category, 0) + 1
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        by_effort_bucket[item.effort_bucket] = by_effort_bucket.get(item.effort_bucket, 0) + 1
        by_priority_band[item.priority_band] = by_priority_band.get(item.priority_band, 0) + 1
    return (
        dict(sorted(by_status.items())),
        dict(sorted(by_category.items())),
        dict(sorted(by_severity.items())),
        dict(sorted(by_effort_bucket.items())),
        dict(sorted(by_priority_band.items())),
    )


def _attach_action_lineage_to_recommendations(
    *,
    recommendations: list[SEORecommendationRead],
    business_id: str,
    site_id: str,
    action_lineage_service: ActionLineageService,
) -> list[SEORecommendationRead]:
    if not recommendations:
        return recommendations
    source_action_ids = [recommendation.id for recommendation in recommendations if recommendation.id]
    if not source_action_ids:
        return recommendations
    lineage_by_source_action_id = action_lineage_service.list_action_lineage_for_source_actions(
        business_id=business_id,
        site_id=site_id,
        source_action_ids=source_action_ids,
    )
    return [
        recommendation.model_copy(
            update={
                "action_lineage": lineage_by_source_action_id.get(recommendation.id),
            }
        )
        for recommendation in recommendations
    ]


def _to_recommendation_measurement_window(
    *,
    current: int,
    previous: int,
    delta_absolute: int,
    delta_percent: float | None,
) -> SEORecommendationMeasurementMetricWindowRead:
    return SEORecommendationMeasurementMetricWindowRead(
        current=max(0, int(current)),
        previous=max(0, int(previous)),
        delta_absolute=int(delta_absolute),
        delta_percent=delta_percent,
    )


def _to_recommendation_measurement_window_summary(
    *,
    start_date: date,
    end_date: date,
    users: int,
    sessions: int,
    pageviews: int,
) -> SEORecommendationMeasurementWindowSummaryRead:
    return SEORecommendationMeasurementWindowSummaryRead(
        start_date=start_date,
        end_date=end_date,
        users=max(0, int(users)),
        sessions=max(0, int(sessions)),
        pageviews=max(0, int(pageviews)),
    )


def _to_recommendation_measurement_delta_summary(
    *,
    before_window: SEORecommendationMeasurementWindowSummaryRead,
    after_window: SEORecommendationMeasurementWindowSummaryRead,
) -> SEORecommendationMeasurementDeltaSummaryRead:
    users_delta_absolute = int(after_window.users) - int(before_window.users)
    sessions_delta_absolute = int(after_window.sessions) - int(before_window.sessions)
    pageviews_delta_absolute = int(after_window.pageviews) - int(before_window.pageviews)

    def _delta_percent(current: int, previous: int) -> float | None:
        if previous <= 0:
            return None if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 2)

    return SEORecommendationMeasurementDeltaSummaryRead(
        users_delta_absolute=users_delta_absolute,
        users_delta_percent=_delta_percent(after_window.users, before_window.users),
        sessions_delta_absolute=sessions_delta_absolute,
        sessions_delta_percent=_delta_percent(after_window.sessions, before_window.sessions),
        pageviews_delta_absolute=pageviews_delta_absolute,
        pageviews_delta_percent=_delta_percent(after_window.pageviews, before_window.pageviews),
    )


def _to_recommendation_search_console_window_summary(
    *,
    start_date: date,
    end_date: date,
    clicks: int,
    impressions: int,
    ctr: float,
    average_position: float,
) -> SEORecommendationSearchConsoleWindowSummaryRead:
    return SEORecommendationSearchConsoleWindowSummaryRead(
        start_date=start_date,
        end_date=end_date,
        clicks=max(0, int(clicks)),
        impressions=max(0, int(impressions)),
        ctr=round(float(ctr), 4),
        average_position=round(float(average_position), 4),
    )


def _to_recommendation_search_console_delta_summary(
    *,
    before_window: SEORecommendationSearchConsoleWindowSummaryRead,
    after_window: SEORecommendationSearchConsoleWindowSummaryRead,
) -> SEORecommendationSearchConsoleDeltaSummaryRead:
    clicks_delta_absolute = int(after_window.clicks) - int(before_window.clicks)
    impressions_delta_absolute = int(after_window.impressions) - int(before_window.impressions)

    def _delta_percent(current: int, previous: int) -> float | None:
        if previous <= 0:
            return None if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 2)

    return SEORecommendationSearchConsoleDeltaSummaryRead(
        clicks_delta_absolute=clicks_delta_absolute,
        clicks_delta_percent=_delta_percent(after_window.clicks, before_window.clicks),
        impressions_delta_absolute=impressions_delta_absolute,
        impressions_delta_percent=_delta_percent(after_window.impressions, before_window.impressions),
        ctr_delta_absolute=round(float(after_window.ctr) - float(before_window.ctr), 4),
        average_position_delta_absolute=round(
            float(after_window.average_position) - float(before_window.average_position),
            4,
        ),
    )


def _derive_direction_from_percent(value: float | None) -> Literal["up", "down", "flat", "unknown"]:
    if value is None:
        return "unknown"
    if abs(value) < 3.0:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _derive_effectiveness_confidence(
    *,
    volume: int | None,
    delta_absolute: int | float | None,
    delta_percent: float | None,
    comparison_scope: Literal["page", "site"] | None,
    volume_moderate_threshold: int,
    volume_high_threshold: int,
    delta_absolute_moderate_threshold: float,
    delta_absolute_high_threshold: float,
    delta_percent_moderate_threshold: float,
    delta_percent_high_threshold: float,
) -> Literal["high", "moderate", "low"]:
    absolute_delta = abs(float(delta_absolute)) if delta_absolute is not None else 0.0
    percent_delta = abs(float(delta_percent)) if delta_percent is not None else 0.0

    # Low-volume windows are intentionally conservative to avoid noisy percent swings.
    low_volume = volume is not None and volume < volume_moderate_threshold
    if low_volume:
        has_minimum_absolute_change = absolute_delta >= delta_absolute_moderate_threshold
        has_material_percent_change = percent_delta >= delta_percent_high_threshold
        if not has_minimum_absolute_change or not has_material_percent_change:
            return "low"

    score = 0
    if volume is not None:
        if volume >= volume_high_threshold:
            score += 2
        elif volume >= volume_moderate_threshold:
            score += 1
    if absolute_delta >= delta_absolute_high_threshold or percent_delta >= delta_percent_high_threshold:
        score += 2
    elif absolute_delta >= delta_absolute_moderate_threshold or percent_delta >= delta_percent_moderate_threshold:
        score += 1
    if comparison_scope == "page":
        score += 1
    if low_volume and score >= 4:
        # Even strong directional movement on small samples should not be treated as high confidence.
        return "moderate"
    if score >= 4:
        return "high"
    if score >= 2:
        return "moderate"
    return "low"


def _confidence_rank(value: Literal["high", "moderate", "low"]) -> int:
    if value == "high":
        return 3
    if value == "moderate":
        return 2
    return 1


def _rank_to_confidence(value: int) -> Literal["high", "moderate", "low"]:
    if value >= 3:
        return "high"
    if value == 2:
        return "moderate"
    return "low"


def _build_effectiveness_summary(
    *,
    trend: Literal["improving", "flat", "declining", "insufficient_data"],
    confidence: Literal["high", "moderate", "low"],
    traffic_direction: Literal["up", "down", "flat", "unknown"],
    search_direction: Literal["up", "down", "flat", "unknown"],
) -> str:
    if trend == "insufficient_data":
        return "Insufficient directional measurement data is available since this recommendation."
    has_traffic = traffic_direction != "unknown"
    has_search = search_direction != "unknown"
    source_label = "Traffic and search visibility" if has_traffic and has_search else (
        "Traffic" if has_traffic else "Search visibility"
    )
    if trend == "improving":
        if confidence == "high":
            return f"{source_label} has improved since this recommendation."
        if confidence == "moderate":
            return f"{source_label} is trending up since this recommendation."
        return f"{source_label} appears to be improving, but signal strength is limited."
    if trend == "declining":
        if confidence == "high":
            return f"{source_label} has declined since this recommendation."
        if confidence == "moderate":
            return f"{source_label} is trending down since this recommendation."
        return f"{source_label} appears to be declining, but signal strength is limited."
    if has_traffic and has_search and traffic_direction != "flat" and search_direction != "flat":
        return "Traffic and search visibility are mixed, so overall directional impact is unclear."
    return f"{source_label} is mostly flat since this recommendation."


def _derive_effectiveness_context(
    *,
    traffic_context: SEORecommendationMeasurementContextRead | None,
    search_context: SEORecommendationSearchConsoleContextRead | None,
) -> SEORecommendationEffectivenessContextRead | None:
    traffic_direction = "unknown"
    traffic_confidence: Literal["high", "moderate", "low"] = "low"
    if (
        traffic_context is not None
        and traffic_context.measurement_status == "available"
        and traffic_context.delta_summary is not None
    ):
        sessions_delta_percent = traffic_context.delta_summary.sessions_delta_percent
        traffic_direction = _derive_direction_from_percent(sessions_delta_percent)
        traffic_volume = (
            traffic_context.after_window_summary.sessions
            if traffic_context.after_window_summary is not None
            else (traffic_context.sessions.current if traffic_context.sessions is not None else None)
        )
        traffic_confidence = _derive_effectiveness_confidence(
            volume=traffic_volume,
            delta_absolute=traffic_context.delta_summary.sessions_delta_absolute,
            delta_percent=sessions_delta_percent,
            comparison_scope=traffic_context.comparison_scope,
            volume_moderate_threshold=60,
            volume_high_threshold=160,
            delta_absolute_moderate_threshold=10.0,
            delta_absolute_high_threshold=30.0,
            delta_percent_moderate_threshold=5.0,
            delta_percent_high_threshold=12.0,
        )

    search_direction = "unknown"
    search_confidence: Literal["high", "moderate", "low"] = "low"
    if (
        search_context is not None
        and search_context.search_console_status == "available"
        and search_context.delta_summary is not None
    ):
        impressions_delta_percent = search_context.delta_summary.impressions_delta_percent
        search_direction = _derive_direction_from_percent(impressions_delta_percent)
        search_volume = (
            search_context.current_window_summary.impressions
            if search_context.current_window_summary is not None
            else None
        )
        search_confidence = _derive_effectiveness_confidence(
            volume=search_volume,
            delta_absolute=search_context.delta_summary.impressions_delta_absolute,
            delta_percent=impressions_delta_percent,
            comparison_scope=search_context.comparison_scope,
            volume_moderate_threshold=900,
            volume_high_threshold=2500,
            delta_absolute_moderate_threshold=100.0,
            delta_absolute_high_threshold=300.0,
            delta_percent_moderate_threshold=4.0,
            delta_percent_high_threshold=10.0,
        )

    has_traffic_signal = traffic_direction != "unknown"
    has_search_signal = search_direction != "unknown"
    if not has_traffic_signal and not has_search_signal:
        return SEORecommendationEffectivenessContextRead(
            effectiveness_status="insufficient",
            traffic_direction=traffic_direction,
            search_visibility_direction=search_direction,
            effectiveness_trend="insufficient_data",
            effectiveness_confidence="low",
            summary=_build_effectiveness_summary(
                trend="insufficient_data",
                confidence="low",
                traffic_direction=traffic_direction,
                search_direction=search_direction,
            ),
        )

    if has_traffic_signal and has_search_signal:
        status = "available"
        if traffic_direction == search_direction:
            if traffic_direction == "up":
                trend: Literal["improving", "flat", "declining", "insufficient_data"] = "improving"
            elif traffic_direction == "down":
                trend = "declining"
            else:
                trend = "flat"
            confidence = _rank_to_confidence(min(_confidence_rank(traffic_confidence), _confidence_rank(search_confidence)))
        elif traffic_direction == "flat" and search_direction in {"up", "down"}:
            trend = "improving" if search_direction == "up" else "declining"
            confidence = _rank_to_confidence(max(1, _confidence_rank(search_confidence) - 1))
        elif search_direction == "flat" and traffic_direction in {"up", "down"}:
            trend = "improving" if traffic_direction == "up" else "declining"
            confidence = _rank_to_confidence(max(1, _confidence_rank(traffic_confidence) - 1))
        else:
            trend = "flat"
            confidence = "low"
    else:
        status = "partial"
        if has_traffic_signal:
            trend = "improving" if traffic_direction == "up" else "declining" if traffic_direction == "down" else "flat"
            confidence = traffic_confidence
        else:
            trend = "improving" if search_direction == "up" else "declining" if search_direction == "down" else "flat"
            confidence = search_confidence

    if confidence == "low" and trend in {"improving", "declining"} and status == "available":
        # Mixed strength from multiple sources is treated conservatively.
        trend = "flat"

    summary = _build_effectiveness_summary(
        trend=trend,
        confidence=confidence,
        traffic_direction=traffic_direction,
        search_direction=search_direction,
    )

    return SEORecommendationEffectivenessContextRead(
        effectiveness_status=status,
        traffic_direction=traffic_direction,
        search_visibility_direction=search_direction,
        effectiveness_trend=trend,
        effectiveness_confidence=confidence,
        summary=summary,
    )


def _build_recommendation_measurement_context_by_id(
    *,
    recommendations: list[SEORecommendationRead],
    site_analytics_summary: SEOAnalyticsSiteSummaryRead,
    seo_analytics_service: SEOAnalyticsService,
    site_domain: str | None,
) -> dict[str, SEORecommendationMeasurementContextRead]:
    if not recommendations:
        return {}

    analytics_status = str(site_analytics_summary.status or "").strip().lower()
    if analytics_status in {"not_configured", "unavailable"}:
        if analytics_status == "not_configured":
            measurement_status: str = "not_configured"
        else:
            measurement_status = "unavailable"
        return {
            recommendation.id: SEORecommendationMeasurementContextRead(
                measurement_status=measurement_status,
            )
            for recommendation in recommendations
        }

    if not site_analytics_summary.available or not site_analytics_summary.top_pages_summary:
        return {
            recommendation.id: SEORecommendationMeasurementContextRead(
                measurement_status="unavailable",
            )
            for recommendation in recommendations
        }

    context_by_recommendation_id: dict[str, SEORecommendationMeasurementContextRead] = {}
    for recommendation in recommendations:
        matched_page = seo_analytics_service.match_recommendation_to_top_page(
            top_pages_summary=site_analytics_summary.top_pages_summary,
            recommendation_target_page_hints=recommendation.recommendation_target_page_hints,
            recommendation_target_context=recommendation.recommendation_target_context,
        )
        matched_page_path = matched_page.page_path if matched_page is not None else None
        comparison = seo_analytics_service.build_recommendation_before_after_comparison(
            site_domain=site_domain,
            recommendation_created_at=recommendation.created_at,
            page_path=matched_page_path,
        )

        if comparison is not None:
            before_window_summary = _to_recommendation_measurement_window_summary(
                start_date=comparison.before_window.start_date,
                end_date=comparison.before_window.end_date,
                users=comparison.before_window.users,
                sessions=comparison.before_window.sessions,
                pageviews=comparison.before_window.pageviews,
            )
            after_window_summary = _to_recommendation_measurement_window_summary(
                start_date=comparison.after_window.start_date,
                end_date=comparison.after_window.end_date,
                users=comparison.after_window.users,
                sessions=comparison.after_window.sessions,
                pageviews=comparison.after_window.pageviews,
            )
            delta_summary = _to_recommendation_measurement_delta_summary(
                before_window=before_window_summary,
                after_window=after_window_summary,
            )
            comparison_scope = "page" if comparison.comparison_scope == "page" else "site"
            context_by_recommendation_id[recommendation.id] = SEORecommendationMeasurementContextRead(
                measurement_status="available",
                matched_page_path=matched_page_path if comparison_scope == "page" else None,
                comparison_scope=comparison_scope,
                sessions=_to_recommendation_measurement_window(
                    current=after_window_summary.sessions,
                    previous=before_window_summary.sessions,
                    delta_absolute=after_window_summary.sessions - before_window_summary.sessions,
                    delta_percent=delta_summary.sessions_delta_percent,
                ),
                pageviews=_to_recommendation_measurement_window(
                    current=after_window_summary.pageviews,
                    previous=before_window_summary.pageviews,
                    delta_absolute=after_window_summary.pageviews - before_window_summary.pageviews,
                    delta_percent=delta_summary.pageviews_delta_percent,
                ),
                before_window_summary=before_window_summary,
                after_window_summary=after_window_summary,
                delta_summary=delta_summary,
            )
            continue

        if matched_page is not None:
            sessions_window = _to_recommendation_measurement_window(
                current=matched_page.sessions,
                previous=matched_page.sessions_previous,
                delta_absolute=matched_page.sessions_delta_absolute,
                delta_percent=matched_page.sessions_delta_percent,
            )
            pageviews_window = _to_recommendation_measurement_window(
                current=matched_page.pageviews,
                previous=matched_page.pageviews_previous,
                delta_absolute=matched_page.pageviews_delta_absolute,
                delta_percent=matched_page.pageviews_delta_percent,
            )
            context_by_recommendation_id[recommendation.id] = SEORecommendationMeasurementContextRead(
                measurement_status="available",
                matched_page_path=matched_page.page_path,
                comparison_scope="page",
                sessions=sessions_window,
                pageviews=pageviews_window,
            )
            continue

        site_metrics_summary = site_analytics_summary.site_metrics_summary
        if site_metrics_summary is not None:
            site_sessions_window = _to_recommendation_measurement_window(
                current=site_metrics_summary.sessions.current,
                previous=site_metrics_summary.sessions.previous,
                delta_absolute=site_metrics_summary.sessions.delta_absolute,
                delta_percent=site_metrics_summary.sessions.delta_percent,
            )
            site_pageviews_window = _to_recommendation_measurement_window(
                current=site_metrics_summary.pageviews.current,
                previous=site_metrics_summary.pageviews.previous,
                delta_absolute=site_metrics_summary.pageviews.delta_absolute,
                delta_percent=site_metrics_summary.pageviews.delta_percent,
            )
            context_by_recommendation_id[recommendation.id] = SEORecommendationMeasurementContextRead(
                measurement_status="available",
                matched_page_path=None,
                comparison_scope="site",
                sessions=site_sessions_window,
                pageviews=site_pageviews_window,
            )
            continue
        context_by_recommendation_id[recommendation.id] = SEORecommendationMeasurementContextRead(
            measurement_status="no_match",
        )
    return context_by_recommendation_id


def _build_recommendation_search_console_context_by_id(
    *,
    recommendations: list[SEORecommendationRead],
    search_console_site_summary: SEOSearchConsoleSiteSummaryRead,
    seo_analytics_service: SEOAnalyticsService,
    search_console_property_url: str | None,
    search_console_enabled: bool,
) -> dict[str, SEORecommendationSearchConsoleContextRead]:
    if not recommendations:
        return {}

    search_console_status = str(search_console_site_summary.status or "").strip().lower()
    if search_console_status in {"not_configured", "unavailable"}:
        status_value = "not_configured" if search_console_status == "not_configured" else "unavailable"
        return {
            recommendation.id: SEORecommendationSearchConsoleContextRead(
                search_console_status=status_value
            )
            for recommendation in recommendations
        }

    if not search_console_site_summary.available or not search_console_site_summary.top_pages_summary:
        return {
            recommendation.id: SEORecommendationSearchConsoleContextRead(
                search_console_status="unavailable"
            )
            for recommendation in recommendations
        }

    context_by_recommendation_id: dict[str, SEORecommendationSearchConsoleContextRead] = {}
    for recommendation in recommendations:
        matched_page = seo_analytics_service.match_recommendation_to_search_console_page(
            top_pages_summary=search_console_site_summary.top_pages_summary,
            recommendation_target_page_hints=recommendation.recommendation_target_page_hints,
            recommendation_target_context=recommendation.recommendation_target_context,
        )
        matched_page_path = matched_page.page_path if matched_page is not None else None
        comparison = seo_analytics_service.build_recommendation_search_console_before_after_comparison(
            search_console_property_url=search_console_property_url,
            search_console_enabled=search_console_enabled,
            recommendation_created_at=recommendation.created_at,
            page_path=matched_page_path,
        )
        if comparison is not None:
            before_window_summary = _to_recommendation_search_console_window_summary(
                start_date=comparison.before_window.start_date,
                end_date=comparison.before_window.end_date,
                clicks=comparison.before_window.clicks,
                impressions=comparison.before_window.impressions,
                ctr=comparison.before_window.ctr,
                average_position=comparison.before_window.average_position,
            )
            after_window_summary = _to_recommendation_search_console_window_summary(
                start_date=comparison.after_window.start_date,
                end_date=comparison.after_window.end_date,
                clicks=comparison.after_window.clicks,
                impressions=comparison.after_window.impressions,
                ctr=comparison.after_window.ctr,
                average_position=comparison.after_window.average_position,
            )
            delta_summary = _to_recommendation_search_console_delta_summary(
                before_window=before_window_summary,
                after_window=after_window_summary,
            )
            context_by_recommendation_id[recommendation.id] = SEORecommendationSearchConsoleContextRead(
                search_console_status="available",
                matched_page_path=matched_page_path if comparison.comparison_scope == "page" else None,
                comparison_scope=comparison.comparison_scope,
                current_window_summary=after_window_summary,
                previous_window_summary=before_window_summary,
                delta_summary=delta_summary,
                top_queries_summary=[
                    SEORecommendationSearchConsoleTopQueryRead.model_validate(query.model_dump())
                    for query in comparison.top_queries
                ],
            )
            continue

        if matched_page is not None:
            current_summary = _to_recommendation_search_console_window_summary(
                start_date=date.today(),
                end_date=date.today(),
                clicks=matched_page.clicks,
                impressions=matched_page.impressions,
                ctr=matched_page.ctr,
                average_position=matched_page.average_position,
            )
            previous_summary = _to_recommendation_search_console_window_summary(
                start_date=date.today(),
                end_date=date.today(),
                clicks=matched_page.clicks_previous,
                impressions=matched_page.impressions_previous,
                ctr=matched_page.ctr_previous,
                average_position=matched_page.average_position_previous,
            )
            context_by_recommendation_id[recommendation.id] = SEORecommendationSearchConsoleContextRead(
                search_console_status="available",
                matched_page_path=matched_page.page_path,
                comparison_scope="page",
                current_window_summary=current_summary,
                previous_window_summary=previous_summary,
                delta_summary=_to_recommendation_search_console_delta_summary(
                    before_window=previous_summary,
                    after_window=current_summary,
                ),
            )
            continue

        site_metrics_summary = search_console_site_summary.site_metrics_summary
        if site_metrics_summary is not None:
            current_summary = _to_recommendation_search_console_window_summary(
                start_date=site_metrics_summary.current_period_start,
                end_date=site_metrics_summary.current_period_end,
                clicks=site_metrics_summary.clicks.current,
                impressions=site_metrics_summary.impressions.current,
                ctr=site_metrics_summary.ctr_current,
                average_position=site_metrics_summary.average_position_current,
            )
            previous_summary = _to_recommendation_search_console_window_summary(
                start_date=site_metrics_summary.previous_period_start,
                end_date=site_metrics_summary.previous_period_end,
                clicks=site_metrics_summary.clicks.previous,
                impressions=site_metrics_summary.impressions.previous,
                ctr=site_metrics_summary.ctr_previous,
                average_position=site_metrics_summary.average_position_previous,
            )
            context_by_recommendation_id[recommendation.id] = SEORecommendationSearchConsoleContextRead(
                search_console_status="available",
                matched_page_path=None,
                comparison_scope="site",
                current_window_summary=current_summary,
                previous_window_summary=previous_summary,
                delta_summary=_to_recommendation_search_console_delta_summary(
                    before_window=previous_summary,
                    after_window=current_summary,
                ),
                top_queries_summary=[
                    SEORecommendationSearchConsoleTopQueryRead.model_validate(query.model_dump())
                    for query in search_console_site_summary.top_queries_summary[:3]
                ],
            )
            continue

        context_by_recommendation_id[recommendation.id] = SEORecommendationSearchConsoleContextRead(
            search_console_status="no_match"
        )
    return context_by_recommendation_id


def _attach_measurement_context_to_recommendations(
    *,
    recommendations: list[SEORecommendationRead],
    site_analytics_summary: SEOAnalyticsSiteSummaryRead,
    search_console_site_summary: SEOSearchConsoleSiteSummaryRead,
    seo_analytics_service: SEOAnalyticsService,
    site_domain: str | None,
    search_console_property_url: str | None,
    search_console_enabled: bool,
) -> list[SEORecommendationRead]:
    if not recommendations:
        return recommendations
    context_by_recommendation_id = _build_recommendation_measurement_context_by_id(
        recommendations=recommendations,
        site_analytics_summary=site_analytics_summary,
        seo_analytics_service=seo_analytics_service,
        site_domain=site_domain,
    )
    search_console_context_by_recommendation_id = _build_recommendation_search_console_context_by_id(
        recommendations=recommendations,
        search_console_site_summary=search_console_site_summary,
        seo_analytics_service=seo_analytics_service,
        search_console_property_url=search_console_property_url,
        search_console_enabled=search_console_enabled,
    )
    return [
        recommendation.model_copy(
            update={
                "recommendation_measurement_context": context_by_recommendation_id.get(recommendation.id),
                "recommendation_search_console_context": search_console_context_by_recommendation_id.get(
                    recommendation.id
                ),
                "recommendation_effectiveness_context": _derive_effectiveness_context(
                    traffic_context=context_by_recommendation_id.get(recommendation.id),
                    search_context=search_console_context_by_recommendation_id.get(recommendation.id),
                ),
            }
        )
        for recommendation in recommendations
    ]


def _extract_workspace_tuning_suggestions(
    *,
    sections_json: dict[str, object] | None,
    recommendation_ids: set[str],
) -> list[SEORecommendationTuningSuggestionRead]:
    if not sections_json or not isinstance(sections_json, dict):
        return []
    raw_items = sections_json.get("tuning_suggestions")
    if not isinstance(raw_items, list):
        return []

    suggestions: list[SEORecommendationTuningSuggestionRead] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        setting = str(raw_item.get("setting", "") or "").strip()
        confidence = str(raw_item.get("confidence", "") or "").strip().lower()
        reason = str(raw_item.get("reason", "") or "").strip()
        if setting not in _WORKSPACE_ALLOWED_TUNING_SETTINGS:
            continue
        if confidence not in _WORKSPACE_ALLOWED_TUNING_CONFIDENCE:
            continue
        if not reason:
            continue
        try:
            current_value = int(raw_item.get("current_value"))
            recommended_value = int(raw_item.get("recommended_value"))
        except (TypeError, ValueError):
            continue

        linked_ids_raw = raw_item.get("linked_recommendation_ids")
        if not isinstance(linked_ids_raw, list):
            continue
        linked_ids: list[str] = []
        for linked_id in linked_ids_raw:
            cleaned_id = str(linked_id or "").strip()
            if cleaned_id and cleaned_id in recommendation_ids:
                linked_ids.append(cleaned_id)
        if not linked_ids:
            continue
        deduped_linked_ids = list(dict.fromkeys(linked_ids))

        try:
            parsed = SEORecommendationTuningSuggestionRead.model_validate(
                {
                    "setting": setting,
                    "current_value": current_value,
                    "recommended_value": recommended_value,
                    "reason": reason,
                    "linked_recommendation_ids": deduped_linked_ids,
                    "confidence": confidence,
                }
            )
        except Exception:  # noqa: BLE001
            continue
        suggestions.append(parsed)
        if len(suggestions) >= _WORKSPACE_MAX_TUNING_SUGGESTIONS:
            break
    return suggestions


def _compact_workspace_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    compacted = " ".join(str(value).split()).strip()
    if not compacted:
        return None
    if len(compacted) <= max_length:
        return compacted
    if max_length <= 1:
        return compacted[:max_length]
    return f"{compacted[: max_length - 1].rstrip()}…"


def _normalize_workspace_location_context_strength(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"strong", "weak"}:
        return normalized
    return "unknown"


def _normalize_workspace_location_context_source(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"explicit_location", "service_area", "zip_capture", "fallback"}:
        return normalized
    return None


def _normalize_workspace_industry_context_strength(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"strong", "weak"}:
        return normalized
    return "unknown"


def _normalize_workspace_service_focus_terms(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for item in value:
        compacted = _compact_workspace_text(item, max_length=64)
        if compacted is None:
            continue
        key = compacted.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(compacted)
        if len(terms) >= 8:
            break
    return terms


def _is_meaningful_workspace_service_focus_term(term: str) -> bool:
    normalized = " ".join(term.lower().split())
    if not normalized:
        return False
    if normalized in _WORKSPACE_CONTEXT_HEALTH_SERVICE_FOCUS_THIN_TERMS:
        return False
    if normalized.endswith(".com"):
        return False
    alpha_count = sum(1 for char in normalized if char.isalpha())
    return alpha_count >= 3


def _workspace_location_source_label(value: str | None) -> str | None:
    if value == "explicit_location":
        return "explicit location"
    if value == "service_area":
        return "service area"
    if value == "zip_capture":
        return "ZIP capture"
    if value == "fallback":
        return "fallback"
    return None


def _build_workspace_competitor_context_health(
    *,
    site_location_context_strength: str,
    site_location_context_source: str | None,
    trusted_site_context: dict[str, object],
) -> SEOCompetitorContextHealthRead:
    checks_payload: list[dict[str, str]] = []

    location_strong = site_location_context_strength == "strong"
    location_source_label = _workspace_location_source_label(site_location_context_source)
    if location_strong:
        location_detail = (
            f"{location_source_label.title()} is available for local competitor matching."
            if location_source_label
            else "Location context is available for local competitor matching."
        )
    else:
        location_detail = "Location context is weak or missing; local competitor matching may be conservative."
    checks_payload.append(
        {
            "key": "location_context",
            "label": _WORKSPACE_CONTEXT_HEALTH_CHECK_LABELS["location_context"],
            "status": "strong" if location_strong else "weak",
            "detail": _compact_workspace_text(
                location_detail,
                max_length=_WORKSPACE_COMPETITOR_CONTEXT_HEALTH_DETAIL_MAX_CHARS,
            )
            or location_detail,
        }
    )

    industry_context = _compact_workspace_text(
        trusted_site_context.get("site_industry_context"),
        max_length=120,
    )
    industry_strength = _normalize_workspace_industry_context_strength(
        trusted_site_context.get("site_industry_context_strength"),
    )
    industry_strong = industry_strength == "strong" and industry_context is not None
    if industry_strong:
        industry_detail = f"Industry context is available: {industry_context}."
    elif industry_context is not None:
        industry_detail = "Industry context is present but weak; classification confidence is limited."
    else:
        industry_detail = "Industry context is missing or weak."
    checks_payload.append(
        {
            "key": "industry_context",
            "label": _WORKSPACE_CONTEXT_HEALTH_CHECK_LABELS["industry_context"],
            "status": "strong" if industry_strong else "weak",
            "detail": _compact_workspace_text(
                industry_detail,
                max_length=_WORKSPACE_COMPETITOR_CONTEXT_HEALTH_DETAIL_MAX_CHARS,
            )
            or industry_detail,
        }
    )

    service_focus_terms = _normalize_workspace_service_focus_terms(
        trusted_site_context.get("service_focus_terms"),
    )
    meaningful_service_terms = [
        term for term in service_focus_terms if _is_meaningful_workspace_service_focus_term(term)
    ]
    service_focus_strong = len(meaningful_service_terms) > 0
    if service_focus_strong:
        service_focus_detail = f"Service focus terms are available: {', '.join(meaningful_service_terms[:3])}."
    elif service_focus_terms:
        service_focus_detail = "Service focus terms are present but too generic for strong competitor matching."
    else:
        service_focus_detail = "Service focus terms are missing."
    checks_payload.append(
        {
            "key": "service_focus",
            "label": _WORKSPACE_CONTEXT_HEALTH_CHECK_LABELS["service_focus"],
            "status": "strong" if service_focus_strong else "weak",
            "detail": _compact_workspace_text(
                service_focus_detail,
                max_length=_WORKSPACE_COMPETITOR_CONTEXT_HEALTH_DETAIL_MAX_CHARS,
            )
            or service_focus_detail,
        }
    )

    target_customer_context = _compact_workspace_text(
        trusted_site_context.get("target_customer_context"),
        max_length=200,
    )
    target_customer_strong = bool(
        target_customer_context
        and target_customer_context.lower().startswith("customers in ")
        and location_strong
        and service_focus_strong
    )
    if target_customer_strong:
        target_customer_detail = "Target customer context is grounded by location and service context."
    elif target_customer_context:
        target_customer_detail = "Target customer context is generic; competitor matching may be conservative."
    else:
        target_customer_detail = "Target customer context is missing."
    checks_payload.append(
        {
            "key": "target_customer_context",
            "label": _WORKSPACE_CONTEXT_HEALTH_CHECK_LABELS["target_customer_context"],
            "status": "strong" if target_customer_strong else "weak",
            "detail": _compact_workspace_text(
                target_customer_detail,
                max_length=_WORKSPACE_COMPETITOR_CONTEXT_HEALTH_DETAIL_MAX_CHARS,
            )
            or target_customer_detail,
        }
    )

    check_status_by_key = {
        check["key"]: check["status"]
        for check in checks_payload
        if check["key"] in _WORKSPACE_CONTEXT_HEALTH_CHECK_ORDER
    }
    strong_count = sum(1 for status_value in check_status_by_key.values() if status_value == "strong")
    if strong_count >= 3:
        status = "strong"
        message = "Competitor matching is using grounded business context."
    elif strong_count <= 1:
        status = "weak"
        message = "Competitor matching is missing key business context; results may be limited until location/industry details improve."
    else:
        status = "mixed"
        message = "Competitor matching has partial business context; results may be narrower or more conservative."

    return SEOCompetitorContextHealthRead.model_validate(
        {
            "status": status,
            "checks": checks_payload,
            "message": message,
        }
    )


def _extract_workspace_changed_tuning_values(
    preview_response: dict[str, object] | None,
) -> tuple[str | None, int | None, int | None]:
    if not isinstance(preview_response, dict):
        return (None, None, None)
    raw_current = preview_response.get("current_values")
    raw_proposed = preview_response.get("proposed_values")
    if not isinstance(raw_current, dict) or not isinstance(raw_proposed, dict):
        return (None, None, None)

    parsed_current: dict[str, int] = {}
    parsed_proposed: dict[str, int] = {}
    for setting in _WORKSPACE_TUNING_SETTING_ORDER:
        try:
            parsed_current[setting] = int(raw_current.get(setting))
            parsed_proposed[setting] = int(raw_proposed.get(setting))
        except (TypeError, ValueError):
            continue

    for setting in _WORKSPACE_TUNING_SETTING_ORDER:
        current_value = parsed_current.get(setting)
        proposed_value = parsed_proposed.get(setting)
        if current_value is None or proposed_value is None:
            continue
        if current_value != proposed_value:
            return (setting, current_value, proposed_value)

    for setting in _WORKSPACE_TUNING_SETTING_ORDER:
        proposed_value = parsed_proposed.get(setting)
        if proposed_value is None:
            continue
        return (setting, parsed_current.get(setting), proposed_value)

    return (None, None, None)


def _build_workspace_apply_outcome(
    *,
    latest_applied_preview_event: SEOCompetitorTuningPreviewEvent | None,
    latest_run_status: str | None,
    latest_narrative_read: SEORecommendationNarrativeRead | None,
    recommendations: list[SEORecommendationRead],
    tuning_suggestions: list[SEORecommendationTuningSuggestionRead],
) -> SEORecommendationApplyOutcomeRead | None:
    if latest_applied_preview_event is None or latest_applied_preview_event.applied_at is None:
        return None

    preview_response = (
        latest_applied_preview_event.preview_response
        if isinstance(latest_applied_preview_event.preview_response, dict)
        else None
    )
    changed_setting, current_value, proposed_value = _extract_workspace_changed_tuning_values(preview_response)

    matching_suggestion = None
    if changed_setting:
        for suggestion in tuning_suggestions:
            if suggestion.setting != changed_setting:
                continue
            if proposed_value is not None and suggestion.recommended_value != proposed_value:
                continue
            matching_suggestion = suggestion
            break

    recommendation_title_by_id = {
        item.id: _compact_workspace_text(item.title, max_length=_WORKSPACE_APPLY_OUTCOME_LABEL_MAX_CHARS)
        for item in recommendations
    }
    applied_recommendation_id = None
    applied_recommendation_title = None
    recommendation_label = None
    source = None
    if matching_suggestion is not None:
        for linked_id in matching_suggestion.linked_recommendation_ids:
            linked_title = recommendation_title_by_id.get(linked_id)
            if linked_title:
                applied_recommendation_id = _compact_workspace_text(linked_id, max_length=36)
                applied_recommendation_title = linked_title
                recommendation_label = linked_title
                source = "recommendation"
                break

    if recommendation_label is None and latest_narrative_read is not None:
        if (
            latest_applied_preview_event.source_narrative_id is None
            or latest_applied_preview_event.source_narrative_id == latest_narrative_read.id
        ) and latest_narrative_read.action_summary is not None:
            recommendation_label = _compact_workspace_text(
                latest_narrative_read.action_summary.primary_action,
                max_length=_WORKSPACE_APPLY_OUTCOME_LABEL_MAX_CHARS,
            )
            if recommendation_label:
                source = "recommendation"

    setting_label = (
        _WORKSPACE_SETTING_LABELS.get(changed_setting, changed_setting.replace("_", " ").title())
        if changed_setting
        else None
    )
    applied_change_summary = None
    if setting_label and current_value is not None and proposed_value is not None:
        applied_change_summary = _compact_workspace_text(
            f"{setting_label} was updated from {current_value} to {proposed_value}.",
            max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
        )
    elif setting_label and proposed_value is not None:
        applied_change_summary = _compact_workspace_text(
            f"{setting_label} was updated to {proposed_value}.",
            max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
        )
    elif setting_label:
        applied_change_summary = _compact_workspace_text(
            f"{setting_label} recommendation was applied to site tuning settings.",
            max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
        )
    else:
        applied_change_summary = _compact_workspace_text(
            "A recommendation-linked tuning change was applied to site settings.",
            max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
        )

    if recommendation_label is None and setting_label:
        if current_value is not None and proposed_value is not None:
            recommendation_label = _compact_workspace_text(
                f"{setting_label}: {current_value} -> {proposed_value}",
                max_length=_WORKSPACE_APPLY_OUTCOME_LABEL_MAX_CHARS,
            )
        else:
            recommendation_label = _compact_workspace_text(
                setting_label,
                max_length=_WORKSPACE_APPLY_OUTCOME_LABEL_MAX_CHARS,
            )
    if source is None and recommendation_label:
        source = "manual"

    expected_change = None
    if isinstance(preview_response, dict):
        estimated_impact = preview_response.get("estimated_impact")
        if isinstance(estimated_impact, dict):
            expected_change = _compact_workspace_text(
                estimated_impact.get("summary"),
                max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
            )
    if expected_change is None and setting_label and current_value is not None and proposed_value is not None:
        expected_change = _compact_workspace_text(
            f"{setting_label} was updated from {current_value} to {proposed_value}.",
            max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
        )
    if expected_change is None:
        expected_change = "This tuning update should improve upcoming recommendation and competitor run outputs."

    applied_preview_summary = expected_change

    if latest_run_status in {"queued", "running"}:
        next_refresh_expectation = (
            "An in-flight run may still reflect previous settings. The next completed run should include this change."
        )
    else:
        next_refresh_expectation = (
            "The next completed recommendation or competitor generation run should reflect this change."
        )
    next_refresh_expectation = _compact_workspace_text(
        next_refresh_expectation,
        max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
    )
    reflected_on_next_run = next_refresh_expectation

    try:
        return SEORecommendationApplyOutcomeRead.model_validate(
            {
                "applied": True,
                "applied_at": latest_applied_preview_event.applied_at,
                "applied_recommendation_id": applied_recommendation_id,
                "applied_recommendation_title": applied_recommendation_title or recommendation_label,
                "applied_change_summary": applied_change_summary,
                "applied_preview_summary": applied_preview_summary,
                "next_refresh_expectation": next_refresh_expectation,
                "recommendation_label": recommendation_label,
                "expected_change": expected_change,
                "reflected_on_next_run": reflected_on_next_run,
                "source": source,
            }
        )
    except Exception:  # noqa: BLE001
        return None


def _derive_workspace_analysis_freshness(
    *,
    analysis_generated_at: datetime | None,
    last_apply_at: datetime | None,
) -> SEORecommendationAnalysisFreshnessRead:
    if analysis_generated_at is not None:
        if last_apply_at is None or analysis_generated_at >= last_apply_at:
            status = "fresh"
            message = "Analysis is up to date with the latest applied changes."
        else:
            status = "pending_refresh"
            message = "Changes were applied after this analysis. Refresh or re-run to reflect them."
    else:
        status = "unknown"
        message = "Analysis freshness could not be determined."

    return SEORecommendationAnalysisFreshnessRead.model_validate(
        {
            "status": status,
            "analysis_generated_at": analysis_generated_at,
            "last_apply_at": last_apply_at,
            "message": message,
        }
    )


def _build_workspace_trust_summary(
    *,
    latest_competitor_outcome_summary: SEOCompetitorProfileOutcomeSummaryRead | None,
    latest_competitor_run_status: str | None,
    apply_outcome: SEORecommendationApplyOutcomeRead | None,
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
) -> SEORecommendationWorkspaceTrustSummaryRead | None:
    latest_competitor_status = (
        latest_competitor_outcome_summary.status_level if latest_competitor_outcome_summary is not None else None
    )
    used_google_places_seeds = (
        bool(latest_competitor_outcome_summary.used_google_places_seeds)
        if latest_competitor_outcome_summary is not None
        else None
    )
    used_synthetic_fallback = (
        bool(latest_competitor_outcome_summary.used_synthetic_fallback)
        if latest_competitor_outcome_summary is not None
        else None
    )

    latest_recommendation_apply_title = None
    latest_recommendation_apply_change_summary = None
    next_refresh_expectation = None
    if apply_outcome is not None and apply_outcome.applied:
        latest_recommendation_apply_title = _compact_workspace_text(
            apply_outcome.applied_recommendation_title or apply_outcome.recommendation_label,
            max_length=_WORKSPACE_APPLY_OUTCOME_LABEL_MAX_CHARS,
        )
        latest_recommendation_apply_change_summary = _compact_workspace_text(
            apply_outcome.applied_change_summary or apply_outcome.expected_change,
            max_length=_WORKSPACE_APPLY_OUTCOME_EXPECTED_MAX_CHARS,
        )
        next_refresh_expectation = _compact_workspace_text(
            apply_outcome.next_refresh_expectation or apply_outcome.reflected_on_next_run,
            max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
        )

    if next_refresh_expectation is None:
        if analysis_freshness is not None and analysis_freshness.status == "pending_refresh":
            next_refresh_expectation = _compact_workspace_text(
                "The next completed recommendation run should reflect the latest applied changes.",
                max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
            )
        elif latest_competitor_run_status in {"queued", "running"}:
            next_refresh_expectation = _compact_workspace_text(
                "A competitor generation run is in progress. Results will refresh after completion.",
                max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
            )
        elif latest_competitor_status in {"recovered", "degraded"}:
            next_refresh_expectation = _compact_workspace_text(
                "The next completed competitor generation run should confirm updated live discovery results.",
                max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
            )
        elif latest_competitor_status == "failed":
            next_refresh_expectation = _compact_workspace_text(
                "Start a new competitor generation run to refresh competitor results.",
                max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
            )

    freshness_note = None
    if analysis_freshness is not None and analysis_freshness.status in {"fresh", "pending_refresh"}:
        freshness_note = _compact_workspace_text(
            analysis_freshness.message,
            max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
        )
    elif latest_competitor_status == "failed":
        freshness_note = _compact_workspace_text(
            "Latest competitor generation failed and needs a fresh run.",
            max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
        )
    elif latest_competitor_status in {"recovered", "degraded"}:
        freshness_note = _compact_workspace_text(
            "Latest competitor generation required recovery handling.",
            max_length=_WORKSPACE_APPLY_OUTCOME_REFLECT_MAX_CHARS,
        )

    if (
        latest_competitor_status is None
        and used_google_places_seeds is None
        and used_synthetic_fallback is None
        and latest_recommendation_apply_title is None
        and latest_recommendation_apply_change_summary is None
        and next_refresh_expectation is None
        and freshness_note is None
    ):
        return None

    return SEORecommendationWorkspaceTrustSummaryRead.model_validate(
        {
            "latest_competitor_status": latest_competitor_status,
            "used_google_places_seeds": used_google_places_seeds,
            "used_synthetic_fallback": used_synthetic_fallback,
            "latest_recommendation_apply_title": latest_recommendation_apply_title,
            "latest_recommendation_apply_change_summary": latest_recommendation_apply_change_summary,
            "next_refresh_expectation": next_refresh_expectation,
            "freshness_note": freshness_note,
        }
    )


def _build_competitor_section_freshness(
    *,
    latest_competitor_run_status: str | None,
    latest_competitor_run_evaluated_at: datetime | None,
    latest_competitor_outcome_summary: SEOCompetitorProfileOutcomeSummaryRead | None,
    apply_outcome: SEORecommendationApplyOutcomeRead | None,
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
) -> SEOWorkspaceSectionFreshnessRead:
    def _build(
        *,
        state: str,
        message: str,
        state_code: str | None = None,
        evaluated_at: datetime | None = None,
        refresh_expected: bool | None = None,
    ) -> SEOWorkspaceSectionFreshnessRead:
        return SEOWorkspaceSectionFreshnessRead.model_validate(
            {
                "state": state,
                "message": message,
                "state_code": state_code,
                "state_label": None,
                "state_reason": message,
                "evaluated_at": evaluated_at,
                "refresh_expected": refresh_expected,
            }
        )

    if latest_competitor_run_status in {"queued", "running"}:
        return _build(
            state="running",
            state_code="running",
            message="Competitor generation is currently running and will refresh this section on completion.",
            evaluated_at=latest_competitor_run_evaluated_at,
            refresh_expected=True,
        )

    if latest_competitor_run_status is None:
        return _build(
            state="stale",
            state_code="stale",
            message="No completed competitor generation run is available yet.",
            evaluated_at=None,
            refresh_expected=False,
        )

    if latest_competitor_outcome_summary is not None:
        if latest_competitor_outcome_summary.status_level == "failed":
            return _build(
                state="stale",
                state_code="possibly_outdated",
                message="Latest competitor generation failed. Start a new run to refresh results.",
                evaluated_at=latest_competitor_run_evaluated_at,
                refresh_expected=True,
            )
        if latest_competitor_outcome_summary.status_level == "degraded":
            return _build(
                state="stale",
                state_code="possibly_outdated",
                message="Latest competitor results were degraded fallback output and may need a fresh run.",
                evaluated_at=latest_competitor_run_evaluated_at,
                refresh_expected=True,
            )

    if (
        apply_outcome is not None
        and apply_outcome.applied
        and analysis_freshness is not None
        and analysis_freshness.status == "pending_refresh"
    ):
        return _build(
            state="pending_refresh",
            state_code="pending_refresh",
            message="Applied tuning changes are newer than current analysis; next completed run should refresh competitor context.",
            evaluated_at=analysis_freshness.last_apply_at or latest_competitor_run_evaluated_at,
            refresh_expected=True,
        )

    if latest_competitor_outcome_summary is not None and latest_competitor_outcome_summary.status_level == "recovered":
        return _build(
            state="fresh",
            state_code="fresh",
            message="Competitor section is current after provider recovery.",
            evaluated_at=latest_competitor_run_evaluated_at,
            refresh_expected=False,
        )

    return _build(
        state="fresh",
        state_code="fresh",
        message="Competitor section is current with the latest completed run.",
        evaluated_at=latest_competitor_run_evaluated_at,
        refresh_expected=False,
    )


def _build_recommendation_section_freshness(
    *,
    latest_recommendation_run_status: str | None,
    latest_completed_recommendation_run_id: str | None,
    latest_recommendation_run_evaluated_at: datetime | None,
    latest_completed_recommendation_run_evaluated_at: datetime | None,
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
    apply_outcome: SEORecommendationApplyOutcomeRead | None,
) -> SEOWorkspaceSectionFreshnessRead:
    def _build(
        *,
        state: str,
        message: str,
        state_code: str | None = None,
        evaluated_at: datetime | None = None,
        refresh_expected: bool | None = None,
    ) -> SEOWorkspaceSectionFreshnessRead:
        return SEOWorkspaceSectionFreshnessRead.model_validate(
            {
                "state": state,
                "message": message,
                "state_code": state_code,
                "state_label": None,
                "state_reason": message,
                "evaluated_at": evaluated_at,
                "refresh_expected": refresh_expected,
            }
        )

    if latest_recommendation_run_status in {"queued", "running"}:
        return _build(
            state="running",
            state_code="running",
            message="Recommendation generation is currently running and will refresh this section on completion.",
            evaluated_at=latest_recommendation_run_evaluated_at,
            refresh_expected=True,
        )

    if analysis_freshness is not None and analysis_freshness.status == "pending_refresh":
        return _build(
            state="pending_refresh",
            state_code="pending_refresh",
            message="Applied changes are waiting for the next completed recommendation analysis run.",
            evaluated_at=analysis_freshness.last_apply_at or latest_recommendation_run_evaluated_at,
            refresh_expected=True,
        )

    if latest_completed_recommendation_run_id is None:
        return _build(
            state="stale",
            state_code="stale",
            message="No completed recommendation run is available yet.",
            evaluated_at=latest_recommendation_run_evaluated_at,
            refresh_expected=False,
        )

    if analysis_freshness is not None and analysis_freshness.status == "fresh":
        return _build(
            state="fresh",
            state_code="fresh",
            message="Recommendation section reflects the latest applied changes.",
            evaluated_at=analysis_freshness.analysis_generated_at or latest_completed_recommendation_run_evaluated_at,
            refresh_expected=False,
        )

    if apply_outcome is not None and apply_outcome.applied:
        return _build(
            state="stale",
            state_code="possibly_outdated",
            message="Results may still reflect older settings until a new recommendation run completes.",
            evaluated_at=apply_outcome.applied_at or latest_completed_recommendation_run_evaluated_at,
            refresh_expected=True,
        )

    return _build(
        state="stale",
        state_code="possibly_outdated",
        message="Recommendation freshness could not be confirmed yet.",
        evaluated_at=latest_completed_recommendation_run_evaluated_at or latest_recommendation_run_evaluated_at,
        refresh_expected=False,
    )


def _extract_workspace_applied_recommendation_ids(
    *,
    latest_applied_preview_event: SEOCompetitorTuningPreviewEvent | None,
    recommendations: list[SEORecommendationRead],
    tuning_suggestions: list[SEORecommendationTuningSuggestionRead],
) -> set[str]:
    if latest_applied_preview_event is None or latest_applied_preview_event.applied_at is None:
        return set()
    if not recommendations or not tuning_suggestions:
        return set()

    preview_response = (
        latest_applied_preview_event.preview_response
        if isinstance(latest_applied_preview_event.preview_response, dict)
        else None
    )
    changed_setting, _, proposed_value = _extract_workspace_changed_tuning_values(preview_response)
    if changed_setting is None:
        return set()

    recommendation_ids = {item.id for item in recommendations}
    applied_recommendation_ids: set[str] = set()
    for suggestion in tuning_suggestions:
        if suggestion.setting != changed_setting:
            continue
        if proposed_value is not None and suggestion.recommended_value != proposed_value:
            continue
        for linked_id in suggestion.linked_recommendation_ids:
            if linked_id in recommendation_ids:
                applied_recommendation_ids.add(linked_id)
    return applied_recommendation_ids


def _derive_workspace_recommendation_progress_metadata(
    *,
    recommendations: list[SEORecommendationRead],
    applied_recommendation_ids: set[str],
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
) -> dict[str, dict[str, str]]:
    progress_metadata: dict[str, dict[str, str]] = {}

    def derive_lifecycle_state(
        *,
        recommendation: SEORecommendationRead,
        progress_status: str,
    ) -> tuple[str, str]:
        if progress_status == "applied_pending_refresh":
            return "applied_waiting_validation", "Applied and waiting for refreshed validation."

        if progress_status == "reflected_in_latest_analysis":
            observed_gap = str(recommendation.recommendation_observed_gap_summary or "").strip().lower()
            has_meaningful_observed_gap = bool(
                observed_gap
                and observed_gap != "current site signals in this recommendation area appear limited or inconsistent."
            )
            meaningful_priority_reasons = [
                reason
                for reason in recommendation.priority_reasons
                if reason not in {"general", "pending_refresh_context"}
            ]
            meaningful_trace_tokens = [
                token
                for token in recommendation.recommendation_evidence_trace
                if str(token or "").strip().lower() not in {"audit-backed", "general site signals"}
            ]
            has_specific_target_context = (
                recommendation.recommendation_target_context is not None
                and recommendation.recommendation_target_context != "general"
            )
            has_current_signal = any(
                [
                    has_meaningful_observed_gap,
                    recommendation.recommendation_evidence_summary,
                    bool(meaningful_trace_tokens),
                    has_specific_target_context,
                    bool(meaningful_priority_reasons),
                    bool(recommendation.eeat_categories),
                ]
            )
            if has_current_signal:
                return "reflected_still_relevant", "Reflected in analysis, but still appears relevant."
            return "likely_resolved", "Likely addressed in the latest analysis."

        return "active", "Still an active recommendation."

    for recommendation in recommendations:
        status = "suggested"
        summary = "Suggested action not yet applied."
        if recommendation.id in applied_recommendation_ids:
            if analysis_freshness is not None and analysis_freshness.status == "pending_refresh":
                status = "applied_pending_refresh"
                summary = "Applied. Waiting for the next analysis refresh to reflect this change."
            elif (
                analysis_freshness is not None
                and analysis_freshness.status == "fresh"
                and analysis_freshness.analysis_generated_at is not None
                and analysis_freshness.last_apply_at is not None
                and analysis_freshness.analysis_generated_at >= analysis_freshness.last_apply_at
            ):
                status = "reflected_in_latest_analysis"
                summary = "Applied and reflected in the latest analysis."
        lifecycle_state, lifecycle_summary = derive_lifecycle_state(
            recommendation=recommendation,
            progress_status=status,
        )
        progress_metadata[recommendation.id] = {
            "recommendation_progress_status": status,
            "recommendation_progress_summary": summary,
            "recommendation_lifecycle_state": lifecycle_state,
            "recommendation_lifecycle_summary": lifecycle_summary,
        }
    return progress_metadata


def _format_eeat_category_label(category: SEORecommendationEEATCategory) -> str:
    if category == "experience":
        return "Experience"
    if category == "expertise":
        return "Expertise"
    if category == "authoritativeness":
        return "Authoritativeness"
    return "Trustworthiness"


def _build_workspace_eeat_gap_summary(
    *,
    recommendations: list[SEORecommendationRead],
    latest_narrative_read: SEORecommendationNarrativeRead | None,
) -> SEORecommendationEEATGapSummaryRead | None:
    categories: list[SEORecommendationEEATCategory] = []
    seen_categories: set[str] = set()
    supporting_signals: list[str] = []
    seen_signals: set[str] = set()

    def add_category(value: SEORecommendationEEATCategory) -> None:
        if value in seen_categories:
            return
        seen_categories.add(value)
        categories.append(value)

    def add_signal(value: object) -> None:
        if len(supporting_signals) >= _WORKSPACE_EEAT_GAP_MAX_SIGNALS:
            return
        compacted = _compact_workspace_text(value, max_length=_WORKSPACE_EEAT_GAP_SIGNAL_MAX_CHARS)
        if compacted is None:
            return
        key = compacted.lower()
        if key in seen_signals:
            return
        seen_signals.add(key)
        supporting_signals.append(compacted)

    for recommendation in recommendations:
        evidence_json = recommendation.evidence_json if isinstance(recommendation.evidence_json, dict) else None
        evidence_sources = evidence_json.get("sources") if isinstance(evidence_json, dict) else None
        has_comparison_source = False
        if isinstance(evidence_sources, list):
            has_comparison_source = any(str(item or "").strip().lower() == "comparison" for item in evidence_sources)
        if not has_comparison_source:
            continue
        for category in recommendation.eeat_categories:
            add_category(category)
        add_signal(f"Recommendation: {recommendation.title}")

    if latest_narrative_read is not None and latest_narrative_read.competitor_influence is not None:
        influence = latest_narrative_read.competitor_influence
        if influence.used:
            competitor_signals: list[object] = []
            competitor_signals.extend(influence.top_opportunities)
            if influence.summary:
                competitor_signals.append(influence.summary)
            for category in infer_eeat_categories_from_signals(competitor_signals):
                add_category(category)
            for opportunity in influence.top_opportunities:
                add_signal(f"Competitor signal: {opportunity}")

    if not categories:
        return None

    category_labels = [_format_eeat_category_label(category) for category in categories]
    if len(category_labels) == 1:
        message = f"Visible EEAT gap: {category_labels[0]}. Competitor signals suggest this area is weaker on the site."
    else:
        message = (
            f"Visible EEAT gaps: {', '.join(category_labels)}. "
            "Competitor signals suggest these areas are weaker on the site."
        )

    try:
        return SEORecommendationEEATGapSummaryRead.model_validate(
            {
                "top_gap_categories": categories,
                "supporting_signals": supporting_signals,
                "message": message,
            }
        )
    except Exception:  # noqa: BLE001
        return None


def _build_workspace_ordering_explanation(
    *,
    recommendations: list[SEORecommendationRead],
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
) -> SEORecommendationOrderingExplanationRead | None:
    if not recommendations:
        return None

    has_competitor_gap = any("competitor_gap" in recommendation.priority_reasons for recommendation in recommendations)
    eeat_gap_reason_order = ("trust_gap", "authority_gap", "experience_gap", "expertise_gap")
    eeat_gap_reasons = [
        reason
        for reason in eeat_gap_reason_order
        if any(reason in recommendation.priority_reasons for recommendation in recommendations)
    ]
    has_clarity_reason = any(
        "high_clarity_action" in recommendation.priority_reasons for recommendation in recommendations
    )

    message_parts = ["Ordering reflects deterministic recommendation metadata only; no score is used."]
    context_reasons: list[str] = []

    if has_competitor_gap and eeat_gap_reasons:
        message_parts.append("Competitor-backed EEAT gap actions are surfaced first when present.")
        context_reasons.append("competitor_gap")
        context_reasons.append(eeat_gap_reasons[0])
    elif has_competitor_gap:
        message_parts.append("Competitor-backed actions are surfaced first when present.")
        context_reasons.append("competitor_gap")
    elif eeat_gap_reasons:
        message_parts.append("EEAT gap-aligned actions are surfaced first when present.")
        context_reasons.append(eeat_gap_reasons[0])

    if has_clarity_reason:
        message_parts.append("Clear next-step actions are highlighted when priorities tie.")
        context_reasons.append("high_clarity_action")

    if analysis_freshness is not None and analysis_freshness.status == "pending_refresh":
        message_parts.append(
            "Applied changes are newer than this analysis and may change ordering after the next completed run."
        )
        context_reasons.append("pending_refresh_context")

    deduped_context_reasons = list(dict.fromkeys(context_reasons))
    try:
        return SEORecommendationOrderingExplanationRead.model_validate(
            {
                "message": " ".join(message_parts),
                "context_reasons": deduped_context_reasons,
            }
        )
    except Exception:  # noqa: BLE001
        return None


def _build_workspace_grouped_recommendations(
    *,
    recommendations: list[SEORecommendationRead],
) -> list[SEORecommendationThemeGroupRead]:
    if not recommendations:
        return []

    theme_to_ids: dict[str, list[str]] = {}
    theme_to_label: dict[str, str] = {}
    seen_ids: set[str] = set()

    for recommendation in recommendations:
        if recommendation.id in seen_ids:
            continue
        seen_ids.add(recommendation.id)
        theme = recommendation.theme or "general_site_improvement"
        if theme not in theme_to_ids:
            theme_to_ids[theme] = []
        theme_to_ids[theme].append(recommendation.id)
        if theme not in theme_to_label:
            if recommendation.theme_label:
                theme_to_label[theme] = recommendation.theme_label
            else:
                theme_to_label[theme] = format_recommendation_theme_label(theme)  # type: ignore[arg-type]

    grouped: list[SEORecommendationThemeGroupRead] = []
    for theme in _WORKSPACE_RECOMMENDATION_THEME_ORDER:
        ids = theme_to_ids.get(theme, [])
        if not ids:
            continue
        try:
            grouped.append(
                SEORecommendationThemeGroupRead.model_validate(
                    {
                        "theme": theme,
                        "label": theme_to_label.get(theme) or format_recommendation_theme_label(theme),  # type: ignore[arg-type]
                        "count": len(ids),
                        "recommendation_ids": ids,
                    }
                )
            )
        except Exception:  # noqa: BLE001
            continue

    return grouped


def _find_recommendation_by_id(
    *,
    recommendations: list[SEORecommendationRead],
    recommendation_id: str,
) -> SEORecommendationRead | None:
    for recommendation in recommendations:
        if recommendation.id == recommendation_id:
            return recommendation
    return None


def _build_workspace_start_here_reason(
    *,
    theme: str,
    recommendation: SEORecommendationRead,
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
) -> tuple[str, list[str]]:
    base_reason_map = {
        "trust_and_legitimacy": "Start here to close a high-visibility trust and legitimacy gap.",
        "experience_and_proof": "Start here to make real work proof more visible to potential customers.",
        "authority_and_visibility": "Start here to strengthen authority and visibility signals customers can verify.",
        "expertise_and_process": "Start here to clarify expertise and execution process for buyers.",
        "general_site_improvement": "Start here because this is the first action in your strongest visible gap theme.",
    }
    context_flags: list[str] = []
    reason = base_reason_map.get(
        theme,
        "Start here because this is the first action in your strongest visible gap theme.",
    )
    if "competitor_gap" in recommendation.priority_reasons:
        reason = "Start here because competitor-backed evidence highlights this gap first."
        context_flags.append("competitor_backed")
    if analysis_freshness is not None and analysis_freshness.status == "pending_refresh":
        context_flags.append("pending_refresh_context")
        reason = f"{reason} Based on the latest available analysis; refresh pending."
    compacted = _compact_workspace_text(reason, max_length=_WORKSPACE_START_HERE_REASON_MAX_CHARS)
    return (
        compacted or "Start here because this is the first action in your strongest visible gap theme.",
        list(dict.fromkeys(context_flags)),
    )


def _build_workspace_start_here(
    *,
    recommendations: list[SEORecommendationRead],
    grouped_recommendations: list[SEORecommendationThemeGroupRead],
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None,
) -> SEORecommendationStartHereRead | None:
    if not recommendations:
        return None

    selected_theme: str | None = None
    selected_theme_label: str | None = None
    selected_recommendation_id: str | None = None

    for group in grouped_recommendations:
        if not group.recommendation_ids:
            continue
        selected_theme = group.theme
        selected_theme_label = group.label
        selected_recommendation_id = group.recommendation_ids[0]
        break

    if selected_recommendation_id is None:
        for theme in _WORKSPACE_RECOMMENDATION_THEME_ORDER:
            for recommendation in recommendations:
                if (recommendation.theme or "general_site_improvement") != theme:
                    continue
                selected_theme = theme
                selected_theme_label = recommendation.theme_label or format_recommendation_theme_label(theme)  # type: ignore[arg-type]
                selected_recommendation_id = recommendation.id
                break
            if selected_recommendation_id is not None:
                break

    if selected_recommendation_id is None:
        fallback = recommendations[0]
        selected_theme = fallback.theme or "general_site_improvement"
        selected_theme_label = fallback.theme_label or format_recommendation_theme_label(selected_theme)  # type: ignore[arg-type]
        selected_recommendation_id = fallback.id

    selected_recommendation = _find_recommendation_by_id(
        recommendations=recommendations,
        recommendation_id=selected_recommendation_id,
    )
    if selected_recommendation is None:
        return None

    reason, context_flags = _build_workspace_start_here_reason(
        theme=selected_theme or "general_site_improvement",
        recommendation=selected_recommendation,
        analysis_freshness=analysis_freshness,
    )

    try:
        return SEORecommendationStartHereRead.model_validate(
            {
                "theme": selected_theme or "general_site_improvement",
                "theme_label": selected_theme_label
                or format_recommendation_theme_label((selected_theme or "general_site_improvement")),  # type: ignore[arg-type]
                "recommendation_id": selected_recommendation.id,
                "title": selected_recommendation.title,
                "reason": reason,
                "context_flags": context_flags,
            }
        )
    except Exception:  # noqa: BLE001
        return None


def _normalize_workspace_recommendation_target_context(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in _WORKSPACE_RECOMMENDATION_TARGET_ALLOWED_CONTEXTS:
        return normalized
    return None


def _normalize_workspace_audit_page_path(url: object) -> str | None:
    compacted = _compact_workspace_text(url, max_length=2048)
    if compacted is None:
        return None

    parsed = urlparse(compacted)
    path = (parsed.path or "/").strip()
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = f"/{path}"
    path = re.sub(r"/+", "/", path)
    if path != "/":
        path = path.rstrip("/")
    return path or "/"


def _is_workspace_homepage_path(path: str) -> bool:
    normalized = path.lower()
    return normalized in {"", "/", "/home", "/index", "/index.html", "/default", "/default.aspx"}


def _build_workspace_recommendation_page_match_text(*, page: SEOAuditPage, path: str) -> str:
    raw_parts: list[object] = [path, page.title, page.meta_description]
    if isinstance(page.h1_json, list):
        raw_parts.extend(page.h1_json[:4])
    if isinstance(page.h2_json, list):
        raw_parts.extend(page.h2_json[:6])

    compact_parts: list[str] = []
    for value in raw_parts:
        compacted = _compact_workspace_text(value, max_length=180)
        if compacted:
            compact_parts.append(compacted.lower())
    return " ".join(compact_parts)


def _build_workspace_page_hint_from_audit_page(*, page: SEOAuditPage, path: str) -> str | None:
    if _is_workspace_homepage_path(path):
        return "Homepage"

    compact_path = _compact_workspace_text(path, max_length=_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_CHARS)
    if compact_path and compact_path != "/":
        return compact_path

    return _compact_workspace_text(page.title, max_length=_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_CHARS)


def _collect_workspace_recommendation_page_hints_by_context(
    pages: list[SEOAuditPage],
) -> dict[str, list[str]]:
    hints_by_context: dict[str, list[str]] = {
        "homepage": [],
        "contact_about": [],
        "service_pages": [],
        "location_pages": [],
        "core": [],
    }
    seen_by_context: dict[str, set[str]] = {key: set() for key in hints_by_context}

    def add_hint(context: str, hint: str) -> None:
        if context not in hints_by_context:
            return
        normalized_key = hint.lower()
        if normalized_key in seen_by_context[context]:
            return
        seen_by_context[context].add(normalized_key)
        hints_by_context[context].append(hint)

    for page in pages:
        path = _normalize_workspace_audit_page_path(page.url)
        if path is None:
            continue
        hint = _build_workspace_page_hint_from_audit_page(page=page, path=path)
        if hint is None:
            continue

        match_text = _build_workspace_recommendation_page_match_text(page=page, path=path)
        is_homepage = _is_workspace_homepage_path(path)
        if is_homepage:
            add_hint("homepage", hint)
        else:
            add_hint("core", hint)

        if any(keyword in match_text for keyword in _WORKSPACE_RECOMMENDATION_TARGET_CONTACT_ABOUT_KEYWORDS):
            add_hint("contact_about", hint)
        if any(keyword in match_text for keyword in _WORKSPACE_RECOMMENDATION_TARGET_SERVICE_KEYWORDS):
            add_hint("service_pages", hint)
        if any(keyword in match_text for keyword in _WORKSPACE_RECOMMENDATION_TARGET_LOCATION_KEYWORDS):
            add_hint("location_pages", hint)

    return hints_by_context


def _derive_workspace_target_page_hints_for_context(
    *,
    target_context: object,
    hints_by_context: dict[str, list[str]],
) -> list[str]:
    normalized_context = _normalize_workspace_recommendation_target_context(target_context)
    if normalized_context is None:
        return []

    if normalized_context == "homepage":
        return hints_by_context.get("homepage", [])[:1]
    if normalized_context == "contact_about":
        return hints_by_context.get("contact_about", [])[:_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_ITEMS]
    if normalized_context == "service_pages":
        return hints_by_context.get("service_pages", [])[:_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_ITEMS]
    if normalized_context == "location_pages":
        return hints_by_context.get("location_pages", [])[:_WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_ITEMS]
    if normalized_context == "sitewide":
        hints: list[str] = []
        seen: set[str] = set()
        for bucket in ("homepage", "service_pages", "contact_about", "location_pages", "core"):
            for hint in hints_by_context.get(bucket, []):
                key = hint.lower()
                if key in seen:
                    continue
                seen.add(key)
                hints.append(hint)
                if len(hints) >= _WORKSPACE_RECOMMENDATION_TARGET_HINT_MAX_ITEMS:
                    return hints
        return hints
    return []


def _derive_workspace_recommendation_target_page_hints(
    *,
    recommendations: list[SEORecommendationRead],
    audit_pages: list[SEOAuditPage],
) -> dict[str, list[str]]:
    if not recommendations or not audit_pages:
        return {}
    hints_by_context = _collect_workspace_recommendation_page_hints_by_context(audit_pages)
    hints_by_recommendation_id: dict[str, list[str]] = {}
    for recommendation in recommendations:
        hints = _derive_workspace_target_page_hints_for_context(
            target_context=recommendation.recommendation_target_context,
            hints_by_context=hints_by_context,
        )
        if hints:
            hints_by_recommendation_id[recommendation.id] = hints
    return hints_by_recommendation_id


def _workspace_recommendation_has_competitor_backing(recommendation: SEORecommendationRead) -> bool:
    if recommendation.comparison_run_id:
        return True
    if "competitor_gap" in recommendation.priority_reasons:
        return True
    evidence_json = recommendation.evidence_json if isinstance(recommendation.evidence_json, dict) else None
    sources = evidence_json.get("sources") if isinstance(evidence_json, dict) else None
    if isinstance(sources, list):
        for source in sources:
            if str(source or "").strip().lower() == "comparison":
                return True
    return False


def _workspace_competitor_link_rank_score(
    *,
    recommendation: SEORecommendationRead,
    draft: SEOCompetitorProfileDraftRead,
) -> float:
    score = max(0.0, float(draft.confidence_score or 0.0))
    if draft.competitor_type in {"direct", "local"}:
        score += 0.1
    if draft.source_type == "places":
        score += 0.08
    if draft.source_type == "synthetic":
        score -= 0.35
    if recommendation.recommendation_target_context == "location_pages":
        if draft.competitor_type == "local":
            score += 0.07
        if draft.source_type == "places":
            score += 0.04
    if recommendation.recommendation_target_context == "service_pages" and draft.competitor_type in {
        "direct",
        "indirect",
    }:
        score += 0.05
    return score


def _normalize_workspace_competitor_verification_status(raw: object) -> str | None:
    normalized = str(raw or "").strip().lower()
    if normalized in {
        _WORKSPACE_COMPETITOR_VERIFICATION_STATUS_VERIFIED,
        _WORKSPACE_COMPETITOR_VERIFICATION_STATUS_UNVERIFIED,
    }:
        return normalized
    return None


def _build_workspace_draft_verification_status_map(
    *,
    competitor_drafts: list[SEOCompetitorProfileDraftRead],
    site_domains: list[object],
) -> dict[str, str]:
    if not competitor_drafts or not site_domains:
        return {}

    verification_status_by_domain_id: dict[str, str] = {}
    for domain in site_domains:
        domain_id = _compact_workspace_text(getattr(domain, "id", None), max_length=36)
        if domain_id is None:
            continue
        verification_status = _normalize_workspace_competitor_verification_status(
            getattr(domain, "verification_status", None)
        )
        if verification_status is None:
            continue
        verification_status_by_domain_id[domain_id] = verification_status

    draft_verification_status_by_id: dict[str, str] = {}
    for draft in competitor_drafts:
        accepted_domain_id = _compact_workspace_text(draft.accepted_competitor_domain_id, max_length=36)
        if accepted_domain_id is None:
            continue
        verification_status = verification_status_by_domain_id.get(accepted_domain_id)
        if verification_status is None:
            continue
        draft_verification_status_by_id[draft.id] = verification_status
    return draft_verification_status_by_id


def _build_workspace_recommendation_competitor_linkage(
    *,
    recommendations: list[SEORecommendationRead],
    competitor_drafts: list[SEOCompetitorProfileDraftRead],
    draft_verification_status_by_id: dict[str, str] | None = None,
) -> dict[str, dict[str, object]]:
    if not recommendations:
        return {}

    normalized_drafts = [
        draft
        for draft in competitor_drafts
        if _compact_workspace_text(draft.suggested_name, max_length=180) is not None
    ]
    if not normalized_drafts:
        return {}

    linkage_by_recommendation_id: dict[str, dict[str, object]] = {}
    for recommendation in recommendations:
        if not _workspace_recommendation_has_competitor_backing(recommendation):
            continue

        ranked_drafts = sorted(
            normalized_drafts,
            key=lambda draft: (
                -_workspace_competitor_link_rank_score(recommendation=recommendation, draft=draft),
                str(draft.suggested_name or "").lower(),
                draft.id,
            ),
        )

        links: list[SEORecommendationCompetitorEvidenceLinkRead] = []
        seen_draft_ids: set[str] = set()
        for draft in ranked_drafts:
            if draft.id in seen_draft_ids:
                continue
            seen_draft_ids.add(draft.id)
            draft_verification_status = (
                _normalize_workspace_competitor_verification_status(
                    (draft_verification_status_by_id or {}).get(draft.id)
                )
                if draft_verification_status_by_id
                else None
            )
            trust_tier = classify_competitor_evidence_link(
                review_status=draft.review_status,
                verification_status=draft_verification_status,
            )
            competitor_name = _compact_workspace_text(draft.suggested_name, max_length=180)
            if competitor_name is None:
                continue
            try:
                links.append(
                    SEORecommendationCompetitorEvidenceLinkRead.model_validate(
                        {
                            "competitor_draft_id": draft.id,
                            "competitor_name": competitor_name,
                            "competitor_domain": _compact_workspace_text(draft.suggested_domain, max_length=255),
                            "confidence_level": draft.confidence_level,
                            "source_type": draft.source_type,
                            "verification_status": draft_verification_status,
                            "trust_tier": trust_tier,
                            "evidence_trust_tier": trust_tier,
                            "evidence_summary": _compact_workspace_text(
                                draft.operator_evidence_summary
                                or draft.provenance_explanation
                                or draft.why_competitor
                                or draft.summary,
                                max_length=_WORKSPACE_COMPETITOR_EVIDENCE_TEXT_MAX_CHARS,
                            ),
                        }
                    )
                )
            except Exception:  # noqa: BLE001
                continue
            if len(links) >= _WORKSPACE_COMPETITOR_EVIDENCE_LINK_MAX_ITEMS:
                break

        observed_gap_or_advantage = _compact_workspace_text(
            recommendation.recommendation_observed_gap_summary,
            max_length=_WORKSPACE_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS,
        )
        if observed_gap_or_advantage is not None:
            linkage_summary = observed_gap_or_advantage
        elif any(link.trust_tier == "trusted_verified" for link in links):
            linkage_summary = _compact_workspace_text(
                "Competitor evidence indicates this recommendation can close a local service visibility gap.",
                max_length=_WORKSPACE_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS,
            )
        elif links:
            linkage_summary = _compact_workspace_text(
                "Competitor linkage is informational; verify websites before treating it as trusted evidence.",
                max_length=_WORKSPACE_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS,
            )
        else:
            linkage_summary = _compact_workspace_text(
                "Competitor evidence is limited for this recommendation; validate against local market context.",
                max_length=_WORKSPACE_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS,
            )

        linkage_by_recommendation_id[recommendation.id] = {
            "competitor_evidence_links": links,
            "competitor_linkage_summary": linkage_summary,
        }

    return linkage_by_recommendation_id


def _derive_workspace_action_delta_evidence_strength(
    links: list[SEORecommendationCompetitorEvidenceLinkRead],
) -> str:
    if not links:
        return "low"
    high_count = sum(1 for link in links if link.confidence_level == "high")
    medium_count = sum(1 for link in links if link.confidence_level == "medium")
    places_count = sum(1 for link in links if link.source_type == "places")
    if high_count >= 1 and (len(links) >= 2 or places_count >= 1):
        return "high"
    if high_count >= 1 or medium_count >= 1 or len(links) >= 2:
        return "medium"
    return "low"


def _derive_workspace_observed_competitor_pattern(
    links: list[SEORecommendationCompetitorEvidenceLinkRead],
) -> str | None:
    if not links:
        return None
    has_places = any(link.source_type == "places" for link in links)
    has_high = any(link.confidence_level == "high" for link in links)
    normalized_source_types = [link.source_type for link in links if link.source_type]
    only_fallback_sources = bool(normalized_source_types) and all(
        source_type in {"fallback", "synthetic"} for source_type in normalized_source_types
    )
    if only_fallback_sources:
        return _compact_workspace_text(
            "Competitor coverage is based on lower-confidence fallback candidates.",
            max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
        )
    if has_places and has_high:
        return _compact_workspace_text(
            "Nearby seeded competitors show strong local service coverage.",
            max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
        )
    if has_places:
        return _compact_workspace_text(
            "Nearby seeded competitors indicate stronger local relevance in this area.",
            max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
        )
    if has_high:
        return _compact_workspace_text(
            "Top linked competitors show stronger coverage in this recommendation area.",
            max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
        )
    return _compact_workspace_text(
        "Linked competitors indicate stronger coverage in this recommendation area.",
        max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
    )


def _build_workspace_recommendation_action_deltas(
    *,
    recommendations: list[SEORecommendationRead],
    competitor_linkage_by_recommendation_id: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not recommendations:
        return {}

    action_deltas_by_recommendation_id: dict[str, dict[str, object]] = {}
    for recommendation in recommendations:
        linkage_payload = competitor_linkage_by_recommendation_id.get(recommendation.id)
        if linkage_payload is None:
            continue

        raw_links = linkage_payload.get("competitor_evidence_links")
        links = (
            [link for link in raw_links if isinstance(link, SEORecommendationCompetitorEvidenceLinkRead)]
            if isinstance(raw_links, list)
            else []
        )
        if not links:
            continue

        observed_competitor_pattern = _derive_workspace_observed_competitor_pattern(links)
        observed_site_gap = _compact_workspace_text(
            recommendation.recommendation_observed_gap_summary,
            max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
        )
        if observed_site_gap is None:
            observed_site_gap = _compact_workspace_text(
                recommendation.recommendation_evidence_summary,
                max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
            )

        recommended_operator_action = _compact_workspace_text(
            recommendation.recommendation_action_clarity,
            max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
        )
        if recommended_operator_action is None:
            recommended_operator_action = _compact_workspace_text(
                recommendation.title,
                max_length=_WORKSPACE_RECOMMENDATION_ACTION_DELTA_MAX_CHARS,
            )

        if observed_competitor_pattern is None or observed_site_gap is None or recommended_operator_action is None:
            continue

        evidence_strength = _derive_workspace_action_delta_evidence_strength(links)

        try:
            action_delta = SEORecommendationActionDeltaRead.model_validate(
                {
                    "observed_competitor_pattern": observed_competitor_pattern,
                    "observed_site_gap": observed_site_gap,
                    "recommended_operator_action": recommended_operator_action,
                    "evidence_strength": evidence_strength,
                }
            )
        except Exception:  # noqa: BLE001
            continue

        action_deltas_by_recommendation_id[recommendation.id] = {
            "recommendation_action_delta": action_delta,
        }

    return action_deltas_by_recommendation_id


def _workspace_recommendation_effort_hint(effort_bucket: str | None) -> str | None:
    normalized = str(effort_bucket or "").strip().upper()
    if normalized == "LOW":
        return "quick_win"
    if normalized == "MEDIUM":
        return "moderate"
    if normalized == "HIGH":
        return "larger_change"
    return None


def _workspace_priority_reason_for_level(
    *,
    priority_level: str,
    has_competitor_linkage: bool,
    has_action_delta: bool,
) -> str:
    if priority_level == "high":
        if has_competitor_linkage and has_action_delta:
            return "Strong competitor-backed gap with a clear next action."
        if has_action_delta:
            return "Clear action with high-impact evidence from current signals."
        return "High-impact recommendation that should be addressed first."
    if priority_level == "medium":
        if has_competitor_linkage:
            return "Competitor-backed gap with an actionable next step."
        return "Actionable recommendation with moderate evidence support."
    if has_action_delta:
        return "Lower-evidence action; schedule after higher-priority items."
    return "Limited competitor evidence; review after higher-confidence actions."


def _build_workspace_recommendation_priorities(
    *,
    recommendations: list[SEORecommendationRead],
    competitor_linkage_by_recommendation_id: dict[str, dict[str, object]],
    action_delta_by_recommendation_id: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not recommendations:
        return {}

    priorities_by_recommendation_id: dict[str, dict[str, object]] = {}
    for recommendation in recommendations:
        linkage_payload = competitor_linkage_by_recommendation_id.get(recommendation.id, {})
        links_raw = linkage_payload.get("competitor_evidence_links")
        links = (
            [link for link in links_raw if isinstance(link, SEORecommendationCompetitorEvidenceLinkRead)]
            if isinstance(links_raw, list)
            else []
        )
        high_link_count = sum(1 for link in links if link.confidence_level == "high")
        has_competitor_linkage = bool(links)

        action_delta_payload = action_delta_by_recommendation_id.get(recommendation.id, {})
        action_delta = action_delta_payload.get("recommendation_action_delta")
        action_delta_evidence_strength = (
            action_delta.evidence_strength if isinstance(action_delta, SEORecommendationActionDeltaRead) else None
        )
        has_action_delta = action_delta_evidence_strength is not None

        score = 0
        if action_delta_evidence_strength == "high":
            score += 4
        elif action_delta_evidence_strength == "medium":
            score += 2
        elif action_delta_evidence_strength == "low":
            score += 1

        if len(links) >= 2:
            score += 1
        if high_link_count >= 1:
            score += 1

        if recommendation.priority_band in {"critical", "high"}:
            score += 1
        if recommendation.severity == "CRITICAL":
            score += 1

        if score >= 5:
            priority_level = "high"
        elif score >= 2:
            priority_level = "medium"
        else:
            priority_level = "low"

        priority_reason = _workspace_priority_reason_for_level(
            priority_level=priority_level,
            has_competitor_linkage=has_competitor_linkage,
            has_action_delta=has_action_delta,
        )
        effort_hint = _workspace_recommendation_effort_hint(recommendation.effort_bucket)

        try:
            priority = SEORecommendationPriorityRead.model_validate(
                {
                    "priority_level": priority_level,
                    "priority_reason": priority_reason,
                    "effort_hint": effort_hint,
                }
            )
        except Exception:  # noqa: BLE001
            continue

        priorities_by_recommendation_id[recommendation.id] = {
            "recommendation_priority": priority,
        }

    return priorities_by_recommendation_id


def _load_workspace_audit_pages_for_recommendations(
    *,
    business_id: str,
    site_id: str,
    recommendation_audit_run_id: str | None,
    seo_audit_repository: SEOAuditRepository,
) -> list[SEOAuditPage]:
    candidate_run_ids: list[str] = []
    if recommendation_audit_run_id:
        candidate_run_ids.append(recommendation_audit_run_id)

    latest_audit_run = seo_audit_repository.get_latest_completed_run_for_business_site(
        business_id=business_id,
        site_id=site_id,
    )
    if latest_audit_run is not None and latest_audit_run.id not in candidate_run_ids:
        candidate_run_ids.append(latest_audit_run.id)

    for audit_run_id in candidate_run_ids:
        pages = seo_audit_repository.list_pages_for_business_run(
            business_id=business_id,
            run_id=audit_run_id,
        )
        if pages:
            return pages
    return []


@router.get("/sites", response_model=SEOSiteListResponse)
def list_seo_sites(
    business_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_site_service.list_sites(business_id=scoped_business_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOSiteListResponse(items=[SEOSiteRead.model_validate(site) for site in items], total=len(items))


@router.post("/sites", response_model=SEOSiteRead, status_code=status.HTTP_201_CREATED)
def create_seo_site(
    business_id: str,
    payload: SEOSiteCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.create_site(business_id=scoped_business_id, payload=payload)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.get("/sites/{site_id}", response_model=SEOSiteRead)
def get_seo_site(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.patch("/sites/{site_id}", response_model=SEOSiteRead)
def patch_seo_site(
    business_id: str,
    site_id: str,
    payload: SEOSiteUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    if tenant_context.principal_role != PrincipalRole.ADMIN and (
        payload.display_name is not None
        or payload.base_url is not None
        or payload.search_console_property_url is not None
        or payload.search_console_enabled is not None
        or payload.is_active is not None
        or payload.is_primary is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin principals can update site name, URL, activation, or primary state.",
        )
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.patch("/admin/sites/{site_id}", response_model=SEOSiteRead)
def patch_admin_seo_site(
    business_id: str,
    site_id: str,
    payload: SEOSiteAdminUpdateRequest,
    _: None = Depends(require_admin_rate_limit("seo_site_admin_update")),
    _admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    update_payload_data: dict[str, str] = {}
    if payload.name is not None:
        update_payload_data["display_name"] = payload.name
    if payload.url is not None:
        update_payload_data["base_url"] = payload.url
    if payload.search_console_property_url is not None:
        update_payload_data["search_console_property_url"] = payload.search_console_property_url
    if payload.search_console_enabled is not None:
        update_payload_data["search_console_enabled"] = payload.search_console_enabled
    update_payload = SEOSiteUpdateRequest.model_validate(update_payload_data)
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=update_payload,
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.delete("/admin/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_seo_site(
    business_id: str,
    site_id: str,
    _: None = Depends(require_admin_rate_limit("seo_site_admin_delete")),
    _admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> Response:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.delete_site_permanently(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sites/{site_id}/deactivate", response_model=SEOSiteRead)
def deactivate_seo_site(
    business_id: str,
    site_id: str,
    _: None = Depends(require_admin_rate_limit("seo_site_deactivate")),
    _admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=SEOSiteUpdateRequest(is_active=False),
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.post("/sites/{site_id}/activate", response_model=SEOSiteRead)
def activate_seo_site(
    business_id: str,
    site_id: str,
    _: None = Depends(require_admin_rate_limit("seo_site_activate")),
    _admin_principal: Principal = Depends(require_credential_manager_principal),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
) -> SEOSiteRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.update_site(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=SEOSiteUpdateRequest(is_active=True),
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSiteValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOSiteRead.model_validate(site)


@router.post("/sites/{site_id}/audit-runs", response_model=SEOAuditRunRead, status_code=status.HTTP_201_CREATED)
def create_seo_audit_run(
    business_id: str,
    site_id: str,
    payload: SEOAuditRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = seo_audit_service.run_audit(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAuditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAuditRunRead.model_validate(result.run)


@router.get("/sites/{site_id}/audit-runs", response_model=SEOAuditRunListResponse)
def list_seo_audit_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        runs = seo_audit_service.list_runs_for_site(business_id=scoped_business_id, site_id=site_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditRunListResponse(
        items=[SEOAuditRunRead.model_validate(run) for run in runs],
        total=len(runs),
    )


@router.get("/audit-runs/{run_id}", response_model=SEOAuditRunRead)
def get_seo_audit_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        run = seo_audit_service.get_run(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditRunRead.model_validate(run)


@router.get("/audit-runs/{run_id}/findings", response_model=SEOAuditFindingListResponse)
def list_seo_audit_run_findings(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditFindingListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        findings = seo_audit_service.list_findings_for_run(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    by_category, by_severity = seo_audit_service.summarize_findings(findings=findings)
    return SEOAuditFindingListResponse(
        items=[SEOAuditFindingRead.model_validate(item) for item in findings],
        total=len(findings),
        by_category=by_category,
        by_severity=by_severity,
    )


@router.get("/audit-runs/{run_id}/summary", response_model=SEOAuditRunSummaryRead)
def get_seo_audit_run_summary(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditRunSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = seo_audit_service.get_run_summary(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditRunSummaryRead(
        run_id=summary.run.id,
        business_id=summary.run.business_id,
        site_id=summary.run.site_id,
        status=summary.run.status,
        total_pages=summary.total_pages,
        total_findings=summary.total_findings,
        critical_findings=summary.critical_findings,
        warning_findings=summary.warning_findings,
        info_findings=summary.info_findings,
        crawl_duration=summary.crawl_duration,
        health_score=summary.health_score,
        by_category=summary.by_category,
        by_severity=summary.by_severity,
    )


@router.get("/audit-runs/{run_id}/report", response_model=SEOAuditReportRead)
def get_seo_audit_run_report(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_audit_service: SEOAuditService = Depends(get_seo_audit_service),
) -> SEOAuditReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        report = seo_audit_service.get_run_report(business_id=scoped_business_id, run_id=run_id)
    except SEOAuditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAuditReportRead(
        site=SEOAuditReportSiteRead(
            id=report.site.id,
            display_name=report.site.display_name,
            base_url=report.site.base_url,
            normalized_domain=report.site.normalized_domain,
        ),
        audit=SEOAuditRunSummaryRead(
            run_id=report.summary.run.id,
            business_id=report.summary.run.business_id,
            site_id=report.summary.run.site_id,
            status=report.summary.run.status,
            total_pages=report.summary.total_pages,
            total_findings=report.summary.total_findings,
            critical_findings=report.summary.critical_findings,
            warning_findings=report.summary.warning_findings,
            info_findings=report.summary.info_findings,
            crawl_duration=report.summary.crawl_duration,
            health_score=report.summary.health_score,
            by_category=report.summary.by_category,
            by_severity=report.summary.by_severity,
        ),
        findings=SEOAuditFindingListResponse(
            items=[SEOAuditFindingRead.model_validate(item) for item in report.findings],
            total=len(report.findings),
            by_category=report.summary.by_category,
            by_severity=report.summary.by_severity,
        ),
    )


@router.post("/audit-runs/{run_id}/summarize", response_model=SEOAuditSummaryRead, status_code=status.HTTP_201_CREATED)
def summarize_seo_audit_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_summary_service: SEOSummaryService = Depends(get_seo_summary_service),
) -> SEOAuditSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = seo_summary_service.summarize_run(
            business_id=scoped_business_id,
            run_id=run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOSummaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAuditSummaryRead.model_validate(result.summary)


@router.post(
    "/sites/{site_id}/recommendation-runs",
    response_model=SEORecommendationRunRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/recommendation-runs",
    response_model=SEORecommendationRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_seo_recommendation_run(
    business_id: str,
    site_id: str,
    payload: SEORecommendationRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = recommendation_service.run_recommendations(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEORecommendationRunRead.model_validate(result.run)


@router.get("/sites/{site_id}/recommendation-runs", response_model=SEORecommendationRunListResponse)
@router_v1.get("/sites/{site_id}/recommendation-runs", response_model=SEORecommendationRunListResponse)
def list_seo_recommendation_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = recommendation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationRunListResponse(
        items=[SEORecommendationRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/sites/{site_id}/recommendations/workspace-summary",
    response_model=SEORecommendationWorkspaceSummaryRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendations/workspace-summary",
    response_model=SEORecommendationWorkspaceSummaryRead,
)
def get_seo_recommendation_workspace_summary(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_audit_repository: SEOAuditRepository = Depends(get_seo_audit_repository),
    seo_competitor_repository: SEOCompetitorRepository = Depends(get_seo_competitor_repository),
    seo_competitor_profile_generation_repository: SEOCompetitorProfileGenerationRepository = Depends(
        get_seo_competitor_profile_generation_repository
    ),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> SEORecommendationWorkspaceSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        runs = recommendation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    latest_run = runs[0] if runs else None
    latest_completed_run = next((run for run in runs if run.status == "completed"), None)
    latest_narrative_read: SEORecommendationNarrativeRead | None = None
    tuning_suggestions: list[SEORecommendationTuningSuggestionRead] = []
    grouped_recommendations: list[SEORecommendationThemeGroupRead] = []
    apply_outcome: SEORecommendationApplyOutcomeRead | None = None
    workspace_trust_summary: SEORecommendationWorkspaceTrustSummaryRead | None = None
    competitor_section_freshness: SEOWorkspaceSectionFreshnessRead | None = None
    recommendation_section_freshness: SEOWorkspaceSectionFreshnessRead | None = None
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None = None
    ordering_explanation: SEORecommendationOrderingExplanationRead | None = None
    start_here: SEORecommendationStartHereRead | None = None
    eeat_gap_summary: SEORecommendationEEATGapSummaryRead | None = None
    competitor_context_health: SEOCompetitorContextHealthRead | None = None
    competitor_prompt_preview = None
    recommendation_prompt_preview = None
    latest_competitor_outcome_summary: SEOCompetitorProfileOutcomeSummaryRead | None = None
    latest_competitor_drafts: list[SEOCompetitorProfileDraftRead] = []
    trusted_site_context: dict[str, object] = {}
    workspace_audit_pages: list[SEOAuditPage] = []
    latest_applied_preview_event = (
        seo_competitor_profile_generation_repository.get_latest_applied_tuning_preview_event_for_business_site(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    )

    empty_recommendations = SEORecommendationListResponse(
        items=[],
        total=0,
        by_status={},
        by_category={},
        by_severity={},
        by_effort_bucket={},
        by_priority_band={},
    )
    recommendations_payload = empty_recommendations
    site_location_details = build_location_context(site)
    site_primary_location = _compact_workspace_text(
        site_location_details.primary_location,
        max_length=_WORKSPACE_PRIMARY_LOCATION_MAX_CHARS,
    )
    site_location_context = (
        _compact_workspace_text(
            site_location_details.location_context,
            max_length=_WORKSPACE_LOCATION_CONTEXT_MAX_CHARS,
        )
        or site_location_details.location_context
    )
    site_location_context_strength = site_location_details.location_context_strength
    site_location_context_source = site_location_details.location_context_source
    site_primary_business_zip = _compact_workspace_text(
        site_location_details.primary_business_zip,
        max_length=5,
    )

    if latest_completed_run is not None:
        recommendation_items = recommendation_service.list_recommendations(
            business_id=scoped_business_id,
            recommendation_run_id=latest_completed_run.id,
        )
        serialized_items = [SEORecommendationRead.model_validate(item) for item in recommendation_items]
        by_status, by_category, by_severity, by_effort_bucket, by_priority_band = _summarize_recommendation_items(
            serialized_items
        )
        recommendations_payload = SEORecommendationListResponse(
            items=serialized_items,
            total=len(serialized_items),
            by_status=by_status,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort_bucket,
            by_priority_band=by_priority_band,
        )
        workspace_audit_pages = _load_workspace_audit_pages_for_recommendations(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_audit_run_id=latest_completed_run.audit_run_id,
            seo_audit_repository=seo_audit_repository,
        )
        grouped_recommendations = _build_workspace_grouped_recommendations(
            recommendations=serialized_items,
        )
        try:
            latest_narrative = recommendation_narrative_service.get_latest_narrative(
                business_id=scoped_business_id,
                site_id=site_id,
                recommendation_run_id=latest_completed_run.id,
            )
            latest_narrative_read = SEORecommendationNarrativeRead.model_validate(latest_narrative)
            recommendation_ids = {item.id for item in serialized_items}
            tuning_suggestions = _extract_workspace_tuning_suggestions(
                sections_json=latest_narrative_read.sections_json,
                recommendation_ids=recommendation_ids,
            )
        except SEORecommendationNarrativeNotFoundError:
            latest_narrative_read = None

        apply_outcome = _build_workspace_apply_outcome(
            latest_applied_preview_event=latest_applied_preview_event,
            latest_run_status=latest_run.status if latest_run else None,
            latest_narrative_read=latest_narrative_read,
            recommendations=serialized_items,
            tuning_suggestions=tuning_suggestions,
        )
        try:
            recommendation_prompt_preview_data = recommendation_narrative_service.build_prompt_preview(
                business_id=scoped_business_id,
                site_id=site_id,
                recommendation_run_id=latest_completed_run.id,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to build recommendation prompt preview business_id=%s site_id=%s run_id=%s",
                scoped_business_id,
                site_id,
                latest_completed_run.id,
            )
            recommendation_prompt_preview_data = None
        if recommendation_prompt_preview_data is not None:
            recommendation_prompt_preview = build_ai_prompt_preview_read(
                prompt_type="recommendation",
                system_prompt=recommendation_prompt_preview_data.system_prompt,
                user_prompt=recommendation_prompt_preview_data.user_prompt,
                model=recommendation_prompt_preview_data.model_name,
                prompt_version=recommendation_prompt_preview_data.prompt_version,
                prompt_label=getattr(recommendation_prompt_preview_data, "prompt_label", None),
                source=recommendation_prompt_preview_data.prompt_source,
                prompt_metrics=getattr(recommendation_prompt_preview_data, "prompt_metrics", None),
            )
        eeat_gap_summary = _build_workspace_eeat_gap_summary(
            recommendations=serialized_items,
            latest_narrative_read=latest_narrative_read,
        )

    latest_competitor_runs = seo_competitor_profile_generation_repository.list_runs_for_business_site(
        scoped_business_id,
        site_id,
    )
    latest_competitor_run = latest_competitor_runs[0] if latest_competitor_runs else None
    if latest_competitor_run is not None:
        try:
            latest_competitor_run_detail = generation_service.get_run_detail(
                business_id=scoped_business_id,
                site_id=site_id,
                generation_run_id=latest_competitor_run.id,
            )
            if latest_competitor_run_detail.outcome_summary is not None:
                latest_competitor_outcome_summary = SEOCompetitorProfileOutcomeSummaryRead.model_validate(
                    latest_competitor_run_detail.outcome_summary
                )
            latest_competitor_drafts = [
                SEOCompetitorProfileDraftRead.model_validate(item)
                for item in (latest_competitor_run_detail.drafts or [])
            ]
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to build competitor run outcome summary for workspace business_id=%s site_id=%s run_id=%s",
                scoped_business_id,
                site_id,
                latest_competitor_run.id,
            )
    competitor_candidate_count = latest_competitor_runs[0].requested_candidate_count if latest_competitor_runs else 10
    try:
        competitor_prompt_preview_data = generation_service.build_prompt_preview(
            business_id=scoped_business_id,
            site_id=site_id,
            candidate_count=competitor_candidate_count,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to build competitor prompt preview business_id=%s site_id=%s",
            scoped_business_id,
            site_id,
        )
        competitor_prompt_preview_data = None
    if competitor_prompt_preview_data is not None:
        competitor_prompt_preview = build_ai_prompt_preview_read(
            prompt_type="competitor",
            system_prompt=competitor_prompt_preview_data.system_prompt,
            user_prompt=competitor_prompt_preview_data.user_prompt,
            model=competitor_prompt_preview_data.model_name,
            prompt_version=competitor_prompt_preview_data.prompt_version,
            prompt_label=competitor_prompt_preview_data.prompt_label,
            source=competitor_prompt_preview_data.prompt_source,
            prompt_metrics=competitor_prompt_preview_data.prompt_metrics,
        )
        trusted_site_context = (
            competitor_prompt_preview_data.trusted_site_context
            if isinstance(competitor_prompt_preview_data.trusted_site_context, dict)
            else {}
        )
        trusted_location_context = _compact_workspace_text(
            trusted_site_context.get("site_location_context"),
            max_length=_WORKSPACE_LOCATION_CONTEXT_MAX_CHARS,
        )
        if trusted_location_context is not None:
            site_location_context = trusted_location_context
        trusted_primary_location = _compact_workspace_text(
            trusted_site_context.get("site_primary_location"),
            max_length=_WORKSPACE_PRIMARY_LOCATION_MAX_CHARS,
        )
        if trusted_primary_location is not None:
            site_primary_location = trusted_primary_location
        trusted_zip = _compact_workspace_text(
            trusted_site_context.get("site_primary_business_zip"),
            max_length=5,
        )
        if trusted_zip is not None and len(trusted_zip) == 5 and trusted_zip.isdigit():
            site_primary_business_zip = trusted_zip
        trusted_strength = _normalize_workspace_location_context_strength(
            trusted_site_context.get("site_location_context_strength")
        )
        if trusted_strength != "unknown":
            site_location_context_strength = trusted_strength
        trusted_source = _normalize_workspace_location_context_source(
            trusted_site_context.get("site_location_context_source")
        )
        if trusted_source is not None:
            site_location_context_source = trusted_source

    competitor_context_health = _build_workspace_competitor_context_health(
        site_location_context_strength=site_location_context_strength,
        site_location_context_source=site_location_context_source,
        trusted_site_context=trusted_site_context,
    )

    if latest_run is None:
        state = "no_runs"
    elif latest_completed_run is None:
        state = "no_completed_runs"
    elif latest_narrative_read is None:
        state = "completed_no_narrative"
    else:
        state = "completed_with_narrative"

    analysis_generated_at = latest_completed_run.completed_at if latest_completed_run is not None else None
    last_apply_at = latest_applied_preview_event.applied_at if latest_applied_preview_event is not None else None
    analysis_freshness = _derive_workspace_analysis_freshness(
        analysis_generated_at=analysis_generated_at,
        last_apply_at=last_apply_at,
    )
    workspace_trust_summary = _build_workspace_trust_summary(
        latest_competitor_outcome_summary=latest_competitor_outcome_summary,
        latest_competitor_run_status=(latest_competitor_run.status if latest_competitor_run is not None else None),
        apply_outcome=apply_outcome,
        analysis_freshness=analysis_freshness,
    )
    competitor_section_freshness = _build_competitor_section_freshness(
        latest_competitor_run_status=(latest_competitor_run.status if latest_competitor_run is not None else None),
        latest_competitor_run_evaluated_at=(
            latest_competitor_run.updated_at
            if latest_competitor_run is not None
            else None
        ),
        latest_competitor_outcome_summary=latest_competitor_outcome_summary,
        apply_outcome=apply_outcome,
        analysis_freshness=analysis_freshness,
    )
    recommendation_section_freshness = _build_recommendation_section_freshness(
        latest_recommendation_run_status=(latest_run.status if latest_run is not None else None),
        latest_completed_recommendation_run_id=(latest_completed_run.id if latest_completed_run is not None else None),
        latest_recommendation_run_evaluated_at=(latest_run.updated_at if latest_run is not None else None),
        latest_completed_recommendation_run_evaluated_at=(
            latest_completed_run.completed_at if latest_completed_run is not None else None
        ),
        analysis_freshness=analysis_freshness,
        apply_outcome=apply_outcome,
    )
    applied_recommendation_ids = _extract_workspace_applied_recommendation_ids(
        latest_applied_preview_event=latest_applied_preview_event,
        recommendations=recommendations_payload.items,
        tuning_suggestions=tuning_suggestions,
    )
    recommendation_progress_metadata = _derive_workspace_recommendation_progress_metadata(
        recommendations=recommendations_payload.items,
        applied_recommendation_ids=applied_recommendation_ids,
        analysis_freshness=analysis_freshness,
    )
    draft_verification_status_by_id = _build_workspace_draft_verification_status_map(
        competitor_drafts=latest_competitor_drafts,
        site_domains=seo_competitor_repository.list_domains_for_business_site(
            scoped_business_id,
            site_id,
        ),
    )
    recommendation_competitor_linkage = _build_workspace_recommendation_competitor_linkage(
        recommendations=recommendations_payload.items,
        competitor_drafts=latest_competitor_drafts,
        draft_verification_status_by_id=draft_verification_status_by_id,
    )
    recommendation_action_deltas = _build_workspace_recommendation_action_deltas(
        recommendations=recommendations_payload.items,
        competitor_linkage_by_recommendation_id=recommendation_competitor_linkage,
    )
    recommendation_priorities = _build_workspace_recommendation_priorities(
        recommendations=recommendations_payload.items,
        competitor_linkage_by_recommendation_id=recommendation_competitor_linkage,
        action_delta_by_recommendation_id=recommendation_action_deltas,
    )
    recommendation_target_page_hints_by_id = _derive_workspace_recommendation_target_page_hints(
        recommendations=recommendations_payload.items,
        audit_pages=workspace_audit_pages,
    )
    recommendations_payload.items = [
        recommendation.model_copy(
            update={
                **recommendation_progress_metadata.get(recommendation.id, {}),
                **recommendation_competitor_linkage.get(recommendation.id, {}),
                **recommendation_action_deltas.get(recommendation.id, {}),
                **recommendation_priorities.get(recommendation.id, {}),
                "recommendation_target_page_hints": recommendation_target_page_hints_by_id.get(
                    recommendation.id,
                    [],
                ),
            }
        )
        for recommendation in recommendations_payload.items
    ]
    recommendations_payload.items = _attach_action_lineage_to_recommendations(
        recommendations=recommendations_payload.items,
        business_id=scoped_business_id,
        site_id=site_id,
        action_lineage_service=action_lineage_service,
    )
    if recommendations_payload.items:
        site_analytics_summary = seo_analytics_service.get_site_summary(
            business_id=scoped_business_id,
            site_id=site_id,
            site_domain=site.base_url or site.normalized_domain,
        )
        search_console_site_summary = seo_analytics_service.get_search_console_site_summary(
            business_id=scoped_business_id,
            site_id=site_id,
            search_console_property_url=site.search_console_property_url,
            search_console_enabled=bool(site.search_console_enabled),
        )
        recommendations_payload.items = _attach_measurement_context_to_recommendations(
            recommendations=recommendations_payload.items,
            site_analytics_summary=site_analytics_summary,
            search_console_site_summary=search_console_site_summary,
            seo_analytics_service=seo_analytics_service,
            site_domain=site.base_url or site.normalized_domain,
            search_console_property_url=site.search_console_property_url,
            search_console_enabled=bool(site.search_console_enabled),
        )
    ordering_explanation = _build_workspace_ordering_explanation(
        recommendations=recommendations_payload.items,
        analysis_freshness=analysis_freshness,
    )
    start_here = _build_workspace_start_here(
        recommendations=recommendations_payload.items,
        grouped_recommendations=grouped_recommendations,
        analysis_freshness=analysis_freshness,
    )

    return SEORecommendationWorkspaceSummaryRead(
        business_id=scoped_business_id,
        site_id=site_id,
        state=state,
        latest_run=(SEORecommendationRunRead.model_validate(latest_run) if latest_run else None),
        latest_completed_run=(
            SEORecommendationRunRead.model_validate(latest_completed_run) if latest_completed_run else None
        ),
        recommendations=recommendations_payload,
        grouped_recommendations=grouped_recommendations,
        latest_narrative=latest_narrative_read,
        tuning_suggestions=tuning_suggestions,
        apply_outcome=apply_outcome,
        workspace_trust_summary=workspace_trust_summary,
        competitor_section_freshness=competitor_section_freshness,
        recommendation_section_freshness=recommendation_section_freshness,
        analysis_freshness=analysis_freshness,
        ordering_explanation=ordering_explanation,
        start_here=start_here,
        eeat_gap_summary=eeat_gap_summary,
        competitor_context_health=competitor_context_health,
        competitor_prompt_preview=competitor_prompt_preview,
        recommendation_prompt_preview=recommendation_prompt_preview,
        site_location_context=site_location_context,
        site_primary_location=site_primary_location,
        site_primary_business_zip=site_primary_business_zip,
        site_location_context_strength=site_location_context_strength,
        site_location_context_source=site_location_context_source,
    )


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}",
    response_model=SEORecommendationRunRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}",
    response_model=SEORecommendationRunRead,
)
def get_seo_recommendation_run(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = recommendation_service.get_run(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="SEO recommendation run not found",
    )
    return SEORecommendationRunRead.model_validate(run)


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations",
    response_model=SEORecommendationListResponse,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations",
    response_model=SEORecommendationListResponse,
)
def list_seo_recommendations_for_run(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> SEORecommendationListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = recommendation_service.get_run(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
        items = recommendation_service.list_recommendations(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="SEO recommendation run not found",
    )
    serialized_items = [SEORecommendationRead.model_validate(item) for item in items]
    serialized_items = _attach_action_lineage_to_recommendations(
        recommendations=serialized_items,
        business_id=scoped_business_id,
        site_id=site_id,
        action_lineage_service=action_lineage_service,
    )
    site_analytics_summary = seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=site.base_url or site.normalized_domain,
    )
    search_console_site_summary = seo_analytics_service.get_search_console_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    serialized_items = _attach_measurement_context_to_recommendations(
        recommendations=serialized_items,
        site_analytics_summary=site_analytics_summary,
        search_console_site_summary=search_console_site_summary,
        seo_analytics_service=seo_analytics_service,
        site_domain=site.base_url or site.normalized_domain,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    by_status, by_category, by_severity, by_effort_bucket, by_priority_band = _summarize_recommendation_items(
        serialized_items
    )
    return SEORecommendationListResponse(
        items=serialized_items,
        total=len(serialized_items),
        by_status=by_status,
        by_category=by_category,
        by_severity=by_severity,
        by_effort_bucket=by_effort_bucket,
        by_priority_band=by_priority_band,
    )


@router.get("/sites/{site_id}/recommendations", response_model=SEORecommendationListResponse)
@router_v1.get("/sites/{site_id}/recommendations", response_model=SEORecommendationListResponse)
def list_seo_recommendations(
    business_id: str,
    site_id: str,
    query: SEORecommendationListQuery = Depends(),
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> SEORecommendationListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        page_result = recommendation_service.list_site_recommendations(
            business_id=scoped_business_id,
            site_id=site_id,
            query=query,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    serialized_items = [SEORecommendationRead.model_validate(item) for item in page_result.items]
    serialized_items = _attach_action_lineage_to_recommendations(
        recommendations=serialized_items,
        business_id=scoped_business_id,
        site_id=site_id,
        action_lineage_service=action_lineage_service,
    )
    site_analytics_summary = seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=site.base_url or site.normalized_domain,
    )
    search_console_site_summary = seo_analytics_service.get_search_console_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    serialized_items = _attach_measurement_context_to_recommendations(
        recommendations=serialized_items,
        site_analytics_summary=site_analytics_summary,
        search_console_site_summary=search_console_site_summary,
        seo_analytics_service=seo_analytics_service,
        site_domain=site.base_url or site.normalized_domain,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    filtered_summary = SEORecommendationFilteredSummary(
        total=page_result.total,
        open=page_result.by_status.get("open", 0),
        accepted=page_result.by_status.get("accepted", 0),
        dismissed=page_result.by_status.get("dismissed", 0),
        high_priority=page_result.by_priority_band.get("high", 0) + page_result.by_priority_band.get("critical", 0),
    )
    return SEORecommendationListResponse(
        items=serialized_items,
        total=page_result.total,
        filtered_summary=filtered_summary,
        by_status=page_result.by_status,
        by_category=page_result.by_category,
        by_severity=page_result.by_severity,
        by_effort_bucket=page_result.by_effort_bucket,
        by_priority_band=page_result.by_priority_band,
    )


@router.patch("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
@router_v1.patch("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
def patch_seo_recommendation(
    business_id: str,
    site_id: str,
    recommendation_id: str,
    payload: SEORecommendationWorkflowUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> SEORecommendationRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        recommendation = recommendation_service.update_recommendation_workflow(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_id=recommendation_id,
            payload=payload,
            updated_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    serialized_recommendation = SEORecommendationRead.model_validate(recommendation)
    serialized_with_lineage = _attach_action_lineage_to_recommendations(
        recommendations=[serialized_recommendation],
        business_id=scoped_business_id,
        site_id=site_id,
        action_lineage_service=action_lineage_service,
    )
    site_analytics_summary = seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=site.base_url or site.normalized_domain,
    )
    search_console_site_summary = seo_analytics_service.get_search_console_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    serialized_with_measurement = _attach_measurement_context_to_recommendations(
        recommendations=serialized_with_lineage,
        site_analytics_summary=site_analytics_summary,
        search_console_site_summary=search_console_site_summary,
        seo_analytics_service=seo_analytics_service,
        site_domain=site.base_url or site.normalized_domain,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    return serialized_with_measurement[0]


@router.get("/sites/{site_id}/actions/{action_id}/next-actions", response_model=list[NextActionDraft])
@router_v1.get("/sites/{site_id}/actions/{action_id}/next-actions", response_model=list[NextActionDraft])
def list_chained_next_actions(
    business_id: str,
    site_id: str,
    action_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> list[NextActionDraft]:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        return recommendation_service.list_chained_action_drafts(
            business_id=scoped_business_id,
            site_id=site_id,
            source_action_id=action_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/sites/{site_id}/actions/{action_id}/lineage", response_model=ActionLineageResponse)
@router_v1.get("/sites/{site_id}/actions/{action_id}/lineage", response_model=ActionLineageResponse)
def get_action_lineage(
    business_id: str,
    site_id: str,
    action_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> ActionLineageResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        return action_lineage_service.get_action_lineage(
            business_id=scoped_business_id,
            site_id=site_id,
            source_action_id=action_id,
        )
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/sites/{site_id}/actions/{action_id}/next-actions/{draft_id}/activate",
    response_model=NextActionDraft,
)
@router_v1.post(
    "/sites/{site_id}/actions/{action_id}/next-actions/{draft_id}/activate",
    response_model=NextActionDraft,
)
def activate_chained_next_action(
    business_id: str,
    site_id: str,
    action_id: str,
    draft_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    action_chain_activation_service: ActionChainActivationService = Depends(get_action_chain_activation_service),
) -> NextActionDraft:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = action_chain_activation_service.activate_chained_action_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            source_action_id=action_id,
            draft_id=draft_id,
            actor_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOActionChainDraftNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOActionChainActivationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return result.draft


@router.post(
    "/sites/{site_id}/actions/execution-items/{execution_item_id}/bind-automation",
    response_model=BoundActionAutomationRead,
)
@router_v1.post(
    "/sites/{site_id}/actions/execution-items/{execution_item_id}/bind-automation",
    response_model=BoundActionAutomationRead,
)
def bind_action_execution_item_automation(
    business_id: str,
    site_id: str,
    execution_item_id: str,
    payload: BindActionAutomationRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    action_automation_binding_service: ActionAutomationBindingService = Depends(get_action_automation_binding_service),
) -> BoundActionAutomationRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = action_automation_binding_service.bind_activated_action_to_automation(
            business_id=scoped_business_id,
            site_id=site_id,
            action_execution_item_id=execution_item_id,
            automation_id=payload.automation_id,
            actor_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOActionAutomationBindingNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOActionAutomationBindingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except SEOActionAutomationBindingConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return result.binding


@router.post(
    "/sites/{site_id}/actions/execution-items/{execution_item_id}/run-automation",
    response_model=RequestedActionAutomationExecutionRead,
)
@router_v1.post(
    "/sites/{site_id}/actions/execution-items/{execution_item_id}/run-automation",
    response_model=RequestedActionAutomationExecutionRead,
)
def request_action_execution_item_automation_run(
    business_id: str,
    site_id: str,
    execution_item_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    action_automation_execution_service: ActionAutomationExecutionService = Depends(get_action_automation_execution_service),
) -> RequestedActionAutomationExecutionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = action_automation_execution_service.request_bound_action_automation_execution(
            business_id=scoped_business_id,
            site_id=site_id,
            action_execution_item_id=execution_item_id,
            actor_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOActionAutomationExecutionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOActionAutomationExecutionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return result.execution


@router.get("/sites/{site_id}/recommendations/backlog", response_model=SEORecommendationBacklogRead)
@router_v1.get("/sites/{site_id}/recommendations/backlog", response_model=SEORecommendationBacklogRead)
def get_seo_recommendation_backlog(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationBacklogRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        backlog = recommendation_service.get_backlog(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationBacklogRead(
        business_id=backlog.business_id,
        site_id=backlog.site_id,
        total_actionable=len(backlog.items),
        items=[SEORecommendationRead.model_validate(item) for item in backlog.items],
    )


@router.get(
    "/sites/{site_id}/recommendations/prioritized-report", response_model=SEORecommendationPrioritizedReportRead
)
@router_v1.get(
    "/sites/{site_id}/recommendations/prioritized-report",
    response_model=SEORecommendationPrioritizedReportRead,
)
def get_seo_recommendation_prioritized_report(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
) -> SEORecommendationPrioritizedReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        report = recommendation_service.get_prioritized_report(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    backlog_items = [SEORecommendationRead.model_validate(item) for item in report.backlog_items]
    backlog_by_status, backlog_by_category, backlog_by_severity, backlog_by_effort, backlog_by_priority = (
        _summarize_recommendation_items(backlog_items)
    )
    return SEORecommendationPrioritizedReportRead(
        business_id=report.business_id,
        site_id=report.site_id,
        generated_at=report.generated_at,
        total_recommendations=report.total_recommendations,
        backlog_total=len(backlog_items),
        by_status=report.by_status,
        by_category=report.by_category,
        by_severity=report.by_severity,
        by_effort_bucket=report.by_effort_bucket,
        by_priority_band=report.by_priority_band,
        backlog=SEORecommendationListResponse(
            items=backlog_items,
            total=len(backlog_items),
            by_status=backlog_by_status,
            by_category=backlog_by_category,
            by_severity=backlog_by_severity,
            by_effort_bucket=backlog_by_effort,
            by_priority_band=backlog_by_priority,
        ),
    )


@router.get("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
@router_v1.get("/sites/{site_id}/recommendations/{recommendation_id}", response_model=SEORecommendationRead)
def get_seo_recommendation(
    business_id: str,
    site_id: str,
    recommendation_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> SEORecommendationRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        recommendation = recommendation_service.get_recommendation(
            business_id=scoped_business_id,
            recommendation_id=recommendation_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=recommendation.site_id,
        detail="SEO recommendation not found",
    )
    serialized_recommendation = SEORecommendationRead.model_validate(recommendation)
    serialized_with_lineage = _attach_action_lineage_to_recommendations(
        recommendations=[serialized_recommendation],
        business_id=scoped_business_id,
        site_id=site_id,
        action_lineage_service=action_lineage_service,
    )
    site_analytics_summary = seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=site.base_url or site.normalized_domain,
    )
    search_console_site_summary = seo_analytics_service.get_search_console_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    serialized_with_measurement = _attach_measurement_context_to_recommendations(
        recommendations=serialized_with_lineage,
        site_analytics_summary=site_analytics_summary,
        search_console_site_summary=search_console_site_summary,
        seo_analytics_service=seo_analytics_service,
        site_domain=site.base_url or site.normalized_domain,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    return serialized_with_measurement[0]


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report",
    response_model=SEORecommendationRunReportRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report",
    response_model=SEORecommendationRunReportRead,
)
def get_seo_recommendation_run_report(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_service: SEORecommendationService = Depends(get_seo_recommendation_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
    action_lineage_service: ActionLineageService = Depends(get_action_lineage_service),
) -> SEORecommendationRunReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        report = recommendation_service.get_report(
            business_id=scoped_business_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (SEOSiteNotFoundError, SEORecommendationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=report.run.site_id,
        detail="SEO recommendation run not found",
    )
    serialized_items = [SEORecommendationRead.model_validate(item) for item in report.recommendations]
    serialized_items = _attach_action_lineage_to_recommendations(
        recommendations=serialized_items,
        business_id=scoped_business_id,
        site_id=site_id,
        action_lineage_service=action_lineage_service,
    )
    site_analytics_summary = seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=site.base_url or site.normalized_domain,
    )
    search_console_site_summary = seo_analytics_service.get_search_console_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    serialized_items = _attach_measurement_context_to_recommendations(
        recommendations=serialized_items,
        site_analytics_summary=site_analytics_summary,
        search_console_site_summary=search_console_site_summary,
        seo_analytics_service=seo_analytics_service,
        site_domain=site.base_url or site.normalized_domain,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )
    by_status, by_category, by_severity, by_effort_bucket, by_priority_band = _summarize_recommendation_items(
        serialized_items
    )
    return SEORecommendationRunReportRead(
        recommendation_run=SEORecommendationRunRead.model_validate(report.run),
        rollups={
            "by_category": report.by_category,
            "by_severity": report.by_severity,
            "by_effort_bucket": report.by_effort_bucket,
        },
        recommendations=SEORecommendationListResponse(
            items=serialized_items,
            total=len(serialized_items),
            by_status=by_status,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort_bucket,
            by_priority_band=by_priority_band,
        ),
    )


@router.post(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_seo_recommendation_narrative(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = recommendation_narrative_service.summarize_run(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationNarrativeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEORecommendationNarrativeRead.model_validate(result.narrative)


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeListResponse,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives",
    response_model=SEORecommendationNarrativeListResponse,
)
def list_seo_recommendation_narratives(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = recommendation_narrative_service.list_narratives(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationNarrativeListResponse(
        items=[SEORecommendationNarrativeRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest",
    response_model=SEORecommendationNarrativeRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest",
    response_model=SEORecommendationNarrativeRead,
)
def get_latest_seo_recommendation_narrative(
    business_id: str,
    site_id: str,
    recommendation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        narrative = recommendation_narrative_service.get_latest_narrative(
            business_id=scoped_business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationNarrativeRead.model_validate(narrative)


@router.get(
    "/sites/{site_id}/recommendation-narratives/{narrative_id}",
    response_model=SEORecommendationNarrativeRead,
)
@router_v1.get(
    "/sites/{site_id}/recommendation-narratives/{narrative_id}",
    response_model=SEORecommendationNarrativeRead,
)
def get_seo_recommendation_narrative(
    business_id: str,
    site_id: str,
    narrative_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationNarrativeRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        narrative = recommendation_narrative_service.get_narrative(
            business_id=scoped_business_id,
            site_id=site_id,
            narrative_id=narrative_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEORecommendationNarrativeRead.model_validate(narrative)


@router.post(
    "/sites/{site_id}/recommendations/tuning-preview",
    response_model=SEORecommendationTuningImpactPreviewRead,
)
@router_v1.post(
    "/sites/{site_id}/recommendations/tuning-preview",
    response_model=SEORecommendationTuningImpactPreviewRead,
)
def preview_seo_recommendation_tuning_impact(
    business_id: str,
    site_id: str,
    payload: SEORecommendationTuningImpactPreviewRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    recommendation_narrative_service: SEORecommendationNarrativeService = Depends(
        get_seo_recommendation_narrative_service
    ),
) -> SEORecommendationTuningImpactPreviewRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = recommendation_narrative_service.preview_tuning_impact(
            business_id=scoped_business_id,
            site_id=site_id,
            current_values_overrides=(
                payload.current_values.model_dump(exclude_none=True) if payload.current_values else {}
            ),
            proposed_values_overrides=payload.proposed_values.model_dump(exclude_none=True),
            recommendation_run_id=payload.recommendation_run_id,
            narrative_id=payload.narrative_id,
        )
    except (
        SEOSiteNotFoundError,
        SEORecommendationNarrativeNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEORecommendationNarrativeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEORecommendationTuningImpactPreviewRead.model_validate(result.__dict__)


@router.post(
    "/sites/{site_id}/automation-config",
    response_model=SEOAutomationConfigRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/automation-config",
    response_model=SEOAutomationConfigRead,
    status_code=status.HTTP_201_CREATED,
)
def create_or_replace_seo_automation_config(
    business_id: str,
    site_id: str,
    payload: SEOAutomationConfigUpsertRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.create_or_replace_config(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.get("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
@router_v1.get("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
def get_seo_automation_config(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.get_config(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.patch("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
@router_v1.patch("/sites/{site_id}/automation-config", response_model=SEOAutomationConfigRead)
def patch_seo_automation_config(
    business_id: str,
    site_id: str,
    payload: SEOAutomationConfigPatchRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.update_config(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.post("/sites/{site_id}/automation-config/enable", response_model=SEOAutomationConfigRead)
@router_v1.post("/sites/{site_id}/automation-config/enable", response_model=SEOAutomationConfigRead)
def enable_seo_automation_config(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.set_config_enabled(
            business_id=scoped_business_id,
            site_id=site_id,
            is_enabled=True,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.post("/sites/{site_id}/automation-config/disable", response_model=SEOAutomationConfigRead)
@router_v1.post("/sites/{site_id}/automation-config/disable", response_model=SEOAutomationConfigRead)
def disable_seo_automation_config(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationConfigRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config = automation_service.set_config_enabled(
            business_id=scoped_business_id,
            site_id=site_id,
            is_enabled=False,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationConfigRead.model_validate(config)


@router.post(
    "/sites/{site_id}/automation-runs",
    response_model=SEOAutomationRunRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/automation-runs",
    response_model=SEOAutomationRunRead,
    status_code=status.HTTP_201_CREATED,
)
def trigger_seo_automation_run(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = automation_service.trigger_manual_run(
            business_id=scoped_business_id,
            site_id=site_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOAutomationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SEOAutomationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOAutomationRunRead.model_validate(run)


@router.get("/sites/{site_id}/automation-runs", response_model=SEOAutomationRunListResponse)
@router_v1.get("/sites/{site_id}/automation-runs", response_model=SEOAutomationRunListResponse)
def list_seo_automation_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = automation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationRunListResponse(
        items=[SEOAutomationRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/sites/{site_id}/automation-runs/{automation_run_id}", response_model=SEOAutomationRunRead)
@router_v1.get("/sites/{site_id}/automation-runs/{automation_run_id}", response_model=SEOAutomationRunRead)
def get_seo_automation_run(
    business_id: str,
    site_id: str,
    automation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = automation_service.get_run(
            business_id=scoped_business_id,
            site_id=site_id,
            automation_run_id=automation_run_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationRunRead.model_validate(run)


@router.get("/sites/{site_id}/automation-status", response_model=SEOAutomationStatusRead)
@router_v1.get("/sites/{site_id}/automation-status", response_model=SEOAutomationStatusRead)
def get_seo_automation_status(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    automation_service: SEOAutomationService = Depends(get_seo_automation_service),
) -> SEOAutomationStatusRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        config, latest_run = automation_service.get_status(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOAutomationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOAutomationStatusRead(
        business_id=scoped_business_id,
        site_id=site_id,
        config=SEOAutomationConfigRead.model_validate(config),
        latest_run=SEOAutomationRunRead.model_validate(latest_run) if latest_run is not None else None,
    )


@router.get("/sites/{site_id}/analytics/site-summary", response_model=SEOAnalyticsSiteSummaryRead)
@router_v1.get("/sites/{site_id}/analytics/site-summary", response_model=SEOAnalyticsSiteSummaryRead)
def get_site_analytics_summary(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
) -> SEOAnalyticsSiteSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=(site.normalized_domain or site.base_url or "").strip() or None,
    )


@router.get(
    "/sites/{site_id}/analytics/search-visibility-summary",
    response_model=SEOSearchConsoleSiteSummaryRead,
)
@router_v1.get(
    "/sites/{site_id}/analytics/search-visibility-summary",
    response_model=SEOSearchConsoleSiteSummaryRead,
)
def get_site_search_console_summary(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
) -> SEOSearchConsoleSiteSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return seo_analytics_service.get_search_console_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        search_console_property_url=site.search_console_property_url,
        search_console_enabled=bool(site.search_console_enabled),
    )


@router.get("/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetListResponse)
@router_v1.get("/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetListResponse)
def list_competitor_sets(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_sets(business_id=scoped_business_id, site_id=site_id)
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSetListResponse(
        items=[SEOCompetitorSetRead.model_validate(item) for item in items],
        total=len(items),
    )


def _to_competitor_profile_generation_run_detail_response(
    *,
    run,
    drafts,
    rejected_candidate_count: int = 0,
    rejected_candidates=None,
    tuning_rejected_candidate_count: int = 0,
    tuning_rejected_candidates=None,
    tuning_rejection_reason_counts=None,
    candidate_pipeline_summary=None,
    outcome_summary=None,
    provider_attempt_count: int = 0,
    provider_degraded_retry_used: bool = False,
    provider_attempts=None,
) -> SEOCompetitorProfileGenerationRunDetailRead:
    serialized_drafts = [SEOCompetitorProfileDraftRead.model_validate(item) for item in drafts]
    serialized_rejected_candidates = [
        SEOCompetitorProfileRejectedCandidateRead.model_validate(item) for item in (rejected_candidates or [])
    ]
    serialized_tuning_rejected_candidates = [
        SEOCompetitorProfileTuningRejectedCandidateRead.model_validate(item)
        for item in (tuning_rejected_candidates or [])
    ]
    return SEOCompetitorProfileGenerationRunDetailRead(
        run=SEOCompetitorProfileGenerationRunRead.model_validate(run),
        drafts=serialized_drafts,
        total_drafts=len(serialized_drafts),
        rejected_candidate_count=max(0, int(rejected_candidate_count)),
        rejected_candidates=serialized_rejected_candidates,
        tuning_rejected_candidate_count=max(0, int(tuning_rejected_candidate_count)),
        tuning_rejected_candidates=serialized_tuning_rejected_candidates,
        tuning_rejection_reason_counts=(
            dict(tuning_rejection_reason_counts) if isinstance(tuning_rejection_reason_counts, dict) else {}
        ),
        candidate_pipeline_summary=(
            SEOCompetitorProfileCandidatePipelineSummaryRead.model_validate(candidate_pipeline_summary)
            if candidate_pipeline_summary is not None
            else None
        ),
        outcome_summary=outcome_summary,
        provider_attempt_count=max(0, int(provider_attempt_count)),
        provider_degraded_retry_used=bool(provider_degraded_retry_used),
        provider_attempts=list(provider_attempts or []),
    )


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_profile_generation_run(
    business_id: str,
    site_id: str,
    payload: SEOCompetitorProfileGenerationRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
    generation_run_executor: SEOCompetitorProfileGenerationRunExecutor = Depends(
        get_seo_competitor_profile_generation_run_executor
    ),
) -> SEOCompetitorProfileGenerationRunDetailRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = generation_service.create_run(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    background_tasks.add_task(
        generation_run_executor,
        scoped_business_id,
        site_id,
        result.run.id,
    )
    return _to_competitor_profile_generation_run_detail_response(
        run=result.run,
        drafts=result.drafts,
        rejected_candidate_count=result.rejected_candidate_count,
        rejected_candidates=result.rejected_candidates,
        tuning_rejected_candidate_count=result.tuning_rejected_candidate_count,
        tuning_rejected_candidates=result.tuning_rejected_candidates,
        tuning_rejection_reason_counts=result.tuning_rejection_reason_counts,
        candidate_pipeline_summary=result.candidate_pipeline_summary,
        outcome_summary=result.outcome_summary,
        provider_attempt_count=result.provider_attempt_count,
        provider_degraded_retry_used=result.provider_degraded_retry_used,
        provider_attempts=result.provider_attempts,
    )


@router.get(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunListResponse,
)
@router_v1.get(
    "/sites/{site_id}/competitor-profile-generation-runs",
    response_model=SEOCompetitorProfileGenerationRunListResponse,
)
def list_competitor_profile_generation_runs(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
) -> SEOCompetitorProfileGenerationRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = generation_service.list_runs(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorProfileGenerationRunListResponse(
        items=[SEOCompetitorProfileGenerationRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/sites/{site_id}/competitor-profile-generation-runs/summary",
    response_model=SEOCompetitorProfileGenerationObservabilitySummaryRead,
)
@router_v1.get(
    "/sites/{site_id}/competitor-profile-generation-runs/summary",
    response_model=SEOCompetitorProfileGenerationObservabilitySummaryRead,
)
def get_competitor_profile_generation_runs_summary(
    business_id: str,
    site_id: str,
    lookback_days: int | None = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
) -> SEOCompetitorProfileGenerationObservabilitySummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        summary = generation_service.get_observability_summary(
            business_id=scoped_business_id,
            site_id=site_id,
            lookback_days=lookback_days,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return SEOCompetitorProfileGenerationObservabilitySummaryRead(
        business_id=scoped_business_id,
        site_id=site_id,
        lookback_days=summary.lookback_days,
        window_start=summary.window_start,
        window_end=summary.window_end,
        queued_count=summary.queued_count,
        running_count=summary.running_count,
        completed_count=summary.completed_count,
        failed_count=summary.failed_count,
        retry_child_runs=summary.retry_child_runs,
        retried_parent_runs=summary.retried_parent_runs,
        failed_runs_retried=summary.failed_runs_retried,
        failure_category_counts=summary.failure_category_counts,
        total_runs=summary.total_runs,
        total_raw_candidate_count=summary.total_raw_candidate_count,
        total_included_candidate_count=summary.total_included_candidate_count,
        total_excluded_candidate_count=summary.total_excluded_candidate_count,
        exclusion_counts_by_reason=summary.exclusion_counts_by_reason,
        preview_accuracy_rate=summary.preview_accuracy_rate,
        avg_error_margin=summary.avg_error_margin,
        last_n_preview_accuracy=summary.last_n_preview_accuracy,
        latest_run_created_at=summary.latest_run_created_at,
        latest_run_completed_at=summary.latest_run_completed_at,
        latest_completed_run_completed_at=summary.latest_completed_run_completed_at,
        latest_failed_run_completed_at=summary.latest_failed_run_completed_at,
    )


@router.get(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
)
@router_v1.get(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
)
def get_competitor_profile_generation_run_detail(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
) -> SEOCompetitorProfileGenerationRunDetailRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        detail = generation_service.get_run_detail(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_competitor_profile_generation_run_detail_response(
        run=detail.run,
        drafts=detail.drafts,
        rejected_candidate_count=detail.rejected_candidate_count,
        rejected_candidates=detail.rejected_candidates,
        tuning_rejected_candidate_count=detail.tuning_rejected_candidate_count,
        tuning_rejected_candidates=detail.tuning_rejected_candidates,
        tuning_rejection_reason_counts=detail.tuning_rejection_reason_counts,
        candidate_pipeline_summary=detail.candidate_pipeline_summary,
        outcome_summary=detail.outcome_summary,
        provider_attempt_count=detail.provider_attempt_count,
        provider_degraded_retry_used=detail.provider_degraded_retry_used,
        provider_attempts=detail.provider_attempts,
    )


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/retry",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/retry",
    response_model=SEOCompetitorProfileGenerationRunDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def retry_competitor_profile_generation_run(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    background_tasks: BackgroundTasks,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
    generation_run_executor: SEOCompetitorProfileGenerationRunExecutor = Depends(
        get_seo_competitor_profile_generation_run_executor
    ),
) -> SEOCompetitorProfileGenerationRunDetailRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = generation_service.retry_failed_run(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    background_tasks.add_task(
        generation_run_executor,
        scoped_business_id,
        site_id,
        result.run.id,
    )
    return _to_competitor_profile_generation_run_detail_response(
        run=result.run,
        drafts=result.drafts,
        rejected_candidate_count=result.rejected_candidate_count,
        rejected_candidates=result.rejected_candidates,
        tuning_rejected_candidate_count=result.tuning_rejected_candidate_count,
        tuning_rejected_candidates=result.tuning_rejected_candidates,
        tuning_rejection_reason_counts=result.tuning_rejection_reason_counts,
        candidate_pipeline_summary=result.candidate_pipeline_summary,
        outcome_summary=result.outcome_summary,
        provider_attempt_count=result.provider_attempt_count,
        provider_degraded_retry_used=result.provider_degraded_retry_used,
        provider_attempts=result.provider_attempts,
    )


@router.patch(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}",
    response_model=SEOCompetitorProfileDraftRead,
)
@router_v1.patch(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}",
    response_model=SEOCompetitorProfileDraftRead,
)
def edit_competitor_profile_generation_draft(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    draft_id: str,
    payload: SEOCompetitorProfileDraftEditRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
) -> SEOCompetitorProfileDraftRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        draft = generation_service.edit_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
            payload=payload,
            reviewed_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorProfileDraftRead.model_validate(draft)


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/reject",
    response_model=SEOCompetitorProfileDraftRead,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/reject",
    response_model=SEOCompetitorProfileDraftRead,
)
def reject_competitor_profile_generation_draft(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    draft_id: str,
    payload: SEOCompetitorProfileDraftRejectRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
) -> SEOCompetitorProfileDraftRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        draft = generation_service.reject_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
            payload=payload,
            reviewed_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorProfileDraftRead.model_validate(draft)


@router.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/accept",
    response_model=SEOCompetitorProfileDraftRead,
)
@router_v1.post(
    "/sites/{site_id}/competitor-profile-generation-runs/{generation_run_id}/drafts/{draft_id}/accept",
    response_model=SEOCompetitorProfileDraftRead,
)
def accept_competitor_profile_generation_draft(
    business_id: str,
    site_id: str,
    generation_run_id: str,
    draft_id: str,
    payload: SEOCompetitorProfileDraftAcceptRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    generation_service: SEOCompetitorProfileGenerationService = Depends(get_seo_competitor_profile_generation_service),
) -> SEOCompetitorProfileDraftRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        result = generation_service.accept_draft(
            business_id=scoped_business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
            payload=payload,
            reviewed_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorProfileGenerationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorProfileGenerationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorProfileDraftRead.model_validate(result.draft)


@router.post(
    "/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetRead, status_code=status.HTTP_201_CREATED
)
@router_v1.post(
    "/sites/{site_id}/competitor-sets", response_model=SEOCompetitorSetRead, status_code=status.HTTP_201_CREATED
)
def create_competitor_set(
    business_id: str,
    site_id: str,
    payload: SEOCompetitorSetCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_set = seo_competitor_service.create_set(
            business_id=scoped_business_id,
            site_id=site_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router.get("/competitor-sets/{set_id}", response_model=SEOCompetitorSetRead)
def get_competitor_set(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router.patch("/competitor-sets/{set_id}", response_model=SEOCompetitorSetRead)
def patch_competitor_set(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorSetUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_set = seo_competitor_service.update_set(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router.get("/competitor-sets/{set_id}/domains", response_model=SEOCompetitorDomainListResponse)
def list_competitor_domains(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_domains(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorDomainListResponse(
        items=[SEOCompetitorDomainRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/competitor-sets/{set_id}/domains", response_model=SEOCompetitorDomainRead, status_code=status.HTTP_201_CREATED
)
def add_competitor_domain(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorDomainCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        competitor_domain = seo_competitor_service.add_domain(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorDomainRead.model_validate(competitor_domain)


@router.delete(
    "/competitor-sets/{set_id}/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def remove_competitor_domain(
    business_id: str,
    set_id: str,
    domain_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> Response:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_competitor_service.remove_domain(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            domain_id=domain_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/competitor-sets/{set_id}/snapshot-runs",
    response_model=SEOCompetitorSnapshotRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_snapshot_run(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorSnapshotRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        snapshot_run = seo_competitor_service.create_snapshot_run(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router.get("/competitor-sets/{set_id}/snapshot-runs", response_model=SEOCompetitorSnapshotRunListResponse)
def list_competitor_snapshot_runs(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_snapshot_runs(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSnapshotRunListResponse(
        items=[SEOCompetitorSnapshotRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/snapshot-runs/{run_id}", response_model=SEOCompetitorSnapshotRunRead)
def get_competitor_snapshot_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        snapshot_run = seo_competitor_service.get_snapshot_run(
            business_id=scoped_business_id,
            snapshot_run_id=run_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router.get("/snapshot-runs/{run_id}/pages", response_model=SEOCompetitorSnapshotPageListResponse)
def list_competitor_snapshot_pages(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotPageListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = seo_competitor_service.list_snapshot_pages(
            business_id=scoped_business_id,
            snapshot_run_id=run_id,
        )
    except SEOCompetitorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorSnapshotPageListResponse(
        items=[SEOCompetitorSnapshotPageRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/competitor-sets/{set_id}/comparison-runs",
    response_model=SEOCompetitorComparisonRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_comparison_run(
    business_id: str,
    set_id: str,
    payload: SEOCompetitorComparisonRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = comparison_service.run_comparison(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorComparisonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunRead.model_validate(result.run)


@router.get("/competitor-sets/{set_id}/comparison-runs", response_model=SEOCompetitorComparisonRunListResponse)
def list_competitor_comparison_runs(
    business_id: str,
    set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = comparison_service.list_runs(
            business_id=scoped_business_id,
            competitor_set_id=set_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunListResponse(
        items=[SEOCompetitorComparisonRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/comparison-runs/{run_id}", response_model=SEOCompetitorComparisonRunRead)
def get_competitor_comparison_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunRead.model_validate(run)


@router.get("/comparison-runs/{run_id}/findings", response_model=SEOCompetitorComparisonFindingListResponse)
def list_competitor_comparison_findings(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonFindingListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        findings = comparison_service.list_findings(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    by_category, by_severity = comparison_service.summarize_findings(findings=findings)
    return SEOCompetitorComparisonFindingListResponse(
        items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in findings],
        total=len(findings),
        by_category=by_category,
        by_severity=by_severity,
    )


@router.get("/comparison-runs/{run_id}/report", response_model=SEOCompetitorComparisonReportRead)
def get_competitor_comparison_report(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        report = comparison_service.get_report(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorComparisonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    metric_rollups = []
    for metric_key in sorted(report.metric_rollups):
        metric = report.metric_rollups[metric_key]
        metric_rollups.append(
            SEOCompetitorComparisonMetricRollupRead(
                key=metric_key,
                title=str(metric.get("title", metric_key)),
                category=str(metric.get("category", "TECHNICAL")),
                unit=str(metric.get("unit", "count")),
                higher_is_better=bool(metric.get("higher_is_better", False)),
                client_value=int(metric.get("client_value", 0)),
                competitor_value=int(metric.get("competitor_value", 0)),
                delta=int(metric.get("delta", 0)),
                severity=str(metric.get("severity", "INFO")),
                gap_direction=str(metric.get("gap_direction", "unknown")),
            )
        )
    return SEOCompetitorComparisonReportRead(
        run=SEOCompetitorComparisonRunRead.model_validate(report.run),
        rollups=SEOCompetitorComparisonRunRollupsRead(
            client_pages_analyzed=report.run.client_pages_analyzed,
            competitor_pages_analyzed=report.run.competitor_pages_analyzed,
            findings_by_type=report.findings_by_type,
            findings_by_category=report.findings_by_category,
            findings_by_severity=report.findings_by_severity,
            metric_rollups=metric_rollups,
        ),
        findings=SEOCompetitorComparisonFindingListResponse(
            items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in report.findings],
            total=len(report.findings),
            by_category=report.findings_by_category,
            by_severity=report.findings_by_severity,
        ),
    )


@router.post(
    "/comparison-runs/{run_id}/summarize",
    response_model=SEOCompetitorComparisonSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def summarize_competitor_comparison_run(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = summary_service.summarize_run(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorSummaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryRead.model_validate(result.summary)


@router.get(
    "/comparison-runs/{run_id}/summaries",
    response_model=SEOCompetitorComparisonSummaryListResponse,
)
def list_competitor_comparison_summaries(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        items = summary_service.list_summaries(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryListResponse(
        items=[SEOCompetitorComparisonSummaryRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.get(
    "/comparison-runs/{run_id}/summaries/latest",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_latest_competitor_comparison_summary(
    business_id: str,
    run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = summary_service.get_latest_summary(
            business_id=scoped_business_id,
            comparison_run_id=run_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)


@router.get(
    "/comparison-summaries/{summary_id}",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_competitor_comparison_summary(
    business_id: str,
    summary_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = summary_service.get_summary(
            business_id=scoped_business_id,
            summary_id=summary_id,
        )
    except SEOCompetitorSummaryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)


@router_v1.get("/sites/{site_id}/competitor-sets/{competitor_set_id}", response_model=SEOCompetitorSetRead)
def get_competitor_set_for_site_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorSetRead.model_validate(competitor_set)


@router_v1.get(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/domains",
    response_model=SEOCompetitorDomainListResponse,
)
def list_competitor_domains_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        items = seo_competitor_service.list_domains(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorDomainListResponse(
        items=[SEOCompetitorDomainRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.post(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/domains",
    response_model=SEOCompetitorDomainRead,
    status_code=status.HTTP_201_CREATED,
)
def add_competitor_domain_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    payload: SEOCompetitorDomainCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorDomainRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        competitor_domain = seo_competitor_service.add_domain(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
            payload=payload,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorDomainRead.model_validate(competitor_domain)


@router_v1.post(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/snapshot-runs",
    response_model=SEOCompetitorSnapshotRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_snapshot_run_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    payload: SEOCompetitorSnapshotRunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        snapshot_run = seo_competitor_service.create_snapshot_run(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
            payload=payload,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router_v1.get(
    "/sites/{site_id}/competitor-sets/{competitor_set_id}/snapshot-runs",
    response_model=SEOCompetitorSnapshotRunListResponse,
)
def list_competitor_snapshot_runs_v1(
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
        items = seo_competitor_service.list_snapshot_runs(
            business_id=scoped_business_id,
            competitor_set_id=competitor_set_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=competitor_set.site_id,
        detail="Competitor set not found",
    )
    return SEOCompetitorSnapshotRunListResponse(
        items=[SEOCompetitorSnapshotRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.get(
    "/sites/{site_id}/competitor-snapshot-runs/{snapshot_run_id}",
    response_model=SEOCompetitorSnapshotRunRead,
)
def get_competitor_snapshot_run_v1(
    business_id: str,
    site_id: str,
    snapshot_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        snapshot_run = seo_competitor_service.get_snapshot_run(
            business_id=scoped_business_id,
            snapshot_run_id=snapshot_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=snapshot_run.site_id,
        detail="Competitor snapshot run not found",
    )
    return SEOCompetitorSnapshotRunRead.model_validate(snapshot_run)


@router_v1.get(
    "/sites/{site_id}/competitor-snapshot-runs/{snapshot_run_id}/pages",
    response_model=SEOCompetitorSnapshotPageListResponse,
)
def list_competitor_snapshot_pages_v1(
    business_id: str,
    site_id: str,
    snapshot_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
) -> SEOCompetitorSnapshotPageListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        snapshot_run = seo_competitor_service.get_snapshot_run(
            business_id=scoped_business_id,
            snapshot_run_id=snapshot_run_id,
        )
        items = seo_competitor_service.list_snapshot_pages(
            business_id=scoped_business_id,
            snapshot_run_id=snapshot_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=snapshot_run.site_id,
        detail="Competitor snapshot run not found",
    )
    return SEOCompetitorSnapshotPageListResponse(
        items=[SEOCompetitorSnapshotPageRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.post(
    "/sites/{site_id}/competitor-comparison-runs",
    response_model=SEOCompetitorComparisonRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor_comparison_run_v1(
    business_id: str,
    site_id: str,
    payload: SEOCompetitorComparisonRunSiteCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_competitor_service: SEOCompetitorService = Depends(get_seo_competitor_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        competitor_set = seo_competitor_service.get_set(
            business_id=scoped_business_id,
            competitor_set_id=payload.competitor_set_id,
        )
        _assert_site_match(
            expected_site_id=site_id,
            actual_site_id=competitor_set.site_id,
            detail="Competitor set not found",
        )
        result = comparison_service.run_comparison(
            business_id=scoped_business_id,
            competitor_set_id=payload.competitor_set_id,
            payload=SEOCompetitorComparisonRunCreateRequest(
                snapshot_run_id=payload.snapshot_run_id,
                baseline_audit_run_id=payload.baseline_audit_run_id,
            ),
            created_by_principal_id=tenant_context.principal_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorComparisonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=result.run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonRunRead.model_validate(result.run)


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs",
    response_model=SEOCompetitorComparisonRunListResponse,
)
def list_competitor_comparison_runs_v1(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        items = comparison_service.list_runs_for_site(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOCompetitorComparisonRunListResponse(
        items=[SEOCompetitorComparisonRunRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}",
    response_model=SEOCompetitorComparisonRunRead,
)
def get_competitor_comparison_run_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonRunRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonRunRead.model_validate(run)


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/findings",
    response_model=SEOCompetitorComparisonFindingListResponse,
)
def list_competitor_comparison_findings_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonFindingListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        findings = comparison_service.list_findings(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    by_category, by_severity = comparison_service.summarize_findings(findings=findings)
    return SEOCompetitorComparisonFindingListResponse(
        items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in findings],
        total=len(findings),
        by_category=by_category,
        by_severity=by_severity,
    )


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/report",
    response_model=SEOCompetitorComparisonReportRead,
)
def get_competitor_comparison_report_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
) -> SEOCompetitorComparisonReportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        report = comparison_service.get_report(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorComparisonNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=report.run.site_id,
        detail="Competitor comparison run not found",
    )
    metric_rollups = []
    for metric_key in sorted(report.metric_rollups):
        metric = report.metric_rollups[metric_key]
        metric_rollups.append(
            SEOCompetitorComparisonMetricRollupRead(
                key=metric_key,
                title=str(metric.get("title", metric_key)),
                category=str(metric.get("category", "TECHNICAL")),
                unit=str(metric.get("unit", "count")),
                higher_is_better=bool(metric.get("higher_is_better", False)),
                client_value=int(metric.get("client_value", 0)),
                competitor_value=int(metric.get("competitor_value", 0)),
                delta=int(metric.get("delta", 0)),
                severity=str(metric.get("severity", "INFO")),
                gap_direction=str(metric.get("gap_direction", "unknown")),
            )
        )
    return SEOCompetitorComparisonReportRead(
        run=SEOCompetitorComparisonRunRead.model_validate(report.run),
        rollups=SEOCompetitorComparisonRunRollupsRead(
            client_pages_analyzed=report.run.client_pages_analyzed,
            competitor_pages_analyzed=report.run.competitor_pages_analyzed,
            findings_by_type=report.findings_by_type,
            findings_by_category=report.findings_by_category,
            findings_by_severity=report.findings_by_severity,
            metric_rollups=metric_rollups,
        ),
        findings=SEOCompetitorComparisonFindingListResponse(
            items=[SEOCompetitorComparisonFindingRead.model_validate(item) for item in report.findings],
            total=len(report.findings),
            by_category=report.findings_by_category,
            by_severity=report.findings_by_severity,
        ),
    )


@router_v1.post(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries",
    response_model=SEOCompetitorComparisonSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def summarize_competitor_comparison_run_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        result = summary_service.summarize_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
            created_by_principal_id=tenant_context.principal_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorComparisonNotFoundError,
        SEOCompetitorSummaryNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOCompetitorSummaryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonSummaryRead.model_validate(result.summary)


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries",
    response_model=SEOCompetitorComparisonSummaryListResponse,
)
def list_competitor_comparison_summaries_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        items = summary_service.list_summaries(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorComparisonNotFoundError,
        SEOCompetitorSummaryNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonSummaryListResponse(
        items=[SEOCompetitorComparisonSummaryRead.model_validate(item) for item in items],
        total=len(items),
    )


@router_v1.get(
    "/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries/latest",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_latest_competitor_comparison_summary_v1(
    business_id: str,
    site_id: str,
    comparison_run_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    comparison_service: SEOCompetitorComparisonService = Depends(get_seo_competitor_comparison_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        run = comparison_service.get_run(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
        summary = summary_service.get_latest_summary(
            business_id=scoped_business_id,
            comparison_run_id=comparison_run_id,
        )
    except (
        SEOSiteNotFoundError,
        SEOCompetitorComparisonNotFoundError,
        SEOCompetitorSummaryNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=run.site_id,
        detail="Competitor comparison run not found",
    )
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)


@router_v1.get(
    "/sites/{site_id}/competitor-summaries/{summary_id}",
    response_model=SEOCompetitorComparisonSummaryRead,
)
def get_competitor_comparison_summary_v1(
    business_id: str,
    site_id: str,
    summary_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    summary_service: SEOCompetitorSummaryService = Depends(get_seo_competitor_summary_service),
) -> SEOCompetitorComparisonSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
        summary = summary_service.get_summary(
            business_id=scoped_business_id,
            summary_id=summary_id,
        )
    except (SEOSiteNotFoundError, SEOCompetitorSummaryNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_site_match(
        expected_site_id=site_id,
        actual_site_id=summary.site_id,
        detail="Competitor summary not found",
    )
    return SEOCompetitorComparisonSummaryRead.model_validate(summary)

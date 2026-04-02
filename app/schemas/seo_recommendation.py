from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.action_chaining import ActionLineageResponse
from app.schemas.ai_prompt import AIPromptPreviewRead

SEORecommendationRunStatus = Literal["queued", "running", "completed", "failed"]
SEORecommendationCategory = Literal["SEO", "CONTENT", "STRUCTURE", "TECHNICAL"]
SEORecommendationSeverity = Literal["INFO", "WARNING", "CRITICAL"]
SEORecommendationEffort = Literal["LOW", "MEDIUM", "HIGH"]
SEORecommendationNarrativeStatus = Literal["completed", "failed"]
SEORecommendationWorkspaceSummaryState = Literal[
    "no_runs",
    "no_completed_runs",
    "completed_no_narrative",
    "completed_with_narrative",
]
SEORecommendationPriorityBand = Literal["low", "medium", "high", "critical"]
SEORecommendationStatus = Literal["open", "in_progress", "accepted", "dismissed", "snoozed", "resolved"]
SEORecommendationDecision = Literal["accept", "dismiss", "snooze", "resolve", "reopen", "start"]
SEORecommendationSourceType = Literal["audit", "comparison", "mixed"]
SEORecommendationSortBy = Literal["priority_score", "priority_band", "severity", "created_at", "updated_at", "due_at"]
SortOrder = Literal["asc", "desc"]
SEORecommendationTuningSuggestionConfidence = Literal["low", "medium", "high"]
SEORecommendationSignalSupportLevel = Literal["low", "medium", "high"]
SEORecommendationPriorityLevel = Literal["high", "medium", "low"]
SEORecommendationEffortHint = Literal["quick_win", "moderate", "larger_change"]
SEORecommendationCompetitorEvidenceTrustTier = Literal[
    "trusted_verified",
    "informational_unverified",
    "informational_candidate",
]
SEORecommendationApplyOutcomeSource = Literal["recommendation", "manual"]
SEORecommendationAnalysisFreshnessStatus = Literal["fresh", "pending_refresh", "unknown"]
SEORecommendationWorkspaceTrustCompetitorStatus = Literal["normal", "recovered", "degraded", "failed"]
SEOWorkspaceSectionFreshnessState = Literal["fresh", "pending_refresh", "running", "stale"]
SEOWorkspaceSectionFreshnessStateCode = Literal[
    "fresh",
    "pending_refresh",
    "running",
    "stale",
    "possibly_outdated",
]
SEORecommendationProgressStatus = Literal[
    "suggested",
    "applied_pending_refresh",
    "reflected_in_latest_analysis",
]
SEORecommendationLifecycleState = Literal[
    "active",
    "applied_waiting_validation",
    "reflected_still_relevant",
    "likely_resolved",
]
SEORecommendationTargetContext = Literal[
    "homepage",
    "service_pages",
    "contact_about",
    "location_pages",
    "sitewide",
    "general",
]
SEOCompetitorContextHealthStatus = Literal["strong", "mixed", "weak"]
SEOCompetitorContextHealthCheckKey = Literal[
    "location_context",
    "industry_context",
    "service_focus",
    "target_customer_context",
]
SEOCompetitorContextHealthCheckStatus = Literal["strong", "weak"]
SEORecommendationLocationContextStrength = Literal["strong", "weak", "unknown"]
SEORecommendationLocationContextSource = Literal[
    "explicit_location",
    "service_area",
    "zip_capture",
    "fallback",
]
SEORecommendationStartHereContextFlag = Literal["pending_refresh_context", "competitor_backed"]
SEORecommendationEEATCategory = Literal[
    "experience",
    "expertise",
    "authoritativeness",
    "trustworthiness",
]
SEORecommendationPriorityReason = Literal[
    "competitor_gap",
    "trust_gap",
    "authority_gap",
    "experience_gap",
    "expertise_gap",
    "high_clarity_action",
    "pending_refresh_context",
    "general",
]
SEORecommendationTheme = Literal[
    "trust_and_legitimacy",
    "experience_and_proof",
    "authority_and_visibility",
    "expertise_and_process",
    "general_site_improvement",
]
RecommendationTuningSetting = Literal[
    "competitor_candidate_min_relevance_score",
    "competitor_candidate_big_box_penalty",
    "competitor_candidate_directory_penalty",
    "competitor_candidate_local_alignment_bonus",
]

_CATEGORIES = {"SEO", "CONTENT", "STRUCTURE", "TECHNICAL"}
_SEVERITIES = {"INFO", "WARNING", "CRITICAL"}
_EFFORT_BUCKETS = {"LOW", "MEDIUM", "HIGH"}
_PRIORITY_BANDS = {"low", "medium", "high", "critical"}
_STATUSES = {"open", "in_progress", "accepted", "dismissed", "snoozed", "resolved"}
_DECISIONS = {"accept", "dismiss", "snooze", "resolve", "reopen", "start"}
_SOURCE_TYPES = {"audit", "comparison", "mixed"}
_SORT_FIELDS = {"priority_score", "priority_band", "severity", "created_at", "updated_at", "due_at"}
_SORT_ORDERS = {"asc", "desc"}
_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS = 4
_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS = 180
_ACTION_SUMMARY_WHY_MAX_CHARS = 240
_ACTION_SUMMARY_FIRST_STEP_MAX_CHARS = 180
_ACTION_SUMMARY_EVIDENCE_ITEM_MAX_CHARS = 160
_APPLY_OUTCOME_RECOMMENDATION_ID_MAX_CHARS = 36
_APPLY_OUTCOME_LABEL_MAX_CHARS = 180
_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS = 260
_APPLY_OUTCOME_NEXT_RUN_MAX_CHARS = 220
_WORKSPACE_TRUST_APPLY_TITLE_MAX_CHARS = 180
_WORKSPACE_TRUST_APPLY_CHANGE_MAX_CHARS = 260
_WORKSPACE_TRUST_NEXT_REFRESH_MAX_CHARS = 220
_WORKSPACE_TRUST_FRESHNESS_NOTE_MAX_CHARS = 220
_WORKSPACE_SECTION_FRESHNESS_MESSAGE_MAX_CHARS = 220
_RECOMMENDATION_PROGRESS_SUMMARY_MAX_CHARS = 220
_RECOMMENDATION_LIFECYCLE_SUMMARY_MAX_CHARS = 220
_RECOMMENDATION_EVIDENCE_SUMMARY_MAX_CHARS = 220
_RECOMMENDATION_OBSERVED_GAP_SUMMARY_MAX_CHARS = 220
_RECOMMENDATION_ACTION_CLARITY_MAX_CHARS = 220
_RECOMMENDATION_EXPECTED_OUTCOME_MAX_CHARS = 220
_RECOMMENDATION_EVIDENCE_TRACE_MAX_CHARS = 80
_RECOMMENDATION_EVIDENCE_TRACE_MAX_ITEMS = 5
_RECOMMENDATION_TARGET_PAGE_HINT_MAX_CHARS = 120
_RECOMMENDATION_TARGET_PAGE_HINT_MAX_ITEMS = 3
_RECOMMENDATION_COMPETITOR_LINK_MAX_ITEMS = 3
_RECOMMENDATION_COMPETITOR_LINK_NAME_MAX_CHARS = 180
_RECOMMENDATION_COMPETITOR_LINK_DOMAIN_MAX_CHARS = 255
_RECOMMENDATION_COMPETITOR_LINK_SUMMARY_MAX_CHARS = 220
_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS = 240
_RECOMMENDATION_ACTION_DELTA_PATTERN_MAX_CHARS = 220
_RECOMMENDATION_ACTION_DELTA_GAP_MAX_CHARS = 220
_RECOMMENDATION_ACTION_DELTA_ACTION_MAX_CHARS = 220
_RECOMMENDATION_PRIORITY_REASON_MAX_CHARS = 220
_SIGNAL_SUMMARY_EVIDENCE_SOURCE_ORDER = ("site", "competitors", "references", "themes")
_RECOMMENDATION_EEAT_GAP_SUPPORTING_SIGNALS_MAX_ITEMS = 6
_RECOMMENDATION_EEAT_GAP_SUPPORTING_SIGNAL_MAX_CHARS = 140
_ORDERING_EXPLANATION_MAX_CHARS = 320
_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS = 80
_RECOMMENDATION_THEME_GROUP_RECOMMENDATION_ID_MAX_ITEMS = 200
_LOCATION_CONTEXT_MAX_CHARS = 220
_PRIMARY_LOCATION_MAX_CHARS = 255
_PRIMARY_ZIP_MAX_CHARS = 5
_START_HERE_TITLE_MAX_CHARS = 180
_START_HERE_REASON_MAX_CHARS = 320
_COMPETITOR_CONTEXT_HEALTH_CHECK_LABEL_MAX_CHARS = 80
_COMPETITOR_CONTEXT_HEALTH_CHECK_DETAIL_MAX_CHARS = 220
_COMPETITOR_CONTEXT_HEALTH_MESSAGE_MAX_CHARS = 220
_COMPETITOR_CONTEXT_HEALTH_MAX_CHECKS = 4
_COMPETITOR_CONTEXT_HEALTH_CHECK_KEY_ORDER: tuple[SEOCompetitorContextHealthCheckKey, ...] = (
    "location_context",
    "industry_context",
    "service_focus",
    "target_customer_context",
)
_EEAT_CATEGORY_ORDER: tuple[SEORecommendationEEATCategory, ...] = (
    "experience",
    "expertise",
    "authoritativeness",
    "trustworthiness",
)
_PRIORITY_REASON_ORDER: tuple[SEORecommendationPriorityReason, ...] = (
    "competitor_gap",
    "trust_gap",
    "authority_gap",
    "experience_gap",
    "expertise_gap",
    "high_clarity_action",
    "pending_refresh_context",
    "general",
)
_RECOMMENDATION_THEME_ORDER: tuple[SEORecommendationTheme, ...] = (
    "trust_and_legitimacy",
    "experience_and_proof",
    "authority_and_visibility",
    "expertise_and_process",
    "general_site_improvement",
)
_THEME_LABELS: dict[SEORecommendationTheme, str] = {
    "trust_and_legitimacy": "Trust & legitimacy",
    "experience_and_proof": "Experience & proof",
    "authority_and_visibility": "Authority & visibility",
    "expertise_and_process": "Expertise & process",
    "general_site_improvement": "General site improvement",
}
_EEAT_CATEGORY_TO_PRIORITY_REASON: dict[SEORecommendationEEATCategory, SEORecommendationPriorityReason] = {
    "trustworthiness": "trust_gap",
    "authoritativeness": "authority_gap",
    "experience": "experience_gap",
    "expertise": "expertise_gap",
}
_EEAT_CATEGORY_TO_THEME: dict[SEORecommendationEEATCategory, SEORecommendationTheme] = {
    "trustworthiness": "trust_and_legitimacy",
    "experience": "experience_and_proof",
    "authoritativeness": "authority_and_visibility",
    "expertise": "expertise_and_process",
}
_PRIORITY_REASON_TO_THEME: dict[SEORecommendationPriorityReason, SEORecommendationTheme] = {
    "trust_gap": "trust_and_legitimacy",
    "experience_gap": "experience_and_proof",
    "authority_gap": "authority_and_visibility",
    "expertise_gap": "expertise_and_process",
    "competitor_gap": "authority_and_visibility",
}
_RECOMMENDATION_TARGET_CONTEXT_ORDER: tuple[SEORecommendationTargetContext, ...] = (
    "homepage",
    "service_pages",
    "contact_about",
    "location_pages",
    "sitewide",
    "general",
)
_HIGH_CLARITY_ACTION_VERBS = {
    "add",
    "build",
    "claim",
    "clarify",
    "create",
    "expand",
    "fix",
    "implement",
    "improve",
    "optimize",
    "publish",
    "refresh",
    "strengthen",
    "update",
    "verify",
}
_THEME_KEYWORDS: dict[SEORecommendationTheme, tuple[str, ...]] = {
    "trust_and_legitimacy": (
        "trust",
        "license",
        "insurance",
        "bbb",
        "verified",
        "review",
        "contact",
        "address",
        "nap",
    ),
    "experience_and_proof": (
        "portfolio",
        "project",
        "before",
        "after",
        "case study",
        "testimonial",
        "proof",
        "photo",
        "video",
    ),
    "authority_and_visibility": (
        "authority",
        "citation",
        "listing",
        "directory",
        "press",
        "award",
        "association",
        "membership",
    ),
    "expertise_and_process": (
        "process",
        "method",
        "technical",
        "capability",
        "qa",
        "quality",
        "implementation",
        "workflow",
    ),
}
_EXPERIENCE_SIGNAL_KEYWORDS = (
    "testimonial",
    "review",
    "project_story",
    "project_proof",
    "portfolio",
    "case_study",
    "before_after",
    "video_proof",
    "experience_proof",
)
_EXPERTISE_SIGNAL_KEYWORDS = (
    "method",
    "process",
    "technical",
    "capability",
    "qa_qc",
    "quality_assurance",
    "project_management",
    "scanning_tool",
    "implementation_detail",
)
_AUTHORITATIVENESS_SIGNAL_KEYWORDS = (
    "award",
    "association",
    "membership",
    "directory_listing",
    "press",
    "recognition",
    "citation",
)
_TRUSTWORTHINESS_SIGNAL_KEYWORDS = (
    "license",
    "insurance",
    "bbb",
    "verified_review",
    "physical_address",
    "nap_consistency",
    "contact_legitimacy",
    "trust_signal",
)


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_int_map(raw: Any) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("Expected object for count map")
    normalized: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            normalized[key] = int(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_category(value: Any) -> SEORecommendationCategory:
    normalized = str(value or "").strip().upper()
    if normalized not in _CATEGORIES:
        return "TECHNICAL"
    return normalized  # type: ignore[return-value]


def _normalize_severity(value: Any) -> SEORecommendationSeverity:
    normalized = str(value or "").strip().upper()
    if normalized not in _SEVERITIES:
        return "INFO"
    return normalized  # type: ignore[return-value]


def _normalize_effort(value: Any) -> SEORecommendationEffort:
    normalized = str(value or "").strip().upper()
    if normalized not in _EFFORT_BUCKETS:
        return "MEDIUM"
    return normalized  # type: ignore[return-value]


def _normalize_priority_band(value: Any) -> SEORecommendationPriorityBand:
    normalized = str(value or "").strip().lower()
    if normalized not in _PRIORITY_BANDS:
        return "medium"
    return normalized  # type: ignore[return-value]


def _normalize_status(value: Any) -> SEORecommendationStatus:
    normalized = str(value or "").strip().lower()
    if normalized not in _STATUSES:
        return "open"
    return normalized  # type: ignore[return-value]


def _normalize_decision(value: Any) -> SEORecommendationDecision | None:
    normalized = _strip_or_none(str(value)) if value is not None else None
    if normalized is None:
        return None
    normalized = normalized.lower()
    if normalized not in _DECISIONS:
        raise ValueError("Invalid recommendation decision")
    return normalized  # type: ignore[return-value]


def _normalize_source_type(value: Any) -> SEORecommendationSourceType:
    normalized = str(value or "").strip().lower()
    if normalized not in _SOURCE_TYPES:
        raise ValueError("Invalid source_type")
    return normalized  # type: ignore[return-value]


def _normalize_sort_by(value: Any) -> SEORecommendationSortBy:
    normalized = str(value or "").strip().lower()
    if normalized not in _SORT_FIELDS:
        raise ValueError("Invalid sort_by")
    return normalized  # type: ignore[return-value]


def _normalize_sort_order(value: Any) -> SortOrder:
    normalized = str(value or "").strip().lower()
    if normalized not in _SORT_ORDERS:
        raise ValueError("Invalid sort_order")
    return normalized  # type: ignore[return-value]


def _compact_text(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    compacted = " ".join(str(value).split())
    cleaned = _strip_or_none(compacted)
    if cleaned is None:
        return None
    return cleaned[:max_length]


def _compact_text_list(value: Any, *, limit: int, max_length: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _compact_text(item, max_length=max_length)
        if cleaned is None:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_signal_text(value: object, *, max_length: int) -> str | None:
    normalized = _compact_text(value, max_length=max_length)
    if normalized is None:
        return None
    return normalized.lower()


def _normalize_priority_reason(value: Any) -> SEORecommendationPriorityReason | None:
    normalized = str(value or "").strip().lower()
    if normalized not in _PRIORITY_REASON_ORDER:
        return None
    return normalized  # type: ignore[return-value]


def _normalize_priority_reason_list(value: Any) -> list[SEORecommendationPriorityReason]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("priority_reasons must be a list")
    parsed: set[SEORecommendationPriorityReason] = set()
    for item in value:
        reason = _normalize_priority_reason(item)
        if reason is None:
            continue
        parsed.add(reason)
    return [reason for reason in _PRIORITY_REASON_ORDER if reason in parsed]


def _normalize_recommendation_theme(value: Any) -> SEORecommendationTheme | None:
    normalized = str(value or "").strip().lower()
    if normalized not in _RECOMMENDATION_THEME_ORDER:
        return None
    return normalized  # type: ignore[return-value]


def _normalize_recommendation_target_context(value: Any) -> SEORecommendationTargetContext | None:
    normalized = str(value or "").strip().lower()
    if normalized not in _RECOMMENDATION_TARGET_CONTEXT_ORDER:
        return None
    return normalized  # type: ignore[return-value]


def format_recommendation_theme_label(theme: SEORecommendationTheme) -> str:
    return _THEME_LABELS.get(theme, theme.replace("_", " ").title())


def _extract_recommendation_evidence_sources(evidence_json: dict[str, object] | None) -> set[str]:
    if not isinstance(evidence_json, dict):
        return set()
    raw_sources = evidence_json.get("sources")
    if not isinstance(raw_sources, list):
        return set()
    normalized_sources: set[str] = set()
    for raw_source in raw_sources:
        source = str(raw_source or "").strip().lower()
        if not source:
            continue
        normalized_sources.add(source)
    return normalized_sources


def _is_high_clarity_action(*, title: str | None, rationale: str | None) -> bool:
    normalized_title = _compact_text(title, max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS)
    normalized_rationale = _compact_text(rationale, max_length=_ACTION_SUMMARY_WHY_MAX_CHARS)
    if normalized_title is None or normalized_rationale is None:
        return False
    tokens = [token.strip(".,:;!?()[]{}-_/").lower() for token in normalized_title.split()]
    tokens = [token for token in tokens if token]
    if len(tokens) < 2:
        return False
    return tokens[0] in _HIGH_CLARITY_ACTION_VERBS


def _derive_recommendation_priority_reasons(
    *,
    comparison_run_id: str | None,
    evidence_json: dict[str, object] | None,
    eeat_categories: list[SEORecommendationEEATCategory],
    title: str | None,
    rationale: str | None,
) -> list[SEORecommendationPriorityReason]:
    reasons: set[SEORecommendationPriorityReason] = set()
    evidence_sources = _extract_recommendation_evidence_sources(evidence_json)
    if comparison_run_id is not None or "comparison" in evidence_sources or "mixed" in evidence_sources:
        reasons.add("competitor_gap")

    for category in eeat_categories:
        mapped_reason = _EEAT_CATEGORY_TO_PRIORITY_REASON.get(category)
        if mapped_reason is not None:
            reasons.add(mapped_reason)

    if _is_high_clarity_action(title=title, rationale=rationale):
        reasons.add("high_clarity_action")

    return [reason for reason in _PRIORITY_REASON_ORDER if reason in reasons]


def _derive_recommendation_theme(
    *,
    eeat_categories: list[SEORecommendationEEATCategory],
    priority_reasons: list[SEORecommendationPriorityReason],
    rule_key: str | None,
    title: str | None,
    rationale: str | None,
) -> SEORecommendationTheme:
    for category in eeat_categories:
        mapped = _EEAT_CATEGORY_TO_THEME.get(category)
        if mapped is not None:
            return mapped

    for reason in priority_reasons:
        mapped = _PRIORITY_REASON_TO_THEME.get(reason)
        if mapped is not None:
            return mapped

    raw_signal = " ".join(
        filter(
            None,
            [
                _normalize_signal_text(rule_key, max_length=120),
                _normalize_signal_text(title, max_length=120),
                _normalize_signal_text(rationale, max_length=160),
            ],
        )
    )
    for theme in _RECOMMENDATION_THEME_ORDER:
        keywords = _THEME_KEYWORDS.get(theme)
        if not keywords:
            continue
        if any(keyword in raw_signal for keyword in keywords):
            return theme

    return "general_site_improvement"


def _derive_recommendation_evidence_summary(
    *,
    priority_reasons: list[SEORecommendationPriorityReason],
    eeat_categories: list[SEORecommendationEEATCategory],
    evidence_json: dict[str, object] | None,
) -> str | None:
    evidence_sources = _extract_recommendation_evidence_sources(evidence_json)
    competitor_backed = (
        "competitor_gap" in priority_reasons or "comparison" in evidence_sources or "mixed" in evidence_sources
    )

    if competitor_backed:
        if "trustworthiness" in eeat_categories:
            return "Competitors show stronger trust signals in this area."
        if "experience" in eeat_categories:
            return "Competitors show stronger proof of real work in this area."
        if "authoritativeness" in eeat_categories:
            return "Competitors show stronger third-party authority signals in this area."
        if "expertise" in eeat_categories:
            return "Competitors show stronger expertise and process signals in this area."
        return "This addresses a visible site gap backed by competitor comparison evidence."

    if eeat_categories:
        primary_category = eeat_categories[0]
        if primary_category == "trustworthiness":
            return "This addresses a visible site trust and legitimacy gap."
        if primary_category == "experience":
            return "This improves visible proof of real work and outcomes."
        if primary_category == "authoritativeness":
            return "This strengthens external credibility and authority signals."
        if primary_category == "expertise":
            return "This clarifies methods and capability signals customers can evaluate."

    if "audit" in evidence_sources:
        return "This is backed by structured site findings from the latest analysis."
    if "comparison" in evidence_sources or "mixed" in evidence_sources:
        return "This is backed by deterministic comparison evidence from current competitor analysis."
    if "high_clarity_action" in priority_reasons:
        return "This is a clear, actionable step supported by current recommendation metadata."
    return None


def _derive_recommendation_action_scope(
    *,
    theme: SEORecommendationTheme | None,
    rule_key: str | None,
    title: str | None,
    rationale: str | None,
) -> str:
    normalized_signal = " ".join(
        filter(
            None,
            [
                _normalize_signal_text(rule_key, max_length=120),
                _normalize_signal_text(title, max_length=120),
                _normalize_signal_text(rationale, max_length=160),
            ],
        )
    )
    if "home page" in normalized_signal or "homepage" in normalized_signal:
        return "homepage and core service pages"
    if "service page" in normalized_signal or "service pages" in normalized_signal:
        return "key service pages"
    if "contact" in normalized_signal or "about" in normalized_signal:
        return "contact and about pages"
    if "location" in normalized_signal or "local" in normalized_signal:
        return "core local and location pages"

    if theme == "trust_and_legitimacy":
        return "key service, contact, and about pages"
    if theme == "experience_and_proof":
        return "service and proof-focused pages"
    if theme == "authority_and_visibility":
        return "profile, listing, and citation surfaces"
    if theme == "expertise_and_process":
        return "service and process-focused pages"
    return "high-visibility service pages"


def _compact_sentence(value: str | None, *, max_length: int) -> str | None:
    compacted = _compact_text(value, max_length=max_length)
    if compacted is None:
        return None
    if compacted.endswith((".", "!", "?")):
        return compacted
    return f"{compacted}."


def _derive_recommendation_action_clarity(
    *,
    title: str | None,
    rationale: str | None,
    rule_key: str | None,
    theme: SEORecommendationTheme | None,
    recommendation_evidence_summary: str | None,
) -> str | None:
    base_action = _compact_text(title, max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS)
    if base_action:
        lowered = base_action.lower()
        has_scope_phrase = any(token in lowered for token in (" on ", " across ", " within ", " in "))
        if not has_scope_phrase and (" page" in lowered or "pages" in lowered):
            has_scope_phrase = True
        if has_scope_phrase:
            return _compact_sentence(base_action, max_length=_RECOMMENDATION_ACTION_CLARITY_MAX_CHARS)
        scope = _derive_recommendation_action_scope(
            theme=theme,
            rule_key=rule_key,
            title=title,
            rationale=rationale,
        )
        return _compact_sentence(
            f"{base_action.rstrip('.')} on {scope}",
            max_length=_RECOMMENDATION_ACTION_CLARITY_MAX_CHARS,
        )

    if recommendation_evidence_summary and "trust" in recommendation_evidence_summary.lower():
        return "Add stronger trust and legitimacy proof to key customer-facing pages."
    if theme == "experience_and_proof":
        return "Add clearer project proof and outcome examples on key service pages."
    if theme == "authority_and_visibility":
        return "Strengthen external authority signals across profile and listing surfaces."
    if theme == "expertise_and_process":
        return "Clarify service process and capability details on core service pages."
    if theme == "trust_and_legitimacy":
        return "Strengthen trust and legitimacy signals across key service and contact pages."
    if theme == "general_site_improvement":
        return "Improve core service-page clarity for high-intent visitors."
    return None


def _derive_recommendation_expected_outcome(
    *,
    eeat_categories: list[SEORecommendationEEATCategory],
    priority_reasons: list[SEORecommendationPriorityReason],
    theme: SEORecommendationTheme | None,
    recommendation_evidence_summary: str | None,
) -> str | None:
    evidence_summary = (recommendation_evidence_summary or "").lower()
    competitor_backed = "competitor" in evidence_summary or "competitor_gap" in priority_reasons

    if competitor_backed and "trustworthiness" in eeat_categories:
        return "Helps visitors trust the business faster while closing visible competitor trust gaps."
    if competitor_backed and "experience" in eeat_categories:
        return "Improves visible proof of experience where competitors currently stand out."
    if competitor_backed:
        return "Helps close visible competitor-backed gaps in this area."

    if "trustworthiness" in eeat_categories:
        return "Helps visitors trust the business faster."
    if "experience" in eeat_categories:
        return "Improves visible proof of experience and completed work."
    if "authoritativeness" in eeat_categories:
        return "Strengthens external credibility and local market authority signals."
    if "expertise" in eeat_categories:
        return "Makes service capability and process quality easier to evaluate."

    if "high_clarity_action" in priority_reasons:
        return "Makes the next optimization step clearer and easier to execute."

    if theme == "trust_and_legitimacy":
        return "Strengthens visible trust and legitimacy signals for prospective customers."
    if theme == "experience_and_proof":
        return "Improves visible proof of work quality and outcomes."
    if theme == "authority_and_visibility":
        return "Improves how external credibility signals are presented to local searchers."
    if theme == "expertise_and_process":
        return "Clarifies process and expertise signals customers use to evaluate providers."
    if theme == "general_site_improvement":
        return "Improves core site clarity for prospective customers."
    return None


def _derive_recommendation_observed_gap_summary(
    *,
    rule_key: str | None,
    title: str | None,
    rationale: str | None,
    recommendation_evidence_summary: str | None,
    recommendation_target_context: SEORecommendationTargetContext | None,
    eeat_categories: list[SEORecommendationEEATCategory],
    priority_reasons: list[SEORecommendationPriorityReason],
    theme: SEORecommendationTheme | None,
) -> str | None:
    normalized_signal = " ".join(
        filter(
            None,
            [
                _normalize_signal_text(rule_key, max_length=140),
                _normalize_signal_text(title, max_length=180),
                _normalize_signal_text(rationale, max_length=220),
                _normalize_signal_text(recommendation_evidence_summary, max_length=220),
            ],
        )
    )

    if (
        recommendation_target_context == "contact_about"
        or "trustworthiness" in eeat_categories
        or "trust_gap" in priority_reasons
        or any(
            keyword in normalized_signal
            for keyword in (
                "trust",
                "license",
                "insurance",
                "verified",
                "review",
                "bbb",
                "contact legitimacy",
                "physical address",
                "nap",
            )
        )
    ):
        return "No strong trust or verification signals were detected on key customer-facing pages."

    if (
        "experience" in eeat_categories
        or "experience_gap" in priority_reasons
        or any(
            keyword in normalized_signal
            for keyword in ("project", "before-after", "before/after", "testimonial", "case study", "portfolio")
        )
    ):
        return "Project/testimonial proof appears limited on likely service pages."

    if recommendation_target_context == "location_pages" or any(
        keyword in normalized_signal
        for keyword in (
            "local",
            "location",
            "service area",
            "cities",
            "zip",
            "map",
            "gbp",
            "google business profile",
        )
    ):
        return "Local/service-area relevance signals appear limited."

    if (
        recommendation_target_context == "service_pages"
        or "expertise" in eeat_categories
        or "expertise_gap" in priority_reasons
        or any(
            keyword in normalized_signal
            for keyword in ("service", "services", "process", "capability", "method", "scope")
        )
    ):
        return "Service-specific wording and proof appear weak or inconsistent."

    if (
        "authoritativeness" in eeat_categories
        or "authority_gap" in priority_reasons
        or any(
            keyword in normalized_signal
            for keyword in ("citation", "directory", "association", "credential", "award", "press")
        )
    ):
        return "External authority and recognition signals appear limited."

    if theme == "general_site_improvement" or normalized_signal:
        return "Current site signals in this recommendation area appear limited or inconsistent."
    return None


def _derive_recommendation_evidence_trace(
    *,
    priority_reasons: list[SEORecommendationPriorityReason],
    eeat_categories: list[SEORecommendationEEATCategory],
    recommendation_target_context: SEORecommendationTargetContext | None,
    recommendation_evidence_summary: str | None,
    recommendation_observed_gap_summary: str | None,
    evidence_json: dict[str, object] | None,
    theme: SEORecommendationTheme | None,
) -> list[str]:
    evidence_sources = _extract_recommendation_evidence_sources(evidence_json)
    evidence_summary = (recommendation_evidence_summary or "").lower()
    observed_gap_summary = (recommendation_observed_gap_summary or "").lower()
    trace_tokens: list[str] = []
    seen: set[str] = set()

    def add_token(value: str | None) -> None:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_EVIDENCE_TRACE_MAX_CHARS)
        if cleaned is None:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        trace_tokens.append(cleaned)
        if len(trace_tokens) >= _RECOMMENDATION_EVIDENCE_TRACE_MAX_ITEMS:
            return

    competitor_backed = (
        "competitor_gap" in priority_reasons
        or "competitor" in evidence_summary
        or "comparison" in evidence_sources
        or "mixed" in evidence_sources
    )
    if competitor_backed:
        add_token("Competitor-backed")
    elif "audit" in evidence_sources:
        add_token("Audit-backed")

    if (
        "trustworthiness" in eeat_categories
        or "trust_gap" in priority_reasons
        or any(
            keyword in observed_gap_summary
            for keyword in ("trust", "verification", "license", "insurance", "contact legitimacy")
        )
    ):
        add_token("Trust/verification gap")
    elif (
        "expertise" in eeat_categories
        or "expertise_gap" in priority_reasons
        or any(keyword in observed_gap_summary for keyword in ("service-specific", "process", "capability"))
    ):
        add_token("Service/process clarity")
    elif (
        "experience" in eeat_categories
        or "experience_gap" in priority_reasons
        or any(keyword in observed_gap_summary for keyword in ("project", "testimonial", "proof"))
    ):
        add_token("Proof/experience gap")
    elif (
        "authoritativeness" in eeat_categories
        or "authority_gap" in priority_reasons
        or "authority" in observed_gap_summary
    ):
        add_token("Authority visibility gap")
    elif recommendation_target_context == "location_pages" or "local/service-area" in observed_gap_summary:
        add_token("Local relevance gap")
    elif recommendation_target_context == "service_pages":
        add_token("Service clarity gap")
    elif theme == "general_site_improvement":
        add_token("General site signals")

    if recommendation_target_context == "homepage":
        add_token("Homepage")
    elif recommendation_target_context == "service_pages":
        add_token("Service pages")
    elif recommendation_target_context == "contact_about":
        add_token("Contact/About")
    elif recommendation_target_context == "location_pages":
        add_token("Location pages")
    elif recommendation_target_context == "sitewide":
        add_token("Sitewide")

    return trace_tokens[:_RECOMMENDATION_EVIDENCE_TRACE_MAX_ITEMS]


def _derive_recommendation_target_context(
    *,
    rule_key: str | None,
    title: str | None,
    rationale: str | None,
    recommendation_action_clarity: str | None,
    recommendation_evidence_summary: str | None,
    theme: SEORecommendationTheme | None,
) -> SEORecommendationTargetContext:
    core_signal = " ".join(
        filter(
            None,
            [
                _normalize_signal_text(rule_key, max_length=140),
                _normalize_signal_text(title, max_length=180),
                _normalize_signal_text(rationale, max_length=220),
            ],
        )
    )
    signal = " ".join(
        filter(
            None,
            [
                core_signal,
                _normalize_signal_text(recommendation_action_clarity, max_length=220),
                _normalize_signal_text(recommendation_evidence_summary, max_length=220),
            ],
        )
    )

    if any(
        keyword in signal
        for keyword in ("sitewide", "across all pages", "across the site", "all pages", "every page", "global")
    ):
        return "sitewide"
    if any(keyword in signal for keyword in ("homepage", "home page", "hero", "h1", "title tag", "above the fold")):
        return "homepage"
    if any(
        keyword in signal
        for keyword in (
            "contact page",
            "about page",
            "contact/about",
            "contact and about",
            "license",
            "insurance",
            "bbb",
            "trust proof",
            "verified review",
            "contact legitimacy",
            "physical address",
            "nap",
        )
    ):
        return "contact_about"
    if any(
        keyword in signal
        for keyword in (
            "location page",
            "location pages",
            "service area",
            "local",
            "nearby",
            "city",
            "zip",
            "map",
            "gbp",
            "google business profile",
        )
    ):
        return "location_pages"
    service_hint_from_core = any(
        keyword in core_signal
        for keyword in (
            "service page",
            "service pages",
            "services",
            "service coverage",
            "service clarity",
            "service proof",
            "process detail",
        )
    )
    service_hint_from_extended = any(
        keyword in signal
        for keyword in (
            "service page",
            "service pages",
            "service coverage",
            "service clarity",
            "service proof",
            "process detail",
        )
    )
    if service_hint_from_core or (service_hint_from_extended and theme != "general_site_improvement"):
        return "service_pages"

    if theme == "trust_and_legitimacy":
        return "contact_about"
    if theme == "experience_and_proof":
        return "service_pages"
    if theme == "authority_and_visibility":
        return "location_pages"
    if theme == "expertise_and_process":
        return "service_pages"
    if theme == "general_site_improvement":
        return "general"
    return "general"


def infer_eeat_categories_from_signals(signal_values: list[object]) -> list[SEORecommendationEEATCategory]:
    normalized_signals: list[str] = []
    for signal in signal_values:
        normalized = _normalize_signal_text(
            signal,
            max_length=_RECOMMENDATION_EEAT_GAP_SUPPORTING_SIGNAL_MAX_CHARS,
        )
        if normalized is None:
            continue
        normalized_signals.append(normalized)

    if not normalized_signals:
        return []

    matched: set[SEORecommendationEEATCategory] = set()
    for signal in normalized_signals:
        if any(keyword in signal for keyword in _EXPERIENCE_SIGNAL_KEYWORDS):
            matched.add("experience")
        if any(keyword in signal for keyword in _EXPERTISE_SIGNAL_KEYWORDS):
            matched.add("expertise")
        if any(keyword in signal for keyword in _AUTHORITATIVENESS_SIGNAL_KEYWORDS):
            matched.add("authoritativeness")
        if any(keyword in signal for keyword in _TRUSTWORTHINESS_SIGNAL_KEYWORDS):
            matched.add("trustworthiness")

    return [category for category in _EEAT_CATEGORY_ORDER if category in matched]


def _first_sentence(value: str | None, *, max_length: int) -> str | None:
    cleaned = _compact_text(value, max_length=max_length * 2 if max_length > 0 else 0)
    if cleaned is None:
        return None
    sentence = cleaned.split(".")[0].strip()
    sentence = sentence or cleaned
    return sentence[:max_length]


class SEORecommendationActionSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_action: str = Field(min_length=1, max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS)
    why_it_matters: str = Field(min_length=1, max_length=_ACTION_SUMMARY_WHY_MAX_CHARS)
    evidence: list[str] = Field(default_factory=list)
    first_step: str = Field(min_length=1, max_length=_ACTION_SUMMARY_FIRST_STEP_MAX_CHARS)

    @field_validator("primary_action", mode="before")
    @classmethod
    def normalize_primary_action(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Action summary text is required")
        return cleaned

    @field_validator("why_it_matters", mode="before")
    @classmethod
    def normalize_why_it_matters(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_ACTION_SUMMARY_WHY_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Action summary text is required")
        return cleaned

    @field_validator("first_step", mode="before")
    @classmethod
    def normalize_first_step(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_ACTION_SUMMARY_FIRST_STEP_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Action summary text is required")
        return cleaned

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, value: Any) -> list[str]:
        return _compact_text_list(
            value,
            limit=_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS,
            max_length=_ACTION_SUMMARY_EVIDENCE_ITEM_MAX_CHARS,
        )


class SEORecommendationSignalSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support_level: SEORecommendationSignalSupportLevel
    evidence_sources: list[str] = Field(default_factory=list)
    competitor_signal_used: bool
    site_signal_used: bool
    reference_signal_used: bool

    @field_validator("support_level", mode="before")
    @classmethod
    def normalize_support_level(cls, value: Any) -> SEORecommendationSignalSupportLevel:
        normalized = str(value or "").strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("Invalid support_level")
        return normalized  # type: ignore[return-value]

    @field_validator("evidence_sources", mode="before")
    @classmethod
    def normalize_evidence_sources(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("evidence_sources must be a list")
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in value:
            source = str(candidate or "").strip().lower()
            if source not in _SIGNAL_SUMMARY_EVIDENCE_SOURCE_ORDER:
                continue
            if source in seen:
                continue
            seen.add(source)
            normalized.append(source)
            if len(normalized) >= len(_SIGNAL_SUMMARY_EVIDENCE_SOURCE_ORDER):
                break
        return normalized


class SEORecommendationApplyOutcomeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool
    applied_at: datetime | None = None
    applied_recommendation_id: str | None = Field(default=None, max_length=_APPLY_OUTCOME_RECOMMENDATION_ID_MAX_CHARS)
    applied_recommendation_title: str | None = Field(default=None, max_length=_APPLY_OUTCOME_LABEL_MAX_CHARS)
    applied_change_summary: str | None = Field(default=None, max_length=_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS)
    applied_preview_summary: str | None = Field(default=None, max_length=_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS)
    next_refresh_expectation: str | None = Field(default=None, max_length=_APPLY_OUTCOME_NEXT_RUN_MAX_CHARS)
    recommendation_label: str | None = Field(default=None, max_length=_APPLY_OUTCOME_LABEL_MAX_CHARS)
    expected_change: str | None = Field(default=None, max_length=_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS)
    reflected_on_next_run: str | None = Field(default=None, max_length=_APPLY_OUTCOME_NEXT_RUN_MAX_CHARS)
    source: SEORecommendationApplyOutcomeSource | None = None

    @field_validator("applied_recommendation_id", mode="before")
    @classmethod
    def normalize_applied_recommendation_id(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_RECOMMENDATION_ID_MAX_CHARS)

    @field_validator("applied_recommendation_title", mode="before")
    @classmethod
    def normalize_applied_recommendation_title(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_LABEL_MAX_CHARS)

    @field_validator("applied_change_summary", mode="before")
    @classmethod
    def normalize_applied_change_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS)

    @field_validator("applied_preview_summary", mode="before")
    @classmethod
    def normalize_applied_preview_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS)

    @field_validator("next_refresh_expectation", mode="before")
    @classmethod
    def normalize_next_refresh_expectation(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_NEXT_RUN_MAX_CHARS)

    @field_validator("recommendation_label", mode="before")
    @classmethod
    def normalize_recommendation_label(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_LABEL_MAX_CHARS)

    @field_validator("expected_change", mode="before")
    @classmethod
    def normalize_expected_change(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_EXPECTED_CHANGE_MAX_CHARS)

    @field_validator("reflected_on_next_run", mode="before")
    @classmethod
    def normalize_reflected_on_next_run(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_APPLY_OUTCOME_NEXT_RUN_MAX_CHARS)

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value: Any) -> SEORecommendationApplyOutcomeSource | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in {"recommendation", "manual"}:
            raise ValueError("Invalid apply outcome source")
        return normalized  # type: ignore[return-value]


class SEORecommendationAnalysisFreshnessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SEORecommendationAnalysisFreshnessStatus
    analysis_generated_at: datetime | None = None
    last_apply_at: datetime | None = None
    message: str = Field(min_length=1, max_length=220)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> SEORecommendationAnalysisFreshnessStatus:
        normalized = str(value or "").strip().lower()
        if normalized not in {"fresh", "pending_refresh", "unknown"}:
            raise ValueError("Invalid analysis freshness status")
        return normalized  # type: ignore[return-value]

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=220)
        if cleaned is None:
            raise ValueError("Analysis freshness message is required")
        return cleaned


class SEORecommendationWorkspaceTrustSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_competitor_status: SEORecommendationWorkspaceTrustCompetitorStatus | None = None
    used_google_places_seeds: bool | None = None
    used_synthetic_fallback: bool | None = None
    latest_recommendation_apply_title: str | None = Field(
        default=None, max_length=_WORKSPACE_TRUST_APPLY_TITLE_MAX_CHARS
    )
    latest_recommendation_apply_change_summary: str | None = Field(
        default=None,
        max_length=_WORKSPACE_TRUST_APPLY_CHANGE_MAX_CHARS,
    )
    next_refresh_expectation: str | None = Field(default=None, max_length=_WORKSPACE_TRUST_NEXT_REFRESH_MAX_CHARS)
    freshness_note: str | None = Field(default=None, max_length=_WORKSPACE_TRUST_FRESHNESS_NOTE_MAX_CHARS)

    @field_validator("latest_competitor_status", mode="before")
    @classmethod
    def normalize_latest_competitor_status(
        cls,
        value: Any,
    ) -> SEORecommendationWorkspaceTrustCompetitorStatus | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in {"normal", "recovered", "degraded", "failed"}:
            return None
        return normalized  # type: ignore[return-value]

    @field_validator(
        "latest_recommendation_apply_title",
        mode="before",
    )
    @classmethod
    def normalize_latest_recommendation_apply_title(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_WORKSPACE_TRUST_APPLY_TITLE_MAX_CHARS)

    @field_validator(
        "latest_recommendation_apply_change_summary",
        mode="before",
    )
    @classmethod
    def normalize_latest_recommendation_apply_change_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_WORKSPACE_TRUST_APPLY_CHANGE_MAX_CHARS)

    @field_validator(
        "next_refresh_expectation",
        mode="before",
    )
    @classmethod
    def normalize_next_refresh_expectation(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_WORKSPACE_TRUST_NEXT_REFRESH_MAX_CHARS)

    @field_validator(
        "freshness_note",
        mode="before",
    )
    @classmethod
    def normalize_freshness_note(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_WORKSPACE_TRUST_FRESHNESS_NOTE_MAX_CHARS)


class SEOWorkspaceSectionFreshnessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: SEOWorkspaceSectionFreshnessState
    message: str = Field(min_length=1, max_length=_WORKSPACE_SECTION_FRESHNESS_MESSAGE_MAX_CHARS)
    state_code: SEOWorkspaceSectionFreshnessStateCode | None = None
    state_label: str | None = Field(default=None, max_length=80)
    state_reason: str | None = Field(default=None, max_length=_WORKSPACE_SECTION_FRESHNESS_MESSAGE_MAX_CHARS)
    evaluated_at: datetime | None = None
    refresh_expected: bool | None = None

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, value: Any) -> SEOWorkspaceSectionFreshnessState:
        normalized = str(value or "").strip().lower()
        if normalized not in {"fresh", "pending_refresh", "running", "stale"}:
            raise ValueError("Invalid workspace section freshness state")
        return normalized  # type: ignore[return-value]

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_WORKSPACE_SECTION_FRESHNESS_MESSAGE_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Workspace section freshness message is required")
        return cleaned

    @field_validator("state_code", mode="before")
    @classmethod
    def normalize_state_code(cls, value: Any) -> SEOWorkspaceSectionFreshnessStateCode | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in {"fresh", "pending_refresh", "running", "stale", "possibly_outdated"}:
            return None
        return normalized  # type: ignore[return-value]

    @field_validator("state_label", mode="before")
    @classmethod
    def normalize_state_label(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=80)

    @field_validator("state_reason", mode="before")
    @classmethod
    def normalize_state_reason(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_WORKSPACE_SECTION_FRESHNESS_MESSAGE_MAX_CHARS)

    @model_validator(mode="after")
    def derive_section_state_metadata(self) -> "SEOWorkspaceSectionFreshnessRead":
        state_code = self.state_code
        if state_code is None:
            state_code = self.state
            self.state_code = state_code

        if self.state_label is None:
            self.state_label = {
                "fresh": "Fresh",
                "pending_refresh": "Refresh pending",
                "running": "Run in progress",
                "stale": "Stale",
                "possibly_outdated": "Possibly outdated",
            }.get(state_code, "Stale")

        if self.state_reason is None:
            self.state_reason = self.message

        if self.refresh_expected is None:
            self.refresh_expected = state_code in {"pending_refresh", "running", "possibly_outdated"}
        return self


class SEOCompetitorContextHealthCheckRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SEOCompetitorContextHealthCheckKey
    label: str = Field(min_length=1, max_length=_COMPETITOR_CONTEXT_HEALTH_CHECK_LABEL_MAX_CHARS)
    status: SEOCompetitorContextHealthCheckStatus
    detail: str = Field(min_length=1, max_length=_COMPETITOR_CONTEXT_HEALTH_CHECK_DETAIL_MAX_CHARS)

    @field_validator("key", mode="before")
    @classmethod
    def normalize_key(cls, value: Any) -> SEOCompetitorContextHealthCheckKey:
        normalized = str(value or "").strip().lower()
        if normalized not in _COMPETITOR_CONTEXT_HEALTH_CHECK_KEY_ORDER:
            raise ValueError("Invalid competitor context health check key")
        return normalized  # type: ignore[return-value]

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_COMPETITOR_CONTEXT_HEALTH_CHECK_LABEL_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Context health check label is required")
        return cleaned

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> SEOCompetitorContextHealthCheckStatus:
        normalized = str(value or "").strip().lower()
        if normalized not in {"strong", "weak"}:
            raise ValueError("Invalid competitor context health check status")
        return normalized  # type: ignore[return-value]

    @field_validator("detail", mode="before")
    @classmethod
    def normalize_detail(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_COMPETITOR_CONTEXT_HEALTH_CHECK_DETAIL_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Context health check detail is required")
        return cleaned


class SEOCompetitorContextHealthRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SEOCompetitorContextHealthStatus
    checks: list[SEOCompetitorContextHealthCheckRead] = Field(default_factory=list)
    message: str = Field(min_length=1, max_length=_COMPETITOR_CONTEXT_HEALTH_MESSAGE_MAX_CHARS)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> SEOCompetitorContextHealthStatus:
        normalized = str(value or "").strip().lower()
        if normalized not in {"strong", "mixed", "weak"}:
            raise ValueError("Invalid competitor context health status")
        return normalized  # type: ignore[return-value]

    @field_validator("checks", mode="before")
    @classmethod
    def normalize_checks(cls, value: Any) -> list[SEOCompetitorContextHealthCheckRead]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("checks must be a list")
        parsed: dict[SEOCompetitorContextHealthCheckKey, SEOCompetitorContextHealthCheckRead] = {}
        for item in value:
            try:
                check = SEOCompetitorContextHealthCheckRead.model_validate(item)
            except Exception:  # noqa: BLE001
                continue
            parsed[check.key] = check
        ordered = [parsed[key] for key in _COMPETITOR_CONTEXT_HEALTH_CHECK_KEY_ORDER if key in parsed]
        return ordered[:_COMPETITOR_CONTEXT_HEALTH_MAX_CHECKS]

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_COMPETITOR_CONTEXT_HEALTH_MESSAGE_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Competitor context health message is required")
        return cleaned


class SEORecommendationOrderingExplanationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=_ORDERING_EXPLANATION_MAX_CHARS)
    context_reasons: list[SEORecommendationPriorityReason] = Field(default_factory=list)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_ORDERING_EXPLANATION_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Ordering explanation message is required")
        return cleaned

    @field_validator("context_reasons", mode="before")
    @classmethod
    def normalize_context_reasons(cls, value: Any) -> list[SEORecommendationPriorityReason]:
        return _normalize_priority_reason_list(value)


class SEORecommendationThemeGroupRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: SEORecommendationTheme
    label: str = Field(min_length=1, max_length=_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS)
    count: int = Field(ge=0)
    recommendation_ids: list[str] = Field(default_factory=list)

    @field_validator("theme", mode="before")
    @classmethod
    def normalize_theme(cls, value: Any) -> SEORecommendationTheme:
        normalized = _normalize_recommendation_theme(value)
        if normalized is None:
            raise ValueError("Invalid recommendation theme")
        return normalized

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS)
        if cleaned is None:
            raise ValueError("Theme group label is required")
        return cleaned

    @field_validator("recommendation_ids", mode="before")
    @classmethod
    def normalize_recommendation_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("recommendation_ids must be a list")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = _strip_or_none(str(item) if item is not None else None)
            if cleaned is None:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
            if len(normalized) >= _RECOMMENDATION_THEME_GROUP_RECOMMENDATION_ID_MAX_ITEMS:
                break
        return normalized


class SEORecommendationStartHereRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: SEORecommendationTheme
    theme_label: str = Field(min_length=1, max_length=_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS)
    recommendation_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=_START_HERE_TITLE_MAX_CHARS)
    reason: str = Field(min_length=1, max_length=_START_HERE_REASON_MAX_CHARS)
    context_flags: list[SEORecommendationStartHereContextFlag] = Field(default_factory=list)

    @field_validator("theme", mode="before")
    @classmethod
    def normalize_theme(cls, value: Any) -> SEORecommendationTheme:
        normalized = _normalize_recommendation_theme(value)
        if normalized is None:
            raise ValueError("Invalid recommendation theme")
        return normalized

    @field_validator("theme_label", mode="before")
    @classmethod
    def normalize_theme_label(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS)
        if cleaned is None:
            raise ValueError("theme_label is required")
        return cleaned

    @field_validator("recommendation_id", mode="before")
    @classmethod
    def normalize_recommendation_id(cls, value: Any) -> str:
        cleaned = _strip_or_none(str(value) if value is not None else None)
        if cleaned is None:
            raise ValueError("recommendation_id is required")
        return cleaned

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_START_HERE_TITLE_MAX_CHARS)
        if cleaned is None:
            raise ValueError("title is required")
        return cleaned

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_START_HERE_REASON_MAX_CHARS)
        if cleaned is None:
            raise ValueError("reason is required")
        return cleaned

    @field_validator("context_flags", mode="before")
    @classmethod
    def normalize_context_flags(cls, value: Any) -> list[SEORecommendationStartHereContextFlag]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("context_flags must be a list")
        normalized: list[SEORecommendationStartHereContextFlag] = []
        seen: set[str] = set()
        for item in value:
            cleaned = str(item or "").strip().lower()
            if cleaned not in {"pending_refresh_context", "competitor_backed"}:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)  # type: ignore[arg-type]
        return normalized


class SEORecommendationEEATGapSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_gap_categories: list[SEORecommendationEEATCategory] = Field(default_factory=list)
    supporting_signals: list[str] = Field(default_factory=list)
    message: str = Field(min_length=1, max_length=260)

    @field_validator("top_gap_categories", mode="before")
    @classmethod
    def normalize_top_gap_categories(cls, value: Any) -> list[SEORecommendationEEATCategory]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("top_gap_categories must be a list")
        seen: set[str] = set()
        normalized: list[SEORecommendationEEATCategory] = []
        for item in value:
            category = str(item or "").strip().lower()
            if category not in _EEAT_CATEGORY_ORDER:
                continue
            if category in seen:
                continue
            seen.add(category)
            normalized.append(category)  # type: ignore[arg-type]
            if len(normalized) >= len(_EEAT_CATEGORY_ORDER):
                break
        return normalized

    @field_validator("supporting_signals", mode="before")
    @classmethod
    def normalize_supporting_signals(cls, value: Any) -> list[str]:
        return _compact_text_list(
            value,
            limit=_RECOMMENDATION_EEAT_GAP_SUPPORTING_SIGNALS_MAX_ITEMS,
            max_length=_RECOMMENDATION_EEAT_GAP_SUPPORTING_SIGNAL_MAX_CHARS,
        )

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=260)
        if cleaned is None:
            raise ValueError("EEAT gap summary message is required")
        return cleaned


class SEORecommendationRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    comparison_run_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("audit_run_id", "comparison_run_id", mode="before")
    @classmethod
    def normalize_optional_ids(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @model_validator(mode="after")
    def require_at_least_one_lineage_reference(self) -> "SEORecommendationRunCreateRequest":
        if self.audit_run_id is None and self.comparison_run_id is None:
            raise ValueError("At least one of audit_run_id or comparison_run_id is required")
        return self


class SEORecommendationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    audit_run_id: str | None
    comparison_run_id: str | None
    status: SEORecommendationRunStatus
    total_recommendations: int
    critical_recommendations: int
    warning_recommendations: int
    info_recommendations: int
    category_counts_json: dict[str, int] = Field(default_factory=dict)
    effort_bucket_counts_json: dict[str, int] = Field(default_factory=dict)
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_summary: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("category_counts_json", "effort_bucket_counts_json", mode="before")
    @classmethod
    def normalize_count_maps(cls, value: Any) -> dict[str, int]:
        return _normalize_int_map(value)


class SEORecommendationRunListResponse(BaseModel):
    items: list[SEORecommendationRunRead]
    total: int


class SEORecommendationCompetitorEvidenceLinkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_draft_id: str = Field(min_length=1, max_length=36)
    competitor_name: str = Field(min_length=1, max_length=_RECOMMENDATION_COMPETITOR_LINK_NAME_MAX_CHARS)
    competitor_domain: str | None = Field(default=None, max_length=_RECOMMENDATION_COMPETITOR_LINK_DOMAIN_MAX_CHARS)
    confidence_level: Literal["high", "medium", "low"] | None = None
    source_type: Literal["search", "places", "fallback", "synthetic"] | None = None
    verification_status: Literal["verified", "unverified"] | None = None
    trust_tier: SEORecommendationCompetitorEvidenceTrustTier = "informational_candidate"
    # Backward-compatible mirror for older consumers. Use trust_tier as canonical field.
    evidence_trust_tier: SEORecommendationCompetitorEvidenceTrustTier | None = None
    evidence_summary: str | None = Field(default=None, max_length=_RECOMMENDATION_COMPETITOR_LINK_SUMMARY_MAX_CHARS)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_trust_tier_key(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        if "trust_tier" not in raw and "evidence_trust_tier" in raw:
            normalized = dict(raw)
            normalized["trust_tier"] = raw.get("evidence_trust_tier")
            return normalized
        return raw

    @field_validator("competitor_draft_id", mode="before")
    @classmethod
    def normalize_competitor_draft_id(cls, value: Any) -> str:
        cleaned = _strip_or_none(str(value) if value is not None else None)
        if cleaned is None:
            raise ValueError("competitor_draft_id is required")
        return cleaned[:36]

    @field_validator("competitor_name", mode="before")
    @classmethod
    def normalize_competitor_name(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_COMPETITOR_LINK_NAME_MAX_CHARS)
        if cleaned is None:
            raise ValueError("competitor_name is required")
        return cleaned

    @field_validator("competitor_domain", mode="before")
    @classmethod
    def normalize_competitor_domain(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_COMPETITOR_LINK_DOMAIN_MAX_CHARS)

    @field_validator("confidence_level", mode="before")
    @classmethod
    def normalize_confidence_level(cls, value: Any) -> Literal["high", "medium", "low"] | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in {"high", "medium", "low"}:
            return None
        return normalized  # type: ignore[return-value]

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, value: Any) -> Literal["search", "places", "fallback", "synthetic"] | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in {"search", "places", "fallback", "synthetic"}:
            return None
        return normalized  # type: ignore[return-value]

    @field_validator("verification_status", mode="before")
    @classmethod
    def normalize_verification_status(cls, value: Any) -> Literal["verified", "unverified"] | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in {"verified", "unverified"}:
            return None
        return normalized  # type: ignore[return-value]

    @field_validator("trust_tier", mode="before")
    @classmethod
    def normalize_trust_tier(cls, value: Any) -> SEORecommendationCompetitorEvidenceTrustTier:
        normalized = str(value or "").strip().lower()
        if normalized not in {"trusted_verified", "informational_unverified", "informational_candidate"}:
            return "informational_candidate"
        return normalized  # type: ignore[return-value]

    @field_validator("evidence_trust_tier", mode="before")
    @classmethod
    def normalize_evidence_trust_tier(cls, value: Any) -> SEORecommendationCompetitorEvidenceTrustTier | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in {"trusted_verified", "informational_unverified", "informational_candidate"}:
            return None
        return normalized  # type: ignore[return-value]

    @field_validator("evidence_summary", mode="before")
    @classmethod
    def normalize_evidence_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_COMPETITOR_LINK_SUMMARY_MAX_CHARS)

    @model_validator(mode="after")
    def sync_legacy_trust_tier_field(self) -> "SEORecommendationCompetitorEvidenceLinkRead":
        self.evidence_trust_tier = self.trust_tier
        return self


class SEORecommendationActionDeltaRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_competitor_pattern: str = Field(min_length=1, max_length=_RECOMMENDATION_ACTION_DELTA_PATTERN_MAX_CHARS)
    observed_site_gap: str = Field(min_length=1, max_length=_RECOMMENDATION_ACTION_DELTA_GAP_MAX_CHARS)
    recommended_operator_action: str = Field(min_length=1, max_length=_RECOMMENDATION_ACTION_DELTA_ACTION_MAX_CHARS)
    evidence_strength: SEORecommendationSignalSupportLevel

    @field_validator("observed_competitor_pattern", mode="before")
    @classmethod
    def normalize_observed_competitor_pattern(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_ACTION_DELTA_PATTERN_MAX_CHARS)
        if cleaned is None:
            raise ValueError("observed_competitor_pattern is required")
        return cleaned

    @field_validator("observed_site_gap", mode="before")
    @classmethod
    def normalize_observed_site_gap(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_ACTION_DELTA_GAP_MAX_CHARS)
        if cleaned is None:
            raise ValueError("observed_site_gap is required")
        return cleaned

    @field_validator("recommended_operator_action", mode="before")
    @classmethod
    def normalize_recommended_operator_action(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_ACTION_DELTA_ACTION_MAX_CHARS)
        if cleaned is None:
            raise ValueError("recommended_operator_action is required")
        return cleaned

    @field_validator("evidence_strength", mode="before")
    @classmethod
    def normalize_evidence_strength(cls, value: Any) -> SEORecommendationSignalSupportLevel:
        normalized = str(value or "").strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("Invalid evidence_strength")
        return normalized  # type: ignore[return-value]


class SEORecommendationPriorityRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority_level: SEORecommendationPriorityLevel
    priority_reason: str = Field(min_length=1, max_length=_RECOMMENDATION_PRIORITY_REASON_MAX_CHARS)
    effort_hint: SEORecommendationEffortHint | None = None

    @field_validator("priority_level", mode="before")
    @classmethod
    def normalize_priority_level(cls, value: Any) -> SEORecommendationPriorityLevel:
        normalized = str(value or "").strip().lower()
        if normalized not in {"high", "medium", "low"}:
            raise ValueError("Invalid priority_level")
        return normalized  # type: ignore[return-value]

    @field_validator("priority_reason", mode="before")
    @classmethod
    def normalize_priority_reason(cls, value: Any) -> str:
        cleaned = _compact_text(value, max_length=_RECOMMENDATION_PRIORITY_REASON_MAX_CHARS)
        if cleaned is None:
            raise ValueError("priority_reason is required")
        return cleaned

    @field_validator("effort_hint", mode="before")
    @classmethod
    def normalize_effort_hint(cls, value: Any) -> SEORecommendationEffortHint | None:
        if value is None:
            return None
        normalized = str(value or "").strip().lower()
        if normalized not in {"quick_win", "moderate", "larger_change"}:
            return None
        return normalized  # type: ignore[return-value]


class SEORecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    recommendation_run_id: str
    audit_run_id: str | None
    comparison_run_id: str | None
    rule_key: str
    category: SEORecommendationCategory
    severity: SEORecommendationSeverity
    title: str
    rationale: str
    priority_score: int
    priority_band: SEORecommendationPriorityBand
    effort_bucket: SEORecommendationEffort
    status: SEORecommendationStatus
    recommendation_progress_status: SEORecommendationProgressStatus = "suggested"
    recommendation_progress_summary: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_PROGRESS_SUMMARY_MAX_CHARS,
    )
    recommendation_lifecycle_state: SEORecommendationLifecycleState = "active"
    recommendation_lifecycle_summary: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_LIFECYCLE_SUMMARY_MAX_CHARS,
    )
    recommendation_evidence_summary: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_EVIDENCE_SUMMARY_MAX_CHARS,
    )
    recommendation_observed_gap_summary: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_OBSERVED_GAP_SUMMARY_MAX_CHARS,
    )
    recommendation_evidence_trace: list[str] = Field(default_factory=list)
    recommendation_action_clarity: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_ACTION_CLARITY_MAX_CHARS,
    )
    recommendation_expected_outcome: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_EXPECTED_OUTCOME_MAX_CHARS,
    )
    recommendation_target_context: SEORecommendationTargetContext | None = None
    recommendation_target_page_hints: list[str] = Field(default_factory=list)
    competitor_evidence_links: list[SEORecommendationCompetitorEvidenceLinkRead] = Field(default_factory=list)
    competitor_linkage_summary: str | None = Field(
        default=None,
        max_length=_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS,
    )
    recommendation_action_delta: SEORecommendationActionDeltaRead | None = None
    recommendation_priority: SEORecommendationPriorityRead | None = None
    action_lineage: ActionLineageResponse | None = None
    decision: SEORecommendationDecision | None = None
    decision_reason: str | None = None
    assigned_principal_id: str | None = None
    due_at: datetime | None = None
    snoozed_until: datetime | None = None
    resolved_at: datetime | None = None
    updated_by_principal_id: str | None = None
    evidence_json: dict[str, object] | None
    eeat_categories: list[SEORecommendationEEATCategory] = Field(default_factory=list)
    primary_eeat_category: SEORecommendationEEATCategory | None = None
    priority_reasons: list[SEORecommendationPriorityReason] = Field(default_factory=list)
    primary_priority_reason: SEORecommendationPriorityReason | None = None
    theme: SEORecommendationTheme | None = None
    theme_label: str | None = Field(default=None, max_length=_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS)
    created_at: datetime
    updated_at: datetime

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category_field(cls, value: Any) -> SEORecommendationCategory:
        return _normalize_category(value)

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity_field(cls, value: Any) -> SEORecommendationSeverity:
        return _normalize_severity(value)

    @field_validator("effort_bucket", mode="before")
    @classmethod
    def normalize_effort_field(cls, value: Any) -> SEORecommendationEffort:
        return _normalize_effort(value)

    @field_validator("priority_band", mode="before")
    @classmethod
    def normalize_priority_band_field(cls, value: Any) -> SEORecommendationPriorityBand:
        return _normalize_priority_band(value)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status_field(cls, value: Any) -> SEORecommendationStatus:
        return _normalize_status(value)

    @field_validator("recommendation_progress_status", mode="before")
    @classmethod
    def normalize_recommendation_progress_status(
        cls,
        value: Any,
    ) -> SEORecommendationProgressStatus:
        normalized = str(value or "").strip().lower()
        if normalized not in {"suggested", "applied_pending_refresh", "reflected_in_latest_analysis"}:
            return "suggested"
        return normalized  # type: ignore[return-value]

    @field_validator("recommendation_progress_summary", mode="before")
    @classmethod
    def normalize_recommendation_progress_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_PROGRESS_SUMMARY_MAX_CHARS)

    @field_validator("recommendation_lifecycle_state", mode="before")
    @classmethod
    def normalize_recommendation_lifecycle_state(
        cls,
        value: Any,
    ) -> SEORecommendationLifecycleState:
        normalized = str(value or "").strip().lower()
        if normalized not in {
            "active",
            "applied_waiting_validation",
            "reflected_still_relevant",
            "likely_resolved",
        }:
            return "active"
        return normalized  # type: ignore[return-value]

    @field_validator("recommendation_lifecycle_summary", mode="before")
    @classmethod
    def normalize_recommendation_lifecycle_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_LIFECYCLE_SUMMARY_MAX_CHARS)

    @field_validator("recommendation_evidence_summary", mode="before")
    @classmethod
    def normalize_recommendation_evidence_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_EVIDENCE_SUMMARY_MAX_CHARS)

    @field_validator("recommendation_observed_gap_summary", mode="before")
    @classmethod
    def normalize_recommendation_observed_gap_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_OBSERVED_GAP_SUMMARY_MAX_CHARS)

    @field_validator("recommendation_evidence_trace", mode="before")
    @classmethod
    def normalize_recommendation_evidence_trace(cls, value: Any) -> list[str]:
        return _compact_text_list(
            value,
            limit=_RECOMMENDATION_EVIDENCE_TRACE_MAX_ITEMS,
            max_length=_RECOMMENDATION_EVIDENCE_TRACE_MAX_CHARS,
        )

    @field_validator("recommendation_action_clarity", mode="before")
    @classmethod
    def normalize_recommendation_action_clarity(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_ACTION_CLARITY_MAX_CHARS)

    @field_validator("recommendation_expected_outcome", mode="before")
    @classmethod
    def normalize_recommendation_expected_outcome(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_EXPECTED_OUTCOME_MAX_CHARS)

    @field_validator("recommendation_target_context", mode="before")
    @classmethod
    def normalize_recommendation_target_context(
        cls,
        value: Any,
    ) -> SEORecommendationTargetContext | None:
        if value is None:
            return None
        return _normalize_recommendation_target_context(value)

    @field_validator("recommendation_target_page_hints", mode="before")
    @classmethod
    def normalize_recommendation_target_page_hints(cls, value: Any) -> list[str]:
        return _compact_text_list(
            value,
            limit=_RECOMMENDATION_TARGET_PAGE_HINT_MAX_ITEMS,
            max_length=_RECOMMENDATION_TARGET_PAGE_HINT_MAX_CHARS,
        )

    @field_validator("competitor_evidence_links", mode="before")
    @classmethod
    def normalize_competitor_evidence_links(
        cls,
        value: Any,
    ) -> list[SEORecommendationCompetitorEvidenceLinkRead]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("competitor_evidence_links must be a list")
        normalized: list[SEORecommendationCompetitorEvidenceLinkRead] = []
        seen_ids: set[str] = set()
        for item in value:
            try:
                parsed = (
                    item
                    if isinstance(item, SEORecommendationCompetitorEvidenceLinkRead)
                    else SEORecommendationCompetitorEvidenceLinkRead.model_validate(item)
                )
            except Exception:  # noqa: BLE001
                continue
            if parsed.competitor_draft_id in seen_ids:
                continue
            seen_ids.add(parsed.competitor_draft_id)
            normalized.append(parsed)
            if len(normalized) >= _RECOMMENDATION_COMPETITOR_LINK_MAX_ITEMS:
                break
        return normalized

    @field_validator("competitor_linkage_summary", mode="before")
    @classmethod
    def normalize_competitor_linkage_summary(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_COMPETITOR_LINKAGE_SUMMARY_MAX_CHARS)

    @field_validator("recommendation_action_delta", mode="before")
    @classmethod
    def normalize_recommendation_action_delta(
        cls,
        value: Any,
    ) -> SEORecommendationActionDeltaRead | None:
        if value is None:
            return None
        if isinstance(value, SEORecommendationActionDeltaRead):
            return value
        try:
            return SEORecommendationActionDeltaRead.model_validate(value)
        except Exception:  # noqa: BLE001
            return None

    @field_validator("recommendation_priority", mode="before")
    @classmethod
    def normalize_recommendation_priority(
        cls,
        value: Any,
    ) -> SEORecommendationPriorityRead | None:
        if value is None:
            return None
        if isinstance(value, SEORecommendationPriorityRead):
            return value
        try:
            return SEORecommendationPriorityRead.model_validate(value)
        except Exception:  # noqa: BLE001
            return None

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision_field(cls, value: Any) -> SEORecommendationDecision | None:
        return _normalize_decision(value)

    @field_validator("eeat_categories", mode="before")
    @classmethod
    def normalize_eeat_categories(
        cls,
        value: Any,
    ) -> list[SEORecommendationEEATCategory]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("eeat_categories must be a list")
        seen: set[str] = set()
        normalized: list[SEORecommendationEEATCategory] = []
        for item in value:
            category = str(item or "").strip().lower()
            if category not in _EEAT_CATEGORY_ORDER:
                continue
            if category in seen:
                continue
            seen.add(category)
            normalized.append(category)  # type: ignore[arg-type]
            if len(normalized) >= len(_EEAT_CATEGORY_ORDER):
                break
        return normalized

    @field_validator("primary_eeat_category", mode="before")
    @classmethod
    def normalize_primary_eeat_category(
        cls,
        value: Any,
    ) -> SEORecommendationEEATCategory | None:
        if value is None:
            return None
        category = str(value).strip().lower()
        if category not in _EEAT_CATEGORY_ORDER:
            return None
        return category  # type: ignore[return-value]

    @field_validator("priority_reasons", mode="before")
    @classmethod
    def normalize_priority_reasons(
        cls,
        value: Any,
    ) -> list[SEORecommendationPriorityReason]:
        return _normalize_priority_reason_list(value)

    @field_validator("primary_priority_reason", mode="before")
    @classmethod
    def normalize_primary_priority_reason(
        cls,
        value: Any,
    ) -> SEORecommendationPriorityReason | None:
        if value is None:
            return None
        return _normalize_priority_reason(value)

    @field_validator("theme", mode="before")
    @classmethod
    def normalize_theme(
        cls,
        value: Any,
    ) -> SEORecommendationTheme | None:
        if value is None:
            return None
        return _normalize_recommendation_theme(value)

    @field_validator("theme_label", mode="before")
    @classmethod
    def normalize_theme_label(
        cls,
        value: Any,
    ) -> str | None:
        return _compact_text(value, max_length=_RECOMMENDATION_THEME_GROUP_LABEL_MAX_CHARS)

    @model_validator(mode="after")
    def derive_eeat_categories(self) -> "SEORecommendationRead":
        categories = list(self.eeat_categories)
        if not categories:
            signals: list[object] = [self.rule_key]
            if isinstance(self.evidence_json, dict):
                finding_types = self.evidence_json.get("finding_types")
                if isinstance(finding_types, list):
                    signals.extend(finding_types)
                counts = self.evidence_json.get("counts")
                if isinstance(counts, dict):
                    signals.extend(list(counts.keys()))
            categories = infer_eeat_categories_from_signals(signals)
            self.eeat_categories = categories

        if self.primary_eeat_category is None and categories:
            self.primary_eeat_category = categories[0]
        elif self.primary_eeat_category is not None and self.primary_eeat_category not in categories:
            self.primary_eeat_category = categories[0] if categories else None
        return self

    @model_validator(mode="after")
    def derive_priority_reasons(self) -> "SEORecommendationRead":
        reasons = list(self.priority_reasons)
        if not reasons:
            reasons = _derive_recommendation_priority_reasons(
                comparison_run_id=self.comparison_run_id,
                evidence_json=self.evidence_json if isinstance(self.evidence_json, dict) else None,
                eeat_categories=self.eeat_categories,
                title=self.title,
                rationale=self.rationale,
            )
        else:
            reasons = [reason for reason in _PRIORITY_REASON_ORDER if reason in reasons]

        self.priority_reasons = reasons
        if self.primary_priority_reason is None and reasons:
            self.primary_priority_reason = reasons[0]
        elif self.primary_priority_reason is not None and self.primary_priority_reason not in reasons:
            self.primary_priority_reason = reasons[0] if reasons else None
        return self

    @model_validator(mode="after")
    def derive_theme(self) -> "SEORecommendationRead":
        if self.theme is None:
            self.theme = _derive_recommendation_theme(
                eeat_categories=self.eeat_categories,
                priority_reasons=self.priority_reasons,
                rule_key=self.rule_key,
                title=self.title,
                rationale=self.rationale,
            )
        if self.theme_label is None and self.theme is not None:
            self.theme_label = format_recommendation_theme_label(self.theme)
        return self

    @model_validator(mode="after")
    def derive_recommendation_evidence_summary(self) -> "SEORecommendationRead":
        if self.recommendation_evidence_summary is not None:
            return self
        self.recommendation_evidence_summary = _derive_recommendation_evidence_summary(
            priority_reasons=self.priority_reasons,
            eeat_categories=self.eeat_categories,
            evidence_json=self.evidence_json if isinstance(self.evidence_json, dict) else None,
        )
        return self

    @model_validator(mode="after")
    def derive_recommendation_progress_summary(self) -> "SEORecommendationRead":
        if self.recommendation_progress_summary is not None:
            return self

        if self.recommendation_progress_status == "applied_pending_refresh":
            self.recommendation_progress_summary = (
                "Applied. Waiting for the next analysis refresh to reflect this change."
            )
        elif self.recommendation_progress_status == "reflected_in_latest_analysis":
            self.recommendation_progress_summary = "Applied and reflected in the latest analysis."
        else:
            self.recommendation_progress_summary = "Suggested action not yet applied."
        return self

    @model_validator(mode="after")
    def derive_recommendation_action_clarity(self) -> "SEORecommendationRead":
        if self.recommendation_action_clarity is not None:
            return self
        self.recommendation_action_clarity = _derive_recommendation_action_clarity(
            title=self.title,
            rationale=self.rationale,
            rule_key=self.rule_key,
            theme=self.theme,
            recommendation_evidence_summary=self.recommendation_evidence_summary,
        )
        return self

    @model_validator(mode="after")
    def derive_recommendation_expected_outcome(self) -> "SEORecommendationRead":
        if self.recommendation_expected_outcome is not None:
            return self
        self.recommendation_expected_outcome = _derive_recommendation_expected_outcome(
            eeat_categories=self.eeat_categories,
            priority_reasons=self.priority_reasons,
            theme=self.theme,
            recommendation_evidence_summary=self.recommendation_evidence_summary,
        )
        return self

    @model_validator(mode="after")
    def derive_recommendation_target_context(self) -> "SEORecommendationRead":
        if self.recommendation_target_context is not None:
            return self
        self.recommendation_target_context = _derive_recommendation_target_context(
            rule_key=self.rule_key,
            title=self.title,
            rationale=self.rationale,
            recommendation_action_clarity=self.recommendation_action_clarity,
            recommendation_evidence_summary=self.recommendation_evidence_summary,
            theme=self.theme,
        )
        return self

    @model_validator(mode="after")
    def derive_recommendation_observed_gap_summary(self) -> "SEORecommendationRead":
        if self.recommendation_observed_gap_summary is not None:
            return self
        self.recommendation_observed_gap_summary = _derive_recommendation_observed_gap_summary(
            rule_key=self.rule_key,
            title=self.title,
            rationale=self.rationale,
            recommendation_evidence_summary=self.recommendation_evidence_summary,
            recommendation_target_context=self.recommendation_target_context,
            eeat_categories=self.eeat_categories,
            priority_reasons=self.priority_reasons,
            theme=self.theme,
        )
        return self

    @model_validator(mode="after")
    def derive_recommendation_evidence_trace(self) -> "SEORecommendationRead":
        if self.recommendation_evidence_trace:
            return self
        self.recommendation_evidence_trace = _derive_recommendation_evidence_trace(
            priority_reasons=self.priority_reasons,
            eeat_categories=self.eeat_categories,
            recommendation_target_context=self.recommendation_target_context,
            recommendation_evidence_summary=self.recommendation_evidence_summary,
            recommendation_observed_gap_summary=self.recommendation_observed_gap_summary,
            evidence_json=self.evidence_json if isinstance(self.evidence_json, dict) else None,
            theme=self.theme,
        )
        return self

    @model_validator(mode="after")
    def derive_recommendation_lifecycle(self) -> "SEORecommendationRead":
        if self.recommendation_lifecycle_state == "active":
            if self.recommendation_progress_status == "applied_pending_refresh":
                self.recommendation_lifecycle_state = "applied_waiting_validation"
            elif self.recommendation_progress_status == "reflected_in_latest_analysis":
                observed_gap = (self.recommendation_observed_gap_summary or "").strip().lower()
                has_meaningful_observed_gap = bool(
                    observed_gap
                    and observed_gap
                    != "current site signals in this recommendation area appear limited or inconsistent."
                )
                meaningful_priority_reasons = [
                    reason for reason in self.priority_reasons if reason not in {"general", "pending_refresh_context"}
                ]
                meaningful_trace_tokens = [
                    token
                    for token in self.recommendation_evidence_trace
                    if token.lower() not in {"audit-backed", "general site signals"}
                ]
                has_specific_target_context = (
                    self.recommendation_target_context is not None and self.recommendation_target_context != "general"
                )
                has_current_signal = any(
                    [
                        has_meaningful_observed_gap,
                        self.recommendation_evidence_summary,
                        bool(meaningful_trace_tokens),
                        has_specific_target_context,
                        bool(meaningful_priority_reasons),
                        bool(self.eeat_categories),
                    ]
                )
                self.recommendation_lifecycle_state = (
                    "reflected_still_relevant" if has_current_signal else "likely_resolved"
                )

        if self.recommendation_lifecycle_summary is None:
            if self.recommendation_lifecycle_state == "applied_waiting_validation":
                self.recommendation_lifecycle_summary = "Applied and waiting for refreshed validation."
            elif self.recommendation_lifecycle_state == "reflected_still_relevant":
                self.recommendation_lifecycle_summary = "Reflected in analysis, but still appears relevant."
            elif self.recommendation_lifecycle_state == "likely_resolved":
                self.recommendation_lifecycle_summary = "Likely addressed in the latest analysis."
            else:
                self.recommendation_lifecycle_summary = "Still an active recommendation."
        return self


class SEORecommendationFilteredSummary(BaseModel):
    total: int
    open: int = 0
    accepted: int = 0
    dismissed: int = 0
    high_priority: int = 0


class SEORecommendationListResponse(BaseModel):
    items: list[SEORecommendationRead]
    total: int
    filtered_summary: SEORecommendationFilteredSummary | None = None
    by_status: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_effort_bucket: dict[str, int] = Field(default_factory=dict)
    by_priority_band: dict[str, int] = Field(default_factory=dict)


class SEORecommendationRunReportRead(BaseModel):
    recommendation_run: SEORecommendationRunRead
    rollups: dict[str, dict[str, int]]
    recommendations: SEORecommendationListResponse


class SEORecommendationWorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SEORecommendationStatus | None = None
    decision: SEORecommendationDecision | None = None
    decision_reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    assigned_principal_id: str | None = Field(default=None, max_length=64)
    due_at: datetime | None = None
    snoozed_until: datetime | None = None

    @field_validator("assigned_principal_id", mode="before")
    @classmethod
    def normalize_assigned_principal(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("decision_reason", mode="before")
    @classmethod
    def normalize_decision_reason(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status_input(cls, value: Any) -> SEORecommendationStatus | None:
        if value is None:
            return None
        return _normalize_status(value)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision_input(cls, value: Any) -> SEORecommendationDecision | None:
        return _normalize_decision(value)

    @model_validator(mode="after")
    def validate_note_alias_consistency(self) -> "SEORecommendationWorkflowUpdateRequest":
        if "note" in self.model_fields_set and "decision_reason" in self.model_fields_set:
            if self.note != self.decision_reason:
                raise ValueError("note and decision_reason must match when both are provided")
        return self

    @model_validator(mode="after")
    def require_update_field(self) -> "SEORecommendationWorkflowUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one workflow field is required")
        return self


class SEORecommendationBacklogRead(BaseModel):
    business_id: str
    site_id: str
    total_actionable: int
    items: list[SEORecommendationRead]


class SEORecommendationPrioritizedReportRead(BaseModel):
    business_id: str
    site_id: str
    generated_at: datetime
    total_recommendations: int
    backlog_total: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_severity: dict[str, int]
    by_effort_bucket: dict[str, int]
    by_priority_band: dict[str, int]
    backlog: SEORecommendationListResponse


class SEORecommendationNarrativeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    recommendation_run_id: str
    version: int
    status: SEORecommendationNarrativeStatus
    narrative_text: str | None
    top_themes_json: list[str] = Field(default_factory=list)
    sections_json: dict[str, object] | None
    competitor_influence: "SEORecommendationCompetitorInfluenceRead | None" = None
    signal_summary: SEORecommendationSignalSummaryRead | None = None
    action_summary: SEORecommendationActionSummaryRead | None = None
    provider_name: str
    model_name: str
    prompt_version: str
    error_message: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("top_themes_json", mode="before")
    @classmethod
    def normalize_top_themes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        raise TypeError("top_themes_json must be a list")

    @model_validator(mode="after")
    def derive_competitor_influence(self) -> "SEORecommendationNarrativeRead":
        if self.competitor_influence is not None:
            return self
        if not isinstance(self.sections_json, dict):
            return self
        raw = self.sections_json.get("competitor_influence")
        if not isinstance(raw, dict):
            return self
        try:
            self.competitor_influence = SEORecommendationCompetitorInfluenceRead.model_validate(raw)
        except Exception:  # noqa: BLE001
            self.competitor_influence = None
        return self

    @model_validator(mode="after")
    def derive_signal_summary(self) -> "SEORecommendationNarrativeRead":
        if self.signal_summary is not None:
            return self

        sections = self.sections_json if isinstance(self.sections_json, dict) else {}
        summary = _compact_text(sections.get("summary"), max_length=_ACTION_SUMMARY_WHY_MAX_CHARS)
        priority_rationale = _compact_text(
            sections.get("priority_rationale"),
            max_length=_ACTION_SUMMARY_WHY_MAX_CHARS,
        )
        next_actions = _compact_text_list(
            sections.get("next_actions"),
            limit=5,
            max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS,
        )
        recommendation_references = _compact_text_list(
            sections.get("recommendation_references"),
            limit=_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS,
            max_length=80,
        )
        top_themes = _compact_text_list(
            self.top_themes_json,
            limit=_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS,
            max_length=_ACTION_SUMMARY_EVIDENCE_ITEM_MAX_CHARS,
        )
        narrative_text = _compact_text(self.narrative_text, max_length=_ACTION_SUMMARY_WHY_MAX_CHARS)

        site_signal_used = bool(summary or priority_rationale or next_actions or narrative_text)
        competitor_signal_used = bool(self.competitor_influence is not None and self.competitor_influence.used)
        reference_signal_used = bool(recommendation_references)

        evidence_sources: list[str] = []
        if site_signal_used:
            evidence_sources.append("site")
        if competitor_signal_used:
            evidence_sources.append("competitors")
        if reference_signal_used:
            evidence_sources.append("references")
        if top_themes:
            evidence_sources.append("themes")

        if not evidence_sources:
            self.signal_summary = None
            return self

        site_richness_score = sum(1 for value in (summary, priority_rationale, narrative_text) if value)
        if next_actions:
            site_richness_score += 1
        source_count = len(evidence_sources)
        if source_count >= 3 and site_richness_score >= 2 and (competitor_signal_used or reference_signal_used):
            support_level: SEORecommendationSignalSupportLevel = "high"
        elif source_count >= 2 or site_richness_score >= 2:
            support_level = "medium"
        else:
            support_level = "low"

        try:
            self.signal_summary = SEORecommendationSignalSummaryRead.model_validate(
                {
                    "support_level": support_level,
                    "evidence_sources": evidence_sources,
                    "competitor_signal_used": competitor_signal_used,
                    "site_signal_used": site_signal_used,
                    "reference_signal_used": reference_signal_used,
                }
            )
        except Exception:  # noqa: BLE001
            self.signal_summary = None
        return self

    @model_validator(mode="after")
    def derive_action_summary(self) -> "SEORecommendationNarrativeRead":
        if self.action_summary is not None:
            return self

        sections = self.sections_json if isinstance(self.sections_json, dict) else {}
        summary = _compact_text(sections.get("summary"), max_length=_ACTION_SUMMARY_WHY_MAX_CHARS)
        priority_rationale = _compact_text(
            sections.get("priority_rationale"),
            max_length=_ACTION_SUMMARY_WHY_MAX_CHARS,
        )
        next_actions = _compact_text_list(
            sections.get("next_actions"),
            limit=5,
            max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS,
        )
        recommendation_references = _compact_text_list(
            sections.get("recommendation_references"),
            limit=_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS,
            max_length=80,
        )
        top_themes = _compact_text_list(
            self.top_themes_json,
            limit=_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS,
            max_length=_ACTION_SUMMARY_EVIDENCE_ITEM_MAX_CHARS,
        )
        narrative_sentence = _first_sentence(
            self.narrative_text,
            max_length=_ACTION_SUMMARY_PRIMARY_ACTION_MAX_CHARS,
        )

        primary_action = next_actions[0] if next_actions else (summary or narrative_sentence)
        why_it_matters = priority_rationale or summary or narrative_sentence

        evidence_candidates: list[str] = []
        for value in top_themes:
            evidence_candidates.append(value)
        for recommendation_id in recommendation_references:
            evidence_candidates.append(f"Linked recommendation: {recommendation_id}")
        if self.competitor_influence is not None and self.competitor_influence.used:
            for opportunity in self.competitor_influence.top_opportunities[:2]:
                evidence_candidates.append(f"Competitor gap: {opportunity}")
        for item in (summary, priority_rationale):
            if item:
                evidence_candidates.append(item)
        evidence = self._dedupe_and_bound(
            evidence_candidates,
            limit=_ACTION_SUMMARY_EVIDENCE_MAX_ITEMS,
            max_length=_ACTION_SUMMARY_EVIDENCE_ITEM_MAX_CHARS,
        )

        first_step = next_actions[0] if next_actions else None
        if first_step is None and recommendation_references:
            first_step = _compact_text(
                f"Review recommendation {recommendation_references[0]} and define owner/timeline.",
                max_length=_ACTION_SUMMARY_FIRST_STEP_MAX_CHARS,
            )
        if first_step is None:
            first_step = primary_action

        if not primary_action or not why_it_matters or not first_step:
            self.action_summary = None
            return self

        try:
            self.action_summary = SEORecommendationActionSummaryRead.model_validate(
                {
                    "primary_action": primary_action,
                    "why_it_matters": why_it_matters,
                    "evidence": evidence,
                    "first_step": first_step,
                }
            )
        except Exception:  # noqa: BLE001
            self.action_summary = None
        return self

    @staticmethod
    def _dedupe_and_bound(values: list[str], *, limit: int, max_length: int) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = _compact_text(value, max_length=max_length)
            if cleaned is None:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
            if len(normalized) >= limit:
                break
        return normalized


class SEORecommendationCompetitorInfluenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used: bool
    summary: str = Field(min_length=1, max_length=300)
    top_opportunities: list[str] = Field(default_factory=list)
    competitor_names: list[str] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: Any) -> str:
        cleaned = _strip_or_none(str(value) if value is not None else None)
        if cleaned is None:
            raise ValueError("summary is required")
        return cleaned[:300]

    @field_validator("top_opportunities", "competitor_names", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("Expected list")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = _strip_or_none(str(item) if item is not None else None)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
            if len(normalized) >= 5:
                break
        return normalized


class SEORecommendationNarrativeListResponse(BaseModel):
    items: list[SEORecommendationNarrativeRead]
    total: int


class SEORecommendationTuningSuggestionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting: RecommendationTuningSetting
    current_value: int = Field(ge=0, le=100)
    recommended_value: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=500)
    linked_recommendation_ids: list[str] = Field(default_factory=list)
    confidence: SEORecommendationTuningSuggestionConfidence

    @field_validator("linked_recommendation_ids", mode="before")
    @classmethod
    def normalize_linked_recommendation_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("linked_recommendation_ids must be a list")
        normalized: list[str] = []
        for item in value:
            cleaned = _strip_or_none(str(item) if item is not None else None)
            if cleaned:
                normalized.append(cleaned)
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> SEORecommendationTuningSuggestionConfidence:
        normalized = str(value or "").strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("Invalid tuning suggestion confidence")
        return normalized  # type: ignore[return-value]

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str:
        cleaned = _strip_or_none(str(value) if value is not None else None)
        if cleaned is None:
            raise ValueError("reason is required")
        return cleaned


class SEORecommendationWorkspaceSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: str
    site_id: str
    state: SEORecommendationWorkspaceSummaryState
    latest_run: SEORecommendationRunRead | None
    latest_completed_run: SEORecommendationRunRead | None
    recommendations: SEORecommendationListResponse
    grouped_recommendations: list[SEORecommendationThemeGroupRead] = Field(default_factory=list)
    latest_narrative: SEORecommendationNarrativeRead | None
    tuning_suggestions: list[SEORecommendationTuningSuggestionRead] = Field(default_factory=list)
    apply_outcome: SEORecommendationApplyOutcomeRead | None = None
    workspace_trust_summary: SEORecommendationWorkspaceTrustSummaryRead | None = None
    competitor_section_freshness: SEOWorkspaceSectionFreshnessRead | None = None
    recommendation_section_freshness: SEOWorkspaceSectionFreshnessRead | None = None
    analysis_freshness: SEORecommendationAnalysisFreshnessRead | None = None
    ordering_explanation: SEORecommendationOrderingExplanationRead | None = None
    start_here: SEORecommendationStartHereRead | None = None
    eeat_gap_summary: SEORecommendationEEATGapSummaryRead | None = None
    competitor_prompt_preview: AIPromptPreviewRead | None = None
    recommendation_prompt_preview: AIPromptPreviewRead | None = None
    competitor_context_health: SEOCompetitorContextHealthRead | None = None
    site_location_context: str | None = Field(default=None, max_length=_LOCATION_CONTEXT_MAX_CHARS)
    site_primary_location: str | None = Field(default=None, max_length=_PRIMARY_LOCATION_MAX_CHARS)
    site_primary_business_zip: str | None = Field(default=None, max_length=_PRIMARY_ZIP_MAX_CHARS)
    site_location_context_strength: SEORecommendationLocationContextStrength = "unknown"
    site_location_context_source: SEORecommendationLocationContextSource | None = None

    @field_validator("site_location_context", mode="before")
    @classmethod
    def normalize_optional_location_context(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_LOCATION_CONTEXT_MAX_CHARS)

    @field_validator("site_primary_location", mode="before")
    @classmethod
    def normalize_optional_primary_location(cls, value: Any) -> str | None:
        return _compact_text(value, max_length=_PRIMARY_LOCATION_MAX_CHARS)

    @field_validator("site_primary_business_zip", mode="before")
    @classmethod
    def normalize_optional_zip(cls, value: Any) -> str | None:
        compacted = _compact_text(value, max_length=_PRIMARY_ZIP_MAX_CHARS)
        if compacted is None:
            return None
        if len(compacted) != 5 or not compacted.isdigit():
            return None
        return compacted

    @field_validator("site_location_context_strength", mode="before")
    @classmethod
    def normalize_location_context_strength(
        cls,
        value: Any,
    ) -> SEORecommendationLocationContextStrength:
        normalized = str(value or "").strip().lower()
        if normalized not in {"strong", "weak", "unknown"}:
            return "unknown"
        return normalized  # type: ignore[return-value]

    @field_validator("site_location_context_source", mode="before")
    @classmethod
    def normalize_location_context_source(
        cls,
        value: Any,
    ) -> SEORecommendationLocationContextSource | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in {"explicit_location", "service_area", "zip_capture", "fallback"}:
            return None
        return normalized  # type: ignore[return-value]


class SEORecommendationTuningValuesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_candidate_min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    competitor_candidate_big_box_penalty: int | None = Field(default=None, ge=0, le=50)
    competitor_candidate_directory_penalty: int | None = Field(default=None, ge=0, le=50)
    competitor_candidate_local_alignment_bonus: int | None = Field(default=None, ge=0, le=50)


class SEORecommendationTuningValuesRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_candidate_min_relevance_score: int = Field(ge=0, le=100)
    competitor_candidate_big_box_penalty: int = Field(ge=0, le=50)
    competitor_candidate_directory_penalty: int = Field(ge=0, le=50)
    competitor_candidate_local_alignment_bonus: int = Field(ge=0, le=50)


class SEORecommendationTuningImpactPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_values: SEORecommendationTuningValuesPatch | None = None
    proposed_values: SEORecommendationTuningValuesPatch
    recommendation_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    narrative_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("recommendation_run_id", "narrative_id", mode="before")
    @classmethod
    def normalize_optional_ids(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @model_validator(mode="after")
    def require_proposed_values(self) -> "SEORecommendationTuningImpactPreviewRequest":
        if not self.proposed_values.model_dump(exclude_none=True):
            raise ValueError("At least one proposed tuning value is required")
        return self


class SEORecommendationTuningTelemetryWindowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_days: int = Field(ge=1)
    total_runs: int = Field(ge=0)
    total_raw_candidate_count: int = Field(ge=0)
    total_included_candidate_count: int = Field(ge=0)
    total_excluded_candidate_count: int = Field(ge=0)
    exclusion_counts_by_reason: dict[str, int] = Field(default_factory=dict)


class SEORecommendationTuningImpactEstimateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insufficient_data: bool
    estimated_included_candidate_delta: int
    estimated_excluded_candidate_delta: int
    estimated_exclusion_reason_deltas: dict[str, int] = Field(default_factory=dict)
    summary: str
    risk_flags: list[str] = Field(default_factory=list)


class SEORecommendationTuningImpactPreviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_id: str
    site_id: str
    preview_event_id: str | None
    source_recommendation_run_id: str | None
    source_narrative_id: str | None
    current_values: SEORecommendationTuningValuesRead
    proposed_values: SEORecommendationTuningValuesRead
    telemetry_window: SEORecommendationTuningTelemetryWindowRead
    estimated_impact: SEORecommendationTuningImpactEstimateRead
    caveat: str


class SEORecommendationListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SEORecommendationStatus | None = None
    category: SEORecommendationCategory | None = None
    severity: SEORecommendationSeverity | None = None
    effort_bucket: SEORecommendationEffort | None = None
    priority_band: SEORecommendationPriorityBand | None = None
    assigned_principal_id: str | None = None
    source_type: SEORecommendationSourceType | None = None
    recommendation_run_id: str | None = None
    sort_by: SEORecommendationSortBy = "priority_score"
    sort_order: SortOrder = "desc"
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=25, ge=1, le=100)

    @field_validator("assigned_principal_id", mode="before")
    @classmethod
    def normalize_query_assignee(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("recommendation_run_id", mode="before")
    @classmethod
    def normalize_query_run_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _strip_or_none(str(value))

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, value: Any) -> SEORecommendationSourceType | None:
        if value is None:
            return None
        return _normalize_source_type(value)

    @field_validator("sort_by", mode="before")
    @classmethod
    def normalize_sort_by(cls, value: Any) -> SEORecommendationSortBy:
        return _normalize_sort_by(value)

    @field_validator("sort_order", mode="before")
    @classmethod
    def normalize_sort_order(cls, value: Any) -> SortOrder:
        return _normalize_sort_order(value)

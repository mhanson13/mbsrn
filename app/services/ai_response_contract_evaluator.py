from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Sequence


AIResponseEvaluationStatus = Literal["accepted", "accepted_with_warnings", "salvaged", "rejected"]
AIResponseContractScope = Literal["competitor", "recommendation", "migration"]


@dataclass(frozen=True)
class AIResponseContractEvaluation:
    status: AIResponseEvaluationStatus
    score: int
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    valid_item_count: int
    dropped_item_count: int
    required_fields_present: bool
    retryable: bool | None

    @property
    def is_accepted(self) -> bool:
        return self.status in {"accepted", "accepted_with_warnings", "salvaged"}


@dataclass(frozen=True)
class AIResponseContractOperatorSummary:
    status: AIResponseEvaluationStatus
    summary: str
    retryable: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "retryable": self.retryable,
        }


_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_ACTION_VERB_PATTERN = re.compile(
    r"\b(add|adjust|audit|build|create|fix|improve|implement|optimiz(?:e|ing)|publish|prioriti(?:ze|zing)|"
    r"reduce|remove|resolve|track|update|verify)\b",
    re.IGNORECASE,
)
_GENERIC_CONTENT_MARKERS = (
    "best practices",
    "overall strategy",
    "improve seo",
    "enhance visibility",
    "optimize performance",
)

_MIGRATION_SCORE_START = 100
_MIGRATION_MIN_AVG_CONTENT_LEN = 120
_RECOMMENDATION_MIN_GUIDANCE_LEN = 80
_COMPETITOR_MIN_REASONING_LEN = 24

_OPERATOR_SUMMARY_BY_SCOPE_AND_STATUS: dict[AIResponseContractScope, dict[AIResponseEvaluationStatus, str]] = {
    "competitor": {
        "accepted": "Competitor results passed quality checks.",
        "accepted_with_warnings": "Results refined for quality.",
        "salvaged": "Partial competitor results were salvaged.",
        "rejected": "No valid competitors could be identified.",
    },
    "recommendation": {
        "accepted": "Recommendation narrative passed quality checks.",
        "accepted_with_warnings": "Recommendations generated with quality warnings.",
        "salvaged": "Partial recommendation narrative was salvaged.",
        "rejected": "Recommendations were not usable for operator action.",
    },
    "migration": {
        "accepted": "Draft artifact package passed quality checks.",
        "accepted_with_warnings": "Draft artifact generated with quality warnings.",
        "salvaged": "Partial site draft generated.",
        "rejected": "Generated draft artifacts were not usable.",
    },
}

_OPERATOR_REASON_SUMMARY_BY_SCOPE: dict[AIResponseContractScope, dict[str, str]] = {
    "competitor": {
        "low_usable_count": "Limited number of strong competitors identified.",
        "duplicate_heavy_output": "Some duplicate competitors were removed.",
        "empty_candidate_list": "No valid competitors could be identified.",
        "missing_required_fields": "Some incomplete competitors were removed during validation.",
        "invalid_domain_shape": "Some invalid competitor domains were removed.",
        "weak_reasoning_density": "Competitor rationale quality was limited; results were refined.",
        "confidence_invalid": "Invalid confidence values were removed during quality checks.",
    },
    "recommendation": {
        "generic_content_heavy": "Recommendations were too generic to be useful.",
        "low_actionability": "Recommendations lacked clear actionable steps.",
        "missing_action_fields": "Some recommendation steps were incomplete and removed.",
        "insufficient_operator_guidance": "Recommendations lacked enough operator guidance.",
        "empty_recommendations": "No usable recommendation narrative content was generated.",
    },
    "migration": {
        "partial_artifact_only": "Partial site draft generated.",
        "insufficient_content_density": "Generated content was too sparse.",
        "empty_artifact_package": "No usable site draft artifacts were generated.",
        "missing_required_artifact_files": "Generated draft was missing required site files.",
        "invalid_artifact_structure": "Generated draft artifact structure was invalid.",
    },
}


def evaluate_migration_artifact_response(
    *,
    strategy_summary: str | None,
    generated_files: list[dict[str, object]],
    raw_generated_file_count: int,
    page_map_count: int,
) -> AIResponseContractEvaluation:
    valid_item_count = max(0, int(len(generated_files)))
    dropped_item_count = max(0, int(raw_generated_file_count) - valid_item_count)

    reasons: list[str] = []
    warnings: list[str] = []

    summary_text = _clean_optional_text(strategy_summary)
    has_summary = summary_text is not None
    has_index_html = any(_normalized_path(item.get("path")) == "index.html" for item in generated_files)
    has_any_html = any(_normalized_path(item.get("path")).endswith(".html") for item in generated_files)

    non_empty_content_count = 0
    total_content_chars = 0
    for item in generated_files:
        content = _clean_optional_text(item.get("content"))
        if content is None:
            continue
        non_empty_content_count += 1
        total_content_chars += len(content)
    avg_content_len = int(total_content_chars / non_empty_content_count) if non_empty_content_count > 0 else 0

    required_fields_present = bool(has_summary and valid_item_count > 0 and has_any_html)
    if raw_generated_file_count <= 0:
        reasons.append("empty_artifact_package")
    if valid_item_count <= 0:
        reasons.append("missing_required_artifact_files")
    if not has_any_html and valid_item_count > 0:
        reasons.append("invalid_artifact_structure")
    if valid_item_count > 0 and not has_index_html:
        warnings.append("missing_required_artifact_files")
    if non_empty_content_count <= 0:
        reasons.append("insufficient_content_density")
    elif avg_content_len < _MIGRATION_MIN_AVG_CONTENT_LEN:
        warnings.append("insufficient_content_density")
    if page_map_count <= 0:
        warnings.append("partial_artifact_only")
    if dropped_item_count > 0:
        warnings.append("partial_artifact_only")

    score = _MIGRATION_SCORE_START
    score -= 40 if "empty_artifact_package" in reasons else 0
    score -= 35 if "missing_required_artifact_files" in reasons else 0
    score -= 35 if "invalid_artifact_structure" in reasons else 0
    score -= 30 if "insufficient_content_density" in reasons else 0
    score -= 12 if "missing_required_artifact_files" in warnings else 0
    score -= 10 if "insufficient_content_density" in warnings else 0
    score -= min(25, dropped_item_count * 8) if dropped_item_count > 0 else 0
    score -= 8 if "partial_artifact_only" in warnings else 0
    score = _bound_score(score)

    reasons_tuple = _stable_codes(reasons)
    warnings_tuple = _stable_codes(warnings)
    status: AIResponseEvaluationStatus
    if reasons_tuple or not required_fields_present:
        status = "rejected"
    elif dropped_item_count > 0:
        status = "salvaged"
    elif warnings_tuple:
        status = "accepted_with_warnings"
    else:
        status = "accepted"

    return AIResponseContractEvaluation(
        status=status,
        score=score,
        reasons=reasons_tuple,
        warnings=warnings_tuple,
        valid_item_count=valid_item_count,
        dropped_item_count=dropped_item_count,
        required_fields_present=required_fields_present,
        retryable=(True if status == "rejected" else None),
    )


def summarize_competitor_response_contract(
    *,
    evaluation: AIResponseContractEvaluation | None = None,
    status: str | None = None,
    reason_codes: Sequence[object] | None = None,
    warning_codes: Sequence[object] | None = None,
    retryable: bool | None = None,
) -> AIResponseContractOperatorSummary | None:
    return _build_operator_summary(
        scope="competitor",
        evaluation=evaluation,
        status=status,
        reason_codes=reason_codes,
        warning_codes=warning_codes,
        retryable=retryable,
    )


def summarize_recommendation_response_contract(
    *,
    evaluation: AIResponseContractEvaluation | None = None,
    status: str | None = None,
    reason_codes: Sequence[object] | None = None,
    warning_codes: Sequence[object] | None = None,
    retryable: bool | None = None,
) -> AIResponseContractOperatorSummary | None:
    return _build_operator_summary(
        scope="recommendation",
        evaluation=evaluation,
        status=status,
        reason_codes=reason_codes,
        warning_codes=warning_codes,
        retryable=retryable,
    )


def summarize_migration_response_contract(
    *,
    evaluation: AIResponseContractEvaluation | None = None,
    status: str | None = None,
    reason_codes: Sequence[object] | None = None,
    warning_codes: Sequence[object] | None = None,
    retryable: bool | None = None,
) -> AIResponseContractOperatorSummary | None:
    return _build_operator_summary(
        scope="migration",
        evaluation=evaluation,
        status=status,
        reason_codes=reason_codes,
        warning_codes=warning_codes,
        retryable=retryable,
    )


def evaluate_competitor_generation_response(
    *,
    raw_candidate_count: int,
    persisted_draft_rows: list[object],
    removed_by_deduplication_count: int,
    rejected_candidate_count: int,
) -> AIResponseContractEvaluation:
    valid_item_count = max(0, int(len(persisted_draft_rows)))
    dropped_item_count = max(0, int(rejected_candidate_count))
    raw_candidate_count = max(0, int(raw_candidate_count))

    reasons: list[str] = []
    warnings: list[str] = []
    valid_domain_count = 0
    confidence_invalid_count = 0
    weak_reasoning_count = 0
    required_field_count = 0

    for row in persisted_draft_rows:
        suggested_name = _clean_optional_text(getattr(row, "suggested_name", None))
        raw_domain_text = _clean_optional_text(getattr(row, "suggested_domain", None))
        suggested_domain = _normalize_hostname(getattr(row, "suggested_domain", None))
        summary = _clean_optional_text(getattr(row, "summary", None))
        why_competitor = _clean_optional_text(getattr(row, "why_competitor", None))
        evidence = _clean_optional_text(getattr(row, "evidence", None))
        confidence_score = _safe_float(getattr(row, "confidence_score", None))

        if suggested_name and raw_domain_text:
            required_field_count += 1
        if suggested_domain is not None:
            valid_domain_count += 1
        if confidence_score is None or confidence_score < 0 or confidence_score > 1:
            confidence_invalid_count += 1
        reasoning_length = len(summary or "") + len(why_competitor or "") + len(evidence or "")
        if reasoning_length < _COMPETITOR_MIN_REASONING_LEN:
            weak_reasoning_count += 1

    required_fields_present = required_field_count > 0
    if raw_candidate_count <= 0 and valid_item_count <= 0:
        reasons.append("empty_candidate_list")
    if valid_item_count <= 0:
        reasons.append("missing_required_fields")
    if valid_item_count > 0 and confidence_invalid_count >= valid_item_count:
        reasons.append("confidence_invalid")
    if valid_item_count == 1:
        warnings.append("low_usable_count")
    if confidence_invalid_count > 0 and confidence_invalid_count < max(1, valid_item_count):
        warnings.append("confidence_invalid")
    if valid_item_count > 0 and valid_domain_count < valid_item_count:
        warnings.append("invalid_domain_shape")
    if weak_reasoning_count >= max(1, valid_item_count // 2):
        warnings.append("weak_reasoning_density")
    if raw_candidate_count > 0 and removed_by_deduplication_count >= max(2, raw_candidate_count // 2):
        warnings.append("duplicate_heavy_output")
    if dropped_item_count > 0 and valid_item_count > 0:
        warnings.append("missing_required_fields")

    score = 100
    score -= 45 if "empty_candidate_list" in reasons else 0
    score -= 40 if "missing_required_fields" in reasons else 0
    score -= 30 if "confidence_invalid" in reasons else 0
    score -= 12 if "low_usable_count" in warnings else 0
    score -= 10 if "weak_reasoning_density" in warnings else 0
    score -= 10 if "duplicate_heavy_output" in warnings else 0
    score -= min(25, dropped_item_count * 2) if dropped_item_count > 0 else 0
    score = _bound_score(score)

    reasons_tuple = _stable_codes(reasons)
    warnings_tuple = _stable_codes(warnings)
    if reasons_tuple:
        status: AIResponseEvaluationStatus = "rejected"
    elif dropped_item_count > 0:
        status = "salvaged"
    elif warnings_tuple:
        status = "accepted_with_warnings"
    else:
        status = "accepted"

    return AIResponseContractEvaluation(
        status=status,
        score=score,
        reasons=reasons_tuple,
        warnings=warnings_tuple,
        valid_item_count=valid_item_count,
        dropped_item_count=dropped_item_count,
        required_fields_present=required_fields_present,
        retryable=(True if status == "rejected" else None),
    )


def evaluate_recommendation_narrative_response(
    *,
    narrative_text: str | None,
    top_themes: list[str],
    raw_sections: dict[str, object] | None,
    normalized_sections: dict[str, object] | None,
    expected_recommendation_count: int,
) -> AIResponseContractEvaluation:
    narrative = _clean_optional_text(narrative_text)
    raw_sections_payload = raw_sections if isinstance(raw_sections, dict) else {}
    normalized_sections_payload = normalized_sections if isinstance(normalized_sections, dict) else {}

    raw_next_actions = raw_sections_payload.get("next_actions")
    raw_next_actions_count = len(raw_next_actions) if isinstance(raw_next_actions, list) else 0
    normalized_next_actions = normalized_sections_payload.get("next_actions")
    normalized_next_actions_count = len(normalized_next_actions) if isinstance(normalized_next_actions, list) else 0
    dropped_item_count = max(0, raw_next_actions_count - normalized_next_actions_count)
    valid_item_count = normalized_next_actions_count

    summary_text = _clean_optional_text(normalized_sections_payload.get("summary"))
    rationale_text = _clean_optional_text(normalized_sections_payload.get("priority_rationale"))
    references = normalized_sections_payload.get("recommendation_references")
    reference_count = len(references) if isinstance(references, list) else 0
    themes_count = len([item for item in top_themes if _clean_optional_text(item)])

    reasons: list[str] = []
    warnings: list[str] = []

    actionable_count = 0
    if isinstance(normalized_next_actions, list):
        for item in normalized_next_actions:
            text = _clean_optional_text(item) or ""
            if _ACTION_VERB_PATTERN.search(text):
                actionable_count += 1

    required_fields_present = bool(narrative)
    if narrative is None:
        warnings.append("empty_recommendations")
    no_operator_guidance = (
        normalized_next_actions_count <= 0 and summary_text is None and rationale_text is None and reference_count <= 0
    )
    if no_operator_guidance and (narrative is None or len(narrative) < _RECOMMENDATION_MIN_GUIDANCE_LEN):
        warnings.append("insufficient_operator_guidance")
    if normalized_next_actions_count <= 0:
        warnings.append("missing_action_fields")
    if normalized_next_actions_count > 0 and actionable_count <= 0:
        warnings.append("low_actionability")
    if expected_recommendation_count > 0 and reference_count <= 0:
        warnings.append("insufficient_operator_guidance")

    generic_marker_hits = 0
    narrative_lower = (narrative or "").lower()
    for marker in _GENERIC_CONTENT_MARKERS:
        if marker in narrative_lower:
            generic_marker_hits += 1
    if (
        generic_marker_hits >= 2
        and normalized_next_actions_count <= 0
        and reference_count <= 0
        and actionable_count <= 0
    ):
        reasons.append("generic_content_heavy")
    elif generic_marker_hits >= 2:
        warnings.append("generic_content_heavy")
    if themes_count <= 0 and normalized_next_actions_count <= 0:
        warnings.append("generic_content_heavy")
    if dropped_item_count > 0:
        warnings.append("missing_action_fields")

    score = 100
    score -= 30 if "empty_recommendations" in warnings else 0
    score -= 20 if "insufficient_operator_guidance" in warnings else 0
    score -= 12 if "missing_action_fields" in warnings else 0
    score -= 10 if "low_actionability" in warnings else 0
    score -= 8 if "generic_content_heavy" in warnings else 0
    score -= min(15, dropped_item_count * 3) if dropped_item_count > 0 else 0
    score = _bound_score(score)

    reasons_tuple = _stable_codes(reasons)
    warnings_tuple = _stable_codes(warnings)
    if reasons_tuple:
        status: AIResponseEvaluationStatus = "rejected"
    elif dropped_item_count > 0:
        status = "salvaged"
    elif warnings_tuple:
        status = "accepted_with_warnings"
    else:
        status = "accepted"

    return AIResponseContractEvaluation(
        status=status,
        score=score,
        reasons=reasons_tuple,
        warnings=warnings_tuple,
        valid_item_count=valid_item_count,
        dropped_item_count=dropped_item_count,
        required_fields_present=required_fields_present,
        retryable=(True if status == "rejected" else None),
    )


def _stable_codes(values: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = _clean_optional_text(value)
        if code is None:
            continue
        code = code.lower().replace(" ", "_")
        if code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return tuple(normalized)


def _build_operator_summary(
    *,
    scope: AIResponseContractScope,
    evaluation: AIResponseContractEvaluation | None,
    status: str | None,
    reason_codes: Sequence[object] | None,
    warning_codes: Sequence[object] | None,
    retryable: bool | None,
) -> AIResponseContractOperatorSummary | None:
    normalized_status = _normalize_operator_status(evaluation.status if evaluation is not None else status)
    if normalized_status is None:
        return None

    reasons = _stable_codes(
        [str(value) for value in (evaluation.reasons if evaluation is not None else (reason_codes or ()))]
    )
    warnings = _stable_codes(
        [str(value) for value in (evaluation.warnings if evaluation is not None else (warning_codes or ()))]
    )
    primary_code = _pick_primary_operator_reason(
        scope=scope,
        status=normalized_status,
        reasons=reasons,
        warnings=warnings,
    )
    summary = _OPERATOR_SUMMARY_BY_SCOPE_AND_STATUS[scope][normalized_status]
    if primary_code is not None:
        summary = _OPERATOR_REASON_SUMMARY_BY_SCOPE[scope].get(primary_code, summary)

    retryable_value = (
        evaluation.retryable if evaluation is not None and isinstance(evaluation.retryable, bool) else retryable
    )
    if not isinstance(retryable_value, bool):
        retryable_value = normalized_status in {"salvaged", "rejected"}

    return AIResponseContractOperatorSummary(
        status=normalized_status,
        summary=summary,
        retryable=retryable_value,
    )


def _normalize_operator_status(value: object) -> AIResponseEvaluationStatus | None:
    normalized = _clean_optional_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered in {"accepted", "accepted_with_warnings", "salvaged", "rejected"}:
        return lowered  # type: ignore[return-value]
    return None


def _pick_primary_operator_reason(
    *,
    scope: AIResponseContractScope,
    status: AIResponseEvaluationStatus,
    reasons: tuple[str, ...],
    warnings: tuple[str, ...],
) -> str | None:
    if scope == "migration" and status == "salvaged":
        if "partial_artifact_only" in warnings:
            return "partial_artifact_only"
        if "partial_artifact_only" in reasons:
            return "partial_artifact_only"
    if status == "accepted":
        return None
    if status == "rejected":
        if reasons:
            return reasons[0]
        if warnings:
            return warnings[0]
        return None
    if warnings:
        return warnings[0]
    if reasons:
        return reasons[0]
    return None


def _bound_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None


def _normalized_path(value: object) -> str:
    text = _clean_optional_text(value)
    if text is None:
        return ""
    return text.strip().replace("\\", "/").lower().lstrip("/")


def _normalize_hostname(value: object) -> str | None:
    text = _clean_optional_text(value)
    if text is None:
        return None
    lowered = text.strip().lower().rstrip(".")
    if lowered.startswith("http://"):
        lowered = lowered[7:]
    elif lowered.startswith("https://"):
        lowered = lowered[8:]
    lowered = lowered.split("/", 1)[0]
    if not lowered:
        return None
    return lowered if _HOSTNAME_PATTERN.fullmatch(lowered) else None


def _safe_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    if parsed in {float("inf"), float("-inf")}:
        return None
    return parsed

from __future__ import annotations

import copy
import json


_DEFAULT_TOP_OPPORTUNITIES = [
    "Improve website clarity",
    "Add trust signals",
    "Clarify services",
]
_DEFAULT_SUMMARY = "Competitor analysis unavailable, using fallback insights."

_FALLBACK_RESPONSE = {
    "competitors": [],
    "top_opportunities": _DEFAULT_TOP_OPPORTUNITIES,
    "summary": _DEFAULT_SUMMARY,
}


def normalize_competitor_response(raw_text: str) -> dict[str, object]:
    payload = _parse_json_object(raw_text)
    if payload is None:
        return _fallback_response()

    raw_competitors = payload.get("competitors")
    if not isinstance(raw_competitors, list):
        # Backward-compatibility for older candidate-style payloads.
        raw_competitors = payload.get("candidates")
    if not isinstance(raw_competitors, list):
        raw_competitors = []

    normalized_competitors: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for raw_competitor in raw_competitors:
        normalized = _normalize_competitor(raw_competitor)
        if normalized is None:
            continue
        dedupe_key = _dedupe_key(normalized.get("name"))
        if dedupe_key in seen_names:
            continue
        seen_names.add(dedupe_key)
        normalized_competitors.append(normalized)

    top_opportunities = _normalize_text_list(payload.get("top_opportunities"))
    summary = _normalize_text(payload.get("summary"))

    return {
        "competitors": normalized_competitors,
        "top_opportunities": top_opportunities,
        "summary": summary or "",
    }


def _parse_json_object(raw_text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalize_competitor(raw_competitor: object) -> dict[str, object] | None:
    if not isinstance(raw_competitor, dict):
        return None

    name = _normalize_text(raw_competitor.get("name")) or _normalize_text(raw_competitor.get("suggested_name")) or "Unknown"
    domain = _normalize_text(raw_competitor.get("domain")) or _normalize_text(raw_competitor.get("suggested_domain")) or ""
    location = _normalize_text(raw_competitor.get("location")) or ""

    strengths = _normalize_text_list(raw_competitor.get("strengths"))
    weaknesses = _normalize_text_list(raw_competitor.get("weaknesses"))
    opportunities = _normalize_text_list(raw_competitor.get("opportunities"))
    threats = _normalize_text_list(raw_competitor.get("threats"))
    differentiators = _normalize_text_list(raw_competitor.get("differentiators"))

    summary = _normalize_text(raw_competitor.get("summary")) or ""
    visibility_score = _clamp_score(raw_competitor.get("visibility_score"), default=3)
    relevance_score = _clamp_score(raw_competitor.get("relevance_score"), default=3)

    normalized = {
        "name": name,
        "domain": domain,
        "location": location,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "opportunities": opportunities,
        "threats": threats,
        "differentiators": differentiators,
        "visibility_score": visibility_score,
        "relevance_score": relevance_score,
        "summary": summary,
    }

    if _is_effectively_empty_competitor(normalized):
        return None
    return normalized


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    normalized = " ".join(str(value).split()).strip()
    return normalized


def _normalize_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _normalize_text(item)
        if text:
            normalized.append(text)
    return normalized


def _clamp_score(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(5, parsed))


def _dedupe_key(value: object) -> str:
    normalized = _normalize_text(value).lower()
    return normalized or "unknown"


def _is_effectively_empty_competitor(normalized: dict[str, object]) -> bool:
    name = _normalize_text(normalized.get("name"))
    domain = _normalize_text(normalized.get("domain"))
    location = _normalize_text(normalized.get("location"))
    summary = _normalize_text(normalized.get("summary"))
    lists = [
        normalized.get("strengths"),
        normalized.get("weaknesses"),
        normalized.get("opportunities"),
        normalized.get("threats"),
        normalized.get("differentiators"),
    ]
    has_list_content = any(isinstance(value, list) and bool(value) for value in lists)
    default_scores = normalized.get("visibility_score") == 3 and normalized.get("relevance_score") == 3
    if name != "Unknown":
        return False
    return not any([domain, location, summary, has_list_content]) and default_scores


def _fallback_response() -> dict[str, object]:
    return copy.deepcopy(_FALLBACK_RESPONSE)

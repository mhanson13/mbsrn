from __future__ import annotations

from typing import Any


_MAX_COMPETITOR_OPPORTUNITIES = 5
_MAX_COMPETITOR_NAMES = 5
_MAX_COMPETITOR_SUMMARY_LENGTH = 320
_FALLBACK_SUMMARY_PREFIX = "Competitor analysis unavailable"


def extract_recommendation_competitor_context(
    competitor_payload: dict[str, Any] | None,
) -> dict[str, object]:
    empty = _empty_context()
    if not isinstance(competitor_payload, dict):
        return empty

    top_opportunities = _dedupe_trimmed_list(
        competitor_payload.get("top_opportunities"),
        limit=_MAX_COMPETITOR_OPPORTUNITIES,
    )
    competitor_names = _extract_competitor_names(
        competitor_payload.get("competitors"),
        limit=_MAX_COMPETITOR_NAMES,
    )
    competitor_summary = _normalize_text(
        competitor_payload.get("summary"),
        max_length=_MAX_COMPETITOR_SUMMARY_LENGTH,
    )

    # Ignore normalizer fallback text when no real competitor signal exists.
    if not competitor_names and competitor_summary.startswith(_FALLBACK_SUMMARY_PREFIX):
        return empty

    if not top_opportunities and not competitor_names and not competitor_summary:
        return empty

    return {
        "top_opportunities": top_opportunities,
        "competitor_summary": competitor_summary,
        "competitor_names": competitor_names,
    }


def _empty_context() -> dict[str, object]:
    return {
        "top_opportunities": [],
        "competitor_summary": "",
        "competitor_names": [],
    }


def _extract_competitor_names(raw: object, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []

    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = _normalize_text(item.get("name"), max_length=120)
        if not text or text.lower() == "unknown":
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
        if len(values) >= limit:
            break
    return values


def _dedupe_trimmed_list(raw: object, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []

    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _normalize_text(item, max_length=140)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
        if len(values) >= limit:
            break
    return values


def _normalize_text(value: object, *, max_length: int) -> str:
    if value is None:
        return ""
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return ""
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized

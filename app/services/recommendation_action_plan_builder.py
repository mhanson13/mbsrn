from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ACTION_STEP_LIMIT = 4

_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "title": "meta_title",
    "meta_description": "meta_description",
    "h1": "heading_h1",
    "internal_link": "internal_links",
}

_CONTENT_TYPE_LABELS: dict[str, str] = {
    "heading_h1": "Main heading",
    "heading_h2": "Supporting headings",
    "intro_paragraph": "Intro paragraph",
    "service_description": "Service description",
    "internal_links": "Internal links",
    "meta_title": "Meta title",
    "meta_description": "Meta description",
    "faq_block": "FAQ section",
    "image_alt_text": "Image alt text",
    "canonical_tag": "Canonical tag",
    "page_title_block": "Page title block",
    "call_to_action": "Call to action",
    "location_copy": "Location/service-area copy",
}

_FIELD_HINTS_BY_CONTENT_TYPE: dict[str, str] = {
    "meta_title": "title",
    "meta_description": "meta_description",
    "heading_h1": "h1",
    "heading_h2": "h2",
    "intro_paragraph": "intro_paragraph",
    "service_description": "service_description",
    "internal_links": "internal_links",
    "faq_block": "faq_section",
    "image_alt_text": "image_alt_text",
    "canonical_tag": "canonical_tag",
    "page_title_block": "page_title_block",
    "call_to_action": "call_to_action",
    "location_copy": "location_copy",
}

_TARGET_CONTEXT_FALLBACKS: dict[str, str] = {
    "homepage": "Homepage",
    "service_pages": "Service pages",
    "contact_about": "Contact/About pages",
    "location_pages": "Location pages",
    "sitewide": "Sitewide pages",
    "general": "Primary pages",
}

_ACTION_TITLES_BY_CONTENT_TYPE: dict[str, str] = {
    "meta_title": "Update page title",
    "meta_description": "Rewrite meta description",
    "heading_h1": "Improve main heading clarity",
    "heading_h2": "Strengthen supporting headings",
    "intro_paragraph": "Expand intro paragraph",
    "service_description": "Strengthen service description",
    "internal_links": "Add internal links",
    "faq_block": "Add FAQ coverage",
    "image_alt_text": "Improve image alt text",
    "canonical_tag": "Fix canonical tag",
    "page_title_block": "Clarify page title block",
    "call_to_action": "Strengthen call to action",
    "location_copy": "Improve location-specific copy",
}

_INSTRUCTION_TEMPLATES: dict[str, str] = {
    "meta_title": "On {target}, replace the page title with a clear service + location title.",
    "meta_description": "On {target}, rewrite the meta description with service, location, and a direct call to action.",
    "heading_h1": "On {target}, add one clear top heading that states the service and location.",
    "heading_h2": "On {target}, use supporting headings to break content into clear sections.",
    "intro_paragraph": "On {target}, add a short opening paragraph that explains the service and who it helps.",
    "service_description": "On {target}, expand service details with scope, process, and expected outcomes.",
    "internal_links": "On {target}, add links to closely related service or location pages.",
    "faq_block": "On {target}, add a short FAQ section that answers common customer questions.",
    "image_alt_text": "On {target}, update image alt text so it describes the service context clearly.",
    "canonical_tag": "On {target}, set one canonical tag that points to the preferred page URL.",
    "page_title_block": "On {target}, tighten the visible page title text so customers immediately understand the offer.",
    "call_to_action": "On {target}, add a clear next-step call to action near key content sections.",
    "location_copy": "On {target}, add specific service-area language so local intent is explicit.",
}

_BEFORE_VALUE_KEYS_BY_CONTENT_TYPE: dict[str, tuple[str, ...]] = {
    "meta_title": ("current_meta_title", "current_title", "title_before", "meta_title_before"),
    "meta_description": (
        "current_meta_description",
        "meta_description_before",
        "current_description",
    ),
    "heading_h1": ("current_h1", "h1_before"),
    "heading_h2": ("current_h2", "h2_before"),
    "intro_paragraph": ("current_intro_paragraph", "intro_before"),
    "service_description": ("current_service_description", "service_description_before"),
    "internal_links": ("current_internal_links", "internal_links_before"),
    "faq_block": ("current_faq_block", "faq_before"),
    "image_alt_text": ("current_image_alt_text", "image_alt_before"),
    "canonical_tag": ("current_canonical_tag", "canonical_before"),
    "page_title_block": ("current_page_title_block", "page_title_block_before"),
    "call_to_action": ("current_call_to_action", "call_to_action_before"),
    "location_copy": ("current_location_copy", "location_copy_before"),
}

_CONFIDENCE_BY_STRENGTH: dict[str, float] = {
    "high": 0.92,
    "medium": 0.8,
    "low": 0.68,
}

_GENERIC_CTA = "Call today for a quote."
_DEFAULT_BENEFIT = "Trusted local support"


def _safe_text(value: object, *, max_length: int = 200) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text)
    if len(compact) > max_length:
        return compact[: max_length - 1].rstrip()
    return compact


def _read_value(source: Mapping[str, Any] | object, key: str) -> object:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _read_text(source: Mapping[str, Any] | object, key: str, *, max_length: int = 200) -> str | None:
    return _safe_text(_read_value(source, key), max_length=max_length)


def _extract_evidence_json(source: Mapping[str, Any] | object) -> dict[str, Any]:
    raw = _read_value(source, "evidence_json")
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_content_type_key(raw_key: object) -> str | None:
    normalized = str(raw_key or "").strip().lower()
    if not normalized:
        return None
    normalized = _CONTENT_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in _CONTENT_TYPE_LABELS:
        return None
    return normalized


def _extract_target_content_types(source: Mapping[str, Any] | object) -> list[dict[str, Any]]:
    raw_targets = _read_value(source, "recommendation_target_content_types")
    if not isinstance(raw_targets, list):
        evidence = _extract_evidence_json(source)
        evidence_targets = evidence.get("target_content_types")
        raw_targets = evidence_targets if isinstance(evidence_targets, list) else []

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_target in raw_targets:
        if not isinstance(raw_target, Mapping):
            continue
        type_key = _normalize_content_type_key(raw_target.get("type_key"))
        if not type_key or type_key in seen:
            continue
        seen.add(type_key)
        label = _safe_text(raw_target.get("label"), max_length=80) or _CONTENT_TYPE_LABELS[type_key]
        strength = _safe_text(raw_target.get("targeting_strength"), max_length=20)
        normalized.append(
            {
                "type_key": type_key,
                "label": label,
                "targeting_strength": strength.lower() if strength else None,
            }
        )
        if len(normalized) >= _ACTION_STEP_LIMIT:
            break
    return normalized


def _extract_target_identifier(source: Mapping[str, Any] | object) -> str:
    raw_hints = _read_value(source, "recommendation_target_page_hints")
    if isinstance(raw_hints, list):
        for raw_hint in raw_hints:
            hint = _safe_text(raw_hint, max_length=120)
            if hint:
                return hint
    context = _read_text(source, "recommendation_target_context", max_length=80)
    if context:
        normalized_context = context.lower()
        if normalized_context in _TARGET_CONTEXT_FALLBACKS:
            return _TARGET_CONTEXT_FALLBACKS[normalized_context]
    return "Primary page"


def _extract_service_phrase(source: Mapping[str, Any] | object) -> str:
    title = _read_text(source, "title", max_length=180) or ""
    rationale = _read_text(source, "rationale", max_length=220) or ""
    signal = f"{title} {rationale}".strip()
    if not signal:
        return "your core service"

    cleaned = re.sub(r"[^A-Za-z0-9\s/&-]", " ", signal)
    tokens = [token for token in cleaned.split() if token]
    stop_words = {
        "add",
        "fix",
        "improve",
        "update",
        "rewrite",
        "strengthen",
        "optimize",
        "normalize",
        "clarify",
        "expand",
        "close",
        "gap",
        "missing",
        "coverage",
        "service",
        "services",
        "page",
        "pages",
    }
    meaningful = [token for token in tokens if token.lower() not in stop_words]
    phrase_tokens = meaningful[:3] if meaningful else tokens[:3]
    phrase = " ".join(phrase_tokens).strip()
    if not phrase:
        return "your core service"
    return phrase.lower()


def _extract_location_phrase(source: Mapping[str, Any] | object) -> str:
    page_hint = _extract_target_identifier(source)
    lowered_hint = page_hint.lower()
    if "homepage" in lowered_hint:
        return "your area"
    if lowered_hint.startswith("/locations") or "location" in lowered_hint:
        return "your service area"
    context = _read_text(source, "recommendation_target_context", max_length=80)
    if context == "location_pages":
        return "your service area"
    return "your area"


def _extract_before_example(evidence_json: dict[str, Any], content_type_key: str) -> str | None:
    for evidence_key in _BEFORE_VALUE_KEYS_BY_CONTENT_TYPE.get(content_type_key, ()):
        before_value = _safe_text(evidence_json.get(evidence_key), max_length=180)
        if before_value:
            return before_value
    return None


def _build_after_example(content_type_key: str, *, service: str, location: str) -> str | None:
    service_title = service.title()
    location_title = location.title()
    if content_type_key == "meta_title":
        return f"{service_title} in {location_title} | {_DEFAULT_BENEFIT}"
    if content_type_key == "meta_description":
        return f"{service_title} in {location}. {_GENERIC_CTA}"
    if content_type_key == "heading_h1":
        return f"{service_title} in {location_title} | {_DEFAULT_BENEFIT}"
    if content_type_key == "heading_h2":
        return "How the service works, pricing options, and what to expect"
    if content_type_key == "intro_paragraph":
        return f"We provide {service} in {location} with clear scope, timeline, and next steps."
    if content_type_key == "service_description":
        return (
            f"Describe {service} steps, timing, coverage limits, and what customers should prepare before scheduling."
        )
    if content_type_key == "internal_links":
        return "Add links to related service and location pages from the first two content sections."
    if content_type_key == "faq_block":
        return "Add 3-5 FAQ items covering cost, timing, and service-area questions."
    if content_type_key == "image_alt_text":
        return f"{service_title} project example in {location_title}"
    if content_type_key == "canonical_tag":
        return "Set canonical URL to the primary page version for this content."
    if content_type_key == "page_title_block":
        return f"{service_title} in {location_title}"
    if content_type_key == "call_to_action":
        return _GENERIC_CTA
    if content_type_key == "location_copy":
        return f"Add service-area cities and ZIP coverage for {location} customers."
    return None


def _instruction_for(content_type_key: str, *, target_identifier: str) -> str:
    template = _INSTRUCTION_TEMPLATES.get(content_type_key)
    if template:
        return template.format(target=target_identifier)
    label = _CONTENT_TYPE_LABELS.get(content_type_key, "content")
    return f"On {target_identifier}, update {label.lower()} with clearer service and location language."


def _title_for(content_type_key: str, *, fallback_label: str) -> str:
    return _ACTION_TITLES_BY_CONTENT_TYPE.get(content_type_key, f"Update {fallback_label}")


def _target_type_for(content_type_key: str) -> str:
    if content_type_key in {"internal_links", "canonical_tag", "meta_title", "meta_description"}:
        return "page"
    return "content"


def _confidence_for(targeting_strength: object) -> float:
    normalized = str(targeting_strength or "").strip().lower()
    return _CONFIDENCE_BY_STRENGTH.get(normalized, 0.7)


def build_action_plan(recommendation: Mapping[str, Any] | object) -> dict[str, Any]:
    target_content_types = _extract_target_content_types(recommendation)
    if not target_content_types:
        return {"action_steps": []}

    evidence_json = _extract_evidence_json(recommendation)
    target_identifier = _extract_target_identifier(recommendation)
    service = _extract_service_phrase(recommendation)
    location = _extract_location_phrase(recommendation)

    action_steps: list[dict[str, Any]] = []
    for index, target in enumerate(target_content_types, start=1):
        content_type_key = str(target.get("type_key") or "").strip().lower()
        if not content_type_key:
            continue
        label = _safe_text(target.get("label"), max_length=80) or _CONTENT_TYPE_LABELS.get(content_type_key, "Content")
        action_steps.append(
            {
                "step_number": index,
                "title": _title_for(content_type_key, fallback_label=label),
                "instruction": _instruction_for(content_type_key, target_identifier=target_identifier),
                "target_type": _target_type_for(content_type_key),
                "target_identifier": target_identifier,
                "field": _FIELD_HINTS_BY_CONTENT_TYPE.get(content_type_key),
                "before_example": _extract_before_example(evidence_json, content_type_key),
                "after_example": _build_after_example(content_type_key, service=service, location=location),
                "confidence": _confidence_for(target.get("targeting_strength")),
            }
        )
        if len(action_steps) >= _ACTION_STEP_LIMIT:
            break

    return {"action_steps": action_steps}


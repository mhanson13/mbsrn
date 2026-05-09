from __future__ import annotations

from collections import Counter
import math
import re


_PLACEHOLDER_PHRASES = (
    "lorem ipsum",
    "your business here",
    "we are a leading provider",
)
_MEDIA_PLACEHOLDER_INDICATORS = (
    "project photo placeholder",
    "draft gallery slot",
    "replace with real",
    "image-placeholder",
)
_GENERIC_PARAGRAPH_MARKERS = (
    "we are a leading provider",
    "committed to quality",
    "contact us today",
    "trusted partner",
)
_EMPTY_HEADING_PATTERN = re.compile(r"<h[1-6][^>]*>\s*</h[1-6]>", re.IGNORECASE)
_PARAGRAPH_PATTERN = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_PATTERN = re.compile(
    r"<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>",
    re.IGNORECASE,
)
_WHITESPACE_PATTERN = re.compile(r"\s+")


def evaluate_migration_artifact_quality(artifact_bundle: dict[str, object]) -> dict[str, object]:
    normalized_files = _normalize_generated_files(artifact_bundle.get("generated_files"))
    html_files = [item for item in normalized_files if item["path"].lower().endswith(".html")]
    page_count = len(html_files)
    index_file = next((item for item in html_files if item["path"].lower() == "index.html"), None)
    combined_text = " ".join(_strip_html_to_text(item["content"]) for item in html_files).strip()
    combined_text_lower = combined_text.lower()

    business_name = _normalize_text(artifact_bundle.get("business_name"))
    location_hints = _normalize_string_list(artifact_bundle.get("location_hints"))
    expected_service_terms = _normalize_string_list(artifact_bundle.get("expected_service_terms"))
    media_required_by_operator = bool(artifact_bundle.get("media_required_by_operator"))
    selected_usable_media_assets_count = _coerce_non_negative_int(
        artifact_bundle.get("selected_usable_media_assets_count")
    )

    has_business_name = bool(business_name and business_name.lower() in combined_text_lower)
    has_location = any(hint.lower() in combined_text_lower for hint in location_hints)
    has_service_mentions = (
        any(term.lower() in combined_text_lower for term in expected_service_terms)
        if expected_service_terms
        else ("service" in combined_text_lower or "services" in combined_text_lower)
    )

    issues: list[dict[str, str]] = []
    missing_sections: list[str] = []
    required_files_present = bool(index_file is not None)
    if not required_files_present:
        issues.append(
            {
                "type": "content_completeness",
                "description": "Required file 'index.html' is missing from generated artifacts.",
            }
        )

    index_text_lower = _strip_html_to_text(index_file["content"]).lower() if index_file else ""
    html_paths_lower = [item["path"].lower() for item in html_files]
    has_services_section = (
        "service" in index_text_lower
        or "services" in index_text_lower
        or any("service" in path for path in html_paths_lower)
    )
    has_contact_section = any(
        token in index_text_lower for token in ("contact", "call", "phone", "email", "quote")
    ) or any("contact" in path for path in html_paths_lower)
    if not has_services_section:
        missing_sections.append("services")
    if not has_contact_section:
        missing_sections.append("contact")
    if missing_sections:
        issues.append(
            {
                "type": "content_completeness",
                "description": "Missing expected sections: " + ", ".join(missing_sections) + ".",
            }
        )

    placeholder_matches = [phrase for phrase in _PLACEHOLDER_PHRASES if phrase in combined_text_lower]
    media_placeholder_matches = [phrase for phrase in _MEDIA_PLACEHOLDER_INDICATORS if phrase in combined_text_lower]
    empty_heading_count = sum(len(_EMPTY_HEADING_PATTERN.findall(item["content"])) for item in html_files)
    repeated_generic_paragraph_count = _count_repeated_generic_paragraphs(html_files)
    placeholder_detected = bool(placeholder_matches or empty_heading_count > 0 or repeated_generic_paragraph_count > 0)
    if placeholder_matches:
        issues.append(
            {
                "type": "placeholder_content",
                "description": "Placeholder text detected: " + ", ".join(sorted(set(placeholder_matches))) + ".",
            }
        )
    if empty_heading_count > 0:
        issues.append(
            {
                "type": "placeholder_content",
                "description": f"Empty heading tags detected ({empty_heading_count}).",
            }
        )
    if repeated_generic_paragraph_count > 0:
        issues.append(
            {
                "type": "placeholder_content",
                "description": (
                    "Repeated generic paragraph content detected "
                    f"({repeated_generic_paragraph_count} repeated block(s))."
                ),
            }
        )

    required_media_missing = media_required_by_operator and (
        selected_usable_media_assets_count <= 0 or bool(media_placeholder_matches)
    )
    if required_media_missing:
        if selected_usable_media_assets_count <= 0:
            description = (
                "Real project images were requested, but no imported/uploaded media was selected. "
                "Draft uses placeholders."
            )
        else:
            markers = (
                ", ".join(sorted(set(media_placeholder_matches)))
                if media_placeholder_matches
                else "placeholder markers"
            )
            description = (
                "Real/existing media was requested, but placeholder markers remain in generated HTML: " + markers + "."
            )
        issues.append(
            {
                "type": "required_media_missing",
                "severity": "warning",
                "description": description,
            }
        )

    if business_name and not has_business_name:
        issues.append(
            {
                "type": "grounding_quality",
                "description": "Business name from workspace context is not present in generated HTML content.",
            }
        )
    if location_hints and not has_location:
        issues.append(
            {
                "type": "grounding_quality",
                "description": "Location context is missing from generated HTML content.",
            }
        )
    if expected_service_terms and not has_service_mentions:
        issues.append(
            {
                "type": "grounding_quality",
                "description": "Expected service terms from migration inputs are missing in generated content.",
            }
        )

    index_size_bytes = len(index_file["content"].encode("utf-8")) if index_file else 0
    if index_file is not None and index_size_bytes < 500:
        issues.append(
            {
                "type": "structural_sanity",
                "description": "index.html content is unusually small and may be incomplete.",
            }
        )
    if index_file is not None and index_size_bytes > 120_000:
        issues.append(
            {
                "type": "structural_sanity",
                "description": "index.html content exceeds expected size bounds.",
            }
        )
    if page_count <= 1:
        issues.append(
            {
                "type": "structural_sanity",
                "description": "Only one HTML page was generated; draft breadth may be limited.",
            }
        )
    duplicated_page_count = _count_near_duplicate_html_pages(html_files)
    if duplicated_page_count > 0:
        issues.append(
            {
                "type": "structural_sanity",
                "description": f"Detected {duplicated_page_count} near-duplicate HTML page(s).",
            }
        )

    score = 100
    if not required_files_present:
        score -= 35
    if missing_sections:
        score -= min(24, len(missing_sections) * 12)
    if placeholder_detected:
        score -= 25
    if business_name and not has_business_name:
        score -= 15
    if location_hints and not has_location:
        score -= 10
    if expected_service_terms and not has_service_mentions:
        score -= 12
    if index_file is not None and (index_size_bytes < 500 or index_size_bytes > 120_000):
        score -= 10
    if page_count <= 1:
        score -= 8
    if duplicated_page_count > 0:
        score -= 10
    if required_media_missing:
        score -= 20
    score = max(0, min(100, int(score)))

    quality_status = _classify_quality_status(
        score=score,
        required_files_present=required_files_present,
        placeholder_detected=placeholder_detected,
        missing_sections=missing_sections,
    )
    operator_summary = _build_operator_summary(
        quality_status=quality_status,
        issue_count=len(issues),
        missing_sections=missing_sections,
        placeholder_detected=placeholder_detected,
        required_media_missing=required_media_missing,
    )

    return {
        "quality_status": quality_status,
        "issues": issues,
        "signals": {
            "has_business_name": has_business_name,
            "has_location": has_location,
            "has_service_mentions": has_service_mentions,
            "placeholder_detected": placeholder_detected,
            "missing_sections": missing_sections,
            "required_files_present": required_files_present,
            "page_count": page_count,
            "index_size_bytes": index_size_bytes,
            "duplicated_page_count": duplicated_page_count,
            "media_required_by_operator": media_required_by_operator,
            "selected_usable_media_assets_count": selected_usable_media_assets_count,
            "required_media_missing": required_media_missing,
            "media_placeholder_markers": media_placeholder_matches,
        },
        "operator_summary": operator_summary,
    }


def _normalize_generated_files(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _normalize_text(item.get("path"))
        content = _normalize_text(item.get("content"))
        if not path or content is None:
            continue
        normalized.append({"path": path, "content": content})
    return normalized


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_text(item)
        if text is None:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
        if len(normalized) >= 20:
            break
    return normalized


def _strip_html_to_text(raw_html: str) -> str:
    without_scripts = _SCRIPT_STYLE_PATTERN.sub(" ", raw_html)
    without_tags = _HTML_TAG_PATTERN.sub(" ", without_scripts)
    return _WHITESPACE_PATTERN.sub(" ", without_tags).strip()


def _count_repeated_generic_paragraphs(html_files: list[dict[str, str]]) -> int:
    paragraphs: list[str] = []
    for item in html_files:
        for match in _PARAGRAPH_PATTERN.findall(item["content"]):
            text = _strip_html_to_text(match).lower()
            if len(text) < 40:
                continue
            if not any(marker in text for marker in _GENERIC_PARAGRAPH_MARKERS):
                continue
            paragraphs.append(text)
    if not paragraphs:
        return 0
    counts = Counter(paragraphs)
    return sum(1 for count in counts.values() if count >= 2)


def _count_near_duplicate_html_pages(html_files: list[dict[str, str]]) -> int:
    if len(html_files) < 2:
        return 0
    fingerprints: list[str] = []
    for item in html_files:
        plain = _strip_html_to_text(item["content"]).lower()
        if not plain:
            continue
        fingerprint = _WHITESPACE_PATTERN.sub(" ", plain)[:1600]
        if fingerprint:
            fingerprints.append(fingerprint)
    counts = Counter(fingerprints)
    duplicates = 0
    for count in counts.values():
        if count > 1:
            duplicates += count - 1
    return duplicates


def _classify_quality_status(
    *,
    score: int,
    required_files_present: bool,
    placeholder_detected: bool,
    missing_sections: list[str],
) -> str:
    if not required_files_present:
        return "low"
    if placeholder_detected and score < 80:
        return "low"
    if score >= 80 and not missing_sections and not placeholder_detected:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _build_operator_summary(
    *,
    quality_status: str,
    issue_count: int,
    missing_sections: list[str],
    placeholder_detected: bool,
    required_media_missing: bool,
) -> str:
    if required_media_missing:
        return (
            "Review warning: real/existing project images were requested, but usable selected media is missing "
            "or placeholders remain."
        )
    if quality_status == "high":
        return "High quality draft: core sections and grounding signals are present."
    if quality_status == "medium":
        if missing_sections:
            return (
                "Medium quality draft: missing "
                + ", ".join(missing_sections)
                + " section coverage should be reviewed before approval."
            )
        return "Medium quality draft: usable with notable gaps to review before approval."
    if placeholder_detected:
        return "Low quality draft: placeholder or generic content was detected; revise before approval."
    if issue_count > 0:
        return "Low quality draft: completeness and grounding gaps were detected; revise before approval."
    return "Low quality draft: generated content is not sufficient for approval."


def _coerce_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, int(value))
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return 0
        return max(0, int(value))
    return 0

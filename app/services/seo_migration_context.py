from __future__ import annotations

from dataclasses import dataclass

from app.models.seo_audit_summary import SEOAuditSummary
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_site import SEOSite
from app.services.seo_sites import build_location_context, build_site_business_context

_SUMMARY_TEXT_MAX_LENGTH = 900
_SUMMARY_LIST_MAX_ITEMS = 10
_SUMMARY_LIST_TEXT_MAX_LENGTH = 240
_SUMMARY_STRUCTURED_MAX_ITEMS = 12
_SUMMARY_STRUCTURED_MAX_DEPTH = 3
_SUMMARY_STRUCTURED_MAX_STRING_LENGTH = 320
_SUMMARY_SECTION_MAX_ITEMS = 8
_SUMMARY_SECTION_MAX_STRING_LENGTH = 800


@dataclass(frozen=True)
class SEOMigrationContextAssemblyResult:
    context_json: dict[str, object]
    context_summary: dict[str, object]


class SEOMigrationContextAssembler:
    def assemble(
        self,
        *,
        site: SEOSite,
        workspace: SEOMigrationWorkspace,
        latest_audit_summary: SEOAuditSummary | None,
        latest_recommendation_narrative: SEORecommendationNarrative | None,
        latest_competitor_summary: SEOCompetitorComparisonSummary | None,
        reused_context: dict[str, object] | None = None,
    ) -> SEOMigrationContextAssemblyResult:
        location_context = build_location_context(site)
        business_context = build_site_business_context(
            site=site,
            location_context=location_context,
            normalized_domain=site.normalized_domain,
        )

        source_snapshot = _normalize_dict(workspace.imported_source_snapshot_json)
        operator_requirements = _normalize_dict(workspace.operator_requirements_json)
        enriched_notes = _normalize_dict(workspace.enriched_content_notes_json)
        business_facts_snapshot = _normalize_dict(workspace.brand_business_facts_snapshot_json)
        reused_context_payload = _normalize_reused_context(reused_context)

        audit_summary_payload = _audit_summary_payload(latest_audit_summary)
        recommendation_summary_payload = _recommendation_summary_payload(latest_recommendation_narrative)
        competitor_summary_payload = _competitor_summary_payload(latest_competitor_summary)

        context_json: dict[str, object] = {
            "site_snapshot": {
                "business_id": site.business_id,
                "site_id": site.id,
                "display_name": site.display_name,
                "base_url": site.base_url,
                "normalized_domain": site.normalized_domain,
                "industry": site.industry,
                "primary_location": site.primary_location,
                "service_areas": site.service_areas_json or [],
                "location_context": {
                    "text": location_context.location_context,
                    "strength": location_context.location_context_strength,
                    "source": location_context.location_context_source,
                },
                "business_context": {
                    "industry_context": business_context.industry_context,
                    "industry_context_strength": business_context.industry_context_strength,
                    "service_focus_terms": business_context.service_focus_terms,
                    "target_customer_context": business_context.target_customer_context,
                },
            },
            "migration_workspace": {
                "workspace_id": workspace.id,
                "source_url": workspace.source_url,
                "ingestion_mode": workspace.ingestion_mode,
                "latest_source_capture_id": workspace.latest_source_capture_id,
                "source_site_status": workspace.source_site_status,
                "migration_status": workspace.migration_status,
            },
            "source_snapshot": source_snapshot,
            "operator_requirements": operator_requirements,
            "enriched_content_notes": enriched_notes,
            "brand_business_facts_snapshot": business_facts_snapshot,
            "reused_context": reused_context_payload,
            "existing_context_summaries": {
                "audit_summary": audit_summary_payload,
                "recommendation_summary": recommendation_summary_payload,
                "competitor_summary": competitor_summary_payload,
            },
        }

        audit_available = _is_reused_context_available(reused_context_payload.get("audit"))
        recommendation_available = _is_reused_context_available(reused_context_payload.get("recommendations"))
        competitor_available = _is_reused_context_available(reused_context_payload.get("competitors"))
        context_summary = {
            "has_source_snapshot": bool(source_snapshot),
            "has_operator_requirements": bool(operator_requirements),
            "has_enriched_content_notes": bool(enriched_notes),
            "has_audit_summary": audit_available or audit_summary_payload is not None,
            "has_recommendation_summary": recommendation_available or recommendation_summary_payload is not None,
            "has_competitor_summary": competitor_available or competitor_summary_payload is not None,
            "reused_context": reused_context_payload,
        }
        return SEOMigrationContextAssemblyResult(
            context_json=context_json,
            context_summary=context_summary,
        )


def _normalize_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): val for key, val in value.items()}
    return {}


def _normalize_reused_context(value: object) -> dict[str, object]:
    normalized = _normalize_dict(value)
    return {
        "audit": _normalize_reused_context_entry(normalized.get("audit")),
        "recommendations": _normalize_reused_context_entry(normalized.get("recommendations")),
        "competitors": _normalize_reused_context_entry(normalized.get("competitors")),
    }


def _normalize_reused_context_entry(value: object) -> dict[str, object]:
    normalized = _normalize_dict(value)
    available_raw = normalized.get("available")
    available = available_raw if isinstance(available_raw, bool) else False
    entry: dict[str, object] = {"available": available}
    source = _normalize_optional_text(normalized.get("source"), max_length=80)
    if source is not None:
        entry["source"] = source
    run_id = _normalize_optional_text(normalized.get("run_id"), max_length=64)
    if run_id is not None:
        entry["run_id"] = run_id
    timestamp = _normalize_optional_text(normalized.get("timestamp"), max_length=80)
    if timestamp is not None:
        entry["timestamp"] = timestamp
    count = normalized.get("count")
    if isinstance(count, int) and count >= 0:
        entry["count"] = count
    return entry


def _normalize_optional_text(value: object, *, max_length: int) -> str | None:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return None
    return normalized[:max_length]


def _is_reused_context_available(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    available = value.get("available")
    return bool(available) if isinstance(available, bool) else False


def _audit_summary_payload(summary: SEOAuditSummary | None) -> dict[str, object] | None:
    if summary is None:
        return None
    return {
        "id": summary.id,
        "status": summary.status,
        "overall_health_summary": _normalize_optional_text(
            summary.overall_health_summary,
            max_length=_SUMMARY_TEXT_MAX_LENGTH,
        ),
        "plain_english_explanation": _normalize_optional_text(
            summary.plain_english_explanation,
            max_length=_SUMMARY_TEXT_MAX_LENGTH,
        ),
        "top_issues": _bounded_structured_list(summary.top_issues_json, max_items=_SUMMARY_STRUCTURED_MAX_ITEMS),
        "top_priorities": _bounded_structured_list(
            summary.top_priorities_json,
            max_items=_SUMMARY_STRUCTURED_MAX_ITEMS,
        ),
        "model_name": summary.model_name,
        "prompt_version": summary.prompt_version,
        "created_at": summary.created_at.isoformat(),
    }


def _recommendation_summary_payload(narrative: SEORecommendationNarrative | None) -> dict[str, object] | None:
    if narrative is None:
        return None
    return {
        "id": narrative.id,
        "status": narrative.status,
        "narrative_text": _normalize_optional_text(
            narrative.narrative_text,
            max_length=_SUMMARY_TEXT_MAX_LENGTH,
        ),
        "top_themes": _bounded_string_list(narrative.top_themes_json, max_items=_SUMMARY_LIST_MAX_ITEMS),
        "sections": _bounded_sections_dict(narrative.sections_json),
        "model_name": narrative.model_name,
        "provider_name": narrative.provider_name,
        "prompt_version": narrative.prompt_version,
        "created_at": narrative.created_at.isoformat(),
    }


def _competitor_summary_payload(summary: SEOCompetitorComparisonSummary | None) -> dict[str, object] | None:
    if summary is None:
        return None
    return {
        "id": summary.id,
        "status": summary.status,
        "overall_gap_summary": _normalize_optional_text(
            summary.overall_gap_summary,
            max_length=_SUMMARY_TEXT_MAX_LENGTH,
        ),
        "plain_english_explanation": _normalize_optional_text(
            summary.plain_english_explanation,
            max_length=_SUMMARY_TEXT_MAX_LENGTH,
        ),
        "top_gaps": _bounded_structured_list(summary.top_gaps_json, max_items=_SUMMARY_STRUCTURED_MAX_ITEMS),
        "provider_name": summary.provider_name,
        "model_name": summary.model_name,
        "prompt_version": summary.prompt_version,
        "created_at": summary.created_at.isoformat(),
    }


def _bounded_string_list(value: object, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_optional_text(item, max_length=_SUMMARY_LIST_TEXT_MAX_LENGTH)
        if text is None:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= max(1, int(max_items)):
            break
    return normalized


def _bounded_structured_list(value: object, *, max_items: int) -> list[object]:
    if not isinstance(value, list):
        return []
    normalized: list[object] = []
    for item in value[: max(1, int(max_items))]:
        normalized_item = _sanitize_structured_value(item, depth=0)
        if normalized_item is not None:
            normalized.append(normalized_item)
    return normalized


def _bounded_sections_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    for raw_key in list(value.keys())[:_SUMMARY_SECTION_MAX_ITEMS]:
        key = _normalize_optional_text(raw_key, max_length=80)
        if key is None:
            continue
        raw_item = value.get(raw_key)
        if isinstance(raw_item, str):
            section_text = _normalize_optional_text(raw_item, max_length=_SUMMARY_SECTION_MAX_STRING_LENGTH)
            if section_text is not None:
                normalized[key] = section_text
            continue
        if isinstance(raw_item, list):
            normalized[key] = _bounded_string_list(raw_item, max_items=_SUMMARY_LIST_MAX_ITEMS)
            continue
        sanitized = _sanitize_structured_value(raw_item, depth=0)
        if sanitized is not None:
            normalized[key] = sanitized
    return normalized


def _sanitize_structured_value(value: object, *, depth: int) -> object | None:
    if depth >= _SUMMARY_STRUCTURED_MAX_DEPTH:
        return None
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _normalize_optional_text(value, max_length=_SUMMARY_STRUCTURED_MAX_STRING_LENGTH)
    if isinstance(value, list):
        normalized: list[object] = []
        for item in value[:_SUMMARY_STRUCTURED_MAX_ITEMS]:
            cleaned = _sanitize_structured_value(item, depth=depth + 1)
            if cleaned is not None:
                normalized.append(cleaned)
        return normalized
    if isinstance(value, dict):
        normalized_dict: dict[str, object] = {}
        for raw_key in list(value.keys())[:_SUMMARY_SECTION_MAX_ITEMS]:
            key = _normalize_optional_text(raw_key, max_length=80)
            if key is None:
                continue
            cleaned = _sanitize_structured_value(value.get(raw_key), depth=depth + 1)
            if cleaned is not None:
                normalized_dict[key] = cleaned
        return normalized_dict
    return None

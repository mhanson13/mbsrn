from __future__ import annotations

from dataclasses import dataclass

from app.models.seo_audit_summary import SEOAuditSummary
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_site import SEOSite
from app.services.seo_sites import build_location_context, build_site_business_context


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

        audit_summary_payload = _audit_summary_payload(latest_audit_summary)
        recommendation_summary_payload = _recommendation_summary_payload(latest_recommendation_narrative)
        competitor_summary_payload = _competitor_summary_payload(latest_competitor_summary)

        context_json: dict[str, object] = {
            "site_snapshot": {
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
                "source_site_status": workspace.source_site_status,
                "migration_status": workspace.migration_status,
            },
            "source_snapshot": source_snapshot,
            "operator_requirements": operator_requirements,
            "enriched_content_notes": enriched_notes,
            "brand_business_facts_snapshot": business_facts_snapshot,
            "existing_context_summaries": {
                "audit_summary": audit_summary_payload,
                "recommendation_summary": recommendation_summary_payload,
                "competitor_summary": competitor_summary_payload,
            },
        }

        context_summary = {
            "has_source_snapshot": bool(source_snapshot),
            "has_operator_requirements": bool(operator_requirements),
            "has_enriched_content_notes": bool(enriched_notes),
            "has_audit_summary": audit_summary_payload is not None,
            "has_recommendation_summary": recommendation_summary_payload is not None,
            "has_competitor_summary": competitor_summary_payload is not None,
        }
        return SEOMigrationContextAssemblyResult(
            context_json=context_json,
            context_summary=context_summary,
        )


def _normalize_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): val for key, val in value.items()}
    return {}


def _audit_summary_payload(summary: SEOAuditSummary | None) -> dict[str, object] | None:
    if summary is None:
        return None
    return {
        "id": summary.id,
        "status": summary.status,
        "overall_health_summary": summary.overall_health_summary,
        "plain_english_explanation": summary.plain_english_explanation,
        "top_issues": summary.top_issues_json or [],
        "top_priorities": summary.top_priorities_json or [],
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
        "narrative_text": narrative.narrative_text,
        "top_themes": narrative.top_themes_json or [],
        "sections": narrative.sections_json or {},
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
        "overall_gap_summary": summary.overall_gap_summary,
        "plain_english_explanation": summary.plain_english_explanation,
        "top_gaps": summary.top_gaps_json or [],
        "provider_name": summary.provider_name,
        "model_name": summary.model_name,
        "prompt_version": summary.prompt_version,
        "created_at": summary.created_at.isoformat(),
    }


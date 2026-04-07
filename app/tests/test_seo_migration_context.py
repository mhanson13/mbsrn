from __future__ import annotations

from app.core.time import utc_now
from app.models.seo_audit_summary import SEOAuditSummary
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_site import SEOSite
from app.services.seo_migration_context import SEOMigrationContextAssembler


def test_context_assembler_combines_workspace_and_existing_summaries() -> None:
    now = utc_now()
    site = SEOSite(
        id="site-1",
        business_id="biz-1",
        display_name="TNM Fire",
        base_url="https://tnmfire.example/",
        normalized_domain="tnmfire.example",
        industry="fire protection",
        primary_location="Longmont, CO",
        service_areas_json=["Longmont", "Boulder"],
        is_active=True,
        is_primary=True,
    )
    workspace = SEOMigrationWorkspace(
        id="workspace-1",
        business_id="biz-1",
        site_id="site-1",
        source_url="https://legacy.example/",
        source_site_status="ingested",
        migration_status="source_ingested",
        operator_requirements_json={"business_objectives": ["Replace weak legacy site copy"]},
        enriched_content_notes_json={"replacement_summary": "Use richer service detail and trust proof."},
        brand_business_facts_snapshot_json={"license": "CO-12345"},
        imported_source_snapshot_json={"title": "Legacy brochure site"},
        publish_config_json={"target_repo": "org/tnmfire-site"},
        deploy_config_json={"target_cluster": "gke-prod"},
    )
    audit_summary = SEOAuditSummary(
        id="audit-summary-1",
        business_id="biz-1",
        site_id="site-1",
        audit_run_id="audit-run-1",
        version=1,
        status="completed",
        overall_health_summary="Legacy site quality is weak.",
        top_issues_json=["Missing service specificity"],
        top_priorities_json=["Clarify service pages"],
        plain_english_explanation="Current pages are thin and repetitive.",
        model_name="mock",
        prompt_version="seo-audit-summary-v1",
        created_at=now,
        updated_at=now,
    )
    recommendation_summary = SEORecommendationNarrative(
        id="recommendation-narrative-1",
        business_id="biz-1",
        site_id="site-1",
        recommendation_run_id="recommendation-run-1",
        version=1,
        status="completed",
        narrative_text="Lead with trust signals and conversion flow improvements.",
        top_themes_json=["trust", "conversion"],
        sections_json={"next_actions": ["Improve homepage service clarity"]},
        provider_name="mock",
        model_name="mock-model",
        prompt_version="seo-recommendation-narrative-v2",
        created_at=now,
        updated_at=now,
    )
    competitor_summary = SEOCompetitorComparisonSummary(
        id="competitor-summary-1",
        business_id="biz-1",
        site_id="site-1",
        competitor_set_id="set-1",
        comparison_run_id="comparison-run-1",
        version=1,
        status="completed",
        overall_gap_summary="Competitors show clearer service segmentation.",
        top_gaps_json=["Service page depth"],
        plain_english_explanation="Competitors communicate expertise more clearly.",
        provider_name="mock",
        model_name="mock-model",
        prompt_version="seo-competitor-summary-v1",
        created_at=now,
        updated_at=now,
    )

    assembler = SEOMigrationContextAssembler()
    assembled = assembler.assemble(
        site=site,
        workspace=workspace,
        latest_audit_summary=audit_summary,
        latest_recommendation_narrative=recommendation_summary,
        latest_competitor_summary=competitor_summary,
    )

    context_json = assembled.context_json
    context_summary = assembled.context_summary
    assert context_json["source_snapshot"]["title"] == "Legacy brochure site"
    assert context_json["operator_requirements"]["business_objectives"] == ["Replace weak legacy site copy"]
    assert context_json["enriched_content_notes"]["replacement_summary"] == (
        "Use richer service detail and trust proof."
    )
    assert context_json["existing_context_summaries"]["audit_summary"]["overall_health_summary"] == (
        "Legacy site quality is weak."
    )
    assert context_json["existing_context_summaries"]["recommendation_summary"]["narrative_text"] == (
        "Lead with trust signals and conversion flow improvements."
    )
    assert context_json["existing_context_summaries"]["competitor_summary"]["overall_gap_summary"] == (
        "Competitors show clearer service segmentation."
    )

    assert context_summary["has_source_snapshot"] is True
    assert context_summary["has_operator_requirements"] is True
    assert context_summary["has_enriched_content_notes"] is True
    assert context_summary["has_audit_summary"] is True
    assert context_summary["has_recommendation_summary"] is True
    assert context_summary["has_competitor_summary"] is True

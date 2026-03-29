from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_recommendation_narrative_repository import (
    SEORecommendationNarrativeRepository,
)
from app.repositories.seo_recommendation_repository import SEORecommendationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite
from app.services.seo_competitor_profile_prompt import build_seo_competitor_profile_prompt
from app.services.seo_competitor_profile_generation import SEOCompetitorProfileGenerationService
from app.services.seo_recommendation_narrative_prompt import build_seo_recommendation_narrative_prompt
from app.services.seo_recommendation_narratives import SEORecommendationNarrativeService


class _MutablePromptProvider:
    provider_name = "test-provider"
    model_name = "test-model"
    prompt_version = "test-prompt-v1"

    def __init__(
        self,
        *,
        competitor_prompt_text: str = "",
        recommendation_prompt_text: str = "",
        legacy_config_used: bool = False,
    ) -> None:
        self.prompt_text_competitor = competitor_prompt_text
        self.prompt_text_recommendations = recommendation_prompt_text
        # Legacy compatibility fields intentionally mirror modern fields.
        self.prompt_text_recommendation = recommendation_prompt_text or competitor_prompt_text
        self.legacy_config_used = legacy_config_used
        self.prompt_source = "env"


def test_competitor_prompt_fallback_resolution_uses_immutable_snapshot_not_mutable_provider(
    db_session,
    seeded_business,
) -> None:
    provider = _MutablePromptProvider(competitor_prompt_text="Configured competitor fallback prompt.")
    service = SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )

    # Simulate runtime mutation performed during run execution.
    provider.prompt_text_competitor = "MUTATED RUNTIME VALUE"
    provider.prompt_text_recommendation = "MUTATED LEGACY VALUE"
    seeded_business.ai_prompt_text_competitor = None

    resolved = service._resolve_competitor_prompt_settings(seeded_business)
    assert resolved.prompt_text == "Configured competitor fallback prompt."
    assert resolved.prompt_source == "env"


def test_recommendation_prompt_fallback_resolution_uses_immutable_snapshot_not_mutable_provider(
    db_session,
    seeded_business,
) -> None:
    provider = _MutablePromptProvider(recommendation_prompt_text="Configured recommendation fallback prompt.")
    service = SEORecommendationNarrativeService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_recommendation_repository=SEORecommendationRepository(db_session),
        seo_recommendation_narrative_repository=SEORecommendationNarrativeRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )

    # Simulate runtime mutation performed during narrative generation.
    provider.prompt_text_recommendations = "MUTATED RUNTIME VALUE"
    provider.prompt_text_recommendation = "MUTATED LEGACY VALUE"
    seeded_business.ai_prompt_text_recommendations = None

    resolved = service._resolve_recommendation_prompt_settings(seeded_business)
    assert resolved.prompt_text == "Configured recommendation fallback prompt."
    assert resolved.prompt_source == "env"


def test_competitor_prompt_apply_resolution_uses_normalized_admin_override_for_execution(
    db_session,
    seeded_business,
) -> None:
    provider = _MutablePromptProvider(competitor_prompt_text="Configured fallback prompt.")
    service = SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )
    seeded_business.ai_prompt_text_competitor = (
        " \n" "PROMPT_VERSION: seo-competitor-profile-v4\n" "TASK: Use the admin override prompt.\n" " "
    )

    resolved = service._apply_resolved_competitor_prompt_settings(seeded_business)

    assert resolved.prompt_source == "admin_config"
    assert resolved.prompt_text.startswith("PROMPT_VERSION: seo-competitor-profile-v4")
    assert provider.prompt_text_competitor == resolved.prompt_text
    assert provider.prompt_source == "admin_config"


def test_competitor_prompt_preview_matches_runtime_prompt_assembly(
    db_session,
    seeded_business,
) -> None:
    site = SEOSite(
        id="site-preview-match",
        business_id=seeded_business.id,
        display_name="Preview Match Site",
        base_url="https://preview-match.example/",
        normalized_domain="preview-match.example",
        industry="Roofing",
        primary_location="Denver, CO",
        service_areas_json=["Denver", "Aurora"],
        is_active=True,
        is_primary=True,
    )
    db_session.add(site)
    seeded_business.ai_prompt_text_competitor = (
        "Prefer direct local competitors for {site_display_name}.\n"
        "Location: {site_location_context}\n"
        "Services: {service_focus_terms}"
    )
    db_session.add(seeded_business)
    db_session.commit()

    provider = _MutablePromptProvider()
    service = SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )
    preview = service.build_prompt_preview(
        business_id=seeded_business.id,
        site_id=site.id,
        candidate_count=4,
        prompt_version="seo-competitor-profile-v1",
    )
    assert preview is not None

    reloaded_site = db_session.get(SEOSite, site.id)
    assert reloaded_site is not None
    resolved_prompt = service._resolve_competitor_prompt_settings(seeded_business)
    runtime_prompt = build_seo_competitor_profile_prompt(
        site=reloaded_site,
        existing_domains=[],
        candidate_count=4,
        prompt_version="seo-competitor-profile-v1",
        prompt_text_competitor=resolved_prompt.prompt_text,
    )

    assert preview.system_prompt == runtime_prompt.system_prompt
    assert preview.user_prompt == runtime_prompt.user_prompt
    assert "{site_display_name}" not in preview.user_prompt
    assert "{site_location_context}" not in preview.user_prompt
    assert "{service_focus_terms}" not in preview.user_prompt


def test_competitor_prompt_preview_parity_preserves_full_long_override_without_cutoff(
    db_session,
    seeded_business,
) -> None:
    site = SEOSite(
        id="site-preview-long-override",
        business_id=seeded_business.id,
        display_name="Preview Long Override Site",
        base_url="https://preview-long-override.example/",
        normalized_domain="preview-long-override.example",
        industry="Roofing",
        primary_location="Denver, CO",
        service_areas_json=["Denver", "Aurora"],
        is_active=True,
        is_primary=True,
    )
    db_session.add(site)
    seeded_business.ai_prompt_text_competitor = (
        "PROMPT_VERSION: seo-competitor-profile-v2\n"
        "TASK: Preserve the complete override body in preview and runtime assembly.\n"
        + ("Long-form competitor guidance sentence. " * 60)
        + "\n"
        "COMPETITOR_QUALITY_CONTRACT:\n"
        "1. Include only substitutable providers.\n"
        "2. Exclude directories and social profiles.\n"
        "3. If evidence is weak or ambiguous, return fewer candidates rather than speculative matches.\n"
        "4. Prioritize local overlap evidence.\n"
        "5. Keep trade relevance strict.\n"
        "6. Keep confidence tied to explicit evidence.\n"
        "7. Avoid adjacent non-substitute businesses.\n"
        "8. Prefer first-party business domains.\n"
        "9. Keep rationale concise.\n"
        "10. Avoid speculative geography.\n"
        "11. Penalize ambiguous service overlap.\n"
        "12. Return fewer candidates if confidence is uncertain.\n"
        "WEB-SEARCH QUALITY RULES:\n"
        "1. Prefer first-party business websites.\n"
        "2. Use snippets as supporting evidence only.\n"
        "OUTPUT FORMAT:\n"
        '{"candidates":[{"domain":"hostname","competitor_type":"direct","confidence_score":0.0}]}\n'
    )
    db_session.add(seeded_business)
    db_session.commit()

    provider = _MutablePromptProvider()
    service = SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )
    preview = service.build_prompt_preview(
        business_id=seeded_business.id,
        site_id=site.id,
        candidate_count=4,
        prompt_version="seo-competitor-profile-v1",
    )
    assert preview is not None

    reloaded_site = db_session.get(SEOSite, site.id)
    assert reloaded_site is not None
    resolved_prompt = service._resolve_competitor_prompt_settings(seeded_business)
    runtime_prompt = build_seo_competitor_profile_prompt(
        site=reloaded_site,
        existing_domains=[],
        candidate_count=4,
        prompt_version="seo-competitor-profile-v1",
        prompt_text_competitor=resolved_prompt.prompt_text,
    )

    assert preview.system_prompt == runtime_prompt.system_prompt
    assert preview.user_prompt == runtime_prompt.user_prompt
    assert "COMPETITOR_QUALITY_CONTRACT:" in preview.user_prompt
    assert "12. Return fewer candidates if confidence is uncertain." in preview.user_prompt
    assert "WEB-SEARCH QUALITY RULES:" in preview.user_prompt
    assert "OUTPUT FORMAT:" in preview.user_prompt
    assert "3. If ev\nPLATFORM_CONSTRAINTS:" not in preview.user_prompt


def test_competitor_prompt_preview_version_reflects_rendered_prompt_marker_not_requested_preview_version(
    db_session,
    seeded_business,
) -> None:
    site = SEOSite(
        id="site-preview-version-marker",
        business_id=seeded_business.id,
        display_name="Preview Version Marker Site",
        base_url="https://preview-version-marker.example/",
        normalized_domain="preview-version-marker.example",
        industry="Roofing",
        primary_location="Denver, CO",
        service_areas_json=["Denver"],
        is_active=True,
        is_primary=True,
    )
    db_session.add(site)
    seeded_business.ai_prompt_text_competitor = (
        "PROMPT_VERSION: seo-competitor-profile-v2\n"
        "TASK: Ensure preview metadata version aligns with rendered prompt marker.\n"
        "OUTPUT FORMAT:\n"
        '{"candidates":[{"domain":"hostname","competitor_type":"direct","confidence_score":0.0}]}\n'
    )
    db_session.add(seeded_business)
    db_session.commit()

    provider = _MutablePromptProvider()
    service = SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )
    preview = service.build_prompt_preview(
        business_id=seeded_business.id,
        site_id=site.id,
        candidate_count=4,
        prompt_version="seo-competitor-profile-v1",
    )

    assert preview is not None
    assert preview.prompt_version == "seo-competitor-profile-v2"
    assert "PROMPT_VERSION: seo-competitor-profile-v2" in preview.user_prompt
    assert "PROMPT_VERSION: seo-competitor-profile-v1" not in preview.user_prompt


def test_recommendation_prompt_preview_matches_runtime_prompt_assembly(
    db_session,
    seeded_business,
) -> None:
    site = SEOSite(
        id="site-recommendation-preview-match",
        business_id=seeded_business.id,
        display_name="Recommendation Preview Match Site",
        base_url="https://recommendation-preview-match.example/",
        normalized_domain="recommendation-preview-match.example",
        industry="Roofing",
        primary_location="Denver, CO",
        service_areas_json=["Denver", "Aurora"],
        is_active=True,
        is_primary=True,
    )
    audit_run = SEOAuditRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        max_pages=5,
        max_depth=1,
        pages_discovered=2,
        pages_crawled=2,
    )
    recommendation_run = SEORecommendationRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        status="completed",
        total_recommendations=2,
        critical_recommendations=1,
        warning_recommendations=1,
        info_recommendations=0,
    )
    recommendation_run.site = site
    recommendation_one = SEORecommendation(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        recommendation_run_id=recommendation_run.id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        rule_key="fix_missing_title_tags",
        category="SEO",
        severity="WARNING",
        title="Fix missing title tags",
        rationale="Missing title tags reduce local intent relevance.",
        priority_score=70,
        priority_band="high",
        effort_bucket="LOW",
        status="open",
        created_at=datetime(2026, 3, 25, 12, 0, tzinfo=UTC),
    )
    recommendation_two = SEORecommendation(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        recommendation_run_id=recommendation_run.id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        rule_key="expand_service_area_content",
        category="CONTENT",
        severity="CRITICAL",
        title="Expand service area content",
        rationale="Service-area pages need deeper local proof and coverage.",
        priority_score=90,
        priority_band="critical",
        effort_bucket="HIGH",
        status="in_progress",
        created_at=datetime(2026, 3, 25, 12, 5, tzinfo=UTC),
    )
    db_session.add(site)
    db_session.add(audit_run)
    db_session.add(recommendation_run)
    db_session.add(recommendation_one)
    db_session.add(recommendation_two)
    seeded_business.ai_prompt_text_recommendations = "Keep recommendation narrative focused and operator-first."
    db_session.add(seeded_business)
    db_session.commit()

    provider = _MutablePromptProvider()
    recommendation_repository = SEORecommendationRepository(db_session)
    service = SEORecommendationNarrativeService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_recommendation_repository=recommendation_repository,
        seo_recommendation_narrative_repository=SEORecommendationNarrativeRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
    )
    preview = service.build_prompt_preview(
        business_id=seeded_business.id,
        site_id=site.id,
        recommendation_run_id=recommendation_run.id,
    )
    assert preview is not None

    resolved_prompt = service._resolve_recommendation_prompt_settings(seeded_business)
    recommendations = recommendation_repository.list_recommendations_for_business_run(
        seeded_business.id,
        recommendation_run.id,
    )
    by_status, by_category, by_severity, by_effort_bucket, by_priority_band = service._summarize(recommendations)
    backlog = service._build_backlog(recommendations)
    competitor_telemetry_summary = service._build_competitor_telemetry_summary(
        business_id=seeded_business.id,
        site_id=site.id,
    )
    competitor_context = service._build_competitor_context(
        business_id=seeded_business.id,
        site_id=site.id,
    )
    current_tuning_values = service._build_current_tuning_values(seeded_business)
    runtime_prompt = build_seo_recommendation_narrative_prompt(
        run=recommendation_run,
        recommendations=recommendations,
        by_status=by_status,
        by_category=by_category,
        by_severity=by_severity,
        by_effort_bucket=by_effort_bucket,
        by_priority_band=by_priority_band,
        backlog=backlog,
        competitor_telemetry_summary=competitor_telemetry_summary,
        competitor_context=competitor_context,
        current_tuning_values=current_tuning_values,
        prompt_version=service.provider.prompt_version,
        prompt_text_recommendations=resolved_prompt.prompt_text,
    )

    assert preview.system_prompt == runtime_prompt.system_prompt
    assert preview.user_prompt == runtime_prompt.user_prompt

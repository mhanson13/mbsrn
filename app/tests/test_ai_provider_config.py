from __future__ import annotations

import pytest

from app.api.deps import (
    get_seo_competitor_profile_generation_provider,
    get_seo_recommendation_narrative_provider,
)
from app.core.config import get_settings
from app.integrations.seo_competitor_profile_generation_provider import (
    MisconfiguredSEOCompetitorProfileGenerationProvider,
    OpenAISEOCompetitorProfileGenerationProvider,
    SEOCompetitorProfileProviderError,
)
from app.integrations.seo_recommendation_narrative_provider import (
    MisconfiguredSEORecommendationNarrativeProvider,
    OpenAISEORecommendationNarrativeProvider,
    SEORecommendationNarrativeProviderError,
)
from app.integrations.seo_summary_provider import (
    MockSEOCompetitorProfileGenerationProvider,
    MockSEORecommendationNarrativeProvider,
)
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _site() -> SEOSite:
    return SEOSite(
        id="site-1",
        business_id="biz-1",
        display_name="Client Site",
        base_url="https://client.example/",
        normalized_domain="client.example",
        is_active=True,
        is_primary=True,
    )


def _recommendation_run() -> SEORecommendationRun:
    return SEORecommendationRun(
        id="rec-run-1",
        business_id="biz-1",
        site_id="site-1",
        audit_run_id="audit-1",
        comparison_run_id=None,
        status="completed",
        total_recommendations=1,
        critical_recommendations=0,
        warning_recommendations=1,
        info_recommendations=0,
    )


def _recommendation() -> SEORecommendation:
    return SEORecommendation(
        id="rec-1",
        business_id="biz-1",
        site_id="site-1",
        recommendation_run_id="rec-run-1",
        audit_run_id="audit-1",
        comparison_run_id=None,
        rule_key="fix_missing_title_tags",
        category="SEO",
        severity="WARNING",
        title="Fix missing title tags",
        rationale="Deterministic recommendation rationale.",
        priority_score=65,
        priority_band="high",
        effort_bucket="LOW",
        status="open",
    )


def test_ai_provider_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER_NAME", raising=False)
    monkeypatch.delenv("AI_MODEL_NAME", raising=False)
    monkeypatch.delenv("AI_TIMEOUT_VALUE", raising=False)
    monkeypatch.delenv("AI_PROMPT_TEXT_COMPETITOR", raising=False)
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATIONS", raising=False)
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATION", raising=False)
    monkeypatch.delenv("AI_EVAL_ALLOW_REAL_PROVIDER", raising=False)
    monkeypatch.delenv("SEO_COMPETITOR_PROFILE_RAW_OUTPUT_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("SEO_COMPETITOR_PROFILE_REJECTED_DRAFT_RETENTION_DAYS", raising=False)

    settings = get_settings()

    assert settings.ai_provider_api_key is None
    assert settings.ai_provider_name == "openai"
    assert settings.ai_model_name == "gpt-4o-mini"
    assert settings.ai_timeout_value == 30
    assert settings.ai_prompt_text_competitor == ""
    assert settings.ai_prompt_text_competitor_source == "empty"
    assert settings.ai_prompt_text_competitor_legacy_config_used is False
    assert settings.ai_prompt_text_recommendations == ""
    assert settings.ai_prompt_text_recommendations_source == "empty"
    assert settings.ai_prompt_text_recommendations_legacy_config_used is False
    assert settings.ai_eval_allow_real_provider is False
    assert settings.ai_prompt_text_recommendation == ""
    assert settings.seo_competitor_profile_raw_output_retention_days == 30
    assert settings.seo_competitor_profile_run_retention_days == 180
    assert settings.seo_competitor_profile_rejected_draft_retention_days == 90


def test_ai_provider_config_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-configured")
    monkeypatch.setenv("AI_PROVIDER_NAME", " OPENAI ")
    monkeypatch.setenv("AI_MODEL_NAME", " gpt-custom-model ")
    monkeypatch.setenv("AI_TIMEOUT_VALUE", "45")
    monkeypatch.setenv("AI_PROMPT_TEXT_COMPETITOR", "Prefer local competitors")
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATIONS", "Focus on recommendation narratives")
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATION", "Legacy fallback text")
    monkeypatch.setenv("AI_EVAL_ALLOW_REAL_PROVIDER", "true")
    monkeypatch.setenv("SEO_COMPETITOR_PROFILE_RAW_OUTPUT_RETENTION_DAYS", "21")
    monkeypatch.setenv("SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS", "365")
    monkeypatch.setenv("SEO_COMPETITOR_PROFILE_REJECTED_DRAFT_RETENTION_DAYS", "60")

    settings = get_settings()

    assert settings.ai_provider_api_key == "sk-configured"
    assert settings.ai_provider_name == "openai"
    assert settings.ai_model_name == "gpt-custom-model"
    assert settings.ai_timeout_value == 45
    assert settings.ai_prompt_text_competitor == "Prefer local competitors"
    assert settings.ai_prompt_text_competitor_source == "split"
    assert settings.ai_prompt_text_competitor_legacy_config_used is False
    assert settings.ai_prompt_text_recommendations == "Focus on recommendation narratives"
    assert settings.ai_prompt_text_recommendations_source == "split"
    assert settings.ai_prompt_text_recommendations_legacy_config_used is False
    assert settings.ai_eval_allow_real_provider is True
    assert settings.ai_prompt_text_recommendation == "Legacy fallback text"
    assert settings.seo_competitor_profile_raw_output_retention_days == 21
    assert settings.seo_competitor_profile_run_retention_days == 365
    assert settings.seo_competitor_profile_rejected_draft_retention_days == 60


def test_ai_provider_config_uses_legacy_prompt_text_as_split_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_PROMPT_TEXT_COMPETITOR", raising=False)
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATIONS", raising=False)
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATION", "Legacy shared guidance")

    settings = get_settings()

    assert settings.ai_prompt_text_competitor == "Legacy shared guidance"
    assert settings.ai_prompt_text_competitor_source == "legacy_fallback"
    assert settings.ai_prompt_text_competitor_legacy_config_used is True
    assert settings.ai_prompt_text_recommendations == "Legacy shared guidance"
    assert settings.ai_prompt_text_recommendations_source == "legacy_fallback"
    assert settings.ai_prompt_text_recommendations_legacy_config_used is True
    assert settings.ai_prompt_text_recommendation == "Legacy shared guidance"


def test_ai_provider_config_uses_legacy_prompt_text_when_split_prompt_vars_are_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROMPT_TEXT_COMPETITOR", "   ")
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATIONS", "")
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATION", "Legacy shared guidance")

    settings = get_settings()

    assert settings.ai_prompt_text_competitor == "Legacy shared guidance"
    assert settings.ai_prompt_text_competitor_source == "legacy_fallback"
    assert settings.ai_prompt_text_competitor_legacy_config_used is True
    assert settings.ai_prompt_text_recommendations == "Legacy shared guidance"
    assert settings.ai_prompt_text_recommendations_source == "legacy_fallback"
    assert settings.ai_prompt_text_recommendations_legacy_config_used is True


def test_provider_factory_uses_configured_model_timeout_and_prompt_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.setenv("AI_TIMEOUT_VALUE", "41")
    monkeypatch.setenv("AI_PROMPT_TEXT_COMPETITOR", "Prioritize direct local rivals")

    provider = get_seo_competitor_profile_generation_provider()

    assert isinstance(provider, OpenAISEOCompetitorProfileGenerationProvider)
    assert provider.model_name == "gpt-configured"
    assert provider.timeout_seconds == 41
    assert provider.prompt_text_competitor == "Prioritize direct local rivals"
    assert provider.prompt_source == "split"
    assert provider.legacy_config_used is False
    assert provider.prompt_config_key == "ai_prompt_text_competitor"


def test_provider_factory_competitor_prompt_metadata_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.delenv("AI_PROMPT_TEXT_COMPETITOR", raising=False)
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATION", "Legacy competitor guidance")

    provider = get_seo_competitor_profile_generation_provider()

    assert isinstance(provider, OpenAISEOCompetitorProfileGenerationProvider)
    assert provider.prompt_text_competitor == "Legacy competitor guidance"
    assert provider.prompt_source == "legacy_fallback"
    assert provider.legacy_config_used is True


def test_provider_factory_competitor_prompt_metadata_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.delenv("AI_PROMPT_TEXT_COMPETITOR", raising=False)
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATION", raising=False)

    provider = get_seo_competitor_profile_generation_provider()

    assert isinstance(provider, OpenAISEOCompetitorProfileGenerationProvider)
    assert provider.prompt_text_competitor == ""
    assert provider.prompt_source == "empty"
    assert provider.legacy_config_used is False


def test_provider_factory_missing_api_key_returns_safe_misconfigured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)

    provider = get_seo_competitor_profile_generation_provider()

    assert isinstance(provider, MisconfiguredSEOCompetitorProfileGenerationProvider)
    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "provider_auth_config"
    assert "credentials are not configured" in exc_info.value.safe_message.lower()


def test_provider_factory_invalid_provider_name_is_rejected_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "invalid-provider")
    monkeypatch.setenv("AI_MODEL_NAME", "invalid-model")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-ignored")

    provider = get_seo_competitor_profile_generation_provider()

    assert isinstance(provider, MisconfiguredSEOCompetitorProfileGenerationProvider)
    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "provider_auth_config"
    assert "selection is invalid" in exc_info.value.safe_message.lower()


def test_provider_factory_supports_mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "mock")
    monkeypatch.setenv("AI_MODEL_NAME", "mock-model-configured")
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)

    provider = get_seo_competitor_profile_generation_provider()

    assert isinstance(provider, MockSEOCompetitorProfileGenerationProvider)
    assert provider.model_name == "mock-model-configured"


def test_retention_config_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS", "0")

    with pytest.raises(RuntimeError, match="SEO_COMPETITOR_PROFILE_RUN_RETENTION_DAYS must be >= 1"):
        get_settings()


def test_recommendation_narrative_provider_factory_uses_openai_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.setenv("AI_TIMEOUT_VALUE", "39")
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATIONS", "Focus on backlog clarity")

    provider = get_seo_recommendation_narrative_provider()

    assert isinstance(provider, OpenAISEORecommendationNarrativeProvider)
    assert provider.model_name == "gpt-configured"
    assert provider.timeout_seconds == 39
    assert provider.prompt_text_recommendations == "Focus on backlog clarity"
    assert provider.prompt_source == "split"
    assert provider.legacy_config_used is False
    assert provider.prompt_config_key == "ai_prompt_text_recommendations"


def test_recommendation_narrative_provider_factory_prompt_metadata_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATIONS", raising=False)
    monkeypatch.setenv("AI_PROMPT_TEXT_RECOMMENDATION", "Legacy recommendation guidance")

    provider = get_seo_recommendation_narrative_provider()

    assert isinstance(provider, OpenAISEORecommendationNarrativeProvider)
    assert provider.prompt_text_recommendations == "Legacy recommendation guidance"
    assert provider.prompt_source == "legacy_fallback"
    assert provider.legacy_config_used is True


def test_recommendation_narrative_provider_factory_prompt_metadata_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATIONS", raising=False)
    monkeypatch.delenv("AI_PROMPT_TEXT_RECOMMENDATION", raising=False)

    provider = get_seo_recommendation_narrative_provider()

    assert isinstance(provider, OpenAISEORecommendationNarrativeProvider)
    assert provider.prompt_text_recommendations == ""
    assert provider.prompt_source == "empty"
    assert provider.legacy_config_used is False


def test_recommendation_narrative_provider_factory_missing_key_in_production_is_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "test-pepper")

    provider = get_seo_recommendation_narrative_provider()

    assert isinstance(provider, MisconfiguredSEORecommendationNarrativeProvider)
    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_recommendation_run(),
            recommendations=[_recommendation()],
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=[_recommendation()],
            competitor_telemetry_summary={
                "lookback_days": 30,
                "total_runs": 0,
                "total_raw_candidate_count": 0,
                "total_included_candidate_count": 0,
                "total_excluded_candidate_count": 0,
                "exclusion_counts_by_reason": {},
            },
            current_tuning_values={
                "competitor_candidate_min_relevance_score": 35,
                "competitor_candidate_big_box_penalty": 20,
                "competitor_candidate_directory_penalty": 35,
                "competitor_candidate_local_alignment_bonus": 10,
            },
        )
    assert exc_info.value.code == "provider_auth_config"
    assert "credentials are not configured" in exc_info.value.safe_message.lower()


def test_recommendation_narrative_provider_factory_missing_key_falls_back_to_mock_in_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_MODEL_NAME", "gpt-configured")
    monkeypatch.delenv("AI_PROVIDER_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ENVIRONMENT", "development")

    provider = get_seo_recommendation_narrative_provider()

    assert isinstance(provider, MockSEORecommendationNarrativeProvider)


def test_recommendation_narrative_provider_factory_invalid_provider_is_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "invalid-provider")
    monkeypatch.setenv("AI_MODEL_NAME", "invalid-model")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-ignored")

    provider = get_seo_recommendation_narrative_provider()

    assert isinstance(provider, MisconfiguredSEORecommendationNarrativeProvider)
    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_recommendation_run(),
            recommendations=[_recommendation()],
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=[_recommendation()],
            competitor_telemetry_summary={
                "lookback_days": 30,
                "total_runs": 0,
                "total_raw_candidate_count": 0,
                "total_included_candidate_count": 0,
                "total_excluded_candidate_count": 0,
                "exclusion_counts_by_reason": {},
            },
            current_tuning_values={
                "competitor_candidate_min_relevance_score": 35,
                "competitor_candidate_big_box_penalty": 20,
                "competitor_candidate_directory_penalty": 35,
                "competitor_candidate_local_alignment_bonus": 10,
            },
        )
    assert exc_info.value.code == "provider_auth_config"
    assert "selection is invalid" in exc_info.value.safe_message.lower()

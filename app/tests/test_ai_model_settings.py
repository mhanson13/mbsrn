from __future__ import annotations

import pytest

from app.services.ai_model_settings import (
    AIModelValidationError,
    ensure_ai_model_capabilities_for_task,
    get_ai_task_registry,
    resolve_ai_model_for_task,
    resolve_ai_model_name,
    UnknownAITaskAliasError,
)


def test_ai_task_registry_contains_expected_aliases() -> None:
    registry = get_ai_task_registry()

    assert set(registry.keys()) == {
        "requirements_helper",
        "media_metadata_helper",
        "recommendation_explanation",
        "competitor_analysis",
        "seo_audit_summary",
        "competitor_comparison_summary",
        "migration_site_plan",
        "migration_site_generation",
        "migration_section_repair",
        "validation_explainer",
        "moderation",
        "embeddings",
        "evaluation_harness",
        "migration_live_contract_validation",
        "maintenance_cleanup",
    }
    assert registry["recommendation_explanation"].default_tier == "mini"
    assert registry["competitor_analysis"].capabilities == ("text", "structured_json", "web_search")
    assert registry["migration_site_generation"].capabilities == ("text", "structured_json", "code_generation")


def test_ai_task_registry_marks_mock_only_aliases() -> None:
    registry = get_ai_task_registry()

    assert registry["seo_audit_summary"].mock_only_for_now is True
    assert registry["competitor_comparison_summary"].mock_only_for_now is True
    assert registry["moderation"].mock_only_for_now is True
    assert registry["embeddings"].mock_only_for_now is True
    assert registry["maintenance_cleanup"].mock_only_for_now is True


def test_resolve_ai_model_name_prefers_explicit_override() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name="  gpt-requested  ",
        admin_default_model_name="gpt-admin",
        env_default_model_name="gpt-env",
        provider_fallback_model_name="gpt-provider",
    )

    assert resolved.model_name == "gpt-requested"
    assert resolved.model_source == "explicit"


def test_resolve_ai_model_name_uses_admin_default_when_explicit_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name="  ",
        admin_default_model_name=" gpt-admin-default ",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-admin-default"
    assert resolved.model_source == "admin_config"


def test_resolve_ai_model_name_uses_env_default_when_admin_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        admin_default_model_name=None,
        env_default_model_name=" gpt-env-default ",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-env-default"
    assert resolved.model_source == "env"


def test_resolve_ai_model_name_uses_provider_fallback_when_admin_and_env_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        admin_default_model_name="",
        env_default_model_name=" ",
        provider_fallback_model_name=" gpt-provider-fallback ",
    )

    assert resolved.model_name == "gpt-provider-fallback"
    assert resolved.model_source == "provider_fallback"


def test_resolve_ai_model_name_uses_final_fallback_when_all_sources_are_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        admin_default_model_name=None,
        env_default_model_name=None,
        provider_fallback_model_name=None,
        final_fallback_model_name="gpt-hardcoded",
    )

    assert resolved.model_name == "gpt-hardcoded"
    assert resolved.model_source == "provider_fallback"


def test_resolve_ai_model_for_task_preserves_current_precedence_for_allowed_models() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="competitor_analysis",
        requested_model_name=None,
        admin_default_model_name=" GPT-5-MINI ",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.task_alias == "competitor_analysis"
    assert resolved.model_name == "gpt-5-mini"
    assert resolved.model_source == "admin_config"
    assert resolved.model_alias == "compatibility_shared"
    assert resolved.tier == "mid_reasoning"
    assert resolved.compatibility_mapped is True
    assert resolved.legacy_compatibility_mode is False
    assert resolved.fallback_used is False


def test_resolve_ai_model_for_task_rejects_deprecated_explicit_model() -> None:
    with pytest.raises(
        AIModelValidationError,
        match="Requested AI model for task alias 'recommendation_explanation' cannot use deprecated or blocked model values.",
    ):
        resolve_ai_model_for_task(
            task_alias="recommendation_explanation",
            requested_model_name=" GPT-4O-MINI ",
            admin_default_model_name="gpt-5-mini",
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )


def test_resolve_ai_model_for_task_allows_legacy_admin_default_in_phase1_compatibility_mode() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="migration_site_generation",
        requested_model_name=None,
        admin_default_model_name=" GPT-4O-MINI ",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-4o-mini"
    assert resolved.model_source == "admin_config"
    assert resolved.compatibility_mapped is True
    assert resolved.legacy_compatibility_mode is True
    assert "compatibility-mapped" in resolved.safe_diagnostic_message


def test_ensure_ai_model_capabilities_for_requirements_helper_rejects_embedding_models() -> None:
    with pytest.raises(
        AIModelValidationError,
        match=(
            "Configured AI model for task alias 'requirements_helper' does not satisfy required "
            "capabilities: structured_json."
        ),
    ):
        ensure_ai_model_capabilities_for_task(
            task_alias="requirements_helper",
            model_name="text-embedding-3-small",
            model_source="admin_config",
        )


def test_ensure_ai_model_capabilities_for_media_metadata_helper_requires_multimodal_models() -> None:
    with pytest.raises(AIModelValidationError) as exc_info:
        ensure_ai_model_capabilities_for_task(
            task_alias="media_metadata_helper",
            model_name="text-embedding-3-small",
            model_source="explicit",
        )

    message = str(exc_info.value)
    assert "Requested AI model for task alias 'media_metadata_helper'" in message
    assert "structured_json" in message
    assert "multimodal" in message


def test_resolve_ai_model_for_task_rejects_unknown_alias() -> None:
    with pytest.raises(UnknownAITaskAliasError, match="Unknown AI task alias 'unknown_task'."):
        resolve_ai_model_for_task(
            task_alias="unknown_task",
            requested_model_name=None,
            admin_default_model_name=None,
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )


def test_resolve_ai_model_for_task_does_not_require_provider_for_mock_only_alias() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="seo_audit_summary",
        requested_model_name="gpt-5-mini",
        admin_default_model_name="gpt-admin-default",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name is None
    assert resolved.model_source == "task_default"
    assert resolved.model_alias is None
    assert resolved.allow_real_provider is False
    assert resolved.mock_only_for_now is True
    assert resolved.compatibility_mapped is False
    assert "deterministic/mock-only" in resolved.safe_diagnostic_message


def test_resolve_ai_model_for_task_rejects_codex_family() -> None:
    with pytest.raises(
        AIModelValidationError,
        match="Requested AI model for task alias 'evaluation_harness' cannot use deprecated or blocked model values.",
    ):
        resolve_ai_model_for_task(
            task_alias="evaluation_harness",
            requested_model_name=" codex-latest ",
            admin_default_model_name=None,
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )

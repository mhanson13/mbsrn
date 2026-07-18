from __future__ import annotations

import pytest

from app.services.ai_model_settings import (
    AIModelValidationError,
    ensure_ai_model_capabilities_for_task,
    get_ai_task_registry,
    list_admin_configurable_ai_task_definitions,
    resolve_ai_model_for_task,
    resolve_ai_model_name,
    resolve_openai_non_tool_structured_output_profile,
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


def test_admin_configurable_ai_tasks_match_expected_aliases() -> None:
    aliases = {task.task_alias for task in list_admin_configurable_ai_task_definitions()}

    assert aliases == {
        "requirements_helper",
        "media_metadata_helper",
        "recommendation_explanation",
        "competitor_analysis",
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
        task_override_model_name="gpt-task",
        business_default_model_name="gpt-business",
        env_default_model_name="gpt-env",
        provider_fallback_model_name="gpt-provider",
    )

    assert resolved.model_name == "gpt-requested"
    assert resolved.model_source == "explicit"


def test_resolve_ai_model_name_uses_task_override_when_explicit_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name="  ",
        task_override_model_name=" gpt-task-default ",
        business_default_model_name="gpt-business-default",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-task-default"
    assert resolved.model_source == "task_override"


def test_resolve_ai_model_name_uses_business_default_when_task_override_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        task_override_model_name=None,
        business_default_model_name=" gpt-business-default ",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-business-default"
    assert resolved.model_source == "business_default"


def test_resolve_ai_model_name_uses_env_default_when_business_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        task_override_model_name=None,
        business_default_model_name=None,
        env_default_model_name=" gpt-env-default ",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-env-default"
    assert resolved.model_source == "env_default"


def test_resolve_ai_model_name_uses_provider_fallback_when_business_and_env_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        task_override_model_name=None,
        business_default_model_name="",
        env_default_model_name=" ",
        provider_fallback_model_name=" gpt-provider-fallback ",
    )

    assert resolved.model_name == "gpt-provider-fallback"
    assert resolved.model_source == "provider_fallback"


def test_resolve_ai_model_name_uses_final_fallback_when_all_sources_are_missing() -> None:
    resolved = resolve_ai_model_name(
        requested_model_name=None,
        task_override_model_name=None,
        business_default_model_name=None,
        env_default_model_name=None,
        provider_fallback_model_name=None,
        final_fallback_model_name="gpt-hardcoded",
    )

    assert resolved.model_name == "gpt-hardcoded"
    assert resolved.model_source == "provider_fallback"


def test_resolve_ai_model_for_task_uses_task_override_before_business_default() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="competitor_analysis",
        requested_model_name=None,
        task_override_model_name=" GPT-5.6-TERRA ",
        business_default_model_name="gpt-business-default",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.task_alias == "competitor_analysis"
    assert resolved.model_name == "gpt-5.6-terra"
    assert resolved.model_source == "task_override"
    assert resolved.model_alias == "compatibility_shared"
    assert resolved.tier == "mid_reasoning"
    assert resolved.compatibility_mapped is True
    assert resolved.legacy_compatibility_mode is False
    assert resolved.validation_status == "allowed"
    assert resolved.fallback_used is False


def test_resolve_ai_model_for_task_explicit_request_still_beats_task_override() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="migration_site_generation",
        requested_model_name=" gpt-5.6 ",
        task_override_model_name="gpt-5.6-terra",
        business_default_model_name="gpt-business-default",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-5.6"
    assert resolved.model_source == "explicit"


def test_resolve_ai_model_for_task_cleared_task_override_inherits_business_default() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="requirements_helper",
        requested_model_name=None,
        task_override_model_name=" \n\t ",
        business_default_model_name=" GPT-5-MINI ",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-5-mini"
    assert resolved.model_source == "business_default"


def test_resolve_ai_model_for_task_rejects_deprecated_explicit_model() -> None:
    with pytest.raises(
        AIModelValidationError,
        match="Requested AI model for task alias 'recommendation_explanation' cannot use deprecated or blocked model values.",
    ):
        resolve_ai_model_for_task(
            task_alias="recommendation_explanation",
            requested_model_name=" GPT-4O-MINI ",
            task_override_model_name=None,
            business_default_model_name="gpt-5-mini",
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )


def test_resolve_ai_model_for_task_allows_legacy_business_default_in_phase1_compatibility_mode() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="migration_site_generation",
        requested_model_name=None,
        task_override_model_name=None,
        business_default_model_name=" GPT-4O-MINI ",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name == "gpt-4o-mini"
    assert resolved.model_source == "business_default"
    assert resolved.compatibility_mapped is True
    assert resolved.legacy_compatibility_mode is True
    assert resolved.validation_status == "compatibility_allowed"
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
            model_source="business_default",
        )


def test_resolve_openai_non_tool_structured_output_profile_prefers_responses_for_gpt_5_family() -> None:
    profile = resolve_openai_non_tool_structured_output_profile(" GPT-5.6-TERRA ")

    assert profile.model_name == "gpt-5.6-terra"
    assert profile.endpoint_path == "/responses"
    assert profile.response_format_mode == "json_schema"
    assert profile.request_body_mode == "responses_text_format_json_schema"
    assert profile.supports_temperature_override is False
    assert profile.temperature_default_only is True
    assert profile.request_shape_adjusted is True


def test_resolve_openai_non_tool_structured_output_profile_keeps_chat_path_for_non_gpt_5_models() -> None:
    profile = resolve_openai_non_tool_structured_output_profile(" gpt-4.1-mini ")

    assert profile.model_name == "gpt-4.1-mini"
    assert profile.endpoint_path == "/chat/completions"
    assert profile.response_format_mode == "json_schema"
    assert profile.request_body_mode == "chat_json_schema"
    assert profile.supports_temperature_override is True
    assert profile.temperature_default_only is False
    assert profile.request_shape_adjusted is False


def test_resolve_ai_model_for_task_rejects_luna_for_media_metadata_helper() -> None:
    with pytest.raises(AIModelValidationError) as exc_info:
        resolve_ai_model_for_task(
            task_alias="media_metadata_helper",
            requested_model_name=None,
            task_override_model_name="gpt-5.6-luna",
            business_default_model_name=None,
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )

    message = str(exc_info.value)
    assert "Configured AI model for task alias 'media_metadata_helper'" in message
    assert "structured_json" not in message
    assert "multimodal" in message


def test_resolve_ai_model_for_task_rejects_unknown_alias() -> None:
    with pytest.raises(UnknownAITaskAliasError, match="Unknown AI task alias 'unknown_task'."):
        resolve_ai_model_for_task(
            task_alias="unknown_task",
            requested_model_name=None,
            task_override_model_name=None,
            business_default_model_name=None,
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )


def test_resolve_ai_model_for_task_keeps_non_admin_mock_only_alias_deterministic() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="seo_audit_summary",
        requested_model_name="gpt-5-mini",
        task_override_model_name="gpt-5.6-terra",
        business_default_model_name="gpt-business-default",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name is None
    assert resolved.model_source == "deterministic"
    assert resolved.model_alias is None
    assert resolved.allow_real_provider is False
    assert resolved.mock_only_for_now is True
    assert resolved.compatibility_mapped is False
    assert resolved.validation_status == "deterministic"
    assert "deterministic/mock-only" in resolved.safe_diagnostic_message


def test_resolve_ai_model_for_task_allows_deterministic_override_for_embeddings() -> None:
    resolved = resolve_ai_model_for_task(
        task_alias="embeddings",
        requested_model_name=None,
        task_override_model_name=" deterministic ",
        business_default_model_name="gpt-business-default",
        env_default_model_name="gpt-env-default",
        provider_fallback_model_name="gpt-provider-fallback",
    )

    assert resolved.model_name is None
    assert resolved.model_source == "deterministic"
    assert resolved.validation_status == "deterministic"
    assert resolved.fallback_used is False


def test_resolve_ai_model_for_task_rejects_codex_family() -> None:
    with pytest.raises(
        AIModelValidationError,
        match="Requested AI model for task alias 'evaluation_harness' cannot use deprecated or blocked model values.",
    ):
        resolve_ai_model_for_task(
            task_alias="evaluation_harness",
            requested_model_name=" codex-latest ",
            task_override_model_name=None,
            business_default_model_name=None,
            env_default_model_name="gpt-env-default",
            provider_fallback_model_name="gpt-provider-fallback",
        )

from __future__ import annotations

from app.services.ai_model_settings import resolve_ai_model_name


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

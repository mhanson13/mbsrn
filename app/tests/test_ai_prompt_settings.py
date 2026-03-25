from __future__ import annotations

from app.services.ai_prompt_settings import resolve_ai_prompt_text


def test_resolve_ai_prompt_text_prefers_admin_override() -> None:
    resolved = resolve_ai_prompt_text(
        admin_prompt_text="  Admin prompt override  ",
        env_prompt_text="Env prompt fallback",
        env_legacy_config_used=True,
    )

    assert resolved.prompt_text == "Admin prompt override"
    assert resolved.prompt_source == "admin_config"
    assert resolved.legacy_config_used is False


def test_resolve_ai_prompt_text_uses_env_when_admin_blank() -> None:
    resolved = resolve_ai_prompt_text(
        admin_prompt_text="   ",
        env_prompt_text="  Env prompt fallback  ",
        env_legacy_config_used=True,
    )

    assert resolved.prompt_text == "Env prompt fallback"
    assert resolved.prompt_source == "env"
    assert resolved.legacy_config_used is True


def test_resolve_ai_prompt_text_uses_default_when_all_unset() -> None:
    resolved = resolve_ai_prompt_text(
        admin_prompt_text=None,
        env_prompt_text="  ",
        env_legacy_config_used=False,
    )

    assert resolved.prompt_text == ""
    assert resolved.prompt_source == "default"
    assert resolved.legacy_config_used is False


def test_resolve_ai_prompt_text_uses_admin_override_when_env_missing() -> None:
    resolved = resolve_ai_prompt_text(
        admin_prompt_text="Business override prompt",
        env_prompt_text=None,
        env_legacy_config_used=False,
    )

    assert resolved.prompt_text == "Business override prompt"
    assert resolved.prompt_source == "admin_config"
    assert resolved.legacy_config_used is False


def test_resolve_ai_prompt_text_uses_default_when_env_missing_and_admin_blank() -> None:
    resolved = resolve_ai_prompt_text(
        admin_prompt_text="  ",
        env_prompt_text=None,
        env_legacy_config_used=False,
    )

    assert resolved.prompt_text == ""
    assert resolved.prompt_source == "default"
    assert resolved.legacy_config_used is False


def test_resolve_ai_prompt_text_trims_outer_whitespace_but_keeps_inner_formatting() -> None:
    resolved = resolve_ai_prompt_text(
        admin_prompt_text="  Keep line one.\n  Keep line two.  ",
        env_prompt_text="Env prompt fallback",
        env_legacy_config_used=False,
    )

    assert resolved.prompt_text == "Keep line one.\n  Keep line two."
    assert resolved.prompt_source == "admin_config"


def test_resolve_ai_prompt_text_precedence_matrix_for_competitor_and_recommendation_keys() -> None:
    prompt_values = {
        "ai_prompt_text_competitor": "Competitor env fallback prompt",
        "ai_prompt_text_recommendations": "Recommendation env fallback prompt",
    }

    for _, env_prompt in prompt_values.items():
        resolved = resolve_ai_prompt_text(
            admin_prompt_text=" \n\t ",
            env_prompt_text=env_prompt,
            env_legacy_config_used=False,
        )
        assert resolved.prompt_text == env_prompt
        assert resolved.prompt_source == "env"

        default_resolved = resolve_ai_prompt_text(
            admin_prompt_text=" ",
            env_prompt_text="",
            env_legacy_config_used=False,
        )
        assert default_resolved.prompt_text == ""
        assert default_resolved.prompt_source == "default"

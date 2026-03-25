from __future__ import annotations

from app.schemas.ai_prompt import build_ai_prompt_preview_read


def test_build_ai_prompt_preview_read_returns_none_when_prompts_are_empty() -> None:
    preview = build_ai_prompt_preview_read(
        prompt_type="competitor",
        system_prompt="   ",
        user_prompt="\n\t ",
        model="gpt-4o-mini",
        prompt_version="v1",
    )
    assert preview is None


def test_build_ai_prompt_preview_read_sanitizes_and_truncates_prompt_text() -> None:
    raw_system_prompt = "A" * 20050
    raw_user_prompt = "line-1\x00\x07\nline-2"

    preview = build_ai_prompt_preview_read(
        prompt_type="recommendation",
        system_prompt=raw_system_prompt,
        user_prompt=raw_user_prompt,
        model="  model-name  ",
        prompt_version="  prompt-v2  ",
    )

    assert preview is not None
    assert preview.prompt_type == "recommendation"
    assert preview.system_prompt == "A" * 20000
    assert preview.user_prompt == "line-1\nline-2"
    assert preview.model == "model-name"
    assert preview.prompt_version == "prompt-v2"
    assert preview.truncated is True


def test_build_ai_prompt_preview_read_bounds_optional_metadata_fields() -> None:
    preview = build_ai_prompt_preview_read(
        prompt_type="competitor",
        system_prompt="system",
        user_prompt="user",
        model="x" * 500,
        prompt_version="y" * 500,
    )

    assert preview is not None
    assert preview.model == "x" * 128
    assert preview.prompt_version == "y" * 64
    assert preview.truncated is False


def test_build_ai_prompt_preview_read_normalizes_prompt_source() -> None:
    preview = build_ai_prompt_preview_read(
        prompt_type="competitor",
        system_prompt="system",
        user_prompt="user",
        source=" ADMIN_CONFIG ",
    )

    assert preview is not None
    assert preview.source == "admin_config"

    unsupported = build_ai_prompt_preview_read(
        prompt_type="competitor",
        system_prompt="system",
        user_prompt="user",
        source="unexpected_source",
    )
    assert unsupported is not None
    assert unsupported.source is None


def test_build_ai_prompt_preview_read_includes_label_and_metrics() -> None:
    preview = build_ai_prompt_preview_read(
        prompt_type="competitor",
        system_prompt="system",
        user_prompt="user",
        prompt_label="  resolved competitor prompt  ",
        prompt_metrics={
            "total_prompt_chars": 3210,
            "context_json_chars": 712,
            "ignored": "bad",
        },
    )

    assert preview is not None
    assert preview.prompt_label == "resolved competitor prompt"
    assert preview.prompt_metrics == {
        "total_prompt_chars": 3210,
        "context_json_chars": 712,
    }

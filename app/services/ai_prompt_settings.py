from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PromptSource = Literal["admin_config", "env", "default"]


@dataclass(frozen=True)
class ResolvedAIPromptText:
    prompt_text: str
    prompt_source: PromptSource
    legacy_config_used: bool


def resolve_ai_prompt_text(
    *,
    admin_prompt_text: str | None,
    env_prompt_text: str | None,
    env_legacy_config_used: bool,
) -> ResolvedAIPromptText:
    # Business-level admin override wins when non-empty; blank values are treated
    # as unset and safely fall back to deployment env/default behavior.
    admin_override = _clean_optional_text(admin_prompt_text)
    if admin_override is not None:
        return ResolvedAIPromptText(
            prompt_text=admin_override,
            prompt_source="admin_config",
            legacy_config_used=False,
        )

    env_value = _clean_optional_text(env_prompt_text)
    if env_value is not None:
        return ResolvedAIPromptText(
            prompt_text=env_value,
            prompt_source="env",
            legacy_config_used=bool(env_legacy_config_used),
        )

    return ResolvedAIPromptText(
        prompt_text="",
        prompt_source="default",
        legacy_config_used=False,
    )


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned

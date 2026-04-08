from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModelSource = Literal["explicit", "admin_config", "env", "provider_fallback"]


@dataclass(frozen=True)
class ResolvedAIModelName:
    model_name: str
    model_source: ModelSource


def resolve_ai_model_name(
    *,
    requested_model_name: str | None,
    admin_default_model_name: str | None,
    env_default_model_name: str | None,
    provider_fallback_model_name: str | None,
    final_fallback_model_name: str = "gpt-4o-mini",
) -> ResolvedAIModelName:
    requested = _clean_optional_text(requested_model_name)
    if requested is not None:
        return ResolvedAIModelName(
            model_name=requested,
            model_source="explicit",
        )

    admin_default = _clean_optional_text(admin_default_model_name)
    if admin_default is not None:
        return ResolvedAIModelName(
            model_name=admin_default,
            model_source="admin_config",
        )

    env_default = _clean_optional_text(env_default_model_name)
    if env_default is not None:
        return ResolvedAIModelName(
            model_name=env_default,
            model_source="env",
        )

    provider_fallback = _clean_optional_text(provider_fallback_model_name)
    if provider_fallback is not None:
        return ResolvedAIModelName(
            model_name=provider_fallback,
            model_source="provider_fallback",
        )

    return ResolvedAIModelName(
        model_name=_clean_optional_text(final_fallback_model_name) or "gpt-4o-mini",
        model_source="provider_fallback",
    )


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned

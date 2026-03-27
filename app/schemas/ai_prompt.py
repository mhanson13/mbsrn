from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AIPromptType = Literal["competitor", "recommendation"]
AIPromptSource = Literal["admin_config", "env", "default"]

_PROMPT_TEXT_MAX_CHARS = 50000
_PROMPT_MODEL_MAX_CHARS = 128
_PROMPT_VERSION_MAX_CHARS = 64
_PROMPT_LABEL_MAX_CHARS = 96
_PROMPT_METRICS_MAX_ITEMS = 24
_PROMPT_METRIC_KEY_MAX_CHARS = 48


def _sanitize_prompt_text(value: Any, *, max_chars: int) -> tuple[str, bool]:
    if value is None:
        return ("", False)

    raw = str(value)
    filtered_chars: list[str] = []
    for char in raw:
        if char in {"\n", "\r", "\t"} or ord(char) >= 32:
            filtered_chars.append(char)
    normalized = "".join(filtered_chars).strip()
    if not normalized:
        return ("", False)

    if len(normalized) <= max_chars:
        return (normalized, False)
    return (normalized[:max_chars], True)


def _compact_optional_text(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None
    compacted = " ".join(str(value).split()).strip()
    if not compacted:
        return None
    return compacted[:max_chars]


class AIPromptPreviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = True
    prompt_type: AIPromptType
    system_prompt: str = ""
    user_prompt: str = ""
    model: str | None = None
    # Effective prompt version extracted from the resolved prompt body when available.
    prompt_version: str | None = None
    # Operator-facing effective prompt identity label.
    prompt_label: str | None = None
    source: AIPromptSource | None = None
    truncated: bool = False
    # Debug-safe bounded metrics only (counts/lengths), never raw prompt bodies or secrets.
    prompt_metrics: dict[str, int] | None = None

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _compact_optional_text(value, max_chars=_PROMPT_MODEL_MAX_CHARS)

    @field_validator("prompt_version", mode="before")
    @classmethod
    def normalize_prompt_version(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _compact_optional_text(value, max_chars=_PROMPT_VERSION_MAX_CHARS)

    @field_validator("prompt_label", mode="before")
    @classmethod
    def normalize_prompt_label(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _compact_optional_text(value, max_chars=_PROMPT_LABEL_MAX_CHARS)

    @field_validator("prompt_metrics", mode="before")
    @classmethod
    def normalize_prompt_metrics(cls, value: Any) -> dict[str, int] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        normalized: dict[str, int] = {}
        for raw_key, raw_value in value.items():
            key = _compact_optional_text(raw_key, max_chars=_PROMPT_METRIC_KEY_MAX_CHARS)
            if key is None:
                continue
            try:
                parsed_value = int(raw_value)
            except (TypeError, ValueError):
                continue
            normalized[key] = max(0, parsed_value)
            if len(normalized) >= _PROMPT_METRICS_MAX_ITEMS:
                break
        if not normalized:
            return None
        return normalized


def build_ai_prompt_preview_read(
    *,
    prompt_type: AIPromptType,
    system_prompt: Any,
    user_prompt: Any,
    model: Any = None,
    prompt_version: Any = None,
    prompt_label: Any = None,
    source: Any = None,
    prompt_metrics: Any = None,
) -> AIPromptPreviewRead | None:
    normalized_system_prompt, system_truncated = _sanitize_prompt_text(
        system_prompt,
        max_chars=_PROMPT_TEXT_MAX_CHARS,
    )
    normalized_user_prompt, user_truncated = _sanitize_prompt_text(
        user_prompt,
        max_chars=_PROMPT_TEXT_MAX_CHARS,
    )
    if not normalized_system_prompt and not normalized_user_prompt:
        return None

    return AIPromptPreviewRead.model_validate(
        {
            "available": True,
            "prompt_type": prompt_type,
            "system_prompt": normalized_system_prompt,
            "user_prompt": normalized_user_prompt,
            "model": _compact_optional_text(model, max_chars=_PROMPT_MODEL_MAX_CHARS),
            "prompt_version": _compact_optional_text(prompt_version, max_chars=_PROMPT_VERSION_MAX_CHARS),
            "prompt_label": _compact_optional_text(prompt_label, max_chars=_PROMPT_LABEL_MAX_CHARS),
            "source": _normalize_prompt_source(source),
            "truncated": system_truncated or user_truncated,
            "prompt_metrics": prompt_metrics,
        }
    )


def _normalize_prompt_source(value: Any) -> str | None:
    compacted = _compact_optional_text(value, max_chars=32)
    if compacted is None:
        return None
    lowered = compacted.lower()
    if lowered in {"admin_config", "env", "default"}:
        return lowered
    return None

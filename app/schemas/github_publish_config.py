from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_optional_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _normalize_base_path(value: object) -> str:
    normalized = _normalize_optional_text(value, max_length=160) or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = normalized.replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


class GitHubPublishConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    repository: str | None = None
    default_branch: str = "main"
    base_path: str = "/"
    enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitHubPublishConfigUpdateRequest(BaseModel):
    repository: str | None = Field(default=None, max_length=255)
    default_branch: str | None = Field(default="main", max_length=120)
    base_path: str | None = Field(default="/", max_length=160)
    enabled: bool = False

    @field_validator("repository", "default_branch", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=255)

    @field_validator("base_path", mode="before")
    @classmethod
    def _normalize_base_path_value(cls, value: object) -> str:
        return _normalize_base_path(value)

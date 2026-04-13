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
    owner: str | None = None
    repository: str | None = None
    default_branch: str = "main"
    base_path: str = "/"
    deploy_workflow_mode: str = "site_repo_template_v1"
    target_environment_key: str = "gke_prod"
    target_environment_source: str = "admin_config"
    enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitHubPublishConfigUpdateRequest(BaseModel):
    owner: str | None = Field(default=None, max_length=120)
    repository: str | None = Field(default=None, max_length=255)
    default_branch: str | None = Field(default="main", max_length=120)
    base_path: str | None = Field(default="/", max_length=160)
    deploy_workflow_mode: str | None = Field(default="site_repo_template_v1", max_length=60)
    target_environment_key: str | None = Field(default="gke_prod", max_length=80)
    enabled: bool = False

    @field_validator("owner", mode="before")
    @classmethod
    def _normalize_owner(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=120)

    @field_validator("repository", mode="before")
    @classmethod
    def _normalize_repository(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=255)

    @field_validator("default_branch", mode="before")
    @classmethod
    def _normalize_default_branch(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=120)

    @field_validator("base_path", mode="before")
    @classmethod
    def _normalize_base_path_value(cls, value: object) -> str:
        return _normalize_base_path(value)

    @field_validator("deploy_workflow_mode", mode="before")
    @classmethod
    def _normalize_deploy_workflow_mode(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=60)
        return normalized.lower() if normalized else None

    @field_validator("target_environment_key", mode="before")
    @classmethod
    def _normalize_target_environment_key(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=80)
        return normalized.lower() if normalized else None

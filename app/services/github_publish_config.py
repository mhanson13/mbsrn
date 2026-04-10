from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.github_publish_config import GitHubPublishConfig
from app.repositories.github_publish_config_repository import GitHubPublishConfigRepository
from app.schemas.github_publish_config import GitHubPublishConfigUpdateRequest

_VALID_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_VALID_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_VALID_BASE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]{0,159}$")

logger = logging.getLogger(__name__)


class GitHubPublishConfigValidationError(ValueError):
    pass


def _normalize_base_path(value: object) -> str:
    normalized = str(value or "/").strip() or "/"
    normalized = normalized.replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


class GitHubPublishConfigService:
    def __init__(
        self,
        *,
        session: Session,
        repository: GitHubPublishConfigRepository,
    ) -> None:
        self.session = session
        self.repository = repository

    def get(self) -> GitHubPublishConfig:
        existing = self.repository.get_singleton()
        if existing is not None:
            return existing
        return GitHubPublishConfig(
            repository="",
            default_branch="main",
            base_path="/",
            enabled=False,
        )

    @staticmethod
    def _emit_structured_log(*, payload: dict[str, object], fallback_message: str, level: int) -> None:
        try:
            message = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            message = fallback_message
        logger.log(level, message, extra={"json_fields": payload})

    def update(
        self,
        *,
        payload: GitHubPublishConfigUpdateRequest,
        actor_principal_id: str | None = None,
        actor_business_id: str | None = None,
    ) -> GitHubPublishConfig:
        repository = (payload.repository or "").strip()
        raw_default_branch = (payload.default_branch or "").strip()
        default_branch = raw_default_branch or "main"
        base_path = _normalize_base_path(payload.base_path)
        enabled = bool(payload.enabled)

        if enabled and not repository:
            raise GitHubPublishConfigValidationError(
                "Repository is required when GitHub publishing is enabled."
            )
        if repository and not _VALID_REPOSITORY_PATTERN.fullmatch(repository):
            raise GitHubPublishConfigValidationError(
                "Repository must use owner/repo format (for example: mhanson13/tnmfire)."
            )
        if enabled and not raw_default_branch:
            raise GitHubPublishConfigValidationError(
                "Default branch is required when GitHub publishing is enabled."
            )
        if (
            not _VALID_BRANCH_PATTERN.fullmatch(default_branch)
            or ".." in default_branch
            or default_branch.startswith("/")
            or default_branch.endswith("/")
            or "//" in default_branch
        ):
            raise GitHubPublishConfigValidationError(
                "Default branch is invalid. Use letters, numbers, ., _, -, or / only."
            )
        if not _VALID_BASE_PATH_PATTERN.fullmatch(base_path) or ".." in base_path:
            raise GitHubPublishConfigValidationError(
                "Base path is invalid. Use '/' or '/subpath' with letters, numbers, -, _, ., and /."
            )

        existing = self.repository.get_singleton()
        previous_values = {
            "repository": (existing.repository if existing is not None else ""),
            "default_branch": (existing.default_branch if existing is not None else "main"),
            "base_path": (existing.base_path if existing is not None else "/"),
            "enabled": bool(existing.enabled) if existing is not None else False,
        }
        updated_values = {
            "repository": repository,
            "default_branch": default_branch,
            "base_path": base_path,
            "enabled": enabled,
        }

        if existing is None:
            existing = GitHubPublishConfig(
                repository=repository,
                default_branch=default_branch,
                base_path=base_path,
                enabled=enabled,
            )
        else:
            existing.repository = repository
            existing.default_branch = default_branch
            existing.base_path = base_path
            existing.enabled = enabled
        self.repository.save(existing)
        self.session.commit()
        self.session.refresh(existing)
        changed_fields = [
            field_name
            for field_name in ("repository", "default_branch", "base_path", "enabled")
            if previous_values.get(field_name) != updated_values.get(field_name)
        ]
        changed_values = {
            field_name: {
                "previous": previous_values.get(field_name),
                "current": updated_values.get(field_name),
            }
            for field_name in changed_fields
        }
        self._emit_structured_log(
            payload={
                "event": "admin_github_publish_config_updated",
                "timestamp": utc_now().isoformat(),
                "actor_principal_id": (actor_principal_id or "").strip() or None,
                "actor_business_id": (actor_business_id or "").strip() or None,
                "changed_fields": changed_fields,
                "changed_values": changed_values,
                "effective_target": {
                    "repository": existing.repository,
                    "default_branch": existing.default_branch,
                    "base_path": existing.base_path,
                    "enabled": bool(existing.enabled),
                },
            },
            fallback_message="admin_github_publish_config_updated",
            level=logging.INFO,
        )
        return existing

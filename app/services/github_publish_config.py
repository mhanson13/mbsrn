from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.github_publish_config import GitHubPublishConfig
from app.repositories.github_publish_config_repository import GitHubPublishConfigRepository
from app.schemas.github_publish_config import GitHubPublishConfigUpdateRequest

_VALID_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_VALID_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_VALID_BASE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]{0,159}$")


class GitHubPublishConfigValidationError(ValueError):
    pass


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

    def update(self, *, payload: GitHubPublishConfigUpdateRequest) -> GitHubPublishConfig:
        repository = (payload.repository or "").strip()
        default_branch = (payload.default_branch or "main").strip() or "main"
        base_path = (payload.base_path or "/").strip() or "/"
        enabled = bool(payload.enabled)

        if enabled and not repository:
            raise GitHubPublishConfigValidationError("repository is required when enabled is true.")
        if repository and not _VALID_REPOSITORY_PATTERN.fullmatch(repository):
            raise GitHubPublishConfigValidationError("repository must use owner/name format.")
        if not _VALID_BRANCH_PATTERN.fullmatch(default_branch) or ".." in default_branch:
            raise GitHubPublishConfigValidationError("default_branch is invalid.")
        if not _VALID_BASE_PATH_PATTERN.fullmatch(base_path) or ".." in base_path:
            raise GitHubPublishConfigValidationError("base_path is invalid.")

        existing = self.repository.get_singleton()
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
        return existing

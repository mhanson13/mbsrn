from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.github_publish_config import GitHubPublishConfig


class GitHubPublishConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_singleton(self) -> GitHubPublishConfig | None:
        stmt: Select[tuple[GitHubPublishConfig]] = select(GitHubPublishConfig).order_by(GitHubPublishConfig.id.asc())
        return self.session.scalar(stmt)

    def save(self, config: GitHubPublishConfig) -> GitHubPublishConfig:
        self.session.add(config)
        self.session.flush()
        return config

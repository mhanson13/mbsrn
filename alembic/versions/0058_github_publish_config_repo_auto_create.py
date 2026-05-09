"""add repo auto-create policy flag to github publish config

Revision ID: 0058_github_publish_config_repo_auto_create
Revises: 0057_github_publish_config_managed_deploy_secret
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0058_github_publish_config_repo_auto_create"
down_revision = "0057_github_publish_config_managed_deploy_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "github_publish_config",
        sa.Column(
            "github_repository_auto_create_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("github_publish_config", "github_repository_auto_create_enabled")

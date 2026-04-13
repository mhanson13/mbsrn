"""add deploy workflow mode and target environment metadata to github publish config

Revision ID: 0054_github_publish_config_deploy_target_metadata
Revises: 0053_github_publish_config
Create Date: 2026-04-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0054_github_publish_config_deploy_target_metadata"
down_revision = "0053_github_publish_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "github_publish_config",
        sa.Column(
            "deploy_workflow_mode",
            sa.String(length=60),
            nullable=False,
            server_default="site_repo_template_v1",
        ),
    )
    op.add_column(
        "github_publish_config",
        sa.Column(
            "target_environment_key",
            sa.String(length=80),
            nullable=False,
            server_default="gke_prod",
        ),
    )
    op.add_column(
        "github_publish_config",
        sa.Column(
            "target_environment_source",
            sa.String(length=60),
            nullable=False,
            server_default="admin_config",
        ),
    )


def downgrade() -> None:
    op.drop_column("github_publish_config", "target_environment_source")
    op.drop_column("github_publish_config", "target_environment_key")
    op.drop_column("github_publish_config", "deploy_workflow_mode")

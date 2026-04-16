"""add namespace isolation defaults json to github publish config

Revision ID: 0055_github_publish_config_namespace_isolation_defaults
Revises: 0054_github_publish_config_deploy_target_metadata
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0055_github_publish_config_namespace_isolation_defaults"
down_revision = "0054_github_publish_config_deploy_target_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "github_publish_config",
        sa.Column(
            "namespace_isolation_defaults_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("github_publish_config", "namespace_isolation_defaults_json")

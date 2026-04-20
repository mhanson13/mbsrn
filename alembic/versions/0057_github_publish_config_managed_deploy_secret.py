"""add managed deploy secret fields to github publish config

Revision ID: 0057_github_publish_config_managed_deploy_secret
Revises: 0056_github_publish_config_managed_gke_fields
Create Date: 2026-04-20 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0057_github_publish_config_managed_deploy_secret"
down_revision = "0056_github_publish_config_managed_gke_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "github_publish_config",
        sa.Column("managed_gcp_deploy_key_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "github_publish_config",
        sa.Column("managed_gcp_deploy_key_key_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "github_publish_config",
        sa.Column("managed_gcp_deploy_key_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("github_publish_config", "managed_gcp_deploy_key_updated_at")
    op.drop_column("github_publish_config", "managed_gcp_deploy_key_key_version")
    op.drop_column("github_publish_config", "managed_gcp_deploy_key_encrypted")

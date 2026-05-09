"""add managed gke config fields to github publish config

Revision ID: 0056_github_publish_config_managed_gke_fields
Revises: 0055_github_publish_config_namespace_isolation_defaults
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0056_github_publish_config_managed_gke_fields"
down_revision = "0055_github_publish_config_namespace_isolation_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "github_publish_config",
        sa.Column("managed_gke_cluster_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "github_publish_config",
        sa.Column("managed_gke_cluster_location", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "github_publish_config",
        sa.Column("managed_gke_project_id", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("github_publish_config", "managed_gke_project_id")
    op.drop_column("github_publish_config", "managed_gke_cluster_location")
    op.drop_column("github_publish_config", "managed_gke_cluster_name")

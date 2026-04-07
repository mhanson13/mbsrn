"""add seo migration publish deploy and approval fields

Revision ID: 0049_seo_migration_publish_and_deploy
Revises: 0048_seo_migration_workspaces
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0049_seo_migration_publish_and_deploy"
down_revision = "0048_seo_migration_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("latest_approved_artifact_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("latest_approved_artifact_version_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("analytics_config_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("publish_status", sa.String(length=32), nullable=False, server_default="not_ready"),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("deploy_status", sa.String(length=32), nullable=False, server_default="not_ready"),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_published_artifact_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_published_artifact_version_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_published_commit_sha", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_published_by_principal_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_deployed_artifact_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_deployed_artifact_version_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_deployed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("last_deployed_by_principal_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("publish_history_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("deploy_history_json", sa.JSON(), nullable=True),
    )

    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("approval_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("approved_by_principal_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("approval_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("publish_status", sa.String(length=32), nullable=False, server_default="not_published"),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("deploy_status", sa.String(length=32), nullable=False, server_default="not_deployed"),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("last_published_commit_sha", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("last_publish_error_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("last_deployed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "seo_migration_artifact_versions",
        sa.Column("last_deploy_error_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("seo_migration_artifact_versions", "last_deploy_error_summary")
    op.drop_column("seo_migration_artifact_versions", "last_deployed_at")
    op.drop_column("seo_migration_artifact_versions", "last_publish_error_summary")
    op.drop_column("seo_migration_artifact_versions", "last_published_at")
    op.drop_column("seo_migration_artifact_versions", "last_published_commit_sha")
    op.drop_column("seo_migration_artifact_versions", "deploy_status")
    op.drop_column("seo_migration_artifact_versions", "publish_status")
    op.drop_column("seo_migration_artifact_versions", "approval_notes")
    op.drop_column("seo_migration_artifact_versions", "approved_at")
    op.drop_column("seo_migration_artifact_versions", "approved_by_principal_id")
    op.drop_column("seo_migration_artifact_versions", "approval_status")

    op.drop_column("seo_migration_workspaces", "deploy_history_json")
    op.drop_column("seo_migration_workspaces", "publish_history_json")
    op.drop_column("seo_migration_workspaces", "last_deployed_by_principal_id")
    op.drop_column("seo_migration_workspaces", "last_deployed_at")
    op.drop_column("seo_migration_workspaces", "last_deployed_artifact_version_number")
    op.drop_column("seo_migration_workspaces", "last_deployed_artifact_version_id")
    op.drop_column("seo_migration_workspaces", "last_published_by_principal_id")
    op.drop_column("seo_migration_workspaces", "last_published_at")
    op.drop_column("seo_migration_workspaces", "last_published_commit_sha")
    op.drop_column("seo_migration_workspaces", "last_published_artifact_version_number")
    op.drop_column("seo_migration_workspaces", "last_published_artifact_version_id")
    op.drop_column("seo_migration_workspaces", "deploy_status")
    op.drop_column("seo_migration_workspaces", "publish_status")
    op.drop_column("seo_migration_workspaces", "analytics_config_json")
    op.drop_column("seo_migration_workspaces", "latest_approved_artifact_version_number")
    op.drop_column("seo_migration_workspaces", "latest_approved_artifact_version_id")

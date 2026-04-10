"""add github publish config singleton table

Revision ID: 0053_github_publish_config
Revises: 0052_seo_migration_artifact_quality_evaluation
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0053_github_publish_config"
down_revision = "0052_seo_migration_artifact_quality_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_publish_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("default_branch", sa.String(length=120), nullable=False, server_default="main"),
        sa.Column("base_path", sa.String(length=160), nullable=False, server_default="/"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("github_publish_config")

"""add seo migration artifact quality evaluation json

Revision ID: 0052_seo_migration_artifact_quality_evaluation
Revises: 0051_business_migration_draft_timeout_seconds
Create Date: 2026-04-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0052_seo_migration_artifact_quality_evaluation"
down_revision = "0051_business_migration_draft_timeout_seconds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seo_migration_artifact_versions") as batch_op:
        batch_op.add_column(sa.Column("artifact_quality_evaluation_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("seo_migration_artifact_versions") as batch_op:
        batch_op.drop_column("artifact_quality_evaluation_json")

"""add seo migration workspace and artifact version tables

Revision ID: 0048_seo_migration_workspaces
Revises: 0047_seo_automation_config_source
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0048_seo_migration_workspaces"
down_revision = "0047_seo_automation_config_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_migration_workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "source_site_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_ingested",
        ),
        sa.Column(
            "migration_status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("operator_requirements_json", sa.JSON(), nullable=True),
        sa.Column("enriched_content_notes_json", sa.JSON(), nullable=True),
        sa.Column("brand_business_facts_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("imported_source_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("latest_generated_artifact_version_id", sa.String(length=36), nullable=True),
        sa.Column("latest_generated_artifact_version_number", sa.Integer(), nullable=True),
        sa.Column("publish_config_json", sa.JSON(), nullable=True),
        sa.Column("deploy_config_json", sa.JSON(), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("updated_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "site_id", name="uq_seo_migration_workspaces_business_site"),
    )
    op.create_index(
        "ix_seo_migration_workspaces_business_id",
        "seo_migration_workspaces",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_migration_workspaces_site_id",
        "seo_migration_workspaces",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_migration_workspaces_business_site_status",
        "seo_migration_workspaces",
        ["business_id", "site_id", "migration_status"],
        unique=False,
    )

    op.create_table(
        "seo_migration_artifact_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("strategy_summary", sa.Text(), nullable=True),
        sa.Column("page_map_json", sa.JSON(), nullable=True),
        sa.Column("homepage_structure_json", sa.JSON(), nullable=True),
        sa.Column("service_page_suggestions_json", sa.JSON(), nullable=True),
        sa.Column("cta_contact_structure_json", sa.JSON(), nullable=True),
        sa.Column("seo_meta_suggestions_json", sa.JSON(), nullable=True),
        sa.Column("redirect_suggestions_json", sa.JSON(), nullable=True),
        sa.Column("analytics_placeholders_json", sa.JSON(), nullable=True),
        sa.Column("generated_files_json", sa.JSON(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_name", sa.String(length=64), nullable=False, server_default="mock"),
        sa.Column(
            "model_name",
            sa.String(length=128),
            nullable=False,
            server_default="mock-seo-migration-v1",
        ),
        sa.Column("prompt_version", sa.String(length=64), nullable=False, server_default="seo-migration-v1"),
        sa.Column("parse_warnings_json", sa.JSON(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"], ),
        sa.ForeignKeyConstraint(["workspace_id"], ["seo_migration_workspaces.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_seo_migration_artifact_versions_workspace_version",
        ),
    )
    op.create_index(
        "ix_seo_migration_artifact_versions_business_id",
        "seo_migration_artifact_versions",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_migration_artifact_versions_site_id",
        "seo_migration_artifact_versions",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_migration_artifact_versions_workspace_id",
        "seo_migration_artifact_versions",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_seo_migration_artifact_versions_business_site_created_at",
        "seo_migration_artifact_versions",
        ["business_id", "site_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seo_migration_artifact_versions_business_site_created_at",
        table_name="seo_migration_artifact_versions",
    )
    op.drop_index("ix_seo_migration_artifact_versions_workspace_id", table_name="seo_migration_artifact_versions")
    op.drop_index("ix_seo_migration_artifact_versions_site_id", table_name="seo_migration_artifact_versions")
    op.drop_index("ix_seo_migration_artifact_versions_business_id", table_name="seo_migration_artifact_versions")
    op.drop_table("seo_migration_artifact_versions")

    op.drop_index("ix_seo_migration_workspaces_business_site_status", table_name="seo_migration_workspaces")
    op.drop_index("ix_seo_migration_workspaces_site_id", table_name="seo_migration_workspaces")
    op.drop_index("ix_seo_migration_workspaces_business_id", table_name="seo_migration_workspaces")
    op.drop_table("seo_migration_workspaces")


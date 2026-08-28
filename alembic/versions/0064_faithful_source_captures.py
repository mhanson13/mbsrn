"""add asynchronous faithful source captures

Revision ID: 0064_faithful_source_captures
Revises: 0063_preview_releases
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0064_faithful_source_captures"
down_revision = "0063_preview_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_migration_source_captures",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_source_url", sa.String(length=2048), nullable=False),
        sa.Column("authorization_acknowledged", sa.Boolean(), nullable=False),
        sa.Column("authorization_statement_version", sa.String(length=64), nullable=True),
        sa.Column("authorization_acknowledged_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("authorization_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_page_limit", sa.Integer(), nullable=False),
        sa.Column("requested_asset_limit", sa.Integer(), nullable=False),
        sa.Column("requested_max_total_bytes", sa.Integer(), nullable=False),
        sa.Column("browser_engine", sa.String(length=32), nullable=True),
        sa.Column("manifest_json", sa.JSON(), nullable=True),
        sa.Column("manifest_storage_provider", sa.String(length=32), nullable=True),
        sa.Column("manifest_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("manifest_storage_generation", sa.String(length=128), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("asset_count", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.Integer(), nullable=False),
        sa.Column("unsupported_features_json", sa.JSON(), nullable=False),
        sa.Column("warning_codes_json", sa.JSON(), nullable=False),
        sa.Column("failure_reason_code", sa.String(length=120), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('analyze_rebuild', 'faithful_snapshot')",
            name="ck_seo_migration_source_captures_mode",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_seo_migration_source_captures_status",
        ),
        sa.CheckConstraint(
            "page_count >= 0 AND asset_count >= 0 AND total_bytes >= 0 AND attempt_count >= 0",
            name="ck_seo_migration_source_captures_counts",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["seo_migration_workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_seo_migration_source_captures_idempotency",
        ),
        sa.UniqueConstraint(
            "site_id",
            "source_version",
            name="uq_seo_migration_source_captures_site_version",
        ),
    )
    op.create_index(
        op.f("ix_seo_migration_source_captures_business_id"),
        "seo_migration_source_captures",
        ["business_id"],
    )
    op.create_index(
        op.f("ix_seo_migration_source_captures_site_id"),
        "seo_migration_source_captures",
        ["site_id"],
    )
    op.create_index(
        op.f("ix_seo_migration_source_captures_workspace_id"),
        "seo_migration_source_captures",
        ["workspace_id"],
    )
    op.create_index(
        "ix_seo_migration_source_captures_business_site_created",
        "seo_migration_source_captures",
        ["business_id", "site_id", "created_at"],
    )
    op.create_index(
        "ix_seo_migration_source_captures_status_created",
        "seo_migration_source_captures",
        ["status", "created_at"],
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("ingestion_mode", sa.String(length=32), nullable=False, server_default="analyze_rebuild"),
    )
    op.add_column(
        "seo_migration_workspaces",
        sa.Column("latest_source_capture_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_seo_migration_workspaces_latest_source_capture_id"),
        "seo_migration_workspaces",
        ["latest_source_capture_id"],
    )
    op.create_foreign_key(
        "fk_seo_migration_workspaces_latest_source_capture",
        "seo_migration_workspaces",
        "seo_migration_source_captures",
        ["latest_source_capture_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_seo_migration_workspaces_latest_source_capture",
        "seo_migration_workspaces",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_seo_migration_workspaces_latest_source_capture_id"),
        table_name="seo_migration_workspaces",
    )
    op.drop_column("seo_migration_workspaces", "latest_source_capture_id")
    op.drop_column("seo_migration_workspaces", "ingestion_mode")
    op.drop_index(
        "ix_seo_migration_source_captures_status_created",
        table_name="seo_migration_source_captures",
    )
    op.drop_index(
        "ix_seo_migration_source_captures_business_site_created",
        table_name="seo_migration_source_captures",
    )
    op.drop_index(
        op.f("ix_seo_migration_source_captures_workspace_id"),
        table_name="seo_migration_source_captures",
    )
    op.drop_index(
        op.f("ix_seo_migration_source_captures_site_id"),
        table_name="seo_migration_source_captures",
    )
    op.drop_index(
        op.f("ix_seo_migration_source_captures_business_id"),
        table_name="seo_migration_source_captures",
    )
    op.drop_table("seo_migration_source_captures")

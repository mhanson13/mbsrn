"""add immutable preview releases and gates

Revision ID: 0063_preview_releases
Revises: 0062_site_preview_identity
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0063_preview_releases"
down_revision = "0062_site_preview_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preview_releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_version_id", sa.String(length=36), nullable=False),
        sa.Column("release_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("preview_slug", sa.String(length=63), nullable=False),
        sa.Column("preview_hostname", sa.String(length=253), nullable=False),
        sa.Column("media_manifest_json", sa.JSON(), nullable=False),
        sa.Column("repo_owner", sa.String(length=120), nullable=True),
        sa.Column("repo_name", sa.String(length=255), nullable=True),
        sa.Column("repo_branch", sa.String(length=255), nullable=True),
        sa.Column("git_commit_sha", sa.String(length=80), nullable=True),
        sa.Column("certificate_asset_id", sa.String(length=36), nullable=True),
        sa.Column("certificate_fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("certificate_resource_name", sa.String(length=63), nullable=True),
        sa.Column("dns_hostname", sa.String(length=253), nullable=True),
        sa.Column("deployment_run_id", sa.String(length=80), nullable=True),
        sa.Column("preview_url", sa.String(length=2048), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_version_id"], ["seo_migration_artifact_versions.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["certificate_asset_id"], ["tls_certificate_assets.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "site_id", "artifact_version_id", name="uq_preview_releases_business_site_artifact"
        ),
        sa.UniqueConstraint("site_id", "release_number", name="uq_preview_releases_site_number"),
    )
    op.create_index(op.f("ix_preview_releases_business_id"), "preview_releases", ["business_id"])
    op.create_index(op.f("ix_preview_releases_site_id"), "preview_releases", ["site_id"])
    op.create_index(op.f("ix_preview_releases_artifact_version_id"), "preview_releases", ["artifact_version_id"])
    op.create_index(
        "ix_preview_releases_business_site_created", "preview_releases", ["business_id", "site_id", "created_at"]
    )

    op.create_table(
        "preview_release_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_gate", sa.String(length=32), nullable=True),
        sa.Column("failure_reason_code", sa.String(length=120), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("support_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["preview_releases.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_preview_release_operations_idempotency"),
        sa.UniqueConstraint("release_id", name="uq_preview_release_operations_release"),
    )
    op.create_index(op.f("ix_preview_release_operations_release_id"), "preview_release_operations", ["release_id"])
    op.create_index(op.f("ix_preview_release_operations_business_id"), "preview_release_operations", ["business_id"])
    op.create_index(op.f("ix_preview_release_operations_site_id"), "preview_release_operations", ["site_id"])
    op.create_index(
        "ix_preview_release_operations_business_site",
        "preview_release_operations",
        ["business_id", "site_id", "created_at"],
    )

    op.create_table(
        "preview_release_gates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("gate_name", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("next_action", sa.String(length=500), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["preview_release_operations.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["preview_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "gate_name", name="uq_preview_release_gates_release_name"),
    )
    op.create_index(op.f("ix_preview_release_gates_release_id"), "preview_release_gates", ["release_id"])
    op.create_index(op.f("ix_preview_release_gates_operation_id"), "preview_release_gates", ["operation_id"])
    op.create_index(
        "ix_preview_release_gates_release_ordinal", "preview_release_gates", ["release_id", "ordinal"]
    )


def downgrade() -> None:
    op.drop_index("ix_preview_release_gates_release_ordinal", table_name="preview_release_gates")
    op.drop_index(op.f("ix_preview_release_gates_operation_id"), table_name="preview_release_gates")
    op.drop_index(op.f("ix_preview_release_gates_release_id"), table_name="preview_release_gates")
    op.drop_table("preview_release_gates")
    op.drop_index("ix_preview_release_operations_business_site", table_name="preview_release_operations")
    op.drop_index(op.f("ix_preview_release_operations_site_id"), table_name="preview_release_operations")
    op.drop_index(op.f("ix_preview_release_operations_business_id"), table_name="preview_release_operations")
    op.drop_index(op.f("ix_preview_release_operations_release_id"), table_name="preview_release_operations")
    op.drop_table("preview_release_operations")
    op.drop_index("ix_preview_releases_business_site_created", table_name="preview_releases")
    op.drop_index(op.f("ix_preview_releases_artifact_version_id"), table_name="preview_releases")
    op.drop_index(op.f("ix_preview_releases_site_id"), table_name="preview_releases")
    op.drop_index(op.f("ix_preview_releases_business_id"), table_name="preview_releases")
    op.drop_table("preview_releases")

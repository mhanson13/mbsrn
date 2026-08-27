"""add self-managed TLS certificate assets and site bindings

Revision ID: 0061_self_managed_tls_certificates
Revises: 0060_business_ai_model_overrides
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0061_self_managed_tls_certificates"
down_revision = "0060_business_ai_model_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tls_certificate_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("custody", sa.String(length=32), nullable=False),
        sa.Column("certificate_kind", sa.String(length=32), nullable=False),
        sa.Column("key_algorithm", sa.String(length=32), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("serial_number", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("san_dns_names_json", sa.JSON(), nullable=False),
        sa.Column("not_valid_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("not_valid_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vault_secret_name", sa.String(length=255), nullable=True),
        sa.Column("vault_secret_version", sa.String(length=512), nullable=True),
        sa.Column("gcp_project_id", sa.String(length=63), nullable=False),
        sa.Column("gcp_resource_name", sa.String(length=63), nullable=True),
        sa.Column("gcp_resource_scope", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_reason_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.String(length=512), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "fingerprint_sha256",
            name="uq_tls_certificate_assets_business_fingerprint",
        ),
    )
    op.create_index(op.f("ix_tls_certificate_assets_business_id"), "tls_certificate_assets", ["business_id"])
    op.create_index(op.f("ix_tls_certificate_assets_hostname"), "tls_certificate_assets", ["hostname"])
    op.create_index(
        op.f("ix_tls_certificate_assets_gcp_resource_name"),
        "tls_certificate_assets",
        ["gcp_resource_name"],
    )
    op.create_index(
        "ix_tls_certificate_assets_business_hostname_status",
        "tls_certificate_assets",
        ["business_id", "hostname", "status"],
    )

    op.create_table(
        "site_tls_certificate_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("certificate_asset_id", sa.String(length=36), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("manifest_state", sa.String(length=32), nullable=False),
        sa.Column("serving_state", sa.String(length=32), nullable=False),
        sa.Column("observed_fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_principal_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["certificate_asset_id"], ["tls_certificate_assets.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "site_id",
            "certificate_asset_id",
            name="uq_site_tls_certificate_bindings_site_asset",
        ),
    )
    op.create_index(
        op.f("ix_site_tls_certificate_bindings_business_id"),
        "site_tls_certificate_bindings",
        ["business_id"],
    )
    op.create_index(op.f("ix_site_tls_certificate_bindings_site_id"), "site_tls_certificate_bindings", ["site_id"])
    op.create_index(
        op.f("ix_site_tls_certificate_bindings_certificate_asset_id"),
        "site_tls_certificate_bindings",
        ["certificate_asset_id"],
    )
    op.create_index(
        "uq_site_tls_certificate_bindings_one_active_per_site",
        "site_tls_certificate_bindings",
        ["business_id", "site_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_site_tls_certificate_bindings_one_active_per_site",
        table_name="site_tls_certificate_bindings",
    )
    op.drop_index(
        op.f("ix_site_tls_certificate_bindings_certificate_asset_id"),
        table_name="site_tls_certificate_bindings",
    )
    op.drop_index(op.f("ix_site_tls_certificate_bindings_site_id"), table_name="site_tls_certificate_bindings")
    op.drop_index(op.f("ix_site_tls_certificate_bindings_business_id"), table_name="site_tls_certificate_bindings")
    op.drop_table("site_tls_certificate_bindings")
    op.drop_index("ix_tls_certificate_assets_business_hostname_status", table_name="tls_certificate_assets")
    op.drop_index(op.f("ix_tls_certificate_assets_gcp_resource_name"), table_name="tls_certificate_assets")
    op.drop_index(op.f("ix_tls_certificate_assets_hostname"), table_name="tls_certificate_assets")
    op.drop_index(op.f("ix_tls_certificate_assets_business_id"), table_name="tls_certificate_assets")
    op.drop_table("tls_certificate_assets")

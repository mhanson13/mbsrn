"""add canonical site preview identity

Revision ID: 0062_site_preview_identity
Revises: 0061_self_managed_tls_certificates
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0062_site_preview_identity"
down_revision = "0061_self_managed_tls_certificates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seo_sites", sa.Column("preview_slug", sa.String(length=63), nullable=True))
    op.add_column("seo_sites", sa.Column("preview_slug_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_seo_sites_preview_slug"), "seo_sites", ["preview_slug"], unique=False)
    op.create_unique_constraint("uq_seo_sites_preview_slug", "seo_sites", ["preview_slug"])


def downgrade() -> None:
    op.drop_constraint("uq_seo_sites_preview_slug", "seo_sites", type_="unique")
    op.drop_index(op.f("ix_seo_sites_preview_slug"), table_name="seo_sites")
    op.drop_column("seo_sites", "preview_slug_locked_at")
    op.drop_column("seo_sites", "preview_slug")

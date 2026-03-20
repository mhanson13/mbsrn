"""add seo site audit lifecycle fields

Revision ID: 0025_seo_site_audit_lifecycle_fields
Revises: 0024_google_business_profile_oauth_connections
Create Date: 2026-03-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0025_seo_site_audit_lifecycle_fields"
down_revision = "0024_google_business_profile_oauth_connections"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns("seo_sites")
    if "last_audit_run_id" not in existing:
        op.add_column("seo_sites", sa.Column("last_audit_run_id", sa.String(length=36), nullable=True))
    if "last_audit_status" not in existing:
        op.add_column("seo_sites", sa.Column("last_audit_status", sa.String(length=32), nullable=True))
    if "last_audit_completed_at" not in existing:
        op.add_column("seo_sites", sa.Column("last_audit_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    existing = _existing_columns("seo_sites")
    if "last_audit_completed_at" in existing:
        op.drop_column("seo_sites", "last_audit_completed_at")
    if "last_audit_status" in existing:
        op.drop_column("seo_sites", "last_audit_status")
    if "last_audit_run_id" in existing:
        op.drop_column("seo_sites", "last_audit_run_id")

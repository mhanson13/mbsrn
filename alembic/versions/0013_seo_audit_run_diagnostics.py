"""add seo audit run diagnostics counters

Revision ID: 0013_seo_audit_run_diagnostics
Revises: 0012_seo_audit_summaries
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_seo_audit_run_diagnostics"
down_revision = "0012_seo_audit_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_audit_runs",
        sa.Column("pages_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "seo_audit_runs",
        sa.Column("errors_encountered", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "seo_audit_runs",
        sa.Column("duplicate_urls_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "seo_audit_runs",
        sa.Column("crawl_duration_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("seo_audit_runs", "crawl_duration_ms")
    op.drop_column("seo_audit_runs", "duplicate_urls_skipped")
    op.drop_column("seo_audit_runs", "errors_encountered")
    op.drop_column("seo_audit_runs", "pages_skipped")

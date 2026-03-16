"""harden seo site uniqueness and primary constraints

Revision ID: 0014_seo_sites_uniqueness_hardening
Revises: 0013_seo_audit_run_diagnostics
Create Date: 2026-03-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_seo_sites_uniqueness_hardening"
down_revision = "0013_seo_audit_run_diagnostics"
branch_labels = None
depends_on = None


def _count_duplicate_domains(connection) -> int:  # noqa: ANN001
    result = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT business_id, normalized_domain
                FROM seo_sites
                GROUP BY business_id, normalized_domain
                HAVING COUNT(*) > 1
            ) AS duplicate_domains
            """
        )
    )
    return int(result.scalar() or 0)


def _count_multiple_primary_sites(connection) -> int:  # noqa: ANN001
    result = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT business_id
                FROM seo_sites
                GROUP BY business_id
                HAVING SUM(CASE WHEN is_primary THEN 1 ELSE 0 END) > 1
            ) AS duplicate_primary_sites
            """
        )
    )
    return int(result.scalar() or 0)


def upgrade() -> None:
    connection = op.get_bind()

    duplicate_domain_count = _count_duplicate_domains(connection)
    if duplicate_domain_count > 0:
        raise RuntimeError(
            "Cannot apply SEO site uniqueness hardening: found "
            f"{duplicate_domain_count} duplicate (business_id, normalized_domain) entries in seo_sites."
        )

    duplicate_primary_count = _count_multiple_primary_sites(connection)
    if duplicate_primary_count > 0:
        raise RuntimeError(
            "Cannot apply SEO primary-site hardening: found "
            f"{duplicate_primary_count} businesses with multiple primary seo_sites rows."
        )

    op.create_index(
        "uq_seo_sites_business_normalized_domain",
        "seo_sites",
        ["business_id", "normalized_domain"],
        unique=True,
    )
    op.create_index(
        "uq_seo_sites_one_primary_per_business",
        "seo_sites",
        ["business_id"],
        unique=True,
        sqlite_where=sa.text("is_primary = 1"),
        postgresql_where=sa.text("is_primary = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_seo_sites_one_primary_per_business", table_name="seo_sites")
    op.drop_index("uq_seo_sites_business_normalized_domain", table_name="seo_sites")

"""enforce tenant ownership on lead_events via composite foreign key

Revision ID: 0004_lead_events_tenant_fk
Revises: 0003_lead_events_business_id
Create Date: 2026-03-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector


revision = "0004_lead_events_tenant_fk"
down_revision = "0003_lead_events_business_id"
branch_labels = None
depends_on = None


def _has_unique_constraint(inspector: Inspector, table: str, columns: tuple[str, ...]) -> bool:
    for constraint in inspector.get_unique_constraints(table):
        if tuple(constraint.get("column_names") or ()) == columns:
            return True
    return False


def _has_index(inspector: Inspector, table: str, name: str) -> bool:
    for index in inspector.get_indexes(table):
        if index.get("name") == name:
            return True
    return False


def _has_composite_fk(
    inspector: Inspector,
    *,
    table: str,
    constrained_columns: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> bool:
    for foreign_key in inspector.get_foreign_keys(table):
        if (
            foreign_key.get("referred_table") == referred_table
            and tuple(foreign_key.get("constrained_columns") or ()) == constrained_columns
            and tuple(foreign_key.get("referred_columns") or ()) == referred_columns
        ):
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()

    invalid_row_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM lead_events AS e
            LEFT JOIN leads AS l
              ON l.id = e.lead_id
             AND l.business_id = e.business_id
            WHERE l.id IS NULL
            """
        )
    ).scalar_one()
    if invalid_row_count > 0:
        raise RuntimeError(
            "Cannot add tenant integrity FK for lead_events: "
            f"found {invalid_row_count} rows without matching leads(id, business_id). "
            "Fix inconsistent lead_events data and rerun this migration."
        )

    inspector = sa.inspect(bind)
    if not _has_unique_constraint(inspector, "leads", ("id", "business_id")):
        with op.batch_alter_table("leads") as batch_op:
            batch_op.create_unique_constraint("uq_leads_id_business_id", ["id", "business_id"])

    inspector = sa.inspect(bind)
    if not _has_composite_fk(
        inspector,
        table="lead_events",
        constrained_columns=("lead_id", "business_id"),
        referred_table="leads",
        referred_columns=("id", "business_id"),
    ):
        with op.batch_alter_table("lead_events") as batch_op:
            batch_op.create_foreign_key(
                "fk_lead_events_lead_id_business_id_leads",
                "leads",
                ["lead_id", "business_id"],
                ["id", "business_id"],
            )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "lead_events", "ix_lead_events_business_id_lead_id"):
        with op.batch_alter_table("lead_events") as batch_op:
            batch_op.create_index("ix_lead_events_business_id_lead_id", ["business_id", "lead_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "lead_events", "ix_lead_events_business_id_lead_id"):
        with op.batch_alter_table("lead_events") as batch_op:
            batch_op.drop_index("ix_lead_events_business_id_lead_id")

    inspector = sa.inspect(bind)
    if _has_composite_fk(
        inspector,
        table="lead_events",
        constrained_columns=("lead_id", "business_id"),
        referred_table="leads",
        referred_columns=("id", "business_id"),
    ):
        with op.batch_alter_table("lead_events") as batch_op:
            batch_op.drop_constraint("fk_lead_events_lead_id_business_id_leads", type_="foreignkey")

    inspector = sa.inspect(bind)
    if _has_unique_constraint(inspector, "leads", ("id", "business_id")):
        with op.batch_alter_table("leads") as batch_op:
            batch_op.drop_constraint("uq_leads_id_business_id", type_="unique")

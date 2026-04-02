from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class SEOActionExecutionItem(Base):
    __tablename__ = "seo_action_execution_items"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "site_id",
            "source_draft_id",
            name="uq_seo_action_execution_items_source_draft",
        ),
        CheckConstraint(
            "state IN ('pending', 'in_progress', 'completed', 'blocked')",
            name="ck_seo_action_execution_items_state",
        ),
        CheckConstraint(
            "source IN ('chained')",
            name="ck_seo_action_execution_items_source",
        ),
        CheckConstraint(
            "automation_binding_state IN ('unbound', 'bound')",
            name="ck_seo_action_execution_items_automation_binding_state",
        ),
        Index(
            "ix_seo_action_execution_items_business_site_created_at",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_seo_action_execution_items_business_site_state",
            "business_id",
            "site_id",
            "state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id"),
        nullable=False,
        index=True,
    )
    site_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_sites.id"),
        nullable=False,
        index=True,
    )
    source_action_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("seo_action_chain_drafts.id"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="chained")
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    automation_ready: Mapped[bool] = mapped_column(default=False, nullable=False)
    automation_template_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bound_automation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("seo_automation_configs.id"),
        nullable=True,
        index=True,
    )
    automation_binding_state: Mapped[str] = mapped_column(String(16), nullable=False, default="unbound", index=True)
    automation_bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

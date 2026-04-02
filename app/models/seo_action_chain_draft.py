from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class SEOActionChainDraft(Base):
    __tablename__ = "seo_action_chain_drafts"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "site_id",
            "source_action_id",
            "action_type",
            name="uq_seo_action_chain_drafts_source_action_type",
        ),
        CheckConstraint(
            "state IN ('pending', 'completed', 'dismissed')",
            name="ck_seo_action_chain_drafts_state",
        ),
        CheckConstraint(
            "activation_state IN ('pending', 'activated')",
            name="ck_seo_action_chain_drafts_activation_state",
        ),
        Index(
            "ix_seo_action_chain_drafts_business_site_created_at",
            "business_id",
            "site_id",
            "created_at",
        ),
        Index(
            "ix_seo_action_chain_drafts_business_site_source_action",
            "business_id",
            "site_id",
            "source_action_id",
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
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    activation_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    activated_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    automation_template_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    automation_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

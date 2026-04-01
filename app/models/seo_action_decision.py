from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class SEOActionDecision(Base):
    __tablename__ = "seo_action_decisions"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "site_id",
            "action_id",
            name="uq_seo_action_decisions_business_site_action",
        ),
        CheckConstraint(
            "decision IN ('accepted', 'rejected', 'deferred')",
            name="ck_seo_action_decisions_decision",
        ),
        Index(
            "ix_seo_action_decisions_business_site_updated_at",
            "business_id",
            "site_id",
            "updated_at",
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
    action_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

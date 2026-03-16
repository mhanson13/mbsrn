from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class PrincipalIdentity(Base):
    __tablename__ = "principal_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "principal_id"],
            ["principals.business_id", "principals.id"],
            name="fk_principal_identities_business_id_principal_id_principals",
        ),
        UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_principal_identities_provider_subject",
        ),
        UniqueConstraint(
            "provider",
            "business_id",
            "principal_id",
            name="uq_principal_identities_provider_business_principal",
        ),
        Index(
            "ix_principal_identities_business_principal",
            "business_id",
            "principal_id",
        ),
        Index(
            "ix_principal_identities_provider_business",
            "provider",
            "business_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    principal = relationship("Principal")

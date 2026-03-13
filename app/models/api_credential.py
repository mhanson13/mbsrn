from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class APICredential(Base):
    __tablename__ = "api_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "principal_id"],
            ["principals.business_id", "principals.id"],
            name="fk_api_credentials_business_id_principal_id_principals",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id"), nullable=False, index=True
    )
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", overlaps="principal,credentials")
    principal = relationship("Principal", back_populates="credentials", overlaps="business")

    @property
    def principal_display_name(self) -> str:
        if self.principal is None:
            return self.principal_id
        return self.principal.display_name

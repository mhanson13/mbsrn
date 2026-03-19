from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.db.base import Base


class PrincipalRole(str, PyEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (PrimaryKeyConstraint("business_id", "id", name="pk_principals_business_id_id"),)

    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id"),
        nullable=False,
        index=True,
    )
    id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[PrincipalRole] = mapped_column(
        SAEnum(PrincipalRole),
        default=PrincipalRole.OPERATOR,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    business = relationship("Business", back_populates="principals", overlaps="credentials")
    credentials = relationship("APICredential", back_populates="principal", overlaps="business")

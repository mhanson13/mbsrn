from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class ProviderOAuthState(Base):
    __tablename__ = "provider_oauth_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "principal_id"],
            ["principals.business_id", "principals.id"],
            name="fk_provider_oauth_states_business_id_principal_id_principals",
        ),
        UniqueConstraint(
            "provider",
            "state_hash",
            name="uq_provider_oauth_states_provider_state_hash",
        ),
        Index(
            "ix_provider_oauth_states_provider_business_principal",
            "provider",
            "business_id",
            "principal_id",
        ),
        Index(
            "ix_provider_oauth_states_provider_expires",
            "provider",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_verifier_key_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

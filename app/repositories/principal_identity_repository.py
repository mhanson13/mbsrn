from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.principal_identity import PrincipalIdentity


class PrincipalIdentityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, identity: PrincipalIdentity) -> PrincipalIdentity:
        self.session.add(identity)
        self.session.flush()
        return identity

    def save(self, identity: PrincipalIdentity) -> PrincipalIdentity:
        self.session.add(identity)
        self.session.flush()
        return identity

    def get_by_provider_subject(self, *, provider: str, provider_subject: str) -> PrincipalIdentity | None:
        stmt: Select[tuple[PrincipalIdentity]] = (
            select(PrincipalIdentity)
            .where(PrincipalIdentity.provider == provider)
            .where(PrincipalIdentity.provider_subject == provider_subject)
        )
        return self.session.scalar(stmt)

    def get_active_by_provider_subject(
        self,
        *,
        provider: str,
        provider_subject: str,
    ) -> PrincipalIdentity | None:
        stmt: Select[tuple[PrincipalIdentity]] = (
            select(PrincipalIdentity)
            .where(PrincipalIdentity.provider == provider)
            .where(PrincipalIdentity.provider_subject == provider_subject)
            .where(PrincipalIdentity.is_active.is_(True))
        )
        return self.session.scalar(stmt)

    def get_for_business(self, *, business_id: str, identity_id: str) -> PrincipalIdentity | None:
        stmt: Select[tuple[PrincipalIdentity]] = (
            select(PrincipalIdentity)
            .where(PrincipalIdentity.business_id == business_id)
            .where(PrincipalIdentity.id == identity_id)
        )
        return self.session.scalar(stmt)

    def list_for_business(self, *, business_id: str) -> list[PrincipalIdentity]:
        stmt: Select[tuple[PrincipalIdentity]] = (
            select(PrincipalIdentity)
            .where(PrincipalIdentity.business_id == business_id)
            .order_by(PrincipalIdentity.created_at.desc(), PrincipalIdentity.id.desc())
        )
        return list(self.session.scalars(stmt))

    def list_for_business_principal(
        self,
        *,
        business_id: str,
        principal_id: str,
    ) -> list[PrincipalIdentity]:
        stmt: Select[tuple[PrincipalIdentity]] = (
            select(PrincipalIdentity)
            .where(PrincipalIdentity.business_id == business_id)
            .where(PrincipalIdentity.principal_id == principal_id)
            .order_by(PrincipalIdentity.created_at.desc(), PrincipalIdentity.id.desc())
        )
        return list(self.session.scalars(stmt))

    def list_for_provider_email(self, *, provider: str, email: str) -> list[PrincipalIdentity]:
        stmt: Select[tuple[PrincipalIdentity]] = (
            select(PrincipalIdentity)
            .where(PrincipalIdentity.provider == provider)
            .where(PrincipalIdentity.email == email)
            .order_by(PrincipalIdentity.created_at.desc(), PrincipalIdentity.id.desc())
        )
        return list(self.session.scalars(stmt))

    def mark_last_authenticated(
        self,
        *,
        provider: str,
        provider_subject: str,
        authenticated_at: datetime | None = None,
    ) -> PrincipalIdentity | None:
        identity = self.get_by_provider_subject(provider=provider, provider_subject=provider_subject)
        if identity is None:
            return None
        identity.last_authenticated_at = authenticated_at or utc_now()
        self.session.add(identity)
        self.session.flush()
        return identity

    def mark_last_authenticated_for_identity(
        self,
        identity: PrincipalIdentity,
        *,
        authenticated_at: datetime | None = None,
    ) -> PrincipalIdentity:
        identity.last_authenticated_at = authenticated_at or utc_now()
        self.session.add(identity)
        self.session.flush()
        return identity

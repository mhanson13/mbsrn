from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.principal import Principal, PrincipalRole


class PrincipalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, principal: Principal) -> Principal:
        self.session.add(principal)
        self.session.flush()
        return principal

    def save(self, principal: Principal) -> Principal:
        self.session.add(principal)
        self.session.flush()
        return principal

    def get_for_business(self, business_id: str, principal_id: str) -> Principal | None:
        stmt: Select[tuple[Principal]] = (
            select(Principal).where(Principal.business_id == business_id).where(Principal.id == principal_id)
        )
        return self.session.scalar(stmt)

    def list_for_business(self, business_id: str) -> list[Principal]:
        stmt: Select[tuple[Principal]] = (
            select(Principal)
            .where(Principal.business_id == business_id)
            .order_by(Principal.created_at.desc(), Principal.id.desc())
        )
        return list(self.session.scalars(stmt))

    def count_all(self) -> int:
        stmt = select(func.count()).select_from(Principal)
        return int(self.session.scalar(stmt) or 0)

    def count_active_admins(self, business_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Principal)
            .where(Principal.business_id == business_id)
            .where(Principal.role == PrincipalRole.ADMIN)
            .where(Principal.is_active.is_(True))
        )
        return int(self.session.scalar(stmt) or 0)

    def mark_last_authenticated(
        self,
        *,
        business_id: str,
        principal_id: str,
        authenticated_at: datetime | None = None,
    ) -> Principal | None:
        principal = self.get_for_business(business_id, principal_id)
        if principal is None:
            return None
        principal.last_authenticated_at = authenticated_at or utc_now()
        self.session.add(principal)
        self.session.flush()
        return principal

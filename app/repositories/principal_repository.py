from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.principal import Principal


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
            select(Principal)
            .where(Principal.business_id == business_id)
            .where(Principal.id == principal_id)
        )
        return self.session.scalar(stmt)

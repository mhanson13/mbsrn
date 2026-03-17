from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.provider_connection import ProviderConnection


class ProviderConnectionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, connection: ProviderConnection) -> ProviderConnection:
        self.session.add(connection)
        self.session.flush()
        return connection

    def save(self, connection: ProviderConnection) -> ProviderConnection:
        self.session.add(connection)
        self.session.flush()
        return connection

    def get_for_business_provider(
        self,
        *,
        business_id: str,
        provider: str,
    ) -> ProviderConnection | None:
        stmt: Select[tuple[ProviderConnection]] = (
            select(ProviderConnection)
            .where(ProviderConnection.business_id == business_id)
            .where(ProviderConnection.provider == provider)
        )
        return self.session.scalar(stmt)

    def list_for_provider(
        self,
        *,
        provider: str,
    ) -> list[ProviderConnection]:
        stmt: Select[tuple[ProviderConnection]] = (
            select(ProviderConnection)
            .where(ProviderConnection.provider == provider)
        )
        return list(self.session.scalars(stmt))

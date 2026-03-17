from __future__ import annotations

from collections.abc import Iterator

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
        business_id: str | None = None,
        include_inactive: bool = True,
        after_id: str | None = None,
        limit: int | None = None,
    ) -> list[ProviderConnection]:
        stmt = self._provider_select_statement(
            provider=provider,
            business_id=business_id,
            include_inactive=include_inactive,
            after_id=after_id,
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def iter_for_provider_batches(
        self,
        *,
        provider: str,
        batch_size: int = 100,
        business_id: str | None = None,
        include_inactive: bool = True,
    ) -> Iterator[list[ProviderConnection]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer.")

        cursor: str | None = None
        while True:
            rows = self.list_for_provider(
                provider=provider,
                business_id=business_id,
                include_inactive=include_inactive,
                after_id=cursor,
                limit=batch_size,
            )
            if not rows:
                return
            yield rows
            cursor = rows[-1].id

    def _provider_select_statement(
        self,
        *,
        provider: str,
        business_id: str | None,
        include_inactive: bool,
        after_id: str | None,
    ) -> Select[tuple[ProviderConnection]]:
        stmt: Select[tuple[ProviderConnection]] = (
            select(ProviderConnection)
            .where(ProviderConnection.provider == provider)
            .order_by(ProviderConnection.id.asc())
        )
        if business_id is not None:
            stmt = stmt.where(ProviderConnection.business_id == business_id)
        if not include_inactive:
            stmt = stmt.where(ProviderConnection.is_active.is_(True))
        if after_id is not None:
            stmt = stmt.where(ProviderConnection.id > after_id)
        return stmt

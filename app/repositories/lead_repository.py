from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.lead import Lead, LeadStatus
from app.models.lead_event import LeadEvent


class LeadRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, lead: Lead) -> Lead:
        self.session.add(lead)
        self.session.flush()
        return lead

    def get(self, lead_id: str) -> Lead | None:
        return self.session.get(Lead, lead_id)

    def get_for_business(self, business_id: str, lead_id: str) -> Lead | None:
        stmt: Select[tuple[Lead]] = select(Lead).where(Lead.business_id == business_id).where(Lead.id == lead_id)
        return self.session.scalar(stmt)

    def list(self, business_id: str, status: LeadStatus | None = None) -> list[Lead]:
        stmt: Select[tuple[Lead]] = select(Lead).where(Lead.business_id == business_id)

        if status is not None:
            stmt = stmt.where(Lead.status == status)

        stmt = stmt.order_by(Lead.submitted_at.desc())
        return list(self.session.scalars(stmt))

    def list_recent_since(self, business_id: str, submitted_after: datetime) -> list[Lead]:
        stmt: Select[tuple[Lead]] = (
            select(Lead)
            .where(Lead.business_id == business_id)
            .where(Lead.submitted_at >= submitted_after)
            .order_by(Lead.submitted_at.desc())
        )
        return list(self.session.scalars(stmt))

    def list_submitted_between(self, business_id: str, start: datetime, end: datetime) -> list[Lead]:
        stmt: Select[tuple[Lead]] = (
            select(Lead)
            .where(Lead.business_id == business_id)
            .where(Lead.submitted_at >= start)
            .where(Lead.submitted_at <= end)
            .order_by(Lead.submitted_at.desc())
        )
        return list(self.session.scalars(stmt))

    def list_awaiting_first_response(self, business_id: str) -> list[Lead]:
        stmt: Select[tuple[Lead]] = (
            select(Lead)
            .where(Lead.business_id == business_id)
            .where(Lead.status == LeadStatus.NEW)
            .where(Lead.first_human_response_at.is_(None))
            .order_by(Lead.submitted_at.asc())
        )
        return list(self.session.scalars(stmt))

    def count_awaiting_first_response(self, business_id: str) -> int:
        stmt = (
            select(func.count(Lead.id))
            .where(Lead.business_id == business_id)
            .where(Lead.status == LeadStatus.NEW)
            .where(Lead.first_human_response_at.is_(None))
        )
        return int(self.session.scalar(stmt) or 0)

    def list_stale_new_leads(self, business_id: str, minutes: int) -> list[Lead]:
        cutoff = utc_now() - timedelta(minutes=minutes)
        stmt: Select[tuple[Lead]] = (
            select(Lead)
            .where(Lead.business_id == business_id)
            .where(Lead.status == LeadStatus.NEW)
            .where(Lead.first_human_response_at.is_(None))
            .where(Lead.submitted_at < cutoff)
            .order_by(Lead.submitted_at.asc())
        )
        return list(self.session.scalars(stmt))

    def count_stale_new_leads(self, business_id: str, minutes: int) -> int:
        cutoff = utc_now() - timedelta(minutes=minutes)
        stmt = (
            select(func.count(Lead.id))
            .where(Lead.business_id == business_id)
            .where(Lead.status == LeadStatus.NEW)
            .where(Lead.first_human_response_at.is_(None))
            .where(Lead.submitted_at < cutoff)
        )
        return int(self.session.scalar(stmt) or 0)

    def add_event(self, event: LeadEvent) -> LeadEvent:
        lead_business_id = self.session.scalar(select(Lead.business_id).where(Lead.id == event.lead_id))
        if not lead_business_id:
            raise ValueError(f"Lead not found for event: {event.lead_id}")

        if not getattr(event, "business_id", None):
            event.business_id = lead_business_id
        elif event.business_id != lead_business_id:
            raise ValueError(
                "Event business_id does not match lead ownership: " f"{event.business_id} != {lead_business_id}"
            )

        self.session.add(event)
        self.session.flush()
        return event

    def list_events_for_lead(self, lead_id: str) -> list[LeadEvent]:
        stmt: Select[tuple[LeadEvent]] = (
            select(LeadEvent)
            .where(LeadEvent.lead_id == lead_id)
            .order_by(LeadEvent.event_timestamp.asc(), LeadEvent.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_events_for_business_lead(self, business_id: str, lead_id: str) -> list[LeadEvent]:
        stmt: Select[tuple[LeadEvent]] = (
            select(LeadEvent)
            .where(LeadEvent.business_id == business_id)
            .where(LeadEvent.lead_id == lead_id)
            .order_by(LeadEvent.event_timestamp.asc(), LeadEvent.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_events_for_business(
        self,
        business_id: str,
        lead_ids: Iterable[str] | None = None,
        event_types: Iterable[str] | None = None,
    ) -> list[LeadEvent]:
        stmt: Select[tuple[LeadEvent]] = select(LeadEvent).where(LeadEvent.business_id == business_id)

        if lead_ids is not None:
            lead_id_list = list(lead_ids)
            if not lead_id_list:
                return []
            stmt = stmt.where(LeadEvent.lead_id.in_(lead_id_list))

        if event_types is not None:
            event_type_list = list(event_types)
            if not event_type_list:
                return []
            stmt = stmt.where(LeadEvent.event_type.in_(event_type_list))

        stmt = stmt.order_by(LeadEvent.lead_id.asc(), LeadEvent.event_timestamp.asc(), LeadEvent.id.asc())
        return list(self.session.scalars(stmt))

    def list_events_for_leads(
        self,
        lead_ids: Iterable[str],
        event_types: Iterable[str] | None = None,
        business_id: str | None = None,
    ) -> list[LeadEvent]:
        lead_id_list = list(lead_ids)
        if not lead_id_list:
            return []

        stmt: Select[tuple[LeadEvent]] = select(LeadEvent).where(LeadEvent.lead_id.in_(lead_id_list))
        if business_id is not None:
            stmt = stmt.where(LeadEvent.business_id == business_id)
        if event_types is not None:
            event_type_list = list(event_types)
            if not event_type_list:
                return []
            stmt = stmt.where(LeadEvent.event_type.in_(event_type_list))

        stmt = stmt.order_by(LeadEvent.lead_id.asc(), LeadEvent.event_timestamp.asc(), LeadEvent.id.asc())
        return list(self.session.scalars(stmt))

    def status_counts(self, business_id: str, start: datetime, end: datetime) -> dict[str, int]:
        stmt = (
            select(Lead.status, func.count(Lead.id))
            .where(Lead.business_id == business_id)
            .where(Lead.submitted_at >= start)
            .where(Lead.submitted_at <= end)
            .group_by(Lead.status)
        )

        rows = self.session.execute(stmt).all()
        return {str(status.value): int(count) for status, count in rows}

    def response_deltas_minutes(self, business_id: str, start: datetime, end: datetime) -> list[float]:
        leads = self.session.scalars(
            select(Lead)
            .where(Lead.business_id == business_id)
            .where(Lead.submitted_at >= start)
            .where(Lead.submitted_at <= end)
            .where(Lead.first_human_response_at.is_not(None))
        ).all()

        deltas: list[float] = []
        for lead in leads:
            diff_seconds = (lead.first_human_response_at - lead.submitted_at).total_seconds()  # type: ignore[arg-type]
            deltas.append(max(diff_seconds / 60.0, 0.0))

        return deltas

    def count_uncontacted_older_than_minutes(self, business_id: str, minutes: int) -> int:
        cutoff = utc_now() - timedelta(minutes=minutes)
        stmt = (
            select(func.count(Lead.id))
            .where(Lead.business_id == business_id)
            .where(Lead.status == LeadStatus.NEW)
            .where(Lead.first_human_response_at.is_(None))
            .where(Lead.submitted_at < cutoff)
        )
        return int(self.session.scalar(stmt) or 0)

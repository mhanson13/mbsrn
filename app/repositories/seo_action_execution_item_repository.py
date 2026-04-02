from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_action_execution_item import SEOActionExecutionItem
from app.models.seo_site import SEOSite
from app.schemas.action_chaining import NextActionDraft


class SEOActionExecutionItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_from_chained_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
        source_draft_id: str,
        draft: NextActionDraft,
        created_by_principal_id: str | None,
    ) -> SEOActionExecutionItem:
        site = self.session.scalar(
            select(SEOSite.id).where(SEOSite.business_id == business_id).where(SEOSite.id == site_id)
        )
        if site is None:
            raise ValueError("SEO site not found for business")

        record = SEOActionExecutionItem(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
            source_draft_id=source_draft_id,
            source="chained",
            action_type=draft.action_type,
            title=draft.title,
            description=draft.description,
            priority=draft.priority,
            state="pending",
            automation_ready=bool(draft.automation_ready),
            automation_template_key=draft.automation_template_key,
            metadata_json=draft.metadata or {},
            created_by_principal_id=created_by_principal_id,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get_for_business_site_source_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        source_draft_id: str,
    ) -> SEOActionExecutionItem | None:
        stmt: Select[tuple[SEOActionExecutionItem]] = (
            select(SEOActionExecutionItem)
            .where(SEOActionExecutionItem.business_id == business_id)
            .where(SEOActionExecutionItem.site_id == site_id)
            .where(SEOActionExecutionItem.source_draft_id == source_draft_id)
        )
        return self.session.scalar(stmt)

    def get_for_business_site_id(
        self,
        *,
        business_id: str,
        site_id: str,
        action_id: str,
    ) -> SEOActionExecutionItem | None:
        stmt: Select[tuple[SEOActionExecutionItem]] = (
            select(SEOActionExecutionItem)
            .where(SEOActionExecutionItem.business_id == business_id)
            .where(SEOActionExecutionItem.site_id == site_id)
            .where(SEOActionExecutionItem.id == action_id)
        )
        return self.session.scalar(stmt)

    def list_for_business_site_source_action(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
    ) -> list[SEOActionExecutionItem]:
        stmt: Select[tuple[SEOActionExecutionItem]] = (
            select(SEOActionExecutionItem)
            .where(SEOActionExecutionItem.business_id == business_id)
            .where(SEOActionExecutionItem.site_id == site_id)
            .where(SEOActionExecutionItem.source_action_id == source_action_id)
            .order_by(SEOActionExecutionItem.created_at.asc(), SEOActionExecutionItem.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_for_business_site_source_action_ids(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_ids: list[str],
    ) -> list[SEOActionExecutionItem]:
        normalized_ids = [source_action_id for source_action_id in source_action_ids if source_action_id]
        if not normalized_ids:
            return []
        stmt: Select[tuple[SEOActionExecutionItem]] = (
            select(SEOActionExecutionItem)
            .where(SEOActionExecutionItem.business_id == business_id)
            .where(SEOActionExecutionItem.site_id == site_id)
            .where(SEOActionExecutionItem.source_action_id.in_(normalized_ids))
            .order_by(
                SEOActionExecutionItem.source_action_id.asc(),
                SEOActionExecutionItem.created_at.asc(),
                SEOActionExecutionItem.id.asc(),
            )
        )
        return list(self.session.scalars(stmt))

    def list_for_business_site_source_draft_ids(
        self,
        *,
        business_id: str,
        site_id: str,
        source_draft_ids: list[str],
    ) -> list[SEOActionExecutionItem]:
        normalized_ids = [draft_id for draft_id in source_draft_ids if draft_id]
        if not normalized_ids:
            return []
        stmt: Select[tuple[SEOActionExecutionItem]] = (
            select(SEOActionExecutionItem)
            .where(SEOActionExecutionItem.business_id == business_id)
            .where(SEOActionExecutionItem.site_id == site_id)
            .where(SEOActionExecutionItem.source_draft_id.in_(normalized_ids))
            .order_by(SEOActionExecutionItem.created_at.asc(), SEOActionExecutionItem.id.asc())
        )
        return list(self.session.scalars(stmt))

    def save(self, record: SEOActionExecutionItem) -> SEOActionExecutionItem:
        self.session.add(record)
        self.session.flush()
        return record

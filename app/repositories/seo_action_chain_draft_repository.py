from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_action_chain_draft import SEOActionChainDraft
from app.models.seo_site import SEOSite
from app.schemas.action_chaining import NextActionDraft


class SEOActionChainDraftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_if_missing(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
        draft: NextActionDraft,
    ) -> tuple[SEOActionChainDraft, bool]:
        site = self.session.scalar(
            select(SEOSite.id).where(SEOSite.business_id == business_id).where(SEOSite.id == site_id)
        )
        if site is None:
            raise ValueError("SEO site not found for business")

        existing = self.get_for_business_site_source_action_type(
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
            action_type=draft.action_type,
        )
        if existing is not None:
            return existing, False

        record = SEOActionChainDraft(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
            action_type=draft.action_type,
            title=draft.title,
            description=draft.description,
            priority=draft.priority,
            state="pending",
            activation_state="pending",
            activated_action_id=None,
            automation_template_key=draft.automation_template_key,
            automation_ready=bool(draft.automation_ready),
            metadata_json=draft.metadata or {},
        )
        self.session.add(record)
        self.session.flush()
        return record, True

    def get_for_business_site_source_action_type(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
        action_type: str,
    ) -> SEOActionChainDraft | None:
        stmt: Select[tuple[SEOActionChainDraft]] = (
            select(SEOActionChainDraft)
            .where(SEOActionChainDraft.business_id == business_id)
            .where(SEOActionChainDraft.site_id == site_id)
            .where(SEOActionChainDraft.source_action_id == source_action_id)
            .where(SEOActionChainDraft.action_type == action_type)
        )
        return self.session.scalar(stmt)

    def list_for_business_site_source_action(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
    ) -> list[SEOActionChainDraft]:
        stmt: Select[tuple[SEOActionChainDraft]] = (
            select(SEOActionChainDraft)
            .where(SEOActionChainDraft.business_id == business_id)
            .where(SEOActionChainDraft.site_id == site_id)
            .where(SEOActionChainDraft.source_action_id == source_action_id)
            .order_by(SEOActionChainDraft.created_at.asc(), SEOActionChainDraft.id.asc())
        )
        return list(self.session.scalars(stmt))

    def get_for_business_site_source_action_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
        draft_id: str,
    ) -> SEOActionChainDraft | None:
        stmt: Select[tuple[SEOActionChainDraft]] = (
            select(SEOActionChainDraft)
            .where(SEOActionChainDraft.business_id == business_id)
            .where(SEOActionChainDraft.site_id == site_id)
            .where(SEOActionChainDraft.source_action_id == source_action_id)
            .where(SEOActionChainDraft.id == draft_id)
        )
        return self.session.scalar(stmt)

    def save(self, record: SEOActionChainDraft) -> SEOActionChainDraft:
        self.session.add(record)
        self.session.flush()
        return record

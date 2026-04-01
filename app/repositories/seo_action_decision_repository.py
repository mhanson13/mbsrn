from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_action_decision import SEOActionDecision
from app.models.seo_site import SEOSite


class SEOActionDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_decision(
        self,
        *,
        business_id: str,
        site_id: str,
        action_id: str,
        decision: str,
    ) -> SEOActionDecision:
        site = self.session.scalar(
            select(SEOSite.id).where(SEOSite.business_id == business_id).where(SEOSite.id == site_id)
        )
        if site is None:
            raise ValueError("SEO site not found for business")

        record = self.get_for_business_site_action_id(
            business_id=business_id,
            site_id=site_id,
            action_id=action_id,
        )
        if record is None:
            record = SEOActionDecision(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                action_id=action_id,
                decision=decision,
            )
        else:
            record.decision = decision
        self.session.add(record)
        self.session.flush()
        return record

    def get_for_business_site_action_id(
        self,
        *,
        business_id: str,
        site_id: str,
        action_id: str,
    ) -> SEOActionDecision | None:
        stmt: Select[tuple[SEOActionDecision]] = (
            select(SEOActionDecision)
            .where(SEOActionDecision.business_id == business_id)
            .where(SEOActionDecision.site_id == site_id)
            .where(SEOActionDecision.action_id == action_id)
        )
        return self.session.scalar(stmt)

    def list_for_business_site_action_ids(
        self,
        *,
        business_id: str,
        site_id: str,
        action_ids: list[str],
    ) -> list[SEOActionDecision]:
        normalized_action_ids = [item for item in action_ids if item]
        if not normalized_action_ids:
            return []
        stmt: Select[tuple[SEOActionDecision]] = (
            select(SEOActionDecision)
            .where(SEOActionDecision.business_id == business_id)
            .where(SEOActionDecision.site_id == site_id)
            .where(SEOActionDecision.action_id.in_(normalized_action_ids))
        )
        return list(self.session.scalars(stmt))

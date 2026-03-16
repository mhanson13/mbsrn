from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_site import SEOSite


class SEOSiteRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, site: SEOSite) -> SEOSite:
        self.session.add(site)
        self.session.flush()
        return site

    def get_for_business(self, business_id: str, site_id: str) -> SEOSite | None:
        stmt: Select[tuple[SEOSite]] = (
            select(SEOSite).where(SEOSite.business_id == business_id).where(SEOSite.id == site_id)
        )
        return self.session.scalar(stmt)

    def get_for_business_domain(self, business_id: str, normalized_domain: str) -> SEOSite | None:
        stmt: Select[tuple[SEOSite]] = (
            select(SEOSite)
            .where(SEOSite.business_id == business_id)
            .where(SEOSite.normalized_domain == normalized_domain)
        )
        return self.session.scalar(stmt)

    def list_for_business(self, business_id: str) -> list[SEOSite]:
        stmt: Select[tuple[SEOSite]] = (
            select(SEOSite)
            .where(SEOSite.business_id == business_id)
            .order_by(SEOSite.is_primary.desc(), SEOSite.display_name.asc())
        )
        return list(self.session.scalars(stmt))

    def clear_primary_for_business(self, business_id: str) -> None:
        sites = self.list_for_business(business_id)
        for site in sites:
            if site.is_primary:
                site.is_primary = False
        self.session.flush()

    def save(self, site: SEOSite) -> SEOSite:
        self.session.add(site)
        self.session.flush()
        return site

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_site import SEOSite


class SEOAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(self, run: SEOAuditRun) -> SEOAuditRun:
        site = self.session.scalar(
            select(SEOSite.id).where(SEOSite.business_id == run.business_id).where(SEOSite.id == run.site_id)
        )
        if site is None:
            raise ValueError("Site not found for business")

        self.session.add(run)
        self.session.flush()
        return run

    def save_run(self, run: SEOAuditRun) -> SEOAuditRun:
        self.session.add(run)
        self.session.flush()
        return run

    def get_run_for_business(self, business_id: str, run_id: str) -> SEOAuditRun | None:
        stmt: Select[tuple[SEOAuditRun]] = (
            select(SEOAuditRun).where(SEOAuditRun.business_id == business_id).where(SEOAuditRun.id == run_id)
        )
        return self.session.scalar(stmt)

    def get_latest_completed_run_for_business_site(self, business_id: str, site_id: str) -> SEOAuditRun | None:
        stmt: Select[tuple[SEOAuditRun]] = (
            select(SEOAuditRun)
            .where(SEOAuditRun.business_id == business_id)
            .where(SEOAuditRun.site_id == site_id)
            .where(SEOAuditRun.status == "completed")
            .order_by(SEOAuditRun.completed_at.desc().nullslast(), SEOAuditRun.created_at.desc())
        )
        return self.session.scalar(stmt)

    def list_runs_for_business_site(self, business_id: str, site_id: str) -> list[SEOAuditRun]:
        stmt: Select[tuple[SEOAuditRun]] = (
            select(SEOAuditRun)
            .where(SEOAuditRun.business_id == business_id)
            .where(SEOAuditRun.site_id == site_id)
            .order_by(SEOAuditRun.created_at.desc())
        )
        return list(self.session.scalars(stmt))

    def add_page(self, page: SEOAuditPage) -> SEOAuditPage:
        run = self.session.scalar(select(SEOAuditRun).where(SEOAuditRun.id == page.audit_run_id))
        if run is None:
            raise ValueError("Audit run not found")
        if run.business_id != page.business_id or run.site_id != page.site_id:
            raise ValueError("Audit page scope mismatch")

        self.session.add(page)
        self.session.flush()
        return page

    def list_pages_for_business_run(self, business_id: str, run_id: str) -> list[SEOAuditPage]:
        stmt: Select[tuple[SEOAuditPage]] = (
            select(SEOAuditPage)
            .where(SEOAuditPage.business_id == business_id)
            .where(SEOAuditPage.audit_run_id == run_id)
            .order_by(SEOAuditPage.url.asc())
        )
        return list(self.session.scalars(stmt))

    def add_finding(self, finding: SEOAuditFinding) -> SEOAuditFinding:
        run = self.session.scalar(select(SEOAuditRun).where(SEOAuditRun.id == finding.audit_run_id))
        if run is None:
            raise ValueError("Audit run not found")
        if run.business_id != finding.business_id or run.site_id != finding.site_id:
            raise ValueError("Audit finding scope mismatch")

        if finding.page_id is not None:
            page = self.session.scalar(select(SEOAuditPage).where(SEOAuditPage.id == finding.page_id))
            if page is None:
                raise ValueError("Audit page not found")
            if page.audit_run_id != finding.audit_run_id or page.business_id != finding.business_id:
                raise ValueError("Audit finding page scope mismatch")

        self.session.add(finding)
        self.session.flush()
        return finding

    def list_findings_for_business_run(self, business_id: str, run_id: str) -> list[SEOAuditFinding]:
        stmt: Select[tuple[SEOAuditFinding]] = (
            select(SEOAuditFinding)
            .where(SEOAuditFinding.business_id == business_id)
            .where(SEOAuditFinding.audit_run_id == run_id)
            .order_by(SEOAuditFinding.created_at.asc(), SEOAuditFinding.id.asc())
        )
        return list(self.session.scalars(stmt))

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.models.seo_site import SEOSite


class SEOCompetitorRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_set(self, competitor_set: SEOCompetitorSet) -> SEOCompetitorSet:
        site = self.session.scalar(
            select(SEOSite.id)
            .where(SEOSite.business_id == competitor_set.business_id)
            .where(SEOSite.id == competitor_set.site_id)
        )
        if site is None:
            raise ValueError("SEO site not found for business")
        self.session.add(competitor_set)
        self.session.flush()
        return competitor_set

    def save_set(self, competitor_set: SEOCompetitorSet) -> SEOCompetitorSet:
        self.session.add(competitor_set)
        self.session.flush()
        return competitor_set

    def get_set_for_business(self, business_id: str, competitor_set_id: str) -> SEOCompetitorSet | None:
        stmt: Select[tuple[SEOCompetitorSet]] = (
            select(SEOCompetitorSet)
            .where(SEOCompetitorSet.business_id == business_id)
            .where(SEOCompetitorSet.id == competitor_set_id)
        )
        return self.session.scalar(stmt)

    def list_sets_for_business_site(self, business_id: str, site_id: str) -> list[SEOCompetitorSet]:
        stmt: Select[tuple[SEOCompetitorSet]] = (
            select(SEOCompetitorSet)
            .where(SEOCompetitorSet.business_id == business_id)
            .where(SEOCompetitorSet.site_id == site_id)
            .order_by(SEOCompetitorSet.created_at.desc(), SEOCompetitorSet.id.desc())
        )
        return list(self.session.scalars(stmt))

    def create_domain(self, competitor_domain: SEOCompetitorDomain) -> SEOCompetitorDomain:
        competitor_set = self.session.scalar(
            select(SEOCompetitorSet).where(SEOCompetitorSet.id == competitor_domain.competitor_set_id)
        )
        if competitor_set is None:
            raise ValueError("Competitor set not found")
        if (
            competitor_set.business_id != competitor_domain.business_id
            or competitor_set.site_id != competitor_domain.site_id
        ):
            raise ValueError("Competitor domain scope mismatch")

        self.session.add(competitor_domain)
        self.session.flush()
        return competitor_domain

    def save_domain(self, competitor_domain: SEOCompetitorDomain) -> SEOCompetitorDomain:
        self.session.add(competitor_domain)
        self.session.flush()
        return competitor_domain

    def get_domain_for_business(
        self,
        business_id: str,
        competitor_set_id: str,
        domain_id: str,
    ) -> SEOCompetitorDomain | None:
        stmt: Select[tuple[SEOCompetitorDomain]] = (
            select(SEOCompetitorDomain)
            .where(SEOCompetitorDomain.business_id == business_id)
            .where(SEOCompetitorDomain.competitor_set_id == competitor_set_id)
            .where(SEOCompetitorDomain.id == domain_id)
        )
        return self.session.scalar(stmt)

    def list_domains_for_business_set(self, business_id: str, competitor_set_id: str) -> list[SEOCompetitorDomain]:
        stmt: Select[tuple[SEOCompetitorDomain]] = (
            select(SEOCompetitorDomain)
            .where(SEOCompetitorDomain.business_id == business_id)
            .where(SEOCompetitorDomain.competitor_set_id == competitor_set_id)
            .order_by(SEOCompetitorDomain.created_at.asc(), SEOCompetitorDomain.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_domains_for_business_site(self, business_id: str, site_id: str) -> list[SEOCompetitorDomain]:
        stmt: Select[tuple[SEOCompetitorDomain]] = (
            select(SEOCompetitorDomain)
            .where(SEOCompetitorDomain.business_id == business_id)
            .where(SEOCompetitorDomain.site_id == site_id)
            .order_by(SEOCompetitorDomain.created_at.asc(), SEOCompetitorDomain.id.asc())
        )
        return list(self.session.scalars(stmt))

    def get_domain_for_business_site_domain(
        self,
        business_id: str,
        site_id: str,
        domain: str,
    ) -> SEOCompetitorDomain | None:
        stmt: Select[tuple[SEOCompetitorDomain]] = (
            select(SEOCompetitorDomain)
            .where(SEOCompetitorDomain.business_id == business_id)
            .where(SEOCompetitorDomain.site_id == site_id)
            .where(SEOCompetitorDomain.domain == domain)
            .limit(1)
        )
        return self.session.scalar(stmt)

    def count_active_domains_for_set(self, business_id: str, competitor_set_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(SEOCompetitorDomain)
            .where(SEOCompetitorDomain.business_id == business_id)
            .where(SEOCompetitorDomain.competitor_set_id == competitor_set_id)
            .where(SEOCompetitorDomain.is_active.is_(True))
        )
        return int(self.session.scalar(stmt) or 0)

    def count_active_verified_domains_for_set(self, business_id: str, competitor_set_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(SEOCompetitorDomain)
            .where(SEOCompetitorDomain.business_id == business_id)
            .where(SEOCompetitorDomain.competitor_set_id == competitor_set_id)
            .where(SEOCompetitorDomain.is_active.is_(True))
            .where(SEOCompetitorDomain.verification_status == "verified")
        )
        return int(self.session.scalar(stmt) or 0)

    def delete_domain(self, competitor_domain: SEOCompetitorDomain) -> None:
        self.session.delete(competitor_domain)
        self.session.flush()

    def create_snapshot_run(self, snapshot_run: SEOCompetitorSnapshotRun) -> SEOCompetitorSnapshotRun:
        competitor_set = self.session.scalar(
            select(SEOCompetitorSet).where(SEOCompetitorSet.id == snapshot_run.competitor_set_id)
        )
        if competitor_set is None:
            raise ValueError("Competitor set not found")
        if competitor_set.business_id != snapshot_run.business_id or competitor_set.site_id != snapshot_run.site_id:
            raise ValueError("Competitor snapshot run scope mismatch")

        if snapshot_run.client_audit_run_id is not None:
            client_run = self.session.scalar(
                select(SEOAuditRun).where(SEOAuditRun.id == snapshot_run.client_audit_run_id)
            )
            if client_run is None:
                raise ValueError("Client audit run not found")
            if client_run.business_id != snapshot_run.business_id or client_run.site_id != snapshot_run.site_id:
                raise ValueError("Client audit run scope mismatch")

        self.session.add(snapshot_run)
        self.session.flush()
        return snapshot_run

    def save_snapshot_run(self, snapshot_run: SEOCompetitorSnapshotRun) -> SEOCompetitorSnapshotRun:
        self.session.add(snapshot_run)
        self.session.flush()
        return snapshot_run

    def get_snapshot_run_for_business(self, business_id: str, snapshot_run_id: str) -> SEOCompetitorSnapshotRun | None:
        stmt: Select[tuple[SEOCompetitorSnapshotRun]] = (
            select(SEOCompetitorSnapshotRun)
            .where(SEOCompetitorSnapshotRun.business_id == business_id)
            .where(SEOCompetitorSnapshotRun.id == snapshot_run_id)
        )
        return self.session.scalar(stmt)

    def list_snapshot_runs_for_business_set(
        self,
        business_id: str,
        competitor_set_id: str,
    ) -> list[SEOCompetitorSnapshotRun]:
        stmt: Select[tuple[SEOCompetitorSnapshotRun]] = (
            select(SEOCompetitorSnapshotRun)
            .where(SEOCompetitorSnapshotRun.business_id == business_id)
            .where(SEOCompetitorSnapshotRun.competitor_set_id == competitor_set_id)
            .order_by(SEOCompetitorSnapshotRun.created_at.desc(), SEOCompetitorSnapshotRun.id.desc())
        )
        return list(self.session.scalars(stmt))

    def create_snapshot_page(self, snapshot_page: SEOCompetitorSnapshotPage) -> SEOCompetitorSnapshotPage:
        snapshot_run = self.session.scalar(
            select(SEOCompetitorSnapshotRun).where(SEOCompetitorSnapshotRun.id == snapshot_page.snapshot_run_id)
        )
        if snapshot_run is None:
            raise ValueError("Snapshot run not found")
        domain = self.session.scalar(
            select(SEOCompetitorDomain).where(SEOCompetitorDomain.id == snapshot_page.competitor_domain_id)
        )
        if domain is None:
            raise ValueError("Competitor domain not found")

        if (
            snapshot_run.business_id != snapshot_page.business_id
            or snapshot_run.site_id != snapshot_page.site_id
            or snapshot_run.competitor_set_id != snapshot_page.competitor_set_id
        ):
            raise ValueError("Snapshot page run scope mismatch")
        if (
            domain.business_id != snapshot_page.business_id
            or domain.site_id != snapshot_page.site_id
            or domain.competitor_set_id != snapshot_page.competitor_set_id
        ):
            raise ValueError("Snapshot page domain scope mismatch")

        self.session.add(snapshot_page)
        self.session.flush()
        return snapshot_page

    def list_snapshot_pages_for_business_run(
        self, business_id: str, snapshot_run_id: str
    ) -> list[SEOCompetitorSnapshotPage]:
        stmt: Select[tuple[SEOCompetitorSnapshotPage]] = (
            select(SEOCompetitorSnapshotPage)
            .where(SEOCompetitorSnapshotPage.business_id == business_id)
            .where(SEOCompetitorSnapshotPage.snapshot_run_id == snapshot_run_id)
            .order_by(SEOCompetitorSnapshotPage.url.asc())
        )
        return list(self.session.scalars(stmt))

    def create_comparison_run(self, comparison_run: SEOCompetitorComparisonRun) -> SEOCompetitorComparisonRun:
        competitor_set = self.session.scalar(
            select(SEOCompetitorSet).where(SEOCompetitorSet.id == comparison_run.competitor_set_id)
        )
        if competitor_set is None:
            raise ValueError("Competitor set not found")
        if competitor_set.business_id != comparison_run.business_id or competitor_set.site_id != comparison_run.site_id:
            raise ValueError("Comparison run set scope mismatch")

        snapshot_run = self.session.scalar(
            select(SEOCompetitorSnapshotRun).where(SEOCompetitorSnapshotRun.id == comparison_run.snapshot_run_id)
        )
        if snapshot_run is None:
            raise ValueError("Snapshot run not found")
        if (
            snapshot_run.business_id != comparison_run.business_id
            or snapshot_run.site_id != comparison_run.site_id
            or snapshot_run.competitor_set_id != comparison_run.competitor_set_id
        ):
            raise ValueError("Comparison run snapshot scope mismatch")

        if comparison_run.baseline_audit_run_id is not None:
            audit_run = self.session.scalar(
                select(SEOAuditRun).where(SEOAuditRun.id == comparison_run.baseline_audit_run_id)
            )
            if audit_run is None:
                raise ValueError("Baseline audit run not found")
            if audit_run.business_id != comparison_run.business_id or audit_run.site_id != comparison_run.site_id:
                raise ValueError("Baseline audit run scope mismatch")

        self.session.add(comparison_run)
        self.session.flush()
        return comparison_run

    def save_comparison_run(self, comparison_run: SEOCompetitorComparisonRun) -> SEOCompetitorComparisonRun:
        self.session.add(comparison_run)
        self.session.flush()
        return comparison_run

    def get_comparison_run_for_business(
        self, business_id: str, comparison_run_id: str
    ) -> SEOCompetitorComparisonRun | None:
        stmt: Select[tuple[SEOCompetitorComparisonRun]] = (
            select(SEOCompetitorComparisonRun)
            .where(SEOCompetitorComparisonRun.business_id == business_id)
            .where(SEOCompetitorComparisonRun.id == comparison_run_id)
        )
        return self.session.scalar(stmt)

    def list_comparison_runs_for_business_set(
        self,
        business_id: str,
        competitor_set_id: str,
    ) -> list[SEOCompetitorComparisonRun]:
        stmt: Select[tuple[SEOCompetitorComparisonRun]] = (
            select(SEOCompetitorComparisonRun)
            .where(SEOCompetitorComparisonRun.business_id == business_id)
            .where(SEOCompetitorComparisonRun.competitor_set_id == competitor_set_id)
            .order_by(SEOCompetitorComparisonRun.created_at.desc(), SEOCompetitorComparisonRun.id.desc())
        )
        return list(self.session.scalars(stmt))

    def list_comparison_runs_for_business_site(
        self,
        business_id: str,
        site_id: str,
    ) -> list[SEOCompetitorComparisonRun]:
        stmt: Select[tuple[SEOCompetitorComparisonRun]] = (
            select(SEOCompetitorComparisonRun)
            .where(SEOCompetitorComparisonRun.business_id == business_id)
            .where(SEOCompetitorComparisonRun.site_id == site_id)
            .order_by(SEOCompetitorComparisonRun.created_at.desc(), SEOCompetitorComparisonRun.id.desc())
        )
        return list(self.session.scalars(stmt))

    def add_comparison_finding(self, finding: SEOCompetitorComparisonFinding) -> SEOCompetitorComparisonFinding:
        comparison_run = self.session.scalar(
            select(SEOCompetitorComparisonRun).where(SEOCompetitorComparisonRun.id == finding.comparison_run_id)
        )
        if comparison_run is None:
            raise ValueError("Comparison run not found")
        if (
            comparison_run.business_id != finding.business_id
            or comparison_run.site_id != finding.site_id
            or comparison_run.competitor_set_id != finding.competitor_set_id
        ):
            raise ValueError("Comparison finding scope mismatch")

        self.session.add(finding)
        self.session.flush()
        return finding

    def list_comparison_findings_for_business_run(
        self,
        business_id: str,
        comparison_run_id: str,
    ) -> list[SEOCompetitorComparisonFinding]:
        stmt: Select[tuple[SEOCompetitorComparisonFinding]] = (
            select(SEOCompetitorComparisonFinding)
            .where(SEOCompetitorComparisonFinding.business_id == business_id)
            .where(SEOCompetitorComparisonFinding.comparison_run_id == comparison_run_id)
            .order_by(
                SEOCompetitorComparisonFinding.created_at.asc(),
                SEOCompetitorComparisonFinding.id.asc(),
            )
        )
        return list(self.session.scalars(stmt))

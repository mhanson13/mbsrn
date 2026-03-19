from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.seo_automation_config import SEOAutomationConfig
from app.models.seo_automation_run import SEOAutomationRun
from app.models.seo_site import SEOSite


class SEOAutomationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_config(self, config: SEOAutomationConfig) -> SEOAutomationConfig:
        site_id = self.session.scalar(
            select(SEOSite.id).where(SEOSite.business_id == config.business_id).where(SEOSite.id == config.site_id)
        )
        if site_id is None:
            raise ValueError("SEO site not found for business")
        self.session.add(config)
        self.session.flush()
        return config

    def save_config(self, config: SEOAutomationConfig) -> SEOAutomationConfig:
        self.session.add(config)
        self.session.flush()
        return config

    def get_config_for_business_site(self, business_id: str, site_id: str) -> SEOAutomationConfig | None:
        stmt: Select[tuple[SEOAutomationConfig]] = (
            select(SEOAutomationConfig)
            .where(SEOAutomationConfig.business_id == business_id)
            .where(SEOAutomationConfig.site_id == site_id)
        )
        return self.session.scalar(stmt)

    def list_due_configs(
        self,
        *,
        now: datetime,
        limit: int,
        business_id: str | None = None,
    ) -> list[SEOAutomationConfig]:
        stmt: Select[tuple[SEOAutomationConfig]] = (
            select(SEOAutomationConfig)
            .where(SEOAutomationConfig.is_enabled.is_(True))
            .where(SEOAutomationConfig.next_run_at.is_not(None))
            .where(SEOAutomationConfig.next_run_at <= now)
            .order_by(SEOAutomationConfig.next_run_at.asc(), SEOAutomationConfig.created_at.asc())
        )
        if business_id is not None:
            stmt = stmt.where(SEOAutomationConfig.business_id == business_id)
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def create_run(self, run: SEOAutomationRun) -> SEOAutomationRun:
        config = self.session.scalar(
            select(SEOAutomationConfig).where(SEOAutomationConfig.id == run.automation_config_id)
        )
        if config is None:
            raise ValueError("SEO automation config not found")
        if config.business_id != run.business_id or config.site_id != run.site_id:
            raise ValueError("SEO automation run scope mismatch")

        self.session.add(run)
        self.session.flush()
        return run

    def save_run(self, run: SEOAutomationRun) -> SEOAutomationRun:
        self.session.add(run)
        self.session.flush()
        return run

    def get_run_for_business_site(
        self,
        business_id: str,
        site_id: str,
        automation_run_id: str,
    ) -> SEOAutomationRun | None:
        stmt: Select[tuple[SEOAutomationRun]] = (
            select(SEOAutomationRun)
            .where(SEOAutomationRun.business_id == business_id)
            .where(SEOAutomationRun.site_id == site_id)
            .where(SEOAutomationRun.id == automation_run_id)
        )
        return self.session.scalar(stmt)

    def list_runs_for_business_site(self, business_id: str, site_id: str) -> list[SEOAutomationRun]:
        stmt: Select[tuple[SEOAutomationRun]] = (
            select(SEOAutomationRun)
            .where(SEOAutomationRun.business_id == business_id)
            .where(SEOAutomationRun.site_id == site_id)
            .order_by(SEOAutomationRun.created_at.desc(), SEOAutomationRun.id.desc())
        )
        return list(self.session.scalars(stmt))

    def get_active_run_for_business_site(self, business_id: str, site_id: str) -> SEOAutomationRun | None:
        stmt: Select[tuple[SEOAutomationRun]] = (
            select(SEOAutomationRun)
            .where(SEOAutomationRun.business_id == business_id)
            .where(SEOAutomationRun.site_id == site_id)
            .where(SEOAutomationRun.status.in_(["queued", "running"]))
            .order_by(SEOAutomationRun.created_at.desc())
        )
        return self.session.scalar(stmt)

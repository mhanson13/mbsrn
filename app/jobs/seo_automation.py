from __future__ import annotations

from app.services.seo_automation import SEOAutomationDueRunSummary, SEOAutomationService


class SEOAutomationJob:
    """Scheduler-ready entry point for due SEO automation execution."""

    def __init__(self, automation_service: SEOAutomationService) -> None:
        self.automation_service = automation_service

    def run_due(self, *, limit: int = 25, business_id: str | None = None) -> SEOAutomationDueRunSummary:
        return self.automation_service.run_due_configs(limit=limit, business_id=business_id)

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SEOAuditRunCreateRequest(BaseModel):
    max_pages: int = Field(default=25, ge=1, le=100)
    max_depth: int = Field(default=2, ge=0, le=5)


class SEOAuditRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    max_pages: int
    max_depth: int
    pages_discovered: int
    pages_crawled: int
    pages_skipped: int
    errors_encountered: int
    duplicate_urls_skipped: int
    crawl_duration_ms: int | None
    error_summary: str | None
    created_by_principal_id: str | None
    created_at: datetime
    updated_at: datetime


class SEOAuditRunListResponse(BaseModel):
    items: list[SEOAuditRunRead]
    total: int


class SEOAuditFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    audit_run_id: str
    page_id: str | None
    finding_type: str
    category: str
    severity: str
    title: str
    details: str | None
    rule_key: str
    suggested_fix: str | None
    created_at: datetime


class SEOAuditFindingListResponse(BaseModel):
    items: list[SEOAuditFindingRead]
    total: int

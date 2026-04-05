from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SEOAnalyticsMetricWindowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current: int = 0
    previous: int = 0
    delta_absolute: int = 0
    delta_percent: float | None = None


class SEOAnalyticsSiteMetricsSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_period_start: date
    current_period_end: date
    previous_period_start: date
    previous_period_end: date
    users: SEOAnalyticsMetricWindowRead
    sessions: SEOAnalyticsMetricWindowRead
    pageviews: SEOAnalyticsMetricWindowRead
    organic_search_sessions: SEOAnalyticsMetricWindowRead


class SEOAnalyticsTopPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_path: str
    pageviews: int = 0
    sessions: int = 0
    pageviews_previous: int = 0
    sessions_previous: int = 0
    pageviews_delta_absolute: int = 0
    sessions_delta_absolute: int = 0
    pageviews_delta_percent: float | None = None
    sessions_delta_percent: float | None = None


class SEOAnalyticsSiteSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: str
    site_id: str
    available: bool
    status: str
    message: str | None = None
    data_source: str | None = None
    site_metrics_summary: SEOAnalyticsSiteMetricsSummaryRead | None = None
    top_pages_summary: list[SEOAnalyticsTopPageRead] = Field(default_factory=list)


class SEOGA4AccessibleAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    display_name: str
    property_count: int = 0


class SEOGA4AccessibleAccountsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: str
    site_id: str
    available: bool
    status: str
    message: str | None = None
    data_source: str | None = None
    accounts: list[SEOGA4AccessibleAccountRead] = Field(default_factory=list)


class SEOGA4SiteOnboardingStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: str
    site_id: str
    ga4_onboarding_status: str
    ga4_account_id: str | None = None
    ga4_property_id: str | None = None
    ga4_data_stream_id: str | None = None
    ga4_measurement_id: str | None = None
    account_discovery_available: bool = False
    discovered_account_count: int = 0
    auto_provisioning_eligible: bool = False
    message: str | None = None


class SEOSearchConsoleMetricWindowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current: int = 0
    previous: int = 0
    delta_absolute: int = 0
    delta_percent: float | None = None


class SEOSearchConsoleSiteMetricsSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_period_start: date
    current_period_end: date
    previous_period_start: date
    previous_period_end: date
    clicks: SEOSearchConsoleMetricWindowRead
    impressions: SEOSearchConsoleMetricWindowRead
    ctr_current: float = 0.0
    ctr_previous: float = 0.0
    ctr_delta_absolute: float = 0.0
    average_position_current: float = 0.0
    average_position_previous: float = 0.0
    average_position_delta_absolute: float = 0.0


class SEOSearchConsoleTopPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_path: str
    clicks: int = 0
    clicks_previous: int = 0
    clicks_delta_absolute: int = 0
    clicks_delta_percent: float | None = None
    impressions: int = 0
    impressions_previous: int = 0
    impressions_delta_absolute: int = 0
    impressions_delta_percent: float | None = None
    ctr: float = 0.0
    ctr_previous: float = 0.0
    ctr_delta_absolute: float = 0.0
    average_position: float = 0.0
    average_position_previous: float = 0.0
    average_position_delta_absolute: float = 0.0


class SEOSearchConsoleTopQueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    query: str
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    average_position: float = 0.0


class SEOSearchConsoleSiteSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: str
    site_id: str
    available: bool
    status: str
    diagnostic_status: str | None = None
    message: str | None = None
    data_source: str | None = None
    site_metrics_summary: SEOSearchConsoleSiteMetricsSummaryRead | None = None
    top_pages_summary: list[SEOSearchConsoleTopPageRead] = Field(default_factory=list)
    top_queries_summary: list[SEOSearchConsoleTopQueryRead] = Field(default_factory=list)

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

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


class SEOGA4HealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ga4_configured: bool = False
    ga4_property_id_present: bool = False
    ga4_property_verified: bool | None = None
    ga4_reachable: bool | None = None
    ga4_data_available: bool | None = None
    ga4_last_checked_at: datetime | None = None
    ga4_health_status: Literal[
        "configured",
        "not_configured",
        "reachable",
        "unavailable",
        "missing_oauth_scope",
        "permission_denied",
        "invalid_property",
        "no_data",
        "unknown",
    ] = "unknown"
    ga4_health_reason: str | None = None
    ga4_health_message: str | None = None
    ga4_health_source: Literal["site_property", "unavailable"] = "site_property"
    ga4_scope_granted: bool | None = None
    ga4_required_scope: str = "https://www.googleapis.com/auth/analytics.readonly"
    ga4_auth_mode: Literal["user_oauth", "service_account", "adc", "mock", "unavailable", "unknown"] = "unknown"


class SEOGA4TopLandingPageInsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    title: str | None = None
    sessions: int | None = None
    active_users: int | None = None
    views: int | None = None
    engagement_rate: float | None = None
    average_engagement_time_seconds: float | None = None
    trend_label: Literal["improving", "declining", "steady", "unknown"] = "unknown"
    operator_hint: str | None = None


class SEOGA4TrafficTrendInsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_sessions: int | None = None
    previous_sessions: int | None = None
    sessions_delta_percent: float | None = None
    current_active_users: int | None = None
    previous_active_users: int | None = None
    active_users_delta_percent: float | None = None
    trend_label: Literal["improving", "declining", "steady", "unknown"] = "unknown"
    operator_hint: str | None = None


class SEOGA4EngagementTrendInsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_engagement_rate: float | None = None
    previous_engagement_rate: float | None = None
    engagement_rate_delta_percent: float | None = None
    current_average_engagement_time_seconds: float | None = None
    previous_average_engagement_time_seconds: float | None = None
    trend_label: Literal["improving", "declining", "steady", "unknown"] = "unknown"
    operator_hint: str | None = None


class SEOGA4InsightsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal[
        "available",
        "not_configured",
        "missing_oauth_scope",
        "permission_denied",
        "invalid_property",
        "no_data",
        "unavailable",
        "unknown",
    ] = "unknown"
    source: Literal["site_property", "unavailable"] = "unavailable"
    date_range_label: str | None = None
    checked_at: datetime | None = None
    top_landing_pages: list[SEOGA4TopLandingPageInsightRead] = Field(default_factory=list)
    traffic_trend: SEOGA4TrafficTrendInsightRead | None = None
    engagement_trend: SEOGA4EngagementTrendInsightRead | None = None
    message: str | None = None


class SEOAnalyticsSiteSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: str
    site_id: str
    available: bool
    status: str
    ga4_status: Literal["not_configured", "configured", "connected", "error"] = "not_configured"
    ga4_error_reason: (
        Literal[
            "not_configured",
            "missing_oauth_scope",
            "permission_denied",
            "access_denied",
            "property_not_found",
            "invalid_property_format",
            "no_data",
            "unknown_error",
        ]
        | None
    ) = None
    ga4_last_successful_fetch_at: datetime | None = None
    ga4_last_data_timestamp: datetime | None = None
    ga4_data_freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    ga4_health: SEOGA4HealthRead = Field(default_factory=SEOGA4HealthRead)
    ga4_insights: SEOGA4InsightsRead = Field(default_factory=SEOGA4InsightsRead)
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
    sc_last_successful_fetch_at: datetime | None = None
    sc_last_data_timestamp: datetime | None = None
    sc_data_freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    message: str | None = None
    data_source: str | None = None
    site_metrics_summary: SEOSearchConsoleSiteMetricsSummaryRead | None = None
    top_pages_summary: list[SEOSearchConsoleTopPageRead] = Field(default_factory=list)
    top_queries_summary: list[SEOSearchConsoleTopQueryRead] = Field(default_factory=list)

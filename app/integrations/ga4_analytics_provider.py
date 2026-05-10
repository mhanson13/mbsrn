from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_GA4_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_DEFAULT_GA4_API_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
_DEFAULT_GA4_ADMIN_API_BASE_URL = "https://analyticsadmin.googleapis.com/v1beta"

logger = logging.getLogger(__name__)


class GA4AnalyticsProviderConfigurationError(ValueError):
    pass


class GA4AnalyticsProviderError(ValueError):
    pass


@dataclass(frozen=True)
class GA4SitePeriodMetrics:
    users: int
    sessions: int
    pageviews: int
    organic_search_sessions: int
    engagement_rate: float | None = None


@dataclass(frozen=True)
class GA4TopPageMetrics:
    page_path: str
    current_pageviews: int
    previous_pageviews: int
    current_sessions: int
    previous_sessions: int


@dataclass(frozen=True)
class GA4TopPagePeriodMetrics:
    page_path: str
    pageviews: int
    sessions: int


@dataclass(frozen=True)
class GA4TopLandingPageMetrics:
    page_path: str
    page_title: str | None
    sessions: int
    active_users: int
    views: int
    engagement_rate: float | None
    average_engagement_time_seconds: float | None


@dataclass(frozen=True)
class GA4AcquisitionChannelMetrics:
    channel_group: str
    sessions: int
    users: int | None
    engagement_rate: float | None


@dataclass(frozen=True)
class GA4AcquisitionSourceMetrics:
    source: str
    medium: str | None
    sessions: int
    users: int | None


@dataclass(frozen=True)
class GA4EngagementTrendMetrics:
    current_engagement_rate: float | None
    previous_engagement_rate: float | None
    current_average_engagement_time_seconds: float | None
    previous_average_engagement_time_seconds: float | None


@dataclass(frozen=True)
class GA4OperatorInsightsResult:
    top_landing_pages: tuple[GA4TopLandingPageMetrics, ...]
    engagement_trend: GA4EngagementTrendMetrics
    data_source: str
    acquisition_channels: tuple[GA4AcquisitionChannelMetrics, ...] = ()
    acquisition_sources: tuple[GA4AcquisitionSourceMetrics, ...] = ()
    acquisition_period_days: int | None = None


@dataclass(frozen=True)
class GA4AccountSummary:
    account_id: str
    display_name: str
    property_count: int


@dataclass(frozen=True)
class GA4SiteMetricsResult:
    current_period: GA4SitePeriodMetrics
    previous_period: GA4SitePeriodMetrics
    top_pages: tuple[GA4TopPageMetrics, ...]
    data_source: str


class GA4AnalyticsProvider(Protocol):
    def is_configured(self) -> bool: ...

    def fetch_account_summaries(self, *, page_size: int = 20) -> tuple[GA4AccountSummary, ...]: ...

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4SiteMetricsResult: ...

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
        ga4_property_id: str | None = None,
    ) -> GA4SitePeriodMetrics: ...

    def fetch_operator_insights(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_landing_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4OperatorInsightsResult: ...


class DisabledGA4AnalyticsProvider:
    def is_configured(self) -> bool:
        return False

    def fetch_account_summaries(self, *, page_size: int = 20) -> tuple[GA4AccountSummary, ...]:
        del page_size
        raise GA4AnalyticsProviderConfigurationError("GA4 analytics is not configured.")

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4SiteMetricsResult:
        del site_domain, period_days, top_pages_limit, ga4_property_id
        raise GA4AnalyticsProviderConfigurationError("GA4 analytics is not configured.")

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
        ga4_property_id: str | None = None,
    ) -> GA4SitePeriodMetrics:
        del site_domain, start_date, end_date, page_path, ga4_property_id
        raise GA4AnalyticsProviderConfigurationError("GA4 analytics is not configured.")

    def fetch_operator_insights(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_landing_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4OperatorInsightsResult:
        del site_domain, period_days, top_landing_pages_limit, ga4_property_id
        raise GA4AnalyticsProviderConfigurationError("GA4 analytics is not configured.")


class MockGA4AnalyticsProvider:
    def is_configured(self) -> bool:
        return True

    def fetch_account_summaries(self, *, page_size: int = 20) -> tuple[GA4AccountSummary, ...]:
        bounded = max(1, min(int(page_size), 5))
        mock_accounts = (
            GA4AccountSummary(
                account_id="1000000001",
                display_name="MBSRN Demo Account",
                property_count=2,
            ),
            GA4AccountSummary(
                account_id="1000000002",
                display_name="MBSRN Secondary Account",
                property_count=1,
            ),
        )
        return mock_accounts[:bounded]

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4SiteMetricsResult:
        del period_days, ga4_property_id
        normalized_domain = _normalize_domain(site_domain)
        seed = sum(ord(character) for character in normalized_domain) % 57
        current_users = 140 + seed
        current_sessions = 190 + (seed * 2)
        current_pageviews = 420 + (seed * 3)
        current_organic_sessions = max(0, int(current_sessions * 0.62))
        previous_users = max(0, current_users - 18)
        previous_sessions = max(0, current_sessions - 22)
        previous_pageviews = max(0, current_pageviews - 35)
        previous_organic_sessions = max(0, current_organic_sessions - 12)
        bounded_limit = max(1, min(int(top_pages_limit), 10))
        top_pages = tuple(
            GA4TopPageMetrics(
                page_path="/" if index == 0 else f"/services/{index}",
                current_pageviews=max(1, current_pageviews // (index + 2)),
                previous_pageviews=max(0, previous_pageviews // (index + 2)),
                current_sessions=max(1, current_sessions // (index + 2)),
                previous_sessions=max(0, previous_sessions // (index + 2)),
            )
            for index in range(bounded_limit)
        )
        return GA4SiteMetricsResult(
            current_period=GA4SitePeriodMetrics(
                users=current_users,
                sessions=current_sessions,
                pageviews=current_pageviews,
                organic_search_sessions=current_organic_sessions,
            ),
            previous_period=GA4SitePeriodMetrics(
                users=previous_users,
                sessions=previous_sessions,
                pageviews=previous_pageviews,
                organic_search_sessions=previous_organic_sessions,
            ),
            top_pages=top_pages,
            data_source="ga4_mock",
        )

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
        ga4_property_id: str | None = None,
    ) -> GA4SitePeriodMetrics:
        del ga4_property_id
        seed_components = (
            f"{_normalize_domain(site_domain)}|{start_date}|{end_date}|{(page_path or '').strip().lower()}"
        )
        seed = sum(ord(character) for character in seed_components) % 71
        base_sessions = 90 if page_path else 180
        sessions = max(0, base_sessions + seed)
        pageviews = max(0, sessions + 45 + (seed // 2))
        users = max(0, sessions - 35 + (seed // 3))
        organic_sessions = max(0, int(sessions * 0.62))
        return GA4SitePeriodMetrics(
            users=users,
            sessions=sessions,
            pageviews=pageviews,
            organic_search_sessions=organic_sessions,
            engagement_rate=round(max(0.12, min(0.9, 0.52 + ((seed % 6) * 0.01))), 4),
        )

    def fetch_operator_insights(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_landing_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4OperatorInsightsResult:
        del ga4_property_id
        normalized_domain = _normalize_domain(site_domain)
        seed = sum(ord(character) for character in normalized_domain) % 57
        bounded_limit = max(1, min(int(top_landing_pages_limit), 10))
        top_landing_pages = tuple(
            GA4TopLandingPageMetrics(
                page_path="/" if index == 0 else f"/services/{index}",
                page_title="Home" if index == 0 else f"Service Page {index}",
                sessions=max(1, (220 + seed) // (index + 1)),
                active_users=max(1, (170 + seed) // (index + 1)),
                views=max(1, (340 + seed) // (index + 1)),
                engagement_rate=round(max(0.12, min(0.9, 0.48 + ((seed % 9) * 0.03) - (index * 0.02))), 4),
                average_engagement_time_seconds=float(max(20, 110 - (index * 12) + (seed % 11))),
            )
            for index in range(bounded_limit)
        )
        engagement_trend = GA4EngagementTrendMetrics(
            current_engagement_rate=round(max(0.15, min(0.9, 0.57 + ((seed % 5) * 0.01))), 4),
            previous_engagement_rate=round(max(0.15, min(0.9, 0.53 + ((seed % 5) * 0.01))), 4),
            current_average_engagement_time_seconds=float(max(20, 86 + (seed % 15))),
            previous_average_engagement_time_seconds=float(max(20, 79 + (seed % 12))),
        )
        mock_channels = (
            GA4AcquisitionChannelMetrics(
                channel_group="Organic Search",
                sessions=max(1, 140 + seed),
                users=max(1, 122 + seed),
                engagement_rate=round(max(0.12, min(0.9, 0.58 + ((seed % 7) * 0.01))), 4),
            ),
            GA4AcquisitionChannelMetrics(
                channel_group="Direct",
                sessions=max(1, 80 + (seed // 2)),
                users=max(1, 68 + (seed // 2)),
                engagement_rate=round(max(0.12, min(0.9, 0.51 + ((seed % 5) * 0.01))), 4),
            ),
            GA4AcquisitionChannelMetrics(
                channel_group="Referral",
                sessions=max(1, 36 + (seed // 3)),
                users=max(1, 30 + (seed // 3)),
                engagement_rate=round(max(0.12, min(0.9, 0.47 + ((seed % 4) * 0.01))), 4),
            ),
        )
        mock_sources = (
            GA4AcquisitionSourceMetrics(
                source="google",
                medium="organic",
                sessions=max(1, 120 + seed),
                users=max(1, 104 + seed),
            ),
            GA4AcquisitionSourceMetrics(
                source="(direct)",
                medium="(none)",
                sessions=max(1, 80 + (seed // 2)),
                users=max(1, 68 + (seed // 2)),
            ),
            GA4AcquisitionSourceMetrics(
                source="yelp.com",
                medium="referral",
                sessions=max(1, 22 + (seed // 4)),
                users=max(1, 18 + (seed // 4)),
            ),
        )
        return GA4OperatorInsightsResult(
            top_landing_pages=top_landing_pages,
            engagement_trend=engagement_trend,
            data_source="ga4_mock",
            acquisition_channels=mock_channels[:bounded_limit],
            acquisition_sources=mock_sources[:bounded_limit],
            acquisition_period_days=max(1, min(int(period_days), 30)),
        )


class GoogleAnalyticsDataAPIClient:
    def __init__(
        self,
        *,
        property_id: str | None,
        timeout_seconds: int = 10,
        credentials_json: str | None = None,
        api_base_url: str = _DEFAULT_GA4_API_BASE_URL,
        ga_admin_api_base_url: str = _DEFAULT_GA4_ADMIN_API_BASE_URL,
    ) -> None:
        self.property_id = (property_id or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.credentials_json = (credentials_json or "").strip() or None
        self.api_base_url = (api_base_url or _DEFAULT_GA4_API_BASE_URL).rstrip("/")
        self.ga_admin_api_base_url = (ga_admin_api_base_url or _DEFAULT_GA4_ADMIN_API_BASE_URL).rstrip("/")
        self._credentials: Any | None = None
        self._auth_request: Any | None = None

    def is_configured(self) -> bool:
        # Per-site GA4 property scoping is supported on each request, so provider
        # availability does not depend on a global default property id.
        return True

    def fetch_account_summaries(self, *, page_size: int = 20) -> tuple[GA4AccountSummary, ...]:
        bounded_page_size = max(1, min(int(page_size), 200))
        account_summaries: list[GA4AccountSummary] = []
        seen_account_ids: set[str] = set()
        page_token: str | None = None
        max_pages = 5
        for _ in range(max_pages):
            endpoint = f"{self.ga_admin_api_base_url}/accountSummaries?pageSize={bounded_page_size}"
            if page_token:
                endpoint = f"{endpoint}&pageToken={page_token}"
            response_payload = self._request_json(url=endpoint, method="GET", body=None)
            summaries = response_payload.get("accountSummaries")
            if isinstance(summaries, list):
                for summary in summaries:
                    if not isinstance(summary, dict):
                        continue
                    account_resource = str(summary.get("account") or summary.get("name") or "").strip()
                    account_id = _parse_resource_id(account_resource, prefix="accounts")
                    if not account_id or account_id in seen_account_ids:
                        continue
                    seen_account_ids.add(account_id)
                    property_summaries = summary.get("propertySummaries")
                    property_count = len(property_summaries) if isinstance(property_summaries, list) else 0
                    display_name = str(summary.get("displayName") or "").strip() or f"Account {account_id}"
                    account_summaries.append(
                        GA4AccountSummary(
                            account_id=account_id,
                            display_name=display_name,
                            property_count=max(0, int(property_count)),
                        )
                    )
            next_page_token_raw = response_payload.get("nextPageToken")
            next_page_token = str(next_page_token_raw or "").strip()
            if not next_page_token:
                break
            page_token = next_page_token
        return tuple(account_summaries)

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4SiteMetricsResult:
        scoped_property_id = self._resolve_ga4_property_id(ga4_property_id)
        normalized_domain = _normalize_domain(site_domain)
        if not normalized_domain:
            raise GA4AnalyticsProviderConfigurationError("A normalized site domain is required for GA4 analytics.")

        bounded_period_days = max(1, min(int(period_days), 30))
        bounded_top_pages_limit = max(1, min(int(top_pages_limit), 10))
        current_start_offset = bounded_period_days - 1
        previous_end_offset = bounded_period_days
        previous_start_offset = (bounded_period_days * 2) - 1

        current_period = self._fetch_period_metrics(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            ga4_property_id=scoped_property_id,
        )
        previous_period = self._fetch_period_metrics(
            site_domain=normalized_domain,
            start_date=f"{previous_start_offset}daysAgo",
            end_date=f"{previous_end_offset}daysAgo",
            ga4_property_id=scoped_property_id,
        )
        current_top_pages = self._fetch_top_pages(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            limit=bounded_top_pages_limit,
            ga4_property_id=scoped_property_id,
        )
        previous_top_pages = self._fetch_top_pages(
            site_domain=normalized_domain,
            start_date=f"{previous_start_offset}daysAgo",
            end_date=f"{previous_end_offset}daysAgo",
            limit=bounded_top_pages_limit,
            ga4_property_id=scoped_property_id,
        )
        previous_top_pages_by_path = {item.page_path: item for item in previous_top_pages}
        merged_top_pages: list[GA4TopPageMetrics] = []
        for item in current_top_pages:
            previous_item = previous_top_pages_by_path.get(item.page_path)
            merged_top_pages.append(
                GA4TopPageMetrics(
                    page_path=item.page_path,
                    current_pageviews=item.pageviews,
                    previous_pageviews=(previous_item.pageviews if previous_item is not None else 0),
                    current_sessions=item.sessions,
                    previous_sessions=(previous_item.sessions if previous_item is not None else 0),
                )
            )
        top_pages: tuple[GA4TopPageMetrics, ...] = tuple(merged_top_pages)

        return GA4SiteMetricsResult(
            current_period=current_period,
            previous_period=previous_period,
            top_pages=top_pages,
            data_source="ga4",
        )

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
        ga4_property_id: str | None = None,
    ) -> GA4SitePeriodMetrics:
        scoped_property_id = self._resolve_ga4_property_id(ga4_property_id)
        normalized_domain = _normalize_domain(site_domain)
        if not normalized_domain:
            raise GA4AnalyticsProviderConfigurationError("A normalized site domain is required for GA4 analytics.")
        return self._fetch_period_metrics(
            site_domain=normalized_domain,
            start_date=start_date,
            end_date=end_date,
            page_path=page_path,
            ga4_property_id=scoped_property_id,
        )

    def fetch_operator_insights(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_landing_pages_limit: int,
        ga4_property_id: str | None = None,
    ) -> GA4OperatorInsightsResult:
        scoped_property_id = self._resolve_ga4_property_id(ga4_property_id)
        normalized_domain = _normalize_domain(site_domain)
        if not normalized_domain:
            raise GA4AnalyticsProviderConfigurationError("A normalized site domain is required for GA4 analytics.")

        bounded_period_days = max(1, min(int(period_days), 30))
        bounded_top_landing_limit = max(1, min(int(top_landing_pages_limit), 10))
        current_start_offset = bounded_period_days - 1
        previous_end_offset = bounded_period_days
        previous_start_offset = (bounded_period_days * 2) - 1

        top_landing_pages = self._fetch_operator_top_landing_pages(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            limit=bounded_top_landing_limit,
            ga4_property_id=scoped_property_id,
        )
        current_engagement_rate, current_avg_duration = self._fetch_operator_engagement_metrics(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            ga4_property_id=scoped_property_id,
        )
        previous_engagement_rate, previous_avg_duration = self._fetch_operator_engagement_metrics(
            site_domain=normalized_domain,
            start_date=f"{previous_start_offset}daysAgo",
            end_date=f"{previous_end_offset}daysAgo",
            ga4_property_id=scoped_property_id,
        )
        acquisition_channels = self._fetch_operator_acquisition_channels(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            limit=bounded_top_landing_limit,
            ga4_property_id=scoped_property_id,
        )
        acquisition_sources = self._fetch_operator_acquisition_sources(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            limit=bounded_top_landing_limit,
            ga4_property_id=scoped_property_id,
        )
        return GA4OperatorInsightsResult(
            top_landing_pages=tuple(top_landing_pages),
            engagement_trend=GA4EngagementTrendMetrics(
                current_engagement_rate=current_engagement_rate,
                previous_engagement_rate=previous_engagement_rate,
                current_average_engagement_time_seconds=current_avg_duration,
                previous_average_engagement_time_seconds=previous_avg_duration,
            ),
            data_source="ga4",
            acquisition_channels=tuple(acquisition_channels),
            acquisition_sources=tuple(acquisition_sources),
            acquisition_period_days=bounded_period_days,
        )

    def _fetch_period_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
        ga4_property_id: str,
    ) -> GA4SitePeriodMetrics:
        site_filter = self._build_site_filter(site_domain)
        page_filter = self._build_page_filter(page_path)
        period_filter = self._combine_dimension_filters(site_filter, page_filter)
        base_payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [
                {"name": "totalUsers"},
                {"name": "sessions"},
                {"name": "screenPageViews"},
                {"name": "engagementRate"},
            ],
            "dimensionFilter": period_filter,
        }
        metrics_response = self._request_report(
            body=base_payload,
            ga4_property_id=ga4_property_id,
        )
        row = _first_row(metrics_response)
        users = _metric_value(row, index=0)
        sessions = _metric_value(row, index=1)
        pageviews = _metric_value(row, index=2)
        engagement_rate = _metric_float_value(row, index=3)

        organic_filter_expressions: list[dict[str, Any]] = [site_filter]
        if page_filter is not None:
            organic_filter_expressions.append(page_filter)
        organic_filter_expressions.append(
            {
                "filter": {
                    "fieldName": "sessionDefaultChannelGroup",
                    "stringFilter": {
                        "matchType": "EXACT",
                        "value": "Organic Search",
                        "caseSensitive": False,
                    },
                }
            },
        )
        organic_payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": "sessions"}],
            "dimensionFilter": {"andGroup": {"expressions": organic_filter_expressions}},
        }
        organic_response = self._request_report(
            body=organic_payload,
            ga4_property_id=ga4_property_id,
        )
        organic_row = _first_row(organic_response)
        organic_sessions = _metric_value(organic_row, index=0)

        return GA4SitePeriodMetrics(
            users=users,
            sessions=sessions,
            pageviews=pageviews,
            organic_search_sessions=organic_sessions,
            engagement_rate=engagement_rate,
        )

    def _fetch_top_pages(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        limit: int,
        ga4_property_id: str,
    ) -> list[GA4TopPagePeriodMetrics]:
        payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "sessions"}],
            "dimensionFilter": self._build_site_filter(site_domain),
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
            "limit": str(limit),
        }
        response_payload = self._request_report(
            body=payload,
            ga4_property_id=ga4_property_id,
        )
        rows = response_payload.get("rows")
        if not isinstance(rows, list):
            return []
        top_pages: list[GA4TopPagePeriodMetrics] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            dimensions = row.get("dimensionValues")
            if not isinstance(dimensions, list) or not dimensions:
                continue
            raw_path = _dimension_value(dimensions, index=0)
            if not raw_path:
                continue
            top_pages.append(
                GA4TopPagePeriodMetrics(
                    page_path=raw_path[:220],
                    pageviews=_metric_value(row, index=0),
                    sessions=_metric_value(row, index=1),
                )
            )
            if len(top_pages) >= limit:
                break
        return top_pages

    def _fetch_operator_top_landing_pages(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        limit: int,
        ga4_property_id: str,
    ) -> list[GA4TopLandingPageMetrics]:
        payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "activeUsers"},
                {"name": "screenPageViews"},
                {"name": "engagementRate"},
                {"name": "averageSessionDuration"},
            ],
            "dimensionFilter": self._build_site_filter(site_domain),
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": str(limit),
        }
        response_payload = self._request_report(
            body=payload,
            ga4_property_id=ga4_property_id,
        )
        rows = response_payload.get("rows")
        if not isinstance(rows, list):
            return []
        top_pages: list[GA4TopLandingPageMetrics] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            dimensions = row.get("dimensionValues")
            if not isinstance(dimensions, list) or not dimensions:
                continue
            raw_path = _dimension_value(dimensions, index=0)
            if not raw_path:
                continue
            raw_title = _dimension_value(dimensions, index=1)
            normalized_title = raw_title[:180] if raw_title else None
            top_pages.append(
                GA4TopLandingPageMetrics(
                    page_path=raw_path[:220],
                    page_title=normalized_title,
                    sessions=_metric_value(row, index=0),
                    active_users=_metric_value(row, index=1),
                    views=_metric_value(row, index=2),
                    engagement_rate=_metric_float_value(row, index=3),
                    average_engagement_time_seconds=_metric_float_value(row, index=4),
                )
            )
            if len(top_pages) >= limit:
                break
        return top_pages

    def _fetch_operator_engagement_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        ga4_property_id: str,
    ) -> tuple[float | None, float | None]:
        payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": "engagementRate"}, {"name": "averageSessionDuration"}],
            "dimensionFilter": self._build_site_filter(site_domain),
        }
        response_payload = self._request_report(
            body=payload,
            ga4_property_id=ga4_property_id,
        )
        row = _first_row(response_payload)
        return (
            _metric_float_value(row, index=0),
            _metric_float_value(row, index=1),
        )

    def _fetch_operator_acquisition_channels(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        limit: int,
        ga4_property_id: str,
    ) -> list[GA4AcquisitionChannelMetrics]:
        payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "engagementRate"}],
            "dimensionFilter": self._build_site_filter(site_domain),
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": str(max(1, min(int(limit), 10))),
        }
        response_payload = self._request_report(
            body=payload,
            ga4_property_id=ga4_property_id,
        )
        rows = response_payload.get("rows")
        if not isinstance(rows, list):
            return []
        channels: list[GA4AcquisitionChannelMetrics] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            dimensions = row.get("dimensionValues")
            if not isinstance(dimensions, list) or not dimensions:
                continue
            raw_channel = _dimension_value(dimensions, index=0)
            channel_group = raw_channel[:120] if raw_channel else "Unassigned"
            channels.append(
                GA4AcquisitionChannelMetrics(
                    channel_group=channel_group,
                    sessions=_metric_value(row, index=0),
                    users=_metric_value(row, index=1),
                    engagement_rate=_metric_float_value(row, index=2),
                )
            )
            if len(channels) >= max(1, min(int(limit), 10)):
                break
        return channels

    def _fetch_operator_acquisition_sources(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        limit: int,
        ga4_property_id: str,
    ) -> list[GA4AcquisitionSourceMetrics]:
        payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "sessionSource"}, {"name": "sessionMedium"}],
            "metrics": [{"name": "sessions"}, {"name": "totalUsers"}],
            "dimensionFilter": self._build_site_filter(site_domain),
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": str(max(1, min(int(limit), 10))),
        }
        response_payload = self._request_report(
            body=payload,
            ga4_property_id=ga4_property_id,
        )
        rows = response_payload.get("rows")
        if not isinstance(rows, list):
            return []
        sources: list[GA4AcquisitionSourceMetrics] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            dimensions = row.get("dimensionValues")
            if not isinstance(dimensions, list) or not dimensions:
                continue
            source_raw = _dimension_value(dimensions, index=0)
            medium_raw = _dimension_value(dimensions, index=1)
            source = (source_raw or "(direct)")[:120]
            medium = (medium_raw or "(none)")[:120]
            sources.append(
                GA4AcquisitionSourceMetrics(
                    source=source,
                    medium=medium,
                    sessions=_metric_value(row, index=0),
                    users=_metric_value(row, index=1),
                )
            )
            if len(sources) >= max(1, min(int(limit), 10)):
                break
        return sources

    def _build_site_filter(self, site_domain: str) -> dict[str, Any]:
        host_values = [site_domain]
        if site_domain.startswith("www."):
            without_www = site_domain[4:]
            if without_www:
                host_values.append(without_www)
        else:
            host_values.append(f"www.{site_domain}")
        deduped_values: list[str] = []
        seen: set[str] = set()
        for value in host_values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped_values.append(value)
        return {
            "filter": {
                "fieldName": "hostName",
                "inListFilter": {"values": deduped_values, "caseSensitive": False},
            }
        }

    def _build_page_filter(self, page_path: str | None) -> dict[str, Any] | None:
        normalized_path = str(page_path or "").strip()
        if not normalized_path:
            return None
        return {
            "filter": {
                "fieldName": "pagePath",
                "stringFilter": {
                    "matchType": "EXACT",
                    "value": normalized_path,
                    "caseSensitive": False,
                },
            }
        }

    def _combine_dimension_filters(
        self,
        primary_filter: dict[str, Any],
        secondary_filter: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if secondary_filter is None:
            return primary_filter
        return {
            "andGroup": {
                "expressions": [
                    primary_filter,
                    secondary_filter,
                ]
            }
        }

    def _request_report(
        self,
        *,
        body: dict[str, Any],
        ga4_property_id: str,
    ) -> dict[str, Any]:
        endpoint = f"{self.api_base_url}/properties/{ga4_property_id}:runReport"
        return self._request_json(url=endpoint, method="POST", body=body)

    def _resolve_ga4_property_id(self, ga4_property_id: str | None) -> str:
        scoped_property_id = str(ga4_property_id or "").strip() or self.property_id
        if not scoped_property_id:
            raise GA4AnalyticsProviderConfigurationError("GA4 property id is required.")
        if not scoped_property_id.isdigit():
            raise GA4AnalyticsProviderConfigurationError("GA4 property id format is invalid.")
        return scoped_property_id

    def _request_json(
        self,
        *,
        url: str,
        method: str,
        body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = (
            json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8") if body is not None else None
        )
        access_token = self._resolve_access_token()
        request = Request(
            url=url,
            method=method,
            data=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail_message = _extract_http_error_message(exc)
            raise GA4AnalyticsProviderError(f"GA4 request failed: {detail_message}") from exc
        except TimeoutError as exc:
            raise GA4AnalyticsProviderError("GA4 request timed out.") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise GA4AnalyticsProviderError("GA4 request timed out.") from exc
            raise GA4AnalyticsProviderError("GA4 endpoint unavailable.") from exc
        except Exception as exc:  # noqa: BLE001
            raise GA4AnalyticsProviderError("GA4 request failed.") from exc

        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GA4AnalyticsProviderError("GA4 response is not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise GA4AnalyticsProviderError("GA4 response payload is invalid.")
        return parsed

    def _resolve_access_token(self) -> str:
        try:
            from google.auth import default as google_auth_default
            from google.auth.transport.requests import Request as GoogleAuthRequest
            from google.oauth2 import service_account
        except ImportError as exc:
            raise GA4AnalyticsProviderConfigurationError(
                "google-auth dependencies are required for GA4 analytics."
            ) from exc

        try:
            if self._credentials is None:
                if self.credentials_json:
                    try:
                        credentials_payload = json.loads(self.credentials_json)
                    except json.JSONDecodeError as exc:
                        raise GA4AnalyticsProviderConfigurationError("GA4 service account JSON is invalid.") from exc
                    if not isinstance(credentials_payload, dict):
                        raise GA4AnalyticsProviderConfigurationError(
                            "GA4 service account JSON must decode to an object."
                        )
                    self._credentials = service_account.Credentials.from_service_account_info(
                        credentials_payload,
                        scopes=[_GA4_ANALYTICS_SCOPE],
                    )
                else:
                    credentials, _ = google_auth_default(scopes=[_GA4_ANALYTICS_SCOPE])
                    self._credentials = credentials
                self._auth_request = GoogleAuthRequest()
            credentials = self._credentials
            if credentials is None:
                raise GA4AnalyticsProviderConfigurationError("Unable to initialize GA4 credentials.")
            if not credentials.valid or not getattr(credentials, "token", None):
                credentials.refresh(self._auth_request)
            token = str(getattr(credentials, "token", "") or "").strip()
            if not token:
                raise GA4AnalyticsProviderConfigurationError("GA4 credentials did not return an access token.")
            return token
        except GA4AnalyticsProviderConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ga4_analytics_authorization_failed error_class=%s error=%s",
                exc.__class__.__name__,
                _summarize_error_message(exc),
            )
            raise GA4AnalyticsProviderConfigurationError("Unable to authorize GA4 analytics request.") from exc


def _extract_http_error_message(error: HTTPError) -> str:
    message = str(error.reason or "request failed")
    try:
        if error.fp is None:
            return message
        payload = error.fp.read().decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return message
    if not payload.strip():
        return message
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload[:260]
    if not isinstance(data, dict):
        return message
    error_payload = data.get("error")
    if isinstance(error_payload, dict):
        parsed_message = str(error_payload.get("message") or "").strip()
        if parsed_message:
            return parsed_message
    parsed_message = str(data.get("message") or data.get("error_description") or "").strip()
    return parsed_message or message


def _dimension_value(values: list[Any], *, index: int) -> str | None:
    if index >= len(values):
        return None
    value = values[index]
    if not isinstance(value, dict):
        return None
    raw = str(value.get("value") or "").strip()
    return raw or None


def _metric_value(row: dict[str, Any], *, index: int) -> int:
    values = row.get("metricValues")
    if not isinstance(values, list) or index >= len(values):
        return 0
    metric_payload = values[index]
    if not isinstance(metric_payload, dict):
        return 0
    raw = str(metric_payload.get("value") or "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 0


def _metric_float_value(row: dict[str, Any], *, index: int) -> float | None:
    values = row.get("metricValues")
    if not isinstance(values, list) or index >= len(values):
        return None
    metric_payload = values[index]
    if not isinstance(metric_payload, dict):
        return None
    raw = str(metric_payload.get("value") or "").strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    if not parsed >= 0:
        return None
    return parsed


def _first_row(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[0]
    if not isinstance(row, dict):
        return {}
    return row


def _normalize_domain(value: str) -> str:
    normalized = " ".join(value.split()).strip().lower()
    return normalized.rstrip("/")


def _summarize_error_message(error: Exception) -> str:
    normalized = " ".join(str(error or "").split())
    if not normalized:
        normalized = error.__class__.__name__
    if len(normalized) <= 220:
        return normalized
    return f"{normalized[:217]}..."


def _parse_resource_id(resource: str, *, prefix: str) -> str | None:
    normalized = str(resource or "").strip()
    if not normalized:
        return None
    if normalized.startswith(f"{prefix}/"):
        candidate = normalized.removeprefix(f"{prefix}/").strip()
        return candidate or None
    parts = [segment.strip() for segment in normalized.split("/") if segment.strip()]
    if not parts:
        return None
    if len(parts) >= 2 and parts[-2] == prefix:
        return parts[-1] or None
    return parts[-1] or None

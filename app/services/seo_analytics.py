from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Literal
from urllib.parse import urlparse

from app.integrations.ga4_analytics_provider import (
    GA4AnalyticsProvider,
    GA4AnalyticsProviderConfigurationError,
    GA4AnalyticsProviderError,
    GA4SitePeriodMetrics,
)
from app.integrations.search_console_analytics_provider import (
    DisabledSearchConsoleAnalyticsProvider,
    SearchConsoleAnalyticsProvider,
    SearchConsoleAnalyticsProviderConfigurationError,
    SearchConsoleAnalyticsProviderError,
    SearchConsolePeriodMetrics,
)
from app.schemas.seo_analytics import (
    SEOGA4AccessibleAccountRead,
    SEOGA4AccessibleAccountsRead,
    SEOGA4SiteOnboardingStatusRead,
    SEOAnalyticsMetricWindowRead,
    SEOAnalyticsSiteMetricsSummaryRead,
    SEOAnalyticsSiteSummaryRead,
    SEOAnalyticsTopPageRead,
    SEOSearchConsoleMetricWindowRead,
    SEOSearchConsoleSiteMetricsSummaryRead,
    SEOSearchConsoleSiteSummaryRead,
    SEOSearchConsoleTopPageRead,
    SEOSearchConsoleTopQueryRead,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SEOAnalyticsServiceSettings:
    period_days: int = 7
    top_pages_limit: int = 5
    search_console_period_days: int = 7
    search_console_top_pages_limit: int = 5
    search_console_top_queries_limit: int = 3


@dataclass(frozen=True)
class SEOAnalyticsWindowSummary:
    start_date: date
    end_date: date
    users: int
    sessions: int
    pageviews: int


@dataclass(frozen=True)
class SEOAnalyticsBeforeAfterComparison:
    before_window: SEOAnalyticsWindowSummary
    after_window: SEOAnalyticsWindowSummary
    comparison_scope: str


@dataclass(frozen=True)
class SEOSearchConsoleWindowSummary:
    start_date: date
    end_date: date
    clicks: int
    impressions: int
    ctr: float
    average_position: float


@dataclass(frozen=True)
class SEOSearchConsoleBeforeAfterComparison:
    before_window: SEOSearchConsoleWindowSummary
    after_window: SEOSearchConsoleWindowSummary
    comparison_scope: Literal["page", "site"]
    top_queries: tuple[SEOSearchConsoleTopQueryRead, ...]


class SEOAnalyticsService:
    def __init__(
        self,
        *,
        provider: GA4AnalyticsProvider,
        search_console_provider: SearchConsoleAnalyticsProvider | None = None,
        settings: SEOAnalyticsServiceSettings | None = None,
    ) -> None:
        self.provider = provider
        self.search_console_provider = search_console_provider or DisabledSearchConsoleAnalyticsProvider()
        self.settings = settings or SEOAnalyticsServiceSettings()

    def get_site_summary(
        self,
        *,
        business_id: str,
        site_id: str,
        site_domain: str | None,
        ga4_property_id: str | None = None,
        enforce_site_ga4_property: bool = False,
    ) -> SEOAnalyticsSiteSummaryRead:
        normalized_site_ga4_property_id = _clean_identifier(ga4_property_id)
        site_ga4_property_configured = bool(normalized_site_ga4_property_id)

        if enforce_site_ga4_property and not site_ga4_property_configured:
            return SEOAnalyticsSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                ga4_status="not_configured",
                ga4_error_reason="not_configured",
                message="Google Analytics property is not configured for this site.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
            )

        if (
            site_ga4_property_configured
            and not _is_valid_ga4_property_id(normalized_site_ga4_property_id)
        ):
            return SEOAnalyticsSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="unavailable",
                ga4_status="error",
                ga4_error_reason="invalid_property_format",
                message="Google Analytics property ID format is invalid for this site.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
            )

        normalized_domain = _normalize_site_domain(site_domain)
        if not normalized_domain:
            return SEOAnalyticsSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="unavailable",
                ga4_status="configured" if site_ga4_property_configured else "not_configured",
                ga4_error_reason=None if site_ga4_property_configured else "not_configured",
                message="Analytics unavailable because site domain is not configured.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
            )

        period_days = max(1, min(int(self.settings.period_days), 30))
        top_pages_limit = max(1, min(int(self.settings.top_pages_limit), 10))
        windows = _build_period_windows(period_days=period_days)

        if not self.provider.is_configured():
            return SEOAnalyticsSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                ga4_status="configured" if site_ga4_property_configured else "not_configured",
                ga4_error_reason="not_configured",
                message="Google Analytics is not configured for this workspace.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
            )

        try:
            result = self.provider.fetch_site_metrics(
                site_domain=normalized_domain,
                period_days=period_days,
                top_pages_limit=top_pages_limit,
            )
        except GA4AnalyticsProviderConfigurationError as exc:
            diagnostic_reason = _classify_ga4_configuration_error_reason(exc)
            return SEOAnalyticsSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                ga4_status="error",
                ga4_error_reason=diagnostic_reason,
                message="Google Analytics is not configured for this workspace.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
            )
        except GA4AnalyticsProviderError as exc:
            diagnostic_reason = _classify_ga4_runtime_error_reason(exc)
            logger.warning(
                "seo_analytics_unavailable business_id=%s site_id=%s ga4_reason=%s reason=%s",
                business_id,
                site_id,
                diagnostic_reason,
                str(exc),
            )
            return SEOAnalyticsSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="unavailable",
                ga4_status="error",
                ga4_error_reason=diagnostic_reason,
                message="Google Analytics data is temporarily unavailable.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
            )

        metrics_summary = SEOAnalyticsSiteMetricsSummaryRead(
            current_period_start=windows.current_start,
            current_period_end=windows.current_end,
            previous_period_start=windows.previous_start,
            previous_period_end=windows.previous_end,
            users=_to_metric_window(
                current=result.current_period.users,
                previous=result.previous_period.users,
            ),
            sessions=_to_metric_window(
                current=result.current_period.sessions,
                previous=result.previous_period.sessions,
            ),
            pageviews=_to_metric_window(
                current=result.current_period.pageviews,
                previous=result.previous_period.pageviews,
            ),
            organic_search_sessions=_to_metric_window(
                current=result.current_period.organic_search_sessions,
                previous=result.previous_period.organic_search_sessions,
            ),
        )

        top_pages_summary = [
            _to_top_page_summary(item)
            for item in result.top_pages[:top_pages_limit]
        ]

        return SEOAnalyticsSiteSummaryRead(
            business_id=business_id,
            site_id=site_id,
            available=True,
            status="ok",
            ga4_status="connected",
            ga4_error_reason=None if _ga4_site_metrics_have_data(metrics_summary) else "no_data",
            message=None,
            data_source=result.data_source,
            site_metrics_summary=metrics_summary,
            top_pages_summary=top_pages_summary,
        )

    def get_ga4_accessible_accounts(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> SEOGA4AccessibleAccountsRead:
        try:
            accounts = self.provider.fetch_account_summaries(page_size=25)
        except GA4AnalyticsProviderConfigurationError:
            return SEOGA4AccessibleAccountsRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                message="Google Analytics account discovery is not configured for this workspace.",
                data_source=None,
                accounts=[],
            )
        except GA4AnalyticsProviderError as exc:
            logger.warning(
                "seo_ga4_account_discovery_unavailable business_id=%s site_id=%s reason=%s",
                business_id,
                site_id,
                str(exc),
            )
            return SEOGA4AccessibleAccountsRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="unavailable",
                message="Google Analytics account discovery is temporarily unavailable.",
                data_source=None,
                accounts=[],
            )

        account_summaries = [
            SEOGA4AccessibleAccountRead(
                account_id=item.account_id,
                display_name=item.display_name,
                property_count=max(0, int(item.property_count)),
            )
            for item in accounts
        ]
        return SEOGA4AccessibleAccountsRead(
            business_id=business_id,
            site_id=site_id,
            available=True,
            status="ok",
            message=None if account_summaries else "No accessible Google Analytics accounts were discovered.",
            data_source="ga4_admin_api",
            accounts=account_summaries,
        )

    def get_ga4_site_onboarding_status(
        self,
        *,
        business_id: str,
        site_id: str,
        ga4_onboarding_status: str | None,
        ga4_account_id: str | None,
        ga4_property_id: str | None,
        ga4_data_stream_id: str | None,
        ga4_measurement_id: str | None,
    ) -> SEOGA4SiteOnboardingStatusRead:
        account_discovery = self.get_ga4_accessible_accounts(
            business_id=business_id,
            site_id=site_id,
        )
        normalized_account_id = _clean_identifier(ga4_account_id)
        normalized_property_id = _clean_identifier(ga4_property_id)
        normalized_stream_id = _clean_identifier(ga4_data_stream_id)
        normalized_measurement_id = _clean_identifier(ga4_measurement_id)

        derived_status = _derive_ga4_onboarding_status_from_identifiers(
            ga4_account_id=normalized_account_id,
            ga4_property_id=normalized_property_id,
            ga4_data_stream_id=normalized_stream_id,
            ga4_measurement_id=normalized_measurement_id,
        )
        persisted_status = str(ga4_onboarding_status or "").strip().lower()
        effective_status = (
            persisted_status
            if persisted_status in {
                "not_connected",
                "account_available",
                "property_configured",
                "stream_configured",
                "incomplete",
                "unavailable",
            }
            else derived_status
        )
        if effective_status in {"stream_configured", "incomplete"}:
            effective_status = "property_configured" if normalized_property_id else "not_connected"
        if effective_status == "not_connected":
            if account_discovery.available and account_discovery.accounts:
                effective_status = "account_available"
            elif account_discovery.status == "unavailable":
                effective_status = "unavailable"
        if (
            effective_status == "unavailable"
            and derived_status not in {"not_connected", "unavailable"}
        ):
            effective_status = derived_status

        discovered_account_count = len(account_discovery.accounts)
        auto_provisioning_eligible = (
            account_discovery.available
            and effective_status in {"account_available"}
        )
        return SEOGA4SiteOnboardingStatusRead(
            business_id=business_id,
            site_id=site_id,
            ga4_onboarding_status=effective_status,
            ga4_account_id=normalized_account_id,
            ga4_property_id=normalized_property_id,
            ga4_data_stream_id=normalized_stream_id,
            ga4_measurement_id=normalized_measurement_id,
            account_discovery_available=account_discovery.available,
            discovered_account_count=discovered_account_count,
            auto_provisioning_eligible=auto_provisioning_eligible,
            message=_ga4_onboarding_message_for_status(
                status=effective_status,
                account_discovery=account_discovery,
            ),
        )

    def get_search_console_site_summary(
        self,
        *,
        business_id: str,
        site_id: str,
        search_console_property_url: str | None = None,
        search_console_enabled: bool = False,
    ) -> SEOSearchConsoleSiteSummaryRead:
        if not search_console_enabled:
            return SEOSearchConsoleSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                diagnostic_status="missing_config",
                message="Search Console is not enabled for this site.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
                top_queries_summary=[],
            )
        site_property = _normalize_search_console_site_property_url(search_console_property_url)
        if not site_property:
            return SEOSearchConsoleSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                diagnostic_status="missing_config",
                message="Search Console property is not configured for this site.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
                top_queries_summary=[],
            )

        period_days = max(1, min(int(self.settings.search_console_period_days), 30))
        top_pages_limit = max(1, min(int(self.settings.search_console_top_pages_limit), 10))
        top_queries_limit = max(1, min(int(self.settings.search_console_top_queries_limit), 10))
        windows = _build_period_windows(period_days=period_days)

        if not self.search_console_provider.is_configured():
            return SEOSearchConsoleSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                diagnostic_status="missing_config",
                message="Search Console is not configured for this workspace.",
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
                top_queries_summary=[],
            )
        try:
            result = self.search_console_provider.fetch_site_metrics(
                site_property=site_property,
                period_days=period_days,
                top_pages_limit=top_pages_limit,
                top_queries_limit=top_queries_limit,
            )
        except SearchConsoleAnalyticsProviderConfigurationError as exc:
            diagnostic_status = _to_search_console_diagnostic_status(
                getattr(exc, "diagnostic_status", None),
                fallback="missing_config",
            )
            logger.info(
                "seo_search_console_not_configured business_id=%s site_id=%s diagnostic_status=%s",
                business_id,
                site_id,
                diagnostic_status,
            )
            return SEOSearchConsoleSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="not_configured",
                diagnostic_status=diagnostic_status,
                message=_search_console_message_for_diagnostic(diagnostic_status),
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
                top_queries_summary=[],
            )
        except SearchConsoleAnalyticsProviderError as exc:
            diagnostic_status = _to_search_console_diagnostic_status(
                getattr(exc, "diagnostic_status", None),
                fallback="api_unavailable",
            )
            logger.warning(
                "seo_search_console_unavailable business_id=%s site_id=%s diagnostic_status=%s reason=%s",
                business_id,
                site_id,
                diagnostic_status,
                str(exc),
            )
            return SEOSearchConsoleSiteSummaryRead(
                business_id=business_id,
                site_id=site_id,
                available=False,
                status="unavailable",
                diagnostic_status=diagnostic_status,
                message=_search_console_message_for_diagnostic(diagnostic_status),
                data_source=None,
                site_metrics_summary=None,
                top_pages_summary=[],
                top_queries_summary=[],
            )

        clicks_window = _to_metric_window(
            current=result.current_period.clicks,
            previous=result.previous_period.clicks,
        )
        impressions_window = _to_metric_window(
            current=result.current_period.impressions,
            previous=result.previous_period.impressions,
        )
        metrics_summary = SEOSearchConsoleSiteMetricsSummaryRead(
            current_period_start=windows.current_start,
            current_period_end=windows.current_end,
            previous_period_start=windows.previous_start,
            previous_period_end=windows.previous_end,
            clicks=SEOSearchConsoleMetricWindowRead.model_validate(clicks_window.model_dump()),
            impressions=SEOSearchConsoleMetricWindowRead.model_validate(impressions_window.model_dump()),
            ctr_current=round(result.current_period.ctr, 4),
            ctr_previous=round(result.previous_period.ctr, 4),
            ctr_delta_absolute=round(result.current_period.ctr - result.previous_period.ctr, 4),
            average_position_current=round(result.current_period.average_position, 4),
            average_position_previous=round(result.previous_period.average_position, 4),
            average_position_delta_absolute=round(
                result.current_period.average_position - result.previous_period.average_position,
                4,
            ),
        )
        top_pages_summary = [
            _to_search_console_top_page_summary(item)
            for item in result.top_pages[:top_pages_limit]
        ]
        top_queries_summary = [
            SEOSearchConsoleTopQueryRead(
                query=item.query,
                clicks=max(0, int(item.clicks)),
                impressions=max(0, int(item.impressions)),
                ctr=round(item.ctr, 4),
                average_position=round(item.average_position, 4),
            )
            for item in result.top_queries[:top_queries_limit]
        ]
        return SEOSearchConsoleSiteSummaryRead(
            business_id=business_id,
            site_id=site_id,
            available=True,
            status="ok",
            diagnostic_status=None,
            message=None,
            data_source=result.data_source,
            site_metrics_summary=metrics_summary,
            top_pages_summary=top_pages_summary,
            top_queries_summary=top_queries_summary,
        )

    def build_recommendation_before_after_comparison(
        self,
        *,
        site_domain: str | None,
        recommendation_created_at: datetime,
        page_path: str | None,
    ) -> SEOAnalyticsBeforeAfterComparison | None:
        normalized_domain = _normalize_site_domain(site_domain)
        if not normalized_domain or not self.provider.is_configured():
            return None

        period_days = max(1, min(int(self.settings.period_days), 30))
        anchor_date = recommendation_created_at.date()
        today = date.today()

        before_end = anchor_date - timedelta(days=1)
        before_start = before_end - timedelta(days=period_days - 1)
        if before_end < before_start:
            return None

        desired_after_end = anchor_date + timedelta(days=period_days - 1)
        if desired_after_end <= today:
            after_start = anchor_date
            after_end = desired_after_end
        else:
            after_end = today
            after_start = anchor_date

        if after_end < after_start:
            return None

        normalized_page_path = _normalize_page_path(page_path) if page_path else None
        page_before = self._fetch_window_summary(
            site_domain=normalized_domain,
            start_date=before_start,
            end_date=before_end,
            page_path=normalized_page_path,
        ) if normalized_page_path else None
        page_after = self._fetch_window_summary(
            site_domain=normalized_domain,
            start_date=after_start,
            end_date=after_end,
            page_path=normalized_page_path,
        ) if normalized_page_path else None
        if page_before is not None and page_after is not None:
            return SEOAnalyticsBeforeAfterComparison(
                before_window=page_before,
                after_window=page_after,
                comparison_scope="page",
            )

        site_before = self._fetch_window_summary(
            site_domain=normalized_domain,
            start_date=before_start,
            end_date=before_end,
            page_path=None,
        )
        site_after = self._fetch_window_summary(
            site_domain=normalized_domain,
            start_date=after_start,
            end_date=after_end,
            page_path=None,
        )
        if site_before is not None and site_after is not None:
            return SEOAnalyticsBeforeAfterComparison(
                before_window=site_before,
                after_window=site_after,
                comparison_scope="site",
            )
        return None

    def build_recommendation_search_console_before_after_comparison(
        self,
        *,
        search_console_property_url: str | None,
        search_console_enabled: bool,
        recommendation_created_at: datetime,
        page_path: str | None,
    ) -> SEOSearchConsoleBeforeAfterComparison | None:
        if not search_console_enabled:
            return None
        site_property = _normalize_search_console_site_property_url(search_console_property_url)
        if not site_property or not self.search_console_provider.is_configured():
            return None
        period_days = max(1, min(int(self.settings.search_console_period_days), 30))
        anchor_date = recommendation_created_at.date()
        today = date.today()

        before_end = anchor_date - timedelta(days=1)
        before_start = before_end - timedelta(days=period_days - 1)
        if before_end < before_start:
            return None

        desired_after_end = anchor_date + timedelta(days=period_days - 1)
        if desired_after_end <= today:
            after_start = anchor_date
            after_end = desired_after_end
        else:
            after_end = today
            after_start = anchor_date

        if after_end < after_start:
            return None

        normalized_page_path = _normalize_page_path(page_path) if page_path else None
        page_before = self._fetch_search_console_window_summary(
            site_property=site_property,
            start_date=before_start,
            end_date=before_end,
            page_path=normalized_page_path,
        ) if normalized_page_path else None
        page_after = self._fetch_search_console_window_summary(
            site_property=site_property,
            start_date=after_start,
            end_date=after_end,
            page_path=normalized_page_path,
        ) if normalized_page_path else None
        if page_before is not None and page_after is not None:
            return SEOSearchConsoleBeforeAfterComparison(
                before_window=page_before,
                after_window=page_after,
                comparison_scope="page",
                top_queries=self._fetch_search_console_top_queries(
                    site_property=site_property,
                    start_date=after_start,
                    end_date=after_end,
                    page_path=normalized_page_path,
                ),
            )

        site_before = self._fetch_search_console_window_summary(
            site_property=site_property,
            start_date=before_start,
            end_date=before_end,
            page_path=None,
        )
        site_after = self._fetch_search_console_window_summary(
            site_property=site_property,
            start_date=after_start,
            end_date=after_end,
            page_path=None,
        )
        if site_before is not None and site_after is not None:
            return SEOSearchConsoleBeforeAfterComparison(
                before_window=site_before,
                after_window=site_after,
                comparison_scope="site",
                top_queries=self._fetch_search_console_top_queries(
                    site_property=site_property,
                    start_date=after_start,
                    end_date=after_end,
                    page_path=None,
                ),
            )
        return None

    def match_recommendation_to_top_page(
        self,
        *,
        top_pages_summary: list[SEOAnalyticsTopPageRead],
        recommendation_target_page_hints: list[str] | None,
        recommendation_target_context: str | None,
    ) -> SEOAnalyticsTopPageRead | None:
        if not top_pages_summary:
            return None

        normalized_top_pages: dict[str, SEOAnalyticsTopPageRead] = {}
        for page_summary in top_pages_summary:
            normalized_path = _normalize_page_path(page_summary.page_path)
            if normalized_path is None:
                continue
            normalized_top_pages[normalized_path] = page_summary

        if not normalized_top_pages:
            return None

        for hint in recommendation_target_page_hints or []:
            normalized_hint = _normalize_page_hint(hint)
            if normalized_hint is None:
                continue
            matched = normalized_top_pages.get(normalized_hint)
            if matched is not None:
                return matched

        normalized_context = str(recommendation_target_context or "").strip().lower()
        if normalized_context == "homepage":
            return normalized_top_pages.get("/")
        if normalized_context == "sitewide":
            return normalized_top_pages.get("/") or top_pages_summary[0]

        return None

    def match_recommendation_to_search_console_page(
        self,
        *,
        top_pages_summary: list[SEOSearchConsoleTopPageRead],
        recommendation_target_page_hints: list[str] | None,
        recommendation_target_context: str | None,
    ) -> SEOSearchConsoleTopPageRead | None:
        if not top_pages_summary:
            return None
        normalized_top_pages: dict[str, SEOSearchConsoleTopPageRead] = {}
        for page_summary in top_pages_summary:
            normalized_path = _normalize_page_path(page_summary.page_path)
            if normalized_path is None:
                continue
            normalized_top_pages[normalized_path] = page_summary
        if not normalized_top_pages:
            return None
        for hint in recommendation_target_page_hints or []:
            normalized_hint = _normalize_page_hint(hint)
            if normalized_hint is None:
                continue
            matched = normalized_top_pages.get(normalized_hint)
            if matched is not None:
                return matched
        normalized_context = str(recommendation_target_context or "").strip().lower()
        if normalized_context == "homepage":
            return normalized_top_pages.get("/")
        if normalized_context == "sitewide":
            return normalized_top_pages.get("/") or top_pages_summary[0]
        return None

    def _fetch_window_summary(
        self,
        *,
        site_domain: str,
        start_date: date,
        end_date: date,
        page_path: str | None,
    ) -> SEOAnalyticsWindowSummary | None:
        if start_date > end_date:
            return None
        fetch_window_metrics = getattr(self.provider, "fetch_window_metrics", None)
        if not callable(fetch_window_metrics):
            return None
        try:
            metrics = fetch_window_metrics(
                site_domain=site_domain,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                page_path=page_path,
            )
        except (GA4AnalyticsProviderConfigurationError, GA4AnalyticsProviderError):
            return None
        return _to_window_summary(start_date=start_date, end_date=end_date, metrics=metrics)

    def _fetch_search_console_window_summary(
        self,
        *,
        site_property: str,
        start_date: date,
        end_date: date,
        page_path: str | None,
    ) -> SEOSearchConsoleWindowSummary | None:
        if start_date > end_date:
            return None
        try:
            metrics = self.search_console_provider.fetch_window_metrics(
                site_property=site_property,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                page_path=page_path,
            )
        except (
            SearchConsoleAnalyticsProviderConfigurationError,
            SearchConsoleAnalyticsProviderError,
        ):
            return None
        return _to_search_console_window_summary(
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
        )

    def _fetch_search_console_top_queries(
        self,
        *,
        site_property: str,
        start_date: date,
        end_date: date,
        page_path: str | None,
    ) -> tuple[SEOSearchConsoleTopQueryRead, ...]:
        limit = max(1, min(int(self.settings.search_console_top_queries_limit), 10))
        try:
            queries = self.search_console_provider.fetch_top_queries(
                site_property=site_property,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                query_limit=limit,
                page_path=page_path,
            )
        except (
            SearchConsoleAnalyticsProviderConfigurationError,
            SearchConsoleAnalyticsProviderError,
        ):
            return ()
        normalized: list[SEOSearchConsoleTopQueryRead] = []
        for query in queries[:limit]:
            normalized.append(
                SEOSearchConsoleTopQueryRead(
                    query=str(query.query or "").strip(),
                    clicks=max(0, int(query.clicks)),
                    impressions=max(0, int(query.impressions)),
                    ctr=round(float(query.ctr), 4),
                    average_position=round(float(query.average_position), 4),
                )
            )
        return tuple(normalized)


@dataclass(frozen=True)
class _PeriodWindows:
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date


def _build_period_windows(*, period_days: int) -> _PeriodWindows:
    today = date.today()
    current_end = today
    current_start = current_end - timedelta(days=period_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    return _PeriodWindows(
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
    )


def _to_metric_window(*, current: int, previous: int) -> SEOAnalyticsMetricWindowRead:
    current_value = max(0, int(current))
    previous_value = max(0, int(previous))
    delta_absolute = current_value - previous_value
    if previous_value <= 0:
        delta_percent = None if current_value > 0 else 0.0
    else:
        delta_percent = round((delta_absolute / previous_value) * 100, 2)
    return SEOAnalyticsMetricWindowRead(
        current=current_value,
        previous=previous_value,
        delta_absolute=delta_absolute,
        delta_percent=delta_percent,
    )


def _normalize_site_domain(value: str | None) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if "://" not in raw:
        return raw.rstrip("/")
    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").strip().lower()
    return hostname or None


def _normalize_search_console_site_property_url(value: str | None) -> str | None:
    compacted = str(value or "").strip()
    if not compacted:
        return None
    lowered = compacted.lower()
    if lowered.startswith("sc-domain:"):
        domain = lowered.removeprefix("sc-domain:").strip()
        if "/" in domain:
            domain = domain.split("/", 1)[0].strip()
        return f"sc-domain:{domain}" if domain else None
    parsed = urlparse(compacted)
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").strip().lower()
    if scheme not in {"http", "https"} or not hostname:
        return None
    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    path = (parsed.path or "/").strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if not path.endswith("/"):
        path = f"{path}/"
    return f"{scheme}://{netloc}{path}"


def _to_top_page_summary(item) -> SEOAnalyticsTopPageRead:
    current_pageviews = max(0, int(item.current_pageviews))
    previous_pageviews = max(0, int(item.previous_pageviews))
    current_sessions = max(0, int(item.current_sessions))
    previous_sessions = max(0, int(item.previous_sessions))
    pageviews_window = _to_metric_window(current=current_pageviews, previous=previous_pageviews)
    sessions_window = _to_metric_window(current=current_sessions, previous=previous_sessions)
    return SEOAnalyticsTopPageRead(
        page_path=item.page_path,
        pageviews=current_pageviews,
        sessions=current_sessions,
        pageviews_previous=previous_pageviews,
        sessions_previous=previous_sessions,
        pageviews_delta_absolute=pageviews_window.delta_absolute,
        sessions_delta_absolute=sessions_window.delta_absolute,
        pageviews_delta_percent=pageviews_window.delta_percent,
        sessions_delta_percent=sessions_window.delta_percent,
    )


def _to_search_console_top_page_summary(item) -> SEOSearchConsoleTopPageRead:
    clicks_window = _to_metric_window(
        current=max(0, int(item.current_clicks)),
        previous=max(0, int(item.previous_clicks)),
    )
    impressions_window = _to_metric_window(
        current=max(0, int(item.current_impressions)),
        previous=max(0, int(item.previous_impressions)),
    )
    return SEOSearchConsoleTopPageRead(
        page_path=item.page_path,
        clicks=clicks_window.current,
        clicks_previous=clicks_window.previous,
        clicks_delta_absolute=clicks_window.delta_absolute,
        clicks_delta_percent=clicks_window.delta_percent,
        impressions=impressions_window.current,
        impressions_previous=impressions_window.previous,
        impressions_delta_absolute=impressions_window.delta_absolute,
        impressions_delta_percent=impressions_window.delta_percent,
        ctr=round(float(item.current_ctr), 4),
        ctr_previous=round(float(item.previous_ctr), 4),
        ctr_delta_absolute=round(float(item.current_ctr) - float(item.previous_ctr), 4),
        average_position=round(float(item.current_average_position), 4),
        average_position_previous=round(float(item.previous_average_position), 4),
        average_position_delta_absolute=round(
            float(item.current_average_position) - float(item.previous_average_position),
            4,
        ),
    )


def _normalize_page_path(value: str | None) -> str | None:
    compacted = str(value or "").strip()
    if not compacted:
        return None

    if "://" in compacted:
        parsed = urlparse(compacted)
    else:
        prefixed = compacted if compacted.startswith("/") else f"/{compacted}"
        parsed = urlparse(f"https://placeholder.invalid{prefixed}")
    path = (parsed.path or "/").strip()
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = f"/{path}"
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/":
        path = path.rstrip("/")
    return path or "/"


def _normalize_page_hint(value: object) -> str | None:
    compacted = str(value or "").strip()
    if not compacted:
        return None
    lowered = compacted.lower()
    if lowered == "homepage":
        return "/"
    return _normalize_page_path(compacted)


def _to_window_summary(
    *,
    start_date: date,
    end_date: date,
    metrics: GA4SitePeriodMetrics,
) -> SEOAnalyticsWindowSummary:
    return SEOAnalyticsWindowSummary(
        start_date=start_date,
        end_date=end_date,
        users=max(0, int(metrics.users)),
        sessions=max(0, int(metrics.sessions)),
        pageviews=max(0, int(metrics.pageviews)),
    )


def _to_search_console_window_summary(
    *,
    start_date: date,
    end_date: date,
    metrics: SearchConsolePeriodMetrics,
) -> SEOSearchConsoleWindowSummary:
    return SEOSearchConsoleWindowSummary(
        start_date=start_date,
        end_date=end_date,
        clicks=max(0, int(metrics.clicks)),
        impressions=max(0, int(metrics.impressions)),
        ctr=round(float(metrics.ctr), 4),
        average_position=round(float(metrics.average_position), 4),
    )


def _to_search_console_diagnostic_status(value: str | None, *, fallback: str) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {
        "missing_config",
        "invalid_credentials",
        "adc_unavailable",
        "access_denied",
        "property_not_accessible",
        "api_unavailable",
    }:
        return candidate
    return fallback


def _search_console_message_for_diagnostic(diagnostic_status: str) -> str:
    if diagnostic_status == "missing_config":
        return "Search Console is not configured for this workspace."
    if diagnostic_status == "invalid_credentials":
        return "Search Console credentials are invalid or unreadable."
    if diagnostic_status == "adc_unavailable":
        return "Search Console credentials are unavailable in runtime."
    if diagnostic_status == "access_denied":
        return "Search Console access was denied for this workspace."
    if diagnostic_status == "property_not_accessible":
        return "Configured Search Console property is not accessible."
    return "Search Console data is temporarily unavailable."


def _is_valid_ga4_property_id(value: str | None) -> bool:
    compacted = str(value or "").strip()
    if not compacted:
        return False
    return compacted.isdigit()


def _classify_ga4_configuration_error_reason(error: Exception) -> str:
    message = str(error or "").strip().lower()
    if not message:
        return "unknown_error"
    if (
        "not configured" in message
        or "property id is required" in message
        or "credentials are required" in message
    ):
        return "not_configured"
    if "invalid" in message and "property" in message:
        return "invalid_property_format"
    if "access denied" in message or "permission denied" in message:
        return "access_denied"
    if "404" in message or "not found" in message:
        return "property_not_found"
    if "credentials" in message or "authorize" in message:
        return "not_configured"
    return "unknown_error"


def _classify_ga4_runtime_error_reason(error: Exception) -> str:
    message = str(error or "").strip().lower()
    if not message:
        return "unknown_error"
    if "permission_denied" in message or "permission denied" in message or "access denied" in message:
        return "access_denied"
    if "invalid argument" in message or "invalid property" in message or "malformed" in message:
        return "invalid_property_format"
    if "404" in message or "not found" in message or "unknown property" in message:
        return "property_not_found"
    if "not configured" in message:
        return "not_configured"
    return "unknown_error"


def _ga4_site_metrics_have_data(metrics: SEOAnalyticsSiteMetricsSummaryRead) -> bool:
    return (
        metrics.users.current > 0
        or metrics.sessions.current > 0
        or metrics.pageviews.current > 0
        or metrics.organic_search_sessions.current > 0
    )


def _clean_identifier(value: str | None) -> str | None:
    compacted = str(value or "").strip()
    return compacted or None


def _derive_ga4_onboarding_status_from_identifiers(
    *,
    ga4_account_id: str | None,
    ga4_property_id: str | None,
    ga4_data_stream_id: str | None,
    ga4_measurement_id: str | None,
) -> str:
    has_account = bool(ga4_account_id)
    has_property = bool(ga4_property_id)
    # Stream and measurement identifiers are intentionally not required for GA4
    # onboarding classification in this phase. Property configuration is sufficient.
    if not has_account and not has_property:
        return "not_connected"
    if has_account and not has_property:
        return "account_available"
    if has_property:
        return "property_configured"
    return "not_connected"


def _ga4_onboarding_message_for_status(
    *,
    status: str,
    account_discovery: SEOGA4AccessibleAccountsRead,
) -> str:
    if status == "property_configured":
        return "Google Analytics property is configured for this site."
    if status == "account_available":
        if account_discovery.accounts:
            return "Accessible Google Analytics accounts were found for this workspace."
        return "Google Analytics account discovery is available. Enter your GA4 property ID to continue."
    if status == "unavailable":
        return account_discovery.message or "Google Analytics onboarding discovery is temporarily unavailable."
    if account_discovery.status == "not_configured":
        return "Account discovery is not enabled. Enter your GA4 property ID directly."
    if account_discovery.status == "unavailable":
        return account_discovery.message or "Google Analytics onboarding discovery is temporarily unavailable."
    if account_discovery.accounts:
        return "Google Analytics onboarding is not connected for this site yet."
    return "Account discovery is not enabled. Enter your GA4 property ID directly."

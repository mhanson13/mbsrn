from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_seo_analytics_service, get_tenant_context
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.integrations.ga4_analytics_provider import (
    GA4AccountSummary,
    DisabledGA4AnalyticsProvider,
    GA4AnalyticsProviderError,
    GA4SiteMetricsResult,
    GA4SitePeriodMetrics,
    GA4TopPageMetrics,
    MockGA4AnalyticsProvider,
)
from app.integrations.search_console_analytics_provider import (
    DisabledSearchConsoleAnalyticsProvider,
    SearchConsoleAnalyticsProviderConfigurationError,
    SearchConsoleAnalyticsProviderError,
    SearchConsolePeriodMetrics,
    SearchConsoleSiteMetricsResult,
    SearchConsoleTopPageMetrics,
    SearchConsoleTopQueryMetrics,
)
from app.schemas.seo_analytics import SEOAnalyticsTopPageRead
from app.services.seo_analytics import SEOAnalyticsService, SEOAnalyticsServiceSettings


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(
    db_session,
    *,
    business_id: str,
    analytics_service: SEOAnalyticsService,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)
    app.include_router(seo_v1_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    app.dependency_overrides[get_seo_analytics_service] = lambda: analytics_service
    return TestClient(app)


def _create_site(
    client: TestClient,
    business_id: str,
    domain: str = "analytics.example",
    *,
    search_console_property_url: str | None = None,
    search_console_enabled: bool | None = None,
    ga4_account_id: str | None = None,
    ga4_property_id: str | None = None,
    ga4_data_stream_id: str | None = None,
    ga4_measurement_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "display_name": "Analytics Site",
        "base_url": f"https://{domain}/",
    }
    if search_console_property_url is not None:
        payload["search_console_property_url"] = search_console_property_url
    if search_console_enabled is not None:
        payload["search_console_enabled"] = search_console_enabled
    if ga4_account_id is not None:
        payload["ga4_account_id"] = ga4_account_id
    if ga4_property_id is not None:
        payload["ga4_property_id"] = ga4_property_id
    if ga4_data_stream_id is not None:
        payload["ga4_data_stream_id"] = ga4_data_stream_id
    if ga4_measurement_id is not None:
        payload["ga4_measurement_id"] = ga4_measurement_id
    response = client.post(
        f"/api/businesses/{business_id}/seo/sites",
        json=payload,
    )
    assert response.status_code == 201
    return response.json()["id"]


class _WindowComparisonProvider:
    def __init__(self, *, fail_page_windows: bool = False) -> None:
        self.fail_page_windows = fail_page_windows

    def is_configured(self) -> bool:
        return True

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult:
        del site_domain, period_days
        return GA4SiteMetricsResult(
            current_period=GA4SitePeriodMetrics(users=300, sessions=420, pageviews=640, organic_search_sessions=250),
            previous_period=GA4SitePeriodMetrics(users=260, sessions=370, pageviews=560, organic_search_sessions=220),
            top_pages=tuple(
                GA4TopPageMetrics(
                    page_path="/" if index == 0 else f"/services/{index}",
                    current_pageviews=200 - (index * 10),
                    previous_pageviews=170 - (index * 10),
                    current_sessions=140 - (index * 8),
                    previous_sessions=120 - (index * 8),
                )
                for index in range(max(1, top_pages_limit))
            ),
            data_source="ga4_mock",
        )

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> GA4SitePeriodMetrics:
        del site_domain, end_date
        if page_path:
            if self.fail_page_windows:
                raise GA4AnalyticsProviderError("page-level window unavailable")
            if start_date == "2026-01-08":
                return GA4SitePeriodMetrics(users=90, sessions=120, pageviews=180, organic_search_sessions=75)
            return GA4SitePeriodMetrics(users=110, sessions=150, pageviews=225, organic_search_sessions=92)
        if start_date == "2026-01-08":
            return GA4SitePeriodMetrics(users=260, sessions=370, pageviews=560, organic_search_sessions=220)
        return GA4SitePeriodMetrics(users=300, sessions=420, pageviews=640, organic_search_sessions=250)


class _GA4AccountDiscoveryProvider:
    def __init__(self, *, accounts: tuple[GA4AccountSummary, ...]) -> None:
        self._accounts = accounts

    def is_configured(self) -> bool:
        return True

    def fetch_account_summaries(self, *, page_size: int = 20) -> tuple[GA4AccountSummary, ...]:
        del page_size
        return self._accounts

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult:
        del site_domain, period_days, top_pages_limit
        raise GA4AnalyticsProviderError("site summary unavailable in discovery stub")


class _GA4ErrorProvider:
    def __init__(self, message: str) -> None:
        self.message = message

    def is_configured(self) -> bool:
        return True

    def fetch_account_summaries(self, *, page_size: int = 20) -> tuple[GA4AccountSummary, ...]:
        del page_size
        return ()

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult:
        del site_domain, period_days, top_pages_limit
        raise GA4AnalyticsProviderError(self.message)

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> GA4SitePeriodMetrics:
        del site_domain, start_date, end_date, page_path
        raise GA4AnalyticsProviderError(self.message)


class _SearchConsoleWindowProvider:
    def is_configured(self) -> bool:
        return True

    def fetch_site_metrics(
        self,
        *,
        site_property: str,
        period_days: int,
        top_pages_limit: int,
        top_queries_limit: int,
    ) -> SearchConsoleSiteMetricsResult:
        del site_property, period_days
        return SearchConsoleSiteMetricsResult(
            current_period=SearchConsolePeriodMetrics(clicks=120, impressions=3600, ctr=3.33, average_position=8.2),
            previous_period=SearchConsolePeriodMetrics(clicks=96, impressions=3300, ctr=2.91, average_position=9.0),
            top_pages=tuple(
                SearchConsoleTopPageMetrics(
                    page_path="/" if index == 0 else f"/services/{index}",
                    current_clicks=max(1, 80 - (index * 10)),
                    previous_clicks=max(0, 70 - (index * 10)),
                    current_impressions=max(1, 1800 - (index * 120)),
                    previous_impressions=max(0, 1600 - (index * 120)),
                    current_ctr=4.4,
                    previous_ctr=4.0,
                    current_average_position=7.9 + index,
                    previous_average_position=8.5 + index,
                )
                for index in range(max(1, top_pages_limit))
            ),
            top_queries=tuple(
                SearchConsoleTopQueryMetrics(
                    query=f"query {index + 1}",
                    clicks=max(1, 32 - (index * 2)),
                    impressions=max(1, 400 - (index * 25)),
                    ctr=8.0,
                    average_position=7.1 + (index * 0.6),
                )
                for index in range(max(1, top_queries_limit))
            ),
            data_source="search_console_mock",
        )

    def fetch_window_metrics(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> SearchConsolePeriodMetrics:
        del site_property, end_date
        if page_path:
            if start_date == "2026-01-08":
                return SearchConsolePeriodMetrics(clicks=20, impressions=620, ctr=3.22, average_position=10.5)
            return SearchConsolePeriodMetrics(clicks=31, impressions=760, ctr=4.08, average_position=9.2)
        if start_date == "2026-01-08":
            return SearchConsolePeriodMetrics(clicks=96, impressions=3300, ctr=2.91, average_position=9.0)
        return SearchConsolePeriodMetrics(clicks=120, impressions=3600, ctr=3.33, average_position=8.2)

    def fetch_top_queries(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        query_limit: int,
        page_path: str | None = None,
    ) -> tuple[SearchConsoleTopQueryMetrics, ...]:
        del site_property, start_date, end_date, page_path
        return tuple(
            SearchConsoleTopQueryMetrics(
                query=f"query {index + 1}",
                clicks=max(1, 22 - (index * 2)),
                impressions=max(1, 210 - (index * 20)),
                ctr=9.5,
                average_position=8.1 + (index * 0.3),
            )
            for index in range(max(1, query_limit))
        )


class _SearchConsoleErrorProvider:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def is_configured(self) -> bool:
        return True

    def fetch_site_metrics(self, **_: object) -> SearchConsoleSiteMetricsResult:
        raise self._exc

    def fetch_window_metrics(self, **_: object) -> SearchConsolePeriodMetrics:
        raise self._exc

    def fetch_top_queries(self, **_: object) -> tuple[SearchConsoleTopQueryMetrics, ...]:
        raise self._exc


def test_site_analytics_summary_returns_metrics_with_mock_provider(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-one.example",
        ga4_property_id="2000000002",
    )

    response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/site-summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["business_id"] == seeded_business.id
    assert payload["site_id"] == site_id
    assert payload["available"] is True
    assert payload["status"] == "ok"
    assert payload["data_source"] == "ga4_mock"
    assert payload["site_metrics_summary"]["users"]["current"] > 0
    assert payload["site_metrics_summary"]["sessions"]["current"] > 0
    assert payload["site_metrics_summary"]["pageviews"]["current"] > 0
    assert payload["site_metrics_summary"]["organic_search_sessions"]["current"] >= 0
    assert len(payload["top_pages_summary"]) == 3
    first_top_page = payload["top_pages_summary"][0]
    assert "page_path" in first_top_page
    assert first_top_page["pageviews"] >= 0
    assert first_top_page["sessions"] >= 0
    assert first_top_page["pageviews_previous"] >= 0
    assert first_top_page["sessions_previous"] >= 0
    assert isinstance(first_top_page["pageviews_delta_absolute"], int)
    assert isinstance(first_top_page["sessions_delta_absolute"], int)
    assert first_top_page["pageviews_delta_percent"] is None or isinstance(
        first_top_page["pageviews_delta_percent"],
        (int, float),
    )
    assert first_top_page["sessions_delta_percent"] is None or isinstance(
        first_top_page["sessions_delta_percent"],
        (int, float),
    )


def test_site_analytics_summary_degrades_cleanly_when_not_configured(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=DisabledGA4AnalyticsProvider(),
            settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=5),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-two.example",
        ga4_property_id="2000000002",
    )

    response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/site-summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "not_configured"
    assert payload["message"] == "Google Analytics is not configured for this workspace."
    assert payload["site_metrics_summary"] is None
    assert payload["top_pages_summary"] == []


def test_site_analytics_summary_reports_site_level_not_configured_when_property_missing(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
        ),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-missing-property.example")

    response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/site-summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "not_configured"
    assert payload["ga4_status"] == "not_configured"
    assert payload["ga4_error_reason"] == "not_configured"
    assert payload["message"] == "Google Analytics property is not configured for this site."


def test_site_analytics_summary_reports_invalid_property_format_reason(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-invalid-property.example",
        ga4_property_id="property/not-valid",
    )

    response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/site-summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "unavailable"
    assert payload["ga4_status"] == "error"
    assert payload["ga4_error_reason"] == "invalid_property_format"


def test_site_analytics_summary_reports_access_denied_reason(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=_GA4ErrorProvider("GA4 request failed: PERMISSION_DENIED"),
            settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-access-denied.example",
        ga4_property_id="2000000002",
    )

    response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/site-summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "unavailable"
    assert payload["ga4_status"] == "error"
    assert payload["ga4_error_reason"] == "access_denied"


def test_site_analytics_summary_enforces_tenant_scope(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
        ),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-scope.example")

    cross_business_response = client.get(
        f"/api/businesses/other-business/seo/sites/{site_id}/analytics/site-summary"
    )
    assert cross_business_response.status_code == 404


def test_ga4_accessible_accounts_returns_account_summaries(db_session, seeded_business) -> None:
    provider = _GA4AccountDiscoveryProvider(
        accounts=(
            GA4AccountSummary(account_id="1000000001", display_name="Primary Account", property_count=3),
            GA4AccountSummary(account_id="1000000002", display_name="Secondary Account", property_count=1),
        ),
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(provider=provider),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-ga4-accounts.example")

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/ga4-accessible-accounts"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "ok"
    assert payload["data_source"] == "ga4_admin_api"
    assert payload["accounts"] == [
        {
            "account_id": "1000000001",
            "display_name": "Primary Account",
            "property_count": 3,
        },
        {
            "account_id": "1000000002",
            "display_name": "Secondary Account",
            "property_count": 1,
        },
    ]


def test_ga4_accessible_accounts_degrades_cleanly_when_not_configured(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(provider=DisabledGA4AnalyticsProvider()),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-ga4-disabled.example")

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/ga4-accessible-accounts"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "not_configured"
    assert payload["accounts"] == []


def test_ga4_site_onboarding_status_reflects_site_configuration(db_session, seeded_business) -> None:
    provider = _GA4AccountDiscoveryProvider(
        accounts=(GA4AccountSummary(account_id="1000000001", display_name="Primary Account", property_count=2),),
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(provider=provider),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-ga4-onboarding.example",
        ga4_account_id="1000000001",
        ga4_property_id="2000000002",
        ga4_data_stream_id="3000000003",
        ga4_measurement_id="g-test1234",
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/ga4-onboarding-status"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ga4_onboarding_status"] == "stream_configured"
    assert payload["ga4_measurement_id"] == "G-TEST1234"
    assert payload["account_discovery_available"] is True
    assert payload["discovered_account_count"] == 1
    assert payload["auto_provisioning_eligible"] is False


def test_ga4_site_onboarding_status_uses_account_available_when_discovered(db_session, seeded_business) -> None:
    provider = _GA4AccountDiscoveryProvider(
        accounts=(GA4AccountSummary(account_id="1000000001", display_name="Primary Account", property_count=2),),
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(provider=provider),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-ga4-account-available.example")

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/ga4-onboarding-status"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ga4_onboarding_status"] == "account_available"
    assert payload["account_discovery_available"] is True
    assert payload["discovered_account_count"] == 1
    assert payload["auto_provisioning_eligible"] is True


def test_ga4_onboarding_endpoints_enforce_tenant_scope(db_session, seeded_business) -> None:
    provider = _GA4AccountDiscoveryProvider(
        accounts=(GA4AccountSummary(account_id="1000000001", display_name="Primary Account", property_count=2),),
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(provider=provider),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-ga4-scope.example")

    onboarding_response = client.get(
        f"/api/businesses/other-business/seo/sites/{site_id}/analytics/ga4-onboarding-status"
    )
    assert onboarding_response.status_code == 404

    accounts_response = client.get(
        f"/api/businesses/other-business/seo/sites/{site_id}/analytics/ga4-accessible-accounts"
    )
    assert accounts_response.status_code == 404


def test_match_recommendation_to_top_page_uses_target_page_hints_first() -> None:
    service = SEOAnalyticsService(
        provider=MockGA4AnalyticsProvider(),
        settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
    )
    top_pages = [
        SEOAnalyticsTopPageRead(
            page_path="/",
            pageviews=220,
            sessions=160,
        ),
        SEOAnalyticsTopPageRead(
            page_path="/services/flooring",
            pageviews=150,
            sessions=95,
        ),
    ]

    matched = service.match_recommendation_to_top_page(
        top_pages_summary=top_pages,
        recommendation_target_page_hints=["/services/flooring"],
        recommendation_target_context="service_pages",
    )

    assert matched is not None
    assert matched.page_path == "/services/flooring"


def test_match_recommendation_to_top_page_returns_homepage_for_homepage_context() -> None:
    service = SEOAnalyticsService(
        provider=MockGA4AnalyticsProvider(),
        settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
    )
    top_pages = [
        SEOAnalyticsTopPageRead(
            page_path="/",
            pageviews=220,
            sessions=160,
        ),
        SEOAnalyticsTopPageRead(
            page_path="/services/flooring",
            pageviews=150,
            sessions=95,
        ),
    ]

    matched = service.match_recommendation_to_top_page(
        top_pages_summary=top_pages,
        recommendation_target_page_hints=[],
        recommendation_target_context="homepage",
    )

    assert matched is not None
    assert matched.page_path == "/"


def test_match_recommendation_to_top_page_returns_none_when_no_hint_or_context_match() -> None:
    service = SEOAnalyticsService(
        provider=MockGA4AnalyticsProvider(),
        settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
    )
    top_pages = [
        SEOAnalyticsTopPageRead(
            page_path="/services/flooring",
            pageviews=150,
            sessions=95,
        ),
    ]

    matched = service.match_recommendation_to_top_page(
        top_pages_summary=top_pages,
        recommendation_target_page_hints=["/missing-page"],
        recommendation_target_context="general",
    )

    assert matched is None


def test_build_recommendation_before_after_comparison_prefers_page_metrics() -> None:
    service = SEOAnalyticsService(
        provider=_WindowComparisonProvider(fail_page_windows=False),
        settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
    )

    comparison = service.build_recommendation_before_after_comparison(
        site_domain="client.example",
        recommendation_created_at=datetime(2026, 1, 15, 10, 0, 0),
        page_path="/services/flooring",
    )

    assert comparison is not None
    assert comparison.comparison_scope == "page"
    assert comparison.before_window.start_date.isoformat() == "2026-01-08"
    assert comparison.before_window.end_date.isoformat() == "2026-01-14"
    assert comparison.before_window.sessions == 120
    assert comparison.after_window.sessions == 150


def test_build_recommendation_before_after_comparison_falls_back_to_site_metrics() -> None:
    service = SEOAnalyticsService(
        provider=_WindowComparisonProvider(fail_page_windows=True),
        settings=SEOAnalyticsServiceSettings(period_days=7, top_pages_limit=3),
    )

    comparison = service.build_recommendation_before_after_comparison(
        site_domain="client.example",
        recommendation_created_at=datetime(2026, 1, 15, 10, 0, 0),
        page_path="/services/flooring",
    )

    assert comparison is not None
    assert comparison.comparison_scope == "site"
    assert comparison.before_window.sessions == 370
    assert comparison.after_window.sessions == 420


def test_search_console_site_summary_returns_metrics_with_mock_provider(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleWindowProvider(),
            settings=SEOAnalyticsServiceSettings(
                period_days=7,
                top_pages_limit=3,
                search_console_period_days=7,
                search_console_top_pages_limit=3,
                search_console_top_queries_limit=2,
            ),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search.example",
        search_console_property_url="sc-domain:analytics-search.example",
        search_console_enabled=True,
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["business_id"] == seeded_business.id
    assert payload["site_id"] == site_id
    assert payload["available"] is True
    assert payload["status"] == "ok"
    assert payload["data_source"] == "search_console_mock"
    assert payload["site_metrics_summary"]["clicks"]["current"] == 120
    assert payload["site_metrics_summary"]["impressions"]["current"] == 3600
    assert len(payload["top_pages_summary"]) == 3
    assert len(payload["top_queries_summary"]) == 2


def test_search_console_site_summary_degrades_cleanly_when_not_configured(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=DisabledSearchConsoleAnalyticsProvider(),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(client, seeded_business.id, domain="analytics-search-two.example")

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "not_configured"
    assert payload["diagnostic_status"] == "missing_config"
    assert payload["message"] == "Search Console is not enabled for this site."
    assert payload["site_metrics_summary"] is None
    assert payload["top_pages_summary"] == []
    assert payload["top_queries_summary"] == []


def test_search_console_site_summary_enforces_tenant_scope(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleWindowProvider(),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-scope.example",
        search_console_property_url="sc-domain:analytics-search-scope.example",
        search_console_enabled=True,
    )

    cross_business_response = client.get(
        f"/api/businesses/other-business/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert cross_business_response.status_code == 404


def test_search_console_site_summary_is_configured_per_site(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleWindowProvider(),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    configured_site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-configured.example",
        search_console_property_url="sc-domain:analytics-search-configured.example",
        search_console_enabled=True,
    )
    unconfigured_site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-unconfigured.example",
    )

    configured_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{configured_site_id}/analytics/search-visibility-summary"
    )
    assert configured_response.status_code == 200
    assert configured_response.json()["status"] == "ok"

    unconfigured_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{unconfigured_site_id}/analytics/search-visibility-summary"
    )
    assert unconfigured_response.status_code == 200
    assert unconfigured_response.json()["status"] == "not_configured"
    assert unconfigured_response.json()["diagnostic_status"] == "missing_config"


def test_search_console_site_summary_surfaces_invalid_credentials_diagnostic(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleErrorProvider(
                SearchConsoleAnalyticsProviderConfigurationError(
                    "bad credentials",
                    diagnostic_status="invalid_credentials",
                )
            ),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-invalid.example",
        search_console_property_url="sc-domain:analytics-search-invalid.example",
        search_console_enabled=True,
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "not_configured"
    assert payload["diagnostic_status"] == "invalid_credentials"
    assert payload["message"] == "Search Console credentials are invalid or unreadable."


def test_search_console_site_summary_surfaces_adc_unavailable_diagnostic(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleErrorProvider(
                SearchConsoleAnalyticsProviderConfigurationError(
                    "adc unavailable",
                    diagnostic_status="adc_unavailable",
                )
            ),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-adc.example",
        search_console_property_url="sc-domain:analytics-search-adc.example",
        search_console_enabled=True,
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_configured"
    assert payload["diagnostic_status"] == "adc_unavailable"
    assert payload["message"] == "Search Console credentials are unavailable in runtime."


def test_search_console_site_summary_surfaces_access_denied_diagnostic(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleErrorProvider(
                SearchConsoleAnalyticsProviderConfigurationError(
                    "forbidden",
                    diagnostic_status="access_denied",
                )
            ),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-denied.example",
        search_console_property_url="sc-domain:analytics-search-denied.example",
        search_console_enabled=True,
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_configured"
    assert payload["diagnostic_status"] == "access_denied"
    assert payload["message"] == "Search Console access was denied for this workspace."


def test_search_console_site_summary_surfaces_property_not_accessible_diagnostic(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleErrorProvider(
                SearchConsoleAnalyticsProviderConfigurationError(
                    "property not accessible",
                    diagnostic_status="property_not_accessible",
                )
            ),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-property.example",
        search_console_property_url="sc-domain:analytics-search-property.example",
        search_console_enabled=True,
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_configured"
    assert payload["diagnostic_status"] == "property_not_accessible"
    assert payload["message"] == "Configured Search Console property is not accessible."


def test_search_console_site_summary_surfaces_api_unavailable_diagnostic(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        analytics_service=SEOAnalyticsService(
            provider=MockGA4AnalyticsProvider(),
            search_console_provider=_SearchConsoleErrorProvider(
                SearchConsoleAnalyticsProviderError(
                    "downstream unavailable",
                    diagnostic_status="api_unavailable",
                )
            ),
            settings=SEOAnalyticsServiceSettings(search_console_period_days=7),
        ),
    )
    site_id = _create_site(
        client,
        seeded_business.id,
        domain="analytics-search-unavailable.example",
        search_console_property_url="sc-domain:analytics-search-unavailable.example",
        search_console_enabled=True,
    )

    response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/analytics/search-visibility-summary"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["diagnostic_status"] == "api_unavailable"
    assert payload["message"] == "Search Console data is temporarily unavailable."

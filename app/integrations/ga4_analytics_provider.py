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
class GA4SiteMetricsResult:
    current_period: GA4SitePeriodMetrics
    previous_period: GA4SitePeriodMetrics
    top_pages: tuple[GA4TopPageMetrics, ...]
    data_source: str


class GA4AnalyticsProvider(Protocol):
    def is_configured(self) -> bool: ...

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult: ...

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> GA4SitePeriodMetrics: ...


class DisabledGA4AnalyticsProvider:
    def is_configured(self) -> bool:
        return False

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult:
        del site_domain, period_days, top_pages_limit
        raise GA4AnalyticsProviderConfigurationError("GA4 analytics is not configured.")

    def fetch_window_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> GA4SitePeriodMetrics:
        del site_domain, start_date, end_date, page_path
        raise GA4AnalyticsProviderConfigurationError("GA4 analytics is not configured.")


class MockGA4AnalyticsProvider:
    def is_configured(self) -> bool:
        return True

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult:
        del period_days
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
    ) -> GA4SitePeriodMetrics:
        seed_components = f"{_normalize_domain(site_domain)}|{start_date}|{end_date}|{(page_path or '').strip().lower()}"
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
        )


class GoogleAnalyticsDataAPIClient:
    def __init__(
        self,
        *,
        property_id: str | None,
        timeout_seconds: int = 10,
        credentials_json: str | None = None,
        api_base_url: str = _DEFAULT_GA4_API_BASE_URL,
    ) -> None:
        self.property_id = (property_id or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.credentials_json = (credentials_json or "").strip() or None
        self.api_base_url = (api_base_url or _DEFAULT_GA4_API_BASE_URL).rstrip("/")
        self._credentials: Any | None = None
        self._auth_request: Any | None = None

    def is_configured(self) -> bool:
        return bool(self.property_id)

    def fetch_site_metrics(
        self,
        *,
        site_domain: str,
        period_days: int,
        top_pages_limit: int,
    ) -> GA4SiteMetricsResult:
        if not self.is_configured():
            raise GA4AnalyticsProviderConfigurationError("GA4 property id is required.")
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
        )
        previous_period = self._fetch_period_metrics(
            site_domain=normalized_domain,
            start_date=f"{previous_start_offset}daysAgo",
            end_date=f"{previous_end_offset}daysAgo",
        )
        current_top_pages = self._fetch_top_pages(
            site_domain=normalized_domain,
            start_date=f"{current_start_offset}daysAgo",
            end_date="today",
            limit=bounded_top_pages_limit,
        )
        previous_top_pages = self._fetch_top_pages(
            site_domain=normalized_domain,
            start_date=f"{previous_start_offset}daysAgo",
            end_date=f"{previous_end_offset}daysAgo",
            limit=bounded_top_pages_limit,
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
    ) -> GA4SitePeriodMetrics:
        if not self.is_configured():
            raise GA4AnalyticsProviderConfigurationError("GA4 property id is required.")
        normalized_domain = _normalize_domain(site_domain)
        if not normalized_domain:
            raise GA4AnalyticsProviderConfigurationError("A normalized site domain is required for GA4 analytics.")
        return self._fetch_period_metrics(
            site_domain=normalized_domain,
            start_date=start_date,
            end_date=end_date,
            page_path=page_path,
        )

    def _fetch_period_metrics(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> GA4SitePeriodMetrics:
        site_filter = self._build_site_filter(site_domain)
        page_filter = self._build_page_filter(page_path)
        period_filter = self._combine_dimension_filters(site_filter, page_filter)
        base_payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": "totalUsers"}, {"name": "sessions"}, {"name": "screenPageViews"}],
            "dimensionFilter": period_filter,
        }
        metrics_response = self._request_report(body=base_payload)
        row = _first_row(metrics_response)
        users = _metric_value(row, index=0)
        sessions = _metric_value(row, index=1)
        pageviews = _metric_value(row, index=2)

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
            "dimensionFilter": {
                "andGroup": {
                    "expressions": organic_filter_expressions
                }
            },
        }
        organic_response = self._request_report(body=organic_payload)
        organic_row = _first_row(organic_response)
        organic_sessions = _metric_value(organic_row, index=0)

        return GA4SitePeriodMetrics(
            users=users,
            sessions=sessions,
            pageviews=pageviews,
            organic_search_sessions=organic_sessions,
        )

    def _fetch_top_pages(
        self,
        *,
        site_domain: str,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> list[GA4TopPagePeriodMetrics]:
        payload: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "sessions"}],
            "dimensionFilter": self._build_site_filter(site_domain),
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
            "limit": str(limit),
        }
        response_payload = self._request_report(body=payload)
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

    def _request_report(self, *, body: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self.api_base_url}/properties/{self.property_id}:runReport"
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        access_token = self._resolve_access_token()
        request = Request(
            url=endpoint,
            method="POST",
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
            raise GA4AnalyticsProviderError(f"GA4 report request failed: {detail_message}") from exc
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
                        raise GA4AnalyticsProviderConfigurationError(
                            "GA4 service account JSON is invalid."
                        ) from exc
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
            raise GA4AnalyticsProviderConfigurationError(
                "Unable to authorize GA4 analytics request."
            ) from exc


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

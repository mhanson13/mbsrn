from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

_SEARCH_CONSOLE_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_DEFAULT_SEARCH_CONSOLE_API_BASE_URL = "https://searchconsole.googleapis.com/webmasters/v3"


class SearchConsoleAnalyticsProviderConfigurationError(ValueError):
    pass


class SearchConsoleAnalyticsProviderError(ValueError):
    pass


@dataclass(frozen=True)
class SearchConsolePeriodMetrics:
    clicks: int
    impressions: int
    ctr: float
    average_position: float


@dataclass(frozen=True)
class SearchConsoleTopPageMetrics:
    page_path: str
    current_clicks: int
    previous_clicks: int
    current_impressions: int
    previous_impressions: int
    current_ctr: float
    previous_ctr: float
    current_average_position: float
    previous_average_position: float


@dataclass(frozen=True)
class SearchConsoleTopQueryMetrics:
    query: str
    clicks: int
    impressions: int
    ctr: float
    average_position: float


@dataclass(frozen=True)
class SearchConsoleSiteMetricsResult:
    current_period: SearchConsolePeriodMetrics
    previous_period: SearchConsolePeriodMetrics
    top_pages: tuple[SearchConsoleTopPageMetrics, ...]
    top_queries: tuple[SearchConsoleTopQueryMetrics, ...]
    data_source: str


class SearchConsoleAnalyticsProvider(Protocol):
    def is_configured(self) -> bool: ...

    def fetch_site_metrics(
        self,
        *,
        site_property: str,
        period_days: int,
        top_pages_limit: int,
        top_queries_limit: int,
    ) -> SearchConsoleSiteMetricsResult: ...

    def fetch_window_metrics(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> SearchConsolePeriodMetrics: ...

    def fetch_top_queries(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        query_limit: int,
        page_path: str | None = None,
    ) -> tuple[SearchConsoleTopQueryMetrics, ...]: ...


class DisabledSearchConsoleAnalyticsProvider:
    def is_configured(self) -> bool:
        return False

    def fetch_site_metrics(self, **_: object) -> SearchConsoleSiteMetricsResult:
        raise SearchConsoleAnalyticsProviderConfigurationError("Search Console analytics is not configured.")

    def fetch_window_metrics(self, **_: object) -> SearchConsolePeriodMetrics:
        raise SearchConsoleAnalyticsProviderConfigurationError("Search Console analytics is not configured.")

    def fetch_top_queries(self, **_: object) -> tuple[SearchConsoleTopQueryMetrics, ...]:
        raise SearchConsoleAnalyticsProviderConfigurationError("Search Console analytics is not configured.")


class MockSearchConsoleAnalyticsProvider:
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
        del period_days
        seed = sum(ord(character) for character in site_property.lower()) % 41
        current_clicks = 90 + (seed * 2)
        current_impressions = 2400 + (seed * 40)
        previous_clicks = max(0, current_clicks - 12)
        previous_impressions = max(0, current_impressions - 180)
        top_pages = tuple(
            SearchConsoleTopPageMetrics(
                page_path="/" if index == 0 else f"/services/{index}",
                current_clicks=max(1, current_clicks // (index + 2)),
                previous_clicks=max(0, previous_clicks // (index + 2)),
                current_impressions=max(1, current_impressions // (index + 2)),
                previous_impressions=max(0, previous_impressions // (index + 2)),
                current_ctr=_safe_ctr(max(1, current_clicks // (index + 2)), max(1, current_impressions // (index + 2))),
                previous_ctr=_safe_ctr(max(0, previous_clicks // (index + 2)), max(0, previous_impressions // (index + 2))),
                current_average_position=max(1.0, 8.5 + (index * 0.4)),
                previous_average_position=max(1.0, 9.3 + (index * 0.4)),
            )
            for index in range(max(1, min(int(top_pages_limit), 10)))
        )
        top_queries = tuple(
            SearchConsoleTopQueryMetrics(
                query=f"query {index + 1}",
                clicks=max(1, 30 + seed - (index * 3)),
                impressions=max(1, 420 + (seed * 10) - (index * 26)),
                ctr=_safe_ctr(max(1, 30 + seed - (index * 3)), max(1, 420 + (seed * 10) - (index * 26))),
                average_position=max(1.0, 10.0 + (index * 0.7)),
            )
            for index in range(max(1, min(int(top_queries_limit), 10)))
        )
        return SearchConsoleSiteMetricsResult(
            current_period=SearchConsolePeriodMetrics(
                clicks=current_clicks,
                impressions=current_impressions,
                ctr=_safe_ctr(current_clicks, current_impressions),
                average_position=8.4,
            ),
            previous_period=SearchConsolePeriodMetrics(
                clicks=previous_clicks,
                impressions=previous_impressions,
                ctr=_safe_ctr(previous_clicks, previous_impressions),
                average_position=9.1,
            ),
            top_pages=top_pages,
            top_queries=top_queries,
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
        seed = sum(ord(character) for character in f"{site_property}|{start_date}|{end_date}|{page_path or ''}") % 53
        base_clicks = 55 if page_path else 120
        base_impressions = 1400 if page_path else 3200
        clicks = max(0, base_clicks + seed)
        impressions = max(0, base_impressions + (seed * 19))
        return SearchConsolePeriodMetrics(
            clicks=clicks,
            impressions=impressions,
            ctr=_safe_ctr(clicks, impressions),
            average_position=max(1.0, 16.0 - (seed / 12)),
        )

    def fetch_top_queries(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        query_limit: int,
        page_path: str | None = None,
    ) -> tuple[SearchConsoleTopQueryMetrics, ...]:
        seed = sum(ord(character) for character in f"{site_property}|{start_date}|{end_date}|{page_path or ''}") % 29
        return tuple(
            SearchConsoleTopQueryMetrics(
                query=(f"page query {index + 1}" if page_path else f"query {index + 1}"),
                clicks=max(1, 30 + seed - (index * 3)),
                impressions=max(1, 420 + (seed * 10) - (index * 26)),
                ctr=_safe_ctr(max(1, 30 + seed - (index * 3)), max(1, 420 + (seed * 10) - (index * 26))),
                average_position=max(1.0, 10.0 + (index * 0.7) + (seed / 20)),
            )
            for index in range(max(1, min(int(query_limit), 10)))
        )


class GoogleSearchConsoleAPIClient:
    def __init__(
        self,
        *,
        site_property_url: str | None,
        timeout_seconds: int = 10,
        credentials_json: str | None = None,
        api_base_url: str = _DEFAULT_SEARCH_CONSOLE_API_BASE_URL,
    ) -> None:
        self.site_property_url = (site_property_url or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.credentials_json = (credentials_json or "").strip() or None
        self.api_base_url = (api_base_url or _DEFAULT_SEARCH_CONSOLE_API_BASE_URL).rstrip("/")
        self._credentials: Any | None = None
        self._auth_request: Any | None = None

    def is_configured(self) -> bool:
        return bool(self.site_property_url)

    def fetch_site_metrics(
        self,
        *,
        site_property: str,
        period_days: int,
        top_pages_limit: int,
        top_queries_limit: int,
    ) -> SearchConsoleSiteMetricsResult:
        bounded_days = max(1, min(int(period_days), 30))
        current_start = _days_ago_iso(bounded_days - 1)
        current_end = _days_ago_iso(0)
        previous_start = _days_ago_iso((bounded_days * 2) - 1)
        previous_end = _days_ago_iso(bounded_days)
        current_period = self.fetch_window_metrics(site_property=site_property, start_date=current_start, end_date=current_end)
        previous_period = self.fetch_window_metrics(site_property=site_property, start_date=previous_start, end_date=previous_end)
        top_pages = self._fetch_top_pages(
            site_property=site_property,
            current_start=current_start,
            current_end=current_end,
            previous_start=previous_start,
            previous_end=previous_end,
            top_pages_limit=max(1, min(int(top_pages_limit), 10)),
        )
        top_queries = self.fetch_top_queries(
            site_property=site_property,
            start_date=current_start,
            end_date=current_end,
            query_limit=max(1, min(int(top_queries_limit), 10)),
        )
        return SearchConsoleSiteMetricsResult(
            current_period=current_period,
            previous_period=previous_period,
            top_pages=top_pages,
            top_queries=top_queries,
            data_source="search_console_api",
        )

    def fetch_window_metrics(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        page_path: str | None = None,
    ) -> SearchConsolePeriodMetrics:
        if page_path:
            rows_payload = self._query(
                site_property=site_property,
                payload={"startDate": start_date, "endDate": end_date, "dimensions": ["page"], "rowLimit": 250},
            )
            target_path = _normalize_page_path(page_path)
            clicks = impressions = 0
            weighted_position = 0.0
            for row in rows_payload:
                page_value = _normalize_page_path(str((row.get("keys") or [""])[0] or ""))
                if page_value != target_path:
                    continue
                row_clicks = max(0, int(float(row.get("clicks", 0) or 0)))
                row_impressions = max(0, int(float(row.get("impressions", 0) or 0)))
                row_position = max(0.0, float(row.get("position", 0) or 0))
                clicks += row_clicks
                impressions += row_impressions
                weighted_position += row_position * row_impressions
            average_position = round(weighted_position / impressions, 4) if impressions > 0 else 0.0
            return SearchConsolePeriodMetrics(
                clicks=clicks,
                impressions=impressions,
                ctr=_safe_ctr(clicks, impressions),
                average_position=average_position,
            )
        rows = self._query(site_property=site_property, payload={"startDate": start_date, "endDate": end_date, "rowLimit": 1})
        row = rows[0] if rows else {}
        clicks = max(0, int(float(row.get("clicks", 0) or 0)))
        impressions = max(0, int(float(row.get("impressions", 0) or 0)))
        return SearchConsolePeriodMetrics(
            clicks=clicks,
            impressions=impressions,
            ctr=_safe_ctr(clicks, impressions),
            average_position=max(0.0, float(row.get("position", 0) or 0)),
        )

    def fetch_top_queries(
        self,
        *,
        site_property: str,
        start_date: str,
        end_date: str,
        query_limit: int,
        page_path: str | None = None,
    ) -> tuple[SearchConsoleTopQueryMetrics, ...]:
        bounded = max(1, min(int(query_limit), 10))
        if page_path:
            rows = self._query(
                site_property=site_property,
                payload={"startDate": start_date, "endDate": end_date, "dimensions": ["query", "page"], "rowLimit": max(50, bounded * 20)},
            )
            target_path = _normalize_page_path(page_path)
            aggregate: dict[str, tuple[int, int, float]] = {}
            for row in rows:
                keys = row.get("keys") or []
                if len(keys) < 2:
                    continue
                if _normalize_page_path(str(keys[1] or "")) != target_path:
                    continue
                query = str(keys[0] or "").strip()
                if not query:
                    continue
                clicks = max(0, int(float(row.get("clicks", 0) or 0)))
                impressions = max(0, int(float(row.get("impressions", 0) or 0)))
                weighted_position = max(0.0, float(row.get("position", 0) or 0)) * impressions
                existing = aggregate.get(query, (0, 0, 0.0))
                aggregate[query] = (existing[0] + clicks, existing[1] + impressions, existing[2] + weighted_position)
            sorted_items = sorted(aggregate.items(), key=lambda item: (item[1][0], item[1][1]), reverse=True)[:bounded]
            return tuple(
                SearchConsoleTopQueryMetrics(
                    query=query,
                    clicks=values[0],
                    impressions=values[1],
                    ctr=_safe_ctr(values[0], values[1]),
                    average_position=round(values[2] / values[1], 4) if values[1] > 0 else 0.0,
                )
                for query, values in sorted_items
            )
        rows = self._query(
            site_property=site_property,
            payload={"startDate": start_date, "endDate": end_date, "dimensions": ["query"], "rowLimit": bounded},
        )
        top_queries: list[SearchConsoleTopQueryMetrics] = []
        for row in rows:
            keys = row.get("keys") or []
            if not keys:
                continue
            query = str(keys[0] or "").strip()
            if not query:
                continue
            clicks = max(0, int(float(row.get("clicks", 0) or 0)))
            impressions = max(0, int(float(row.get("impressions", 0) or 0)))
            top_queries.append(
                SearchConsoleTopQueryMetrics(
                    query=query,
                    clicks=clicks,
                    impressions=impressions,
                    ctr=_safe_ctr(clicks, impressions),
                    average_position=max(0.0, float(row.get("position", 0) or 0)),
                )
            )
        return tuple(top_queries[:bounded])

    def _fetch_top_pages(
        self,
        *,
        site_property: str,
        current_start: str,
        current_end: str,
        previous_start: str,
        previous_end: str,
        top_pages_limit: int,
    ) -> tuple[SearchConsoleTopPageMetrics, ...]:
        current_rows = self._query(
            site_property=site_property,
            payload={"startDate": current_start, "endDate": current_end, "dimensions": ["page"], "rowLimit": top_pages_limit},
        )
        previous_rows = self._query(
            site_property=site_property,
            payload={"startDate": previous_start, "endDate": previous_end, "dimensions": ["page"], "rowLimit": top_pages_limit},
        )
        prev_by_path: dict[str, dict[str, Any]] = {}
        for row in previous_rows:
            keys = row.get("keys") or []
            if not keys:
                continue
            path = _normalize_page_path(str(keys[0] or ""))
            if path:
                prev_by_path[path] = row
        top_pages: list[SearchConsoleTopPageMetrics] = []
        for row in current_rows:
            keys = row.get("keys") or []
            if not keys:
                continue
            path = _normalize_page_path(str(keys[0] or ""))
            if not path:
                continue
            previous = prev_by_path.get(path, {})
            current_clicks = max(0, int(float(row.get("clicks", 0) or 0)))
            current_impressions = max(0, int(float(row.get("impressions", 0) or 0)))
            previous_clicks = max(0, int(float(previous.get("clicks", 0) or 0)))
            previous_impressions = max(0, int(float(previous.get("impressions", 0) or 0)))
            top_pages.append(
                SearchConsoleTopPageMetrics(
                    page_path=path,
                    current_clicks=current_clicks,
                    previous_clicks=previous_clicks,
                    current_impressions=current_impressions,
                    previous_impressions=previous_impressions,
                    current_ctr=_safe_ctr(current_clicks, current_impressions),
                    previous_ctr=_safe_ctr(previous_clicks, previous_impressions),
                    current_average_position=max(0.0, float(row.get("position", 0) or 0)),
                    previous_average_position=max(0.0, float(previous.get("position", 0) or 0)),
                )
            )
        return tuple(top_pages[:top_pages_limit])

    def _query(self, *, site_property: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        resolved_property = (site_property or self.site_property_url).strip()
        if not resolved_property:
            raise SearchConsoleAnalyticsProviderConfigurationError("Search Console site property URL is required.")
        token = self._resolve_access_token()
        request = Request(
            f"{self.api_base_url}/sites/{quote(resolved_property, safe='')}/searchAnalytics/query",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise SearchConsoleAnalyticsProviderConfigurationError(
                    "Search Console credentials or property access are not configured."
                ) from exc
            raise SearchConsoleAnalyticsProviderError("Search Console request failed.") from exc
        except TimeoutError as exc:
            raise SearchConsoleAnalyticsProviderError("Search Console request timed out.") from exc
        except URLError as exc:
            if isinstance(getattr(exc, "reason", None), socket.timeout):
                raise SearchConsoleAnalyticsProviderError("Search Console request timed out.") from exc
            raise SearchConsoleAnalyticsProviderError("Search Console endpoint unavailable.") from exc
        except OSError as exc:
            raise SearchConsoleAnalyticsProviderError("Search Console request failed.") from exc
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise SearchConsoleAnalyticsProviderError("Search Console response is not valid JSON.") from exc
        rows = body.get("rows") if isinstance(body, dict) else None
        return rows if isinstance(rows, list) else []

    def _resolve_access_token(self) -> str:
        credentials = self._get_credentials()
        request_adapter = self._get_auth_request()
        try:
            if not getattr(credentials, "valid", False):
                credentials.refresh(request_adapter)
            token = getattr(credentials, "token", None)
            if not token:
                raise SearchConsoleAnalyticsProviderConfigurationError(
                    "Search Console credentials did not return an access token."
                )
            return str(token)
        except SearchConsoleAnalyticsProviderConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SearchConsoleAnalyticsProviderConfigurationError(
                "Unable to authorize Search Console analytics request."
            ) from exc

    def _get_credentials(self):
        if self._credentials is not None:
            return self._credentials
        try:
            from google.auth import default as google_auth_default
            from google.auth.transport.requests import Request as GoogleAuthRequest
            from google.oauth2 import service_account
        except ImportError as exc:
            raise SearchConsoleAnalyticsProviderConfigurationError(
                "google-auth dependencies are required for Search Console analytics."
            ) from exc
        try:
            if self.credentials_json:
                info = json.loads(self.credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=[_SEARCH_CONSOLE_READONLY_SCOPE],
                )
            else:
                credentials, _ = google_auth_default(scopes=[_SEARCH_CONSOLE_READONLY_SCOPE])
            self._credentials = credentials
            self._auth_request = GoogleAuthRequest()
        except Exception as exc:  # noqa: BLE001
            raise SearchConsoleAnalyticsProviderConfigurationError(
                "Unable to initialize Search Console credentials."
            ) from exc
        return self._credentials

    def _get_auth_request(self):
        if self._auth_request is not None:
            return self._auth_request
        self._get_credentials()
        return self._auth_request


def _safe_ctr(clicks: int, impressions: int) -> float:
    if impressions <= 0:
        return 0.0
    return round((max(0, clicks) / impressions) * 100, 4)


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


def _days_ago_iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=max(0, int(days_ago)))).isoformat()

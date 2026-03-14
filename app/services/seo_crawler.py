from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import re
import socket


HTTP_SCHEMES = {"http", "https"}
PRIVATE_IPV4_PREFIXES = (
    "10.",
    "127.",
    "169.254.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",
)
PRIVATE_HOSTS = {"localhost", "::1"}


class SEOCrawlerValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FetchResponse:
    final_url: str
    status_code: int
    body: str


@dataclass(frozen=True)
class CrawlPageResult:
    requested_url: str
    final_url: str
    depth: int
    status_code: int
    body_text: str | None
    outgoing_internal_links: list[str]
    fetch_error: str | None


class SEOCrawler:
    def __init__(self, *, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def crawl(
        self,
        *,
        base_url: str,
        max_pages: int,
        max_depth: int,
        same_domain_only: bool = True,
    ) -> list[CrawlPageResult]:
        if max_pages <= 0:
            raise SEOCrawlerValidationError("max_pages must be > 0")
        if max_depth < 0:
            raise SEOCrawlerValidationError("max_depth must be >= 0")

        normalized_base_url = self.normalize_url(base_url)
        base_netloc = urlsplit(normalized_base_url).netloc
        if not base_netloc:
            raise SEOCrawlerValidationError("base_url must include a domain")

        queue: deque[tuple[str, int]] = deque([(normalized_base_url, 0)])
        seen_urls: set[str] = {normalized_base_url}
        crawled: list[CrawlPageResult] = []

        while queue and len(crawled) < max_pages:
            current_url, depth = queue.popleft()
            page = self._fetch_page(current_url, depth)
            crawled.append(page)

            if depth >= max_depth:
                continue
            if page.body_text is None:
                continue

            for candidate in page.outgoing_internal_links:
                normalized_candidate = self.normalize_url(candidate)
                parts = urlsplit(normalized_candidate)
                if parts.scheme not in HTTP_SCHEMES:
                    continue
                if same_domain_only and parts.netloc != base_netloc:
                    continue
                if normalized_candidate in seen_urls:
                    continue
                seen_urls.add(normalized_candidate)
                queue.append((normalized_candidate, depth + 1))

        return crawled

    def normalize_url(self, url: str) -> str:
        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in HTTP_SCHEMES:
            raise SEOCrawlerValidationError("Only http/https URLs are allowed")
        if not parsed.netloc:
            raise SEOCrawlerValidationError("URL must include a domain")

        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
            if not path:
                path = "/"

        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query = urlencode(sorted(query_pairs), doseq=True)
        return urlunsplit((scheme, netloc, path, query, ""))

    def _fetch_page(self, requested_url: str, depth: int) -> CrawlPageResult:
        try:
            response = self._fetch(requested_url)
            final_url = self.normalize_url(response.final_url)
            outgoing = self._extract_links(response.body, final_url)
            return CrawlPageResult(
                requested_url=requested_url,
                final_url=final_url,
                depth=depth,
                status_code=response.status_code,
                body_text=response.body,
                outgoing_internal_links=outgoing,
                fetch_error=None,
            )
        except Exception as exc:  # noqa: BLE001
            return CrawlPageResult(
                requested_url=requested_url,
                final_url=requested_url,
                depth=depth,
                status_code=0,
                body_text=None,
                outgoing_internal_links=[],
                fetch_error=str(exc),
            )

    def _fetch(self, url: str) -> FetchResponse:
        self._validate_resolvable_host(url)
        request = Request(
            url=url,
            headers={"User-Agent": "WorkBootsSEOAudit/1.0"},
            method="GET",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            final_url = self.normalize_url(response.geturl())
            self._validate_resolvable_host(final_url)
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200) or 200)
            return FetchResponse(final_url=final_url, status_code=status_code, body=body)

    def _validate_resolvable_host(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        host_lower = host.lower()
        if host_lower in PRIVATE_HOSTS:
            raise SEOCrawlerValidationError("Blocked host")

        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return

        for entry in addresses:
            address = entry[4][0]
            if any(address.startswith(prefix) for prefix in PRIVATE_IPV4_PREFIXES):
                raise SEOCrawlerValidationError("Blocked private network host")
            if address == "::1":
                raise SEOCrawlerValidationError("Blocked loopback host")
            if address.lower().startswith("fe80:"):
                raise SEOCrawlerValidationError("Blocked link-local host")

    def _extract_links(self, html: str, page_url: str) -> list[str]:
        href_pattern = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)
        links: list[str] = []
        for raw_href in href_pattern.findall(html):
            href = unescape(raw_href.strip())
            if not href:
                continue
            absolute = urljoin(page_url, href)
            try:
                normalized = self.normalize_url(absolute)
            except SEOCrawlerValidationError:
                continue
            links.append(normalized)
        return links

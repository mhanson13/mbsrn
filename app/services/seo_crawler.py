from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from collections import deque
from dataclasses import dataclass
from html import unescape
import re
import socket
import time
from ipaddress import ip_address
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


HTTP_SCHEMES = {"http", "https"}
PRIVATE_HOSTS = {"localhost", "::1"}
DEFAULT_INDEX_PATHS = {"/index.html", "/index.htm", "/index.php", "/default.aspx"}
TRANSIENT_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
IGNORED_QUERY_PARAMS = {"gclid", "fbclid", "msclkid", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}


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


@dataclass(frozen=True)
class CrawlStats:
    pages_discovered: int
    pages_skipped: int
    duplicate_urls_skipped: int
    errors_encountered: int


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, *, max_redirects: int, validate_redirect_url) -> None:  # noqa: ANN001
        super().__init__()
        self.max_redirections = max_redirects
        self._validate_redirect_url = validate_redirect_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        self._validate_redirect_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SEOCrawler:
    def __init__(
        self,
        *,
        timeout_seconds: int = 8,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        max_redirects: int = 5,
        max_response_bytes: int = 1_000_000,
        max_workers: int = 4,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self.max_workers = max(1, max_workers)
        self.last_crawl_stats: CrawlStats | None = None

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
        base_host = urlsplit(normalized_base_url).hostname or ""
        base_scheme = urlsplit(normalized_base_url).scheme
        if not base_netloc:
            raise SEOCrawlerValidationError("base_url must include a domain")

        queue: deque[tuple[str, int]] = deque([(normalized_base_url, 0)])
        seen_urls: set[str] = {normalized_base_url}
        crawled: list[CrawlPageResult] = []
        pages_discovered = 1
        pages_skipped = 0
        duplicate_urls_skipped = 0
        errors_encountered = 0

        while queue and len(crawled) < max_pages:
            current_depth = queue[0][1]
            current_batch: list[tuple[str, int]] = []
            while queue and queue[0][1] == current_depth and len(crawled) + len(current_batch) < max_pages:
                current_batch.append(queue.popleft())
            current_batch.sort(key=lambda item: self._url_priority_key(item[0]))
            batch_pages = self._fetch_batch(current_batch)

            for page in batch_pages:
                crawled.append(page)
                if page.fetch_error is not None:
                    errors_encountered += 1

                if page.depth >= max_depth:
                    continue
                if page.body_text is None:
                    continue

                next_depth_links: list[str] = []
                for candidate in page.outgoing_internal_links:
                    try:
                        normalized_candidate = self.normalize_url(
                            candidate,
                            preferred_scheme=base_scheme if same_domain_only else None,
                            preferred_host=base_host if same_domain_only else None,
                        )
                    except SEOCrawlerValidationError:
                        pages_skipped += 1
                        continue
                    parts = urlsplit(normalized_candidate)
                    if parts.scheme not in HTTP_SCHEMES:
                        pages_skipped += 1
                        continue
                    if same_domain_only and parts.netloc != base_netloc:
                        pages_skipped += 1
                        continue
                    if normalized_candidate in seen_urls:
                        duplicate_urls_skipped += 1
                        continue
                    seen_urls.add(normalized_candidate)
                    pages_discovered += 1
                    next_depth_links.append(normalized_candidate)

                for normalized_candidate in sorted(next_depth_links, key=self._url_priority_key):
                    queue.append((normalized_candidate, page.depth + 1))

        if queue:
            pages_skipped += len(queue)

        self.last_crawl_stats = CrawlStats(
            pages_discovered=pages_discovered,
            pages_skipped=pages_skipped,
            duplicate_urls_skipped=duplicate_urls_skipped,
            errors_encountered=errors_encountered,
        )
        return crawled

    def _fetch_batch(self, batch: list[tuple[str, int]]) -> list[CrawlPageResult]:
        if not batch:
            return []
        if self.max_workers <= 1 or len(batch) == 1:
            return [self._fetch_page(url, depth) for url, depth in batch]

        results: list[CrawlPageResult | None] = [None] * len(batch)
        worker_count = min(self.max_workers, len(batch))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures: dict[Future[CrawlPageResult], int] = {}
            for idx, (url, depth) in enumerate(batch):
                futures[executor.submit(self._fetch_page, url, depth)] = idx
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()
        return [result for result in results if result is not None]

    def normalize_url(
        self,
        url: str,
        *,
        preferred_scheme: str | None = None,
        preferred_host: str | None = None,
    ) -> str:
        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in HTTP_SCHEMES:
            raise SEOCrawlerValidationError("Only http/https URLs are allowed")
        host = (parsed.hostname or "").lower()
        if not host:
            raise SEOCrawlerValidationError("URL must include a domain")

        if preferred_scheme and preferred_host and host == preferred_host.lower():
            preferred = preferred_scheme.lower().strip()
            if preferred in HTTP_SCHEMES:
                scheme = preferred

        try:
            port = parsed.port
        except ValueError as exc:
            raise SEOCrawlerValidationError("URL contains an invalid port") from exc
        netloc = host
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"{host}:{port}"

        path = re.sub(r"/+", "/", parsed.path or "/")
        if not path.startswith("/"):
            path = f"/{path}"
        if path.lower() in DEFAULT_INDEX_PATHS:
            path = "/"
        if path != "/":
            path = path.rstrip("/")
            if not path:
                path = "/"

        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_pairs = [(key, value) for key, value in query_pairs if key.lower() not in IGNORED_QUERY_PARAMS]
        deduplicated_pairs = sorted(set(query_pairs))
        query = urlencode(deduplicated_pairs, doseq=True)
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
        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._fetch_once(url)
            except HTTPError as exc:
                if exc.code in TRANSIENT_HTTP_STATUS_CODES and attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                return self._http_error_to_response(exc=exc, original_url=url)
            except (URLError, TimeoutError, socket.timeout) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                break

        message = "Request failed after retries"
        if last_exception is not None:
            message = f"{message}: {last_exception}"
        raise SEOCrawlerValidationError(message)

    def _fetch_once(self, url: str) -> FetchResponse:
        self._validate_resolvable_host(url)
        request = Request(
            url=url,
            headers={
                "User-Agent": "WorkBootsSEOAudit/1.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        redirect_handler = _ValidatingRedirectHandler(
            max_redirects=self.max_redirects,
            validate_redirect_url=self._validate_resolvable_host,
        )
        opener = build_opener(redirect_handler)
        with opener.open(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            final_url = self.normalize_url(response.geturl())
            self._validate_resolvable_host(final_url)
            body = self._decode_response_body(response)
            status_code = int(getattr(response, "status", 200) or 200)
            return FetchResponse(final_url=final_url, status_code=status_code, body=body)

    def _http_error_to_response(self, *, exc: HTTPError, original_url: str) -> FetchResponse:
        final_url = self.normalize_url(exc.geturl() or original_url)
        self._validate_resolvable_host(final_url)
        body = self._decode_response_body(exc)
        status_code = int(exc.code or 0)
        return FetchResponse(final_url=final_url, status_code=status_code, body=body)

    def _decode_response_body(self, response) -> str:  # noqa: ANN001
        raw_body = self._read_limited_body_bytes(response)
        if not raw_body:
            return ""
        content_type = ((getattr(response, "headers", None) or {}).get("Content-Type") or "").lower()
        if content_type and "html" not in content_type and "xml" not in content_type:
            return ""
        return raw_body.decode("utf-8", errors="replace")

    def _read_limited_body_bytes(self, response) -> bytes:  # noqa: ANN001
        headers = getattr(response, "headers", None)
        if headers is not None:
            content_length = headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > self.max_response_bytes:
                        raise SEOCrawlerValidationError("Response body exceeds size limit")
                except ValueError:
                    pass

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_response_bytes:
                raise SEOCrawlerValidationError("Response body exceeds size limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = self.retry_backoff_seconds * (attempt + 1)
        if delay > 0:
            time.sleep(delay)

    def _validate_resolvable_host(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        host_lower = host.lower()
        if not host_lower:
            raise SEOCrawlerValidationError("Blocked host")
        if host_lower in PRIVATE_HOSTS:
            raise SEOCrawlerValidationError("Blocked host")

        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return

        for entry in addresses:
            address = entry[4][0]
            try:
                parsed_ip = ip_address(address)
            except ValueError:
                continue

            if parsed_ip.is_loopback:
                raise SEOCrawlerValidationError("Blocked loopback host")
            if parsed_ip.is_private:
                raise SEOCrawlerValidationError("Blocked private network host")
            if parsed_ip.is_link_local:
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

    @staticmethod
    def _url_priority_key(url: str) -> tuple[int, str]:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        return (len(path), f"{path}?{parsed.query}")

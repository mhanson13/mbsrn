from __future__ import annotations

import io
import threading
import time
from urllib.error import URLError

import pytest

from app.services.seo_crawler import FetchResponse, SEOCrawler, SEOCrawlerValidationError


class _FakeCrawler(SEOCrawler):
    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        super().__init__(timeout_seconds=1)
        self.pages = pages
        self.requested: list[str] = []

    def _fetch(self, url: str) -> FetchResponse:  # type: ignore[override]
        self.requested.append(url)
        return self.pages[url]


class _RetryCrawler(SEOCrawler):
    def __init__(self) -> None:
        super().__init__(timeout_seconds=1, max_retries=2, retry_backoff_seconds=0)
        self.attempts = 0

    def _fetch_once(self, url: str) -> FetchResponse:  # type: ignore[override]
        self.attempts += 1
        if self.attempts < 3:
            raise URLError("temporary upstream failure")
        return FetchResponse(final_url=url, status_code=200, body="<html><body>ok</body></html>")


def test_crawler_is_bounded_and_same_domain_only() -> None:
    pages = {
        "https://example.com/": FetchResponse(
            final_url="https://example.com/",
            status_code=200,
            body=(
                '<a href="/a">A</a>'
                '<a href="/b?x=1&y=2">B1</a>'
                '<a href="https://external.example/page">EXT</a>'
                '<a href="ftp://example.com/file.txt">FTP</a>'
            ),
        ),
        "https://example.com/a": FetchResponse(
            final_url="https://example.com/a",
            status_code=200,
            body='<a href="/b?y=2&x=1">B2</a><a href="/c">C</a>',
        ),
        "https://example.com/b?x=1&y=2": FetchResponse(
            final_url="https://example.com/b?x=1&y=2",
            status_code=200,
            body="<p>page b</p>",
        ),
        "https://example.com/c": FetchResponse(
            final_url="https://example.com/c",
            status_code=200,
            body="<p>page c</p>",
        ),
    }
    crawler = _FakeCrawler(pages)

    limited = crawler.crawl(
        base_url="https://example.com/",
        max_pages=2,
        max_depth=3,
        same_domain_only=True,
    )
    assert len(limited) == 2
    assert all(item.final_url.startswith("https://example.com/") for item in limited)

    full = crawler.crawl(
        base_url="https://example.com/",
        max_pages=10,
        max_depth=3,
        same_domain_only=True,
    )
    crawled_urls = [item.final_url for item in full]
    assert "https://example.com/b?x=1&y=2" in crawled_urls
    assert crawled_urls.count("https://example.com/b?x=1&y=2") == 1
    assert crawler.last_crawl_stats is not None
    assert crawler.last_crawl_stats.duplicate_urls_skipped >= 1


def test_url_normalization_handles_index_fragments_and_duplicate_query_items() -> None:
    crawler = SEOCrawler()

    normalized = crawler.normalize_url("https://Example.com/index.html?a=1&a=1&b=2#frag")
    assert normalized == "https://example.com/?a=1&b=2"

    normalized_slash = crawler.normalize_url("https://example.com/services/")
    assert normalized_slash == "https://example.com/services"

    preferred_scheme = crawler.normalize_url(
        "http://example.com/services//fire///",
        preferred_scheme="https",
        preferred_host="example.com",
    )
    assert preferred_scheme == "https://example.com/services/fire"

    tracking_cleaned = crawler.normalize_url(
        "https://example.com/service?utm_source=google&a=1&gclid=abc&a=1",
    )
    assert tracking_cleaned == "https://example.com/service?a=1"


def test_crawler_retries_transient_failures() -> None:
    crawler = _RetryCrawler()
    result = crawler.crawl(
        base_url="https://example.com/",
        max_pages=1,
        max_depth=1,
        same_domain_only=True,
    )
    assert len(result) == 1
    assert crawler.attempts == 3


def test_crawler_enforces_response_size_limit() -> None:
    crawler = SEOCrawler(max_response_bytes=16)

    class _LargeResponse:
        headers = {"Content-Length": "1024"}

        def __init__(self) -> None:
            self._stream = io.BytesIO(b"<html>" + (b"a" * 1000) + b"</html>")

        def read(self, size: int) -> bytes:  # noqa: ARG002
            return self._stream.read(size)

    with pytest.raises(SEOCrawlerValidationError):
        crawler._read_limited_body_bytes(_LargeResponse())


def test_crawler_parallel_fetch_is_bounded_and_deterministic() -> None:
    class _ConcurrentCrawler(SEOCrawler):
        def __init__(self) -> None:
            super().__init__(timeout_seconds=1, max_workers=3)
            self._active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def _fetch_page(self, requested_url: str, depth: int):  # type: ignore[override]
            with self.lock:
                self._active += 1
                if self._active > self.max_active:
                    self.max_active = self._active
            try:
                time.sleep(0.02)
                return super()._fetch_page(requested_url, depth)
            finally:
                with self.lock:
                    self._active -= 1

        def _fetch(self, url: str) -> FetchResponse:  # type: ignore[override]
            if url == "https://example.com/":
                body = "".join(f'<a href="/page-{i}">x</a>' for i in range(6))
                return FetchResponse(final_url=url, status_code=200, body=body)
            return FetchResponse(final_url=url, status_code=200, body="<html><body>ok</body></html>")

    crawler = _ConcurrentCrawler()
    results = crawler.crawl(
        base_url="https://example.com/",
        max_pages=7,
        max_depth=2,
        same_domain_only=True,
    )
    assert len(results) == 7
    assert crawler.max_active <= 3
    assert crawler.max_active > 1

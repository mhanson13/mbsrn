from __future__ import annotations

import pytest

from app.services import seo_crawler as seo_crawler_module
from app.services.seo_crawler import SEOCrawler, SEOCrawlerValidationError


def test_non_http_schemes_are_rejected() -> None:
    crawler = SEOCrawler()
    with pytest.raises(SEOCrawlerValidationError):
        crawler.normalize_url("file:///etc/passwd")
    with pytest.raises(SEOCrawlerValidationError):
        crawler.normalize_url("ftp://example.com/file.txt")


def test_ssrf_block_matrix_for_local_and_private_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = SEOCrawler()

    with pytest.raises(SEOCrawlerValidationError):
        crawler._validate_resolvable_host("http://localhost/")
    with pytest.raises(SEOCrawlerValidationError):
        crawler._validate_resolvable_host("http://127.0.0.1/")

    def _fake_getaddrinfo(host, port):  # noqa: ANN001, ANN202
        mapping = {
            "private.example": [("x", "y", "z", "w", ("10.1.2.3", 0))],
            "linklocal.example": [("x", "y", "z", "w", ("169.254.1.10", 0))],
            "private192.example": [("x", "y", "z", "w", ("192.168.1.20", 0))],
            "private172.example": [("x", "y", "z", "w", ("172.16.5.8", 0))],
            "linklocalv6.example": [("x", "y", "z", "w", ("fe80::1", 0))],
            "carriergrade.example": [("x", "y", "z", "w", ("100.64.1.20", 0))],
            "multicast.example": [("x", "y", "z", "w", ("224.0.0.5", 0))],
            "unspecified.example": [("x", "y", "z", "w", ("0.0.0.0", 0))],
            "documentation.example": [("x", "y", "z", "w", ("198.51.100.20", 0))],
        }
        return mapping[host]

    monkeypatch.setattr(seo_crawler_module.socket, "getaddrinfo", _fake_getaddrinfo)

    for host in [
        "private.example",
        "linklocal.example",
        "private192.example",
        "private172.example",
        "linklocalv6.example",
        "carriergrade.example",
        "multicast.example",
        "unspecified.example",
        "documentation.example",
    ]:
        with pytest.raises(SEOCrawlerValidationError):
            crawler._validate_resolvable_host(f"https://{host}/")


def test_unresolvable_hosts_are_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = SEOCrawler()

    def _raise_gaierror(host, port):  # noqa: ANN001, ANN202
        raise seo_crawler_module.socket.gaierror("name resolution failed")

    monkeypatch.setattr(seo_crawler_module.socket, "getaddrinfo", _raise_gaierror)

    with pytest.raises(SEOCrawlerValidationError):
        crawler._validate_resolvable_host("https://does-not-resolve.invalid/")


def test_redirects_cannot_bypass_ssrf_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RedirectGuardCrawler(SEOCrawler):
        def _validate_resolvable_host(self, url: str) -> None:  # type: ignore[override]
            if "127.0.0.1" in url:
                raise SEOCrawlerValidationError("Blocked host")

    class _FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html"}

        def geturl(self) -> str:
            return "http://127.0.0.1/internal"

        def read(self) -> bytes:
            return b"redirect target body"

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

    class _FakeOpener:
        def open(self, request, timeout=8):  # noqa: ANN001, ARG002
            return _FakeResponse()

    monkeypatch.setattr(seo_crawler_module, "build_opener", lambda *args, **kwargs: _FakeOpener())

    crawler = _RedirectGuardCrawler(timeout_seconds=1)
    with pytest.raises(SEOCrawlerValidationError):
        crawler._fetch("https://example.com/")

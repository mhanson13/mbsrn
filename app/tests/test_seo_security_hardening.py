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
        }
        return mapping[host]

    monkeypatch.setattr(seo_crawler_module.socket, "getaddrinfo", _fake_getaddrinfo)

    for host in [
        "private.example",
        "linklocal.example",
        "private192.example",
        "private172.example",
        "linklocalv6.example",
    ]:
        with pytest.raises(SEOCrawlerValidationError):
            crawler._validate_resolvable_host(f"https://{host}/")


def test_redirects_cannot_bypass_ssrf_protection(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RedirectGuardCrawler(SEOCrawler):
        def _validate_resolvable_host(self, url: str) -> None:  # type: ignore[override]
            if "127.0.0.1" in url:
                raise SEOCrawlerValidationError("Blocked host")

    class _FakeResponse:
        status = 200

        def geturl(self) -> str:
            return "http://127.0.0.1/internal"

        def read(self) -> bytes:
            return b"redirect target body"

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

    monkeypatch.setattr(
        seo_crawler_module,
        "urlopen",
        lambda request, timeout=8: _FakeResponse(),  # noqa: ARG005
    )

    crawler = _RedirectGuardCrawler(timeout_seconds=1)
    with pytest.raises(SEOCrawlerValidationError):
        crawler._fetch("https://example.com/")

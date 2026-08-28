from __future__ import annotations

import urllib.request

import pytest

from app.services.seo_migration_ingest import SEOMigrationSourceIngestError, SEOMigrationSourceIngestService


class _FakeResponse:
    def __init__(
        self,
        *,
        content_type: str,
        body: str | bytes,
        final_url: str,
        status_code: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        headers = {"Content-Type": content_type}
        if extra_headers:
            headers.update(extra_headers)
        self.headers = headers
        self.url = final_url
        self.status = status_code
        self._body = payload
        self._offset = 0

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: ANN001
        return False

    def read(self, amount: int = -1) -> bytes:
        if amount <= 0:
            amount = len(self._body) - self._offset
        if self._offset >= len(self._body):
            return b""
        start = self._offset
        end = min(len(self._body), start + amount)
        self._offset = end
        return self._body[start:end]


class _RouteOpener:
    def __init__(self, routes: dict[tuple[str, str], _FakeResponse | Exception]) -> None:
        self.routes = routes

    def open(self, request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        method = request.get_method().upper()
        key = (method, request.full_url)
        route = self.routes.get(key)
        if route is None:
            raise AssertionError(f"Unexpected request: {method} {request.full_url}")
        if isinstance(route, Exception):
            raise route
        # Create a fresh response object each call.
        return _FakeResponse(
            content_type=str(route.headers.get("Content-Type") or "text/html"),
            body=route._body,  # noqa: SLF001
            final_url=route.url,
            status_code=route.status,
            extra_headers={k: v for k, v in route.headers.items() if k.lower() != "content-type"},
        )


def _install_routes(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[tuple[str, str], _FakeResponse | Exception],
) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _RouteOpener(routes))


def _html_response(*, url: str, body: str) -> _FakeResponse:
    return _FakeResponse(
        content_type="text/html; charset=utf-8",
        body=body,
        final_url=url,
    )


def _image_head_response(*, url: str, content_type: str = "image/jpeg", content_length: int = 12345) -> _FakeResponse:
    return _FakeResponse(
        content_type=content_type,
        body=b"",
        final_url=url,
        extra_headers={"Content-Length": str(content_length)},
    )


def test_ingest_extracts_homepage_signals_and_scans_priority_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    homepage_html = """
    <html>
      <head>
        <title>TNM Fire Protection</title>
        <meta name="description" content="Local fire protection installation and inspection." />
      </head>
      <body>
        <h1>Fire Protection Services</h1>
        <p>Phone: (303) 555-0110</p>
        <p>Email: info@tnmfire.example</p>
        <a href="/services">Services</a>
        <a href="/projects">Projects</a>
        <img src="/images/logo.png" />
      </body>
    </html>
    """
    services_html = """
    <html><body><h1>Services</h1><img src="/images/service-1.jpg" /></body></html>
    """
    projects_html = """
    <html><body><h1>Projects</h1><img src="/images/project-1.jpg" /></body></html>
    """
    routes = {
        ("GET", "https://tnmfire.example/"): _html_response(url="https://tnmfire.example/", body=homepage_html),
        ("GET", "https://tnmfire.example/services"): _html_response(
            url="https://tnmfire.example/services",
            body=services_html,
        ),
        ("GET", "https://tnmfire.example/projects"): _html_response(
            url="https://tnmfire.example/projects",
            body=projects_html,
        ),
        ("HEAD", "https://tnmfire.example/images/logo.png"): _image_head_response(
            url="https://tnmfire.example/images/logo.png",
            content_type="image/png",
        ),
        ("HEAD", "https://tnmfire.example/images/service-1.jpg"): _image_head_response(
            url="https://tnmfire.example/images/service-1.jpg",
        ),
        ("HEAD", "https://tnmfire.example/images/project-1.jpg"): _image_head_response(
            url="https://tnmfire.example/images/project-1.jpg",
        ),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService(max_discovery_pages=8)
    result = service.ingest_homepage(source_url="https://tnmfire.example")
    snapshot = result.snapshot

    assert snapshot["title"] == "TNM Fire Protection"
    assert any("555-0110" in phone for phone in snapshot["phone_numbers"])
    assert "info@tnmfire.example" in snapshot["emails"]
    assert "https://tnmfire.example/services" in snapshot["internal_links"]
    assert snapshot.get("pages_scanned_count") == 3
    assert "https://tnmfire.example/projects" in (snapshot.get("pages_scanned") or [])
    assert "https://tnmfire.example/services" in (snapshot.get("pages_scanned") or [])

    discovered = snapshot.get("discovered_images")
    assert isinstance(discovered, list)
    by_url = {str(item.get("normalized_url")): item for item in discovered if isinstance(item, dict)}
    assert "https://tnmfire.example/images/logo.png" in by_url
    assert "https://tnmfire.example/images/service-1.jpg" in by_url
    assert "https://tnmfire.example/images/project-1.jpg" in by_url
    assert (
        by_url["https://tnmfire.example/images/service-1.jpg"].get("source_page_url")
        == "https://tnmfire.example/services"
    )


def test_ingest_rejects_non_html_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        ("GET", "https://tnmfire.example/"): _FakeResponse(
            content_type="application/json",
            body='{"ok":true}',
            final_url="https://tnmfire.example/",
        ),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService()
    with pytest.raises(SEOMigrationSourceIngestError, match="HTML document"):
        service.ingest_homepage(source_url="https://tnmfire.example")


def test_ingest_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<html><body>" + ("A" * 20_000) + "</body></html>"
    routes = {
        ("GET", "https://tnmfire.example/"): _html_response(url="https://tnmfire.example/", body=html),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService(max_response_bytes=10_000)
    with pytest.raises(SEOMigrationSourceIngestError, match="size limit"):
        service.ingest_homepage(source_url="https://tnmfire.example")


def test_ingest_discovers_images_from_img_srcset_meta_lazy_and_style(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://tnmfire.example/media/hero.jpg?token=abc" />
        <meta name="twitter:image" content="/media/twitter-card.jpg?signature=123" />
      </head>
      <body>
        <img src="/images/logo.png?cache=1" />
        <img data-src="/images/lazy.jpg?cache=2" />
        <img srcset="/images/gallery-1.jpg 1x, /images/gallery-2.jpg 2x" />
        <picture>
          <source srcset="/images/gallery-2.jpg 1x, /images/gallery-3.jpg 2x" />
        </picture>
        <div style="background-image:url('/images/background-hero.jpg')"></div>
      </body>
    </html>
    """
    routes: dict[tuple[str, str], _FakeResponse | Exception] = {
        ("GET", "https://tnmfire.example/"): _html_response(url="https://tnmfire.example/", body=html),
    }
    for url in (
        "https://tnmfire.example/images/logo.png",
        "https://tnmfire.example/images/lazy.jpg",
        "https://tnmfire.example/images/gallery-1.jpg",
        "https://tnmfire.example/images/gallery-2.jpg",
        "https://tnmfire.example/images/gallery-3.jpg",
        "https://tnmfire.example/images/background-hero.jpg",
        "https://tnmfire.example/media/hero.jpg",
        "https://tnmfire.example/media/twitter-card.jpg",
    ):
        routes[("HEAD", url)] = _image_head_response(url=url, content_type="image/jpeg")
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService()
    result = service.ingest_homepage(source_url="https://tnmfire.example")
    discovered = result.snapshot.get("discovered_images")
    assert isinstance(discovered, list)

    normalized_urls = {str(item.get("normalized_url")) for item in discovered if isinstance(item, dict)}
    assert "https://tnmfire.example/images/logo.png" in normalized_urls
    assert "https://tnmfire.example/images/lazy.jpg" in normalized_urls
    assert "https://tnmfire.example/images/gallery-1.jpg" in normalized_urls
    assert "https://tnmfire.example/images/gallery-2.jpg" in normalized_urls
    assert "https://tnmfire.example/images/gallery-3.jpg" in normalized_urls
    assert "https://tnmfire.example/images/background-hero.jpg" in normalized_urls
    assert "https://tnmfire.example/media/hero.jpg" in normalized_urls
    assert "https://tnmfire.example/media/twitter-card.jpg" in normalized_urls


def test_ingest_rejects_non_image_route_candidates_like_mobile_path(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <body>
        <img src="/m" />
        <img src="/images/real-project.jpg" />
      </body>
    </html>
    """
    routes = {
        ("GET", "https://lars-construction.example/"): _html_response(
            url="https://lars-construction.example/",
            body=html,
        ),
        ("HEAD", "https://lars-construction.example/m"): _FakeResponse(
            content_type="text/html; charset=utf-8",
            body="<html><body>mobile route</body></html>",
            final_url="https://lars-construction.example/m",
        ),
        ("GET", "https://lars-construction.example/m"): _FakeResponse(
            content_type="text/html; charset=utf-8",
            body="<html><body>mobile route</body></html>",
            final_url="https://lars-construction.example/m",
        ),
        ("HEAD", "https://lars-construction.example/images/real-project.jpg"): _image_head_response(
            url="https://lars-construction.example/images/real-project.jpg",
            content_type="image/jpeg",
        ),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService()
    result = service.ingest_homepage(source_url="https://lars-construction.example")
    discovered = result.snapshot.get("discovered_images")
    assert isinstance(discovered, list)

    by_url = {str(item.get("normalized_url")): item for item in discovered if isinstance(item, dict)}
    assert by_url["https://lars-construction.example/m"].get("candidate_quality") == "rejected"
    assert by_url["https://lars-construction.example/m"].get("quality_reason") == "non_image_candidate_detected"
    assert by_url["https://lars-construction.example/images/real-project.jpg"].get("candidate_quality") == "useful"


def test_ingest_respects_discovery_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    homepage_html = """
    <html><body>
      <a href="/projects">Projects</a>
      <a href="/services">Services</a>
    </body></html>
    """
    projects_html = """<html><body><img src="/images/project-a.jpg" /></body></html>"""
    services_html = """<html><body><img src="/images/service-a.jpg" /></body></html>"""
    routes = {
        ("GET", "https://bounded.example/"): _html_response(url="https://bounded.example/", body=homepage_html),
        ("GET", "https://bounded.example/projects"): _html_response(
            url="https://bounded.example/projects",
            body=projects_html,
        ),
        ("GET", "https://bounded.example/services"): _html_response(
            url="https://bounded.example/services",
            body=services_html,
        ),
        ("HEAD", "https://bounded.example/images/project-a.jpg"): _image_head_response(
            url="https://bounded.example/images/project-a.jpg",
            content_type="image/jpeg",
        ),
        ("HEAD", "https://bounded.example/images/service-a.jpg"): _image_head_response(
            url="https://bounded.example/images/service-a.jpg",
            content_type="image/jpeg",
        ),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService(max_discovery_pages=2)
    result = service.ingest_homepage(source_url="https://bounded.example")
    snapshot = result.snapshot

    assert snapshot.get("pages_scanned_count") == 2
    pages_scanned = snapshot.get("pages_scanned") or []
    assert isinstance(pages_scanned, list)
    assert "https://bounded.example/" in pages_scanned
    assert len(pages_scanned) == 2


def test_ingest_uses_get_probe_when_head_is_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """<html><body><img src="/images/fallback-validated.jpg" /></body></html>"""
    routes = {
        ("GET", "https://fallback.example/"): _html_response(url="https://fallback.example/", body=html),
        (
            "HEAD",
            "https://fallback.example/images/fallback-validated.jpg",
        ): urllib.error.HTTPError(
            "https://fallback.example/images/fallback-validated.jpg",
            405,
            "Method Not Allowed",
            {},
            None,
        ),
        ("GET", "https://fallback.example/images/fallback-validated.jpg"): _FakeResponse(
            content_type="image/jpeg",
            body=b"\xff\xd8\xff",
            final_url="https://fallback.example/images/fallback-validated.jpg",
        ),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService()
    result = service.ingest_homepage(source_url="https://fallback.example")
    discovered = result.snapshot.get("discovered_images")
    assert isinstance(discovered, list)
    candidate = next(
        (
            item
            for item in discovered
            if isinstance(item, dict)
            and item.get("normalized_url") == "https://fallback.example/images/fallback-validated.jpg"
        ),
        None,
    )
    assert isinstance(candidate, dict)
    assert candidate.get("candidate_quality") == "useful"
    assert candidate.get("fetch_status") == "validated_get"
    assert candidate.get("content_type") == "image/jpeg"


def test_ingest_dedupes_wsimg_variant_urls_by_canonical_asset_key(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <body>
        <img src="https://img1.wsimg.com/isteam/ip/abc123/22222.jpg/:/rs=w:400,cg:true,m" />
        <img src="https://img1.wsimg.com/isteam/ip/abc123/22222.jpg/:/rs=w:1200,cg:true,m" />
      </body>
    </html>
    """
    routes = {
        ("GET", "https://legacy.example/"): _html_response(url="https://legacy.example/", body=html),
        ("HEAD", "https://img1.wsimg.com/isteam/ip/abc123/22222.jpg/:/rs=w:400,cg:true,m"): _image_head_response(
            url="https://img1.wsimg.com/isteam/ip/abc123/22222.jpg/:/rs=w:400,cg:true,m",
            content_type="image/jpeg",
        ),
    }
    _install_routes(monkeypatch, routes)

    service = SEOMigrationSourceIngestService()
    result = service.ingest_homepage(source_url="https://legacy.example")
    discovered = result.snapshot.get("discovered_images")
    assert isinstance(discovered, list)
    assert len(discovered) == 1

    candidate = discovered[0]
    assert candidate.get("candidate_quality") == "useful"
    assert str(candidate.get("canonical_image_key", "")).endswith("/isteam/ip/abc123/22222.jpg")


def test_ingest_rejects_private_or_local_source_hosts() -> None:
    service = SEOMigrationSourceIngestService()
    with pytest.raises(SEOMigrationSourceIngestError, match="host is not allowed"):
        service.ingest_homepage(source_url="http://localhost:8080")
    with pytest.raises(SEOMigrationSourceIngestError, match="host is not allowed"):
        service.ingest_homepage(source_url="http://169.254.169.254/latest/meta-data/")

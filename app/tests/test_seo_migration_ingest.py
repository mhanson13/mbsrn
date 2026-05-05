from __future__ import annotations

import urllib.request

import pytest

from app.services.seo_migration_ingest import SEOMigrationSourceIngestError, SEOMigrationSourceIngestService


class _FakeResponse:
    def __init__(
        self,
        *,
        content_type: str,
        body: str,
        final_url: str,
        status_code: int = 200,
    ) -> None:
        self.headers = {"Content-Type": content_type}
        self.url = final_url
        self.status = status_code
        self._body = body.encode("utf-8")
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


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    def open(self, request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        return self.response


def test_ingest_extracts_homepage_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <head>
        <title>TNM Fire Protection</title>
        <meta name="description" content="Local fire protection installation and inspection." />
        <link rel="canonical" href="https://tnmfire.example/" />
        <link rel="stylesheet" href="/styles/site.css" />
        <script src="/assets/app.js"></script>
      </head>
      <body>
        <h1>Fire Protection Services</h1>
        <h2>Installation and Inspection</h2>
        <p>Call us now for a quote and schedule service.</p>
        <p>Phone: (303) 555-0110</p>
        <p>Email: info@tnmfire.example</p>
        <p>123 Main Street, Longmont, CO</p>
        <a href="/services">Services</a>
        <a href="https://tnmfire.example/contact">Contact</a>
        <a href="https://external.example/offsite">External</a>
        <img src="/images/logo.png" />
        <div>Installation, maintenance, inspection, and testing for local systems.</div>
      </body>
    </html>
    """
    response = _FakeResponse(
        content_type="text/html; charset=utf-8",
        body=html,
        final_url="https://tnmfire.example/",
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _FakeOpener(response))

    service = SEOMigrationSourceIngestService(max_internal_links=5, max_text_blocks=40, max_headings=10)
    result = service.ingest_homepage(source_url="https://tnmfire.example")
    snapshot = result.snapshot

    assert result.source_url == "https://tnmfire.example/"
    assert snapshot["title"] == "TNM Fire Protection"
    assert snapshot["meta_description"] == "Local fire protection installation and inspection."
    assert snapshot["canonical_url"] == "https://tnmfire.example/"
    assert "Fire Protection Services" in snapshot["headings"]
    assert "Installation and Inspection" in snapshot["headings"]
    assert "info@tnmfire.example" in snapshot["emails"]
    assert any("555-0110" in phone for phone in snapshot["phone_numbers"])
    assert any("Main Street" in item for item in snapshot["addresses"])
    assert "https://tnmfire.example/services" in snapshot["internal_links"]
    assert "https://tnmfire.example/contact" in snapshot["internal_links"]
    assert all("external.example" not in link for link in snapshot["internal_links"])
    assert "https://tnmfire.example/styles/site.css" in snapshot["asset_references"]["stylesheets"]
    assert "https://tnmfire.example/assets/app.js" in snapshot["asset_references"]["scripts"]
    assert "https://tnmfire.example/images/logo.png" in snapshot["asset_references"]["images"]
    assert any("inspection" in block.lower() for block in snapshot["service_blocks"])


def test_ingest_rejects_non_html_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        content_type="application/json",
        body='{"ok":true}',
        final_url="https://tnmfire.example/",
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _FakeOpener(response))

    service = SEOMigrationSourceIngestService()
    with pytest.raises(SEOMigrationSourceIngestError, match="HTML document"):
        service.ingest_homepage(source_url="https://tnmfire.example")


def test_ingest_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<html><body>" + ("A" * 20_000) + "</body></html>"
    response = _FakeResponse(
        content_type="text/html; charset=utf-8",
        body=html,
        final_url="https://tnmfire.example/",
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _FakeOpener(response))

    service = SEOMigrationSourceIngestService(max_response_bytes=10_000)
    with pytest.raises(SEOMigrationSourceIngestError, match="size limit"):
        service.ingest_homepage(source_url="https://tnmfire.example")


def test_ingest_discovers_images_from_img_srcset_and_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://tnmfire.example/media/hero.jpg?token=abc" />
        <meta name="twitter:image" content="/media/twitter-card.jpg?signature=123" />
      </head>
      <body>
        <img src="/images/logo.png?cache=1" />
        <img data-src="/images/logo.png?cache=2" />
        <img srcset="/images/gallery-1.jpg 1x, /images/gallery-2.jpg 2x" />
        <picture>
          <source srcset="/images/gallery-2.jpg 1x, /images/gallery-3.jpg 2x" />
        </picture>
      </body>
    </html>
    """
    response = _FakeResponse(
        content_type="text/html; charset=utf-8",
        body=html,
        final_url="https://tnmfire.example/",
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _FakeOpener(response))

    service = SEOMigrationSourceIngestService()
    result = service.ingest_homepage(source_url="https://tnmfire.example")
    discovered = result.snapshot.get("discovered_images")
    assert isinstance(discovered, list)
    assert len(discovered) >= 5

    normalized_urls = {
        str(item.get("normalized_url"))
        for item in discovered
        if isinstance(item, dict)
    }
    assert "https://tnmfire.example/images/logo.png" in normalized_urls
    assert "https://tnmfire.example/images/gallery-1.jpg" in normalized_urls
    assert "https://tnmfire.example/images/gallery-2.jpg" in normalized_urls
    assert "https://tnmfire.example/images/gallery-3.jpg" in normalized_urls
    assert "https://tnmfire.example/media/hero.jpg" in normalized_urls
    assert "https://tnmfire.example/media/twitter-card.jpg" in normalized_urls

    for item in discovered:
        assert isinstance(item, dict)
        assert str(item.get("asset_id", "")).startswith("srcimg-")
        assert item.get("provenance") == "source_site_import"
        assert item.get("selected_for_draft") is False
        assert item.get("import_status") == "discovered"


def test_ingest_rejects_private_or_local_source_hosts() -> None:
    service = SEOMigrationSourceIngestService()
    with pytest.raises(SEOMigrationSourceIngestError, match="host is not allowed"):
        service.ingest_homepage(source_url="http://localhost:8080")
    with pytest.raises(SEOMigrationSourceIngestError, match="host is not allowed"):
        service.ingest_homepage(source_url="http://169.254.169.254/latest/meta-data/")


def test_ingest_classifies_low_value_and_non_image_discovered_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <body>
        <img src="/images/transparent_placeholder.png" />
        <img src="/assets/tracking-pixel.gif?cache=1" />
        <img src="/project-gallery/before-after.jpg" />
        <img src="/services/fire-protection.html" />
      </body>
    </html>
    """
    response = _FakeResponse(
        content_type="text/html; charset=utf-8",
        body=html,
        final_url="https://tnmfire.example/",
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _FakeOpener(response))

    service = SEOMigrationSourceIngestService()
    result = service.ingest_homepage(source_url="https://tnmfire.example")
    discovered = result.snapshot.get("discovered_images")
    assert isinstance(discovered, list)

    by_url = {
        str(item.get("normalized_url")): item
        for item in discovered
        if isinstance(item, dict)
    }
    placeholder = by_url["https://tnmfire.example/images/transparent_placeholder.png"]
    tracking = by_url["https://tnmfire.example/assets/tracking-pixel.gif"]
    useful = by_url["https://tnmfire.example/project-gallery/before-after.jpg"]
    non_image = by_url["https://tnmfire.example/services/fire-protection.html"]

    assert placeholder.get("candidate_quality") == "low_value"
    assert placeholder.get("quality_reason") == "placeholder_image_detected"
    assert tracking.get("candidate_quality") == "rejected"
    assert tracking.get("quality_reason") == "tracking_pixel_detected"
    assert useful.get("candidate_quality") == "useful"
    assert useful.get("quality_reason") is None
    assert non_image.get("candidate_quality") == "rejected"
    assert non_image.get("quality_reason") == "non_image_candidate_detected"

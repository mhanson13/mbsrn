from __future__ import annotations

import socket
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.core.safe_url import UnsafePublicURLError, normalize_public_http_url, same_site_www_equivalent
from app.services.faithful_source_capture import (
    PlaywrightFaithfulSourceCaptureEngine,
    _build_host_resolver_rules,
    _is_allowed_capture_url,
    _record_unsupported_features,
)


def test_runtime_probe_requires_chromium_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    launch_options: dict[str, object] = {}

    class FakeBrowser:
        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, **kwargs: object) -> FakeBrowser:
            launch_options.update(kwargs)
            return FakeBrowser()

    class FakePlaywrightContext:
        def __enter__(self) -> SimpleNamespace:
            return SimpleNamespace(chromium=FakeChromium())

        def __exit__(self, *_args: object) -> None:
            return None

    playwright_module = ModuleType("playwright")
    sync_api_module = ModuleType("playwright.sync_api")
    sync_api_module.Error = RuntimeError  # type: ignore[attr-defined]
    sync_api_module.sync_playwright = lambda: FakePlaywrightContext()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_module)

    PlaywrightFaithfulSourceCaptureEngine().verify_runtime()

    assert launch_options["headless"] is True
    assert launch_options["chromium_sandbox"] is True


def test_public_url_validation_rejects_credentials_and_private_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 0))],
    )
    with pytest.raises(UnsafePublicURLError, match="without credentials"):
        normalize_public_http_url("https://user:secret@example.com/")
    with pytest.raises(UnsafePublicURLError, match="not allowed"):
        normalize_public_http_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(UnsafePublicURLError, match="not allowed"):
        normalize_public_http_url("http://localhost:8080/")


def test_public_url_validation_fails_closed_when_dns_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_dns(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", fail_dns)
    with pytest.raises(UnsafePublicURLError, match="not allowed"):
        normalize_public_http_url("https://unresolved.example/", require_dns=True)


def test_capture_scope_allows_only_www_equivalent_hosts() -> None:
    assert same_site_www_equivalent("https://example.com", "https://www.example.com/about") is True
    assert same_site_www_equivalent("https://www.example.com", "http://example.com/about") is True
    assert same_site_www_equivalent("https://example.com", "https://cdn.example.com/image.jpg") is False
    assert same_site_www_equivalent("https://example.com", "https://example.net/") is False
    assert _is_allowed_capture_url("https://example.com", "https://example.com:8080/admin") is False
    assert _is_allowed_capture_url("http://example.com", "https://www.example.com/about") is True


def test_capture_pins_authorized_host_and_www_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(host: str, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        address = "93.184.216.34" if host == "example.com" else "93.184.216.35"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    rules = _build_host_resolver_rules("https://example.com/")
    assert rules == ("MAP example.com 93.184.216.34," "MAP www.example.com 93.184.216.35," "EXCLUDE localhost")


def test_unsupported_feature_detection_is_operator_readable() -> None:
    unsupported: set[str] = set()
    _record_unsupported_features(
        {
            "formCount": 2,
            "passwordInputCount": 1,
            "fileInputCount": 1,
            "iframeCount": 1,
            "mediaCount": 1,
            "commerceSignalCount": 1,
        },
        unsupported,
    )
    assert unsupported == {
        "authentication_not_captured",
        "commerce_backend_not_captured",
        "embedded_iframes_require_review",
        "file_uploads_not_captured",
        "server_side_forms_require_replacement",
        "streaming_media_requires_review",
    }

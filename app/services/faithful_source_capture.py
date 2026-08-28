from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.safe_url import (
    UnsafePublicURLError,
    normalize_public_http_url,
    resolve_public_host_ips,
    same_site_www_equivalent,
)


_CAPTURED_ASSET_CONTENT_TYPES = {
    "application/javascript",
    "application/json",
    "application/manifest+json",
    "application/wasm",
    "application/x-javascript",
    "font/otf",
    "font/ttf",
    "font/woff",
    "font/woff2",
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
    "image/webp",
    "text/css",
    "text/javascript",
}
_ASSET_EXTENSIONS = {
    "application/javascript": ".js",
    "application/json": ".json",
    "application/manifest+json": ".webmanifest",
    "application/wasm": ".wasm",
    "application/x-javascript": ".js",
    "font/otf": ".otf",
    "font/ttf": ".ttf",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
    "text/css": ".css",
    "text/javascript": ".js",
}
_PATH_SAFE_PATTERN = re.compile(r"[^a-z0-9]+")


class FaithfulSourceCaptureError(RuntimeError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class FaithfulCapturedObject:
    kind: str
    source_url: str
    final_url: str
    artifact_path: str
    content_type: str
    payload: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.payload)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class FaithfulSourceCaptureResult:
    source_url: str
    final_url: str
    title: str | None
    objects: tuple[FaithfulCapturedObject, ...]
    pages: tuple[dict[str, object], ...]
    unsupported_features: tuple[str, ...]
    warning_codes: tuple[str, ...]
    blocked_external_request_count: int


class PlaywrightFaithfulSourceCaptureEngine:
    def __init__(
        self,
        *,
        navigation_timeout_seconds: int = 20,
        capture_timeout_seconds: int = 180,
        render_wait_milliseconds: int = 750,
        max_resource_bytes: int = 5_000_000,
    ) -> None:
        self.navigation_timeout_seconds = max(1, int(navigation_timeout_seconds))
        self.capture_timeout_seconds = max(5, int(capture_timeout_seconds))
        self.render_wait_milliseconds = max(0, min(5_000, int(render_wait_milliseconds)))
        self.max_resource_bytes = max(10_000, int(max_resource_bytes))

    def verify_runtime(self) -> None:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FaithfulSourceCaptureError(
                "Browser capture runtime is unavailable.",
                reason_code="browser_runtime_unavailable",
            ) from exc
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage", "--disable-background-networking"],
                )
                browser.close()
        except PlaywrightError as exc:
            raise FaithfulSourceCaptureError(
                "Chromium could not start in the capture worker.",
                reason_code="browser_runtime_unavailable",
            ) from exc

    def capture(
        self,
        *,
        source_url: str,
        page_limit: int,
        asset_limit: int,
        max_total_bytes: int,
    ) -> FaithfulSourceCaptureResult:
        try:
            normalized_source_url = normalize_public_http_url(source_url, require_dns=True)
        except UnsafePublicURLError as exc:
            raise FaithfulSourceCaptureError(str(exc), reason_code="unsafe_source_url") from exc

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FaithfulSourceCaptureError(
                "Browser capture runtime is unavailable.",
                reason_code="browser_runtime_unavailable",
            ) from exc

        started_at = time.monotonic()
        host_resolver_rules = _build_host_resolver_rules(normalized_source_url)
        objects: list[FaithfulCapturedObject] = []
        pages: list[dict[str, object]] = []
        unsupported_features: set[str] = set()
        warning_codes: set[str] = set()
        captured_asset_urls: set[str] = set()
        queued_page_urls: list[str] = [normalized_source_url]
        visited_page_urls: set[str] = set()
        blocked_external_urls: set[str] = set()
        total_bytes = 0
        final_url = normalized_source_url
        capture_title: str | None = None

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    chromium_sandbox=True,
                    args=[
                        "--disable-dev-shm-usage",
                        "--disable-background-networking",
                        f"--host-resolver-rules={host_resolver_rules}",
                    ],
                )
                context = browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    java_script_enabled=True,
                    ignore_https_errors=False,
                )
                context.set_default_navigation_timeout(self.navigation_timeout_seconds * 1000)
                context.set_default_timeout(self.navigation_timeout_seconds * 1000)

                def route_request(route: Any) -> None:
                    request_url = str(route.request.url or "")
                    if not _is_allowed_capture_url(normalized_source_url, request_url):
                        blocked_external_urls.add(_redacted_origin(request_url))
                        route.abort("blockedbyclient")
                        return
                    try:
                        normalize_public_http_url(request_url, require_dns=True)
                    except UnsafePublicURLError:
                        warning_codes.add("unsafe_request_blocked")
                        route.abort("blockedbyclient")
                        return
                    route.continue_()

                context.route("**/*", route_request)
                context.on("serviceworker", lambda _worker: unsupported_features.add("service_worker_not_captured"))
                context.on("weberror", lambda _error: warning_codes.add("browser_page_error"))

                while queued_page_urls and len(pages) < max(1, int(page_limit)):
                    if time.monotonic() - started_at > self.capture_timeout_seconds:
                        raise FaithfulSourceCaptureError(
                            "Browser capture exceeded its time limit.",
                            reason_code="capture_timeout",
                        )
                    page_url = queued_page_urls.pop(0)
                    page_key = _normalize_page_url(page_url)
                    if page_key in visited_page_urls:
                        continue
                    visited_page_urls.add(page_key)
                    page = context.new_page()
                    responses: list[Any] = []
                    page.on("response", lambda response: responses.append(response))
                    page.on("websocket", lambda _socket: unsupported_features.add("websocket_backend_not_captured"))
                    page.on("download", lambda _download: unsupported_features.add("downloads_not_captured"))
                    try:
                        response = page.goto(
                            page_url,
                            wait_until="domcontentloaded",
                            timeout=self.navigation_timeout_seconds * 1000,
                        )
                        if self.render_wait_milliseconds:
                            page.wait_for_timeout(self.render_wait_milliseconds)
                        observed_url = normalize_public_http_url(page.url, require_dns=True)
                        if not _is_allowed_capture_url(normalized_source_url, observed_url):
                            raise FaithfulSourceCaptureError(
                                "Browser capture redirected outside the authorized site.",
                                reason_code="unsafe_redirect",
                            )
                        if response is not None and int(response.status) >= 400:
                            raise FaithfulSourceCaptureError(
                                f"Source page returned HTTP {int(response.status)}.",
                                reason_code="source_http_error",
                            )

                        page_details = _read_rendered_page_details(page)
                        html_payload = str(page.content()).encode("utf-8")
                        if len(html_payload) > self.max_resource_bytes:
                            raise FaithfulSourceCaptureError(
                                "Rendered source page exceeded the per-resource size limit.",
                                reason_code="page_too_large",
                            )
                        if total_bytes + len(html_payload) > max_total_bytes:
                            raise FaithfulSourceCaptureError(
                                "Rendered source capture exceeded the total size limit.",
                                reason_code="capture_too_large",
                            )
                        page_index = len(pages) + 1
                        page_title = _clean_text(page_details.get("title"), max_length=220)
                        if capture_title is None:
                            capture_title = page_title
                            final_url = observed_url
                        page_artifact_path = _page_artifact_path(observed_url, page_index)
                        objects.append(
                            FaithfulCapturedObject(
                                kind="rendered_page",
                                source_url=page_url,
                                final_url=observed_url,
                                artifact_path=page_artifact_path,
                                content_type="text/html; charset=utf-8",
                                payload=html_payload,
                            )
                        )
                        total_bytes += len(html_payload)
                        pages.append(
                            {
                                "source_url": page_url,
                                "final_url": observed_url,
                                "artifact_path": page_artifact_path,
                                "title": page_title,
                                "text_excerpt": _clean_text(page_details.get("text"), max_length=12_000),
                            }
                        )
                        _record_unsupported_features(page_details, unsupported_features)

                        for raw_link in _string_list(page_details.get("links"), max_items=500):
                            if not _is_allowed_capture_url(normalized_source_url, raw_link):
                                continue
                            normalized_link = _normalize_page_url(raw_link)
                            if normalized_link not in visited_page_urls and normalized_link not in queued_page_urls:
                                queued_page_urls.append(normalized_link)

                        for captured_response in responses:
                            if len(captured_asset_urls) >= max(1, int(asset_limit)):
                                warning_codes.add("asset_limit_reached")
                                break
                            response_url = str(captured_response.url or "")
                            if response_url in captured_asset_urls:
                                continue
                            if not _is_allowed_capture_url(normalized_source_url, response_url):
                                continue
                            content_type = _normalize_content_type(captured_response.headers.get("content-type"))
                            if content_type not in _CAPTURED_ASSET_CONTENT_TYPES:
                                request_type = str(getattr(captured_response.request, "resource_type", "") or "")
                                if request_type in {"fetch", "xhr"}:
                                    unsupported_features.add("dynamic_api_responses_not_captured")
                                continue
                            declared_size = _safe_int(captured_response.headers.get("content-length"))
                            if declared_size is not None and declared_size > self.max_resource_bytes:
                                warning_codes.add("oversized_asset_skipped")
                                continue
                            try:
                                body = bytes(captured_response.body())
                            except PlaywrightError:
                                warning_codes.add("asset_body_unavailable")
                                continue
                            if not body or len(body) > self.max_resource_bytes:
                                if body:
                                    warning_codes.add("oversized_asset_skipped")
                                continue
                            if total_bytes + len(body) > max_total_bytes:
                                warning_codes.add("total_size_limit_reached")
                                break
                            normalized_asset_url = _strip_fragment(response_url)
                            captured_asset_urls.add(normalized_asset_url)
                            objects.append(
                                FaithfulCapturedObject(
                                    kind="first_party_asset",
                                    source_url=normalized_asset_url,
                                    final_url=normalized_asset_url,
                                    artifact_path=_asset_artifact_path(normalized_asset_url, content_type),
                                    content_type=content_type,
                                    payload=body,
                                )
                            )
                            total_bytes += len(body)
                    finally:
                        page.close()
                context.close()
                browser.close()
        except FaithfulSourceCaptureError:
            raise
        except PlaywrightTimeoutError as exc:
            raise FaithfulSourceCaptureError(
                "Browser navigation timed out.",
                reason_code="navigation_timeout",
            ) from exc
        except UnsafePublicURLError as exc:
            raise FaithfulSourceCaptureError(str(exc), reason_code="unsafe_redirect") from exc
        except PlaywrightError as exc:
            raise FaithfulSourceCaptureError(
                "Browser capture failed while rendering the source site.",
                reason_code="browser_capture_failed",
            ) from exc

        if queued_page_urls:
            warning_codes.add("page_limit_reached")
        if blocked_external_urls:
            warning_codes.add("external_resources_blocked")
            unsupported_features.add("external_runtime_dependencies_not_captured")
        if not pages:
            raise FaithfulSourceCaptureError(
                "Browser capture did not produce a rendered page.",
                reason_code="empty_capture",
            )
        return FaithfulSourceCaptureResult(
            source_url=normalized_source_url,
            final_url=final_url,
            title=capture_title,
            objects=tuple(objects),
            pages=tuple(pages),
            unsupported_features=tuple(sorted(unsupported_features)),
            warning_codes=tuple(sorted(warning_codes)),
            blocked_external_request_count=len(blocked_external_urls),
        )


def _read_rendered_page_details(page: Any) -> dict[str, object]:
    payload = page.evaluate(
        """
        () => ({
          title: document.title || null,
          text: document.body ? document.body.innerText : "",
          links: Array.from(document.querySelectorAll('a[href]')).map((node) => node.href),
          formCount: document.querySelectorAll('form').length,
          passwordInputCount: document.querySelectorAll('input[type="password"]').length,
          fileInputCount: document.querySelectorAll('input[type="file"]').length,
          iframeCount: document.querySelectorAll('iframe').length,
          mediaCount: document.querySelectorAll('video,audio').length,
          commerceSignalCount: document.querySelectorAll(
            '[class*="cart" i],[id*="cart" i],[class*="checkout" i],[id*="checkout" i]'
          ).length
        })
        """
    )
    return payload if isinstance(payload, dict) else {}


def _record_unsupported_features(page_details: dict[str, object], unsupported: set[str]) -> None:
    if _safe_int(page_details.get("formCount"), default=0):
        unsupported.add("server_side_forms_require_replacement")
    if _safe_int(page_details.get("passwordInputCount"), default=0):
        unsupported.add("authentication_not_captured")
    if _safe_int(page_details.get("fileInputCount"), default=0):
        unsupported.add("file_uploads_not_captured")
    if _safe_int(page_details.get("iframeCount"), default=0):
        unsupported.add("embedded_iframes_require_review")
    if _safe_int(page_details.get("mediaCount"), default=0):
        unsupported.add("streaming_media_requires_review")
    if _safe_int(page_details.get("commerceSignalCount"), default=0):
        unsupported.add("commerce_backend_not_captured")


def _is_allowed_capture_url(source_url: str, candidate_url: str) -> bool:
    if not same_site_www_equivalent(source_url, candidate_url):
        return False
    try:
        source = urlsplit(source_url)
        candidate = urlsplit(candidate_url)
        source_port = source.port or (443 if source.scheme.lower() == "https" else 80)
        candidate_port = candidate.port or (443 if candidate.scheme.lower() == "https" else 80)
    except ValueError:
        return False
    allowed_ports = {80, 443} if source_port in {80, 443} else {source_port}
    return candidate_port in allowed_ports


def _build_host_resolver_rules(source_url: str) -> str:
    source_host = (urlsplit(source_url).hostname or "").lower().rstrip(".")
    base_host = source_host[4:] if source_host.startswith("www.") else source_host
    candidate_hosts = [base_host, f"www.{base_host}"]
    mappings: list[str] = []
    for host in candidate_hosts:
        try:
            addresses = resolve_public_host_ips(host)
        except UnsafePublicURLError:
            if host == source_host:
                raise
            continue
        ipv4_addresses = [address for address in addresses if ":" not in address]
        selected_address = (ipv4_addresses or list(addresses))[0]
        if ":" in selected_address:
            selected_address = f"[{selected_address}]"
        mappings.append(f"MAP {host} {selected_address}")
    if not mappings:
        raise UnsafePublicURLError("URL host is not allowed.")
    mappings.append("EXCLUDE localhost")
    return ",".join(mappings)


def _normalize_page_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", ""))


def _strip_fragment(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _redacted_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "invalid-origin"
    return f"{parsed.scheme.lower()}://{(parsed.hostname or 'unknown').lower()}"


def _page_artifact_path(url: str, index: int) -> str:
    path = urlsplit(url).path.strip("/") or "home"
    slug = _PATH_SAFE_PATTERN.sub("-", path.lower()).strip("-")[:80] or "page"
    return f"pages/{index:03d}-{slug}.html"


def _asset_artifact_path(url: str, content_type: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    url_suffix = mimetypes.guess_type(urlsplit(url).path)[0]
    extension = _ASSET_EXTENSIONS.get(content_type)
    if extension is None and url_suffix:
        extension = mimetypes.guess_extension(url_suffix)
    return f"assets/{digest}{extension or '.bin'}"


def _normalize_content_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _clean_text(value: object, *, max_length: int) -> str | None:
    normalized = " ".join(str(value or "").split()).strip()
    return normalized[:max_length] if normalized else None


def _string_list(value: object, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:max_items] if str(item or "").strip()]


def _safe_int(value: object, *, default: int | None = None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

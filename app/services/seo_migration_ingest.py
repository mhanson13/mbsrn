from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import hashlib
import ipaddress
import re
import socket
import urllib.parse
import urllib.error
import urllib.request

from app.core.time import utc_now


_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "p",
    "section",
    "td",
    "th",
}
_HEADING_TAGS = {"h1", "h2", "h3"}
_PHONE_PATTERN = re.compile(r"\+?\d[\d\-\.\s\(\)]{6,}\d")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9][A-Za-z0-9\.\- ]{2,80}\s(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b",
    re.IGNORECASE,
)
_SERVICE_HINT_PATTERN = re.compile(
    r"\b(service|services|installation|repair|inspection|maintenance|testing|design|consulting|support)\b",
    re.IGNORECASE,
)
_CONTACT_HINT_PATTERN = re.compile(
    r"\b(contact|call|quote|estimate|book|request service|schedule)\b",
    re.IGNORECASE,
)
_MAX_PHONE_RESULTS = 12
_MAX_EMAIL_RESULTS = 12
_MAX_ADDRESS_RESULTS = 12
_MAX_IMAGE_CANDIDATES = 120
_MAX_DISCOVERED_IMAGE_METADATA = 80
_MAX_DISCOVERY_PAGES = 8
_MAX_IMAGE_VALIDATION_BYTES = 262_144
_MAX_IMAGE_VALIDATIONS = 120
_IMAGE_PROBE_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}
_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
    ".heic",
}
_NON_IMAGE_EXTENSIONS = {
    ".html",
    ".htm",
    ".php",
    ".aspx",
    ".jsp",
    ".txt",
    ".json",
    ".xml",
    ".svg",
}
_PLACEHOLDER_TOKENS = (
    "transparent_placeholder",
    "placeholder",
    "spacer",
    "blank",
    "loader",
    "spinner",
)
_TRACKING_TOKENS = (
    "tracking",
    "beacon",
    "pixel",
    "collect",
    "analytics",
)
_LAYOUT_TOKENS = (
    "logo",
    "icon",
    "sprite",
    "favicon",
)
_SCANNABLE_PATH_HINTS = (
    "/projects",
    "/project",
    "/gallery",
    "/work",
    "/portfolio",
    "/services",
    "/about",
)
_SCANNABLE_LABEL_HINTS = (
    "projects",
    "project",
    "gallery",
    "services",
    "our work",
    "portfolio",
    "process",
)
_INLINE_STYLE_URL_PATTERN = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)
_WSIMG_VARIANT_MARKER = "/:/"


class SEOMigrationSourceIngestError(ValueError):
    pass


@dataclass(frozen=True)
class SEOMigrationIngestResult:
    source_url: str
    snapshot: dict[str, object]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _FetchedHtmlPage:
    url: str
    status_code: int
    content_type: str
    body_text: str


@dataclass(frozen=True)
class _ImageProbeResult:
    accepted: bool
    content_type: str | None
    final_url: str | None
    byte_size: int | None
    fetch_status: str
    diagnostic_reason: str | None


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, max_redirects: int):
        super().__init__()
        self.max_redirects = max(0, int(max_redirects))

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirect_count = int(getattr(req, "_mbsrn_redirect_count", 0))
        if redirect_count >= self.max_redirects:
            raise SEOMigrationSourceIngestError("Source URL exceeded redirect limit")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            setattr(redirected, "_mbsrn_redirect_count", redirect_count + 1)
        return redirected


class _HomepageExtractParser(HTMLParser):
    def __init__(self, *, base_url: str, max_internal_links: int, max_text_blocks: int, max_headings: int):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.max_internal_links = max_internal_links
        self.max_text_blocks = max_text_blocks
        self.max_headings = max_headings
        self.title: str | None = None
        self.meta_description: str | None = None
        self.canonical_url: str | None = None
        self.headings: list[str] = []
        self.internal_links: list[str] = []
        self.asset_stylesheets: list[str] = []
        self.asset_scripts: list[str] = []
        self.asset_images: list[str] = []
        self.internal_link_metadata: list[dict[str, str]] = []
        self.contact_signals: list[str] = []
        self.text_blocks: list[str] = []
        self.service_blocks: list[str] = []
        self.warnings: list[str] = []
        self._current_tag: str | None = None
        self._in_title = False
        self._capture_disabled_depth = 0
        self._heading_depth = 0
        self._current_block_parts: list[str] = []
        self._seen_internal_links: set[str] = set()
        self._seen_internal_link_metadata: set[tuple[str, str]] = set()
        self._seen_contact_signals: set[str] = set()
        self._seen_stylesheets: set[str] = set()
        self._seen_scripts: set[str] = set()
        self._seen_images: set[str] = set()
        self._active_anchor_url: str | None = None
        self._active_anchor_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        lower_tag = (tag or "").lower()
        attrs_dict = {str(key).lower(): str(value) for key, value in attrs if key and value}
        self._current_tag = lower_tag
        self._capture_inline_style_urls(attrs_dict.get("style"))
        if lower_tag in {"script", "style", "noscript"}:
            self._capture_disabled_depth += 1
        if lower_tag == "title":
            self._in_title = True
        if lower_tag in _HEADING_TAGS:
            self._heading_depth += 1
        if lower_tag == "meta" and self.meta_description is None:
            name = attrs_dict.get("name", "").strip().lower()
            if name == "description":
                content = _clean_optional_text(attrs_dict.get("content"))
                if content:
                    self.meta_description = content[:320]
        if lower_tag == "meta":
            property_name = attrs_dict.get("property", "").strip().lower()
            meta_name = attrs_dict.get("name", "").strip().lower()
            if property_name in {"og:image", "og:image:url"} or meta_name in {"og:image", "twitter:image"}:
                self._capture_image_candidate(attrs_dict.get("content"))
        if lower_tag == "link":
            rel = attrs_dict.get("rel", "").strip().lower()
            href = attrs_dict.get("href")
            if rel == "canonical" and self.canonical_url is None and href:
                normalized = self._normalize_url(href)
                if normalized:
                    self.canonical_url = normalized
            if "stylesheet" in rel and href:
                normalized = self._normalize_url(href)
                if normalized and normalized not in self._seen_stylesheets:
                    self._seen_stylesheets.add(normalized)
                    self.asset_stylesheets.append(normalized)
        if lower_tag == "script":
            src = attrs_dict.get("src")
            if src:
                normalized = self._normalize_url(src)
                if normalized and normalized not in self._seen_scripts:
                    self._seen_scripts.add(normalized)
                    self.asset_scripts.append(normalized)
        if lower_tag == "img":
            self._capture_image_candidate(attrs_dict.get("src"))
            self._capture_image_candidate(attrs_dict.get("data-src"))
            self._capture_image_candidate(attrs_dict.get("data-lazy-src"))
            self._capture_image_candidate(attrs_dict.get("data-original"))
            self._capture_srcset_candidates(attrs_dict.get("srcset"))
            self._capture_srcset_candidates(attrs_dict.get("data-srcset"))
        if lower_tag == "source":
            self._capture_image_candidate(attrs_dict.get("src"))
            self._capture_srcset_candidates(attrs_dict.get("srcset"))
            self._capture_srcset_candidates(attrs_dict.get("data-srcset"))
        if lower_tag == "a":
            self._active_anchor_url = None
            self._active_anchor_text_parts = []
            href = attrs_dict.get("href")
            if href:
                normalized_link = self._normalize_url(href)
                if normalized_link and _is_same_origin(self.base_url, normalized_link):
                    self._active_anchor_url = normalized_link
                    if normalized_link not in self._seen_internal_links:
                        self._seen_internal_links.add(normalized_link)
                        if len(self.internal_links) < self.max_internal_links:
                            self.internal_links.append(normalized_link)
                        elif "Internal link list was truncated." not in self.warnings:
                            self.warnings.append("Internal link list was truncated.")
            anchor_hint = attrs_dict.get("aria-label") or attrs_dict.get("title")
            if anchor_hint:
                self._capture_contact_signal(anchor_hint)
                if self._active_anchor_url is not None:
                    self._record_internal_link_label(self._active_anchor_url, anchor_hint)

    def _capture_image_candidate(self, raw_url: object) -> None:
        normalized = self._normalize_url(str(raw_url or ""))
        if not normalized:
            return
        if normalized in self._seen_images:
            return
        self._seen_images.add(normalized)
        if len(self.asset_images) < _MAX_IMAGE_CANDIDATES:
            self.asset_images.append(normalized)
        elif "Image candidate list was truncated." not in self.warnings:
            self.warnings.append("Image candidate list was truncated.")

    def _capture_srcset_candidates(self, raw_srcset: object) -> None:
        srcset = _clean_optional_text(raw_srcset)
        if srcset is None:
            return
        for candidate in _parse_srcset_urls(srcset):
            self._capture_image_candidate(candidate)

    def _capture_inline_style_urls(self, raw_style: object) -> None:
        style_text = _clean_optional_text(raw_style)
        if style_text is None:
            return
        for match in _INLINE_STYLE_URL_PATTERN.finditer(style_text):
            candidate = _clean_optional_text(match.group(1))
            if candidate is None:
                continue
            cleaned = candidate.strip("\"'")
            if not cleaned:
                continue
            self._capture_image_candidate(cleaned)

    def _record_internal_link_label(self, url: str, label: object) -> None:
        normalized_label = _clean_optional_text(label)
        if normalized_label is None:
            return
        key = (url.lower(), normalized_label.lower())
        if key in self._seen_internal_link_metadata:
            return
        self._seen_internal_link_metadata.add(key)
        if len(self.internal_link_metadata) < self.max_internal_links:
            self.internal_link_metadata.append({"url": url, "label": normalized_label[:220]})

    def handle_endtag(self, tag: str) -> None:
        lower_tag = (tag or "").lower()
        if lower_tag == "title":
            self._in_title = False
        if lower_tag == "a":
            if self._active_anchor_url is not None and self._active_anchor_text_parts:
                self._record_internal_link_label(
                    self._active_anchor_url,
                    " ".join(self._active_anchor_text_parts),
                )
            self._active_anchor_url = None
            self._active_anchor_text_parts = []
        if lower_tag in _HEADING_TAGS and self._heading_depth > 0:
            self._heading_depth -= 1
        if lower_tag in {"script", "style", "noscript"} and self._capture_disabled_depth > 0:
            self._capture_disabled_depth -= 1
        if lower_tag in _BLOCK_TAGS:
            self._flush_block_text()
        self._current_tag = None

    def handle_data(self, data: str) -> None:
        if self._capture_disabled_depth > 0:
            return
        text = _clean_optional_text(data)
        if not text:
            return
        if self._in_title and self.title is None:
            self.title = text[:220]
        if self._heading_depth > 0:
            if len(self.headings) < self.max_headings:
                self.headings.append(text[:220])
            elif "Heading list was truncated." not in self.warnings:
                self.warnings.append("Heading list was truncated.")
        self._capture_contact_signal(text)
        if self._active_anchor_url is not None and self._current_tag in {"a", "span", "strong"}:
            self._active_anchor_text_parts.append(text[:160])
        if self._current_tag in _BLOCK_TAGS:
            self._current_block_parts.append(text)
        elif self._current_tag in {"a", "span", "strong"}:
            self._current_block_parts.append(text)

    def close(self) -> None:
        self._flush_block_text()
        super().close()

    def _normalize_url(self, raw_value: str) -> str | None:
        cleaned = _clean_optional_text(raw_value)
        if cleaned is None:
            return None
        joined = urllib.parse.urljoin(self.base_url, cleaned)
        parsed = urllib.parse.urlsplit(joined)
        if parsed.scheme not in {"http", "https"}:
            return None
        if not parsed.netloc:
            return None
        normalized = urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                parsed.query or "",
                "",
            )
        )
        return normalized

    def _capture_contact_signal(self, text: str) -> None:
        if not _CONTACT_HINT_PATTERN.search(text):
            return
        normalized = text.strip()
        key = normalized.lower()
        if key in self._seen_contact_signals:
            return
        self._seen_contact_signals.add(key)
        if len(self.contact_signals) < 20:
            self.contact_signals.append(normalized[:180])

    def _flush_block_text(self) -> None:
        if not self._current_block_parts:
            return
        combined = _clean_optional_text(" ".join(self._current_block_parts))
        self._current_block_parts = []
        if not combined:
            return
        if len(self.text_blocks) < self.max_text_blocks:
            self.text_blocks.append(combined[:420])
        elif "Text block list was truncated." not in self.warnings:
            self.warnings.append("Text block list was truncated.")
        if _SERVICE_HINT_PATTERN.search(combined):
            if combined not in self.service_blocks and len(self.service_blocks) < 30:
                self.service_blocks.append(combined[:280])


class SEOMigrationSourceIngestService:
    def __init__(
        self,
        *,
        timeout_seconds: int = 8,
        max_redirects: int = 4,
        max_response_bytes: int = 800_000,
        max_internal_links: int = 40,
        max_text_blocks: int = 120,
        max_headings: int = 60,
        max_discovery_pages: int = _MAX_DISCOVERY_PAGES,
        max_image_validations: int = _MAX_IMAGE_VALIDATIONS,
        max_image_validation_bytes: int = _MAX_IMAGE_VALIDATION_BYTES,
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_redirects = max(0, int(max_redirects))
        self.max_response_bytes = max(10_000, int(max_response_bytes))
        self.max_internal_links = max(1, int(max_internal_links))
        self.max_text_blocks = max(1, int(max_text_blocks))
        self.max_headings = max(1, int(max_headings))
        self.max_discovery_pages = max(1, int(max_discovery_pages))
        self.max_image_validations = max(1, int(max_image_validations))
        self.max_image_validation_bytes = max(4096, int(max_image_validation_bytes))

    def ingest_homepage(self, *, source_url: str) -> SEOMigrationIngestResult:
        normalized_source_url = self._normalize_source_url(source_url)
        opener = urllib.request.build_opener(_BoundedRedirectHandler(max_redirects=self.max_redirects))
        scanned_pages: list[dict[str, object]] = []
        discovery_warnings: list[str] = []
        discovered_image_candidates: list[tuple[str, str]] = []

        homepage_page = self._fetch_html_page(normalized_source_url=normalized_source_url, page_url=normalized_source_url, opener=opener)
        homepage_parser = self._parse_html_page(page=homepage_page)
        scanned_pages.append(
            {
                "url": homepage_page.url,
                "status_code": homepage_page.status_code,
                "content_type": homepage_page.content_type,
            }
        )
        discovery_warnings.extend(homepage_parser.warnings)
        for image_url in homepage_parser.asset_images:
            discovered_image_candidates.append((image_url, homepage_page.url))

        pages_to_scan = self._build_page_scan_order(
            homepage_url=homepage_page.url,
            homepage_parser=homepage_parser,
        )

        visited_pages = {homepage_page.url.lower()}
        for candidate_page_url in pages_to_scan:
            if len(scanned_pages) >= self.max_discovery_pages:
                break
            lowered_candidate_page = candidate_page_url.lower()
            if lowered_candidate_page in visited_pages:
                continue
            visited_pages.add(lowered_candidate_page)
            try:
                page = self._fetch_html_page(
                    normalized_source_url=normalized_source_url,
                    page_url=candidate_page_url,
                    opener=opener,
                )
            except SEOMigrationSourceIngestError:
                discovery_warnings.append(f"Skipped source page due to fetch failure: {candidate_page_url}")
                continue
            parser = self._parse_html_page(page=page)
            scanned_pages.append(
                {
                    "url": page.url,
                    "status_code": page.status_code,
                    "content_type": page.content_type,
                }
            )
            discovery_warnings.extend(parser.warnings)
            for image_url in parser.asset_images:
                discovered_image_candidates.append((image_url, page.url))

        combined_text = "\n".join(homepage_parser.text_blocks)
        phones = _dedupe_results(_PHONE_PATTERN.findall(combined_text), max_items=_MAX_PHONE_RESULTS, max_len=48)
        emails = _dedupe_results(_EMAIL_PATTERN.findall(combined_text), max_items=_MAX_EMAIL_RESULTS, max_len=120)
        addresses = _dedupe_results(
            _ADDRESS_PATTERN.findall(combined_text), max_items=_MAX_ADDRESS_RESULTS, max_len=180
        )
        fetched_at = _format_datetime(utc_now())
        discovered_images = _build_discovered_image_metadata(
            discovered_image_candidates,
            max_items=_MAX_DISCOVERED_IMAGE_METADATA,
            opener=opener,
            timeout_seconds=self.timeout_seconds,
            max_probe_bytes=self.max_image_validation_bytes,
            max_validations=self.max_image_validations,
            warnings=discovery_warnings,
        )
        pages_scanned_urls = [str(item.get("url") or "").strip() for item in scanned_pages]
        pages_scanned_urls = [item for item in pages_scanned_urls if item]
        pages_scanned_urls = pages_scanned_urls[: self.max_discovery_pages]

        snapshot: dict[str, object] = {
            "fetched_at": fetched_at,
            "final_url": homepage_page.url,
            "status_code": homepage_page.status_code,
            "content_type": homepage_page.content_type,
            "title": homepage_parser.title,
            "meta_description": homepage_parser.meta_description,
            "canonical_url": homepage_parser.canonical_url,
            "headings": homepage_parser.headings,
            "contact_signals": homepage_parser.contact_signals,
            "phone_numbers": phones,
            "emails": emails,
            "addresses": addresses,
            "internal_links": homepage_parser.internal_links,
            "internal_link_metadata": homepage_parser.internal_link_metadata,
            "service_blocks": homepage_parser.service_blocks,
            "pages_scanned_count": len(pages_scanned_urls),
            "pages_scanned": pages_scanned_urls,
            "asset_references": {
                "stylesheets": homepage_parser.asset_stylesheets[:60],
                "scripts": homepage_parser.asset_scripts[:60],
                "images": homepage_parser.asset_images[:60],
            },
            "discovered_images": discovered_images,
            "cleaned_text_blocks": homepage_parser.text_blocks,
            "warnings": _dedupe_results(discovery_warnings, max_items=40, max_len=220),
        }
        return SEOMigrationIngestResult(
            source_url=normalized_source_url,
            snapshot=snapshot,
            warnings=tuple(_dedupe_results(discovery_warnings, max_items=40, max_len=220)),
        )

    def _fetch_html_page(
        self,
        *,
        normalized_source_url: str,
        page_url: str,
        opener,
    ) -> _FetchedHtmlPage:
        request = urllib.request.Request(
            page_url,
            headers={
                "User-Agent": "MBSRN-MigrationIngest/1.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                content_type_header = response.headers.get("Content-Type", "")
                content_type = content_type_header.split(";", 1)[0].strip().lower()
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    raise SEOMigrationSourceIngestError("Source URL did not return an HTML document.")
                body_bytes = self._read_bounded_body(response)
                final_url = str(getattr(response, "url", page_url) or page_url)
                final_url = self._normalize_page_url_for_scan(
                    base_source_url=normalized_source_url,
                    candidate_url=final_url,
                )
                if not _is_same_origin(normalized_source_url, final_url):
                    raise SEOMigrationSourceIngestError("Source ingest redirected outside the source site.")
                status_code = int(getattr(response, "status", 200) or 200)
                charset = _resolve_charset(content_type_header)
        except urllib.error.HTTPError as exc:
            raise SEOMigrationSourceIngestError(f"Source ingest failed with HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise SEOMigrationSourceIngestError("Source ingest failed due to network error.") from exc
        except TimeoutError as exc:
            raise SEOMigrationSourceIngestError("Source ingest timed out.") from exc

        body_text = body_bytes.decode(charset, errors="replace")
        return _FetchedHtmlPage(
            url=final_url,
            status_code=status_code,
            content_type=content_type,
            body_text=body_text,
        )

    def _parse_html_page(self, *, page: _FetchedHtmlPage) -> _HomepageExtractParser:
        parser = _HomepageExtractParser(
            base_url=page.url,
            max_internal_links=self.max_internal_links,
            max_text_blocks=self.max_text_blocks,
            max_headings=self.max_headings,
        )
        parser.feed(page.body_text)
        parser.close()
        return parser

    def _build_page_scan_order(
        self,
        *,
        homepage_url: str,
        homepage_parser: _HomepageExtractParser,
    ) -> list[str]:
        ranked: list[tuple[int, str]] = []
        seen: set[str] = set()
        for item in homepage_parser.internal_link_metadata:
            if not isinstance(item, dict):
                continue
            url = _clean_optional_text(item.get("url"))
            label = _clean_optional_text(item.get("label"))
            if url is None:
                continue
            normalized = self._normalize_page_url_for_scan(base_source_url=homepage_url, candidate_url=url)
            if normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            priority = _internal_link_priority(url=normalized, label=label)
            if priority <= 0:
                continue
            ranked.append((priority, normalized))
        for url in homepage_parser.internal_links:
            normalized = self._normalize_page_url_for_scan(base_source_url=homepage_url, candidate_url=url)
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            priority = _internal_link_priority(url=normalized, label=None)
            if priority <= 0:
                continue
            ranked.append((priority, normalized))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [url for _, url in ranked]

    def _normalize_page_url_for_scan(self, *, base_source_url: str, candidate_url: str) -> str:
        normalized = urllib.parse.urljoin(base_source_url, candidate_url)
        parsed = urllib.parse.urlsplit(normalized)
        return urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                parsed.query or "",
                "",
            )
        )

    def _normalize_source_url(self, source_url: str) -> str:
        cleaned = _clean_optional_text(source_url)
        if cleaned is None:
            raise SEOMigrationSourceIngestError("source_url is required.")
        parsed = urllib.parse.urlsplit(cleaned)
        if parsed.scheme not in {"http", "https"}:
            raise SEOMigrationSourceIngestError("source_url must use http or https.")
        if not parsed.netloc:
            raise SEOMigrationSourceIngestError("source_url must include a valid host.")
        if _is_disallowed_host(parsed.hostname):
            raise SEOMigrationSourceIngestError("source_url host is not allowed for ingest.")
        normalized = urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
        return normalized

    def _read_bounded_body(self, response) -> bytes:  # noqa: ANN001
        total = 0
        chunks: list[bytes] = []
        while True:
            chunk = response.read(16_384)
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_response_bytes:
                raise SEOMigrationSourceIngestError("Source response exceeded size limit.")
            chunks.append(chunk)
        return b"".join(chunks)


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None


def _resolve_charset(content_type_header: str) -> str:
    lowered = (content_type_header or "").lower()
    marker = "charset="
    if marker not in lowered:
        return "utf-8"
    suffix = lowered.split(marker, 1)[1].strip()
    candidate = suffix.split(";", 1)[0].strip()
    if not candidate:
        return "utf-8"
    return candidate


def _is_same_origin(base_url: str, candidate_url: str) -> bool:
    base = urllib.parse.urlsplit(base_url)
    candidate = urllib.parse.urlsplit(candidate_url)
    return base.scheme.lower() == candidate.scheme.lower() and base.netloc.lower() == candidate.netloc.lower()


def _internal_link_priority(*, url: str, label: str | None) -> int:
    lowered_url = url.lower()
    lowered_label = (label or "").strip().lower()
    score = 0
    for hint in _SCANNABLE_PATH_HINTS:
        if hint in lowered_url:
            score += 20
            if lowered_url.endswith(hint) or lowered_url.endswith(f"{hint}/"):
                score += 8
    for hint in _SCANNABLE_LABEL_HINTS:
        if hint in lowered_label:
            score += 18
    if "/projects" in lowered_url:
        score += 8
    if "/services" in lowered_url:
        score += 6
    return score


def _dedupe_results(items: list[str], *, max_items: int, max_len: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _clean_optional_text(item)
        if cleaned is None:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned[:max_len])
        if len(normalized) >= max_items:
            break
    return normalized


def _parse_srcset_urls(raw_srcset: str) -> list[str]:
    normalized = _clean_optional_text(raw_srcset)
    if normalized is None:
        return []
    urls: list[str] = []
    for candidate in normalized.split(","):
        token = candidate.strip().split(" ", 1)[0].strip()
        if token:
            urls.append(token)
    return urls


def _safe_filename_from_url(value: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    basename = (parsed.path or "").rsplit("/", 1)[-1].strip()
    cleaned = _clean_optional_text(basename)
    if cleaned is None:
        return None
    return cleaned[:140]


def _build_discovered_image_metadata(
    image_candidates: list[tuple[str, str]],
    *,
    max_items: int,
    opener,
    timeout_seconds: int,
    max_probe_bytes: int,
    max_validations: int,
    warnings: list[str],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    validations_performed = 0
    for raw_url, source_page_url in image_candidates:
        cleaned_source_page_url = _clean_optional_text(source_page_url)
        cleaned = _clean_optional_text(raw_url)
        if cleaned is None or cleaned_source_page_url is None:
            continue
        try:
            parsed = urllib.parse.urlsplit(cleaned)
        except ValueError:
            continue
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        normalized_url_for_lookup = urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                "",
                "",
            )
        )
        canonical_key = _canonical_image_dedupe_key(normalized_url_for_lookup)
        if canonical_key in seen:
            continue
        seen.add(canonical_key)
        asset_id = "srcimg-" + hashlib.sha1(canonical_key.encode("utf-8")).hexdigest()[:16]
        filename = _safe_filename_from_url(canonical_key)
        candidate_quality, quality_reason = _classify_discovered_image_candidate(
            normalized_url=normalized_url_for_lookup,
            filename=filename,
        )
        probe_result = _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=normalized_url_for_lookup,
            byte_size=None,
            fetch_status="skipped",
            diagnostic_reason="validation_skipped",
        )
        if candidate_quality != "rejected" and validations_performed < max_validations:
            probe_result = _probe_image_candidate_url(
                candidate_url=_strip_url_query(cleaned),
                opener=opener,
                timeout_seconds=timeout_seconds,
                max_probe_bytes=max_probe_bytes,
            )
            validations_performed += 1
            if not probe_result.accepted:
                candidate_quality = "rejected"
                quality_reason = "non_image_candidate_detected"
                if probe_result.diagnostic_reason:
                    warnings.append(
                        f"Rejected discovered image candidate from {cleaned_source_page_url}: {probe_result.diagnostic_reason}."
                    )
            elif probe_result.final_url:
                normalized_url_for_lookup = _strip_url_query(probe_result.final_url)
        elif candidate_quality != "rejected" and validations_performed >= max_validations:
            warnings.append("Image validation limit reached; remaining candidates were not content-validated.")
        extension = _path_extension(canonical_key) or _path_extension(normalized_url_for_lookup)
        has_validated_image_content_type = _is_allowed_image_content_type(probe_result.content_type)
        if not extension and candidate_quality != "rejected" and not has_validated_image_content_type:
            candidate_quality = "rejected"
            quality_reason = "non_image_candidate_detected"
            warnings.append(f"Rejected discovered image candidate without image path evidence: {normalized_url_for_lookup}.")
        normalized.append(
            {
                "asset_id": asset_id,
                "original_url": _strip_url_query(cleaned)[:2048],
                "normalized_url": normalized_url_for_lookup[:2048],
                "canonical_image_key": canonical_key[:2048],
                "filename": filename,
                "source_page_url": _strip_url_query(cleaned_source_page_url)[:2048],
                "provenance": "source_site_import",
                "selected_for_draft": False,
                "import_status": "discovered",
                "candidate_quality": candidate_quality,
                "quality_reason": quality_reason,
                "content_type": probe_result.content_type,
                "fetch_status": probe_result.fetch_status,
                "size_bytes": probe_result.byte_size,
            }
        )
        if len(normalized) >= max(1, int(max_items)):
            break
    return normalized


def _classify_discovered_image_candidate(*, normalized_url: str, filename: str | None) -> tuple[str, str | None]:
    lowered_url = normalized_url.lower()
    lowered_filename = (filename or "").lower()
    extension = _path_extension(normalized_url)
    if extension in _NON_IMAGE_EXTENSIONS:
        return "rejected", "non_image_candidate_detected"

    joined = f"{lowered_url} {lowered_filename}"
    if any(token in joined for token in _TRACKING_TOKENS):
        return "rejected", "tracking_pixel_detected"
    if any(token in joined for token in _PLACEHOLDER_TOKENS):
        return "low_value", "placeholder_image_detected"
    if any(token in joined for token in _LAYOUT_TOKENS):
        return "low_value", "layout_asset_detected"

    if extension and extension not in _IMAGE_EXTENSIONS:
        return "rejected", "non_image_candidate_detected"
    return "useful", None


def _canonical_image_dedupe_key(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return value
    path = (parsed.path or "/").strip() or "/"
    host = (parsed.netloc or "").lower()
    if "wsimg.com" in host and _WSIMG_VARIANT_MARKER in path:
        path = path.split(_WSIMG_VARIANT_MARKER, 1)[0] or "/"
    canonical_path = urllib.parse.unquote(path)
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            host,
            canonical_path,
            "",
            "",
        )
    )


def _probe_image_candidate_url(
    *,
    candidate_url: str,
    opener,
    timeout_seconds: int,
    max_probe_bytes: int,
) -> _ImageProbeResult:
    normalized_candidate = _clean_optional_text(candidate_url)
    if normalized_candidate is None:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="invalid_candidate",
            diagnostic_reason="empty_candidate_url",
        )
    try:
        parsed_candidate = urllib.parse.urlsplit(normalized_candidate)
    except ValueError:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="invalid_candidate",
            diagnostic_reason="malformed_candidate_url",
        )
    if parsed_candidate.scheme not in {"http", "https"} or not parsed_candidate.netloc:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="invalid_candidate",
            diagnostic_reason="unsupported_candidate_scheme",
        )

    head_request = urllib.request.Request(
        normalized_candidate,
        method="HEAD",
        headers={
            "User-Agent": "MBSRN-MigrationIngest/1.0",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    head_content_type: str | None = None
    head_final_url: str | None = None
    head_content_length: int | None = None
    try:
        with opener.open(head_request, timeout=timeout_seconds) as response:
            head_content_type = _normalize_content_type(response.headers.get("Content-Type", ""))
            head_final_url = _normalize_fetch_url(getattr(response, "url", normalized_candidate))
            content_length_raw = _clean_optional_text(response.headers.get("Content-Length", ""))
            if content_length_raw is not None and content_length_raw.isdigit():
                head_content_length = int(content_length_raw)
    except urllib.error.HTTPError as exc:
        if exc.code not in {400, 403, 405, 501}:
            return _ImageProbeResult(
                accepted=False,
                content_type=None,
                final_url=None,
                byte_size=None,
                fetch_status="head_failed",
                diagnostic_reason=f"head_http_{exc.code}",
            )
    except urllib.error.URLError as exc:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="head_failed",
            diagnostic_reason=f"head_network_{_clean_optional_text(getattr(exc, 'reason', None)) or 'unknown'}",
        )
    except TimeoutError:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="head_timeout",
            diagnostic_reason="head_timeout",
        )

    if _is_allowed_image_content_type(head_content_type):
        return _ImageProbeResult(
            accepted=True,
            content_type=head_content_type,
            final_url=head_final_url or normalized_candidate,
            byte_size=head_content_length,
            fetch_status="validated_head",
            diagnostic_reason=None,
        )

    get_request = urllib.request.Request(
        normalized_candidate,
        method="GET",
        headers={
            "User-Agent": "MBSRN-MigrationIngest/1.0",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Range": f"bytes=0-{max(1024, max_probe_bytes) - 1}",
        },
    )
    try:
        with opener.open(get_request, timeout=timeout_seconds) as response:
            content_type = _normalize_content_type(response.headers.get("Content-Type", ""))
            final_url = _normalize_fetch_url(getattr(response, "url", normalized_candidate))
            if not _is_allowed_image_content_type(content_type):
                return _ImageProbeResult(
                    accepted=False,
                    content_type=content_type,
                    final_url=final_url,
                    byte_size=None,
                    fetch_status="validated_get",
                    diagnostic_reason=f"get_non_image_content_type_{content_type or 'unknown'}",
                )
            body = _read_bounded_candidate_payload(response=response, max_bytes=max_probe_bytes)
            return _ImageProbeResult(
                accepted=True,
                content_type=content_type,
                final_url=final_url,
                byte_size=len(body),
                fetch_status="validated_get",
                diagnostic_reason=None,
            )
    except urllib.error.HTTPError as exc:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="get_failed",
            diagnostic_reason=f"get_http_{exc.code}",
        )
    except urllib.error.URLError as exc:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="get_failed",
            diagnostic_reason=f"get_network_{_clean_optional_text(getattr(exc, 'reason', None)) or 'unknown'}",
        )
    except TimeoutError:
        return _ImageProbeResult(
            accepted=False,
            content_type=None,
            final_url=None,
            byte_size=None,
            fetch_status="get_timeout",
            diagnostic_reason="get_timeout",
        )


def _read_bounded_candidate_payload(*, response, max_bytes: int) -> bytes:  # noqa: ANN001
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = response.read(8_192)
        if not chunk:
            break
        total += len(chunk)
        chunks.append(chunk)
        if total >= max_bytes:
            break
    return b"".join(chunks)


def _normalize_content_type(value: object) -> str | None:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return None
    return cleaned.split(";", 1)[0].strip().lower() or None


def _is_allowed_image_content_type(value: str | None) -> bool:
    if value is None:
        return False
    return value in _IMAGE_PROBE_ALLOWED_CONTENT_TYPES


def _normalize_fetch_url(value: object) -> str | None:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return None
    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            "",
        )
    )


def _path_extension(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    path = (parsed.path or "").strip().lower()
    if not path:
        return ""
    _, _, tail = path.rpartition("/")
    filename = tail or path
    dot_index = filename.rfind(".")
    if dot_index <= 0:
        return ""
    return filename[dot_index:]


def _is_disallowed_host(hostname: str | None) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal", "metadata"}:
        return True
    if host.endswith(".localhost") or host.endswith(".local"):
        return True

    try:
        direct_ip = ipaddress.ip_address(host)
    except ValueError:
        direct_ip = None
    if direct_ip is not None:
        return _is_disallowed_ip(direct_ip)

    try:
        resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        # If DNS cannot be resolved here, rely on runtime fetch safeguards.
        return False
    for item in resolved:
        if not isinstance(item, tuple) or len(item) < 5:
            continue
        sockaddr = item[4]
        if not isinstance(sockaddr, tuple) or not sockaddr:
            continue
        candidate = sockaddr[0]
        try:
            resolved_ip = ipaddress.ip_address(str(candidate))
        except ValueError:
            continue
        if _is_disallowed_ip(resolved_ip):
            return True
    return False


def _is_disallowed_ip(value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_unspecified
        or value.is_reserved
    )


def _strip_url_query(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return value
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            "",
        )
    )


def _format_datetime(value: datetime) -> str:
    return value.isoformat()

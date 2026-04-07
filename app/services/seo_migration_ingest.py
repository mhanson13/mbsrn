from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import re
import urllib.parse
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


class SEOMigrationSourceIngestError(ValueError):
    pass


@dataclass(frozen=True)
class SEOMigrationIngestResult:
    source_url: str
    snapshot: dict[str, object]
    warnings: tuple[str, ...]


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
        self._seen_contact_signals: set[str] = set()
        self._seen_stylesheets: set[str] = set()
        self._seen_scripts: set[str] = set()
        self._seen_images: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        lower_tag = (tag or "").lower()
        attrs_dict = {str(key).lower(): str(value) for key, value in attrs if key and value}
        self._current_tag = lower_tag
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
            src = attrs_dict.get("src")
            if src:
                normalized = self._normalize_url(src)
                if normalized and normalized not in self._seen_images:
                    self._seen_images.add(normalized)
                    self.asset_images.append(normalized)
        if lower_tag == "a":
            href = attrs_dict.get("href")
            if href:
                normalized_link = self._normalize_url(href)
                if normalized_link and _is_same_origin(self.base_url, normalized_link):
                    if normalized_link not in self._seen_internal_links:
                        self._seen_internal_links.add(normalized_link)
                        if len(self.internal_links) < self.max_internal_links:
                            self.internal_links.append(normalized_link)
                        elif "Internal link list was truncated." not in self.warnings:
                            self.warnings.append("Internal link list was truncated.")
            anchor_hint = attrs_dict.get("aria-label") or attrs_dict.get("title")
            if anchor_hint:
                self._capture_contact_signal(anchor_hint)

    def handle_endtag(self, tag: str) -> None:
        lower_tag = (tag or "").lower()
        if lower_tag == "title":
            self._in_title = False
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
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_redirects = max(0, int(max_redirects))
        self.max_response_bytes = max(10_000, int(max_response_bytes))
        self.max_internal_links = max(1, int(max_internal_links))
        self.max_text_blocks = max(1, int(max_text_blocks))
        self.max_headings = max(1, int(max_headings))

    def ingest_homepage(self, *, source_url: str) -> SEOMigrationIngestResult:
        normalized_source_url = self._normalize_source_url(source_url)
        opener = urllib.request.build_opener(_BoundedRedirectHandler(max_redirects=self.max_redirects))
        request = urllib.request.Request(
            normalized_source_url,
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
                final_url = str(getattr(response, "url", normalized_source_url) or normalized_source_url)
                status_code = int(getattr(response, "status", 200) or 200)
                charset = _resolve_charset(content_type_header)
        except urllib.error.HTTPError as exc:
            raise SEOMigrationSourceIngestError(f"Source ingest failed with HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise SEOMigrationSourceIngestError("Source ingest failed due to network error.") from exc
        except TimeoutError as exc:
            raise SEOMigrationSourceIngestError("Source ingest timed out.") from exc

        body_text = body_bytes.decode(charset, errors="replace")
        parser = _HomepageExtractParser(
            base_url=final_url,
            max_internal_links=self.max_internal_links,
            max_text_blocks=self.max_text_blocks,
            max_headings=self.max_headings,
        )
        parser.feed(body_text)
        parser.close()

        combined_text = "\n".join(parser.text_blocks)
        phones = _dedupe_results(_PHONE_PATTERN.findall(combined_text), max_items=_MAX_PHONE_RESULTS, max_len=48)
        emails = _dedupe_results(_EMAIL_PATTERN.findall(combined_text), max_items=_MAX_EMAIL_RESULTS, max_len=120)
        addresses = _dedupe_results(
            _ADDRESS_PATTERN.findall(combined_text), max_items=_MAX_ADDRESS_RESULTS, max_len=180
        )
        fetched_at = _format_datetime(utc_now())

        snapshot: dict[str, object] = {
            "fetched_at": fetched_at,
            "final_url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "title": parser.title,
            "meta_description": parser.meta_description,
            "canonical_url": parser.canonical_url,
            "headings": parser.headings,
            "contact_signals": parser.contact_signals,
            "phone_numbers": phones,
            "emails": emails,
            "addresses": addresses,
            "internal_links": parser.internal_links,
            "service_blocks": parser.service_blocks,
            "asset_references": {
                "stylesheets": parser.asset_stylesheets[:60],
                "scripts": parser.asset_scripts[:60],
                "images": parser.asset_images[:60],
            },
            "cleaned_text_blocks": parser.text_blocks,
            "warnings": parser.warnings,
        }
        return SEOMigrationIngestResult(
            source_url=normalized_source_url,
            snapshot=snapshot,
            warnings=tuple(parser.warnings),
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


def _format_datetime(value: datetime) -> str:
    return value.isoformat()

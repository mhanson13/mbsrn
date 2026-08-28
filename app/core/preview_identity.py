from __future__ import annotations

from dataclasses import dataclass
import re


PREVIEW_BASE_DOMAIN = "site.mbsrn.com"
_PREVIEW_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESERVED_PREVIEW_SLUGS = {
    "admin",
    "api",
    "app",
    "ftp",
    "mail",
    "mbsrn",
    "operator",
    "site",
    "smtp",
    "status",
    "support",
    "www",
}


class PreviewIdentityValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SitePreviewIdentity:
    slug: str
    hostname: str


def normalize_preview_slug(value: object, *, allow_none: bool = True) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise PreviewIdentityValidationError("preview_slug is required before preview infrastructure is created")
    normalized = str(value).strip().lower()
    if not normalized:
        if allow_none:
            return None
        raise PreviewIdentityValidationError("preview_slug is required before preview infrastructure is created")
    if not _PREVIEW_SLUG_PATTERN.fullmatch(normalized):
        raise PreviewIdentityValidationError(
            "preview_slug must be a lowercase DNS label using letters, numbers, and interior hyphens"
        )
    if normalized in _RESERVED_PREVIEW_SLUGS:
        raise PreviewIdentityValidationError("preview_slug is reserved for platform use")
    return normalized


def build_site_preview_identity(value: object) -> SitePreviewIdentity:
    slug = normalize_preview_slug(value, allow_none=False)
    assert slug is not None
    return SitePreviewIdentity(slug=slug, hostname=f"{slug}.{PREVIEW_BASE_DOMAIN}")

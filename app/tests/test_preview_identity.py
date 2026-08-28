from __future__ import annotations

import pytest

from app.core.preview_identity import (
    PreviewIdentityValidationError,
    build_site_preview_identity,
    normalize_preview_slug,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PlatFire", "platfire"),
        ("  second-preview  ", "second-preview"),
        ("site-123", "site-123"),
    ],
)
def test_preview_slug_normalization(value: str, expected: str) -> None:
    assert normalize_preview_slug(value) == expected
    assert build_site_preview_identity(value).hostname == f"{expected}.site.mbsrn.com"


@pytest.mark.parametrize("value", ["www", "api", "-leading", "trailing-", "has space", "under_score"])
def test_preview_slug_rejects_reserved_or_invalid_labels(value: str) -> None:
    with pytest.raises(PreviewIdentityValidationError):
        build_site_preview_identity(value)

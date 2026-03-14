from __future__ import annotations

from app.models.seo_audit_page import SEOAuditPage
from app.services.seo_finding_rules import SEOFindingRules


def _page(
    *,
    page_id: str,
    url: str,
    title: str | None,
    meta_description: str | None,
    h1_json: list[str] | None,
    h2_json: list[str] | None,
    canonical_url: str | None,
    word_count: int,
    internal_link_count: int,
) -> SEOAuditPage:
    return SEOAuditPage(
        id=page_id,
        business_id="11111111-1111-1111-1111-111111111111",
        site_id="22222222-2222-2222-2222-222222222222",
        audit_run_id="33333333-3333-3333-3333-333333333333",
        url=url,
        status_code=200,
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        h1_json=h1_json,
        h2_json=h2_json,
        word_count=word_count,
        internal_link_count=internal_link_count,
        image_count=0,
        missing_alt_count=0,
    )


def test_finding_rules_cover_additional_deterministic_checks() -> None:
    rules = SEOFindingRules(thin_content_min_words=150, extremely_thin_content_min_words=30)
    page = _page(
        page_id="page-1",
        url="https://example.com/service",
        title="Hi",
        meta_description="Short meta",
        h1_json=["Service", "Another H1"],
        h2_json=[],
        canonical_url=None,
        word_count=10,
        internal_link_count=0,
    )

    findings = rules.evaluate(pages=[page])
    finding_types = {item.finding_type for item in findings}

    assert "title_too_short" in finding_types
    assert "meta_description_too_short" in finding_types
    assert "multiple_h1" in finding_types
    assert "missing_h2" in finding_types
    assert "thin_content" in finding_types
    assert "extremely_thin_content" in finding_types
    assert "missing_internal_links" in finding_types
    assert "missing_canonical" in finding_types


def test_duplicate_title_and_meta_detection_is_case_insensitive_per_run() -> None:
    rules = SEOFindingRules(thin_content_min_words=1, extremely_thin_content_min_words=0)
    page_a = _page(
        page_id="page-a",
        url="https://example.com/a",
        title="Fire Restoration Denver",
        meta_description="Fast fire restoration in Denver with 24/7 response.",
        h1_json=["Fire Restoration"],
        h2_json=["Why choose us"],
        canonical_url="https://example.com/a",
        word_count=300,
        internal_link_count=2,
    )
    page_b = _page(
        page_id="page-b",
        url="https://example.com/b",
        title="fire restoration denver",
        meta_description="FAST FIRE RESTORATION IN DENVER WITH 24/7 RESPONSE.",
        h1_json=["Fire Damage Help"],
        h2_json=["Service areas"],
        canonical_url="https://example.com/b",
        word_count=280,
        internal_link_count=2,
    )

    findings = rules.evaluate(pages=[page_a, page_b])
    duplicate_title = [item for item in findings if item.finding_type == "duplicate_title"]
    duplicate_meta = [item for item in findings if item.finding_type == "duplicate_meta_description"]

    assert len(duplicate_title) == 2
    assert len(duplicate_meta) == 2

from __future__ import annotations

from dataclasses import dataclass

from app.models.seo_audit_page import SEOAuditPage


@dataclass(frozen=True)
class FindingDraft:
    page_id: str | None
    finding_type: str
    category: str
    severity: str
    title: str
    details: str
    rule_key: str
    suggested_fix: str | None


class SEOFindingRules:
    def __init__(
        self,
        *,
        thin_content_min_words: int = 150,
        extremely_thin_content_min_words: int = 30,
        title_min_length: int = 20,
        title_max_length: int = 60,
        meta_min_length: int = 70,
        meta_max_length: int = 160,
    ) -> None:
        self.thin_content_min_words = thin_content_min_words
        self.extremely_thin_content_min_words = extremely_thin_content_min_words
        self.title_min_length = title_min_length
        self.title_max_length = title_max_length
        self.meta_min_length = meta_min_length
        self.meta_max_length = meta_max_length

    def evaluate(
        self,
        *,
        pages: list[SEOAuditPage],
        broken_internal_links_by_page_id: dict[str, int] | None = None,
    ) -> list[FindingDraft]:
        findings: list[FindingDraft] = []
        broken_map = broken_internal_links_by_page_id or {}

        title_to_pages: dict[str, list[SEOAuditPage]] = {}
        meta_to_pages: dict[str, list[SEOAuditPage]] = {}

        for page in pages:
            if not (page.title or "").strip():
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="missing_title",
                        category="metadata",
                        severity="high",
                        title="Missing title tag",
                        details=f"Page {page.url} has no title tag.",
                        rule_key="missing_title",
                        suggested_fix="Add a unique title tag with service and location intent.",
                    )
                )
            else:
                normalized_title = page.title.strip()
                key = normalized_title.lower()
                title_to_pages.setdefault(key, []).append(page)
                title_length = len(normalized_title)
                if title_length < self.title_min_length:
                    findings.append(
                        FindingDraft(
                            page_id=page.id,
                            finding_type="title_too_short",
                            category="metadata",
                            severity="medium",
                            title="Title tag too short",
                            details=(
                                f"Page {page.url} title length is {title_length}. "
                                f"Recommended minimum is {self.title_min_length}."
                            ),
                            rule_key="title_too_short",
                            suggested_fix="Expand title tag with clear service and location intent.",
                        )
                    )
                if title_length > self.title_max_length:
                    findings.append(
                        FindingDraft(
                            page_id=page.id,
                            finding_type="title_too_long",
                            category="metadata",
                            severity="low",
                            title="Title tag too long",
                            details=(
                                f"Page {page.url} title length is {title_length}. "
                                f"Recommended maximum is {self.title_max_length}."
                            ),
                            rule_key="title_too_long",
                            suggested_fix="Shorten title tag while keeping service and location keywords.",
                        )
                    )

            if not (page.meta_description or "").strip():
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="missing_meta_description",
                        category="metadata",
                        severity="medium",
                        title="Missing meta description",
                        details=f"Page {page.url} has no meta description.",
                        rule_key="missing_meta_description",
                        suggested_fix="Add a clear meta description with service and location context.",
                    )
                )
            else:
                normalized_meta = page.meta_description.strip()
                meta_key = normalized_meta.lower()
                meta_to_pages.setdefault(meta_key, []).append(page)
                meta_length = len(normalized_meta)
                if meta_length < self.meta_min_length:
                    findings.append(
                        FindingDraft(
                            page_id=page.id,
                            finding_type="meta_description_too_short",
                            category="metadata",
                            severity="low",
                            title="Meta description too short",
                            details=(
                                f"Page {page.url} meta description length is {meta_length}. "
                                f"Recommended minimum is {self.meta_min_length}."
                            ),
                            rule_key="meta_description_too_short",
                            suggested_fix="Expand meta description with service and local context.",
                        )
                    )
                if meta_length > self.meta_max_length:
                    findings.append(
                        FindingDraft(
                            page_id=page.id,
                            finding_type="meta_description_too_long",
                            category="metadata",
                            severity="low",
                            title="Meta description too long",
                            details=(
                                f"Page {page.url} meta description length is {meta_length}. "
                                f"Recommended maximum is {self.meta_max_length}."
                            ),
                            rule_key="meta_description_too_long",
                            suggested_fix="Shorten meta description to focus on service and local intent.",
                        )
                    )

            h1_items = page.h1_json or []
            if len(h1_items) == 0:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="missing_h1",
                        category="content",
                        severity="medium",
                        title="Missing H1 heading",
                        details=f"Page {page.url} has no H1 heading.",
                        rule_key="missing_h1",
                        suggested_fix="Add one clear H1 that matches page intent.",
                    )
                )
            elif len(h1_items) > 1:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="multiple_h1",
                        category="content",
                        severity="medium",
                        title="Multiple H1 headings",
                        details=f"Page {page.url} has {len(h1_items)} H1 headings.",
                        rule_key="multiple_h1",
                        suggested_fix="Use one primary H1 and move additional headings to H2 or H3.",
                    )
                )

            h2_items = page.h2_json or []
            if len(h2_items) == 0:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="missing_h2",
                        category="content",
                        severity="low",
                        title="Missing H2 headings",
                        details=f"Page {page.url} has no H2 headings.",
                        rule_key="missing_h2",
                        suggested_fix="Add H2 sections to improve structure and readability.",
                    )
                )

            if not (page.canonical_url or "").strip():
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="missing_canonical",
                        category="technical",
                        severity="low",
                        title="Missing canonical URL",
                        details=f"Page {page.url} has no canonical tag.",
                        rule_key="missing_canonical",
                        suggested_fix="Add a canonical link tag for preferred URL.",
                    )
                )

            word_count = page.word_count or 0
            if word_count < self.thin_content_min_words:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="thin_content",
                        category="content",
                        severity="medium",
                        title="Thin content",
                        details=(
                            f"Page {page.url} has low word count ({word_count}). "
                            f"Minimum target is {self.thin_content_min_words}."
                        ),
                        rule_key="thin_content",
                        suggested_fix="Expand page copy with service details, proof, and location context.",
                    )
                )
            if word_count < self.extremely_thin_content_min_words:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="extremely_thin_content",
                        category="content",
                        severity="high",
                        title="Extremely thin content",
                        details=(
                            f"Page {page.url} has very low word count ({word_count}). "
                            f"Minimum target is {self.extremely_thin_content_min_words}."
                        ),
                        rule_key="extremely_thin_content",
                        suggested_fix="Add substantial page content with clear service, location, and trust signals.",
                    )
                )

            if (page.internal_link_count or 0) == 0:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="missing_internal_links",
                        category="technical",
                        severity="low",
                        title="Missing internal links",
                        details=f"Page {page.url} has no internal outgoing links.",
                        rule_key="missing_internal_links",
                        suggested_fix="Add internal links to related service and trust pages.",
                    )
                )

            broken_count = broken_map.get(page.id, 0)
            if broken_count > 0:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="broken_internal_links",
                        category="technical",
                        severity="high",
                        title="Broken internal links",
                        details=f"Page {page.url} contains {broken_count} broken internal links.",
                        rule_key="broken_internal_links",
                        suggested_fix="Update or remove broken internal links.",
                    )
                )

        for title_key, grouped_pages in title_to_pages.items():
            if len(grouped_pages) <= 1:
                continue
            for page in grouped_pages:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="duplicate_title",
                        category="metadata",
                        severity="high",
                        title="Duplicate title tag",
                        details=f"Title '{title_key}' appears on multiple pages in this run.",
                        rule_key="duplicate_title",
                        suggested_fix="Make each title unique per page intent.",
                    )
                )

        for meta_key, grouped_pages in meta_to_pages.items():
            if len(grouped_pages) <= 1:
                continue
            for page in grouped_pages:
                findings.append(
                    FindingDraft(
                        page_id=page.id,
                        finding_type="duplicate_meta_description",
                        category="metadata",
                        severity="medium",
                        title="Duplicate meta description",
                        details=f"Meta description '{meta_key}' appears on multiple pages in this run.",
                        rule_key="duplicate_meta_description",
                        suggested_fix="Write unique meta descriptions per page.",
                    )
                )

        return findings

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Literal
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_audit_summary import SEOAuditSummary
from app.models.seo_automation_config import SEOAutomationConfig
from app.models.seo_automation_run import SEOAutomationRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_site import extract_primary_business_zip, normalize_primary_business_zip
from app.schemas.seo_site import SEOSiteCreateRequest, SEOSiteUpdateRequest


class SEOSiteNotFoundError(ValueError):
    pass


class SEOSiteValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedURL:
    url: str
    domain: str


SEOLocationContextStrength = Literal["strong", "weak"]
SEOLocationContextSource = Literal["explicit_location", "service_area", "zip_capture", "fallback"]
_ZIP_CAPTURE_ALLOWED_TOKENS = {"zip", "code", "serving", "service", "area", "around", "primary"}
_LOCATION_CONTEXT_FALLBACK_TEXT = "Location not yet established from available business/site data."
_MAX_SERVICE_AREAS = 25
_SITE_CONTEXT_FALLBACK_TARGET_CUSTOMER = "Customers seeking clearly substitutable services in the same market context."
_SITE_CONTEXT_FALLBACK_INDUSTRY = "Industry not yet confidently classified from available structured data."
_SITE_CONTEXT_MAX_SERVICE_TERMS = 8
_SITE_CONTEXT_EMBEDDED_DOMAIN_PATTERN = re.compile(
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+\b",
    re.IGNORECASE,
)
_SITE_CONTEXT_SERVICE_NOISE_TOKENS = {
    "about",
    "and",
    "biz",
    "business",
    "co",
    "company",
    "com",
    "contact",
    "corp",
    "corporation",
    "example",
    "group",
    "home",
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "net",
    "org",
    "services",
    "service",
    "site",
    "welcome",
    "www",
}
_SITE_CONTEXT_GENERIC_INDUSTRY_TOKENS = {
    "business",
    "company",
    "expert",
    "experts",
    "group",
    "professional",
    "professionals",
    "provider",
    "providers",
    "service",
    "services",
    "solutions",
    "support",
}
_SITE_CONTEXT_DOMAIN_NOISE_TOKENS = {
    "app",
    "biz",
    "ca",
    "co",
    "com",
    "info",
    "io",
    "localhost",
    "net",
    "online",
    "org",
    "site",
    "test",
    "uk",
    "us",
    "www",
}
_SITE_CONTEXT_SERVICE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("seo", ("seo", "search engine optimization")),
    ("digital marketing", ("digital marketing", "online marketing", "marketing agency", "growth marketing")),
    ("web design", ("web design", "website design", "web development", "website development")),
    ("web hosting", ("web hosting", "managed hosting", "cloud hosting", "hosting provider", "website hosting")),
    ("managed it services", ("managed it", "it services", "it support", "network support", "cybersecurity")),
    ("general contractor", ("general contractor", "general contracting")),
    ("construction", ("construction", "contracting", "builder", "builders")),
    ("remodeling", ("remodel", "renovation", "renovations")),
    ("kitchen remodel", ("kitchen remodel", "kitchen renovation", "kitchen remodeling")),
    ("bathroom remodel", ("bathroom remodel", "bathroom renovation", "bathroom remodeling")),
    ("commercial tenant finish", ("tenant finish", "tenant improvement", "tenant buildout", "commercial buildout")),
    ("flooring", ("flooring", "floor installation")),
    ("hardwood flooring", ("hardwood flooring", "hardwood floor", "hardwood installation", "wood floor")),
    ("tile installation", ("tile installation", "tile floor", "tile flooring")),
    ("carpet installation", ("carpet installation", "carpet flooring", "carpet replacement")),
    ("floor refinishing", ("floor refinishing", "hardwood refinishing", "floor refinish")),
    ("roofing", ("roofing", "roof repair", "roof replacement")),
    ("plumbing", ("plumbing", "plumber")),
    ("electrical", ("electrical", "electrician")),
    ("hvac", ("hvac", "heating", "cooling", "air conditioning")),
    ("landscaping", ("landscaping", "landscape")),
    ("concrete", ("concrete", "foundation")),
    ("painting", ("painting", "painter")),
    ("home services", ("home service", "home services")),
)

# Ordered child-table deletion for permanent site removal.
_SITE_PERMANENT_DELETE_MODELS = (
    SEOCompetitorTuningPreviewEvent,
    SEORecommendationNarrative,
    SEORecommendation,
    SEORecommendationRun,
    SEOCompetitorProfileDraft,
    SEOCompetitorProfileGenerationRun,
    SEOCompetitorComparisonSummary,
    SEOCompetitorComparisonFinding,
    SEOCompetitorComparisonRun,
    SEOCompetitorSnapshotPage,
    SEOCompetitorSnapshotRun,
    SEOCompetitorDomain,
    SEOCompetitorSet,
    SEOAuditSummary,
    SEOAuditFinding,
    SEOAuditPage,
    SEOAuditRun,
    SEOAutomationRun,
    SEOAutomationConfig,
    SEOCompetitorProfileCleanupExecution,
)


SEOIndustryContextStrength = Literal["strong", "weak"]
SEOServiceFocusSource = Literal[
    "site_content",
    "structured_metadata",
    "domain_hints",
    "explicit_industry",
    "fallback",
]


@dataclass(frozen=True)
class SEOSiteBusinessContext:
    industry_context: str
    industry_context_strength: SEOIndustryContextStrength
    service_focus_terms: list[str]
    target_customer_context: str
    service_focus_terms_sources: list[SEOServiceFocusSource]
    service_focus_terms_dropped: list[str]


@dataclass(frozen=True)
class SEOSiteLocationContext:
    location_context: str
    location_context_strength: SEOLocationContextStrength
    location_context_source: SEOLocationContextSource
    primary_location: str | None
    primary_business_zip: str | None
    service_areas: list[str]


def build_primary_location_from_zip(zip_code: str) -> str:
    return f"Serving area around ZIP code {zip_code}"


def build_location_context(site: SEOSite) -> SEOSiteLocationContext:
    primary_location = _clean_location_text(site.primary_location)
    service_areas = _normalize_location_service_areas(site.service_areas_json)
    primary_business_zip = _extract_location_zip(primary_location=primary_location, service_areas=service_areas)

    if primary_location and not _is_zip_capture_location(primary_location):
        if service_areas:
            non_duplicate_service_areas = [area for area in service_areas if area.lower() != primary_location.lower()]
            if non_duplicate_service_areas:
                preview = non_duplicate_service_areas[:3]
                suffix = " and surrounding areas" if len(non_duplicate_service_areas) > 3 else ""
                location_context = f"{primary_location} and nearby service areas: {', '.join(preview)}{suffix}"
            else:
                location_context = primary_location
        else:
            location_context = primary_location
        return SEOSiteLocationContext(
            location_context=location_context,
            location_context_strength="strong",
            location_context_source="explicit_location",
            primary_location=primary_location,
            primary_business_zip=primary_business_zip,
            service_areas=service_areas,
        )

    if service_areas:
        preview = service_areas[:4]
        suffix = " and surrounding areas" if len(service_areas) > 4 else ""
        return SEOSiteLocationContext(
            location_context=f"Serves {', '.join(preview)}{suffix}",
            location_context_strength="strong",
            location_context_source="service_area",
            primary_location=primary_location,
            primary_business_zip=primary_business_zip,
            service_areas=service_areas,
        )

    if primary_business_zip:
        return SEOSiteLocationContext(
            location_context=build_primary_location_from_zip(primary_business_zip),
            location_context_strength="strong",
            location_context_source="zip_capture",
            primary_location=primary_location,
            primary_business_zip=primary_business_zip,
            service_areas=service_areas,
        )

    return SEOSiteLocationContext(
        location_context=_LOCATION_CONTEXT_FALLBACK_TEXT,
        location_context_strength="weak",
        location_context_source="fallback",
        primary_location=primary_location,
        primary_business_zip=primary_business_zip,
        service_areas=service_areas,
    )


def build_site_business_context(
    *,
    site: SEOSite,
    location_context: SEOSiteLocationContext,
    business_name: str | None = None,
    normalized_domain: str | None = None,
    site_content_signals: list[str] | None = None,
) -> SEOSiteBusinessContext:
    cleaned_industry = _clean_location_text(getattr(site, "industry", None))
    cleaned_display_name = _clean_location_text(getattr(site, "display_name", None))
    cleaned_business_name = _clean_location_text(business_name)
    effective_domain = _clean_location_text(normalized_domain) or _clean_location_text(
        getattr(site, "normalized_domain", None)
    )
    inference_display_name = _display_name_for_structured_inference(
        cleaned_display_name=cleaned_display_name,
        effective_domain=effective_domain,
    )
    content_sources = _normalize_context_sources(site_content_signals or [])
    structured_sources = _normalize_context_sources(
        [
            cleaned_industry or "",
            inference_display_name or "",
            cleaned_business_name or "",
        ]
    )
    domain_sources = _extract_domain_service_source(effective_domain or "")

    content_terms = _infer_service_terms_from_sources(
        content_sources,
        max_terms=_SITE_CONTEXT_MAX_SERVICE_TERMS,
        allow_token_fallback=True,
    )
    structured_terms = _infer_service_terms_from_sources(
        structured_sources,
        max_terms=_SITE_CONTEXT_MAX_SERVICE_TERMS,
        allow_token_fallback=False,
    )
    domain_terms = _infer_service_terms_from_sources(
        domain_sources,
        max_terms=_SITE_CONTEXT_MAX_SERVICE_TERMS,
        allow_token_fallback=False,
    )

    primary_service_terms: list[str]
    primary_service_source: SEOServiceFocusSource
    if content_terms:
        primary_service_terms = content_terms
        primary_service_source = "site_content"
    elif structured_terms:
        primary_service_terms = structured_terms
        primary_service_source = "structured_metadata"
    elif domain_terms:
        primary_service_terms = domain_terms
        primary_service_source = "domain_hints"
    else:
        primary_service_terms = []
        primary_service_source = "fallback"

    service_focus_terms = _dedupe_terms(
        primary_service_terms,
        max_terms=_SITE_CONTEXT_MAX_SERVICE_TERMS,
    )
    service_focus_terms_sources: list[SEOServiceFocusSource] = []
    if service_focus_terms:
        service_focus_terms_sources.append(primary_service_source)
    service_focus_terms_dropped: list[str] = []
    explicit_industry_conflicted = False
    if cleaned_industry:
        explicit_industry_conflicted = bool(content_terms) and not _is_explicit_industry_supported_by_content(
            cleaned_industry=cleaned_industry,
            content_sources=content_sources,
            content_terms=content_terms,
        )
        if explicit_industry_conflicted:
            service_focus_terms_dropped.append(cleaned_industry)
        else:
            service_focus_terms = _dedupe_terms(
                [cleaned_industry, *service_focus_terms],
                max_terms=_SITE_CONTEXT_MAX_SERVICE_TERMS,
            )
            if "explicit_industry" not in service_focus_terms_sources:
                service_focus_terms_sources.append("explicit_industry")
    if not service_focus_terms_sources:
        service_focus_terms_sources.append("fallback")

    if cleaned_industry and not explicit_industry_conflicted:
        industry_context = cleaned_industry
        industry_context_strength: SEOIndustryContextStrength = "strong"
    elif content_terms:
        qualifier = _derive_market_qualifier(content_sources)
        primary_term = content_terms[0]
        industry_context = f"{qualifier}{primary_term.title()} services"
        industry_context_strength = "strong"
    elif structured_terms:
        industry_context = f"{structured_terms[0].title()} services (inferred from structured metadata)."
        industry_context_strength = "weak"
    elif domain_terms:
        industry_context = f"{domain_terms[0].title()} services (inferred from site identity hints)."
        industry_context_strength = "weak"
    else:
        industry_context = _SITE_CONTEXT_FALLBACK_INDUSTRY
        industry_context_strength = "weak"

    service_phrase = ", ".join(service_focus_terms[:3]) if service_focus_terms else None
    if not service_phrase:
        service_phrase = industry_context if industry_context_strength == "strong" else "clearly substitutable services"
    target_customer_context = _build_target_customer_context(
        location_context=location_context.location_context,
        has_location_context=location_context.location_context_strength == "strong",
        service_phrase=service_phrase,
    )

    return SEOSiteBusinessContext(
        industry_context=industry_context,
        industry_context_strength=industry_context_strength,
        service_focus_terms=service_focus_terms,
        target_customer_context=target_customer_context,
        service_focus_terms_sources=service_focus_terms_sources,
        service_focus_terms_dropped=service_focus_terms_dropped,
    )


def _clean_location_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _normalize_context_sources(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        cleaned = _clean_location_text(value)
        if cleaned:
            normalized.append(cleaned.lower())
    return normalized


def _is_explicit_industry_supported_by_content(
    *,
    cleaned_industry: str,
    content_sources: list[str],
    content_terms: list[str],
) -> bool:
    normalized_content_terms = {term.lower() for term in content_terms if term}
    explicit_hint_terms = _infer_service_terms_from_sources(
        [cleaned_industry.lower()],
        max_terms=_SITE_CONTEXT_MAX_SERVICE_TERMS,
        allow_token_fallback=False,
    )
    if explicit_hint_terms:
        for term in explicit_hint_terms:
            if term.lower() in normalized_content_terms:
                return True

    explicit_tokens = [
        token
        for token in _tokenize_context(cleaned_industry.lower())
        if len(token) >= 4
        and token not in _SITE_CONTEXT_SERVICE_NOISE_TOKENS
        and token not in _SITE_CONTEXT_GENERIC_INDUSTRY_TOKENS
    ]
    if not explicit_tokens:
        return False

    for source in content_sources:
        for token in explicit_tokens:
            if token in source:
                return True
    return False


def _display_name_for_structured_inference(
    *,
    cleaned_display_name: str | None,
    effective_domain: str | None,
) -> str | None:
    if cleaned_display_name is None:
        return None
    normalized_effective_domain = _normalize_site_domain_for_match(effective_domain)
    if normalized_effective_domain is None:
        return cleaned_display_name
    embedded_domains = [
        _normalize_site_domain_for_match(match.group(0))
        for match in _SITE_CONTEXT_EMBEDDED_DOMAIN_PATTERN.finditer(cleaned_display_name)
    ]
    embedded_domains = [domain for domain in embedded_domains if domain is not None]
    if not embedded_domains:
        return cleaned_display_name
    if any(
        _is_matching_site_domain(
            embedded_domain,
            normalized_effective_domain,
        )
        for embedded_domain in embedded_domains
    ):
        return cleaned_display_name
    return None


def _normalize_site_domain_for_match(value: str | None) -> str | None:
    cleaned = _clean_location_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.lower().strip().strip(".")
    if not lowered:
        return None
    if "://" in lowered:
        parsed = urlparse(lowered)
        lowered = (parsed.hostname or "").lower().strip().strip(".")
        if not lowered:
            return None
    if lowered.startswith("www."):
        lowered = lowered[4:]
    return lowered or None


def _is_matching_site_domain(candidate_domain: str, effective_domain: str) -> bool:
    if candidate_domain == effective_domain:
        return True
    if candidate_domain.endswith(f".{effective_domain}"):
        return True
    if effective_domain.endswith(f".{candidate_domain}"):
        return True
    return False


def _tokenize_context(value: str) -> list[str]:
    filtered = []
    for char in value:
        if char.isalnum():
            filtered.append(char.lower())
        else:
            filtered.append(" ")
    tokens = " ".join("".join(filtered).split()).split(" ")
    return [token for token in tokens if token]


def _extract_domain_service_source(normalized_domain: str) -> list[str]:
    labels: list[str] = []
    for label in normalized_domain.split("."):
        cleaned = label.strip().lower()
        if not cleaned or cleaned in _SITE_CONTEXT_DOMAIN_NOISE_TOKENS:
            continue
        labels.append(cleaned)
    return labels


def _infer_service_terms_from_sources(
    raw_sources: list[str],
    *,
    max_terms: int,
    allow_token_fallback: bool,
) -> list[str]:
    if not raw_sources:
        return []

    corpus = " ".join(raw_sources)
    inferred: list[str] = []
    seen: set[str] = set()
    for label, fragments in _SITE_CONTEXT_SERVICE_HINTS:
        if len(inferred) >= max_terms:
            break
        if any(fragment in corpus for fragment in fragments):
            lowered = label.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            inferred.append(label)

    if inferred:
        return inferred

    if not allow_token_fallback:
        return []

    token_counts: Counter[str] = Counter()
    for source in raw_sources:
        for token in _tokenize_context(source):
            if len(token) < 4:
                continue
            if token in _SITE_CONTEXT_SERVICE_NOISE_TOKENS:
                continue
            token_counts[token] += 1

    fallback_terms: list[str] = []
    for token, count in token_counts.most_common(max_terms):
        if count < 2:
            continue
        fallback_terms.append(token)
    return fallback_terms


def _dedupe_terms(terms: list[str], *, max_terms: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = _clean_location_text(term)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(cleaned)
        if len(deduped) >= max_terms:
            break
    return deduped


def _derive_market_qualifier(content_sources: list[str]) -> str:
    corpus = " ".join(content_sources)
    has_residential = "residential" in corpus
    has_commercial = "commercial" in corpus
    if has_residential and has_commercial:
        return "Residential and commercial "
    if has_residential:
        return "Residential "
    if has_commercial:
        return "Commercial "
    return ""


def _build_target_customer_context(
    *,
    location_context: str,
    has_location_context: bool,
    service_phrase: str,
) -> str:
    if not has_location_context:
        return f"Customers seeking {service_phrase} and evaluating clearly substitutable providers in the same market context."
    return f"Customers in {location_context} seeking {service_phrase} and evaluating comparable local providers."


def _normalize_location_service_areas(service_areas: list[str] | None) -> list[str]:
    if not isinstance(service_areas, list):
        return []
    normalized: set[str] = set()
    for item in service_areas:
        if not isinstance(item, str):
            continue
        compacted = _clean_location_text(item)
        if compacted:
            normalized.add(compacted)
    return sorted(normalized)[:_MAX_SERVICE_AREAS]


def _extract_location_zip(*, primary_location: str | None, service_areas: list[str]) -> str | None:
    if primary_location:
        matched = extract_primary_business_zip(primary_location)
        if matched is not None:
            return matched
    for area in service_areas:
        matched = extract_primary_business_zip(area)
        if matched is not None:
            return matched
    return None


def _is_zip_capture_location(primary_location: str) -> bool:
    if extract_primary_business_zip(primary_location) is None:
        return False
    normalized = " ".join(primary_location.lower().split())
    normalized = re.sub(r"\b\d{5}\b", " ", normalized)
    normalized = re.sub(r"[^a-z]+", " ", normalized)
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return True
    return all(token in _ZIP_CAPTURE_ALLOWED_TOKENS for token in tokens)


class SEOSiteService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository

    def list_sites(self, *, business_id: str) -> list[SEOSite]:
        self._require_business(business_id)
        return self.seo_site_repository.list_for_business(business_id)

    def get_site(self, *, business_id: str, site_id: str) -> SEOSite:
        self._require_business(business_id)
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOSiteNotFoundError("SEO site not found")
        return site

    def create_site(self, *, business_id: str, payload: SEOSiteCreateRequest) -> SEOSite:
        self._require_business(business_id)
        normalized = self._normalize_base_url(payload.base_url)
        self._ensure_unique_domain(
            business_id=business_id,
            normalized_domain=normalized.domain,
        )

        existing_sites = self.seo_site_repository.list_for_business(business_id)
        is_primary = payload.is_primary or len(existing_sites) == 0
        if is_primary:
            self.seo_site_repository.clear_primary_for_business(business_id)

        primary_location = self._clean_optional(payload.primary_location)
        if primary_location is None and payload.primary_business_zip is not None:
            primary_location = build_primary_location_from_zip(payload.primary_business_zip)
        search_console_property_url = self._normalize_search_console_property_url(payload.search_console_property_url)
        search_console_enabled = (
            payload.search_console_enabled
            if payload.search_console_enabled is not None
            else bool(search_console_property_url)
        )
        if search_console_enabled and not search_console_property_url:
            raise SEOSiteValidationError(
                "search_console_property_url is required when search_console_enabled is true"
            )
        ga4_account_id = self._normalize_ga4_identifier(payload.ga4_account_id)
        ga4_property_id = self._normalize_ga4_identifier(payload.ga4_property_id)
        ga4_data_stream_id = self._normalize_ga4_identifier(payload.ga4_data_stream_id)
        ga4_measurement_id = self._normalize_ga4_measurement_id(payload.ga4_measurement_id)
        ga4_onboarding_status = self._derive_ga4_onboarding_status(
            ga4_account_id=ga4_account_id,
            ga4_property_id=ga4_property_id,
            ga4_data_stream_id=ga4_data_stream_id,
            ga4_measurement_id=ga4_measurement_id,
        )

        site = SEOSite(
            id=str(uuid4()),
            business_id=business_id,
            display_name=payload.display_name.strip(),
            base_url=normalized.url,
            normalized_domain=normalized.domain,
            industry=self._clean_optional(payload.industry),
            primary_location=primary_location,
            service_areas_json=payload.service_areas,
            search_console_property_url=search_console_property_url,
            search_console_enabled=search_console_enabled,
            ga4_onboarding_status=ga4_onboarding_status,
            ga4_account_id=ga4_account_id,
            ga4_property_id=ga4_property_id,
            ga4_data_stream_id=ga4_data_stream_id,
            ga4_measurement_id=ga4_measurement_id,
            is_active=payload.is_active,
            is_primary=is_primary,
        )
        self.seo_site_repository.create(site)
        self._commit_with_constraint_handling()
        self.session.refresh(site)
        return site

    def update_site(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOSiteUpdateRequest,
    ) -> SEOSite:
        self._require_business(business_id)
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOSiteNotFoundError("SEO site not found")

        changes = payload.model_dump(exclude_unset=True)
        original_normalized_domain = (site.normalized_domain or "").strip().lower()
        domain_changed = False
        if "display_name" in changes:
            site.display_name = changes["display_name"].strip()
        if "base_url" in changes:
            normalized = self._normalize_base_url(changes["base_url"])
            self._ensure_unique_domain(
                business_id=business_id,
                normalized_domain=normalized.domain,
                excluding_site_id=site.id,
            )
            site.base_url = normalized.url
            site.normalized_domain = normalized.domain
            domain_changed = normalized.domain != original_normalized_domain
        # When a site is repointed to a different domain/vendor, stale explicit
        # industry assignments from the previous site identity can contaminate
        # downstream context derivation. Clear only on real domain change unless
        # a new industry was explicitly supplied in the same update.
        if domain_changed and "industry" not in changes:
            site.industry = None
        if "industry" in changes:
            site.industry = self._clean_optional(changes["industry"])
        if "primary_location" in changes:
            site.primary_location = self._clean_optional(changes["primary_location"])
        if "primary_business_zip" in changes and "primary_location" not in changes:
            normalized_zip = normalize_primary_business_zip(changes["primary_business_zip"])
            site.primary_location = (
                build_primary_location_from_zip(normalized_zip) if normalized_zip is not None else None
            )
        if "service_areas" in changes:
            site.service_areas_json = changes["service_areas"]
        property_updated = False
        if "search_console_property_url" in changes:
            site.search_console_property_url = self._normalize_search_console_property_url(
                changes["search_console_property_url"]
            )
            property_updated = True
        if "search_console_enabled" in changes:
            site.search_console_enabled = bool(changes["search_console_enabled"])
        elif property_updated:
            site.search_console_enabled = bool(site.search_console_property_url)
        if site.search_console_enabled and not site.search_console_property_url:
            raise SEOSiteValidationError(
                "search_console_property_url is required when search_console_enabled is true"
            )
        ga4_fields_updated = False
        if "ga4_account_id" in changes:
            site.ga4_account_id = self._normalize_ga4_identifier(changes["ga4_account_id"])
            ga4_fields_updated = True
        if "ga4_property_id" in changes:
            site.ga4_property_id = self._normalize_ga4_identifier(changes["ga4_property_id"])
            ga4_fields_updated = True
        if "ga4_data_stream_id" in changes:
            site.ga4_data_stream_id = self._normalize_ga4_identifier(changes["ga4_data_stream_id"])
            ga4_fields_updated = True
        if "ga4_measurement_id" in changes:
            site.ga4_measurement_id = self._normalize_ga4_measurement_id(changes["ga4_measurement_id"])
            ga4_fields_updated = True
        if ga4_fields_updated:
            site.ga4_onboarding_status = self._derive_ga4_onboarding_status(
                ga4_account_id=site.ga4_account_id,
                ga4_property_id=site.ga4_property_id,
                ga4_data_stream_id=site.ga4_data_stream_id,
                ga4_measurement_id=site.ga4_measurement_id,
            )
        if "is_active" in changes:
            site.is_active = changes["is_active"]
        if "is_primary" in changes:
            if changes["is_primary"]:
                self.seo_site_repository.clear_primary_for_business(business_id)
                site.is_primary = True
            else:
                site.is_primary = False

        self.seo_site_repository.save(site)
        self._commit_with_constraint_handling()
        self.session.refresh(site)
        return site

    def delete_site_permanently(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> None:
        self._require_business(business_id)
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOSiteNotFoundError("SEO site not found")

        try:
            for model in _SITE_PERMANENT_DELETE_MODELS:
                self.session.execute(
                    delete(model).where(model.business_id == business_id).where(model.site_id == site_id)
                )
            deleted_site = self.session.execute(
                delete(SEOSite).where(SEOSite.business_id == business_id).where(SEOSite.id == site_id)
            )
            if int(deleted_site.rowcount or 0) != 1:
                self.session.rollback()
                raise SEOSiteValidationError("Permanent site deletion did not remove exactly one site record")
            self._commit_with_constraint_handling()
        except SEOSiteValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            raise SEOSiteValidationError("Failed to permanently delete SEO site") from exc

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOSiteNotFoundError("Business not found")

    def _normalize_base_url(self, raw_base_url: str) -> NormalizedURL:
        cleaned = raw_base_url.strip()
        parsed = urlparse(cleaned)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise SEOSiteValidationError("base_url must use http or https")
        if not parsed.netloc:
            raise SEOSiteValidationError("base_url must include a valid domain")

        domain = parsed.netloc.lower()
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
            if not path:
                path = "/"

        normalized = urlunparse((scheme, domain, path, "", "", ""))
        return NormalizedURL(url=normalized, domain=domain)

    def _normalize_search_console_property_url(self, raw_property_url: str | None) -> str | None:
        cleaned = self._clean_optional(raw_property_url)
        if cleaned is None:
            return None
        lowered = cleaned.lower()
        if lowered.startswith("sc-domain:"):
            domain = lowered.removeprefix("sc-domain:").strip()
            if not domain:
                raise SEOSiteValidationError("search_console_property_url must include a domain after sc-domain:")
            if "/" in domain:
                domain = domain.split("/", 1)[0].strip()
            if not domain:
                raise SEOSiteValidationError("search_console_property_url must include a valid domain")
            return f"sc-domain:{domain}"

        parsed = urlparse(cleaned)
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise SEOSiteValidationError(
                "search_console_property_url must be an sc-domain property or http/https URL-prefix property"
            )
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise SEOSiteValidationError("search_console_property_url must include a valid host")
        netloc = hostname
        if parsed.port is not None:
            netloc = f"{hostname}:{parsed.port}"
        path = (parsed.path or "/").strip()
        if not path:
            path = "/"
        if not path.startswith("/"):
            path = f"/{path}"
        if not path.endswith("/"):
            path = f"{path}/"
        return urlunparse((scheme, netloc, path, "", "", ""))

    def _normalize_ga4_identifier(self, raw_identifier: str | None) -> str | None:
        return self._clean_optional(raw_identifier)

    def _normalize_ga4_measurement_id(self, raw_measurement_id: str | None) -> str | None:
        normalized = self._clean_optional(raw_measurement_id)
        if normalized is None:
            return None
        return normalized.upper()

    def _derive_ga4_onboarding_status(
        self,
        *,
        ga4_account_id: str | None,
        ga4_property_id: str | None,
        ga4_data_stream_id: str | None,
        ga4_measurement_id: str | None,
    ) -> str:
        has_account = bool(ga4_account_id)
        has_property = bool(ga4_property_id)
        has_stream = bool(ga4_data_stream_id)
        has_measurement = bool(ga4_measurement_id)
        if not has_account and not has_property and not has_stream and not has_measurement:
            return "not_connected"
        if has_account and not has_property and not has_stream and not has_measurement:
            return "account_available"
        if has_property and has_stream and has_measurement:
            return "stream_configured"
        if has_property and not has_stream and not has_measurement:
            return "property_configured"
        return "incomplete"

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _ensure_unique_domain(
        self,
        *,
        business_id: str,
        normalized_domain: str,
        excluding_site_id: str | None = None,
    ) -> None:
        existing = self.seo_site_repository.get_for_business_domain(
            business_id=business_id,
            normalized_domain=normalized_domain,
        )
        if existing is None:
            return
        if excluding_site_id and existing.id == excluding_site_id:
            return
        raise SEOSiteValidationError("A site for this domain already exists for the business")

    def _commit_with_constraint_handling(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            error_text = str(exc).lower()
            if "uq_seo_sites_business_normalized_domain" in error_text:
                raise SEOSiteValidationError("A site for this domain already exists for the business") from exc
            if "uq_seo_sites_one_primary_per_business" in error_text:
                raise SEOSiteValidationError("Only one primary SEO site is allowed per business") from exc
            raise SEOSiteValidationError("SEO site update violated a database constraint") from exc

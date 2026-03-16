from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_site import SEOSiteCreateRequest, SEOSiteUpdateRequest


class SEOSiteNotFoundError(ValueError):
    pass


class SEOSiteValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedURL:
    url: str
    domain: str


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

        site = SEOSite(
            id=str(uuid4()),
            business_id=business_id,
            display_name=payload.display_name.strip(),
            base_url=normalized.url,
            normalized_domain=normalized.domain,
            industry=self._clean_optional(payload.industry),
            primary_location=self._clean_optional(payload.primary_location),
            service_areas_json=payload.service_areas,
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
        if "industry" in changes:
            site.industry = self._clean_optional(changes["industry"])
        if "primary_location" in changes:
            site.primary_location = self._clean_optional(changes["primary_location"])
        if "service_areas" in changes:
            site.service_areas_json = changes["service_areas"]
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

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_competitor import (
    SEOCompetitorDomainCreateRequest,
    SEOCompetitorSetCreateRequest,
    SEOCompetitorSetUpdateRequest,
    SEOCompetitorSnapshotRunCreateRequest,
)


class SEOCompetitorNotFoundError(ValueError):
    pass


class SEOCompetitorValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedCompetitorTarget:
    domain: str
    base_url: str


class SEOCompetitorService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_competitor_repository: SEOCompetitorRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_competitor_repository = seo_competitor_repository

    def list_sets(self, *, business_id: str, site_id: str) -> list[SEOCompetitorSet]:
        self._require_business(business_id)
        self._require_site(business_id, site_id)
        return self.seo_competitor_repository.list_sets_for_business_site(business_id, site_id)

    def create_set(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOCompetitorSetCreateRequest,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorSet:
        self._require_business(business_id)
        self._require_site(business_id, site_id)
        name = payload.name.strip()
        if not name:
            raise SEOCompetitorValidationError("name is required")

        competitor_set = SEOCompetitorSet(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            name=name,
            city=self._clean_optional(payload.city),
            state=self._clean_optional(payload.state),
            is_active=payload.is_active,
            created_by_principal_id=created_by_principal_id,
        )
        try:
            self.seo_competitor_repository.create_set(competitor_set)
            self._commit_with_constraint_handling()
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)
        self.session.refresh(competitor_set)
        return competitor_set

    def get_set(self, *, business_id: str, competitor_set_id: str) -> SEOCompetitorSet:
        self._require_business(business_id)
        competitor_set = self.seo_competitor_repository.get_set_for_business(business_id, competitor_set_id)
        if competitor_set is None:
            raise SEOCompetitorNotFoundError("Competitor set not found")
        return competitor_set

    def update_set(
        self,
        *,
        business_id: str,
        competitor_set_id: str,
        payload: SEOCompetitorSetUpdateRequest,
    ) -> SEOCompetitorSet:
        self._require_business(business_id)
        competitor_set = self.get_set(business_id=business_id, competitor_set_id=competitor_set_id)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes:
            name = changes["name"].strip()
            if not name:
                raise SEOCompetitorValidationError("name must not be empty")
            competitor_set.name = name
        if "city" in changes:
            competitor_set.city = self._clean_optional(changes["city"])
        if "state" in changes:
            competitor_set.state = self._clean_optional(changes["state"])
        if "is_active" in changes:
            competitor_set.is_active = changes["is_active"]

        try:
            self.seo_competitor_repository.save_set(competitor_set)
            self._commit_with_constraint_handling()
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)
        self.session.refresh(competitor_set)
        return competitor_set

    def list_domains(self, *, business_id: str, competitor_set_id: str) -> list[SEOCompetitorDomain]:
        self._require_business(business_id)
        self.get_set(business_id=business_id, competitor_set_id=competitor_set_id)
        return self.seo_competitor_repository.list_domains_for_business_set(business_id, competitor_set_id)

    def add_domain(
        self,
        *,
        business_id: str,
        competitor_set_id: str,
        payload: SEOCompetitorDomainCreateRequest,
    ) -> SEOCompetitorDomain:
        self._require_business(business_id)
        competitor_set = self.get_set(business_id=business_id, competitor_set_id=competitor_set_id)
        normalized_target = self._normalize_domain_target(domain=payload.domain, base_url=payload.base_url)
        competitor_domain = SEOCompetitorDomain(
            id=str(uuid4()),
            business_id=business_id,
            site_id=competitor_set.site_id,
            competitor_set_id=competitor_set.id,
            domain=normalized_target.domain,
            base_url=normalized_target.base_url,
            display_name=self._clean_optional(payload.display_name),
            source="manual",
            is_active=payload.is_active,
            notes=self._clean_optional(payload.notes),
        )
        try:
            self.seo_competitor_repository.create_domain(competitor_domain)
            self._commit_with_constraint_handling()
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)
        self.session.refresh(competitor_domain)
        return competitor_domain

    def remove_domain(self, *, business_id: str, competitor_set_id: str, domain_id: str) -> None:
        self._require_business(business_id)
        self.get_set(business_id=business_id, competitor_set_id=competitor_set_id)
        competitor_domain = self.seo_competitor_repository.get_domain_for_business(
            business_id,
            competitor_set_id,
            domain_id,
        )
        if competitor_domain is None:
            raise SEOCompetitorNotFoundError("Competitor domain not found")
        self.seo_competitor_repository.delete_domain(competitor_domain)
        self.session.commit()

    def create_snapshot_run(
        self,
        *,
        business_id: str,
        competitor_set_id: str,
        payload: SEOCompetitorSnapshotRunCreateRequest,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorSnapshotRun:
        self._require_business(business_id)
        competitor_set = self.get_set(business_id=business_id, competitor_set_id=competitor_set_id)
        active_domain_count = self.seo_competitor_repository.count_active_domains_for_set(
            business_id,
            competitor_set_id,
        )
        if active_domain_count == 0:
            raise SEOCompetitorValidationError("Cannot create snapshot run without active competitor domains")

        snapshot_run = SEOCompetitorSnapshotRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=competitor_set.site_id,
            competitor_set_id=competitor_set.id,
            client_audit_run_id=payload.client_audit_run_id,
            status="queued",
            max_domains=payload.max_domains,
            max_pages_per_domain=payload.max_pages_per_domain,
            max_depth=payload.max_depth,
            same_domain_only=payload.same_domain_only,
            domains_targeted=min(active_domain_count, payload.max_domains),
            domains_completed=0,
            pages_attempted=0,
            pages_captured=0,
            pages_skipped=0,
            errors_encountered=0,
            created_by_principal_id=created_by_principal_id,
        )
        try:
            self.seo_competitor_repository.create_snapshot_run(snapshot_run)
            self._commit_with_constraint_handling()
        except ValueError as exc:
            raise SEOCompetitorValidationError(str(exc)) from exc
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)
        self.session.refresh(snapshot_run)
        return snapshot_run

    def list_snapshot_runs(
        self,
        *,
        business_id: str,
        competitor_set_id: str,
    ) -> list[SEOCompetitorSnapshotRun]:
        self._require_business(business_id)
        self.get_set(business_id=business_id, competitor_set_id=competitor_set_id)
        return self.seo_competitor_repository.list_snapshot_runs_for_business_set(business_id, competitor_set_id)

    def get_snapshot_run(self, *, business_id: str, snapshot_run_id: str) -> SEOCompetitorSnapshotRun:
        self._require_business(business_id)
        snapshot_run = self.seo_competitor_repository.get_snapshot_run_for_business(business_id, snapshot_run_id)
        if snapshot_run is None:
            raise SEOCompetitorNotFoundError("Competitor snapshot run not found")
        return snapshot_run

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorNotFoundError("Business not found")

    def _require_site(self, business_id: str, site_id: str) -> None:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOCompetitorNotFoundError("SEO site not found")

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _normalize_domain_target(self, *, domain: str | None, base_url: str | None) -> NormalizedCompetitorTarget:
        if domain is None and base_url is None:
            raise SEOCompetitorValidationError("Either domain or base_url is required")

        normalized_base_url: str | None = None
        host_from_base_url: str | None = None

        if base_url is not None:
            cleaned_url = base_url.strip()
            parsed = urlsplit(cleaned_url)
            scheme = parsed.scheme.lower()
            if scheme not in {"http", "https"}:
                raise SEOCompetitorValidationError("base_url must use http or https")
            host = (parsed.hostname or "").lower()
            if not host:
                raise SEOCompetitorValidationError("base_url must include a valid domain")
            path = parsed.path or "/"
            if path != "/":
                path = path.rstrip("/")
                if not path:
                    path = "/"
            netloc = host
            if parsed.port and not (
                (scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443)
            ):
                netloc = f"{host}:{parsed.port}"
            normalized_base_url = urlunsplit((scheme, netloc, path, "", ""))
            host_from_base_url = host

        normalized_domain = self._normalize_domain_value(domain or host_from_base_url or "")
        if host_from_base_url is not None and host_from_base_url != normalized_domain:
            raise SEOCompetitorValidationError("domain must match base_url host")

        if normalized_base_url is None:
            normalized_base_url = f"https://{normalized_domain}/"

        return NormalizedCompetitorTarget(domain=normalized_domain, base_url=normalized_base_url)

    def _normalize_domain_value(self, raw_domain: str) -> str:
        candidate = raw_domain.strip().lower()
        if not candidate:
            raise SEOCompetitorValidationError("domain is required")
        if "://" in candidate:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").lower()
        else:
            parsed = urlsplit(f"https://{candidate}")
            host = (parsed.hostname or "").lower()
        if not host:
            raise SEOCompetitorValidationError("domain must be valid")
        cleaned = host.strip(".")
        if not cleaned or "." not in cleaned:
            raise SEOCompetitorValidationError("domain must include a top-level domain")
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-." for ch in cleaned):
            raise SEOCompetitorValidationError("domain contains invalid characters")
        return cleaned

    def _commit_with_constraint_handling(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)

    def _raise_constraint_validation_error(self, exc: IntegrityError) -> None:
        self.session.rollback()
        error_text = str(exc).lower()
        if "uq_seo_competitor_sets_business_site_name" in error_text:
            raise SEOCompetitorValidationError("A competitor set with this name already exists for the site") from exc
        if "uq_seo_competitor_domains_business_set_domain" in error_text:
            raise SEOCompetitorValidationError("A competitor domain with this host already exists in the set") from exc
        raise SEOCompetitorValidationError("Competitor data violated a database constraint") from exc

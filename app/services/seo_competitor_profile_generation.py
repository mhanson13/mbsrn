from __future__ import annotations

from dataclasses import dataclass
import logging
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationProvider,
)
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.seo_competitor import (
    SEOCompetitorProfileDraftAcceptRequest,
    SEOCompetitorProfileDraftEditRequest,
    SEOCompetitorProfileDraftRejectRequest,
    SEOCompetitorProfileGenerationRunCreateRequest,
)


logger = logging.getLogger(__name__)

_ALLOWED_COMPETITOR_TYPES = {"direct", "indirect", "local", "marketplace", "informational", "unknown"}


class SEOCompetitorProfileGenerationNotFoundError(ValueError):
    pass


class SEOCompetitorProfileGenerationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEOCompetitorProfileGenerationRunDetail:
    run: SEOCompetitorProfileGenerationRun
    drafts: list[SEOCompetitorProfileDraft]


@dataclass(frozen=True)
class SEOCompetitorProfileDraftAcceptanceResult:
    draft: SEOCompetitorProfileDraft
    competitor_domain: SEOCompetitorDomain


class SEOCompetitorProfileGenerationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_competitor_repository: SEOCompetitorRepository,
        seo_competitor_profile_generation_repository: SEOCompetitorProfileGenerationRepository,
        provider: SEOCompetitorProfileGenerationProvider,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_competitor_repository = seo_competitor_repository
        self.seo_competitor_profile_generation_repository = seo_competitor_profile_generation_repository
        self.provider = provider

    def create_run(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEOCompetitorProfileGenerationRunCreateRequest,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorProfileGenerationRunDetail:
        self._require_business(business_id)
        site = self._require_site(business_id=business_id, site_id=site_id)

        run = SEOCompetitorProfileGenerationRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            status="running",
            requested_candidate_count=payload.candidate_count,
            generated_draft_count=0,
            provider_name="pending",
            model_name="pending",
            prompt_version="seo-competitor-profile-v1",
            error_summary=None,
            completed_at=None,
            created_by_principal_id=created_by_principal_id,
        )
        self.seo_competitor_profile_generation_repository.create_run(run)
        self.session.commit()
        self.session.refresh(run)

        try:
            existing_domains = [
                item.domain
                for item in self.seo_competitor_repository.list_domains_for_business_site(
                    business_id,
                    site_id,
                )
            ]
            output = self.provider.generate_competitor_profiles(
                site=site,
                existing_domains=existing_domains,
                candidate_count=payload.candidate_count,
            )

            drafts = self._build_drafts(
                run=run,
                raw_candidates=output.candidates,
            )
            if not drafts:
                raise SEOCompetitorProfileGenerationValidationError(
                    "No valid competitor profile drafts were generated"
                )

            run.status = "completed"
            run.generated_draft_count = len(drafts)
            run.provider_name = self._clean_required_value(output.provider_name, field_name="provider_name")
            run.model_name = self._clean_required_value(output.model_name, field_name="model_name")
            run.prompt_version = self._clean_required_value(output.prompt_version, field_name="prompt_version")
            run.error_summary = None
            run.completed_at = utc_now()
            self.seo_competitor_profile_generation_repository.save_run(run)
            for draft in drafts:
                self.seo_competitor_profile_generation_repository.create_draft(draft)
            self.session.commit()
            self.session.refresh(run)
            return SEOCompetitorProfileGenerationRunDetail(run=run, drafts=drafts)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SEO competitor profile generation failed business_id=%s site_id=%s run_id=%s reason=%s",
                business_id,
                site_id,
                run.id,
                str(exc),
            )
            self.session.rollback()
            run = self.seo_competitor_profile_generation_repository.get_run_for_business(business_id, run.id) or run
            run.status = "failed"
            run.generated_draft_count = 0
            run.error_summary = "Competitor profile generation failed"
            run.completed_at = utc_now()
            self.seo_competitor_profile_generation_repository.save_run(run)
            self.session.commit()
            raise SEOCompetitorProfileGenerationValidationError("Competitor profile generation failed") from exc

    def list_runs(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> list[SEOCompetitorProfileGenerationRun]:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        return self.seo_competitor_profile_generation_repository.list_runs_for_business_site(
            business_id,
            site_id,
        )

    def get_run_detail(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
    ) -> SEOCompetitorProfileGenerationRunDetail:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        run = self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        drafts = self.seo_competitor_profile_generation_repository.list_drafts_for_business_run(
            business_id,
            generation_run_id,
        )
        return SEOCompetitorProfileGenerationRunDetail(run=run, drafts=drafts)

    def edit_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
        payload: SEOCompetitorProfileDraftEditRequest,
        reviewed_by_principal_id: str | None,
    ) -> SEOCompetitorProfileDraft:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        draft = self._get_draft_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
        )
        if draft.review_status == "accepted":
            raise SEOCompetitorProfileGenerationValidationError("Accepted drafts cannot be edited")
        if draft.review_status == "rejected":
            raise SEOCompetitorProfileGenerationValidationError("Rejected drafts cannot be edited")

        updates = payload.model_dump(exclude_unset=True)
        changed_fields = self._apply_draft_updates(
            draft=draft,
            updates=updates,
        )
        if draft.review_status == "pending":
            draft.review_status = "edited"
        draft.edited_fields_json = changed_fields or draft.edited_fields_json
        draft.reviewed_by_principal_id = reviewed_by_principal_id
        draft.reviewed_at = utc_now()
        self.seo_competitor_profile_generation_repository.save_draft(draft)
        self._commit_with_constraint_handling()
        self.session.refresh(draft)
        return draft

    def reject_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
        payload: SEOCompetitorProfileDraftRejectRequest,
        reviewed_by_principal_id: str | None,
    ) -> SEOCompetitorProfileDraft:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        draft = self._get_draft_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
        )
        if draft.review_status == "accepted":
            raise SEOCompetitorProfileGenerationValidationError("Accepted drafts cannot be rejected")
        draft.review_status = "rejected"
        draft.review_notes = self._clean_optional(payload.reason)
        draft.reviewed_by_principal_id = reviewed_by_principal_id
        draft.reviewed_at = utc_now()
        self.seo_competitor_profile_generation_repository.save_draft(draft)
        self._commit_with_constraint_handling()
        self.session.refresh(draft)
        return draft

    def accept_draft(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
        payload: SEOCompetitorProfileDraftAcceptRequest,
        reviewed_by_principal_id: str | None,
    ) -> SEOCompetitorProfileDraftAcceptanceResult:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        self._get_run_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
        )
        draft = self._get_draft_for_site(
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run_id,
            draft_id=draft_id,
        )
        if draft.review_status == "accepted":
            raise SEOCompetitorProfileGenerationValidationError("Draft has already been accepted")
        if draft.review_status == "rejected":
            raise SEOCompetitorProfileGenerationValidationError("Rejected drafts cannot be accepted")

        updates = payload.model_dump(exclude_unset=True, exclude={"competitor_set_id", "review_notes"})
        changed_fields = self._apply_draft_updates(draft=draft, updates=updates)

        normalized_domain = self._normalize_domain_value(draft.suggested_domain)
        existing_domain = self.seo_competitor_repository.get_domain_for_business_site_domain(
            business_id,
            site_id,
            normalized_domain,
        )
        if existing_domain is not None:
            raise SEOCompetitorProfileGenerationValidationError(
                "A competitor domain with this host already exists for the site"
            )

        target_set = self._resolve_target_set(
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=payload.competitor_set_id,
            created_by_principal_id=reviewed_by_principal_id,
        )
        competitor_domain = SEOCompetitorDomain(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=target_set.id,
            domain=normalized_domain,
            base_url=f"https://{normalized_domain}/",
            display_name=draft.suggested_name,
            source="ai_generated",
            is_active=True,
            notes=self._build_domain_notes_from_draft(draft),
        )
        self.seo_competitor_repository.create_domain(competitor_domain)

        draft.review_status = "accepted"
        draft.review_notes = self._clean_optional(payload.review_notes)
        draft.reviewed_by_principal_id = reviewed_by_principal_id
        draft.reviewed_at = utc_now()
        draft.accepted_competitor_set_id = target_set.id
        draft.accepted_competitor_domain_id = competitor_domain.id
        draft.edited_fields_json = changed_fields or draft.edited_fields_json
        self.seo_competitor_profile_generation_repository.save_draft(draft)
        self._commit_with_constraint_handling()
        self.session.refresh(draft)
        self.session.refresh(competitor_domain)
        return SEOCompetitorProfileDraftAcceptanceResult(
            draft=draft,
            competitor_domain=competitor_domain,
        )

    def _build_drafts(
        self,
        *,
        run: SEOCompetitorProfileGenerationRun,
        raw_candidates: list[SEOCompetitorProfileDraftCandidateOutput],
    ) -> list[SEOCompetitorProfileDraft]:
        drafts: list[SEOCompetitorProfileDraft] = []
        seen_domains: set[str] = set()
        for candidate in raw_candidates:
            suggested_name = self._clean_required_value(candidate.suggested_name, field_name="suggested_name")
            suggested_domain = self._normalize_domain_value(candidate.suggested_domain)
            if suggested_domain in seen_domains:
                continue
            seen_domains.add(suggested_domain)
            competitor_type = self._normalize_competitor_type(candidate.competitor_type)
            confidence_score = self._normalize_confidence_score(candidate.confidence_score)
            draft = SEOCompetitorProfileDraft(
                id=str(uuid4()),
                business_id=run.business_id,
                site_id=run.site_id,
                generation_run_id=run.id,
                suggested_name=suggested_name,
                suggested_domain=suggested_domain,
                competitor_type=competitor_type,
                summary=self._clean_optional(candidate.summary),
                why_competitor=self._clean_optional(candidate.why_competitor),
                evidence=self._clean_optional(candidate.evidence),
                confidence_score=confidence_score,
                source="ai_generated",
                review_status="pending",
            )
            drafts.append(draft)
        return drafts

    def _apply_draft_updates(
        self,
        *,
        draft: SEOCompetitorProfileDraft,
        updates: dict[str, object],
    ) -> dict[str, object]:
        changed_fields: dict[str, object] = {}
        if "suggested_name" in updates:
            suggested_name = self._clean_required_value(str(updates["suggested_name"]), field_name="suggested_name")
            if suggested_name != draft.suggested_name:
                draft.suggested_name = suggested_name
                changed_fields["suggested_name"] = suggested_name
        if "suggested_domain" in updates:
            suggested_domain = self._normalize_domain_value(str(updates["suggested_domain"]))
            if suggested_domain != draft.suggested_domain:
                draft.suggested_domain = suggested_domain
                changed_fields["suggested_domain"] = suggested_domain
        if "competitor_type" in updates:
            competitor_type = self._normalize_competitor_type(str(updates["competitor_type"]))
            if competitor_type != draft.competitor_type:
                draft.competitor_type = competitor_type
                changed_fields["competitor_type"] = competitor_type
        if "summary" in updates:
            summary = self._clean_optional(str(updates["summary"]) if updates["summary"] is not None else None)
            if summary != draft.summary:
                draft.summary = summary
                changed_fields["summary"] = summary
        if "why_competitor" in updates:
            why_competitor = self._clean_optional(
                str(updates["why_competitor"]) if updates["why_competitor"] is not None else None
            )
            if why_competitor != draft.why_competitor:
                draft.why_competitor = why_competitor
                changed_fields["why_competitor"] = why_competitor
        if "evidence" in updates:
            evidence = self._clean_optional(str(updates["evidence"]) if updates["evidence"] is not None else None)
            if evidence != draft.evidence:
                draft.evidence = evidence
                changed_fields["evidence"] = evidence
        if "confidence_score" in updates:
            confidence_score = self._normalize_confidence_score(float(updates["confidence_score"]))
            if confidence_score != draft.confidence_score:
                draft.confidence_score = confidence_score
                changed_fields["confidence_score"] = confidence_score
        return changed_fields

    def _resolve_target_set(
        self,
        *,
        business_id: str,
        site_id: str,
        competitor_set_id: str | None,
        created_by_principal_id: str | None,
    ) -> SEOCompetitorSet:
        if competitor_set_id:
            competitor_set = self.seo_competitor_repository.get_set_for_business(
                business_id,
                competitor_set_id,
            )
            if competitor_set is None or competitor_set.site_id != site_id:
                raise SEOCompetitorProfileGenerationNotFoundError("Competitor set not found")
            return competitor_set

        sets = self.seo_competitor_repository.list_sets_for_business_site(business_id, site_id)
        if sets:
            active_set = next((item for item in sets if item.is_active), None)
            return active_set or sets[0]

        generated_set = SEOCompetitorSet(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            name=f"AI Generated Competitors ({utc_now().date().isoformat()})",
            city=None,
            state=None,
            is_active=True,
            created_by_principal_id=created_by_principal_id,
        )
        self.seo_competitor_repository.create_set(generated_set)
        return generated_set

    def _build_domain_notes_from_draft(self, draft: SEOCompetitorProfileDraft) -> str | None:
        parts = [
            "Added from AI-generated competitor profile draft.",
            f"Type: {draft.competitor_type}",
            f"Confidence: {draft.confidence_score:.2f}",
        ]
        if draft.summary:
            parts.append(f"Summary: {draft.summary}")
        if draft.why_competitor:
            parts.append(f"Rationale: {draft.why_competitor}")
        if draft.evidence:
            parts.append(f"Evidence: {draft.evidence}")
        combined = " ".join(parts).strip()
        if len(combined) > 2000:
            return combined[:1997] + "..."
        return combined or None

    def _get_run_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
    ) -> SEOCompetitorProfileGenerationRun:
        run = self.seo_competitor_profile_generation_repository.get_run_for_business(
            business_id,
            generation_run_id,
        )
        if run is None or run.site_id != site_id:
            raise SEOCompetitorProfileGenerationNotFoundError("Competitor profile generation run not found")
        return run

    def _get_draft_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        generation_run_id: str,
        draft_id: str,
    ) -> SEOCompetitorProfileDraft:
        draft = self.seo_competitor_profile_generation_repository.get_draft_for_business_run(
            business_id,
            generation_run_id,
            draft_id,
        )
        if draft is None or draft.site_id != site_id:
            raise SEOCompetitorProfileGenerationNotFoundError("Competitor profile draft not found")
        return draft

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOCompetitorProfileGenerationNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str):
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOCompetitorProfileGenerationNotFoundError("SEO site not found")
        return site

    def _normalize_domain_value(self, raw_domain: str) -> str:
        candidate = raw_domain.strip().lower()
        if not candidate:
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain is required")
        if "://" in candidate:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").lower()
        else:
            parsed = urlsplit(f"https://{candidate}")
            host = (parsed.hostname or "").lower()
        if not host:
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain must be valid")
        cleaned = host.strip(".")
        if not cleaned or "." not in cleaned:
            raise SEOCompetitorProfileGenerationValidationError(
                "suggested_domain must include a top-level domain"
            )
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-." for ch in cleaned):
            raise SEOCompetitorProfileGenerationValidationError("suggested_domain contains invalid characters")
        return cleaned

    def _normalize_competitor_type(self, raw: str) -> str:
        normalized = (raw or "").strip().lower()
        if not normalized:
            return "unknown"
        if normalized not in _ALLOWED_COMPETITOR_TYPES:
            return "unknown"
        return normalized

    def _normalize_confidence_score(self, raw: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise SEOCompetitorProfileGenerationValidationError("confidence_score must be a number") from exc
        if value < 0 or value > 1:
            raise SEOCompetitorProfileGenerationValidationError("confidence_score must be between 0 and 1")
        return value

    def _clean_required_value(self, raw: str, *, field_name: str) -> str:
        cleaned = (raw or "").strip()
        if not cleaned:
            raise SEOCompetitorProfileGenerationValidationError(f"{field_name} is required")
        return cleaned

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _commit_with_constraint_handling(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self._raise_constraint_validation_error(exc)

    def _raise_constraint_validation_error(self, exc: IntegrityError) -> None:
        self.session.rollback()
        error_text = str(exc).lower()
        if "uq_seo_competitor_domains_business_set_domain" in error_text:
            raise SEOCompetitorProfileGenerationValidationError(
                "A competitor domain with this host already exists in the set"
            ) from exc
        if "uq_seo_competitor_profile_drafts_business_run_domain" in error_text:
            raise SEOCompetitorProfileGenerationValidationError(
                "Duplicate suggested domain generated for this run"
            ) from exc
        if "uq_seo_competitor_sets_business_site_name" in error_text:
            raise SEOCompetitorProfileGenerationValidationError(
                "Generated competitor set name conflicts with an existing set"
            ) from exc
        raise SEOCompetitorProfileGenerationValidationError(
            "Competitor profile generation data violated a database constraint"
        ) from exc

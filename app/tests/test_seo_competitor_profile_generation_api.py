from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_competitor_profile_generation_provider,
    get_seo_competitor_profile_generation_run_executor,
    get_tenant_context,
)
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.core.time import utc_now
from app.integrations.seo_competitor_profile_generation_provider import SEOCompetitorProfileProviderError
from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
    SEOCompetitorProfileGenerationProvider,
)
from app.models.business import Business
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.seo_competitor_profile_generation import (
    INVALID_OUTPUT_ERROR_SUMMARY,
    PROVIDER_AUTH_CONFIG_ERROR_SUMMARY,
    PROVIDER_TIMEOUT_ERROR_SUMMARY,
    STALE_QUEUED_RUN_ERROR_SUMMARY,
    STALE_QUEUED_RUN_TIMEOUT,
    STALE_RUNNING_RUN_ERROR_SUMMARY,
    STALE_RUNNING_RUN_TIMEOUT,
    SEOCompetitorProfileGenerationService,
)
from app.services.seo_competitor_profile_candidate_quality import (
    CompetitorCandidateDomainProbe,
    CompetitorCandidateDomainProbeResult,
)


class _DeterministicCompetitorProfileProvider:
    provider_name = "deterministic-test-provider"
    model_name = "deterministic-test-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Draft Competitor One",
                suggested_domain="draft-competitor-one.example",
                competitor_type="direct",
                summary="Direct overlap in service intent.",
                why_competitor="Competes for transactional query demand.",
                evidence="Domain + intent overlap heuristic.",
                confidence_score=0.88,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Draft Competitor Two",
                suggested_domain="draft-competitor-two.example",
                competitor_type="local",
                summary="Likely local competitor for geo-intent queries.",
                why_competitor="Localized service market overlap.",
                evidence="Local SERP-style coverage pattern.",
                confidence_score=0.72,
            ),
        ]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates[:candidate_count],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response=(
                '{\"candidates\":[{\"name\":\"Draft Competitor One\"},{\"name\":\"Draft Competitor Two\"}]}'
            ),
        )


class _InvalidCompetitorProfileProvider:
    provider_name = "invalid-test-provider"
    model_name = "invalid-test-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Broken Candidate",
                    suggested_domain="invalid-domain-without-tld",
                    competitor_type="direct",
                    summary="broken",
                    why_competitor="broken",
                    evidence="broken",
                    confidence_score=0.5,
                )
            ],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{\"candidates\":[{\"domain\":\"invalid-domain-without-tld\"}]}',
        )


class _PartiallyInvalidCompetitorProfileProvider:
    provider_name = "partial-invalid-provider"
    model_name = "partial-invalid-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Valid Candidate",
                    suggested_domain="valid-competitor.example",
                    competitor_type="direct",
                    summary="valid",
                    why_competitor="valid",
                    evidence="valid",
                    confidence_score=0.8,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Broken Candidate",
                    suggested_domain="broken",
                    competitor_type="direct",
                    summary="broken",
                    why_competitor="broken",
                    evidence="broken",
                    confidence_score=0.4,
                ),
            ],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{\"candidates\":[{\"domain\":\"valid-competitor.example\"},{\"domain\":\"broken\"}]}',
        )


class _MixedInvalidReasonCompetitorProfileProvider:
    provider_name = "mixed-invalid-reasons-provider"
    model_name = "mixed-invalid-reasons-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="",
                    suggested_domain="missing-name.example",
                    competitor_type="direct",
                    summary="Missing business name.",
                    why_competitor="Missing business name.",
                    evidence="Missing business name.",
                    confidence_score=0.7,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Malformed URL Candidate",
                    suggested_domain="malformed-domain",
                    competitor_type="direct",
                    summary="Malformed domain.",
                    why_competitor="Malformed domain.",
                    evidence="Malformed domain.",
                    confidence_score=0.7,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Missing Domain Candidate",
                    suggested_domain="",
                    competitor_type="direct",
                    summary="Missing domain.",
                    why_competitor="Missing domain.",
                    evidence="Missing domain.",
                    confidence_score=0.7,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Unsupported Type Candidate",
                    suggested_domain="unsupported-type.example",
                    competitor_type="franchise",
                    summary="Local provider with overlapping remodeling services and intent.",
                    why_competitor="Targets the same conversion-driven local service queries.",
                    evidence="Has similar service inventory and local service-area framing.",
                    confidence_score=0.82,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Invalid Confidence Candidate",
                    suggested_domain="invalid-confidence.example",
                    competitor_type="direct",
                    summary="Invalid confidence score.",
                    why_competitor="Invalid confidence score.",
                    evidence="Invalid confidence score.",
                    confidence_score=1.2,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Unknown Competitor",
                    suggested_domain="unknown-low-usefulness.example",
                    competitor_type="unknown",
                    summary=None,
                    why_competitor=None,
                    evidence=None,
                    confidence_score=0.2,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Valid Local Candidate",
                    suggested_domain="valid-local-candidate.example",
                    competitor_type="direct",
                    summary="Serves the same local market for core services.",
                    why_competitor="Competes for the same local transactional search demand.",
                    evidence="Service overlap, local coverage overlap, and similar conversion intent.",
                    confidence_score=0.88,
                ),
            ],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"mixed-invalid-reasons"}]}',
        )


class _InvalidConfidenceCompetitorProfileProvider:
    provider_name = "invalid-confidence-provider"
    model_name = "invalid-confidence-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Invalid Confidence Candidate",
                    suggested_domain="invalid-confidence.example",
                    competitor_type="direct",
                    summary="invalid confidence",
                    why_competitor="invalid confidence",
                    evidence="invalid confidence",
                    confidence_score=1.2,
                )
            ],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{\"candidates\":[{\"confidence_score\":1.2}]}',
        )


class _TimeoutCompetitorProfileProvider:
    provider_name = "openai"
    model_name = "gpt-4.1-mini"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        raise SEOCompetitorProfileProviderError(
            code="timeout",
            safe_message="provider timeout",
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output="{\"error\":\"timeout\"}",
        )


class _TimeoutThenSuccessCompetitorProfileProvider:
    provider_name = "openai"
    model_name = "gpt-4.1-mini"
    prompt_version = "seo-competitor-profile-v1"

    def __init__(self) -> None:
        self.requested_candidate_counts: list[int] = []
        self.reduced_context_modes: list[bool] = []
        self.run_ids: list[str | None] = []
        self.attempt_numbers: list[int | None] = []
        self.degraded_modes: list[bool] = []

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
        reduced_context_mode: bool = False,
        run_id: str | None = None,
        attempt_number: int | None = None,
        degraded_mode: bool = False,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        self.requested_candidate_counts.append(candidate_count)
        self.reduced_context_modes.append(bool(reduced_context_mode))
        self.run_ids.append(run_id)
        self.attempt_numbers.append(attempt_number)
        self.degraded_modes.append(bool(degraded_mode))
        if len(self.requested_candidate_counts) == 1:
            raise SEOCompetitorProfileProviderError(
                code="timeout",
                safe_message="provider timeout",
                provider_name=self.provider_name,
                model_name=self.model_name,
                prompt_version=self.prompt_version,
                raw_output=(
                    "{\"failure_kind\":\"timeout\",\"endpoint_path\":\"/responses\","
                    "\"request_debug\":{\"request_duration_ms\":30500,\"timeout_seconds\":30,"
                    "\"web_search_enabled\":true,\"prompt_size_risk\":\"normal\"}}"
                ),
            )
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Recovered Competitor",
                    suggested_domain="recovered-competitor.example",
                    competitor_type="direct",
                    summary="Recovered on timeout retry.",
                    why_competitor="Recovered deterministic retry output.",
                    evidence="Retry path worked.",
                    confidence_score=0.82,
                )
            ],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response="{\"candidates\":[{\"name\":\"Recovered Competitor\"}]}",
        )


class _ProviderEndpointMetadataSuccessProvider:
    provider_name = "openai"
    model_name = "gpt-5-mini"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
        reduced_context_mode: bool = False,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, reduced_context_mode
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Metadata Competitor",
                    suggested_domain="metadata-competitor.example",
                    competitor_type="direct",
                    summary="Metadata-backed successful provider attempt.",
                    why_competitor="Used to validate endpoint/debug telemetry.",
                    evidence="Provider returned endpoint/tooling metadata on success.",
                    confidence_score=0.83,
                )
            ][:candidate_count],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Metadata Competitor"}]}',
            endpoint_path="/responses",
            web_search_enabled=True,
            request_duration_ms=187,
        )


class _ProviderEndpointMetadataSearchUnavailableLowResultProvider:
    provider_name = "openai"
    model_name = "gpt-5-mini"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
        reduced_context_mode: bool = False,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, reduced_context_mode
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Valid Local Candidate",
                    suggested_domain="valid-local-candidate.example",
                    competitor_type="direct",
                    summary="Serves the same local market for core services.",
                    why_competitor="Competes for the same local transactional search demand.",
                    evidence="Service overlap and local market overlap.",
                    confidence_score=0.86,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="",
                    suggested_domain="missing-name.example",
                    competitor_type="direct",
                    summary="Missing business name.",
                    why_competitor="Missing business name.",
                    evidence="Missing business name.",
                    confidence_score=0.71,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Malformed Candidate",
                    suggested_domain="malformed-domain",
                    competitor_type="direct",
                    summary="Malformed domain.",
                    why_competitor="Malformed domain.",
                    evidence="Malformed domain.",
                    confidence_score=0.64,
                ),
            ][:candidate_count],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Valid Local Candidate"},{"name":"Missing Name"},{"name":"Malformed"}]}',
            endpoint_path="/chat/completions",
            web_search_enabled=False,
            request_duration_ms=432,
        )


class _MalformedOutputReasonDebugProvider:
    provider_name = "openai"
    model_name = "gpt-5-mini"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
        reduced_context_mode: bool = False,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count, reduced_context_mode
        raise SEOCompetitorProfileProviderError(
            code="invalid_output",
            safe_message="Competitor profile generation returned malformed output.",
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output=(
                '{"endpoint_path":"/responses","failure_kind":"malformed_output",'
                '"malformed_output_reason":"missing_candidates_array",'
                '"request_debug":{"request_duration_ms":321,"timeout_seconds":30,"web_search_enabled":true}}'
            ),
        )


class _ProviderRequestFailureObservingProvider:
    provider_name = "openai"
    model_name = "gpt-4.1-mini"
    prompt_version = "seo-competitor-profile-v1"

    def __init__(self) -> None:
        self.requested_candidate_counts: list[int] = []
        self.reduced_context_modes: list[bool] = []

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
        reduced_context_mode: bool = False,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        self.requested_candidate_counts.append(candidate_count)
        self.reduced_context_modes.append(bool(reduced_context_mode))
        raise SEOCompetitorProfileProviderError(
            code="provider_request",
            safe_message="provider request failed",
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output=(
                "{\"failure_kind\":\"provider_request\",\"endpoint_path\":\"/responses\","
                "\"request_debug\":{\"request_duration_ms\":2200,\"timeout_seconds\":30,"
                "\"web_search_enabled\":true,\"prompt_size_risk\":\"normal\"}}"
            ),
        )


class _ProviderAuthCompetitorProfileProvider:
    provider_name = "openai"
    model_name = "gpt-4.1-mini"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        raise SEOCompetitorProfileProviderError(
            code="provider_auth_config",
            safe_message="provider auth failure",
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output="{\"error\":\"unauthorized\"}",
        )


class _DedupScoringCompetitorProfileProvider:
    provider_name = "dedup-scoring-provider"
    model_name = "dedup-scoring-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Denver Precision Plumbing LLC",
                suggested_domain="denver-precision-plumbing.example",
                competitor_type="direct",
                summary="Denver plumbing specialist serving emergency repair and maintenance jobs.",
                why_competitor="Competes on local transactional plumbing intent.",
                evidence="Service area messaging and local emergency coverage.",
                confidence_score=0.89,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Denver Precision Plumbing, Inc.",
                suggested_domain="https://www.denver-precision-plumbing.example/services",
                competitor_type="local",
                summary="Local Denver and Aurora plumbing team with 24/7 service intent.",
                why_competitor="Captures local-pack demand for the same service categories.",
                evidence="Neighborhood-specific service pages and local conversion focus.",
                confidence_score=0.83,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Summit Plumbing Pros",
                suggested_domain="summitplumbingpros.example",
                competitor_type="direct",
                summary="Regional plumbing provider serving Denver metro repair and replacement terms.",
                why_competitor="Competes in the same metro transactional search market.",
                evidence="Overlapping plumbing service inventory and local targeting.",
                confidence_score=0.74,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Walmart Home Services",
                suggested_domain="walmart.com",
                competitor_type="direct",
                summary="National chain marketplace with broad non-local service positioning.",
                why_competitor="Broad service discovery profile but not metro-specific.",
                evidence="No city-specific service-area targeting in candidate text.",
                confidence_score=0.55,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Denver Plumbing Yelp Listings",
                suggested_domain="yelp.com",
                competitor_type="marketplace",
                summary="Directory list page with Denver plumbers.",
                why_competitor="Directory visibility only.",
                evidence="Aggregation content rather than primary business site.",
                confidence_score=0.58,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Unknown Competitor",
                suggested_domain="unknown.example",
                competitor_type="unknown",
                summary=None,
                why_competitor=None,
                evidence=None,
                confidence_score=0.1,
            ),
        ]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates[:candidate_count],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Denver Precision Plumbing LLC"}]}',
        )


class _AllExcludedCompetitorProfileProvider:
    provider_name = "all-excluded-provider"
    model_name = "all-excluded-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Denver Plumbers on Yelp",
                    suggested_domain="yelp.com",
                    competitor_type="marketplace",
                    summary="Directory listing for local plumbers.",
                    why_competitor="Directory listing only.",
                    evidence="Aggregation page, not a direct business website.",
                    confidence_score=0.61,
                ),
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Unknown Competitor",
                    suggested_domain="unknown.example",
                    competitor_type="unknown",
                    summary=None,
                    why_competitor=None,
                    evidence=None,
                    confidence_score=0.1,
                ),
            ],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Denver Plumbers on Yelp"},{"name":"Unknown Competitor"}]}',
        )


class _ModerateCompetitorProfileProvider:
    provider_name = "moderate-provider"
    model_name = "moderate-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Unknown Competitor",
                suggested_domain="genericservicesgroup.example",
                competitor_type="direct",
                summary=None,
                why_competitor=None,
                evidence=None,
                confidence_score=0.2,
            )
        ]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates[:candidate_count],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Generic Services Group"}]}',
        )


class _OverProducingCompetitorProfileProvider:
    provider_name = "over-producing-provider"
    model_name = "over-producing-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Denver Prime Remodeling",
                suggested_domain="denver-prime-remodeling.example",
                competitor_type="direct",
                summary="Denver remodeling services for kitchens and bathrooms.",
                why_competitor="Competes on local remodeling service intent.",
                evidence="Detailed service and neighborhood pages.",
                confidence_score=0.82,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Aurora Build Works",
                suggested_domain="aurora-build-works.example",
                competitor_type="local",
                summary="Aurora and Denver contractor services with emergency scheduling.",
                why_competitor="Overlaps on high-intent local contractor terms.",
                evidence="Same service categories and local conversion pages.",
                confidence_score=0.8,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Northern Range Contractors",
                suggested_domain="northern-range-contractors.example",
                competitor_type="direct",
                summary="Regional construction and remodeling for residential properties.",
                why_competitor="Targets the same local residential project demand.",
                evidence="Service inventory and quote-driven pages.",
                confidence_score=0.79,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Frontier Renovation Group",
                suggested_domain="frontier-renovation-group.example",
                competitor_type="direct",
                summary="Local renovation and project planning services.",
                why_competitor="Competes for the same renovation category intent.",
                evidence="Project-focused pages and contact-ready lead forms.",
                confidence_score=0.77,
            ),
        ]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Denver Prime Remodeling"}]}',
        )


class _EligibilityGateCompetitorProfileProvider:
    provider_name = "eligibility-gate-provider"
    model_name = "eligibility-gate-model"
    prompt_version = "seo-competitor-profile-v1"

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Valid Local Contractor",
                suggested_domain="valid-local-contractor.com",
                competitor_type="direct",
                summary="Serving Denver and Aurora for licensed remodeling and construction projects.",
                why_competitor="Competes for local remodeling and contractor-intent searches.",
                evidence="Service pages, contact details, and local customer proof.",
                confidence_score=0.85,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Parked Domain Candidate",
                suggested_domain="parked-candidate.com",
                competitor_type="direct",
                summary="Supposed competitor with weak web presence.",
                why_competitor="Unclear overlap.",
                evidence="Minimal evidence.",
                confidence_score=0.6,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Offline Domain Candidate",
                suggested_domain="offline-candidate.com",
                competitor_type="local",
                summary="Potential competitor with unavailable site.",
                why_competitor="Unknown overlap.",
                evidence="Unknown.",
                confidence_score=0.6,
            ),
        ]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates[:candidate_count],
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response='{"candidates":[{"name":"Valid Local Contractor"}]}',
        )


class _StatusObservingProvider(_DeterministicCompetitorProfileProvider):
    def __init__(self, *, db_session: Session, business_id: str, run_id: str) -> None:
        self._db_session = db_session
        self._business_id = business_id
        self._run_id = run_id
        self.observed_status: str | None = None

    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        self._db_session.expire_all()
        run = (
            self._db_session.query(SEOCompetitorProfileGenerationRun)
            .filter(SEOCompetitorProfileGenerationRun.business_id == self._business_id)
            .filter(SEOCompetitorProfileGenerationRun.id == self._run_id)
            .one_or_none()
        )
        self.observed_status = run.status if run is not None else None
        return super().generate_competitor_profiles(
            site=site,
            existing_domains=existing_domains,
            candidate_count=candidate_count,
        )


class _DeferredRunExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, business_id: str, site_id: str, generation_run_id: str) -> None:
        self.calls.append((business_id, site_id, generation_run_id))


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(
    db_session,
    *,
    business_id: str,
    generation_provider: SEOCompetitorProfileGenerationProvider | None = None,
    run_executor: Callable[[str, str, str], None] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)
    app.include_router(seo_v1_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    if generation_provider is not None:
        app.dependency_overrides[get_seo_competitor_profile_generation_provider] = lambda: generation_provider
    if run_executor is not None:
        app.dependency_overrides[get_seo_competitor_profile_generation_run_executor] = lambda: run_executor
    return TestClient(app)


def _seed_other_business(db_session) -> Business:
    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550199",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.commit()
    return other_business


def _create_site(client: TestClient, business_id: str, *, domain: str = "client.example") -> str:
    create_site = client.post(
        f"/api/businesses/{business_id}/seo/sites",
        json={"display_name": f"Client Site {domain}", "base_url": f"https://{domain}/"},
    )
    assert create_site.status_code == 201
    return create_site.json()["id"]


def _create_generation_run(
    client: TestClient,
    business_id: str,
    site_id: str,
    *,
    candidate_count: int = 2,
) -> dict[str, object]:
    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": candidate_count},
    )
    assert response.status_code == 201
    return response.json()


def _execute_generation_run(
    *,
    db_session: Session,
    business_id: str,
    site_id: str,
    run_id: str,
    provider: SEOCompetitorProfileGenerationProvider,
    candidate_domain_probe: CompetitorCandidateDomainProbe | None = None,
):
    service = SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=provider,
        candidate_domain_probe=candidate_domain_probe,
    )
    return service.execute_queued_run(
        business_id=business_id,
        site_id=site_id,
        generation_run_id=run_id,
    )


def _seed_tuning_preview_event(
    db_session: Session,
    *,
    business_id: str,
    site_id: str,
    applied_at,
    telemetry_total_runs: int,
    telemetry_total_included: int,
    estimated_included_delta: int,
) -> SEOCompetitorTuningPreviewEvent:
    event = SEOCompetitorTuningPreviewEvent(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        source_narrative_id=None,
        source_recommendation_run_id=None,
        preview_request={
            "current_values": {
                "competitor_candidate_min_relevance_score": 35,
                "competitor_candidate_big_box_penalty": 20,
                "competitor_candidate_directory_penalty": 35,
                "competitor_candidate_local_alignment_bonus": 10,
            },
            "proposed_values": {
                "competitor_candidate_min_relevance_score": 30,
                "competitor_candidate_big_box_penalty": 20,
                "competitor_candidate_directory_penalty": 35,
                "competitor_candidate_local_alignment_bonus": 10,
            },
        },
        preview_response={
            "telemetry_window": {
                "lookback_days": 30,
                "total_runs": telemetry_total_runs,
                "total_raw_candidate_count": 20,
                "total_included_candidate_count": telemetry_total_included,
                "total_excluded_candidate_count": 8,
                "exclusion_counts_by_reason": {
                    "duplicate": 1,
                    "low_relevance": 3,
                    "directory_or_aggregator": 2,
                    "big_box_mismatch": 2,
                    "existing_domain_match": 0,
                    "invalid_candidate": 0,
                },
            },
            "estimated_impact": {
                "insufficient_data": False,
                "estimated_included_candidate_delta": estimated_included_delta,
                "estimated_excluded_candidate_delta": -estimated_included_delta,
                "estimated_exclusion_reason_deltas": {
                    "duplicate": 0,
                    "low_relevance": -estimated_included_delta,
                    "directory_or_aggregator": 0,
                    "big_box_mismatch": 0,
                    "existing_domain_match": 0,
                    "invalid_candidate": 0,
                },
                "summary": "Deterministic preview summary.",
                "risk_flags": [],
            },
            "current_values": {
                "competitor_candidate_min_relevance_score": 35,
                "competitor_candidate_big_box_penalty": 20,
                "competitor_candidate_directory_penalty": 35,
                "competitor_candidate_local_alignment_bonus": 10,
            },
            "proposed_values": {
                "competitor_candidate_min_relevance_score": 30,
                "competitor_candidate_big_box_penalty": 20,
                "competitor_candidate_directory_penalty": 35,
                "competitor_candidate_local_alignment_bonus": 10,
            },
            "caveat": "Preview is deterministic.",
        },
        applied_at=applied_at,
        evaluated_generation_run_id=None,
        evaluated_at=None,
        estimated_included_delta=None,
        actual_included_delta=None,
        error_margin=None,
        direction_correct=None,
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def _complete_generation_run(
    *,
    db_session: Session,
    business_id: str,
    site_id: str,
    run_id: str,
    provider: SEOCompetitorProfileGenerationProvider,
) -> dict[str, object]:
    _execute_generation_run(
        db_session=db_session,
        business_id=business_id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )
    detail = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == business_id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    drafts = (
        db_session.query(SEOCompetitorProfileDraft)
        .filter(SEOCompetitorProfileDraft.business_id == business_id)
        .filter(SEOCompetitorProfileDraft.generation_run_id == run_id)
        .all()
    )
    return {
        "run": detail,
        "drafts": drafts,
    }


def _set_run_stale(
    *,
    db_session: Session,
    business_id: str,
    run_id: str,
    status: str,
    age: timedelta,
) -> None:
    run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == business_id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    run.status = status
    run.error_summary = None
    run.completed_at = None
    run.updated_at = utc_now() - age
    db_session.add(run)
    db_session.commit()


def test_generate_endpoint_queues_run_and_schedules_executor(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)

    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    assert created["run"]["status"] == "queued"
    assert created["run"]["generated_draft_count"] == 0
    assert created["total_drafts"] == 0
    assert created["drafts"] == []
    assert deferred_executor.calls == [(seeded_business.id, site_id, run_id)]

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "queued"
    assert payload["total_drafts"] == 0


def test_async_execution_transitions_running_to_completed_and_persists_drafts(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    observing_provider = _StatusObservingProvider(
        db_session=db_session,
        business_id=seeded_business.id,
        run_id=run_id,
    )
    result = _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=observing_provider,
    )
    assert result is not None
    assert observing_provider.observed_status == "running"

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["generated_draft_count"] == 2
    assert payload["run"]["provider_name"] == "deterministic-test-provider"
    assert payload["run"]["model_name"] == "deterministic-test-model"
    assert payload["run"]["prompt_version"] == "seo-competitor-profile-v1"
    assert payload["total_drafts"] == 2

    persisted_runs = db_session.query(SEOCompetitorProfileGenerationRun).all()
    persisted_drafts = db_session.query(SEOCompetitorProfileDraft).all()
    assert len(persisted_runs) == 1
    assert len(persisted_drafts) == 2
    assert persisted_runs[0].raw_output is not None
    assert "Draft Competitor One" in persisted_runs[0].raw_output


def test_async_execution_failure_marks_run_failed_safely(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_InvalidCompetitorProfileProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["generated_draft_count"] == 0
    assert payload["run"]["error_summary"] == INVALID_OUTPUT_ERROR_SUMMARY
    assert payload["run"]["provider_name"] == "invalid-test-provider"
    assert payload["run"]["model_name"] == "invalid-test-model"
    assert payload["run"]["prompt_version"] == "seo-competitor-profile-v1"
    assert payload["run"]["failure_category"] == "malformed_output"
    assert payload["total_drafts"] == 0
    persisted_run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    assert persisted_run.raw_output is not None
    assert "invalid-domain-without-tld" in persisted_run.raw_output


def test_malformed_provider_output_skips_invalid_candidates_and_keeps_valid_drafts(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_PartiallyInvalidCompetitorProfileProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["error_summary"] is None
    assert payload["run"]["failure_category"] is None
    assert payload["run"]["generated_draft_count"] == 1
    assert payload["run"]["included_candidate_count"] == 1
    assert payload["run"]["excluded_candidate_count"] == 1
    assert payload["run"]["exclusion_counts_by_reason"]["invalid_candidate"] == 1
    assert payload["total_drafts"] == 1
    assert payload["drafts"][0]["suggested_domain"] == "valid-competitor.example"
    assert payload["rejected_candidate_count"] == 1
    assert payload["rejected_candidates"][0]["domain"] == "broken"
    assert "malformed_url" in payload["rejected_candidates"][0]["reasons"]


def test_invalid_candidate_reasons_are_classified_with_specific_codes(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id, candidate_count=5)
    run_id = created["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_MixedInvalidReasonCompetitorProfileProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["raw_candidate_count"] == 7
    assert payload["run"]["included_candidate_count"] == 1
    assert payload["run"]["excluded_candidate_count"] == 6
    assert payload["run"]["exclusion_counts_by_reason"]["invalid_candidate"] == 6
    assert payload["rejected_candidate_count"] == 6
    rejected_reason_set = {
        reason
        for item in payload["rejected_candidates"]
        for reason in item["reasons"]
    }
    assert rejected_reason_set == {
        "missing_business_name",
        "malformed_url",
        "missing_domain",
        "unsupported_type",
        "invalid_confidence_score",
        "low_usefulness_unknown",
    }
    assert [item["suggested_domain"] for item in payload["drafts"]] == ["valid-local-candidate.example"]


def test_invalid_confidence_output_fails_run_safely(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_InvalidConfidenceCompetitorProfileProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["error_summary"] == INVALID_OUTPUT_ERROR_SUMMARY
    assert payload["run"]["failure_category"] == "malformed_output"
    assert payload["total_drafts"] == 0


def test_timeout_provider_failure_marks_run_failed_safely(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_TimeoutCompetitorProfileProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["error_summary"] == PROVIDER_TIMEOUT_ERROR_SUMMARY
    assert payload["run"]["provider_name"] == "openai"
    assert payload["run"]["model_name"] == "gpt-4.1-mini"
    assert payload["run"]["failure_category"] == "timeout"
    assert payload["provider_attempt_count"] == 2
    assert payload["provider_degraded_retry_used"] is True
    assert len(payload["provider_attempts"]) == 2
    assert payload["provider_attempts"][0]["attempt_number"] == 1
    assert payload["provider_attempts"][0]["degraded_mode"] is False
    assert payload["provider_attempts"][0]["failure_kind"] == "timeout"
    assert payload["provider_attempts"][1]["attempt_number"] == 2
    assert payload["provider_attempts"][1]["degraded_mode"] is True
    assert payload["provider_attempts"][1]["failure_kind"] == "timeout"
    assert payload["provider_attempts"][0]["requested_candidate_count"] == 2
    assert payload["provider_attempts"][1]["requested_candidate_count"] == 1
    persisted_run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    assert persisted_run.raw_output is not None
    assert "timeout" in persisted_run.raw_output


def test_provider_auth_failure_marks_run_failed_safely(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_ProviderAuthCompetitorProfileProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["error_summary"] == PROVIDER_AUTH_CONFIG_ERROR_SUMMARY
    assert payload["run"]["provider_name"] == "openai"
    assert payload["run"]["model_name"] == "gpt-4.1-mini"
    assert payload["run"]["failure_category"] == "provider_config"
    assert payload["provider_attempt_count"] == 1
    assert payload["provider_degraded_retry_used"] is False
    assert len(payload["provider_attempts"]) == 1
    assert payload["provider_attempts"][0]["attempt_number"] == 1
    assert payload["provider_attempts"][0]["degraded_mode"] is False
    assert payload["provider_attempts"][0]["failure_kind"] in {"unknown", None}


def test_timeout_retry_recovers_with_degraded_second_attempt(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id, candidate_count=5)
    run_id = created["run"]["id"]
    provider = _TimeoutThenSuccessCompetitorProfileProvider()

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["generated_draft_count"] == 1
    assert payload["total_drafts"] == 1
    assert payload["provider_attempt_count"] == 2
    assert payload["provider_degraded_retry_used"] is True
    assert len(payload["provider_attempts"]) == 2
    assert payload["provider_attempts"][0]["attempt_number"] == 1
    assert payload["provider_attempts"][0]["degraded_mode"] is False
    assert payload["provider_attempts"][0]["reduced_context_mode"] is False
    assert payload["provider_attempts"][0]["failure_kind"] == "timeout"
    assert payload["provider_attempts"][1]["attempt_number"] == 2
    assert payload["provider_attempts"][1]["degraded_mode"] is True
    assert payload["provider_attempts"][1]["reduced_context_mode"] is True
    assert payload["provider_attempts"][1]["outcome"] == "success"
    assert payload["provider_attempts"][1]["requested_candidate_count"] == 3
    assert payload["provider_attempts"][0]["prompt_total_chars"] > payload["provider_attempts"][1]["prompt_total_chars"]
    assert payload["provider_attempts"][0]["context_json_chars"] > payload["provider_attempts"][1]["context_json_chars"]
    assert provider.requested_candidate_counts == [5, 3]
    assert provider.reduced_context_modes == [False, True]
    assert provider.run_ids == [run_id, run_id]
    assert provider.attempt_numbers == [1, 2]
    assert provider.degraded_modes == [False, True]


def test_success_attempt_debug_captures_endpoint_and_web_search_metadata(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    run_id = _create_generation_run(client, seeded_business.id, site_id, candidate_count=1)["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_ProviderEndpointMetadataSuccessProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["provider_attempt_count"] == 1
    assert len(payload["provider_attempts"]) == 1
    attempt = payload["provider_attempts"][0]
    assert attempt["attempt_number"] == 1
    assert attempt["degraded_mode"] is False
    assert attempt["outcome"] == "success"
    assert attempt["endpoint_path"] == "/responses"
    assert attempt["web_search_enabled"] is True
    assert attempt["request_duration_ms"] == 187


def test_run_detail_exposes_low_result_search_unavailable_quality_signals(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    run_id = _create_generation_run(client, seeded_business.id, site_id, candidate_count=3)["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_ProviderEndpointMetadataSearchUnavailableLowResultProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["included_candidate_count"] == 1
    assert payload["run"]["excluded_candidate_count"] == 2
    assert payload["candidate_pipeline_summary"] == {
        "proposed_candidate_count": 3,
        "rejected_by_eligibility_count": 2,
        "eligible_candidate_count": 1,
        "rejected_by_tuning_count": 0,
        "survived_tuning_count": 1,
        "removed_by_existing_domain_match_count": 0,
        "removed_by_deduplication_count": 0,
        "removed_by_final_limit_count": 0,
        "final_candidate_count": 1,
    }
    assert payload["provider_degraded_retry_used"] is False
    assert payload["provider_attempt_count"] == 1
    assert len(payload["provider_attempts"]) == 1
    attempt = payload["provider_attempts"][0]
    assert attempt["endpoint_path"] == "/chat/completions"
    assert attempt["web_search_enabled"] is False
    assert attempt["request_duration_ms"] == 432


def test_run_detail_exposes_malformed_output_reason_in_provider_attempt_debug(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    run_id = _create_generation_run(client, seeded_business.id, site_id, candidate_count=2)["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_MalformedOutputReasonDebugProvider(),
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["failure_category"] == "malformed_output"
    assert payload["provider_attempt_count"] == 1
    assert len(payload["provider_attempts"]) == 1
    attempt = payload["provider_attempts"][0]
    assert attempt["failure_kind"] == "malformed_output"
    assert attempt["malformed_output_reason"] == "missing_candidates_array"
    assert attempt["endpoint_path"] == "/responses"
    assert attempt["web_search_enabled"] is True


def test_non_timeout_provider_failure_does_not_retry(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id, candidate_count=5)
    run_id = created["run"]["id"]
    provider = _ProviderRequestFailureObservingProvider()

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["failure_category"] == "provider_request"
    assert payload["provider_attempt_count"] == 1
    assert payload["provider_degraded_retry_used"] is False
    assert len(payload["provider_attempts"]) == 1
    assert payload["provider_attempts"][0]["attempt_number"] == 1
    assert payload["provider_attempts"][0]["degraded_mode"] is False
    assert payload["provider_attempts"][0]["reduced_context_mode"] is False
    assert payload["provider_attempts"][0]["failure_kind"] == "provider_request"
    assert provider.requested_candidate_counts == [5]
    assert provider.reduced_context_modes == [False]


def test_list_runs_reconciles_stale_queued_and_running_runs(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    queued_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    running_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]

    _set_run_stale(
        db_session=db_session,
        business_id=seeded_business.id,
        run_id=queued_run_id,
        status="queued",
        age=STALE_QUEUED_RUN_TIMEOUT + timedelta(minutes=1),
    )
    _set_run_stale(
        db_session=db_session,
        business_id=seeded_business.id,
        run_id=running_run_id,
        status="running",
        age=STALE_RUNNING_RUN_TIMEOUT + timedelta(minutes=1),
    )

    listed = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs"
    )
    assert listed.status_code == 200
    items = {item["id"]: item for item in listed.json()["items"]}
    assert items[queued_run_id]["status"] == "failed"
    assert items[queued_run_id]["error_summary"] == STALE_QUEUED_RUN_ERROR_SUMMARY
    assert items[queued_run_id]["failure_category"] == "timeout"
    assert items[running_run_id]["status"] == "failed"
    assert items[running_run_id]["error_summary"] == STALE_RUNNING_RUN_ERROR_SUMMARY
    assert items[running_run_id]["failure_category"] == "timeout"


def test_stale_queued_run_marked_failed_is_not_executed(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    _set_run_stale(
        db_session=db_session,
        business_id=seeded_business.id,
        run_id=run_id,
        status="queued",
        age=STALE_QUEUED_RUN_TIMEOUT + timedelta(minutes=1),
    )

    # Trigger reconciliation via list endpoint.
    listed = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs"
    )
    assert listed.status_code == 200

    executed = _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    assert executed is None

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["error_summary"] == STALE_QUEUED_RUN_ERROR_SUMMARY
    assert payload["run"]["failure_category"] == "timeout"
    assert payload["total_drafts"] == 0


def test_retry_failed_run_creates_new_queued_run_with_lineage_and_schedules_executor(
    db_session,
    seeded_business,
) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    original_run_id = created["run"]["id"]

    original_run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == original_run_id)
        .one()
    )
    original_run.status = "failed"
    original_run.error_summary = "provider timeout"
    original_run.prompt_version = "seo-competitor-profile-v2"
    original_run.completed_at = utc_now()
    db_session.add(original_run)
    db_session.commit()

    prior_executor_call_count = len(deferred_executor.calls)
    response = client.post(
        (
            f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/"
            f"competitor-profile-generation-runs/{original_run_id}/retry"
        )
    )
    assert response.status_code == 201
    payload = response.json()
    retried_run = payload["run"]

    assert retried_run["id"] != original_run_id
    assert retried_run["status"] == "queued"
    assert retried_run["parent_run_id"] == original_run_id
    assert retried_run["requested_candidate_count"] == original_run.requested_candidate_count
    assert retried_run["prompt_version"] == "seo-competitor-profile-v2"
    assert payload["total_drafts"] == 0
    assert payload["drafts"] == []

    assert len(deferred_executor.calls) == prior_executor_call_count + 1
    assert deferred_executor.calls[-1] == (seeded_business.id, site_id, retried_run["id"])

    persisted_original = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == original_run_id)
        .one()
    )
    assert persisted_original.status == "failed"
    assert persisted_original.error_summary == "provider timeout"

    persisted_retry = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == retried_run["id"])
        .one()
    )
    assert persisted_retry.parent_run_id == original_run_id


def test_retry_is_rejected_for_non_failed_runs(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/retry"
    )
    assert response.status_code == 422
    assert "only failed competitor profile generation runs can be retried" in response.json()["detail"].lower()


def test_retry_route_enforces_tenant_scope(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    run.status = "failed"
    run.error_summary = "forced failure"
    run.completed_at = utc_now()
    db_session.add(run)
    db_session.commit()

    cross_tenant_retry = client.post(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/retry"
    )
    assert cross_tenant_retry.status_code == 404


def test_competitor_profile_draft_accept_creates_real_competitor_domain(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    completed = _complete_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    draft_id = completed["drafts"][0].id

    accept = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/accept",
        json={},
    )
    assert accept.status_code == 200
    payload = accept.json()
    assert payload["review_status"] == "accepted"
    assert payload["accepted_competitor_domain_id"] is not None
    assert payload["accepted_competitor_set_id"] is not None

    created_domain = (
        db_session.query(SEOCompetitorDomain)
        .filter(SEOCompetitorDomain.id == payload["accepted_competitor_domain_id"])
        .one_or_none()
    )
    assert created_domain is not None
    assert created_domain.source == "ai_generated"
    assert created_domain.site_id == site_id


def test_competitor_profile_draft_reject_does_not_create_competitor_domain(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    completed = _complete_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    draft_id = completed["drafts"][1].id

    reject = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/reject",
        json={"reason": "Not relevant for this market"},
    )
    assert reject.status_code == 200
    payload = reject.json()
    assert payload["review_status"] == "rejected"

    domain_count = (
        db_session.query(SEOCompetitorDomain)
        .filter(SEOCompetitorDomain.business_id == seeded_business.id)
        .filter(SEOCompetitorDomain.site_id == site_id)
        .count()
    )
    assert domain_count == 0


def test_generation_excludes_domains_that_already_exist_as_live_competitors(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)

    first_created = _create_generation_run(client, seeded_business.id, site_id)
    first_run_id = first_created["run"]["id"]
    first_completed = _complete_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=first_run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    first_target_draft = next(
        draft for draft in first_completed["drafts"] if draft.suggested_domain == "draft-competitor-one.example"
    )
    first_draft_id = first_target_draft.id
    first_accept = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{first_run_id}/drafts/{first_draft_id}/accept",
        json={},
    )
    assert first_accept.status_code == 200

    second_created = _create_generation_run(client, seeded_business.id, site_id)
    second_run_id = second_created["run"]["id"]
    second_completed = _complete_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=second_run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    second_domains = {draft.suggested_domain for draft in second_completed["drafts"]}
    assert "draft-competitor-one.example" not in second_domains


def test_competitor_profile_generation_routes_enforce_tenant_scope(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    completed = _complete_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    draft_id = completed["drafts"][0].id

    cross_tenant_list = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs"
    )
    assert cross_tenant_list.status_code == 404

    cross_tenant_detail = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert cross_tenant_detail.status_code == 404

    cross_tenant_accept = client.post(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/accept",
        json={},
    )
    assert cross_tenant_accept.status_code == 404


def test_duplicate_execution_of_same_run_is_prevented(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]

    first = _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    second = _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    assert first is not None
    assert second is None

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["total_drafts"] == 2


def test_generation_dedup_scoring_and_exclusion_are_applied_before_persistence(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    provider = _DedupScoringCompetitorProfileProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    site = (
        db_session.query(SEOSite)
        .filter(SEOSite.business_id == seeded_business.id)
        .filter(SEOSite.id == site_id)
        .one()
    )
    site.primary_location = "Denver, CO"
    site.service_areas_json = ["Denver", "Aurora"]
    db_session.add(site)
    db_session.commit()

    created = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": 6},
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["generated_draft_count"] == 2
    assert payload["run"]["raw_candidate_count"] == 6
    assert payload["run"]["included_candidate_count"] == 2
    assert payload["run"]["excluded_candidate_count"] == 4
    assert payload["run"]["provider_name"] == provider.provider_name
    assert payload["run"]["model_name"] == provider.model_name
    assert payload["total_drafts"] == 2
    assert payload["run"]["exclusion_counts_by_reason"] == {
        "duplicate": 1,
        "low_relevance": 0,
        "directory_or_aggregator": 1,
        "big_box_mismatch": 1,
        "existing_domain_match": 0,
        "invalid_candidate": 1,
    }
    assert payload["tuning_rejected_candidate_count"] == 2
    assert payload["tuning_rejection_reason_counts"] == {
        "below_minimum_relevance_score": 0,
        "directory_or_aggregator_penalty": 1,
        "big_box_mismatch_penalty": 1,
        "insufficient_local_alignment": 0,
    }
    tuning_rejected_by_domain = {item["domain"]: item for item in payload["tuning_rejected_candidates"]}
    assert set(tuning_rejected_by_domain.keys()) == {"yelp.com", "walmart.com"}
    assert tuning_rejected_by_domain["yelp.com"]["reasons"] == ["directory_or_aggregator_penalty"]
    assert tuning_rejected_by_domain["walmart.com"]["reasons"] == ["big_box_mismatch_penalty"]

    returned_domains = [item["suggested_domain"] for item in payload["drafts"]]
    assert returned_domains == [
        "denver-precision-plumbing.example",
        "summitplumbingpros.example",
    ]
    assert payload["candidate_pipeline_summary"] == {
        "proposed_candidate_count": 6,
        "rejected_by_eligibility_count": 1,
        "eligible_candidate_count": 5,
        "rejected_by_tuning_count": 2,
        "survived_tuning_count": 3,
        "removed_by_existing_domain_match_count": 0,
        "removed_by_deduplication_count": 1,
        "removed_by_final_limit_count": 0,
        "final_candidate_count": len(payload["drafts"]),
    }

    persisted_drafts = (
        db_session.query(SEOCompetitorProfileDraft)
        .filter(SEOCompetitorProfileDraft.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileDraft.generation_run_id == run_id)
        .order_by(SEOCompetitorProfileDraft.relevance_score.desc(), SEOCompetitorProfileDraft.suggested_name.asc())
        .all()
    )
    assert len(persisted_drafts) == 2
    assert persisted_drafts[0].suggested_domain == "denver-precision-plumbing.example"
    assert persisted_drafts[0].relevance_score >= persisted_drafts[1].relevance_score

    persisted_run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    assert persisted_run.raw_output is not None
    assert persisted_run.raw_candidate_count == 6
    assert persisted_run.included_candidate_count == 2
    assert persisted_run.excluded_candidate_count == 4
    assert persisted_run.exclusion_counts_by_reason["duplicate"] == 1


def test_generation_ordering_is_deterministic_for_same_input(db_session, seeded_business) -> None:
    provider = _DedupScoringCompetitorProfileProvider()
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)

    first_created = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": 6},
    )
    assert first_created.status_code == 201
    first_run_id = first_created.json()["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=first_run_id,
        provider=provider,
    )

    second_created = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": 6},
    )
    assert second_created.status_code == 201
    second_run_id = second_created.json()["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=second_run_id,
        provider=provider,
    )

    first_detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{first_run_id}"
    )
    second_detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{second_run_id}"
    )
    assert first_detail.status_code == 200
    assert second_detail.status_code == 200

    first_domains = [item["suggested_domain"] for item in first_detail.json()["drafts"]]
    second_domains = [item["suggested_domain"] for item in second_detail.json()["drafts"]]
    assert first_domains == second_domains


def test_generation_pipeline_summary_tracks_final_limit_stage(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    provider = _OverProducingCompetitorProfileProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    site = (
        db_session.query(SEOSite)
        .filter(SEOSite.business_id == seeded_business.id)
        .filter(SEOSite.id == site_id)
        .one()
    )
    site.primary_location = "Denver, CO"
    site.service_areas_json = ["Denver", "Aurora"]
    site.industry = "Construction and remodeling"
    db_session.add(site)
    competitor_set = SEOCompetitorSet(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site_id,
        name="Known Competitors",
        city="Denver",
        state="CO",
        is_active=True,
    )
    db_session.add(competitor_set)
    db_session.add(
        SEOCompetitorDomain(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            domain="northern-range-contractors.example",
            base_url="https://northern-range-contractors.example/",
            display_name="Northern Range Contractors",
            source="manual",
            is_active=True,
        )
    )
    db_session.commit()

    run_id = _create_generation_run(
        client,
        seeded_business.id,
        site_id,
        candidate_count=2,
    )["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["raw_candidate_count"] == 4
    assert payload["run"]["included_candidate_count"] == 2
    assert payload["run"]["excluded_candidate_count"] == 2
    assert payload["run"]["exclusion_counts_by_reason"]["existing_domain_match"] == 1
    assert payload["candidate_pipeline_summary"] == {
        "proposed_candidate_count": 4,
        "rejected_by_eligibility_count": 0,
        "eligible_candidate_count": 4,
        "rejected_by_tuning_count": 0,
        "survived_tuning_count": 4,
        "removed_by_existing_domain_match_count": 1,
        "removed_by_deduplication_count": 0,
        "removed_by_final_limit_count": 1,
        "final_candidate_count": 2,
    }
    assert payload["candidate_pipeline_summary"]["final_candidate_count"] == len(payload["drafts"])


def test_generation_applies_eligibility_filter_before_admin_tuning(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    provider = _EligibilityGateCompetitorProfileProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    site = (
        db_session.query(SEOSite)
        .filter(SEOSite.business_id == seeded_business.id)
        .filter(SEOSite.id == site_id)
        .one()
    )
    site.industry = "Construction"
    site.primary_location = "Denver, CO"
    site.service_areas_json = ["Denver", "Aurora"]
    db_session.add(site)
    db_session.commit()

    run_id = _create_generation_run(client, seeded_business.id, site_id, candidate_count=3)["run"]["id"]

    def domain_probe(domain: str) -> CompetitorCandidateDomainProbeResult | None:
        if domain == "parked-candidate.com":
            return CompetitorCandidateDomainProbeResult(
                status_code=200,
                body_text="This domain is for sale. Buy this domain on Sedo.",
            )
        if domain == "offline-candidate.com":
            return CompetitorCandidateDomainProbeResult(
                status_code=None,
                body_text=None,
                fetch_error="Request failed after retries",
            )
        if domain == "valid-local-contractor.com":
            return CompetitorCandidateDomainProbeResult(
                status_code=200,
                body_text=(
                    "Denver construction and remodeling services. About our team. "
                    "Contact us for licensed residential and commercial projects."
                ),
            )
        return None

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
        candidate_domain_probe=domain_probe,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["raw_candidate_count"] == 3
    assert payload["run"]["included_candidate_count"] == 1
    assert payload["run"]["excluded_candidate_count"] == 2
    assert payload["run"]["exclusion_counts_by_reason"]["invalid_candidate"] == 2
    assert [item["suggested_domain"] for item in payload["drafts"]] == ["valid-local-contractor.com"]
    assert payload["candidate_pipeline_summary"] == {
        "proposed_candidate_count": 3,
        "rejected_by_eligibility_count": 2,
        "eligible_candidate_count": 1,
        "rejected_by_tuning_count": 0,
        "survived_tuning_count": 1,
        "removed_by_existing_domain_match_count": 0,
        "removed_by_deduplication_count": 0,
        "removed_by_final_limit_count": 0,
        "final_candidate_count": 1,
    }
    assert payload["rejected_candidate_count"] == 2
    assert payload["tuning_rejected_candidate_count"] == 0
    assert payload["tuning_rejected_candidates"] == []
    assert payload["tuning_rejection_reason_counts"] == {
        "below_minimum_relevance_score": 0,
        "directory_or_aggregator_penalty": 0,
        "big_box_mismatch_penalty": 0,
        "insufficient_local_alignment": 0,
    }
    rejected_by_domain = {item["domain"]: item for item in payload["rejected_candidates"]}
    assert set(rejected_by_domain.keys()) == {"parked-candidate.com", "offline-candidate.com"}
    assert "parked_domain" in rejected_by_domain["parked-candidate.com"]["reasons"]
    assert rejected_by_domain["parked-candidate.com"]["summary"] == "Unclear overlap."
    assert "no_live_site" in rejected_by_domain["offline-candidate.com"]["reasons"]
    assert rejected_by_domain["offline-candidate.com"]["summary"] == "Unknown overlap."


def test_generation_failure_with_all_candidates_excluded_persists_exclusion_telemetry(
    db_session, seeded_business
) -> None:
    deferred_executor = _DeferredRunExecutor()
    provider = _AllExcludedCompetitorProfileProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    site = (
        db_session.query(SEOSite)
        .filter(SEOSite.business_id == seeded_business.id)
        .filter(SEOSite.id == site_id)
        .one()
    )
    site.primary_location = "Denver, CO"
    site.service_areas_json = ["Denver", "Aurora"]
    db_session.add(site)
    db_session.commit()

    created = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": 2},
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["id"]

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["generated_draft_count"] == 0
    assert payload["run"]["raw_candidate_count"] == 2
    assert payload["run"]["included_candidate_count"] == 0
    assert payload["run"]["excluded_candidate_count"] == 2
    assert payload["run"]["exclusion_counts_by_reason"] == {
        "duplicate": 0,
        "low_relevance": 0,
        "directory_or_aggregator": 1,
        "big_box_mismatch": 0,
        "existing_domain_match": 0,
        "invalid_candidate": 1,
    }
    assert payload["total_drafts"] == 0


def test_generation_uses_business_quality_tuning_threshold_settings(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    provider = _ModerateCompetitorProfileProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    site = (
        db_session.query(SEOSite)
        .filter(SEOSite.business_id == seeded_business.id)
        .filter(SEOSite.id == site_id)
        .one()
    )
    site.primary_location = "Denver, CO"
    site.service_areas_json = ["Denver", "Aurora"]
    db_session.add(site)
    db_session.commit()

    business = db_session.query(Business).filter(Business.id == seeded_business.id).one()
    business.competitor_candidate_min_relevance_score = 0
    db_session.add(business)
    db_session.commit()

    default_threshold_run_id = _create_generation_run(
        client,
        seeded_business.id,
        site_id,
        candidate_count=1,
    )["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=default_threshold_run_id,
        provider=provider,
    )
    default_detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{default_threshold_run_id}"
    )
    assert default_detail.status_code == 200
    assert default_detail.json()["run"]["status"] == "completed"
    assert default_detail.json()["run"]["included_candidate_count"] == 1

    business = db_session.query(Business).filter(Business.id == seeded_business.id).one()
    business.competitor_candidate_min_relevance_score = 35
    db_session.add(business)
    db_session.commit()

    high_threshold_run_id = _create_generation_run(
        client,
        seeded_business.id,
        site_id,
        candidate_count=1,
    )["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=high_threshold_run_id,
        provider=provider,
    )
    high_threshold_detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{high_threshold_run_id}"
    )
    assert high_threshold_detail.status_code == 200
    high_payload = high_threshold_detail.json()
    assert high_payload["run"]["status"] == "failed"
    assert high_payload["run"]["included_candidate_count"] == 0
    assert high_payload["run"]["excluded_candidate_count"] == 1
    assert high_payload["run"]["exclusion_counts_by_reason"]["low_relevance"] == 1
    assert high_payload["candidate_pipeline_summary"] == {
        "proposed_candidate_count": 1,
        "rejected_by_eligibility_count": 0,
        "eligible_candidate_count": 1,
        "rejected_by_tuning_count": 1,
        "survived_tuning_count": 0,
        "removed_by_existing_domain_match_count": 0,
        "removed_by_deduplication_count": 0,
        "removed_by_final_limit_count": 0,
        "final_candidate_count": 0,
    }
    assert high_payload["tuning_rejected_candidate_count"] == 1
    assert high_payload["tuning_rejection_reason_counts"]["below_minimum_relevance_score"] == 1
    assert high_payload["tuning_rejection_reason_counts"]["insufficient_local_alignment"] == 1


def test_generation_fails_safely_when_business_quality_tuning_is_invalid(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    provider = _ModerateCompetitorProfileProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=provider,
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    business = db_session.query(Business).filter(Business.id == seeded_business.id).one()
    business.competitor_candidate_big_box_penalty = 100
    db_session.add(business)
    db_session.commit()

    run_id = _create_generation_run(
        client,
        seeded_business.id,
        site_id,
        candidate_count=1,
    )["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=provider,
    )

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["error_summary"] == "Competitor profile generation failed due to invalid candidate quality settings."
    assert payload["run"]["failure_category"] == "internal_error"


def test_competitor_profile_draft_edit_marks_edited_status(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    completed = _complete_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )
    draft_id = completed["drafts"][0].id

    edit = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}",
        json={"suggested_name": "Edited Competitor Name"},
    )
    assert edit.status_code == 200
    payload = edit.json()
    assert payload["review_status"] == "edited"
    assert payload["suggested_name"] == "Edited Competitor Name"


def test_generation_summary_endpoint_returns_status_failure_and_retry_metrics(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)

    completed_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=completed_run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )

    timeout_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=timeout_run_id,
        provider=_TimeoutCompetitorProfileProvider(),
    )

    invalid_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=invalid_run_id,
        provider=_InvalidCompetitorProfileProvider(),
    )

    retry_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{timeout_run_id}/retry"
    )
    assert retry_response.status_code == 201

    summary_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert summary_response.status_code == 200
    payload = summary_response.json()

    assert payload["queued_count"] == 1
    assert payload["running_count"] == 0
    assert payload["completed_count"] == 1
    assert payload["failed_count"] == 2
    assert payload["retry_child_runs"] == 1
    assert payload["retried_parent_runs"] == 1
    assert payload["failed_runs_retried"] == 1
    assert payload["failure_category_counts"]["timeout"] == 1
    assert payload["failure_category_counts"]["malformed_output"] == 1
    assert payload["total_runs"] == 4
    assert payload["total_raw_candidate_count"] == 3
    assert payload["total_included_candidate_count"] == 2
    assert payload["total_excluded_candidate_count"] == 1
    assert payload["exclusion_counts_by_reason"] == {
        "duplicate": 0,
        "low_relevance": 0,
        "directory_or_aggregator": 0,
        "big_box_mismatch": 0,
        "existing_domain_match": 0,
        "invalid_candidate": 1,
    }
    assert payload["latest_run_created_at"] is not None
    assert payload["latest_run_completed_at"] is not None


def test_generation_summary_endpoint_aggregates_cross_run_exclusion_telemetry(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    site = (
        db_session.query(SEOSite)
        .filter(SEOSite.business_id == seeded_business.id)
        .filter(SEOSite.id == site_id)
        .one()
    )
    site.primary_location = "Denver, CO"
    site.service_areas_json = ["Denver", "Aurora"]
    db_session.add(site)
    db_session.commit()

    rich_run_id = _create_generation_run(
        client,
        seeded_business.id,
        site_id,
        candidate_count=6,
    )["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=rich_run_id,
        provider=_DedupScoringCompetitorProfileProvider(),
    )

    all_excluded_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=all_excluded_run_id,
        provider=_AllExcludedCompetitorProfileProvider(),
    )

    timeout_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=timeout_run_id,
        provider=_TimeoutCompetitorProfileProvider(),
    )

    summary_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert summary_response.status_code == 200
    payload = summary_response.json()

    assert payload["total_runs"] == 3
    assert payload["total_raw_candidate_count"] == 8
    assert payload["total_included_candidate_count"] == 2
    assert payload["total_excluded_candidate_count"] == 6
    assert payload["exclusion_counts_by_reason"] == {
        "duplicate": 1,
        "low_relevance": 0,
        "directory_or_aggregator": 2,
        "big_box_mismatch": 1,
        "existing_domain_match": 0,
        "invalid_candidate": 2,
    }


def test_generation_summary_endpoint_enforces_bounded_exclusion_reason_keys(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == run_id)
        .one()
    )
    run.status = "completed"
    run.generated_draft_count = 0
    run.raw_candidate_count = 4
    run.included_candidate_count = 1
    run.excluded_candidate_count = 3
    run.exclusion_counts_by_reason = {
        "duplicate": 1,
        "low_relevance": 2,
        "unexpected_reason": 99,
    }
    run.completed_at = utc_now()
    db_session.add(run)
    db_session.commit()

    summary_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert summary_response.status_code == 200
    payload = summary_response.json()
    assert payload["total_runs"] == 1
    assert payload["total_excluded_candidate_count"] == 3
    assert payload["exclusion_counts_by_reason"] == {
        "duplicate": 1,
        "low_relevance": 2,
        "directory_or_aggregator": 0,
        "big_box_mismatch": 0,
        "existing_domain_match": 0,
        "invalid_candidate": 0,
    }


def test_generation_summary_endpoint_returns_zero_candidate_telemetry_when_no_runs(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)

    summary_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert summary_response.status_code == 200
    payload = summary_response.json()
    assert payload["total_runs"] == 0
    assert payload["total_raw_candidate_count"] == 0
    assert payload["total_included_candidate_count"] == 0
    assert payload["total_excluded_candidate_count"] == 0
    assert payload["exclusion_counts_by_reason"] == {
        "duplicate": 0,
        "low_relevance": 0,
        "directory_or_aggregator": 0,
        "big_box_mismatch": 0,
        "existing_domain_match": 0,
        "invalid_candidate": 0,
    }


def test_generation_summary_endpoint_includes_failed_run_candidate_telemetry_totals(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)

    completed_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    failed_run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]

    completed_run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == completed_run_id)
        .one()
    )
    completed_run.status = "completed"
    completed_run.generated_draft_count = 2
    completed_run.raw_candidate_count = 2
    completed_run.included_candidate_count = 2
    completed_run.excluded_candidate_count = 0
    completed_run.exclusion_counts_by_reason = {
        "duplicate": 0,
        "low_relevance": 0,
        "directory_or_aggregator": 0,
        "big_box_mismatch": 0,
        "existing_domain_match": 0,
        "invalid_candidate": 0,
    }
    completed_run.completed_at = utc_now()
    db_session.add(completed_run)

    failed_run = (
        db_session.query(SEOCompetitorProfileGenerationRun)
        .filter(SEOCompetitorProfileGenerationRun.business_id == seeded_business.id)
        .filter(SEOCompetitorProfileGenerationRun.id == failed_run_id)
        .one()
    )
    failed_run.status = "failed"
    failed_run.generated_draft_count = 0
    failed_run.raw_candidate_count = 5
    failed_run.included_candidate_count = 0
    failed_run.excluded_candidate_count = 5
    failed_run.exclusion_counts_by_reason = {
        "duplicate": 0,
        "low_relevance": 5,
        "directory_or_aggregator": 0,
        "big_box_mismatch": 0,
        "existing_domain_match": 0,
        "invalid_candidate": 0,
    }
    failed_run.completed_at = utc_now()
    db_session.add(failed_run)
    db_session.commit()

    summary_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert summary_response.status_code == 200
    payload = summary_response.json()

    assert payload["total_runs"] == 2
    assert payload["total_raw_candidate_count"] == 7
    assert payload["total_included_candidate_count"] == 2
    assert payload["total_excluded_candidate_count"] == 5
    assert payload["exclusion_counts_by_reason"]["low_relevance"] == 5


def test_generation_run_completion_evaluates_pending_preview_accuracy_event(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    run_id = _create_generation_run(client, seeded_business.id, site_id)["run"]["id"]
    preview_event = _seed_tuning_preview_event(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        applied_at=utc_now() - timedelta(minutes=1),
        telemetry_total_runs=2,
        telemetry_total_included=2,
        estimated_included_delta=2,
    )

    _execute_generation_run(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        run_id=run_id,
        provider=_DeterministicCompetitorProfileProvider(),
    )

    db_session.refresh(preview_event)
    assert preview_event.evaluated_generation_run_id == run_id
    assert preview_event.evaluated_at is not None
    assert preview_event.estimated_included_delta == 1
    assert preview_event.actual_included_delta == 1
    assert preview_event.error_margin == 0
    assert preview_event.direction_correct is True


def test_generation_summary_endpoint_includes_preview_accuracy_aggregates(db_session, seeded_business) -> None:
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    now = utc_now()
    event_one = _seed_tuning_preview_event(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        applied_at=now - timedelta(days=1),
        telemetry_total_runs=3,
        telemetry_total_included=6,
        estimated_included_delta=3,
    )
    event_two = _seed_tuning_preview_event(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        applied_at=now - timedelta(days=1),
        telemetry_total_runs=2,
        telemetry_total_included=4,
        estimated_included_delta=-2,
    )
    event_one.evaluated_generation_run_id = str(uuid4())
    event_one.evaluated_at = now - timedelta(hours=1)
    event_one.estimated_included_delta = 1
    event_one.actual_included_delta = 2
    event_one.error_margin = 1
    event_one.direction_correct = True
    event_two.evaluated_generation_run_id = str(uuid4())
    event_two.evaluated_at = now - timedelta(minutes=30)
    event_two.estimated_included_delta = -1
    event_two.actual_included_delta = 1
    event_two.error_margin = 2
    event_two.direction_correct = False
    db_session.add(event_one)
    db_session.add(event_two)
    db_session.commit()

    summary_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert summary_response.status_code == 200
    payload = summary_response.json()

    assert payload["preview_accuracy_rate"] == 0.5
    assert payload["avg_error_margin"] == 1.5
    assert payload["last_n_preview_accuracy"]["window_size"] == 10
    assert payload["last_n_preview_accuracy"]["sample_size"] == 2
    assert payload["last_n_preview_accuracy"]["direction_correct_count"] == 1
    assert payload["last_n_preview_accuracy"]["accuracy_rate"] == 0.5
    assert payload["last_n_preview_accuracy"]["avg_error_margin"] == 1.5


def test_generation_summary_endpoint_enforces_tenant_scope(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    deferred_executor = _DeferredRunExecutor()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
        run_executor=deferred_executor,
    )
    site_id = _create_site(client, seeded_business.id)
    _create_generation_run(client, seeded_business.id, site_id)

    scoped = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert scoped.status_code == 200

    cross_tenant = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    )
    assert cross_tenant.status_code == 404

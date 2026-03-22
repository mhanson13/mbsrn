from __future__ import annotations

import pytest

from app.models.seo_site import SEOSite
from app.services.seo_competitor_profile_candidate_quality import (
    DEFAULT_MIN_RELEVANCE_SCORE,
    CompetitorCandidateQualityTuning,
    CompetitorCandidateInput,
    EXCLUSION_REASON_KEYS,
    canonicalize_domain,
    default_competitor_candidate_quality_tuning,
    normalize_competitor_name_for_matching,
    normalize_location_for_matching,
    process_competitor_candidates,
)


def _site() -> SEOSite:
    return SEOSite(
        id="site-1",
        business_id="biz-1",
        display_name="Acme Home Services",
        base_url="https://acmehomeservices.example/",
        normalized_domain="acmehomeservices.example",
        industry="Plumbing",
        primary_location="Denver, CO",
        service_areas_json=["Denver", "Aurora", "Lakewood"],
        is_active=True,
        is_primary=True,
        last_audit_run_id=None,
        last_audit_status=None,
        last_audit_completed_at=None,
    )


def _candidate(
    *,
    name: str,
    domain: str,
    competitor_type: str = "direct",
    summary: str | None = "Serving Denver customers for plumbing emergencies and repairs.",
    why: str | None = "Competes on local service intent for residential plumbing terms in Denver.",
    evidence: str | None = "Uses neighborhood service pages and local intent messaging.",
    confidence: float = 0.75,
    index: int = 0,
) -> CompetitorCandidateInput:
    return CompetitorCandidateInput(
        suggested_name=name,
        suggested_domain=domain,
        competitor_type=competitor_type,
        summary=summary,
        why_competitor=why,
        evidence=evidence,
        confidence_score=confidence,
        source_index=index,
    )


def test_name_domain_location_normalizers_are_deterministic() -> None:
    assert normalize_competitor_name_for_matching("Acme Plumbing, LLC") == "acme plumbing"
    assert canonicalize_domain("https://WWW.AcmePlumbing.com/services") == "acmeplumbing.com"
    assert normalize_location_for_matching(" Denver,\n CO ") == "denver, co"


def test_exact_domain_match_collapses_to_single_candidate() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(name="Acme Plumbing", domain="acmeplumbing.com", index=0),
            _candidate(name="Acme Plumbing Co.", domain="https://www.acmeplumbing.com/contact", index=1),
        ],
    )
    assert len(result.included_candidates) == 1
    assert result.raw_candidate_count == 2
    assert result.deduped_candidate_count == 1
    assert result.excluded_candidate_count == 1
    assert result.exclusion_counts_by_reason["duplicate"] == 1


def test_name_suffix_and_punctuation_variants_collapse_safely() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Acme Plumbing, LLC",
                domain="acmeplumbing-denver.example",
                summary="Denver plumbing service across Aurora and Lakewood neighborhoods.",
                index=0,
            ),
            _candidate(
                name="Acme Plumbing Inc.",
                domain="acmeplumbingco.example",
                summary="Local Denver plumbing contractor serving Aurora and Lakewood.",
                index=1,
            ),
        ],
    )
    assert len(result.included_candidates) == 1
    assert result.raw_candidate_count == 2
    assert result.deduped_candidate_count == 1
    assert result.excluded_candidate_count == 1
    assert result.exclusion_counts_by_reason["duplicate"] == 1


def test_distinct_businesses_do_not_merge() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(name="Acme Plumbing", domain="acmeplumbing.example", index=0),
            _candidate(
                name="Summit Electric",
                domain="summitelectric.example",
                summary="Denver electrical contractor focused on rewiring and panel upgrades.",
                why="Competes in electrical search demand rather than plumbing intent.",
                evidence="Targets electrical repair and electrician service terms.",
                index=1,
            ),
        ],
    )
    assert len(result.included_candidates) == 2
    included_domains = {item.canonical_domain for item in result.included_candidates}
    assert included_domains == {"acmeplumbing.example", "summitelectric.example"}
    assert result.excluded_candidate_count == 0
    assert all(count == 0 for count in result.exclusion_counts_by_reason.values())


def test_business_specific_candidate_scores_higher_than_generic_candidate() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Denver Precision Plumbing",
                domain="denverprecisionplumbing.example",
                index=0,
            ),
            _candidate(
                name="Unknown Competitor",
                domain="listing-hub.example",
                competitor_type="unknown",
                summary="Generic listings.",
                why=None,
                evidence=None,
                confidence=0.2,
                index=1,
            ),
        ],
        minimum_relevance_score=0,
    )
    assert len(result.included_candidates) == 2
    assert result.included_candidates[0].canonical_domain == "denverprecisionplumbing.example"
    assert result.included_candidates[0].relevance_score > result.included_candidates[1].relevance_score


def test_directory_candidate_is_conservatively_excluded() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(name="Denver Precision Plumbing", domain="denverprecisionplumbing.example", index=0),
            _candidate(
                name="Denver Plumbers on Yelp",
                domain="yelp.com",
                competitor_type="marketplace",
                summary="Directory listing for local plumbers in Denver.",
                index=1,
            ),
        ],
    )
    assert len(result.included_candidates) == 1
    assert result.excluded_candidate_count == 1
    assert result.exclusion_counts_by_reason["directory_or_aggregator"] == 1
    assert result.included_candidates[0].canonical_domain == "denverprecisionplumbing.example"


def test_local_alignment_scores_higher_than_non_local_chain_candidate() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Denver Precision Plumbing",
                domain="denverprecisionplumbing.example",
                summary="Serving Denver and Aurora for emergency and routine plumbing support.",
                index=0,
            ),
            _candidate(
                name="Walmart Home Services",
                domain="walmart.com",
                competitor_type="marketplace",
                summary="National marketplace for home services.",
                why="Broad national service offering.",
                evidence="No Denver-specific service area references.",
                index=1,
            ),
        ],
        minimum_relevance_score=0,
    )
    assert len(result.included_candidates) == 2
    assert result.included_candidates[0].canonical_domain == "denverprecisionplumbing.example"
    walmart = next(item for item in result.included_candidates if item.canonical_domain == "walmart.com")
    denver_local = next(
        item for item in result.included_candidates if item.canonical_domain == "denverprecisionplumbing.example"
    )
    assert denver_local.relevance_score > walmart.relevance_score


def test_weak_candidate_is_excluded_below_threshold() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Unknown Competitor",
                domain="unknown.example",
                competitor_type="unknown",
                summary=None,
                why=None,
                evidence=None,
                confidence=0.1,
                index=0,
            )
        ],
    )
    assert result.raw_candidate_count == 1
    assert result.deduped_candidate_count == 1
    assert result.excluded_candidate_count == 1
    assert result.exclusion_counts_by_reason["low_relevance"] == 1
    assert result.included_candidates == []


def test_big_box_candidate_is_excluded_when_local_context_is_missing() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Walmart Home Services",
                domain="walmart.com",
                competitor_type="direct",
                summary="National marketplace for home services.",
                why="Broad national service catalog.",
                evidence="No neighborhood or city-specific service details.",
                confidence=0.62,
                index=0,
            )
        ],
    )
    assert result.raw_candidate_count == 1
    assert result.included_candidates == []
    assert result.excluded_candidate_count == 1
    assert result.exclusion_counts_by_reason["big_box_mismatch"] == 1
    assert tuple(result.exclusion_counts_by_reason.keys()) == EXCLUSION_REASON_KEYS


def test_existing_domain_match_is_counted_as_excluded_reason() -> None:
    result = process_competitor_candidates(
        site=_site(),
        existing_domains=["summitplumbingpros.example"],
        candidates=[
            _candidate(
                name="Summit Plumbing Pros",
                domain="summitplumbingpros.example",
                competitor_type="direct",
                confidence=0.82,
                index=0,
            )
        ],
    )
    assert result.raw_candidate_count == 1
    assert result.included_candidates == []
    assert result.excluded_candidate_count == 1
    assert result.exclusion_counts_by_reason["existing_domain_match"] == 1


def test_default_tuning_is_used_when_quality_tuning_not_provided() -> None:
    default_result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Denver Precision Plumbing",
                domain="denverprecisionplumbing.example",
                summary="Serving Denver and Aurora for emergency and routine plumbing support.",
                index=0,
            ),
            _candidate(
                name="Walmart Home Services",
                domain="walmart.com",
                competitor_type="marketplace",
                summary="National marketplace for home services.",
                why="Broad national service offering.",
                evidence="No Denver-specific service area references.",
                index=1,
            ),
        ],
        minimum_relevance_score=0,
    )
    explicit_default_result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Denver Precision Plumbing",
                domain="denverprecisionplumbing.example",
                summary="Serving Denver and Aurora for emergency and routine plumbing support.",
                index=0,
            ),
            _candidate(
                name="Walmart Home Services",
                domain="walmart.com",
                competitor_type="marketplace",
                summary="National marketplace for home services.",
                why="Broad national service offering.",
                evidence="No Denver-specific service area references.",
                index=1,
            ),
        ],
        quality_tuning=default_competitor_candidate_quality_tuning(),
    )

    assert [item.canonical_domain for item in default_result.included_candidates] == [
        item.canonical_domain for item in explicit_default_result.included_candidates
    ]
    assert [item.relevance_score for item in default_result.included_candidates] == [
        item.relevance_score for item in explicit_default_result.included_candidates
    ]


def test_custom_tuning_changes_scores_deterministically() -> None:
    base_result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Denver Precision Plumbing",
                domain="denverprecisionplumbing.example",
                summary="Serving Denver and Aurora for emergency and routine plumbing support.",
                index=0,
            ),
            _candidate(
                name="Walmart Home Services",
                domain="walmart.com",
                competitor_type="marketplace",
                summary="National marketplace for home services.",
                why="Broad national service offering.",
                evidence="No Denver-specific service area references.",
                index=1,
            ),
        ],
        quality_tuning=CompetitorCandidateQualityTuning(
            minimum_relevance_score=0,
            big_box_penalty=20,
            directory_penalty=35,
            local_alignment_bonus=10,
        ),
    )
    tuned_result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[
            _candidate(
                name="Denver Precision Plumbing",
                domain="denverprecisionplumbing.example",
                summary="Serving Denver and Aurora for emergency and routine plumbing support.",
                index=0,
            ),
            _candidate(
                name="Walmart Home Services",
                domain="walmart.com",
                competitor_type="marketplace",
                summary="National marketplace for home services.",
                why="Broad national service offering.",
                evidence="No Denver-specific service area references.",
                index=1,
            ),
        ],
        quality_tuning=CompetitorCandidateQualityTuning(
            minimum_relevance_score=0,
            big_box_penalty=50,
            directory_penalty=35,
            local_alignment_bonus=0,
        ),
    )

    base_by_domain = {item.canonical_domain: item.relevance_score for item in base_result.included_candidates}
    tuned_by_domain = {item.canonical_domain: item.relevance_score for item in tuned_result.included_candidates}
    assert tuned_by_domain["walmart.com"] < base_by_domain["walmart.com"]
    assert tuned_by_domain["denverprecisionplumbing.example"] <= base_by_domain["denverprecisionplumbing.example"]


def test_custom_minimum_relevance_threshold_controls_exclusion() -> None:
    candidate = _candidate(
        name="Generic Services Group",
        domain="genericservicesgroup.example",
        competitor_type="unknown",
        summary="General services provider.",
        why=None,
        evidence=None,
        confidence=0.35,
        index=0,
    )
    included_result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[candidate],
        quality_tuning=CompetitorCandidateQualityTuning(
            minimum_relevance_score=DEFAULT_MIN_RELEVANCE_SCORE,
            big_box_penalty=20,
            directory_penalty=35,
            local_alignment_bonus=10,
        ),
    )
    excluded_result = process_competitor_candidates(
        site=_site(),
        existing_domains=[],
        candidates=[candidate],
        quality_tuning=CompetitorCandidateQualityTuning(
            minimum_relevance_score=80,
            big_box_penalty=20,
            directory_penalty=35,
            local_alignment_bonus=10,
        ),
    )

    assert included_result.raw_candidate_count == 1
    assert len(included_result.included_candidates) == 1
    assert excluded_result.included_candidates == []
    assert excluded_result.exclusion_counts_by_reason["low_relevance"] == 1


def test_quality_tuning_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        CompetitorCandidateQualityTuning(minimum_relevance_score=101)

    with pytest.raises(ValueError):
        CompetitorCandidateQualityTuning(big_box_penalty=51)

    with pytest.raises(ValueError):
        CompetitorCandidateQualityTuning(directory_penalty=51)

    with pytest.raises(ValueError):
        CompetitorCandidateQualityTuning(local_alignment_bonus=51)

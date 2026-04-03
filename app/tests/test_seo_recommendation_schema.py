from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.seo_recommendation import (
    SEOCompetitorContextHealthRead,
    SEORecommendationRead,
    SEORecommendationStartHereRead,
    infer_eeat_categories_from_signals,
)


def _recommendation_payload(**overrides):
    payload = {
        "id": str(uuid4()),
        "business_id": str(uuid4()),
        "site_id": str(uuid4()),
        "recommendation_run_id": str(uuid4()),
        "audit_run_id": None,
        "comparison_run_id": None,
        "rule_key": "fix_missing_title_tags",
        "category": "SEO",
        "severity": "WARNING",
        "title": "Fix title tags",
        "rationale": "Missing titles were detected.",
        "priority_score": 70,
        "priority_band": "high",
        "effort_bucket": "LOW",
        "status": "open",
        "decision": None,
        "decision_reason": None,
        "assigned_principal_id": None,
        "due_at": None,
        "snoozed_until": None,
        "resolved_at": None,
        "updated_by_principal_id": None,
        "evidence_json": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return payload


def test_infer_eeat_categories_from_signals_maps_supported_values() -> None:
    categories = infer_eeat_categories_from_signals(
        [
            "missing_license_proof",
            "missing_project_story",
            "association_membership_gap",
            "technical_capability_missing",
        ]
    )
    assert categories == ["experience", "expertise", "authoritativeness", "trustworthiness"]


def test_infer_eeat_categories_from_signals_ignores_ambiguous_values() -> None:
    categories = infer_eeat_categories_from_signals(["missing_title", "thin_content", "meta_description"])
    assert categories == []


def test_recommendation_read_derives_eeat_categories_from_structured_signals() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="close_competitor_gap_missing_license_proof",
            evidence_json={
                "sources": ["comparison"],
                "finding_types": ["missing_license_proof", "missing_project_story"],
                "counts": {"missing_license_proof": 1, "missing_project_story": 1},
            },
        )
    )
    assert recommendation.eeat_categories == ["experience", "trustworthiness"]
    assert recommendation.primary_eeat_category == "experience"


def test_recommendation_read_keeps_eeat_empty_for_unsupported_structured_signals() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="fix_missing_title_tags",
            evidence_json={
                "sources": ["audit"],
                "finding_types": ["missing_title"],
                "counts": {"missing_title": 2},
            },
        )
    )
    assert recommendation.eeat_categories == []
    assert recommendation.primary_eeat_category is None


def test_recommendation_read_derives_competitor_and_trust_priority_reasons() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            comparison_run_id=str(uuid4()),
            rule_key="close_competitor_gap_missing_license_proof",
            title="Publish license proof on service pages",
            rationale="This creates verifiable trust proof where competitors are currently stronger.",
            evidence_json={
                "sources": ["comparison"],
                "finding_types": ["missing_license_proof"],
            },
        )
    )
    assert recommendation.priority_reasons == [
        "competitor_gap",
        "trust_gap",
        "high_clarity_action",
    ]
    assert recommendation.primary_priority_reason == "competitor_gap"


def test_recommendation_read_derives_authority_priority_reason_from_eeat() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            title="Authority coverage gap",
            rationale="Third-party recognition proof is weaker than peer providers.",
            eeat_categories=["authoritativeness"],
            primary_eeat_category="authoritativeness",
            evidence_json={"sources": ["audit"]},
        )
    )
    assert recommendation.priority_reasons == ["authority_gap"]
    assert recommendation.primary_priority_reason == "authority_gap"


def test_recommendation_read_keeps_priority_reasons_empty_when_metadata_is_sparse() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            title="Site metadata cleanup",
            rationale="General cleanup note",
            comparison_run_id=None,
            evidence_json={"sources": ["audit"], "finding_types": ["missing_title"]},
            eeat_categories=[],
            primary_eeat_category=None,
        )
    )
    assert recommendation.priority_reasons == []
    assert recommendation.primary_priority_reason is None


@pytest.mark.parametrize(
    ("category", "expected_theme"),
    [
        ("trustworthiness", "trust_and_legitimacy"),
        ("experience", "experience_and_proof"),
        ("authoritativeness", "authority_and_visibility"),
        ("expertise", "expertise_and_process"),
    ],
)
def test_recommendation_read_derives_theme_from_eeat_category(
    category: str,
    expected_theme: str,
) -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            eeat_categories=[category],
            primary_eeat_category=category,
            priority_reasons=[],
            primary_priority_reason=None,
            evidence_json={"sources": ["audit"]},
        )
    )
    assert recommendation.theme == expected_theme
    assert recommendation.theme_label


def test_recommendation_read_derives_theme_from_priority_reason_when_eeat_missing() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            eeat_categories=[],
            primary_eeat_category=None,
            priority_reasons=["authority_gap"],
            primary_priority_reason="authority_gap",
            evidence_json={"sources": ["comparison"]},
        )
    )
    assert recommendation.theme == "authority_and_visibility"
    assert recommendation.theme_label == "Authority & visibility"


def test_recommendation_read_falls_back_to_general_theme_for_sparse_metadata() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="fix_missing_title_tags",
            title="Fix title tags",
            rationale="General cleanup note",
            eeat_categories=[],
            primary_eeat_category=None,
            priority_reasons=[],
            primary_priority_reason=None,
            evidence_json={"sources": ["audit"], "finding_types": ["missing_title"]},
        )
    )
    assert recommendation.theme == "general_site_improvement"
    assert recommendation.theme_label == "General site improvement"


def test_recommendation_read_derives_default_progress_summary_from_status() -> None:
    suggested = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_progress_status="suggested",
            recommendation_progress_summary=None,
        )
    )
    pending_refresh = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_progress_status="applied_pending_refresh",
            recommendation_progress_summary=None,
        )
    )
    reflected = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_progress_status="reflected_in_latest_analysis",
            recommendation_progress_summary=None,
        )
    )

    assert suggested.recommendation_progress_summary == "Suggested action not yet applied."
    assert pending_refresh.recommendation_progress_summary == (
        "Applied. Waiting for the next analysis refresh to reflect this change."
    )
    assert reflected.recommendation_progress_summary == "Applied and reflected in the latest analysis."


def test_recommendation_read_derives_lifecycle_state_from_progress_status() -> None:
    suggested = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_progress_status="suggested",
            recommendation_progress_summary=None,
        )
    )
    pending_refresh = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_progress_status="applied_pending_refresh",
            recommendation_progress_summary=None,
        )
    )
    reflected = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_progress_status="reflected_in_latest_analysis",
            recommendation_progress_summary=None,
        )
    )

    assert suggested.recommendation_lifecycle_state == "active"
    assert suggested.recommendation_lifecycle_summary == "Still an active recommendation."
    assert pending_refresh.recommendation_lifecycle_state == "applied_waiting_validation"
    assert pending_refresh.recommendation_lifecycle_summary == "Applied and waiting for refreshed validation."
    assert reflected.recommendation_lifecycle_state == "reflected_still_relevant"
    assert reflected.recommendation_lifecycle_summary == "Reflected in analysis, but still appears relevant."


def test_recommendation_read_derives_likely_resolved_only_for_sparse_reflected_signals() -> None:
    reflected_sparse = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="",
            title="Metadata review",
            rationale="",
            recommendation_progress_status="reflected_in_latest_analysis",
            recommendation_progress_summary=None,
            recommendation_evidence_summary=None,
            recommendation_observed_gap_summary="Current site signals in this recommendation area appear limited or inconsistent.",
            recommendation_target_context="general",
            recommendation_evidence_trace=[],
            eeat_categories=[],
            priority_reasons=[],
        )
    )
    assert reflected_sparse.recommendation_lifecycle_state == "likely_resolved"
    assert reflected_sparse.recommendation_lifecycle_summary == "Likely addressed in the latest analysis."


def test_recommendation_read_derives_competitor_backed_evidence_summary() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            comparison_run_id=str(uuid4()),
            rule_key="close_competitor_gap_missing_license_proof",
            title="Publish license proof on service pages",
            rationale="This creates verifiable trust proof where competitors are currently stronger.",
            evidence_json={
                "sources": ["comparison"],
                "finding_types": ["missing_license_proof"],
            },
        )
    )
    assert recommendation.recommendation_evidence_summary == "Competitors show stronger trust signals in this area."


def test_recommendation_read_derives_eeat_evidence_summary_when_competitor_signal_absent() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            eeat_categories=["experience"],
            primary_eeat_category="experience",
            evidence_json={"sources": ["audit"]},
        )
    )
    assert recommendation.recommendation_evidence_summary == "This improves visible proof of real work and outcomes."


def test_recommendation_read_omits_evidence_summary_when_metadata_is_sparse() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            title="Site metadata cleanup",
            rationale="General cleanup note",
            comparison_run_id=None,
            evidence_json=None,
            eeat_categories=[],
            primary_eeat_category=None,
            priority_reasons=[],
            primary_priority_reason=None,
        )
    )
    assert recommendation.recommendation_evidence_summary is None


def test_recommendation_read_derives_action_clarity_and_expected_outcome_for_trust_gap() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            comparison_run_id=str(uuid4()),
            rule_key="close_competitor_gap_missing_license_proof",
            title="Add license and insurance proof to service pages",
            rationale="This creates verifiable trust proof where competitors are currently stronger.",
            evidence_json={
                "sources": ["comparison"],
                "finding_types": ["missing_license_proof"],
            },
        )
    )
    assert recommendation.recommendation_action_clarity == "Add license and insurance proof to service pages."
    assert (
        recommendation.recommendation_expected_outcome
        == "Helps visitors trust the business faster while closing visible competitor trust gaps."
    )


def test_recommendation_read_derives_action_clarity_and_expected_outcome_for_service_clarity() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="improve_service_page_clarity",
            title="Clarify flooring services",
            rationale="Service detail and local intent clarity are weak on primary pages.",
            eeat_categories=["expertise"],
            primary_eeat_category="expertise",
            priority_reasons=["expertise_gap"],
            primary_priority_reason="expertise_gap",
            theme="expertise_and_process",
            theme_label="Expertise & process",
            evidence_json={"sources": ["audit"]},
        )
    )
    assert recommendation.recommendation_action_clarity == "Clarify flooring services on core local and location pages."
    assert (
        recommendation.recommendation_expected_outcome
        == "Makes service capability and process quality easier to evaluate."
    )


def test_recommendation_read_derives_safe_expected_outcome_fallback_for_sparse_metadata() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="fix_missing_title_tags",
            title="Site metadata cleanup",
            rationale="General cleanup note",
            comparison_run_id=None,
            evidence_json=None,
            eeat_categories=[],
            primary_eeat_category=None,
            priority_reasons=[],
            primary_priority_reason=None,
        )
    )
    assert recommendation.recommendation_action_clarity == (
        "Update meta title and page title block on high-visibility service pages."
    )
    assert recommendation.recommendation_expected_outcome == "Improves core site clarity for prospective customers."


def test_recommendation_read_normalizes_target_page_hints_with_bounds() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            recommendation_target_page_hints=[
                "Homepage",
                "  /services  ",
                "homepage",
                "/about",
                "/contact",
            ]
        )
    )
    assert recommendation.recommendation_target_page_hints == ["Homepage", "/services", "/about"]


def test_recommendation_read_derives_target_content_types_from_evidence() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            evidence_json={
                "sources": ["audit"],
                "target_content_types": [
                    {
                        "type_key": "meta_title",
                        "label": "Meta title",
                        "source_type": "audit_signal",
                        "targeting_strength": "high",
                    },
                    {
                        "type_key": "meta_description",
                        "label": "Meta description",
                        "source_type": "audit_signal",
                        "targeting_strength": "high",
                    },
                ],
            }
        )
    )
    assert [item.type_key for item in recommendation.recommendation_target_content_types] == [
        "meta_title",
        "meta_description",
    ]
    assert recommendation.recommendation_target_content_summary == "Meta title and Meta description"


def test_recommendation_read_derives_target_content_types_deterministically_from_signals() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="fix_missing_h1",
            title="Fix missing H1 heading coverage",
            rationale="Missing_h1 issues were detected on key service pages.",
            evidence_json={"sources": ["audit"], "finding_types": ["missing_h1"]},
        )
    )
    derived_keys = [item.type_key for item in recommendation.recommendation_target_content_types]
    assert "heading_h1" in derived_keys
    assert "page_title_block" in derived_keys
    assert recommendation.recommendation_target_content_summary is not None


def test_recommendation_read_keeps_target_content_empty_when_not_grounded() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="generic_housekeeping",
            title="General cleanup",
            rationale="Perform manual review of this recommendation.",
            evidence_json={"sources": ["audit"]},
        )
    )
    assert recommendation.recommendation_target_content_types == []
    assert recommendation.recommendation_target_content_summary is None


def test_recommendation_read_uses_plain_language_action_when_content_target_summary_is_present() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="fix_missing_h1",
            title="Fix missing H1 headings on service pages",
            rationale="Missing_h1 issues were detected on key service pages.",
            recommendation_target_context="service_pages",
            recommendation_target_content_summary="Main heading and Intro paragraph",
            evidence_json={"sources": ["audit"], "finding_types": ["missing_h1"]},
        )
    )
    assert recommendation.recommendation_action_clarity is not None
    assert recommendation.recommendation_action_clarity.startswith("Update main heading and intro paragraph on")
    assert recommendation.recommendation_action_clarity.endswith("service pages.")


def test_recommendation_read_derives_contact_about_target_context_for_trust_signals() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="close_competitor_gap_missing_license_proof",
            title="Add license and insurance proof to service pages",
            rationale="Trust proof and contact legitimacy are weaker than nearby competitors.",
            eeat_categories=["trustworthiness"],
            primary_eeat_category="trustworthiness",
            priority_reasons=["trust_gap"],
            primary_priority_reason="trust_gap",
            theme="trust_and_legitimacy",
            theme_label="Trust & legitimacy",
        )
    )
    assert recommendation.recommendation_target_context == "contact_about"


def test_recommendation_read_derives_homepage_target_context_from_homepage_signal() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="improve_homepage_service_clarity",
            title="Clarify core services on homepage",
            rationale="Homepage value proposition is unclear for local service intent.",
        )
    )
    assert recommendation.recommendation_target_context == "homepage"


def test_recommendation_read_derives_location_pages_target_context_from_local_signals() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="expand_location_page_coverage",
            title="Strengthen location page coverage",
            rationale="Local city/service-area intent is underrepresented across location pages.",
            theme="authority_and_visibility",
            theme_label="Authority & visibility",
        )
    )
    assert recommendation.recommendation_target_context == "location_pages"


def test_recommendation_read_derives_sitewide_target_context_for_global_changes() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="standardize_trust_signals_sitewide",
            title="Apply trust signal consistency across all pages",
            rationale="Global trust copy and verification signals should be standardized sitewide.",
        )
    )
    assert recommendation.recommendation_target_context == "sitewide"


def test_recommendation_read_derives_general_target_context_for_sparse_metadata() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="generic_cleanup",
            title="General metadata cleanup",
            rationale="General cleanup note.",
            theme="general_site_improvement",
            theme_label="General site improvement",
            eeat_categories=[],
            priority_reasons=[],
        )
    )
    assert recommendation.recommendation_target_context == "general"


def test_recommendation_read_derives_observed_gap_summary_for_trust_signals() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="close_competitor_gap_missing_license_proof",
            title="Add license and insurance proof to service pages",
            rationale="Trust proof and contact legitimacy are weaker than nearby competitors.",
            eeat_categories=["trustworthiness"],
            primary_eeat_category="trustworthiness",
            priority_reasons=["trust_gap"],
            primary_priority_reason="trust_gap",
            theme="trust_and_legitimacy",
            theme_label="Trust & legitimacy",
        )
    )
    assert recommendation.recommendation_observed_gap_summary is not None
    assert "trust" in recommendation.recommendation_observed_gap_summary.lower()


def test_recommendation_read_derives_observed_gap_summary_for_service_clarity() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="improve_service_page_clarity",
            title="Clarify flooring services on core service pages",
            rationale="Service detail and service proof are inconsistent across key pages.",
            recommendation_target_context="service_pages",
            eeat_categories=["expertise"],
            primary_eeat_category="expertise",
            priority_reasons=["expertise_gap"],
            primary_priority_reason="expertise_gap",
            theme="expertise_and_process",
            theme_label="Expertise & process",
        )
    )
    assert recommendation.recommendation_observed_gap_summary == (
        "Service-specific wording and proof appear weak or inconsistent."
    )


def test_recommendation_read_derives_observed_gap_summary_for_location_context() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="expand_location_page_coverage",
            title="Strengthen location page coverage",
            rationale="Local city/service-area intent is underrepresented.",
            recommendation_target_context="location_pages",
            theme="authority_and_visibility",
            theme_label="Authority & visibility",
        )
    )
    assert recommendation.recommendation_observed_gap_summary == "Local/service-area relevance signals appear limited."


def test_recommendation_read_derives_observed_gap_summary_for_experience_proof() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="add_project_testimonial_proof",
            title="Publish project stories and testimonial proof",
            rationale="Project proof is limited compared to nearby providers.",
            eeat_categories=["experience"],
            primary_eeat_category="experience",
            priority_reasons=["experience_gap"],
            primary_priority_reason="experience_gap",
            theme="experience_and_proof",
            theme_label="Experience & proof",
        )
    )
    assert recommendation.recommendation_observed_gap_summary == (
        "Project/testimonial proof appears limited on likely service pages."
    )


def test_recommendation_read_derives_observed_gap_summary_safe_fallback_for_sparse_metadata() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="generic_cleanup",
            title="General metadata cleanup",
            rationale="General cleanup note.",
            theme="general_site_improvement",
            theme_label="General site improvement",
            eeat_categories=[],
            priority_reasons=[],
        )
    )
    assert recommendation.recommendation_observed_gap_summary == (
        "Current site signals in this recommendation area appear limited or inconsistent."
    )


def test_recommendation_read_derives_evidence_trace_for_competitor_backed_trust_recommendation() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="close_competitor_gap_missing_license_proof",
            title="Add license and insurance proof to service pages",
            rationale="Trust proof and contact legitimacy are weaker than nearby competitors.",
            comparison_run_id=str(uuid4()),
            recommendation_target_context="contact_about",
            eeat_categories=["trustworthiness"],
            primary_eeat_category="trustworthiness",
            priority_reasons=["competitor_gap", "trust_gap"],
            primary_priority_reason="competitor_gap",
            evidence_json={"sources": ["comparison"], "finding_types": ["missing_license_proof"]},
        )
    )
    trace = recommendation.recommendation_evidence_trace
    assert "Competitor-backed" in trace
    assert "Trust/verification gap" in trace
    assert "Contact/About" in trace


def test_recommendation_read_derives_evidence_trace_for_service_clarity_recommendation() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="improve_service_page_clarity",
            title="Clarify flooring services on core service pages",
            rationale="Service detail and service proof are inconsistent across key pages.",
            recommendation_target_context="service_pages",
            eeat_categories=["expertise"],
            primary_eeat_category="expertise",
            priority_reasons=["expertise_gap"],
            primary_priority_reason="expertise_gap",
            evidence_json={"sources": ["audit"]},
        )
    )
    trace = recommendation.recommendation_evidence_trace
    assert "Service/process clarity" in trace
    assert "Service pages" in trace


def test_recommendation_read_derives_evidence_trace_for_location_recommendation() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="expand_location_page_coverage",
            title="Strengthen location page coverage",
            rationale="Local city/service-area intent is underrepresented.",
            recommendation_target_context="location_pages",
            theme="authority_and_visibility",
            theme_label="Authority & visibility",
        )
    )
    trace = recommendation.recommendation_evidence_trace
    assert "Local relevance gap" in trace
    assert "Location pages" in trace


def test_recommendation_read_derives_safe_evidence_trace_fallback_for_sparse_metadata() -> None:
    recommendation = SEORecommendationRead.model_validate(
        _recommendation_payload(
            rule_key="generic_cleanup",
            title="General metadata cleanup",
            rationale="General cleanup note.",
            theme="general_site_improvement",
            theme_label="General site improvement",
            eeat_categories=[],
            priority_reasons=[],
            evidence_json=None,
        )
    )
    trace = recommendation.recommendation_evidence_trace
    assert "General site signals" in trace


def test_recommendation_start_here_read_normalizes_context_flags() -> None:
    start_here = SEORecommendationStartHereRead.model_validate(
        {
            "theme": "trust_and_legitimacy",
            "theme_label": "Trust & legitimacy",
            "recommendation_id": str(uuid4()),
            "title": "Publish license and insurance trust proof",
            "reason": "Start here to close a high-visibility trust and legitimacy gap.",
            "context_flags": ["pending_refresh_context", "pending_refresh_context", "ignored", "competitor_backed"],
        }
    )
    assert start_here.context_flags == ["pending_refresh_context", "competitor_backed"]


def test_recommendation_start_here_read_rejects_invalid_theme() -> None:
    with pytest.raises(ValueError):
        SEORecommendationStartHereRead.model_validate(
            {
                "theme": "invalid_theme",
                "theme_label": "Invalid",
                "recommendation_id": str(uuid4()),
                "title": "Invalid",
                "reason": "Invalid",
                "context_flags": [],
            }
        )


def test_competitor_context_health_read_normalizes_and_orders_checks() -> None:
    health = SEOCompetitorContextHealthRead.model_validate(
        {
            "status": "mixed",
            "message": "Competitor matching has partial business context; results may be narrower or more conservative.",
            "checks": [
                {
                    "key": "service_focus",
                    "label": "Service focus",
                    "status": "strong",
                    "detail": "Service focus terms are available: construction, remodeling.",
                },
                {
                    "key": "location_context",
                    "label": "Location context",
                    "status": "weak",
                    "detail": "Location context is weak or missing.",
                },
                {
                    "key": "industry_context",
                    "label": "Industry context",
                    "status": "strong",
                    "detail": "Industry context is available: Construction.",
                },
            ],
        }
    )
    assert [check.key for check in health.checks] == [
        "location_context",
        "industry_context",
        "service_focus",
    ]

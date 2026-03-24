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

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.seo_recommendation import SEORecommendationRead, infer_eeat_categories_from_signals


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

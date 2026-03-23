from __future__ import annotations

from datetime import UTC, datetime

from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.services.seo_recommendation_narrative_prompt import (
    SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION,
    build_seo_recommendation_narrative_prompt,
)


def _run() -> SEORecommendationRun:
    return SEORecommendationRun(
        id="run-1",
        business_id="biz-1",
        site_id="site-1",
        audit_run_id="audit-1",
        comparison_run_id=None,
        status="completed",
        total_recommendations=2,
        critical_recommendations=1,
        warning_recommendations=1,
        info_recommendations=0,
    )


def _recommendations() -> list[SEORecommendation]:
    return [
        SEORecommendation(
            id="rec-2",
            business_id="biz-1",
            site_id="site-1",
            recommendation_run_id="run-1",
            audit_run_id="audit-1",
            comparison_run_id=None,
            rule_key="expand_thin_content_pages",
            category="CONTENT",
            severity="CRITICAL",
            title="Expand thin content pages",
            rationale="Pages are thin and need meaningful depth updates.",
            priority_score=90,
            priority_band="critical",
            effort_bucket="HIGH",
            status="open",
            created_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        ),
        SEORecommendation(
            id="rec-1",
            business_id="biz-1",
            site_id="site-1",
            recommendation_run_id="run-1",
            audit_run_id="audit-1",
            comparison_run_id=None,
            rule_key="fix_missing_title_tags",
            category="SEO",
            severity="WARNING",
            title="Fix missing title tags",
            rationale="A" * 500,
            priority_score=70,
            priority_band="high",
            effort_bucket="LOW",
            status="in_progress",
            created_at=datetime(2026, 3, 20, 11, 0, tzinfo=UTC),
        ),
    ]


def test_prompt_contains_grounded_deterministic_context() -> None:
    prompt = build_seo_recommendation_narrative_prompt(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1, "in_progress": 1},
        by_category={"SEO": 1, "CONTENT": 1},
        by_severity={"CRITICAL": 1, "WARNING": 1},
        by_effort_bucket={"HIGH": 1, "LOW": 1},
        by_priority_band={"critical": 1, "high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "lookback_days": 30,
            "total_runs": 4,
            "total_raw_candidate_count": 12,
            "total_included_candidate_count": 8,
            "total_excluded_candidate_count": 4,
            "exclusion_counts_by_reason": {
                "duplicate": 1,
                "low_relevance": 2,
                "directory_or_aggregator": 1,
                "big_box_mismatch": 0,
                "existing_domain_match": 0,
                "invalid_candidate": 0,
            },
        },
        current_tuning_values={
            "competitor_candidate_min_relevance_score": 35,
            "competitor_candidate_big_box_penalty": 20,
            "competitor_candidate_directory_penalty": 35,
            "competitor_candidate_local_alignment_bonus": 10,
        },
    )

    assert prompt.prompt_version == SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION
    assert "RECOMMENDATION_CONTEXT_JSON" in prompt.user_prompt
    assert prompt.grounded_context["recommendation_run_id"] == "run-1"
    assert prompt.grounded_context["allowed_recommendation_ids"] == ["rec-1", "rec-2"]
    assert len(prompt.grounded_context["top_recommendations"]) == 2
    top_item = prompt.grounded_context["top_recommendations"][0]
    assert top_item["id"] == "rec-2"
    assert len(top_item["rationale_excerpt"]) <= 320
    assert prompt.grounded_context["competitor_candidate_telemetry"]["total_excluded_candidate_count"] == 4
    assert (
        prompt.grounded_context["current_candidate_quality_tuning"]["competitor_candidate_directory_penalty"] == 35
    )
    assert "tuning_suggestions" in prompt.user_prompt
    assert "ONLY if justified by provided recommendation and telemetry data" in prompt.user_prompt


def test_prompt_appends_additional_recommendation_text_safely() -> None:
    prompt = build_seo_recommendation_narrative_prompt(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1},
        by_category={"SEO": 1},
        by_severity={"WARNING": 1},
        by_effort_bucket={"LOW": 1},
        by_priority_band={"high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "lookback_days": 30,
            "total_runs": 0,
            "total_raw_candidate_count": 0,
            "total_included_candidate_count": 0,
            "total_excluded_candidate_count": 0,
            "exclusion_counts_by_reason": {},
        },
        current_tuning_values={
            "competitor_candidate_min_relevance_score": 35,
            "competitor_candidate_big_box_penalty": 20,
            "competitor_candidate_directory_penalty": 35,
            "competitor_candidate_local_alignment_bonus": 10,
        },
        prompt_text_recommendations="Prefer concise operator language.",
    )

    assert "ADDITIONAL_RECOMMENDATIONS_TEXT" in prompt.user_prompt
    assert "Prefer concise operator language." in prompt.user_prompt


def test_prompt_is_deterministic_for_same_inputs() -> None:
    left = build_seo_recommendation_narrative_prompt(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1, "in_progress": 1},
        by_category={"SEO": 1, "CONTENT": 1},
        by_severity={"CRITICAL": 1, "WARNING": 1},
        by_effort_bucket={"HIGH": 1, "LOW": 1},
        by_priority_band={"critical": 1, "high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "lookback_days": 30,
            "total_runs": 4,
            "total_raw_candidate_count": 12,
            "total_included_candidate_count": 8,
            "total_excluded_candidate_count": 4,
            "exclusion_counts_by_reason": {"low_relevance": 2},
        },
        current_tuning_values={
            "competitor_candidate_min_relevance_score": 35,
            "competitor_candidate_big_box_penalty": 20,
            "competitor_candidate_directory_penalty": 35,
            "competitor_candidate_local_alignment_bonus": 10,
        },
    )
    right = build_seo_recommendation_narrative_prompt(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1, "in_progress": 1},
        by_category={"SEO": 1, "CONTENT": 1},
        by_severity={"CRITICAL": 1, "WARNING": 1},
        by_effort_bucket={"HIGH": 1, "LOW": 1},
        by_priority_band={"critical": 1, "high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "lookback_days": 30,
            "total_runs": 4,
            "total_raw_candidate_count": 12,
            "total_included_candidate_count": 8,
            "total_excluded_candidate_count": 4,
            "exclusion_counts_by_reason": {"low_relevance": 2},
        },
        current_tuning_values={
            "competitor_candidate_min_relevance_score": 35,
            "competitor_candidate_big_box_penalty": 20,
            "competitor_candidate_directory_penalty": 35,
            "competitor_candidate_local_alignment_bonus": 10,
        },
    )

    assert left.system_prompt == right.system_prompt
    assert left.user_prompt == right.user_prompt
    assert left.grounded_context == right.grounded_context


def test_prompt_supports_deprecated_prompt_alias() -> None:
    prompt = build_seo_recommendation_narrative_prompt(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1},
        by_category={"SEO": 1},
        by_severity={"WARNING": 1},
        by_effort_bucket={"LOW": 1},
        by_priority_band={"high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "lookback_days": 30,
            "total_runs": 1,
            "total_raw_candidate_count": 2,
            "total_included_candidate_count": 1,
            "total_excluded_candidate_count": 1,
            "exclusion_counts_by_reason": {"low_relevance": 1},
        },
        current_tuning_values={
            "competitor_candidate_min_relevance_score": 35,
            "competitor_candidate_big_box_penalty": 20,
            "competitor_candidate_directory_penalty": 35,
            "competitor_candidate_local_alignment_bonus": 10,
        },
        prompt_text_recommendation="Prefer concise summaries.",
    )

    assert "ADDITIONAL_RECOMMENDATIONS_TEXT" in prompt.user_prompt


def test_recommendation_prompt_avoids_competitor_discovery_language() -> None:
    prompt = build_seo_recommendation_narrative_prompt(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1},
        by_category={"SEO": 1},
        by_severity={"WARNING": 1},
        by_effort_bucket={"LOW": 1},
        by_priority_band={"high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "lookback_days": 30,
            "total_runs": 0,
            "total_raw_candidate_count": 0,
            "total_included_candidate_count": 0,
            "total_excluded_candidate_count": 0,
            "exclusion_counts_by_reason": {},
        },
        current_tuning_values={
            "competitor_candidate_min_relevance_score": 35,
            "competitor_candidate_big_box_penalty": 20,
            "competitor_candidate_directory_penalty": 35,
            "competitor_candidate_local_alignment_bonus": 10,
        },
    )

    assert "REQUESTED_CANDIDATE_COUNT" not in prompt.user_prompt
    assert "ALLOWED_COMPETITOR_TYPES" not in prompt.user_prompt

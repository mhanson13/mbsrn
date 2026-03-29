from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
    SEORecommendationNarrativeOutput,
)
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite
from app.services.seo_ai_evaluation_harness import (
    CompetitorEvalCase,
    CompetitorEvalExpected,
    CompetitorEvalInput,
    RecommendationEvalCase,
    RecommendationEvalExpected,
    RecommendationEvalInput,
    format_eval_report_text,
    load_competitor_eval_cases,
    load_recommendation_eval_cases,
    reports_to_json,
    run_competitor_eval,
    run_recommendation_eval,
    score_competitor_output,
    score_recommendation_output,
)


def _fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "ai_eval"


def _site() -> SEOSite:
    return SEOSite(
        id="site-1",
        business_id="biz-1",
        display_name="Client Site",
        base_url="https://client.example/",
        normalized_domain="client.example",
        industry="Roofing",
        primary_location="Denver, CO",
        service_areas_json=["Denver"],
        is_active=True,
        is_primary=True,
    )


def _recommendation_run() -> SEORecommendationRun:
    return SEORecommendationRun(
        id="run-1",
        business_id="biz-1",
        site_id="site-1",
        audit_run_id="audit-1",
        comparison_run_id=None,
        status="completed",
        total_recommendations=1,
        critical_recommendations=0,
        warning_recommendations=1,
        info_recommendations=0,
    )


def _recommendation() -> SEORecommendation:
    return SEORecommendation(
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
        rationale="Deterministic recommendation rationale.",
        priority_score=70,
        priority_band="high",
        effort_bucket="LOW",
        status="open",
    )


def test_competitor_fixture_loading_invalid_shape_fails(tmp_path: Path) -> None:
    fixture_file = tmp_path / "competitor_cases.json"
    fixture_file.write_text('{"cases":[{"description":"missing id","input":{},"expected":{}}]}', encoding="utf-8")
    (tmp_path / "recommendation_cases.json").write_text('{"cases":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="case_id"):
        load_competitor_eval_cases(tmp_path)


def test_recommendation_fixture_loading_invalid_shape_fails(tmp_path: Path) -> None:
    (tmp_path / "competitor_cases.json").write_text('{"cases":[]}', encoding="utf-8")
    fixture_file = tmp_path / "recommendation_cases.json"
    fixture_file.write_text('{"cases":[{"case_id":"x","description":"y","input":{},"expected":{}}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="run"):
        load_recommendation_eval_cases(tmp_path)


def test_golden_fixtures_load_cleanly() -> None:
    competitor_cases = load_competitor_eval_cases(_fixture_root())
    recommendation_cases = load_recommendation_eval_cases(_fixture_root())
    assert len(competitor_cases) >= 8
    assert len(recommendation_cases) >= 8


def test_competitor_scoring_penalizes_forbidden_domain() -> None:
    case = CompetitorEvalCase(
        case_id="case-1",
        description="forbidden domain test",
        input=CompetitorEvalInput(
            business_id="biz-1",
            site=_site(),
            existing_domains=[],
            candidate_count=3,
        ),
        expected=CompetitorEvalExpected(
            forbidden_domain_substrings=["yelp"],
            required_service_terms_any=["roof"],
            min_candidate_count=1,
            max_candidate_count=3,
        ),
    )
    output = SEOCompetitorProfileGenerationOutput(
        candidates=[
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Yelp Listing",
                suggested_domain="yelp.com",
                competitor_type="marketplace",
                summary="Directory listing",
                why_competitor="Ranks for terms",
                evidence="Directory",
                confidence_score=0.7,
            )
        ],
        provider_name="mock",
        model_name="mock-model",
        prompt_version="prompt-v1",
    )

    score, reasons, hard_fail = score_competitor_output(output=output, case=case)
    assert score < 70
    assert hard_fail is True
    assert any("forbidden_domain_substring:yelp" in reason for reason in reasons)


def test_competitor_scoring_penalizes_geography_mismatch() -> None:
    case = CompetitorEvalCase(
        case_id="case-2",
        description="geo mismatch test",
        input=CompetitorEvalInput(
            business_id="biz-1",
            site=_site(),
            existing_domains=[],
            candidate_count=3,
        ),
        expected=CompetitorEvalExpected(
            required_location_terms_any=["denver"],
            required_service_terms_any=["roof"],
            min_candidate_count=1,
            max_candidate_count=3,
        ),
    )
    output = SEOCompetitorProfileGenerationOutput(
        candidates=[
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Austin Roof Pro",
                suggested_domain="austinroofpro.example",
                competitor_type="direct",
                summary="Austin roofing business",
                why_competitor="Service overlap",
                evidence="search overlap",
                confidence_score=0.6,
            )
        ],
        provider_name="mock",
        model_name="mock-model",
        prompt_version="prompt-v1",
    )

    score, reasons, _ = score_competitor_output(output=output, case=case)
    assert score < 90
    assert "missing_required_location_signal" in reasons


def test_recommendation_scoring_penalizes_generic_phrase() -> None:
    case = RecommendationEvalCase(
        case_id="rec-case-1",
        description="generic text check",
        input=RecommendationEvalInput(
            run=_recommendation_run(),
            recommendations=[_recommendation()],
            backlog_ids=["rec-1"],
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            competitor_telemetry_summary={},
            current_tuning_values={},
        ),
        expected=RecommendationEvalExpected(
            forbidden_phrases=["as an ai language model"],
            min_narrative_chars=10,
        ),
    )
    output = SEORecommendationNarrativeOutput(
        narrative_text="As an AI language model, optimize your website.",
        top_themes=["SEO basics"],
        sections={"next_actions": ["Do something"], "recommendation_references": ["rec-1"]},
        provider_name="mock",
        model_name="mock-model",
        prompt_version="prompt-v1",
    )

    score, reasons, hard_fail = score_recommendation_output(output=output, case=case)
    assert score < 80
    assert hard_fail is True
    assert any(reason.startswith("generic_phrase:") for reason in reasons)


def test_recommendation_scoring_penalizes_missing_references() -> None:
    case = RecommendationEvalCase(
        case_id="rec-case-2",
        description="missing references check",
        input=RecommendationEvalInput(
            run=_recommendation_run(),
            recommendations=[_recommendation()],
            backlog_ids=["rec-1"],
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            competitor_telemetry_summary={},
            current_tuning_values={},
        ),
        expected=RecommendationEvalExpected(
            required_recommendation_ids_any=["rec-1"],
            require_recommendation_references=True,
            min_narrative_chars=10,
        ),
    )
    output = SEORecommendationNarrativeOutput(
        narrative_text="Focus on title tags first.",
        top_themes=["title tags"],
        sections={"next_actions": ["Fix title tags"], "recommendation_references": []},
        provider_name="mock",
        model_name="mock-model",
        prompt_version="prompt-v1",
    )

    score, reasons, _ = score_recommendation_output(output=output, case=case)
    assert score < 90
    assert "missing_recommendation_references" in reasons
    assert "missing_expected_reference_ids" in reasons


class _StubCompetitorProvider:
    def generate_competitor_profiles(
        self, *, site: SEOSite, existing_domains: list[str], candidate_count: int
    ):  # noqa: ANN001
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Denver Roof Works",
                    suggested_domain="denverroofworks.example",
                    competitor_type="direct",
                    summary="Roofing services in Denver",
                    why_competitor="Direct service overlap",
                    evidence="intent overlap",
                    confidence_score=0.8,
                )
            ],
            provider_name="stub",
            model_name="stub-model",
            prompt_version="stub-prompt",
        )


class _StubRecommendationProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003
        del kwargs
        return SEORecommendationNarrativeOutput(
            narrative_text="Priority focus is fixing missing title tags on service pages.",
            top_themes=["metadata quality"],
            sections={"next_actions": ["Fix title tags"], "recommendation_references": ["rec-1"]},
            provider_name="stub",
            model_name="stub-model",
            prompt_version="stub-prompt",
        )


def test_runner_and_report_include_aggregate_fields() -> None:
    competitor_case = CompetitorEvalCase(
        case_id="runner-case-1",
        description="runner",
        input=CompetitorEvalInput(
            business_id="biz-1",
            site=_site(),
            existing_domains=[],
            candidate_count=1,
        ),
        expected=CompetitorEvalExpected(
            required_location_terms_any=["denver"],
            required_service_terms_any=["roof"],
            min_candidate_count=1,
            max_candidate_count=2,
        ),
    )
    report = run_competitor_eval(cases=[competitor_case], provider=_StubCompetitorProvider())
    report_text = format_eval_report_text(report)
    report_json = reports_to_json([report])

    assert report.total_cases == 1
    assert report.eval_mode == "mock"
    assert report.provider_name == "unknown-provider"
    assert report.model_name == "unknown-model"
    assert "aggregate_score" in report_text
    assert "mode=mock" in report_text
    assert "runner-case-1" in report_text
    assert '"pipeline": "competitor"' in report_json
    assert '"eval_mode": "mock"' in report_json

    recommendation_case = RecommendationEvalCase(
        case_id="runner-case-2",
        description="runner rec",
        input=RecommendationEvalInput(
            run=_recommendation_run(),
            recommendations=[_recommendation()],
            backlog_ids=["rec-1"],
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            competitor_telemetry_summary={},
            current_tuning_values={},
        ),
        expected=RecommendationEvalExpected(
            must_address_topics=["title"],
            min_narrative_chars=20,
        ),
    )
    rec_report = run_recommendation_eval(cases=[recommendation_case], provider=_StubRecommendationProvider())
    assert rec_report.total_cases == 1

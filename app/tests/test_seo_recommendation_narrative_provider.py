from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
import logging
import urllib.error
import urllib.request

import pytest

from app.integrations.seo_recommendation_narrative_provider import (
    OpenAISEORecommendationNarrativeProvider,
    SEORecommendationNarrativeProviderError,
)
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun


class _FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


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
            rationale="Deterministic rationale one.",
            priority_score=70,
            priority_band="high",
            effort_bucket="LOW",
            status="open",
            created_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        ),
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
            rationale="Deterministic rationale two.",
            priority_score=92,
            priority_band="critical",
            effort_bucket="HIGH",
            status="in_progress",
            created_at=datetime(2026, 3, 20, 13, 0, tzinfo=UTC),
        ),
    ]


def _competitor_telemetry(*, raw: int = 10, excluded: int = 4) -> dict[str, object]:
    return {
        "lookback_days": 30,
        "total_runs": 3,
        "total_raw_candidate_count": raw,
        "total_included_candidate_count": max(0, raw - excluded),
        "total_excluded_candidate_count": max(0, excluded),
        "exclusion_counts_by_reason": {
            "duplicate": 1,
            "low_relevance": 1,
            "directory_or_aggregator": 1,
            "big_box_mismatch": 1,
            "existing_domain_match": 0,
            "invalid_candidate": 0,
        },
    }


def _current_tuning_values() -> dict[str, int]:
    return {
        "competitor_candidate_min_relevance_score": 35,
        "competitor_candidate_big_box_penalty": 20,
        "competitor_candidate_directory_penalty": 35,
        "competitor_candidate_local_alignment_bonus": 10,
    }


def test_openai_recommendation_narrative_provider_parses_structured_response(monkeypatch) -> None:
    captured_payload: dict[str, object] = {}

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 18
        request_body = request.data.decode("utf-8") if isinstance(request.data, bytes) else "{}"
        captured_payload.update(json.loads(request_body))
        response = {
            "model": "gpt-4.1-mini-2026-02-01",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Focus on title coverage and thin content first.",
                                "top_themes": ["metadata quality", "content depth"],
                                "sections": {
                                    "summary": "Deterministic recommendations were summarized.",
                                    "priority_rationale": "Critical content issues lead the backlog.",
                                    "next_actions": [
                                        "Address critical content pages first",
                                        "Then resolve warning metadata issues",
                                    ],
                                    "recommendation_references": ["rec-2", "unknown-id", "rec-2"],
                                    "tuning_suggestions": [
                                        {
                                            "setting": "competitor_candidate_min_relevance_score",
                                            "current_value": 35,
                                            "recommended_value": 30,
                                            "reason": "High low_relevance exclusions indicate threshold is too strict.",
                                            "linked_recommendation_ids": ["rec-2"],
                                            "confidence": "medium",
                                        }
                                    ],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=18,
    )

    output = provider.generate_narrative(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1, "in_progress": 1},
        by_category={"SEO": 1, "CONTENT": 1},
        by_severity={"WARNING": 1, "CRITICAL": 1},
        by_effort_bucket={"LOW": 1, "HIGH": 1},
        by_priority_band={"high": 1, "critical": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary=_competitor_telemetry(),
        current_tuning_values=_current_tuning_values(),
        competitor_context={
            "top_opportunities": ["Expand service coverage pages", "Improve local trust signals"],
            "competitor_summary": "Nearby competitors have stronger local page coverage.",
            "competitor_names": ["Alpha Plumbing", "Beta HVAC"],
        },
    )

    assert output.provider_name == "openai"
    assert output.model_name == "gpt-4.1-mini-2026-02-01"
    assert output.prompt_version == "seo-recommendation-narrative-v2"
    assert "Focus on title coverage" in output.narrative_text
    assert output.top_themes == ["metadata quality", "content depth"]
    assert isinstance(output.sections, dict)
    assert output.sections["recommendation_references"] == ["rec-2"]
    assert output.sections["tuning_suggestions"] == [
        {
            "setting": "competitor_candidate_min_relevance_score",
            "current_value": 35,
            "recommended_value": 30,
            "reason": "High low_relevance exclusions indicate threshold is too strict.",
            "linked_recommendation_ids": ["rec-2"],
            "confidence": "medium",
        }
    ]
    assert output.sections["status_rollup"] == {"in_progress": 1, "open": 1}
    assert captured_payload["model"] == "gpt-4.1-mini"
    assert captured_payload["response_format"]["type"] == "json_schema"
    user_prompt = captured_payload["messages"][1]["content"]
    assert "Expand service coverage pages" in user_prompt
    assert "Alpha Plumbing" in user_prompt


def test_openai_recommendation_narrative_provider_applies_next_action_diversity_dedupe(monkeypatch) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini-2026-02-01",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Focus on distinct operator actions.",
                                "top_themes": ["service clarity", "local SEO"],
                                "sections": {
                                    "summary": "Narrative summary.",
                                    "priority_rationale": "Distinct actions improve execution quality.",
                                    "next_actions": [
                                        "Improve service pages.",
                                        "Improve service pages for nearby competitors and local emergency intent coverage.",
                                        "Improve service pages",
                                        "Add trust badges and testimonials to service pages.",
                                    ],
                                    "recommendation_references": ["rec-2", "rec-1", "rec-2"],
                                    "tuning_suggestions": [],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_narrative(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1, "in_progress": 1},
        by_category={"SEO": 1, "CONTENT": 1},
        by_severity={"WARNING": 1, "CRITICAL": 1},
        by_effort_bucket={"LOW": 1, "HIGH": 1},
        by_priority_band={"high": 1, "critical": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary=_competitor_telemetry(),
        current_tuning_values=_current_tuning_values(),
    )

    assert output.sections is not None
    assert output.sections["next_actions"] == [
        "Improve service pages for nearby competitors and local emergency intent coverage.",
        "Add trust badges and testimonials to service pages.",
    ]
    assert output.sections["recommendation_references"] == ["rec-2", "rec-1"]


def test_openai_recommendation_narrative_provider_timeout_is_normalized(monkeypatch) -> None:
    def _timeout_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise TimeoutError("timeout")

    monkeypatch.setattr(urllib.request, "urlopen", _timeout_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(),
            current_tuning_values=_current_tuning_values(),
        )

    assert exc_info.value.code == "provider_request"
    assert exc_info.value.normalized_failure_category == "remote_timeout"
    assert exc_info.value.normalized_failure_reason == "request_too_large_or_complex"
    assert exc_info.value.normalized_failure_source == "remote_provider"
    assert exc_info.value.normalized_retryable is False
    assert exc_info.value.attempt_count == 1


def test_openai_recommendation_narrative_provider_auth_error_is_normalized(monkeypatch) -> None:
    def _unauthorized_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid_api_key"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(),
            current_tuning_values=_current_tuning_values(),
        )

    assert exc_info.value.code == "provider_auth_config"
    assert exc_info.value.normalized_failure_category == "configuration_invalid"
    assert exc_info.value.normalized_failure_reason == "provider_auth_or_configuration_invalid"
    assert exc_info.value.normalized_failure_source == "local_configuration"
    assert exc_info.value.normalized_retryable is False
    assert exc_info.value.attempt_count == 1


def test_recommendation_context_budget_keeps_required_and_aggressively_trims_optional_context() -> None:
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )
    competitor_context = {
        "top_opportunities": ["A" * 12000],
        "competitor_summary": "B" * 12000,
        "competitor_names": ["C" * 4000],
    }
    competitor_telemetry_summary = {
        "total_raw_candidate_count": 200,
        "total_excluded_candidate_count": 100,
        "dense_payload": "D" * 24000,
    }

    (
        budgeted_telemetry,
        budgeted_tuning,
        budgeted_competitor_context,
        budget_result,
    ) = provider._apply_recommendation_context_budget(
        competitor_telemetry_summary=competitor_telemetry_summary,
        current_tuning_values=_current_tuning_values(),
        competitor_context=competitor_context,
    )

    # Required tuning block must always remain available.
    assert budgeted_tuning == _current_tuning_values()
    # Recommendation adapter policy: once any trim occurs, enrichment context is removed entirely.
    assert budget_result["aggressive_trim_applied"] is True
    assert budgeted_telemetry == {}
    assert budgeted_competitor_context is None
    dropped_blocks = budget_result.get("dropped_optional_blocks") or []
    assert dropped_blocks
    assert dropped_blocks[0] == "competitor_context"
    assert isinstance(budget_result.get("trimming_pass_count"), int)
    assert isinstance(budget_result.get("trimmed_bytes"), int)


def test_recommendation_budget_logs_submission_telemetry(caplog, monkeypatch) -> None:
    caplog.set_level(logging.INFO, logger="app.integrations.seo_recommendation_narrative_provider")

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini-2026-02-01",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Budgeted narrative.",
                                "top_themes": ["metadata quality"],
                                "sections": {
                                    "summary": "Budgeted.",
                                    "priority_rationale": "Budgeted rationale.",
                                    "next_actions": ["Complete highest priority recommendation."],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    provider.generate_narrative(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1, "in_progress": 1},
        by_category={"SEO": 1, "CONTENT": 1},
        by_severity={"WARNING": 1, "CRITICAL": 1},
        by_effort_bucket={"LOW": 1, "HIGH": 1},
        by_priority_band={"high": 1, "critical": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary={
            "total_raw_candidate_count": 300,
            "total_excluded_candidate_count": 120,
            "dense_payload": "D" * 32000,
        },
        current_tuning_values=_current_tuning_values(),
        competitor_context={
            "top_opportunities": ["A" * 14000],
            "competitor_summary": "B" * 14000,
            "competitor_names": ["C" * 5000],
        },
    )

    budget_events = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "recommendation_narrative_request_budget"
    ]
    assert budget_events
    latest_budget_event = budget_events[-1]
    assert latest_budget_event.get("feature_area") == "recommendation_ai"
    assert latest_budget_event.get("budget_outcome") == "provider_submission"
    assert isinstance(latest_budget_event.get("trimmed_bytes"), int)
    assert isinstance(latest_budget_event.get("trimming_pass_count"), int)
    assert latest_budget_event.get("aggressive_trim_applied") is True
    dropped_optional = latest_budget_event.get("dropped_optional_blocks")
    assert isinstance(dropped_optional, list)
    assert "competitor_context" in dropped_optional


def test_openai_recommendation_narrative_provider_malformed_content_is_normalized(monkeypatch) -> None:
    def _invalid_content_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [{"message": {"content": "not-json"}}],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _invalid_content_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(),
            current_tuning_values=_current_tuning_values(),
        )

    assert exc_info.value.code == "invalid_output"


def test_openai_recommendation_narrative_provider_parses_wrapped_json_content(monkeypatch) -> None:
    wrapped_content = (
        "Here is the narrative payload:\n"
        "```json\n"
        + json.dumps(
            {
                "narrative_text": "Wrapped payload narrative.",
                "top_themes": ["theme one", "theme two"],
                "sections": {
                    "summary": "Wrapped summary",
                    "priority_rationale": "Wrapped rationale",
                    "next_actions": ["Action one"],
                    "recommendation_references": ["rec-1"],
                    "tuning_suggestions": [],
                },
            },
            ensure_ascii=True,
        )
        + "\n```\n"
        "Thanks."
    )

    def _wrapped_content_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-5.1",
            "choices": [{"message": {"content": wrapped_content}}],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _wrapped_content_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-5.1",
    )
    output = provider.generate_narrative(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1},
        by_category={"SEO": 1},
        by_severity={"WARNING": 1},
        by_effort_bucket={"LOW": 1},
        by_priority_band={"high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary=_competitor_telemetry(),
        current_tuning_values=_current_tuning_values(),
    )
    assert output.narrative_text == "Wrapped payload narrative."
    assert output.top_themes == ["theme one", "theme two"]


def test_openai_recommendation_narrative_provider_salvages_partial_tuning_suggestions(monkeypatch) -> None:
    def _partial_schema_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-5.1",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Narrative with partial suggestion recovery.",
                                "top_themes": ["theme"],
                                "sections": {
                                    "summary": "Summary",
                                    "priority_rationale": "Rationale",
                                    "next_actions": ["Action one"],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [
                                        {
                                            "setting": "competitor_candidate_directory_penalty",
                                            "current_value": 35,
                                            "recommended_value": 30,
                                            "reason": "Directory exclusions are elevated.",
                                            "linked_recommendation_ids": ["rec-1"],
                                            "confidence": "high",
                                        },
                                        {
                                            "setting": "competitor_candidate_directory_penalty",
                                            "current_value": 35,
                                            "recommended_value": 30,
                                            "reason": "Invalid because references are missing.",
                                            "linked_recommendation_ids": [],
                                            "confidence": "high",
                                        },
                                    ],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _partial_schema_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-5.1",
    )
    output = provider.generate_narrative(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1},
        by_category={"SEO": 1},
        by_severity={"WARNING": 1},
        by_effort_bucket={"LOW": 1},
        by_priority_band={"high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary=_competitor_telemetry(raw=12, excluded=4),
        current_tuning_values=_current_tuning_values(),
    )
    assert output.sections is not None
    assert len(output.sections["tuning_suggestions"]) == 1
    assert output.sections["tuning_suggestions"][0]["setting"] == "competitor_candidate_directory_penalty"


def test_openai_recommendation_narrative_provider_truncated_json_is_invalid_output(monkeypatch) -> None:
    def _truncated_content_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-5.1",
            "choices": [{"message": {"content": '{"narrative_text":"broken"'}}],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _truncated_content_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-5.1",
    )

    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(),
            current_tuning_values=_current_tuning_values(),
        )

    assert exc_info.value.code == "invalid_output"


def test_openai_recommendation_narrative_provider_rejects_invalid_tuning_suggestion_references(monkeypatch) -> None:
    def _invalid_suggestions_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Narrative",
                                "top_themes": ["theme"],
                                "sections": {
                                    "summary": "Summary",
                                    "priority_rationale": "Rationale",
                                    "next_actions": ["Action one"],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [
                                        {
                                            "setting": "competitor_candidate_directory_penalty",
                                            "current_value": 35,
                                            "recommended_value": 30,
                                            "reason": "Directory exclusions are elevated.",
                                            "linked_recommendation_ids": ["unknown-rec-id"],
                                            "confidence": "high",
                                        }
                                    ],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _invalid_suggestions_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(),
            current_tuning_values=_current_tuning_values(),
        )

    assert exc_info.value.code == "schema_validation"


def test_openai_recommendation_narrative_provider_rejects_out_of_bounds_tuning_values(monkeypatch) -> None:
    def _out_of_bounds_suggestions_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Narrative",
                                "top_themes": ["theme"],
                                "sections": {
                                    "summary": "Summary",
                                    "priority_rationale": "Rationale",
                                    "next_actions": ["Action one"],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [
                                        {
                                            "setting": "competitor_candidate_directory_penalty",
                                            "current_value": 35,
                                            "recommended_value": 500,
                                            "reason": "Directory exclusions are elevated.",
                                            "linked_recommendation_ids": ["rec-1"],
                                            "confidence": "high",
                                        }
                                    ],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _out_of_bounds_suggestions_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEORecommendationNarrativeProviderError) as exc_info:
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(),
            current_tuning_values=_current_tuning_values(),
        )

    assert exc_info.value.code == "schema_validation"


def test_openai_recommendation_narrative_provider_suppresses_tuning_suggestions_for_balanced_telemetry(
    monkeypatch,
) -> None:
    def _balanced_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Narrative",
                                "top_themes": ["theme"],
                                "sections": {
                                    "summary": "Summary",
                                    "priority_rationale": "Rationale",
                                    "next_actions": ["Action one"],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [
                                        {
                                            "setting": "competitor_candidate_big_box_penalty",
                                            "current_value": 20,
                                            "recommended_value": 25,
                                            "reason": "Potential local mismatch.",
                                            "linked_recommendation_ids": ["rec-1"],
                                            "confidence": "low",
                                        }
                                    ],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _balanced_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_narrative(
        run=_run(),
        recommendations=_recommendations(),
        by_status={"open": 1},
        by_category={"SEO": 1},
        by_severity={"WARNING": 1},
        by_effort_bucket={"LOW": 1},
        by_priority_band={"high": 1},
        backlog=_recommendations(),
        competitor_telemetry_summary=_competitor_telemetry(raw=10, excluded=0),
        current_tuning_values=_current_tuning_values(),
    )

    assert output.sections is not None
    assert output.sections["tuning_suggestions"] == []


def test_openai_recommendation_narrative_provider_logs_prompt_resolution_without_raw_prompt_text(
    monkeypatch,
    caplog,
) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Narrative",
                                "top_themes": ["theme"],
                                "sections": {
                                    "summary": "Summary",
                                    "priority_rationale": "Rationale",
                                    "next_actions": ["Action one"],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        prompt_text_recommendations="SENSITIVE_RECOMMENDATIONS_PROMPT_TEXT",
        prompt_source="split",
        prompt_config_key="ai_prompt_text_recommendations",
        legacy_config_used=False,
    )

    with caplog.at_level(logging.INFO):
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(raw=10, excluded=4),
            current_tuning_values=_current_tuning_values(),
        )

    assert "ai_prompt_resolution pipeline=recommendations" in caplog.text
    assert "prompt_source=split" in caplog.text
    assert "legacy_config_used=False" in caplog.text
    assert "SENSITIVE_RECOMMENDATIONS_PROMPT_TEXT" not in caplog.text
    assert "ai_prompt_legacy_fallback pipeline=recommendations" not in caplog.text


def test_openai_recommendation_narrative_provider_warns_on_legacy_fallback_without_raw_prompt_text(
    monkeypatch,
    caplog,
) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "narrative_text": "Narrative",
                                "top_themes": ["theme"],
                                "sections": {
                                    "summary": "Summary",
                                    "priority_rationale": "Rationale",
                                    "next_actions": ["Action one"],
                                    "recommendation_references": ["rec-1"],
                                    "tuning_suggestions": [],
                                },
                            }
                        )
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEORecommendationNarrativeProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        prompt_text_recommendations="SENSITIVE_LEGACY_RECOMMENDATION_PROMPT_TEXT",
        prompt_source="legacy_fallback",
        prompt_config_key="ai_prompt_text_recommendations",
        legacy_config_used=True,
    )

    with caplog.at_level(logging.WARNING):
        provider.generate_narrative(
            run=_run(),
            recommendations=_recommendations(),
            by_status={"open": 1},
            by_category={"SEO": 1},
            by_severity={"WARNING": 1},
            by_effort_bucket={"LOW": 1},
            by_priority_band={"high": 1},
            backlog=_recommendations(),
            competitor_telemetry_summary=_competitor_telemetry(raw=10, excluded=4),
            current_tuning_values=_current_tuning_values(),
        )

    assert "ai_prompt_legacy_fallback pipeline=recommendations" in caplog.text
    assert "prompt_source=legacy_fallback" in caplog.text
    assert "SENSITIVE_LEGACY_RECOMMENDATION_PROMPT_TEXT" not in caplog.text

from __future__ import annotations

from types import SimpleNamespace

from app.services.ai_response_contract_evaluator import (
    evaluate_competitor_generation_response,
    evaluate_migration_artifact_response,
    evaluate_recommendation_narrative_response,
    summarize_competitor_response_contract,
    summarize_migration_response_contract,
    summarize_recommendation_response_contract,
)


def test_migration_contract_accepts_complete_package() -> None:
    evaluation = evaluate_migration_artifact_response(
        strategy_summary="Structured migration strategy for service-first website replacement.",
        generated_files=[
            {
                "path": "index.html",
                "content": (
                    "<html><body><h1>TNM Fire Protection</h1><p>Trusted fire suppression installation, "
                    "inspection, monitoring, and service with licensed technicians and local response "
                    "coverage across commercial and residential properties.</p></body></html>"
                ),
            },
            {
                "path": "styles.css",
                "content": (
                    "body { font-family: sans-serif; color: #111; } .hero { margin: 2rem auto; max-width: 72rem; } "
                    ".cta { background: #b70; color: #fff; padding: 1rem; border-radius: 0.5rem; }"
                ),
            },
        ],
        raw_generated_file_count=2,
        page_map_count=1,
    )
    assert evaluation.status == "accepted"
    assert evaluation.reasons == ()
    assert evaluation.valid_item_count == 2


def test_migration_contract_marks_partial_salvage_when_files_dropped() -> None:
    evaluation = evaluate_migration_artifact_response(
        strategy_summary="Migration strategy with partial salvage.",
        generated_files=[
            {"path": "index.html", "content": "<html><body><h1>Recovered</h1></body></html>"},
        ],
        raw_generated_file_count=3,
        page_map_count=0,
    )
    assert evaluation.status == "salvaged"
    assert evaluation.dropped_item_count == 2
    assert "partial_artifact_only" in evaluation.warnings


def test_migration_contract_rejects_empty_package() -> None:
    evaluation = evaluate_migration_artifact_response(
        strategy_summary=None,
        generated_files=[],
        raw_generated_file_count=0,
        page_map_count=0,
    )
    assert evaluation.status == "rejected"
    assert "empty_artifact_package" in evaluation.reasons
    assert "missing_required_artifact_files" in evaluation.reasons


def test_competitor_contract_accepts_valid_candidates() -> None:
    rows = [
        SimpleNamespace(
            suggested_name="Front Range Fire",
            suggested_domain="fr-fire.example",
            summary="Strong local overlap and commercial service intent match.",
            why_competitor="Competes for local transactional fire safety queries.",
            evidence="Similar services and location signals.",
            confidence_score=0.82,
        ),
        SimpleNamespace(
            suggested_name="Mile High Fire",
            suggested_domain="milehigh-fire.example",
            summary="Nearby competitor with overlapping inspection and suppression offerings.",
            why_competitor="Comparable services and local market overlap.",
            evidence="Service + location alignment.",
            confidence_score=0.76,
        ),
    ]
    evaluation = evaluate_competitor_generation_response(
        raw_candidate_count=2,
        persisted_draft_rows=rows,
        removed_by_deduplication_count=0,
        rejected_candidate_count=0,
    )
    assert evaluation.status == "accepted"
    assert evaluation.reasons == ()


def test_competitor_contract_salvages_partial_output() -> None:
    rows = [
        SimpleNamespace(
            suggested_name="Front Range Fire",
            suggested_domain="fr-fire.example",
            summary="Solid overlap.",
            why_competitor="Competes in same local market.",
            evidence="Shared service coverage.",
            confidence_score=0.7,
        )
    ]
    evaluation = evaluate_competitor_generation_response(
        raw_candidate_count=3,
        persisted_draft_rows=rows,
        removed_by_deduplication_count=1,
        rejected_candidate_count=2,
    )
    assert evaluation.status == "salvaged"
    assert evaluation.dropped_item_count == 2


def test_competitor_contract_rejects_unusable_output() -> None:
    evaluation = evaluate_competitor_generation_response(
        raw_candidate_count=0,
        persisted_draft_rows=[],
        removed_by_deduplication_count=0,
        rejected_candidate_count=0,
    )
    assert evaluation.status == "rejected"
    assert "empty_candidate_list" in evaluation.reasons


def test_recommendation_contract_accepts_actionable_output() -> None:
    evaluation = evaluate_recommendation_narrative_response(
        narrative_text="Prioritize emergency service page updates and reinforce local trust signals.",
        top_themes=["Trust", "Visibility"],
        raw_sections={
            "summary": "Improve emergency service conversion pages.",
            "next_actions": [
                "Update emergency service headers and service descriptions for local intent.",
                "Add testimonial and certification proof to core conversion pages.",
            ],
            "recommendation_references": ["rec-1", "rec-2"],
        },
        normalized_sections={
            "summary": "Improve emergency service conversion pages.",
            "priority_rationale": "Improves trust and conversion for local high-intent queries.",
            "next_actions": [
                "Update emergency service headers and service descriptions for local intent.",
                "Add testimonial and certification proof to core conversion pages.",
            ],
            "recommendation_references": ["rec-1", "rec-2"],
        },
        expected_recommendation_count=2,
    )
    assert evaluation.status == "accepted"
    assert evaluation.reasons == ()


def test_recommendation_contract_salvages_partial_actions() -> None:
    evaluation = evaluate_recommendation_narrative_response(
        narrative_text="Prioritize homepage updates and trust proof improvements.",
        top_themes=["Trust"],
        raw_sections={
            "summary": "Improve homepage clarity.",
            "next_actions": ["Update homepage service copy.", "Not usable", " "],
            "recommendation_references": ["rec-1"],
        },
        normalized_sections={
            "summary": "Improve homepage clarity.",
            "priority_rationale": "Improves conversion and trust.",
            "next_actions": ["Update homepage service copy."],
            "recommendation_references": ["rec-1"],
        },
        expected_recommendation_count=1,
    )
    assert evaluation.status == "salvaged"
    assert evaluation.dropped_item_count == 2


def test_recommendation_contract_rejects_generic_filler_only_output() -> None:
    evaluation = evaluate_recommendation_narrative_response(
        narrative_text=(
            "Improve SEO by following best practices and enhance visibility with overall strategy "
            "to optimize performance."
        ),
        top_themes=[],
        raw_sections={"summary": None, "next_actions": [], "recommendation_references": []},
        normalized_sections={
            "summary": None,
            "priority_rationale": None,
            "next_actions": [],
            "recommendation_references": [],
        },
        expected_recommendation_count=2,
    )
    assert evaluation.status == "rejected"
    assert "generic_content_heavy" in evaluation.reasons


def test_competitor_operator_summary_uses_safe_warning_message() -> None:
    rows = [
        SimpleNamespace(
            suggested_name="Single competitor",
            suggested_domain="single-competitor.example",
            summary="Valid summary text with overlap.",
            why_competitor="Competes in same area.",
            evidence="Service overlap evidence.",
            confidence_score=0.73,
        )
    ]
    evaluation = evaluate_competitor_generation_response(
        raw_candidate_count=3,
        persisted_draft_rows=rows,
        removed_by_deduplication_count=0,
        rejected_candidate_count=2,
    )
    summary = summarize_competitor_response_contract(evaluation=evaluation)
    assert summary is not None
    assert summary.status == "salvaged"
    assert summary.summary == "Limited number of strong competitors identified."
    assert summary.retryable is True
    assert set(summary.to_dict().keys()) == {"status", "summary", "retryable"}


def test_recommendation_operator_summary_uses_safe_rejection_message() -> None:
    evaluation = evaluate_recommendation_narrative_response(
        narrative_text=(
            "Improve SEO by following best practices and enhance visibility with overall strategy "
            "to optimize performance."
        ),
        top_themes=[],
        raw_sections={"summary": None, "next_actions": [], "recommendation_references": []},
        normalized_sections={
            "summary": None,
            "priority_rationale": None,
            "next_actions": [],
            "recommendation_references": [],
        },
        expected_recommendation_count=2,
    )
    summary = summarize_recommendation_response_contract(evaluation=evaluation)
    assert summary is not None
    assert summary.status == "rejected"
    assert summary.summary == "Recommendations were too generic to be useful."
    assert summary.retryable is True


def test_migration_operator_summary_maps_partial_artifact_warning() -> None:
    evaluation = evaluate_migration_artifact_response(
        strategy_summary="Fallback draft content.",
        generated_files=[{"path": "index.html", "content": "<html><body><p>content</p></body></html>"}],
        raw_generated_file_count=2,
        page_map_count=0,
    )
    summary = summarize_migration_response_contract(evaluation=evaluation)
    assert summary is not None
    assert summary.status == "salvaged"
    assert summary.summary == "Partial site draft generated."

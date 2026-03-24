from __future__ import annotations

from app.services.seo_recommendation_diversity import (
    normalize_recommendation_narrative_sections,
    normalize_recommendation_next_actions,
)


def test_normalize_recommendation_next_actions_reduces_near_duplicates_and_keeps_specific_variant() -> None:
    actions = [
        "Improve service pages",
        "Improve service pages for nearby competitors and local emergency intent coverage.",
        "Improve service pages.",
        "Improve service pages for nearby competitors and local emergency intent coverage.",
    ]

    normalized = normalize_recommendation_next_actions(
        actions,
        limit=10,
        max_length=220,
    )

    assert len(normalized) == 1
    assert normalized[0] == "Improve service pages for nearby competitors and local emergency intent coverage."


def test_normalize_recommendation_next_actions_preserves_distinct_actions() -> None:
    actions = [
        "Add testimonial proof to the service hero block.",
        "Clarify emergency service coverage on key pages.",
        "Expand local service-area page content for top cities.",
        "Improve contact CTA placement on mobile.",
    ]

    normalized = normalize_recommendation_next_actions(
        actions,
        limit=10,
        max_length=220,
    )

    assert normalized == actions


def test_normalize_recommendation_next_actions_handles_sparse_input_safely() -> None:
    assert normalize_recommendation_next_actions(None, limit=10, max_length=220) == []
    assert normalize_recommendation_next_actions([], limit=10, max_length=220) == []
    assert normalize_recommendation_next_actions(["   ", ""], limit=10, max_length=220) == []


def test_normalize_recommendation_narrative_sections_filters_invalid_references_and_dedupes_actions() -> None:
    sections = {
        "summary": "Summary",
        "next_actions": [
            "Improve service pages.",
            "Improve service pages for nearby competitors and local emergency intent coverage.",
            "Improve service pages",
        ],
        "recommendation_references": ["rec-2", "rec-1", "rec-2", "unknown"],
    }

    normalized = normalize_recommendation_narrative_sections(
        sections,
        next_action_limit=10,
        next_action_max_length=220,
        recommendation_reference_limit=25,
    )

    assert normalized is not None
    assert normalized["next_actions"] == [
        "Improve service pages for nearby competitors and local emergency intent coverage.",
    ]
    assert normalized["recommendation_references"] == ["rec-2", "rec-1", "unknown"]

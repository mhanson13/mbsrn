from __future__ import annotations

import json

from app.services.competitors.normalizer import normalize_competitor_response


def test_normalize_competitor_response_valid_json() -> None:
    raw = json.dumps(
        {
            "competitors": [
                {
                    "name": "  Alpha Plumbing  ",
                    "domain": " alpha.example ",
                    "location": " Denver, CO ",
                    "strengths": [" Fast response "],
                    "weaknesses": ["Limited weekend support"],
                    "opportunities": ["Expand emergency service"],
                    "threats": ["Large regional chain"],
                    "differentiators": ["Family owned"],
                    "visibility_score": 4,
                    "relevance_score": 5,
                    "summary": "Strong local visibility",
                }
            ],
            "top_opportunities": [" Improve local pages "],
            "summary": " Competitive set is active ",
        }
    )

    normalized = normalize_competitor_response(raw)

    assert normalized["top_opportunities"] == ["Improve local pages"]
    assert normalized["summary"] == "Competitive set is active"
    competitor = normalized["competitors"][0]
    assert competitor["name"] == "Alpha Plumbing"
    assert competitor["domain"] == "alpha.example"
    assert competitor["location"] == "Denver, CO"
    assert competitor["strengths"] == ["Fast response"]
    assert competitor["visibility_score"] == 4
    assert competitor["relevance_score"] == 5


def test_normalize_competitor_response_fills_missing_fields_and_removes_empty_competitor() -> None:
    raw = json.dumps(
        {
            "competitors": [
                {},
                {"name": "Beta Electric"},
            ]
        }
    )

    normalized = normalize_competitor_response(raw)

    assert len(normalized["competitors"]) == 1
    competitor = normalized["competitors"][0]
    assert competitor["name"] == "Beta Electric"
    assert competitor["domain"] == ""
    assert competitor["location"] == ""
    assert competitor["strengths"] == []
    assert competitor["weaknesses"] == []
    assert competitor["opportunities"] == []
    assert competitor["threats"] == []
    assert competitor["differentiators"] == []
    assert competitor["visibility_score"] == 3
    assert competitor["relevance_score"] == 3
    assert competitor["summary"] == ""


def test_normalize_competitor_response_bad_json_returns_fallback() -> None:
    normalized = normalize_competitor_response("not-json")

    assert normalized == {
        "competitors": [],
        "top_opportunities": [
            "Improve website clarity",
            "Add trust signals",
            "Clarify services",
        ],
        "summary": "Competitor analysis unavailable, using fallback insights.",
    }


def test_normalize_competitor_response_clamps_scores() -> None:
    raw = json.dumps(
        {
            "competitors": [
                {"name": "High", "visibility_score": 999, "relevance_score": 0},
                {"name": "Low", "visibility_score": -100, "relevance_score": 7},
            ]
        }
    )

    normalized = normalize_competitor_response(raw)

    high = normalized["competitors"][0]
    low = normalized["competitors"][1]
    assert high["visibility_score"] == 5
    assert high["relevance_score"] == 1
    assert low["visibility_score"] == 1
    assert low["relevance_score"] == 5


def test_normalize_competitor_response_deduplicates_by_name() -> None:
    raw = json.dumps(
        {
            "competitors": [
                {"name": "Gamma HVAC", "domain": "gamma.example"},
                {"name": " gamma hvac ", "domain": "gamma-duplicate.example"},
                {"name": "Delta HVAC", "domain": "delta.example"},
            ]
        }
    )

    normalized = normalize_competitor_response(raw)
    names = [item["name"] for item in normalized["competitors"]]
    domains = [item["domain"] for item in normalized["competitors"]]

    assert names == ["Gamma HVAC", "Delta HVAC"]
    assert domains == ["gamma.example", "delta.example"]

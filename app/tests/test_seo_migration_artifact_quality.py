from __future__ import annotations

from app.services.seo_migration_artifact_quality import evaluate_migration_artifact_quality


def _long_html(body: str) -> str:
    return (
        "<html><head><title>Draft</title></head><body>"
        + body
        + "<p>"
        + ("Detailed local business content. " * 20)
        + "</p>"
        + "</body></html>"
    )


def test_evaluate_migration_artifact_quality_flags_placeholder_content() -> None:
    evaluation = evaluate_migration_artifact_quality(
        {
            "generated_files": [
                {
                    "path": "index.html",
                    "content": _long_html(
                        "<h1>TNM Fire Protection</h1><p>Lorem ipsum dolor sit amet.</p><p>Your business here.</p>"
                    ),
                    "media_type": "text/html",
                }
            ],
            "business_name": "TNM Fire Protection",
            "location_hints": ["Longmont, CO"],
            "expected_service_terms": ["inspection", "testing"],
        }
    )

    assert evaluation["quality_status"] == "low"
    signals = evaluation["signals"]
    assert isinstance(signals, dict)
    assert signals.get("placeholder_detected") is True
    issues = evaluation["issues"]
    assert isinstance(issues, list)
    assert any(isinstance(item, dict) and item.get("type") == "placeholder_content" for item in issues)


def test_evaluate_migration_artifact_quality_flags_missing_sections() -> None:
    evaluation = evaluate_migration_artifact_quality(
        {
            "generated_files": [
                {
                    "path": "index.html",
                    "content": _long_html(
                        "<h1>TNM Fire Protection</h1><p>Serving Longmont, CO with reliable fire safety improvements.</p>"
                    ),
                    "media_type": "text/html",
                }
            ],
            "business_name": "TNM Fire Protection",
            "location_hints": ["Longmont, CO"],
            "expected_service_terms": ["installation", "inspection"],
        }
    )

    signals = evaluation["signals"]
    assert isinstance(signals, dict)
    missing_sections = signals.get("missing_sections")
    assert isinstance(missing_sections, list)
    assert "services" in missing_sections
    assert "contact" in missing_sections
    issues = evaluation["issues"]
    assert isinstance(issues, list)
    assert any(
        isinstance(item, dict)
        and item.get("type") == "content_completeness"
        and "Missing expected sections" in str(item.get("description"))
        for item in issues
    )


def test_evaluate_migration_artifact_quality_marks_well_formed_artifact_high() -> None:
    evaluation = evaluate_migration_artifact_quality(
        {
            "generated_files": [
                {
                    "path": "index.html",
                    "content": _long_html(
                        "<h1>TNM Fire Protection</h1>"
                        "<h2>Fire Protection Services</h2>"
                        "<p>Inspection, testing, and repair services in Longmont, CO.</p>"
                        "<h2>Contact</h2><p>Call our team for a quote today.</p>"
                    ),
                    "media_type": "text/html",
                },
                {
                    "path": "contact.html",
                    "content": _long_html(
                        "<h1>Contact TNM Fire Protection</h1><p>Phone, email, and local service details for Longmont.</p>"
                    ),
                    "media_type": "text/html",
                },
            ],
            "business_name": "TNM Fire Protection",
            "location_hints": ["Longmont, CO"],
            "expected_service_terms": ["inspection", "testing", "repair"],
        }
    )

    assert evaluation["quality_status"] == "high"
    assert isinstance(evaluation.get("operator_summary"), str)
    signals = evaluation["signals"]
    assert isinstance(signals, dict)
    assert signals.get("has_business_name") is True
    assert signals.get("has_location") is True
    assert signals.get("placeholder_detected") is False

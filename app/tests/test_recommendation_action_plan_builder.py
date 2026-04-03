from app.services.recommendation_action_plan_builder import build_action_plan


def test_build_action_plan_generates_title_step_with_before_after() -> None:
    plan = build_action_plan(
        {
            "title": "Improve flooring service page title coverage",
            "rationale": "Missing title tag issues were detected on key pages.",
            "recommendation_target_context": "service_pages",
            "recommendation_target_page_hints": ["/services/flooring"],
            "recommendation_target_content_types": [
                {
                    "type_key": "meta_title",
                    "label": "Meta title",
                    "source_type": "audit_signal",
                    "targeting_strength": "high",
                }
            ],
            "evidence_json": {"current_meta_title": "Home"},
        }
    )

    assert plan["action_steps"]
    first_step = plan["action_steps"][0]
    assert first_step["step_number"] == 1
    assert first_step["title"] == "Update page title"
    assert first_step["field"] == "title"
    assert first_step["target_identifier"] == "/services/flooring"
    assert first_step["before_example"] == "Home"
    assert isinstance(first_step["after_example"], str)
    assert " in " in first_step["after_example"].lower()


def test_build_action_plan_generates_meta_description_template() -> None:
    plan = build_action_plan(
        {
            "title": "Expand local plumbing metadata",
            "rationale": "Missing meta description findings were detected.",
            "recommendation_target_context": "location_pages",
            "recommendation_target_content_types": [
                {
                    "type_key": "meta_description",
                    "label": "Meta description",
                    "source_type": "audit_signal",
                    "targeting_strength": "high",
                }
            ],
        }
    )

    assert plan["action_steps"]
    step = plan["action_steps"][0]
    assert step["title"] == "Rewrite meta description"
    assert step["field"] == "meta_description"
    assert step["before_example"] is None
    assert isinstance(step["after_example"], str)
    assert "call today for a quote" in step["after_example"].lower()


def test_build_action_plan_returns_empty_steps_for_missing_targets() -> None:
    plan = build_action_plan(
        {
            "title": "General housekeeping recommendation",
            "rationale": "Operator review is required.",
            "recommendation_target_context": "general",
            "recommendation_target_content_types": [],
        }
    )

    assert plan == {"action_steps": []}


def test_build_action_plan_keeps_multiple_targets_ordered() -> None:
    plan = build_action_plan(
        {
            "title": "Fix missing headings and linking",
            "rationale": "Missing_h1 and weak_internal_links findings are present.",
            "recommendation_target_context": "service_pages",
            "recommendation_target_content_types": [
                {
                    "type_key": "heading_h1",
                    "label": "Main heading",
                    "source_type": "audit_signal",
                    "targeting_strength": "high",
                },
                {
                    "type_key": "internal_links",
                    "label": "Internal links",
                    "source_type": "audit_signal",
                    "targeting_strength": "medium",
                },
            ],
        }
    )

    step_numbers = [step["step_number"] for step in plan["action_steps"]]
    titles = [step["title"] for step in plan["action_steps"]]
    assert step_numbers == [1, 2]
    assert titles == ["Improve main heading clarity", "Add internal links"]

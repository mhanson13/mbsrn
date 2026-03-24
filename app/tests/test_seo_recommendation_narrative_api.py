from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_recommendation_narrative_provider,
    get_tenant_context,
)
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.integrations.seo_recommendation_narrative_provider import SEORecommendationNarrativeProviderError
from app.integrations.seo_summary_provider import (
    MockSEORecommendationNarrativeProvider,
    SEORecommendationNarrativeOutput,
    SEORecommendationNarrativeProvider,
)
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.business import Business
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent


NARRATIVE_RESPONSE_KEYS = {
    "id",
    "business_id",
    "site_id",
    "recommendation_run_id",
    "version",
    "status",
    "narrative_text",
    "top_themes_json",
    "sections_json",
    "competitor_influence",
    "signal_summary",
    "action_summary",
    "provider_name",
    "model_name",
    "prompt_version",
    "error_message",
    "created_by_principal_id",
    "created_at",
    "updated_at",
}


class _FailingRecommendationNarrativeProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("provider unavailable")


class _StructuredOutputFailingNarrativeProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003, ANN201
        raise SEORecommendationNarrativeProviderError(
            code="schema_validation",
            safe_message="Recommendation narrative returned invalid structured output.",
            provider_name="openai",
            model_name="gpt-4o-mini",
            prompt_version="seo-recommendation-narrative-v2",
            raw_output='{"bad":"payload"}',
        )


class _CapturingRecommendationNarrativeProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_narrative(
        self,
        *,
        run,
        recommendations,
        by_status,
        by_category,
        by_severity,
        by_effort_bucket,
        by_priority_band,
        backlog,
        competitor_telemetry_summary,
        current_tuning_values,
        competitor_context=None,
    ) -> SEORecommendationNarrativeOutput:
        self.calls.append(
            {
                "run_id": run.id,
                "recommendation_count": len(recommendations),
                "by_status": dict(by_status),
                "by_category": dict(by_category),
                "by_severity": dict(by_severity),
                "by_effort_bucket": dict(by_effort_bucket),
                "by_priority_band": dict(by_priority_band),
                "backlog_count": len(backlog),
                "backlog_rule_keys": [item.rule_key for item in backlog],
                "competitor_telemetry_summary": dict(competitor_telemetry_summary),
                "current_tuning_values": dict(current_tuning_values),
                "competitor_context": dict(competitor_context or {}),
            }
        )
        return SEORecommendationNarrativeOutput(
            narrative_text=f"grounded run={run.id} backlog={len(backlog)}",
            top_themes=["theme_a", "theme_b"],
            sections={
                "status": dict(by_status),
                "priority_band": dict(by_priority_band),
                "tuning_suggestions": [],
            },
            provider_name="capturing-test-provider",
            model_name="capturing-test-model",
            prompt_version="seo-recommendation-narrative-v2",
        )


class _RichActionSummaryRecommendationNarrativeProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return SEORecommendationNarrativeOutput(
            narrative_text=(
                "Prioritize emergency service coverage updates and local trust proof improvements "
                "to recover local high-intent visibility."
            ),
            top_themes=[
                "Emergency service pages are weaker than nearby competitors.",
                "Local trust proof is less visible than competitors.",
                "Critical content gaps remain open.",
            ],
            sections={
                "summary": "Expand emergency service pages and strengthen local trust proof visibility.",
                "priority_rationale": "This addresses the strongest local conversion and visibility gaps first.",
                "next_actions": [
                    "Publish emergency service page updates for top service categories.",
                    "Add trust badges and testimonial proof to priority pages.",
                ],
                "recommendation_references": ["rec-2", "rec-1"],
            },
            provider_name="rich-test-provider",
            model_name="rich-test-model",
            prompt_version="seo-recommendation-narrative-v2",
        )


class _SparseActionSummaryRecommendationNarrativeProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return SEORecommendationNarrativeOutput(
            narrative_text="   ",
            top_themes=[],
            sections={
                "summary": "  ",
                "priority_rationale": None,
                "next_actions": "not-a-list",
                "recommendation_references": [None, ""],
            },
            provider_name="sparse-test-provider",
            model_name="sparse-test-model",
            prompt_version="seo-recommendation-narrative-v2",
        )


class _ReferenceHeavyRecommendationNarrativeProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return SEORecommendationNarrativeOutput(
            narrative_text="Prioritize high-impact recommendation references first.",
            top_themes=[],
            sections={
                "summary": "Use linked recommendation references to drive first implementation steps.",
                "priority_rationale": "Referenced recommendations are already deterministic and scoped.",
                "next_actions": [],
                "recommendation_references": ["rec-2", "rec-1", "rec-2"],
            },
            provider_name="reference-test-provider",
            model_name="reference-test-model",
            prompt_version="seo-recommendation-narrative-v2",
        )


class _DuplicateActionRecommendationNarrativeProvider:
    def generate_narrative(self, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return SEORecommendationNarrativeOutput(
            narrative_text="Prioritize distinct actions with clear owner-ready steps.",
            top_themes=["service coverage", "local trust"],
            sections={
                "summary": "Reduce repetition and keep focused next steps.",
                "priority_rationale": "Distinct actions improve operator execution clarity.",
                "next_actions": [
                    "Improve service pages.",
                    "Improve service pages for nearby competitors and local emergency intent coverage.",
                    "Improve service pages",
                    "Add trust badges and testimonials to service pages.",
                ],
                "recommendation_references": ["rec-2", "rec-1", "rec-2"],
            },
            provider_name="dedupe-test-provider",
            model_name="dedupe-test-model",
            prompt_version="seo-recommendation-narrative-v2",
        )


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(
    db_session,
    *,
    business_id: str,
    narrative_provider: SEORecommendationNarrativeProvider | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)
    app.include_router(seo_v1_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    # Keep contract tests deterministic across CI/runtime env variants:
    # success-path tests should use a mock provider unless a test explicitly
    # overrides provider behavior (e.g., failure/structured-output cases).
    provider = narrative_provider or MockSEORecommendationNarrativeProvider(
        provider_name="mock",
        model_name="mock-seo-recommendation-narrative-v1",
        prompt_version="seo-recommendation-narrative-v2",
    )
    app.dependency_overrides[get_seo_recommendation_narrative_provider] = lambda: provider
    return TestClient(app)


def _seed_other_business(db_session) -> Business:
    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550199",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.commit()
    return other_business


def _create_site(client: TestClient, business_id: str, *, domain: str = "client.example") -> str:
    create_site = client.post(
        f"/api/businesses/{business_id}/seo/sites",
        json={"display_name": f"Client Site {domain}", "base_url": f"https://{domain}/"},
    )
    assert create_site.status_code == 201
    return create_site.json()["id"]


def _seed_completed_audit_run(
    db_session,
    *,
    business_id: str,
    site_id: str,
    missing_title_count: int = 2,
) -> str:
    run = SEOAuditRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        max_pages=10,
        max_depth=2,
        pages_discovered=3,
        pages_crawled=3,
    )
    db_session.add(run)
    db_session.flush()

    for _ in range(missing_title_count):
        db_session.add(
            SEOAuditFinding(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                audit_run_id=run.id,
                page_id=None,
                finding_type="missing_title",
                category="SEO",
                severity="CRITICAL",
                title="Missing title tag",
                details="No title tag found.",
                rule_key="missing_title",
                suggested_fix="Add unique title tags",
            )
        )
    db_session.add(
        SEOAuditFinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=run.id,
            page_id=None,
            finding_type="thin_content",
            category="CONTENT",
            severity="WARNING",
            title="Thin content",
            details="Low word count.",
            rule_key="thin_content",
            suggested_fix="Expand content depth",
        )
    )
    db_session.commit()
    return run.id


def _create_completed_recommendation_run(client: TestClient, db_session, business_id: str) -> tuple[str, str]:
    site_id = _create_site(client, business_id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=business_id,
        site_id=site_id,
        missing_title_count=2,
    )
    create_run = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert create_run.status_code == 201
    return site_id, create_run.json()["id"]


def _seed_competitor_generation_telemetry_run(
    db_session,
    *,
    business_id: str,
    site_id: str,
    raw_candidate_count: int,
    included_candidate_count: int,
    excluded_candidate_count: int,
    exclusion_counts_by_reason: dict[str, int],
    raw_output: str | None = None,
) -> str:
    run = SEOCompetitorProfileGenerationRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        parent_run_id=None,
        status="completed",
        requested_candidate_count=max(1, raw_candidate_count),
        generated_draft_count=max(0, included_candidate_count),
        raw_candidate_count=max(0, raw_candidate_count),
        included_candidate_count=max(0, included_candidate_count),
        excluded_candidate_count=max(0, excluded_candidate_count),
        exclusion_counts_by_reason=exclusion_counts_by_reason,
        provider_name="mock",
        model_name="mock-seo-competitor-profile-v1",
        prompt_version="seo-competitor-profile-v1",
        failure_category=None,
        raw_output=raw_output,
        error_summary=None,
    )
    db_session.add(run)
    db_session.commit()
    return run.id


def test_recommendation_narrative_manual_trigger_success_and_retrieval(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    create_narrative = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert create_narrative.status_code == 201
    narrative = create_narrative.json()
    assert set(narrative.keys()) == NARRATIVE_RESPONSE_KEYS
    assert narrative["status"] == "completed"
    assert narrative["version"] == 1
    assert narrative["provider_name"] == "mock"
    assert narrative["model_name"]
    assert narrative["prompt_version"]
    assert narrative["error_message"] is None
    assert narrative["competitor_influence"] is None
    assert narrative["signal_summary"] == {
        "support_level": "medium",
        "evidence_sources": ["site", "themes"],
        "competitor_signal_used": False,
        "site_signal_used": True,
        "reference_signal_used": False,
    }

    list_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    assert set(list_payload["items"][0].keys()) == NARRATIVE_RESPONSE_KEYS

    latest_response = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives/latest"
    )
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == narrative["id"]

    by_id = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-narratives/{narrative['id']}"
    )
    assert by_id.status_code == 200
    assert by_id.json()["id"] == narrative["id"]


def test_recommendation_narrative_surfaces_action_summary_from_rich_sections(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=_RichActionSummaryRecommendationNarrativeProvider(),
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    payload = response.json()
    action_summary = payload["action_summary"]
    assert action_summary is not None
    assert action_summary["primary_action"] == "Publish emergency service page updates for top service categories."
    assert action_summary["first_step"] == "Publish emergency service page updates for top service categories."
    assert action_summary["why_it_matters"] == "This addresses the strongest local conversion and visibility gaps first."
    assert 1 <= len(action_summary["evidence"]) <= 4
    assert "Emergency service pages are weaker than nearby competitors." in action_summary["evidence"]
    signal_summary = payload["signal_summary"]
    assert signal_summary is not None
    assert signal_summary["competitor_signal_used"] is False
    assert signal_summary["site_signal_used"] is True
    assert signal_summary["reference_signal_used"] is True
    assert signal_summary["support_level"] in {"medium", "high"}
    assert signal_summary["evidence_sources"] == ["site", "references", "themes"]


def test_recommendation_narrative_action_summary_is_safe_when_sections_are_sparse_or_malformed(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=_SparseActionSummaryRecommendationNarrativeProvider(),
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    assert response.json()["action_summary"] is None
    assert response.json()["signal_summary"] is None


def test_recommendation_narrative_signal_summary_sets_reference_signal_when_references_exist(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=_ReferenceHeavyRecommendationNarrativeProvider(),
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    signal_summary = response.json()["signal_summary"]
    assert signal_summary is not None
    assert signal_summary["reference_signal_used"] is True
    assert signal_summary["competitor_signal_used"] is False
    assert "references" in signal_summary["evidence_sources"]


def test_recommendation_narrative_dedupes_overlapping_next_actions_and_preserves_action_summary_compatibility(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=_DuplicateActionRecommendationNarrativeProvider(),
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    payload = response.json()
    sections = payload["sections_json"]
    assert sections["next_actions"] == [
        "Improve service pages for nearby competitors and local emergency intent coverage.",
        "Add trust badges and testimonials to service pages.",
    ]
    action_summary = payload["action_summary"]
    assert action_summary is not None
    assert (
        action_summary["primary_action"]
        == "Improve service pages for nearby competitors and local emergency intent coverage."
    )
    assert (
        action_summary["first_step"]
        == "Improve service pages for nearby competitors and local emergency intent coverage."
    )
    signal_summary = payload["signal_summary"]
    assert signal_summary is not None
    assert signal_summary["support_level"] in {"medium", "high"}
    assert signal_summary["site_signal_used"] is True


def test_recommendation_narrative_failure_is_isolated_and_persisted(db_session, seeded_business) -> None:
    success_client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(success_client, db_session, seeded_business.id)

    first_narrative = success_client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert first_narrative.status_code == 201
    assert first_narrative.json()["version"] == 1

    recs_before = success_client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recs_before.status_code == 200
    total_recs_before = recs_before.json()["total"]

    failing_client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=_FailingRecommendationNarrativeProvider(),
    )
    failed = failing_client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert failed.status_code == 422

    run_after = success_client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}"
    )
    assert run_after.status_code == 200
    assert run_after.json()["status"] == "completed"

    recs_after = success_client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recs_after.status_code == 200
    assert recs_after.json()["total"] == total_recs_before

    narratives = (
        db_session.query(SEORecommendationNarrative)
        .filter(SEORecommendationNarrative.recommendation_run_id == run_id)
        .order_by(SEORecommendationNarrative.version.asc())
        .all()
    )
    assert [item.version for item in narratives] == [1, 2]
    assert [item.status for item in narratives] == ["completed", "failed"]
    assert narratives[1].error_message is not None

    latest = success_client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives/latest"
    )
    assert latest.status_code == 200
    assert latest.json()["version"] == 2
    assert latest.json()["status"] == "failed"


def test_recommendation_narrative_structured_output_failure_is_safe_and_auditable(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=_StructuredOutputFailingNarrativeProvider(),
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    failed = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert failed.status_code == 422
    assert failed.json()["detail"] == "Recommendation narrative returned invalid structured output."

    narratives = (
        db_session.query(SEORecommendationNarrative)
        .filter(SEORecommendationNarrative.recommendation_run_id == run_id)
        .order_by(SEORecommendationNarrative.version.asc())
        .all()
    )
    assert len(narratives) == 1
    assert narratives[0].status == "failed"
    assert narratives[0].provider_name == "openai"
    assert narratives[0].model_name == "gpt-4o-mini"
    assert narratives[0].prompt_version == "seo-recommendation-narrative-v2"
    assert narratives[0].error_message == "Recommendation narrative returned invalid structured output."

    recs_after = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recs_after.status_code == 200
    assert recs_after.json()["total"] >= 1


def test_recommendation_narrative_business_isolation_and_invalid_lineage(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    create_narrative = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert create_narrative.status_code == 201
    narrative_id = create_narrative.json()["id"]

    cross_tenant_trigger = client.post(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert cross_tenant_trigger.status_code == 404

    cross_tenant_latest = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives/latest"
    )
    assert cross_tenant_latest.status_code == 404

    cross_tenant_by_id = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendation-narratives/{narrative_id}"
    )
    assert cross_tenant_by_id.status_code == 404

    invalid_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{uuid4()}/narratives"
    )
    assert invalid_run.status_code == 404


def test_recommendation_narrative_is_grounded_in_persisted_recommendation_artifacts_only(
    db_session,
    seeded_business,
) -> None:
    capturing_provider = _CapturingRecommendationNarrativeProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=capturing_provider,
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    recommendation = (
        db_session.query(SEORecommendation)
        .filter(SEORecommendation.recommendation_run_id == run_id)
        .order_by(SEORecommendation.priority_score.desc())
        .first()
    )
    assert recommendation is not None
    recommendation.status = "in_progress"
    recommendation.priority_band = "critical"
    db_session.add(recommendation)
    db_session.commit()

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["provider_name"] == "capturing-test-provider"
    assert f"run={run_id}" in payload["narrative_text"]

    assert len(capturing_provider.calls) == 1
    call = capturing_provider.calls[0]
    assert call["run_id"] == run_id
    assert call["recommendation_count"] >= 1
    assert call["by_status"].get("in_progress", 0) >= 1
    assert call["by_priority_band"].get("critical", 0) >= 1
    assert call["competitor_telemetry_summary"]["lookback_days"] == 30
    assert "competitor_candidate_min_relevance_score" in call["current_tuning_values"]
    assert call["competitor_context"] == {
        "competitor_names": [],
        "competitor_summary": "",
        "top_opportunities": [],
    }


def test_recommendation_narrative_optionally_includes_normalized_competitor_context(
    db_session,
    seeded_business,
) -> None:
    capturing_provider = _CapturingRecommendationNarrativeProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        narrative_provider=capturing_provider,
    )
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)
    _seed_competitor_generation_telemetry_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        raw_candidate_count=6,
        included_candidate_count=3,
        excluded_candidate_count=3,
        exclusion_counts_by_reason={
            "duplicate": 1,
            "low_relevance": 1,
            "directory_or_aggregator": 1,
            "big_box_mismatch": 0,
            "existing_domain_match": 0,
            "invalid_candidate": 0,
        },
        raw_output=(
            '{"competitors":[{"name":"Alpha Plumbing"},{"name":"Beta HVAC"}],'
            '"top_opportunities":["Improve emergency pages","Improve emergency pages","Add local proof"],'
            '"summary":"Competitors emphasize emergency response and local trust."}'
        ),
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201

    assert len(capturing_provider.calls) == 1
    call = capturing_provider.calls[0]
    assert call["competitor_context"] == {
        "top_opportunities": ["Improve emergency pages", "Add local proof"],
        "competitor_summary": "Competitors emphasize emergency response and local trust.",
        "competitor_names": ["Alpha Plumbing", "Beta HVAC"],
    }
    payload = response.json()
    assert payload["competitor_influence"] == {
        "used": True,
        "summary": (
            "Recommendation specificity used normalized competitor context: "
            "Competitors emphasize emergency response and local trust."
        ),
        "top_opportunities": ["Improve emergency pages", "Add local proof"],
        "competitor_names": ["Alpha Plumbing", "Beta HVAC"],
    }
    action_summary = payload["action_summary"]
    assert action_summary is not None
    assert action_summary["primary_action"].startswith("grounded run=")
    assert action_summary["first_step"].startswith("grounded run=")
    assert len(action_summary["evidence"]) <= 4
    assert any(item.startswith("Competitor gap: ") for item in action_summary["evidence"])
    signal_summary = payload["signal_summary"]
    assert signal_summary is not None
    assert signal_summary["competitor_signal_used"] is True
    assert signal_summary["site_signal_used"] is True
    assert signal_summary["support_level"] in {"medium", "high"}
    assert "competitors" in signal_summary["evidence_sources"]


def test_recommendation_narrative_does_not_surface_competitor_influence_for_fallback_only_payload(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)
    _seed_competitor_generation_telemetry_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        raw_candidate_count=3,
        included_candidate_count=0,
        excluded_candidate_count=3,
        exclusion_counts_by_reason={
            "duplicate": 1,
            "low_relevance": 1,
            "directory_or_aggregator": 1,
            "big_box_mismatch": 0,
            "existing_domain_match": 0,
            "invalid_candidate": 0,
        },
        raw_output=(
            '{"competitors":[],'
            '"top_opportunities":["Improve website clarity","Add trust signals","Clarify services"],'
            '"summary":"Competitor analysis unavailable, using fallback insights."}'
        ),
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    assert response.json()["competitor_influence"] is None


def test_recommendation_narrative_competitor_influence_remains_bounded(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)
    _seed_competitor_generation_telemetry_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        raw_candidate_count=12,
        included_candidate_count=7,
        excluded_candidate_count=5,
        exclusion_counts_by_reason={
            "duplicate": 1,
            "low_relevance": 2,
            "directory_or_aggregator": 1,
            "big_box_mismatch": 1,
            "existing_domain_match": 0,
            "invalid_candidate": 0,
        },
        raw_output=(
            '{"competitors":['
            '{"name":"Competitor 1"},{"name":"Competitor 2"},{"name":"Competitor 3"},'
            '{"name":"Competitor 4"},{"name":"Competitor 5"},{"name":"Competitor 6"}'
            '],'
            '"top_opportunities":['
            '"Opportunity 1","Opportunity 2","Opportunity 3",'
            '"Opportunity 4","Opportunity 5","Opportunity 6"'
            '],'
            '"summary":"Competitor context with many entries."}'
        ),
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert response.status_code == 201
    payload = response.json()["competitor_influence"]
    assert payload is not None
    assert payload["used"] is True
    assert len(payload["top_opportunities"]) == 5
    assert len(payload["competitor_names"]) == 5


def test_phase3c_v1_site_scoped_narrative_routes(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    create_narrative = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert create_narrative.status_code == 201
    narrative_id = create_narrative.json()["id"]

    list_narratives = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives"
    )
    assert list_narratives.status_code == 200
    assert list_narratives.json()["total"] >= 1

    latest = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives/latest"
    )
    assert latest.status_code == 200

    by_id = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-narratives/{narrative_id}"
    )
    assert by_id.status_code == 200

    wrong_site = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{uuid4()}/recommendation-narratives/{narrative_id}"
    )
    assert wrong_site.status_code == 404


def test_recommendation_tuning_preview_returns_deterministic_estimate(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)
    _seed_competitor_generation_telemetry_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        raw_candidate_count=10,
        included_candidate_count=4,
        excluded_candidate_count=6,
        exclusion_counts_by_reason={
            "duplicate": 1,
            "low_relevance": 3,
            "directory_or_aggregator": 1,
            "big_box_mismatch": 1,
            "existing_domain_match": 0,
            "invalid_candidate": 0,
        },
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "recommendation_run_id": run_id,
            "current_values": {"competitor_candidate_min_relevance_score": 35},
            "proposed_values": {"competitor_candidate_min_relevance_score": 40},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["business_id"] == seeded_business.id
    assert payload["site_id"] == site_id
    assert payload["preview_event_id"] is not None
    assert payload["source_recommendation_run_id"] == run_id
    assert payload["current_values"]["competitor_candidate_min_relevance_score"] == 35
    assert payload["proposed_values"]["competitor_candidate_min_relevance_score"] == 40
    assert payload["telemetry_window"]["total_raw_candidate_count"] == 10
    assert payload["estimated_impact"]["insufficient_data"] is False
    assert payload["estimated_impact"]["estimated_excluded_candidate_delta"] > 0
    assert payload["estimated_impact"]["estimated_included_candidate_delta"] < 0
    assert "estimate" in payload["caveat"].lower()

    v1_response = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "recommendation_run_id": run_id,
            "current_values": {"competitor_candidate_min_relevance_score": 35},
            "proposed_values": {"competitor_candidate_min_relevance_score": 40},
        },
    )
    assert v1_response.status_code == 200
    assert v1_response.json()["source_recommendation_run_id"] == run_id


def test_recommendation_tuning_preview_persists_preview_event(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)
    _seed_competitor_generation_telemetry_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        raw_candidate_count=6,
        included_candidate_count=3,
        excluded_candidate_count=3,
        exclusion_counts_by_reason={
            "duplicate": 1,
            "low_relevance": 1,
            "directory_or_aggregator": 1,
            "big_box_mismatch": 0,
            "existing_domain_match": 0,
            "invalid_candidate": 0,
        },
    )

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "recommendation_run_id": run_id,
            "current_values": {"competitor_candidate_directory_penalty": 35},
            "proposed_values": {"competitor_candidate_directory_penalty": 30},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_event_id"] is not None

    events = (
        db_session.query(SEOCompetitorTuningPreviewEvent)
        .filter(SEOCompetitorTuningPreviewEvent.business_id == seeded_business.id)
        .filter(SEOCompetitorTuningPreviewEvent.site_id == site_id)
        .order_by(SEOCompetitorTuningPreviewEvent.created_at.desc(), SEOCompetitorTuningPreviewEvent.id.desc())
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.id == payload["preview_event_id"]
    assert event.source_recommendation_run_id == run_id
    assert event.source_narrative_id is None
    assert event.preview_request["proposed_values"]["competitor_candidate_directory_penalty"] == 30
    assert event.preview_response["estimated_impact"]["summary"]
    assert event.applied_at is None
    assert event.evaluated_at is None


def test_recommendation_tuning_preview_rejects_invalid_payload(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, _ = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    invalid_setting = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "proposed_values": {"unknown_setting": 42},
        },
    )
    assert invalid_setting.status_code == 422

    invalid_bounds = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "proposed_values": {"competitor_candidate_min_relevance_score": 101},
        },
    )
    assert invalid_bounds.status_code == 422


def test_recommendation_tuning_preview_isolation_and_no_mutation(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    business_before = db_session.query(Business).filter(Business.id == seeded_business.id).one()
    before_values = (
        business_before.competitor_candidate_min_relevance_score,
        business_before.competitor_candidate_big_box_penalty,
        business_before.competitor_candidate_directory_penalty,
        business_before.competitor_candidate_local_alignment_bonus,
    )

    preview = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "recommendation_run_id": run_id,
            "proposed_values": {"competitor_candidate_directory_penalty": 30},
        },
    )
    assert preview.status_code == 200

    business_after = db_session.query(Business).filter(Business.id == seeded_business.id).one()
    after_values = (
        business_after.competitor_candidate_min_relevance_score,
        business_after.competitor_candidate_big_box_penalty,
        business_after.competitor_candidate_directory_penalty,
        business_after.competitor_candidate_local_alignment_bonus,
    )
    assert before_values == after_values

    cross_tenant = client.post(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "recommendation_run_id": run_id,
            "proposed_values": {"competitor_candidate_directory_penalty": 30},
        },
    )
    assert cross_tenant.status_code == 404


def test_recommendation_tuning_preview_handles_no_telemetry_safely(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/tuning-preview",
        json={
            "recommendation_run_id": run_id,
            "proposed_values": {"competitor_candidate_local_alignment_bonus": 15},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["estimated_impact"]["insufficient_data"] is True
    assert payload["estimated_impact"]["estimated_included_candidate_delta"] == 0
    assert payload["estimated_impact"]["estimated_excluded_candidate_delta"] == 0
    assert payload["telemetry_window"]["total_runs"] == 0


def test_recommendation_narrative_endpoints_not_found_behaviors(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, run_id = _create_completed_recommendation_run(client, db_session, seeded_business.id)

    latest_before_any = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/narratives/latest"
    )
    assert latest_before_any.status_code == 404

    list_unknown_run = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{uuid4()}/narratives"
    )
    assert list_unknown_run.status_code == 404

    by_unknown_narrative_id = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-narratives/{uuid4()}"
    )
    assert by_unknown_narrative_id.status_code == 404

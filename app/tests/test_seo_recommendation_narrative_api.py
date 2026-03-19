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
from app.integrations.seo_summary_provider import (
    SEORecommendationNarrativeOutput,
    SEORecommendationNarrativeProvider,
)
from app.models.business import Business
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_recommendation_run import SEORecommendationRun


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
            }
        )
        return SEORecommendationNarrativeOutput(
            narrative_text=f"grounded run={run.id} backlog={len(backlog)}",
            top_themes=["theme_a", "theme_b"],
            sections={
                "status": dict(by_status),
                "priority_band": dict(by_priority_band),
            },
            provider_name="capturing-test-provider",
            model_name="capturing-test-model",
            prompt_version="seo-recommendation-narrative-v1",
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
    if narrative_provider is not None:
        app.dependency_overrides[get_seo_recommendation_narrative_provider] = lambda: narrative_provider
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

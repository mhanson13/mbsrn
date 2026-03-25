from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.core.time import utc_now
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.models.business import Business
from app.models.principal import Principal, PrincipalRole
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_recommendation_run import SEORecommendationRun


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(db_session, *, business_id: str) -> TestClient:
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


def _seed_principal(
    db_session,
    *,
    business_id: str,
    principal_id: str,
    is_active: bool = True,
) -> Principal:
    principal = Principal(
        business_id=business_id,
        id=principal_id,
        display_name=f"Principal {principal_id}",
        role=PrincipalRole.OPERATOR,
        is_active=is_active,
    )
    db_session.add(principal)
    db_session.commit()
    return principal


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


def _seed_audit_pages(
    db_session,
    *,
    business_id: str,
    site_id: str,
    audit_run_id: str,
    pages: list[dict[str, object]],
) -> None:
    for page_data in pages:
        db_session.add(
            SEOAuditPage(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                audit_run_id=audit_run_id,
                url=str(page_data.get("url") or "https://example.com/"),
                status_code=200,
                title=page_data.get("title"),
                meta_description=page_data.get("meta_description"),
                h1_json=page_data.get("h1_json") or [],
                h2_json=page_data.get("h2_json") or [],
                word_count=page_data.get("word_count") or 0,
                internal_link_count=0,
                image_count=0,
                missing_alt_count=0,
            )
        )
    db_session.commit()


def _seed_completed_comparison_run(
    db_session,
    *,
    business_id: str,
    site_id: str,
) -> str:
    competitor_set = SEOCompetitorSet(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        name="Set A",
        is_active=True,
    )
    db_session.add(competitor_set)
    db_session.flush()

    snapshot_run = SEOCompetitorSnapshotRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        status="completed",
        max_domains=5,
        max_pages_per_domain=5,
        max_depth=1,
        same_domain_only=True,
        domains_targeted=1,
        domains_completed=1,
        pages_attempted=3,
        pages_captured=3,
    )
    db_session.add(snapshot_run)
    db_session.flush()

    comparison_run = SEOCompetitorComparisonRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        snapshot_run_id=snapshot_run.id,
        status="completed",
        total_findings=1,
        critical_findings=1,
        warning_findings=0,
        info_findings=0,
        client_pages_analyzed=3,
        competitor_pages_analyzed=4,
        finding_type_counts_json={"missing_title_count_gap": 1},
        category_counts_json={"SEO": 1},
        severity_counts_json={"CRITICAL": 1},
        metric_rollups_json={
            "missing_title_count": {
                "title": "Missing title count gap",
                "category": "SEO",
                "unit": "count",
                "higher_is_better": False,
                "client_value": 3,
                "competitor_value": 1,
                "delta": 2,
                "severity": "CRITICAL",
                "gap_direction": "client_trails",
            }
        },
    )
    db_session.add(comparison_run)
    db_session.flush()

    db_session.add(
        SEOCompetitorComparisonFinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            comparison_run_id=comparison_run.id,
            finding_type="missing_title_count_gap",
            category="SEO",
            severity="CRITICAL",
            title="Missing title count gap",
            details="Client trails competitor on missing title count.",
            rule_key="comparison_missing_title_count",
            client_value="3",
            competitor_value="1",
            gap_direction="client_trails",
            evidence_json={"delta": 2},
        )
    )
    db_session.commit()
    return comparison_run.id


def test_create_recommendation_run_from_persisted_inputs(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        missing_title_count=2,
    )
    comparison_run_id = _seed_completed_comparison_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id, "comparison_run_id": comparison_run_id},
    )
    assert create_run.status_code == 201
    run_payload = create_run.json()
    assert run_payload["status"] == "completed"
    assert run_payload["total_recommendations"] >= 2
    assert run_payload["critical_recommendations"] >= 1
    run_id = run_payload["id"]

    list_runs = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs")
    assert list_runs.status_code == 200
    assert list_runs.json()["total"] >= 1

    list_recommendations = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert list_recommendations.status_code == 200
    payload = list_recommendations.json()
    assert payload["total"] >= 2
    rule_keys = {item["rule_key"] for item in payload["items"]}
    assert "fix_missing_title_tags" in rule_keys
    assert "expand_thin_content_pages" in rule_keys
    assert "close_competitor_gap_missing_title_count" in rule_keys

    # Deterministic merge check: two missing_title findings should yield one recommendation rule.
    assert sum(1 for item in payload["items"] if item["rule_key"] == "fix_missing_title_tags") == 1

    report = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/report")
    assert report.status_code == 200
    report_payload = report.json()
    assert set(report_payload.keys()) == {"recommendation_run", "rollups", "recommendations"}
    assert report_payload["recommendation_run"]["id"] == run_id
    assert "by_category" in report_payload["rollups"]
    assert "by_severity" in report_payload["rollups"]
    assert "by_effort_bucket" in report_payload["rollups"]


def test_recommendation_run_requires_lineage_and_completed_inputs(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    missing_lineage = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={},
    )
    assert missing_lineage.status_code == 422

    incomplete_audit_run = SEOAuditRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site_id,
        status="running",
        max_pages=10,
        max_depth=2,
    )
    db_session.add(incomplete_audit_run)
    db_session.commit()

    non_completed_input = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": incomplete_audit_run.id},
    )
    assert non_completed_input.status_code == 422


def test_recommendation_routes_enforce_site_and_business_scoping(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id, domain="client-a.example")
    other_site_id = _create_site(client, seeded_business.id, domain="client-b.example")

    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)
    comparison_run_id = _seed_completed_comparison_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id, "comparison_run_id": comparison_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    cross_tenant_run = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}"
    )
    assert cross_tenant_run.status_code == 404

    wrong_site_run = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{other_site_id}/recommendation-runs/{run_id}"
    )
    assert wrong_site_run.status_code == 404

    list_cross_tenant = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert list_cross_tenant.status_code == 404


def test_recommendation_lineage_mismatch_is_rejected(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_a_id = _create_site(client, seeded_business.id, domain="client-a.example")
    site_b_id = _create_site(client, seeded_business.id, domain="client-b.example")

    audit_run_for_other_site = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_b_id,
    )
    mismatch = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_a_id}/recommendation-runs",
        json={"audit_run_id": audit_run_for_other_site},
    )
    assert mismatch.status_code == 422

    comparison_run_for_other_site = _seed_completed_comparison_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_b_id,
    )
    mismatch_comparison = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_a_id}/recommendation-runs",
        json={"comparison_run_id": comparison_run_for_other_site},
    )
    assert mismatch_comparison.status_code == 422


def test_phase2_v1_site_scoped_recommendation_routes(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    get_run = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}")
    assert get_run.status_code == 200

    list_recommendations = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert list_recommendations.status_code == 200
    recommendation_id = list_recommendations.json()["items"][0]["id"]

    get_recommendation = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}"
    )
    assert get_recommendation.status_code == 200

    report = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/report"
    )
    assert report.status_code == 200

    wrong_site = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{uuid4()}/recommendation-runs/{run_id}")
    assert wrong_site.status_code == 404


def test_recommendation_run_repeat_execution_is_deterministic(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        missing_title_count=3,
    )
    comparison_run_id = _seed_completed_comparison_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )

    first_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id, "comparison_run_id": comparison_run_id},
    )
    second_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id, "comparison_run_id": comparison_run_id},
    )
    assert first_run.status_code == 201
    assert second_run.status_code == 201
    first_run_id = first_run.json()["id"]
    second_run_id = second_run.json()["id"]

    first_recs = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{first_run_id}/recommendations"
    )
    second_recs = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{second_run_id}/recommendations"
    )
    assert first_recs.status_code == 200
    assert second_recs.status_code == 200

    def _signature(payload: dict) -> list[tuple[str, str, str, int, str]]:
        return sorted(
            (
                item["rule_key"],
                item["category"],
                item["severity"],
                item["priority_score"],
                item["effort_bucket"],
            )
            for item in payload["items"]
        )

    assert _signature(first_recs.json()) == _signature(second_recs.json())


def test_recommendation_not_found_behaviors(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    get_run = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{uuid4()}")
    assert get_run.status_code == 404

    get_recommendation = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{uuid4()}"
    )
    assert get_recommendation.status_code == 404


def test_recommendation_workflow_patch_backlog_and_prioritized_report(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="owner-1")
    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    list_items = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert list_items.status_code == 200
    recommendation_id = list_items.json()["items"][0]["id"]

    patch_in_progress = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={
            "status": "in_progress",
            "assigned_principal_id": "owner-1",
            "due_at": (utc_now() + timedelta(days=2)).isoformat(),
        },
    )
    assert patch_in_progress.status_code == 200
    in_progress_payload = patch_in_progress.json()
    assert in_progress_payload["status"] == "in_progress"
    assert in_progress_payload["decision"] == "start"
    assert in_progress_payload["assigned_principal_id"] == "owner-1"

    patch_snoozed = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={
            "decision": "snooze",
            "decision_reason": "Waiting on client website access",
            "snoozed_until": (utc_now() + timedelta(days=1)).isoformat(),
        },
    )
    assert patch_snoozed.status_code == 200
    assert patch_snoozed.json()["status"] == "snoozed"
    assert patch_snoozed.json()["decision"] == "snooze"
    assert patch_snoozed.json()["snoozed_until"] is not None

    backlog = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/backlog")
    assert backlog.status_code == 200
    backlog_ids = {item["id"] for item in backlog.json()["items"]}
    assert recommendation_id not in backlog_ids

    patch_reopen = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"decision": "reopen"},
    )
    assert patch_reopen.status_code == 200
    assert patch_reopen.json()["status"] == "open"
    assert patch_reopen.json()["snoozed_until"] is None

    report = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/prioritized-report")
    assert report.status_code == 200
    payload = report.json()
    assert set(payload.keys()) == {
        "business_id",
        "site_id",
        "generated_at",
        "total_recommendations",
        "backlog_total",
        "by_status",
        "by_category",
        "by_severity",
        "by_effort_bucket",
        "by_priority_band",
        "backlog",
    }
    assert "open" in payload["by_status"]
    assert payload["backlog"]["total"] == payload["backlog_total"]


def test_recommendation_workflow_patch_accepts_note_alias(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    other_site_id = _create_site(client, seeded_business.id, domain="other-site.example")
    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    recommendation_id = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    ).json()["items"][0]["id"]

    patch_with_note_alias = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={
            "status": "accepted",
            "note": "Looks valid for Q2 rollout",
        },
    )
    assert patch_with_note_alias.status_code == 200
    patched_payload = patch_with_note_alias.json()
    assert patched_payload["status"] == "accepted"
    assert patched_payload["decision_reason"] == "Looks valid for Q2 rollout"

    patch_note_only = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={
            "note": "Reviewed with operator notes only",
        },
    )
    assert patch_note_only.status_code == 200
    patch_note_only_payload = patch_note_only.json()
    assert patch_note_only_payload["status"] == "accepted"
    assert patch_note_only_payload["decision_reason"] == "Reviewed with operator notes only"

    wrong_site_patch = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{other_site_id}/recommendations/{recommendation_id}",
        json={
            "note": "attempt from wrong site scope",
        },
    )
    assert wrong_site_patch.status_code == 404

    cross_business_patch = client.patch(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={
            "note": "attempt from wrong business scope",
        },
    )
    assert cross_business_patch.status_code == 404

    patch_mismatch = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={
            "note": "foo",
            "decision_reason": "bar",
        },
    )
    assert patch_mismatch.status_code == 422


def test_recommendation_workflow_rejects_invalid_transitions_and_assignments(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="inactive-owner", is_active=False)
    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    run_id = create_run.json()["id"]
    recommendation_id = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    ).json()["items"][0]["id"]

    dismissed = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200

    invalid_transition = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"status": "in_progress"},
    )
    assert invalid_transition.status_code == 422

    missing_snooze_until = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"status": "snoozed"},
    )
    assert missing_snooze_until.status_code == 422

    inactive_assignee = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"status": "open", "assigned_principal_id": "inactive-owner"},
    )
    assert inactive_assignee.status_code == 422


def test_phase3b_recommendation_filters_and_scope_guards(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_a_id = _create_site(client, seeded_business.id, domain="site-a.example")
    site_b_id = _create_site(client, seeded_business.id, domain="site-b.example")

    run_id = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_a_id}/recommendation-runs",
        json={"audit_run_id": _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_a_id)},
    ).json()["id"]
    recommendation_id = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_a_id}/recommendation-runs/{run_id}/recommendations"
    ).json()["items"][0]["id"]
    resolved = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_a_id}/recommendations/{recommendation_id}",
        json={"decision": "resolve"},
    )
    assert resolved.status_code == 200

    filtered = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_a_id}/recommendations",
        params={"status": "resolved"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == recommendation_id

    wrong_site = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_b_id}/recommendations/{recommendation_id}"
    )
    assert wrong_site.status_code == 404

    cross_business = client.get(f"/api/businesses/{other_business.id}/seo/sites/{site_a_id}/recommendations")
    assert cross_business.status_code == 404


def test_phase3b_recommendation_list_backend_pagination(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id, domain="paged-site.example")

    for _ in range(3):
        audit_run_id = _seed_completed_audit_run(
            db_session,
            business_id=seeded_business.id,
            site_id=site_id,
        )
        create_run = client.post(
            f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
            json={"audit_run_id": audit_run_id},
        )
        assert create_run.status_code == 201

    full_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"sort_by": "created_at", "sort_order": "asc", "page": 1, "page_size": 100},
    )
    assert full_list.status_code == 200
    full_payload = full_list.json()
    full_ids = [item["id"] for item in full_payload["items"]]
    assert full_payload["total"] == len(full_ids)
    assert full_payload["total"] >= 6
    full_summary = full_payload["filtered_summary"]
    assert full_summary["total"] == full_payload["total"]
    assert full_summary["open"] == full_payload["total"]
    assert full_summary["accepted"] == 0
    assert full_summary["dismissed"] == 0
    assert 0 <= full_summary["high_priority"] <= full_payload["total"]

    first_page = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"sort_by": "created_at", "sort_order": "asc", "page": 1, "page_size": 2},
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["total"] == full_payload["total"]
    assert len(first_payload["items"]) == 2
    assert [item["id"] for item in first_payload["items"]] == full_ids[:2]
    assert first_payload["filtered_summary"] == full_summary
    assert first_payload["by_status"].get("open") == full_payload["total"]
    assert sum(first_payload["by_category"].values()) == full_payload["total"]

    second_page = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"sort_by": "created_at", "sort_order": "asc", "page": 2, "page_size": 2},
    )
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert second_payload["total"] == full_payload["total"]
    assert len(second_payload["items"]) == 2
    assert [item["id"] for item in second_payload["items"]] == full_ids[2:4]
    assert second_payload["filtered_summary"] == full_summary
    assert second_payload["by_status"].get("open") == full_payload["total"]
    assert sum(second_payload["by_category"].values()) == full_payload["total"]

    recommendation_id = full_ids[0]
    resolve_recommendation = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"decision": "resolve"},
    )
    assert resolve_recommendation.status_code == 200

    resolved_page = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"status": "resolved", "sort_by": "created_at", "sort_order": "asc", "page": 1, "page_size": 1},
    )
    assert resolved_page.status_code == 200
    resolved_payload = resolved_page.json()
    assert resolved_payload["total"] == 1
    assert len(resolved_payload["items"]) == 1
    assert resolved_payload["items"][0]["id"] == recommendation_id
    assert resolved_payload["filtered_summary"]["total"] == 1
    assert resolved_payload["filtered_summary"]["open"] == 0
    assert resolved_payload["filtered_summary"]["accepted"] == 0
    assert resolved_payload["filtered_summary"]["dismissed"] == 0
    assert 0 <= resolved_payload["filtered_summary"]["high_priority"] <= 1
    assert resolved_payload["by_status"].get("resolved") == 1
    assert sum(resolved_payload["by_status"].values()) == 1


def test_phase3b_recommendation_list_pagination_bounds_validation(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id, domain="bounds-site.example")

    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert create_run.status_code == 201

    invalid_page = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"page": 0},
    )
    assert invalid_page.status_code == 422

    invalid_page_size = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"page_size": 101},
    )
    assert invalid_page_size.status_code == 422


def test_phase3b_v1_recommendation_workflow_routes(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    _seed_principal(db_session, business_id=seeded_business.id, principal_id="owner-v1")
    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    rec_list = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    recommendation_id = rec_list.json()["items"][0]["id"]

    patch_rec = client.patch(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/{recommendation_id}",
        json={"status": "in_progress", "assigned_principal_id": "owner-v1"},
    )
    assert patch_rec.status_code == 200
    assert patch_rec.json()["status"] == "in_progress"

    list_site = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations",
        params={"sort_by": "updated_at", "sort_order": "asc"},
    )
    assert list_site.status_code == 200

    backlog = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/backlog")
    assert backlog.status_code == 200

    report = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/prioritized-report"
    )
    assert report.status_code == 200


def test_recommendation_workspace_summary_returns_latest_completed_run(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )

    created = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["state"] == "completed_no_narrative"
    assert payload["latest_run"]["id"] == run_id
    assert payload["latest_completed_run"]["id"] == run_id
    assert payload["recommendations"]["total"] > 0
    assert isinstance(payload["recommendations"]["items"][0]["eeat_categories"], list)
    assert payload["recommendations"]["items"][0]["primary_eeat_category"] is None
    assert isinstance(payload["recommendations"]["items"][0]["priority_reasons"], list)
    assert payload["recommendations"]["items"][0]["primary_priority_reason"] in {
        None,
        "competitor_gap",
        "trust_gap",
        "authority_gap",
        "experience_gap",
        "expertise_gap",
        "high_clarity_action",
        "pending_refresh_context",
        "general",
    }
    assert payload["recommendations"]["items"][0]["theme"] in {
        "trust_and_legitimacy",
        "experience_and_proof",
        "authority_and_visibility",
        "expertise_and_process",
        "general_site_improvement",
    }
    assert isinstance(payload["grouped_recommendations"], list)
    grouped_ids = [
        recommendation_id
        for group in payload["grouped_recommendations"]
        for recommendation_id in group["recommendation_ids"]
    ]
    flat_ids = [item["id"] for item in payload["recommendations"]["items"]]
    assert grouped_ids
    assert grouped_ids == flat_ids
    assert payload["start_here"] is not None
    assert payload["start_here"]["recommendation_id"] == flat_ids[0]
    assert payload["start_here"]["title"] == payload["recommendations"]["items"][0]["title"]
    assert payload["start_here"]["reason"]
    assert payload["start_here"]["context_flags"] == []
    assert payload["recommendations"]["items"][0]["recommendation_progress_status"] == "suggested"
    assert (
        payload["recommendations"]["items"][0]["recommendation_progress_summary"]
        == "Suggested action not yet applied."
    )
    assert (
        payload["recommendations"]["items"][0]["recommendation_evidence_summary"]
        == "This is backed by structured site findings from the latest analysis."
    )
    assert payload["recommendations"]["items"][0]["recommendation_action_clarity"]
    assert payload["recommendations"]["items"][0]["recommendation_expected_outcome"]
    assert payload["latest_narrative"] is None
    assert payload["tuning_suggestions"] == []
    assert payload["apply_outcome"] is None
    assert payload["analysis_freshness"]["status"] == "fresh"
    assert payload["analysis_freshness"]["analysis_generated_at"] is not None
    assert payload["analysis_freshness"]["last_apply_at"] is None
    assert payload["competitor_context_health"] is not None
    assert payload["competitor_context_health"]["status"] == "weak"
    assert payload["competitor_context_health"]["message"]
    assert [check["key"] for check in payload["competitor_context_health"]["checks"]] == [
        "location_context",
        "industry_context",
        "service_focus",
        "target_customer_context",
    ]
    assert payload["site_location_context_strength"] == "weak"
    assert payload["site_location_context_source"] == "fallback"
    assert payload["site_primary_business_zip"] is None
    assert payload["site_location_context"]
    assert payload["ordering_explanation"] is not None
    assert payload["ordering_explanation"]["message"]
    assert payload["eeat_gap_summary"] is None
    assert payload["competitor_prompt_preview"] is not None
    assert payload["competitor_prompt_preview"]["prompt_type"] == "competitor"
    assert payload["competitor_prompt_preview"]["system_prompt"]
    assert payload["competitor_prompt_preview"]["user_prompt"]
    assert "Authorization:" not in payload["competitor_prompt_preview"]["system_prompt"]
    assert "Authorization:" not in payload["competitor_prompt_preview"]["user_prompt"]
    assert payload["recommendation_prompt_preview"] is not None
    assert payload["recommendation_prompt_preview"]["prompt_type"] == "recommendation"
    assert payload["recommendation_prompt_preview"]["model"]
    assert payload["recommendation_prompt_preview"]["system_prompt"]
    assert payload["recommendation_prompt_preview"]["user_prompt"]
    assert "Authorization:" not in payload["recommendation_prompt_preview"]["system_prompt"]
    assert "Authorization:" not in payload["recommendation_prompt_preview"]["user_prompt"]


def test_recommendation_workspace_summary_reflects_primary_business_zip_location_context(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    patch_site = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"primary_business_zip": "80538"},
    )
    assert patch_site.status_code == 200
    patched_payload = patch_site.json()
    assert patched_payload["primary_business_zip"] == "80538"
    assert patched_payload["primary_location"] == "Serving area around ZIP code 80538"

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["state"] == "no_runs"
    assert payload["start_here"] is None
    assert payload["site_location_context_strength"] == "strong"
    assert payload["site_location_context_source"] == "zip_capture"
    assert payload["site_primary_business_zip"] == "80538"
    assert payload["site_primary_location"] == "Serving area around ZIP code 80538"
    assert "80538" in payload["site_location_context"]


def test_recommendation_workspace_summary_reflects_explicit_location_source(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    patch_site = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"primary_location": "Loveland, Colorado"},
    )
    assert patch_site.status_code == 200

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["start_here"] is None
    assert payload["site_location_context_strength"] == "strong"
    assert payload["site_location_context_source"] == "explicit_location"
    assert payload["site_primary_location"] == "Loveland, Colorado"
    assert payload["site_primary_business_zip"] is None
    assert payload["site_location_context"] == "Loveland, Colorado"


def test_recommendation_workspace_summary_reflects_service_area_location_source(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    patch_site = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"service_areas": ["Fort Collins", "Loveland"]},
    )
    assert patch_site.status_code == 200

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["start_here"] is None
    assert payload["site_location_context_strength"] == "strong"
    assert payload["site_location_context_source"] == "service_area"
    assert payload["site_primary_location"] is None
    assert payload["site_location_context"] == "Serves Fort Collins, Loveland"


def test_recommendation_workspace_summary_prefers_audit_page_content_for_industry_and_service_focus(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id, domain="grahams.example")

    patch_site = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "display_name": "Graham's",
            "industry": None,
        },
    )
    assert patch_site.status_code == 200

    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        missing_title_count=1,
    )
    _seed_audit_pages(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        audit_run_id=audit_run_id,
        pages=[
            {
                "url": "https://grahams.example/flooring-installation",
                "title": "Graham's Flooring - Hardwood and Tile Installation",
                "meta_description": "Residential and commercial flooring services in Northern Colorado.",
                "h1_json": ["Flooring Installation and Refinishing"],
                "h2_json": ["Hardwood Flooring", "Tile Installation", "Carpet Installation"],
                "word_count": 1200,
            }
        ],
    )

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()

    context_health = payload["competitor_context_health"]
    assert context_health is not None
    check_statuses = {check["key"]: check["status"] for check in context_health["checks"]}
    assert check_statuses["industry_context"] == "strong"
    assert check_statuses["service_focus"] == "strong"
    assert check_statuses["target_customer_context"] == "weak"

    prompt_preview = payload["competitor_prompt_preview"]
    assert prompt_preview is not None


def test_recommendation_workspace_summary_context_health_strong_when_location_industry_service_and_target_are_grounded(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    patch_site = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "primary_location": "Loveland, Colorado",
            "industry": "Residential and commercial construction",
        },
    )
    assert patch_site.status_code == 200

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    context_health = payload["competitor_context_health"]
    assert context_health is not None
    assert context_health["status"] == "strong"
    check_statuses = {check["key"]: check["status"] for check in context_health["checks"]}
    assert check_statuses == {
        "location_context": "strong",
        "industry_context": "strong",
        "service_focus": "strong",
        "target_customer_context": "strong",
    }


def test_recommendation_workspace_summary_context_health_mixed_when_location_is_weak_but_industry_service_are_grounded(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    patch_site = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"industry": "Residential and commercial construction"},
    )
    assert patch_site.status_code == 200

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    context_health = payload["competitor_context_health"]
    assert context_health is not None
    assert context_health["status"] == "mixed"
    check_statuses = {check["key"]: check["status"] for check in context_health["checks"]}
    assert check_statuses["location_context"] == "weak"
    assert check_statuses["industry_context"] == "strong"
    assert check_statuses["service_focus"] == "strong"
    assert check_statuses["target_customer_context"] == "weak"


def test_recommendation_workspace_summary_groups_recommendations_by_theme_without_changing_flat_order(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(db_session, business_id=seeded_business.id, site_id=site_id)
    comparison_run_id = _seed_completed_comparison_run(db_session, business_id=seeded_business.id, site_id=site_id)

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id, "comparison_run_id": comparison_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    recommendation_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recommendation_list.status_code == 200
    items = recommendation_list.json()["items"]
    assert len(items) >= 3
    recommendation_ids = [item["id"] for item in items]

    recommendation_one = db_session.get(SEORecommendation, recommendation_ids[0])
    recommendation_two = db_session.get(SEORecommendation, recommendation_ids[1])
    recommendation_three = db_session.get(SEORecommendation, recommendation_ids[2])
    assert recommendation_one is not None
    assert recommendation_two is not None
    assert recommendation_three is not None

    recommendation_one.rule_key = "close_competitor_gap_missing_license_proof"
    recommendation_one.title = "Publish license and insurance trust proof"
    recommendation_one.evidence_json = {
        "sources": ["comparison"],
        "finding_types": ["missing_license_proof"],
    }

    recommendation_two.rule_key = "add_project_story_portfolio_proof"
    recommendation_two.title = "Publish recent project stories with before/after proof"
    recommendation_two.evidence_json = {
        "sources": ["audit"],
        "finding_types": ["missing_project_story"],
    }

    recommendation_three.rule_key = "association_membership_gap"
    recommendation_three.title = "Show association memberships and press mentions"
    recommendation_three.evidence_json = {
        "sources": ["comparison"],
        "finding_types": ["association_membership_gap"],
    }
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()

    flat_ids = [item["id"] for item in payload["recommendations"]["items"]]
    assert flat_ids == recommendation_ids

    grouped = payload["grouped_recommendations"]
    assert grouped
    expected_theme_order = [
        "trust_and_legitimacy",
        "experience_and_proof",
        "authority_and_visibility",
        "expertise_and_process",
        "general_site_improvement",
    ]
    grouped_theme_positions = [expected_theme_order.index(group["theme"]) for group in grouped]
    assert grouped_theme_positions == sorted(grouped_theme_positions)

    flat_index_by_id = {recommendation_id: index for index, recommendation_id in enumerate(flat_ids)}
    grouped_ids = []
    for group in grouped:
        ids = group["recommendation_ids"]
        assert ids == sorted(ids, key=lambda recommendation_id: flat_index_by_id[recommendation_id])
        grouped_ids.extend(ids)

    assert set(grouped_ids) == set(flat_ids)
    assert payload["start_here"] is not None
    assert payload["start_here"]["recommendation_id"] == grouped[0]["recommendation_ids"][0]
    assert payload["start_here"]["theme"] == grouped[0]["theme"]
    assert payload["start_here"]["theme_label"] == grouped[0]["label"]


def test_recommendation_workspace_summary_includes_latest_narrative_and_bounded_suggestions(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    recommendation_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recommendation_list.status_code == 200
    recommendation_id = recommendation_list.json()["items"][0]["id"]

    db_session.add(
        SEORecommendationNarrative(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            recommendation_run_id=run_id,
            version=1,
            status="completed",
            narrative_text="Narrative summary.",
            top_themes_json=["seo"],
            sections_json={
                "tuning_suggestions": [
                    {
                        "setting": "competitor_candidate_min_relevance_score",
                        "current_value": 35,
                        "recommended_value": 30,
                        "reason": "High low-relevance exclusions",
                        "linked_recommendation_ids": [recommendation_id, "rec-unknown"],
                        "confidence": "medium",
                    },
                    {
                        "setting": "not_allowed_setting",
                        "current_value": 1,
                        "recommended_value": 2,
                        "reason": "ignore",
                        "linked_recommendation_ids": [recommendation_id],
                        "confidence": "high",
                    },
                ]
            },
            provider_name="mock",
            model_name="mock-model",
            prompt_version="seo-recommendation-narrative-v2",
            error_message=None,
            created_by_principal_id="principal-1",
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["state"] == "completed_with_narrative"
    assert payload["latest_narrative"] is not None
    assert payload["latest_narrative"]["recommendation_run_id"] == run_id
    assert len(payload["tuning_suggestions"]) == 1
    assert payload["tuning_suggestions"][0]["setting"] == "competitor_candidate_min_relevance_score"
    assert payload["tuning_suggestions"][0]["linked_recommendation_ids"] == [recommendation_id]
    assert payload["apply_outcome"] is None
    assert payload["analysis_freshness"]["status"] == "fresh"
    assert payload["competitor_prompt_preview"] is not None
    assert payload["recommendation_prompt_preview"] is not None


def test_recommendation_workspace_summary_derives_eeat_categories_and_gap_summary_from_competitor_signals(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    recommendation_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recommendation_list.status_code == 200
    recommendation_id = recommendation_list.json()["items"][0]["id"]
    recommendation = db_session.get(SEORecommendation, recommendation_id)
    assert recommendation is not None
    recommendation.rule_key = "close_competitor_gap_missing_license_proof"
    recommendation.title = "Add license and insurance proof to service pages"
    recommendation.evidence_json = {
        "sources": ["comparison"],
        "finding_types": ["missing_license_proof"],
        "counts": {"missing_license_proof": 1},
    }
    db_session.add(recommendation)

    db_session.add(
        SEORecommendationNarrative(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            recommendation_run_id=run_id,
            version=1,
            status="completed",
            narrative_text="Narrative summary.",
            top_themes_json=["trust proof"],
            sections_json={
                "competitor_influence": {
                    "used": True,
                    "summary": "Competitors show stronger trust proof.",
                    "top_opportunities": ["Add verified_review badges and license proof"],
                    "competitor_names": ["Trusted Local Co"],
                }
            },
            provider_name="mock",
            model_name="mock-model",
            prompt_version="seo-recommendation-narrative-v2",
            error_message=None,
            created_by_principal_id="principal-1",
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["recommendations"]["items"][0]["eeat_categories"] == ["trustworthiness"]
    assert payload["recommendations"]["items"][0]["primary_eeat_category"] == "trustworthiness"
    assert "competitor_gap" in payload["recommendations"]["items"][0]["priority_reasons"]
    assert "trust_gap" in payload["recommendations"]["items"][0]["priority_reasons"]
    assert (
        payload["recommendations"]["items"][0]["recommendation_evidence_summary"]
        == "Competitors show stronger trust signals in this area."
    )
    assert "license and insurance proof" in payload["recommendations"]["items"][0]["recommendation_action_clarity"].lower()
    assert "trust" in payload["recommendations"]["items"][0]["recommendation_expected_outcome"].lower()
    assert payload["eeat_gap_summary"] is not None
    assert "trustworthiness" in payload["eeat_gap_summary"]["top_gap_categories"]
    assert payload["eeat_gap_summary"]["message"]
    assert payload["ordering_explanation"] is not None
    assert "Competitor-backed" in payload["ordering_explanation"]["message"]


def test_recommendation_workspace_summary_omits_eeat_gap_summary_when_competitor_signals_are_insufficient(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    recommendation_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recommendation_list.status_code == 200
    recommendation_id = recommendation_list.json()["items"][0]["id"]
    recommendation = db_session.get(SEORecommendation, recommendation_id)
    assert recommendation is not None
    recommendation.rule_key = "fix_missing_title_tags"
    recommendation.evidence_json = {
        "sources": ["audit"],
        "finding_types": ["missing_title"],
        "counts": {"missing_title": 1},
    }
    db_session.add(recommendation)
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["recommendations"]["items"][0]["eeat_categories"] == []
    assert payload["recommendations"]["items"][0]["primary_eeat_category"] is None
    assert payload["recommendations"]["items"][0]["priority_reasons"] in ([], ["high_clarity_action"])
    assert payload["eeat_gap_summary"] is None
    assert payload["ordering_explanation"] is not None


def test_recommendation_workspace_summary_includes_latest_apply_outcome(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    recommendation_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recommendation_list.status_code == 200
    recommendation = recommendation_list.json()["items"][0]
    recommendation_id = recommendation["id"]
    recommendation_title = recommendation["title"]

    narrative_id = str(uuid4())
    db_session.add(
        SEORecommendationNarrative(
            id=narrative_id,
            business_id=seeded_business.id,
            site_id=site_id,
            recommendation_run_id=run_id,
            version=1,
            status="completed",
            narrative_text="Narrative summary.",
            top_themes_json=["seo"],
            sections_json={
                "tuning_suggestions": [
                    {
                        "setting": "competitor_candidate_min_relevance_score",
                        "current_value": 35,
                        "recommended_value": 30,
                        "reason": "High low-relevance exclusions",
                        "linked_recommendation_ids": [recommendation_id],
                        "confidence": "medium",
                    }
                ]
            },
            provider_name="mock",
            model_name="mock-model",
            prompt_version="seo-recommendation-narrative-v2",
            error_message=None,
            created_by_principal_id="principal-1",
        )
    )
    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            source_narrative_id=narrative_id,
            source_recommendation_run_id=run_id,
            preview_request={
                "current_values": {
                    "competitor_candidate_min_relevance_score": 35,
                    "competitor_candidate_big_box_penalty": 20,
                    "competitor_candidate_directory_penalty": 35,
                    "competitor_candidate_local_alignment_bonus": 10,
                },
                "proposed_values": {
                    "competitor_candidate_min_relevance_score": 30,
                    "competitor_candidate_big_box_penalty": 20,
                    "competitor_candidate_directory_penalty": 35,
                    "competitor_candidate_local_alignment_bonus": 10,
                },
            },
            preview_response={
                "current_values": {
                    "competitor_candidate_min_relevance_score": 35,
                    "competitor_candidate_big_box_penalty": 20,
                    "competitor_candidate_directory_penalty": 35,
                    "competitor_candidate_local_alignment_bonus": 10,
                },
                "proposed_values": {
                    "competitor_candidate_min_relevance_score": 30,
                    "competitor_candidate_big_box_penalty": 20,
                    "competitor_candidate_directory_penalty": 35,
                    "competitor_candidate_local_alignment_bonus": 10,
                },
                "estimated_impact": {
                    "summary": "Estimated increase of 2 included candidates over the last 30 days of telemetry."
                },
            },
            applied_at=utc_now(),
            evaluated_generation_run_id=None,
            evaluated_at=None,
            estimated_included_delta=None,
            actual_included_delta=None,
            error_margin=None,
            direction_correct=None,
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["apply_outcome"] is not None
    assert payload["analysis_freshness"]["status"] == "pending_refresh"
    assert payload["analysis_freshness"]["analysis_generated_at"] is not None
    assert payload["analysis_freshness"]["last_apply_at"] is not None
    assert payload["ordering_explanation"] is not None
    assert "pending_refresh_context" in payload["ordering_explanation"]["context_reasons"]
    assert payload["start_here"] is not None
    assert "pending_refresh_context" in payload["start_here"]["context_flags"]
    assert payload["apply_outcome"]["applied"] is True
    assert payload["apply_outcome"]["source"] == "recommendation"
    assert payload["apply_outcome"]["recommendation_label"] == recommendation_title
    assert (
        payload["apply_outcome"]["expected_change"]
        == "Estimated increase of 2 included candidates over the last 30 days of telemetry."
    )
    assert payload["apply_outcome"]["reflected_on_next_run"]
    assert payload["apply_outcome"]["applied_at"] is not None
    assert payload["recommendations"]["items"][0]["recommendation_progress_status"] == "applied_pending_refresh"
    assert (
        payload["recommendations"]["items"][0]["recommendation_progress_summary"]
        == "Applied. Waiting for the next analysis refresh to reflect this change."
    )


def test_recommendation_workspace_summary_handles_partial_apply_metadata_safely(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201

    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            source_narrative_id=None,
            source_recommendation_run_id=None,
            preview_request={},
            preview_response={"estimated_impact": {}},
            applied_at=utc_now(),
            evaluated_generation_run_id=None,
            evaluated_at=None,
            estimated_included_delta=None,
            actual_included_delta=None,
            error_margin=None,
            direction_correct=None,
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["apply_outcome"] is not None
    assert payload["apply_outcome"]["applied"] is True
    assert payload["apply_outcome"]["expected_change"]
    assert payload["apply_outcome"]["reflected_on_next_run"]
    assert payload["analysis_freshness"]["status"] == "pending_refresh"
    assert payload["start_here"] is not None
    assert payload["start_here"]["context_flags"]


def test_recommendation_workspace_summary_handles_in_progress_runs_safely(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )

    running_run = SEORecommendationRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site_id,
        audit_run_id=audit_run_id,
        comparison_run_id=None,
        status="running",
        total_recommendations=0,
        critical_recommendations=0,
        warning_recommendations=0,
        info_recommendations=0,
        category_counts_json={},
        effort_bucket_counts_json={},
        started_at=utc_now(),
        created_by_principal_id="principal-1",
    )
    db_session.add(running_run)
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["state"] == "no_completed_runs"
    assert payload["latest_run"]["id"] == running_run.id
    assert payload["latest_completed_run"] is None
    assert payload["recommendations"]["total"] == 0
    assert payload["latest_narrative"] is None
    assert payload["apply_outcome"] is None
    assert payload["start_here"] is None
    assert payload["analysis_freshness"]["status"] == "unknown"
    assert payload["analysis_freshness"]["analysis_generated_at"] is None
    assert payload["competitor_prompt_preview"] is not None
    assert payload["recommendation_prompt_preview"] is None


def test_recommendation_workspace_summary_marks_fresh_when_apply_is_older_than_analysis(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    run = db_session.get(SEORecommendationRun, run_id)
    assert run is not None
    run.completed_at = utc_now()
    db_session.add(run)
    db_session.flush()

    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            source_narrative_id=None,
            source_recommendation_run_id=run_id,
            preview_request={},
            preview_response={},
            applied_at=run.completed_at - timedelta(minutes=5),
            evaluated_generation_run_id=None,
            evaluated_at=None,
            estimated_included_delta=None,
            actual_included_delta=None,
            error_margin=None,
            direction_correct=None,
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["analysis_freshness"]["status"] == "fresh"
    assert payload["analysis_freshness"]["analysis_generated_at"] is not None
    assert payload["analysis_freshness"]["last_apply_at"] is not None
    assert payload["start_here"] is not None
    assert payload["start_here"]["context_flags"] == []
    assert payload["recommendations"]["items"][0]["recommendation_progress_status"] == "suggested"


def test_recommendation_workspace_summary_marks_reflected_when_apply_link_is_fresh(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    audit_run_id = _seed_completed_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
    )
    run_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs",
        json={"audit_run_id": audit_run_id},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    recommendation_list = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendation-runs/{run_id}/recommendations"
    )
    assert recommendation_list.status_code == 200
    recommendation = recommendation_list.json()["items"][0]
    recommendation_id = recommendation["id"]

    narrative_id = str(uuid4())
    db_session.add(
        SEORecommendationNarrative(
            id=narrative_id,
            business_id=seeded_business.id,
            site_id=site_id,
            recommendation_run_id=run_id,
            version=1,
            status="completed",
            narrative_text="Narrative summary.",
            top_themes_json=["seo"],
            sections_json={
                "tuning_suggestions": [
                    {
                        "setting": "competitor_candidate_min_relevance_score",
                        "current_value": 35,
                        "recommended_value": 30,
                        "reason": "High low-relevance exclusions",
                        "linked_recommendation_ids": [recommendation_id],
                        "confidence": "medium",
                    }
                ]
            },
            provider_name="mock",
            model_name="mock-model",
            prompt_version="seo-recommendation-narrative-v2",
            error_message=None,
            created_by_principal_id="principal-1",
        )
    )
    run = db_session.get(SEORecommendationRun, run_id)
    assert run is not None
    run.completed_at = utc_now()
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            source_narrative_id=narrative_id,
            source_recommendation_run_id=run_id,
            preview_request={
                "current_values": {
                    "competitor_candidate_min_relevance_score": 35,
                },
                "proposed_values": {
                    "competitor_candidate_min_relevance_score": 30,
                },
            },
            preview_response={
                "current_values": {
                    "competitor_candidate_min_relevance_score": 35,
                },
                "proposed_values": {
                    "competitor_candidate_min_relevance_score": 30,
                },
            },
            applied_at=run.completed_at - timedelta(minutes=5),
            evaluated_generation_run_id=None,
            evaluated_at=None,
            estimated_included_delta=None,
            actual_included_delta=None,
            error_margin=None,
            direction_correct=None,
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["analysis_freshness"]["status"] == "fresh"
    assert payload["recommendations"]["items"][0]["recommendation_progress_status"] == "reflected_in_latest_analysis"
    assert (
        payload["recommendations"]["items"][0]["recommendation_progress_summary"]
        == "Applied and reflected in the latest analysis."
    )


def test_recommendation_workspace_summary_marks_unknown_when_no_analysis_exists(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["state"] == "no_runs"
    assert payload["start_here"] is None
    assert payload["analysis_freshness"]["status"] == "unknown"
    assert payload["analysis_freshness"]["analysis_generated_at"] is None
    assert payload["analysis_freshness"]["last_apply_at"] is None


def test_recommendation_workspace_summary_marks_unknown_when_apply_exists_without_analysis(
    db_session, seeded_business
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=seeded_business.id,
            site_id=site_id,
            source_narrative_id=None,
            source_recommendation_run_id=None,
            preview_request={},
            preview_response={},
            applied_at=utc_now(),
            evaluated_generation_run_id=None,
            evaluated_at=None,
            estimated_included_delta=None,
            actual_included_delta=None,
            error_margin=None,
            direction_correct=None,
        )
    )
    db_session.commit()

    summary = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["start_here"] is None
    assert payload["analysis_freshness"]["status"] == "unknown"
    assert payload["analysis_freshness"]["analysis_generated_at"] is None
    assert payload["analysis_freshness"]["last_apply_at"] is not None


def test_recommendation_workspace_summary_enforces_business_scope(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    summary = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/recommendations/workspace-summary"
    )
    assert summary.status_code == 404

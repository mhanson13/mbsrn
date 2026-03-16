from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_competitor_summary_provider,
    get_tenant_context,
)
from app.api.routes.seo import router as seo_router
from app.integrations.seo_summary_provider import (
    SEOCompetitorComparisonSummaryOutput,
    SEOCompetitorComparisonSummaryProvider,
)
from app.models.business import Business
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun


SUMMARY_RESPONSE_KEYS = {
    "id",
    "business_id",
    "site_id",
    "competitor_set_id",
    "comparison_run_id",
    "version",
    "status",
    "overall_gap_summary",
    "top_gaps_json",
    "plain_english_explanation",
    "provider_name",
    "model_name",
    "prompt_version",
    "error_summary",
    "created_by_principal_id",
    "created_at",
    "updated_at",
}


class _FailingCompetitorSummaryProvider:
    def generate_summary(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("provider unavailable")


class _CapturingCompetitorSummaryProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_summary(
        self,
        *,
        run,
        findings,
        metric_rollups,
        findings_by_type,
        findings_by_category,
        findings_by_severity,
    ) -> SEOCompetitorComparisonSummaryOutput:
        self.calls.append(
            {
                "run_id": run.id,
                "competitor_pages_analyzed": run.competitor_pages_analyzed,
                "metric_rollups": metric_rollups,
                "findings_count": len(findings),
                "findings_by_type": findings_by_type,
                "findings_by_category": findings_by_category,
                "findings_by_severity": findings_by_severity,
            }
        )
        sentinel_metric_count = len(metric_rollups)
        sentinel_pages = run.competitor_pages_analyzed
        return SEOCompetitorComparisonSummaryOutput(
            overall_gap_summary=(
                f"grounded metric_count={sentinel_metric_count} competitor_pages={sentinel_pages}"
            ),
            top_gaps=["grounded_gap_a", "grounded_gap_b"],
            plain_english_explanation="grounded deterministic summary",
            provider_name="capturing-test-provider",
            model_name="capturing-test-model",
            prompt_version="seo-competitor-summary-v1",
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
    summary_provider: SEOCompetitorComparisonSummaryProvider | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    if summary_provider is not None:
        app.dependency_overrides[get_seo_competitor_summary_provider] = lambda: summary_provider
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


def _create_site_set_domain_snapshot(client: TestClient, business_id: str) -> tuple[str, str, str, str]:
    create_site = client.post(
        f"/api/businesses/{business_id}/seo/sites",
        json={"display_name": "Client Site", "base_url": "https://client.example/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    create_set = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Set A"},
    )
    assert create_set.status_code == 201
    competitor_set_id = create_set.json()["id"]

    add_domain = client.post(
        f"/api/businesses/{business_id}/seo/competitor-sets/{competitor_set_id}/domains",
        json={"domain": "competitor.example"},
    )
    assert add_domain.status_code == 201
    competitor_domain_id = add_domain.json()["id"]

    snapshot_run = client.post(
        f"/api/businesses/{business_id}/seo/competitor-sets/{competitor_set_id}/snapshot-runs",
        json={"max_domains": 10, "max_pages_per_domain": 5, "max_depth": 1},
    )
    assert snapshot_run.status_code == 201
    snapshot_run_id = snapshot_run.json()["id"]

    return site_id, competitor_set_id, competitor_domain_id, snapshot_run_id


def _mark_snapshot_completed(db_session, *, snapshot_run_id: str) -> SEOCompetitorSnapshotRun:
    snapshot_run = db_session.get(SEOCompetitorSnapshotRun, snapshot_run_id)
    assert snapshot_run is not None
    snapshot_run.status = "completed"
    snapshot_run.domains_completed = max(1, snapshot_run.domains_targeted)
    db_session.add(snapshot_run)
    db_session.flush()
    return snapshot_run


def _seed_snapshot_page(
    db_session,
    *,
    business_id: str,
    site_id: str,
    competitor_set_id: str,
    snapshot_run_id: str,
    competitor_domain_id: str,
    url: str,
    title: str | None,
    meta_description: str | None,
    h1_count: int,
    word_count: int,
    canonical_url: str | None,
    internal_link_count: int = 2,
) -> SEOCompetitorSnapshotPage:
    page = SEOCompetitorSnapshotPage(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set_id,
        snapshot_run_id=snapshot_run_id,
        competitor_domain_id=competitor_domain_id,
        url=url,
        status_code=200,
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        h1_json=["H1"] * h1_count,
        h2_json=["H2"],
        word_count=word_count,
        internal_link_count=internal_link_count,
    )
    db_session.add(page)
    db_session.flush()
    return page


def _seed_baseline_audit_run(
    db_session,
    *,
    business_id: str,
    site_id: str,
) -> SEOAuditRun:
    run = SEOAuditRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        max_pages=25,
        max_depth=2,
        pages_discovered=2,
        pages_crawled=2,
    )
    db_session.add(run)
    db_session.flush()

    page_a = SEOAuditPage(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        audit_run_id=run.id,
        url="https://client.example/page-a",
        status_code=200,
        title=None,
        meta_description=None,
        canonical_url=None,
        h1_json=[],
        h2_json=["H2"],
        word_count=80,
        internal_link_count=0,
    )
    page_b = SEOAuditPage(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        audit_run_id=run.id,
        url="https://client.example/page-b",
        status_code=200,
        title="Client page",
        meta_description="client desc",
        canonical_url="https://client.example/page-b",
        h1_json=["H1"],
        h2_json=["H2"],
        word_count=220,
        internal_link_count=2,
    )
    db_session.add_all([page_a, page_b])
    db_session.flush()

    db_session.add(
        SEOAuditFinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=run.id,
            page_id=page_a.id,
            finding_type="missing_title",
            category="SEO",
            severity="CRITICAL",
            title="missing title",
            details="missing title",
            rule_key="missing_title",
            suggested_fix=None,
        )
    )
    db_session.flush()
    return run


def _create_completed_comparison_run(client: TestClient, db_session, business_id: str) -> tuple[str, str]:
    site_id, competitor_set_id, competitor_domain_id, snapshot_run_id = _create_site_set_domain_snapshot(client, business_id)
    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)
    _seed_snapshot_page(
        db_session,
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set_id,
        snapshot_run_id=snapshot_run.id,
        competitor_domain_id=competitor_domain_id,
        url="https://competitor.example/",
        title="Home",
        meta_description="desc",
        h1_count=1,
        word_count=180,
        canonical_url="https://competitor.example/",
        internal_link_count=2,
    )
    baseline = _seed_baseline_audit_run(db_session, business_id=business_id, site_id=site_id)
    db_session.commit()

    create_comparison = client.post(
        f"/api/businesses/{business_id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id, "baseline_audit_run_id": baseline.id},
    )
    assert create_comparison.status_code == 201
    return create_comparison.json()["id"], competitor_set_id


def test_competitor_summary_manual_trigger_success_and_retrieval(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    run_id, _ = _create_completed_comparison_run(client, db_session, seeded_business.id)

    report_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/report")
    assert report_response.status_code == 200
    metric_count = len(report_response.json()["rollups"]["metric_rollups"])

    create_summary = client.post(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summarize")
    assert create_summary.status_code == 201
    summary = create_summary.json()
    assert set(summary.keys()) == SUMMARY_RESPONSE_KEYS
    assert summary["status"] == "completed"
    assert summary["version"] == 1
    assert f"across {metric_count} deterministic metrics" in summary["overall_gap_summary"]
    assert isinstance(summary["top_gaps_json"], list)
    assert summary["comparison_run_id"] == run_id
    assert summary["provider_name"] == "mock"
    assert summary["model_name"]
    assert summary["prompt_version"]
    assert summary["error_summary"] is None

    list_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summaries")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    assert set(list_payload["items"][0].keys()) == SUMMARY_RESPONSE_KEYS

    latest_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summaries/latest")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["id"] == summary["id"]
    assert set(latest_payload.keys()) == SUMMARY_RESPONSE_KEYS

    by_id = client.get(
        f"/api/businesses/{seeded_business.id}/seo/comparison-summaries/{summary['id']}"
    )
    assert by_id.status_code == 200
    by_id_payload = by_id.json()
    assert by_id_payload["id"] == summary["id"]
    assert set(by_id_payload.keys()) == SUMMARY_RESPONSE_KEYS


def test_competitor_summary_failure_is_isolated_and_persisted(db_session, seeded_business) -> None:
    success_client = _make_client(db_session, business_id=seeded_business.id)
    run_id, _ = _create_completed_comparison_run(success_client, db_session, seeded_business.id)

    report_before = success_client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/report")
    assert report_before.status_code == 200
    findings_total_before = report_before.json()["findings"]["total"]

    first_summary = success_client.post(
        f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summarize"
    )
    assert first_summary.status_code == 201
    assert first_summary.json()["version"] == 1

    failing_client = _make_client(
        db_session,
        business_id=seeded_business.id,
        summary_provider=_FailingCompetitorSummaryProvider(),
    )
    failed_summary = failing_client.post(
        f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summarize"
    )
    assert failed_summary.status_code == 422

    report_after = success_client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/report")
    assert report_after.status_code == 200
    assert report_after.json()["findings"]["total"] == findings_total_before

    summaries = (
        db_session.query(SEOCompetitorComparisonSummary)
        .filter(SEOCompetitorComparisonSummary.comparison_run_id == run_id)
        .order_by(SEOCompetitorComparisonSummary.version.asc())
        .all()
    )
    assert [item.version for item in summaries] == [1, 2]
    assert [item.status for item in summaries] == ["completed", "failed"]
    assert summaries[1].error_summary is not None

    list_response = success_client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summaries")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    versions = [item["version"] for item in list_payload["items"]]
    statuses = [item["status"] for item in list_payload["items"]]
    assert versions == [1, 2]
    assert statuses == ["completed", "failed"]

    latest_response = success_client.get(
        f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summaries/latest"
    )
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["version"] == 2
    assert latest_payload["status"] == "failed"
    assert latest_payload["error_summary"] is not None


def test_competitor_summary_business_isolation_and_invalid_lineage(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    run_id, _ = _create_completed_comparison_run(client, db_session, seeded_business.id)

    create_summary = client.post(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summarize")
    assert create_summary.status_code == 201
    summary_id = create_summary.json()["id"]

    cross_tenant_trigger = client.post(f"/api/businesses/{other_business.id}/seo/comparison-runs/{run_id}/summarize")
    assert cross_tenant_trigger.status_code == 404

    cross_tenant_latest = client.get(
        f"/api/businesses/{other_business.id}/seo/comparison-runs/{run_id}/summaries/latest"
    )
    assert cross_tenant_latest.status_code == 404

    cross_tenant_by_id = client.get(
        f"/api/businesses/{other_business.id}/seo/comparison-summaries/{summary_id}"
    )
    assert cross_tenant_by_id.status_code == 404

    invalid_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{uuid4()}/summarize"
    )
    assert invalid_run.status_code == 404


def test_competitor_summary_is_grounded_in_persisted_comparison_outputs_only(db_session, seeded_business) -> None:
    capturing_provider = _CapturingCompetitorSummaryProvider()
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        summary_provider=capturing_provider,
    )
    run_id, _ = _create_completed_comparison_run(client, db_session, seeded_business.id)

    run = db_session.get(SEOCompetitorComparisonRun, run_id)
    assert run is not None
    run.metric_rollups_json = {
        "sentinel_metric": {
            "title": "Sentinel metric",
            "category": "TECHNICAL",
            "unit": "count",
            "higher_is_better": True,
            "client_value": 9,
            "competitor_value": 3,
            "delta": 6,
            "severity": "INFO",
            "gap_direction": "client_leads",
        }
    }
    run.finding_type_counts_json = {"sentinel_gap": 7}
    run.category_counts_json = {"TECHNICAL": 7}
    run.severity_counts_json = {"INFO": 7}
    run.competitor_pages_analyzed = 77
    db_session.add(run)
    db_session.commit()

    summary_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/summarize"
    )
    assert summary_response.status_code == 201
    payload = summary_response.json()
    assert payload["status"] == "completed"
    assert payload["provider_name"] == "capturing-test-provider"
    assert "metric_count=1" in payload["overall_gap_summary"]
    assert "competitor_pages=77" in payload["overall_gap_summary"]

    assert len(capturing_provider.calls) == 1
    call = capturing_provider.calls[0]
    assert call["run_id"] == run_id
    assert call["competitor_pages_analyzed"] == 77
    assert call["metric_rollups"] == run.metric_rollups_json
    assert call["findings_by_type"] == {"sentinel_gap": 7}
    assert call["findings_by_category"] == {"TECHNICAL": 7}
    assert call["findings_by_severity"] == {"INFO": 7}

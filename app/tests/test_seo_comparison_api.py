from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.models.business import Business
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun


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
    page_count: int,
    finding_counts: dict[str, int],
) -> SEOAuditRun:
    run = SEOAuditRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        max_pages=25,
        max_depth=2,
        pages_discovered=page_count,
        pages_crawled=page_count,
    )
    db_session.add(run)
    db_session.flush()

    pages: list[SEOAuditPage] = []
    for idx in range(page_count):
        page = SEOAuditPage(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=run.id,
            url=f"https://client.example/page-{idx}",
            status_code=200,
            title=f"Page {idx}",
            meta_description="desc",
            canonical_url=f"https://client.example/page-{idx}",
            h1_json=["H1"],
            h2_json=["H2"],
            word_count=250,
            internal_link_count=2,
        )
        db_session.add(page)
        pages.append(page)
    db_session.flush()

    first_page_id = pages[0].id if pages else None
    for finding_type, count in finding_counts.items():
        for _ in range(count):
            db_session.add(
                SEOAuditFinding(
                    id=str(uuid4()),
                    business_id=business_id,
                    site_id=site_id,
                    audit_run_id=run.id,
                    page_id=first_page_id,
                    finding_type=finding_type,
                    category="SEO" if "title" in finding_type or "meta" in finding_type else "TECHNICAL",
                    severity="WARNING",
                    title=finding_type,
                    details=finding_type,
                    rule_key=finding_type,
                    suggested_fix=None,
                )
            )
    db_session.flush()
    return run


def test_deterministic_comparison_run_outputs_expected_metrics(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, competitor_set_id, competitor_domain_id, snapshot_run_id = _create_site_set_domain_snapshot(
        client,
        seeded_business.id,
    )

    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        competitor_set_id=competitor_set_id,
        snapshot_run_id=snapshot_run.id,
        competitor_domain_id=competitor_domain_id,
        url="https://competitor.example/",
        title=None,
        meta_description=None,
        h1_count=0,
        word_count=100,
        canonical_url=None,
    )
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        competitor_set_id=competitor_set_id,
        snapshot_run_id=snapshot_run.id,
        competitor_domain_id=competitor_domain_id,
        url="https://competitor.example/services",
        title="Service",
        meta_description=None,
        h1_count=1,
        word_count=250,
        canonical_url="https://competitor.example/services",
        internal_link_count=0,
    )
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        competitor_set_id=competitor_set_id,
        snapshot_run_id=snapshot_run.id,
        competitor_domain_id=competitor_domain_id,
        url="https://competitor.example/about",
        title="About",
        meta_description="About competitor",
        h1_count=1,
        word_count=190,
        canonical_url=None,
    )
    baseline_run = _seed_baseline_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        page_count=2,
        finding_counts={
            "missing_title": 2,
            "missing_meta_description": 1,
            "missing_h1": 1,
            "thin_content": 1,
            "missing_canonical": 1,
        },
    )
    baseline_pages = (
        db_session.query(SEOAuditPage)
        .filter(SEOAuditPage.audit_run_id == baseline_run.id)
        .order_by(SEOAuditPage.url.asc())
        .all()
    )
    assert len(baseline_pages) == 2
    baseline_pages[0].title = None
    baseline_pages[0].meta_description = None
    baseline_pages[0].h1_json = []
    baseline_pages[0].word_count = 80
    baseline_pages[0].canonical_url = None
    baseline_pages[0].internal_link_count = 0
    baseline_pages[1].title = None
    db_session.commit()

    create_comparison = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run_id, "baseline_audit_run_id": baseline_run.id},
    )
    assert create_comparison.status_code == 201
    run_payload = create_comparison.json()
    assert run_payload["status"] == "completed"
    assert run_payload["client_pages_analyzed"] == 2
    assert run_payload["competitor_pages_analyzed"] == 3
    assert run_payload["severity_counts_json"]["CRITICAL"] >= 1
    assert "page_count_gap" in run_payload["finding_type_counts_json"]
    run_id = run_payload["id"]

    findings_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/findings")
    assert findings_response.status_code == 200
    payload = findings_response.json()
    assert payload["total"] >= 10
    assert payload["by_severity"]["WARNING"] >= 1

    findings_by_type = {item["finding_type"]: item for item in payload["items"]}
    assert findings_by_type["page_count_gap"]["client_value"] == "2"
    assert findings_by_type["page_count_gap"]["competitor_value"] == "3"
    assert findings_by_type["page_count_gap"]["gap_direction"] == "client_trails"

    assert findings_by_type["missing_title_count_gap"]["client_value"] == "2"
    assert findings_by_type["missing_title_count_gap"]["competitor_value"] == "1"
    assert findings_by_type["missing_title_count_gap"]["gap_direction"] == "client_trails"
    assert findings_by_type["meta_description_coverage_percent_gap"]["rule_key"] == (
        "comparison_meta_description_coverage_percent"
    )


def test_comparison_run_rejects_invalid_lineage_references(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, competitor_set_id, _, snapshot_run_id = _create_site_set_domain_snapshot(client, seeded_business.id)
    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)

    foreign_baseline_run = _seed_baseline_audit_run(
        db_session,
        business_id=other_business.id,
        site_id=str(uuid4()),
        page_count=1,
        finding_counts={},
    )
    db_session.commit()

    invalid_baseline = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id, "baseline_audit_run_id": foreign_baseline_run.id},
    )
    assert invalid_baseline.status_code == 422

    cross_tenant = client.post(
        f"/api/businesses/{other_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id},
    )
    assert cross_tenant.status_code == 404

    create_set_two = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Set B"},
    )
    assert create_set_two.status_code == 201
    competitor_set_two_id = create_set_two.json()["id"]

    add_domain_set_two = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_two_id}/domains",
        json={"domain": "other-competitor.example"},
    )
    assert add_domain_set_two.status_code == 201

    wrong_set_snapshot = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_two_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id},
    )
    assert wrong_set_snapshot.status_code == 422


def test_comparison_handles_missing_baseline_and_empty_snapshot(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, competitor_set_id, competitor_domain_id, snapshot_run_id = _create_site_set_domain_snapshot(
        client,
        seeded_business.id,
    )

    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)
    db_session.commit()

    create_without_baseline = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id},
    )
    assert create_without_baseline.status_code == 201
    run_payload = create_without_baseline.json()
    run_id = run_payload["id"]
    assert run_payload["client_pages_analyzed"] == 0
    assert run_payload["competitor_pages_analyzed"] == 0

    findings_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/findings")
    assert findings_response.status_code == 200
    finding_types = {item["finding_type"] for item in findings_response.json()["items"]}
    assert "missing_client_baseline" in finding_types
    assert "empty_competitor_snapshot" in finding_types

    first_report = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/report")
    assert first_report.status_code == 200
    first_rollups = first_report.json()["rollups"]
    assert first_rollups["metric_rollups"] == []
    assert first_rollups["findings_by_type"]["missing_client_baseline"] == 1

    # Now add competitor snapshot pages but no baseline; ensure run still succeeds deterministically.
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
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
    )
    db_session.commit()

    second_comparison = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id},
    )
    assert second_comparison.status_code == 201
    second_run_id = second_comparison.json()["id"]

    second_findings = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{second_run_id}/findings")
    assert second_findings.status_code == 200
    second_types = {item["finding_type"] for item in second_findings.json()["items"]}
    assert "missing_client_baseline" in second_types
    assert "empty_competitor_snapshot" not in second_types


def test_comparison_run_requires_completed_snapshot_run(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    _, competitor_set_id, _, snapshot_run_id = _create_site_set_domain_snapshot(client, seeded_business.id)

    not_completed = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run_id},
    )
    assert not_completed.status_code == 422


def test_comparison_request_contract_requires_non_blank_snapshot_run_id(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    _, competitor_set_id, _, _ = _create_site_set_domain_snapshot(client, seeded_business.id)

    blank_snapshot_id = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": "   "},
    )
    assert blank_snapshot_id.status_code == 422

    unknown_field = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": str(uuid4()), "unexpected": "value"},
    )
    assert unknown_field.status_code == 422


def test_comparison_report_endpoint_returns_run_and_findings(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, competitor_set_id, competitor_domain_id, snapshot_run_id = _create_site_set_domain_snapshot(
        client,
        seeded_business.id,
    )
    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
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
    )
    db_session.commit()

    create_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run_id},
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    report_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{run_id}/report")
    assert report_response.status_code == 200
    report = report_response.json()
    assert set(report.keys()) == {"run", "rollups", "findings"}
    assert report["run"]["id"] == run_id
    assert report["findings"]["total"] >= 1
    assert report["rollups"]["client_pages_analyzed"] >= 0
    assert report["rollups"]["competitor_pages_analyzed"] >= 1
    assert report["rollups"]["findings_by_category"]
    assert report["rollups"]["findings_by_severity"]
    assert isinstance(report["rollups"]["metric_rollups"], list)
    assert report["rollups"]["findings_by_type"]["missing_client_baseline"] == 1

    cross_tenant_report = client.get(f"/api/businesses/{other_business.id}/seo/comparison-runs/{run_id}/report")
    assert cross_tenant_report.status_code == 404

    cross_tenant_run = client.get(f"/api/businesses/{other_business.id}/seo/comparison-runs/{run_id}")
    assert cross_tenant_run.status_code == 404

    cross_tenant_findings = client.get(f"/api/businesses/{other_business.id}/seo/comparison-runs/{run_id}/findings")
    assert cross_tenant_findings.status_code == 404


def test_phase2_v1_site_scoped_comparison_routes(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, competitor_set_id, competitor_domain_id, snapshot_run_id = _create_site_set_domain_snapshot(
        client,
        seeded_business.id,
    )
    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
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
    )
    baseline_run = _seed_baseline_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        page_count=2,
        finding_counts={},
    )
    db_session.commit()

    create_run = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-comparison-runs",
        json={
            "competitor_set_id": competitor_set_id,
            "snapshot_run_id": snapshot_run.id,
            "baseline_audit_run_id": baseline_run.id,
        },
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]

    list_runs = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-comparison-runs")
    assert list_runs.status_code == 200
    assert list_runs.json()["total"] >= 1

    get_run = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-comparison-runs/{run_id}"
    )
    assert get_run.status_code == 200

    findings = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-comparison-runs/{run_id}/findings"
    )
    assert findings.status_code == 200

    report = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-comparison-runs/{run_id}/report"
    )
    assert report.status_code == 200

    wrong_site = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{uuid4()}/competitor-comparison-runs/{run_id}"
    )
    assert wrong_site.status_code == 404


def test_comparison_run_repeat_execution_is_deterministic_for_same_inputs(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id, competitor_set_id, competitor_domain_id, snapshot_run_id = _create_site_set_domain_snapshot(
        client,
        seeded_business.id,
    )
    snapshot_run = _mark_snapshot_completed(db_session, snapshot_run_id=snapshot_run_id)
    _seed_snapshot_page(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        competitor_set_id=competitor_set_id,
        snapshot_run_id=snapshot_run.id,
        competitor_domain_id=competitor_domain_id,
        url="https://competitor.example/",
        title=None,
        meta_description=None,
        h1_count=0,
        word_count=100,
        canonical_url=None,
    )
    baseline_run = _seed_baseline_audit_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        page_count=1,
        finding_counts={"missing_title": 1, "missing_meta_description": 1},
    )
    baseline_pages = db_session.query(SEOAuditPage).filter(SEOAuditPage.audit_run_id == baseline_run.id).all()
    assert len(baseline_pages) == 1
    baseline_pages[0].title = None
    baseline_pages[0].meta_description = None
    baseline_pages[0].h1_json = []
    baseline_pages[0].word_count = 90
    baseline_pages[0].canonical_url = None
    baseline_pages[0].internal_link_count = 0
    db_session.commit()

    first_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id, "baseline_audit_run_id": baseline_run.id},
    )
    assert first_run.status_code == 201
    first_run_payload = first_run.json()
    first_run_id = first_run_payload["id"]

    second_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{competitor_set_id}/comparison-runs",
        json={"snapshot_run_id": snapshot_run.id, "baseline_audit_run_id": baseline_run.id},
    )
    assert second_run.status_code == 201
    second_run_payload = second_run.json()
    second_run_id = second_run_payload["id"]

    assert first_run_payload["finding_type_counts_json"] == second_run_payload["finding_type_counts_json"]
    assert first_run_payload["category_counts_json"] == second_run_payload["category_counts_json"]
    assert first_run_payload["severity_counts_json"] == second_run_payload["severity_counts_json"]
    assert first_run_payload["total_findings"] == second_run_payload["total_findings"]
    assert first_run_payload["critical_findings"] == second_run_payload["critical_findings"]
    assert first_run_payload["warning_findings"] == second_run_payload["warning_findings"]
    assert first_run_payload["info_findings"] == second_run_payload["info_findings"]

    first_findings = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{first_run_id}/findings")
    second_findings = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{second_run_id}/findings")
    assert first_findings.status_code == 200
    assert second_findings.status_code == 200

    def _signature(payload: dict) -> list[tuple[str, str, str, str | None, str | None, str | None]]:
        return sorted(
            (
                item["finding_type"],
                item["category"],
                item["severity"],
                item["gap_direction"],
                item["client_value"],
                item["competitor_value"],
            )
            for item in payload["items"]
        )

    assert _signature(first_findings.json()) == _signature(second_findings.json())


def test_comparison_endpoints_return_404_for_unknown_run(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    unknown_id = str(uuid4())

    run_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{unknown_id}")
    assert run_response.status_code == 404

    findings_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{unknown_id}/findings")
    assert findings_response.status_code == 404

    report_response = client.get(f"/api/businesses/{seeded_business.id}/seo/comparison-runs/{unknown_id}/report")
    assert report_response.status_code == 404

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.models.business import Business
from app.models.seo_audit_run import SEOAuditRun


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


def test_competitor_set_and_domain_crud_flow(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    create_set = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Front Range Competitors", "city": "Denver", "state": "CO"},
    )
    assert create_set.status_code == 201
    set_payload = create_set.json()
    assert set_payload["site_id"] == site_id
    set_id = set_payload["id"]

    list_sets = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets")
    assert list_sets.status_code == 200
    assert list_sets.json()["total"] == 1

    get_set = client.get(f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}")
    assert get_set.status_code == 200

    patch_set = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}",
        json={"city": "Lakewood", "is_active": False},
    )
    assert patch_set.status_code == 200
    assert patch_set.json()["city"] == "Lakewood"
    assert patch_set.json()["is_active"] is False

    snapshot_without_domains = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/snapshot-runs",
        json={},
    )
    assert snapshot_without_domains.status_code == 422

    add_domain = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"base_url": "https://CompetitorOne.com/", "display_name": "Competitor One"},
    )
    assert add_domain.status_code == 201
    domain_payload = add_domain.json()
    assert domain_payload["domain"] == "competitorone.com"
    domain_id = domain_payload["id"]

    duplicate_domain = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"domain": "COMPETITORONE.COM"},
    )
    assert duplicate_domain.status_code == 422

    list_domains = client.get(f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains")
    assert list_domains.status_code == 200
    assert list_domains.json()["total"] == 1

    create_snapshot_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/snapshot-runs",
        json={"max_domains": 5, "max_pages_per_domain": 4, "max_depth": 1},
    )
    assert create_snapshot_run.status_code == 201
    run_payload = create_snapshot_run.json()
    assert run_payload["status"] == "queued"
    assert run_payload["domains_targeted"] == 1
    run_id = run_payload["id"]

    list_runs = client.get(f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/snapshot-runs")
    assert list_runs.status_code == 200
    assert list_runs.json()["total"] == 1

    get_run = client.get(f"/api/businesses/{seeded_business.id}/seo/snapshot-runs/{run_id}")
    assert get_run.status_code == 200
    assert get_run.json()["competitor_set_id"] == set_id

    remove_domain = client.delete(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains/{domain_id}"
    )
    assert remove_domain.status_code == 204

    list_domains_after_delete = client.get(f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains")
    assert list_domains_after_delete.status_code == 200
    assert list_domains_after_delete.json()["total"] == 0


def test_competitor_routes_enforce_business_scoping(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)

    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    create_set = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Competitors"},
    )
    assert create_set.status_code == 201
    set_id = create_set.json()["id"]

    cross_tenant_get_set = client.get(f"/api/businesses/{other_business.id}/seo/competitor-sets/{set_id}")
    assert cross_tenant_get_set.status_code == 404

    cross_tenant_add_domain = client.post(
        f"/api/businesses/{other_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"domain": "competitor.com"},
    )
    assert cross_tenant_add_domain.status_code == 404


def test_snapshot_run_rejects_cross_business_client_audit_reference(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)

    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    create_set = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Competitors"},
    )
    assert create_set.status_code == 201
    set_id = create_set.json()["id"]

    add_domain = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"domain": "competitor.com"},
    )
    assert add_domain.status_code == 201

    foreign_run = SEOAuditRun(
        id=str(uuid4()),
        business_id=other_business.id,
        site_id=str(uuid4()),
        status="completed",
        max_pages=10,
        max_depth=2,
    )
    db_session.add(foreign_run)
    db_session.commit()

    create_snapshot_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/snapshot-runs",
        json={"client_audit_run_id": foreign_run.id},
    )
    assert create_snapshot_run.status_code == 422


def test_phase2_v1_site_scoped_competitor_routes(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    create_set = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Front Range"},
    )
    assert create_set.status_code == 201
    set_id = create_set.json()["id"]

    get_set = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets/{set_id}")
    assert get_set.status_code == 200
    assert get_set.json()["site_id"] == site_id

    add_domain = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets/{set_id}/domains",
        json={"domain": "competitor.com"},
    )
    assert add_domain.status_code == 201

    create_snapshot = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets/{set_id}/snapshot-runs",
        json={"max_domains": 5, "max_pages_per_domain": 3, "max_depth": 1},
    )
    assert create_snapshot.status_code == 201
    snapshot_id = create_snapshot.json()["id"]

    get_snapshot = client.get(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-snapshot-runs/{snapshot_id}"
    )
    assert get_snapshot.status_code == 200

    wrong_site_set = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{uuid4()}/competitor-sets/{set_id}")
    assert wrong_site_set.status_code == 404


def test_competitor_request_contract_rejects_unknown_fields(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    invalid_set = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Competitors", "unexpected": "value"},
    )
    assert invalid_set.status_code == 422

    create_set = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Competitors"},
    )
    assert create_set.status_code == 201
    set_id = create_set.json()["id"]

    invalid_domain = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"domain": "competitor.example", "unexpected": True},
    )
    assert invalid_domain.status_code == 422

    valid_domain = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"domain": "competitor.example"},
    )
    assert valid_domain.status_code == 201

    invalid_snapshot = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/snapshot-runs",
        json={"max_domains": 5, "unknown": "value"},
    )
    assert invalid_snapshot.status_code == 422


def test_competitor_snapshot_and_domain_reads_enforce_business_scoping(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)

    create_site = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main", "base_url": "https://example.com/"},
    )
    assert create_site.status_code == 201
    site_id = create_site.json()["id"]

    create_set = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-sets",
        json={"name": "Competitors"},
    )
    assert create_set.status_code == 201
    set_id = create_set.json()["id"]

    add_domain = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/domains",
        json={"domain": "competitor.com"},
    )
    assert add_domain.status_code == 201

    create_snapshot_run = client.post(
        f"/api/businesses/{seeded_business.id}/seo/competitor-sets/{set_id}/snapshot-runs",
        json={},
    )
    assert create_snapshot_run.status_code == 201
    snapshot_run_id = create_snapshot_run.json()["id"]

    cross_tenant_domain_list = client.get(f"/api/businesses/{other_business.id}/seo/competitor-sets/{set_id}/domains")
    assert cross_tenant_domain_list.status_code == 404

    cross_tenant_snapshot_list = client.get(
        f"/api/businesses/{other_business.id}/seo/competitor-sets/{set_id}/snapshot-runs"
    )
    assert cross_tenant_snapshot_list.status_code == 404

    cross_tenant_snapshot_get = client.get(f"/api/businesses/{other_business.id}/seo/snapshot-runs/{snapshot_run_id}")
    assert cross_tenant_snapshot_get.status_code == 404

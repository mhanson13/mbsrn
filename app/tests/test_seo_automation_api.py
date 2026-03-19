from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_seo_summary_provider, get_tenant_context
from app.api.routes.jobs import router as jobs_router
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.core.time import utc_now
from app.models.business import Business
from app.models.seo_automation_config import SEOAutomationConfig
from app.models.seo_automation_run import SEOAutomationRun


class _FailingAuditSummaryProvider:
    def generate_summary(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("summary provider unavailable")


def _override_tenant_context(business_id: str):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    return _resolver


def _make_client(db_session, *, business_id: str, failing_summary_provider: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)
    app.include_router(seo_v1_router)
    app.include_router(jobs_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    if failing_summary_provider:
        app.dependency_overrides[get_seo_summary_provider] = lambda: _FailingAuditSummaryProvider()
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


def _create_site(client: TestClient, business_id: str, domain: str = "client.example") -> str:
    response = client.post(
        f"/api/businesses/{business_id}/seo/sites",
        json={"display_name": f"Site {domain}", "base_url": f"https://{domain}/"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_config(client: TestClient, business_id: str, site_id: str, **overrides):
    payload = {
        "is_enabled": True,
        "cadence_type": "interval_minutes",
        "cadence_minutes": 60,
        "trigger_audit": True,
        "trigger_audit_summary": True,
        "trigger_competitor_snapshot": False,
        "trigger_comparison": False,
        "trigger_competitor_summary": False,
        "trigger_recommendations": True,
        "trigger_recommendation_narrative": False,
    }
    payload.update(overrides)
    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/automation-config",
        json=payload,
    )
    assert response.status_code == 201
    return response


def _steps_by_name(run_payload: dict) -> dict[str, dict]:
    return {step["step_name"]: step for step in run_payload["steps_json"]}


def test_phase4_automation_config_crud_and_status(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    created = _create_config(client, seeded_business.id, site_id)
    config = created.json()
    assert config["is_enabled"] is True
    assert config["cadence_type"] == "interval_minutes"
    assert config["next_run_at"] is not None

    get_config = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-config")
    assert get_config.status_code == 200
    assert get_config.json()["id"] == config["id"]

    patched = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-config",
        json={"trigger_recommendation_narrative": True, "cadence_minutes": 120},
    )
    assert patched.status_code == 200
    assert patched.json()["trigger_recommendation_narrative"] is True
    assert patched.json()["cadence_minutes"] == 120

    disabled = client.post(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-config/disable")
    assert disabled.status_code == 200
    assert disabled.json()["is_enabled"] is False
    assert disabled.json()["next_run_at"] is None

    enabled = client.post(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-config/enable")
    assert enabled.status_code == 200
    assert enabled.json()["is_enabled"] is True

    status = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["business_id"] == seeded_business.id
    assert payload["site_id"] == site_id
    assert payload["latest_run"] is None


def test_phase4_manual_automation_run_sequencing_and_history(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    _create_config(client, seeded_business.id, site_id)

    triggered = client.post(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert triggered.status_code == 201
    run_payload = triggered.json()
    assert run_payload["status"] == "completed"
    assert run_payload["trigger_source"] == "manual"

    steps = _steps_by_name(run_payload)
    assert steps["audit_run"]["status"] == "completed"
    assert steps["audit_summary"]["status"] == "completed"
    assert steps["recommendation_run"]["status"] == "completed"
    assert steps["competitor_snapshot_run"]["status"] == "skipped"
    assert steps["comparison_run"]["status"] == "skipped"
    assert steps["competitor_summary"]["status"] == "skipped"
    assert steps["recommendation_narrative"]["status"] == "skipped"

    listed = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    run_id = run_payload["id"]
    detail = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id

    status = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-status")
    assert status.status_code == 200
    assert status.json()["latest_run"]["id"] == run_id


def test_phase4_automation_scope_guards_and_not_found(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(db_session, business_id=seeded_business.id)

    site_id = _create_site(client, seeded_business.id, domain="tenant-a.example")
    other_site_id = _create_site(client, seeded_business.id, domain="tenant-b.example")
    _create_config(client, seeded_business.id, site_id)

    triggered = client.post(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert triggered.status_code == 201
    run_id = triggered.json()["id"]

    cross_business = client.get(f"/api/businesses/{other_business.id}/seo/sites/{site_id}/automation-runs/{run_id}")
    assert cross_business.status_code == 404

    wrong_site = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{other_site_id}/automation-runs/{run_id}")
    assert wrong_site.status_code == 404


def test_phase4_automation_concurrency_guard(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    config_response = _create_config(client, seeded_business.id, site_id)
    config_id = config_response.json()["id"]

    active_run = SEOAutomationRun(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site_id,
        automation_config_id=config_id,
        trigger_source="manual",
        status="running",
        steps_json=[],
    )
    db_session.add(active_run)
    db_session.commit()

    blocked = client.post(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert blocked.status_code == 409


def test_phase4_automation_summary_failure_isolation(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        failing_summary_provider=True,
    )
    site_id = _create_site(client, seeded_business.id)
    _create_config(client, seeded_business.id, site_id)

    triggered = client.post(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert triggered.status_code == 201
    payload = triggered.json()
    assert payload["status"] == "failed"

    steps = _steps_by_name(payload)
    assert steps["audit_run"]["status"] == "completed"
    assert steps["audit_summary"]["status"] == "failed"
    assert steps["recommendation_run"]["status"] == "completed"

    status = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-status")
    assert status.status_code == 200
    assert status.json()["config"]["last_status"] == "failed"
    assert status.json()["config"]["last_error_message"] is not None


def test_phase4_scheduler_ready_due_execution_path(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)
    config_payload = _create_config(client, seeded_business.id, site_id).json()

    config = db_session.get(SEOAutomationConfig, config_payload["id"])
    assert config is not None
    config.next_run_at = utc_now() - timedelta(minutes=5)
    db_session.add(config)
    db_session.commit()

    due_result = client.post(
        "/api/jobs/seo-automation/run-due",
        json={"business_id": seeded_business.id, "limit": 10},
    )
    assert due_result.status_code == 200
    summary = due_result.json()
    assert summary["scanned_configs"] >= 1
    assert summary["triggered_runs"] >= 1

    listed = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1


def test_phase4_v1_automation_surface(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site_id = _create_site(client, seeded_business.id)

    created = client.post(
        f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-config",
        json={
            "is_enabled": True,
            "cadence_type": "interval_minutes",
            "cadence_minutes": 30,
            "trigger_audit": True,
            "trigger_audit_summary": True,
            "trigger_competitor_snapshot": False,
            "trigger_comparison": False,
            "trigger_competitor_summary": False,
            "trigger_recommendations": True,
            "trigger_recommendation_narrative": False,
        },
    )
    assert created.status_code == 201

    run = client.post(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs")
    assert run.status_code == 201
    run_id = run.json()["id"]

    run_detail = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-runs/{run_id}")
    assert run_detail.status_code == 200

    status = client.get(f"/api/v1/businesses/{seeded_business.id}/seo/sites/{site_id}/automation-status")
    assert status.status_code == 200

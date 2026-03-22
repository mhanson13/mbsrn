from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.jobs import router as jobs_router
from app.api.routes.seo import router as seo_router
from app.core.time import utc_now
from app.integrations.seo_summary_provider import MockSEOCompetitorProfileGenerationProvider
from app.models.business import Business
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.seo_competitor_profile_generation import (
    SEOCompetitorProfileGenerationService,
    SEOCompetitorProfileRetentionPolicy,
)


def _make_service(
    db_session,
    *,
    raw_output_retention_days: int = 30,
    run_retention_days: int = 180,
    rejected_draft_retention_days: int = 90,
) -> SEOCompetitorProfileGenerationService:
    return SEOCompetitorProfileGenerationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(db_session),
        provider=MockSEOCompetitorProfileGenerationProvider(),
        retention_policy=SEOCompetitorProfileRetentionPolicy(
            raw_output_retention_days=raw_output_retention_days,
            run_retention_days=run_retention_days,
            rejected_draft_retention_days=rejected_draft_retention_days,
        ),
    )


def _make_client(db_session, *, business_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)
    app.include_router(jobs_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_tenant_context() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    return TestClient(app)


def _create_site(db_session, *, business_id: str, domain: str = "client.example") -> SEOSite:
    site = SEOSite(
        id=str(uuid4()),
        business_id=business_id,
        display_name=f"Site {domain}",
        base_url=f"https://{domain}/",
        normalized_domain=domain,
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)
    return site


def _create_run(
    db_session,
    *,
    business_id: str,
    site_id: str,
    status: str,
    age_days: int,
    generated_draft_count: int,
    raw_output: str | None = None,
    parent_run_id: str | None = None,
) -> SEOCompetitorProfileGenerationRun:
    timestamp = utc_now() - timedelta(days=age_days)
    run = SEOCompetitorProfileGenerationRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        parent_run_id=parent_run_id,
        status=status,
        requested_candidate_count=2,
        generated_draft_count=generated_draft_count,
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-competitor-profile-v1",
        raw_output=raw_output,
        error_summary="failed run" if status == "failed" else None,
        completed_at=timestamp if status in {"completed", "failed"} else None,
        created_by_principal_id=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def _create_draft(
    db_session,
    *,
    business_id: str,
    site_id: str,
    run_id: str,
    review_status: str,
    age_days: int,
    accepted_competitor_set_id: str | None = None,
    accepted_competitor_domain_id: str | None = None,
) -> SEOCompetitorProfileDraft:
    timestamp = utc_now() - timedelta(days=age_days)
    draft = SEOCompetitorProfileDraft(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        generation_run_id=run_id,
        suggested_name="Competitor",
        suggested_domain=f"{uuid4().hex[:10]}.example",
        competitor_type="direct",
        summary="summary",
        why_competitor="why",
        evidence="evidence",
        confidence_score=0.7,
        source="ai_generated",
        review_status=review_status,
        reviewed_by_principal_id="reviewer" if review_status in {"accepted", "rejected", "edited"} else None,
        reviewed_at=timestamp if review_status in {"accepted", "rejected", "edited"} else None,
        accepted_competitor_set_id=accepted_competitor_set_id,
        accepted_competitor_domain_id=accepted_competitor_domain_id,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


def _create_accepted_domain(
    db_session,
    *,
    business_id: str,
    site_id: str,
) -> tuple[SEOCompetitorSet, SEOCompetitorDomain]:
    competitor_set = SEOCompetitorSet(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        name=f"Set-{uuid4().hex[:8]}",
        is_active=True,
    )
    db_session.add(competitor_set)
    db_session.flush()
    competitor_domain = SEOCompetitorDomain(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        domain=f"{uuid4().hex[:10]}.example",
        base_url="https://accepted.example/",
        display_name="Accepted",
        source="ai_generated",
        is_active=True,
    )
    db_session.add(competitor_domain)
    db_session.commit()
    db_session.refresh(competitor_set)
    db_session.refresh(competitor_domain)
    return competitor_set, competitor_domain


def test_retention_cleanup_prunes_raw_output_after_threshold(db_session, seeded_business) -> None:
    site = _create_site(db_session, business_id=seeded_business.id, domain="raw-prune.example")
    run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        age_days=40,
        generated_draft_count=1,
        raw_output='{"debug":"payload"}',
    )
    _create_draft(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        run_id=run.id,
        review_status="pending",
        age_days=40,
    )

    service = _make_service(
        db_session,
        raw_output_retention_days=30,
        run_retention_days=365,
        rejected_draft_retention_days=365,
    )
    summary = service.cleanup_retention(business_id=seeded_business.id)

    refreshed_run = db_session.get(SEOCompetitorProfileGenerationRun, run.id)
    assert refreshed_run is not None
    assert summary.raw_output_pruned_runs == 1
    assert refreshed_run.raw_output is None


def test_retention_cleanup_prunes_old_rejected_drafts(db_session, seeded_business) -> None:
    site = _create_site(db_session, business_id=seeded_business.id, domain="reject-prune.example")
    run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        age_days=20,
        generated_draft_count=1,
    )
    rejected = _create_draft(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        run_id=run.id,
        review_status="rejected",
        age_days=100,
    )

    service = _make_service(
        db_session,
        raw_output_retention_days=365,
        run_retention_days=365,
        rejected_draft_retention_days=90,
    )
    summary = service.cleanup_retention(business_id=seeded_business.id)

    assert summary.rejected_drafts_pruned == 1
    assert db_session.get(SEOCompetitorProfileDraft, rejected.id) is None
    assert db_session.get(SEOCompetitorProfileGenerationRun, run.id) is not None


def test_retention_cleanup_preserves_accepted_and_lineage_records(db_session, seeded_business) -> None:
    site = _create_site(db_session, business_id=seeded_business.id, domain="lineage.example")

    parent_run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="failed",
        age_days=300,
        generated_draft_count=0,
        raw_output='{"error":"x"}',
    )
    child_run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="failed",
        age_days=300,
        generated_draft_count=0,
        parent_run_id=parent_run.id,
    )
    child_run_id = child_run.id
    accepted_run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        age_days=300,
        generated_draft_count=1,
    )
    competitor_set, competitor_domain = _create_accepted_domain(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
    )
    accepted_draft = _create_draft(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        run_id=accepted_run.id,
        review_status="accepted",
        age_days=300,
        accepted_competitor_set_id=competitor_set.id,
        accepted_competitor_domain_id=competitor_domain.id,
    )

    service = _make_service(db_session)
    summary = service.cleanup_retention(business_id=seeded_business.id)

    assert summary.runs_pruned >= 1
    assert db_session.get(SEOCompetitorProfileGenerationRun, parent_run.id) is not None
    assert db_session.get(SEOCompetitorProfileGenerationRun, accepted_run.id) is not None
    assert db_session.get(SEOCompetitorProfileGenerationRun, child_run_id) is None
    assert db_session.get(SEOCompetitorProfileDraft, accepted_draft.id) is not None
    assert db_session.get(SEOCompetitorDomain, competitor_domain.id) is not None


def test_retention_cleanup_does_not_prune_active_queued_or_running_runs(db_session, seeded_business) -> None:
    site = _create_site(db_session, business_id=seeded_business.id, domain="active.example")
    queued_run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="queued",
        age_days=0,
        generated_draft_count=0,
    )
    running_run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="running",
        age_days=0,
        generated_draft_count=0,
    )

    service = _make_service(
        db_session,
        raw_output_retention_days=1,
        run_retention_days=1,
        rejected_draft_retention_days=1,
    )
    summary = service.cleanup_retention(business_id=seeded_business.id)

    refreshed_queued = db_session.get(SEOCompetitorProfileGenerationRun, queued_run.id)
    refreshed_running = db_session.get(SEOCompetitorProfileGenerationRun, running_run.id)
    assert refreshed_queued is not None
    assert refreshed_running is not None
    assert refreshed_queued.status == "queued"
    assert refreshed_running.status == "running"
    assert summary.runs_pruned == 0


def test_retention_cleanup_is_business_scoped(db_session, seeded_business) -> None:
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

    site_a = _create_site(db_session, business_id=seeded_business.id, domain="tenant-a.example")
    site_b = _create_site(db_session, business_id=other_business.id, domain="tenant-b.example")

    run_a = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site_a.id,
        status="completed",
        age_days=40,
        generated_draft_count=1,
        raw_output='{"debug":"a"}',
    )
    _create_draft(
        db_session,
        business_id=seeded_business.id,
        site_id=site_a.id,
        run_id=run_a.id,
        review_status="rejected",
        age_days=100,
    )

    run_b = _create_run(
        db_session,
        business_id=other_business.id,
        site_id=site_b.id,
        status="completed",
        age_days=40,
        generated_draft_count=1,
        raw_output='{"debug":"b"}',
    )
    draft_b = _create_draft(
        db_session,
        business_id=other_business.id,
        site_id=site_b.id,
        run_id=run_b.id,
        review_status="rejected",
        age_days=100,
    )

    service = _make_service(
        db_session,
        raw_output_retention_days=30,
        run_retention_days=365,
        rejected_draft_retention_days=90,
    )
    summary = service.cleanup_retention(business_id=seeded_business.id)

    assert summary.raw_output_pruned_runs == 1
    assert db_session.get(SEOCompetitorProfileGenerationRun, run_a.id).raw_output is None
    assert db_session.get(SEOCompetitorProfileGenerationRun, run_b.id).raw_output is not None
    assert db_session.get(SEOCompetitorProfileDraft, draft_b.id) is not None


def test_cleanup_job_endpoint_keeps_detail_api_stable_and_enforces_scope(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site = _create_site(db_session, business_id=seeded_business.id, domain="jobs-cleanup.example")
    run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        age_days=40,
        generated_draft_count=1,
        raw_output='{"debug":"payload"}',
    )
    _create_draft(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        run_id=run.id,
        review_status="rejected",
        age_days=100,
    )

    cleanup = client.post(
        "/api/jobs/seo-competitor-profile-generation/cleanup",
        json={"business_id": seeded_business.id, "site_id": site.id},
    )
    assert cleanup.status_code == 200
    cleanup_payload = cleanup.json()
    assert cleanup_payload["business_id"] == seeded_business.id
    assert cleanup_payload["site_id"] == site.id
    assert cleanup_payload["raw_output_pruned_runs"] == 1
    assert cleanup_payload["rejected_drafts_pruned"] == 1

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site.id}/competitor-profile-generation-runs/{run.id}"
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["run"]["id"] == run.id
    assert detail_payload["run"]["status"] == "completed"
    assert detail_payload["total_drafts"] == 0

    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550198",
        notification_email="owner2@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.commit()

    cross_tenant = client.post(
        "/api/jobs/seo-competitor-profile-generation/cleanup",
        json={"business_id": other_business.id},
    )
    assert cross_tenant.status_code == 404


def test_cleanup_status_endpoint_returns_latest_execution_and_recent_counts(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site = _create_site(db_session, business_id=seeded_business.id, domain="cleanup-status.example")
    run = _create_run(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        status="completed",
        age_days=40,
        generated_draft_count=1,
        raw_output='{"debug":"payload"}',
    )
    _create_draft(
        db_session,
        business_id=seeded_business.id,
        site_id=site.id,
        run_id=run.id,
        review_status="rejected",
        age_days=100,
    )

    cleanup = client.post(
        "/api/jobs/seo-competitor-profile-generation/cleanup",
        json={"business_id": seeded_business.id},
    )
    assert cleanup.status_code == 200

    status_response = client.get(
        f"/api/jobs/seo-competitor-profile-generation/cleanup-status?business_id={seeded_business.id}"
    )
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["business_id"] == seeded_business.id
    assert payload["site_id"] is None
    assert payload["recent_success_count"] >= 1
    assert payload["recent_failure_count"] == 0
    assert payload["latest_execution"] is not None
    assert payload["latest_execution"]["status"] == "completed"
    assert payload["latest_execution"]["raw_output_pruned_runs"] >= 1
    assert payload["latest_execution"]["rejected_drafts_pruned"] >= 1

    persisted_execution_count = (
        db_session.query(SEOCompetitorProfileCleanupExecution)
        .filter(SEOCompetitorProfileCleanupExecution.business_id == seeded_business.id)
        .count()
    )
    assert persisted_execution_count >= 1


def test_cleanup_status_endpoint_enforces_site_and_tenant_scope(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site = _create_site(db_session, business_id=seeded_business.id, domain="cleanup-site-scope.example")

    cleanup = client.post(
        "/api/jobs/seo-competitor-profile-generation/cleanup",
        json={"business_id": seeded_business.id, "site_id": site.id},
    )
    assert cleanup.status_code == 200

    scoped_status = client.get(
        f"/api/jobs/seo-competitor-profile-generation/cleanup-status?business_id={seeded_business.id}&site_id={site.id}"
    )
    assert scoped_status.status_code == 200
    scoped_payload = scoped_status.json()
    assert scoped_payload["site_id"] == site.id

    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550197",
        notification_email="owner3@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.commit()

    cross_tenant = client.get(
        f"/api/jobs/seo-competitor-profile-generation/cleanup-status?business_id={other_business.id}"
    )
    assert cross_tenant.status_code == 404

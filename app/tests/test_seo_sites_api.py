from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.seo import router as seo_router
from app.models.business import Business
from app.models.principal import Principal, PrincipalRole
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_audit_summary import SEOAuditSummary
from app.models.seo_automation_config import SEOAutomationConfig
from app.models.seo_automation_run import SEOAutomationRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_recommendation_run import SEORecommendationRun


def _override_tenant_context(
    business_id: str,
    principal_id: str | None = None,
    principal_role: PrincipalRole | None = None,
):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=principal_id or f"test-principal:{business_id}",
            auth_source="test",
            principal_role=principal_role,
        )

    return _resolver


def _make_client(
    db_session,
    *,
    business_id: str,
    principal_id: str | None = None,
    principal_role: PrincipalRole | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(
        business_id,
        principal_id=principal_id,
        principal_role=principal_role,
    )
    return TestClient(app)


_SITE_OWNED_MODELS = (
    SEOAuditRun,
    SEOAuditPage,
    SEOAuditFinding,
    SEOAuditSummary,
    SEOCompetitorSet,
    SEOCompetitorDomain,
    SEOCompetitorSnapshotRun,
    SEOCompetitorSnapshotPage,
    SEOCompetitorComparisonRun,
    SEOCompetitorComparisonFinding,
    SEOCompetitorComparisonSummary,
    SEORecommendationRun,
    SEORecommendation,
    SEORecommendationNarrative,
    SEOAutomationConfig,
    SEOAutomationRun,
    SEOCompetitorProfileGenerationRun,
    SEOCompetitorProfileDraft,
    SEOCompetitorTuningPreviewEvent,
    SEOCompetitorProfileCleanupExecution,
)


def _count_site_rows(*, db_session, model, business_id: str, site_id: str) -> int:
    stmt = (
        select(func.count()).select_from(model).where(model.business_id == business_id).where(model.site_id == site_id)
    )
    return int(db_session.scalar(stmt) or 0)


def _seed_admin_principal(*, db_session, business_id: str, principal_id: str = "seo-admin") -> Principal:
    principal = Principal(
        business_id=business_id,
        id=principal_id,
        display_name="SEO Admin",
        role=PrincipalRole.ADMIN,
        is_active=True,
    )
    db_session.add(principal)
    db_session.commit()
    return principal


def _seed_site_owned_data(*, db_session, business_id: str, site_id: str, token: str) -> None:
    audit_run = SEOAuditRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        max_pages=10,
        crawl_max_pages_used=10,
        max_depth=1,
    )
    db_session.add(audit_run)
    db_session.flush()

    audit_page = SEOAuditPage(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        audit_run_id=audit_run.id,
        url=f"https://{token}.example.com/",
    )
    db_session.add(audit_page)
    db_session.flush()

    db_session.add(
        SEOAuditFinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=audit_run.id,
            page_id=audit_page.id,
            finding_type="missing_title",
            category="metadata",
            severity="warning",
            title="Missing title",
            details="No title tag",
            rule_key="missing_title",
        )
    )
    db_session.add(
        SEOAuditSummary(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=audit_run.id,
            version=1,
            status="completed",
            model_name="mock",
            prompt_version="seo-audit-summary-v1",
        )
    )

    competitor_set = SEOCompetitorSet(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        name=f"{token}-set",
        is_active=True,
    )
    db_session.add(competitor_set)
    db_session.flush()

    competitor_domain = SEOCompetitorDomain(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        domain=f"{token}-competitor.example.com",
        base_url=f"https://{token}-competitor.example.com/",
        source="manual",
        is_active=True,
    )
    db_session.add(competitor_domain)
    db_session.flush()

    snapshot_run = SEOCompetitorSnapshotRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        client_audit_run_id=audit_run.id,
        status="completed",
    )
    db_session.add(snapshot_run)
    db_session.flush()

    db_session.add(
        SEOCompetitorSnapshotPage(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            snapshot_run_id=snapshot_run.id,
            competitor_domain_id=competitor_domain.id,
            url=f"https://{token}-competitor.example.com/service",
        )
    )

    comparison_run = SEOCompetitorComparisonRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        snapshot_run_id=snapshot_run.id,
        baseline_audit_run_id=audit_run.id,
        status="completed",
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
            finding_type="gap",
            category="content",
            severity="warning",
            title="Gap",
            details="Gap details",
            rule_key="gap_rule",
        )
    )
    db_session.add(
        SEOCompetitorComparisonSummary(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            comparison_run_id=comparison_run.id,
            version=1,
            status="completed",
            provider_name="mock",
            model_name="mock-model",
            prompt_version="seo-competitor-summary-v1",
        )
    )

    recommendation_run = SEORecommendationRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        audit_run_id=audit_run.id,
        comparison_run_id=comparison_run.id,
        status="completed",
    )
    db_session.add(recommendation_run)
    db_session.flush()

    db_session.add(
        SEORecommendation(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run.id,
            audit_run_id=audit_run.id,
            comparison_run_id=comparison_run.id,
            rule_key=f"{token}_rule",
            category="SEO",
            severity="warning",
            title="Recommendation",
            rationale="Improve title tags.",
            priority_score=50,
            priority_band="medium",
            effort_bucket="MEDIUM",
            status="open",
        )
    )

    recommendation_narrative = SEORecommendationNarrative(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        recommendation_run_id=recommendation_run.id,
        version=1,
        status="completed",
        provider_name="mock",
        model_name="mock-model",
        prompt_version="seo-recommendation-narrative-v1",
    )
    db_session.add(recommendation_narrative)
    db_session.flush()

    automation_config = SEOAutomationConfig(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        is_enabled=False,
        cadence_type="manual",
    )
    db_session.add(automation_config)
    db_session.flush()

    db_session.add(
        SEOAutomationRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            automation_config_id=automation_config.id,
            trigger_source="manual",
            status="completed",
        )
    )

    generation_run = SEOCompetitorProfileGenerationRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        requested_candidate_count=3,
        generated_draft_count=1,
        raw_candidate_count=3,
        included_candidate_count=1,
        excluded_candidate_count=2,
        exclusion_counts_by_reason={"low_relevance": 2},
        provider_name="mock",
        model_name="mock-model",
        prompt_version="seo-competitor-profile-v1",
    )
    db_session.add(generation_run)
    db_session.flush()

    db_session.add(
        SEOCompetitorProfileDraft(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run.id,
            suggested_name=f"{token} competitor",
            suggested_domain=f"{token}-draft.example.com",
            competitor_type="direct",
            confidence_score=0.7,
            relevance_score=60,
            source="ai_generated",
            review_status="pending",
        )
    )
    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            source_narrative_id=recommendation_narrative.id,
            source_recommendation_run_id=recommendation_run.id,
            preview_request={"proposed_values": {"competitor_candidate_min_relevance_score": 40}},
            preview_response={"summary": "Preview"},
            evaluated_generation_run_id=generation_run.id,
        )
    )
    db_session.add(
        SEOCompetitorProfileCleanupExecution(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            status="completed",
            stale_runs_reconciled=0,
            raw_output_pruned_runs=0,
            rejected_drafts_pruned=0,
            runs_pruned=0,
            started_at=audit_run.created_at,
            completed_at=audit_run.created_at,
        )
    )
    db_session.commit()


def test_seo_site_crud_and_business_scoping(db_session, seeded_business) -> None:
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

    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Main Site",
            "base_url": "https://Example.COM/",
            "industry": "Fire Restoration",
            "primary_location": "Denver, CO",
            "service_areas": ["Denver", "Lakewood"],
            "is_active": True,
            "is_primary": True,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["normalized_domain"] == "example.com"
    assert created["base_url"] == "https://example.com/"
    assert created["last_audit_run_id"] is None
    assert created["last_audit_status"] is None
    assert created["last_audit_completed_at"] is None
    assert created["search_console_property_url"] is None
    assert created["search_console_enabled"] is False

    site_id = created["id"]
    list_response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == site_id

    read_response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}")
    assert read_response.status_code == 200

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"display_name": "Main Site Updated", "base_url": "https://example.com/services/"},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["display_name"] == "Main Site Updated"
    assert patched["base_url"] == "https://example.com/services"
    assert patched["search_console_property_url"] is None
    assert patched["search_console_enabled"] is False

    cross_tenant = client.get(f"/api/businesses/{other_business.id}/seo/sites/{site_id}")
    assert cross_tenant.status_code == 404


def test_admin_can_set_site_level_search_console_configuration(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Search Console Site",
            "base_url": "https://search-console.example/",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "search_console_property_url": "sc-domain:search-console.example",
            "search_console_enabled": True,
        },
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["search_console_property_url"] == "sc-domain:search-console.example"
    assert payload["search_console_enabled"] is True


def test_seo_site_invalid_url_rejected(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Bad URL Site",
            "base_url": "ftp://example.com",
        },
    )
    assert response.status_code == 422


def test_seo_site_duplicate_domain_rejected_for_business(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    first = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Main Site",
            "base_url": "https://example.com/",
        },
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Duplicate Domain",
            "base_url": "https://EXAMPLE.com/services",
        },
    )
    assert duplicate.status_code == 422
    assert "already exists" in duplicate.json()["detail"].lower()


def test_admin_can_deactivate_and_reactivate_site(db_session, seeded_business) -> None:
    admin_principal = Principal(
        business_id=seeded_business.id,
        id="seo-admin",
        display_name="SEO Admin",
        role=PrincipalRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin_principal)
    db_session.commit()
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/deactivate",
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False

    activate_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/activate",
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True


def test_operator_cannot_deactivate_site(db_session, seeded_business) -> None:
    operator_principal = Principal(
        business_id=seeded_business.id,
        id="seo-operator",
        display_name="SEO Operator",
        role=PrincipalRole.OPERATOR,
        is_active=True,
    )
    db_session.add(operator_principal)
    db_session.commit()
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=operator_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/deactivate",
    )
    assert deactivate_response.status_code == 403


def test_operator_cannot_patch_site_activation_state(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-test",
        principal_role=PrincipalRole.OPERATOR,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"is_active": False},
    )
    assert patch_response.status_code == 403


def test_operator_cannot_patch_site_name_or_url(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-test",
        principal_role=PrincipalRole.OPERATOR,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    rename_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"display_name": "Renamed"},
    )
    assert rename_response.status_code == 403

    reurl_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"base_url": "https://example.com/new"},
    )
    assert reurl_response.status_code == 403

    search_console_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "search_console_property_url": "sc-domain:example.com",
            "search_console_enabled": True,
        },
    )
    assert search_console_response.status_code == 403


def test_admin_can_update_site_name_via_admin_endpoint(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"name": "Renamed Site"},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["display_name"] == "Renamed Site"
    assert payload["base_url"] == "https://example.com/"


def test_admin_can_update_site_url_via_admin_endpoint(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"url": "https://EXAMPLE.com/services/"},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["base_url"] == "https://example.com/services"
    assert payload["normalized_domain"] == "example.com"


def test_admin_site_domain_change_clears_stale_industry_when_not_explicitly_updated(
    db_session, seeded_business
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Legacy Roofing Site",
            "base_url": "https://legacy-roofing.example/",
            "industry": "Roofing services",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    assert create_response.json()["industry"] == "Roofing services"

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"url": "https://vmsdata.com/"},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["normalized_domain"] == "vmsdata.com"
    assert payload["industry"] is None


def test_site_patch_domain_change_keeps_industry_when_explicitly_supplied(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        principal_role=PrincipalRole.ADMIN,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Legacy Roofing Site",
            "base_url": "https://legacy-roofing.example/",
            "industry": "Roofing services",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "base_url": "https://vmsdata.com/",
            "industry": "Managed IT and cloud hosting services",
        },
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["normalized_domain"] == "vmsdata.com"
    assert payload["industry"] == "Managed IT and cloud hosting services"


def test_admin_site_url_validation_rejects_invalid_url(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"url": "ftp://example.com"},
    )
    assert patch_response.status_code == 422
    assert "http or https" in patch_response.json()["detail"].lower()


def test_admin_can_permanently_delete_site_and_site_owned_data(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_one = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/"},
    )
    create_two = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Keep Me", "base_url": "https://keep-me.example.com/"},
    )
    assert create_one.status_code == 201
    assert create_two.status_code == 201
    delete_site_id = create_one.json()["id"]
    keep_site_id = create_two.json()["id"]

    _seed_site_owned_data(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=delete_site_id,
        token="delete-site",
    )
    _seed_site_owned_data(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=keep_site_id,
        token="keep-site",
    )

    for model in _SITE_OWNED_MODELS:
        assert (
            _count_site_rows(
                db_session=db_session,
                model=model,
                business_id=seeded_business.id,
                site_id=delete_site_id,
            )
            > 0
        )

    delete_response = client.delete(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{delete_site_id}",
    )
    assert delete_response.status_code == 204

    deleted_site_read = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{delete_site_id}")
    assert deleted_site_read.status_code == 404

    for model in _SITE_OWNED_MODELS:
        assert (
            _count_site_rows(
                db_session=db_session,
                model=model,
                business_id=seeded_business.id,
                site_id=delete_site_id,
            )
            == 0
        )
        assert (
            _count_site_rows(
                db_session=db_session,
                model=model,
                business_id=seeded_business.id,
                site_id=keep_site_id,
            )
            > 0
        )

    kept_site_read = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{keep_site_id}")
    assert kept_site_read.status_code == 200

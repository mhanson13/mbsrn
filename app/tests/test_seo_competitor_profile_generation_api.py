from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_competitor_profile_generation_provider,
    get_tenant_context,
)
from app.api.routes.seo import router as seo_router
from app.api.routes.seo import router_v1 as seo_v1_router
from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
    SEOCompetitorProfileGenerationProvider,
)
from app.models.business import Business
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun


class _DeterministicCompetitorProfileProvider:
    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains
        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Draft Competitor One",
                suggested_domain="draft-competitor-one.example",
                competitor_type="direct",
                summary="Direct overlap in service intent.",
                why_competitor="Competes for transactional query demand.",
                evidence="Domain + intent overlap heuristic.",
                confidence_score=0.88,
            ),
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name="Draft Competitor Two",
                suggested_domain="draft-competitor-two.example",
                competitor_type="local",
                summary="Likely local competitor for geo-intent queries.",
                why_competitor="Localized service market overlap.",
                evidence="Local SERP-style coverage pattern.",
                confidence_score=0.72,
            ),
        ]
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates[:candidate_count],
            provider_name="deterministic-test-provider",
            model_name="deterministic-test-model",
            prompt_version="seo-competitor-profile-v1",
        )


class _InvalidCompetitorProfileProvider:
    def generate_competitor_profiles(
        self,
        *,
        site,  # noqa: ANN001
        existing_domains,  # noqa: ANN001
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
        return SEOCompetitorProfileGenerationOutput(
            candidates=[
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name="Broken Candidate",
                    suggested_domain="invalid-domain-without-tld",
                    competitor_type="direct",
                    summary="broken",
                    why_competitor="broken",
                    evidence="broken",
                    confidence_score=0.5,
                )
            ],
            provider_name="invalid-test-provider",
            model_name="invalid-test-model",
            prompt_version="seo-competitor-profile-v1",
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
    generation_provider: SEOCompetitorProfileGenerationProvider | None = None,
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
    if generation_provider is not None:
        app.dependency_overrides[get_seo_competitor_profile_generation_provider] = lambda: generation_provider
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


def _create_generation_run(client: TestClient, business_id: str, site_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": 2},
    )
    assert response.status_code == 201
    return response.json()


def test_competitor_profile_generation_run_create_list_detail_and_persistence(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)

    created = _create_generation_run(client, seeded_business.id, site_id)
    assert created["run"]["status"] == "completed"
    assert created["run"]["generated_draft_count"] == 2
    assert created["total_drafts"] == 2
    assert {item["review_status"] for item in created["drafts"]} == {"pending"}

    listed = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs"
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    run_id = listed.json()["items"][0]["id"]

    detail = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert detail.status_code == 200
    assert detail.json()["total_drafts"] == 2

    persisted_runs = db_session.query(SEOCompetitorProfileGenerationRun).all()
    persisted_drafts = db_session.query(SEOCompetitorProfileDraft).all()
    assert len(persisted_runs) == 1
    assert len(persisted_drafts) == 2


def test_competitor_profile_generation_validation_failure_records_failed_run(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_InvalidCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)

    failed = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs",
        json={"candidate_count": 1},
    )
    assert failed.status_code == 422

    runs = client.get(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs"
    )
    assert runs.status_code == 200
    assert runs.json()["total"] == 1
    assert runs.json()["items"][0]["status"] == "failed"
    assert runs.json()["items"][0]["generated_draft_count"] == 0


def test_competitor_profile_draft_accept_creates_real_competitor_domain(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    draft_id = created["drafts"][0]["id"]

    accept = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/accept",
        json={},
    )
    assert accept.status_code == 200
    payload = accept.json()
    assert payload["review_status"] == "accepted"
    assert payload["accepted_competitor_domain_id"] is not None
    assert payload["accepted_competitor_set_id"] is not None

    created_domain = (
        db_session.query(SEOCompetitorDomain)
        .filter(SEOCompetitorDomain.id == payload["accepted_competitor_domain_id"])
        .one_or_none()
    )
    assert created_domain is not None
    assert created_domain.source == "ai_generated"
    assert created_domain.site_id == site_id


def test_competitor_profile_draft_reject_does_not_create_competitor_domain(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    draft_id = created["drafts"][1]["id"]

    reject = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/reject",
        json={"reason": "Not relevant for this market"},
    )
    assert reject.status_code == 200
    payload = reject.json()
    assert payload["review_status"] == "rejected"

    domain_count = (
        db_session.query(SEOCompetitorDomain)
        .filter(SEOCompetitorDomain.business_id == seeded_business.id)
        .filter(SEOCompetitorDomain.site_id == site_id)
        .count()
    )
    assert domain_count == 0


def test_competitor_profile_draft_accept_prevents_duplicate_domains(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    draft_id = created["drafts"][0]["id"]

    first_accept = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/accept",
        json={},
    )
    assert first_accept.status_code == 200

    second_run = _create_generation_run(client, seeded_business.id, site_id)
    second_run_id = second_run["run"]["id"]
    second_draft_id = second_run["drafts"][0]["id"]
    duplicate_accept = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{second_run_id}/drafts/{second_draft_id}/accept",
        json={},
    )
    assert duplicate_accept.status_code == 422
    assert "already exists" in duplicate_accept.json()["detail"].lower()


def test_competitor_profile_generation_routes_enforce_tenant_scope(db_session, seeded_business) -> None:
    other_business = _seed_other_business(db_session)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    draft_id = created["drafts"][0]["id"]

    cross_tenant_list = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs"
    )
    assert cross_tenant_list.status_code == 404

    cross_tenant_detail = client.get(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}"
    )
    assert cross_tenant_detail.status_code == 404

    cross_tenant_accept = client.post(
        f"/api/businesses/{other_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}/accept",
        json={},
    )
    assert cross_tenant_accept.status_code == 404


def test_competitor_profile_draft_edit_marks_edited_status(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        generation_provider=_DeterministicCompetitorProfileProvider(),
    )
    site_id = _create_site(client, seeded_business.id)
    created = _create_generation_run(client, seeded_business.id, site_id)
    run_id = created["run"]["id"]
    draft_id = created["drafts"][0]["id"]

    edit = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/competitor-profile-generation-runs/{run_id}/drafts/{draft_id}",
        json={"suggested_name": "Edited Competitor Name"},
    )
    assert edit.status_code == 200
    payload = edit.json()
    assert payload["review_status"] == "edited"
    assert payload["suggested_name"] == "Edited Competitor Name"

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from uuid import uuid4

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.businesses import router as businesses_router
from app.models.principal import Principal, PrincipalRole
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_site import SEOSite


def _detail_contains_field(detail: object, field_name: str) -> bool:
    if isinstance(detail, str):
        return field_name in detail
    if isinstance(detail, list):
        for item in detail:
            if not isinstance(item, dict):
                continue
            loc = item.get("loc")
            if isinstance(loc, list) and field_name in [str(value) for value in loc]:
                return True
            msg = item.get("msg")
            if isinstance(msg, str) and field_name in msg:
                return True
    return False


def _make_client(
    db_session,
    *,
    business_id: str,
    principal_id: str = "settings-admin",
    principal_role: PrincipalRole = PrincipalRole.ADMIN,
) -> TestClient:
    principal = db_session.get(Principal, (business_id, principal_id))
    if principal is None:
        db_session.add(
            Principal(
                business_id=business_id,
                id=principal_id,
                display_name=principal_id,
                role=principal_role,
                is_active=True,
            )
        )
    else:
        principal.role = principal_role
        principal.is_active = True
    db_session.commit()

    app = FastAPI()
    app.include_router(businesses_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_tenant_context() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=principal_id,
            auth_source="test",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    return TestClient(app)


def test_get_business_settings_endpoint(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.get(f"/api/businesses/{seeded_business.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == seeded_business.id
    assert payload["sms_enabled"] is True
    assert payload["email_enabled"] is True
    assert payload["customer_auto_ack_enabled"] is True
    assert payload["contractor_alerts_enabled"] is True
    assert payload["seo_audit_crawl_max_pages"] == 25
    assert payload["competitor_candidate_min_relevance_score"] == 35
    assert payload["competitor_candidate_big_box_penalty"] == 20
    assert payload["competitor_candidate_directory_penalty"] == 35
    assert payload["competitor_candidate_local_alignment_bonus"] == 10
    assert payload["competitor_primary_timeout_seconds"] is None
    assert payload["competitor_degraded_timeout_seconds"] is None
    assert payload["ai_prompt_text_competitor"] is None
    assert payload["ai_prompt_text_recommendations"] is None


def test_patch_business_settings_valid_partial_update_succeeds(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "notification_email": "  OWNER+ALERTS@TMFIRE.EXAMPLE  ",
            "timezone": "America/Chicago",
            "seo_audit_crawl_max_pages": 60,
            "competitor_candidate_min_relevance_score": 45,
            "competitor_candidate_big_box_penalty": 18,
            "competitor_candidate_directory_penalty": 30,
            "competitor_candidate_local_alignment_bonus": 14,
            "competitor_primary_timeout_seconds": 45,
            "competitor_degraded_timeout_seconds": 25,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_email"] == "owner+alerts@tmfire.example"
    assert payload["timezone"] == "America/Chicago"
    assert payload["seo_audit_crawl_max_pages"] == 60
    assert payload["competitor_candidate_min_relevance_score"] == 45
    assert payload["competitor_candidate_big_box_penalty"] == 18
    assert payload["competitor_candidate_directory_penalty"] == 30
    assert payload["competitor_candidate_local_alignment_bonus"] == 14
    assert payload["competitor_primary_timeout_seconds"] == 45
    assert payload["competitor_degraded_timeout_seconds"] == 25
    assert payload["sms_enabled"] is True


def test_patch_business_settings_accepts_and_clears_ai_prompt_text_overrides(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    save_response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "ai_prompt_text_competitor": "  Prefer local competitors only.  ",
            "ai_prompt_text_recommendations": "  Focus on specific action steps.  ",
        },
    )
    assert save_response.status_code == 200
    save_payload = save_response.json()
    assert save_payload["ai_prompt_text_competitor"] == "Prefer local competitors only."
    assert save_payload["ai_prompt_text_recommendations"] == "Focus on specific action steps."

    clear_response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "ai_prompt_text_competitor": " \n\t ",
            "ai_prompt_text_recommendations": "",
        },
    )
    assert clear_response.status_code == 200
    clear_payload = clear_response.json()
    assert clear_payload["ai_prompt_text_competitor"] is None
    assert clear_payload["ai_prompt_text_recommendations"] is None


def test_patch_business_settings_normalizes_email_and_phone(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "notification_email": "  MHANSON13@GMAIL.COM ",
            "notification_phone": " (303) 210-2035 ",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_email"] == "mhanson13@gmail.com"
    assert payload["notification_phone"] == "+13032102035"


def test_patch_business_settings_normalizes_global_e164_phone(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "notification_phone": "+44 20 7123 4567",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_phone"] == "+442071234567"


def test_patch_business_settings_invalid_email_rejected(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"notification_email": "bad-email"},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "notification_email")


def test_patch_business_settings_invalid_phone_rejected_when_sms_enabled(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "sms_enabled": True,
            "notification_phone": "1234",
        },
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "notification_phone")


def test_patch_business_settings_invalid_timezone_rejected(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"timezone": "Mars/Olympus"},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "timezone")


def test_patch_business_settings_rejects_contractor_alerts_with_no_channels(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "sms_enabled": False,
            "email_enabled": False,
            "contractor_alerts_enabled": True,
        },
    )

    assert response.status_code == 422
    assert "contractor_alerts_enabled" in response.json()["detail"]


def test_patch_business_settings_rejects_customer_ack_with_no_channels(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "sms_enabled": False,
            "email_enabled": False,
            "contractor_alerts_enabled": False,
            "customer_auto_ack_enabled": True,
        },
    )

    assert response.status_code == 422
    assert "customer_auto_ack_enabled" in response.json()["detail"]


def test_patch_business_settings_requires_admin_principal_role(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="settings-operator",
        principal_role=PrincipalRole.OPERATOR,
    )

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"timezone": "America/Chicago"},
    )

    assert response.status_code == 403


def test_patch_business_settings_rejects_crawl_page_limit_below_minimum(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"seo_audit_crawl_max_pages": 4},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "seo_audit_crawl_max_pages")


def test_patch_business_settings_accepts_crawl_page_limit_at_maximum(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"seo_audit_crawl_max_pages": 250},
    )

    assert response.status_code == 200
    assert response.json()["seo_audit_crawl_max_pages"] == 250


def test_patch_business_settings_rejects_crawl_page_limit_above_maximum(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"seo_audit_crawl_max_pages": 251},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "seo_audit_crawl_max_pages")


def test_patch_business_settings_rejects_extreme_crawl_page_limit(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"seo_audit_crawl_max_pages": 1000},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "seo_audit_crawl_max_pages")


def test_patch_business_settings_partial_crawl_update_ignores_invalid_competitor_settings(
    db_session,
    seeded_business,
) -> None:
    seeded_business.competitor_candidate_min_relevance_score = 999
    db_session.commit()

    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"seo_audit_crawl_max_pages": 250},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["seo_audit_crawl_max_pages"] == 250
    assert payload["competitor_candidate_min_relevance_score"] == 999


def test_patch_business_settings_accepts_candidate_quality_tuning_bounds(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "competitor_candidate_min_relevance_score": 100,
            "competitor_candidate_big_box_penalty": 50,
            "competitor_candidate_directory_penalty": 0,
            "competitor_candidate_local_alignment_bonus": 50,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["competitor_candidate_min_relevance_score"] == 100
    assert payload["competitor_candidate_big_box_penalty"] == 50
    assert payload["competitor_candidate_directory_penalty"] == 0
    assert payload["competitor_candidate_local_alignment_bonus"] == 50


def test_patch_business_settings_partial_candidate_update_ignores_invalid_crawl_limit(
    db_session,
    seeded_business,
) -> None:
    seeded_business.seo_audit_crawl_max_pages = 1000
    db_session.commit()

    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_min_relevance_score": 40},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["competitor_candidate_min_relevance_score"] == 40
    assert payload["seo_audit_crawl_max_pages"] == 1000


def test_patch_business_settings_rejects_candidate_min_relevance_out_of_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_min_relevance_score": 101},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "competitor_candidate_min_relevance_score")


def test_patch_business_settings_rejects_candidate_big_box_penalty_out_of_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_big_box_penalty": 51},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "competitor_candidate_big_box_penalty")


def test_patch_business_settings_rejects_candidate_directory_penalty_out_of_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_directory_penalty": 51},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "competitor_candidate_directory_penalty")


def test_patch_business_settings_rejects_candidate_local_bonus_out_of_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_local_alignment_bonus": 51},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "competitor_candidate_local_alignment_bonus")


def test_patch_business_settings_accepts_competitor_timeout_values_in_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "competitor_primary_timeout_seconds": 40,
            "competitor_degraded_timeout_seconds": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["competitor_primary_timeout_seconds"] == 40
    assert payload["competitor_degraded_timeout_seconds"] == 20


def test_patch_business_settings_rejects_primary_timeout_out_of_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_primary_timeout_seconds": 9},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "competitor_primary_timeout_seconds")


def test_patch_business_settings_rejects_degraded_timeout_out_of_range(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_degraded_timeout_seconds": 91},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "competitor_degraded_timeout_seconds")


def test_patch_business_settings_can_clear_competitor_timeout_values(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    seeded_business.competitor_primary_timeout_seconds = 44
    seeded_business.competitor_degraded_timeout_seconds = 22
    db_session.commit()

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "competitor_primary_timeout_seconds": None,
            "competitor_degraded_timeout_seconds": None,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["competitor_primary_timeout_seconds"] is None
    assert payload["competitor_degraded_timeout_seconds"] is None


def test_patch_business_settings_links_matching_tuning_preview_event(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Preview Link Site",
        base_url="https://preview-link.example/",
        normalized_domain="preview-link.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.flush()

    event = SEOCompetitorTuningPreviewEvent(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        source_narrative_id=None,
        source_recommendation_run_id=None,
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
            "telemetry_window": {
                "lookback_days": 30,
                "total_runs": 4,
                "total_raw_candidate_count": 12,
                "total_included_candidate_count": 6,
                "total_excluded_candidate_count": 6,
                "exclusion_counts_by_reason": {
                    "duplicate": 1,
                    "low_relevance": 3,
                    "directory_or_aggregator": 1,
                    "big_box_mismatch": 1,
                    "existing_domain_match": 0,
                    "invalid_candidate": 0,
                },
            },
            "estimated_impact": {
                "insufficient_data": False,
                "estimated_included_candidate_delta": 2,
                "estimated_excluded_candidate_delta": -2,
                "estimated_exclusion_reason_deltas": {
                    "duplicate": 0,
                    "low_relevance": -2,
                    "directory_or_aggregator": 0,
                    "big_box_mismatch": 0,
                    "existing_domain_match": 0,
                    "invalid_candidate": 0,
                },
                "summary": "Estimated increase of included candidates.",
                "risk_flags": [],
            },
            "caveat": "Preview is estimated only.",
        },
        applied_at=None,
        evaluated_generation_run_id=None,
        evaluated_at=None,
        estimated_included_delta=None,
        actual_included_delta=None,
        error_margin=None,
        direction_correct=None,
    )
    db_session.add(event)
    db_session.commit()

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_min_relevance_score": 30},
    )
    assert response.status_code == 200

    db_session.refresh(event)
    assert event.applied_at is not None


def test_patch_business_settings_links_explicit_tuning_preview_event_id(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Explicit Link Site",
        base_url="https://explicit-link.example/",
        normalized_domain="explicit-link.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.flush()

    explicit_event = SEOCompetitorTuningPreviewEvent(
        id=str(uuid4()),
        business_id=seeded_business.id,
        site_id=site.id,
        source_narrative_id=None,
        source_recommendation_run_id=None,
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
            "telemetry_window": {
                "lookback_days": 30,
                "total_runs": 2,
                "total_raw_candidate_count": 8,
                "total_included_candidate_count": 4,
                "total_excluded_candidate_count": 4,
                "exclusion_counts_by_reason": {
                    "duplicate": 0,
                    "low_relevance": 2,
                    "directory_or_aggregator": 1,
                    "big_box_mismatch": 1,
                    "existing_domain_match": 0,
                    "invalid_candidate": 0,
                },
            },
            "estimated_impact": {
                "insufficient_data": False,
                "estimated_included_candidate_delta": 1,
                "estimated_excluded_candidate_delta": -1,
                "estimated_exclusion_reason_deltas": {
                    "duplicate": 0,
                    "low_relevance": -1,
                    "directory_or_aggregator": 0,
                    "big_box_mismatch": 0,
                    "existing_domain_match": 0,
                    "invalid_candidate": 0,
                },
                "summary": "Estimated increase of included candidates.",
                "risk_flags": [],
            },
            "caveat": "Preview is estimated only.",
        },
        applied_at=None,
        evaluated_generation_run_id=None,
        evaluated_at=None,
        estimated_included_delta=None,
        actual_included_delta=None,
        error_margin=None,
        direction_correct=None,
    )
    db_session.add(explicit_event)
    db_session.commit()

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "competitor_candidate_min_relevance_score": 30,
            "competitor_tuning_preview_event_id": explicit_event.id,
        },
    )
    assert response.status_code == 200
    assert response.json()["competitor_candidate_min_relevance_score"] == 30

    db_session.refresh(explicit_event)
    assert explicit_event.applied_at is not None


def test_patch_business_settings_apply_mutates_only_targeted_candidate_field(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)
    before = db_session.get(type(seeded_business), seeded_business.id)
    assert before is not None
    baseline = (
        int(before.competitor_candidate_min_relevance_score),
        int(before.competitor_candidate_big_box_penalty),
        int(before.competitor_candidate_directory_penalty),
        int(before.competitor_candidate_local_alignment_bonus),
        int(before.seo_audit_crawl_max_pages),
    )

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"competitor_candidate_min_relevance_score": 30},
    )
    assert response.status_code == 200

    after = db_session.get(type(seeded_business), seeded_business.id)
    assert after is not None
    assert int(after.competitor_candidate_min_relevance_score) == 30
    assert int(after.competitor_candidate_big_box_penalty) == baseline[1]
    assert int(after.competitor_candidate_directory_penalty) == baseline[2]
    assert int(after.competitor_candidate_local_alignment_bonus) == baseline[3]
    assert int(after.seo_audit_crawl_max_pages) == baseline[4]

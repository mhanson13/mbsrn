from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.businesses import router as businesses_router
from app.models.principal import Principal, PrincipalRole


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
    assert payload["sms_enabled"] is True


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

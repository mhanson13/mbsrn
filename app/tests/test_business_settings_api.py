from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.routes.businesses import router as businesses_router


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


def _make_client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(businesses_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_get_business_settings_endpoint(db_session, seeded_business) -> None:
    client = _make_client(db_session)

    response = client.get(f"/api/businesses/{seeded_business.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == seeded_business.id
    assert payload["sms_enabled"] is True
    assert payload["email_enabled"] is True
    assert payload["customer_auto_ack_enabled"] is True
    assert payload["contractor_alerts_enabled"] is True


def test_patch_business_settings_valid_partial_update_succeeds(db_session, seeded_business) -> None:
    client = _make_client(db_session)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={
            "notification_email": "  OWNER+ALERTS@TMFIRE.EXAMPLE  ",
            "timezone": "America/Chicago",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_email"] == "owner+alerts@tmfire.example"
    assert payload["timezone"] == "America/Chicago"
    assert payload["sms_enabled"] is True


def test_patch_business_settings_normalizes_email_and_phone(db_session, seeded_business) -> None:
    client = _make_client(db_session)

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
    client = _make_client(db_session)

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
    client = _make_client(db_session)

    response = client.patch(
        f"/api/businesses/{seeded_business.id}/settings",
        json={"notification_email": "bad-email"},
    )

    assert response.status_code == 422
    assert _detail_contains_field(response.json()["detail"], "notification_email")


def test_patch_business_settings_invalid_phone_rejected_when_sms_enabled(db_session, seeded_business) -> None:
    client = _make_client(db_session)

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
    client = _make_client(db_session)

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
    client = _make_client(db_session)

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
    client = _make_client(db_session)

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

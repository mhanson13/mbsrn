from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.intake import router as intake_router
from app.core.time import utc_now


def test_manual_intake_endpoint_creates_lead(db_session, seeded_business) -> None:
    app = FastAPI()
    app.include_router(intake_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_tenant_context() -> TenantContext:
        return TenantContext(
            business_id=seeded_business.id,
            principal_id="test-principal",
            auth_source="test",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    client = TestClient(app)

    response = client.post(
        "/api/intake/manual",
        json={
            "business_id": seeded_business.id,
            "submitted_at": (utc_now() - timedelta(minutes=1)).isoformat(),
            "customer_name": "Robin",
            "phone": "+13035550124",
            "service_type": "smoke cleanup",
            "city": "Aurora",
            "message": "Need callback tonight",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["lead"]["source"] == "manual"
    assert payload["lead"]["status"] == "new"

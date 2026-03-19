from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.leads import router as leads_router
from app.core.time import utc_now
from app.models.lead import Lead, LeadSource, LeadStatus


def test_summary_endpoint_returns_counts(db_session: Session, seeded_business) -> None:
    now = utc_now()
    db_session.add_all(
        [
            Lead(
                id=str(uuid4()),
                business_id=seeded_business.id,
                source=LeadSource.MANUAL,
                source_ref=None,
                submitted_at=now - timedelta(hours=1),
                customer_name="A",
                phone="3035550101",
                status=LeadStatus.NEW,
            ),
            Lead(
                id=str(uuid4()),
                business_id=seeded_business.id,
                source=LeadSource.MANUAL,
                source_ref=None,
                submitted_at=now - timedelta(hours=2),
                customer_name="B",
                phone="3035550102",
                status=LeadStatus.CONTACTED,
                first_human_response_at=now - timedelta(hours=1, minutes=30),
            ),
        ]
    )
    db_session.commit()

    app = FastAPI()
    app.include_router(leads_router)

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

    response = client.get(
        "/api/leads/summary",
        params={"business_id": seeded_business.id, "window": "7d"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_leads"] == 2
    assert payload["by_status"]["new"] == 1
    assert payload["by_status"]["contacted"] == 1

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.admin_github_publish_config import router as admin_github_publish_config_router
from app.models.principal import Principal, PrincipalRole


def _make_client(
    db_session,
    *,
    business_id: str,
    principal_id: str = "admin-1",
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
    app.include_router(admin_github_publish_config_router)

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


def test_get_github_publish_config_returns_defaults_when_unset(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.get("/api/admin/github-publish-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["repository"] == ""
    assert payload["default_branch"] == "main"
    assert payload["base_path"] == "/"
    assert payload["enabled"] is False


def test_put_github_publish_config_persists_and_reads_back(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    update_response = client.put(
        "/api/admin/github-publish-config",
        json={
            "repository": "mhanson13/tnmfire",
            "default_branch": "main",
            "base_path": "/site",
            "enabled": True,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["repository"] == "mhanson13/tnmfire"
    assert updated["default_branch"] == "main"
    assert updated["base_path"] == "/site"
    assert updated["enabled"] is True

    get_response = client.get("/api/admin/github-publish-config")
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["repository"] == "mhanson13/tnmfire"
    assert fetched["default_branch"] == "main"
    assert fetched["base_path"] == "/site"
    assert fetched["enabled"] is True


def test_put_github_publish_config_rejects_enabled_without_repository(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "repository": "",
            "default_branch": "main",
            "base_path": "/",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert "repository is required" in response.json()["detail"]


def test_github_publish_config_routes_require_admin_role(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-1",
        principal_role=PrincipalRole.OPERATOR,
    )

    get_response = client.get("/api/admin/github-publish-config")
    assert get_response.status_code == 403

    put_response = client.put(
        "/api/admin/github-publish-config",
        json={
            "repository": "mhanson13/tnmfire",
            "default_branch": "main",
            "base_path": "/",
            "enabled": True,
        },
    )
    assert put_response.status_code == 403

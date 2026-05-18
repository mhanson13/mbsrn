from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import TenantContext, get_db, get_tenant_context
from app.api.routes.admin_github_publish_config import router as admin_github_publish_config_router
from app.core.config import get_settings
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
    assert payload["owner"] == ""
    assert payload["repository"] == ""
    assert payload["default_branch"] == "main"
    assert payload["base_path"] == "/"
    assert payload["deploy_workflow_mode"] == "site_repo_template_v1"
    assert payload["target_environment_key"] == "gke_prod"
    assert payload["target_environment_source"] == "admin_config"
    assert payload["github_repository_auto_create_enabled"] is False
    assert payload["managed_gke_cluster_name"] is None
    assert payload["managed_gke_cluster_location"] is None
    assert payload["managed_gke_project_id"] is None
    assert payload["managed_gcp_deploy_key_configured"] is False
    assert payload["managed_gcp_deploy_key_updated_at"] is None
    assert payload["namespace_isolation_defaults"] == {
        "resource_quota": {
            "enabled": False,
            "requests_cpu": "1000m",
            "requests_memory": "1Gi",
            "limits_cpu": "2000m",
            "limits_memory": "2Gi",
            "pods": 20,
            "services": 10,
            "configmaps": 40,
            "secrets": 40,
            "persistentvolumeclaims": 10,
        },
        "limit_range": {
            "enabled": False,
            "default_cpu": "500m",
            "default_memory": "512Mi",
            "default_request_cpu": "250m",
            "default_request_memory": "256Mi",
            "min_cpu": "100m",
            "min_memory": "128Mi",
            "max_cpu": "2000m",
            "max_memory": "2Gi",
        },
        "network_policy": {
            "enabled": False,
            "mode": "default_deny_ingress",
        },
        "migration_generation_budget": {
            "migration_context_budget_chars": 18000,
            "migration_recommendation_limit": 6,
            "migration_competitor_limit": 8,
            "migration_source_page_summary_limit": 8,
            "migration_media_asset_limit": 24,
            "migration_generated_page_limit": 12,
            "migration_generated_file_limit": 12,
            "migration_generation_depth": "standard",
            "migration_variation_level": "balanced",
            "migration_require_page_variety": True,
            "migration_require_design_variation": True,
        },
        "migration_generation_safety": {
            "migration_provider_timeout_seconds": 300,
            "migration_preflight_mode": "compact_fallback",
            "migration_max_final_input_chars": 9000,
            "migration_max_difficulty_score": 12,
            "migration_compact_fallback_enabled": True,
            "migration_compact_page_limit": 4,
            "migration_compact_media_asset_limit": 3,
            "migration_compact_recommendation_limit": 4,
        },
    }
    assert payload["enabled"] is False


def test_put_github_publish_config_persists_and_reads_back(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    update_response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/site",
            "deploy_workflow_mode": "site_repo_template_v1",
            "target_environment_key": "gke_prod_us_central1",
            "github_repository_auto_create_enabled": True,
            "managed_gke_cluster_name": "mbsrn-cluster",
            "managed_gke_cluster_location": "us-central1",
            "managed_gke_project_id": "mbsrn-prod",
            "namespace_isolation_defaults": {
                "resource_quota": {
                    "enabled": True,
                    "requests_cpu": "1200m",
                    "requests_memory": "2Gi",
                    "limits_cpu": "2400m",
                    "limits_memory": "3Gi",
                    "pods": 25,
                    "services": 12,
                    "configmaps": 50,
                    "secrets": 50,
                    "persistentvolumeclaims": 12,
                },
                "limit_range": {
                    "enabled": True,
                    "default_cpu": "600m",
                    "default_memory": "768Mi",
                    "default_request_cpu": "300m",
                    "default_request_memory": "384Mi",
                    "min_cpu": "150m",
                    "min_memory": "192Mi",
                    "max_cpu": "2600m",
                    "max_memory": "4Gi",
                },
                "network_policy": {
                    "enabled": True,
                    "mode": "default_deny_ingress",
                },
                "migration_generation_safety": {
                    "migration_provider_timeout_seconds": 240,
                    "migration_preflight_mode": "block_before_provider",
                    "migration_max_final_input_chars": 8500,
                    "migration_max_difficulty_score": 11,
                    "migration_compact_fallback_enabled": True,
                    "migration_compact_page_limit": 3,
                    "migration_compact_media_asset_limit": 2,
                    "migration_compact_recommendation_limit": 3,
                },
            },
            "enabled": True,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["owner"] == "mhanson13"
    assert updated["repository"] == "mhanson13"
    assert updated["default_branch"] == "main"
    assert updated["base_path"] == "/site"
    assert updated["deploy_workflow_mode"] == "site_repo_template_v1"
    assert updated["target_environment_key"] == "gke_prod_us_central1"
    assert updated["target_environment_source"] == "admin_config"
    assert updated["github_repository_auto_create_enabled"] is True
    assert updated["managed_gke_cluster_name"] == "mbsrn-cluster"
    assert updated["managed_gke_cluster_location"] == "us-central1"
    assert updated["managed_gke_project_id"] == "mbsrn-prod"
    assert updated["managed_gcp_deploy_key_configured"] is False
    assert updated["managed_gcp_deploy_key_updated_at"] is None
    assert updated["namespace_isolation_defaults"]["resource_quota"]["enabled"] is True
    assert updated["namespace_isolation_defaults"]["resource_quota"]["requests_cpu"] == "1200m"
    assert updated["namespace_isolation_defaults"]["limit_range"]["enabled"] is True
    assert updated["namespace_isolation_defaults"]["network_policy"] == {
        "enabled": True,
        "mode": "default_deny_ingress",
    }
    assert updated["namespace_isolation_defaults"]["migration_generation_safety"] == {
        "migration_provider_timeout_seconds": 240,
        "migration_preflight_mode": "block_before_provider",
        "migration_max_final_input_chars": 8500,
        "migration_max_difficulty_score": 11,
        "migration_compact_fallback_enabled": True,
        "migration_compact_page_limit": 3,
        "migration_compact_media_asset_limit": 2,
        "migration_compact_recommendation_limit": 3,
    }
    assert updated["enabled"] is True

    get_response = client.get("/api/admin/github-publish-config")
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["owner"] == "mhanson13"
    assert fetched["repository"] == "mhanson13"
    assert fetched["default_branch"] == "main"
    assert fetched["base_path"] == "/site"
    assert fetched["deploy_workflow_mode"] == "site_repo_template_v1"
    assert fetched["target_environment_key"] == "gke_prod_us_central1"
    assert fetched["target_environment_source"] == "admin_config"
    assert fetched["github_repository_auto_create_enabled"] is True
    assert fetched["managed_gke_cluster_name"] == "mbsrn-cluster"
    assert fetched["managed_gke_cluster_location"] == "us-central1"
    assert fetched["managed_gke_project_id"] == "mbsrn-prod"
    assert fetched["managed_gcp_deploy_key_configured"] is False
    assert fetched["managed_gcp_deploy_key_updated_at"] is None
    assert fetched["namespace_isolation_defaults"] == updated["namespace_isolation_defaults"]
    assert fetched["enabled"] is True


def test_put_github_publish_config_sets_managed_gcp_deploy_key_status_without_exposing_value(
    db_session,
    seeded_business,
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_SESSION_SECRET", "test-app-session-secret-for-managed-deploy")
    get_settings.cache_clear()
    try:
        client = _make_client(db_session, business_id=seeded_business.id)
        payload = '{"type":"service_account","project_id":"mbsrn-prod"}'

        update_response = client.put(
            "/api/admin/github-publish-config",
            json={
                "owner": "mhanson13",
                "default_branch": "main",
                "base_path": "/",
                "managed_gcp_deploy_key_value": payload,
                "enabled": True,
            },
        )

        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["managed_gcp_deploy_key_configured"] is True
        assert updated["managed_gcp_deploy_key_updated_at"] is not None
        assert "managed_gcp_deploy_key_value" not in updated

        get_response = client.get("/api/admin/github-publish-config")
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["managed_gcp_deploy_key_configured"] is True
        assert fetched["managed_gcp_deploy_key_updated_at"] is not None
        assert "managed_gcp_deploy_key_value" not in fetched
    finally:
        get_settings.cache_clear()


def test_put_github_publish_config_clears_managed_gcp_deploy_key(
    db_session,
    seeded_business,
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_SESSION_SECRET", "test-app-session-secret-for-managed-deploy")
    get_settings.cache_clear()
    try:
        client = _make_client(db_session, business_id=seeded_business.id)
        seed_response = client.put(
            "/api/admin/github-publish-config",
            json={
                "owner": "mhanson13",
                "default_branch": "main",
                "base_path": "/",
                "managed_gcp_deploy_key_value": '{"type":"service_account","project_id":"mbsrn-prod"}',
                "enabled": True,
            },
        )
        assert seed_response.status_code == 200
        assert seed_response.json()["managed_gcp_deploy_key_configured"] is True

        clear_response = client.put(
            "/api/admin/github-publish-config",
            json={
                "owner": "mhanson13",
                "default_branch": "main",
                "base_path": "/",
                "managed_gcp_deploy_key_clear": True,
                "enabled": True,
            },
        )
        assert clear_response.status_code == 200
        cleared = clear_response.json()
        assert cleared["managed_gcp_deploy_key_configured"] is False
        assert cleared["managed_gcp_deploy_key_updated_at"] is not None
    finally:
        get_settings.cache_clear()


def test_put_github_publish_config_rejects_setting_and_clearing_managed_key_together(
    db_session,
    seeded_business,
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_SESSION_SECRET", "test-app-session-secret-for-managed-deploy")
    get_settings.cache_clear()
    try:
        client = _make_client(db_session, business_id=seeded_business.id)
        response = client.put(
            "/api/admin/github-publish-config",
            json={
                "owner": "mhanson13",
                "default_branch": "main",
                "base_path": "/",
                "managed_gcp_deploy_key_value": '{"type":"service_account","project_id":"mbsrn-prod"}',
                "managed_gcp_deploy_key_clear": True,
                "enabled": True,
            },
        )
        assert response.status_code == 422
        assert "cannot be set and cleared" in str(response.json().get("detail", "")).lower()
    finally:
        get_settings.cache_clear()


def test_put_github_publish_config_allows_clearing_managed_gke_fields_with_blank_values(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    seed_response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/site",
            "deploy_workflow_mode": "site_repo_template_v1",
            "target_environment_key": "gke_prod",
            "managed_gke_cluster_name": "mbsrn-cluster",
            "managed_gke_cluster_location": "us-central1",
            "managed_gke_project_id": "mbsrn-prod",
            "enabled": True,
        },
    )
    assert seed_response.status_code == 200

    clear_response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/site",
            "deploy_workflow_mode": "site_repo_template_v1",
            "target_environment_key": "gke_prod",
            "managed_gke_cluster_name": "   ",
            "managed_gke_cluster_location": "",
            "managed_gke_project_id": " ",
            "enabled": True,
        },
    )
    assert clear_response.status_code == 200
    cleared = clear_response.json()
    assert cleared["managed_gke_cluster_name"] is None
    assert cleared["managed_gke_cluster_location"] is None
    assert cleared["managed_gke_project_id"] is None


def test_put_github_publish_config_rejects_invalid_namespace_isolation_defaults(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "namespace_isolation_defaults": {
                "resource_quota": {
                    "enabled": True,
                    "requests_cpu": "bad-cpu",
                }
            },
            "enabled": True,
        },
    )

    assert response.status_code == 422
    detail = str(response.json().get("detail", ""))
    assert "requests_cpu" in detail


def test_put_github_publish_config_rejects_invalid_migration_generation_safety_ranges(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "namespace_isolation_defaults": {
                "migration_generation_safety": {
                    "migration_provider_timeout_seconds": 601,
                    "migration_preflight_mode": "invalid_mode",
                }
            },
            "enabled": True,
        },
    )

    assert response.status_code == 422
    detail = str(response.json().get("detail", ""))
    assert "migration_provider_timeout_seconds" in detail or "migration_preflight_mode" in detail


def test_put_github_publish_config_accepts_max_migration_provider_timeout_seconds(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "namespace_isolation_defaults": {
                "migration_generation_safety": {
                    "migration_provider_timeout_seconds": 600,
                }
            },
            "enabled": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace_isolation_defaults"]["migration_generation_safety"]["migration_provider_timeout_seconds"] == 600


def test_put_github_publish_config_rejects_migration_provider_timeout_seconds_6000(
    db_session,
    seeded_business,
) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "namespace_isolation_defaults": {
                "migration_generation_safety": {
                    "migration_provider_timeout_seconds": 6000,
                }
            },
            "enabled": True,
        },
    )

    assert response.status_code == 422
    detail = str(response.json().get("detail", ""))
    assert "migration_provider_timeout_seconds" in detail


def test_put_github_publish_config_rejects_enabled_without_owner(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "",
            "default_branch": "main",
            "base_path": "/",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert "GitHub owner is required" in response.json()["detail"]


def test_put_github_publish_config_rejects_invalid_owner_format(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "invalid owner",
            "default_branch": "main",
            "base_path": "/",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert "GitHub owner is invalid" in response.json()["detail"]


def test_put_github_publish_config_rejects_empty_default_branch_when_enabled(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "   ",
            "base_path": "/",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert "Default branch is required" in response.json()["detail"]


def test_put_github_publish_config_rejects_invalid_deploy_workflow_mode(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "deploy_workflow_mode": "unknown_mode_v9",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert "Deploy workflow mode is invalid" in response.json()["detail"]


def test_put_github_publish_config_rejects_invalid_target_environment_key(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "target_environment_key": "BAD KEY",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert "Target environment key is invalid" in response.json()["detail"]


def test_put_github_publish_config_normalizes_base_path(db_session, seeded_business) -> None:
    client = _make_client(db_session, business_id=seeded_business.id)

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "site//docs/",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_path"] == "/site/docs"


def test_put_github_publish_config_emits_structured_update_log(db_session, seeded_business, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.github_publish_config")
    client = _make_client(db_session, business_id=seeded_business.id, principal_id="admin-audit-1")

    response = client.put(
        "/api/admin/github-publish-config",
        json={
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/site",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    log_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "admin_github_publish_config_updated"
    ]
    assert log_payloads
    payload = log_payloads[-1]
    assert payload.get("actor_principal_id") == "admin-audit-1"
    assert payload.get("actor_business_id") == seeded_business.id
    assert "owner" in (payload.get("changed_fields") or [])
    assert "enabled" in (payload.get("changed_fields") or [])


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
            "owner": "mhanson13",
            "default_branch": "main",
            "base_path": "/",
            "enabled": True,
        },
    )
    assert put_response.status_code == 403

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_migration_artifact_provider,
    get_seo_migration_github_publisher,
    get_seo_migration_ingest_service,
    get_tenant_context,
)
from app.api.routes.seo_migration import router as seo_migration_router
from app.integrations.seo_migration_artifact_provider import MockSEOMigrationArtifactGenerationProvider
from app.integrations.seo_migration_github_publisher import (
    MisconfiguredSEOMigrationGitHubPublisher,
    SEOMigrationGitHubDeployResult,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishResult,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
)
from app.models.business import Business
from app.models.seo_site import SEOSite
from app.services.seo_migration_ingest import (
    SEOMigrationIngestResult,
    SEOMigrationSourceIngestError,
)


class _StubMigrationIngestService:
    def ingest_homepage(self, *, source_url: str) -> SEOMigrationIngestResult:
        if "fail-ingest" in source_url:
            raise SEOMigrationSourceIngestError("Source ingest failed due to simulated failure.")
        return SEOMigrationIngestResult(
            source_url=source_url.rstrip("/") + "/",
            snapshot={
                "fetched_at": "2026-04-07T10:00:00+00:00",
                "final_url": source_url.rstrip("/") + "/",
                "status_code": 200,
                "content_type": "text/html",
                "title": "Legacy Site",
                "meta_description": "Legacy SMB brochure copy.",
                "canonical_url": source_url.rstrip("/") + "/",
                "headings": ["Legacy Site"],
                "contact_signals": ["Call for quote"],
                "phone_numbers": ["+13035550100"],
                "emails": ["info@legacy.example"],
                "addresses": ["123 Main Street"],
                "internal_links": [source_url.rstrip("/") + "/services"],
                "service_blocks": ["Installation and maintenance"],
                "asset_references": {"stylesheets": [], "scripts": [], "images": []},
                "cleaned_text_blocks": ["Legacy content block"],
                "warnings": [],
            },
            warnings=(),
        )


class _StubMigrationGitHubPublisher(SEOMigrationGitHubPublisher):
    def __init__(self, *, fail_publish: bool = False, fail_deploy: bool = False) -> None:
        self.fail_publish = fail_publish
        self.fail_deploy = fail_deploy
        self.publish_calls: list[tuple[SEOMigrationGitHubPublishTarget, list[SEOMigrationGitHubPublishFile], bool]] = []
        self.deploy_calls: list[tuple[SEOMigrationGitHubDeployTarget, bool]] = []

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        del commit_message
        self.publish_calls.append((target, files, dry_run))
        if self.fail_publish:
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="Simulated publish failure.",
            )
        return SEOMigrationGitHubPublishResult(
            dry_run=dry_run,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            branch=target.branch,
            artifact_root=target.artifact_root,
            files_published=len(files),
            total_bytes=sum(len(item.content.encode("utf-8")) for item in files),
            commit_shas=() if dry_run else ("abc123",),
            committed_paths=tuple(item.path for item in files),
            published_at="2026-04-07T12:00:00+00:00",
        )

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
    ) -> SEOMigrationGitHubDeployResult:
        self.deploy_calls.append((target, dry_run))
        if self.fail_deploy:
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="Simulated deploy failure.",
            )
        return SEOMigrationGitHubDeployResult(
            dry_run=dry_run,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            inputs=dict(target.inputs),
            dispatched_at="2026-04-07T12:10:00+00:00",
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
    github_publisher: SEOMigrationGitHubPublisher | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_migration_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    app.dependency_overrides[get_seo_migration_ingest_service] = lambda: _StubMigrationIngestService()
    app.dependency_overrides[get_seo_migration_artifact_provider] = lambda: MockSEOMigrationArtifactGenerationProvider(
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    if github_publisher is not None:
        app.dependency_overrides[get_seo_migration_github_publisher] = lambda: github_publisher
    return TestClient(app)


def _seed_business_and_site(db_session, *, business_id: str, site_id: str) -> None:
    business = Business(
        id=business_id,
        name="TNM Fire Protection",
        notification_phone="+13035550199",
        notification_email="owner@tnmfire.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    site = SEOSite(
        id=site_id,
        business_id=business_id,
        display_name="TNM Fire",
        base_url="https://tnmfire.example/",
        normalized_domain="tnmfire.example",
        industry="fire protection",
        primary_location="Longmont, CO",
        service_areas_json=["Longmont", "Boulder"],
        is_active=True,
        is_primary=True,
    )
    db_session.add(business)
    db_session.add(site)
    db_session.commit()


def test_migration_api_happy_path_workflow(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher()
    client = _make_client(db_session, business_id=business_id, github_publisher=publisher)

    upsert_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "operator_requirements": {
                "business_objectives": ["Replace weak legacy pages"],
                "requested_pages": ["Homepage", "Services", "Contact"],
            },
            "enriched_content_notes": {
                "replacement_summary": "Use richer service-specific content and trust proof.",
                "service_highlights": ["Installation", "Inspection"],
            },
            "publish_config": {
                "enabled": True,
                "repo_owner": "acme",
                "repo_name": "tnmfire-site",
                "branch": "main",
                "artifact_root": "sites/tnmfire",
            },
            "deploy_config": {
                "enabled": True,
                "workflow_id": "deploy-www-prod.yml",
                "ref": "main",
            },
            "analytics_config": {
                "enabled": True,
                "ga_measurement_id": "G-ABCD1234",
                "insertion_mode": "publish_and_deploy",
            },
        },
    )
    assert upsert_response.status_code == 200
    workspace_id = upsert_response.json()["id"]

    ingest_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/source-ingest",
        json={"source_url": "https://legacy.example"},
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json()["source_site_status"] == "ingested"

    requirements_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/operator-requirements",
        json={
            "operator_requirements": {
                "business_objectives": ["Improve trust and conversion"],
                "requested_pages": ["Homepage", "Services", "Contact"],
                "calls_to_action": ["Request a Quote"],
            }
        },
    )
    assert requirements_response.status_code == 200

    enriched_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/enriched-content",
        json={
            "enriched_content_notes": {
                "replacement_summary": "Prepared replacement copy set.",
                "homepage_value_proposition": "Fast local fire protection service.",
                "trust_signals": ["Licensed and insured", "24/7 response"],
            }
        },
    )
    assert enriched_response.status_code == 200

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["workspace"]["id"] == workspace_id
    assert summary_payload["source_snapshot"]["title"] == "Legacy Site"
    assert "Draft artifacts only" in summary_payload["draft_only_notice"]

    prompt_preview_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/prompt-preview")
    assert prompt_preview_response.status_code == 200
    assert prompt_preview_response.json()["prompt_version"] == "seo-migration-v1"

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": False},
    )
    assert generate_response.status_code == 201
    generated_artifact = generate_response.json()
    artifact_id = generated_artifact["id"]
    assert generated_artifact["version"] == 1
    assert generated_artifact["file_count"] >= 1

    approve_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/approve",
        json={"approval_notes": "Approved for publish/deploy"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["approval_status"] == "approved"

    publish_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
            "commit_message": "Publish migrated site",
        },
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["workspace"]["publish_status"] == "published"
    assert publish_response.json()["artifact"]["publish_status"] == "published"

    deploy_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert deploy_response.status_code == 200
    assert deploy_response.json()["workspace"]["deploy_status"] == "deploy_requested"
    assert deploy_response.json()["artifact"]["deploy_status"] == "deploy_requested"

    publish_history_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish-history"
    )
    assert publish_history_response.status_code == 200
    assert publish_history_response.json()["total"] >= 1

    deploy_history_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-history")
    assert deploy_history_response.status_code == 200
    assert deploy_history_response.json()["total"] >= 1

    versions_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions")
    assert versions_response.status_code == 200
    assert versions_response.json()["total"] == 1
    assert versions_response.json()["items"][0]["id"] == artifact_id

    version_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}"
    )
    assert version_response.status_code == 200
    assert version_response.json()["id"] == artifact_id

    file_preview_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/file-preview",
        params={"path": "index.html"},
    )
    assert file_preview_response.status_code == 200
    assert file_preview_response.json()["path"] == "index.html"
    assert "ANALYTICS_PLACEHOLDER" in file_preview_response.json()["content"]
    assert publisher.publish_calls
    assert publisher.deploy_calls


def test_migration_summary_requires_existing_workspace(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert response.status_code == 404
    assert response.json()["detail"] == "Migration workspace not found"


def test_publish_requires_approved_artifact_version(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=_StubMigrationGitHubPublisher(),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "acme",
                "repo_name": "tnmfire-site",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    publish_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": True,
        },
    )
    assert publish_response.status_code == 422
    assert "not approved" in publish_response.json()["detail"].lower()


def test_publish_duplicate_returns_operator_usable_422(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=_StubMigrationGitHubPublisher(),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "acme",
                "repo_name": "tnmfire-site",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    approve_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/approve",
        json={"approval_notes": "Approved"},
    )
    assert approve_response.status_code == 200

    first_publish = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert first_publish.status_code == 200

    duplicate_publish = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert duplicate_publish.status_code == 422
    detail = str(duplicate_publish.json().get("detail") or "")
    assert "already published" in detail.lower()
    assert "traceback" not in detail.lower()


def test_migration_summary_contract_includes_readiness_and_history_shapes(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    payload = summary_response.json()

    assert isinstance(payload.get("publish_readiness"), dict)
    assert isinstance(payload.get("deploy_readiness"), dict)
    assert isinstance(payload["publish_readiness"].get("ready"), bool)
    assert isinstance(payload["publish_readiness"].get("reasons"), list)
    assert isinstance(payload["publish_readiness"].get("target"), dict)
    assert isinstance(payload["publish_readiness"].get("config_prerequisites"), dict)
    assert "last_status" in payload["publish_readiness"]
    assert "last_failure_category" in payload["publish_readiness"]
    assert "last_failure_message" in payload["publish_readiness"]
    assert isinstance(payload["deploy_readiness"].get("ready"), bool)
    assert isinstance(payload["deploy_readiness"].get("reasons"), list)
    assert isinstance(payload["deploy_readiness"].get("target"), dict)
    assert isinstance(payload["deploy_readiness"].get("config_prerequisites"), dict)
    assert "last_status" in payload["deploy_readiness"]
    assert "last_failure_category" in payload["deploy_readiness"]
    assert "last_failure_message" in payload["deploy_readiness"]
    migration_diagnostics = payload.get("context_summary", {}).get("migration_diagnostics")
    assert isinstance(migration_diagnostics, dict)
    assert "last_publish_status" in migration_diagnostics
    assert "last_deploy_status" in migration_diagnostics
    assert isinstance(payload.get("publish_history"), list)
    assert isinstance(payload.get("deploy_history"), list)


def test_publish_missing_runtime_config_surfaces_config_diagnostics(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=MisconfiguredSEOMigrationGitHubPublisher(
            safe_message="GitHub migration publisher is not configured.",
        ),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "acme",
                "repo_name": "tnmfire-site",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    approve_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/approve",
        json={"approval_notes": "Approved"},
    )
    assert approve_response.status_code == 200

    publish_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert publish_response.status_code == 422
    assert "not configured" in str(publish_response.json().get("detail") or "").lower()

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    publish_readiness = summary_response.json()["publish_readiness"]
    assert publish_readiness.get("failure_category") == "config_missing"
    prereqs = publish_readiness.get("config_prerequisites")
    assert isinstance(prereqs, dict)
    assert prereqs.get("github_publisher_configured") is False


def test_publish_failure_history_and_summary_include_failure_category(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=_StubMigrationGitHubPublisher(fail_publish=True),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "acme",
                "repo_name": "tnmfire-site",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    approve_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/approve",
        json={"approval_notes": "Approved"},
    )
    assert approve_response.status_code == 200

    publish_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert publish_response.status_code == 422
    assert "simulated publish failure" in str(publish_response.json().get("detail") or "").lower()
    assert "traceback" not in str(publish_response.json().get("detail") or "").lower()

    history_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish-history")
    assert history_response.status_code == 200
    items = history_response.json().get("items") or []
    assert items
    assert items[-1].get("failure_category") == "provider_error"
    assert items[-1].get("error_summary") == "Simulated publish failure."

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    publish_readiness = summary_response.json()["publish_readiness"]
    assert publish_readiness.get("last_failure_category") == "provider_error"
    assert publish_readiness.get("last_failure_message") == "Simulated publish failure."


def test_migration_summary_diagnostics_contract_tracks_publish_and_deploy_state_transitions(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=_StubMigrationGitHubPublisher(fail_deploy=True),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "acme",
                "repo_name": "tnmfire-site",
                "branch": "main",
            },
            "deploy_config": {
                "enabled": True,
                "workflow_id": "deploy-www-prod.yml",
                "ref": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    approve_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/approve",
        json={"approval_notes": "Approved"},
    )
    assert approve_response.status_code == 200

    publish_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert publish_response.status_code == 200

    deploy_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert deploy_response.status_code == 422
    assert "simulated deploy failure" in str(deploy_response.json().get("detail") or "").lower()

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    payload = summary_response.json()

    publish_readiness = payload.get("publish_readiness") or {}
    deploy_readiness = payload.get("deploy_readiness") or {}
    diagnostics = payload.get("context_summary", {}).get("migration_diagnostics") or {}

    publish_prereqs = publish_readiness.get("config_prerequisites") or {}
    deploy_prereqs = deploy_readiness.get("config_prerequisites") or {}
    assert isinstance(publish_prereqs.get("github_publisher_configured"), bool)
    assert isinstance(publish_prereqs.get("target_config_valid"), bool)
    assert isinstance(publish_prereqs.get("target_enabled"), bool)
    assert isinstance(deploy_prereqs.get("github_publisher_configured"), bool)
    assert isinstance(deploy_prereqs.get("target_config_valid"), bool)
    assert isinstance(deploy_prereqs.get("target_enabled"), bool)

    assert diagnostics.get("last_publish_status") == "published"
    assert diagnostics.get("last_publish_failure_category") is None
    assert diagnostics.get("last_publish_failure_message") is None
    assert diagnostics.get("last_deploy_status") == "failed"
    assert diagnostics.get("last_deploy_failure_category") == "deploy_error"
    assert diagnostics.get("last_deploy_failure_message") == "Simulated deploy failure."

    assert publish_readiness.get("last_status") == "published"
    assert publish_readiness.get("last_failure_category") is None
    assert publish_readiness.get("last_failure_message") is None
    assert deploy_readiness.get("last_status") == "failed"
    assert deploy_readiness.get("last_failure_category") == "deploy_error"
    assert deploy_readiness.get("last_failure_message") == "Simulated deploy failure."

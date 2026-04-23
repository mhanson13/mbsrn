from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.time import utc_now
from app.core.config import get_settings
from app.api.deps import (
    TenantContext,
    get_db,
    get_seo_migration_artifact_provider,
    get_seo_migration_github_publisher,
    get_seo_migration_ingest_service,
    get_tenant_context,
)
from app.api.routes.seo_migration import router as seo_migration_router
from app.integrations.seo_migration_artifact_provider import (
    MockSEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactGenerationOutput,
    SEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
    SEOMigrationGeneratedFileOutput,
    SEOMigrationProviderCompatibilityResult,
)
from app.integrations.seo_migration_github_publisher import (
    GitHubSEOMigrationPublisher,
    MisconfiguredSEOMigrationGitHubPublisher,
    SEOMigrationGitHubActionsSecretUpsertResult,
    SEOMigrationGitHubDeployResult,
    SEOMigrationGitHubDeployRunStatusResult,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishPreflightResult,
    SEOMigrationGitHubPublishResult,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
    SEOMigrationGitHubRepositoryEnsureResult,
    SEOMigrationGitHubTargetReadinessResult,
    SEOMigrationGitHubWorkflowProvisionResult,
)
from app.models.business import Business
from app.models.github_publish_config import GitHubPublishConfig
from app.models.principal import PrincipalRole
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite
from app.services.seo_migration_ingest import (
    SEOMigrationIngestResult,
    SEOMigrationSourceIngestError,
)


@pytest.fixture(autouse=True)
def _ensure_test_gcp_deploy_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "GCP_DEPLOY_KEY",
        os.getenv("GCP_DEPLOY_KEY", '{"type":"service_account","project_id":"test-project"}'),
    )
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


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
    def __init__(
        self,
        *,
        fail_publish: bool = False,
        fail_deploy: bool = False,
        fail_workflow_provision: bool = False,
        existing_workflow: bool = True,
        deploy_workflow_run_id: int | None = None,
        deploy_workflow_run_status: str | None = None,
        deploy_workflow_run_conclusion: str | None = None,
        refresh_workflow_run_status: str | None = None,
        refresh_workflow_run_conclusion: str | None = None,
        refresh_workflow_output: dict[str, str] | None = None,
        deploy_target_dispatch_service_reason_code: str | None = None,
    ) -> None:
        self.fail_publish = fail_publish
        self.fail_deploy = fail_deploy
        self.fail_workflow_provision = fail_workflow_provision
        self.existing_workflow = existing_workflow
        self.deploy_workflow_run_id = deploy_workflow_run_id
        self.deploy_workflow_run_status = deploy_workflow_run_status
        self.deploy_workflow_run_conclusion = deploy_workflow_run_conclusion
        self.refresh_workflow_run_status = refresh_workflow_run_status
        self.refresh_workflow_run_conclusion = refresh_workflow_run_conclusion
        self.refresh_workflow_output = dict(refresh_workflow_output or {})
        self.deploy_target_dispatch_service_reason_code = (
            (deploy_target_dispatch_service_reason_code or "").strip().lower() or None
        )
        self.publish_calls: list[tuple[SEOMigrationGitHubPublishTarget, list[SEOMigrationGitHubPublishFile], bool]] = []
        self.deploy_calls: list[tuple[SEOMigrationGitHubDeployTarget, bool]] = []
        self.refresh_calls: list[tuple[SEOMigrationGitHubDeployTarget, int, str | None]] = []
        self.secret_upsert_calls: list[tuple[str, str, str, str]] = []
        self.workflow_provision_calls: list[
            tuple[
                str,
                str,
                str,
                str,
                bool,
                str | None,
                str | None,
                str | None,
                dict[str, object] | None,
                str | None,
            ]
        ] = []

    def ensure_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        auto_create_enabled: bool,
        create_if_missing: bool = True,
        expected_owner: str | None = None,
        private_by_default: bool = True,
    ) -> SEOMigrationGitHubRepositoryEnsureResult:
        del auto_create_enabled, create_if_missing, expected_owner, private_by_default
        return SEOMigrationGitHubRepositoryEnsureResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            exists=True,
            auto_create_enabled=False,
            auto_create_attempted=False,
            auto_create_created=False,
            outcome="repo_exists",
            skipped_reason=None,
        )

    def run_publish_preflight(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        target_ref: str,
        auto_create_enabled: bool,
        expected_owner: str | None = None,
    ) -> SEOMigrationGitHubPublishPreflightResult:
        del auto_create_enabled, expected_owner
        return SEOMigrationGitHubPublishPreflightResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            target_ref=target_ref,
            repo_exists=True,
            repo_ensure_outcome="exists",
            target_ref_exists=True,
            repo_initialized=True,
            can_read_contents=True,
            can_write_contents=True,
            can_write_workflows=True,
            would_auto_create_repo=False,
            would_bootstrap_branch=False,
            preflight_status="ready",
            preflight_blocker_code=None,
        )

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

    def upsert_actions_secret(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        secret_name: str,
        secret_value: str,
    ) -> SEOMigrationGitHubActionsSecretUpsertResult:
        self.secret_upsert_calls.append((repo_owner, repo_name, secret_name, secret_value))
        return SEOMigrationGitHubActionsSecretUpsertResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            secret_name=secret_name,
            action="created",
            updated_at="2026-04-07T12:01:00+00:00",
        )

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        del managed_gke_config
        self.deploy_calls.append((target, dry_run))
        if self.deploy_target_dispatch_service_reason_code and not dry_run:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_dispatchable",
                safe_message="Simulated deploy target configuration is missing required GKE environment values.",
                stage="workflow_lookup",
            )
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
            workflow_run_id=self.deploy_workflow_run_id,
            workflow_run_status=self.deploy_workflow_run_status,
            workflow_run_conclusion=self.deploy_workflow_run_conclusion,
        )

    def refresh_deploy_run_status(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult:
        self.refresh_calls.append((target, workflow_run_id, dispatched_at))
        return SEOMigrationGitHubDeployRunStatusResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            workflow_run_id=workflow_run_id,
            workflow_run_status=self.refresh_workflow_run_status,
            workflow_run_conclusion=self.refresh_workflow_run_conclusion,
            workflow_output=dict(self.refresh_workflow_output),
            refreshed_at="2026-04-07T12:20:00+00:00",
        )

    def ensure_deploy_workflow(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        workflow_id: str,
        dry_run: bool,
        deploy_workflow_mode: str | None = None,
        target_environment_key: str | None = None,
        target_environment_source: str | None = None,
        managed_gke_config: dict[str, object] | None = None,
        namespace_isolation_defaults: dict[str, object] | None = None,
        site_id: str | None = None,
        repository_auto_create_created: bool | None = None,
    ) -> SEOMigrationGitHubWorkflowProvisionResult:
        self.workflow_provision_calls.append(
            (
                repo_owner,
                repo_name,
                branch,
                workflow_id,
                dry_run,
                deploy_workflow_mode,
                target_environment_key,
                target_environment_source,
                managed_gke_config,
                namespace_isolation_defaults,
                site_id,
                repository_auto_create_created,
            )
        )
        if self.fail_workflow_provision:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_provision_failed",
                safe_message="Simulated workflow provisioning failure.",
            )
        provisioned = (not self.existing_workflow) and (not dry_run)
        if provisioned:
            self.existing_workflow = True
        return SEOMigrationGitHubWorkflowProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            workflow_id=workflow_id,
            workflow_path=f".github/workflows/{workflow_id}",
            provisioned=provisioned,
            commit_sha="wf123" if provisioned else None,
            deploy_workflow_mode=deploy_workflow_mode,
            target_environment_key=target_environment_key,
            target_environment_source=target_environment_source,
        )

    def check_deploy_target_readiness(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        allow_ref_repair: bool = False,
        allow_workflow_repair: bool = False,
        dry_run: bool = False,
        remediation_mode: str = "none",
        managed_gke_config: dict[str, object] | None = None,
        namespace_isolation_defaults: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubTargetReadinessResult:
        del allow_ref_repair, allow_workflow_repair, dry_run, managed_gke_config, namespace_isolation_defaults
        dispatch_reason = self.deploy_target_dispatch_service_reason_code or "available"
        dispatch_available = dispatch_reason == "available"
        return SEOMigrationGitHubTargetReadinessResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            requested_ref=target.ref,
            resolved_ref=target.ref,
            ref_source="requested",
            workflow_id=target.workflow_id,
            workflow_path=f".github/workflows/{target.workflow_id}",
            repo_exists=True,
            ref_exists=True,
            workflow_exists=True,
            workflow_dispatch_ready=dispatch_available,
            workflow_dispatch_supported=True,
            workflow_trigger_types=("workflow_dispatch",),
            dispatch_service_availability=dispatch_available,
            dispatch_service_reason_code=dispatch_reason,
            dispatch_identifier_type="workflow_id",
            remediation_mode=remediation_mode.strip() or "none",
            workflow_conformance_checked=True,
            workflow_conformance_status="conformant",
            workflow_conformance_reasons=(),
            workflow_conformance_evidence_summary="stub_conformant",
        )


class _RaisingMigrationArtifactProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.provider_name = "openai"
        self.model_name = "gpt-4o-mini"
        self.prompt_version = "seo-migration-v1"

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        raise self.error


class _StaticMigrationArtifactProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, output: SEOMigrationArtifactGenerationOutput) -> None:
        self.output = output

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        return self.output


class _IncompatibleMigrationArtifactProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self) -> None:
        self.generate_call_count = 0

    def evaluate_compatibility(self) -> SEOMigrationProviderCompatibilityResult:
        return SEOMigrationProviderCompatibilityResult(
            supported=False,
            reason_code="unsupported_request_shape",
            operator_message="This model/provider setup is not compatible with the current migration request settings.",
            admin_summary=(
                "unsupported_request_shape "
                "model=gpt-4o-mini endpoint=/chat/completions mode=full response_format=json_schema "
                "request_body_mode=chat_json_schema"
            ),
            retryable=False,
            provider_name="openai",
            model_name="gpt-4o-mini",
            endpoint_path="/chat/completions",
            execution_mode="full",
            web_search_enabled=False,
            degraded_mode=False,
            response_format_mode="json_schema",
            request_body_mode="chat_json_schema",
        )

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        self.generate_call_count += 1
        raise RuntimeError("provider call should be blocked by compatibility preflight")


def _override_tenant_context(
    business_id: str,
    *,
    principal_role: PrincipalRole | None = None,
):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=f"test-principal:{business_id}",
            auth_source="test",
            principal_role=principal_role,
        )

    return _resolver


def _make_client(
    db_session,
    *,
    business_id: str,
    github_publisher: SEOMigrationGitHubPublisher | None = None,
    artifact_provider: SEOMigrationArtifactGenerationProvider | None = None,
    principal_role: PrincipalRole | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_migration_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(
        business_id,
        principal_role=principal_role,
    )
    app.dependency_overrides[get_seo_migration_ingest_service] = lambda: _StubMigrationIngestService()
    resolved_provider = artifact_provider or MockSEOMigrationArtifactGenerationProvider(
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    app.dependency_overrides[get_seo_migration_artifact_provider] = lambda: resolved_provider
    if github_publisher is not None:
        app.dependency_overrides[get_seo_migration_github_publisher] = lambda: github_publisher
    return TestClient(app)


def test_github_publisher_dependency_uses_migration_github_token_when_present() -> None:
    settings = SimpleNamespace(
        migration_github_token=" test-token ",
        migration_github_api_base_url="https://api.github.com",
        migration_github_timeout_seconds=30.0,
        migration_publish_committer_name="MBSRN Automation",
        migration_publish_committer_email="automation@example.com",
    )
    with patch("app.api.deps.get_settings", return_value=settings):
        publisher = get_seo_migration_github_publisher()

    assert isinstance(publisher, GitHubSEOMigrationPublisher)


def test_github_publisher_dependency_returns_misconfigured_when_token_missing() -> None:
    settings = SimpleNamespace(
        migration_github_token="  ",
        migration_github_api_base_url="https://api.github.com",
        migration_github_timeout_seconds=30.0,
        migration_publish_committer_name="MBSRN Automation",
        migration_publish_committer_email="automation@example.com",
    )
    with patch("app.api.deps.get_settings", return_value=settings):
        publisher = get_seo_migration_github_publisher()

    assert isinstance(publisher, MisconfiguredSEOMigrationGitHubPublisher)
    assert publisher.reason_code == "runtime_credential_missing"
    assert "credential is unavailable" in publisher.safe_message.lower()


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
    db_session.add(
        GitHubPublishConfig(
            repository="acme",
            default_branch="main",
            base_path="/",
            enabled=True,
        )
    )
    db_session.commit()


def _prepare_workspace_for_draft_generation(client: TestClient, *, business_id: str, site_id: str) -> None:
    ingest_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/source-ingest",
        json={"source_url": "https://legacy.example"},
    )
    assert ingest_response.status_code == 200
    requirements_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/operator-requirements",
        json={
            "operator_requirements": {
                "business_objectives": ["Replace weak legacy pages"],
                "requested_pages": ["Homepage", "Services", "Contact"],
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
            }
        },
    )
    assert enriched_response.status_code == 200


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
    assert isinstance(generated_artifact.get("artifact_quality_evaluation"), dict)
    assert isinstance(generated_artifact.get("artifact_quality_evaluation_json"), dict)
    quality_payload = generated_artifact["artifact_quality_evaluation"]
    assert quality_payload.get("quality_status") in {
        "high",
        "medium",
        "low",
    }

    post_generate_summary = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert post_generate_summary.status_code == 200
    post_generate_context = post_generate_summary.json().get("context_summary") or {}
    post_generate_state = post_generate_context.get("draft_generation_state") or {}
    assert post_generate_state.get("status") == "generation_succeeded"
    assert post_generate_state.get("summary") == "Draft generated successfully."
    post_generate_diagnostics = post_generate_context.get("migration_diagnostics") or {}
    assert post_generate_diagnostics.get("last_draft_generation_status") == "completed"
    assert post_generate_diagnostics.get("last_draft_failure_category") is None
    assert post_generate_diagnostics.get("last_draft_failure_message") is None

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
    assert "expected_publish_url" in (publish_response.json().get("result") or {})
    assert "url_source" in (publish_response.json().get("result") or {})
    assert "workflow_remediation_attempted" in (publish_response.json().get("result") or {})
    assert "workflow_remediation_outcome" in (publish_response.json().get("result") or {})
    assert "deploy_secret_propagation_attempted" in (publish_response.json().get("result") or {})
    assert "deploy_secret_propagation_status" in (publish_response.json().get("result") or {})
    assert "deploy_secret_propagation_reason" in (publish_response.json().get("result") or {})

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
    deploy_result = deploy_response.json().get("result") or {}
    assert "resolved_live_url" in deploy_result
    assert "url_source" in deploy_result
    assert isinstance(deploy_result.get("deploy_trace_id"), str)
    assert deploy_result.get("deploy_trace_id")
    assert "workflow_identifier" in deploy_result
    assert "workflow_identifier_requested" in deploy_result
    assert "workflow_identifier_used" in deploy_result
    assert "workflow_identifier_type_requested" in deploy_result
    assert "workflow_identifier_type_used" in deploy_result
    assert "workflow_dispatch_resolution_source" in deploy_result
    assert "actual_dispatch_identifier_sent" in deploy_result
    assert "actual_dispatch_identifier_type_sent" in deploy_result
    assert "dispatch_ref_sent" in deploy_result
    assert "workflow_inputs_configured_keys" in deploy_result
    assert "workflow_inputs_sent_keys" in deploy_result
    assert "workflow_run_lookup_attempted" in deploy_result
    assert "workflow_run_found" in deploy_result
    assert "workflow_job_failure_detected" in deploy_result
    assert "post_dispatch_state" in deploy_result
    assert "post_conformance_stage" in deploy_result
    assert "post_conformance_reason_text" in deploy_result
    assert "expected_workflow_outputs" in deploy_result
    assert "deploy_evidence_contract_status" in deploy_result
    assert "deploy_evidence_contract_reasons" in deploy_result
    assert "workflow_contract_advisory" in deploy_result
    assert isinstance(deploy_result.get("workflow_trigger_types"), list)
    assert "dispatch_service_availability" in deploy_result
    assert "dispatch_service_reason_code" in deploy_result
    assert "dispatch_result_stage" in deploy_result
    assert "workflow_conformance_checked" in deploy_result
    assert "workflow_conformance_status" in deploy_result
    assert isinstance(deploy_result.get("workflow_conformance_reasons"), list)
    assert "workflow_conformance_evidence_summary" in deploy_result

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
    assert isinstance(version_response.json().get("artifact_quality_evaluation"), dict)
    assert isinstance(version_response.json().get("artifact_quality_evaluation_json"), dict)

    file_preview_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/file-preview",
        params={"path": "index.html"},
    )
    assert file_preview_response.status_code == 200
    assert file_preview_response.json()["path"] == "index.html"
    assert "ANALYTICS_PLACEHOLDER" in file_preview_response.json()["content"]
    assert publisher.publish_calls
    assert publisher.deploy_calls


def test_delete_migration_artifact_version_allows_eligible_draft(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id, github_publisher=_StubMigrationGitHubPublisher())

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    delete_response = client.delete(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}",
    )
    assert delete_response.status_code == 200
    payload = delete_response.json()
    assert payload["deleted_artifact_version_id"] == artifact_id
    assert payload["workspace"]["latest_generated_artifact_version_id"] is None
    assert payload["workspace"]["migration_status"] == "draft"

    artifact_versions_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions",
    )
    assert artifact_versions_response.status_code == 200
    assert artifact_versions_response.json()["total"] == 0


def test_delete_migration_artifact_version_blocks_published_artifact(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id, github_publisher=_StubMigrationGitHubPublisher())

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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
        json={"artifact_version_id": artifact_id, "dry_run": False},
    )
    assert publish_response.status_code == 200

    delete_response = client.delete(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}",
    )
    assert delete_response.status_code == 422
    detail = delete_response.json().get("detail") or {}
    assert detail.get("error_code") == "artifact_already_published"


def test_migration_summary_requires_existing_workspace(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert response.status_code == 404
    assert response.json()["detail"] == "Migration workspace not found"


def test_operator_cannot_update_admin_owned_deploy_workflow_fields(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    bootstrap_client = _make_client(db_session, business_id=business_id)
    operator_client = _make_client(
        db_session,
        business_id=business_id,
        principal_role=PrincipalRole.OPERATOR,
    )

    workspace_response = bootstrap_client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    response = operator_client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-config",
        json={
            "deploy_config": {
                "enabled": True,
                "workflow_id": "deploy-custom-prod.yml",
            }
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Only admin principals can update deploy repository/workflow controls."


def test_operator_can_toggle_deploy_enabled_without_changing_admin_owned_fields(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    bootstrap_client = _make_client(db_session, business_id=business_id)
    operator_client = _make_client(
        db_session,
        business_id=business_id,
        principal_role=PrincipalRole.OPERATOR,
    )

    workspace_response = bootstrap_client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_name": "tnmfire-site",
                "branch": "main",
            },
            "deploy_config": {
                "enabled": False,
                "workflow_id": "deploy-tnmfire-www-prod.yml",
                "ref": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    response = operator_client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-config",
        json={"deploy_config": {"enabled": True}},
    )
    assert response.status_code == 200
    deploy_config_json = response.json().get("deploy_config_json") or {}
    assert deploy_config_json.get("enabled") is True
    assert deploy_config_json.get("workflow_id") == "deploy-tnmfire-www-prod.yml"
    assert deploy_config_json.get("ref") == "main"


def test_refresh_migration_deploy_status_updates_run_metadata_and_confirms_live_url(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher(
        deploy_workflow_run_id=778899,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="success",
        refresh_workflow_output={"live_url": "https://live.tnmfire.example"},
    )
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=publisher,
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    assert deploy_response.status_code == 200
    deploy_result = deploy_response.json().get("result") or {}
    deploy_trace_id = deploy_result.get("deploy_trace_id")
    assert isinstance(deploy_trace_id, str)
    assert deploy_trace_id

    refresh_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy/refresh-status",
        json={"artifact_version_id": artifact_id},
    )
    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    refresh_result = refresh_payload.get("result") or {}
    assert refresh_result.get("status") == "updated"
    assert refresh_result.get("workflow_run_status") == "completed"
    assert refresh_result.get("workflow_run_conclusion") == "success"
    assert refresh_result.get("resolved_live_url") == "https://live.tnmfire.example"
    assert refresh_result.get("url_source") == "workflow_output"
    assert refresh_result.get("deploy_trace_id") == deploy_trace_id
    assert "dispatch_service_availability" in refresh_result
    assert "dispatch_service_reason_code" in refresh_result
    assert "workflow_identifier" in refresh_result
    assert len(publisher.refresh_calls) == 1


def test_refresh_migration_deploy_status_is_noop_without_workflow_run_metadata(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher(
        deploy_workflow_run_id=None,
        deploy_workflow_run_status=None,
        deploy_workflow_run_conclusion=None,
    )
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=publisher,
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    assert deploy_response.status_code == 200

    refresh_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy/refresh-status",
        json={"artifact_version_id": artifact_id},
    )
    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    refresh_result = refresh_payload.get("result") or {}
    assert refresh_result.get("status") == "no_change"
    assert refresh_result.get("no_change_reason") == "no_run_observed_after_refresh"
    assert refresh_result.get("dispatch_verification_state") == "unverified_dispatch_no_run_observed"
    assert not publisher.refresh_calls


def test_migration_summary_destination_reports_expected_publish_and_deploy_urls(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_name": "tnmfire-site",
                "branch": "main",
                "artifact_root": "site",
            },
            "deploy_config": {
                "enabled": True,
                "workflow_id": "deploy-www-prod.yml",
                "ref": "main",
                "inputs": {
                    "site_url": "https://tnmfire-www.example",
                },
            },
        },
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)
    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_id = generate_response.json()["id"]

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    destination = summary_response.json().get("context_summary", {}).get("destination_summary") or {}
    draft_preview = destination.get("draft_preview") or {}
    publish_destination = destination.get("publish_destination") or {}
    deploy_destination = destination.get("deploy_destination") or {}

    assert draft_preview.get("state") == "available"
    assert draft_preview.get("artifact_version_id") == artifact_id
    assert draft_preview.get("entry_path") == "index.html"
    assert publish_destination.get("repository") == "acme/tnmfire-site"
    assert publish_destination.get("expected_location") == "acme/tnmfire-site@main:/site"
    assert publish_destination.get("expected_url") == "https://github.com/acme/tnmfire-site/tree/main/site"
    assert publish_destination.get("expected_publish_url") == "https://tnmfire-www.example"
    assert publish_destination.get("url_source") == "deterministic_target_config"
    assert publish_destination.get("url_source_detail") == "deploy_input:site_url"
    assert deploy_destination.get("expected_publish_url") == "https://tnmfire-www.example"
    assert deploy_destination.get("resolved_live_url") is None
    assert deploy_destination.get("expected_url") == "https://tnmfire-www.example"
    assert deploy_destination.get("preview_hostname") == "tnmfire-site.site.mbsrn.com"
    assert deploy_destination.get("preview_url") == "https://tnmfire-site.site.mbsrn.com"
    assert deploy_destination.get("preview_state") == "expected_after_deploy"
    assert deploy_destination.get("customer_domain_url") == "https://tnmfire-www.example"
    assert deploy_destination.get("customer_domain_state") == "pending_cutover"
    assert deploy_destination.get("customer_domain_live_url") is None
    assert deploy_destination.get("url_source") == "deterministic_target_config"
    assert deploy_destination.get("url_source_detail") == "deploy_input:site_url"
    assert deploy_destination.get("state") == "expected_after_deploy"


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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    assert "approved artifact is required before publish" in publish_response.json()["detail"].lower()


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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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


def test_publish_duplicate_repairs_missing_workflow_when_artifact_already_exists(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher(existing_workflow=False)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=publisher,
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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    assert len(publisher.publish_calls) == 1

    publisher.existing_workflow = False
    remediation_publish = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert remediation_publish.status_code == 200
    result_payload = remediation_publish.json().get("result") or {}
    assert result_payload.get("status") == "published"
    assert result_payload.get("duplicate_artifact_skipped") is True
    assert result_payload.get("deploy_workflow_provisioned") is True
    assert result_payload.get("workflow_provisioning_remediation_mode") == "duplicate_publish_repair"
    assert result_payload.get("workflow_provisioning_status") == "created"
    assert result_payload.get("workflow_remediation_attempted") is True
    assert result_payload.get("workflow_remediation_outcome") in {
        "remediation_already_current",
        "remediation_upgraded_managed_placeholder",
    }
    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 2


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
    assert isinstance(payload["publish_readiness"].get("blocker_codes"), list)
    assert isinstance(payload["publish_readiness"].get("target"), dict)
    assert isinstance(payload["publish_readiness"].get("config_prerequisites"), dict)
    publish_prereqs = payload["publish_readiness"].get("config_prerequisites") or {}
    assert "publish_target_ref" in publish_prereqs
    assert "publish_target_ref_exists" in publish_prereqs
    assert "publish_target_repo_initialized" in publish_prereqs
    assert "publish_target_can_read_contents" in publish_prereqs
    assert "publish_target_can_write_contents" in publish_prereqs
    assert "publish_target_can_write_workflows" in publish_prereqs
    assert "publish_target_would_auto_create_repo" in publish_prereqs
    assert "publish_target_would_bootstrap_branch" in publish_prereqs
    assert "publish_target_preflight_status" in publish_prereqs
    assert "publish_target_preflight_blocker_code" in publish_prereqs
    assert "last_status" in payload["publish_readiness"]
    assert "last_failure_category" in payload["publish_readiness"]
    assert "last_failure_message" in payload["publish_readiness"]
    assert "last_workflow_remediation_attempted" in payload["publish_readiness"]
    assert "last_workflow_remediation_outcome" in payload["publish_readiness"]
    assert "last_deploy_secret_propagation_attempted" in payload["publish_readiness"]
    assert "last_deploy_secret_propagation_status" in payload["publish_readiness"]
    assert "last_deploy_secret_propagation_reason" in payload["publish_readiness"]
    assert isinstance(payload["deploy_readiness"].get("ready"), bool)
    assert isinstance(payload["deploy_readiness"].get("reasons"), list)
    assert isinstance(payload["deploy_readiness"].get("blocker_codes"), list)
    assert isinstance(payload["deploy_readiness"].get("target"), dict)
    assert isinstance(payload["deploy_readiness"].get("config_prerequisites"), dict)
    assert "last_status" in payload["deploy_readiness"]
    assert "last_failure_category" in payload["deploy_readiness"]
    assert "last_failure_reason" in payload["deploy_readiness"]
    assert "last_failure_stage" in payload["deploy_readiness"]
    assert "last_failure_message" in payload["deploy_readiness"]
    assert "last_failure_remediation_hint" in payload["deploy_readiness"]
    assert "last_failure_workflow_identifier_requested" in payload["deploy_readiness"]
    assert "last_failure_workflow_identifier_used" in payload["deploy_readiness"]
    assert "last_failure_workflow_file_path" in payload["deploy_readiness"]
    assert "last_failure_workflow_exists" in payload["deploy_readiness"]
    assert "last_failure_workflow_dispatch_resolution_source" in payload["deploy_readiness"]
    assert "last_failure_dispatch_service_reason_code" in payload["deploy_readiness"]
    assert "last_failure_workflow_conformance_status" in payload["deploy_readiness"]
    assert "last_failure_workflow_conformance_reasons" in payload["deploy_readiness"]
    assert "workflow_identifier_requested" in payload["deploy_readiness"]
    assert "workflow_identifier_used" in payload["deploy_readiness"]
    assert "workflow_dispatch_resolution_source" in payload["deploy_readiness"]
    assert "dispatch_service_reason_code" in payload["deploy_readiness"]
    assert "last_dispatch_ref_sent" in payload["deploy_readiness"]
    assert "last_workflow_inputs_configured_keys" in payload["deploy_readiness"]
    assert "last_workflow_inputs_sent_keys" in payload["deploy_readiness"]
    assert "last_workflow_run_lookup_attempted" in payload["deploy_readiness"]
    assert "last_workflow_run_found" in payload["deploy_readiness"]
    assert "last_workflow_job_failure_detected" in payload["deploy_readiness"]
    assert "last_workflow_run_failure_reason_code" in payload["deploy_readiness"]
    assert "last_workflow_run_failure_stage" in payload["deploy_readiness"]
    assert "last_workflow_run_failure_step" in payload["deploy_readiness"]
    assert "last_workflow_run_failure_hint" in payload["deploy_readiness"]
    assert "last_post_dispatch_state" in payload["deploy_readiness"]
    assert "last_post_conformance_stage" in payload["deploy_readiness"]
    assert "last_post_conformance_reason_text" in payload["deploy_readiness"]
    assert "expected_workflow_outputs" in payload["deploy_readiness"]
    assert "last_deploy_evidence_contract_status" in payload["deploy_readiness"]
    assert "last_deploy_evidence_contract_reasons" in payload["deploy_readiness"]
    assert "last_workflow_contract_advisory" in payload["deploy_readiness"]
    assert "last_workflow_exists" in payload["deploy_readiness"]
    migration_diagnostics = payload.get("context_summary", {}).get("migration_diagnostics")
    assert isinstance(migration_diagnostics, dict)
    assert "last_publish_workflow_remediation_attempted" in migration_diagnostics
    assert "last_publish_workflow_remediation_outcome" in migration_diagnostics
    assert "last_publish_deploy_secret_propagation_attempted" in migration_diagnostics
    assert "last_publish_deploy_secret_propagation_status" in migration_diagnostics
    assert "last_publish_deploy_secret_propagation_reason" in migration_diagnostics
    draft_readiness = payload.get("context_summary", {}).get("draft_generation_readiness")
    assert isinstance(draft_readiness, dict)
    assert draft_readiness.get("status") in {"ready", "ready_with_warnings", "not_ready"}
    assert isinstance(draft_readiness.get("score"), int)
    assert isinstance(draft_readiness.get("hard_blocked"), bool)
    assert isinstance(draft_readiness.get("summary"), str)
    assert isinstance(draft_readiness.get("reasons"), list)
    assert isinstance(draft_readiness.get("signals"), dict)
    draft_provider_compatibility = payload.get("context_summary", {}).get("draft_provider_compatibility")
    assert isinstance(draft_provider_compatibility, dict)
    assert isinstance(draft_provider_compatibility.get("supported"), bool)
    assert isinstance(draft_provider_compatibility.get("reason_code"), str)
    assert isinstance(draft_provider_compatibility.get("operator_message"), str)
    assert isinstance(draft_provider_compatibility.get("retryable"), bool)
    ai_execution = payload.get("context_summary", {}).get("ai_execution")
    assert isinstance(ai_execution, dict)
    assert "model_requested" in ai_execution
    assert "model_resolved" in ai_execution
    assert "model_used" in ai_execution
    assert "endpoint_path" in ai_execution
    assert "request_body_mode" in ai_execution
    assert "compatibility_decision" in ai_execution
    assert "request_contract_status" in ai_execution
    assert "provider_execution_status" in ai_execution
    assert "artifact_status" in ai_execution
    assert "artifact_result" in ai_execution
    assert "duration_ms" in ai_execution
    assert "timeout_seconds" in ai_execution
    assert "timeout_source" in ai_execution
    draft_generation_state = payload.get("context_summary", {}).get("draft_generation_state")
    assert isinstance(draft_generation_state, dict)
    assert draft_generation_state.get("status") in {
        "ready",
        "ready_with_warnings",
        "blocked_by_workspace",
        "blocked_by_provider",
        "generation_failed",
        "generation_partial",
        "generation_succeeded",
    }
    assert isinstance(draft_generation_state.get("summary"), str)
    destination_summary = payload.get("context_summary", {}).get("destination_summary")
    assert isinstance(destination_summary, dict)
    assert isinstance(destination_summary.get("draft_preview"), dict)
    assert isinstance(destination_summary.get("publish_destination"), dict)
    assert isinstance(destination_summary.get("deploy_destination"), dict)
    assert "last_draft_generation_status" in migration_diagnostics
    assert "last_draft_failure_category" in migration_diagnostics
    assert "last_draft_failure_reason" in migration_diagnostics
    assert "last_draft_failure_message" in migration_diagnostics
    assert "last_draft_failure_retryable" in migration_diagnostics
    assert "last_draft_failure_code" in migration_diagnostics
    assert "last_draft_failure_correlation_id" in migration_diagnostics
    assert "last_draft_failure_artifact_version_id" in migration_diagnostics
    assert "last_draft_failure_source" in migration_diagnostics
    assert "last_draft_failure_request_body_mode" in migration_diagnostics
    assert "last_draft_failure_model_requested" in migration_diagnostics
    assert "last_draft_failure_model_resolved" in migration_diagnostics
    assert "last_draft_failure_model_used" in migration_diagnostics
    assert "last_draft_failure_timeout_seconds" in migration_diagnostics
    assert "last_draft_failure_timeout_source" in migration_diagnostics
    assert "last_draft_ai_diagnostics_summary" in migration_diagnostics
    assert "last_draft_contract_status" in migration_diagnostics
    assert "last_draft_contract_reason_codes" in migration_diagnostics
    assert "last_draft_contract_warning_codes" in migration_diagnostics
    assert "last_draft_contract_retry_likelihood" in migration_diagnostics
    assert "last_draft_contract_candidate_item_count" in migration_diagnostics
    assert "last_draft_contract_normalized_item_count" in migration_diagnostics
    assert "last_draft_contract_dropped_item_count" in migration_diagnostics
    assert "last_draft_contract_required_artifact_files_expected" in migration_diagnostics
    assert "last_draft_contract_required_artifact_files_present" in migration_diagnostics
    assert "last_draft_contract_missing_required_artifact_files" in migration_diagnostics
    assert "last_draft_contract_content_density_failures_by_file" in migration_diagnostics
    assert "last_draft_contract_parser_rejection_reason_counts" in migration_diagnostics
    assert "last_draft_contract_artifact_primary_file_detected" in migration_diagnostics
    assert "last_draft_execution_duration_ms" in migration_diagnostics
    assert "last_draft_request_contract_status" in migration_diagnostics
    assert "last_draft_provider_execution_status" in migration_diagnostics
    assert "last_draft_artifact_status" in migration_diagnostics
    assert "last_draft_artifact_result" in migration_diagnostics
    assert "draft_timeout_seconds" in migration_diagnostics
    assert "draft_timeout_source" in migration_diagnostics
    assert "draft_provider_compatibility_supported" in migration_diagnostics
    assert "draft_provider_compatibility_reason_code" in migration_diagnostics
    assert "draft_provider_compatibility_message" in migration_diagnostics
    assert "draft_provider_compatibility_retryable" in migration_diagnostics
    assert "draft_provider_compatibility_admin_summary" in migration_diagnostics
    assert "draft_provider_compatibility_request_body_mode" in migration_diagnostics
    assert "draft_generation_state_status" in migration_diagnostics
    assert "draft_generation_state_summary" in migration_diagnostics
    assert "last_publish_status" in migration_diagnostics
    assert "last_deploy_status" in migration_diagnostics
    assert isinstance(payload.get("publish_history"), list)
    assert isinstance(payload.get("deploy_history"), list)


def test_generate_draft_is_blocked_when_readiness_has_blockers(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "enriched_content_notes": {
                "replacement_summary": "Prepared replacement copy.",
            },
        },
    )
    assert workspace_response.status_code == 200
    ingest_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/source-ingest",
        json={"source_url": "https://legacy.example"},
    )
    assert ingest_response.status_code == 200

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("message")
    assert "not ready yet" in str(detail.get("message") or "").lower()
    assert detail.get("error_code") == "operator_requirements_required"
    assert detail.get("failure_category") == "unknown_error"

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    top_state = (summary_response.json().get("context_summary") or {}).get("draft_generation_state") or {}
    assert top_state.get("status") == "blocked_by_workspace"
    assert "not ready yet" in str(top_state.get("summary") or "").lower()


def test_generate_draft_is_blocked_when_provider_compatibility_is_unsupported(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    incompatible_provider = _IncompatibleMigrationArtifactProvider()
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=incompatible_provider,
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert (
        detail.get("message")
        == "This model/provider setup is not compatible with the current migration request settings."
    )
    assert detail.get("failure_category") == "config_missing"
    assert detail.get("failure_reason") == "unsupported_configuration"
    assert detail.get("error_code") == "unsupported_request_shape"
    assert detail.get("retryable") is False
    assert incompatible_provider.generate_call_count == 0

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    context_summary = summary_response.json().get("context_summary") or {}
    diagnostics = context_summary.get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_failure_category") == "config_missing"
    assert diagnostics.get("last_draft_failure_reason") == "unsupported_configuration"
    assert diagnostics.get("last_draft_failure_code") == "unsupported_request_shape"
    assert diagnostics.get("last_draft_failure_source") == "local_preflight"
    assert diagnostics.get("last_draft_failure_endpoint_path") == "/chat/completions"
    assert diagnostics.get("last_draft_failure_execution_mode") == "full"
    assert diagnostics.get("last_draft_failure_response_format_mode") == "json_schema"
    assert diagnostics.get("last_draft_failure_request_body_mode") == "chat_json_schema"
    assert diagnostics.get("last_draft_failure_model_requested") is None
    assert diagnostics.get("last_draft_failure_model_resolved") == "gpt-4o-mini"
    assert diagnostics.get("last_draft_failure_model_used") == "gpt-4o-mini"
    assert "unsupported_request_shape" in str(diagnostics.get("draft_provider_compatibility_admin_summary") or "")
    ai_execution = context_summary.get("ai_execution") or {}
    assert ai_execution.get("model_requested") is None
    assert ai_execution.get("model_resolved") == "gpt-4o-mini"
    assert ai_execution.get("model_used") == "gpt-4o-mini"
    assert ai_execution.get("endpoint_path") == "/chat/completions"
    assert ai_execution.get("request_body_mode") == "chat_json_schema"
    assert ai_execution.get("compatibility_decision") == "blocked_local_preflight"
    assert ai_execution.get("request_contract_status") == "blocked"
    assert ai_execution.get("provider_execution_status") == "not_called"
    assert ai_execution.get("artifact_status") == "failed"
    assert ai_execution.get("artifact_result") == "failed"
    assert isinstance(ai_execution.get("duration_ms"), int)
    compatibility = context_summary.get("draft_provider_compatibility") or {}
    assert compatibility.get("supported") is False
    assert compatibility.get("reason_code") == "unsupported_request_shape"
    assert compatibility.get("response_format_mode") == "json_schema"
    assert compatibility.get("request_body_mode") == "chat_json_schema"
    top_state = context_summary.get("draft_generation_state") or {}
    assert top_state.get("status") == "blocked_by_provider"
    assert "not compatible" in str(top_state.get("summary") or "").lower()


def test_migration_summary_reused_context_reports_best_available_signals(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    now = utc_now()
    audit_run = SEOAuditRun(
        id="audit-run-api-context-1",
        business_id=business_id,
        site_id=site_id,
        status="completed",
        started_at=now,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    recommendation_run = SEORecommendationRun(
        id="recommendation-run-api-context-1",
        business_id=business_id,
        site_id=site_id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        status="completed",
        total_recommendations=1,
        warning_recommendations=1,
        started_at=now,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    recommendation = SEORecommendation(
        id="recommendation-api-context-1",
        business_id=business_id,
        site_id=site_id,
        recommendation_run_id=recommendation_run.id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        rule_key="api-migration-context-rule",
        category="SEO",
        severity="WARNING",
        title="Improve service page specificity",
        rationale="Legacy copy is too sparse for conversion.",
        priority_score=65,
        priority_band="high",
        effort_bucket="small",
        status="open",
    )
    competitor_set = SEOCompetitorSet(
        id="competitor-set-api-context-1",
        business_id=business_id,
        site_id=site_id,
        name="Primary competitors",
        is_active=True,
        created_by_principal_id="principal-1",
    )
    snapshot_run = SEOCompetitorSnapshotRun(
        id="snapshot-run-api-context-1",
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        client_audit_run_id=audit_run.id,
        status="completed",
        pages_captured=3,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    comparison_run = SEOCompetitorComparisonRun(
        id="comparison-run-api-context-1",
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        snapshot_run_id=snapshot_run.id,
        baseline_audit_run_id=audit_run.id,
        status="completed",
        total_findings=2,
        warning_findings=2,
        client_pages_analyzed=2,
        competitor_pages_analyzed=3,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    db_session.add(audit_run)
    db_session.add(recommendation_run)
    db_session.add(recommendation)
    db_session.add(competitor_set)
    db_session.add(snapshot_run)
    db_session.add(comparison_run)
    db_session.commit()

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    context_summary = summary_response.json().get("context_summary") or {}
    reused_context = context_summary.get("reused_context") or {}

    audit = reused_context.get("audit") or {}
    recommendations = reused_context.get("recommendations") or {}
    competitors = reused_context.get("competitors") or {}

    assert audit.get("available") is True
    assert audit.get("source") == "latest_successful_run"
    assert audit.get("run_id") == audit_run.id

    assert recommendations.get("available") is True
    assert recommendations.get("source") == "latest_generated"
    assert recommendations.get("run_id") == recommendation_run.id
    assert recommendations.get("count") == 1

    assert competitors.get("available") is True
    assert competitors.get("source") == "latest_run"
    assert competitors.get("run_id") == comparison_run.id
    assert competitors.get("count") == 2


def test_generate_draft_timeout_returns_structured_error_and_persisted_diagnostics(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=_RaisingMigrationArtifactProvider(
            SEOMigrationArtifactProviderError(
                code="timeout",
                reason="timeout",
                safe_message="Migration draft generation timed out while calling the AI provider.",
                provider_name="openai",
                model_name="gpt-4o-mini",
                prompt_version="seo-migration-v1",
                retryable=True,
                correlation_id="provider-timeout-1",
            )
        ),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("message") == "Migration draft generation timed out while calling the AI provider."
    assert detail.get("failure_category") == "config_missing"
    assert detail.get("failure_reason") == "timeout"
    assert detail.get("error_code") == "timeout"
    assert detail.get("retryable") is True
    assert detail.get("correlation_id") in {"provider-timeout-1"}
    assert detail.get("workspace_id") == workspace_response.json()["id"]
    assert isinstance(detail.get("artifact_version_id"), str)
    assert detail.get("provider_name") == "openai"
    assert detail.get("model_name") == "gpt-4o-mini"
    assert detail.get("prompt_version") == "seo-migration-v1"
    assert detail.get("timeout_seconds") == 120
    assert detail.get("timeout_source") == "default"

    versions_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions")
    assert versions_response.status_code == 200
    versions = versions_response.json().get("items") or []
    assert versions
    assert versions[0].get("status") == "failed"
    assert versions[0].get("error_summary") == "Migration draft generation timed out while calling the AI provider."

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    diagnostics = summary_response.json().get("context_summary", {}).get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_generation_status") == "failed"
    assert diagnostics.get("last_draft_failure_category") == "config_missing"
    assert diagnostics.get("last_draft_failure_reason") == "timeout"
    assert (
        diagnostics.get("last_draft_failure_message")
        == "Migration draft generation timed out while calling the AI provider."
    )
    assert diagnostics.get("last_draft_failure_retryable") is True
    assert diagnostics.get("last_draft_failure_code") == "timeout"
    assert diagnostics.get("last_draft_failure_artifact_version_id") == versions[0].get("id")
    assert diagnostics.get("last_draft_failure_source") == "remote_provider"
    assert diagnostics.get("last_draft_failure_model_requested") is None
    assert diagnostics.get("last_draft_failure_model_resolved") == "gpt-4o-mini"
    assert diagnostics.get("last_draft_failure_model_used") == "gpt-4o-mini"
    assert diagnostics.get("last_draft_failure_timeout_seconds") == 120
    assert diagnostics.get("last_draft_failure_timeout_source") == "default"
    assert diagnostics.get("draft_timeout_seconds") == 120
    assert diagnostics.get("draft_timeout_source") == "default"
    ai_execution = summary_response.json().get("context_summary", {}).get("ai_execution") or {}
    assert ai_execution.get("model_requested") is None
    assert ai_execution.get("model_resolved") == "gpt-4o-mini"
    assert ai_execution.get("model_used") == "gpt-4o-mini"
    assert ai_execution.get("request_contract_status") == "rejected"
    assert ai_execution.get("provider_execution_status") == "rejected"
    assert ai_execution.get("artifact_status") == "failed"
    assert ai_execution.get("artifact_result") == "failed"
    assert isinstance(ai_execution.get("duration_ms"), int)
    assert ai_execution.get("timeout_seconds") == 120
    assert ai_execution.get("timeout_source") == "default"
    assert "raw_output" not in ai_execution
    top_state = summary_response.json().get("context_summary", {}).get("draft_generation_state") or {}
    assert top_state.get("status") == "generation_failed"
    assert top_state.get("summary") == "Migration draft generation timed out while calling the AI provider."


def test_generate_draft_malformed_provider_output_returns_artifact_invalid(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=_RaisingMigrationArtifactProvider(
            SEOMigrationArtifactProviderError(
                code="malformed_response",
                reason="malformed_response",
                safe_message="Migration draft returned malformed output.",
                provider_name="openai",
                model_name="gpt-4o-mini",
                prompt_version="seo-migration-v1",
                retryable=True,
            )
        ),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("failure_category") == "artifact_invalid"
    assert detail.get("failure_reason") == "malformed_response"
    assert detail.get("retryable") is True


def test_generate_draft_contract_rejection_exposes_structural_retry_hint(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    output = SEOMigrationArtifactGenerationOutput(
        strategy_summary="Draft strategy",
        page_map=[],
        homepage_structure=[],
        service_page_suggestions=[],
        cta_contact_structure={},
        seo_meta_suggestions={},
        redirect_suggestions=[],
        analytics_placeholders=[],
        generated_files=[
            SEOMigrationGeneratedFileOutput(
                path="https://tnmfire.example",
                media_type="text/html",
                content="",
            )
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=_StaticMigrationArtifactProvider(output),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("failure_category") == "artifact_invalid"
    assert detail.get("failure_reason") == "validation_failed"
    assert detail.get("retryable") is False

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    diagnostics = summary_response.json().get("context_summary", {}).get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_contract_status") == "rejected"
    assert diagnostics.get("last_draft_contract_retry_likelihood") == "unlikely_without_contract_fix"
    assert diagnostics.get("last_draft_contract_missing_required_artifact_files") == ["index.html"]
    assert diagnostics.get("last_draft_contract_candidate_item_count") == 1
    assert diagnostics.get("last_draft_contract_normalized_item_count") == 0
    assert diagnostics.get("last_draft_contract_dropped_item_count") == 1
    assert diagnostics.get("last_draft_contract_required_artifact_files_expected") == ["index.html"]
    assert diagnostics.get("last_draft_contract_required_artifact_files_present") == []
    assert diagnostics.get("last_draft_contract_content_density_failures_by_file") == []
    assert diagnostics.get("last_draft_contract_artifact_primary_file_detected") is False
    parser_rejections = diagnostics.get("last_draft_contract_parser_rejection_reason_counts") or {}
    assert isinstance(parser_rejections, dict)
    assert parser_rejections.get("invalid_path", 0) >= 1
    assert "prompt" not in diagnostics
    assert "raw_model_output" not in diagnostics


def test_generate_draft_provider_config_failure_returns_config_missing(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=_RaisingMigrationArtifactProvider(
            SEOMigrationArtifactProviderError(
                code="unsupported_configuration",
                reason="unsupported_configuration",
                safe_message="AI provider configuration is invalid for migration draft generation.",
                provider_name="openai",
                model_name="gpt-4o-mini",
                prompt_version="seo-migration-v1",
                retryable=False,
            )
        ),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("failure_category") == "config_missing"
    assert detail.get("failure_reason") == "unsupported_configuration"
    assert detail.get("retryable") is False


def test_generate_draft_unknown_provider_exception_returns_stable_unknown_error(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=_RaisingMigrationArtifactProvider(RuntimeError("boom")),
    )

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("message") == "Migration draft generation failed due to an unexpected provider error."
    assert detail.get("failure_category") == "unknown_error"
    assert detail.get("failure_reason") == "unknown"
    assert detail.get("error_code") == "unknown"
    assert "traceback" not in str(detail).lower()


def test_publish_missing_runtime_config_surfaces_config_diagnostics(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=MisconfiguredSEOMigrationGitHubPublisher(
            safe_message="GitHub publishing runtime credential is unavailable.",
            reason_code="runtime_credential_missing",
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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    assert "credential is unavailable" in str(publish_response.json().get("detail") or "").lower()

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    publish_readiness = summary_response.json()["publish_readiness"]
    assert publish_readiness.get("failure_category") == "config_missing"
    prereqs = publish_readiness.get("config_prerequisites")
    assert isinstance(prereqs, dict)
    assert prereqs.get("github_publisher_configured") is False
    assert prereqs.get("github_publisher_reason_code") == "runtime_credential_missing"
    assert "credential is unavailable" in str(prereqs.get("github_publisher_status_message") or "").lower()


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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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
    assert isinstance(publish_prereqs.get("github_publisher_reason_code"), str)
    assert isinstance(publish_prereqs.get("github_publisher_status_message"), str)
    assert isinstance(publish_prereqs.get("target_config_valid"), bool)
    assert isinstance(publish_prereqs.get("target_enabled"), bool)
    assert isinstance(deploy_prereqs.get("github_publisher_configured"), bool)
    assert isinstance(deploy_prereqs.get("github_publisher_reason_code"), str)
    assert isinstance(deploy_prereqs.get("github_publisher_status_message"), str)
    assert isinstance(deploy_prereqs.get("target_config_valid"), bool)
    assert isinstance(deploy_prereqs.get("target_enabled"), bool)

    assert diagnostics.get("last_publish_status") == "published"
    assert diagnostics.get("last_publish_failure_category") is None
    assert diagnostics.get("last_publish_failure_message") is None
    assert diagnostics.get("last_deploy_status") == "failed"
    assert diagnostics.get("last_deploy_failure_category") == "deploy_error"
    assert diagnostics.get("last_deploy_failure_message") == "Simulated deploy failure."
    assert "last_deploy_failure_remediation_hint" in diagnostics
    assert "last_deploy_failure_workflow_identifier_requested" in diagnostics
    assert "last_deploy_failure_workflow_identifier_used" in diagnostics
    assert "last_deploy_failure_workflow_file_path" in diagnostics
    assert "last_deploy_failure_workflow_exists" in diagnostics
    assert "last_deploy_failure_workflow_dispatch_resolution_source" in diagnostics
    assert "last_deploy_failure_dispatch_service_reason_code" in diagnostics
    assert "last_deploy_failure_workflow_conformance_status" in diagnostics
    assert "last_deploy_failure_workflow_conformance_reasons" in diagnostics

    assert publish_readiness.get("last_status") == "published"
    assert publish_readiness.get("last_failure_category") is None
    assert publish_readiness.get("last_failure_message") is None
    assert deploy_readiness.get("last_status") == "failed"
    assert deploy_readiness.get("last_failure_category") == "deploy_error"
    assert deploy_readiness.get("last_failure_message") == "Simulated deploy failure."
    assert "last_failure_remediation_hint" in deploy_readiness


def test_migration_summary_surfaces_missing_managed_gke_config_reason_and_remediation(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        github_publisher=_StubMigrationGitHubPublisher(
            deploy_target_dispatch_service_reason_code="missing_cluster_name"
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
            "deploy_config": {
                "enabled": True,
                "workflow_id": "deploy-www-prod.yml",
                "ref": "main",
            },
        },
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

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

    pre_deploy_summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert pre_deploy_summary_response.status_code == 200
    pre_deploy_payload = pre_deploy_summary_response.json()
    pre_deploy_readiness = pre_deploy_payload.get("deploy_readiness") or {}
    assert pre_deploy_readiness.get("ready") is False
    assert pre_deploy_readiness.get("dispatch_service_reason_code") == "missing_cluster_name"
    pre_deploy_reasons = [str(item).lower() for item in pre_deploy_readiness.get("reasons") or []]
    assert any(
        "managed deploy target is missing required admin gke cluster name configuration" in item
        for item in pre_deploy_reasons
    )
    assert "deploy_configuration_missing" in (pre_deploy_readiness.get("blocker_codes") or [])

    deploy_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy",
        json={
            "artifact_version_id": artifact_id,
            "dry_run": False,
        },
    )
    assert deploy_response.status_code == 422

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    payload = summary_response.json()

    deploy_readiness = payload.get("deploy_readiness") or {}
    diagnostics = payload.get("context_summary", {}).get("migration_diagnostics") or {}

    assert deploy_readiness.get("dispatch_service_reason_code") == "missing_cluster_name"
    assert deploy_readiness.get("ready") is False
    deploy_reasons = [str(item).lower() for item in deploy_readiness.get("reasons") or []]
    assert any(
        "managed deploy target is missing required admin gke cluster name configuration" in item
        for item in deploy_reasons
    )
    if deploy_readiness.get("last_failure_reason") is not None:
        assert deploy_readiness.get("last_failure_reason") == "workflow_not_dispatchable"
        assert deploy_readiness.get("last_failure_dispatch_service_reason_code") == "missing_cluster_name"
        assert (
            deploy_readiness.get("last_failure_remediation_hint")
            == "Managed deploy target is missing required admin GKE cluster name configuration. Update MBSRN admin deployment settings."
        )
        assert diagnostics.get("last_deploy_failure_dispatch_service_reason_code") == "missing_cluster_name"
        assert (
            diagnostics.get("last_deploy_failure_remediation_hint")
            == "Managed deploy target is missing required admin GKE cluster name configuration. Update MBSRN admin deployment settings."
        )

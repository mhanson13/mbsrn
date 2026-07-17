from __future__ import annotations

from datetime import date, timedelta
import json
import os
from types import SimpleNamespace
import urllib.error
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.time import utc_now
from app.core.config import get_settings
from app.api.deps import (
    TenantContext,
    get_seo_analytics_service,
    get_db,
    get_seo_migration_service,
    get_seo_migration_artifact_provider,
    get_seo_migration_github_publisher,
    get_seo_migration_ingest_service,
    get_session_token_service,
    get_tenant_context,
)
from app.core.session_token import AppSessionTokenError
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
    SEOMigrationGitHubManagedSiteDnsEnsureResult,
    SEOMigrationGitHubManagedSiteStaticIPEnsureResult,
    SEOMigrationGitHubImagePullSecretProvisionResult,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishPreflightResult,
    SEOMigrationGitHubPublishResult,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
    SEOMigrationGitHubRepoAdoptionResult,
    SEOMigrationGitHubRepositoryEnsureResult,
    SEOMigrationGitHubTargetReadinessResult,
    SEOMigrationGitHubWorkflowProvisionResult,
    derive_site_preview_static_ip_name,
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
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_site import SEOSite
from app.schemas.seo_analytics import SEOAnalyticsSiteSummaryRead
from app.services import seo_migration as seo_migration_module
from app.services.seo_migration import SEOMigrationValidationError
from app.services.seo_migration_ingest import (
    SEOMigrationIngestResult,
    SEOMigrationSourceIngestError,
)

_STUB_MANAGED_SITE_STATIC_IP_ADDRESS = "34.149.170.250"


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


@pytest.fixture(autouse=True)
def _stub_dns_resolver_for_managed_site_propagation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        seo_migration_module,
        "_resolve_hostname_ipv4_addresses",
        lambda _hostname: [_STUB_MANAGED_SITE_STATIC_IP_ADDRESS],
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
        fail_adoption: bool = False,
        adoption_error_code: str | None = None,
        adoption_error_message: str | None = None,
        ensure_static_ip_address: str = _STUB_MANAGED_SITE_STATIC_IP_ADDRESS,
        ensure_static_ip_created: bool = False,
        ensure_static_ip_result: str = "exists",
        ensure_dns_managed_zone: str = "sites",
        ensure_dns_project_id: str = "test-project",
        ensure_dns_ttl: int = 300,
        ensure_dns_result: str = "exists",
        ensure_dns_created: bool = False,
        ensure_dns_updated: bool = False,
        ensure_dns_previous_ips: tuple[str, ...] | list[str] | None = None,
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
            deploy_target_dispatch_service_reason_code or ""
        ).strip().lower() or None
        self.fail_adoption = fail_adoption
        self.adoption_error_code = adoption_error_code
        self.adoption_error_message = adoption_error_message
        self.ensure_static_ip_address = ensure_static_ip_address
        self.ensure_static_ip_created = ensure_static_ip_created
        self.ensure_static_ip_result = ensure_static_ip_result
        self.ensure_dns_managed_zone = ensure_dns_managed_zone
        self.ensure_dns_project_id = ensure_dns_project_id
        self.ensure_dns_ttl = ensure_dns_ttl
        self.ensure_dns_result = ensure_dns_result
        self.ensure_dns_created = ensure_dns_created
        self.ensure_dns_updated = ensure_dns_updated
        self.ensure_dns_previous_ips = tuple(ensure_dns_previous_ips or ())
        self.publish_calls: list[tuple[SEOMigrationGitHubPublishTarget, list[SEOMigrationGitHubPublishFile], bool]] = []
        self.deploy_calls: list[tuple[SEOMigrationGitHubDeployTarget, bool]] = []
        self.refresh_calls: list[tuple[SEOMigrationGitHubDeployTarget, int, str | None]] = []
        self.secret_upsert_calls: list[tuple[str, str, str, str]] = []
        self.ensure_static_ip_calls: list[tuple[str, str, str | None, dict[str, object] | None, str | None, bool]] = []
        self.ensure_dns_calls: list[tuple[str, str, str, str, str | None, int, bool]] = []
        self.adopt_repository_calls: list[tuple[str, str, str, str, str, str | None, str | None]] = []
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
                dict[str, object] | None,
                str | None,
                str | None,
                str | None,
                bool | None,
                str | None,
            ]
        ] = []

    def ensure_managed_site_static_ip(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        site_id: str | None,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        namespace_isolation_defaults: dict[str, object] | None = None,
        preview_hostname: str | None = None,
        dry_run: bool = False,
    ) -> SEOMigrationGitHubManagedSiteStaticIPEnsureResult:
        del namespace_isolation_defaults, preview_hostname
        self.ensure_static_ip_calls.append(
            (
                repo_owner,
                repo_name,
                site_id,
                managed_gke_config,
                gcp_deploy_key,
                bool(dry_run),
            )
        )
        static_ip_name, _ = derive_site_preview_static_ip_name(
            repo_name=repo_name,
            site_id=site_id,
        )
        project_id = str((managed_gke_config or {}).get("project_id") or self.ensure_dns_project_id or "test-project")
        if dry_run:
            return SEOMigrationGitHubManagedSiteStaticIPEnsureResult(
                static_ip_name=static_ip_name,
                static_ip_address=None,
                static_ip_created=False,
                gcp_project_id=project_id,
                result="dry_run",
            )
        return SEOMigrationGitHubManagedSiteStaticIPEnsureResult(
            static_ip_name=static_ip_name,
            static_ip_address=self.ensure_static_ip_address,
            static_ip_created=bool(self.ensure_static_ip_created),
            gcp_project_id=project_id,
            result=self.ensure_static_ip_result,
        )

    def ensure_managed_site_dns_a_record(
        self,
        *,
        preview_hostname: str,
        expected_ip_address: str,
        dns_managed_zone: str,
        dns_project_id: str,
        gcp_deploy_key: str | None,
        ttl: int = 300,
        dry_run: bool = False,
    ) -> SEOMigrationGitHubManagedSiteDnsEnsureResult:
        self.ensure_dns_calls.append(
            (
                preview_hostname,
                expected_ip_address,
                dns_managed_zone,
                dns_project_id,
                gcp_deploy_key,
                int(ttl),
                bool(dry_run),
            )
        )
        normalized_record_name = f"{str(preview_hostname).strip().rstrip('.') or preview_hostname}."
        if dry_run:
            return SEOMigrationGitHubManagedSiteDnsEnsureResult(
                dns_record_name=normalized_record_name,
                dns_record_type="A",
                dns_managed_zone=str(dns_managed_zone or self.ensure_dns_managed_zone),
                dns_project_id=str(dns_project_id or self.ensure_dns_project_id),
                dns_expected_ip=str(expected_ip_address or self.ensure_static_ip_address),
                dns_previous_ips=(),
                dns_updated=False,
                dns_created=False,
                dns_ttl=int(ttl) if int(ttl) > 0 else self.ensure_dns_ttl,
                result="dry_run",
            )
        return SEOMigrationGitHubManagedSiteDnsEnsureResult(
            dns_record_name=normalized_record_name,
            dns_record_type="A",
            dns_managed_zone=str(dns_managed_zone or self.ensure_dns_managed_zone),
            dns_project_id=str(dns_project_id or self.ensure_dns_project_id),
            dns_expected_ip=str(expected_ip_address or self.ensure_static_ip_address),
            dns_previous_ips=tuple(self.ensure_dns_previous_ips),
            dns_updated=bool(self.ensure_dns_updated),
            dns_created=bool(self.ensure_dns_created),
            dns_ttl=int(ttl) if int(ttl) > 0 else self.ensure_dns_ttl,
            result=self.ensure_dns_result,
        )

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
        expected_business_id: str | None = None,
        expected_site_id: str | None = None,
    ) -> SEOMigrationGitHubPublishPreflightResult:
        del auto_create_enabled, expected_owner, expected_business_id, expected_site_id
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

    def adopt_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        business_id: str,
        site_id: str,
        principal_id: str | None = None,
        expected_owner: str | None = None,
    ) -> SEOMigrationGitHubRepoAdoptionResult:
        self.adopt_repository_calls.append(
            (
                repo_owner,
                repo_name,
                ref,
                business_id,
                site_id,
                principal_id,
                expected_owner,
            )
        )
        if self.fail_adoption:
            raise SEOMigrationGitHubPublisherError(
                code=self.adoption_error_code or "github_repo_adoption_failed",
                safe_message=self.adoption_error_message or "Simulated adoption failure.",
                stage="repo_adoption",
            )
        return SEOMigrationGitHubRepoAdoptionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=ref,
            marker_written=True,
            adoption_outcome="marker_written",
            management_status="managed_marker_match",
            marker_business_id=business_id,
            marker_site_id=site_id,
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
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        del managed_gke_config, managed_image_pull_secret_config
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

    def provision_managed_image_pull_secret(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        kubernetes_namespace: str,
        managed_gke_config: dict[str, object] | None,
        git_userid: str | None,
        git_email: str | None,
        git_token: str | None,
        gcp_deploy_key: str | None,
        dry_run: bool = False,
    ) -> SEOMigrationGitHubImagePullSecretProvisionResult:
        del managed_gke_config, git_userid, git_email, git_token, gcp_deploy_key
        return SEOMigrationGitHubImagePullSecretProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            namespace=kubernetes_namespace,
            secret_name="ghcr-pull-secret",
            action="dry_run" if dry_run else "updated",
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
        managed_image_pull_secret_config: dict[str, object] | None = None,
        namespace_isolation_defaults: dict[str, object] | None = None,
        site_id: str | None = None,
        business_id: str | None = None,
        repository_auto_create_created: bool | None = None,
        artifact_version_id: str | None = None,
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
                managed_image_pull_secret_config,
                namespace_isolation_defaults,
                site_id,
                business_id,
                repository_auto_create_created,
                artifact_version_id,
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
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubTargetReadinessResult:
        del (
            allow_ref_repair,
            allow_workflow_repair,
            dry_run,
            managed_gke_config,
            namespace_isolation_defaults,
            managed_image_pull_secret_config,
        )
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


class _StubSEOAnalyticsServiceForOutcome:
    def __init__(
        self,
        *,
        site_summary: SEOAnalyticsSiteSummaryRead,
        comparison: object | None = None,
        min_after_days: int = 7,
    ) -> None:
        self.site_summary = site_summary
        self.comparison = comparison
        self.settings = SimpleNamespace(ga4_outcome_min_after_days=min_after_days)
        self.site_summary_calls: list[dict[str, object]] = []
        self.comparison_calls: list[dict[str, object]] = []

    def get_site_summary(
        self,
        *,
        business_id: str,
        site_id: str,
        site_domain: str | None,
        ga4_property_id: str | None = None,
        enforce_site_ga4_property: bool = False,
    ) -> SEOAnalyticsSiteSummaryRead:
        self.site_summary_calls.append(
            {
                "business_id": business_id,
                "site_id": site_id,
                "site_domain": site_domain,
                "ga4_property_id": ga4_property_id,
                "enforce_site_ga4_property": enforce_site_ga4_property,
            }
        )
        return self.site_summary

    def build_recommendation_outcome_comparison(
        self,
        *,
        site_domain: str | None,
        anchor_timestamp,
        page_path: str | None,
        ga4_property_id: str | None,
        before_window_days: int | None = None,
        after_window_days: int | None = None,
    ):
        self.comparison_calls.append(
            {
                "site_domain": site_domain,
                "anchor_timestamp": anchor_timestamp,
                "page_path": page_path,
                "ga4_property_id": ga4_property_id,
                "before_window_days": before_window_days,
                "after_window_days": after_window_days,
            }
        )
        return self.comparison


def _build_outcome_comparison_stub() -> object:
    return SimpleNamespace(
        before_window=SimpleNamespace(
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 14),
            sessions=100,
            users=82,
            engagement_rate=0.42,
            organic_search_sessions=61,
        ),
        after_window=SimpleNamespace(
            start_date=date(2026, 3, 15),
            end_date=date(2026, 3, 28),
            sessions=131,
            users=101,
            engagement_rate=0.48,
            organic_search_sessions=79,
        ),
        comparison_scope="site",
    )


class _AlwaysExpiredSessionTokenService:
    def verify_access_token(self, token: str):  # noqa: ANN001
        del token
        raise AppSessionTokenError("expired")


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


def test_github_publisher_dependency_uses_git_token_when_present() -> None:
    settings = SimpleNamespace(
        git_token=" test-token ",
        migration_github_api_base_url="https://api.github.com",
        migration_github_timeout_seconds=30.0,
        migration_publish_committer_name="MBSRN Automation",
        migration_publish_committer_email="automation@example.com",
        gcp_managed_deploy=None,
    )
    with patch("app.api.deps.get_settings", return_value=settings):
        publisher = get_seo_migration_github_publisher()

    assert isinstance(publisher, GitHubSEOMigrationPublisher)


def test_github_publisher_dependency_returns_misconfigured_when_token_missing() -> None:
    settings = SimpleNamespace(
        git_token="  ",
        migration_github_api_base_url="https://api.github.com",
        migration_github_timeout_seconds=30.0,
        migration_publish_committer_name="MBSRN Automation",
        migration_publish_committer_email="automation@example.com",
        gcp_managed_deploy=None,
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


def _seed_site_for_business(
    db_session,
    *,
    business_id: str,
    site_id: str,
    base_url: str,
    normalized_domain: str,
    is_primary: bool = False,
) -> None:
    site = SEOSite(
        id=site_id,
        business_id=business_id,
        display_name=f"Site {site_id[-4:]}",
        base_url=base_url,
        normalized_domain=normalized_domain,
        industry="fire protection",
        primary_location="Longmont, CO",
        service_areas_json=["Longmont", "Boulder"],
        is_active=True,
        is_primary=is_primary,
    )
    db_session.add(site)
    db_session.commit()


def _tiny_png_payload() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0bIDAT\x08\xd7c\xf8\x0f"
        b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb1\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _build_migration_artifact_output(
    *,
    index_content: str | None = None,
    styles_content: str | None = None,
) -> SEOMigrationArtifactGenerationOutput:
    return SEOMigrationArtifactGenerationOutput(
        strategy_summary="Draft strategy",
        page_map=[{"path": "/", "title": "Home"}],
        homepage_structure=[],
        service_page_suggestions=[],
        cta_contact_structure={},
        seo_meta_suggestions={},
        redirect_suggestions=[],
        analytics_placeholders=[],
        generated_files=[
            SEOMigrationGeneratedFileOutput(
                path="index.html",
                media_type="text/html",
                content=index_content
                or "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body><h1>Draft Home</h1></body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="styles.css",
                media_type="text/css",
                content=styles_content or "body { color: #111; }",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )


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


def test_requirements_suggestion_endpoint_returns_completed_payload_for_supported_fields(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/requirements/suggest",
        json={
            "field": "must_include",
            "current_value": ["Include emergency response coverage"],
            "force_refresh": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("field") == "must_include"
    assert payload.get("suggestion_status") == "completed"
    assert payload.get("reason_code") == "requirements_suggestion_completed"
    assert isinstance(payload.get("suggested_value"), list)
    assert payload.get("retryable") is False
    assert isinstance(payload.get("context_sources_used"), list)
    diagnostics = payload.get("model_diagnostics") or {}
    assert diagnostics.get("task_alias") == "requirements_helper"
    assert diagnostics.get("source") in {"env", "provider_fallback"}
    assert diagnostics.get("fallback_used") is True
    payload_json = json.dumps(payload).lower()
    assert "database_url" not in payload_json
    assert "storage_key" not in payload_json
    assert "raw_token" not in payload_json
    assert "image_base64" not in payload_json


def test_requirements_suggestion_endpoint_returns_not_available_for_unsupported_fields(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/requirements/suggest",
        json={
            "field": "unsupported_field",
            "current_value": None,
            "force_refresh": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("suggestion_status") == "not_available"
    assert payload.get("suggested_value") is None
    assert payload.get("reason_code") == "requirements_suggestion_field_unsupported"


def test_requirements_suggestion_endpoint_maps_provider_unavailable_without_google_dependency(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    provider = MockSEOMigrationArtifactGenerationProvider(
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
    )
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=provider,
    )
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/requirements/suggest",
        json={
            "field": "tone",
            "current_value": ["Clear and practical"],
            "force_refresh": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("field") == "tone"
    assert payload.get("suggestion_status") == "failed"
    assert payload.get("suggested_value") is None
    assert payload.get("reason_code") == "requirements_suggestion_provider_unavailable"


def test_requirements_suggestion_endpoint_fails_safely_for_incompatible_default_model(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    business = db_session.get(Business, business_id)
    assert business is not None
    business.default_ai_model = "text-embedding-3-small"
    db_session.add(business)
    db_session.commit()

    client = _make_client(db_session, business_id=business_id)
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/requirements/suggest",
        json={
            "field": "must_include",
            "current_value": None,
            "force_refresh": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("suggestion_status") == "failed"
    assert payload.get("reason_code") == "requirements_suggestion_model_incompatible"
    diagnostics = payload.get("model_diagnostics") or {}
    assert diagnostics.get("task_alias") == "requirements_helper"
    assert diagnostics.get("source") == "admin_config"
    assert diagnostics.get("fallback_used") is False
    assert "structured_json" in str(diagnostics.get("message") or "")


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
    assert isinstance(deploy_result.get("expected_static_ip_name"), str)
    assert deploy_result.get("expected_static_ip_address") == _STUB_MANAGED_SITE_STATIC_IP_ADDRESS
    assert isinstance(deploy_result.get("expected_dns_hostname"), str)
    assert deploy_result.get("expected_dns_ip") == _STUB_MANAGED_SITE_STATIC_IP_ADDRESS
    assert deploy_result.get("dns_propagation_result") in {
        "observed_expected_ip",
        "observed_expected_ip_after_retry",
    }

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


def test_adopt_publish_repository_endpoint_writes_management_marker(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher()
    client = _make_client(db_session, business_id=business_id, github_publisher=publisher)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "mhanson13",
                "repo_name": "scmechanical",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish/adopt-repository",
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["marker_written"] is True
    assert payload["result"]["adoption_outcome"] == "marker_written"
    assert len(publisher.adopt_repository_calls) == 1


def test_artifact_file_stream_route_serves_materialized_media_without_exposing_base64_in_version_payload(
    db_session,
) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    provider = _StaticMigrationArtifactProvider(_build_migration_artifact_output())
    client = _make_client(db_session, business_id=business_id, artifact_provider=provider)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    upload_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "hero.png", "selected_for_draft": "true"},
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert upload_response.status_code == 201
    uploaded_asset_id = str(upload_response.json().get("asset_id") or "")
    assert uploaded_asset_id.startswith("upl-")

    provider.output = _build_migration_artifact_output(
        index_content=(
            "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body>"
            f"<img src=\"{uploaded_asset_id}\" alt=\"hero\"/>"
            "</body></html>"
        )
    )

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 201
    artifact_payload = generate_response.json()
    artifact_id = str(artifact_payload.get("id") or "")
    assert artifact_id

    artifact_version_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}"
    )
    assert artifact_version_response.status_code == 200
    generated_files = artifact_version_response.json().get("generated_files_json") or []
    assert isinstance(generated_files, list)
    index_file = next(item for item in generated_files if isinstance(item, dict) and item.get("path") == "index.html")
    image_file = next(
        item
        for item in generated_files
        if isinstance(item, dict) and str(item.get("path") or "").startswith("assets/images/")
    )
    index_content = str(index_file.get("content") or "")
    assert uploaded_asset_id not in index_content
    assert "assets/images/" in index_content
    assert image_file.get("content_base64") is None
    assert image_file.get("content_encoding") is None

    image_path = str(image_file.get("path") or "")
    image_stream_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/files/{image_path}"
    )
    assert image_stream_response.status_code == 200
    assert image_stream_response.headers.get("content-type", "").startswith("image/png")
    assert image_stream_response.content == _tiny_png_payload()


def test_adopt_publish_repository_endpoint_returns_validation_error_on_failure(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher(
        fail_adoption=True,
        adoption_error_code="github_repo_adoption_failed",
        adoption_error_message="GitHub repository adoption failed.",
    )
    client = _make_client(db_session, business_id=business_id, github_publisher=publisher)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "publish_config": {
                "enabled": True,
                "repo_owner": "mhanson13",
                "repo_name": "scmechanical",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200

    response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/publish/adopt-repository",
    )
    assert response.status_code == 422
    detail = response.json().get("detail") or {}
    detail_message = detail.get("message") if isinstance(detail, dict) else str(detail)
    assert "adoption failed" in str(detail_message).lower()


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


def test_workspace_publish_target_supports_platform_public_site_repo_name(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    admin_publish_config = db_session.query(GitHubPublishConfig).one()
    admin_publish_config.repository = "mhanson13"
    admin_publish_config.default_branch = "main"
    db_session.add(admin_publish_config)
    db_session.commit()

    client = _make_client(db_session, business_id=business_id)
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://www.mbsrn.com/",
            "publish_config": {
                "enabled": True,
                "repo_owner": "should-not-override-admin-owner",
                "repo_name": "mbsrn-www",
                "branch": "main",
            },
        },
    )
    assert workspace_response.status_code == 200
    workspace_payload = workspace_response.json()
    publish_config_json = workspace_payload.get("publish_config_json") or {}
    assert publish_config_json.get("repo_name") == "mbsrn-www"
    assert publish_config_json.get("repo_owner") in {"", None}

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    publish_readiness = summary_response.json().get("publish_readiness") or {}
    publish_target = publish_readiness.get("target") or {}
    assert publish_target.get("repo_owner") == "mhanson13"
    assert publish_target.get("repo_name") == "mbsrn-www"
    assert publish_target.get("branch") == "main"
    config_prereqs = publish_readiness.get("config_prerequisites") or {}
    assert config_prereqs.get("admin_publish_configured") is True
    assert config_prereqs.get("operator_repository_configured") is True


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


def test_deploy_endpoint_accepts_replace_existing_runtime_flag(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    publisher = _StubMigrationGitHubPublisher()
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
            "replace_existing_runtime": True,
        },
    )
    assert deploy_response.status_code == 200
    deploy_result = deploy_response.json().get("result") or {}
    assert "replace_existing_runtime" in (deploy_result.get("workflow_inputs_sent_keys") or [])
    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.inputs.get("replace_existing_runtime") == "true"


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
    deploy_prereqs = payload["deploy_readiness"].get("config_prerequisites") or {}
    for key in (
        "runtime_ready",
        "ingress_address_resolved",
        "service_exists",
        "endpoints_ready",
        "managed_certificate_exists",
        "https_ready",
        "runtime_ready_tls_pending",
        "replace_existing_runtime_requested",
        "replace_existing_runtime_performed",
        "deploy_runtime_reason_code_present",
        "managed_deploy_template_marker_present",
    ):
        value = payload["deploy_readiness"].get(key)
        assert value is None or isinstance(value, bool)
        prereq_value = deploy_prereqs.get(key)
        assert prereq_value is None or isinstance(prereq_value, bool)
    for key in (
        "managed_certificate_status",
        "deploy_runtime_failure_stage",
        "deploy_runtime_reason_message",
        "mbsrn_managed_deploy_template_version",
    ):
        value = payload["deploy_readiness"].get(key)
        assert value is None or isinstance(value, str)
        prereq_value = deploy_prereqs.get(key)
        assert prereq_value is None or isinstance(prereq_value, str)
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


def test_migration_summary_redacts_private_generated_media_urls_in_readiness_payload(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    monkeypatch.setenv("API_CORS_ALLOWED_ORIGINS", "https://operator.internal.example")
    get_settings.cache_clear()
    try:
        preview_media_url = (
            "https://operator.internal.example"
            f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/upl-private-preview/preview"
        )
        storage_media_url = (
            "https://storage.googleapis.com/private-bucket/hero.png"
            "?X-Goog-Algorithm=GOOG4-RSA-SHA256"
            "&X-Goog-Credential=test%2Fcredential"
            "&X-Goog-Signature=secret-signature"
        )
        provider = _StaticMigrationArtifactProvider(
            _build_migration_artifact_output(
                index_content=(
                    "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body>"
                    f"<img src=\"{preview_media_url}\" alt=\"preview\" />"
                    "</body></html>"
                ),
                styles_content=f"body {{ background-image: url('{storage_media_url}'); }}",
            )
        )
        client = _make_client(db_session, business_id=business_id, artifact_provider=provider)

        workspace_response = client.put(
            f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
            json={"source_url": "https://legacy.example"},
        )
        assert workspace_response.status_code == 200
        _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

        generate_response = client.post(
            f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
            json={"force_new_version": False},
        )
        assert generate_response.status_code == 201
        artifact_id = generate_response.json()["id"]

        approve_response = client.post(
            f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_id}/approve",
            json={"approval_notes": None},
        )
        assert approve_response.status_code == 200

        summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
        assert summary_response.status_code == 200
        payload = summary_response.json()
        publish_readiness = payload.get("publish_readiness") or {}
        deploy_readiness = payload.get("deploy_readiness") or {}
        publish_media = publish_readiness.get("artifact_media_readiness") or {}
        deploy_media = deploy_readiness.get("artifact_media_readiness") or {}

        assert publish_media.get("ready") is False
        assert deploy_media.get("ready") is False
        publish_reasons = [str(item).lower() for item in (publish_media.get("reasons") or [])]
        assert any("private app/control-plane preview or media urls" in item for item in publish_reasons)
        assert any("private or signed storage media urls" in item for item in publish_reasons)
        publish_reason_counts = publish_media.get("invalid_media_reference_reason_counts") or {}
        assert publish_reason_counts.get("artifact_media_app_private_url") == 1
        assert publish_reason_counts.get("artifact_media_private_storage_url") == 1

        serialized_publish_media = json.dumps(publish_media).lower()
        serialized_deploy_media = json.dumps(deploy_media).lower()
        assert "operator.internal.example" not in serialized_publish_media
        assert "storage.googleapis.com" not in serialized_publish_media
        assert "x-goog-signature" not in serialized_publish_media
        assert "operator.internal.example" not in serialized_deploy_media
        assert "storage.googleapis.com" not in serialized_deploy_media
        assert "x-goog-signature" not in serialized_deploy_media
    finally:
        get_settings.cache_clear()


def test_migration_summary_prefers_deploy_anchor_for_ga4_outcome_snapshot(db_session) -> None:
    business_id = "0f0f0f0f-0000-4000-8000-000000000001"
    site_id = "0f0f0f0f-0000-4000-8000-000000000002"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"workspace": {}},
    )
    assert workspace_response.status_code == 200

    site = db_session.query(SEOSite).filter(SEOSite.id == site_id).one()
    site.ga4_property_id = "123456789"
    workspace = db_session.query(SEOMigrationWorkspace).filter(SEOMigrationWorkspace.site_id == site_id).one()
    workspace.last_published_at = utc_now() - timedelta(days=40)
    workspace.last_deployed_at = utc_now() - timedelta(days=20)
    db_session.add(site)
    db_session.add(workspace)
    db_session.commit()

    analytics_stub = _StubSEOAnalyticsServiceForOutcome(
        site_summary=SEOAnalyticsSiteSummaryRead(
            business_id=business_id,
            site_id=site_id,
            available=True,
            status="available",
            ga4_status="connected",
            ga4_error_reason=None,
            ga4_health={"ga4_health_status": "reachable"},
        ),
        comparison=_build_outcome_comparison_stub(),
        min_after_days=7,
    )
    client.app.dependency_overrides[get_seo_analytics_service] = lambda: analytics_stub

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    snapshot = summary_response.json().get("ga4_outcome_snapshot") or {}
    assert snapshot.get("status") == "available"
    assert snapshot.get("anchor_type") == "migration_deployed"
    assert snapshot.get("outcome_direction") in {"improved", "declined", "mixed", "no_clear_change", "insufficient_data"}
    assert "Observed after deploy" in str(snapshot.get("operator_hint") or "")
    assert analytics_stub.comparison_calls
    assert analytics_stub.comparison_calls[0].get("page_path") is None
    assert analytics_stub.comparison_calls[0].get("ga4_property_id") == "123456789"


def test_migration_summary_uses_publish_anchor_when_deploy_timestamp_missing(db_session) -> None:
    business_id = "0f0f0f0f-0000-4000-8000-000000000011"
    site_id = "0f0f0f0f-0000-4000-8000-000000000012"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"workspace": {}},
    )
    assert workspace_response.status_code == 200

    site = db_session.query(SEOSite).filter(SEOSite.id == site_id).one()
    site.ga4_property_id = "123456789"
    workspace = db_session.query(SEOMigrationWorkspace).filter(SEOMigrationWorkspace.site_id == site_id).one()
    workspace.last_published_at = utc_now() - timedelta(days=2)
    workspace.last_deployed_at = None
    db_session.add(site)
    db_session.add(workspace)
    db_session.commit()

    analytics_stub = _StubSEOAnalyticsServiceForOutcome(
        site_summary=SEOAnalyticsSiteSummaryRead(
            business_id=business_id,
            site_id=site_id,
            available=True,
            status="available",
            ga4_status="connected",
            ga4_error_reason=None,
            ga4_health={"ga4_health_status": "reachable"},
        ),
        comparison=_build_outcome_comparison_stub(),
        min_after_days=7,
    )
    client.app.dependency_overrides[get_seo_analytics_service] = lambda: analytics_stub

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    snapshot = summary_response.json().get("ga4_outcome_snapshot") or {}
    assert snapshot.get("status") == "pending_after_window"
    assert snapshot.get("anchor_type") == "migration_published"
    assert "after-publish traffic" in str(snapshot.get("operator_hint") or "")
    assert not analytics_stub.comparison_calls


def test_migration_summary_returns_not_configured_when_site_ga4_property_missing(db_session) -> None:
    business_id = "0f0f0f0f-0000-4000-8000-000000000021"
    site_id = "0f0f0f0f-0000-4000-8000-000000000022"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"workspace": {}},
    )
    assert workspace_response.status_code == 200

    workspace = db_session.query(SEOMigrationWorkspace).filter(SEOMigrationWorkspace.site_id == site_id).one()
    workspace.last_deployed_at = utc_now() - timedelta(days=14)
    db_session.add(workspace)
    db_session.commit()

    analytics_stub = _StubSEOAnalyticsServiceForOutcome(
        site_summary=SEOAnalyticsSiteSummaryRead(
            business_id=business_id,
            site_id=site_id,
            available=False,
            status="not_configured",
            ga4_status="not_configured",
            ga4_error_reason="not_configured",
        ),
        comparison=_build_outcome_comparison_stub(),
        min_after_days=7,
    )
    client.app.dependency_overrides[get_seo_analytics_service] = lambda: analytics_stub

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    snapshot = summary_response.json().get("ga4_outcome_snapshot") or {}
    assert snapshot.get("status") == "not_configured"
    assert snapshot.get("anchor_type") == "migration_deployed"
    assert "add a ga4 property id" in str(snapshot.get("operator_hint") or "").lower()
    assert not analytics_stub.comparison_calls


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
    assert detail.get("timeout_seconds") == 300
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
    assert diagnostics.get("last_draft_failure_timeout_seconds") == 300
    assert diagnostics.get("last_draft_failure_timeout_source") == "default"
    assert diagnostics.get("draft_timeout_seconds") == 300
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
    assert ai_execution.get("timeout_seconds") == 300
    assert ai_execution.get("timeout_source") == "default"
    assert "raw_output" not in ai_execution
    top_state = summary_response.json().get("context_summary", {}).get("draft_generation_state") or {}
    assert top_state.get("status") == "generation_failed"
    assert top_state.get("summary") == "Migration draft generation timed out while calling the AI provider."


def test_generate_draft_preflight_block_returns_actionable_reason_code(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(
        db_session,
        business_id=business_id,
        artifact_provider=_RaisingMigrationArtifactProvider(
            SEOMigrationArtifactProviderError(
                code="migration_generation_preflight_too_large",
                reason="validation_failed",
                safe_message=(
                    "Migration draft generation was blocked before provider call because preflight input size "
                    "or complexity exceeded Admin safety settings."
                ),
                provider_name="openai",
                model_name="gpt-4o-mini",
                prompt_version="seo-migration-v1",
                retryable=False,
                normalized_failure_category="local_validation_failure",
                normalized_failure_reason="request_too_large_or_complex",
                normalized_failure_source="local_validation",
                normalized_retryable=False,
                attempt_count=0,
                internal_details={
                    "generation_safety": {
                        "migration_preflight_mode": "block_before_provider",
                        "migration_max_final_input_chars": 9000,
                        "migration_max_difficulty_score": 12,
                        "compact_fallback_attempted": False,
                        "budget_capped": False,
                        "preflight_blocked": True,
                        "preflight_block_reason": "final_input_chars_exceeded",
                    },
                },
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
    assert detail.get("reason_code") == "migration_generation_preflight_too_large"
    assert "blocked before provider call" in str(detail.get("operator_action", "")).lower()

    summary_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/summary")
    assert summary_response.status_code == 200
    context_summary = summary_response.json().get("context_summary", {})
    diagnostics = context_summary.get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_failure_source") == "local_preflight"
    ai_execution = context_summary.get("ai_execution") or {}
    assert ai_execution.get("provider_execution_status") == "not_called"
    assert ai_execution.get("failure_source") == "local_preflight"
    draft_input_summary = summary_response.json().get("context_summary", {}).get("draft_input_summary") or {}
    assert draft_input_summary.get("generation_preflight_blocked") is True
    assert draft_input_summary.get("generation_preflight_block_reason") == "final_input_chars_exceeded"
    assert draft_input_summary.get("generation_provider_call_skipped") is True


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


def test_migration_media_routes_scope_assets_and_sanitize_payloads(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    other_site_id = "33333333-3333-3333-3333-333333333333"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    _seed_site_for_business(
        db_session,
        business_id=business_id,
        site_id=other_site_id,
        base_url="https://second.example/",
        normalized_domain="second.example",
    )
    client = _make_client(db_session, business_id=business_id)

    for target_site_id in (site_id, other_site_id):
        workspace_response = client.put(
            f"/api/businesses/{business_id}/seo/sites/{target_site_id}/migration/workspace",
            json={"source_url": "https://legacy.example"},
        )
        assert workspace_response.status_code == 200

    upload_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={
            "filename": "crew-photo.png",
            "selected_for_draft": "true",
            "category": "project_gallery",
            "alt_text": "Crew photo",
            "description": "Project crew onsite",
            "usage_note": "Use in projects gallery",
            "page_assignment": "/projects",
        },
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    assert uploaded.get("provenance") == "operator_upload"
    assert uploaded.get("selected_for_draft") is True
    assert uploaded.get("content_type") == "image/png"
    assert "storage_key" not in uploaded

    asset_id = str(uploaded.get("asset_id") or "")
    assert asset_id

    preview_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}/preview"
    )
    assert preview_response.status_code == 200
    assert (preview_response.headers.get("content-type") or "").startswith("image/png")
    assert preview_response.content == _tiny_png_payload()

    cross_site_preview_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{other_site_id}/migration/media/assets/{asset_id}/preview"
    )
    assert cross_site_preview_response.status_code == 404

    update_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}",
        json={
            "selected_for_draft": False,
            "category": "hero",
            "alt_text": "Updated hero alt",
            "description": "Updated hero description",
            "usage_note": "Updated usage note",
            "page_assignment": "/",
        },
    )
    assert update_response.status_code == 200
    updated_asset = update_response.json()
    assert updated_asset.get("selected_for_draft") is False
    assert updated_asset.get("category") == "hero"
    assert updated_asset.get("alt_text") == "Updated hero alt"

    suggest_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}/suggest-metadata",
    )
    assert suggest_response.status_code == 200
    suggested_asset = suggest_response.json()
    suggestion = suggested_asset.get("metadata_suggestion") or {}
    assert suggestion.get("suggestion_status") == "completed"
    assert suggestion.get("reason_code") == "image_metadata_suggested"
    diagnostics = suggestion.get("model_diagnostics") or {}
    assert diagnostics.get("task_alias") == "media_metadata_helper"
    assert diagnostics.get("source") in {"env", "provider_fallback"}
    assert diagnostics.get("fallback_used") is True
    suggested_json = json.dumps(suggested_asset).lower()
    for forbidden in (
        "storage_key",
        "base64",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "\\\\",
        "/tmp/",
    ):
        assert forbidden not in suggested_json

    apply_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}",
        json={"apply_suggested_metadata": True},
    )
    assert apply_response.status_code == 200
    applied_asset = apply_response.json()
    assert applied_asset.get("metadata_suggestion_applied") is True
    assert isinstance(applied_asset.get("metadata_suggestion_applied_at"), str)
    assert applied_asset.get("alt_text") != "Updated hero alt"

    site_media_response = client.get(f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets")
    assert site_media_response.status_code == 200
    site_media_payload = site_media_response.json()
    assert site_media_payload.get("operator_uploaded_count") == 1
    assert site_media_payload.get("selected_assets_count") == 0
    serialized_payload = json.dumps(site_media_payload).lower()
    for forbidden in (
        "storage_key",
        "base64",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "\\\\",
        "/tmp/",
    ):
        assert forbidden not in serialized_payload

    other_media_response = client.get(f"/api/businesses/{business_id}/seo/sites/{other_site_id}/migration/media/assets")
    assert other_media_response.status_code == 200
    other_payload = other_media_response.json()
    assert other_payload.get("operator_uploaded_count") == 0
    assert other_payload.get("selected_assets_count") == 0

    cross_site_update_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{other_site_id}/migration/media/assets/{asset_id}",
        json={"apply_suggested_metadata": True},
    )
    assert cross_site_update_response.status_code == 404

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-ignore",
                "normalized_url": "https://legacy.example/images/ignore.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "useful",
                "fetch_status": "validated_head",
                "content_type": "image/jpeg",
            }
        ]
    }
    db_session.add(workspace)
    db_session.commit()

    ignore_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/srcimg-ignore/lifecycle",
        json={"action": "ignore"},
    )
    assert ignore_response.status_code == 200
    ignore_payload = ignore_response.json()
    assert ignore_payload.get("status") == "ignored"
    ignored_asset = ignore_payload.get("media_asset") or {}
    assert ignored_asset.get("workspace_status") == "ignored"

    remove_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{asset_id}/lifecycle",
        json={"action": "remove"},
    )
    assert remove_response.status_code == 200
    remove_payload = remove_response.json()
    assert remove_payload.get("status") == "removed"
    removed_asset = remove_payload.get("media_asset") or {}
    assert removed_asset.get("workspace_status") == "removed"
    assert removed_asset.get("selected_for_draft") is False


def test_migration_media_suggest_metadata_returns_image_not_imported_for_remote_discovered_assets(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-remote-only",
                "normalized_url": "https://legacy.example/images/hero.jpg?token=abc123",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": True,
            }
        ]
    }
    db_session.add(workspace)
    db_session.commit()

    suggest_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/srcimg-remote-only/suggest-metadata",
    )
    assert suggest_response.status_code == 200
    payload = suggest_response.json()
    suggestion = payload.get("metadata_suggestion") or {}
    assert suggestion.get("suggestion_status") == "not_available"
    assert suggestion.get("reason_code") == "image_not_imported"
    serialized = json.dumps(payload).lower()
    for forbidden in ("storage_key", "base64", "access_token", "refresh_token", "authorization", "cookie", "\\\\"):
        assert forbidden not in serialized


def test_migration_media_update_rejects_selecting_unimported_discovered_assets(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-remote-only",
                "normalized_url": "https://legacy.example/images/hero.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "useful",
            },
            {
                "asset_id": "srcimg-placeholder",
                "normalized_url": "https://legacy.example/images/transparent_placeholder.png",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "low_value",
                "quality_reason": "placeholder_image_detected",
            },
        ],
    }
    db_session.add(workspace)
    db_session.commit()

    unimported_select_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/srcimg-remote-only",
        json={"selected_for_draft": True},
    )
    assert unimported_select_response.status_code == 422
    unimported_detail = unimported_select_response.json().get("detail") or {}
    assert unimported_detail.get("error_code") == "media_asset_not_imported"

    low_value_select_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/srcimg-placeholder",
        json={"selected_for_draft": True},
    )
    assert low_value_select_response.status_code == 422
    low_value_detail = low_value_select_response.json().get("detail") or {}
    assert low_value_detail.get("error_code") == "media_asset_not_imported"


def test_migration_media_batch_suggest_metadata_succeeds_for_selected_uploaded_assets(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    uploaded_asset_ids: list[str] = []
    for index in range(2):
        upload_response = client.post(
            f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
            params={
                "filename": f"batch-{index}.png",
                "selected_for_draft": "true",
            },
            headers={"Content-Type": "image/png"},
            content=_tiny_png_payload(),
        )
        assert upload_response.status_code == 201
        payload = upload_response.json()
        asset_id = str(payload.get("asset_id") or "")
        assert asset_id
        uploaded_asset_ids.append(asset_id)

    batch_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/suggest-metadata",
        json={"asset_ids": uploaded_asset_ids},
    )
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload.get("batch_status") == "completed"
    assert payload.get("completed_count") == 2
    assert payload.get("failed_count") == 0
    assert payload.get("skipped_count") == 0
    results = payload.get("results") or []
    assert isinstance(results, list)
    assert len(results) == 2
    for result in results:
        assert isinstance(result, dict)
        assert result.get("asset_id") in uploaded_asset_ids
        assert result.get("suggestion_status") == "completed"
        assert result.get("reason_code") == "image_metadata_suggested"
        assert isinstance(result.get("retryable"), bool)
        diagnostics = ((result.get("metadata_suggestion") or {}).get("model_diagnostics") or {})
        assert diagnostics.get("task_alias") == "media_metadata_helper"
    serialized = json.dumps(payload).lower()
    for forbidden in (
        "storage_key",
        "base64",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "\\\\",
        "/tmp/",
    ):
        assert forbidden not in serialized


def test_migration_media_batch_suggest_metadata_returns_partial_success_for_import_required_assets(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    upload_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={
            "filename": "batch-controlled.png",
            "selected_for_draft": "true",
        },
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert upload_response.status_code == 201
    uploaded_asset_id = str(upload_response.json().get("asset_id") or "")
    assert uploaded_asset_id

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    source_snapshot = dict(workspace.imported_source_snapshot_json or {})
    discovered = list(source_snapshot.get("discovered_images") or [])
    discovered.append(
        {
            "asset_id": "srcimg-remote-only",
            "normalized_url": "https://legacy.example/images/front.jpg?token=abc123",
            "provenance": "source_site_import",
            "import_status": "discovered",
            "selected_for_draft": True,
        }
    )
    source_snapshot["discovered_images"] = discovered
    workspace.imported_source_snapshot_json = source_snapshot
    db_session.add(workspace)
    db_session.commit()

    batch_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/suggest-metadata",
        json={"asset_ids": [uploaded_asset_id, "srcimg-remote-only"]},
    )
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload.get("batch_status") == "partial_success"
    assert payload.get("completed_count") == 1
    assert payload.get("failed_count") == 0
    assert payload.get("skipped_count") == 1
    results = payload.get("results") or []
    assert isinstance(results, list)
    assert len(results) == 2
    results_by_asset = {str(item.get("asset_id") or ""): item for item in results if isinstance(item, dict)}
    uploaded_result = results_by_asset.get(uploaded_asset_id) or {}
    remote_result = results_by_asset.get("srcimg-remote-only") or {}
    assert uploaded_result.get("suggestion_status") == "completed"
    assert uploaded_result.get("reason_code") == "image_metadata_suggested"
    assert remote_result.get("suggestion_status") == "not_available"
    assert remote_result.get("reason_code") == "media_asset_not_imported"
    serialized = json.dumps(payload).lower()
    for forbidden in ("storage_key", "base64", "access_token", "refresh_token", "authorization", "cookie", "\\\\"):
        assert forbidden not in serialized


def test_migration_media_batch_suggest_metadata_blocks_cross_site_asset_access(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    other_site_id = "33333333-3333-3333-3333-333333333333"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    _seed_site_for_business(
        db_session,
        business_id=business_id,
        site_id=other_site_id,
        base_url="https://other.example/",
        normalized_domain="other.example",
    )
    client = _make_client(db_session, business_id=business_id)

    for target_site_id in (site_id, other_site_id):
        workspace_response = client.put(
            f"/api/businesses/{business_id}/seo/sites/{target_site_id}/migration/workspace",
            json={"source_url": "https://legacy.example"},
        )
        assert workspace_response.status_code == 200

    upload_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={
            "filename": "site-a-only.png",
            "selected_for_draft": "true",
        },
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert upload_response.status_code == 201
    site_a_asset_id = str(upload_response.json().get("asset_id") or "")
    assert site_a_asset_id

    batch_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{other_site_id}/migration/media/assets/suggest-metadata",
        json={"asset_ids": [site_a_asset_id]},
    )
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload.get("batch_status") == "failed"
    assert payload.get("completed_count") == 0
    assert payload.get("failed_count") == 1
    assert payload.get("skipped_count") == 0
    results = payload.get("results") or []
    assert isinstance(results, list)
    assert len(results) == 1
    result = results[0] if isinstance(results[0], dict) else {}
    assert result.get("asset_id") == site_a_asset_id
    assert result.get("suggestion_status") == "failed"
    assert result.get("reason_code") == "media_asset_not_authorized"
    assert result.get("retryable") is False


def test_migration_media_batch_suggest_metadata_enforces_max_asset_count(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    oversized_batch = [f"upl-{index}" for index in range(25)]
    batch_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/suggest-metadata",
        json={"asset_ids": oversized_batch},
    )
    assert batch_response.status_code == 422
    detail = batch_response.json().get("detail") or {}
    assert detail.get("error_code") == "media_suggestion_batch_limit_reached"


def test_migration_media_import_endpoint_returns_disabled_reason_when_feature_flag_off(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "false")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-disabled",
                "normalized_url": "https://legacy.example/media/hero.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": True,
            }
        ]
    }
    db_session.add(workspace)
    db_session.commit()

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-disabled"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("batch_status") == "failed"
    assert payload.get("imported_count") == 0
    assert payload.get("disabled_count") == 1
    results = payload.get("results") or []
    assert isinstance(results, list)
    assert results[0].get("status") == "disabled"
    assert results[0].get("reason_code") == "remote_import_disabled"


def test_migration_media_import_endpoint_imports_discovered_assets_and_enables_suggestion(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
                {
                    "asset_id": "srcimg-import-me",
                    "normalized_url": "https://legacy.example/media/hero.jpg?token=abc",
                    "provenance": "source_site_import",
                    "import_status": "discovered",
                    "selected_for_draft": True,
                    "candidate_quality": "useful",
                    "fetch_status": "validated_head",
                    "content_type": "image/png",
                    "metadata_suggestion": {
                        "suggestion_status": "not_available",
                        "reason_code": "image_not_imported",
                    },
                }
        ]
    }
    db_session.add(workspace)
    db_session.commit()

    monkeypatch.setattr(
        seo_migration_module.SEOMigrationService,
        "_fetch_remote_discovered_image_for_import",
        lambda self, *, url: {
            "reason_code": "remote_image_imported",
            "payload": _tiny_png_payload(),
            "content_type": "image/png",
            "final_url": "https://legacy.example/media/hero.jpg",
        },
    )

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-import-me"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("batch_status") == "completed"
    assert payload.get("imported_count") == 1
    assert payload.get("failed_count") == 0
    assert payload.get("skipped_count") == 0
    result_items = payload.get("results") or []
    assert isinstance(result_items, list)
    assert len(result_items) == 1
    first_result = result_items[0] if isinstance(result_items[0], dict) else {}
    assert first_result.get("status") == "imported"
    assert first_result.get("reason_code") == "remote_image_imported"
    media_asset = first_result.get("media_asset") or {}
    assert media_asset.get("import_status") == "selected"
    assert media_asset.get("selected_for_draft") is True
    assert media_asset.get("content_type") == "image/png"
    assert "storage_key" not in media_asset
    serialized = json.dumps(payload).lower()
    for forbidden in ("storage_key", "base64", "access_token", "refresh_token", "authorization", "cookie", "\\\\"):
        assert forbidden not in serialized

    suggest_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/srcimg-import-me/suggest-metadata",
    )
    assert suggest_response.status_code == 200
    suggestion = suggest_response.json().get("metadata_suggestion") or {}
    assert suggestion.get("reason_code") == "image_metadata_suggested"
    assert suggestion.get("suggestion_status") == "completed"


def test_migration_media_import_endpoint_rejects_unknown_discovered_asset_ids(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-missing"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("batch_status") == "failed"
    assert payload.get("failed_count") == 1
    result_items = payload.get("results") or []
    assert isinstance(result_items, list)
    assert result_items[0].get("reason_code") == "image_not_found_in_source_snapshot"


def test_migration_media_import_endpoint_blocks_cross_site_discovered_asset_access(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    other_site_id = "33333333-3333-3333-3333-333333333333"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    _seed_site_for_business(
        db_session,
        business_id=business_id,
        site_id=other_site_id,
        base_url="https://other.example/",
        normalized_domain="other.example",
    )
    client = _make_client(db_session, business_id=business_id)

    for target_site_id in (site_id, other_site_id):
        workspace_response = client.put(
            f"/api/businesses/{business_id}/seo/sites/{target_site_id}/migration/workspace",
            json={"source_url": "https://legacy.example"},
        )
        assert workspace_response.status_code == 200

    site_a_workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    site_a_workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-site-a-only",
                "normalized_url": "https://legacy.example/media/site-a.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": True,
            }
        ]
    }
    db_session.add(site_a_workspace)
    db_session.commit()

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{other_site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-site-a-only"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("imported_count") == 0
    assert payload.get("failed_count") == 1
    results = payload.get("results") or []
    assert isinstance(results, list)
    assert results[0].get("reason_code") == "image_not_found_in_source_snapshot"


def test_migration_media_import_endpoint_blocks_private_source_hosts(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
                {
                    "asset_id": "srcimg-private-host",
                    "normalized_url": "http://127.0.0.1/blocked.png",
                    "provenance": "source_site_import",
                    "import_status": "discovered",
                    "selected_for_draft": True,
                    "candidate_quality": "useful",
                    "fetch_status": "validated_head",
                    "content_type": "image/png",
                }
            ]
        }
    db_session.add(workspace)
    db_session.commit()

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-private-host"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("failed_count") == 1
    first_result = (payload.get("results") or [{}])[0]
    assert first_result.get("reason_code") == "blocked_private_network"


def test_migration_media_import_endpoint_blocks_redirect_escape_to_private_host(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
                {
                    "asset_id": "srcimg-redirect",
                    "normalized_url": "https://legacy.example/media/redirect.jpg",
                    "provenance": "source_site_import",
                    "import_status": "discovered",
                    "selected_for_draft": True,
                    "candidate_quality": "useful",
                    "fetch_status": "validated_head",
                    "content_type": "image/png",
                }
            ]
        }
    db_session.add(workspace)
    db_session.commit()

    def _mock_getaddrinfo(host: str, *_args, **_kwargs):  # noqa: ANN001
        normalized = str(host).strip().lower()
        if normalized == "legacy.example":
            return [(None, None, None, None, ("93.184.216.34", 443))]
        if normalized == "169.254.169.254":
            return [(None, None, None, None, ("169.254.169.254", 80))]
        raise OSError("unknown host")

    class _RedirectOnceOpener:
        def __init__(self) -> None:
            self.calls = 0

        def open(self, request, timeout):  # noqa: ANN001
            del timeout
            self.calls += 1
            if self.calls == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "http://169.254.169.254/latest/meta-data/"},
                    None,
                )
            raise AssertionError("import should block private redirect target before follow-up fetch")

    monkeypatch.setattr(seo_migration_module.socket, "getaddrinfo", _mock_getaddrinfo)
    monkeypatch.setattr(
        seo_migration_module.urllib.request,
        "build_opener",
        lambda *_args, **_kwargs: _RedirectOnceOpener(),
    )

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-redirect"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("failed_count") == 1
    result_items = payload.get("results") or []
    assert isinstance(result_items, list)
    assert result_items[0].get("reason_code") == "blocked_private_network"


@pytest.mark.parametrize(
    ("reason_code", "expected_status", "expected_reason_code"),
    [
        ("unsupported_image_type", "failed", "unsupported_content_type"),
        ("image_too_large", "failed", "file_too_large"),
        ("image_fetch_timeout", "failed", "fetch_timeout"),
        ("image_fetch_failed", "failed", "image_fetch_failed"),
        ("image_content_type_mismatch", "failed", "unsupported_content_type"),
    ],
)
def test_migration_media_import_endpoint_surfaces_stable_fetch_reason_codes(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
    expected_status: str,
    expected_reason_code: str,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-fetch-error",
                "normalized_url": "https://legacy.example/media/error.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": True,
                "candidate_quality": "useful",
                "fetch_status": "validated_head",
                "content_type": "image/jpeg",
            }
        ]
    }
    db_session.add(workspace)
    db_session.commit()

    monkeypatch.setattr(
        seo_migration_module.SEOMigrationService,
        "_fetch_remote_discovered_image_for_import",
        lambda self, *, url: {"reason_code": reason_code},
    )

    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-fetch-error"], "selected_for_draft": True},
    )
    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload.get("imported_count") == 0
    result_items = payload.get("results") or []
    assert isinstance(result_items, list)
    assert result_items[0].get("status") == expected_status
    assert result_items[0].get("reason_code") == expected_reason_code


def test_migration_media_import_endpoint_deduplicates_repeated_import_of_same_discovered_asset(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
                {
                    "asset_id": "srcimg-repeat",
                    "normalized_url": "https://legacy.example/media/repeat.jpg",
                    "provenance": "source_site_import",
                    "import_status": "discovered",
                    "selected_for_draft": True,
                    "candidate_quality": "useful",
                    "fetch_status": "validated_head",
                    "content_type": "image/png",
                }
            ]
        }
    db_session.add(workspace)
    db_session.commit()

    monkeypatch.setattr(
        seo_migration_module.SEOMigrationService,
        "_fetch_remote_discovered_image_for_import",
        lambda self, *, url: {
            "reason_code": "remote_image_imported",
            "payload": _tiny_png_payload(),
            "content_type": "image/png",
            "final_url": "https://legacy.example/media/repeat.jpg",
        },
    )

    first_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-repeat"], "selected_for_draft": True},
    )
    assert first_response.status_code == 200
    assert first_response.json().get("imported_count") == 1

    second_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": ["srcimg-repeat"], "selected_for_draft": True},
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload.get("imported_count") == 0
    assert second_payload.get("skipped_count") == 1
    second_results = second_payload.get("results") or []
    assert isinstance(second_results, list)
    assert second_results[0].get("status") == "skipped"
    assert second_results[0].get("reason_code") == "remote_image_imported"


def test_migration_media_import_endpoint_enforces_batch_count_limit(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEO_MIGRATION_REMOTE_IMAGE_IMPORT_ENABLED", "true")
    get_settings.cache_clear()

    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    oversized_ids = [f"srcimg-{index}" for index in range(13)]
    import_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/discovered/import",
        json={"discovered_image_ids": oversized_ids, "selected_for_draft": True},
    )
    assert import_response.status_code == 422
    detail = import_response.json().get("detail") or {}
    assert detail.get("error_code") == "media_import_count_limit_reached"


def test_migration_media_routes_enforce_validation_and_stable_error_codes(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200

    unsupported_mime_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "vector.svg"},
        headers={"Content-Type": "image/svg+xml"},
        content=_tiny_png_payload(),
    )
    assert unsupported_mime_response.status_code == 422
    unsupported_detail = unsupported_mime_response.json().get("detail") or {}
    assert unsupported_detail.get("error_code") == "unsupported_mime_type"

    mismatched_mime_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "photo.jpg"},
        headers={"Content-Type": "image/jpeg"},
        content=_tiny_png_payload(),
    )
    assert mismatched_mime_response.status_code == 422
    mismatched_detail = mismatched_mime_response.json().get("detail") or {}
    assert mismatched_detail.get("error_code") == "media_upload_content_type_mismatch"

    oversized_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "oversized.png"},
        headers={"Content-Type": "image/png"},
        content=(b"\x89PNG\r\n\x1a\n" + (b"x" * ((8 * 1024 * 1024) + 1))),
    )
    assert oversized_response.status_code == 422
    oversized_detail = oversized_response.json().get("detail") or {}
    assert oversized_detail.get("error_code") == "file_too_large"

    valid_upload_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "metadata-target.png"},
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert valid_upload_response.status_code == 201
    valid_asset = valid_upload_response.json()
    valid_asset_id = str(valid_asset.get("asset_id") or "")
    assert valid_asset_id

    invalid_metadata_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/{valid_asset_id}",
        json={"alt_text": "x" * 500},
    )
    assert invalid_metadata_response.status_code == 422

    invalid_asset_id_response = client.patch(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/assets/%20",
        json={"selected_for_draft": True},
    )
    assert invalid_asset_id_response.status_code == 422
    invalid_asset_id_detail = invalid_asset_id_response.json().get("detail") or {}
    assert invalid_asset_id_detail.get("error_code") == "media_asset_id_required"

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.enriched_content_notes_json = {
        "workspace_media_assets": [
            {
                "asset_id": f"upl-preseed-{index}",
                "display_filename": f"seed-{index}.png",
                "content_type": "image/png",
                "size_bytes": 68,
                "provenance": "operator_upload",
                "selected_for_draft": False,
                "import_status": "uploaded",
            }
            for index in range(80)
        ]
    }
    db_session.add(workspace)
    db_session.commit()

    max_count_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "exceeds-limit.png"},
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert max_count_response.status_code == 422
    max_count_detail = max_count_response.json().get("detail") or {}
    assert max_count_detail.get("error_code") == "workspace_media_upload_limit_reached"


def test_migration_media_upload_requires_existing_workspace_context(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    upload_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/media/upload",
        params={"filename": "without-workspace.png"},
        headers={"Content-Type": "image/png"},
        content=_tiny_png_payload(),
    )
    assert upload_response.status_code == 404
    assert "workspace" in str(upload_response.json().get("detail") or "").lower()


@pytest.mark.parametrize(
    ("raised_code", "expected_code"),
    [
        ("google_reconnect_required", "google_reconnect_required"),
        ("google_integration_unavailable", "google_integration_unavailable"),
        ("draft_generation_context_unavailable", "draft_generation_context_unavailable"),
        ("google_token_expired", "google_reconnect_required"),
    ],
)
def test_generate_draft_route_surfaces_deterministic_reason_codes_for_auth_and_context_failures(
    db_session,
    raised_code: str,
    expected_code: str,
) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)

    class _ReasonCodeDraftService:
        def generate_draft_artifacts(self, *, business_id: str, site_id: str, principal_id: str | None):  # noqa: ANN001
            del business_id, site_id, principal_id
            raise SEOMigrationValidationError(
                "Simulated deterministic draft gating failure.",
                failure_category="unknown_error",
                failure_reason="unknown",
                error_code=raised_code,
            )

    app = FastAPI()
    app.include_router(seo_migration_router)
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(business_id)
    app.dependency_overrides[get_seo_migration_service] = lambda: _ReasonCodeDraftService()
    client = TestClient(app)

    generate_response = client.post(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert generate_response.status_code == 422
    detail = generate_response.json().get("detail") or {}
    assert detail.get("reason_code") == expected_code
    assert detail.get("error_code") == expected_code
    assert isinstance(detail.get("message"), str)
    assert isinstance(detail.get("retryable"), bool)
    assert isinstance(detail.get("operator_action"), str)
    diagnostic_context = detail.get("diagnostic_context") or {}
    assert isinstance(diagnostic_context, dict)
    assert "token" not in json.dumps(detail).lower()


def test_generate_draft_route_requires_app_auth_reason_code_when_bearer_missing(db_session) -> None:
    app = FastAPI()
    app.include_router(seo_migration_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.post(
        "/api/businesses/11111111-1111-1111-1111-111111111111/seo/sites/22222222-2222-2222-2222-222222222222/migration/generate-draft-artifacts",
        json={"force_new_version": True},
    )
    assert response.status_code == 401
    detail = response.json().get("detail") or {}
    assert detail.get("reason_code") == "app_auth_required"


def test_generate_draft_route_returns_session_expired_reason_code_for_expired_session_token(db_session) -> None:
    app = FastAPI()
    app.include_router(seo_migration_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_token_service] = lambda: _AlwaysExpiredSessionTokenService()
    client = TestClient(app)

    response = client.post(
        "/api/businesses/11111111-1111-1111-1111-111111111111/seo/sites/22222222-2222-2222-2222-222222222222/migration/generate-draft-artifacts",
        json={"force_new_version": True},
        headers={"Authorization": "Bearer a.b.c"},
    )
    assert response.status_code == 401
    detail = response.json().get("detail") or {}
    assert detail.get("reason_code") == "session_expired"


def test_draft_readiness_endpoint_returns_bounded_counts_and_no_secrets(db_session) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "operator_requirements": {
                "business_objectives": ["Replace weak legacy pages"],
            },
            "enriched_content_notes": {
                "replacement_summary": "Prepared replacement copy.",
            },
        },
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    now = utc_now()
    audit_run = SEOAuditRun(
        id="audit-run-readiness-1",
        business_id=business_id,
        site_id=site_id,
        status="completed",
        started_at=now,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    recommendation_run = SEORecommendationRun(
        id="recommendation-run-readiness-1",
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
        id="recommendation-readiness-1",
        business_id=business_id,
        site_id=site_id,
        recommendation_run_id=recommendation_run.id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        rule_key="migration-readiness-rule",
        category="SEO",
        severity="WARNING",
        title="Improve service-page trust proof",
        rationale="Legacy content is sparse.",
        priority_score=70,
        priority_band="high",
        effort_bucket="small",
        status="open",
    )
    db_session.add(audit_run)
    db_session.add(recommendation_run)
    db_session.add(recommendation)

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "title": "Legacy",
        "discovered_images": [
            {
                "asset_id": "srcimg-1",
                "normalized_url": "https://legacy.example/hero.jpg?token=abc",
                "selected_for_draft": True,
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAUA",
            },
            {
                "asset_id": "srcimg-2",
                "normalized_url": "https://legacy.example/gallery.jpg?token=def",
                "selected_for_draft": False,
            },
        ],
    }
    enriched_notes = dict(workspace.enriched_content_notes_json or {})
    enriched_notes["workspace_media_assets"] = [
        {
            "asset_id": "upl-1",
            "display_filename": "crew.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 2048,
            "provenance": "operator_upload",
            "selected_for_draft": True,
            "import_status": "selected",
            "raw_token_value": "secret-token-value",
            "storage_key": "workspace/asset/upl-1.jpg",
        }
    ]
    workspace.enriched_content_notes_json = enriched_notes
    db_session.add(workspace)
    db_session.commit()

    readiness_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/draft-readiness",
    )
    assert readiness_response.status_code == 200
    payload = readiness_response.json()
    assert payload.get("app_auth_ready") is True
    assert isinstance(payload.get("ready"), bool)
    assert isinstance(payload.get("blocking_reason_codes"), list)
    assert isinstance(payload.get("warning_reason_codes"), list)
    assert payload.get("recommendations_available_count") == 1
    assert payload.get("selected_media_assets_count") == 2
    assert payload.get("source_site_images_discovered_count") == 2
    assert isinstance(payload.get("media_required_by_operator"), bool)
    assert isinstance(payload.get("media_requirement_sources"), list)
    assert isinstance(payload.get("usable_media_assets_count"), int)
    assert isinstance(payload.get("useful_discovered_images_count"), int)
    assert isinstance(payload.get("low_value_discovered_images_count"), int)
    assert isinstance(payload.get("rejected_discovered_images_count"), int)
    assert isinstance(payload.get("selected_usable_media_assets_count"), int)
    assert isinstance(payload.get("media_requirement_satisfied"), bool)
    assert isinstance(payload.get("operator_action"), str)

    serialized = json.dumps(payload).lower()
    assert "raw_token_value" not in serialized
    assert "secret-token-value" not in serialized
    assert "image_base64" not in serialized
    assert "ivborw0kggo" not in serialized
    assert "storage_key" not in serialized


def test_draft_readiness_endpoint_requires_app_auth_reason_code_when_bearer_missing(db_session) -> None:
    app = FastAPI()
    app.include_router(seo_migration_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get(
        "/api/businesses/11111111-1111-1111-1111-111111111111/seo/sites/22222222-2222-2222-2222-222222222222/migration/draft-readiness",
    )
    assert response.status_code == 401
    detail = response.json().get("detail") or {}
    assert detail.get("reason_code") == "app_auth_required"


def test_draft_readiness_endpoint_returns_session_expired_reason_code_for_expired_session_token(db_session) -> None:
    app = FastAPI()
    app.include_router(seo_migration_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_token_service] = lambda: _AlwaysExpiredSessionTokenService()
    client = TestClient(app)

    response = client.get(
        "/api/businesses/11111111-1111-1111-1111-111111111111/seo/sites/22222222-2222-2222-2222-222222222222/migration/draft-readiness",
        headers={"Authorization": "Bearer a.b.c"},
    )
    assert response.status_code == 401
    detail = response.json().get("detail") or {}
    assert detail.get("reason_code") == "session_expired"


def test_draft_readiness_endpoint_surfaces_google_reconnect_warning_without_blocking_when_live_fetch_not_required(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    def _raise_google_reconnect(self, *, site, workspace):  # noqa: ANN001
        del self, site, workspace
        raise SEOMigrationValidationError(
            "Google token refresh is required.",
            failure_category="config_missing",
            failure_reason="authentication_failed",
            error_code="google_token_expired",
        )

    monkeypatch.setattr(seo_migration_module.SEOMigrationService, "_assemble_context", _raise_google_reconnect)

    readiness_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/draft-readiness",
    )
    assert readiness_response.status_code == 200
    payload = readiness_response.json()
    assert payload.get("ready") is True
    assert payload.get("google_reconnect_required") is True
    assert payload.get("draft_context_ready") is True
    assert payload.get("live_google_data_required") is False
    assert payload.get("google_integration_ready") is False
    assert "google_reconnect_required" not in set(payload.get("blocking_reason_codes") or [])
    assert "google_reconnect_required" in set(payload.get("warning_reason_codes") or [])


def test_draft_readiness_endpoint_surfaces_context_unavailable_as_blocking(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)
    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={"source_url": "https://legacy.example"},
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    def _raise_context_error(self, *, site, workspace):  # noqa: ANN001
        del self, site, workspace
        raise RuntimeError("context assembly exploded")

    monkeypatch.setattr(seo_migration_module.SEOMigrationService, "_assemble_context", _raise_context_error)

    readiness_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/draft-readiness",
    )
    assert readiness_response.status_code == 200
    payload = readiness_response.json()
    assert payload.get("ready") is False
    assert payload.get("draft_context_ready") is False
    assert "draft_generation_context_unavailable" in set(payload.get("blocking_reason_codes") or [])


def test_draft_readiness_endpoint_warns_when_media_is_required_but_no_usable_selected_assets(
    db_session,
) -> None:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    _seed_business_and_site(db_session, business_id=business_id, site_id=site_id)
    client = _make_client(db_session, business_id=business_id)

    workspace_response = client.put(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace",
        json={
            "source_url": "https://legacy.example",
            "operator_requirements": {
                "business_objectives": ["Use real project photos and bring over existing images."],
            },
            "enriched_content_notes": {
                "replacement_summary": "Prepared replacement copy.",
            },
        },
    )
    assert workspace_response.status_code == 200
    _prepare_workspace_for_draft_generation(client, business_id=business_id, site_id=site_id)

    workspace = (
        db_session.query(SEOMigrationWorkspace)
        .filter(
            SEOMigrationWorkspace.business_id == business_id,
            SEOMigrationWorkspace.site_id == site_id,
        )
        .one()
    )
    workspace.imported_source_snapshot_json = {
        "title": "Legacy",
        "discovered_images": [
            {
                "asset_id": "srcimg-useful",
                "normalized_url": "https://legacy.example/gallery/project-1.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "useful",
            },
            {
                "asset_id": "srcimg-placeholder",
                "normalized_url": "https://legacy.example/images/transparent_placeholder.png",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "low_value",
                "quality_reason": "placeholder_image_detected",
            },
            {
                "asset_id": "srcimg-tracking",
                "normalized_url": "https://legacy.example/assets/tracking-pixel.gif",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "rejected",
                "quality_reason": "tracking_pixel_detected",
            },
        ],
    }
    workspace.operator_requirements_json = {
        "business_objectives": ["Use real project photos and bring over existing images."],
    }
    db_session.add(workspace)
    db_session.commit()

    readiness_response = client.get(
        f"/api/businesses/{business_id}/seo/sites/{site_id}/migration/draft-readiness",
    )
    assert readiness_response.status_code == 200
    payload = readiness_response.json()
    warning_codes = set(payload.get("warning_reason_codes") or [])
    assert "media_required_but_not_selected" in warning_codes
    assert payload.get("media_required_by_operator") is True
    assert payload.get("media_requirement_satisfied") is False
    assert payload.get("media_requirement_warning_reason") == "media_required_but_not_selected"
    assert payload.get("selected_usable_media_assets_count") == 0
    assert payload.get("usable_media_assets_count") == 0
    assert payload.get("useful_discovered_images_count") == 1
    assert payload.get("low_value_discovered_images_count") == 1
    assert payload.get("rejected_discovered_images_count") == 1

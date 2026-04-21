from __future__ import annotations

import json
import urllib.request

import pytest

from app.core.time import utc_now
from app.integrations.seo_migration_artifact_provider import (
    OpenAISEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactGenerationOutput,
    SEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
    SEOMigrationGeneratedFileOutput,
    SEOMigrationProviderCompatibilityResult,
)
from app.integrations.seo_migration_github_publisher import (
    MisconfiguredSEOMigrationGitHubPublisher,
    SEOMigrationGitHubActionsSecretUpsertResult,
    SEOMigrationGitHubDeployResult,
    SEOMigrationGitHubDeployRunStatusResult,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishResult,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
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
from app.repositories.business_repository import BusinessRepository
from app.repositories.github_publish_config_repository import GitHubPublishConfigRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_audit_summary_repository import SEOAuditSummaryRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_competitor_summary_repository import SEOCompetitorSummaryRepository
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_recommendation_narrative_repository import SEORecommendationNarrativeRepository
from app.repositories.seo_recommendation_repository import SEORecommendationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.seo_migration import SEOMigrationService, SEOMigrationValidationError
from app.services.seo_migration_context import SEOMigrationContextAssembler
from app.services.seo_migration_ingest import SEOMigrationSourceIngestService
from app.services.github_publish_config import GitHubPublishConfigService

_AI_DIAGNOSTICS_SUMMARY_KEYS = {
    "failure_category",
    "failure_reason",
    "failure_source",
    "retryable",
    "hint",
    "budget_outcome",
    "retry_suppressed",
    "trimming_pass_count",
    "difficulty_bucket",
    "input_size_bucket",
    "degraded_state",
}


class _StaticMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, output: SEOMigrationArtifactGenerationOutput) -> None:
        self.output = output

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        return self.output


class _RaisingMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, error: SEOMigrationArtifactProviderError) -> None:
        self.error = error

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        raise self.error


class _ExplodingMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        raise RuntimeError("boom")


class _TrackingMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, output: SEOMigrationArtifactGenerationOutput) -> None:
        self.output = output
        self.call_count = 0

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        self.call_count += 1
        return self.output


class _TimeoutCaptureMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, output: SEOMigrationArtifactGenerationOutput) -> None:
        self.output = output
        self.timeout_seconds = 1
        self.timeout_source = "default"
        self.observed_timeout_seconds: int | None = None
        self.observed_timeout_source: str | None = None

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        self.observed_timeout_seconds = int(self.timeout_seconds)
        self.observed_timeout_source = str(self.timeout_source)
        return self.output


class _CompatibilityTrackingMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(
        self,
        *,
        compatibility: SEOMigrationProviderCompatibilityResult,
        output: SEOMigrationArtifactGenerationOutput,
    ) -> None:
        self.compatibility = compatibility
        self.output = output
        self.call_count = 0

    def evaluate_compatibility(self) -> SEOMigrationProviderCompatibilityResult:
        return self.compatibility

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        self.call_count += 1
        return self.output


class _RecordingGitHubPublisher(SEOMigrationGitHubPublisher):
    def __init__(
        self,
        *,
        fail_publish: bool = False,
        fail_deploy: bool = False,
        deploy_live_url: str | None = None,
        deploy_workflow_output: dict[str, str] | None = None,
        deploy_workflow_run_id: int | None = None,
        deploy_workflow_run_status: str | None = None,
        deploy_workflow_run_conclusion: str | None = None,
        deploy_workflow_run_failure_reason_code: str | None = None,
        deploy_workflow_run_failure_stage: str | None = None,
        deploy_workflow_run_failure_step: str | None = None,
        refresh_workflow_output: dict[str, str] | None = None,
        refresh_workflow_run_id: int | None = None,
        refresh_workflow_run_status: str | None = None,
        refresh_workflow_run_conclusion: str | None = None,
        refresh_workflow_run_failure_reason_code: str | None = None,
        refresh_workflow_run_failure_stage: str | None = None,
        refresh_workflow_run_failure_step: str | None = None,
        lookup_workflow_run_id: int | None = None,
        lookup_workflow_run_status: str | None = None,
        lookup_workflow_run_conclusion: str | None = None,
        lookup_workflow_output: dict[str, str] | None = None,
        lookup_workflow_run_failure_reason_code: str | None = None,
        lookup_workflow_run_failure_stage: str | None = None,
        lookup_workflow_run_failure_step: str | None = None,
        fail_lookup: bool = False,
        lookup_error_code: str | None = None,
        lookup_error_message: str | None = None,
        lookup_error_stage: str | None = None,
        fail_refresh: bool = False,
        refresh_error_code: str | None = None,
        refresh_error_message: str | None = None,
        refresh_error_stage: str | None = None,
        deploy_error_code: str | None = None,
        deploy_error_message: str | None = None,
        deploy_error_stage: str | None = None,
        fail_workflow_provision: bool = False,
        existing_workflow: bool = False,
        existing_workflow_placeholder: bool = False,
        existing_workflow_custom: bool = False,
        readiness_workflow_dispatch_supported: bool = True,
        readiness_workflow_trigger_types: tuple[str, ...] | None = None,
        readiness_dispatch_service_availability: bool = True,
        readiness_dispatch_service_reason_code: str | None = "available",
        readiness_dispatch_identifier_type: str | None = None,
        readiness_workflow_conformance_checked: bool = True,
        readiness_workflow_conformance_status: str = "conformant",
        readiness_workflow_conformance_reasons: tuple[str, ...] | None = None,
        readiness_workflow_conformance_evidence_summary: str | None = "managed_contract_markers_present",
        available_workflow_paths: set[str] | None = None,
        non_dispatchable_workflow_paths: set[str] | None = None,
        non_production_ready_workflow_paths: set[str] | None = None,
        fail_secret_propagation: bool = False,
        secret_propagation_error_code: str | None = None,
        secret_propagation_error_message: str | None = None,
        secret_propagation_error_stage: str | None = None,
        existing_deploy_secret: bool = False,
    ) -> None:
        self.fail_publish = fail_publish
        self.fail_deploy = fail_deploy
        self.deploy_live_url = deploy_live_url
        self.deploy_workflow_output = dict(deploy_workflow_output or {})
        self.deploy_workflow_run_id = deploy_workflow_run_id
        self.deploy_workflow_run_status = deploy_workflow_run_status
        self.deploy_workflow_run_conclusion = deploy_workflow_run_conclusion
        self.deploy_workflow_run_failure_reason_code = deploy_workflow_run_failure_reason_code
        self.deploy_workflow_run_failure_stage = deploy_workflow_run_failure_stage
        self.deploy_workflow_run_failure_step = deploy_workflow_run_failure_step
        self.refresh_workflow_output = dict(refresh_workflow_output or {})
        self.refresh_workflow_run_id = refresh_workflow_run_id
        self.refresh_workflow_run_status = refresh_workflow_run_status
        self.refresh_workflow_run_conclusion = refresh_workflow_run_conclusion
        self.refresh_workflow_run_failure_reason_code = refresh_workflow_run_failure_reason_code
        self.refresh_workflow_run_failure_stage = refresh_workflow_run_failure_stage
        self.refresh_workflow_run_failure_step = refresh_workflow_run_failure_step
        self.lookup_workflow_run_id = lookup_workflow_run_id
        self.lookup_workflow_run_status = lookup_workflow_run_status
        self.lookup_workflow_run_conclusion = lookup_workflow_run_conclusion
        self.lookup_workflow_output = dict(lookup_workflow_output or {})
        self.lookup_workflow_run_failure_reason_code = lookup_workflow_run_failure_reason_code
        self.lookup_workflow_run_failure_stage = lookup_workflow_run_failure_stage
        self.lookup_workflow_run_failure_step = lookup_workflow_run_failure_step
        self.fail_lookup = fail_lookup
        self.lookup_error_code = lookup_error_code
        self.lookup_error_message = lookup_error_message
        self.lookup_error_stage = lookup_error_stage
        self.fail_refresh = fail_refresh
        self.refresh_error_code = refresh_error_code
        self.refresh_error_message = refresh_error_message
        self.refresh_error_stage = refresh_error_stage
        self.deploy_error_code = deploy_error_code
        self.deploy_error_message = deploy_error_message
        self.deploy_error_stage = deploy_error_stage
        self.fail_workflow_provision = fail_workflow_provision
        self.existing_workflow = existing_workflow
        self.existing_workflow_placeholder = existing_workflow_placeholder
        self.existing_workflow_custom = existing_workflow_custom
        self.readiness_workflow_dispatch_supported = readiness_workflow_dispatch_supported
        self.readiness_workflow_trigger_types = readiness_workflow_trigger_types or ("workflow_dispatch",)
        self.readiness_dispatch_service_availability = readiness_dispatch_service_availability
        self.readiness_dispatch_service_reason_code = readiness_dispatch_service_reason_code
        self.readiness_dispatch_identifier_type = readiness_dispatch_identifier_type
        self.readiness_workflow_conformance_checked = readiness_workflow_conformance_checked
        self.readiness_workflow_conformance_status = readiness_workflow_conformance_status
        self.readiness_workflow_conformance_reasons = readiness_workflow_conformance_reasons or ()
        self.readiness_workflow_conformance_evidence_summary = readiness_workflow_conformance_evidence_summary
        self.available_workflow_paths = (
            {str(item).strip() for item in available_workflow_paths if str(item).strip()}
            if available_workflow_paths is not None
            else None
        )
        self.non_dispatchable_workflow_paths = (
            {str(item).strip() for item in non_dispatchable_workflow_paths if str(item).strip()}
            if non_dispatchable_workflow_paths is not None
            else set()
        )
        self.non_production_ready_workflow_paths = (
            {str(item).strip() for item in non_production_ready_workflow_paths if str(item).strip()}
            if non_production_ready_workflow_paths is not None
            else set()
        )
        self.fail_secret_propagation = fail_secret_propagation
        self.secret_propagation_error_code = secret_propagation_error_code
        self.secret_propagation_error_message = secret_propagation_error_message
        self.secret_propagation_error_stage = secret_propagation_error_stage
        self.existing_deploy_secret = existing_deploy_secret
        self.publish_calls: list[
            tuple[SEOMigrationGitHubPublishTarget, list[SEOMigrationGitHubPublishFile], str, bool]
        ] = []
        self.deploy_calls: list[tuple[SEOMigrationGitHubDeployTarget, bool]] = []
        self.deploy_managed_gke_configs: list[dict[str, object] | None] = []
        self.refresh_calls: list[tuple[SEOMigrationGitHubDeployTarget, int, str | None]] = []
        self.lookup_calls: list[tuple[SEOMigrationGitHubDeployTarget, str | None]] = []
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

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        self.publish_calls.append((target, list(files), commit_message, dry_run))
        if self.fail_publish:
            raise SEOMigrationGitHubPublisherError(
                code="publish_failed",
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
        if self.fail_secret_propagation:
            raise SEOMigrationGitHubPublisherError(
                code=self.secret_propagation_error_code or "github_request_failed",
                safe_message=self.secret_propagation_error_message or "Simulated deploy secret propagation failure.",
                stage=self.secret_propagation_error_stage or "secret_propagation",
            )
        action = "updated" if self.existing_deploy_secret else "created"
        self.existing_deploy_secret = True
        return SEOMigrationGitHubActionsSecretUpsertResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            secret_name=secret_name,
            action=action,
            updated_at="2026-04-07T12:01:00+00:00",
        )

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        self.deploy_managed_gke_configs.append(dict(managed_gke_config or {}) or None)
        self.deploy_calls.append((target, dry_run))
        if self.fail_deploy:
            raise SEOMigrationGitHubPublisherError(
                code=self.deploy_error_code or "deploy_failed",
                safe_message=self.deploy_error_message or "Simulated deploy failure.",
                stage=self.deploy_error_stage,
            )
        return SEOMigrationGitHubDeployResult(
            dry_run=dry_run,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            inputs=dict(target.inputs),
            dispatched_at="2026-04-07T12:05:00+00:00",
            live_url=self.deploy_live_url,
            workflow_output=dict(self.deploy_workflow_output),
            workflow_run_id=self.deploy_workflow_run_id,
            workflow_run_status=self.deploy_workflow_run_status,
            workflow_run_conclusion=self.deploy_workflow_run_conclusion,
            workflow_run_failure_reason_code=self.deploy_workflow_run_failure_reason_code,
            workflow_run_failure_stage=self.deploy_workflow_run_failure_stage,
            workflow_run_failure_step=self.deploy_workflow_run_failure_step,
        )

    def refresh_deploy_run_status(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult:
        self.refresh_calls.append((target, workflow_run_id, dispatched_at))
        if self.fail_refresh:
            raise SEOMigrationGitHubPublisherError(
                code=self.refresh_error_code or "workflow_not_found",
                safe_message=self.refresh_error_message or "Simulated deploy status refresh failure.",
                stage=self.refresh_error_stage or "workflow_run_lookup",
            )
        return SEOMigrationGitHubDeployRunStatusResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            workflow_run_id=self.refresh_workflow_run_id or workflow_run_id,
            workflow_run_status=self.refresh_workflow_run_status,
            workflow_run_conclusion=self.refresh_workflow_run_conclusion,
            workflow_output=dict(self.refresh_workflow_output),
            workflow_run_failure_reason_code=self.refresh_workflow_run_failure_reason_code,
            workflow_run_failure_stage=self.refresh_workflow_run_failure_stage,
            workflow_run_failure_step=self.refresh_workflow_run_failure_step,
            refreshed_at="2026-04-07T12:15:00+00:00",
        )

    def lookup_deploy_run_status_after_dispatch(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult | None:
        self.lookup_calls.append((target, dispatched_at))
        if self.fail_lookup:
            raise SEOMigrationGitHubPublisherError(
                code=self.lookup_error_code or "workflow_not_found",
                safe_message=self.lookup_error_message or "Simulated workflow run lookup failure.",
                stage=self.lookup_error_stage or "workflow_run_lookup",
            )
        if self.lookup_workflow_run_id is None:
            return None
        return SEOMigrationGitHubDeployRunStatusResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            workflow_run_id=self.lookup_workflow_run_id,
            workflow_run_status=self.lookup_workflow_run_status,
            workflow_run_conclusion=self.lookup_workflow_run_conclusion,
            workflow_output=dict(self.lookup_workflow_output),
            workflow_run_failure_reason_code=self.lookup_workflow_run_failure_reason_code,
            workflow_run_failure_stage=self.lookup_workflow_run_failure_stage,
            workflow_run_failure_step=self.lookup_workflow_run_failure_step,
            refreshed_at="2026-04-07T12:15:00+00:00",
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
            )
        )
        if self.fail_workflow_provision:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_provision_failed",
                safe_message="Simulated workflow provisioning failure.",
            )
        provisioned = (not dry_run) and (not self.existing_workflow or self.existing_workflow_placeholder)
        managed_workflow_outcome: str | None = None
        if provisioned:
            if self.existing_workflow_placeholder:
                managed_workflow_outcome = "managed_workflow_upgraded"
            else:
                managed_workflow_outcome = "managed_workflow_created"
        else:
            if self.existing_workflow_custom:
                managed_workflow_outcome = "managed_workflow_preserved_custom"
            else:
                managed_workflow_outcome = "managed_workflow_already_current"
        commit_sha = "wf123" if provisioned else None
        if provisioned:
            self.existing_workflow = True
            self.existing_workflow_placeholder = False
            self.existing_workflow_custom = False
        return SEOMigrationGitHubWorkflowProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            workflow_id=workflow_id,
            workflow_path=f".github/workflows/{workflow_id}",
            provisioned=provisioned,
            commit_sha=commit_sha,
            deploy_workflow_mode=deploy_workflow_mode,
            target_environment_key=target_environment_key,
            target_environment_source=target_environment_source,
            managed_workflow_outcome=managed_workflow_outcome,
        )

    def check_deploy_target_readiness(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        allow_ref_repair: bool = False,
        allow_workflow_repair: bool = False,
        dry_run: bool = False,
        managed_gke_config: dict[str, object] | None = None,
        namespace_isolation_defaults: dict[str, object] | None = None,
        remediation_mode: str = "none",
    ) -> SEOMigrationGitHubTargetReadinessResult:
        del allow_ref_repair, allow_workflow_repair, dry_run, managed_gke_config, namespace_isolation_defaults
        workflow_path = (
            target.workflow_id
            if str(target.workflow_id or "").startswith(".github/workflows/")
            else f".github/workflows/{target.workflow_id}"
        )
        if self.available_workflow_paths is not None and workflow_path not in self.available_workflow_paths:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_found",
                safe_message="GitHub workflow target was not found.",
                stage="workflow_lookup",
            )
        if workflow_path in self.non_dispatchable_workflow_paths:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_dispatchable",
                safe_message="GitHub workflow is not dispatchable for the deploy target.",
                stage="workflow_lookup",
            )
        if workflow_path in self.non_production_ready_workflow_paths:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_production_ready",
                safe_message="GitHub workflow target is scaffold-only and not production-ready for deploy execution.",
                stage="workflow_lookup",
            )
        dispatch_identifier_type = self.readiness_dispatch_identifier_type or (
            "workflow_file_path" if workflow_path == target.workflow_id else "workflow_id"
        )
        return SEOMigrationGitHubTargetReadinessResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            requested_ref=target.ref,
            resolved_ref=target.ref,
            ref_source="requested",
            workflow_id=target.workflow_id,
            workflow_path=workflow_path,
            repo_exists=True,
            ref_exists=True,
            workflow_exists=True,
            workflow_dispatch_ready=True,
            workflow_dispatch_supported=self.readiness_workflow_dispatch_supported,
            workflow_trigger_types=tuple(self.readiness_workflow_trigger_types),
            dispatch_service_availability=self.readiness_dispatch_service_availability,
            dispatch_service_reason_code=self.readiness_dispatch_service_reason_code,
            dispatch_identifier_type=dispatch_identifier_type,
            remediation_mode=remediation_mode.strip() or "none",
            workflow_conformance_checked=self.readiness_workflow_conformance_checked,
            workflow_conformance_status=self.readiness_workflow_conformance_status,
            workflow_conformance_reasons=tuple(self.readiness_workflow_conformance_reasons),
            workflow_conformance_evidence_summary=self.readiness_workflow_conformance_evidence_summary,
        )


def _seed_business_and_site(db_session, *, ga_measurement_id: str | None = None) -> tuple[str, str]:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
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
        ga4_measurement_id=ga_measurement_id,
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
    return business_id, site_id


def _build_service(
    db_session,
    provider: SEOMigrationArtifactGenerationProvider,
    *,
    github_publisher: SEOMigrationGitHubPublisher | None = None,
    env_default_model_name: str | None = None,
    deploy_secret_gcp_key: str | None = "{\"type\":\"service_account\"}",
) -> SEOMigrationService:
    github_publish_config_service = GitHubPublishConfigService(
        session=db_session,
        repository=GitHubPublishConfigRepository(db_session),
    )
    return SEOMigrationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_migration_repository=SEOMigrationRepository(db_session),
        seo_audit_repository=SEOAuditRepository(db_session),
        seo_audit_summary_repository=SEOAuditSummaryRepository(db_session),
        seo_recommendation_repository=SEORecommendationRepository(db_session),
        seo_recommendation_narrative_repository=SEORecommendationNarrativeRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_summary_repository=SEOCompetitorSummaryRepository(db_session),
        ingest_service=SEOMigrationSourceIngestService(),
        context_assembler=SEOMigrationContextAssembler(),
        artifact_provider=provider,
        github_publisher=github_publisher,
        github_publish_config_service=github_publish_config_service,
        provider_name="mock",
        provider_model_name="mock-seo-migration-v1",
        env_default_model_name=env_default_model_name,
        deploy_secret_gcp_key=deploy_secret_gcp_key,
    )


def _seed_workspace(service: SEOMigrationService, *, business_id: str, site_id: str) -> None:
    service.create_or_update_workspace(
        business_id=business_id,
        site_id=site_id,
        source_url="https://legacy.example/",
        operator_requirements={"business_objectives": ["Replace legacy site"]},
        enriched_content_notes={"replacement_summary": "Use richer replacement content."},
        publish_config={"target_repo": "org/repo"},
        deploy_config={"target_cluster": "gke-prod"},
        principal_id="principal-1",
    )
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)


def _mark_workspace_ingested(service: SEOMigrationService, *, business_id: str, site_id: str) -> None:
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.source_site_status = "ingested"
    workspace.imported_source_snapshot_json = {
        "title": "Legacy Site",
        "fetched_at": utc_now().isoformat(),
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()


def _seed_reused_context_records(db_session, *, business_id: str, site_id: str) -> None:
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
        rule_key="readiness-rule",
        category="SEO",
        severity="WARNING",
        title="Improve content specificity",
        rationale="Legacy copy is too thin.",
        priority_score=70,
        priority_band="high",
        effort_bucket="small",
        status="open",
    )
    competitor_set = SEOCompetitorSet(
        id="competitor-set-readiness-1",
        business_id=business_id,
        site_id=site_id,
        name="Primary competitors",
        is_active=True,
        created_by_principal_id="principal-1",
    )
    snapshot_run = SEOCompetitorSnapshotRun(
        id="snapshot-run-readiness-1",
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
        id="comparison-run-readiness-1",
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
    db_session.add_all([audit_run, recommendation_run, recommendation, competitor_set, snapshot_run, comparison_run])
    db_session.commit()


def _build_publishable_output(*, index_content: str | None = None) -> SEOMigrationArtifactGenerationOutput:
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
                or "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body><h1>Draft</h1></body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="styles.css",
                media_type="text/css",
                content="body { color: #111; }",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )


def _configure_publish_target(
    service: SEOMigrationService,
    *,
    business_id: str,
    site_id: str,
    artifact_root: str = "",
) -> None:
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": artifact_root,
        },
        principal_id="principal-1",
    )


def _configure_deploy_target(
    service: SEOMigrationService,
    *,
    business_id: str,
    site_id: str,
    workflow_id: str = "deploy-www-prod.yml",
) -> None:
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": workflow_id,
            "ref": "main",
        },
        principal_id="principal-1",
    )


def test_update_deploy_config_rejects_operator_updates_to_admin_owned_fields(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-tnmfire-www-prod.yml",
            "ref": "main",
        },
        deploy_config_field_names={"enabled", "workflow_id", "ref"},
        principal_id="admin-principal",
        principal_role=PrincipalRole.ADMIN,
    )

    with pytest.raises(
        SEOMigrationValidationError,
        match="Only admin principals can update deploy repository/workflow controls.",
    ):
        service.update_deploy_config(
            business_id=business_id,
            site_id=site_id,
            deploy_config={"workflow_id": "deploy-other.yml"},
            deploy_config_field_names={"workflow_id"},
            principal_id="operator-principal",
            principal_role=PrincipalRole.OPERATOR,
        )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert isinstance(workspace.deploy_config_json, dict)
    assert workspace.deploy_config_json.get("workflow_id") == "deploy-tnmfire-www-prod.yml"


def test_update_deploy_config_allows_operator_to_toggle_enabled_only(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": False,
            "workflow_id": "deploy-tnmfire-www-prod.yml",
            "ref": "main",
        },
        deploy_config_field_names={"enabled", "workflow_id", "ref"},
        principal_id="admin-principal",
        principal_role=PrincipalRole.ADMIN,
    )

    workspace = service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={"enabled": True},
        deploy_config_field_names={"enabled"},
        principal_id="operator-principal",
        principal_role=PrincipalRole.OPERATOR,
    )
    assert isinstance(workspace.deploy_config_json, dict)
    assert workspace.deploy_config_json.get("enabled") is True
    assert workspace.deploy_config_json.get("workflow_id") == "deploy-tnmfire-www-prod.yml"
    assert workspace.deploy_config_json.get("ref") == "main"


def test_generate_artifacts_applies_guardrails_and_analytics_normalization(db_session) -> None:
    output = SEOMigrationArtifactGenerationOutput(
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
                content=(
                    "<html><head><script>gtag('config','G-ABCD1234');</script></head>"
                    "<body><h1>Draft</h1></body></html>"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="styles.css",
                media_type="text/css",
                content="body { color: #111; }",
            ),
            SEOMigrationGeneratedFileOutput(
                path="app/main.py",
                media_type="text/plain",
                content="print('forbidden')",
            ),
            SEOMigrationGeneratedFileOutput(
                path="../escape.html",
                media_type="text/html",
                content="<html></html>",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "partial"
    assert artifact.file_count == 2
    files = artifact.generated_files_json or []
    paths = {str(item["path"]) for item in files if isinstance(item, dict)}
    assert paths == {"index.html", "styles.css"}
    index_file = next(item for item in files if item["path"] == "index.html")
    index_content = str(index_file["content"])
    assert "<!-- ANALYTICS_PLACEHOLDER -->" in index_content
    assert "gtag(" not in index_content
    warnings = artifact.parse_warnings_json or []
    assert any("forbidden generated path" in warning for warning in warnings)
    assert any("invalid path" in warning for warning in warnings)
    quality = artifact.artifact_quality_evaluation_json
    assert isinstance(quality, dict)
    assert artifact.artifact_quality_evaluation == quality
    assert quality.get("quality_status") in {"medium", "low", "high"}
    assert isinstance(quality.get("operator_summary"), str)
    signals = quality.get("signals")
    assert isinstance(signals, dict)
    assert signals.get("required_files_present") is True


def test_draft_generation_readiness_ready_with_all_core_and_reused_context_signals(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)
    _seed_reused_context_records(db_session, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = (summary.context_summary or {}).get("draft_generation_readiness")
    assert isinstance(readiness, dict)
    assert readiness.get("status") == "ready"
    assert readiness.get("hard_blocked") is False
    assert readiness.get("score") == 100
    assert readiness.get("summary") == "Ready to generate draft."
    signals = readiness.get("signals")
    assert isinstance(signals, dict)
    assert signals.get("source_site_ingested") is True
    assert signals.get("operator_requirements_present") is True
    assert signals.get("enriched_content_present") is True
    assert signals.get("audit_available") is True
    assert signals.get("recommendations_available") is True
    assert signals.get("competitors_available") is True
    top_state = (summary.context_summary or {}).get("draft_generation_state")
    assert isinstance(top_state, dict)
    assert top_state.get("status") == "ready"
    assert top_state.get("summary") == "Ready to generate draft."


def test_draft_generation_readiness_missing_operator_requirements_is_blocking(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    service.create_or_update_workspace(
        business_id=business_id,
        site_id=site_id,
        source_url="https://legacy.example/",
        operator_requirements={},
        enriched_content_notes={"replacement_summary": "Prepared content."},
        principal_id="principal-1",
    )
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = (summary.context_summary or {}).get("draft_generation_readiness")
    assert isinstance(readiness, dict)
    assert readiness.get("status") == "not_ready"
    assert readiness.get("hard_blocked") is True
    reasons = readiness.get("reasons") or []
    assert any(
        isinstance(item, dict)
        and item.get("code") == "operator_requirements_required"
        and item.get("severity") == "blocking"
        for item in reasons
    )


def test_draft_generation_readiness_missing_enriched_content_is_blocking(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    service.create_or_update_workspace(
        business_id=business_id,
        site_id=site_id,
        source_url="https://legacy.example/",
        operator_requirements={"business_objectives": ["Replace weak source pages"]},
        enriched_content_notes={},
        principal_id="principal-1",
    )
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = (summary.context_summary or {}).get("draft_generation_readiness")
    assert isinstance(readiness, dict)
    assert readiness.get("status") == "not_ready"
    assert readiness.get("hard_blocked") is True
    reasons = readiness.get("reasons") or []
    assert any(
        isinstance(item, dict)
        and item.get("code") == "enriched_content_required"
        and item.get("severity") == "blocking"
        for item in reasons
    )


def test_draft_generation_readiness_missing_reused_context_is_warning_only(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = (summary.context_summary or {}).get("draft_generation_readiness")
    assert isinstance(readiness, dict)
    assert readiness.get("status") == "ready_with_warnings"
    assert readiness.get("hard_blocked") is False
    reasons = readiness.get("reasons") or []
    warning_codes = {
        item.get("code") for item in reasons if isinstance(item, dict) and item.get("severity") == "warning"
    }
    assert "audit_context_unavailable" in warning_codes
    assert "recommendations_context_unavailable" in warning_codes
    assert "competitors_context_unavailable" in warning_codes


def test_generate_artifacts_is_blocked_by_readiness_before_provider_call(db_session) -> None:
    tracking_provider = _TrackingMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, tracking_provider)
    business_id, site_id = _seed_business_and_site(db_session)
    service.create_or_update_workspace(
        business_id=business_id,
        site_id=site_id,
        source_url="https://legacy.example/",
        operator_requirements={},
        enriched_content_notes={"replacement_summary": "Prepared content."},
        principal_id="principal-1",
    )
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError, match="Not ready yet"):
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    assert tracking_provider.call_count == 0
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    top_state = (summary.context_summary or {}).get("draft_generation_state")
    assert isinstance(top_state, dict)
    assert top_state.get("status") == "blocked_by_workspace"
    assert "Not ready yet" in str(top_state.get("summary") or "")


def test_draft_generation_readiness_emits_structured_log(db_session, caplog) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    service.get_workspace_summary(business_id=business_id, site_id=site_id)
    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_readiness_evaluation"
    ]
    assert payloads
    latest = payloads[-1]
    assert latest.get("business_id") == business_id
    assert latest.get("site_id") == site_id
    assert latest.get("workspace_id")
    assert latest.get("readiness_status") in {"ready", "ready_with_warnings", "not_ready"}
    assert isinstance(latest.get("readiness_score"), int)
    assert isinstance(latest.get("hard_blocked"), bool)
    assert isinstance(latest.get("blocking_reason_codes"), list)
    assert isinstance(latest.get("warning_reason_codes"), list)


def test_generate_artifacts_is_blocked_by_provider_compatibility_before_provider_call(db_session) -> None:
    provider = _CompatibilityTrackingMigrationProvider(
        compatibility=SEOMigrationProviderCompatibilityResult(
            supported=False,
            reason_code="unsupported_model_configuration",
            operator_message="This model/provider setup is not compatible with the current migration request settings.",
            admin_summary="model_or_response_format_incompatible",
            retryable=False,
            provider_name="openai",
            model_name="text-embedding-3-small",
            endpoint_path="/chat/completions",
            execution_mode="full",
            web_search_enabled=False,
            degraded_mode=False,
            response_format_mode="json_schema",
        ),
        output=_build_publishable_output(),
    )
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert error.failure_category == "config_missing"
    assert error.failure_reason == "unsupported_configuration"
    assert error.error_code == "unsupported_model_configuration"
    assert error.retryable is False
    assert provider.call_count == 0

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert workspace.migration_status == "draft_generation_failed"
    assert workspace.latest_generated_artifact_version_id
    artifact = service.get_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=workspace.latest_generated_artifact_version_id or "",
    )
    assert artifact.status == "failed"
    assert artifact.error_summary == (
        "This model/provider setup is not compatible with the current migration request settings."
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_failure_category") == "config_missing"
    assert diagnostics.get("last_draft_failure_reason") == "unsupported_configuration"
    assert diagnostics.get("last_draft_failure_code") == "unsupported_model_configuration"
    compatibility = (summary.context_summary or {}).get("draft_provider_compatibility") or {}
    assert compatibility.get("supported") is False
    assert compatibility.get("reason_code") == "unsupported_model_configuration"
    assert compatibility.get("execution_mode") == "full"
    top_state = (summary.context_summary or {}).get("draft_generation_state") or {}
    assert top_state.get("status") == "blocked_by_provider"
    assert "not compatible" in str(top_state.get("summary") or "").lower()


def test_generate_artifacts_blocks_known_unsupported_openai_fallback_request_shape_before_provider_call(
    db_session,
    monkeypatch,
    caplog,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-4o-mini",
        timeout_seconds=5,
    )
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    outbound_call_count = {"count": 0}

    def _unexpected_urlopen(request, timeout):  # noqa: ANN001
        del request, timeout
        outbound_call_count["count"] += 1
        raise AssertionError("migration draft generation should be blocked before provider call")

    monkeypatch.setattr(urllib.request, "urlopen", _unexpected_urlopen)
    caplog.set_level("INFO", logger="app.services.seo_migration")
    caplog.set_level("INFO", logger="app.integrations.seo_migration_artifact_provider")

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert error.failure_category == "config_missing"
    assert error.failure_reason == "unsupported_configuration"
    assert error.error_code == "unsupported_request_shape"
    assert error.retryable is False
    assert outbound_call_count["count"] == 0

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_failure_reason") == "unsupported_configuration"
    assert diagnostics.get("last_draft_failure_code") == "unsupported_request_shape"
    assert diagnostics.get("last_draft_failure_endpoint_path") == "/chat/completions"
    assert diagnostics.get("last_draft_failure_execution_mode") == "full"
    assert diagnostics.get("last_draft_failure_response_format_mode") == "json_schema"
    assert diagnostics.get("last_draft_failure_source") == "local_preflight"
    assert diagnostics.get("last_draft_failure_model_requested") is None
    assert diagnostics.get("last_draft_failure_model_resolved") == "gpt-4o-mini"
    assert diagnostics.get("last_draft_failure_model_used") == "gpt-4o-mini"
    assert "unsupported_request_shape" in str(diagnostics.get("draft_provider_compatibility_admin_summary") or "")
    ai_execution = (summary.context_summary or {}).get("ai_execution") or {}
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
    compatibility = (summary.context_summary or {}).get("draft_provider_compatibility") or {}
    assert compatibility.get("supported") is False
    assert compatibility.get("reason_code") == "unsupported_request_shape"
    assert compatibility.get("model_name") == "gpt-4o-mini"
    assert compatibility.get("endpoint_path") == "/chat/completions"
    assert compatibility.get("response_format_mode") == "json_schema"
    top_state = (summary.context_summary or {}).get("draft_generation_state") or {}
    assert top_state.get("status") == "blocked_by_provider"

    compatibility_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_provider_compatibility_evaluation"
    ]
    assert compatibility_logs
    latest_compatibility_log = compatibility_logs[-1]
    assert latest_compatibility_log.get("supported") is False
    assert latest_compatibility_log.get("reason_code") == "unsupported_request_shape"
    assert latest_compatibility_log.get("decision") == "blocked_local_preflight"

    request_start_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_draft_provider_request_start"
    ]
    assert request_start_logs == []


def test_migration_model_resolution_prefers_business_default_over_env_default(db_session) -> None:
    provider = _TrackingMigrationProvider(_build_publishable_output())
    provider.model_name = "mock-provider-fallback"
    service = _build_service(
        db_session,
        provider,
        env_default_model_name="gpt-env-default",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    business = db_session.get(Business, business_id)
    assert business is not None
    business.default_ai_model = "gpt-admin-default"
    db_session.commit()
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    preview = service.get_prompt_preview(business_id=business_id, site_id=site_id)

    assert preview.model_name == "gpt-admin-default"
    assert provider.model_name == "gpt-admin-default"


def test_migration_model_resolution_uses_env_default_when_business_default_missing(db_session) -> None:
    provider = _TrackingMigrationProvider(_build_publishable_output())
    provider.model_name = "mock-provider-fallback"
    service = _build_service(
        db_session,
        provider,
        env_default_model_name="gpt-env-default",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    preview = service.get_prompt_preview(business_id=business_id, site_id=site_id)

    assert preview.model_name == "gpt-env-default"
    assert provider.model_name == "gpt-env-default"


def test_generate_artifacts_uses_default_migration_timeout_when_admin_setting_is_unset(db_session) -> None:
    provider = _TimeoutCaptureMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "completed"
    assert provider.observed_timeout_seconds == 120
    assert provider.observed_timeout_source == "default"
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("draft_timeout_seconds") == 120
    assert diagnostics.get("draft_timeout_source") == "default"
    ai_execution = (summary.context_summary or {}).get("ai_execution") or {}
    assert ai_execution.get("timeout_seconds") == 120
    assert ai_execution.get("timeout_source") == "default"


def test_generate_artifacts_uses_admin_configured_migration_timeout(db_session) -> None:
    provider = _TimeoutCaptureMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    business = db_session.get(Business, business_id)
    assert business is not None
    business.migration_draft_timeout_seconds = 180
    db_session.commit()
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "completed"
    assert provider.observed_timeout_seconds == 180
    assert provider.observed_timeout_source == "admin"
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("draft_timeout_seconds") == 180
    assert diagnostics.get("draft_timeout_source") == "admin"
    ai_execution = (summary.context_summary or {}).get("ai_execution") or {}
    assert ai_execution.get("timeout_seconds") == 180
    assert ai_execution.get("timeout_source") == "admin"


def test_generate_artifacts_uses_default_timeout_when_admin_timeout_is_below_safe_floor(db_session) -> None:
    provider = _TimeoutCaptureMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    business = db_session.get(Business, business_id)
    assert business is not None
    business.migration_draft_timeout_seconds = 45
    db_session.commit()
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "completed"
    assert provider.observed_timeout_seconds == 120
    assert provider.observed_timeout_source == "default"
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("draft_timeout_seconds") == 120
    assert diagnostics.get("draft_timeout_source") == "default"
    ai_execution = (summary.context_summary or {}).get("ai_execution") or {}
    assert ai_execution.get("timeout_seconds") == 120
    assert ai_execution.get("timeout_source") == "default"


def test_generate_artifacts_blocks_unsupported_shape_when_admin_default_model_is_incompatible(
    db_session,
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    service = _build_service(
        db_session,
        provider,
        env_default_model_name="gpt-5.1",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    business = db_session.get(Business, business_id)
    assert business is not None
    business.default_ai_model = "gpt-4o-mini"
    db_session.commit()
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    outbound_call_count = {"count": 0}

    def _unexpected_urlopen(request, timeout):  # noqa: ANN001
        del request, timeout
        outbound_call_count["count"] += 1
        raise AssertionError("migration draft generation should be blocked before provider call")

    monkeypatch.setattr(urllib.request, "urlopen", _unexpected_urlopen)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert error.failure_category == "config_missing"
    assert error.failure_reason == "unsupported_configuration"
    assert error.error_code == "unsupported_request_shape"
    assert outbound_call_count["count"] == 0

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    compatibility = (summary.context_summary or {}).get("draft_provider_compatibility") or {}
    assert compatibility.get("supported") is False
    assert compatibility.get("reason_code") == "unsupported_request_shape"
    assert compatibility.get("model_name") == "gpt-4o-mini"
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("last_draft_failure_source") == "local_preflight"
    assert diagnostics.get("last_draft_failure_model_requested") is None
    assert diagnostics.get("last_draft_failure_model_resolved") == "gpt-4o-mini"
    assert diagnostics.get("last_draft_failure_model_used") == "gpt-4o-mini"


def test_generate_artifacts_allows_supported_openai_gpt_5_1_shape_and_calls_provider(
    db_session,
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    service = _build_service(
        db_session,
        provider,
        env_default_model_name="gpt-5.1",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    outbound_call_count = {"count": 0}

    class _FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")
            self.headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def read(self) -> bytes:
            return self._body

    def _valid_urlopen(request, timeout):  # noqa: ANN001
        del timeout
        outbound_call_count["count"] += 1
        body = json.loads(request.data.decode("utf-8"))
        assert body.get("model") == "gpt-5.1"
        assert isinstance(body.get("input"), str)
        assert "System Instructions:" in str(body.get("input"))
        assert "User Request:" in str(body.get("input"))
        assert isinstance((body.get("text") or {}).get("format"), dict)
        return _FakeResponse(
            json.dumps(
                {
                    "model": "gpt-5.1",
                    "output_text": json.dumps(
                        {
                            "strategy_summary": "Draft strategy",
                            "page_map": [{"path": "/", "title": "Home"}],
                            "homepage_structure": [],
                            "service_page_suggestions": [],
                            "cta_contact_structure": {},
                            "seo_meta_suggestions": {},
                            "redirect_suggestions": [],
                            "analytics_placeholders": [],
                            "generated_files": [
                                {
                                    "path": "index.html",
                                    "media_type": "text/html",
                                    "content": "<html><body>Draft</body></html>",
                                }
                            ],
                        },
                        ensure_ascii=True,
                    ),
                },
                ensure_ascii=True,
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert outbound_call_count["count"] == 1
    assert artifact.status == "completed"
    assert artifact.model_name == "gpt-5.1"
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    compatibility = (summary.context_summary or {}).get("draft_provider_compatibility") or {}
    assert compatibility.get("supported") is True
    assert compatibility.get("model_name") == "gpt-5.1"
    assert compatibility.get("endpoint_path") == "/responses"
    assert compatibility.get("response_format_mode") == "json_schema"
    assert compatibility.get("request_body_mode") == "responses_text_format_json_schema"
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("draft_model_requested") is None
    assert diagnostics.get("draft_model_resolved") == "gpt-5.1"
    assert diagnostics.get("draft_model_used") == "gpt-5.1"
    ai_execution = (summary.context_summary or {}).get("ai_execution") or {}
    assert ai_execution.get("model_requested") is None
    assert ai_execution.get("model_resolved") == "gpt-5.1"
    assert ai_execution.get("model_used") == "gpt-5.1"
    assert ai_execution.get("endpoint_path") == "/responses"
    assert ai_execution.get("request_body_mode") == "responses_text_format_json_schema"
    assert ai_execution.get("compatibility_decision") == "allowed"
    assert ai_execution.get("request_contract_status") == "accepted"
    assert ai_execution.get("provider_execution_status") == "accepted"
    assert ai_execution.get("artifact_status") == "completed"
    assert ai_execution.get("artifact_result") == "succeeded"
    assert isinstance(ai_execution.get("duration_ms"), int)
    assert ai_execution.get("timeout_seconds") == 120
    assert ai_execution.get("timeout_source") == "default"
    assert diagnostics.get("last_draft_request_contract_status") == "accepted"
    assert diagnostics.get("last_draft_provider_execution_status") == "accepted"
    assert diagnostics.get("last_draft_artifact_status") == "completed"
    assert diagnostics.get("last_draft_artifact_result") == "succeeded"
    assert isinstance(diagnostics.get("last_draft_execution_duration_ms"), int)


def test_draft_provider_compatibility_summary_and_log_are_emitted(db_session, caplog) -> None:
    provider = _CompatibilityTrackingMigrationProvider(
        compatibility=SEOMigrationProviderCompatibilityResult(
            supported=True,
            reason_code="supported",
            operator_message="AI configuration is compatible with migration draft generation.",
            admin_summary="openai_responses_json_schema_supported",
            retryable=False,
            provider_name="openai",
            model_name="gpt-5.1",
            endpoint_path="/responses",
            execution_mode="full",
            web_search_enabled=False,
            degraded_mode=False,
            response_format_mode="json_schema",
            request_body_mode="responses_text_format_json_schema",
        ),
        output=_build_publishable_output(),
    )
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    compatibility = (summary.context_summary or {}).get("draft_provider_compatibility") or {}
    assert compatibility.get("supported") is True
    assert compatibility.get("reason_code") == "supported"
    assert compatibility.get("provider_name") == "openai"
    assert compatibility.get("model_name") == "gpt-5.1"
    assert compatibility.get("endpoint_path") == "/responses"
    assert compatibility.get("response_format_mode") == "json_schema"
    assert compatibility.get("request_body_mode") == "responses_text_format_json_schema"
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("draft_provider_compatibility_admin_summary") == "openai_responses_json_schema_supported"

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_provider_compatibility_evaluation"
    ]
    assert payloads
    latest = payloads[-1]
    assert latest.get("business_id") == business_id
    assert latest.get("site_id") == site_id
    assert latest.get("workspace_id")
    assert latest.get("supported") is True
    assert latest.get("reason_code") == "supported"
    assert latest.get("endpoint_path") == "/responses"
    assert latest.get("execution_mode") == "full"
    assert latest.get("web_search_enabled") is False
    assert latest.get("degraded_mode") is False
    assert latest.get("response_format_mode") == "json_schema"
    assert latest.get("request_body_mode") == "responses_text_format_json_schema"
    assert latest.get("timeout_seconds") == 120
    assert latest.get("timeout_source") == "default"
    assert latest.get("decision") == "allowed"


def test_generate_artifacts_salvages_partial_provider_output(db_session) -> None:
    provider_error = SEOMigrationArtifactProviderError(
        code="schema_validation",
        safe_message="Provider returned malformed structured output.",
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
        raw_output=json.dumps(
            {
                "strategy_summary": "Partial salvage strategy",
                "generated_files": [
                    {
                        "path": "index.html",
                        "media_type": "text/html",
                        "content": "<html><head></head><body>Recovered</body></html>",
                    },
                    {
                        "path": "app/main.py",
                        "media_type": "text/plain",
                        "content": "forbidden",
                    },
                ],
            },
            ensure_ascii=True,
        ),
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "partial"
    assert artifact.error_summary == "Provider returned malformed structured output."
    assert artifact.file_count == 1
    assert (artifact.generated_files_json or [])[0]["path"] == "index.html"
    warnings = artifact.parse_warnings_json or []
    assert any("Recovered partial provider output." in warning for warning in warnings)
    assert any("partially salvaged" in warning for warning in warnings)
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    top_state = (summary.context_summary or {}).get("draft_generation_state")
    assert isinstance(top_state, dict)
    assert top_state.get("status") == "generation_partial"
    assert top_state.get("summary") == "Partial draft generated."


def test_generate_artifacts_emits_contract_evaluation_log(db_session, caplog) -> None:
    output = SEOMigrationArtifactGenerationOutput(
        strategy_summary="Contract-eval salvage strategy",
        page_map=[],
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
                content="<html><body><h1>Recovered Draft</h1></body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="infra/deploy.yaml",
                media_type="text/plain",
                content="forbidden",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert artifact.status == "partial"

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_draft_contract_evaluation"
    ]
    assert payloads
    latest = payloads[-1]
    assert latest.get("evaluation_status") == "salvaged"
    assert latest.get("dropped_item_count") == 1
    assert "partial_artifact_only" in (latest.get("warning_codes") or [])


def test_generate_artifacts_salvages_wrapped_provider_output_payload(db_session) -> None:
    wrapped_payload = (
        "Here is the structured migration payload:\n"
        "```json\n"
        + json.dumps(
            {
                "strategy_summary": "Wrapped salvage strategy",
                "generated_files": [
                    {
                        "path": "index.html",
                        "media_type": "text/html",
                        "content": "<html><body>Wrapped</body></html>",
                    }
                ],
            },
            ensure_ascii=True,
        )
        + "\n```\n"
        "Done."
    )
    provider_error = SEOMigrationArtifactProviderError(
        code="validation_failed",
        reason="validation_failed",
        safe_message="Provider returned invalid structured output.",
        provider_name="openai",
        model_name="gpt-5.1",
        prompt_version="seo-migration-v1",
        raw_output=wrapped_payload,
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "partial"
    assert artifact.file_count == 1
    assert (artifact.generated_files_json or [])[0]["path"] == "index.html"


def test_generate_artifacts_rejects_when_no_valid_files_remain(db_session) -> None:
    output = SEOMigrationArtifactGenerationOutput(
        strategy_summary="No usable files",
        page_map=[],
        homepage_structure=[],
        service_page_suggestions=[],
        cta_contact_structure={},
        seo_meta_suggestions={},
        redirect_suggestions=[],
        analytics_placeholders=[],
        generated_files=[
            SEOMigrationGeneratedFileOutput(
                path="app/main.py",
                media_type="text/plain",
                content="forbidden",
            )
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(
        SEOMigrationValidationError,
        match="Migration draft output did not include required static files.",
    ):
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )


def test_generate_artifacts_normalizes_absolute_and_root_paths(db_session) -> None:
    output = SEOMigrationArtifactGenerationOutput(
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
                path="https://tnmfire.example/index.html",
                media_type="text/html",
                content="<html><head></head><body><h1>Draft Home Content Block</h1></body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="/assets/site.css",
                media_type="text/css",
                content="body { color: #111; max-width: 72rem; margin: 0 auto; }",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert artifact.status in {"completed", "partial"}
    files = artifact.generated_files_json or []
    assert any(item.get("path") == "index.html" for item in files if isinstance(item, dict))
    assert any(item.get("path") == "assets/site.css" for item in files if isinstance(item, dict))


def test_generate_artifacts_root_path_normalization_keeps_forbidden_and_traversal_blocks(db_session) -> None:
    output = SEOMigrationArtifactGenerationOutput(
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
                path="/index.html",
                media_type="text/html",
                content="<html><body><h1>Valid Home Content Block</h1></body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="/../../escape.html",
                media_type="text/html",
                content="<html><body>bad</body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="/.github/workflows/evil.yml",
                media_type="text/yaml",
                content="name: bad",
            ),
            SEOMigrationGeneratedFileOutput(
                path="https://tnmfire.example/.git/config",
                media_type="text/plain",
                content="[core]",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    files = artifact.generated_files_json or []
    paths = {str(item["path"]) for item in files if isinstance(item, dict)}
    assert paths == {"index.html"}
    warnings = artifact.parse_warnings_json or []
    assert any("invalid path" in warning for warning in warnings)
    assert any("forbidden generated path" in warning for warning in warnings)


def test_generate_artifacts_rejection_emits_contract_diagnostics(db_session, caplog) -> None:
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
            SEOMigrationGeneratedFileOutput(path="https://tnmfire.example", media_type="text/html", content=" "),
            SEOMigrationGeneratedFileOutput(path="app/main.py", media_type="text/plain", content="forbidden"),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert error.failure_category == "artifact_invalid"
    assert error.failure_reason == "validation_failed"
    assert error.retryable is False

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_draft_contract_evaluation"
    ]
    assert payloads
    latest = payloads[-1]
    assert latest.get("evaluation_status") == "rejected"
    assert latest.get("candidate_item_count") == 2
    assert latest.get("normalized_item_count") == 0
    assert latest.get("dropped_item_count") == 2
    assert latest.get("missing_required_artifact_files") == ["index.html"]
    assert latest.get("artifact_primary_file_detected") is False
    assert latest.get("retry_likelihood") == "unlikely_without_contract_fix"
    parser_rejections = latest.get("parser_rejection_reason_counts") or {}
    assert isinstance(parser_rejections, dict)
    assert parser_rejections.get("invalid_path", 0) >= 1


def test_generate_artifacts_provider_timeout_persists_failed_diagnostics(db_session) -> None:
    provider_error = SEOMigrationArtifactProviderError(
        code="timeout",
        reason="timeout",
        safe_message="Migration draft generation timed out while calling the AI provider.",
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
        retryable=True,
        correlation_id="provider-timeout-1",
        normalized_failure_category="remote_timeout",
        normalized_failure_reason="provider_timeout",
        normalized_failure_source="remote_provider",
        normalized_retryable=True,
        attempt_count=2,
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert str(error) == "Migration draft generation timed out while calling the AI provider."
    assert error.failure_category == "config_missing"
    assert error.failure_reason == "timeout"
    assert error.error_code == "timeout"
    assert error.retryable is True
    assert error.correlation_id == "provider-timeout-1"
    assert error.timeout_seconds == 120
    assert error.timeout_source == "default"

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert workspace.migration_status == "draft_generation_failed"
    assert workspace.latest_generated_artifact_version_id
    assert workspace.latest_generated_artifact_version_number == 1
    artifact = service.get_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=workspace.latest_generated_artifact_version_id or "",
    )
    assert artifact.status == "failed"
    assert artifact.error_summary == "Migration draft generation timed out while calling the AI provider."
    assert artifact.file_count == 0

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    migration_diagnostics = summary.context_summary.get("migration_diagnostics")
    assert isinstance(migration_diagnostics, dict)
    assert migration_diagnostics.get("last_draft_generation_status") == "failed"
    assert migration_diagnostics.get("last_draft_failure_category") == "config_missing"
    assert migration_diagnostics.get("last_draft_failure_reason") == "timeout"
    assert migration_diagnostics.get("last_draft_failure_retryable") is True
    assert migration_diagnostics.get("last_draft_failure_code") == "timeout"
    assert migration_diagnostics.get("last_draft_failure_source") == "remote_provider"
    assert migration_diagnostics.get("last_draft_failure_timeout_seconds") == 120
    assert migration_diagnostics.get("last_draft_failure_timeout_source") == "default"
    assert migration_diagnostics.get("last_failure_normalized_category") == "remote_timeout"
    assert migration_diagnostics.get("last_failure_normalized_reason") == "provider_timeout"
    assert migration_diagnostics.get("last_failure_normalized_source") == "remote_provider"
    assert migration_diagnostics.get("last_failure_normalized_retryable") is True
    assert migration_diagnostics.get("last_failure_provider_attempt_count") == 2
    assert migration_diagnostics.get("last_draft_failure_hint") == "Provider timeout"
    draft_ai_summary = migration_diagnostics.get("last_draft_ai_diagnostics_summary")
    assert isinstance(draft_ai_summary, dict)
    assert set(draft_ai_summary.keys()) == _AI_DIAGNOSTICS_SUMMARY_KEYS
    assert draft_ai_summary.get("failure_category") == "remote_timeout"
    assert draft_ai_summary.get("failure_reason") == "provider_timeout"
    assert draft_ai_summary.get("failure_source") == "remote_provider"
    assert draft_ai_summary.get("retryable") is True
    assert draft_ai_summary.get("hint") == "Provider timeout"
    assert migration_diagnostics.get("draft_timeout_seconds") == 120
    assert migration_diagnostics.get("draft_timeout_source") == "default"
    assert migration_diagnostics.get("last_draft_failure_model_requested") is None
    assert migration_diagnostics.get("last_draft_failure_model_resolved") == "mock-seo-migration-v1"
    assert migration_diagnostics.get("last_draft_failure_model_used") == "gpt-4o-mini"
    assert migration_diagnostics.get("last_draft_failure_message") == (
        "Migration draft generation timed out while calling the AI provider."
    )
    ai_execution = summary.context_summary.get("ai_execution")
    assert isinstance(ai_execution, dict)
    assert ai_execution.get("model_requested") is None
    assert ai_execution.get("model_resolved") == "mock-seo-migration-v1"
    assert ai_execution.get("model_used") == "gpt-4o-mini"
    assert ai_execution.get("request_contract_status") == "rejected"
    assert ai_execution.get("provider_execution_status") == "rejected"
    assert ai_execution.get("artifact_status") == "failed"
    assert ai_execution.get("artifact_result") == "failed"
    assert isinstance(ai_execution.get("duration_ms"), int)
    assert ai_execution.get("timeout_seconds") == 120
    assert ai_execution.get("timeout_source") == "default"
    top_state = summary.context_summary.get("draft_generation_state")
    assert isinstance(top_state, dict)
    assert top_state.get("status") == "generation_failed"
    assert top_state.get("summary") == "Migration draft generation timed out while calling the AI provider."


def test_generate_artifacts_request_too_large_persists_non_retryable_hint(db_session) -> None:
    provider_error = SEOMigrationArtifactProviderError(
        code="validation_failed",
        reason="validation_failed",
        safe_message="Migration draft request is too large or complex for synchronous generation.",
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
        retryable=False,
        normalized_failure_category="local_validation_failure",
        normalized_failure_reason="request_too_large_or_complex",
        normalized_failure_source="local_validation",
        normalized_retryable=False,
        attempt_count=0,
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert error.failure_category == "artifact_invalid"
    assert error.failure_reason == "validation_failed"
    assert error.retryable is False

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    migration_diagnostics = summary.context_summary.get("migration_diagnostics")
    assert isinstance(migration_diagnostics, dict)
    assert migration_diagnostics.get("last_draft_failure_retryable") is False
    assert migration_diagnostics.get("last_failure_normalized_category") == "local_validation_failure"
    assert migration_diagnostics.get("last_failure_normalized_reason") == "request_too_large_or_complex"
    assert migration_diagnostics.get("last_failure_normalized_source") == "local_validation"
    assert migration_diagnostics.get("last_failure_normalized_retryable") is False
    assert migration_diagnostics.get("last_draft_failure_hint") == "Input too large"
    draft_ai_summary = migration_diagnostics.get("last_draft_ai_diagnostics_summary")
    assert isinstance(draft_ai_summary, dict)
    assert set(draft_ai_summary.keys()) == _AI_DIAGNOSTICS_SUMMARY_KEYS
    assert draft_ai_summary.get("failure_category") == "local_validation_failure"
    assert draft_ai_summary.get("failure_reason") == "request_too_large_or_complex"
    assert draft_ai_summary.get("failure_source") == "local_validation"
    assert draft_ai_summary.get("retryable") is False
    assert draft_ai_summary.get("hint") == "Input too large"
    assert draft_ai_summary.get("budget_outcome") == "retry_suppressed"
    assert draft_ai_summary.get("retry_suppressed") is True


def test_generate_artifacts_success_state_overrides_stale_failure_messaging(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert artifact.status == "completed"

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    migration_diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert migration_diagnostics.get("last_draft_generation_status") == "completed"
    assert migration_diagnostics.get("last_draft_failure_category") is None
    assert migration_diagnostics.get("last_draft_failure_message") is None
    top_state = (summary.context_summary or {}).get("draft_generation_state")
    assert isinstance(top_state, dict)
    assert top_state.get("status") == "generation_succeeded"
    assert top_state.get("summary") == "Draft generated successfully."


def test_generate_artifacts_provider_reason_classification_uses_config_missing_for_configuration_failures(
    db_session,
) -> None:
    provider_error = SEOMigrationArtifactProviderError(
        code="unsupported_configuration",
        reason="unsupported_configuration",
        safe_message="AI provider configuration is invalid for migration draft generation.",
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
        retryable=False,
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert error.failure_category == "config_missing"
    assert error.failure_reason == "unsupported_configuration"
    assert error.retryable is False


def test_generate_artifacts_unknown_provider_exception_returns_stable_unknown_error(db_session) -> None:
    service = _build_service(db_session, _ExplodingMigrationProvider())
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    error = exc_info.value
    assert str(error) == "Migration draft generation failed due to an unexpected provider error."
    assert error.failure_category == "unknown_error"
    assert error.failure_reason == "unknown"
    assert error.error_code == "unknown"
    assert error.retryable is None


def test_generate_artifacts_failure_emits_structured_draft_generation_logs(db_session, caplog) -> None:
    provider_error = SEOMigrationArtifactProviderError(
        code="timeout",
        reason="timeout",
        safe_message="Migration draft generation timed out while calling the AI provider.",
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
        retryable=True,
        correlation_id="provider-timeout-2",
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError):
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_draft_generation"
    ]
    assert payloads
    assert any(
        payload.get("status") == "requested"
        and payload.get("business_id") == business_id
        and payload.get("site_id") == site_id
        and payload.get("workspace_id")
        and payload.get("draft_run_id")
        for payload in payloads
    )
    assert any(
        payload.get("status") == "failed"
        and payload.get("failure_category") == "config_missing"
        and payload.get("failure_reason") == "timeout"
        and payload.get("retryable") is True
        and payload.get("timeout_seconds") == 120
        and payload.get("timeout_source") == "default"
        and payload.get("artifact_version_id")
        and isinstance(payload.get("duration_ms"), int)
        for payload in payloads
    )


def test_workspace_summary_reused_context_uses_best_available_signals(db_session, caplog) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    now = utc_now()
    audit_run = SEOAuditRun(
        id="audit-run-context-1",
        business_id=business_id,
        site_id=site_id,
        status="completed",
        started_at=now,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    service.seo_audit_repository.create_run(audit_run)

    recommendation_run = SEORecommendationRun(
        id="recommendation-run-context-1",
        business_id=business_id,
        site_id=site_id,
        audit_run_id=audit_run.id,
        comparison_run_id=None,
        status="completed",
        total_recommendations=1,
        critical_recommendations=0,
        warning_recommendations=1,
        info_recommendations=0,
        started_at=now,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    service.seo_recommendation_repository.create_run(recommendation_run)
    service.seo_recommendation_repository.add_recommendation(
        SEORecommendation(
            id="recommendation-context-1",
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run.id,
            audit_run_id=audit_run.id,
            comparison_run_id=None,
            rule_key="migration-context-rule",
            category="SEO",
            severity="WARNING",
            title="Clarify homepage service copy",
            rationale="Service details are sparse and repetitive.",
            priority_score=70,
            priority_band="high",
            effort_bucket="small",
            status="open",
        )
    )

    competitor_set = SEOCompetitorSet(
        id="competitor-set-context-1",
        business_id=business_id,
        site_id=site_id,
        name="Primary competitors",
        is_active=True,
        created_by_principal_id="principal-1",
    )
    service.seo_competitor_repository.create_set(competitor_set)
    snapshot_run = SEOCompetitorSnapshotRun(
        id="snapshot-run-context-1",
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        client_audit_run_id=audit_run.id,
        status="completed",
        pages_captured=3,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    service.seo_competitor_repository.create_snapshot_run(snapshot_run)
    comparison_run = SEOCompetitorComparisonRun(
        id="comparison-run-context-1",
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        snapshot_run_id=snapshot_run.id,
        baseline_audit_run_id=audit_run.id,
        status="completed",
        total_findings=2,
        critical_findings=1,
        warning_findings=1,
        client_pages_analyzed=2,
        competitor_pages_analyzed=3,
        completed_at=now,
        created_by_principal_id="principal-1",
    )
    service.seo_competitor_repository.create_comparison_run(comparison_run)
    db_session.commit()

    caplog.set_level("INFO", logger="app.services.seo_migration")
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)

    reused_context = summary.context_summary.get("reused_context")
    assert isinstance(reused_context, dict)

    audit_context = reused_context.get("audit")
    assert isinstance(audit_context, dict)
    assert audit_context.get("available") is True
    assert audit_context.get("source") == "latest_successful_run"
    assert audit_context.get("run_id") == audit_run.id

    recommendations_context = reused_context.get("recommendations")
    assert isinstance(recommendations_context, dict)
    assert recommendations_context.get("available") is True
    assert recommendations_context.get("source") == "latest_generated"
    assert recommendations_context.get("run_id") == recommendation_run.id
    assert recommendations_context.get("count") == 1

    competitors_context = reused_context.get("competitors")
    assert isinstance(competitors_context, dict)
    assert competitors_context.get("available") is True
    assert competitors_context.get("source") == "latest_run"
    assert competitors_context.get("run_id") == comparison_run.id
    assert competitors_context.get("count") == 2

    existing_context_summaries = summary.context_summary.get("existing_context_summaries")
    assert isinstance(existing_context_summaries, dict)
    assert existing_context_summaries.get("audit_summary") is None
    assert existing_context_summaries.get("recommendation_summary") is None
    assert existing_context_summaries.get("competitor_summary") is None

    assert summary.context_summary.get("has_audit_summary") is True
    assert summary.context_summary.get("has_recommendation_summary") is True
    assert summary.context_summary.get("has_competitor_summary") is True

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "migration_context_summary"
    ]
    assert payloads
    latest_payload = payloads[-1]
    assert latest_payload.get("site_id") == site_id
    assert latest_payload.get("business_id") == business_id
    assert latest_payload.get("workspace_id")
    assert latest_payload.get("audit_available") is True
    assert latest_payload.get("recommendation_available") is True
    assert latest_payload.get("competitor_available") is True
    assert latest_payload.get("audit_source") == "latest_successful_run"
    assert latest_payload.get("recommendation_source") == "latest_generated"
    assert latest_payload.get("competitor_source") == "latest_run"


def test_publish_requires_approved_artifact(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "sites/tnmfire",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="approved artifact is required before publish"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=True,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert publisher.publish_calls == []


def test_publish_and_deploy_flow_records_status_and_analytics(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session, ga_measurement_id="G-SITE1234")
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "sites/tnmfire",
        },
        principal_id="principal-1",
    )
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
        },
        principal_id="principal-1",
    )
    service.update_analytics_config(
        business_id=business_id,
        site_id=site_id,
        analytics_config={
            "enabled": True,
            "ga_measurement_id": "G-WORK1234",
            "insertion_mode": "publish_and_deploy",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved for publish",
        principal_id="principal-1",
    )

    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message="Publish migration",
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert publish_result.artifact.publish_status == "published"
    assert publish_result.workspace.publish_status == "published"
    assert publish_result.workspace.last_published_artifact_version_id == artifact.id
    assert publish_result.workspace.last_published_commit_sha == "abc123"
    assert publisher.publish_calls
    _, published_files, _, _ = publisher.publish_calls[-1]
    index_file = next(item for item in published_files if item.path == "index.html")
    assert "G-WORK1234" in index_file.content
    assert "ANALYTICS_PLACEHOLDER" not in index_file.content

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.artifact.deploy_status == "deploy_requested"
    assert deploy_result.workspace.deploy_status == "deploy_requested"
    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert "ga_measurement_id" not in deploy_target.inputs


def test_deploy_dispatch_payload_uses_explicit_configured_inputs_only(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session, ga_measurement_id="G-SITE1234")
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "sites/tnmfire",
        },
        principal_id="principal-1",
    )
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"site_url": "https://www.tnmfire.com"},
        },
        principal_id="principal-1",
    )
    service.update_analytics_config(
        business_id=business_id,
        site_id=site_id,
        analytics_config={
            "enabled": True,
            "ga_measurement_id": "G-WORK1234",
            "insertion_mode": "publish_and_deploy",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved for publish",
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message="Publish migration",
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.inputs == {"site_url": "https://www.tnmfire.com"}
    assert deploy_result.result.get("workflow_inputs_configured_keys") == ["site_url"]
    assert deploy_result.result.get("workflow_inputs_sent_keys") == ["site_url"]


def test_publish_records_expected_publish_url_when_determinable(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"site_url": "https://www.tnmfire.com"},
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert result.result.get("expected_publish_url") == "https://www.tnmfire.com"
    assert result.result.get("url_source") == "deterministic_target_config"
    assert result.result.get("url_source_detail") == "deploy_input:site_url"

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = workspace.publish_history_json or []
    assert publish_history
    assert publish_history[-1].get("expected_publish_url") == "https://www.tnmfire.com"


def test_publish_records_null_expected_publish_url_when_not_determinable(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert result.result.get("expected_publish_url") is None
    assert result.result.get("url_source") == "unknown"
    assert result.result.get("url_source_detail") is None


def test_deploy_records_resolved_live_url_from_deploy_result(db_session) -> None:
    publisher = _RecordingGitHubPublisher(deploy_live_url="https://live.tnmfire.com")
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"site_url": "https://www.tnmfire.com"},
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") == "https://live.tnmfire.com"
    assert deploy_result.result.get("url_source") == "deploy_result"
    assert deploy_result.result.get("url_source_detail") == "deploy_result:live_url"

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_destination.get("state") == "active_live"
    assert deploy_destination.get("active_url") == "https://live.tnmfire.com"
    assert deploy_destination.get("resolved_live_url") == "https://live.tnmfire.com"


def test_deploy_does_not_confirm_live_url_without_explicit_deploy_evidence(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"site_url": "https://www.tnmfire.com"},
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") is None
    assert deploy_result.result.get("url_source") == "unknown"
    assert deploy_result.result.get("url_source_detail") is None
    assert deploy_result.result.get("expected_publish_url") == "https://www.tnmfire.com"
    assert deploy_result.result.get("deploy_evidence_contract_status") in {
        "evidence_pending",
        "workflow_succeeded_without_explicit_evidence",
    }

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_destination.get("state") == "expected_after_deploy"
    assert deploy_destination.get("active_url") is None
    assert deploy_destination.get("resolved_live_url") is None
    assert deploy_destination.get("expected_publish_url") == "https://www.tnmfire.com"


def test_deploy_records_resolved_live_url_from_workflow_output(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_output={"live_url": "https://workflow-live.tnmfire.com"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"site_url": "https://www.tnmfire.com"},
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") == "https://workflow-live.tnmfire.com"
    assert deploy_result.result.get("url_source") == "workflow_output"
    assert deploy_result.result.get("url_source_detail") == "workflow_output:live_url"
    assert deploy_result.result.get("expected_workflow_outputs") == ["resolved_live_url", "live_url", "deployed_url"]
    assert deploy_result.result.get("deploy_evidence_contract_status") == "confirmed_live_evidence"
    assert deploy_result.result.get("workflow_contract_advisory") is None

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_destination.get("state") == "active_live"
    assert deploy_destination.get("active_url") == "https://workflow-live.tnmfire.com"


def test_deploy_prefers_resolved_live_url_over_live_url_and_deployed_url(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_output={
            "live_url": "https://workflow-live.tnmfire.com",
            "resolved_live_url": "https://resolved-live.tnmfire.com",
            "deployed_url": "https://deployed-live.tnmfire.com",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") == "https://resolved-live.tnmfire.com"
    assert deploy_result.result.get("url_source") == "workflow_output"
    assert deploy_result.result.get("url_source_detail") == "workflow_output:resolved_live_url"


def test_deploy_uses_deployed_url_when_higher_priority_workflow_output_keys_absent(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_output={"deployed_url": "https://deployed-live.tnmfire.com"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") == "https://deployed-live.tnmfire.com"
    assert deploy_result.result.get("url_source") == "workflow_output"
    assert deploy_result.result.get("url_source_detail") == "workflow_output:deployed_url"


@pytest.mark.parametrize("workflow_id", ["deploy-tnmfire-www-prod.yml", "deploy-www-prod.yml"])
def test_deploy_consumes_pages_evidence_contract_identically_for_site_specific_and_fallback_workflows(
    db_session,
    workflow_id: str,
) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_output={"resolved_live_url": "https://resolved-live.tnmfire.com"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id=workflow_id,
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") == "https://resolved-live.tnmfire.com"
    assert deploy_result.result.get("url_source") == "workflow_output"
    assert deploy_result.result.get("url_source_detail") == "workflow_output:resolved_live_url"


def test_deploy_does_not_treat_request_inputs_as_confirmed_live_url(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"live_url": "https://operator-input.example"},
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("resolved_live_url") is None
    assert deploy_result.result.get("url_source") == "unknown"
    assert deploy_result.result.get("url_source_detail") is None
    assert deploy_result.result.get("workflow_inputs_configured_keys") == ["live_url"]
    assert deploy_result.result.get("workflow_inputs_sent_keys") == ["live_url"]
    assert deploy_result.result.get("workflow_run_lookup_attempted") is True
    assert deploy_result.result.get("workflow_run_found") is False
    assert deploy_result.result.get("dispatch_verification_state") == "unverified_dispatch_no_run_observed"
    assert deploy_result.result.get("post_dispatch_state") == "dispatch_unverified_no_run"
    assert deploy_result.result.get("post_conformance_stage") == "workflow_dispatch_succeeded_waiting_for_run"
    assert deploy_result.result.get("post_conformance_reason_text") == (
        "Workflow dispatch succeeded but run evidence is still pending."
    )
    assert deploy_result.result.get("deploy_evidence_contract_status") == "evidence_pending"
    assert deploy_result.result.get("deploy_evidence_contract_reasons") == ["dispatch_unverified_no_run"]

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_destination.get("state") == "unknown"
    assert deploy_destination.get("active_url") is None
    assert deploy_destination.get("resolved_live_url") is None


def test_deploy_records_run_failure_without_live_url_confirmation(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=556677,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion="failure",
        deploy_workflow_run_failure_reason_code="rollout_verification_failed",
        deploy_workflow_run_failure_stage="rollout_verify",
        deploy_workflow_run_failure_step="Verify rollout",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("workflow_run_id") == 556677
    assert deploy_result.result.get("workflow_run_status") == "completed"
    assert deploy_result.result.get("workflow_run_conclusion") == "failure"
    assert deploy_result.result.get("workflow_run_lookup_attempted") is True
    assert deploy_result.result.get("workflow_run_found") is True
    assert deploy_result.result.get("workflow_job_failure_detected") is True
    assert deploy_result.result.get("workflow_run_failure_reason_code") == "rollout_verification_failed"
    assert deploy_result.result.get("workflow_run_failure_stage") == "rollout_verify"
    assert deploy_result.result.get("workflow_run_failure_step") == "Verify rollout"
    assert deploy_result.result.get("workflow_run_failure_hint") == (
        "Deployment rollout verification failed or timed out in the deploy workflow run."
    )
    assert deploy_result.result.get("post_dispatch_state") == "workflow_run_failed"
    assert deploy_result.result.get("post_conformance_stage") == "rollout_failed"
    assert deploy_result.result.get("post_conformance_reason_text") == (
        "Deployment rollout verification failed or timed out in the deploy workflow run."
    )
    assert (
        deploy_result.result.get("deploy_evidence_contract_status") == "workflow_run_failed_without_explicit_evidence"
    )
    assert deploy_result.result.get("workflow_contract_advisory") == (
        "Workflow run failed before explicit live URL evidence was captured."
    )
    assert deploy_result.result.get("resolved_live_url") is None

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("last_workflow_run_lookup_attempted") is True
    assert deploy_readiness.get("last_workflow_run_found") is True
    assert deploy_readiness.get("last_workflow_job_failure_detected") is True
    assert deploy_readiness.get("last_workflow_run_failure_reason_code") == "rollout_verification_failed"
    assert deploy_readiness.get("last_workflow_run_failure_stage") == "rollout_verify"
    assert deploy_readiness.get("last_workflow_run_failure_step") == "Verify rollout"
    assert deploy_readiness.get("last_workflow_run_failure_hint") == (
        "Deployment rollout verification failed or timed out in the deploy workflow run."
    )
    assert deploy_readiness.get("last_post_dispatch_state") == "workflow_run_failed"
    assert deploy_readiness.get("last_post_conformance_stage") == "rollout_failed"
    assert deploy_readiness.get("last_post_conformance_reason_text") == (
        "Deployment rollout verification failed or timed out in the deploy workflow run."
    )
    assert (
        deploy_readiness.get("last_deploy_evidence_contract_status") == "workflow_run_failed_without_explicit_evidence"
    )


def test_deploy_completed_without_explicit_live_url_evidence_is_advisory(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=112233,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion="success",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("workflow_run_id") == 112233
    assert deploy_result.result.get("workflow_run_status") == "completed"
    assert deploy_result.result.get("workflow_run_conclusion") == "success"
    assert deploy_result.result.get("resolved_live_url") is None
    assert deploy_result.result.get("post_dispatch_state") == "workflow_run_succeeded_without_live_url"
    assert deploy_result.result.get("post_conformance_stage") == "live_url_evidence_missing"
    assert deploy_result.result.get("post_conformance_reason_text") == (
        "Workflow run completed without resolved_live_url evidence."
    )
    assert deploy_result.result.get("deploy_evidence_contract_status") == "workflow_succeeded_without_explicit_evidence"
    assert deploy_result.result.get("workflow_contract_advisory") == (
        "Workflow run completed but did not emit explicit live URL evidence."
    )


def test_deploy_placeholder_workflow_is_blocked_as_not_production_ready(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        non_production_ready_workflow_paths={".github/workflows/deploy-tnmfire-www-prod.yml"},
        readiness_workflow_conformance_status="workflow_placeholder_detected",
        readiness_workflow_conformance_reasons=("placeholder_workflow_content_detected",),
        readiness_workflow_conformance_evidence_summary="workflow_dispatch=true;placeholder_markers=placeholder",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert "scaffold-only and not production-ready" in str(exc_info.value)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("last_failure_reason") == "workflow_not_production_ready"
    assert deploy_readiness.get("last_failure_stage") == "workflow_lookup"
    assert deploy_readiness.get("workflow_conformance_status") == "workflow_placeholder_detected"
    assert deploy_readiness.get("last_post_conformance_stage") == "workflow_conformance_failed"
    assert deploy_readiness.get("last_post_conformance_reason_text") == (
        "Workflow conformance validation failed before dispatch."
    )
    assert deploy_readiness.get("last_deploy_evidence_contract_status") == "workflow_placeholder_advisory"


def test_refresh_deploy_status_updates_run_metadata_and_captures_workflow_output_url(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998877,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=998877,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="success",
        refresh_workflow_output={"live_url": "https://refresh-live.tnmfire.com"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    caplog.set_level("INFO", logger="app.services.seo_migration")

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("status") == "updated"
    assert refresh_result.result.get("workflow_run_status") == "completed"
    assert refresh_result.result.get("workflow_run_conclusion") == "success"
    assert refresh_result.result.get("resolved_live_url") == "https://refresh-live.tnmfire.com"
    assert refresh_result.result.get("url_source") == "workflow_output"
    assert refresh_result.result.get("workflow_run_lookup_attempted") is True
    assert refresh_result.result.get("workflow_run_found") is True
    assert refresh_result.result.get("workflow_job_failure_detected") is False
    assert refresh_result.result.get("post_dispatch_state") == "workflow_run_succeeded_with_live_url"
    assert refresh_result.result.get("deploy_trace_id") == deploy_result.result.get("deploy_trace_id")
    assert publisher.refresh_calls

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest_entry = deploy_history[-1]
    assert latest_entry.get("workflow_run_status") == "completed"
    assert latest_entry.get("workflow_run_conclusion") == "success"
    assert latest_entry.get("resolved_live_url") == "https://refresh-live.tnmfire.com"
    assert latest_entry.get("url_source") == "workflow_output"
    assert latest_entry.get("workflow_run_lookup_attempted") is True
    assert latest_entry.get("workflow_run_found") is True
    assert latest_entry.get("workflow_job_failure_detected") is False
    assert latest_entry.get("post_dispatch_state") == "workflow_run_succeeded_with_live_url"

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_destination.get("active_url") == "https://refresh-live.tnmfire.com"
    assert deploy_destination.get("url_source") == "workflow_output"

    refresh_logs = [record.msg for record in caplog.records if isinstance(record.msg, str)]
    assert any('"event": "seo_migration_deploy_status_refresh_requested"' in item for item in refresh_logs)
    assert any('"event": "seo_migration_workflow_run_refresh_lookup_attempted"' in item for item in refresh_logs)
    assert any('"event": "seo_migration_workflow_run_refresh_result_captured"' in item for item in refresh_logs)
    assert any('"event": "seo_migration_workflow_output_url_captured_via_refresh"' in item for item in refresh_logs)
    assert any('"event": "seo_migration_deploy_status_refresh_completed"' in item for item in refresh_logs)
    assert "MIGRATION_GITHUB_TOKEN" not in " ".join(refresh_logs)


def test_refresh_deploy_status_records_run_failure_classification(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998877,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=998877,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="gcp_auth_failed",
        refresh_workflow_run_failure_stage="gcp_auth",
        refresh_workflow_run_failure_step="Authenticate to GCP",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("status") == "updated"
    assert refresh_result.result.get("workflow_run_status") == "completed"
    assert refresh_result.result.get("workflow_run_conclusion") == "failure"
    assert refresh_result.result.get("workflow_job_failure_detected") is True
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "gcp_auth_failed"
    assert refresh_result.result.get("workflow_run_failure_stage") == "gcp_auth"
    assert refresh_result.result.get("workflow_run_failure_step") == "Authenticate to GCP"
    assert refresh_result.result.get("workflow_run_failure_hint") == (
        "GCP authentication failed in the deploy workflow run."
    )
    assert refresh_result.result.get("resolved_live_url") is None

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("last_workflow_run_failure_reason_code") == "gcp_auth_failed"
    assert deploy_readiness.get("last_workflow_run_failure_stage") == "gcp_auth"
    assert deploy_readiness.get("last_workflow_run_failure_step") == "Authenticate to GCP"
    assert deploy_readiness.get("last_workflow_run_failure_hint") == (
        "GCP authentication failed in the deploy workflow run."
    )


def test_refresh_deploy_status_records_cloudsql_proxy_invalid_state_hint(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998878,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=998878,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="cloudsql_instance_invalid_state",
        refresh_workflow_run_failure_stage="manifest_apply",
        refresh_workflow_run_failure_step="Run Alembic migrations (pre-rollout gate)",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "cloudsql_instance_invalid_state"
    assert refresh_result.result.get("workflow_run_failure_stage") == "manifest_apply"
    assert refresh_result.result.get("workflow_run_failure_step") == "Run Alembic migrations (pre-rollout gate)"
    assert refresh_result.result.get("workflow_run_failure_hint") == (
        "Cloud SQL proxy could not fetch an ephemeral certificate because the instance reported invalidState. "
        "Confirm Cloud SQL instance state is RUNNABLE and retry deploy."
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("last_workflow_run_failure_reason_code") == "cloudsql_instance_invalid_state"
    assert deploy_readiness.get("last_workflow_run_failure_hint") == (
        "Cloud SQL proxy could not fetch an ephemeral certificate because the instance reported invalidState. "
        "Confirm Cloud SQL instance state is RUNNABLE and retry deploy."
    )


def test_refresh_deploy_status_records_cloudsql_inspection_failed_hint(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998879,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=998879,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="cloudsql_instance_inspection_failed",
        refresh_workflow_run_failure_stage="manifest_apply",
        refresh_workflow_run_failure_step="Preflight Cloud SQL instance state",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "cloudsql_instance_inspection_failed"
    assert refresh_result.result.get("workflow_run_failure_stage") == "manifest_apply"
    assert refresh_result.result.get("workflow_run_failure_step") == "Preflight Cloud SQL instance state"
    assert refresh_result.result.get("workflow_run_failure_hint") == (
        "Cloud SQL instance inspection failed before migration startup. "
        "Verify instance name/project/permissions and retry deploy."
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("last_workflow_run_failure_reason_code") == "cloudsql_instance_inspection_failed"
    assert deploy_readiness.get("last_workflow_run_failure_hint") == (
        "Cloud SQL instance inspection failed before migration startup. "
        "Verify instance name/project/permissions and retry deploy."
    )


def test_refresh_deploy_status_is_noop_without_workflow_run_metadata(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("status") == "no_change"
    assert refresh_result.result.get("no_change_reason") == "no_run_observed_after_refresh"
    assert refresh_result.result.get("dispatch_attempted") is True
    assert refresh_result.result.get("workflow_run_lookup_attempted") is True
    assert refresh_result.result.get("workflow_run_found") is False
    assert refresh_result.result.get("dispatch_verification_state") == "unverified_dispatch_no_run_observed"
    assert refresh_result.result.get("post_dispatch_state") == "dispatch_unverified_no_run"
    assert publisher.refresh_calls == []
    assert len(publisher.lookup_calls) == 1
    refresh_logs = [record.msg for record in caplog.records if isinstance(record.msg, str)]
    assert any('"event": "no_run_observed_after_refresh"' in item for item in refresh_logs)


def test_refresh_deploy_status_workflow_not_found_marks_tracking_lost_and_allows_retry(
    db_session,
    caplog,
) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998880,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        fail_refresh=True,
        refresh_error_code="workflow_not_found",
        refresh_error_message="Simulated workflow run lookup failure.",
        refresh_error_stage="workflow_run_lookup",
        lookup_workflow_run_id=None,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    first_deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert first_deploy_result.result.get("post_dispatch_state") == "workflow_run_in_progress"

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("status") == "no_change"
    assert refresh_result.result.get("no_change_reason") == "workflow_run_tracking_lost"
    assert refresh_result.result.get("message") == (
        "Deploy tracking lost (workflow run not found after dispatch). Retry deploy."
    )
    assert refresh_result.result.get("post_dispatch_state") == "workflow_run_failed"
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "workflow_run_tracking_lost"
    assert refresh_result.result.get("workflow_run_failure_stage") == "workflow_execution"
    assert refresh_result.result.get("workflow_run_failure_hint") == (
        "Deploy tracking lost (workflow run not found after dispatch). Retry deploy."
    )
    assert refresh_result.result.get("workflow_run_lookup_attempted") is True
    assert refresh_result.result.get("workflow_run_found") is False
    assert refresh_result.result.get("workflow_job_failure_detected") is True
    assert refresh_result.result.get("dispatch_verification_state") == "unverified_dispatch_no_run_observed"
    assert len(publisher.refresh_calls) == 1
    assert len(publisher.lookup_calls) == 1

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest_entry = deploy_history[-1]
    assert latest_entry.get("post_dispatch_state") == "workflow_run_failed"
    assert latest_entry.get("workflow_run_failure_reason_code") == "workflow_run_tracking_lost"
    assert latest_entry.get("workflow_run_failure_stage") == "workflow_execution"
    assert latest_entry.get("workflow_run_lookup_attempted") is True
    assert latest_entry.get("workflow_run_found") is False
    assert latest_entry.get("workflow_job_failure_detected") is True

    # Tracking-lost refresh should clear duplicate in-progress deadlocks so redeploy can proceed.
    second_deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert second_deploy_result.result.get("status") == "deploy_requested"
    assert second_deploy_result.result.get("post_dispatch_state") == "workflow_run_in_progress"
    assert len(publisher.deploy_calls) == 2

    refresh_logs = [record.msg for record in caplog.records if isinstance(record.msg, str)]
    assert any('"event": "dispatch_attempted_without_run"' in item for item in refresh_logs)
    assert any('"event": "downgrade_to_stale_unverified_dispatch"' in item for item in refresh_logs)


def test_refresh_deploy_status_preserves_stronger_existing_confirmed_url(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_live_url="https://deploy-live.tnmfire.com",
        deploy_workflow_run_id=123456,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=123456,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="success",
        refresh_workflow_output={"live_url": "https://workflow-live.tnmfire.com"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("status") == "updated"
    assert refresh_result.result.get("resolved_live_url") == "https://deploy-live.tnmfire.com"
    assert refresh_result.result.get("url_source") == "deploy_result"


def test_publish_filters_invalid_stored_paths_before_publish(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    artifact.generated_files_json = [
        {"path": "index.html", "content": "<html><head></head><body>ok</body></html>", "media_type": "text/html"},
        {"path": "app/main.py", "content": "print('bad')", "media_type": "text/plain"},
        {"path": "../escape.html", "content": "<html>bad</html>", "media_type": "text/html"},
    ]
    service.seo_migration_repository.save_artifact_version(artifact)
    db_session.commit()
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=True,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert publisher.publish_calls
    _, files, _, dry_run = publisher.publish_calls[-1]
    assert dry_run is True
    assert [item.path for item in files] == ["index.html"]
    warnings = publish_result.result.get("warnings")
    assert isinstance(warnings, list)
    assert any("outside static package boundary" in str(item) for item in warnings)


def test_publish_provisions_missing_deploy_workflow_once(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=False)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    caplog.set_level("INFO", logger="app.services.seo_migration")
    result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.workflow_provision_calls) == 1
    workflow_call = publisher.workflow_provision_calls[0]
    assert workflow_call[:8] == (
        "acme",
        "tnmfire-site",
        "main",
        "deploy-tnmfire-www-prod.yml",
        False,
        "site_repo_template_v1",
        "gke_prod",
        "admin_config",
    )
    assert isinstance(workflow_call[8], dict)
    assert isinstance(workflow_call[9], dict)
    assert workflow_call[10] == site_id
    assert result.result.get("deploy_workflow_provisioned") is True
    assert result.result.get("deploy_workflow_id") == "deploy-tnmfire-www-prod.yml"
    assert result.result.get("deploy_workflow_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    provision_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "migration_workflow_provisioned"' in record.msg
    ]
    assert provision_logs
    assert '"workflow_id": "deploy-tnmfire-www-prod.yml"' in provision_logs[-1].msg
    provisioning_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_workflow_provisioning"' in record.msg
    ]
    assert provisioning_logs
    assert any('"status": "created"' in record.msg for record in provisioning_logs)
    assert any('"status": "verified"' in record.msg for record in provisioning_logs)
    assert any('"remediation_mode": "bootstrap"' in record.msg for record in provisioning_logs)


def test_publish_workflow_resolution_aligns_with_deploy_candidate_precedence(db_session, caplog) -> None:
    site_specific_workflow_id = "deploy-tnmfire-www-prod.yml"
    site_specific_workflow_path = f".github/workflows/{site_specific_workflow_id}"
    publisher = _RecordingGitHubPublisher(
        existing_workflow=False,
        available_workflow_paths={site_specific_workflow_path, ".github/workflows/deploy-www-prod.yml"},
        non_production_ready_workflow_paths={site_specific_workflow_path},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    caplog.set_level("INFO", logger="app.services.seo_migration")
    result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert result.result.get("deploy_workflow_id") == site_specific_workflow_id
    assert result.result.get("deploy_workflow_path") == site_specific_workflow_path
    assert len(publisher.workflow_provision_calls) == 1
    workflow_call = publisher.workflow_provision_calls[0]
    assert workflow_call[:4] == (
        "acme",
        "tnmfire-site",
        "main",
        site_specific_workflow_id,
    )
    resolution_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_publish_workflow_resolution"' in record.msg
    ]
    assert resolution_logs
    assert f'"workflow_path": "{site_specific_workflow_path}"' in resolution_logs[-1].msg
    assert '"resolved_workflow_source": "site_specific_workflow"' in resolution_logs[-1].msg


def test_publish_does_not_overwrite_existing_deploy_workflow(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    caplog.set_level("INFO", logger="app.services.seo_migration")
    result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.workflow_provision_calls) == 1
    workflow_call = publisher.workflow_provision_calls[0]
    assert workflow_call[:8] == (
        "acme",
        "tnmfire-site",
        "main",
        "deploy-tnmfire-www-prod.yml",
        False,
        "site_repo_template_v1",
        "gke_prod",
        "admin_config",
    )
    assert isinstance(workflow_call[8], dict)
    assert isinstance(workflow_call[9], dict)
    assert workflow_call[10] == site_id
    assert result.result.get("deploy_workflow_provisioned") is False
    provision_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "migration_workflow_provisioned"' in record.msg
    ]
    assert provision_logs == []
    provisioning_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_workflow_provisioning"' in record.msg
    ]
    assert provisioning_logs
    assert any('"status": "already_exists"' in record.msg for record in provisioning_logs)


def test_publish_failure_records_failed_state_and_history(db_session) -> None:
    publisher = _RecordingGitHubPublisher(fail_publish=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated publish failure."):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    updated_artifact = service.get_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
    )
    updated_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert updated_artifact.publish_status == "publish_failed"
    assert updated_workspace.publish_status == "publish_failed"
    history = updated_workspace.publish_history_json or []
    assert history
    last_entry = history[-1]
    assert last_entry.get("action") == "publish"
    assert last_entry.get("status") == "failed"
    assert last_entry.get("timestamp")
    assert last_entry.get("repo_owner") == "acme"
    assert last_entry.get("repo_name") == "tnmfire-site"
    assert last_entry.get("branch") == "main"
    assert last_entry.get("failure_category") == "provider_error"
    assert last_entry.get("error_summary") == "Simulated publish failure."
    assert "traceback" not in str(last_entry.get("error_summary", "")).lower()
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    assert summary.publish_readiness.get("last_status") == "failed"
    assert summary.publish_readiness.get("last_failure_category") == "provider_error"
    assert summary.publish_readiness.get("last_failure_message") == "Simulated publish failure."
    migration_diagnostics = summary.context_summary.get("migration_diagnostics")
    assert isinstance(migration_diagnostics, dict)
    assert migration_diagnostics.get("last_publish_status") == "failed"
    assert migration_diagnostics.get("last_publish_failure_category") == "provider_error"
    assert bool(summary.deploy_readiness.get("ready")) is False
    deploy_reasons = [str(item).lower() for item in summary.deploy_readiness.get("reasons", [])]
    assert any("published artifact is required before deploy" in reason for reason in deploy_reasons)


def test_deploy_omits_ga_input_when_analytics_mode_is_publish_only(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session, ga_measurement_id="G-SITE1234")
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "",
        },
        principal_id="principal-1",
    )
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
        },
        principal_id="principal-1",
    )
    service.update_analytics_config(
        business_id=business_id,
        site_id=site_id,
        analytics_config={
            "enabled": True,
            "ga_measurement_id": "G-WORK1234",
            "insertion_mode": "publish_only",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert "ga_measurement_id" not in deploy_target.inputs


def test_approve_twice_is_rejected(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved once",
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="already approved"):
        service.approve_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            approval_notes="Approved twice",
            principal_id="principal-1",
        )


def test_publish_duplicate_non_dry_run_is_rejected(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    with pytest.raises(SEOMigrationValidationError, match="already published"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 2


def test_publish_duplicate_request_logs_workflow_remediation_attempted(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="already published"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 2
    duplicate_failure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "publish"
        and record.__dict__["json_fields"].get("failure_category") == "duplicate_request"
    ]
    assert duplicate_failure_logs
    duplicate_target = duplicate_failure_logs[-1].get("target") or {}
    assert duplicate_target.get("workflow_remediation_attempted") is True
    assert duplicate_target.get("workflow_remediation_outcome") == "remediation_already_current"


def test_publish_propagates_deploy_secret_for_approved_managed_target(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key="{\"type\":\"service_account\",\"project_id\":\"acme\"}",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.secret_upsert_calls) == 1
    secret_call = publisher.secret_upsert_calls[0]
    assert secret_call[0] == "acme"
    assert secret_call[1] == "tnmfire-site"
    assert secret_call[2] == "GCP_DEPLOY_KEY"
    assert publish_result.result.get("deploy_secret_propagation_attempted") is True
    assert publish_result.result.get("deploy_secret_propagation_status") == "created"
    assert publish_result.result.get("deploy_secret_propagation_reason") is None
    assert publish_result.result.get("deploy_secret_propagation_source") == "runtime_env_fallback"


def test_publish_skips_deploy_secret_propagation_for_unapproved_target_owner(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key="{\"type\":\"service_account\",\"project_id\":\"acme\"}",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "repo_owner": "unapproved-owner",
            "repo_name": "tnmfire-site",
            "workflow_id": "deploy-tnmfire-www-prod.yml",
            "ref": "main",
        },
        deploy_config_field_names={"enabled", "repo_owner", "repo_name", "workflow_id", "ref"},
        principal_id="admin-principal",
        principal_role=PrincipalRole.ADMIN,
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert not publisher.secret_upsert_calls
    assert publish_result.result.get("deploy_secret_propagation_attempted") is False
    assert publish_result.result.get("deploy_secret_propagation_status") == "skipped_guardrail"
    assert publish_result.result.get("deploy_secret_propagation_reason") == "repo_owner_not_approved"
    assert publish_result.result.get("deploy_secret_propagation_source") == "runtime_env_fallback"


def test_publish_surfaces_deploy_secret_propagation_failure_without_blocking_publish(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        existing_workflow=True,
        fail_secret_propagation=True,
        secret_propagation_error_code="token_not_authorized",
        secret_propagation_error_message="Simulated token authorization failure.",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key="{\"type\":\"service_account\",\"project_id\":\"acme\"}",
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.secret_upsert_calls) == 1
    assert publish_result.workspace.publish_status == "published"
    assert publish_result.result.get("deploy_secret_propagation_attempted") is True
    assert publish_result.result.get("deploy_secret_propagation_status") == "failed"
    assert publish_result.result.get("deploy_secret_propagation_reason") == "token_not_authorized"
    assert publish_result.result.get("deploy_secret_propagation_source") == "runtime_env_fallback"
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    assert summary.publish_readiness.get("last_deploy_secret_propagation_status") == "failed"
    assert summary.publish_readiness.get("last_deploy_secret_propagation_reason") == "token_not_authorized"
    assert summary.publish_readiness.get("last_deploy_secret_propagation_source") == "runtime_env_fallback"


def test_publish_uses_admin_managed_deploy_secret_as_primary_source(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key='{"type":"service_account","project_id":"runtime-fallback"}',
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    service.github_publish_config_service.get_managed_gcp_deploy_key_status = lambda: {
        "configured": True,
        "updated_at": None,
        "source": "admin_managed_secret",
    }
    service.github_publish_config_service.get_managed_gcp_deploy_key_value = lambda: (
        '{"type":"service_account","project_id":"admin-managed"}'
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.secret_upsert_calls) == 1
    secret_call = publisher.secret_upsert_calls[0]
    assert secret_call[3] == '{"type":"service_account","project_id":"admin-managed"}'
    assert publish_result.result.get("deploy_secret_propagation_source") == "admin_managed_secret"


def test_publish_duplicate_repairs_missing_workflow_without_republishing_artifact(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=False)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    first_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert first_result.result.get("deploy_workflow_provisioned") is True
    assert len(publisher.publish_calls) == 1

    # Simulate historical drift where workflow file is missing despite prior published artifact.
    publisher.existing_workflow = False
    repair_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 2
    assert repair_result.result.get("duplicate_artifact_skipped") is True
    assert repair_result.result.get("deploy_workflow_provisioned") is True
    assert repair_result.result.get("workflow_provisioning_remediation_mode") == "duplicate_publish_repair"
    assert repair_result.result.get("workflow_provisioning_status") == "created"
    assert repair_result.result.get("workflow_provisioning_verified") is True
    assert repair_result.result.get("workflow_remediation_attempted") is True
    assert repair_result.result.get("workflow_remediation_outcome") == "remediation_upgraded_managed_placeholder"


def test_publish_duplicate_repairs_managed_placeholder_workflow_without_republishing_artifact(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 1

    # Simulate a managed placeholder drift on an already-published artifact target.
    publisher.existing_workflow = True
    publisher.existing_workflow_placeholder = True
    repair_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 2
    assert repair_result.result.get("duplicate_artifact_skipped") is True
    assert repair_result.result.get("deploy_workflow_provisioned") is True
    assert repair_result.result.get("workflow_provisioning_remediation_mode") == "duplicate_publish_repair"
    assert repair_result.result.get("workflow_provisioning_status") == "created"
    assert repair_result.result.get("workflow_provisioning_verified") is True
    assert repair_result.result.get("workflow_remediation_attempted") is True
    assert repair_result.result.get("workflow_remediation_outcome") == "remediation_upgraded_managed_placeholder"


def test_publish_duplicate_preserves_custom_workflow_and_reports_outcome(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(existing_workflow=True, existing_workflow_custom=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    with pytest.raises(SEOMigrationValidationError, match="already published"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert len(publisher.publish_calls) == 1
    assert len(publisher.workflow_provision_calls) == 2
    duplicate_failure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "publish"
        and record.__dict__["json_fields"].get("failure_category") == "duplicate_request"
    ]
    assert duplicate_failure_logs
    duplicate_target = duplicate_failure_logs[-1].get("target") or {}
    assert duplicate_target.get("workflow_remediation_attempted") is True
    assert duplicate_target.get("workflow_remediation_outcome") == "remediation_preserved_custom"


def test_publish_duplicate_write_failure_reports_remediation_write_failed(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(existing_workflow=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    publisher.fail_workflow_provision = True
    with pytest.raises(SEOMigrationValidationError, match="workflow provisioning failure"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    failure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "publish"
        and record.__dict__["json_fields"].get("status") == "failed"
        and record.__dict__["json_fields"].get("failure_category") == "target_invalid"
    ]
    assert failure_logs
    failure_target = failure_logs[-1].get("target") or {}
    assert failure_target.get("workflow_remediation_attempted") is True
    assert failure_target.get("workflow_remediation_outcome") == "remediation_write_failed"


def test_publish_fails_when_workflow_provisioning_fails(db_session) -> None:
    publisher = _RecordingGitHubPublisher(fail_workflow_provision=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="workflow provisioning failure"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    refreshed_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = refreshed_workspace.publish_history_json or []
    assert publish_history
    latest = publish_history[-1]
    assert latest.get("status") == "failed"
    assert latest.get("failure_category") == "target_invalid"
    assert latest.get("failure_reason") == "workflow_provision_failed"


def test_duplicate_publish_rejection_still_allows_deploy(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    with pytest.raises(SEOMigrationValidationError, match="already published"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.publish_calls) == 1
    assert len(publisher.deploy_calls) == 1


def test_deploy_duplicate_non_dry_run_is_rejected(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    with pytest.raises(SEOMigrationValidationError, match="already in progress"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert len(publisher.deploy_calls) == 1
    duplicate_failure_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "deploy"
        and record.__dict__["json_fields"].get("failure_category") == "duplicate_request"
    ]
    assert duplicate_failure_payloads
    duplicate_target = duplicate_failure_payloads[-1].get("target") or {}
    assert "blocking_post_dispatch_state" in duplicate_target
    assert "blocking_deploy_trace_id" in duplicate_target
    assert "blocking_stale_reference_field" in duplicate_target
    assert "blocking_stale_threshold_seconds" in duplicate_target
    assert duplicate_target.get("blocking_stale_threshold_seconds") == 120
    assert duplicate_target.get("blocking_stale_evaluated") is True
    assert duplicate_target.get("blocking_stale_is_stale") is False
    assert duplicate_target.get("blocking_treated_as_stale") is False
    deploy_logs = [record.msg for record in caplog.records if isinstance(record.msg, str)]
    assert any('"event": "dispatch_attempted_without_run"' in item for item in deploy_logs)


@pytest.mark.parametrize(
    "active_run_status",
    ("queued", "waiting", "requested", "pending", "in_progress", "running"),
)
def test_deploy_duplicate_blocks_for_active_workflow_run_status(db_session, active_run_status: str) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status=active_run_status,
        deploy_workflow_run_conclusion=None,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="already in progress"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert len(publisher.deploy_calls) == 1


@pytest.mark.parametrize("active_run_status", ("pending", "in_progress", "running"))
def test_deploy_retry_allowed_when_active_workflow_run_is_stale(
    db_session,
    caplog,
    active_run_status: str,
) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status=active_run_status,
        deploy_workflow_run_conclusion=None,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.deploy_history_json or []
    latest_deploy_item = next(
        (
            dict(item)
            for item in reversed(history)
            if str(item.get("action") or "").strip().lower() == "deploy"
            and str(item.get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert latest_deploy_item is not None
    stale_trace_id = str(latest_deploy_item.get("deploy_trace_id") or "")
    assert stale_trace_id
    latest_deploy_item["refreshed_at"] = None
    latest_deploy_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["timestamp"] = "2000-01-01T00:00:00+00:00"
    workspace.deploy_history_json = [latest_deploy_item]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.deploy_calls) == 2
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    stale_entry = next(
        (
            item
            for item in workspace.deploy_history_json or []
            if str(item.get("deploy_trace_id") or "") == stale_trace_id
        ),
        None,
    )
    assert stale_entry is not None
    assert stale_entry.get("post_dispatch_state") == "workflow_run_failed"
    assert stale_entry.get("workflow_run_status") == "completed"
    assert stale_entry.get("workflow_run_conclusion") == "failure"
    assert stale_entry.get("workflow_run_failure_reason_code") == "workflow_reconciliation_timeout"
    assert stale_entry.get("workflow_run_failure_stage") == "workflow_execution"
    assert stale_entry.get("workflow_job_failure_detected") is True
    deploy_logs = [record.msg for record in caplog.records if isinstance(record.msg, str)]
    assert any('"event": "downgrade_to_stale_active_deploy_blocker"' in item for item in deploy_logs)
    assert any('"event": "stale_duplicate_blocker_reconciled"' in item for item in deploy_logs)


def test_deploy_duplicate_active_run_uses_most_recent_activity_timestamp(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="pending",
        deploy_workflow_run_conclusion=None,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.deploy_history_json or []
    latest_deploy_item = next(
        (
            dict(item)
            for item in reversed(history)
            if str(item.get("action") or "").strip().lower() == "deploy"
            and str(item.get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert latest_deploy_item is not None
    latest_deploy_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["timestamp"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["refreshed_at"] = utc_now().isoformat()
    workspace.deploy_history_json = [latest_deploy_item]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(SEOMigrationValidationError, match="already in progress"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert len(publisher.deploy_calls) == 1


def test_deploy_retry_allowed_after_terminal_failed_run(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion="failure",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.deploy_calls) == 2


def test_deploy_retry_allowed_after_terminal_cancelled_run(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998801,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion="cancelled",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.deploy_calls) == 2


def test_deploy_retry_allowed_after_completed_run_without_conclusion(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=112233,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion=None,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.deploy_calls) == 2


def test_deploy_retry_allowed_when_no_run_record_is_stale(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.deploy_history_json or []
    assert history
    stale_item = next(
        (
            dict(item)
            for item in reversed(history)
            if str(item.get("action") or "").strip().lower() == "deploy"
            and str(item.get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert stale_item is not None
    stale_trace_id = str(stale_item.get("deploy_trace_id") or "")
    assert stale_trace_id
    stale_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["timestamp"] = "2000-01-01T00:00:00+00:00"
    workspace.deploy_history_json = [stale_item]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    latest_deploy_entry = next(
        (
            item
            for item in reversed(workspace.deploy_history_json or [])
            if str(item.get("action") or "").strip().lower() == "deploy"
            and str(item.get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert latest_deploy_entry is not None
    assert latest_deploy_entry.get("timestamp") == "2000-01-01T00:00:00+00:00"
    assert latest_deploy_entry.get("dispatched_at") == "2000-01-01T00:00:00+00:00"

    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.deploy_calls) == 2
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    stale_entry = next(
        (
            item
            for item in workspace.deploy_history_json or []
            if str(item.get("deploy_trace_id") or "") == stale_trace_id
        ),
        None,
    )
    assert stale_entry is not None
    assert stale_entry.get("post_dispatch_state") == "workflow_run_failed"
    assert stale_entry.get("workflow_run_status") == "completed"
    assert stale_entry.get("workflow_run_conclusion") == "failure"
    assert stale_entry.get("workflow_run_failure_reason_code") == "workflow_reconciliation_timeout"
    assert stale_entry.get("workflow_run_failure_stage") == "workflow_execution"
    assert stale_entry.get("workflow_job_failure_detected") is True
    deploy_logs = [record.msg for record in caplog.records if isinstance(record.msg, str)]
    assert any('"event": "downgrade_to_stale_unverified_dispatch"' in item for item in deploy_logs)
    assert any('"event": "stale_duplicate_blocker_reconciled"' in item for item in deploy_logs)


def test_deploy_duplicate_no_run_uses_most_recent_activity_timestamp(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.deploy_history_json or []
    assert history
    latest_deploy_index = next(
        (
            index
            for index in range(len(history) - 1, -1, -1)
            if str(history[index].get("action") or "").strip().lower() == "deploy"
            and str(history[index].get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert latest_deploy_index is not None
    latest_deploy_item = dict(history[latest_deploy_index])
    latest_deploy_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    latest_deploy_item["timestamp"] = utc_now().isoformat()
    history[latest_deploy_index] = latest_deploy_item
    workspace.deploy_history_json = history
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(SEOMigrationValidationError, match="already in progress"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert len(publisher.deploy_calls) == 1


def test_deploy_duplicate_gate_respects_target_tuple(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_config = dict(workspace.deploy_config_json or {})
    deploy_config["ref"] = "release"
    workspace.deploy_config_json = deploy_config
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert len(publisher.deploy_calls) == 2


def test_deploy_duplicate_gate_matches_active_record_via_configured_workflow_id(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.deploy_history_json or []
    assert history
    latest_deploy_index = next(
        (
            index
            for index in range(len(history) - 1, -1, -1)
            if str(history[index].get("action") or "").strip().lower() == "deploy"
            and str(history[index].get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert latest_deploy_index is not None
    mutated_item = dict(history[latest_deploy_index])
    mutated_item["workflow_id"] = "stale-workflow-id.yml"
    mutated_item["workflow_identifier_used"] = ".github/workflows/stale-workflow-id.yml"
    history[latest_deploy_index] = mutated_item
    workspace.deploy_history_json = history
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(SEOMigrationValidationError, match="already in progress"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert len(publisher.deploy_calls) == 1


def test_deploy_prefers_site_specific_workflow_when_workspace_config_is_stale(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        available_workflow_paths={
            ".github/workflows/deploy-www-prod.yml",
            ".github/workflows/deploy-tnmfire-www-prod.yml",
        }
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="stale-workflow.yml",
    )
    caplog.set_level("INFO", logger="app.services.seo_migration")
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.workflow_id == ".github/workflows/deploy-tnmfire-www-prod.yml"

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    last_deploy = deploy_history[-1]
    assert last_deploy.get("resolved_workflow_source") == "site_specific_workflow"
    assert last_deploy.get("workflow_id") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert last_deploy.get("workflow_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"

    resolution_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_deploy_workflow_resolution"
    ]
    assert resolution_payloads
    assert resolution_payloads[-1].get("resolved_workflow_source") == "site_specific_workflow"
    assert resolution_payloads[-1].get("workflow_id") == "deploy-tnmfire-www-prod.yml"


def test_deploy_prefers_site_specific_workflow_when_publish_history_is_stale(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        available_workflow_paths={
            ".github/workflows/deploy-www-prod.yml",
            ".github/workflows/deploy-tnmfire-www-prod.yml",
        }
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = list(workspace.publish_history_json or [])
    assert publish_history
    publish_history[-1] = {
        **dict(publish_history[-1]),
        "deploy_workflow_id": "stale-workflow-id.yml",
        "deploy_workflow_path": ".github/workflows/deploy-www-prod.yml",
    }
    workspace.publish_history_json = publish_history
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    caplog.set_level("INFO", logger="app.services.seo_migration")
    action_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.workflow_id == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_identifier_used") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_identifier_type_requested") == "workflow_id"
    assert action_result.result.get("workflow_identifier_type_used") == "workflow_file_path"
    assert action_result.result.get("workflow_dispatch_resolution_source") == "workflow_file_path"
    assert action_result.result.get("workflow_file_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_name") == "deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("resolved_workflow_source") == "site_specific_workflow"
    assert action_result.result.get("actual_dispatch_identifier_sent") == "deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("actual_dispatch_identifier_type_sent") == "workflow_id"
    assert action_result.result.get("workflow_conformance_checked") is True
    assert action_result.result.get("workflow_conformance_status") == "conformant"
    assert action_result.result.get("workflow_conformance_reasons") == []
    assert action_result.result.get("workflow_conformance_evidence_summary") == "managed_contract_markers_present"

    accepted_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_deploy_dispatch_accepted"
    ]
    assert accepted_payloads
    assert accepted_payloads[-1].get("workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert accepted_payloads[-1].get("workflow_identifier_used") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert accepted_payloads[-1].get("workflow_identifier_type_used") == "workflow_file_path"
    assert accepted_payloads[-1].get("workflow_dispatch_resolution_source") == "workflow_file_path"
    assert accepted_payloads[-1].get("actual_dispatch_identifier_sent") == "deploy-tnmfire-www-prod.yml"
    assert accepted_payloads[-1].get("actual_dispatch_identifier_type_sent") == "workflow_id"
    assert accepted_payloads[-1].get("workflow_conformance_checked") is True
    assert accepted_payloads[-1].get("workflow_conformance_status") == "conformant"
    assert accepted_payloads[-1].get("workflow_conformance_reasons") == []
    assert accepted_payloads[-1].get("workflow_conformance_evidence_summary") == "managed_contract_markers_present"
    preflight_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_deploy_dispatch_preflight"
    ]
    assert preflight_payloads
    assert preflight_payloads[-1].get("actual_dispatch_identifier_sent") == "deploy-tnmfire-www-prod.yml"
    assert preflight_payloads[-1].get("actual_dispatch_identifier_type_sent") == "workflow_id"
    assert preflight_payloads[-1].get("workflow_conformance_checked") is True
    assert preflight_payloads[-1].get("workflow_conformance_status") == "conformant"
    alignment_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_workflow_candidate_alignment"
    ]
    assert alignment_payloads
    assert alignment_payloads[-1].get("publish_resolved_workflow_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert alignment_payloads[-1].get("readiness_resolved_workflow_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert alignment_payloads[-1].get("publish_resolved_ref") == "main"
    assert alignment_payloads[-1].get("readiness_resolved_ref") == "main"
    assert alignment_payloads[-1].get("workflow_candidate_alignment_exact") is True
    assert alignment_payloads[-1].get("publish_history_workflow_path") == ".github/workflows/deploy-www-prod.yml"


def test_deploy_keeps_requested_workflow_identifier_when_history_workflow_path_missing(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = list(workspace.publish_history_json or [])
    assert publish_history
    publish_history[-1] = {
        **dict(publish_history[-1]),
        "deploy_workflow_id": "stale-workflow-id.yml",
        "deploy_workflow_path": None,
    }
    workspace.publish_history_json = publish_history
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    action_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.workflow_id == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_identifier_used") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert action_result.result.get("workflow_dispatch_resolution_source") == "workflow_file_path"


def test_deploy_prefers_site_specific_workflow_even_when_non_dispatchable(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        available_workflow_paths={".github/workflows/deploy-tnmfire-www-prod.yml"},
        non_dispatchable_workflow_paths={".github/workflows/deploy-tnmfire-www-prod.yml"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = list(workspace.publish_history_json or [])
    assert publish_history
    publish_history[-1] = {
        **dict(publish_history[-1]),
        "deploy_workflow_id": "stale-workflow-id.yml",
        "deploy_workflow_path": ".github/workflows/deploy-www-prod.yml",
    }
    workspace.publish_history_json = publish_history
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(SEOMigrationValidationError, match="not dispatchable"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert not publisher.deploy_calls
    updated_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = updated_workspace.deploy_history_json or []
    assert deploy_history
    last_failure = deploy_history[-1]
    assert last_failure.get("resolved_workflow_source") == "site_specific_workflow"
    assert last_failure.get("workflow_id") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert last_failure.get("workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert last_failure.get("workflow_identifier_used") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert last_failure.get("workflow_dispatch_resolution_source") == "workflow_file_path"
    assert last_failure.get("failure_reason") == "workflow_not_dispatchable"
    assert last_failure.get("failure_stage") == "workflow_lookup"
    assert last_failure.get("workflow_exists") is True
    assert (
        last_failure.get("failure_remediation_hint")
        == "Selected workflow exists but is not dispatchable for this deploy target."
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness
    assert deploy_readiness.get("last_failure_reason") == "workflow_not_dispatchable"
    assert deploy_readiness.get("last_failure_stage") == "workflow_lookup"
    assert deploy_readiness.get("last_workflow_exists") is True
    assert (
        deploy_readiness.get("last_failure_remediation_hint")
        == "Selected workflow exists but is not dispatchable for this deploy target."
    )
    assert deploy_readiness.get("last_failure_workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert deploy_readiness.get("last_failure_workflow_file_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert deploy_readiness.get("last_failure_workflow_exists") is True
    assert deploy_readiness.get("workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert deploy_readiness.get("workflow_identifier_used") == ".github/workflows/deploy-tnmfire-www-prod.yml"
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert (
        diagnostics.get("last_deploy_failure_remediation_hint")
        == "Selected workflow exists but is not dispatchable for this deploy target."
    )
    assert diagnostics.get("last_deploy_failure_workflow_identifier_requested") == "deploy-tnmfire-www-prod.yml"
    assert diagnostics.get("last_deploy_failure_workflow_file_path") == ".github/workflows/deploy-tnmfire-www-prod.yml"


@pytest.mark.parametrize(
    ("reason_code", "failure_stage", "expected_failure_category"),
    [
        ("repo_not_found", "repo_lookup", "target_invalid"),
        ("workflow_not_found", "workflow_lookup", "target_invalid"),
        ("branch_not_found_or_ref_invalid", "workflow_dispatch", "target_invalid"),
        ("workflow_dispatch_not_supported", "workflow_dispatch", "target_invalid"),
        ("token_not_authorized", "repo_lookup", "config_missing"),
    ],
)
def test_deploy_failure_reason_codes_are_recorded(
    db_session,
    caplog,
    reason_code: str,
    failure_stage: str,
    expected_failure_category: str,
) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_deploy=True,
        deploy_error_code=reason_code,
        deploy_error_message="Simulated deploy target failure.",
        deploy_error_stage=failure_stage,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError, match="Simulated deploy target failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    failed_entry = deploy_history[-1]
    assert failed_entry.get("status") == "failed"
    assert failed_entry.get("failure_category") == expected_failure_category
    assert failed_entry.get("failure_reason") == reason_code
    assert failed_entry.get("failure_stage") == failure_stage

    dispatch_failure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_deploy_dispatch_failed"
    ]
    assert dispatch_failure_logs
    assert dispatch_failure_logs[-1].get("failure_reason_code") == reason_code
    assert dispatch_failure_logs[-1].get("failure_stage") == failure_stage


def test_deploy_failure_without_known_mapping_omits_remediation_hint(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_deploy=True,
        deploy_error_code="github_request_failed",
        deploy_error_message="Simulated deploy failure.",
        deploy_error_stage="workflow_dispatch",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated deploy failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness
    assert deploy_readiness.get("last_failure_remediation_hint") is None
    diagnostics = (summary.context_summary or {}).get("migration_diagnostics") or {}
    assert diagnostics.get("last_deploy_failure_remediation_hint") is None


def test_publish_retry_after_failure_is_deterministic(db_session) -> None:
    publisher = _RecordingGitHubPublisher(fail_publish=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated publish failure."):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    publisher.fail_publish = False
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.publish_history_json or []
    assert [str(item.get("status")) for item in history[-2:]] == ["failed", "published"]
    assert workspace.publish_status == "published"
    assert workspace.last_published_commit_sha == "abc123"


def test_deploy_retry_after_failure_preserves_publish_state(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_deploy=True,
        available_workflow_paths={".github/workflows/deploy-www-prod.yml"},
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    workspace_after_publish = service.get_workspace(business_id=business_id, site_id=site_id)
    published_sha = workspace_after_publish.last_published_commit_sha

    with pytest.raises(SEOMigrationValidationError, match="Simulated deploy failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    workspace_after_failed_deploy = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace_after_failed_deploy.deploy_history_json or []
    assert workspace_after_failed_deploy.publish_status == "published"
    assert workspace_after_failed_deploy.last_published_commit_sha == published_sha
    assert workspace_after_failed_deploy.deploy_status == "deploy_failed"
    assert deploy_history
    last_failure = deploy_history[-1]
    assert last_failure.get("action") == "deploy"
    assert last_failure.get("status") == "failed"
    assert last_failure.get("workflow_id") == ".github/workflows/deploy-www-prod.yml"
    assert last_failure.get("ref") == "main"
    assert last_failure.get("error_summary") == "Simulated deploy failure."

    publisher.fail_deploy = False
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    workspace_after_retry = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history_after_retry = workspace_after_retry.deploy_history_json or []
    assert [str(item.get("status")) for item in deploy_history_after_retry[-2:]] == ["failed", "deploy_requested"]
    assert workspace_after_retry.publish_status == "published"
    assert workspace_after_retry.deploy_status == "deploy_requested"


def test_publish_rejects_reserved_git_root_path(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(
        service,
        business_id=business_id,
        site_id=site_id,
        artifact_root=".git/releases",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="artifact_root is invalid"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert not publisher.publish_calls


def test_deploy_uses_publish_history_workflow_when_workspace_workflow_path_is_invalid(db_session) -> None:
    publisher = _RecordingGitHubPublisher(available_workflow_paths={".github/workflows/deploy-www-prod.yml"})
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id=".github/workflows/deploy-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.workflow_id == ".github/workflows/deploy-www-prod.yml"
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    assert deploy_history[-1].get("resolved_workflow_source") == "publish_history_workflow"
    assert deploy_history[-1].get("workflow_id") == ".github/workflows/deploy-www-prod.yml"


def test_publish_analytics_insertion_collapses_duplicate_placeholders(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(
            _build_publishable_output(
                index_content=(
                    "<html><head><!-- ANALYTICS_PLACEHOLDER -->"
                    "<!-- ANALYTICS_PLACEHOLDER --></head><body>Draft</body></html>"
                )
            )
        ),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id="G-ABCD1234",
        principal_id="principal-1",
    )
    assert publisher.publish_calls
    _, published_files, _, _ = publisher.publish_calls[-1]
    index_file = next(item for item in published_files if item.path == "index.html")
    assert index_file.content.count("googletagmanager.com/gtag/js?id=G-ABCD1234") == 1
    assert index_file.content.count("gtag('config', 'G-ABCD1234');") == 1
    assert "ANALYTICS_PLACEHOLDER" not in index_file.content


def test_publish_dry_run_does_not_overwrite_published_state(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=True,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    updated_artifact = service.get_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
    )
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert updated_artifact.publish_status == "published"
    assert workspace.publish_status == "published"
    assert workspace.last_published_commit_sha == "abc123"
    publish_history = workspace.publish_history_json or []
    assert publish_history[-1].get("status") == "dry_run"


def test_publish_requires_admin_github_publish_config_enabled(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    config = service.github_publish_config_service.get()
    config.enabled = False
    service.github_publish_config_service.repository.save(config)
    service.session.commit()

    with pytest.raises(SEOMigrationValidationError, match="Admin has disabled GitHub publishing."):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    prereqs = summary.publish_readiness.get("config_prerequisites")
    assert isinstance(prereqs, dict)
    assert prereqs.get("admin_publish_configured") is False
    assert prereqs.get("admin_publish_config_enabled") is False
    publish_reasons = [str(item) for item in summary.publish_readiness.get("reasons", [])]
    assert "Admin has disabled GitHub publishing." in publish_reasons


def test_publish_requires_admin_github_publish_repository_configured(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    config = service.github_publish_config_service.get()
    config.repository = ""
    config.enabled = True
    service.github_publish_config_service.repository.save(config)
    service.session.commit()

    with pytest.raises(
        SEOMigrationValidationError,
        match="Admin must configure a GitHub publish target before publish is available.",
    ):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )


def test_publish_requires_operator_repository_when_workspace_publish_config_is_default(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    service.create_or_update_workspace(
        business_id=business_id,
        site_id=site_id,
        source_url="https://legacy.example/",
        operator_requirements={"business_objectives": ["Replace legacy site"]},
        enriched_content_notes={"replacement_summary": "Use richer replacement content."},
        principal_id="principal-1",
    )
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    with pytest.raises(
        SEOMigrationValidationError,
        match="Operator must configure a GitHub repository before publish is available.",
    ):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert not publisher.publish_calls
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    prereqs = summary.publish_readiness.get("config_prerequisites")
    assert isinstance(prereqs, dict)
    assert prereqs.get("operator_repository_configured") is False


def test_missing_publisher_config_is_categorized_for_readiness_and_errors(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="integration is unavailable"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    assert summary.publish_readiness.get("failure_category") == "config_missing"
    publish_prereqs = summary.publish_readiness.get("config_prerequisites")
    assert isinstance(publish_prereqs, dict)
    assert publish_prereqs.get("github_publisher_configured") is False
    assert publish_prereqs.get("github_publisher_reason_code") == "runtime_integration_unavailable"
    assert "integration is unavailable" in str(publish_prereqs.get("github_publisher_status_message") or "").lower()
    assert publish_prereqs.get("publish_runtime_available") is False
    assert summary.deploy_readiness.get("failure_category") == "config_missing"
    deploy_prereqs = summary.deploy_readiness.get("config_prerequisites")
    assert isinstance(deploy_prereqs, dict)
    assert deploy_prereqs.get("deploy_runtime_available") is False
    deploy_blocker_codes = summary.deploy_readiness.get("blocker_codes") or []
    assert "deploy_integration_unavailable" in deploy_blocker_codes


def test_runtime_credential_missing_reason_is_exposed_in_publish_readiness(db_session) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=MisconfiguredSEOMigrationGitHubPublisher(
            safe_message="GitHub publishing runtime credential is unavailable.",
            reason_code="runtime_credential_missing",
        ),
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    publish_prereqs = summary.publish_readiness.get("config_prerequisites")
    assert isinstance(publish_prereqs, dict)
    assert publish_prereqs.get("github_publisher_configured") is False
    assert publish_prereqs.get("github_publisher_reason_code") == "runtime_credential_missing"
    assert "credential is unavailable" in str(publish_prereqs.get("github_publisher_status_message") or "").lower()
    publish_reasons = [str(item).lower() for item in summary.publish_readiness.get("reasons", [])]
    assert any("credential is unavailable" in reason for reason in publish_reasons)


@pytest.mark.parametrize(
    ("dispatch_reason_code", "expected_reason_snippet"),
    [
        (
            "missing_cluster_name",
            "managed deploy target is missing required admin gke cluster name configuration",
        ),
        (
            "missing_cluster_location",
            "managed deploy target is missing required admin gke cluster location configuration",
        ),
        (
            "missing_gcp_project_id",
            "managed deploy target is missing required admin gke project id configuration",
        ),
    ],
)
def test_deploy_readiness_blocks_when_managed_gke_environment_config_is_missing(
    db_session,
    dispatch_reason_code: str,
    expected_reason_snippet: str,
) -> None:
    publisher = _RecordingGitHubPublisher(
        readiness_dispatch_service_availability=False,
        readiness_dispatch_service_reason_code=dispatch_reason_code,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("ready") is False
    assert deploy_readiness.get("dispatch_service_reason_code") == dispatch_reason_code
    deploy_reasons = [str(item).lower() for item in deploy_readiness.get("reasons", [])]
    assert any(expected_reason_snippet in item for item in deploy_reasons)
    assert "deploy_configuration_missing" in (deploy_readiness.get("blocker_codes") or [])
    deploy_prereqs = deploy_readiness.get("config_prerequisites") or {}
    assert deploy_prereqs.get("target_config_valid") is True
    assert deploy_prereqs.get("dispatch_service_reason_code") == dispatch_reason_code


def test_deploy_readiness_prioritizes_managed_gke_blocker_when_secret_propagation_runtime_credential_missing(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(
        readiness_dispatch_service_availability=False,
        readiness_dispatch_service_reason_code="missing_cluster_name",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key=None,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id="deploy-tnmfire-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert publish_result.result.get("deploy_secret_propagation_attempted") is False
    assert publish_result.result.get("deploy_secret_propagation_status") == "failed"
    assert publish_result.result.get("deploy_secret_propagation_reason") == "runtime_credential_missing"

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    publish_readiness = summary.publish_readiness or {}
    assert publish_readiness.get("last_deploy_secret_propagation_reason") == "runtime_credential_missing"

    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("ready") is False
    assert deploy_readiness.get("dispatch_service_reason_code") == "missing_cluster_name"
    deploy_reasons = [str(item).lower() for item in deploy_readiness.get("reasons", [])]
    assert any(
        "managed deploy target is missing required admin gke cluster name configuration" in item
        for item in deploy_reasons
    )
    assert "deploy_configuration_missing" in (deploy_readiness.get("blocker_codes") or [])


def test_runtime_publisher_readiness_log_includes_reason_code(db_session, caplog) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=MisconfiguredSEOMigrationGitHubPublisher(
            safe_message="GitHub publishing runtime credential is unavailable.",
            reason_code="runtime_credential_missing",
        ),
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    service.get_workspace_summary(business_id=business_id, site_id=site_id)

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
    ]
    runtime_events = [
        payload for payload in payloads if payload.get("event") == "seo_migration_runtime_publisher_readiness"
    ]
    assert runtime_events
    assert any(
        event.get("runtime_publisher_reason_code") == "runtime_credential_missing" and event.get("action") == "publish"
        for event in runtime_events
    )


def test_workspace_summary_includes_destination_summary_and_draft_preview_entry(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id, artifact_root="site")
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {"site_url": "https://tnmfire-www.example"},
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    assert isinstance(destination, dict)
    draft_preview = destination.get("draft_preview") or {}
    assert draft_preview.get("state") == "available"
    assert draft_preview.get("artifact_version_id") == artifact.id
    assert draft_preview.get("entry_path") == "index.html"

    publish_destination = destination.get("publish_destination") or {}
    assert publish_destination.get("state") == "configured"
    assert publish_destination.get("repository") == "acme/tnmfire-site"
    assert publish_destination.get("expected_location") == "acme/tnmfire-site@main:/site"
    assert publish_destination.get("expected_url") == "https://github.com/acme/tnmfire-site/tree/main/site"
    assert publish_destination.get("expected_publish_url") == "https://tnmfire-www.example"
    assert publish_destination.get("url_source") == "deterministic_target_config"
    assert publish_destination.get("url_source_detail") == "deploy_input:site_url"

    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_destination.get("state") == "expected_after_deploy"
    assert deploy_destination.get("expected_publish_url") == "https://tnmfire-www.example"
    assert deploy_destination.get("resolved_live_url") is None
    assert deploy_destination.get("expected_url") == "https://tnmfire-www.example"
    assert deploy_destination.get("url_source") == "deterministic_target_config"
    assert deploy_destination.get("url_source_detail") == "deploy_input:site_url"


def test_workspace_summary_handles_legacy_history_without_url_fields(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    workspace = _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "inputs": {},
        },
        principal_id="principal-1",
    )
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.publish_history_json = [
        {
            "action": "publish",
            "status": "published",
            "artifact_version_id": "legacy-artifact-1",
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "dry_run": False,
        }
    ]
    workspace.deploy_history_json = [
        {
            "action": "deploy",
            "status": "deploy_requested",
            "artifact_version_id": "legacy-artifact-1",
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
            "dry_run": False,
        }
    ]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    publish_destination = destination.get("publish_destination") or {}
    deploy_destination = destination.get("deploy_destination") or {}

    assert publish_destination.get("expected_publish_url") is None
    assert publish_destination.get("url_source") == "unknown"
    assert deploy_destination.get("resolved_live_url") is None
    assert deploy_destination.get("url_source") == "unknown"


def test_delete_artifact_version_deletes_eligible_draft_and_recomputes_workspace(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    result = service.delete_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )

    assert result.deleted_artifact_version_id == artifact.id
    assert result.deleted_artifact_version_number == artifact.version
    workspace = result.workspace
    assert workspace.latest_generated_artifact_version_id is None
    assert workspace.latest_generated_artifact_version_number is None
    assert workspace.latest_approved_artifact_version_id is None
    assert workspace.latest_approved_artifact_version_number is None
    assert workspace.migration_status == "draft"
    artifacts = service.list_artifact_versions(business_id=business_id, site_id=site_id)
    assert artifacts == []


def test_delete_artifact_version_blocks_when_publish_history_references_artifact(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.publish_history_json = [
        {
            "action": "publish",
            "artifact_version_id": artifact.id,
            "status": "failed",
            "timestamp": utc_now().isoformat(),
        }
    ]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(SEOMigrationValidationError, match="publish history cannot be deleted"):
        service.delete_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            principal_id="principal-1",
        )


def test_publish_deploy_emit_structured_control_plane_logs(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_output={"live_url": "https://workflow-live.tnmfire.com"},
        deploy_workflow_run_id=998877,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion="success",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved",
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
    ]
    assert payloads
    for payload in payloads:
        assert payload.get("business_id") == business_id
        assert payload.get("site_id") == site_id
        assert payload.get("workspace_id")
        assert payload.get("artifact_version_id") == artifact.id
        assert isinstance(payload.get("timestamp"), str)
        assert isinstance(payload.get("target"), dict)
        assert "failure_category" in payload
    assert any(payload.get("action") == "approve" and payload.get("status") == "requested" for payload in payloads)
    assert any(
        payload.get("action") == "approve"
        and payload.get("status") == "completed"
        and isinstance(payload.get("duration_ms"), int)
        for payload in payloads
    )
    assert any(
        payload.get("action") == "publish"
        and payload.get("status") == "completed"
        and isinstance(payload.get("target"), dict)
        and payload.get("target", {}).get("repo_owner") == "acme"
        and "expected_publish_url" in payload.get("target", {})
        and "url_source" in payload.get("target", {})
        for payload in payloads
    )
    assert any(
        payload.get("action") == "deploy"
        and payload.get("status") == "completed"
        and isinstance(payload.get("target"), dict)
        and payload.get("target", {}).get("workflow_id") == ".github/workflows/deploy-tnmfire-www-prod.yml"
        and "resolved_live_url" in payload.get("target", {})
        and "url_source" in payload.get("target", {})
        for payload in payloads
    )
    service_events = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
    ]
    readiness_events = [
        payload for payload in service_events if payload.get("event") == "seo_migration_target_readiness_check"
    ]
    assert readiness_events
    assert any(
        payload.get("repo_exists") is True
        and payload.get("ref_exists") is True
        and payload.get("workflow_exists") is True
        and payload.get("workflow_dispatch_ready") is True
        and payload.get("workflow_dispatch_supported") is True
        and "workflow_dispatch" in (payload.get("workflow_trigger_types") or [])
        and payload.get("dispatch_identifier_type") == "workflow_file_path"
        and payload.get("remediation_mode") == "none"
        for payload in readiness_events
    )
    assert any(
        payload.get("event") == "seo_migration_workflow_run_lookup_attempted"
        and payload.get("workflow_run_id") is not None
        and payload.get("workflow_run_status")
        and payload.get("workflow_inputs_configured_keys") == []
        and payload.get("workflow_inputs_sent_keys") == []
        and payload.get("workflow_run_lookup_attempted") is True
        and payload.get("workflow_run_found") is True
        and payload.get("workflow_job_failure_detected") is False
        and payload.get("post_dispatch_state") == "workflow_run_succeeded_with_live_url"
        for payload in service_events
    )
    assert any(
        payload.get("event") == "seo_migration_workflow_output_url_captured"
        and payload.get("url_source") == "workflow_output"
        and payload.get("resolved_live_url") == "https://workflow-live.tnmfire.com"
        for payload in service_events
    )


def test_deploy_failure_logs_failure_category(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(fail_deploy=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError, match="Simulated deploy failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
    ]
    assert any(
        payload.get("action") == "deploy"
        and payload.get("status") == "failed"
        and payload.get("failure_category") == "deploy_error"
        and payload.get("failure_reason") == "Simulated deploy failure."
        for payload in payloads
    )


def test_deploy_logs_distinguish_trigger_support_from_dispatch_service_availability(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_deploy=True,
        deploy_error_code="workflow_dispatch_not_supported",
        deploy_error_message="Workflow dispatch rejected.",
        deploy_error_stage="workflow_dispatch",
        readiness_workflow_dispatch_supported=True,
        readiness_workflow_trigger_types=("workflow_dispatch",),
        readiness_dispatch_service_availability=False,
        readiness_dispatch_service_reason_code="runtime_unavailable",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    caplog.set_level("INFO", logger="app.services.seo_migration")

    with pytest.raises(SEOMigrationValidationError, match="Workflow dispatch rejected."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    event_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
    ]
    readiness_events = [
        payload for payload in event_payloads if payload.get("event") == "seo_migration_target_readiness_check"
    ]
    assert readiness_events
    assert any(
        payload.get("workflow_dispatch_supported") is True
        and "workflow_dispatch" in (payload.get("workflow_trigger_types") or [])
        and payload.get("dispatch_service_availability") is False
        and payload.get("dispatch_service_reason_code") == "runtime_unavailable"
        and payload.get("dispatch_identifier_type") == "workflow_file_path"
        for payload in readiness_events
    )

    control_plane_payloads = [
        payload
        for payload in event_payloads
        if payload.get("event") == "seo_migration_control_plane_action"
        and payload.get("action") == "deploy"
        and payload.get("status") == "failed"
    ]
    assert control_plane_payloads
    assert any(
        isinstance(payload.get("target"), dict)
        and payload.get("target", {}).get("dispatch_service_availability") is False
        and payload.get("target", {}).get("dispatch_service_reason_code") == "runtime_unavailable"
        and payload.get("target", {}).get("dispatch_result_stage") == "workflow_dispatch"
        and payload.get("target", {}).get("post_conformance_stage") == "workflow_dispatch_failed"
        and payload.get("target", {}).get("post_conformance_reason_text")
        == "GitHub workflow dispatch rejected by API."
        and payload.get("target", {}).get("failure_reason_code") == "workflow_dispatch_not_supported"
        and isinstance(payload.get("target", {}).get("deploy_trace_id"), str)
        and payload.get("target", {}).get("deploy_trace_id")
        for payload in control_plane_payloads
    )

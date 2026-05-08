from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
    SEOMigrationGitHubImagePullSecretProvisionResult,
    SEOMigrationGitHubLiveRuntimeProbeResult,
    SEOMigrationGitHubManagedSiteDnsEnsureResult,
    SEOMigrationGitHubManagedSiteStaticIPEnsureResult,
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
from app.models.seo_competitor_domain import SEOCompetitorDomain
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
from app.services.seo_migration_artifact_quality import evaluate_migration_artifact_quality
from app.services.seo_migration_context import SEOMigrationContextAssembler
from app.services.seo_migration_ingest import SEOMigrationSourceIngestService
from app.services.github_publish_config import GitHubPublishConfigService
from app.services import seo_migration as seo_migration_module

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


class _ContextCaptureMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, output: SEOMigrationArtifactGenerationOutput) -> None:
        self.output = output
        self.last_context: dict[str, object] | None = None

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        self.last_context = dict(migration_context)
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
        existing_repository: bool = True,
        ensure_repository_error_code: str | None = None,
        ensure_repository_error_message: str | None = None,
        ensure_repository_error_stage: str | None = None,
        fail_publish: bool = False,
        publish_error_code: str | None = None,
        publish_error_message: str | None = None,
        publish_error_stage: str | None = None,
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
        fail_current_live_probe: bool = False,
        current_live_probe_error_code: str | None = None,
        current_live_probe_error_message: str | None = None,
        current_live_probe_error_stage: str | None = None,
        current_live_probe_result: dict[str, object] | None = None,
        deploy_error_code: str | None = None,
        deploy_error_message: str | None = None,
        deploy_error_stage: str | None = None,
        fail_workflow_provision: bool = False,
        workflow_provision_error_code: str | None = None,
        workflow_provision_error_message: str | None = None,
        workflow_provision_error_stage: str | None = None,
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
        readiness_workflow_integrity_status: str | None = None,
        readiness_workflow_integrity_reason_code: str | None = None,
        available_workflow_paths: set[str] | None = None,
        non_dispatchable_workflow_paths: set[str] | None = None,
        non_production_ready_workflow_paths: set[str] | None = None,
        fail_secret_propagation: bool = False,
        secret_propagation_error_code: str | None = None,
        secret_propagation_error_message: str | None = None,
        secret_propagation_error_stage: str | None = None,
        existing_deploy_secret: bool = False,
        preflight_status: str | None = None,
        preflight_blocker_code: str | None = None,
        preflight_target_ref_exists: bool | None = None,
        preflight_repo_initialized: bool | None = None,
        preflight_can_read_contents: bool | None = None,
        preflight_can_write_contents: bool | None = None,
        preflight_can_write_workflows: bool | None = None,
        preflight_would_bootstrap_branch: bool | None = None,
        fail_adoption: bool = False,
        adoption_error_code: str | None = None,
        adoption_error_message: str | None = None,
        adoption_error_stage: str | None = None,
        adoption_marker_written: bool = True,
        adoption_outcome: str = "marker_written",
        adoption_management_status: str = "managed_marker_match",
        fail_static_ip_ensure: bool = False,
        static_ip_ensure_error_code: str | None = None,
        static_ip_ensure_error_message: str | None = None,
        static_ip_ensure_error_stage: str | None = None,
        static_ip_ensure_error_diagnostics: dict[str, object] | None = None,
        ensure_static_ip_name: str | None = None,
        ensure_static_ip_address: str | None = "34.149.170.250",
        ensure_static_ip_addresses: tuple[str | None, ...] | list[str | None] | None = None,
        ensure_static_ip_created: bool = False,
        ensure_static_ip_result: str = "exists",
        ensure_static_ip_project_id: str | None = None,
        ensure_static_ip_credential_source: str | None = None,
        ensure_static_ip_principal_email: str | None = None,
        ensure_static_ip_impersonated_service_account_email: str | None = None,
        fail_dns_ensure: bool = False,
        dns_ensure_error_code: str | None = None,
        dns_ensure_error_message: str | None = None,
        dns_ensure_error_stage: str | None = None,
        ensure_dns_hostname: str | None = None,
        ensure_dns_managed_zone: str = "sites",
        ensure_dns_project_id: str | None = None,
        ensure_dns_expected_ip: str | None = None,
        ensure_dns_previous_ips: tuple[str, ...] | list[str] | None = None,
        ensure_dns_created: bool = False,
        ensure_dns_updated: bool = False,
        ensure_dns_ttl: int = 300,
        ensure_dns_result: str = "exists",
        ensure_dns_credential_source: str | None = None,
        ensure_dns_principal_email: str | None = None,
        ensure_dns_impersonated_service_account_email: str | None = None,
    ) -> None:
        self.existing_repository = existing_repository
        self.ensure_repository_error_code = ensure_repository_error_code
        self.ensure_repository_error_message = ensure_repository_error_message
        self.ensure_repository_error_stage = ensure_repository_error_stage
        self.fail_publish = fail_publish
        self.publish_error_code = publish_error_code
        self.publish_error_message = publish_error_message
        self.publish_error_stage = publish_error_stage
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
        self.fail_current_live_probe = fail_current_live_probe
        self.current_live_probe_error_code = current_live_probe_error_code
        self.current_live_probe_error_message = current_live_probe_error_message
        self.current_live_probe_error_stage = current_live_probe_error_stage
        self.current_live_probe_result = dict(current_live_probe_result or {})
        self.deploy_error_code = deploy_error_code
        self.deploy_error_message = deploy_error_message
        self.deploy_error_stage = deploy_error_stage
        self.fail_workflow_provision = fail_workflow_provision
        self.workflow_provision_error_code = workflow_provision_error_code
        self.workflow_provision_error_message = workflow_provision_error_message
        self.workflow_provision_error_stage = workflow_provision_error_stage
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
        self.readiness_workflow_integrity_status = readiness_workflow_integrity_status
        self.readiness_workflow_integrity_reason_code = readiness_workflow_integrity_reason_code
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
        self.preflight_status = preflight_status
        self.preflight_blocker_code = preflight_blocker_code
        self.preflight_target_ref_exists = preflight_target_ref_exists
        self.preflight_repo_initialized = preflight_repo_initialized
        self.preflight_can_read_contents = preflight_can_read_contents
        self.preflight_can_write_contents = preflight_can_write_contents
        self.preflight_can_write_workflows = preflight_can_write_workflows
        self.preflight_would_bootstrap_branch = preflight_would_bootstrap_branch
        self.fail_adoption = fail_adoption
        self.adoption_error_code = adoption_error_code
        self.adoption_error_message = adoption_error_message
        self.adoption_error_stage = adoption_error_stage
        self.adoption_marker_written = adoption_marker_written
        self.adoption_outcome = adoption_outcome
        self.adoption_management_status = adoption_management_status
        self.fail_static_ip_ensure = fail_static_ip_ensure
        self.static_ip_ensure_error_code = static_ip_ensure_error_code
        self.static_ip_ensure_error_message = static_ip_ensure_error_message
        self.static_ip_ensure_error_stage = static_ip_ensure_error_stage
        self.static_ip_ensure_error_diagnostics = (
            dict(static_ip_ensure_error_diagnostics)
            if isinstance(static_ip_ensure_error_diagnostics, dict)
            else None
        )
        self.ensure_static_ip_name = ensure_static_ip_name
        self.ensure_static_ip_address = ensure_static_ip_address
        self.ensure_static_ip_addresses = list(ensure_static_ip_addresses or ())
        self.ensure_static_ip_call_count = 0
        self.ensure_static_ip_created = ensure_static_ip_created
        self.ensure_static_ip_result = ensure_static_ip_result
        self.ensure_static_ip_project_id = ensure_static_ip_project_id
        self.ensure_static_ip_credential_source = ensure_static_ip_credential_source
        self.ensure_static_ip_principal_email = ensure_static_ip_principal_email
        self.ensure_static_ip_impersonated_service_account_email = ensure_static_ip_impersonated_service_account_email
        self.fail_dns_ensure = fail_dns_ensure
        self.dns_ensure_error_code = dns_ensure_error_code
        self.dns_ensure_error_message = dns_ensure_error_message
        self.dns_ensure_error_stage = dns_ensure_error_stage
        self.ensure_dns_hostname = ensure_dns_hostname
        self.ensure_dns_managed_zone = ensure_dns_managed_zone
        self.ensure_dns_project_id = ensure_dns_project_id
        self.ensure_dns_expected_ip = ensure_dns_expected_ip
        self.ensure_dns_previous_ips = tuple(ensure_dns_previous_ips or ())
        self.ensure_dns_created = ensure_dns_created
        self.ensure_dns_updated = ensure_dns_updated
        self.ensure_dns_ttl = ensure_dns_ttl
        self.ensure_dns_result = ensure_dns_result
        self.ensure_dns_credential_source = ensure_dns_credential_source
        self.ensure_dns_principal_email = ensure_dns_principal_email
        self.ensure_dns_impersonated_service_account_email = ensure_dns_impersonated_service_account_email
        self.publish_calls: list[
            tuple[SEOMigrationGitHubPublishTarget, list[SEOMigrationGitHubPublishFile], str, bool]
        ] = []
        self.ensure_repository_calls: list[tuple[str, str, bool, bool, str | None, bool]] = []
        self.deploy_calls: list[tuple[SEOMigrationGitHubDeployTarget, bool]] = []
        self.deploy_managed_gke_configs: list[dict[str, object] | None] = []
        self.deploy_managed_image_pull_secret_configs: list[dict[str, object] | None] = []
        self.provision_managed_image_pull_secret_calls: list[
            tuple[str, str, str, str, dict[str, object] | None, str | None, str | None, str | None, str | None, bool]
        ] = []
        self.ensure_managed_site_static_ip_calls: list[
            tuple[str, str, str | None, dict[str, object] | None, str | None, bool]
        ] = []
        self.ensure_managed_site_dns_calls: list[
            tuple[str, str, str, str, str | None, int, bool]
        ] = []
        self.deploy_call_order: list[str] = []
        self.refresh_calls: list[tuple[SEOMigrationGitHubDeployTarget, int, str | None]] = []
        self.current_live_probe_calls: list[str] = []
        self.lookup_calls: list[tuple[SEOMigrationGitHubDeployTarget, str | None]] = []
        self.secret_upsert_calls: list[tuple[str, str, str, str]] = []
        self.publish_preflight_calls: list[
            tuple[str, str, str, bool, str | None, str | None, str | None]
        ] = []
        self.adopt_repository_calls: list[
            tuple[str, str, str, str, str, str | None, str | None]
        ] = []
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
        self.ensure_repository_calls.append(
            (
                repo_owner,
                repo_name,
                bool(auto_create_enabled),
                bool(create_if_missing),
                expected_owner,
                bool(private_by_default),
            )
        )
        if self.ensure_repository_error_code:
            raise SEOMigrationGitHubPublisherError(
                code=self.ensure_repository_error_code,
                safe_message=self.ensure_repository_error_message or "Simulated repository ensure failure.",
                stage=self.ensure_repository_error_stage or "repo_create",
            )
        if self.existing_repository:
            return SEOMigrationGitHubRepositoryEnsureResult(
                repo_owner=repo_owner,
                repo_name=repo_name,
                exists=True,
                auto_create_enabled=bool(auto_create_enabled),
                auto_create_attempted=False,
                auto_create_created=False,
                outcome="repo_exists",
                skipped_reason=None,
            )
        if bool(create_if_missing) and not bool(auto_create_enabled):
            raise SEOMigrationGitHubPublisherError(
                code="repo_auto_create_disabled",
                safe_message=(
                    "GitHub repository target was not found and repository auto-create is disabled in admin settings."
                ),
                stage="repo_create",
            )
        if bool(create_if_missing) and bool(auto_create_enabled):
            self.existing_repository = True
            return SEOMigrationGitHubRepositoryEnsureResult(
                repo_owner=repo_owner,
                repo_name=repo_name,
                exists=True,
                auto_create_enabled=True,
                auto_create_attempted=True,
                auto_create_created=True,
                outcome="repo_created",
                skipped_reason=None,
            )
        skipped_reason = "check_only" if not bool(create_if_missing) else "policy_disabled"
        return SEOMigrationGitHubRepositoryEnsureResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            exists=False,
            auto_create_enabled=bool(auto_create_enabled),
            auto_create_attempted=False,
            auto_create_created=False,
            outcome="repo_missing",
            skipped_reason=skipped_reason,
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
        self.publish_preflight_calls.append(
            (
                repo_owner,
                repo_name,
                target_ref,
                bool(auto_create_enabled),
                expected_owner,
                expected_business_id,
                expected_site_id,
            )
        )
        repo_status = self.ensure_repository(
            repo_owner=repo_owner,
            repo_name=repo_name,
            auto_create_enabled=bool(auto_create_enabled),
            create_if_missing=False,
            expected_owner=expected_owner,
        )
        repo_exists = bool(repo_status.exists)
        target_ref_exists = (
            bool(self.preflight_target_ref_exists)
            if self.preflight_target_ref_exists is not None
            else repo_exists
        )
        can_read_contents = (
            bool(self.preflight_can_read_contents)
            if self.preflight_can_read_contents is not None
            else repo_exists
        )
        can_write_contents = (
            bool(self.preflight_can_write_contents)
            if self.preflight_can_write_contents is not None
            else repo_exists
        )
        can_write_workflows = (
            bool(self.preflight_can_write_workflows)
            if self.preflight_can_write_workflows is not None
            else can_write_contents
        )
        repo_initialized = (
            bool(self.preflight_repo_initialized)
            if self.preflight_repo_initialized is not None
            else target_ref_exists
        )
        would_bootstrap_branch = (
            bool(self.preflight_would_bootstrap_branch)
            if self.preflight_would_bootstrap_branch is not None
            else bool(repo_exists and (not target_ref_exists) and can_write_contents)
        )
        would_auto_create_repo = bool((not repo_exists) and bool(auto_create_enabled))
        repo_ensure_outcome = (
            "exists"
            if repo_exists
            else ("would_create_on_publish" if bool(auto_create_enabled) else "skipped_policy_disabled")
        )
        preflight_blocker_code = str(self.preflight_blocker_code or "").strip().lower() or None
        preflight_status = str(self.preflight_status or "").strip().lower() or None
        if preflight_status is None:
            if preflight_blocker_code:
                preflight_status = "blocked"
            elif would_auto_create_repo or would_bootstrap_branch:
                preflight_status = "ready_with_actions"
            else:
                preflight_status = "ready"
        return SEOMigrationGitHubPublishPreflightResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            target_ref=target_ref,
            repo_exists=repo_exists,
            repo_ensure_outcome=repo_ensure_outcome,
            target_ref_exists=target_ref_exists,
            repo_initialized=repo_initialized,
            can_read_contents=can_read_contents,
            can_write_contents=can_write_contents,
            can_write_workflows=can_write_workflows,
            would_auto_create_repo=would_auto_create_repo,
            would_bootstrap_branch=would_bootstrap_branch,
            preflight_status=preflight_status,
            preflight_blocker_code=preflight_blocker_code,
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
        if self.fail_adoption or self.adoption_error_code:
            raise SEOMigrationGitHubPublisherError(
                code=self.adoption_error_code or "github_repo_adoption_failed",
                safe_message=self.adoption_error_message or "Simulated repository adoption failure.",
                stage=self.adoption_error_stage or "repo_adoption",
            )
        return SEOMigrationGitHubRepoAdoptionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=ref,
            marker_written=bool(self.adoption_marker_written),
            adoption_outcome=self.adoption_outcome,
            management_status=self.adoption_management_status,
            marker_business_id=business_id,
            marker_site_id=site_id,
        )

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
                code=self.publish_error_code or "publish_failed",
                safe_message=self.publish_error_message or "Simulated publish failure.",
                stage=self.publish_error_stage,
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
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        self.deploy_managed_gke_configs.append(dict(managed_gke_config or {}) or None)
        self.deploy_managed_image_pull_secret_configs.append(
            dict(managed_image_pull_secret_config or {}) or None
        )
        self.deploy_calls.append((target, dry_run))
        self.deploy_call_order.append("dispatch_deploy")
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
        self.provision_managed_image_pull_secret_calls.append(
            (
                repo_owner,
                repo_name,
                ref,
                kubernetes_namespace,
                dict(managed_gke_config or {}) or None,
                git_userid,
                git_email,
                git_token,
                gcp_deploy_key,
                bool(dry_run),
            )
        )
        return SEOMigrationGitHubImagePullSecretProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            namespace=kubernetes_namespace,
            secret_name="ghcr-pull-secret",
            action="dry_run" if dry_run else "updated",
        )

    def ensure_managed_site_static_ip(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        site_id: str | None,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        dry_run: bool = False,
    ) -> SEOMigrationGitHubManagedSiteStaticIPEnsureResult:
        self.ensure_managed_site_static_ip_calls.append(
            (
                repo_owner,
                repo_name,
                site_id,
                dict(managed_gke_config or {}) or None,
                gcp_deploy_key,
                bool(dry_run),
            )
        )
        self.deploy_call_order.append("ensure_static_ip")
        if self.fail_static_ip_ensure or self.static_ip_ensure_error_code:
            raise SEOMigrationGitHubPublisherError(
                code=self.static_ip_ensure_error_code or "managed_site_static_ip_provisioning_failed",
                safe_message=self.static_ip_ensure_error_message or "Simulated managed-site static IP ensure failure.",
                stage=self.static_ip_ensure_error_stage or "static_ip_provision",
                diagnostics=self.static_ip_ensure_error_diagnostics,
            )
        static_ip_name = self.ensure_static_ip_name
        if not static_ip_name:
            static_ip_name, _ = derive_site_preview_static_ip_name(
                repo_name=repo_name,
                site_id=site_id,
            )
        project_id = self.ensure_static_ip_project_id or str((managed_gke_config or {}).get("project_id") or "")
        if not project_id:
            project_id = "mbsrn-prod"
        static_ip_address = self.ensure_static_ip_address
        if self.ensure_static_ip_call_count < len(self.ensure_static_ip_addresses):
            static_ip_address = self.ensure_static_ip_addresses[self.ensure_static_ip_call_count]
        self.ensure_static_ip_call_count += 1
        return SEOMigrationGitHubManagedSiteStaticIPEnsureResult(
            static_ip_name=static_ip_name,
            static_ip_address=static_ip_address,
            static_ip_created=bool(self.ensure_static_ip_created),
            gcp_project_id=project_id,
            result=self.ensure_static_ip_result,
            gcp_credential_source=self.ensure_static_ip_credential_source,
            gcp_principal_email=self.ensure_static_ip_principal_email,
            gcp_impersonated_service_account_email=self.ensure_static_ip_impersonated_service_account_email,
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
        self.ensure_managed_site_dns_calls.append(
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
        self.deploy_call_order.append("ensure_dns")
        if self.fail_dns_ensure or self.dns_ensure_error_code:
            raise SEOMigrationGitHubPublisherError(
                code=self.dns_ensure_error_code or "managed_site_dns_provisioning_failed",
                safe_message=self.dns_ensure_error_message or "Simulated managed-site DNS ensure failure.",
                stage=self.dns_ensure_error_stage or "dns_provision",
            )
        dns_record_name = str((self.ensure_dns_hostname or preview_hostname).strip() or preview_hostname).rstrip(".")
        dns_record_name = f"{dns_record_name}."
        dns_expected_ip = str((self.ensure_dns_expected_ip or expected_ip_address).strip() or expected_ip_address)
        return SEOMigrationGitHubManagedSiteDnsEnsureResult(
            dns_record_name=dns_record_name,
            dns_record_type="A",
            dns_managed_zone=str((self.ensure_dns_managed_zone or dns_managed_zone).strip() or dns_managed_zone),
            dns_project_id=str((self.ensure_dns_project_id or dns_project_id).strip() or dns_project_id),
            dns_expected_ip=dns_expected_ip,
            dns_previous_ips=tuple(self.ensure_dns_previous_ips),
            dns_updated=bool(self.ensure_dns_updated),
            dns_created=bool(self.ensure_dns_created),
            dns_ttl=int(self.ensure_dns_ttl),
            result=str(self.ensure_dns_result or "exists"),
            gcp_credential_source=self.ensure_dns_credential_source,
            gcp_principal_email=self.ensure_dns_principal_email,
            gcp_impersonated_service_account_email=self.ensure_dns_impersonated_service_account_email,
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

    def probe_live_runtime_https(
        self,
        *,
        probe_url: str,
    ) -> SEOMigrationGitHubLiveRuntimeProbeResult | None:
        self.current_live_probe_calls.append(probe_url)
        if self.fail_current_live_probe or self.current_live_probe_error_code:
            raise SEOMigrationGitHubPublisherError(
                code=self.current_live_probe_error_code or "https_probe_failed_after_control_plane_ready",
                safe_message=self.current_live_probe_error_message or "Simulated current live probe failure.",
                stage=self.current_live_probe_error_stage or "ingress_evidence",
            )
        if not self.current_live_probe_result:
            return None
        probe_checked_at = str(
            self.current_live_probe_result.get("checked_at")
            or self.current_live_probe_result.get("current_live_evidence_checked_at")
            or "2026-04-07T12:15:00+00:00"
        )
        status_code_raw = self.current_live_probe_result.get("https_probe_status_code")
        if not isinstance(status_code_raw, int):
            status_code_raw = self.current_live_probe_result.get("current_https_probe_status_code")
        status_code = int(status_code_raw) if isinstance(status_code_raw, int) and status_code_raw > 0 else None
        return SEOMigrationGitHubLiveRuntimeProbeResult(
            probe_url=str(self.current_live_probe_result.get("probe_url") or probe_url),
            checked_at=probe_checked_at,
            source=str(
                self.current_live_probe_result.get("source")
                or self.current_live_probe_result.get("current_live_evidence_source")
                or "current_live_probe"
            ),
            live_url=str(
                self.current_live_probe_result.get("live_url")
                or self.current_live_probe_result.get("current_live_url")
                or ""
            )
            or None,
            host_reachable=(
                bool(self.current_live_probe_result.get("host_reachable"))
                if isinstance(self.current_live_probe_result.get("host_reachable"), bool)
                else (
                    bool(self.current_live_probe_result.get("current_host_reachable"))
                    if isinstance(self.current_live_probe_result.get("current_host_reachable"), bool)
                    else None
                )
            ),
            host_reachability_scheme=str(
                self.current_live_probe_result.get("host_reachability_scheme")
                or self.current_live_probe_result.get("current_host_reachability_scheme")
                or ""
            )
            or None,
            deploy_https_ready=(
                bool(self.current_live_probe_result.get("deploy_https_ready"))
                if isinstance(self.current_live_probe_result.get("deploy_https_ready"), bool)
                else (
                    bool(self.current_live_probe_result.get("current_deploy_https_ready"))
                    if isinstance(self.current_live_probe_result.get("current_deploy_https_ready"), bool)
                    else None
                )
            ),
            cert_identity_valid=(
                bool(self.current_live_probe_result.get("cert_identity_valid"))
                if isinstance(self.current_live_probe_result.get("cert_identity_valid"), bool)
                else (
                    bool(self.current_live_probe_result.get("current_cert_identity_valid"))
                    if isinstance(self.current_live_probe_result.get("current_cert_identity_valid"), bool)
                    else None
                )
            ),
            https_probe_status_code=status_code,
            https_probe_error_summary=str(
                self.current_live_probe_result.get("https_probe_error_summary")
                or self.current_live_probe_result.get("current_https_probe_error_summary")
                or ""
            )
            or None,
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
                code=self.workflow_provision_error_code or "workflow_provision_failed",
                safe_message=self.workflow_provision_error_message or "Simulated workflow provisioning failure.",
                stage=self.workflow_provision_error_stage,
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
            workflow_integrity_status=self.readiness_workflow_integrity_status,
            workflow_integrity_reason_code=self.readiness_workflow_integrity_reason_code,
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


@pytest.fixture(autouse=True)
def _stub_managed_site_dns_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        seo_migration_module,
        "_resolve_hostname_ipv4_addresses",
        lambda _hostname: ["34.149.170.250"],
    )


def _build_service(
    db_session,
    provider: SEOMigrationArtifactGenerationProvider,
    *,
    github_publisher: SEOMigrationGitHubPublisher | None = None,
    env_default_model_name: str | None = None,
    deploy_secret_gcp_key: str | None = "{\"type\":\"service_account\"}",
    deploy_secret_git_userid: str | None = None,
    deploy_secret_git_email: str | None = None,
    deploy_secret_git_token: str | None = None,
    managed_site_private_image_auth_enabled: bool = False,
    remote_image_import_enabled: bool = False,
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
        deploy_secret_git_userid=deploy_secret_git_userid,
        deploy_secret_git_email=deploy_secret_git_email,
        deploy_secret_git_token=deploy_secret_git_token,
        managed_site_private_image_auth_enabled=managed_site_private_image_auth_enabled,
        remote_image_import_enabled=remote_image_import_enabled,
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


def test_managed_image_pull_secret_runtime_config_reads_control_plane_runtime_values(db_session) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        deploy_secret_git_userid="mhanson13",
        deploy_secret_git_email="mhanson13@gmail.com",
        deploy_secret_git_token="pat-test-value",
        managed_site_private_image_auth_enabled=True,
    )

    payload, reason_code = service._resolve_managed_image_pull_secret_runtime_config()

    assert reason_code is None
    assert payload.get("config_source") == "control_plane_runtime"
    assert payload.get("git_userid_configured") is True
    assert payload.get("git_email_configured") is True
    assert payload.get("git_token_configured") is True
    assert payload.get("private_image_auth_required") is True
    assert payload.get("private_image_credentials_available_in_control_plane") is True
    assert payload.get("target_repo_secrets_not_required") is True
    assert payload.get("image_pull_secret_not_provisioned") is True
    assert payload.get("image_pull_secret_provisioning_unavailable") is False
    assert "missing_fields" not in payload


def test_managed_image_pull_secret_runtime_config_allows_missing_runtime_projection_in_public_mode(
    db_session,
) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        deploy_secret_git_userid=None,
        deploy_secret_git_email=None,
        deploy_secret_git_token=None,
        managed_site_private_image_auth_enabled=False,
    )

    payload, reason_code = service._resolve_managed_image_pull_secret_runtime_config()

    assert reason_code is None
    assert payload.get("config_source") == "control_plane_runtime"
    assert payload.get("git_userid_configured") is False
    assert payload.get("git_email_configured") is False
    assert payload.get("git_token_configured") is False
    assert payload.get("private_image_auth_required") is False
    assert payload.get("private_image_credentials_available_in_control_plane") is False
    assert payload.get("target_repo_secrets_not_required") is True
    assert payload.get("image_pull_secret_not_provisioned") is False
    assert payload.get("image_pull_secret_provisioning_unavailable") is False
    assert payload.get("image_pull_auth_mode") == "public"
    assert "missing_fields" not in payload


def test_managed_image_pull_secret_runtime_config_requires_runtime_projection_in_private_mode(
    db_session,
) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        deploy_secret_git_userid=None,
        deploy_secret_git_email=None,
        deploy_secret_git_token=None,
        managed_site_private_image_auth_enabled=True,
    )

    payload, reason_code = service._resolve_managed_image_pull_secret_runtime_config()

    assert reason_code == "image_pull_secret_missing"
    assert payload.get("private_image_auth_required") is True
    assert payload.get("image_pull_auth_mode") == "private"
    assert payload.get("private_image_credentials_available_in_control_plane") is False
    assert payload.get("target_repo_secrets_not_required") is True
    assert payload.get("image_pull_secret_not_provisioned") is True
    assert payload.get("image_pull_secret_provisioning_unavailable") is True
    assert sorted(payload.get("missing_fields") or []) == [
        "git_email",
        "git_token",
        "git_userid",
    ]


def test_deploy_readiness_exposes_private_image_control_plane_status_flags(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        readiness_dispatch_service_availability=True,
        readiness_dispatch_service_reason_code="available",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key='{"type":"service_account"}',
        deploy_secret_git_userid=None,
        deploy_secret_git_email=None,
        deploy_secret_git_token=None,
        managed_site_private_image_auth_enabled=True,
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

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_target_raw = summary.deploy_readiness.get("target")
    deploy_target = deploy_target_raw if isinstance(deploy_target_raw, dict) else {}

    assert deploy_target.get("private_image_auth_required") is True
    assert deploy_target.get("private_image_credentials_available_in_control_plane") is False
    assert deploy_target.get("target_repo_secrets_not_required") is True
    assert deploy_target.get("image_pull_secret_not_provisioned") is True
    assert deploy_target.get("image_pull_secret_provisioning_unavailable") is True


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


def _tiny_png_payload() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0AIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe5'\xd4\xa2"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
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


def _prepare_published_artifact(
    service: SEOMigrationService,
    *,
    business_id: str,
    site_id: str,
    workflow_id: str = "deploy-www-prod.yml",
) -> object:
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id, workflow_id=workflow_id)
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
    return artifact


def _prepare_and_request_deploy(
    service: SEOMigrationService,
    *,
    business_id: str,
    site_id: str,
    workflow_id: str = "deploy-www-prod.yml",
) -> object:
    artifact = _prepare_published_artifact(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id=workflow_id,
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    return artifact


def _set_admin_repo_auto_create_enabled(db_session, *, enabled: bool) -> None:
    config = db_session.query(GitHubPublishConfig).first()
    assert config is not None
    config.github_repository_auto_create_enabled = bool(enabled)
    db_session.commit()


def test_yaml_dependency_import_available() -> None:
    yaml_module = importlib.import_module("yaml")
    assert hasattr(yaml_module, "safe_load")


def test_app_main_import_succeeds() -> None:
    main_module = importlib.import_module("app.main")
    assert getattr(main_module, "app", None) is not None


def test_gbp_contract_guard_script_check_succeeds() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.setdefault("APP_ENV", "test")
    result = subprocess.run(
        [sys.executable, "scripts/gbp_verification_contract_guard.py", "--check"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "GBP verification contract guard --check failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
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


def test_workspace_media_upload_update_and_listing_are_bounded_and_workspace_scoped(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MIGRATION_MEDIA_STORAGE_ROOT", str(tmp_path))
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-a",
                "normalized_url": "https://legacy.example/images/front.jpg?token=abc",
                "source_page_url": "https://legacy.example/?signed=123",
                "selected_for_draft": False,
                "provenance": "source_site_import",
                "import_status": "discovered",
            }
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    uploaded = service.upload_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        filename="crew-photo.png",
        content_type="image/png",
        payload=_tiny_png_payload(),
        selected_for_draft=True,
        category="project_gallery",
        alt_text="Project crew photo",
        description="Crew onsite during install",
        usage_note="Use in gallery section",
        page_assignment="/projects",
        principal_id="principal-1",
    )
    assert isinstance(uploaded, dict)
    assert str(uploaded.get("asset_id", "")).startswith("upl-")
    assert uploaded.get("provenance") == "operator_upload"
    assert uploaded.get("selected_for_draft") is True
    assert uploaded.get("content_type") == "image/png"
    assert uploaded.get("width") == 1
    assert uploaded.get("height") == 1
    assert "storage_key" not in uploaded

    stored_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(stored_files) == 1
    assert stored_files[0].suffix == ".png"

    listed = service.list_workspace_media_assets(business_id=business_id, site_id=site_id)
    assert listed.get("source_discovered_count") == 1
    assert listed.get("operator_uploaded_count") == 1
    assert listed.get("selected_assets_count") == 1

    with pytest.raises(SEOMigrationValidationError) as selection_error:
        service.update_workspace_media_asset(
            business_id=business_id,
            site_id=site_id,
            asset_id="srcimg-a",
            selected_for_draft=True,
            category="hero",
            alt_text="Legacy storefront hero",
            description="Legacy storefront exterior",
            usage_note="Potential hero fallback",
            page_assignment="/",
            principal_id="principal-1",
        )
    assert selection_error.value.error_code == "media_asset_not_imported"

    updated_source_metadata = service.update_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        asset_id="srcimg-a",
        selected_for_draft=None,
        category="hero",
        alt_text="Legacy storefront hero",
        description="Legacy storefront exterior",
        usage_note="Potential hero fallback",
        page_assignment="/",
        principal_id="principal-1",
    )
    assert updated_source_metadata.get("selected_for_draft") is False
    assert updated_source_metadata.get("category") == "hero"
    assert updated_source_metadata.get("alt_text") == "Legacy storefront hero"

    listed_after_update = service.list_workspace_media_assets(business_id=business_id, site_id=site_id)
    assert listed_after_update.get("selected_assets_count") == 1
    selected_assets = listed_after_update.get("selected_assets")
    assert isinstance(selected_assets, list)
    assert {item.get("asset_id") for item in selected_assets if isinstance(item, dict)} == {uploaded.get("asset_id")}


def test_workspace_media_metadata_suggestions_are_stored_separately_and_apply_only_on_explicit_action(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MIGRATION_MEDIA_STORAGE_ROOT", str(tmp_path))
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    uploaded = service.upload_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        filename="crew-photo.png",
        content_type="image/png",
        payload=_tiny_png_payload(),
        selected_for_draft=True,
        category="project_gallery",
        alt_text="Operator-authored alt",
        description="Operator-authored description",
        usage_note="Operator-authored usage",
        page_assignment="/projects",
        principal_id="principal-1",
    )
    uploaded_asset_id = str(uploaded.get("asset_id") or "")
    assert uploaded_asset_id

    def _mock_suggestion_request(**kwargs) -> dict[str, object]:  # noqa: ANN003
        del kwargs
        return {
            "suggested_category": "hero",
            "suggested_alt_text": "AI suggested alt text",
            "suggested_description": "AI suggested description",
            "suggested_usage_note": "AI suggested usage",
            "suggested_page_assignment": "/",
            "confidence": 0.87,
        }

    monkeypatch.setattr(service, "_request_media_metadata_suggestion", _mock_suggestion_request)

    suggested = service.suggest_media_asset_metadata(
        business_id=business_id,
        site_id=site_id,
        asset_id=uploaded_asset_id,
        force_refresh=True,
        principal_id="principal-1",
    )
    suggestion = suggested.get("metadata_suggestion") or {}
    assert suggestion.get("suggestion_status") == "completed"
    assert suggestion.get("reason_code") == "image_metadata_suggested"
    assert suggestion.get("suggested_alt_text") == "AI suggested alt text"
    assert suggested.get("alt_text") == "Operator-authored alt"
    assert suggested.get("description") == "Operator-authored description"
    assert suggested.get("metadata_suggestion_applied") is False

    applied = service.update_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        asset_id=uploaded_asset_id,
        selected_for_draft=None,
        apply_suggested_metadata=True,
        principal_id="principal-1",
    )
    assert applied.get("metadata_suggestion_applied") is True
    assert isinstance(applied.get("metadata_suggestion_applied_at"), str)
    assert applied.get("category") == "hero"
    assert applied.get("alt_text") == "AI suggested alt text"
    assert applied.get("description") == "AI suggested description"
    assert applied.get("usage_note") == "AI suggested usage"
    assert applied.get("page_assignment") == "/"


@pytest.mark.parametrize("provider_reason_code", ["provider_unavailable", "provider_response_invalid"])
def test_workspace_media_metadata_suggestion_normalizes_provider_failure_reason_codes(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_reason_code: str,
) -> None:
    monkeypatch.setenv("MIGRATION_MEDIA_STORAGE_ROOT", str(tmp_path))
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    uploaded = service.upload_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        filename="provider-failure.png",
        content_type="image/png",
        payload=_tiny_png_payload(),
        selected_for_draft=False,
        category=None,
        alt_text=None,
        description=None,
        usage_note=None,
        page_assignment=None,
        principal_id="principal-1",
    )
    uploaded_asset_id = str(uploaded.get("asset_id") or "")
    assert uploaded_asset_id

    def _raise_provider_failure(**kwargs):  # noqa: ANN003
        del kwargs
        raise SEOMigrationValidationError(
            "simulated provider failure",
            failure_category="provider_error",
            failure_reason="unknown",
            error_code=provider_reason_code,
        )

    monkeypatch.setattr(service, "_request_media_metadata_suggestion", _raise_provider_failure)

    suggested = service.suggest_media_asset_metadata(
        business_id=business_id,
        site_id=site_id,
        asset_id=uploaded_asset_id,
        force_refresh=True,
        principal_id="principal-1",
    )
    suggestion = suggested.get("metadata_suggestion") or {}
    assert suggestion.get("suggestion_status") == "failed"
    assert suggestion.get("reason_code") == provider_reason_code


def test_workspace_media_metadata_suggestion_returns_image_not_imported_for_remote_discovered_assets(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-remote-only",
                "normalized_url": "https://legacy.example/images/front.jpg?signed=abc123",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": True,
            }
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    suggested = service.suggest_media_asset_metadata(
        business_id=business_id,
        site_id=site_id,
        asset_id="srcimg-remote-only",
        force_refresh=True,
        principal_id="principal-1",
    )
    suggestion = suggested.get("metadata_suggestion") or {}
    assert suggestion.get("suggestion_status") == "not_available"
    assert suggestion.get("reason_code") == "image_not_imported"


def test_workspace_media_metadata_batch_suggestions_support_force_refresh(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MIGRATION_MEDIA_STORAGE_ROOT", str(tmp_path))
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    uploaded_asset_ids: list[str] = []
    for index in range(2):
        uploaded = service.upload_workspace_media_asset(
            business_id=business_id,
            site_id=site_id,
            filename=f"batch-{index}.png",
            content_type="image/png",
            payload=_tiny_png_payload(),
            selected_for_draft=True,
            category=None,
            alt_text=None,
            description=None,
            usage_note=None,
            page_assignment=None,
            principal_id="principal-1",
        )
        asset_id = str(uploaded.get("asset_id") or "")
        assert asset_id
        uploaded_asset_ids.append(asset_id)

    request_call_count = {"count": 0}

    def _mock_suggestion_request(**kwargs) -> dict[str, object]:  # noqa: ANN003
        request_call_count["count"] += 1
        asset_metadata = kwargs.get("asset_metadata")
        asset_id = (
            str(asset_metadata.get("asset_id") or "").strip()
            if isinstance(asset_metadata, dict)
            else "unknown"
        )
        return {
            "suggested_category": "project_gallery",
            "suggested_alt_text": f"AI alt for {asset_id}",
            "suggested_description": "AI generated description",
            "suggested_usage_note": "AI generated usage note",
            "suggested_page_assignment": "/projects",
            "confidence": 0.91,
        }

    monkeypatch.setattr(service, "_request_media_metadata_suggestion", _mock_suggestion_request)

    first_batch = service.suggest_media_assets_metadata_batch(
        business_id=business_id,
        site_id=site_id,
        asset_ids=uploaded_asset_ids,
        force_refresh=False,
        principal_id="principal-1",
    )
    assert first_batch.get("batch_status") == "completed"
    assert first_batch.get("completed_count") == 2
    assert first_batch.get("failed_count") == 0
    assert first_batch.get("skipped_count") == 0
    assert request_call_count["count"] == 2

    second_batch = service.suggest_media_assets_metadata_batch(
        business_id=business_id,
        site_id=site_id,
        asset_ids=uploaded_asset_ids,
        force_refresh=False,
        principal_id="principal-1",
    )
    assert second_batch.get("batch_status") == "completed"
    assert request_call_count["count"] == 2

    third_batch = service.suggest_media_assets_metadata_batch(
        business_id=business_id,
        site_id=site_id,
        asset_ids=uploaded_asset_ids,
        force_refresh=True,
        principal_id="principal-1",
    )
    assert third_batch.get("batch_status") == "completed"
    assert request_call_count["count"] == 4
    serialized = json.dumps(third_batch).lower()
    for forbidden in ("storage_key", "base64", "access_token", "refresh_token", "authorization", "cookie", "\\\\"):
        assert forbidden not in serialized


def test_workspace_media_metadata_batch_suggestion_returns_partial_success_for_remote_not_imported_assets(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MIGRATION_MEDIA_STORAGE_ROOT", str(tmp_path))
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    uploaded = service.upload_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        filename="controlled.png",
        content_type="image/png",
        payload=_tiny_png_payload(),
        selected_for_draft=True,
        category=None,
        alt_text=None,
        description=None,
        usage_note=None,
        page_assignment=None,
        principal_id="principal-1",
    )
    uploaded_asset_id = str(uploaded.get("asset_id") or "")
    assert uploaded_asset_id

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    source_snapshot = dict(workspace.imported_source_snapshot_json or {})
    discovered = list(source_snapshot.get("discovered_images") or [])
    discovered.append(
        {
            "asset_id": "srcimg-remote-only",
            "normalized_url": "https://legacy.example/images/front.jpg?signed=abc123",
            "provenance": "source_site_import",
            "import_status": "discovered",
            "selected_for_draft": True,
        }
    )
    source_snapshot["discovered_images"] = discovered
    workspace.imported_source_snapshot_json = source_snapshot
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    batch_result = service.suggest_media_assets_metadata_batch(
        business_id=business_id,
        site_id=site_id,
        asset_ids=[uploaded_asset_id, "srcimg-remote-only"],
        force_refresh=False,
        principal_id="principal-1",
    )
    assert batch_result.get("batch_status") == "partial_success"
    assert batch_result.get("completed_count") == 1
    assert batch_result.get("failed_count") == 0
    assert batch_result.get("skipped_count") == 1
    results = batch_result.get("results")
    assert isinstance(results, list)
    results_by_asset = {
        str(item.get("asset_id") or ""): item
        for item in results
        if isinstance(item, dict)
    }
    assert (results_by_asset.get(uploaded_asset_id) or {}).get("suggestion_status") == "completed"
    assert (results_by_asset.get("srcimg-remote-only") or {}).get("suggestion_status") == "not_available"
    assert (results_by_asset.get("srcimg-remote-only") or {}).get("reason_code") == "media_asset_not_imported"


def test_workspace_media_selection_and_batch_suggestion_reject_low_value_discovered_assets(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-low-value",
                "normalized_url": "https://legacy.example/images/transparent_placeholder.png",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": True,
                "candidate_quality": "low_value",
                "quality_reason": "placeholder_image_detected",
            }
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    with pytest.raises(SEOMigrationValidationError) as selection_error:
        service.update_workspace_media_asset(
            business_id=business_id,
            site_id=site_id,
            asset_id="srcimg-low-value",
            selected_for_draft=True,
            principal_id="principal-1",
        )
    assert selection_error.value.error_code == "placeholder_image_detected"

    batch_result = service.suggest_media_assets_metadata_batch(
        business_id=business_id,
        site_id=site_id,
        asset_ids=["srcimg-low-value"],
        force_refresh=False,
        principal_id="principal-1",
    )
    assert batch_result.get("batch_status") == "failed"
    assert batch_result.get("completed_count") == 0
    assert batch_result.get("failed_count") == 0
    assert batch_result.get("skipped_count") == 1
    results = batch_result.get("results")
    assert isinstance(results, list)
    assert len(results) == 1
    result = results[0] if isinstance(results[0], dict) else {}
    assert result.get("suggestion_status") == "not_available"
    assert result.get("reason_code") == "placeholder_image_detected"
    assert result.get("retryable") is False


def test_workspace_media_metadata_batch_suggestion_blocks_cross_site_assets(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MIGRATION_MEDIA_STORAGE_ROOT", str(tmp_path))
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    other_site_id = "33333333-3333-3333-3333-333333333333"
    db_session.add(
        SEOSite(
            id=other_site_id,
            business_id=business_id,
            display_name="Secondary Site",
            base_url="https://secondary.example/",
            normalized_domain="secondary.example",
            industry="fire protection",
            primary_location="Longmont, CO",
            service_areas_json=["Longmont"],
            is_active=True,
            is_primary=False,
        )
    )
    db_session.commit()
    _seed_workspace(service, business_id=business_id, site_id=other_site_id)

    uploaded = service.upload_workspace_media_asset(
        business_id=business_id,
        site_id=site_id,
        filename="site-a-only.png",
        content_type="image/png",
        payload=_tiny_png_payload(),
        selected_for_draft=True,
        category=None,
        alt_text=None,
        description=None,
        usage_note=None,
        page_assignment=None,
        principal_id="principal-1",
    )
    asset_id = str(uploaded.get("asset_id") or "")
    assert asset_id

    batch_result = service.suggest_media_assets_metadata_batch(
        business_id=business_id,
        site_id=other_site_id,
        asset_ids=[asset_id],
        force_refresh=False,
        principal_id="principal-1",
    )
    assert batch_result.get("batch_status") == "failed"
    assert batch_result.get("completed_count") == 0
    assert batch_result.get("failed_count") == 1
    results = batch_result.get("results")
    assert isinstance(results, list)
    assert len(results) == 1
    result = results[0] if isinstance(results[0], dict) else {}
    assert result.get("asset_id") == asset_id
    assert result.get("reason_code") == "media_asset_not_authorized"
    assert result.get("suggestion_status") == "failed"
    assert result.get("retryable") is False


def test_workspace_media_metadata_batch_suggestion_enforces_max_asset_count(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    oversized_asset_ids = [f"asset-{index}" for index in range(25)]
    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.suggest_media_assets_metadata_batch(
            business_id=business_id,
            site_id=site_id,
            asset_ids=oversized_asset_ids,
            force_refresh=False,
            principal_id="principal-1",
        )
    assert exc_info.value.error_code == "media_suggestion_batch_limit_reached"


def test_workspace_media_upload_rejects_unsupported_or_mismatched_mime_types(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    png_payload = _tiny_png_payload()

    with pytest.raises(SEOMigrationValidationError) as unsupported_error:
        service.upload_workspace_media_asset(
            business_id=business_id,
            site_id=site_id,
            filename="vector.svg",
            content_type="image/svg+xml",
            payload=png_payload,
            selected_for_draft=False,
            category=None,
            alt_text=None,
            description=None,
            usage_note=None,
            page_assignment=None,
            principal_id="principal-1",
        )
    assert unsupported_error.value.error_code == "unsupported_mime_type"

    with pytest.raises(SEOMigrationValidationError) as mismatch_error:
        service.upload_workspace_media_asset(
            business_id=business_id,
            site_id=site_id,
            filename="photo.jpg",
            content_type="image/jpeg",
            payload=png_payload,
            selected_for_draft=False,
            category=None,
            alt_text=None,
            description=None,
            usage_note=None,
            page_assignment=None,
            principal_id="principal-1",
        )
    assert mismatch_error.value.error_code == "media_upload_content_type_mismatch"


def test_selected_discovered_media_import_returns_disabled_reason_when_feature_flag_off(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-selected",
                "normalized_url": "https://legacy.example/media/hero.jpg",
                "selected_for_draft": True,
                "provenance": "source_site_import",
                "import_status": "discovered",
            },
            {
                "asset_id": "srcimg-unselected",
                "normalized_url": "https://legacy.example/media/gallery.jpg",
                "selected_for_draft": False,
                "provenance": "source_site_import",
                "import_status": "discovered",
            },
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    boundary_result = service.import_selected_discovered_media_assets(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert boundary_result.get("implemented") is False
    assert boundary_result.get("attempted_count") == 1
    assert boundary_result.get("imported_count") == 0
    assert boundary_result.get("failure_reason_code") == "remote_image_import_disabled"
    failures = boundary_result.get("failures")
    assert isinstance(failures, list)
    assert failures[0].get("asset_id") == "srcimg-selected"
    assert failures[0].get("reason_code") == "remote_image_import_disabled"


def test_discovered_media_import_imports_selected_assets_when_feature_flag_enabled(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        remote_image_import_enabled=True,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-selected",
                "normalized_url": "https://legacy.example/media/hero.jpg?token=abc",
                "selected_for_draft": True,
                "provenance": "source_site_import",
                "import_status": "discovered",
                "metadata_suggestion": {
                    "suggestion_status": "not_available",
                    "reason_code": "image_not_imported",
                },
            }
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    monkeypatch.setattr(
        service,
        "_fetch_remote_discovered_image_for_import",
        lambda *, url: {
            "reason_code": "remote_image_imported",
            "payload": _tiny_png_payload(),
            "content_type": "image/png",
            "final_url": "https://legacy.example/media/hero.jpg",
        },
    )

    result = service.import_discovered_media_assets(
        business_id=business_id,
        site_id=site_id,
        discovered_image_ids=["srcimg-selected"],
        normalized_urls=[],
        selected_for_draft=True,
        principal_id="principal-1",
    )
    assert result.get("batch_status") == "completed"
    assert result.get("imported_count") == 1
    assert result.get("failed_count") == 0
    assert result.get("skipped_count") == 0
    assert result.get("disabled_count") == 0
    results = result.get("results")
    assert isinstance(results, list)
    assert results[0].get("status") == "imported"
    assert results[0].get("reason_code") == "remote_image_imported"

    refreshed_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    discovered_assets = list((refreshed_workspace.imported_source_snapshot_json or {}).get("discovered_images") or [])
    assert len(discovered_assets) == 1
    imported_asset = discovered_assets[0]
    assert imported_asset.get("import_status") == "selected"
    assert imported_asset.get("selected_for_draft") is True
    assert imported_asset.get("content_type") == "image/png"
    assert imported_asset.get("size_bytes") == len(_tiny_png_payload())
    assert isinstance(imported_asset.get("storage_key"), str)
    assert imported_asset.get("metadata_suggestion") is None


def test_discovered_media_import_blocks_private_source_urls_without_fetch(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        remote_image_import_enabled=True,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-private",
                "normalized_url": "http://127.0.0.1/internal.png",
                "selected_for_draft": True,
                "provenance": "source_site_import",
                "import_status": "discovered",
            }
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    class _UnexpectedFetchOpener:
        def open(self, request, timeout):  # noqa: ANN001
            del request, timeout
            raise AssertionError("network fetch should not be attempted for private host URLs")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: _UnexpectedFetchOpener())

    result = service.import_discovered_media_assets(
        business_id=business_id,
        site_id=site_id,
        discovered_image_ids=["srcimg-private"],
        normalized_urls=[],
        selected_for_draft=True,
        principal_id="principal-1",
    )
    assert result.get("batch_status") == "failed"
    assert result.get("imported_count") == 0
    assert result.get("failed_count") == 1
    results = result.get("results")
    assert isinstance(results, list)
    assert results[0].get("status") == "failed"
    assert results[0].get("reason_code") == "image_import_private_address_blocked"


def test_discovered_media_import_deduplicates_repeated_import_attempts(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        remote_image_import_enabled=True,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "discovered_images": [
            {
                "asset_id": "srcimg-repeat",
                "normalized_url": "https://legacy.example/media/repeat.jpg",
                "selected_for_draft": True,
                "provenance": "source_site_import",
                "import_status": "discovered",
            }
        ]
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    monkeypatch.setattr(
        service,
        "_fetch_remote_discovered_image_for_import",
        lambda *, url: {
            "reason_code": "remote_image_imported",
            "payload": _tiny_png_payload(),
            "content_type": "image/png",
            "final_url": "https://legacy.example/media/repeat.jpg",
        },
    )

    first_result = service.import_discovered_media_assets(
        business_id=business_id,
        site_id=site_id,
        discovered_image_ids=["srcimg-repeat"],
        normalized_urls=[],
        selected_for_draft=True,
        principal_id="principal-1",
    )
    assert first_result.get("imported_count") == 1

    second_result = service.import_discovered_media_assets(
        business_id=business_id,
        site_id=site_id,
        discovered_image_ids=["srcimg-repeat"],
        normalized_urls=[],
        selected_for_draft=True,
        principal_id="principal-1",
    )
    assert second_result.get("imported_count") == 0
    assert second_result.get("skipped_count") == 1
    second_results = second_result.get("results")
    assert isinstance(second_results, list)
    assert second_results[0].get("status") == "skipped"
    assert second_results[0].get("reason_code") == "remote_image_imported"


def test_generate_draft_artifacts_sets_context_unavailable_reason_code_when_context_assembly_errors(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    def _explode_context(*, site, workspace):  # noqa: ANN001
        del site, workspace
        raise RuntimeError("context assembly exploded")

    monkeypatch.setattr(service, "_assemble_context", _explode_context)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    assert exc_info.value.error_code == "draft_generation_context_unavailable"
    assert exc_info.value.failure_category == "unknown_error"
    assert exc_info.value.retryable is True


def test_generate_draft_artifacts_normalizes_google_reconnect_reason_code_from_context_validation_error(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    def _raise_reconnect_validation(*, site, workspace):  # noqa: ANN001
        del site, workspace
        raise SEOMigrationValidationError(
            "Google token refresh is required before draft context assembly can continue.",
            failure_category="config_missing",
            failure_reason="authentication_failed",
            error_code="google_token_expired",
        )

    monkeypatch.setattr(service, "_assemble_context", _raise_reconnect_validation)

    with pytest.raises(SEOMigrationValidationError) as exc_info:
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    assert exc_info.value.error_code == "google_reconnect_required"
    assert exc_info.value.failure_category == "config_missing"
    assert exc_info.value.failure_reason == "authentication_failed"
    assert exc_info.value.retryable is False


def test_generate_draft_artifacts_includes_bounded_draft_input_summary_and_media_context(db_session) -> None:
    provider = _ContextCaptureMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session, ga_measurement_id="G-ABCD1234")
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _seed_reused_context_records(db_session, business_id=business_id, site_id=site_id)

    competitor_domain = SEOCompetitorDomain(
        id="competitor-domain-summary-1",
        business_id=business_id,
        site_id=site_id,
        competitor_set_id="competitor-set-readiness-1",
        domain="competitor.example",
        base_url="https://competitor.example/",
        display_name="Competitor Example",
        source="manual",
        verification_status="verified",
        is_active=True,
    )
    db_session.add(competitor_domain)

    site = service.seo_site_repository.get_for_business(business_id, site_id)
    assert site is not None
    site.search_console_enabled = True
    site.search_console_property_url = "https://search.google.com/search-console?resource_id=sc-domain:tnmfire.example"
    site.ga4_onboarding_status = "connected"

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "title": "Legacy Site",
        "fetched_at": utc_now().isoformat(),
        "warnings": ["private_host_rejected"],
        "discovered_images": [
            {
                "asset_id": "srcimg-selected",
                "normalized_url": "https://legacy.example/media/hero.jpg?signed=abc123",
                "source_page_url": "https://legacy.example/?sig=xyz",
                "selected_for_draft": True,
                "provenance": "source_site_import",
                "import_status": "selected",
                "category": "hero",
                "alt_text": "Existing storefront",
            },
            {
                "asset_id": "srcimg-unselected",
                "normalized_url": "https://legacy.example/media/gallery.jpg?token=def",
                "selected_for_draft": False,
                "provenance": "source_site_import",
                "import_status": "discovered",
                "category": "project_gallery",
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAUA",
                "metadata_suggestion": {
                    "suggestion_status": "not_available",
                    "reason_code": "image_not_imported",
                },
            },
        ],
    }
    enriched_notes = dict(workspace.enriched_content_notes_json or {})
    enriched_notes["workspace_media_assets"] = [
        {
            "asset_id": "upl-selected",
            "display_filename": "crew.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 2048,
            "provenance": "operator_upload",
            "selected_for_draft": True,
            "import_status": "selected",
            "category": None,
            "alt_text": None,
            "description": None,
            "usage_note": None,
            "page_assignment": None,
            "metadata_suggestion": {
                "suggestion_status": "completed",
                "reason_code": "image_metadata_suggested",
                "suggestion_source": "ai_image_recognition",
                "suggested_category": "project_gallery",
                "suggested_alt_text": "Crew on jobsite",
                "suggested_description": "Customer gallery image",
                "suggested_usage_note": "Use on projects page",
                "suggested_page_assignment": "/projects",
                "confidence": 0.8,
                "generated_at": utc_now().isoformat(),
            },
            "storage_key": "business/site/upl-selected.jpg",
            "raw_token_value": "secret-token-value",
        }
    ]
    workspace.enriched_content_notes_json = enriched_notes
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert artifact.status in {"completed", "partial"}
    assert isinstance(provider.last_context, dict)

    context = provider.last_context or {}
    draft_input_summary = context.get("draft_input_summary")
    assert isinstance(draft_input_summary, dict)
    assert draft_input_summary.get("recommendations_included_count") == 1
    assert draft_input_summary.get("gsc_signals_included") is True
    assert draft_input_summary.get("ga4_signals_included") is True
    assert draft_input_summary.get("competitor_profiles_included_count") == 1
    assert draft_input_summary.get("operator_requirements_included") is True
    assert draft_input_summary.get("enriched_business_context_included") is True
    assert draft_input_summary.get("source_site_images_discovered_count") == 2
    assert draft_input_summary.get("source_site_images_imported_count") == 1
    assert draft_input_summary.get("operator_uploaded_images_count") == 1
    assert draft_input_summary.get("selected_media_assets_count") == 2
    assert draft_input_summary.get("selected_usable_media_assets_count") == 2
    assert draft_input_summary.get("usable_media_assets_count") == 2
    assert draft_input_summary.get("useful_discovered_images_count") == 2
    assert draft_input_summary.get("low_value_discovered_images_count") == 0
    assert draft_input_summary.get("rejected_discovered_images_count") == 0
    assert draft_input_summary.get("media_required_by_operator") is False
    assert draft_input_summary.get("media_requirement_satisfied") is True
    assert draft_input_summary.get("media_requirement_warning_reason") is None
    assert draft_input_summary.get("media_context_included") is True
    assert draft_input_summary.get("media_context_trimmed") is False
    assert draft_input_summary.get("media_assets_with_ai_suggestions_count") == 1
    assert draft_input_summary.get("media_assets_with_operator_applied_metadata_count") == 0
    assert draft_input_summary.get("media_suggestion_failures_count") == 1
    assert draft_input_summary.get("provider_source") == "mock"
    assert draft_input_summary.get("mocked_source") is True

    summary_json = json.dumps(draft_input_summary).lower()
    assert "token_value" not in summary_json
    assert "raw_token" not in summary_json
    assert "image_base64" not in summary_json
    assert "ivborw0kggo" not in summary_json

    media_context = context.get("media_assets")
    assert isinstance(media_context, dict)
    selected_assets = media_context.get("selected_assets")
    assert isinstance(selected_assets, list)
    assert len(selected_assets) == 2
    selected_by_id = {
        str(item.get("asset_id")): item
        for item in selected_assets
        if isinstance(item, dict) and isinstance(item.get("asset_id"), str)
    }
    uploaded_context = selected_by_id.get("upl-selected") or {}
    assert uploaded_context.get("metadata_source") == "ai_suggested"
    assert uploaded_context.get("category") == "project_gallery"
    assert uploaded_context.get("alt_text") == "Crew on jobsite"
    for item in selected_assets:
        assert isinstance(item, dict)
        assert "storage_key" not in item
        assert "raw_token_value" not in item
        assert "image_base64" not in item
        normalized_url = item.get("normalized_url")
        if isinstance(normalized_url, str) and normalized_url:
            assert "?" not in normalized_url


def test_generate_draft_artifacts_flags_media_context_trimming_when_selected_assets_are_oversized(
    db_session,
) -> None:
    provider = _ContextCaptureMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _seed_reused_context_records(db_session, business_id=business_id, site_id=site_id)

    discovered_images: list[dict[str, object]] = []
    for index in range(35):
        discovered_images.append(
            {
                "asset_id": f"srcimg-{index}",
                "normalized_url": f"https://legacy.example/media/photo-{index}.jpg?token=abc{index}",
                "selected_for_draft": True,
                "provenance": "source_site_import",
                "import_status": "selected",
                "category": "project_gallery",
            }
        )

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.imported_source_snapshot_json = {
        "title": "Legacy Site",
        "fetched_at": utc_now().isoformat(),
        "discovered_images": discovered_images,
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert artifact.status in {"completed", "partial"}
    assert isinstance(provider.last_context, dict)

    context = provider.last_context or {}
    draft_input_summary = context.get("draft_input_summary")
    assert isinstance(draft_input_summary, dict)
    assert draft_input_summary.get("source_site_images_discovered_count") == 35
    assert draft_input_summary.get("media_context_trimmed") is True

    media_context = context.get("media_assets")
    assert isinstance(media_context, dict)
    selected_assets_count = media_context.get("selected_assets_count")
    assert isinstance(selected_assets_count, int)
    assert selected_assets_count < 35
    assert media_context.get("context_trimmed") is True

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


def test_draft_generation_readiness_missing_enriched_content_is_supporting_only(db_session) -> None:
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
    assert readiness.get("status") == "ready_with_warnings"
    assert readiness.get("hard_blocked") is False
    reasons = readiness.get("reasons") or []
    assert all(
        not (
            isinstance(item, dict)
            and item.get("code") == "enriched_content_required"
            and item.get("severity") == "blocking"
        )
        for item in reasons
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "business_objectives",
        "requested_pages",
        "must_include",
        "must_avoid",
        "tone",
        "calls_to_action",
    ],
)
def test_requirements_suggestion_returns_completed_for_supported_fields_with_mock_provider(
    db_session,
    field_name: str,
) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _seed_reused_context_records(db_session, business_id=business_id, site_id=site_id)

    suggestion = service.suggest_operator_requirement_field(
        business_id=business_id,
        site_id=site_id,
        field=field_name,
        current_value=None,
        force_refresh=False,
        principal_id="principal-1",
    )

    assert suggestion.get("field") == field_name
    assert suggestion.get("suggestion_status") == "completed"
    assert suggestion.get("reason_code") == "requirements_suggestion_completed"
    assert suggestion.get("retryable") is False
    suggested_value = suggestion.get("suggested_value")
    assert isinstance(suggested_value, list)
    assert len(suggested_value) >= 1
    sources = suggestion.get("context_sources_used")
    assert isinstance(sources, list)
    assert "source_snapshot" in sources
    payload_json = json.dumps(suggestion).lower()
    assert "database_url" not in payload_json
    assert "storage_key" not in payload_json
    assert "raw_token" not in payload_json
    assert "image_base64" not in payload_json


def test_requirements_suggestion_returns_not_available_for_unsupported_field(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    suggestion = service.suggest_operator_requirement_field(
        business_id=business_id,
        site_id=site_id,
        field="unsupported_field",
        current_value=None,
        force_refresh=False,
        principal_id="principal-1",
    )

    assert suggestion.get("field") == "unsupported_field"
    assert suggestion.get("suggestion_status") == "not_available"
    assert suggestion.get("suggested_value") is None
    assert suggestion.get("reason_code") == "requirements_suggestion_field_unsupported"
    assert suggestion.get("retryable") is False


@pytest.mark.parametrize(
    "error_code,expected_status,expected_retryable",
    [
        ("requirements_suggestion_provider_unavailable", "failed", True),
        ("requirements_suggestion_provider_invalid", "failed", False),
        ("requirements_suggestion_budget_rejected", "not_available", False),
    ],
)
def test_requirements_suggestion_normalizes_provider_reason_codes(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_status: str,
    expected_retryable: bool,
) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    def _raise_provider_error(**kwargs):  # noqa: ANN003
        del kwargs
        raise SEOMigrationValidationError(
            "simulated requirement suggestion failure",
            failure_category="provider_error",
            failure_reason="unknown",
            error_code=error_code,
            retryable=expected_retryable,
        )

    monkeypatch.setattr(service, "_request_requirement_field_suggestion", _raise_provider_error)

    suggestion = service.suggest_operator_requirement_field(
        business_id=business_id,
        site_id=site_id,
        field="must_include",
        current_value=None,
        force_refresh=False,
        principal_id="principal-1",
    )

    assert suggestion.get("suggestion_status") == expected_status
    assert suggestion.get("suggested_value") is None
    assert suggestion.get("reason_code") == error_code
    assert suggestion.get("retryable") is expected_retryable


def test_requirements_suggestion_returns_context_unavailable_when_context_assembly_fails(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    def _raise_context_failure(*, site, workspace):  # noqa: ANN001
        del site, workspace
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(service, "_assemble_context", _raise_context_failure)

    suggestion = service.suggest_operator_requirement_field(
        business_id=business_id,
        site_id=site_id,
        field="must_include",
        current_value=None,
        force_refresh=False,
        principal_id="principal-1",
    )

    assert suggestion.get("suggestion_status") == "failed"
    assert suggestion.get("suggested_value") is None
    assert suggestion.get("reason_code") == "requirements_suggestion_context_unavailable"
    assert suggestion.get("retryable") is True
    assert suggestion.get("context_sources_used") == []


def test_generate_draft_artifacts_does_not_include_unapplied_requirement_suggestions(
    db_session,
) -> None:
    provider = _ContextCaptureMigrationProvider(_build_publishable_output())
    service = _build_service(db_session, provider)
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    before_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    before_requirements = dict(before_workspace.operator_requirements_json or {})

    suggestion = service.suggest_operator_requirement_field(
        business_id=business_id,
        site_id=site_id,
        field="must_include",
        current_value=None,
        force_refresh=False,
        principal_id="principal-1",
    )
    suggested_value = suggestion.get("suggested_value") or []
    assert isinstance(suggested_value, list)
    assert suggested_value

    after_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert dict(after_workspace.operator_requirements_json or {}) == before_requirements

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    assert artifact.status in {"completed", "partial"}
    assert isinstance(provider.last_context, dict)

    operator_context = (provider.last_context or {}).get("operator_requirements")
    assert isinstance(operator_context, dict)
    operator_context_json = json.dumps(operator_context)
    for line in suggested_value:
        assert str(line) not in operator_context_json


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


def test_draft_generation_readiness_warns_when_operator_requires_media_but_no_usable_selected_assets(
    db_session,
) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _mark_workspace_ingested(service, business_id=business_id, site_id=site_id)
    _seed_reused_context_records(db_session, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    workspace.operator_requirements_json = {
        "business_objectives": [
            "Use real project photos and bring over existing images into the new Project Gallery."
        ],
    }
    workspace.imported_source_snapshot_json = {
        "title": "Legacy",
        "discovered_images": [
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
            {
                "asset_id": "srcimg-useful",
                "normalized_url": "https://legacy.example/gallery/project-1.jpg",
                "provenance": "source_site_import",
                "import_status": "discovered",
                "selected_for_draft": False,
                "candidate_quality": "useful",
            },
        ],
    }
    service.seo_migration_repository.save_workspace(workspace)
    service.session.commit()

    readiness = service.get_draft_generation_readiness(business_id=business_id, site_id=site_id)
    assert readiness.get("ready") is True
    assert "media_required_but_not_selected" in set(readiness.get("warning_reason_codes") or [])
    assert readiness.get("media_required_by_operator") is True
    assert readiness.get("media_requirement_satisfied") is False
    assert readiness.get("media_requirement_warning_reason") == "media_required_but_not_selected"
    assert readiness.get("selected_usable_media_assets_count") == 0
    assert readiness.get("usable_media_assets_count") == 0
    assert readiness.get("useful_discovered_images_count") == 1
    assert readiness.get("low_value_discovered_images_count") == 1
    assert readiness.get("rejected_discovered_images_count") == 1


def test_artifact_quality_flags_required_media_missing_when_placeholders_are_present() -> None:
    quality = evaluate_migration_artifact_quality(
        {
            "generated_files": [
                {
                    "path": "index.html",
                    "media_type": "text/html",
                    "content": (
                        "<html><body>"
                        "<h1>Project Photo Placeholder</h1>"
                        "<p>Draft gallery slot - replace with a real project photo.</p>"
                        "</body></html>"
                    ),
                }
            ],
            "operator_requirements": {
                "business_objectives": [
                    "Use real project photos from existing jobs and include before/after examples."
                ],
            },
            "selected_usable_media_assets_count": 0,
            "media_required_by_operator": True,
        }
    )
    assert isinstance(quality, dict)
    issues = quality.get("issues")
    assert isinstance(issues, list)
    assert any(
        isinstance(item, dict)
        and item.get("type") == "required_media_missing"
        and item.get("severity") in {"warning", "needs_review"}
        for item in issues
    )
    operator_summary = str(quality.get("operator_summary") or "")
    assert "real/existing project images were requested" in operator_summary.lower()
    assert "No quality issues detected" not in operator_summary


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
    assert latest.get("evaluation_context") == "workspace_summary"


def test_draft_generation_readiness_expected_operator_blockers_log_info(db_session, caplog) -> None:
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

    caplog.set_level(logging.INFO, logger="app.services.seo_migration")
    service.get_workspace_summary(business_id=business_id, site_id=site_id)
    records = [
        record
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_readiness_evaluation"
    ]
    assert records
    latest_record = records[-1]
    latest_payload = latest_record.__dict__["json_fields"]
    assert latest_record.levelno == logging.INFO
    assert latest_payload.get("readiness_status") == "not_ready"
    assert latest_payload.get("hard_blocked") is True
    blocking_codes = set(latest_payload.get("blocking_reason_codes") or [])
    assert "source_site_ingest_required" in blocking_codes
    assert "operator_requirements_required" in blocking_codes


def test_draft_generation_readiness_generate_attempt_blocked_logs_warning_not_error(db_session, caplog) -> None:
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

    caplog.set_level(logging.INFO, logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError, match="Not ready yet"):
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )
    assert tracking_provider.call_count == 0
    records = [
        record
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_readiness_evaluation"
    ]
    assert records
    latest_record = records[-1]
    latest_payload = latest_record.__dict__["json_fields"]
    assert latest_payload.get("evaluation_context") == "draft_generate_attempt"
    assert latest_payload.get("readiness_status") == "not_ready"
    assert latest_record.levelno == logging.WARNING
    assert latest_record.levelno < logging.ERROR


def test_draft_generation_readiness_unknown_blocker_logs_warning_non_error(db_session, caplog) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)

    caplog.set_level(logging.INFO, logger="app.services.seo_migration")
    service._log_draft_readiness_evaluation(
        business_id=business_id,
        site_id=site_id,
        workspace_id="workspace-1",
        readiness_status="not_ready",
        readiness_score=0,
        hard_blocked=True,
        blocking_reason_codes=["unexpected_blocker_state"],
        warning_reason_codes=[],
        log_context="workspace_summary",
    )
    records = [
        record
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_readiness_evaluation"
    ]
    assert records
    latest_record = records[-1]
    assert latest_record.levelno == logging.WARNING
    assert latest_record.levelno < logging.ERROR


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


def test_deploy_ensures_managed_site_static_ip_before_dispatch_and_records_metadata(
    db_session, caplog, monkeypatch
) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=True,
        ensure_static_ip_result="created",
        ensure_static_ip_address="34.160.224.212",
        ensure_static_ip_credential_source="service_account_json",
        ensure_static_ip_principal_email="mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
        ensure_static_ip_impersonated_service_account_email=(
            "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
        ),
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    monkeypatch.setattr(
        seo_migration_module,
        "_resolve_hostname_ipv4_addresses",
        lambda _hostname: ["34.160.224.212"],
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.deploy_calls
    ensure_call = publisher.ensure_managed_site_static_ip_calls[-1]
    assert ensure_call[0] == "acme"
    assert ensure_call[1] == "tnmfire-site"
    assert ensure_call[2] == site_id
    assert ensure_call[5] is False
    expected_static_ip_name, _ = derive_site_preview_static_ip_name(
        repo_name="tnmfire-site",
        site_id=site_id,
    )
    assert deploy_result.result.get("expected_static_ip_name") == expected_static_ip_name
    assert deploy_result.result.get("expected_static_ip_address") == "34.160.224.212"
    assert deploy_result.result.get("static_ip_created") is True
    assert deploy_result.result.get("static_ip_ensure_result") == "created"
    assert deploy_result.result.get("static_ip_project_id")
    assert deploy_result.result.get("static_ip_gcp_credential_source") == "service_account_json"
    assert (
        deploy_result.result.get("static_ip_gcp_principal_email")
        == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert (
        deploy_result.result.get("static_ip_gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    ensure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_static_ip_ensure"
    ]
    assert ensure_logs
    assert ensure_logs[-1].get("result") == "created"
    assert ensure_logs[-1].get("gcp_credential_source") == "service_account_json"
    assert ensure_logs[-1].get("gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert (
        ensure_logs[-1].get("gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert ensure_logs[-1].get("operation") == "ensure"
    assert "gcp_deploy_key" not in json.dumps(ensure_logs[-1]).lower()
    assert "private_key" not in json.dumps(ensure_logs[-1]).lower()


def test_deploy_ensures_managed_site_static_ip_existing_before_dispatch(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
        ensure_static_ip_address="34.149.170.250",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.deploy_calls
    assert deploy_result.result.get("static_ip_created") is False
    assert deploy_result.result.get("static_ip_ensure_result") == "exists"


def test_deploy_ensures_managed_site_static_ip_handles_already_exists_race(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="already_exists_after_race",
        ensure_static_ip_address="34.149.170.250",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.deploy_calls
    assert deploy_result.result.get("static_ip_created") is False
    assert deploy_result.result.get("static_ip_ensure_result") == "already_exists_after_race"


def test_deploy_blocks_dispatch_when_managed_site_static_ip_ensure_fails(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_static_ip_ensure=True,
        static_ip_ensure_error_code="managed_site_static_ip_permission_denied",
        static_ip_ensure_error_message="Simulated static IP provisioning permission failure.",
        static_ip_ensure_error_stage="static_ip_provision",
        static_ip_ensure_error_diagnostics={
            "static_ip_operation": "create",
            "static_ip_error_category": "permission_denied",
            "static_ip_error_code": "PERMISSION_DENIED",
            "static_ip_error_summary": "Permission denied while creating static IP.",
            "static_ip_exit_code": None,
            "static_ip_permission_hint": "Grant compute.globalAddresses.create permission.",
            "gcp_credential_source": "service_account_json",
            "gcp_principal_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
            "gcp_impersonated_service_account_email": "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError, match="Simulated static IP provisioning permission failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert publisher.ensure_managed_site_static_ip_calls
    assert not publisher.deploy_calls
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_site_static_ip_permission_denied"
    assert latest.get("dispatch_service_reason_code") == "managed_site_static_ip_permission_denied"
    assert latest.get("dispatch_result_stage") == "static_ip_provision"
    assert latest.get("static_ip_operation") == "create"
    assert latest.get("static_ip_error_category") == "permission_denied"
    assert latest.get("static_ip_error_code") == "PERMISSION_DENIED"
    assert latest.get("static_ip_error_summary") == "Permission denied while creating static IP."
    assert latest.get("static_ip_permission_hint") == "Grant compute.globalAddresses.create permission."
    assert latest.get("static_ip_gcp_credential_source") == "service_account_json"
    assert latest.get("static_ip_gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert (
        latest.get("static_ip_gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    ensure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_static_ip_ensure"
    ]
    assert ensure_logs
    assert ensure_logs[-1].get("result") == "failed"
    assert ensure_logs[-1].get("reason_code") == "managed_site_static_ip_permission_denied"
    assert ensure_logs[-1].get("static_ip_operation") == "create"
    assert ensure_logs[-1].get("static_ip_error_category") == "permission_denied"
    assert ensure_logs[-1].get("static_ip_error_code") == "PERMISSION_DENIED"
    assert ensure_logs[-1].get("static_ip_error_summary") == "Permission denied while creating static IP."
    assert ensure_logs[-1].get("static_ip_permission_hint") == "Grant compute.globalAddresses.create permission."
    assert ensure_logs[-1].get("gcp_credential_source") == "service_account_json"
    assert ensure_logs[-1].get("gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert (
        ensure_logs[-1].get("gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert ensure_logs[-1].get("operation") == "create"
    assert "gcp_deploy_key" not in json.dumps(ensure_logs[-1]).lower()
    assert "private_key" not in json.dumps(ensure_logs[-1]).lower()
    assert "access_token" not in json.dumps(ensure_logs[-1]).lower()


def test_deploy_blocks_dispatch_when_managed_site_static_ip_config_is_missing(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_static_ip_ensure=True,
        static_ip_ensure_error_code="managed_site_static_ip_config_missing",
        static_ip_ensure_error_message="Simulated static IP config missing.",
        static_ip_ensure_error_stage="static_ip_provision",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError, match="Simulated static IP config missing."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert publisher.ensure_managed_site_static_ip_calls
    assert not publisher.deploy_calls
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_site_static_ip_config_missing"
    assert latest.get("dispatch_service_reason_code") == "managed_site_static_ip_config_missing"


def test_deploy_blocks_dispatch_when_managed_deploy_impersonation_permission_denied(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_static_ip_ensure=True,
        static_ip_ensure_error_code="managed_deploy_impersonation_permission_denied",
        static_ip_ensure_error_message="Simulated managed deploy impersonation permission denied.",
        static_ip_ensure_error_stage="static_ip_provision",
        static_ip_ensure_error_diagnostics={
            "gcp_credential_source": "managed_deploy_impersonation",
            "gcp_principal_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
            "gcp_impersonated_service_account_email": "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com",
            "static_ip_permission_hint": (
                "Grant roles/iam.serviceAccountTokenCreator to mbsrn-api@mbsrn-prod.iam.gserviceaccount.com "
                "on mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com."
            ),
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError, match="impersonation permission denied"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert publisher.ensure_managed_site_static_ip_calls
    assert not publisher.deploy_calls
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_deploy_impersonation_permission_denied"
    assert latest.get("dispatch_service_reason_code") == "managed_deploy_impersonation_permission_denied"
    assert latest.get("dispatch_result_stage") == "static_ip_provision"
    assert latest.get("static_ip_gcp_credential_source") == "managed_deploy_impersonation"
    assert (
        latest.get("static_ip_gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )


def test_deploy_ensures_managed_site_dns_after_static_ip_and_before_dispatch(
    db_session, caplog, monkeypatch
) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=True,
        ensure_static_ip_result="created",
        ensure_static_ip_address="34.160.224.212",
        ensure_static_ip_credential_source="service_account_json",
        ensure_static_ip_principal_email="mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
        ensure_dns_created=True,
        ensure_dns_updated=False,
        ensure_dns_result="created",
        ensure_dns_expected_ip="34.160.224.212",
        ensure_dns_previous_ips=(),
        ensure_dns_ttl=300,
        ensure_dns_credential_source="service_account_json",
        ensure_dns_principal_email="mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
        ensure_dns_impersonated_service_account_email=(
            "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
        ),
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    monkeypatch.setattr(
        seo_migration_module,
        "_resolve_hostname_ipv4_addresses",
        lambda _hostname: ["34.160.224.212"],
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.ensure_managed_site_dns_calls
    assert publisher.deploy_calls
    assert publisher.deploy_call_order[:3] == ["ensure_static_ip", "ensure_dns", "dispatch_deploy"]
    dns_call = publisher.ensure_managed_site_dns_calls[-1]
    assert dns_call[0].endswith(".site.mbsrn.com")
    assert dns_call[1] == "34.160.224.212"
    assert dns_call[2] == "sites"
    assert dns_call[6] is False
    assert deploy_result.result.get("expected_dns_hostname")
    assert deploy_result.result.get("expected_dns_hostname").endswith(".site.mbsrn.com")
    assert deploy_result.result.get("expected_dns_managed_zone") == "sites"
    assert deploy_result.result.get("expected_dns_project_id")
    assert deploy_result.result.get("expected_dns_ip") == "34.160.224.212"
    assert deploy_result.result.get("dns_record_created") is True
    assert deploy_result.result.get("dns_record_updated") is False
    assert deploy_result.result.get("dns_previous_ips") == []
    assert deploy_result.result.get("dns_ttl") == 300
    assert deploy_result.result.get("dns_ensure_result") == "created"
    assert deploy_result.result.get("dns_gcp_credential_source") == "service_account_json"
    assert deploy_result.result.get("dns_gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert (
        deploy_result.result.get("dns_gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert deploy_result.result.get("dns_propagation_result") == "observed_expected_ip"
    assert deploy_result.result.get("dns_propagation_observed_ips") == ["34.160.224.212"]
    assert deploy_result.result.get("observed_dns_ips") == ["34.160.224.212"]
    assert deploy_result.result.get("dns_propagation_attempts") == 1
    ensure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_dns_ensure"
    ]
    assert ensure_logs
    assert ensure_logs[-1].get("result") == "created"
    assert ensure_logs[-1].get("gcp_credential_source") == "service_account_json"
    assert ensure_logs[-1].get("gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert (
        ensure_logs[-1].get("gcp_impersonated_service_account_email")
        == "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert ensure_logs[-1].get("operation") == "ensure"
    assert "gcp_deploy_key" not in json.dumps(ensure_logs[-1]).lower()
    propagation_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_dns_propagation_check"
    ]
    assert propagation_logs
    assert propagation_logs[-1].get("result") == "observed_expected_ip"
    assert propagation_logs[-1].get("dns_expected_ip") == dns_call[1]
    assert propagation_logs[-1].get("observed_dns_ips") == ["34.160.224.212"]
    assert "gcp_deploy_key" not in json.dumps(propagation_logs[-1]).lower()
    prerequisite_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event")
        == "seo_migration_managed_deploy_prerequisite_chain"
    ]
    assert prerequisite_logs
    stages = [str(log.get("stage")) for log in prerequisite_logs]
    assert "static_ip_ensured" in stages
    assert "dns_ensure_start" in stages
    assert "dns_ensure_succeeded" in stages
    assert "dns_propagation_start" in stages
    assert "dns_propagation_succeeded" in stages


def test_deploy_refreshes_static_ip_address_in_same_request_before_dns_ensure(
    db_session, monkeypatch
) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_addresses=(None, "34.160.224.212"),
        ensure_static_ip_created=True,
        ensure_static_ip_result="created",
        ensure_dns_created=True,
        ensure_dns_updated=False,
        ensure_dns_result="created",
        ensure_dns_expected_ip="34.160.224.212",
        ensure_dns_previous_ips=(),
        ensure_dns_ttl=300,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    monkeypatch.setattr(
        seo_migration_module,
        "_resolve_hostname_ipv4_addresses",
        lambda _hostname: ["34.160.224.212"],
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert len(publisher.ensure_managed_site_static_ip_calls) == 2
    assert publisher.ensure_managed_site_dns_calls
    dns_call = publisher.ensure_managed_site_dns_calls[-1]
    assert dns_call[1] == "34.160.224.212"
    assert publisher.deploy_calls
    assert deploy_result.result.get("expected_static_ip_address") == "34.160.224.212"
    assert deploy_result.result.get("expected_dns_ip") == "34.160.224.212"
    assert deploy_result.result.get("dns_propagation_result") == "observed_expected_ip"


def test_deploy_blocks_before_dns_ensure_when_static_ip_address_missing_after_refresh(
    db_session, caplog
) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_address=None,
        ensure_static_ip_addresses=(None, None),
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    caplog.set_level("INFO", logger="app.services.seo_migration")

    with pytest.raises(SEOMigrationValidationError, match="did not return an address value"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert len(publisher.ensure_managed_site_static_ip_calls) == 2
    assert publisher.ensure_managed_site_dns_calls == []
    assert publisher.deploy_calls == []
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_site_static_ip_address_missing"
    assert latest.get("dispatch_service_reason_code") == "managed_site_static_ip_address_missing"
    assert latest.get("dispatch_result_stage") == "static_ip_provision"
    prerequisite_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event")
        == "seo_migration_managed_deploy_prerequisite_chain"
    ]
    assert prerequisite_logs
    missing_logs = [
        log for log in prerequisite_logs if log.get("stage") == "static_ip_address_missing"
    ]
    assert missing_logs
    assert missing_logs[-1].get("reason_code") == "managed_site_static_ip_address_missing"
    assert missing_logs[-1].get("static_ip_address_present") is False
    assert missing_logs[-1].get("dns_expected_ip_present") is False


def test_deploy_ensures_managed_site_dns_updates_old_ips_before_dispatch(db_session, monkeypatch) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
        ensure_static_ip_address="34.160.224.212",
        ensure_dns_created=False,
        ensure_dns_updated=True,
        ensure_dns_result="updated",
        ensure_dns_expected_ip="34.160.224.212",
        ensure_dns_previous_ips=("34.149.170.250", "34.149.170.251"),
        ensure_dns_ttl=300,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    monkeypatch.setattr(
        seo_migration_module,
        "_resolve_hostname_ipv4_addresses",
        lambda _hostname: ["34.160.224.212"],
    )

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.ensure_managed_site_dns_calls
    assert publisher.deploy_calls
    assert deploy_result.result.get("dns_record_created") is False
    assert deploy_result.result.get("dns_record_updated") is True
    assert deploy_result.result.get("dns_previous_ips") == ["34.149.170.250", "34.149.170.251"]
    assert deploy_result.result.get("dns_ensure_result") == "updated"
    assert deploy_result.result.get("dns_propagation_result") == "observed_expected_ip"


def test_deploy_waits_for_dns_propagation_then_dispatches_when_match_observed(
    db_session, monkeypatch, caplog
) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
        ensure_static_ip_address="34.149.170.250",
        ensure_dns_created=False,
        ensure_dns_updated=True,
        ensure_dns_result="updated",
        ensure_dns_expected_ip="34.149.170.250",
        ensure_dns_previous_ips=("34.149.170.249",),
        ensure_dns_ttl=300,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    resolution_attempts = iter([[], ["34.149.170.250"]])

    def _resolve_with_delay(_hostname: object) -> list[str]:
        try:
            return next(resolution_attempts)
        except StopIteration:
            return ["34.149.170.250"]

    sleep_calls: list[object] = []
    monkeypatch.setattr(seo_migration_module, "_resolve_hostname_ipv4_addresses", _resolve_with_delay)
    monkeypatch.setattr(seo_migration_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    caplog.set_level("INFO", logger="app.services.seo_migration")

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    assert publisher.deploy_calls
    assert sleep_calls
    assert deploy_result.result.get("dns_propagation_result") == "observed_expected_ip_after_retry"
    assert int(deploy_result.result.get("dns_propagation_attempts") or 0) >= 2
    assert deploy_result.result.get("dns_propagation_observed_ips") == ["34.149.170.250"]
    propagation_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_dns_propagation_check"
    ]
    assert propagation_logs
    assert propagation_logs[-1].get("result") == "observed_expected_ip_after_retry"
    assert propagation_logs[-1].get("observed_dns_ips") == ["34.149.170.250"]


def test_deploy_blocks_dispatch_when_dns_propagation_times_out_before_dispatch(
    db_session, monkeypatch, caplog
) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
        ensure_static_ip_address="34.149.170.250",
        ensure_dns_created=False,
        ensure_dns_updated=True,
        ensure_dns_result="updated",
        ensure_dns_expected_ip="34.149.170.250",
        ensure_dns_previous_ips=("34.149.170.251",),
        ensure_dns_ttl=300,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key='{"type":"service_account","private_key":"sensitive"}',
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
    monkeypatch.setattr(seo_migration_module, "_resolve_hostname_ipv4_addresses", lambda _hostname: [])
    monkeypatch.setattr(seo_migration_module, "_MANAGED_SITE_DNS_PROPAGATION_MAX_WAIT_SECONDS", 0)
    caplog.set_level("INFO", logger="app.services.seo_migration")

    with pytest.raises(SEOMigrationValidationError, match="DNS propagation is still pending"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.ensure_managed_site_dns_calls
    assert not publisher.deploy_calls
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_site_dns_propagation_pending"
    assert latest.get("dispatch_service_reason_code") == "managed_site_dns_propagation_pending"
    assert latest.get("dispatch_result_stage") == "dns_propagation"
    assert latest.get("expected_dns_ip") == "34.149.170.250"
    assert latest.get("observed_dns_ips") == []
    propagation_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_dns_propagation_check"
    ]
    assert propagation_logs
    assert propagation_logs[-1].get("result") == "pending"
    assert propagation_logs[-1].get("dns_expected_ip") == "34.149.170.250"
    assert propagation_logs[-1].get("observed_dns_ips") == []
    assert propagation_logs[-1].get("preview_hostname")
    assert propagation_logs[-1].get("dns_managed_zone") == "sites"
    assert propagation_logs[-1].get("dns_project_id")
    assert "private_key" not in caplog.text.lower()


def test_deploy_blocks_dispatch_when_managed_site_dns_conflicting_record(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
        ensure_static_ip_address="34.160.224.212",
        fail_dns_ensure=True,
        dns_ensure_error_code="managed_site_dns_conflicting_record",
        dns_ensure_error_message="Simulated DNS conflicting record.",
        dns_ensure_error_stage="dns_provision",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError, match="Simulated DNS conflicting record."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.ensure_managed_site_dns_calls
    assert not publisher.deploy_calls
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_site_dns_conflicting_record"
    assert latest.get("dispatch_service_reason_code") == "managed_site_dns_conflicting_record"
    assert latest.get("dispatch_result_stage") == "dns_provision"
    ensure_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_site_dns_ensure"
    ]
    assert ensure_logs
    assert ensure_logs[-1].get("result") == "failed"
    assert ensure_logs[-1].get("reason_code") == "managed_site_dns_conflicting_record"
    assert "gcp_deploy_key" not in json.dumps(ensure_logs[-1]).lower()


def test_deploy_blocks_dispatch_when_managed_site_dns_permission_denied(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        ensure_static_ip_created=False,
        ensure_static_ip_result="exists",
        ensure_static_ip_address="34.160.224.212",
        fail_dns_ensure=True,
        dns_ensure_error_code="managed_site_dns_permission_denied",
        dns_ensure_error_message="Simulated DNS permission denied.",
        dns_ensure_error_stage="dns_provision",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError, match="Simulated DNS permission denied."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    assert publisher.ensure_managed_site_static_ip_calls
    assert publisher.ensure_managed_site_dns_calls
    assert not publisher.deploy_calls
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest = deploy_history[-1]
    assert latest.get("failure_reason") == "managed_site_dns_permission_denied"
    assert latest.get("dispatch_service_reason_code") == "managed_site_dns_permission_denied"
    assert latest.get("dispatch_result_stage") == "dns_provision"


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
    assert refresh_result.result.get("deploy_https_ready") is True
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
    assert "GIT_TOKEN" not in " ".join(refresh_logs)


def test_refresh_deploy_status_current_live_probe_overrides_selected_failed_attempt_for_current_runtime(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=777888,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=777888,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="managed_site_static_ip_address_missing",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Resolve live URL from ingress status",
        refresh_workflow_output={
            "host_reachable": "false",
            "deploy_https_ready": "false",
            "https_probe_error_summary": "",
        },
        current_live_probe_result={
            "live_url": "https://lars-construction.site.mbsrn.com/",
            "host_reachable": True,
            "host_reachability_scheme": "https",
            "deploy_https_ready": True,
            "cert_identity_valid": True,
            "https_probe_status_code": 200,
            "https_probe_error_summary": None,
            "source": "current_live_probe",
            "checked_at": "2026-04-07T12:15:00+00:00",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_conclusion") == "failure"
    assert refresh_result.result.get("selected_workflow_attempt_conclusion") == "failure"
    assert refresh_result.result.get("selected_workflow_failure_reason") == "managed_site_static_ip_address_missing"
    assert refresh_result.result.get("current_deploy_https_ready") is True
    assert refresh_result.result.get("current_live_url") == "https://lars-construction.site.mbsrn.com/"
    assert refresh_result.result.get("current_live_runtime_status") == "success"
    assert refresh_result.result.get("current_live_evidence_source") == "current_live_probe"

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest_entry = deploy_history[-1]
    assert latest_entry.get("workflow_run_conclusion") == "failure"
    assert latest_entry.get("workflow_run_failure_reason_code") == "managed_site_static_ip_address_missing"
    assert latest_entry.get("current_deploy_https_ready") is True
    assert latest_entry.get("current_live_url") == "https://lars-construction.site.mbsrn.com/"

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    destination = (summary.context_summary or {}).get("destination_summary") or {}
    deploy_destination = destination.get("deploy_destination") or {}
    assert deploy_readiness.get("deploy_https_ready") is True
    assert deploy_readiness.get("current_deploy_https_ready") is True
    assert deploy_readiness.get("selected_workflow_attempt_conclusion") == "failure"
    assert deploy_readiness.get("selected_workflow_failure_reason") == "managed_site_static_ip_address_missing"
    assert "current live HTTPS evidence is healthy" in str(deploy_readiness.get("current_live_runtime_note") or "")
    assert deploy_readiness.get("dns_record_matches_ingress") is True
    assert deploy_readiness.get("ingress_conflict_detected") is False
    assert deploy_readiness.get("tls_certificate_status") == "ACTIVE"
    assert deploy_readiness.get("tls_domain_status") == "ACTIVE"
    assert deploy_destination.get("state") == "active_live"
    assert deploy_destination.get("active_url") == "https://lars-construction.site.mbsrn.com/"
    assert deploy_destination.get("url_source") == "current_live_probe"
    assert publisher.current_live_probe_calls


def test_refresh_deploy_status_current_live_probe_failure_sets_bounded_summary(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910115,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910115,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="ingress_endpoint_not_ready",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Resolve live URL from ingress status",
        refresh_workflow_output={
            "host_reachable": "false",
            "deploy_https_ready": "false",
        },
        fail_current_live_probe=True,
        current_live_probe_error_message="temporary probe timeout",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("current_deploy_https_ready") is False
    assert refresh_result.result.get("current_live_runtime_status") in {"blocked", "pending"}
    assert "reason=https_probe_failed_after_control_plane_ready" in str(
        refresh_result.result.get("current_https_probe_error_summary") or ""
    )


def test_refresh_deploy_status_falls_back_to_latest_deploy_record_for_current_live_probe(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910116,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910116,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="ingress_endpoint_not_ready",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Resolve live URL from ingress status",
        current_live_probe_result={
            "live_url": "https://sc-mechanical.site.mbsrn.com/",
            "host_reachable": True,
            "host_reachability_scheme": "https",
            "deploy_https_ready": True,
            "cert_identity_valid": True,
            "https_probe_status_code": 200,
            "source": "current_live_probe",
            "checked_at": "2026-04-07T12:25:00+00:00",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    deployed_artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)
    non_deployed_artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=non_deployed_artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("refresh_history_scope") == "latest_deploy_record"
    assert refresh_result.result.get("current_deploy_https_ready") is True
    assert refresh_result.result.get("current_live_url") == "https://sc-mechanical.site.mbsrn.com/"
    assert publisher.current_live_probe_calls

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace.deploy_history_json or []
    assert deploy_history
    latest_entry = deploy_history[-1]
    assert latest_entry.get("artifact_version_id") == deployed_artifact.id
    assert latest_entry.get("current_deploy_https_ready") is True
    assert latest_entry.get("current_live_url") == "https://sc-mechanical.site.mbsrn.com/"


def test_refresh_deploy_status_metadata_missing_still_persists_current_live_probe_fields(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910117,
        deploy_workflow_run_status="in_progress",
        current_live_probe_result={
            "live_url": "https://sc-mechanical.site.mbsrn.com/",
            "host_reachable": True,
            "host_reachability_scheme": "https",
            "deploy_https_ready": True,
            "cert_identity_valid": True,
            "https_probe_status_code": 200,
            "source": "current_live_probe",
            "checked_at": "2026-04-07T12:30:00+00:00",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = [dict(item) for item in (workspace.deploy_history_json or []) if isinstance(item, dict)]
    assert deploy_history
    latest_entry = dict(deploy_history[-1])
    latest_entry["repo_owner"] = None
    latest_entry["repo_name"] = None
    latest_entry["workflow_id"] = None
    latest_entry["workflow_identifier_used"] = None
    latest_entry["workflow_file_path"] = None
    latest_entry["ref"] = None
    deploy_history[-1] = latest_entry
    workspace.deploy_history_json = deploy_history
    workspace.publish_config_json = {
        "enabled": True,
        "repo_owner": None,
        "repo_name": None,
        "branch": None,
        "artifact_root": None,
    }
    workspace.deploy_config_json = {
        "enabled": True,
        "workflow_id": None,
        "ref": None,
    }
    db_session.add(workspace)
    db_session.commit()

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("status") == "no_change"
    assert refresh_result.result.get("no_change_reason") == "deploy_target_metadata_missing"
    assert refresh_result.result.get("current_deploy_https_ready") is True
    assert refresh_result.result.get("current_live_url") == "https://sc-mechanical.site.mbsrn.com/"
    assert publisher.current_live_probe_calls

    refreshed_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    refreshed_history = refreshed_workspace.deploy_history_json or []
    assert refreshed_history
    refreshed_latest_entry = refreshed_history[-1]
    assert refreshed_latest_entry.get("current_deploy_https_ready") is True
    assert refreshed_latest_entry.get("current_live_url") == "https://sc-mechanical.site.mbsrn.com/"
    assert refreshed_latest_entry.get("current_live_evidence_source") == "current_live_probe"


def test_refresh_deploy_status_dns_mismatch_sets_dns_failure_and_blocks_https_ready(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910001,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910001,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="dns_record_mismatch",
        refresh_workflow_run_failure_stage="ingress_verify",
        refresh_workflow_run_failure_step="Validate DNS against ingress IP",
        refresh_workflow_output={
            "dns_expected_ip": "34.120.10.20",
            "dns_observed_ip": "34.120.10.99",
            "ingress_ip": "34.120.10.20",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "dns_record_mismatch"
    assert refresh_result.result.get("dns_record_matches_ingress") is False
    assert refresh_result.result.get("dns_expected_ip") == "34.120.10.20"
    assert refresh_result.result.get("dns_observed_ip") == "34.120.10.99"
    assert refresh_result.result.get("ingress_ip") == "34.120.10.20"
    assert refresh_result.result.get("deploy_https_ready") is False
    assert refresh_result.result.get("post_dispatch_state") == "workflow_run_failed"

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("dns_record_matches_ingress") is False
    assert deploy_readiness.get("deploy_https_ready") is False


def test_refresh_deploy_status_https_probe_timeout_after_control_plane_ready_surfaces_probe_summary(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910101,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910101,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="https_probe_timeout",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Resolve live URL from ingress status",
        refresh_workflow_output={
            "dns_record_matches_ingress": "true",
            "dns_expected_ip": "34.95.101.96",
            "dns_observed_ip": "34.95.101.96",
            "tls_certificate_status": "ACTIVE",
            "tls_domain_status": "ACTIVE",
            "cert_identity_valid": "true",
            "host_reachable": "false",
            "host_reachability_scheme": "https",
            "https_probe_error_summary": (
                "reason=https_probe_timeout;exit_code=28;status=000;"
                "detail=operation timed out after control plane was ready"
            ),
            "deploy_https_ready": "false",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "https_probe_timeout"
    assert refresh_result.result.get("deploy_https_ready") is False
    assert refresh_result.result.get("host_reachable") is False
    assert refresh_result.result.get("host_reachability_scheme") == "https"
    assert "https_probe_timeout" in str(refresh_result.result.get("https_probe_error_summary") or "")

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("deploy_https_ready") is False
    assert deploy_readiness.get("host_reachable") is False
    assert "https_probe_timeout" in str(deploy_readiness.get("https_probe_error_summary") or "")
    assert "backend health" in str(deploy_readiness.get("last_workflow_run_failure_hint") or "").lower()


def test_refresh_deploy_status_https_probe_not_attempted_surfaces_reason_and_hint(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910102,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910102,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="https_probe_not_attempted",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Resolve live URL from ingress status",
        refresh_workflow_output={
            "host_reachable": "false",
            "https_probe_error_summary": "reason=https_probe_not_attempted;detail=preview_host_missing",
            "deploy_https_ready": "false",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "https_probe_not_attempted"
    assert refresh_result.result.get("deploy_https_ready") is False
    assert refresh_result.result.get("host_reachable") is False
    assert "https_probe_not_attempted" in str(refresh_result.result.get("https_probe_error_summary") or "")
    assert "not attempted" in str(refresh_result.result.get("workflow_run_failure_hint") or "").lower()


def test_refresh_deploy_status_certificate_domain_mismatch_blocks_https_ready(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910002,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910002,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="tls_certificate_bound_to_wrong_site",
        refresh_workflow_run_failure_stage="ingress_verify",
        refresh_workflow_run_failure_step="Validate certificate domain",
        refresh_workflow_output={
            "tls_certificate_status": "ACTIVE",
            "tls_domain_status": "MISMATCHED",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "tls_certificate_bound_to_wrong_site"
    assert refresh_result.result.get("cert_identity_valid") is False
    assert refresh_result.result.get("tls_certificate_status") == "ACTIVE"
    assert refresh_result.result.get("tls_domain_status") == "MISMATCHED"
    assert refresh_result.result.get("deploy_https_ready") is False
    assert refresh_result.result.get("post_dispatch_state") == "workflow_run_failed"


def test_refresh_deploy_status_failed_not_visible_sets_dns_and_tls_failure_context(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910003,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910003,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="managed_certificate_failed_not_visible",
        refresh_workflow_run_failure_stage="ingress_verify",
        refresh_workflow_run_failure_step="Validate managed certificate domain visibility",
        refresh_workflow_output={
            "dns_expected_ip": "34.120.10.20",
            "dns_observed_ip": "34.120.10.99",
            "ingress_ip": "34.120.10.20",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "managed_certificate_failed_not_visible"
    assert refresh_result.result.get("dns_record_matches_ingress") is False
    assert refresh_result.result.get("tls_certificate_status") == "FAILED_NOT_VISIBLE"
    assert refresh_result.result.get("tls_domain_status") == "FAILED_NOT_VISIBLE"
    assert refresh_result.result.get("deploy_https_ready") is False
    assert "dns/ingress exposure" in str(refresh_result.result.get("workflow_run_failure_hint") or "").lower()


def test_refresh_deploy_status_static_ip_conflict_blocks_success(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910004,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910004,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="shared_static_ip_not_allowed_for_per_site_ingress",
        refresh_workflow_run_failure_stage="ingress_verify",
        refresh_workflow_run_failure_step="Validate ingress static IP isolation",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == (
        "shared_static_ip_not_allowed_for_per_site_ingress"
    )
    assert refresh_result.result.get("ingress_conflict_detected") is True
    assert refresh_result.result.get("deploy_https_ready") is False


def test_refresh_deploy_status_managed_site_static_ip_missing_sets_actionable_hint(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910004,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910004,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="managed_site_static_ip_missing",
        refresh_workflow_run_failure_stage="ingress_verify",
        refresh_workflow_run_failure_step="Verify expected per-site static IP exists",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "managed_site_static_ip_missing"
    assert "expected per-site global static ip" in str(
        refresh_result.result.get("workflow_run_failure_hint") or ""
    ).lower()


def test_refresh_deploy_status_expected_static_ip_not_bound_flags_ingress_conflict(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910004,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910004,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="expected_static_ip_not_bound_to_ingress",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Validate ingress static IP binding",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "expected_static_ip_not_bound_to_ingress"
    assert refresh_result.result.get("ingress_conflict_detected") is True
    assert "expected per-site static ip annotation binding" in str(
        refresh_result.result.get("workflow_run_failure_hint") or ""
    ).lower()


def test_static_ip_reason_code_hint_mappings_cover_missing_and_not_bound() -> None:
    assert "Expected per-site global static IP" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_missing"
        )
        or ""
    )
    assert "missing the expected per-site static ip annotation binding" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="expected_static_ip_not_bound_to_ingress"
        )
        or ""
    ).lower()
    assert "create/reserve the deterministic site static ip" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_missing",
        )
        or ""
    ).lower()
    assert "missing the expected per-site static ip annotation binding" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="expected_static_ip_not_bound_to_ingress",
        )
        or ""
    ).lower()


def test_managed_certificate_domain_drift_reason_code_hint_mappings() -> None:
    assert "safe delete/recreate repair was attempted" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_certificate_domain_drift_repaired"
        )
        or ""
    ).lower()
    assert "did not converge" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_certificate_domain_drift_repair_failed"
        )
        or ""
    ).lower()
    assert "automatic safe repair was attempted" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_certificate_domain_drift_repaired",
        )
        or ""
    ).lower()
    assert "persisted after safe repair attempt" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_certificate_domain_drift_repair_failed",
        )
        or ""
    ).lower()
    assert "safe delete/recreate repair was attempted" in str(
        seo_migration_module._derive_workflow_run_failure_hint(
            failure_reason="managed_certificate_domain_drift_repaired",
            post_dispatch_state=None,
        )
        or ""
    ).lower()
    assert "persisted after safe repair attempt" in str(
        seo_migration_module._derive_workflow_run_failure_hint(
            failure_reason="managed_certificate_domain_drift_repair_failed",
            post_dispatch_state=None,
        )
        or ""
    ).lower()


def test_static_ip_pre_dispatch_reason_code_hint_mappings_cover_config_and_provisioning_failures() -> None:
    assert "configuration is incomplete" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_config_missing"
        )
        or ""
    ).lower()
    assert "provisioning failed in control plane" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_provisioning_failed"
        )
        or ""
    ).lower()
    assert "did not return an address value" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_address_missing"
        )
        or ""
    ).lower()
    assert "config is missing" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_config_missing",
        )
        or ""
    ).lower()
    assert "provisioning failed before workflow dispatch" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_provisioning_failed",
        )
        or ""
    ).lower()
    assert "did not return an address" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_address_missing",
        )
        or ""
    ).lower()
    assert "not authorized" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_permission_denied"
        )
        or ""
    ).lower()
    assert "compute engine api" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_api_disabled"
        )
        or ""
    ).lower()
    assert "quota" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_quota_exceeded"
        )
        or ""
    ).lower()
    assert "project configuration is invalid" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_project_not_found"
        )
        or ""
    ).lower()
    assert "name conflict" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_static_ip_conflict"
        )
        or ""
    ).lower()
    assert "not authorized" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_permission_denied",
        )
        or ""
    ).lower()
    assert "enable the api" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_api_disabled",
        )
        or ""
    ).lower()
    assert "quota" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_quota_exceeded",
        )
        or ""
    ).lower()
    assert "project id is invalid" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_project_not_found",
        )
        or ""
    ).lower()
    assert "conflicts with an existing unmanaged resource" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_static_ip_conflict",
        )
        or ""
    ).lower()
    assert "did not return an address value" in str(
        seo_migration_module._derive_workflow_run_failure_hint(
            failure_reason="managed_site_static_ip_address_missing",
            post_dispatch_state=None,
        )
        or ""
    ).lower()


def test_managed_deploy_impersonation_reason_code_hint_mappings() -> None:
    assert "gcp_managed_deploy" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_deploy_impersonation_config_invalid"
        )
        or ""
    ).lower()
    assert "tokencreator" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_deploy_impersonation_permission_denied"
        )
        or ""
    ).lower()
    assert "gcp_managed_deploy is invalid" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_deploy_impersonation_config_invalid",
        )
        or ""
    ).lower()
    assert "tokencreator" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_deploy_impersonation_permission_denied",
        )
        or ""
    ).lower()
    assert "gcp_managed_deploy is invalid" in str(
        seo_migration_module._derive_workflow_run_failure_hint(
            failure_reason="managed_deploy_impersonation_config_invalid",
            post_dispatch_state=None,
        )
        or ""
    ).lower()
    assert "tokencreator" in str(
        seo_migration_module._derive_workflow_run_failure_hint(
            failure_reason="managed_deploy_impersonation_permission_denied",
            post_dispatch_state=None,
        )
        or ""
    ).lower()


def test_dns_pre_dispatch_reason_code_hint_mappings_cover_config_conflict_permission_and_conflict_retry() -> None:
    assert "dns provisioning configuration is incomplete" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_dns_config_missing"
        )
        or ""
    ).lower()
    assert "dns a-record provisioning failed in control plane" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_dns_provisioning_failed"
        )
        or ""
    ).lower()
    assert "conflicting dns record type" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_dns_conflicting_record"
        )
        or ""
    ).lower()
    assert "not authorized" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_dns_permission_denied"
        )
        or ""
    ).lower()
    assert "transaction conflict" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_dns_transaction_conflict"
        )
        or ""
    ).lower()
    assert "propagation is still pending" in str(
        seo_migration_module._derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code="managed_site_dns_propagation_pending"
        )
        or ""
    ).lower()
    assert "config is missing" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_dns_config_missing",
        )
        or ""
    ).lower()
    assert "dns a-record provisioning failed" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_dns_provisioning_failed",
        )
        or ""
    ).lower()
    assert "conflicting non-a dns record" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_dns_conflicting_record",
        )
        or ""
    ).lower()
    assert "cloud dns permissions" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_dns_permission_denied",
        )
        or ""
    ).lower()
    assert "concurrent transaction conflict" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_dns_transaction_conflict",
        )
        or ""
    ).lower()
    assert "resolver propagation has not reached" in str(
        seo_migration_module._derive_deploy_failure_remediation_hint(
            failure_reason=None,
            failure_stage=None,
            workflow_exists=None,
            dispatch_service_reason_code="managed_site_dns_propagation_pending",
        )
        or ""
    ).lower()


def test_refresh_deploy_status_stale_pre_shared_cert_binding_blocks_success(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910005,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910005,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="stale_pre_shared_cert_binding_detected",
        refresh_workflow_run_failure_stage="ingress_verify",
        refresh_workflow_run_failure_step="Validate pre-shared certificate annotation",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "stale_pre_shared_cert_binding_detected"
    assert refresh_result.result.get("ingress_conflict_detected") is True
    assert refresh_result.result.get("deploy_https_ready") is False


def test_refresh_deploy_status_pre_shared_cert_metadata_mismatch_is_advisory(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910005,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910005,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="pre_shared_cert_metadata_mismatch",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Inspect pre-shared certificate metadata",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "pre_shared_cert_metadata_mismatch"
    assert refresh_result.result.get("workflow_run_failure_stage") == "ingress_evidence"
    assert "advisory by itself" in str(refresh_result.result.get("workflow_run_failure_hint") or "").lower()
    assert refresh_result.result.get("ingress_conflict_detected") is not True
    assert refresh_result.result.get("deploy_https_ready") is False


def test_refresh_deploy_status_managed_certificate_metadata_unavailable_is_advisory(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910006,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910006,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="managed_certificate_metadata_unavailable",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Collect managed certificate evidence",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "managed_certificate_metadata_unavailable"
    assert refresh_result.result.get("workflow_run_failure_stage") == "ingress_evidence"
    assert "treat this as advisory" in str(refresh_result.result.get("workflow_run_failure_hint") or "").lower()
    assert refresh_result.result.get("ingress_conflict_detected") is not True


def test_refresh_deploy_status_ingress_status_ip_stale_reason_is_advisory(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910005,
        deploy_workflow_run_status="in_progress",
        refresh_workflow_run_id=910005,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="ingress_status_ip_stale_or_mismatched",
        refresh_workflow_run_failure_stage="ingress_evidence",
        refresh_workflow_run_failure_step="Validate reserved static IP binding",
        refresh_workflow_output={
            "dns_expected_ip": "34.95.101.96",
            "dns_observed_ip": "34.95.101.96",
            "ingress_ip": "34.120.56.254",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_and_request_deploy(service, business_id=business_id, site_id=site_id)

    refresh_result = service.refresh_deploy_run_status(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        principal_id="principal-1",
    )
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "ingress_status_ip_stale_or_mismatched"
    assert refresh_result.result.get("workflow_run_failure_stage") == "ingress_evidence"
    assert "lagging metadata" in str(refresh_result.result.get("workflow_run_failure_hint") or "").lower()
    assert refresh_result.result.get("dns_record_matches_ingress") is not False
    assert refresh_result.result.get("ingress_conflict_detected") is not True


def test_deploy_completed_success_requires_https_live_url_for_https_ready(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=910006,
        deploy_workflow_run_status="completed",
        deploy_workflow_run_conclusion="success",
        deploy_workflow_output={
            "live_url": "http://tnmfire.site.mbsrn.com",
            "deploy_https_ready": "true",
            "dns_record_matches_ingress": "true",
            "cert_identity_valid": "true",
        },
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("workflow_run_status") == "completed"
    assert deploy_result.result.get("workflow_run_conclusion") == "success"
    assert deploy_result.result.get("resolved_live_url") == "http://tnmfire.site.mbsrn.com"
    assert deploy_result.result.get("post_dispatch_state") == "workflow_run_succeeded_without_live_url"
    assert deploy_result.result.get("deploy_https_ready") is False

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


def test_refresh_deploy_status_records_in_cluster_probe_timeout_hint(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=998880,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=998880,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="in_cluster_service_probe_timeout",
        refresh_workflow_run_failure_stage="rollout_verify",
        refresh_workflow_run_failure_step="Verify service and ingress",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)
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
    assert refresh_result.result.get("workflow_run_failure_reason_code") == "in_cluster_service_probe_timeout"
    assert refresh_result.result.get("workflow_run_failure_stage") == "rollout_verify"
    assert refresh_result.result.get("workflow_run_failure_step") == "Verify service and ingress"
    assert refresh_result.result.get("workflow_run_failure_hint") == (
        "In-cluster service probe timed out reaching site-web on cluster-local DNS. "
        "Likely causes are NetworkPolicy ingress blocking, selector/port mismatch, or pod listener readiness."
    )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("last_workflow_run_failure_reason_code") == "in_cluster_service_probe_timeout"
    assert deploy_readiness.get("last_workflow_run_failure_hint") == (
        "In-cluster service probe timed out reaching site-web on cluster-local DNS. "
        "Likely causes are NetworkPolicy ingress blocking, selector/port mismatch, or pod listener readiness."
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
    assert isinstance(workflow_call[10], dict)
    assert workflow_call[11] == site_id
    assert workflow_call[14] == artifact.id
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
    runtime_context_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_publish_runtime_context"' in record.msg
    ]
    assert runtime_context_logs
    assert '"dry_run": false' in runtime_context_logs[-1].msg
    assert '"allow_repair": true' in runtime_context_logs[-1].msg
    assert '"bootstrap_allowed": true' in runtime_context_logs[-1].msg
    assert '"remediation_mode": "bootstrap"' in runtime_context_logs[-1].msg


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
    assert isinstance(workflow_call[10], dict)
    assert workflow_call[11] == site_id
    assert workflow_call[14] == artifact.id
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


def test_adopt_publish_repository_writes_marker_and_returns_readiness(db_session) -> None:
    publisher = _RecordingGitHubPublisher(adoption_marker_written=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)

    action_result = service.adopt_publish_repository(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert action_result.result.get("marker_written") is True
    assert action_result.result.get("adoption_outcome") == "marker_written"
    assert action_result.result.get("reason_code") == "github_repo_management_marker_written"
    assert action_result.readiness.get("target", {}).get("repo_owner") == "acme"
    assert len(publisher.adopt_repository_calls) == 1


def test_adopt_publish_repository_surfaces_adoption_failure(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        fail_adoption=True,
        adoption_error_code="github_repo_management_marker_mismatch",
        adoption_error_message="Repository is marked for a different migration site.",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError, match="different migration site"):
        service.adopt_publish_repository(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )

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
def test_deploy_stale_pending_blocker_is_reconciled_and_still_active_blocks_duplicate(
    db_session,
    caplog,
    active_run_status: str,
) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status=active_run_status,
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=445566,
        refresh_workflow_run_status=active_run_status,
        refresh_workflow_run_conclusion=None,
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
    stale_activity_at = (utc_now() - timedelta(minutes=15)).isoformat()
    latest_deploy_item["refreshed_at"] = stale_activity_at
    latest_deploy_item["dispatched_at"] = stale_activity_at
    latest_deploy_item["occurred_at"] = stale_activity_at
    latest_deploy_item["timestamp"] = stale_activity_at
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
    assert len(publisher.refresh_calls) == 1

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
    assert duplicate_target.get("blocking_deploy_trace_id") == stale_trace_id
    assert duplicate_target.get("blocking_reconciliation_attempted") is True
    assert duplicate_target.get("blocking_reconciliation_result") == "active"
    assert duplicate_target.get("blocking_reconciliation_reason_code") == "duplicate_request"

    reconciliation_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event")
        == "seo_migration_deploy_duplicate_blocker_reconciliation"
    ]
    assert reconciliation_payloads
    assert reconciliation_payloads[-1].get("blocking_deploy_trace_id") == stale_trace_id
    assert reconciliation_payloads[-1].get("reconciliation_result") == "active"
    assert reconciliation_payloads[-1].get("reason_code") == "duplicate_request"


def test_deploy_retry_allowed_when_duplicate_blocker_reconciles_to_terminal(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=445566,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="rollout_verification_failed",
        refresh_workflow_run_failure_stage="rollout_verify",
        refresh_workflow_run_failure_step="Verify rollout",
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
    stale_deploy_item = next(
        (
            dict(item)
            for item in reversed(history)
            if str(item.get("action") or "").strip().lower() == "deploy"
            and str(item.get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert stale_deploy_item is not None
    stale_trace_id = str(stale_deploy_item.get("deploy_trace_id") or "")
    assert stale_trace_id
    stale_activity_at = (utc_now() - timedelta(minutes=15)).isoformat()
    stale_deploy_item["refreshed_at"] = stale_activity_at
    stale_deploy_item["dispatched_at"] = stale_activity_at
    stale_deploy_item["occurred_at"] = stale_activity_at
    stale_deploy_item["timestamp"] = stale_activity_at
    workspace.deploy_history_json = [stale_deploy_item]
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
    assert len(publisher.refresh_calls) == 1

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    reconciled_entry = next(
        (
            item
            for item in workspace.deploy_history_json or []
            if str(item.get("deploy_trace_id") or "") == stale_trace_id
        ),
        None,
    )
    assert reconciled_entry is not None
    assert reconciled_entry.get("workflow_run_status") == "completed"
    assert reconciled_entry.get("workflow_run_conclusion") == "failure"
    assert reconciled_entry.get("post_dispatch_state") == "workflow_run_failed"
    assert reconciled_entry.get("workflow_run_failure_reason_code") == "rollout_verification_failed"
    assert reconciled_entry.get("workflow_run_failure_stage") == "rollout_verify"
    assert reconciled_entry.get("workflow_run_failure_step") == "Verify rollout"

    reconciliation_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event")
        == "seo_migration_deploy_duplicate_blocker_reconciliation"
        and record.__dict__["json_fields"].get("blocking_deploy_trace_id") == stale_trace_id
    ]
    assert reconciliation_payloads
    assert reconciliation_payloads[-1].get("reconciliation_result") == "terminal_cleared"


def test_duplicate_blocker_reconciliation_failure_returns_deploy_error(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    secret_token = "ghp_super_secret_token_for_test"
    secret_private_key = "-----BEGIN PRIVATE KEY-----\\nsecret\\n-----END PRIVATE KEY-----"
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        fail_refresh=True,
        refresh_error_code="github_timeout",
        refresh_error_message="Simulated refresh timeout.",
        refresh_error_stage="workflow_run_lookup",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key=json.dumps({"type": "service_account", "private_key": secret_private_key}),
        deploy_secret_git_token=secret_token,
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
    blocking_item = next(
        (
            dict(item)
            for item in reversed(history)
            if str(item.get("action") or "").strip().lower() == "deploy"
            and str(item.get("status") or "").strip().lower() == "deploy_requested"
        ),
        None,
    )
    assert blocking_item is not None
    stale_activity_at = (utc_now() - timedelta(minutes=15)).isoformat()
    blocking_item["refreshed_at"] = stale_activity_at
    blocking_item["dispatched_at"] = stale_activity_at
    blocking_item["occurred_at"] = stale_activity_at
    blocking_item["timestamp"] = stale_activity_at
    workspace.deploy_history_json = [blocking_item]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(SEOMigrationValidationError, match="Unable to reconcile previous deploy blocker with GitHub") as exc:
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert exc.value.failure_category == "deploy_error"
    assert exc.value.failure_reason == "deploy_blocker_reconciliation_failed"
    assert len(publisher.deploy_calls) == 1
    assert len(publisher.refresh_calls) == 1

    deploy_failure_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "deploy"
        and record.__dict__["json_fields"].get("failure_category") == "deploy_error"
    ]
    assert deploy_failure_payloads
    failure_payload = deploy_failure_payloads[-1]
    target_payload = failure_payload.get("target") or {}
    assert failure_payload.get("failure_reason") == "deploy_blocker_reconciliation_failed"
    assert target_payload.get("blocking_reconciliation_result") == "refresh_failed"
    assert target_payload.get("blocking_reconciliation_reason_code") == "deploy_blocker_reconciliation_failed"

    target_blob = json.dumps(target_payload, sort_keys=True)
    assert secret_token not in target_blob
    assert secret_private_key not in target_blob
    assert "deploy_secret_git_token" not in target_blob
    assert "deploy_secret_gcp_key" not in target_blob

    logged_messages = "\n".join(record.msg for record in caplog.records if isinstance(record.msg, str))
    assert secret_token not in logged_messages
    assert secret_private_key not in logged_messages

    assert seo_migration_module._derive_deploy_failure_remediation_hint(
        failure_reason="deploy_blocker_reconciliation_failed",
        failure_stage="workflow_dispatch",
        workflow_exists=None,
        dispatch_service_reason_code=None,
    ) == (
        "Previous deploy may still be active, but blocker reconciliation with GitHub failed. "
        "Refresh deploy status and retry after run state is confirmed."
    )


def test_stale_duplicate_blocker_refresh_failure_requires_manual_refresh(db_session, caplog) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        fail_refresh=True,
        refresh_error_code="github_timeout",
        refresh_error_message="Simulated stale refresh timeout.",
        refresh_error_stage="workflow_run_lookup",
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
    stale_activity_at = (utc_now() - timedelta(minutes=90)).isoformat()
    stale_item["refreshed_at"] = stale_activity_at
    stale_item["dispatched_at"] = stale_activity_at
    stale_item["occurred_at"] = stale_activity_at
    stale_item["timestamp"] = stale_activity_at
    workspace.deploy_history_json = [stale_item]
    service.seo_migration_repository.save_workspace(workspace)
    db_session.commit()

    with pytest.raises(
        SEOMigrationValidationError,
        match="Previous deploy appears stale; refresh deploy status and retry deploy",
    ) as exc:
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert exc.value.failure_category == "deploy_error"
    assert exc.value.failure_reason == "stale_deploy_blocker_requires_refresh"
    assert len(publisher.deploy_calls) == 1
    assert len(publisher.refresh_calls) == 1

    deploy_failure_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "deploy"
        and record.__dict__["json_fields"].get("failure_category") == "deploy_error"
    ]
    assert deploy_failure_payloads
    target_payload = deploy_failure_payloads[-1].get("target") or {}
    assert target_payload.get("blocking_reconciliation_result") == "stale_requires_manual_refresh"
    assert target_payload.get("blocking_reconciliation_reason_code") == "stale_deploy_blocker_requires_refresh"

    reconciliation_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event")
        == "seo_migration_deploy_duplicate_blocker_reconciliation"
    ]
    assert reconciliation_payloads
    assert reconciliation_payloads[-1].get("reconciliation_result") == "stale_requires_manual_refresh"
    assert reconciliation_payloads[-1].get("reason_code") == "stale_deploy_blocker_requires_refresh"

    assert seo_migration_module._derive_deploy_failure_remediation_hint(
        failure_reason="stale_deploy_blocker_requires_refresh",
        failure_stage="workflow_dispatch",
        workflow_exists=None,
        dispatch_service_reason_code=None,
    ) == (
        "Previous deploy blocker appears stale and could not be safely reconciled automatically. "
        "Run deploy status refresh, confirm terminal state, then retry deploy."
    )


def test_very_stale_duplicate_blocker_refresh_failure_is_superseded_and_retry_proceeds(
    db_session,
    caplog,
) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    secret_token = "ghp_stale_blocker_secret_token"
    secret_private_key = "-----BEGIN PRIVATE KEY-----\\nvery-secret\\n-----END PRIVATE KEY-----"
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        fail_refresh=True,
        refresh_error_code="github_timeout",
        refresh_error_message="Simulated stale blocker refresh timeout.",
        refresh_error_stage="workflow_run_lookup",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
        deploy_secret_gcp_key=json.dumps({"type": "service_account", "private_key": secret_private_key}),
        deploy_secret_git_token=secret_token,
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
    stale_item["refreshed_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["timestamp"] = "2000-01-01T00:00:00+00:00"
    workspace.deploy_history_json = [stale_item]
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
    assert len(publisher.refresh_calls) == 1

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    superseded_entry = next(
        (
            item
            for item in workspace.deploy_history_json or []
            if str(item.get("deploy_trace_id") or "") == stale_trace_id
        ),
        None,
    )
    assert superseded_entry is not None
    assert superseded_entry.get("post_dispatch_state") == "workflow_run_failed"
    assert superseded_entry.get("workflow_run_status") == "completed"
    assert superseded_entry.get("workflow_run_conclusion") == "failure"
    assert superseded_entry.get("workflow_run_failure_reason_code") == "stale_deploy_blocker_superseded"
    assert superseded_entry.get("workflow_run_failure_stage") == "workflow_execution"

    supersede_payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_deploy_stale_blocker_superseded"
    ]
    assert supersede_payloads
    latest_supersede_payload = supersede_payloads[-1]
    assert latest_supersede_payload.get("blocking_deploy_trace_id") == stale_trace_id
    assert latest_supersede_payload.get("supersede_reason_code") == "deploy_blocker_superseded_after_stale_threshold"
    assert latest_supersede_payload.get("prior_state") in {
        "workflow_run_pending",
        "workflow_run_in_progress",
    }
    assert latest_supersede_payload.get("refreshed_state") in {
        "workflow_run_pending",
        "workflow_run_in_progress",
    }
    assert int(latest_supersede_payload.get("blocker_age_seconds") or 0) >= 2 * 60 * 60
    assert latest_supersede_payload.get("principal_id") == "principal-1"
    assert "target_environment_key" in latest_supersede_payload

    target_blob = json.dumps(latest_supersede_payload, sort_keys=True)
    assert secret_token not in target_blob
    assert secret_private_key not in target_blob
    assert "deploy_secret_git_token" not in target_blob
    assert "deploy_secret_gcp_key" not in target_blob
    assert secret_token not in caplog.text
    assert secret_private_key not in caplog.text

    assert seo_migration_module._derive_deploy_failure_remediation_hint(
        failure_reason="deploy_blocker_superseded_after_stale_threshold",
        failure_stage="workflow_dispatch",
        workflow_exists=None,
        dispatch_service_reason_code=None,
    ) == (
        "Previous deploy blocker exceeded the hard stale threshold and was superseded automatically. "
        "Retry deploy and inspect GitHub Actions history if an orphan run is suspected."
    )
    assert seo_migration_module._derive_workflow_run_failure_hint(
        failure_reason="stale_deploy_blocker_superseded",
        post_dispatch_state="workflow_run_failed",
    ) == (
        "Previous deploy blocker exceeded the hard stale threshold without reliable active-run evidence. "
        "Blocker was superseded so deploy retry can proceed."
    )


def test_very_stale_duplicate_blocker_with_explicitly_active_run_still_blocks(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=445566,
        refresh_workflow_run_status="in_progress",
        refresh_workflow_run_conclusion=None,
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
    stale_item["refreshed_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["timestamp"] = "2000-01-01T00:00:00+00:00"
    workspace.deploy_history_json = [stale_item]
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
    assert len(publisher.refresh_calls) == 1


def test_very_stale_duplicate_blocker_terminal_refresh_still_clears_and_retries(
    db_session,
) -> None:
    publisher = _RecordingGitHubPublisher(
        deploy_workflow_run_id=445566,
        deploy_workflow_run_status="in_progress",
        deploy_workflow_run_conclusion=None,
        refresh_workflow_run_id=445566,
        refresh_workflow_run_status="completed",
        refresh_workflow_run_conclusion="failure",
        refresh_workflow_run_failure_reason_code="rollout_verification_failed",
        refresh_workflow_run_failure_stage="rollout_verify",
        refresh_workflow_run_failure_step="Verify rollout",
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
    stale_item["refreshed_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["dispatched_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["occurred_at"] = "2000-01-01T00:00:00+00:00"
    stale_item["timestamp"] = "2000-01-01T00:00:00+00:00"
    workspace.deploy_history_json = [stale_item]
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
    assert len(publisher.refresh_calls) == 1


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


def test_publish_dry_run_reports_repo_auto_create_capability_without_creating_repo(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_repository=False)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _set_admin_repo_auto_create_enabled(db_session, enabled=True)
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

    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=True,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    assert publisher.ensure_repository_calls
    assert all(call[3] is False for call in publisher.ensure_repository_calls)
    assert publisher.publish_preflight_calls
    assert publish_result.result.get("repository_ensure_attempted") is False
    assert publish_result.result.get("repository_auto_create_created") is False
    assert publish_result.result.get("repo_ensure_outcome") == "would_create_on_publish"
    assert publish_result.result.get("publish_preflight_status") == "ready_with_actions"
    assert publish_result.result.get("publish_preflight_would_auto_create_repo") is True
    assert publish_result.result.get("publish_preflight_blocker_code") is None


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
        (
            "image_pull_secret_missing",
            "private managed-site image auth is required",
        ),
        (
            "image_pull_secret_not_referenced",
            "managed deployment manifest is missing required image pull secret reference",
        ),
        (
            "deployed_content_identity_mismatch",
            "managed deployment manifest image identity does not match this site/repo target",
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


def test_deploy_readiness_surfaces_workflow_integrity_mismatch_without_blocking_dispatch(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        readiness_dispatch_service_availability=True,
        readiness_dispatch_service_reason_code="available",
        readiness_workflow_integrity_status="mismatch",
        readiness_workflow_integrity_reason_code="managed_workflow_signature_mismatch",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    artifact = _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.result.get("workflow_integrity_status") == "mismatch"
    assert deploy_result.result.get("workflow_integrity_reason_code") == "managed_workflow_signature_mismatch"
    assert deploy_result.result.get("dispatch_service_reason_code") == "available"
    assert publisher.deploy_calls

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("workflow_integrity_status") == "mismatch"
    assert deploy_readiness.get("workflow_integrity_reason_code") == "managed_workflow_signature_mismatch"
    assert deploy_readiness.get("dispatch_service_reason_code") == "available"


def test_deploy_readiness_surfaces_workflow_integrity_missing_for_unsigned_workflow(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        readiness_dispatch_service_availability=True,
        readiness_dispatch_service_reason_code="available",
        readiness_workflow_integrity_status="missing",
        readiness_workflow_integrity_reason_code="managed_workflow_signature_missing",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _prepare_published_artifact(service, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    deploy_readiness = summary.deploy_readiness or {}
    assert deploy_readiness.get("workflow_integrity_status") == "missing"
    assert deploy_readiness.get("workflow_integrity_reason_code") == "managed_workflow_signature_missing"


@pytest.mark.parametrize(
    (
        "managed_details",
        "latest_traceability",
        "last_published_at",
        "last_deployed_at",
        "expected_state",
    ),
    [
        (
            {
                "site_runtime_image_repository_observed": "ghcr.io/mhanson13/site-web",
                "site_runtime_image_reference_observed": "ghcr.io/mhanson13/site-web:latest",
            },
            {},
            datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
            "managed_workflow_not_yet_republished",
        ),
        (
            {
                "site_runtime_image_repository_observed": "ghcr.io/mhanson13/scmechanical-site-web",
                "site_runtime_image_reference_observed": "ghcr.io/mhanson13/scmechanical-site-web:latest",
            },
            {},
            datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
            "workflow_republished_but_deploy_not_rerun",
        ),
        (
            {
                "site_runtime_image_repository_observed": "ghcr.io/mhanson13/scmechanical-site-web",
                "site_runtime_image_reference_observed": "ghcr.io/mhanson13/scmechanical-site-web:latest",
            },
            {
                "site_runtime_image_repository": "ghcr.io/mhanson13/site-web",
                "site_runtime_image_reference": "ghcr.io/mhanson13/site-web:latest",
            },
            datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
            "deploy_running_old_generic_image",
        ),
        (
            {
                "site_runtime_image_repository_observed": "ghcr.io/mhanson13/scmechanical-site-web",
                "site_runtime_image_reference_observed": "ghcr.io/mhanson13/scmechanical-site-web:latest",
            },
            {
                "site_runtime_image_repository": "ghcr.io/mhanson13/scmechanical-site-web",
                "site_runtime_image_reference": "ghcr.io/mhanson13/scmechanical-site-web:sha12345",
            },
            datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
            "deploy_running_expected_site_scoped_image",
        ),
    ],
)
def test_derive_managed_site_rollout_state_distinguishes_rollout_phases(
    managed_details: dict[str, object],
    latest_traceability: dict[str, object],
    last_published_at: datetime,
    last_deployed_at: datetime,
    expected_state: str,
) -> None:
    workspace = SimpleNamespace(
        last_published_at=last_published_at,
        last_deployed_at=last_deployed_at,
    )
    result = seo_migration_module._derive_managed_site_rollout_state(
        deploy_workflow_mode="site_repo_template_v1",
        repo_owner="mhanson13",
        repo_name="scmechanical",
        managed_gke_config_details=managed_details,
        latest_traceability=latest_traceability,
        workspace=workspace,
    )
    assert result.get("managed_site_rollout_state") == expected_state
    if expected_state == "deploy_running_expected_site_scoped_image":
        assert result.get("managed_site_rollout_fix_active") is True
    else:
        assert result.get("managed_site_rollout_fix_active") is False


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
    assert deploy_destination.get("preview_hostname") == "tnmfire-site.site.mbsrn.com"
    assert deploy_destination.get("preview_url") == "https://tnmfire-site.site.mbsrn.com"
    assert deploy_destination.get("preview_state") == "expected_after_deploy"
    assert deploy_destination.get("customer_domain_url") == "https://tnmfire-www.example"
    assert deploy_destination.get("customer_domain_state") == "pending_cutover"
    assert deploy_destination.get("customer_domain_live_url") is None
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


def test_publish_missing_repo_with_auto_create_disabled_returns_precise_failure(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_repository=False)
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
        approval_notes="Approved for publish",
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="repository auto-create is disabled"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message="Publish migration",
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    assert publisher.ensure_repository_calls
    assert all(call[2] is False for call in publisher.ensure_repository_calls)
    assert all(call[3] is False for call in publisher.ensure_repository_calls)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = summary.publish_readiness
    reasons = readiness.get("reasons") if isinstance(readiness.get("reasons"), list) else []
    target = readiness.get("target") if isinstance(readiness.get("target"), dict) else {}
    assert any("auto-create is disabled" in str(reason).lower() for reason in reasons)
    assert target.get("repository_auto_create_enabled") is False
    assert target.get("repository_exists") is False
    assert target.get("repo_ensure_outcome") == "skipped_policy_disabled"


def test_publish_missing_repo_with_auto_create_enabled_creates_repo_and_continues(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_repository=False)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _set_admin_repo_auto_create_enabled(db_session, enabled=True)
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

    assert publisher.ensure_repository_calls
    assert any(call[2] is True and call[3] is True for call in publisher.ensure_repository_calls)
    assert publish_result.result.get("repository_auto_create_enabled") is True
    assert publish_result.result.get("repository_ensure_attempted") is True
    assert publish_result.result.get("repository_auto_create_created") is True
    assert publish_result.result.get("repository_ensure_outcome") == "repo_created"
    assert publish_result.result.get("repo_ensure_outcome") == "created"


@pytest.mark.parametrize(
    ("provision_error_code", "expected_failure_category"),
    (
        ("github_workflow_write_not_authorized", "config_missing"),
        ("github_contents_write_not_authorized", "config_missing"),
        ("github_branch_not_found_or_uninitialized", "target_invalid"),
        ("github_repo_state_invalid_for_bootstrap", "target_invalid"),
    ),
)
def test_publish_new_repo_preserves_precise_workflow_provision_failure_code(
    db_session,
    caplog,
    provision_error_code: str,
    expected_failure_category: str,
) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        existing_repository=False,
        fail_workflow_provision=True,
        workflow_provision_error_code=provision_error_code,
        workflow_provision_error_message="Simulated workflow provisioning failure.",
        workflow_provision_error_stage="workflow_provisioning",
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _set_admin_repo_auto_create_enabled(db_session, enabled=True)
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
        approval_notes="Approved for publish",
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated workflow provisioning failure"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message="Publish migration",
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    assert publisher.ensure_repository_calls
    assert any(call[2] is True and call[3] is True for call in publisher.ensure_repository_calls)
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = workspace.publish_history_json or []
    assert publish_history
    latest_history_item = publish_history[-1]
    assert latest_history_item.get("status") == "failed"
    assert latest_history_item.get("failure_reason") == provision_error_code
    assert latest_history_item.get("repository_auto_create_created") is True
    assert latest_history_item.get("repo_ensure_outcome") == "created"
    assert latest_history_item.get("failure_reason") != "github_request_failed"

    failed_action_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "publish"
        and record.__dict__["json_fields"].get("status") == "failed"
    ]
    assert failed_action_logs
    failed_payload = failed_action_logs[-1]
    target_payload = failed_payload.get("target") or {}
    assert failed_payload.get("failure_category") == expected_failure_category
    assert target_payload.get("failure_reason_code") == provision_error_code
    assert target_payload.get("failure_reason_code") != "github_request_failed"
    assert target_payload.get("repository_auto_create_created") is True
    assert target_payload.get("repo_ensure_outcome") == "created"


@pytest.mark.parametrize(
    ("publish_error_code", "expected_failure_category"),
    (
        ("github_contents_write_not_authorized", "config_missing"),
        ("github_branch_not_found_or_uninitialized", "target_invalid"),
        ("github_contents_publish_failed", "provider_error"),
    ),
)
def test_publish_existing_repo_preserves_precise_publish_write_failure_code(
    db_session,
    caplog,
    publish_error_code: str,
    expected_failure_category: str,
) -> None:
    caplog.set_level("INFO", logger="app.services.seo_migration")
    publisher = _RecordingGitHubPublisher(
        existing_repository=True,
        fail_publish=True,
        publish_error_code=publish_error_code,
        publish_error_message="Simulated publish write failure.",
        publish_error_stage="publish",
    )
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
        approval_notes="Approved for publish",
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated publish write failure"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message="Publish migration",
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    assert publisher.ensure_repository_calls
    assert any(call[2] is False and call[3] is True for call in publisher.ensure_repository_calls)

    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    publish_history = workspace.publish_history_json or []
    assert publish_history
    latest_history_item = publish_history[-1]
    assert latest_history_item.get("status") == "failed"
    assert latest_history_item.get("failure_reason") == publish_error_code
    assert latest_history_item.get("repository_auto_create_created") is False
    assert latest_history_item.get("repo_ensure_outcome") == "exists"
    assert latest_history_item.get("failure_reason") != "github_request_failed"

    failed_action_logs = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
        and record.__dict__["json_fields"].get("action") == "publish"
        and record.__dict__["json_fields"].get("status") == "failed"
    ]
    assert failed_action_logs
    failed_payload = failed_action_logs[-1]
    target_payload = failed_payload.get("target") or {}
    assert failed_payload.get("failure_category") == expected_failure_category
    assert target_payload.get("failure_reason_code") == publish_error_code
    assert target_payload.get("failure_reason_code") != "github_request_failed"
    assert target_payload.get("repository_auto_create_created") is False
    assert target_payload.get("repo_ensure_outcome") == "exists"


def test_publish_readiness_reports_repo_auto_create_capability_for_missing_repo(db_session) -> None:
    publisher = _RecordingGitHubPublisher(existing_repository=False)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _set_admin_repo_auto_create_enabled(db_session, enabled=True)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = summary.publish_readiness
    target = readiness.get("target") if isinstance(readiness.get("target"), dict) else {}
    prerequisites = (
        readiness.get("config_prerequisites") if isinstance(readiness.get("config_prerequisites"), dict) else {}
    )

    assert target.get("repository_auto_create_enabled") is True
    assert target.get("repository_exists") is False
    assert target.get("repository_auto_create_available") is True
    assert target.get("repo_ensure_outcome") == "would_create_on_publish"
    assert target.get("preflight_status") == "ready_with_actions"
    assert target.get("would_auto_create_repo") is True
    assert target.get("preflight_blocker_code") is None
    assert prerequisites.get("publish_target_repo_exists") is False
    assert prerequisites.get("publish_target_repo_auto_create_available") is True
    assert prerequisites.get("publish_target_repo_ensure_summary") == "would_create_on_publish"
    assert prerequisites.get("publish_target_preflight_status") == "ready_with_actions"
    assert prerequisites.get("publish_target_would_auto_create_repo") is True


def test_publish_readiness_reports_workflow_write_blocker_from_preflight(db_session) -> None:
    publisher = _RecordingGitHubPublisher(
        existing_repository=True,
        preflight_blocker_code="github_workflow_write_not_authorized",
        preflight_can_read_contents=True,
        preflight_can_write_contents=True,
        preflight_can_write_workflows=False,
    )
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    readiness = summary.publish_readiness
    reasons = readiness.get("reasons") if isinstance(readiness.get("reasons"), list) else []
    target = readiness.get("target") if isinstance(readiness.get("target"), dict) else {}
    prerequisites = (
        readiness.get("config_prerequisites") if isinstance(readiness.get("config_prerequisites"), dict) else {}
    )

    assert readiness.get("ready") is False
    assert any("not authorized to write workflow files" in str(reason).lower() for reason in reasons)
    assert target.get("preflight_status") == "blocked"
    assert target.get("preflight_blocker_code") == "github_workflow_write_not_authorized"
    assert target.get("can_write_contents") is True
    assert target.get("can_write_workflows") is False
    assert prerequisites.get("publish_target_preflight_blocker_code") == "github_workflow_write_not_authorized"

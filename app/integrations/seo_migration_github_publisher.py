from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import logging
import re
import ssl
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

from app.core.log_sanitizer import sanitize_log_payload
from app.core.time import utc_now
from app.core.runtime_metadata import get_runtime_build_metadata

_LOGGER = logging.getLogger(__name__)
_VALID_REPO_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_VALID_REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_MANAGED_DEPLOY_SERVICE_ACCOUNT_EMAIL_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._-]{1,100}@[a-z0-9][a-z0-9-]{1,100}\.iam\.gserviceaccount\.com$"
)
_GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED = "github_workflow_write_not_authorized"
_GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED = "github_contents_write_not_authorized"
_GITHUB_REASON_BRANCH_UNINITIALIZED = "github_branch_not_found_or_uninitialized"
_GITHUB_REASON_REPO_BOOTSTRAP_INVALID = "github_repo_state_invalid_for_bootstrap"
_GITHUB_REASON_WORKFLOW_PROVISIONING_FAILED = "github_workflow_provisioning_failed"
_GITHUB_REASON_CONTENTS_PUBLISH_FAILED = "github_contents_publish_failed"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISSING = "github_repo_management_marker_missing"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISMATCH = "github_repo_management_marker_mismatch"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_INVALID = "github_repo_management_marker_invalid"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_PRESENT = "github_repo_management_marker_present"
_GITHUB_REASON_REPO_ADOPTION_REQUIRED = "github_repo_adoption_required"
_GITHUB_REASON_REPO_ADOPTION_FAILED = "github_repo_adoption_failed"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_WRITTEN = "github_repo_management_marker_written"
_GITHUB_REASON_REPO_BOOTSTRAP_MARKER_WRITE_FAILED = "github_repo_bootstrap_marker_write_failed"
_GITHUB_REASON_REPO_BASELINE_RECONCILIATION_FAILED = "github_repo_baseline_reconciliation_failed"
_GITHUB_REASON_REPO_INITIALIZATION_FAILED = "github_repo_initialization_failed"
_GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION = "github_repo_requires_manual_initialization"
_GITHUB_REASON_MANAGED_WORKFLOW_TEMPLATE_INVALID = "managed_workflow_template_invalid"
_MBSRN_REPO_MANAGEMENT_MARKER_PATH = "mbsrn.key"
_MANAGED_IMAGE_PULL_SECRET_ACTION_VALUES = {"created", "updated", "unchanged", "skipped"}


def _normalize_managed_image_pull_secret_action(
    value: object,
    *,
    allow_dry_run: bool = False,
) -> str:
    normalized = (_coerce_string(value) or "").strip().lower()
    allowed = set(_MANAGED_IMAGE_PULL_SECRET_ACTION_VALUES)
    if allow_dry_run:
        allowed.add("dry_run")
    if normalized in allowed:
        return normalized
    raise SEOMigrationGitHubPublisherError(
        code="image_pull_secret_provisioning_failed",
        safe_message="Managed image pull secret provisioning returned an invalid action status.",
        stage="image_pull_secret_provision",
    )


@dataclass(frozen=True)
class SEOMigrationGitHubPublishTarget:
    repo_owner: str
    repo_name: str
    branch: str
    artifact_root: str
    business_id: str | None = None
    site_id: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubPublishFile:
    path: str
    content: str | None = None
    media_type: str = "text/plain"
    content_bytes: bytes | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubPublishResult:
    dry_run: bool
    repo_owner: str
    repo_name: str
    branch: str
    artifact_root: str
    files_published: int
    total_bytes: int
    commit_shas: tuple[str, ...]
    committed_paths: tuple[str, ...]
    published_at: str


@dataclass(frozen=True)
class SEOMigrationGitHubActionsSecretUpsertResult:
    repo_owner: str
    repo_name: str
    secret_name: str
    action: str
    updated_at: str


@dataclass(frozen=True)
class SEOMigrationGitHubImagePullSecretProvisionResult:
    repo_owner: str
    repo_name: str
    namespace: str
    secret_name: str
    action: str


@dataclass(frozen=True)
class SEOMigrationGitHubManagedSiteStaticIPEnsureResult:
    static_ip_name: str
    static_ip_address: str | None
    static_ip_created: bool
    gcp_project_id: str
    result: str
    gcp_credential_source: str | None = None
    gcp_principal_email: str | None = None
    gcp_impersonated_service_account_email: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubManagedSiteDnsEnsureResult:
    dns_record_name: str
    dns_record_type: str
    dns_managed_zone: str
    dns_project_id: str
    dns_expected_ip: str
    dns_previous_ips: tuple[str, ...]
    dns_updated: bool
    dns_created: bool
    dns_ttl: int
    result: str
    gcp_credential_source: str | None = None
    gcp_principal_email: str | None = None
    gcp_impersonated_service_account_email: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubManagedCertificateReadinessResult:
    managed_certificate_name: str
    preview_hostname: str
    kubernetes_namespace: str
    managed_certificate_exists: bool
    certificate_domain_matches_expected: bool | None = None
    observed_managed_certificate_domains: tuple[str, ...] = ()
    observed_managed_certificate_status: str | None = None
    observed_managed_certificate_domain_status: str | None = None
    dispatch_service_reason_code: str | None = None
    gcp_credential_source: str | None = None
    gcp_principal_email: str | None = None
    gcp_impersonated_service_account_email: str | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubManagedCertificateEnsureResult:
    action: str
    readiness: SEOMigrationGitHubManagedCertificateReadinessResult


@dataclass(frozen=True)
class SEOMigrationGitHubRepositoryEnsureResult:
    repo_owner: str
    repo_name: str
    exists: bool
    auto_create_enabled: bool
    auto_create_attempted: bool
    auto_create_created: bool
    outcome: str
    skipped_reason: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubPublishPreflightResult:
    repo_owner: str
    repo_name: str
    target_ref: str
    repo_exists: bool
    repo_ensure_outcome: str
    target_ref_exists: bool
    repo_initialized: bool
    can_read_contents: bool
    can_write_contents: bool
    can_write_workflows: bool
    would_auto_create_repo: bool
    would_bootstrap_branch: bool
    preflight_status: str
    preflight_blocker_code: str | None = None
    repo_visibility_target: str | None = None
    repo_visibility_observed: str | None = None
    repo_baseline_required: bool | None = None
    repo_baseline_reconciliation_needed: bool | None = None
    readme_present: bool | None = None
    gitignore_present: bool | None = None
    license_present: bool | None = None
    repo_management_status: str | None = None
    repo_management_marker_present: bool | None = None
    repo_management_marker_valid: bool | None = None
    repo_management_marker_matches_site: bool | None = None
    repo_management_marker_business_id: str | None = None
    repo_management_marker_site_id: str | None = None
    repo_management_marker_source_ref: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubRepoAdoptionResult:
    repo_owner: str
    repo_name: str
    ref: str
    marker_written: bool
    adoption_outcome: str
    management_status: str
    marker_business_id: str | None = None
    marker_site_id: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubRepoManagementState:
    status: str
    marker_present: bool
    marker_valid: bool
    marker_matches_site: bool
    marker_business_id: str | None = None
    marker_site_id: str | None = None
    source_ref: str | None = None
    blocker_code: str | None = None
    blocker_message: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubRefEnsureResult:
    ref_exists: bool
    ref_created: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubDeployTarget:
    repo_owner: str
    repo_name: str
    workflow_id: str
    ref: str
    inputs: dict[str, str]


@dataclass(frozen=True)
class SEOMigrationGitHubDeployResult:
    dry_run: bool
    repo_owner: str
    repo_name: str
    workflow_id: str
    ref: str
    inputs: dict[str, str]
    dispatched_at: str
    live_url: str | None = None
    workflow_output: dict[str, str] | None = None
    workflow_run_id: int | None = None
    workflow_run_status: str | None = None
    workflow_run_conclusion: str | None = None
    workflow_run_failure_reason_code: str | None = None
    workflow_run_failure_stage: str | None = None
    workflow_run_failure_step: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubDeployRunStatusResult:
    repo_owner: str
    repo_name: str
    workflow_id: str
    ref: str
    workflow_run_id: int
    workflow_run_status: str | None = None
    workflow_run_conclusion: str | None = None
    workflow_output: dict[str, str] | None = None
    workflow_run_failure_reason_code: str | None = None
    workflow_run_failure_stage: str | None = None
    workflow_run_failure_step: str | None = None
    refreshed_at: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubLiveRuntimeProbeResult:
    probe_url: str
    checked_at: str
    source: str
    live_url: str | None = None
    host_reachable: bool | None = None
    host_reachability_scheme: str | None = None
    deploy_https_ready: bool | None = None
    cert_identity_valid: bool | None = None
    https_probe_status_code: int | None = None
    https_probe_error_summary: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubWorkflowProvisionResult:
    repo_owner: str
    repo_name: str
    branch: str
    workflow_id: str
    workflow_path: str
    provisioned: bool
    commit_sha: str | None
    deploy_workflow_mode: str | None = None
    target_environment_key: str | None = None
    target_environment_source: str | None = None
    kubernetes_namespace: str | None = None
    namespace_source: str | None = None
    preview_hostname: str | None = None
    managed_manifest_paths: tuple[str, ...] = ()
    namespace_model_status: str | None = None
    managed_resource_quota_expected: bool = False
    managed_resource_quota_present: bool | None = None
    managed_limit_range_expected: bool = False
    managed_limit_range_present: bool | None = None
    managed_network_policy_expected: bool = False
    managed_network_policy_present: bool | None = None
    managed_namespace_policies_aligned: bool | None = None
    managed_workflow_outcome: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubTargetReadinessResult:
    repo_owner: str
    repo_name: str
    requested_ref: str
    resolved_ref: str
    ref_source: str
    workflow_id: str
    workflow_path: str
    repo_exists: bool
    ref_exists: bool
    workflow_exists: bool
    workflow_dispatch_ready: bool
    workflow_dispatch_supported: bool
    workflow_trigger_types: tuple[str, ...]
    dispatch_service_availability: bool
    dispatch_service_reason_code: str | None
    dispatch_identifier_type: str
    remediation_mode: str
    workflow_conformance_checked: bool = False
    workflow_conformance_status: str = "workflow_conformance_unknown"
    workflow_conformance_reasons: tuple[str, ...] = ()
    workflow_conformance_evidence_summary: str | None = None
    kubernetes_namespace: str | None = None
    namespace_source: str | None = None
    preview_hostname: str | None = None
    workflow_namespace_aligned: bool | None = None
    manifest_namespace_aligned: bool | None = None
    namespace_model_status: str | None = None
    managed_resource_quota_expected: bool = False
    managed_resource_quota_present: bool | None = None
    managed_limit_range_expected: bool = False
    managed_limit_range_present: bool | None = None
    managed_network_policy_expected: bool = False
    managed_network_policy_present: bool | None = None
    managed_namespace_policies_aligned: bool | None = None
    dns_record_matches_ingress: bool | None = None
    dns_expected_ip: str | None = None
    dns_observed_ip: str | None = None
    tls_certificate_status: str | None = None
    tls_domain_status: str | None = None
    ingress_ip: str | None = None
    ingress_conflict_detected: bool | None = None
    cert_identity_valid: bool | None = None
    deploy_https_ready: bool | None = None
    workflow_integrity_status: str | None = None
    workflow_integrity_reason_code: str | None = None
    managed_gke_config_details: dict[str, object] | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubWorkflowConformanceResult:
    is_conformant: bool
    conformance_status: str
    conformance_reasons: tuple[str, ...]
    evidence_summary: str | None = None


@dataclass(frozen=True)
class SEOMigrationManagedWorkflowTemplateValidationResult:
    is_valid: bool
    validation_errors: tuple[str, ...]


@dataclass(frozen=True)
class SEOMigrationGitHubPublisherError(RuntimeError):
    code: str
    safe_message: str
    status_code: int | None = None
    stage: str | None = None
    provider_message: str | None = None
    diagnostics: dict[str, object] | None = None

    def __str__(self) -> str:
        return self.safe_message


class SEOMigrationGitHubPublisher:
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
            repo_management_status="managed_marker_match",
            repo_management_marker_present=True,
            repo_management_marker_valid=True,
            repo_management_marker_matches_site=True,
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
        del (
            repo_owner,
            repo_name,
            auto_create_enabled,
            create_if_missing,
            expected_owner,
            private_by_default,
        )
        raise NotImplementedError

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        raise NotImplementedError

    def upsert_actions_secret(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        secret_name: str,
        secret_value: str,
    ) -> SEOMigrationGitHubActionsSecretUpsertResult:
        raise NotImplementedError

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
        del (
            repo_owner,
            repo_name,
            ref,
            kubernetes_namespace,
            managed_gke_config,
            git_userid,
            git_email,
            git_token,
            gcp_deploy_key,
            dry_run,
        )
        raise NotImplementedError

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
        del (
            repo_owner,
            repo_name,
            site_id,
            managed_gke_config,
            gcp_deploy_key,
            dry_run,
        )
        raise NotImplementedError

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
        del (
            preview_hostname,
            expected_ip_address,
            dns_managed_zone,
            dns_project_id,
            gcp_deploy_key,
            ttl,
            dry_run,
        )
        raise NotImplementedError

    def check_managed_certificate_readiness(
        self,
        *,
        repo_name: str,
        site_id: str | None,
        preview_hostname: str,
        kubernetes_namespace: str,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        expected_managed_certificate_name: str | None = None,
    ) -> SEOMigrationGitHubManagedCertificateReadinessResult | None:
        del (
            repo_name,
            site_id,
            preview_hostname,
            kubernetes_namespace,
            managed_gke_config,
            gcp_deploy_key,
            expected_managed_certificate_name,
        )
        return None

    def ensure_managed_certificate(
        self,
        *,
        repo_name: str,
        site_id: str | None,
        preview_hostname: str,
        kubernetes_namespace: str,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        expected_managed_certificate_name: str | None = None,
    ) -> SEOMigrationGitHubManagedCertificateEnsureResult:
        del (
            repo_name,
            site_id,
            preview_hostname,
            kubernetes_namespace,
            managed_gke_config,
            gcp_deploy_key,
            expected_managed_certificate_name,
        )
        raise NotImplementedError

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
        del repo_owner, repo_name, ref, business_id, site_id, principal_id, expected_owner
        raise NotImplementedError

    def delete_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
    ) -> None:
        del repo_owner, repo_name
        raise NotImplementedError

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        raise NotImplementedError

    def refresh_deploy_run_status(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult:
        raise NotImplementedError

    def lookup_deploy_run_status_after_dispatch(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult | None:
        del target, dispatched_at
        return None

    def probe_live_runtime_https(
        self,
        *,
        probe_url: str,
    ) -> SEOMigrationGitHubLiveRuntimeProbeResult | None:
        del probe_url
        return None

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
        del (
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
        workflow_path = _workflow_repo_path(workflow_id)
        return SEOMigrationGitHubWorkflowProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            workflow_id=workflow_id,
            workflow_path=workflow_path,
            provisioned=False,
            commit_sha=None,
            deploy_workflow_mode="site_repo_template_v1",
            target_environment_key="gke_prod",
            target_environment_source="admin_config",
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
        workflow_path = _workflow_repo_path(target.workflow_id)
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
            workflow_dispatch_supported=True,
            workflow_trigger_types=("workflow_dispatch",),
            dispatch_service_availability=True,
            dispatch_service_reason_code="available",
            dispatch_identifier_type="workflow_id",
            remediation_mode=remediation_mode.strip() or "none",
            workflow_conformance_checked=True,
            workflow_conformance_status="conformant",
            workflow_conformance_reasons=(),
            workflow_conformance_evidence_summary="default_stub",
        )


class MisconfiguredSEOMigrationGitHubPublisher(SEOMigrationGitHubPublisher):
    def __init__(self, *, safe_message: str, reason_code: str = "publisher_not_configured") -> None:
        self.safe_message = safe_message
        self.reason_code = reason_code.strip() or "publisher_not_configured"

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
        del (
            repo_owner,
            repo_name,
            auto_create_enabled,
            create_if_missing,
            expected_owner,
            private_by_default,
        )
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
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
        del (
            repo_owner,
            repo_name,
            target_ref,
            auto_create_enabled,
            expected_owner,
            expected_business_id,
            expected_site_id,
        )
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        del target, files, commit_message, dry_run
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def upsert_actions_secret(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        secret_name: str,
        secret_value: str,
    ) -> SEOMigrationGitHubActionsSecretUpsertResult:
        del repo_owner, repo_name, secret_name, secret_value
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
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
        del repo_owner, repo_name, ref, business_id, site_id, principal_id, expected_owner
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def delete_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
    ) -> None:
        del repo_owner, repo_name
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        del target, dry_run, managed_gke_config, managed_image_pull_secret_config
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
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
        del (
            repo_owner,
            repo_name,
            ref,
            kubernetes_namespace,
            managed_gke_config,
            git_userid,
            git_email,
            git_token,
            gcp_deploy_key,
            dry_run,
        )
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
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
        del repo_owner, repo_name, site_id, managed_gke_config, gcp_deploy_key, dry_run
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
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
        del (
            preview_hostname,
            expected_ip_address,
            dns_managed_zone,
            dns_project_id,
            gcp_deploy_key,
            ttl,
            dry_run,
        )
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def refresh_deploy_run_status(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult:
        del target, workflow_run_id, dispatched_at
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def lookup_deploy_run_status_after_dispatch(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult | None:
        del target, dispatched_at
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )

    def probe_live_runtime_https(
        self,
        *,
        probe_url: str,
    ) -> SEOMigrationGitHubLiveRuntimeProbeResult | None:
        del probe_url
        return None

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
            target,
            allow_ref_repair,
            allow_workflow_repair,
            dry_run,
            remediation_mode,
            managed_gke_config,
            namespace_isolation_defaults,
            managed_image_pull_secret_config,
        )
        raise SEOMigrationGitHubPublisherError(
            code=self.reason_code,
            safe_message=self.safe_message,
        )


class GitHubSEOMigrationPublisher(SEOMigrationGitHubPublisher):
    def __init__(
        self,
        *,
        token: str,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: int = 15,
        committer_name: str = "MBSRN Migration Bot",
        committer_email: str = "migration-bot@mbsrn.local",
        managed_deploy_service_account_email: str | None = None,
    ) -> None:
        normalized_token = token.strip()
        if not normalized_token:
            raise ValueError("GitHub token is required.")
        self.token = normalized_token
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.committer_name = committer_name.strip() or "MBSRN Migration Bot"
        self.committer_email = committer_email.strip() or "migration-bot@mbsrn.local"
        self.managed_deploy_service_account_email = (
            _coerce_string(managed_deploy_service_account_email) or ""
        ).strip() or None
        self.runtime_build_metadata = get_runtime_build_metadata()

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
        normalized_owner = self._normalize_repo_owner_or_raise(repo_owner)
        normalized_repo = self._normalize_repo_name_or_raise(repo_name)
        normalized_expected_owner = self._normalize_expected_owner(expected_owner)
        auto_create_enabled_value = bool(auto_create_enabled)
        create_if_missing_value = bool(create_if_missing)
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_repo_ensure_started",
                "repo_owner": normalized_owner,
                "repo_name": normalized_repo,
                "auto_create_enabled": auto_create_enabled_value,
                "create_if_missing": create_if_missing_value,
                "expected_owner": normalized_expected_owner,
                "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
            },
            fallback_message="seo_migration_repo_ensure_started",
            level=logging.INFO,
        )
        try:
            repo_payload = self._ensure_repo_exists(repo_owner=normalized_owner, repo_name=normalized_repo)
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_repo_ensure_result",
                    "repo_owner": normalized_owner,
                    "repo_name": normalized_repo,
                    "auto_create_enabled": auto_create_enabled_value,
                    "create_if_missing": create_if_missing_value,
                    "auto_create_attempted": False,
                    "auto_create_created": False,
                    "outcome": "repo_exists",
                    "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                    "repo_visibility_observed": _normalize_repo_visibility(repo_payload),
                },
                fallback_message="seo_migration_repo_ensure_result",
                level=logging.INFO,
            )
            return SEOMigrationGitHubRepositoryEnsureResult(
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                exists=True,
                auto_create_enabled=auto_create_enabled_value,
                auto_create_attempted=False,
                auto_create_created=False,
                outcome="repo_exists",
                skipped_reason=None,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code != "repo_not_found":
                raise

        if not create_if_missing_value:
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_repo_ensure_result",
                    "repo_owner": normalized_owner,
                    "repo_name": normalized_repo,
                    "auto_create_enabled": auto_create_enabled_value,
                    "create_if_missing": False,
                    "auto_create_attempted": False,
                    "auto_create_created": False,
                    "outcome": "repo_missing",
                    "skipped_reason": "check_only",
                    "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                },
                fallback_message="seo_migration_repo_ensure_result",
                level=logging.INFO,
            )
            return SEOMigrationGitHubRepositoryEnsureResult(
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                exists=False,
                auto_create_enabled=auto_create_enabled_value,
                auto_create_attempted=False,
                auto_create_created=False,
                outcome="repo_missing",
                skipped_reason="check_only",
            )

        if not auto_create_enabled_value:
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_repo_auto_create_skipped",
                    "repo_owner": normalized_owner,
                    "repo_name": normalized_repo,
                    "auto_create_enabled": False,
                    "skipped_reason": "policy_disabled",
                    "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                },
                fallback_message="seo_migration_repo_auto_create_skipped",
                level=logging.WARNING,
            )
            raise SEOMigrationGitHubPublisherError(
                code="repo_auto_create_disabled",
                safe_message=(
                    "GitHub repository target was not found and repository auto-create is disabled in admin settings."
                ),
                stage="repo_create",
            )

        if normalized_expected_owner and normalized_owner.lower() != normalized_expected_owner.lower():
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_repo_auto_create_skipped",
                    "repo_owner": normalized_owner,
                    "repo_name": normalized_repo,
                    "auto_create_enabled": True,
                    "skipped_reason": "owner_mismatch",
                    "expected_owner": normalized_expected_owner,
                    "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                },
                fallback_message="seo_migration_repo_auto_create_skipped",
                level=logging.WARNING,
            )
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_owner_mismatch",
                safe_message="GitHub repository owner is outside the configured admin-owned publish target.",
                stage="repo_create",
            )

        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_repo_auto_create_attempted",
                "repo_owner": normalized_owner,
                "repo_name": normalized_repo,
                "auto_create_enabled": auto_create_enabled_value,
                "expected_owner": normalized_expected_owner,
                "private_by_default": bool(private_by_default),
                "repo_auto_create_auto_init_requested": True,
                "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
            },
            fallback_message="seo_migration_repo_auto_create_attempted",
            level=logging.INFO,
        )
        try:
            create_mode = self._create_repository(
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                private_by_default=private_by_default,
                expected_owner=normalized_expected_owner,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code == "repo_create_failed_conflict":
                try:
                    repo_payload = self._ensure_repo_exists(
                        repo_owner=normalized_owner,
                        repo_name=normalized_repo,
                    )
                except SEOMigrationGitHubPublisherError:
                    pass
                else:
                    _emit_structured_publisher_log(
                        payload={
                            "event": "seo_migration_repo_auto_create_succeeded",
                            "repo_owner": normalized_owner,
                            "repo_name": normalized_repo,
                            "auto_create_enabled": auto_create_enabled_value,
                            "create_mode": "race_conflict_repo_exists",
                            "outcome": "repo_exists",
                            "race_conflict_resolved": True,
                            "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                            "repo_visibility_observed": _normalize_repo_visibility(repo_payload),
                        },
                        fallback_message="seo_migration_repo_auto_create_succeeded",
                        level=logging.INFO,
                    )
                    return SEOMigrationGitHubRepositoryEnsureResult(
                        repo_owner=normalized_owner,
                        repo_name=normalized_repo,
                        exists=True,
                        auto_create_enabled=auto_create_enabled_value,
                        auto_create_attempted=True,
                        auto_create_created=False,
                        outcome="repo_exists",
                        skipped_reason="created_during_race",
                    )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_repo_auto_create_failed",
                    "repo_owner": normalized_owner,
                    "repo_name": normalized_repo,
                    "auto_create_enabled": auto_create_enabled_value,
                    "failure_reason_code": exc.code,
                    "failure_stage": exc.stage,
                },
                fallback_message="seo_migration_repo_auto_create_failed",
                level=logging.WARNING,
            )
            raise
        repo_payload = self._ensure_repo_exists(repo_owner=normalized_owner, repo_name=normalized_repo)
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_repo_auto_create_succeeded",
                "repo_owner": normalized_owner,
                "repo_name": normalized_repo,
                "auto_create_enabled": auto_create_enabled_value,
                "create_mode": create_mode,
                "outcome": "repo_created",
                "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                "repo_visibility_observed": _normalize_repo_visibility(repo_payload),
            },
            fallback_message="seo_migration_repo_auto_create_succeeded",
            level=logging.INFO,
        )
        self._verify_repository_auto_init_branch(
            repo_owner=normalized_owner,
            repo_name=normalized_repo,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_repo_auto_create_auto_init_verified",
                "repo_owner": normalized_owner,
                "repo_name": normalized_repo,
                "repo_auto_create_auto_init_verified": True,
                "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                "repo_visibility_observed": _normalize_repo_visibility(repo_payload),
            },
            fallback_message="seo_migration_repo_auto_create_auto_init_verified",
            level=logging.INFO,
        )
        return SEOMigrationGitHubRepositoryEnsureResult(
            repo_owner=normalized_owner,
            repo_name=normalized_repo,
            exists=True,
            auto_create_enabled=auto_create_enabled_value,
            auto_create_attempted=True,
            auto_create_created=True,
            outcome="repo_created",
            skipped_reason=None,
        )

    def _verify_repository_auto_init_branch(
        self,
        *,
        repo_owner: str,
        repo_name: str,
    ) -> None:
        try:
            default_branch = self._resolve_default_branch(repo_owner=repo_owner, repo_name=repo_name)
            self._resolve_branch_head_sha(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=default_branch,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if _should_treat_ref_check_as_uninitialized(exc):
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION,
                    safe_message=(
                        "GitHub repository exists but is empty. Create an initial commit or README before publish."
                    ),
                    status_code=exc.status_code,
                    stage="repo_create",
                    provider_message=_sanitize_github_error_message(exc.provider_message),
                ) from exc
            raise

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
        normalized_owner = self._normalize_repo_owner_or_raise(repo_owner)
        normalized_repo = self._normalize_repo_name_or_raise(repo_name)
        normalized_ref = (_coerce_string(target_ref) or "").strip() or "main"
        normalized_expected_owner = self._normalize_expected_owner(expected_owner)
        normalized_expected_business_id = _normalize_repo_management_id(expected_business_id)
        normalized_expected_site_id = _normalize_repo_management_id(expected_site_id)
        auto_create_enabled_value = bool(auto_create_enabled)

        repo_exists = False
        repo_ensure_outcome = "unknown"
        target_ref_exists = False
        repo_initialized = False
        can_read_contents = False
        can_write_contents = False
        can_write_workflows = False
        would_auto_create_repo = False
        would_bootstrap_branch = False
        would_reconcile_repo_baseline = False
        preflight_status = "blocked"
        preflight_blocker_code: str | None = None
        repo_visibility_target = _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY
        repo_visibility_observed: str | None = None
        repo_baseline_required: bool | None = None
        readme_present: bool | None = None
        gitignore_present: bool | None = None
        license_present: bool | None = None
        repo_management_status: str | None = None
        repo_management_marker_present: bool | None = None
        repo_management_marker_valid: bool | None = None
        repo_management_marker_matches_site: bool | None = None
        repo_management_marker_business_id: str | None = None
        repo_management_marker_site_id: str | None = None
        repo_management_marker_source_ref: str | None = None
        permissions_push_value: bool | None = None
        workflows_api_accessible: bool | None = None

        try:
            ensure_result = self.ensure_repository(
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                auto_create_enabled=auto_create_enabled_value,
                create_if_missing=False,
                expected_owner=normalized_expected_owner,
            )
        except SEOMigrationGitHubPublisherError as exc:
            preflight_blocker_code = (_coerce_string(exc.code) or "").strip().lower() or None
            if preflight_blocker_code == "repo_auto_create_disabled":
                repo_ensure_outcome = "skipped_policy_disabled"
            elif preflight_blocker_code == "repo_create_failed_invalid_name":
                repo_ensure_outcome = "failed_invalid_name"
            elif preflight_blocker_code == "repo_create_failed_owner_mismatch":
                repo_ensure_outcome = "failed_owner_mismatch"
            elif preflight_blocker_code == "repo_auto_create_not_authorized":
                repo_ensure_outcome = "failed_not_authorized"
            else:
                repo_ensure_outcome = "failed_unknown"
        else:
            repo_exists = bool(ensure_result.exists)
            if repo_exists:
                repo_ensure_outcome = "exists"
            elif auto_create_enabled_value:
                repo_ensure_outcome = "would_create_on_publish"
            else:
                repo_ensure_outcome = "skipped_policy_disabled"
            would_auto_create_repo = bool((not repo_exists) and auto_create_enabled_value)
            if (
                would_auto_create_repo
                and normalized_expected_owner
                and normalized_owner.lower() != normalized_expected_owner.lower()
            ):
                would_auto_create_repo = False
                preflight_blocker_code = "repo_create_failed_owner_mismatch"
                repo_ensure_outcome = "failed_owner_mismatch"

            if not repo_exists and preflight_blocker_code is None and not would_auto_create_repo:
                preflight_blocker_code = "repo_auto_create_disabled"

            if repo_exists:
                try:
                    repo_payload = self._request_json(
                        method="GET",
                        path=f"/repos/{urllib.parse.quote(normalized_owner)}/{urllib.parse.quote(normalized_repo)}",
                        expected_statuses=(200,),
                        status_error_map={
                            401: (
                                "token_not_authorized",
                                "GitHub token is not authorized for publish operations.",
                            ),
                            403: (
                                "token_not_authorized",
                                "GitHub token is not authorized for publish operations.",
                            ),
                            404: (
                                "repo_not_found",
                                "GitHub repository target was not found.",
                            ),
                        },
                        error_stage="publish_preflight",
                    )
                except SEOMigrationGitHubPublisherError as exc:
                    if preflight_blocker_code is None:
                        preflight_blocker_code = (_coerce_string(exc.code) or "").strip().lower() or None
                    repo_payload = None
                can_read_contents = isinstance(repo_payload, dict)
                repo_visibility_observed = _normalize_repo_visibility(repo_payload)
                permissions_payload = repo_payload.get("permissions") if isinstance(repo_payload, dict) else None
                can_write_contents, permissions_push_value = self._infer_contents_write_capability(
                    permissions_payload=permissions_payload,
                )
                if not can_write_contents and preflight_blocker_code is None:
                    preflight_blocker_code = _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED

                try:
                    self._request_json(
                        method="GET",
                        path=(
                            f"/repos/{urllib.parse.quote(normalized_owner)}/{urllib.parse.quote(normalized_repo)}"
                            "/actions/workflows?per_page=1"
                        ),
                        expected_statuses=(200,),
                        allow_404=True,
                        status_error_map={
                            401: (
                                _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED,
                                "GitHub token is not authorized to access workflow operations for publish.",
                            ),
                            403: (
                                _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED,
                                "GitHub token is not authorized to access workflow operations for publish.",
                            ),
                        },
                        error_stage="publish_preflight",
                        expect_object=False,
                    )
                    workflows_api_accessible = True
                except SEOMigrationGitHubPublisherError as exc:
                    workflows_api_accessible = False
                    if preflight_blocker_code is None:
                        preflight_blocker_code = (_coerce_string(exc.code) or "").strip().lower() or None
                can_write_workflows = bool(can_write_contents and workflows_api_accessible)
                if (not can_write_workflows) and preflight_blocker_code is None:
                    preflight_blocker_code = _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED

                try:
                    branch_payload = self._request_json(
                        method="GET",
                        path=(
                            f"/repos/{urllib.parse.quote(normalized_owner)}/{urllib.parse.quote(normalized_repo)}"
                            f"/branches/{urllib.parse.quote(normalized_ref, safe='')}"
                        ),
                        expected_statuses=(200,),
                        allow_404=True,
                        status_error_map={
                            401: (
                                "token_not_authorized",
                                "GitHub token is not authorized for publish operations.",
                            ),
                            403: (
                                "token_not_authorized",
                                "GitHub token is not authorized for publish operations.",
                            ),
                        },
                        error_stage="publish_preflight",
                    )
                except SEOMigrationGitHubPublisherError as exc:
                    branch_payload = None
                    if preflight_blocker_code is None:
                        preflight_blocker_code = (_coerce_string(exc.code) or "").strip().lower() or None
                target_ref_exists = isinstance(branch_payload, dict)
                if target_ref_exists:
                    repo_initialized = True
                else:
                    default_branch = (
                        _coerce_string((repo_payload or {}).get("default_branch")) or ""
                    ).strip() or "main"
                    try:
                        _ = self._resolve_branch_head_sha(
                            repo_owner=normalized_owner,
                            repo_name=normalized_repo,
                            branch=default_branch,
                        )
                        repo_initialized = True
                    except SEOMigrationGitHubPublisherError as exc:
                        if exc.code == _GITHUB_REASON_BRANCH_UNINITIALIZED:
                            repo_initialized = False
                        elif preflight_blocker_code is None:
                            preflight_blocker_code = (_coerce_string(exc.code) or "").strip().lower() or None
                    would_bootstrap_branch = bool((not target_ref_exists) and can_write_contents)
                    if not repo_initialized and repo_exists:
                        would_bootstrap_branch = False
                        if preflight_blocker_code is None:
                            preflight_blocker_code = _GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION
                    elif (not would_bootstrap_branch) and preflight_blocker_code is None:
                        preflight_blocker_code = _GITHUB_REASON_BRANCH_UNINITIALIZED

                management_state = self._evaluate_repo_management_state(
                    repo_owner=normalized_owner,
                    repo_name=normalized_repo,
                    target_ref=normalized_ref,
                    expected_business_id=normalized_expected_business_id,
                    expected_site_id=normalized_expected_site_id,
                    repo_initialized=repo_initialized,
                    default_branch=(_coerce_string((repo_payload or {}).get("default_branch")) or "").strip() or "main",
                    error_stage="publish_preflight",
                )
                repo_management_status = management_state.status
                repo_management_marker_present = management_state.marker_present
                repo_management_marker_valid = management_state.marker_valid
                repo_management_marker_matches_site = management_state.marker_matches_site
                repo_management_marker_business_id = management_state.marker_business_id
                repo_management_marker_site_id = management_state.marker_site_id
                repo_management_marker_source_ref = management_state.source_ref
                if management_state.blocker_code and preflight_blocker_code is None:
                    preflight_blocker_code = management_state.blocker_code
                if (
                    management_state.blocker_code is None
                    and normalized_expected_business_id
                    and normalized_expected_site_id
                ):
                    baseline_ref = (_coerce_string(management_state.source_ref) or "").strip() or normalized_ref
                    try:
                        baseline_presence = self._evaluate_repo_baseline_presence(
                            repo_owner=normalized_owner,
                            repo_name=normalized_repo,
                            ref=baseline_ref,
                            repo_initialized=repo_initialized,
                            error_stage="publish_preflight",
                        )
                    except SEOMigrationGitHubPublisherError as exc:
                        if preflight_blocker_code is None:
                            preflight_blocker_code = (_coerce_string(exc.code) or "").strip().lower() or None
                    else:
                        repo_baseline_required = bool(baseline_presence.get("repo_baseline_required"))
                        readme_present = (
                            bool(baseline_presence.get("readme_present"))
                            if baseline_presence.get("readme_present") is not None
                            else None
                        )
                        gitignore_present = (
                            bool(baseline_presence.get("gitignore_present"))
                            if baseline_presence.get("gitignore_present") is not None
                            else None
                        )
                        license_present = (
                            bool(baseline_presence.get("license_present"))
                            if baseline_presence.get("license_present") is not None
                            else None
                        )
                        would_reconcile_repo_baseline = bool(
                            repo_baseline_required and repo_initialized and can_write_contents
                        )

        if preflight_blocker_code:
            preflight_status = "blocked"
        elif would_auto_create_repo or would_bootstrap_branch or would_reconcile_repo_baseline:
            preflight_status = "ready_with_actions"
        else:
            preflight_status = "ready"

        result = SEOMigrationGitHubPublishPreflightResult(
            repo_owner=normalized_owner,
            repo_name=normalized_repo,
            target_ref=normalized_ref,
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
            repo_visibility_target=repo_visibility_target,
            repo_visibility_observed=repo_visibility_observed,
            repo_baseline_required=repo_baseline_required,
            repo_baseline_reconciliation_needed=would_reconcile_repo_baseline,
            readme_present=readme_present,
            gitignore_present=gitignore_present,
            license_present=license_present,
            repo_management_status=repo_management_status,
            repo_management_marker_present=repo_management_marker_present,
            repo_management_marker_valid=repo_management_marker_valid,
            repo_management_marker_matches_site=repo_management_marker_matches_site,
            repo_management_marker_business_id=repo_management_marker_business_id,
            repo_management_marker_site_id=repo_management_marker_site_id,
            repo_management_marker_source_ref=repo_management_marker_source_ref,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_publish_preflight",
                "repo_owner": result.repo_owner,
                "repo_name": result.repo_name,
                "target_ref": result.target_ref,
                "repo_exists": result.repo_exists,
                "repo_ensure_outcome": result.repo_ensure_outcome,
                "target_ref_exists": result.target_ref_exists,
                "repo_initialized": result.repo_initialized,
                "can_read_contents": result.can_read_contents,
                "can_write_contents": result.can_write_contents,
                "can_write_workflows": result.can_write_workflows,
                "would_auto_create_repo": result.would_auto_create_repo,
                "would_bootstrap_branch": result.would_bootstrap_branch,
                "would_reconcile_repo_baseline": result.repo_baseline_reconciliation_needed,
                "preflight_status": result.preflight_status,
                "preflight_blocker_code": result.preflight_blocker_code,
                "repo_visibility_target": result.repo_visibility_target,
                "repo_visibility_observed": result.repo_visibility_observed,
                "repo_baseline_required": result.repo_baseline_required,
                "readme_present": result.readme_present,
                "gitignore_present": result.gitignore_present,
                "license_present": result.license_present,
                "repo_management_status": result.repo_management_status,
                "repo_management_marker_present": result.repo_management_marker_present,
                "repo_management_marker_valid": result.repo_management_marker_valid,
                "repo_management_marker_matches_site": result.repo_management_marker_matches_site,
                "repo_management_marker_source_ref": result.repo_management_marker_source_ref,
                "permissions_push_value": permissions_push_value,
                "workflows_api_accessible": workflows_api_accessible,
            },
            fallback_message="seo_migration_publish_preflight",
            level=(logging.INFO if preflight_status != "blocked" else logging.WARNING),
        )
        return result

    @staticmethod
    def _infer_contents_write_capability(*, permissions_payload: object) -> tuple[bool, bool | None]:
        if not isinstance(permissions_payload, dict):
            return True, None
        push_value = permissions_payload.get("push")
        maintain_value = permissions_payload.get("maintain")
        admin_value = permissions_payload.get("admin")
        can_write = bool(push_value or maintain_value or admin_value)
        return can_write, bool(push_value)

    @staticmethod
    def _normalize_repo_owner_or_raise(value: object) -> str:
        normalized = (_coerce_string(value) or "").strip()
        if not normalized or not _VALID_REPO_OWNER_PATTERN.fullmatch(normalized):
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_owner_mismatch",
                safe_message="GitHub repository owner is outside the configured admin-owned publish target.",
                stage="repo_create",
            )
        return normalized

    @staticmethod
    def _normalize_repo_name_or_raise(value: object) -> str:
        normalized = (_coerce_string(value) or "").strip()
        if not normalized or not _VALID_REPO_NAME_PATTERN.fullmatch(normalized):
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_invalid_name",
                safe_message="GitHub repository name is invalid for auto-create.",
                stage="repo_create",
            )
        return normalized

    @staticmethod
    def _normalize_expected_owner(value: object) -> str | None:
        normalized = (_coerce_string(value) or "").strip()
        if not normalized:
            return None
        if not _VALID_REPO_OWNER_PATTERN.fullmatch(normalized):
            return None
        return normalized

    def _create_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        private_by_default: bool,
        expected_owner: str | None,
    ) -> str:
        payload = {
            "name": repo_name,
            "private": bool(private_by_default),
            "auto_init": True,
            "default_branch": "main",
        }
        org_path = f"/orgs/{urllib.parse.quote(repo_owner, safe='')}/repos"
        try:
            self._request_json(
                method="POST",
                path=org_path,
                payload=payload,
                expected_statuses=(201,),
                status_error_map={
                    401: (
                        "repo_auto_create_not_authorized",
                        "GitHub token is not authorized to create repositories for the configured owner.",
                    ),
                    403: (
                        "repo_auto_create_not_authorized",
                        "GitHub token is not authorized to create repositories for the configured owner.",
                    ),
                    409: (
                        "repo_create_failed_conflict",
                        "GitHub repository creation conflict occurred for the configured target.",
                    ),
                },
                error_stage="repo_create",
            )
            return "org_repository_created"
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code in {"repo_auto_create_not_authorized", "repo_create_failed_conflict"}:
                raise
            if exc.code in {"github_timeout", "github_network_error", "github_temporal_failure"}:
                raise SEOMigrationGitHubPublisherError(
                    code="repo_create_failed_runtime_unavailable",
                    safe_message="GitHub repository auto-create failed temporarily.",
                    stage="repo_create",
                ) from exc
            if exc.code == "github_request_failed":
                raise self._classify_repo_create_request_failed(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    exc=exc,
                ) from exc
            if exc.code != "github_target_not_found":
                raise

        user_login = self._resolve_authenticated_user_login()
        if not user_login:
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_runtime_unavailable",
                safe_message="GitHub repository auto-create could not verify authenticated owner.",
                stage="repo_create",
            )
        if user_login.lower() != repo_owner.lower():
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_owner_mismatch",
                safe_message="GitHub repository owner is outside the configured admin-owned publish target.",
                stage="repo_create",
            )
        if expected_owner and user_login.lower() != expected_owner.lower():
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_owner_mismatch",
                safe_message="GitHub repository owner is outside the configured admin-owned publish target.",
                stage="repo_create",
            )

        user_path = "/user/repos"
        try:
            self._request_json(
                method="POST",
                path=user_path,
                payload=payload,
                expected_statuses=(201,),
                status_error_map={
                    401: (
                        "repo_auto_create_not_authorized",
                        "GitHub token is not authorized to create repositories for the configured owner.",
                    ),
                    403: (
                        "repo_auto_create_not_authorized",
                        "GitHub token is not authorized to create repositories for the configured owner.",
                    ),
                    409: (
                        "repo_create_failed_conflict",
                        "GitHub repository creation conflict occurred for the configured target.",
                    ),
                },
                error_stage="repo_create",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code in {"repo_auto_create_not_authorized", "repo_create_failed_conflict"}:
                raise
            if exc.code in {"github_timeout", "github_network_error", "github_temporal_failure"}:
                raise SEOMigrationGitHubPublisherError(
                    code="repo_create_failed_runtime_unavailable",
                    safe_message="GitHub repository auto-create failed temporarily.",
                    stage="repo_create",
                ) from exc
            if exc.code == "github_request_failed":
                raise self._classify_repo_create_request_failed(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    exc=exc,
                ) from exc
            raise
        return "user_repository_created"

    def _classify_repo_create_request_failed(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        exc: SEOMigrationGitHubPublisherError,
    ) -> SEOMigrationGitHubPublisherError:
        repo_exists = self._repo_exists_probe(repo_owner=repo_owner, repo_name=repo_name)
        if repo_exists:
            return SEOMigrationGitHubPublisherError(
                code="repo_create_failed_conflict",
                safe_message="GitHub repository creation conflict occurred for the configured target.",
                stage="repo_create",
                status_code=exc.status_code,
            )
        return SEOMigrationGitHubPublisherError(
            code="repo_create_failed_invalid_name",
            safe_message="GitHub repository name is invalid for auto-create.",
            stage="repo_create",
            status_code=exc.status_code,
        )

    def _repo_exists_probe(self, *, repo_owner: str, repo_name: str) -> bool:
        payload = self._request_json(
            method="GET",
            path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}",
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    "repo_auto_create_not_authorized",
                    "GitHub token is not authorized to create repositories for the configured owner.",
                ),
                403: (
                    "repo_auto_create_not_authorized",
                    "GitHub token is not authorized to create repositories for the configured owner.",
                ),
            },
            error_stage="repo_create",
        )
        return isinstance(payload, dict)

    def _resolve_authenticated_user_login(self) -> str | None:
        payload = self._request_json(
            method="GET",
            path="/user",
            expected_statuses=(200,),
            status_error_map={
                401: (
                    "repo_auto_create_not_authorized",
                    "GitHub token is not authorized to create repositories for the configured owner.",
                ),
                403: (
                    "repo_auto_create_not_authorized",
                    "GitHub token is not authorized to create repositories for the configured owner.",
                ),
            },
            error_stage="repo_create",
        )
        if not isinstance(payload, dict):
            return None
        return _coerce_string(payload.get("login"))

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
        normalized_owner = self._normalize_repo_owner_or_raise(repo_owner)
        normalized_repo = self._normalize_repo_name_or_raise(repo_name)
        normalized_ref = (_coerce_string(ref) or "").strip() or "main"
        normalized_expected_owner = self._normalize_expected_owner(expected_owner)
        normalized_business_id = _normalize_repo_management_id(business_id)
        normalized_site_id = _normalize_repo_management_id(site_id)
        if not normalized_business_id or not normalized_site_id:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                safe_message="Repository adoption requires valid business/site identifiers.",
                stage="repo_adoption",
            )
        if normalized_expected_owner and normalized_owner.lower() != normalized_expected_owner.lower():
            raise SEOMigrationGitHubPublisherError(
                code="repo_create_failed_owner_mismatch",
                safe_message="GitHub repository owner is outside the configured admin-owned publish target.",
                stage="repo_adoption",
            )

        adoption_started_payload: dict[str, object] = {
            "repo_owner": normalized_owner,
            "repo_name": normalized_repo,
            "ref": normalized_ref,
            "business_id": normalized_business_id,
            "site_id": normalized_site_id,
            "principal_id": _coerce_string(principal_id),
            "marker_written": False,
            "failure_reason_code": None,
        }
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_github_repo_adoption",
                "status": "started",
                **adoption_started_payload,
            },
            fallback_message="seo_migration_github_repo_adoption",
            level=logging.INFO,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "repo_adoption_started",
                **adoption_started_payload,
            },
            fallback_message="repo_adoption_started",
            level=logging.INFO,
        )

        def _emit_adoption_failure(*, code: str, message: str | None = None, stage: str | None = None) -> None:
            payload = {
                "repo_owner": normalized_owner,
                "repo_name": normalized_repo,
                "ref": normalized_ref,
                "business_id": normalized_business_id,
                "site_id": normalized_site_id,
                "principal_id": _coerce_string(principal_id),
                "marker_written": False,
                "failure_reason_code": code,
                "failure_stage": stage,
                "failure_message": _sanitize_github_error_message(message),
            }
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_github_repo_adoption",
                    "status": "failed",
                    **payload,
                },
                fallback_message="seo_migration_github_repo_adoption",
                level=logging.WARNING,
            )
            _emit_structured_publisher_log(
                payload={
                    "event": "repo_adoption_failed",
                    **payload,
                },
                fallback_message="repo_adoption_failed",
                level=logging.WARNING,
            )

        try:
            self._ensure_repo_exists(repo_owner=normalized_owner, repo_name=normalized_repo)
            default_branch = self._resolve_default_branch(repo_owner=normalized_owner, repo_name=normalized_repo)
            repo_initialized = self._is_repository_initialized(
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                default_branch=default_branch,
            )
            if not repo_initialized:
                _emit_adoption_failure(code=_GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION)
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION,
                    safe_message=(
                        "GitHub repository exists but is empty and must be manually initialized before adoption."
                    ),
                    stage="repo_adoption",
                )
            management_state = self._evaluate_repo_management_state(
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                target_ref=normalized_ref,
                expected_business_id=normalized_business_id,
                expected_site_id=normalized_site_id,
                repo_initialized=True,
                default_branch=default_branch,
                error_stage="repo_adoption",
            )
            if management_state.status == "managed_marker_match":
                _emit_structured_publisher_log(
                    payload={
                        "event": "seo_migration_github_repo_adoption",
                        "status": "completed",
                        "repo_owner": normalized_owner,
                        "repo_name": normalized_repo,
                        "ref": normalized_ref,
                        "business_id": normalized_business_id,
                        "site_id": normalized_site_id,
                        "principal_id": _coerce_string(principal_id),
                        "marker_written": False,
                        "adoption_outcome": "already_managed",
                        "reason_code": _GITHUB_REASON_REPO_MANAGEMENT_MARKER_PRESENT,
                    },
                    fallback_message="seo_migration_github_repo_adoption",
                    level=logging.INFO,
                )
                _emit_structured_publisher_log(
                    payload={
                        "event": "repo_adoption_completed",
                        "repo_owner": normalized_owner,
                        "repo_name": normalized_repo,
                        "ref": normalized_ref,
                        "business_id": normalized_business_id,
                        "site_id": normalized_site_id,
                        "principal_id": _coerce_string(principal_id),
                        "marker_written": False,
                        "adoption_outcome": "already_managed",
                        "reason_code": _GITHUB_REASON_REPO_MANAGEMENT_MARKER_PRESENT,
                    },
                    fallback_message="repo_adoption_completed",
                    level=logging.INFO,
                )
                return SEOMigrationGitHubRepoAdoptionResult(
                    repo_owner=normalized_owner,
                    repo_name=normalized_repo,
                    ref=normalized_ref,
                    marker_written=False,
                    adoption_outcome="already_managed",
                    management_status=management_state.status,
                    marker_business_id=management_state.marker_business_id,
                    marker_site_id=management_state.marker_site_id,
                )
            if management_state.blocker_code in {
                _GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISMATCH,
                _GITHUB_REASON_REPO_MANAGEMENT_MARKER_INVALID,
            }:
                _emit_adoption_failure(
                    code=str(management_state.blocker_code),
                    message=management_state.blocker_message,
                    stage="repo_adoption",
                )
                raise SEOMigrationGitHubPublisherError(
                    code=str(management_state.blocker_code),
                    safe_message=(
                        _coerce_string(management_state.blocker_message)
                        or "Repository management marker is not compatible with this migration target."
                    ),
                    stage="repo_adoption",
                )
            if not management_state.marker_present:
                marker_content = _render_repo_management_marker_content(
                    business_id=normalized_business_id,
                    site_id=normalized_site_id,
                    adopted_at=utc_now().isoformat(),
                    adopted_by=principal_id,
                )
                self._upsert_repo_file_if_missing(
                    repo_owner=normalized_owner,
                    repo_name=normalized_repo,
                    branch=normalized_ref,
                    path=_MBSRN_REPO_MANAGEMENT_MARKER_PATH,
                    content=marker_content,
                    commit_message="chore(migration): adopt repository into MBSRN management",
                    dry_run=False,
                )
                post_state = self._evaluate_repo_management_state(
                    repo_owner=normalized_owner,
                    repo_name=normalized_repo,
                    target_ref=normalized_ref,
                    expected_business_id=normalized_business_id,
                    expected_site_id=normalized_site_id,
                    repo_initialized=True,
                    default_branch=default_branch,
                    error_stage="repo_adoption",
                )
                if not post_state.marker_present or not post_state.marker_valid or not post_state.marker_matches_site:
                    _emit_adoption_failure(
                        code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                        message="Repository marker write did not produce a valid managed marker.",
                        stage="repo_adoption",
                    )
                    raise SEOMigrationGitHubPublisherError(
                        code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                        safe_message="GitHub repository adoption failed to verify management marker.",
                        stage="repo_adoption",
                    )
                _emit_structured_publisher_log(
                    payload={
                        "event": "seo_migration_github_repo_adoption",
                        "status": "completed",
                        "repo_owner": normalized_owner,
                        "repo_name": normalized_repo,
                        "ref": normalized_ref,
                        "business_id": normalized_business_id,
                        "site_id": normalized_site_id,
                        "principal_id": _coerce_string(principal_id),
                        "marker_written": True,
                        "adoption_outcome": "marker_written",
                        "reason_code": _GITHUB_REASON_REPO_MANAGEMENT_MARKER_WRITTEN,
                    },
                    fallback_message="seo_migration_github_repo_adoption",
                    level=logging.INFO,
                )
                _emit_structured_publisher_log(
                    payload={
                        "event": "repo_adoption_completed",
                        "repo_owner": normalized_owner,
                        "repo_name": normalized_repo,
                        "ref": normalized_ref,
                        "business_id": normalized_business_id,
                        "site_id": normalized_site_id,
                        "principal_id": _coerce_string(principal_id),
                        "marker_written": True,
                        "adoption_outcome": "marker_written",
                        "reason_code": _GITHUB_REASON_REPO_MANAGEMENT_MARKER_WRITTEN,
                    },
                    fallback_message="repo_adoption_completed",
                    level=logging.INFO,
                )
                return SEOMigrationGitHubRepoAdoptionResult(
                    repo_owner=normalized_owner,
                    repo_name=normalized_repo,
                    ref=normalized_ref,
                    marker_written=True,
                    adoption_outcome="marker_written",
                    management_status=post_state.status,
                    marker_business_id=post_state.marker_business_id,
                    marker_site_id=post_state.marker_site_id,
                )
            _emit_adoption_failure(
                code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                message="Repository adoption decision path was inconclusive.",
                stage="repo_adoption",
            )
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                safe_message="GitHub repository adoption could not be completed.",
                stage="repo_adoption",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code not in {
                _GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISMATCH,
                _GITHUB_REASON_REPO_MANAGEMENT_MARKER_INVALID,
                _GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION,
                _GITHUB_REASON_REPO_ADOPTION_FAILED,
            }:
                _emit_adoption_failure(
                    code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                    message=exc.provider_message or exc.safe_message,
                    stage=exc.stage or "repo_adoption",
                )
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_REPO_ADOPTION_FAILED,
                    safe_message="GitHub repository adoption failed.",
                    status_code=exc.status_code,
                    stage=exc.stage or "repo_adoption",
                    provider_message=_sanitize_github_error_message(exc.provider_message),
                ) from exc
            raise

    def delete_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
    ) -> None:
        normalized_owner = self._normalize_repo_owner_or_raise(repo_owner)
        normalized_repo = self._normalize_repo_name_or_raise(repo_name)
        self._request_json(
            method="DELETE",
            path=f"/repos/{urllib.parse.quote(normalized_owner)}/{urllib.parse.quote(normalized_repo)}",
            expected_statuses=(204,),
            status_error_map={
                401: ("github_repo_delete_failed", "GitHub repository deletion is not authorized."),
                403: ("github_repo_delete_failed", "GitHub repository deletion is not authorized."),
                404: ("github_target_not_found", "GitHub repository target was not found."),
            },
            error_stage="repo_delete",
            expect_object=False,
        )

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        def _payload_bytes(file_item: SEOMigrationGitHubPublishFile) -> bytes:
            if isinstance(file_item.content_bytes, (bytes, bytearray)):
                return bytes(file_item.content_bytes)
            if isinstance(file_item.content, str):
                return file_item.content.encode("utf-8")
            return b""

        published_at = utc_now().isoformat()
        committed_paths: list[str] = []
        if dry_run:
            total_bytes = sum(len(_payload_bytes(item)) for item in files)
            return SEOMigrationGitHubPublishResult(
                dry_run=True,
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                branch=target.branch,
                artifact_root=target.artifact_root,
                files_published=len(files),
                total_bytes=total_bytes,
                commit_shas=(),
                committed_paths=tuple(item.path for item in files),
                published_at=published_at,
            )

        default_branch = self._resolve_default_branch(repo_owner=target.repo_owner, repo_name=target.repo_name)
        repo_initialized = self._is_repository_initialized(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            default_branch=default_branch,
        )
        management_state = self._evaluate_repo_management_state(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            target_ref=target.branch,
            expected_business_id=_normalize_repo_management_id(target.business_id),
            expected_site_id=_normalize_repo_management_id(target.site_id),
            repo_initialized=repo_initialized,
            default_branch=default_branch,
            error_stage="publish",
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_repo_management_marker_check",
                "repo_owner": target.repo_owner,
                "repo_name": target.repo_name,
                "ref": target.branch,
                "repo_initialized": repo_initialized,
                "repo_management_status": management_state.status,
                "repo_management_marker_present": management_state.marker_present,
                "repo_management_marker_valid": management_state.marker_valid,
                "repo_management_marker_matches_site": management_state.marker_matches_site,
                "repo_management_marker_source_ref": management_state.source_ref,
                "repo_management_blocker_code": management_state.blocker_code,
                "operation_kind": "publish_contents",
            },
            fallback_message="seo_migration_repo_management_marker_check",
            level=(logging.INFO if not management_state.blocker_code else logging.WARNING),
        )
        if management_state.blocker_code:
            raise SEOMigrationGitHubPublisherError(
                code=management_state.blocker_code,
                safe_message=management_state.blocker_message
                or "Repository is not managed by MBSRN and publish is blocked.",
                stage="publish",
            )
        effective_business_id = _normalize_repo_management_id(target.business_id) or _normalize_repo_management_id(
            management_state.marker_business_id
        )
        effective_site_id = _normalize_repo_management_id(target.site_id) or _normalize_repo_management_id(
            management_state.marker_site_id
        )
        baseline_reconcile_result = self._reconcile_managed_repo_baseline_files(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            branch=target.branch,
            business_id=effective_business_id,
            site_id=effective_site_id,
            dry_run=dry_run,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_repo_baseline_reconciliation",
                "repo_owner": target.repo_owner,
                "repo_name": target.repo_name,
                "ref": target.branch,
                "repo_visibility_target": _MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY,
                "repo_baseline_required": baseline_reconcile_result.get("repo_baseline_required"),
                "repo_baseline_initialized": False,
                "repo_baseline_reconciled": baseline_reconcile_result.get("repo_baseline_reconciled"),
                "repo_management_marker_present": management_state.marker_present,
                "repo_management_marker_valid": management_state.marker_valid,
                "readme_present": baseline_reconcile_result.get("readme_present"),
                "gitignore_present": baseline_reconcile_result.get("gitignore_present"),
                "license_present": baseline_reconcile_result.get("license_present"),
            },
            fallback_message="seo_migration_repo_baseline_reconciliation",
            level=logging.INFO,
        )

        commit_shas: list[str] = []
        total_bytes = 0
        for file_item in files:
            payload_bytes = _payload_bytes(file_item)
            total_bytes += len(payload_bytes)
            final_path = _join_repo_path(target.artifact_root, file_item.path)
            try:
                existing_payload = self._request_json(
                    method="GET",
                    path=(
                        f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                        f"/contents/{urllib.parse.quote(final_path, safe='/')}?ref={urllib.parse.quote(target.branch, safe='')}"
                    ),
                    expected_statuses=(200,),
                    allow_404=True,
                    error_stage="publish",
                    status_error_map={
                        401: (
                            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                            "GitHub token is not authorized to write repository contents for publish.",
                        ),
                        403: (
                            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                            "GitHub token is not authorized to write repository contents for publish.",
                        ),
                    },
                )
            except SEOMigrationGitHubPublisherError as exc:
                if exc.code == "github_request_failed":
                    raise self._classify_publish_request_failed(exc=exc) from exc
                raise
            existing_sha = _coerce_string(existing_payload.get("sha")) if isinstance(existing_payload, dict) else None
            encoded_content = base64.b64encode(payload_bytes).decode("ascii")
            payload: dict[str, object] = {
                "message": commit_message,
                "content": encoded_content,
                "branch": target.branch,
                "committer": {
                    "name": self.committer_name,
                    "email": self.committer_email,
                },
            }
            if existing_sha:
                payload["sha"] = existing_sha
            try:
                response_payload = self._request_json(
                    method="PUT",
                    path=(
                        f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                        f"/contents/{urllib.parse.quote(final_path, safe='/')}"
                    ),
                    payload=payload,
                    error_stage="publish",
                    status_error_map={
                        401: (
                            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                            "GitHub token is not authorized to write repository contents for publish.",
                        ),
                        403: (
                            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                            "GitHub token is not authorized to write repository contents for publish.",
                        ),
                    },
                )
            except SEOMigrationGitHubPublisherError as exc:
                if exc.code == "github_request_failed":
                    raise self._classify_publish_request_failed(exc=exc) from exc
                raise
            if not isinstance(response_payload, dict):
                raise SEOMigrationGitHubPublisherError(
                    code="publish_response_invalid",
                    safe_message="GitHub publish response was malformed.",
                )
            commit_payload = response_payload.get("commit")
            if isinstance(commit_payload, dict):
                commit_sha = str(commit_payload.get("sha") or "").strip()
                if commit_sha:
                    commit_shas.append(commit_sha)
            committed_paths.append(final_path)

        return SEOMigrationGitHubPublishResult(
            dry_run=False,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            branch=target.branch,
            artifact_root=target.artifact_root,
            files_published=len(files),
            total_bytes=total_bytes,
            commit_shas=tuple(_dedupe_strings(commit_shas)),
            committed_paths=tuple(committed_paths),
            published_at=published_at,
        )

    def _classify_publish_request_failed(
        self,
        *,
        exc: SEOMigrationGitHubPublisherError,
    ) -> SEOMigrationGitHubPublisherError:
        provider_message = _sanitize_github_error_message(exc.provider_message)
        provider_message_lower = (provider_message or "").lower()
        branch_state_markers = (
            "branch",
            "ref",
            "reference",
            "repository is empty",
            "empty repository",
            "no commit",
            "no default branch",
            "uninitialized",
        )
        if exc.status_code == 409 or (
            exc.status_code == 422
            and (not provider_message_lower or any(marker in provider_message_lower for marker in branch_state_markers))
        ):
            return SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                safe_message="GitHub repository branch is missing or uninitialized for publish.",
                status_code=exc.status_code,
                stage=exc.stage or "publish",
                provider_message=provider_message,
            )
        return SEOMigrationGitHubPublisherError(
            code=_GITHUB_REASON_CONTENTS_PUBLISH_FAILED,
            safe_message="GitHub repository contents publish request failed.",
            status_code=exc.status_code,
            stage=exc.stage or "publish",
            provider_message=provider_message,
        )

    def upsert_actions_secret(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        secret_name: str,
        secret_value: str,
    ) -> SEOMigrationGitHubActionsSecretUpsertResult:
        normalized_secret_name = (_coerce_string(secret_name) or "").upper()
        if not normalized_secret_name or not re.fullmatch(r"[A-Z0-9_]{1,80}", normalized_secret_name):
            raise SEOMigrationGitHubPublisherError(
                code="github_secret_invalid",
                safe_message="GitHub Actions secret target is invalid.",
                stage="secret_propagation",
            )
        normalized_secret_value = _coerce_string(secret_value)
        if not normalized_secret_value:
            raise SEOMigrationGitHubPublisherError(
                code="runtime_credential_missing",
                safe_message="Deploy credential is unavailable for repository propagation.",
                stage="secret_propagation",
            )

        self._ensure_repo_exists(repo_owner=repo_owner, repo_name=repo_name)
        secret_path = (
            f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
            f"/actions/secrets/{urllib.parse.quote(normalized_secret_name, safe='')}"
        )
        existing_secret_payload = self._request_json(
            method="GET",
            path=secret_path,
            expected_statuses=(200,),
            allow_404=True,
            error_stage="secret_propagation",
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy secret propagation.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy secret propagation.",
                ),
                404: (
                    "repo_not_found",
                    "GitHub repository target was not found.",
                ),
            },
        )
        action = "updated" if isinstance(existing_secret_payload, dict) else "created"

        public_key_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}" "/actions/secrets/public-key"
            ),
            expected_statuses=(200,),
            error_stage="secret_propagation",
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy secret propagation.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy secret propagation.",
                ),
                404: (
                    "repo_not_found",
                    "GitHub repository target was not found.",
                ),
            },
        )
        if not isinstance(public_key_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code="github_secret_public_key_invalid",
                safe_message="GitHub Actions secret public key response was malformed.",
                stage="secret_propagation",
            )
        key_id = _coerce_string(public_key_payload.get("key_id"))
        public_key_value = _coerce_string(public_key_payload.get("key"))
        if not key_id or not public_key_value:
            raise SEOMigrationGitHubPublisherError(
                code="github_secret_public_key_invalid",
                safe_message="GitHub Actions secret public key response was malformed.",
                stage="secret_propagation",
            )
        encrypted_value = _encrypt_actions_secret_value(
            public_key=public_key_value,
            secret_value=normalized_secret_value,
        )
        self._request_json(
            method="PUT",
            path=secret_path,
            payload={
                "encrypted_value": encrypted_value,
                "key_id": key_id,
            },
            expected_statuses=(201, 204),
            expect_object=False,
            error_stage="secret_propagation",
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy secret propagation.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy secret propagation.",
                ),
                404: (
                    "repo_not_found",
                    "GitHub repository target was not found.",
                ),
                422: (
                    "github_secret_invalid",
                    "GitHub Actions secret payload is invalid.",
                ),
            },
        )
        return SEOMigrationGitHubActionsSecretUpsertResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            secret_name=normalized_secret_name,
            action=action,
            updated_at=utc_now().isoformat(),
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
        normalized_namespace = _safe_identifier_fragment(
            kubernetes_namespace,
            fallback="site",
            max_length=63,
        )
        normalized_git_userid = _coerce_string(git_userid)
        normalized_git_email = _coerce_string(git_email)
        normalized_git_token = _coerce_string(git_token)
        missing_fields: list[str] = []
        if not normalized_git_userid:
            missing_fields.append(_GIT_ENV_USERID.lower())
        if not normalized_git_email:
            missing_fields.append(_GIT_ENV_EMAIL.lower())
        if not normalized_git_token:
            missing_fields.append(_GIT_ENV_TOKEN.lower())
        if missing_fields:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_IMAGE_PULL_SECRET_MISSING,
                safe_message=(
                    "Managed deploy target is missing required GHCR pull credentials "
                    "(GIT_USERID, GIT_EMAIL, GIT_TOKEN)."
                ),
                stage="image_pull_secret_provision",
            )
        if not _coerce_string(gcp_deploy_key):
            raise SEOMigrationGitHubPublisherError(
                code="runtime_credential_missing",
                safe_message="Managed deploy runtime credential is unavailable for image pull secret provisioning.",
                stage="image_pull_secret_provision",
            )
        normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
        cluster_name = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_NAME))
        cluster_location = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_LOCATION))
        project_id = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_PROJECT_ID))
        if not cluster_name:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME,
                safe_message="Managed deploy target is missing required GKE cluster name configuration.",
                stage="image_pull_secret_provision",
            )
        if not cluster_location:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION,
                safe_message="Managed deploy target is missing required GKE cluster location configuration.",
                stage="image_pull_secret_provision",
            )
        if not project_id:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID,
                safe_message="Managed deploy target is missing required GKE project id configuration.",
                stage="image_pull_secret_provision",
            )

        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_managed_image_pull_secret_provisioning",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": ref,
                "kubernetes_namespace": normalized_namespace,
                "secret_name": _MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
                "dry_run": bool(dry_run),
                "operation_status": "started",
            },
            fallback_message="seo_migration_managed_image_pull_secret_provisioning",
            level=logging.INFO,
        )
        if dry_run:
            return SEOMigrationGitHubImagePullSecretProvisionResult(
                repo_owner=repo_owner,
                repo_name=repo_name,
                namespace=normalized_namespace,
                secret_name=_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
                action=_normalize_managed_image_pull_secret_action("dry_run", allow_dry_run=True),
            )

        try:
            action = _normalize_managed_image_pull_secret_action(
                _upsert_namespace_scoped_ghcr_pull_secret(
                    gcp_deploy_key=gcp_deploy_key,
                    project_id=project_id,
                    cluster_location=cluster_location,
                    cluster_name=cluster_name,
                    kubernetes_namespace=normalized_namespace,
                    git_userid=normalized_git_userid,
                    git_email=normalized_git_email,
                    git_token=normalized_git_token,
                    timeout_seconds=self.timeout_seconds,
                )
            )
        except SEOMigrationGitHubPublisherError:
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_managed_image_pull_secret_provisioning",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": ref,
                    "kubernetes_namespace": normalized_namespace,
                    "secret_name": _MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
                    "operation_status": "failed",
                },
                fallback_message="seo_migration_managed_image_pull_secret_provisioning",
                level=logging.WARNING,
            )
            raise
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_managed_image_pull_secret_provisioning",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": ref,
                "kubernetes_namespace": normalized_namespace,
                "secret_name": _MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
                "operation_status": "completed",
                "action": action,
            },
            fallback_message="seo_migration_managed_image_pull_secret_provisioning",
            level=logging.INFO,
        )
        return SEOMigrationGitHubImagePullSecretProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            namespace=normalized_namespace,
            secret_name=_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
            action=action,
        )

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
        del repo_owner
        preview_endpoint = resolve_managed_preview_endpoint_configuration(
            repo_name=repo_name,
            site_id=site_id,
            preview_hostname=preview_hostname,
            namespace_isolation_defaults=namespace_isolation_defaults,
        )
        preview_endpoint_reason_code = _coerce_string(preview_endpoint.get("reason_code"))
        if preview_endpoint_reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_MISSING:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_MISSING,
                safe_message=(
                    "Shared preview gateway mode is enabled, but shared preview static IP name is not configured."
                ),
                stage="static_ip_provision",
            )
        if preview_endpoint_reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_HOSTNAME_MISSING:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_HOSTNAME_MISSING,
                safe_message=(
                    "Shared preview gateway mode requires a preview hostname before deploy static-IP checks can run."
                ),
                stage="static_ip_provision",
            )
        static_ip_name = _coerce_string(preview_endpoint.get("expected_static_ip_name"))
        if not static_ip_name:
            static_ip_name, _ = derive_site_preview_static_ip_name(
                repo_name=repo_name,
                site_id=site_id,
            )
        normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
        project_id = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_PROJECT_ID))
        if not project_id:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING,
                safe_message=(
                    "Managed deploy target is missing required GKE project id configuration "
                    "for static IP provisioning."
                ),
                stage="static_ip_provision",
            )
        impersonated_service_account_email: str | None = None
        if self.managed_deploy_service_account_email:
            impersonated_service_account_email = _validate_managed_deploy_impersonation_service_account_email(
                self.managed_deploy_service_account_email,
                stage="static_ip_provision",
            )
        credential_source, principal_email = _resolve_google_credential_principal(
            credentials_json=gcp_deploy_key,
            timeout_seconds=self.timeout_seconds,
        )
        if impersonated_service_account_email:
            credential_source = _GCP_CREDENTIAL_SOURCE_MANAGED_DEPLOY_IMPERSONATION
        if dry_run:
            return SEOMigrationGitHubManagedSiteStaticIPEnsureResult(
                static_ip_name=static_ip_name,
                static_ip_address=None,
                static_ip_created=False,
                gcp_project_id=project_id,
                result="dry_run",
                gcp_credential_source=credential_source,
                gcp_principal_email=principal_email,
                gcp_impersonated_service_account_email=impersonated_service_account_email,
            )
        ownership_labels: dict[str, str] | None = None
        if bool(preview_endpoint.get("requires_dedicated_static_ip")):
            ownership_preview_hostname = _coerce_string(preview_endpoint.get("preview_hostname"))
            if not ownership_preview_hostname:
                ownership_preview_hostname, _ = derive_site_preview_hostname(
                    repo_name=repo_name,
                    site_id=site_id,
                )
            ownership_labels = build_managed_site_static_ip_labels(
                repo_name=repo_name,
                site_id=site_id,
                preview_hostname=ownership_preview_hostname,
            )
        try:
            ensure_result = _ensure_managed_site_global_static_ip(
                gcp_deploy_key=_coerce_string(gcp_deploy_key),
                project_id=project_id,
                static_ip_name=static_ip_name,
                timeout_seconds=self.timeout_seconds,
                labels=ownership_labels,
                gcp_credential_source=credential_source,
                gcp_principal_email=principal_email,
                gcp_impersonated_service_account_email=impersonated_service_account_email,
            )
        except SEOMigrationGitHubPublisherError as exc:
            diagnostics = _normalize_static_ip_error_diagnostics(
                {
                    **(exc.diagnostics if isinstance(exc.diagnostics, dict) else {}),
                    "gcp_credential_source": credential_source,
                    "gcp_principal_email": principal_email,
                    "gcp_impersonated_service_account_email": impersonated_service_account_email,
                }
            )
            if exc.code in {
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PERMISSION_DENIED,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_API_DISABLED,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_QUOTA_EXCEEDED,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROJECT_NOT_FOUND,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_ADDRESS_MISSING,
                _DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_ADDRESS_MISSING_AFTER_RETRY,
                _DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_PROVISIONING_PENDING,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED,
            }:
                raise SEOMigrationGitHubPublisherError(
                    code=exc.code,
                    safe_message=exc.safe_message,
                    status_code=exc.status_code,
                    stage=exc.stage,
                    provider_message=exc.provider_message,
                    diagnostics=diagnostics,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED,
                safe_message="Managed site static IP provisioning failed before deploy dispatch.",
                status_code=exc.status_code,
                stage=exc.stage or "static_ip_provision",
                provider_message=exc.provider_message,
                diagnostics=diagnostics,
            ) from exc
        return SEOMigrationGitHubManagedSiteStaticIPEnsureResult(
            static_ip_name=static_ip_name,
            static_ip_address=_coerce_string(ensure_result.get("static_ip_address")),
            static_ip_created=bool(ensure_result.get("static_ip_created")),
            gcp_project_id=project_id,
            result=_coerce_string(ensure_result.get("result")) or "exists",
            gcp_credential_source=credential_source,
            gcp_principal_email=principal_email,
            gcp_impersonated_service_account_email=impersonated_service_account_email,
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
        normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower().rstrip(".")
        if not normalized_preview_hostname:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
                safe_message="Managed-site DNS provisioning requires a preview hostname.",
                stage="dns_provision",
            )
        expected_suffix = f".{_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX}"
        if not normalized_preview_hostname.endswith(expected_suffix):
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
                safe_message=(
                    "Managed-site DNS provisioning is restricted to preview hostnames under "
                    f"{_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX}."
                ),
                stage="dns_provision",
            )
        normalized_record_name = f"{normalized_preview_hostname}."
        normalized_expected_ip = _coerce_string(expected_ip_address)
        if not normalized_expected_ip:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_ADDRESS_MISSING,
                safe_message=(
                    "Managed-site static IP ensure succeeded but did not provide an address for DNS provisioning."
                ),
                stage="static_ip_provision",
            )
        normalized_zone = (_coerce_string(dns_managed_zone) or "").strip().lower()
        normalized_project_id = (_coerce_string(dns_project_id) or "").strip().lower()
        if not normalized_zone or not normalized_project_id:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
                safe_message=("Managed-site DNS provisioning requires managed zone and project configuration."),
                stage="dns_provision",
            )
        normalized_ttl = _coerce_int(ttl)
        if normalized_ttl is None or normalized_ttl <= 0:
            normalized_ttl = _MBSRN_MANAGED_PREVIEW_DNS_TTL_DEFAULT
        impersonated_service_account_email: str | None = None
        if self.managed_deploy_service_account_email:
            impersonated_service_account_email = _validate_managed_deploy_impersonation_service_account_email(
                self.managed_deploy_service_account_email,
                stage="dns_provision",
            )
        credential_source, principal_email = _resolve_google_credential_principal(
            credentials_json=gcp_deploy_key,
            timeout_seconds=self.timeout_seconds,
        )
        if impersonated_service_account_email:
            credential_source = _GCP_CREDENTIAL_SOURCE_MANAGED_DEPLOY_IMPERSONATION
        if dry_run:
            return SEOMigrationGitHubManagedSiteDnsEnsureResult(
                dns_record_name=normalized_record_name,
                dns_record_type="A",
                dns_managed_zone=normalized_zone,
                dns_project_id=normalized_project_id,
                dns_expected_ip=normalized_expected_ip,
                dns_previous_ips=(),
                dns_updated=False,
                dns_created=False,
                dns_ttl=normalized_ttl,
                result="dry_run",
                gcp_credential_source=credential_source,
                gcp_principal_email=principal_email,
                gcp_impersonated_service_account_email=impersonated_service_account_email,
            )
        try:
            ensure_result = _ensure_managed_site_dns_a_record(
                gcp_deploy_key=_coerce_string(gcp_deploy_key),
                dns_project_id=normalized_project_id,
                dns_managed_zone=normalized_zone,
                record_name=normalized_record_name,
                expected_ip_address=normalized_expected_ip,
                ttl=normalized_ttl,
                timeout_seconds=self.timeout_seconds,
                gcp_impersonated_service_account_email=impersonated_service_account_email,
            )
        except SEOMigrationGitHubPublisherError as exc:
            diagnostics = _normalize_gcp_credential_diagnostics(
                {
                    **(exc.diagnostics if isinstance(exc.diagnostics, dict) else {}),
                    "gcp_credential_source": credential_source,
                    "gcp_principal_email": principal_email,
                    "gcp_impersonated_service_account_email": impersonated_service_account_email,
                }
            )
            if exc.code in {
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PROVISIONING_FAILED,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFLICTING_RECORD,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PERMISSION_DENIED,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_TRANSACTION_CONFLICT,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_ADDRESS_MISSING,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED,
            }:
                raise SEOMigrationGitHubPublisherError(
                    code=exc.code,
                    safe_message=exc.safe_message,
                    status_code=exc.status_code,
                    stage=exc.stage,
                    provider_message=exc.provider_message,
                    diagnostics=diagnostics,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PROVISIONING_FAILED,
                safe_message="Managed-site DNS provisioning failed before deploy dispatch.",
                status_code=exc.status_code,
                stage=exc.stage or "dns_provision",
                provider_message=exc.provider_message,
                diagnostics=diagnostics,
            ) from exc
        previous_ips_raw = ensure_result.get("dns_previous_ips")
        previous_ips: list[str] = []
        if isinstance(previous_ips_raw, list):
            for raw in previous_ips_raw:
                candidate = _coerce_string(raw)
                if candidate:
                    previous_ips.append(candidate)
        return SEOMigrationGitHubManagedSiteDnsEnsureResult(
            dns_record_name=_coerce_string(ensure_result.get("dns_record_name")) or normalized_record_name,
            dns_record_type="A",
            dns_managed_zone=normalized_zone,
            dns_project_id=normalized_project_id,
            dns_expected_ip=normalized_expected_ip,
            dns_previous_ips=tuple(_dedupe_strings(previous_ips)),
            dns_updated=bool(ensure_result.get("dns_updated")),
            dns_created=bool(ensure_result.get("dns_created")),
            dns_ttl=_coerce_int(ensure_result.get("dns_ttl")) or normalized_ttl,
            result=_coerce_string(ensure_result.get("result")) or "exists",
            gcp_credential_source=credential_source,
            gcp_principal_email=principal_email,
            gcp_impersonated_service_account_email=impersonated_service_account_email,
        )

    def check_managed_certificate_readiness(
        self,
        *,
        repo_name: str,
        site_id: str | None,
        preview_hostname: str,
        kubernetes_namespace: str,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        expected_managed_certificate_name: str | None = None,
    ) -> SEOMigrationGitHubManagedCertificateReadinessResult:
        normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower().rstrip(".")
        if not normalized_preview_hostname:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_HOSTNAME_MISSING,
                safe_message=(
                    "ManagedCertificate readiness checks require a valid preview hostname before deploy dispatch."
                ),
                stage="certificate_readiness",
            )
        normalized_namespace = _safe_identifier_fragment(
            kubernetes_namespace,
            fallback="site",
            max_length=63,
        )
        managed_certificate_name = _coerce_string(expected_managed_certificate_name)
        if not managed_certificate_name:
            managed_certificate_name, _ = derive_site_preview_certificate_name(
                repo_name=repo_name,
                site_id=site_id,
            )
        if not managed_certificate_name:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message=(
                    "ManagedCertificate readiness checks could not derive the expected deterministic certificate name."
                ),
                stage="certificate_readiness",
            )
        normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
        cluster_name = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_NAME))
        cluster_location = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_LOCATION))
        project_id = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_PROJECT_ID))
        if not cluster_name:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME,
                safe_message="Managed deploy target is missing required GKE cluster name configuration.",
                stage="certificate_readiness",
            )
        if not cluster_location:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION,
                safe_message="Managed deploy target is missing required GKE cluster location configuration.",
                stage="certificate_readiness",
            )
        if not project_id:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID,
                safe_message="Managed deploy target is missing required GKE project id configuration.",
                stage="certificate_readiness",
            )

        impersonated_service_account_email: str | None = None
        if self.managed_deploy_service_account_email:
            impersonated_service_account_email = _validate_managed_deploy_impersonation_service_account_email(
                self.managed_deploy_service_account_email,
                stage="certificate_readiness",
            )
        credential_source, principal_email = _resolve_google_credential_principal(
            credentials_json=gcp_deploy_key,
            timeout_seconds=self.timeout_seconds,
        )
        if impersonated_service_account_email:
            credential_source = _GCP_CREDENTIAL_SOURCE_MANAGED_DEPLOY_IMPERSONATION

        access_token = _resolve_google_access_token_for_managed_deploy_operations(
            credentials_json=_coerce_string(gcp_deploy_key),
            impersonated_service_account_email=impersonated_service_account_email,
            missing_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            missing_safe_message=(
                "ManagedCertificate readiness check could not resolve control-plane credentials."
            ),
            invalid_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            invalid_safe_message=(
                "ManagedCertificate readiness check could not resolve control-plane credentials."
            ),
            integration_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            integration_safe_message=(
                "ManagedCertificate readiness check could not resolve control-plane credentials."
            ),
            stage="certificate_readiness",
        )
        encoded_project = urllib.parse.quote(project_id, safe="")
        encoded_location = urllib.parse.quote(cluster_location, safe="")
        encoded_cluster = urllib.parse.quote(cluster_name, safe="")
        cluster_payload = _request_google_json(
            method="GET",
            url=(
                "https://container.googleapis.com/v1/projects/"
                f"{encoded_project}/locations/{encoded_location}/clusters/{encoded_cluster}"
            ),
            access_token=access_token,
            timeout_seconds=self.timeout_seconds,
            error_stage="certificate_readiness",
            code_on_failure=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            safe_message_on_failure=(
                "ManagedCertificate readiness check could not resolve target GKE cluster metadata."
            ),
            safe_message_on_timeout="ManagedCertificate readiness check timed out while loading cluster metadata.",
        )
        if not isinstance(cluster_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message="ManagedCertificate readiness check could not resolve target GKE cluster metadata.",
                stage="certificate_readiness",
            )
        cluster_endpoint = _coerce_string(cluster_payload.get("endpoint"))
        if not cluster_endpoint:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message="ManagedCertificate readiness check could not resolve target GKE cluster endpoint.",
                stage="certificate_readiness",
            )
        master_auth = cluster_payload.get("masterAuth")
        cluster_ca_certificate = ""
        if isinstance(master_auth, dict):
            cluster_ca_certificate = _coerce_string(master_auth.get("clusterCaCertificate"))
        if not cluster_ca_certificate:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message="ManagedCertificate readiness check could not resolve target GKE cluster CA bundle.",
                stage="certificate_readiness",
            )
        try:
            decoded_cluster_ca = base64.b64decode(cluster_ca_certificate.encode("ascii")).decode(
                "utf-8",
                errors="ignore",
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message="ManagedCertificate readiness check could not decode target GKE cluster CA bundle.",
                stage="certificate_readiness",
            ) from exc
        ssl_context = ssl.create_default_context(cadata=decoded_cluster_ca)
        certificate_path = (
            "/apis/networking.gke.io/v1/namespaces/"
            f"{urllib.parse.quote(normalized_namespace, safe='')}/managedcertificates/"
            f"{urllib.parse.quote(managed_certificate_name, safe='')}"
        )
        managed_certificate_payload = _request_kubernetes_json(
            method="GET",
            endpoint=cluster_endpoint,
            path=certificate_path,
            access_token=access_token,
            ssl_context=ssl_context,
            timeout_seconds=self.timeout_seconds,
            allow_404=True,
            error_stage="certificate_readiness",
            code_on_failure=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            safe_message_on_failure="ManagedCertificate readiness request to Kubernetes API failed.",
            safe_message_on_timeout="ManagedCertificate readiness request timed out.",
        )
        if not isinstance(managed_certificate_payload, dict):
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_managed_certificate_readiness_probe",
                    "repo_name": repo_name,
                    "preview_hostname": normalized_preview_hostname,
                    "kubernetes_namespace": normalized_namespace,
                    "managed_certificate_name": managed_certificate_name,
                    "managed_certificate_exists": False,
                    "dispatch_service_reason_code": _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_VISIBILITY_PENDING,
                    "gcp_credential_source": credential_source,
                    "gcp_principal_email": principal_email,
                    "gcp_impersonated_service_account_email": impersonated_service_account_email,
                },
                fallback_message="seo_migration_managed_certificate_readiness_probe",
                level=logging.INFO,
            )
            return SEOMigrationGitHubManagedCertificateReadinessResult(
                managed_certificate_name=managed_certificate_name,
                preview_hostname=normalized_preview_hostname,
                kubernetes_namespace=normalized_namespace,
                managed_certificate_exists=False,
                certificate_domain_matches_expected=None,
                observed_managed_certificate_domains=(),
                observed_managed_certificate_status=None,
                observed_managed_certificate_domain_status=None,
                dispatch_service_reason_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_VISIBILITY_PENDING,
                gcp_credential_source=credential_source,
                gcp_principal_email=principal_email,
                gcp_impersonated_service_account_email=impersonated_service_account_email,
            )

        spec_payload = managed_certificate_payload.get("spec")
        observed_domains: list[str] = []
        if isinstance(spec_payload, dict):
            domains_payload = spec_payload.get("domains")
            if isinstance(domains_payload, list):
                for raw_domain in domains_payload:
                    normalized_domain = (_coerce_string(raw_domain) or "").strip().lower().rstrip(".")
                    if normalized_domain:
                        observed_domains.append(normalized_domain)
        observed_domains = _dedupe_strings(observed_domains)
        certificate_domain_matches_expected = normalized_preview_hostname in observed_domains if observed_domains else False
        ownership_verified = _managed_certificate_ownership_is_verified(
            managed_certificate_payload=managed_certificate_payload,
            repo_name=repo_name,
            site_id=site_id,
            preview_hostname=normalized_preview_hostname,
        )
        status_payload = managed_certificate_payload.get("status")
        observed_certificate_status = ""
        observed_domain_status = ""
        if isinstance(status_payload, dict):
            observed_certificate_status = _coerce_string(status_payload.get("certificateStatus"))
            domain_status_payload = status_payload.get("domainStatus")
            if isinstance(domain_status_payload, list):
                fallback_domain_status = ""
                for item in domain_status_payload:
                    if not isinstance(item, dict):
                        continue
                    candidate_status = _coerce_string(item.get("status"))
                    candidate_domain = (_coerce_string(item.get("domain")) or "").strip().lower().rstrip(".")
                    if candidate_status and not fallback_domain_status:
                        fallback_domain_status = candidate_status
                    if candidate_status and candidate_domain == normalized_preview_hostname:
                        observed_domain_status = candidate_status
                        break
                if not observed_domain_status:
                    observed_domain_status = fallback_domain_status
            elif isinstance(domain_status_payload, str):
                observed_domain_status = _coerce_string(domain_status_payload)
        normalized_certificate_status = observed_certificate_status.strip().upper()
        normalized_domain_status = observed_domain_status.strip().upper()
        dispatch_service_reason_code: str | None = None
        if certificate_domain_matches_expected is False:
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_CERTIFICATE_DOMAIN_MISMATCH
        elif ownership_verified is not True:
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_OWNERSHIP_UNVERIFIED
        elif "FAILEDNOTVISIBLE" in {normalized_certificate_status, normalized_domain_status} or "FAILED_NOT_VISIBLE" in {
            normalized_certificate_status,
            normalized_domain_status,
        }:
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE
        elif normalized_certificate_status == "PROVISIONING" or normalized_domain_status == "PROVISIONING":
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING
        elif normalized_certificate_status in {"FAILED", "ERROR"} or normalized_domain_status in {"FAILED", "ERROR"}:
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE
        elif normalized_certificate_status in {"ACTIVE", ""} and normalized_domain_status in {"ACTIVE", ""}:
            dispatch_service_reason_code = None
        else:
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING

        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_managed_certificate_readiness_probe",
                "repo_name": repo_name,
                "preview_hostname": normalized_preview_hostname,
                "kubernetes_namespace": normalized_namespace,
                "managed_certificate_name": managed_certificate_name,
                "managed_certificate_exists": True,
                "certificate_domain_matches_expected": certificate_domain_matches_expected,
                "managed_certificate_ownership_verified": ownership_verified,
                "observed_managed_certificate_domains": list(observed_domains),
                "observed_managed_certificate_status": observed_certificate_status or None,
                "observed_managed_certificate_domain_status": observed_domain_status or None,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "gcp_credential_source": credential_source,
                "gcp_principal_email": principal_email,
                "gcp_impersonated_service_account_email": impersonated_service_account_email,
            },
            fallback_message="seo_migration_managed_certificate_readiness_probe",
            level=(
                logging.INFO
                if dispatch_service_reason_code in {None, _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING}
                else logging.WARNING
            ),
        )
        return SEOMigrationGitHubManagedCertificateReadinessResult(
            managed_certificate_name=managed_certificate_name,
            preview_hostname=normalized_preview_hostname,
            kubernetes_namespace=normalized_namespace,
            managed_certificate_exists=True,
            certificate_domain_matches_expected=certificate_domain_matches_expected,
            observed_managed_certificate_domains=tuple(observed_domains),
            observed_managed_certificate_status=observed_certificate_status or None,
            observed_managed_certificate_domain_status=observed_domain_status or None,
            dispatch_service_reason_code=dispatch_service_reason_code,
            gcp_credential_source=credential_source,
            gcp_principal_email=principal_email,
            gcp_impersonated_service_account_email=impersonated_service_account_email,
        )

    def ensure_managed_certificate(
        self,
        *,
        repo_name: str,
        site_id: str | None,
        preview_hostname: str,
        kubernetes_namespace: str,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        expected_managed_certificate_name: str | None = None,
    ) -> SEOMigrationGitHubManagedCertificateEnsureResult:
        readiness = self.check_managed_certificate_readiness(
            repo_name=repo_name,
            site_id=site_id,
            preview_hostname=preview_hostname,
            kubernetes_namespace=kubernetes_namespace,
            managed_gke_config=managed_gke_config,
            gcp_deploy_key=gcp_deploy_key,
            expected_managed_certificate_name=expected_managed_certificate_name,
        )
        if readiness.managed_certificate_exists:
            if readiness.dispatch_service_reason_code in {
                _DEPLOY_DISPATCH_SERVICE_REASON_CERTIFICATE_DOMAIN_MISMATCH,
                _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_OWNERSHIP_UNVERIFIED,
            }:
                raise SEOMigrationGitHubPublisherError(
                    code=readiness.dispatch_service_reason_code,
                    safe_message=(
                        "The existing ManagedCertificate does not belong to this site or does not match its preview hostname."
                    ),
                    stage="certificate_provisioning",
                )
            return SEOMigrationGitHubManagedCertificateEnsureResult(action="reused", readiness=readiness)

        normalized_preview_hostname = readiness.preview_hostname
        normalized_namespace = readiness.kubernetes_namespace
        managed_certificate_name = readiness.managed_certificate_name
        (
            cluster_endpoint,
            ssl_context,
            access_token,
            credential_source,
            principal_email,
            impersonated_service_account_email,
        ) = self._resolve_managed_certificate_kubernetes_api_context(
            managed_gke_config=managed_gke_config,
            gcp_deploy_key=gcp_deploy_key,
            stage="certificate_provisioning",
        )
        namespace_path = "/api/v1/namespaces/" + urllib.parse.quote(
            normalized_namespace,
            safe="",
        )
        namespace_payload = _request_kubernetes_json(
            method="GET",
            endpoint=cluster_endpoint,
            path=namespace_path,
            access_token=access_token,
            ssl_context=ssl_context,
            timeout_seconds=self.timeout_seconds,
            allow_404=True,
            error_stage="certificate_provisioning",
            code_on_failure=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_CREATE_FAILED,
            safe_message_on_failure="ManagedCertificate namespace readiness request to Kubernetes API failed.",
            safe_message_on_timeout="ManagedCertificate namespace readiness request timed out.",
        )
        if not isinstance(namespace_payload, dict):
            try:
                _request_kubernetes_json(
                    method="POST",
                    endpoint=cluster_endpoint,
                    path="/api/v1/namespaces",
                    access_token=access_token,
                    ssl_context=ssl_context,
                    timeout_seconds=self.timeout_seconds,
                    payload={
                        "apiVersion": "v1",
                        "kind": "Namespace",
                        "metadata": {"name": normalized_namespace},
                    },
                    expected_statuses=(200, 201),
                    error_stage="certificate_provisioning",
                    code_on_failure=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_CREATE_FAILED,
                    safe_message_on_failure="ManagedCertificate namespace creation request to Kubernetes API failed.",
                    safe_message_on_timeout="ManagedCertificate namespace creation request timed out.",
                )
            except SEOMigrationGitHubPublisherError as exc:
                # Another request can create the deterministic site namespace after
                # the readiness probe but before this create reaches Kubernetes.
                if exc.status_code != 409:
                    raise
        create_path = "/apis/networking.gke.io/v1/namespaces/" + urllib.parse.quote(
            normalized_namespace,
            safe="",
        ) + "/managedcertificates"
        try:
            created_payload = _request_kubernetes_json(
                method="POST",
                endpoint=cluster_endpoint,
                path=create_path,
                access_token=access_token,
                ssl_context=ssl_context,
                timeout_seconds=self.timeout_seconds,
                payload={
                    "apiVersion": "networking.gke.io/v1",
                    "kind": "ManagedCertificate",
                    "metadata": {
                        "name": managed_certificate_name,
                        "namespace": normalized_namespace,
                        "labels": build_managed_certificate_ownership_labels(
                            repo_name=repo_name,
                            site_id=site_id,
                            preview_hostname=normalized_preview_hostname,
                        ),
                    },
                    "spec": {"domains": [normalized_preview_hostname]},
                },
                expected_statuses=(200, 201),
                error_stage="certificate_provisioning",
                code_on_failure=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_CREATE_FAILED,
                safe_message_on_failure="ManagedCertificate creation request to Kubernetes API failed.",
                safe_message_on_timeout="ManagedCertificate creation request timed out.",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.status_code != 409:
                raise
            refreshed_readiness = self.check_managed_certificate_readiness(
                repo_name=repo_name,
                site_id=site_id,
                preview_hostname=normalized_preview_hostname,
                kubernetes_namespace=normalized_namespace,
                managed_gke_config=managed_gke_config,
                gcp_deploy_key=gcp_deploy_key,
                expected_managed_certificate_name=managed_certificate_name,
            )
            if (
                refreshed_readiness.managed_certificate_exists
                and refreshed_readiness.certificate_domain_matches_expected is not False
                and refreshed_readiness.dispatch_service_reason_code
                != _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_OWNERSHIP_UNVERIFIED
            ):
                return SEOMigrationGitHubManagedCertificateEnsureResult(
                    action="reused",
                    readiness=refreshed_readiness,
                )
            raise
        if not isinstance(created_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_CREATE_FAILED,
                safe_message="ManagedCertificate provisioning returned no resource details.",
                stage="certificate_provisioning",
            )
        created_status_payload = created_payload.get("status")
        created_certificate_status = (
            _coerce_string(created_status_payload.get("certificateStatus"))
            if isinstance(created_status_payload, dict)
            else ""
        )
        created_readiness = SEOMigrationGitHubManagedCertificateReadinessResult(
            managed_certificate_name=managed_certificate_name,
            preview_hostname=normalized_preview_hostname,
            kubernetes_namespace=normalized_namespace,
            managed_certificate_exists=True,
            certificate_domain_matches_expected=True,
            observed_managed_certificate_domains=(normalized_preview_hostname,),
            observed_managed_certificate_status=created_certificate_status or "PROVISIONING",
            dispatch_service_reason_code=_DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING,
            gcp_credential_source=credential_source,
            gcp_principal_email=principal_email,
            gcp_impersonated_service_account_email=impersonated_service_account_email,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_managed_certificate_provisioned",
                "repo_name": repo_name,
                "preview_hostname": normalized_preview_hostname,
                "kubernetes_namespace": normalized_namespace,
                "managed_certificate_name": managed_certificate_name,
                "action": "created",
                "gcp_credential_source": credential_source,
                "gcp_principal_email": principal_email,
                "gcp_impersonated_service_account_email": impersonated_service_account_email,
            },
            fallback_message="seo_migration_managed_certificate_provisioned",
            level=logging.INFO,
        )
        return SEOMigrationGitHubManagedCertificateEnsureResult(action="created", readiness=created_readiness)

    def _resolve_managed_certificate_kubernetes_api_context(
        self,
        *,
        managed_gke_config: dict[str, object] | None,
        gcp_deploy_key: str | None,
        stage: str,
    ) -> tuple[str, ssl.SSLContext, str, str | None, str | None, str | None]:
        normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
        cluster_name = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_NAME))
        cluster_location = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_LOCATION))
        project_id = _coerce_string(normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_PROJECT_ID))
        if not cluster_name or not cluster_location or not project_id:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_CREATE_FAILED,
                safe_message="ManagedCertificate provisioning requires complete managed GKE configuration.",
                stage=stage,
            )
        impersonated_service_account_email = (
            _validate_managed_deploy_impersonation_service_account_email(
                self.managed_deploy_service_account_email,
                stage=stage,
            )
            if self.managed_deploy_service_account_email
            else None
        )
        credential_source, principal_email = _resolve_google_credential_principal(
            credentials_json=gcp_deploy_key,
            timeout_seconds=self.timeout_seconds,
        )
        if impersonated_service_account_email:
            credential_source = _GCP_CREDENTIAL_SOURCE_MANAGED_DEPLOY_IMPERSONATION
        access_token = _resolve_google_access_token_for_managed_deploy_operations(
            credentials_json=_coerce_string(gcp_deploy_key),
            impersonated_service_account_email=impersonated_service_account_email,
            missing_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            missing_safe_message="ManagedCertificate provisioning could not resolve control-plane credentials.",
            invalid_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            invalid_safe_message="ManagedCertificate provisioning could not resolve control-plane credentials.",
            integration_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            integration_safe_message="ManagedCertificate provisioning could not resolve control-plane credentials.",
            stage=stage,
        )
        cluster_payload = _request_google_json(
            method="GET",
            url=(
                "https://container.googleapis.com/v1/projects/"
                f"{urllib.parse.quote(project_id, safe='')}/locations/{urllib.parse.quote(cluster_location, safe='')}"
                f"/clusters/{urllib.parse.quote(cluster_name, safe='')}"
            ),
            access_token=access_token,
            timeout_seconds=self.timeout_seconds,
            error_stage=stage,
            code_on_failure=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
            safe_message_on_failure="ManagedCertificate provisioning could not resolve target GKE cluster metadata.",
            safe_message_on_timeout="ManagedCertificate provisioning timed out while loading cluster metadata.",
        )
        cluster_endpoint = _coerce_string(cluster_payload.get("endpoint")) if isinstance(cluster_payload, dict) else ""
        master_auth = cluster_payload.get("masterAuth") if isinstance(cluster_payload, dict) else None
        cluster_ca_certificate = _coerce_string(master_auth.get("clusterCaCertificate")) if isinstance(master_auth, dict) else ""
        if not cluster_endpoint or not cluster_ca_certificate:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message="ManagedCertificate provisioning could not resolve target GKE cluster access.",
                stage=stage,
            )
        try:
            decoded_cluster_ca = base64.b64decode(cluster_ca_certificate.encode("ascii")).decode("utf-8", errors="ignore")
        except Exception as exc:  # pragma: no cover - defensive
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE,
                safe_message="ManagedCertificate provisioning could not decode target GKE cluster CA bundle.",
                stage=stage,
            ) from exc
        return (
            cluster_endpoint,
            ssl.create_default_context(cadata=decoded_cluster_ca),
            access_token,
            credential_source,
            principal_email,
            impersonated_service_account_email,
        )

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        dispatched_at = utc_now().isoformat()
        workflow_output: dict[str, str] | None = None
        workflow_run_id: int | None = None
        workflow_run_status: str | None = None
        workflow_run_conclusion: str | None = None
        workflow_run_failure_reason_code: str | None = None
        workflow_run_failure_stage: str | None = None
        workflow_run_failure_step: str | None = None
        readiness_result: SEOMigrationGitHubTargetReadinessResult | None = None
        if not dry_run:
            readiness_result = self.check_deploy_target_readiness(
                target=target,
                allow_ref_repair=False,
                allow_workflow_repair=False,
                dry_run=False,
                remediation_mode="none",
                managed_gke_config=managed_gke_config,
                managed_image_pull_secret_config=managed_image_pull_secret_config,
            )
            readiness_gke_details = (
                readiness_result.managed_gke_config_details
                if isinstance(readiness_result.managed_gke_config_details, dict)
                else {}
            )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_dispatch_managed_gke_config_presence",
                    "repo_owner": target.repo_owner,
                    "repo_name": target.repo_name,
                    "ref": target.ref,
                    "workflow_id": target.workflow_id,
                    "effective_cluster_name_present": bool(readiness_gke_details.get("effective_cluster_name_present")),
                    "effective_cluster_location_present": bool(
                        readiness_gke_details.get("effective_cluster_location_present")
                    ),
                    "effective_project_id_present": bool(readiness_gke_details.get("effective_project_id_present")),
                    "gke_config_resolution_source": _coerce_string(
                        readiness_gke_details.get("gke_config_resolution_source")
                    ),
                    "dispatch_service_availability": bool(readiness_result.dispatch_service_availability),
                    "dispatch_service_reason_code": readiness_result.dispatch_service_reason_code,
                },
                fallback_message="seo_migration_dispatch_managed_gke_config_presence",
                level=(logging.INFO if readiness_result.dispatch_service_availability else logging.WARNING),
            )
            if (
                readiness_result.dispatch_service_availability is False
                and readiness_result.dispatch_service_reason_code in _DEPLOY_GKE_CONFIG_MISSING_REASON_PRIORITY
            ):
                raise SEOMigrationGitHubPublisherError(
                    code="workflow_not_dispatchable",
                    safe_message=(
                        "Managed deploy target is missing required GKE environment configuration "
                        "(cluster_name/location/project_id)."
                    ),
                    stage="workflow_lookup",
                )
            self._dispatch_workflow_request(
                target=target,
                preflight_ref_verified=bool(readiness_result.ref_exists),
                preflight_workflow_verified=bool(readiness_result.workflow_exists),
                preflight_dispatch_ready=bool(readiness_result.workflow_dispatch_ready),
            )
            (
                workflow_run_id,
                workflow_run_status,
                workflow_run_conclusion,
                workflow_output,
                workflow_run_failure_reason_code,
                workflow_run_failure_stage,
                workflow_run_failure_step,
            ) = self._try_capture_post_dispatch_workflow_result(
                target=target,
                dispatched_at=dispatched_at,
            )
        return SEOMigrationGitHubDeployResult(
            dry_run=dry_run,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            inputs={str(key): str(value) for key, value in target.inputs.items()},
            dispatched_at=dispatched_at,
            live_url=None,
            workflow_output=workflow_output,
            workflow_run_id=workflow_run_id,
            workflow_run_status=workflow_run_status,
            workflow_run_conclusion=workflow_run_conclusion,
            workflow_run_failure_reason_code=workflow_run_failure_reason_code,
            workflow_run_failure_stage=workflow_run_failure_stage,
            workflow_run_failure_step=workflow_run_failure_step,
        )

    def refresh_deploy_run_status(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult:
        if workflow_run_id <= 0:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_found",
                safe_message="GitHub workflow run target was not found.",
                stage="workflow_run_lookup",
            )

        run_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                f"/actions/runs/{workflow_run_id}"
            ),
            expected_statuses=(200,),
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                404: (
                    "workflow_not_found",
                    "GitHub workflow run target was not found.",
                ),
            },
            error_stage="workflow_run_lookup",
        )
        if not isinstance(run_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_found",
                safe_message="GitHub workflow run target was not found.",
                stage="workflow_run_lookup",
            )

        run_id = _coerce_int(run_payload.get("id")) or workflow_run_id
        run_status = _coerce_string(run_payload.get("status"))
        run_conclusion = _coerce_string(run_payload.get("conclusion"))
        created_at = _coerce_string(run_payload.get("created_at"))
        completed_at = _coerce_string(run_payload.get("updated_at"))
        refreshed_at = completed_at or created_at or utc_now().isoformat()

        dispatched_at_candidate = _coerce_string(dispatched_at) or created_at or refreshed_at
        workflow_output: dict[str, str] | None = None
        workflow_run_failure_reason_code: str | None = None
        workflow_run_failure_stage: str | None = None
        workflow_run_failure_step: str | None = None
        if run_status == "completed" and run_conclusion == "success":
            live_url = self._resolve_live_url_from_workflow_completion_metadata(
                target=target,
                workflow_run_id=run_id,
                dispatched_at=dispatched_at_candidate,
            )
            if live_url:
                workflow_output = {"live_url": live_url}
        elif run_status == "completed" and run_conclusion:
            (
                workflow_run_failure_reason_code,
                workflow_run_failure_stage,
                workflow_run_failure_step,
                failure_workflow_output,
            ) = self._resolve_workflow_run_failure_details(
                target=target,
                workflow_run_id=run_id,
                workflow_run_status=run_status,
                workflow_run_conclusion=run_conclusion,
            )
            if failure_workflow_output:
                workflow_output = failure_workflow_output

        return SEOMigrationGitHubDeployRunStatusResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            workflow_run_id=run_id,
            workflow_run_status=run_status,
            workflow_run_conclusion=run_conclusion,
            workflow_output=workflow_output,
            workflow_run_failure_reason_code=workflow_run_failure_reason_code,
            workflow_run_failure_stage=workflow_run_failure_stage,
            workflow_run_failure_step=workflow_run_failure_step,
            refreshed_at=refreshed_at,
        )

    def lookup_deploy_run_status_after_dispatch(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str | None = None,
    ) -> SEOMigrationGitHubDeployRunStatusResult | None:
        dispatched_at_candidate = _coerce_string(dispatched_at)
        if not dispatched_at_candidate:
            return None
        run_payload = self._find_recent_workflow_run_for_dispatch(
            target=target,
            dispatched_at=dispatched_at_candidate,
        )
        if not isinstance(run_payload, dict):
            return None
        workflow_run_id = _coerce_int(run_payload.get("id"))
        if workflow_run_id is None:
            return None
        return self.refresh_deploy_run_status(
            target=target,
            workflow_run_id=workflow_run_id,
            dispatched_at=dispatched_at_candidate,
        )

    def probe_live_runtime_https(
        self,
        *,
        probe_url: str,
    ) -> SEOMigrationGitHubLiveRuntimeProbeResult | None:
        normalized_probe_url = _normalize_url(_coerce_string(probe_url))
        checked_at = utc_now().isoformat()

        def _build_summary(
            reason: str,
            *,
            status_code: int | None = None,
            detail: str | None = None,
        ) -> str:
            summary = f"reason={reason}"
            if isinstance(status_code, int) and status_code > 0:
                summary = f"{summary};status={status_code}"
            detail_text = (_coerce_string(detail) or "").replace("\r", " ").replace("\n", " ").strip()
            if detail_text:
                summary = f"{summary};detail={detail_text[:120]}"
            return summary[:240]

        if not normalized_probe_url or not normalized_probe_url.lower().startswith("https://"):
            return SEOMigrationGitHubLiveRuntimeProbeResult(
                probe_url=normalized_probe_url or "",
                checked_at=checked_at,
                source="current_live_probe",
                live_url=None,
                host_reachable=False,
                host_reachability_scheme="https",
                deploy_https_ready=False,
                cert_identity_valid=None,
                https_probe_status_code=None,
                https_probe_error_summary=_build_summary(
                    "https_probe_not_attempted",
                    detail="invalid_or_missing_probe_url",
                ),
            )

        request = urllib.request.Request(
            url=normalized_probe_url,
            data=None,
            method="HEAD",
            headers={
                "User-Agent": "MBSRN-MigrationPublisher/1.0",
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout_seconds, 10)) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                resolved_url = _normalize_url(_coerce_string(getattr(response, "url", None))) or normalized_probe_url
                if 200 <= status_code < 400:
                    return SEOMigrationGitHubLiveRuntimeProbeResult(
                        probe_url=normalized_probe_url,
                        checked_at=checked_at,
                        source="current_live_probe",
                        live_url=resolved_url,
                        host_reachable=True,
                        host_reachability_scheme="https",
                        deploy_https_ready=True,
                        cert_identity_valid=True,
                        https_probe_status_code=status_code,
                        https_probe_error_summary=None,
                    )
                reason_code = (
                    "ingress_backend_502" if status_code == 502 else "https_probe_failed_after_control_plane_ready"
                )
                return SEOMigrationGitHubLiveRuntimeProbeResult(
                    probe_url=normalized_probe_url,
                    checked_at=checked_at,
                    source="current_live_probe",
                    live_url=resolved_url,
                    host_reachable=True,
                    host_reachability_scheme="https",
                    deploy_https_ready=False,
                    cert_identity_valid=True,
                    https_probe_status_code=status_code,
                    https_probe_error_summary=_build_summary(reason_code, status_code=status_code),
                )
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            reason_code = (
                "ingress_backend_502" if status_code == 502 else "https_probe_failed_after_control_plane_ready"
            )
            return SEOMigrationGitHubLiveRuntimeProbeResult(
                probe_url=normalized_probe_url,
                checked_at=checked_at,
                source="current_live_probe",
                live_url=normalized_probe_url,
                host_reachable=True,
                host_reachability_scheme="https",
                deploy_https_ready=False,
                cert_identity_valid=True,
                https_probe_status_code=status_code if status_code > 0 else None,
                https_probe_error_summary=_build_summary(
                    reason_code, status_code=status_code if status_code > 0 else None
                ),
            )
        except (TimeoutError, socket.timeout) as exc:
            return SEOMigrationGitHubLiveRuntimeProbeResult(
                probe_url=normalized_probe_url,
                checked_at=checked_at,
                source="current_live_probe",
                live_url=None,
                host_reachable=False,
                host_reachability_scheme="https",
                deploy_https_ready=False,
                cert_identity_valid=None,
                https_probe_status_code=None,
                https_probe_error_summary=_build_summary("https_probe_timeout", detail=str(exc)),
            )
        except urllib.error.URLError as exc:
            reason_text = str(getattr(exc, "reason", exc) or "").strip()
            reason_text_lower = reason_text.lower()
            reason_code = "https_probe_failed_after_control_plane_ready"
            cert_identity_valid: bool | None = None
            if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
                reason_code = "reachable_but_tls_certificate_mismatch"
                cert_identity_valid = False
            elif isinstance(getattr(exc, "reason", None), ssl.SSLError):
                reason_code = "reachable_but_tls_certificate_mismatch"
                cert_identity_valid = False
            elif "certificate" in reason_text_lower or "hostname" in reason_text_lower or "tls" in reason_text_lower:
                reason_code = "reachable_but_tls_certificate_mismatch"
                cert_identity_valid = False
            elif "timed out" in reason_text_lower or "timeout" in reason_text_lower:
                reason_code = "https_probe_timeout"
            elif "empty" in reason_text_lower or "eof" in reason_text_lower:
                reason_code = "https_probe_empty_reply"
            return SEOMigrationGitHubLiveRuntimeProbeResult(
                probe_url=normalized_probe_url,
                checked_at=checked_at,
                source="current_live_probe",
                live_url=None,
                host_reachable=False,
                host_reachability_scheme="https",
                deploy_https_ready=False,
                cert_identity_valid=cert_identity_valid,
                https_probe_status_code=None,
                https_probe_error_summary=_build_summary(reason_code, detail=reason_text),
            )
        except Exception as exc:  # pragma: no cover - defensive guardrail
            return SEOMigrationGitHubLiveRuntimeProbeResult(
                probe_url=normalized_probe_url,
                checked_at=checked_at,
                source="current_live_probe",
                live_url=None,
                host_reachable=False,
                host_reachability_scheme="https",
                deploy_https_ready=False,
                cert_identity_valid=None,
                https_probe_status_code=None,
                https_probe_error_summary=_build_summary(
                    "https_probe_failed_after_control_plane_ready", detail=str(exc)
                ),
            )

    def _try_capture_post_dispatch_workflow_result(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str,
    ) -> tuple[
        int | None,
        str | None,
        str | None,
        dict[str, str] | None,
        str | None,
        str | None,
        str | None,
    ]:
        try:
            run_payload = self._find_recent_workflow_run_for_dispatch(
                target=target,
                dispatched_at=dispatched_at,
            )
        except SEOMigrationGitHubPublisherError:
            return None, None, None, None, None, None, None

        if not isinstance(run_payload, dict):
            return None, None, None, None, None, None, None

        workflow_run_id = _coerce_int(run_payload.get("id"))
        workflow_run_status = _coerce_string(run_payload.get("status"))
        workflow_run_conclusion = _coerce_string(run_payload.get("conclusion"))

        workflow_output: dict[str, str] | None = None
        workflow_run_failure_reason_code: str | None = None
        workflow_run_failure_stage: str | None = None
        workflow_run_failure_step: str | None = None
        if workflow_run_status == "completed" and workflow_run_conclusion == "success":
            live_url = self._resolve_live_url_from_workflow_completion_metadata(
                target=target,
                workflow_run_id=workflow_run_id,
                dispatched_at=dispatched_at,
            )
            if live_url:
                workflow_output = {"live_url": live_url}
        elif workflow_run_status == "completed" and workflow_run_conclusion:
            (
                workflow_run_failure_reason_code,
                workflow_run_failure_stage,
                workflow_run_failure_step,
                failure_workflow_output,
            ) = self._resolve_workflow_run_failure_details(
                target=target,
                workflow_run_id=workflow_run_id,
                workflow_run_status=workflow_run_status,
                workflow_run_conclusion=workflow_run_conclusion,
            )
            if failure_workflow_output:
                workflow_output = failure_workflow_output

        return (
            workflow_run_id,
            workflow_run_status,
            workflow_run_conclusion,
            workflow_output,
            workflow_run_failure_reason_code,
            workflow_run_failure_stage,
            workflow_run_failure_step,
        )

    def _find_recent_workflow_run_for_dispatch(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str,
    ) -> dict[str, object] | None:
        dispatched_dt = _parse_iso8601_timestamp(dispatched_at)
        if dispatched_dt is None:
            return None
        lower_bound = dispatched_dt - timedelta(minutes=2)
        upper_bound = dispatched_dt + timedelta(minutes=15)
        lookup_identifier = normalize_workflow_dispatch_identifier_for_api(target.workflow_id) or target.workflow_id

        for attempt in range(3):
            runs_response = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                    f"/actions/workflows/{urllib.parse.quote(lookup_identifier, safe='')}/runs"
                    f"?event=workflow_dispatch&branch={urllib.parse.quote(target.ref, safe='')}&per_page=10"
                ),
                expected_statuses=(200,),
                status_error_map={
                    401: (
                        "token_not_authorized",
                        "GitHub token is not authorized for deploy operations.",
                    ),
                    403: (
                        "token_not_authorized",
                        "GitHub token is not authorized for deploy operations.",
                    ),
                    404: (
                        "workflow_not_found",
                        "GitHub workflow target was not found.",
                    ),
                },
                error_stage="workflow_result_lookup",
            )
            runs_payload = runs_response.get("workflow_runs") if isinstance(runs_response, dict) else None
            if not isinstance(runs_payload, list):
                return None

            selected_run: dict[str, object] | None = None
            for item in runs_payload:
                if not isinstance(item, dict):
                    continue
                head_branch = _coerce_string(item.get("head_branch"))
                if head_branch and head_branch != target.ref:
                    continue
                event_name = _coerce_string(item.get("event"))
                if event_name and event_name != "workflow_dispatch":
                    continue
                created_at_value = _parse_iso8601_timestamp(_coerce_string(item.get("created_at")))
                if created_at_value is not None:
                    if created_at_value < lower_bound or created_at_value > upper_bound:
                        continue
                selected_run = item
                break

            if selected_run is not None:
                return selected_run
            if attempt < 2:
                time.sleep(0.5)
        return None

    def _resolve_live_url_from_workflow_completion_metadata(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int | None,
        dispatched_at: str,
    ) -> str | None:
        dispatched_dt = _parse_iso8601_timestamp(dispatched_at)
        if dispatched_dt is None:
            return None
        deployments_response = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                f"/deployments?ref={urllib.parse.quote(target.ref, safe='')}&per_page=10"
            ),
            expected_statuses=(200,),
            allow_404=True,
            error_stage="workflow_result_lookup",
            expect_object=False,
        )
        if not isinstance(deployments_response, list):
            return None
        for deployment_item in deployments_response:
            if not isinstance(deployment_item, dict):
                continue
            deployment_created_at = _parse_iso8601_timestamp(_coerce_string(deployment_item.get("created_at")))
            # Ignore deployments clearly older than this dispatch window.
            if deployment_created_at is not None and deployment_created_at < (dispatched_dt - timedelta(minutes=2)):
                continue
            deployment_id = _coerce_int(deployment_item.get("id"))
            if deployment_id is None:
                continue
            statuses_response = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                    f"/deployments/{deployment_id}/statuses?per_page=10"
                ),
                expected_statuses=(200,),
                allow_404=True,
                error_stage="workflow_result_lookup",
                expect_object=False,
            )
            if not isinstance(statuses_response, list):
                continue
            for status_item in statuses_response:
                if not isinstance(status_item, dict):
                    continue
                status_state = _coerce_string(status_item.get("state")) or ""
                if status_state.lower() not in {"success", "active"}:
                    continue
                environment_url = _normalize_url(_coerce_string(status_item.get("environment_url")))
                if environment_url:
                    status_created_at = _parse_iso8601_timestamp(_coerce_string(status_item.get("created_at")))
                    if status_created_at is not None:
                        if status_created_at < (dispatched_dt - timedelta(minutes=2)):
                            continue
                        if status_created_at > (dispatched_dt + timedelta(hours=1)):
                            continue
                    if workflow_run_id is not None and not _status_links_to_workflow_run(
                        status_item=status_item,
                        workflow_run_id=workflow_run_id,
                    ):
                        continue
                    return environment_url
        return None

    def _resolve_workflow_run_failure_details(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_run_id: int | None,
        workflow_run_status: str | None,
        workflow_run_conclusion: str | None,
    ) -> tuple[str | None, str | None, str | None, dict[str, str] | None]:
        run_id = workflow_run_id if isinstance(workflow_run_id, int) and workflow_run_id > 0 else None
        run_status = (_coerce_string(workflow_run_status) or "").strip().lower()
        run_conclusion = (_coerce_string(workflow_run_conclusion) or "").strip().lower()
        if run_id is None or run_status != "completed" or run_conclusion in {"", "success"}:
            return None, None, None, None

        jobs_response = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                f"/actions/runs/{run_id}/jobs?per_page=20"
            ),
            expected_statuses=(200,),
            allow_404=True,
            error_stage="workflow_result_lookup",
        )
        jobs_payload = jobs_response.get("jobs") if isinstance(jobs_response, dict) else None
        failed_step_name: str | None = None
        failed_job_id: int | None = None
        if isinstance(jobs_payload, list):
            for job_item in jobs_payload:
                if not isinstance(job_item, dict):
                    continue
                job_conclusion = (_coerce_string(job_item.get("conclusion")) or "").strip().lower()
                if job_conclusion in {"", "success"}:
                    continue
                failed_job_id = _coerce_int(job_item.get("id"))
                steps_payload = job_item.get("steps")
                if isinstance(steps_payload, list):
                    for step_item in steps_payload:
                        if not isinstance(step_item, dict):
                            continue
                        step_conclusion = (_coerce_string(step_item.get("conclusion")) or "").strip().lower()
                        if step_conclusion in {"", "success"}:
                            continue
                        failed_step_name = _coerce_string(step_item.get("name")) or _coerce_string(job_item.get("name"))
                        break
                if failed_step_name is None:
                    failed_step_name = _coerce_string(job_item.get("name"))
                break

        reason_code, failure_stage = _classify_workflow_run_failure(
            failed_step_name=failed_step_name,
            run_conclusion=run_conclusion,
        )
        workflow_output: dict[str, str] | None = None
        if failed_job_id is not None:
            (
                cloudsql_reason_code,
                cloudsql_failure_stage,
                extracted_runtime_network_state,
            ) = self._classify_cloudsql_proxy_failure_from_job_logs(
                target=target,
                job_id=failed_job_id,
            )
            if extracted_runtime_network_state:
                workflow_output = dict(extracted_runtime_network_state)
            if cloudsql_reason_code:
                fallback_reason_codes = {
                    _DEPLOY_RUNTIME_REASON_RUNTIME_READINESS_UNKNOWN_FAILURE,
                    _DEPLOY_RUNTIME_REASON_MANAGED_DEPLOY_WORKFLOW_TEMPLATE_STALE,
                }
                should_override_with_cloudsql_reason = True
                if cloudsql_reason_code in fallback_reason_codes and reason_code not in {
                    "workflow_run_failed",
                    "ingress_endpoint_not_ready",
                }:
                    should_override_with_cloudsql_reason = False
                if should_override_with_cloudsql_reason:
                    reason_code = cloudsql_reason_code
                    if cloudsql_failure_stage:
                        failure_stage = cloudsql_failure_stage
            reason_code_present = bool(
                isinstance(workflow_output, dict)
                and workflow_output.get(_DEPLOY_RUNTIME_REASON_CODE_PRESENT_OUTPUT_KEY) == "true"
            )
            template_marker_present = bool(
                isinstance(workflow_output, dict)
                and workflow_output.get(_MANAGED_DEPLOY_TEMPLATE_MARKER_PRESENT_OUTPUT_KEY) == "true"
            )
            runtime_step_failed = bool(
                isinstance(failed_step_name, str)
                and "resolve live url from ingress status" in failed_step_name.strip().lower()
            )
            if not reason_code_present and (
                runtime_step_failed
                or reason_code in {"workflow_run_failed", "ingress_endpoint_not_ready"}
                or failure_stage == "ingress_evidence"
            ):
                reason_code = (
                    _DEPLOY_RUNTIME_REASON_RUNTIME_READINESS_UNKNOWN_FAILURE
                    if template_marker_present
                    else _DEPLOY_RUNTIME_REASON_MANAGED_DEPLOY_WORKFLOW_TEMPLATE_STALE
                )
                if workflow_output is None:
                    workflow_output = {}
                if reason_code == _DEPLOY_RUNTIME_REASON_RUNTIME_READINESS_UNKNOWN_FAILURE:
                    workflow_output.setdefault(
                        "deploy_runtime_reason_message",
                        "Managed-site runtime readiness failed before a precise reason was recorded.",
                    )
                else:
                    workflow_output.setdefault(
                        "deploy_runtime_reason_message",
                        (
                            "Deploy workflow logs did not include managed deploy template diagnostics. "
                            "Reprovision target workflow template and retry deploy."
                        ),
                    )
                if not failure_stage:
                    failure_stage = "ingress_evidence"
        ingress_failure_stages = {"ingress_verify", "ingress_evidence"}
        if failure_stage in ingress_failure_stages:
            if workflow_output is None:
                workflow_output = {}
            if "deploy_https_ready" not in workflow_output:
                workflow_output["deploy_https_ready"] = "false"
            if "https_probe_error_summary" not in workflow_output:
                fallback_probe_summary = _derive_https_probe_error_summary_for_failure(
                    reason_code=reason_code,
                    failure_stage=failure_stage,
                )
                if fallback_probe_summary is not None:
                    workflow_output["https_probe_error_summary"] = fallback_probe_summary
        return reason_code, failure_stage, failed_step_name, workflow_output

    def _classify_cloudsql_proxy_failure_from_job_logs(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        job_id: int,
    ) -> tuple[str | None, str | None, dict[str, str]]:
        if job_id <= 0:
            return None, None, {}
        logs_text = self._request_text(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                f"/actions/jobs/{job_id}/logs"
            ),
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
            },
            error_stage="workflow_result_lookup",
        )
        reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(logs_text)
        runtime_network_state = _extract_resolve_live_url_state_from_log_text(logs_text)
        runtime_network_state.update(_extract_runtime_failure_state_from_log_text(logs_text))
        return reason_code, failure_stage, runtime_network_state

    def _request_text(
        self,
        *,
        method: str,
        path: str,
        expected_statuses: tuple[int, ...] = (200,),
        allow_404: bool = False,
        status_error_map: dict[int, tuple[str, str]] | None = None,
        error_stage: str | None = None,
    ) -> str | None:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MBSRN-MigrationPublisher/1.0",
        }
        request = urllib.request.Request(
            url=f"{self.api_base_url}{path}",
            data=None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                if status_code not in expected_statuses:
                    raise SEOMigrationGitHubPublisherError(
                        code="github_unexpected_status",
                        safe_message="GitHub operation returned an unexpected status code.",
                        status_code=status_code,
                        stage=error_stage,
                    )
                response_body = response.read().decode("utf-8", errors="replace")
                return response_body if response_body else None
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            provider_message = _sanitize_github_error_message(self._extract_http_error_message(exc))
            if allow_404 and status_code == 404:
                return None
            if status_error_map and status_code in status_error_map:
                code, safe_message = status_error_map[status_code]
                raise SEOMigrationGitHubPublisherError(
                    code=code,
                    safe_message=safe_message,
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            if status_code in {401, 403}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_auth_failed",
                    safe_message="GitHub publish/deploy authentication failed.",
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            if status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code="github_target_not_found",
                    safe_message="GitHub repository or workflow target was not found.",
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            if status_code in {408, 429, 500, 502, 503, 504}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_temporal_failure",
                    safe_message="GitHub publish/deploy request failed temporarily.",
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="GitHub publish/deploy request failed.",
                status_code=status_code,
                stage=error_stage,
                provider_message=provider_message,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise SEOMigrationGitHubPublisherError(
                code="github_timeout",
                safe_message="GitHub publish/deploy request timed out.",
                stage=error_stage,
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                raise SEOMigrationGitHubPublisherError(
                    code="github_timeout",
                    safe_message="GitHub publish/deploy request timed out.",
                    stage=error_stage,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_network_error",
                safe_message="GitHub publish/deploy network request failed.",
                stage=error_stage,
            ) from exc

    def _ensure_repo_exists(self, *, repo_owner: str, repo_name: str) -> dict[str, object] | None:
        payload = self._request_json(
            method="GET",
            path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}",
            expected_statuses=(200,),
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                404: (
                    "repo_not_found",
                    "GitHub repository target was not found.",
                ),
            },
            error_stage="repo_lookup",
        )
        return payload if isinstance(payload, dict) else None

    def _ensure_repository_initialized(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        allow_repair: bool,
        repo_initialized_hint: bool | None = None,
        dry_run: bool | None = None,
        remediation_mode: str | None = None,
        workflow_path: str | None = None,
        business_id: str | None = None,
        site_id: str | None = None,
        artifact_version_id: str | None = None,
        repository_auto_create_created: bool | None = None,
        default_branch: str | None = None,
    ) -> bool:
        normalized_ref = str(ref or "").strip()
        if not normalized_ref:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_INITIALIZATION_FAILED,
                safe_message="GitHub repository initialization failed before workflow provisioning.",
                stage="workflow_provisioning",
            )
        dry_run_value = bool(dry_run) if dry_run is not None else False
        allow_repair_value = bool(allow_repair)
        bootstrap_allowed = bool(allow_repair_value and (not dry_run_value))
        normalized_remediation_mode = _coerce_string(remediation_mode) or "none"
        runtime_git_commit = _coerce_string(self.runtime_build_metadata.get("git_commit")) or "unknown"
        runtime_build_version = _coerce_string(self.runtime_build_metadata.get("build_version")) or "unknown"
        effective_default_branch = (_coerce_string(default_branch) or "").strip() or self._resolve_default_branch(
            repo_owner=repo_owner,
            repo_name=repo_name,
        )

        if repo_initialized_hint is True:
            return False

        ref_check_exc: SEOMigrationGitHubPublisherError | None = None
        branch_exists: dict[str, object] | list[object] | None = None
        try:
            branch_exists = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                    f"/branches/{urllib.parse.quote(normalized_ref, safe='')}"
                ),
                expected_statuses=(200,),
                allow_404=True,
                status_error_map={
                    401: (
                        "token_not_authorized",
                        "GitHub token is not authorized for deploy operations.",
                    ),
                    403: (
                        "token_not_authorized",
                        "GitHub token is not authorized for deploy operations.",
                    ),
                    409: (
                        _GITHUB_REASON_BRANCH_UNINITIALIZED,
                        "GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                    ),
                },
                error_stage="ref_lookup",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if not _should_treat_ref_check_as_uninitialized(exc):
                raise
            ref_check_exc = exc

        if isinstance(branch_exists, dict):
            return False

        bootstrap_decision_source = "ref_check_uninitialized" if ref_check_exc else "ref_missing_or_not_found"
        if ref_check_exc is None or bootstrap_allowed:
            try:
                effective_default_branch = self._resolve_default_branch(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                )
                self._resolve_branch_head_sha(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    branch=effective_default_branch,
                )
                return False
            except SEOMigrationGitHubPublisherError as exc:
                if not _should_treat_ref_check_as_uninitialized(exc):
                    raise
                if ref_check_exc is None:
                    ref_check_exc = exc
                    bootstrap_decision_source = "default_branch_uninitialized"

        provider_message = _sanitize_github_error_message(ref_check_exc.provider_message) if ref_check_exc else None
        will_attempt_bootstrap = False
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "repo_bootstrap_decision",
                "operation_status": "evaluated",
                "bootstrap_decision_source": bootstrap_decision_source,
                "repo_exists": True,
                "repository_auto_create_created": (
                    bool(repository_auto_create_created) if repository_auto_create_created is not None else None
                ),
                "dry_run": dry_run_value,
                "allow_repair": allow_repair_value,
                "remediation_mode": normalized_remediation_mode,
                "bootstrap_allowed": bootstrap_allowed,
                "will_attempt_bootstrap": will_attempt_bootstrap,
                "bootstrap_blocked_reason": ("bootstrap_disabled_by_execution_mode" if not bootstrap_allowed else None),
                "github_error_code": (ref_check_exc.code if ref_check_exc else _GITHUB_REASON_BRANCH_UNINITIALIZED),
                "github_error_message": provider_message,
                "http_status_code": (ref_check_exc.status_code if ref_check_exc else None),
                "ref": normalized_ref,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                "artifact_version_id": _coerce_string(artifact_version_id),
                "business_id": _coerce_string(business_id),
                "site_id": _coerce_string(site_id),
                "git_commit": runtime_git_commit,
                "build_version": runtime_build_version,
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "repo_initialization_started",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": normalized_ref,
                "step_failed": None,
                "artifact_version_id": _coerce_string(artifact_version_id),
                "business_id": _coerce_string(business_id),
                "site_id": _coerce_string(site_id),
                "dry_run": dry_run_value,
                "allow_repair": allow_repair_value,
                "remediation_mode": normalized_remediation_mode,
                "bootstrap_allowed": bootstrap_allowed,
                "repository_auto_create_created": (
                    bool(repository_auto_create_created) if repository_auto_create_created is not None else None
                ),
                "github_error_code": (ref_check_exc.code if ref_check_exc else _GITHUB_REASON_BRANCH_UNINITIALIZED),
                "github_error_message": provider_message,
                "http_status_code": (ref_check_exc.status_code if ref_check_exc else None),
                "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                "git_commit": runtime_git_commit,
                "build_version": runtime_build_version,
            },
            fallback_message="repo_initialization_started",
            level=logging.INFO,
        )
        if not bootstrap_allowed:
            _emit_structured_publisher_log(
                payload={
                    "event": "repo_initialization_failed",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "step_failed": "bootstrap_not_allowed",
                    "github_error_code": (ref_check_exc.code if ref_check_exc else _GITHUB_REASON_BRANCH_UNINITIALIZED),
                    "github_error_message": provider_message,
                    "http_status_code": (ref_check_exc.status_code if ref_check_exc else None),
                    "bootstrap_allowed": False,
                    "will_attempt_bootstrap": False,
                    "bootstrap_blocked_reason": "bootstrap_disabled_by_execution_mode",
                },
                fallback_message="repo_initialization_failed",
                level=logging.WARNING,
            )
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_INITIALIZATION_FAILED,
                safe_message=(
                    "GitHub repository is uninitialized and cannot be bootstrapped in the current execution mode."
                ),
                status_code=(ref_check_exc.status_code if ref_check_exc else None),
                stage="workflow_provisioning",
                provider_message=provider_message,
            ) from ref_check_exc

        if not bool(repository_auto_create_created):
            _emit_structured_publisher_log(
                payload={
                    "event": "repo_requires_manual_initialization",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "step_failed": "manual_initialization_required",
                    "github_error_code": _GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION,
                    "github_error_message": provider_message,
                    "http_status_code": (ref_check_exc.status_code if ref_check_exc else None),
                    "bootstrap_allowed": True,
                    "will_attempt_bootstrap": False,
                },
                fallback_message="repo_requires_manual_initialization",
                level=logging.WARNING,
            )
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_REQUIRES_MANUAL_INITIALIZATION,
                safe_message=("GitHub repository exists but is empty and must be manually initialized before publish."),
                status_code=(ref_check_exc.status_code if ref_check_exc else None),
                stage="workflow_provisioning",
                provider_message=provider_message,
            )

        try:
            verified_default_branch = self._resolve_default_branch(
                repo_owner=repo_owner,
                repo_name=repo_name,
            )
            self._resolve_branch_head_sha(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=verified_default_branch,
            )
        except SEOMigrationGitHubPublisherError as verify_exc:
            verify_provider_message = _sanitize_github_error_message(verify_exc.provider_message)
            _emit_structured_publisher_log(
                payload={
                    "event": "repo_initialization_failed",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "step_failed": "auto_init_verification_failed",
                    "github_error_code": verify_exc.code,
                    "github_error_message": verify_provider_message,
                    "http_status_code": verify_exc.status_code,
                    "bootstrap_allowed": True,
                    "will_attempt_bootstrap": False,
                },
                fallback_message="repo_initialization_failed",
                level=logging.WARNING,
            )
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_INITIALIZATION_FAILED,
                safe_message="GitHub repository initialization failed before workflow provisioning.",
                status_code=verify_exc.status_code,
                stage="workflow_provisioning",
                provider_message=verify_provider_message or verify_exc.provider_message,
            ) from verify_exc

        _emit_structured_publisher_log(
            payload={
                "event": "repo_initialization_completed",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": normalized_ref,
                "step_failed": None,
                "artifact_version_id": _coerce_string(artifact_version_id),
                "business_id": _coerce_string(business_id),
                "site_id": _coerce_string(site_id),
            },
            fallback_message="repo_initialization_completed",
            level=logging.INFO,
        )
        return True

    def _ensure_ref_exists(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        allow_repair: bool,
        ref_already_verified: bool = False,
        dry_run: bool | None = None,
        remediation_mode: str | None = None,
        workflow_path: str | None = None,
        business_id: str | None = None,
        site_id: str | None = None,
        artifact_version_id: str | None = None,
        repository_auto_create_created: bool | None = None,
        default_branch: str | None = None,
    ) -> SEOMigrationGitHubRefEnsureResult:
        normalized_ref = str(ref or "").strip()
        if not normalized_ref:
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        dry_run_value = bool(dry_run) if dry_run is not None else False
        allow_repair_value = bool(allow_repair)
        bootstrap_allowed = bool(allow_repair_value and (not dry_run_value))
        normalized_remediation_mode = _coerce_string(remediation_mode) or "none"
        runtime_git_commit = _coerce_string(self.runtime_build_metadata.get("git_commit")) or "unknown"
        runtime_build_version = _coerce_string(self.runtime_build_metadata.get("build_version")) or "unknown"
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "ref_check",
                "operation_status": "started",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": normalized_ref,
                "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                "artifact_version_id": _coerce_string(artifact_version_id),
                "business_id": _coerce_string(business_id),
                "site_id": _coerce_string(site_id),
                "dry_run": dry_run_value,
                "allow_repair": allow_repair_value,
                "remediation_mode": normalized_remediation_mode,
                "bootstrap_allowed": bootstrap_allowed,
                "git_commit": runtime_git_commit,
                "build_version": runtime_build_version,
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        if ref_already_verified:
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "ref_check",
                    "operation_status": "succeeded",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                    "artifact_version_id": _coerce_string(artifact_version_id),
                    "business_id": _coerce_string(business_id),
                    "site_id": _coerce_string(site_id),
                    "branch_exists_verified": True,
                    "repo_bootstrap_required": True,
                    "repo_bootstrap_completed": True,
                    "repo_bootstrap_state": "initialized_before_ref_check",
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.INFO,
            )
            return SEOMigrationGitHubRefEnsureResult(
                ref_exists=True,
                ref_created=False,
                reason="initialized_before_ref_check",
            )
        try:
            branch_exists = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                    f"/branches/{urllib.parse.quote(normalized_ref, safe='')}"
                ),
                expected_statuses=(200,),
                allow_404=True,
                status_error_map={
                    401: (
                        "token_not_authorized",
                        "GitHub token is not authorized for deploy operations.",
                    ),
                    403: (
                        "token_not_authorized",
                        "GitHub token is not authorized for deploy operations.",
                    ),
                    409: (
                        _GITHUB_REASON_BRANCH_UNINITIALIZED,
                        "GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                    ),
                },
                error_stage="ref_lookup",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if not _should_treat_ref_check_as_uninitialized(exc):
                raise
            return SEOMigrationGitHubRefEnsureResult(
                ref_exists=False,
                ref_created=False,
                reason="ref_check_uninitialized",
            )
        if isinstance(branch_exists, dict):
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "ref_check",
                    "operation_status": "succeeded",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                    "artifact_version_id": _coerce_string(artifact_version_id),
                    "business_id": _coerce_string(business_id),
                    "site_id": _coerce_string(site_id),
                    "branch_exists_verified": True,
                    "repo_bootstrap_required": False,
                    "repo_bootstrap_completed": False,
                    "repo_bootstrap_state": "ref_exists",
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.INFO,
            )
            return SEOMigrationGitHubRefEnsureResult(
                ref_exists=True,
                ref_created=False,
                reason="ref_exists",
            )
        if not bootstrap_allowed:
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        effective_default_branch = (_coerce_string(default_branch) or "").strip() or self._resolve_default_branch(
            repo_owner=repo_owner,
            repo_name=repo_name,
        )
        try:
            default_branch_sha = self._resolve_branch_head_sha(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=effective_default_branch,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if _should_treat_ref_check_as_uninitialized(exc):
                return SEOMigrationGitHubRefEnsureResult(
                    ref_exists=False,
                    ref_created=False,
                    reason="default_branch_uninitialized",
                )
            raise
        self._request_json(
            method="POST",
            path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/refs",
            payload={
                "ref": f"refs/heads/{normalized_ref}",
                "sha": default_branch_sha,
            },
            expected_statuses=(201,),
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                422: (
                    "branch_not_found_or_ref_invalid",
                    "GitHub deploy ref was not found or is invalid.",
                ),
            },
            error_stage="ref_lookup",
        )
        branch_exists_after = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/branches/{urllib.parse.quote(normalized_ref, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
            },
            error_stage="ref_lookup",
        )
        if not isinstance(branch_exists_after, dict):
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "ref_repair",
                "operation_status": "succeeded",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": normalized_ref,
                "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                "artifact_version_id": _coerce_string(artifact_version_id),
                "business_id": _coerce_string(business_id),
                "site_id": _coerce_string(site_id),
                "branch_exists_verified": True,
                "repo_bootstrap_required": False,
                "repo_bootstrap_completed": False,
                "repo_bootstrap_state": "ref_created_from_default",
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        return SEOMigrationGitHubRefEnsureResult(
            ref_exists=True,
            ref_created=True,
            reason="ref_created_from_default",
        )

    def _resolve_default_branch(self, *, repo_owner: str, repo_name: str) -> str:
        repo_payload = self._request_json(
            method="GET",
            path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}",
            expected_statuses=(200,),
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                404: (
                    "repo_not_found",
                    "GitHub repository target was not found.",
                ),
            },
            error_stage="repo_lookup",
        )
        default_branch = ""
        if isinstance(repo_payload, dict):
            default_branch = _coerce_string(repo_payload.get("default_branch")) or ""
        return default_branch or "main"

    def _resolve_branch_head_sha(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
    ) -> str:
        branch_ref_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/git/ref/heads/{urllib.parse.quote(branch, safe='')}"
            ),
            expected_statuses=(200,),
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                404: (
                    _GITHUB_REASON_BRANCH_UNINITIALIZED,
                    "GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                ),
                409: (
                    _GITHUB_REASON_BRANCH_UNINITIALIZED,
                    "GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                ),
            },
            error_stage="ref_lookup",
        )
        if not isinstance(branch_ref_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        object_payload = branch_ref_payload.get("object")
        if not isinstance(object_payload, dict):
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        sha = _coerce_string(object_payload.get("sha"))
        if not sha:
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        return sha

    def _is_repository_initialized(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        default_branch: str,
    ) -> bool:
        try:
            _ = self._resolve_branch_head_sha(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=default_branch,
            )
            return True
        except SEOMigrationGitHubPublisherError as exc:
            if _should_treat_ref_check_as_uninitialized(exc):
                return False
            raise

    def _evaluate_repo_management_state(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        target_ref: str,
        expected_business_id: str | None,
        expected_site_id: str | None,
        repo_initialized: bool,
        default_branch: str,
        error_stage: str,
    ) -> SEOMigrationGitHubRepoManagementState:
        normalized_target_ref = (_coerce_string(target_ref) or "").strip() or default_branch
        refs_to_try: list[str] = [normalized_target_ref]
        normalized_default_branch = (_coerce_string(default_branch) or "").strip() or "main"
        if normalized_default_branch not in refs_to_try:
            refs_to_try.append(normalized_default_branch)

        marker_payload: dict[str, object] | None = None
        source_ref: str | None = None
        for candidate_ref in refs_to_try:
            try:
                payload = self._fetch_repo_management_marker_payload(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    ref=candidate_ref,
                    error_stage=error_stage,
                )
            except SEOMigrationGitHubPublisherError as exc:
                if _should_treat_ref_check_as_uninitialized(exc):
                    continue
                raise
            if isinstance(payload, dict):
                marker_payload = payload
                source_ref = candidate_ref
                break

        if marker_payload is None:
            if not repo_initialized:
                return SEOMigrationGitHubRepoManagementState(
                    status="bootstrap_required_no_marker",
                    marker_present=False,
                    marker_valid=False,
                    marker_matches_site=True,
                    source_ref=None,
                    blocker_code=None,
                    blocker_message=None,
                )
            return SEOMigrationGitHubRepoManagementState(
                status="marker_missing",
                marker_present=False,
                marker_valid=False,
                marker_matches_site=False,
                source_ref=None,
                blocker_code=_GITHUB_REASON_REPO_ADOPTION_REQUIRED,
                blocker_message=("GitHub repository exists but is not marked as MBSRN-managed (mbsrn.key missing)."),
            )

        marker_business_id, marker_site_id = _parse_repo_management_marker_payload(marker_payload)
        if not marker_business_id or not marker_site_id:
            return SEOMigrationGitHubRepoManagementState(
                status="marker_invalid",
                marker_present=True,
                marker_valid=False,
                marker_matches_site=False,
                source_ref=source_ref,
                blocker_code=_GITHUB_REASON_REPO_MANAGEMENT_MARKER_INVALID,
                blocker_message=("GitHub repository management marker (mbsrn.key) is invalid for managed publish."),
            )
        if (
            expected_business_id
            and expected_site_id
            and (
                marker_business_id.strip().lower() != expected_business_id.strip().lower()
                or marker_site_id.strip().lower() != expected_site_id.strip().lower()
            )
        ):
            return SEOMigrationGitHubRepoManagementState(
                status="marker_mismatch",
                marker_present=True,
                marker_valid=True,
                marker_matches_site=False,
                marker_business_id=marker_business_id,
                marker_site_id=marker_site_id,
                source_ref=source_ref,
                blocker_code=_GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISMATCH,
                blocker_message=(
                    "GitHub repository management marker (mbsrn.key) is assigned to a different business/site."
                ),
            )
        return SEOMigrationGitHubRepoManagementState(
            status="managed_marker_match",
            marker_present=True,
            marker_valid=True,
            marker_matches_site=True,
            marker_business_id=marker_business_id,
            marker_site_id=marker_site_id,
            source_ref=source_ref,
            blocker_code=None,
            blocker_message=None,
        )

    def _fetch_repo_management_marker_payload(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        error_stage: str,
    ) -> dict[str, object] | None:
        try:
            payload = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                    f"/contents/{urllib.parse.quote(_MBSRN_REPO_MANAGEMENT_MARKER_PATH, safe='/')}"
                    f"?ref={urllib.parse.quote(ref, safe='')}"
                ),
                expected_statuses=(200,),
                allow_404=True,
                status_error_map={
                    401: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to read repository contents for managed publish.",
                    ),
                    403: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to read repository contents for managed publish.",
                    ),
                    409: (
                        _GITHUB_REASON_BRANCH_UNINITIALIZED,
                        "GitHub repository branch is missing or uninitialized for managed publish.",
                    ),
                    422: (
                        _GITHUB_REASON_BRANCH_UNINITIALIZED,
                        "GitHub repository branch is missing or uninitialized for managed publish.",
                    ),
                },
                error_stage=error_stage,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if _should_treat_ref_check_as_uninitialized(exc):
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                    safe_message="GitHub repository branch is missing or uninitialized for managed publish.",
                    status_code=exc.status_code,
                    stage=exc.stage,
                    provider_message=exc.provider_message,
                ) from exc
            if exc.code == "github_request_failed":
                raise self._classify_publish_request_failed(exc=exc) from exc
            raise
        if not isinstance(payload, dict):
            return None
        return payload

    def _evaluate_repo_baseline_presence(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        repo_initialized: bool,
        error_stage: str,
    ) -> dict[str, bool | None]:
        if not repo_initialized:
            return {
                "repo_baseline_required": True,
                "readme_present": None,
                "gitignore_present": None,
                "license_present": None,
            }
        readme_present = self._repo_file_exists_on_ref(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=ref,
            path=_MBSRN_MANAGED_REPO_BASELINE_README_PATH,
            error_stage=error_stage,
        )
        gitignore_present = self._repo_file_exists_on_ref(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=ref,
            path=_MBSRN_MANAGED_REPO_BASELINE_GITIGNORE_PATH,
            error_stage=error_stage,
        )
        license_present = self._repo_file_exists_on_ref(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=ref,
            path=_MBSRN_MANAGED_REPO_BASELINE_LICENSE_PATH,
            error_stage=error_stage,
        )
        return {
            "repo_baseline_required": not bool(readme_present and gitignore_present and license_present),
            "readme_present": bool(readme_present),
            "gitignore_present": bool(gitignore_present),
            "license_present": bool(license_present),
        }

    def _repo_file_exists_on_ref(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        path: str,
        error_stage: str,
    ) -> bool:
        try:
            payload = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                    f"/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(ref, safe='')}"
                ),
                expected_statuses=(200,),
                allow_404=True,
                status_error_map={
                    401: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to read repository contents for managed publish.",
                    ),
                    403: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to read repository contents for managed publish.",
                    ),
                    409: (
                        _GITHUB_REASON_BRANCH_UNINITIALIZED,
                        "GitHub repository branch is missing or uninitialized for managed publish.",
                    ),
                    422: (
                        _GITHUB_REASON_BRANCH_UNINITIALIZED,
                        "GitHub repository branch is missing or uninitialized for managed publish.",
                    ),
                },
                error_stage=error_stage,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if _should_treat_ref_check_as_uninitialized(exc):
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                    safe_message="GitHub repository branch is missing or uninitialized for managed publish.",
                    status_code=exc.status_code,
                    stage=exc.stage,
                    provider_message=exc.provider_message,
                ) from exc
            if exc.code == "github_request_failed":
                raise self._classify_publish_request_failed(exc=exc) from exc
            raise
        return isinstance(payload, dict)

    def _bootstrap_repository_branch(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        business_id: str | None = None,
        site_id: str | None = None,
    ) -> None:
        def _raise_init_failed(
            *,
            step_failed: str,
            request_path: str | None = None,
            payload_keys: tuple[str, ...] | None = None,
            status_code: int | None = None,
            provider_message: str | None = None,
            safe_message: str | None = None,
        ) -> SEOMigrationGitHubPublisherError:
            normalized_provider_message = _sanitize_github_error_message(provider_message)
            normalized_payload_keys = tuple(str(item).strip() for item in (payload_keys or ()) if str(item).strip())
            detail_parts: list[str] = []
            if request_path:
                detail_parts.append(f"request_path={request_path}")
            if normalized_payload_keys:
                detail_parts.append(f"payload_keys={','.join(normalized_payload_keys)}")
            if normalized_provider_message:
                detail_parts.append(f"detail={normalized_provider_message}")
            detail_suffix = ""
            if detail_parts:
                detail_suffix = ";" + ";".join(detail_parts)
            return SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_INITIALIZATION_FAILED,
                safe_message=(safe_message or "GitHub repository initialization failed before workflow provisioning."),
                status_code=status_code,
                stage="workflow_provisioning",
                provider_message=f"step_failed={step_failed}{detail_suffix}",
            )

        normalized_business_id = _normalize_repo_management_id(business_id)
        normalized_site_id = _normalize_repo_management_id(site_id)
        if not normalized_business_id or not normalized_site_id:
            raise _raise_init_failed(
                step_failed="blob",
                request_path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/blobs",
                payload_keys=("content", "encoding"),
                safe_message="GitHub repository bootstrap requires managed ownership metadata and cannot proceed.",
            )
        baseline_files = _render_repo_baseline_files(
            repo_owner=repo_owner,
            repo_name=repo_name,
            business_id=normalized_business_id,
            site_id=normalized_site_id,
        )
        blob_sha_by_path: dict[str, str] = {}
        for baseline_path, baseline_content in baseline_files.items():
            try:
                blob_payload = self._request_json(
                    method="POST",
                    path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/blobs",
                    payload={
                        "content": baseline_content,
                        "encoding": "utf-8",
                    },
                    expected_statuses=(201,),
                    status_error_map={
                        401: (
                            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                            "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                        ),
                        403: (
                            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                            "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                        ),
                    },
                    error_stage="workflow_provisioning",
                )
            except SEOMigrationGitHubPublisherError as exc:
                raise _raise_init_failed(
                    step_failed="blob",
                    request_path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/blobs",
                    payload_keys=("content", "encoding"),
                    status_code=exc.status_code,
                    provider_message=exc.provider_message or exc.safe_message,
                ) from exc
            blob_sha = _coerce_string((blob_payload or {}).get("sha")) if isinstance(blob_payload, dict) else None
            if not blob_sha:
                raise _raise_init_failed(
                    step_failed="blob",
                    request_path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/blobs",
                    payload_keys=("content", "encoding"),
                    safe_message="GitHub repository initialization failed before workflow provisioning.",
                    provider_message=f"missing_blob_sha_for_path={baseline_path}",
                )
            blob_sha_by_path[baseline_path] = blob_sha

        tree_request_path = f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/trees"
        try:
            tree_payload = self._request_json(
                method="POST",
                path=tree_request_path,
                payload={
                    "tree": [
                        {
                            "path": baseline_path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": baseline_sha,
                        }
                        for baseline_path, baseline_sha in blob_sha_by_path.items()
                    ]
                },
                expected_statuses=(201,),
                status_error_map={
                    401: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                    403: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                },
                error_stage="workflow_provisioning",
            )
        except SEOMigrationGitHubPublisherError as exc:
            raise _raise_init_failed(
                step_failed="tree",
                request_path=tree_request_path,
                payload_keys=("tree",),
                status_code=exc.status_code,
                provider_message=exc.provider_message or exc.safe_message,
            ) from exc
        tree_sha = _coerce_string((tree_payload or {}).get("sha")) if isinstance(tree_payload, dict) else None
        if not tree_sha:
            raise _raise_init_failed(
                step_failed="tree",
                request_path=tree_request_path,
                payload_keys=("tree",),
                provider_message="missing_tree_sha",
            )

        commit_request_path = f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/commits"
        try:
            commit_payload = self._request_json(
                method="POST",
                path=commit_request_path,
                payload={
                    "message": "chore(migration): initialize repository for managed publish bootstrap",
                    "tree": tree_sha,
                    "parents": [],
                },
                expected_statuses=(201,),
                status_error_map={
                    401: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                    403: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                },
                error_stage="workflow_provisioning",
            )
        except SEOMigrationGitHubPublisherError as exc:
            raise _raise_init_failed(
                step_failed="commit",
                request_path=commit_request_path,
                payload_keys=("message", "tree", "parents"),
                status_code=exc.status_code,
                provider_message=exc.provider_message or exc.safe_message,
            ) from exc
        commit_sha = _coerce_string((commit_payload or {}).get("sha")) if isinstance(commit_payload, dict) else None
        if not commit_sha:
            raise _raise_init_failed(
                step_failed="commit",
                request_path=commit_request_path,
                payload_keys=("message", "tree", "parents"),
                provider_message="missing_commit_sha",
            )

        ref_request_path = f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/refs"
        try:
            self._request_json(
                method="POST",
                path=ref_request_path,
                payload={
                    "ref": f"refs/heads/{branch}",
                    "sha": commit_sha,
                },
                expected_statuses=(201,),
                status_error_map={
                    401: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                    403: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                },
                error_stage="workflow_provisioning",
            )
        except SEOMigrationGitHubPublisherError as exc:
            raise _raise_init_failed(
                step_failed="ref",
                request_path=ref_request_path,
                payload_keys=("ref", "sha"),
                status_code=exc.status_code,
                provider_message=exc.provider_message or exc.safe_message,
            ) from exc

    def _fetch_workflow_file_payload_on_ref(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        workflow_path: str,
    ) -> dict[str, object] | None:
        payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/contents/{urllib.parse.quote(workflow_path, safe='/')}"
                f"?ref={urllib.parse.quote(ref, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
            },
            error_stage="workflow_lookup",
        )
        if not isinstance(payload, dict):
            return None
        return payload

    def _actions_variable_present(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        variable_name: str,
    ) -> bool:
        payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/actions/variables/{urllib.parse.quote(variable_name, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
            },
            error_stage="workflow_lookup",
        )
        return isinstance(payload, dict)

    def _actions_secret_present(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        secret_name: str,
    ) -> bool:
        payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/actions/secrets/{urllib.parse.quote(secret_name, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
            },
            error_stage="workflow_lookup",
        )
        return isinstance(payload, dict)

    def _validate_managed_gke_environment_config(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        managed_gke_config: dict[str, object] | None = None,
    ) -> tuple[str | None, list[str], dict[str, bool], dict[str, object]]:
        normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
        admin_cluster_name_present = bool(normalized_managed_gke_config.get("cluster_name"))
        admin_cluster_location_present = bool(normalized_managed_gke_config.get("cluster_location"))
        admin_project_id_present = bool(normalized_managed_gke_config.get("project_id"))
        presence = {
            "admin_cluster_name_present": admin_cluster_name_present,
            "admin_cluster_location_present": admin_cluster_location_present,
            "admin_project_id_present": admin_project_id_present,
            "cluster_name_variable_present": False,
            "cluster_location_variable_present": False,
            "project_id_variable_present": False,
            "cluster_name_secret_present": False,
            "cluster_location_secret_present": False,
            "project_id_secret_present": False,
        }
        if not admin_cluster_name_present:
            presence["cluster_name_variable_present"] = self._actions_variable_present(
                repo_owner=repo_owner,
                repo_name=repo_name,
                variable_name=_GKE_ENV_CLUSTER_NAME,
            )
        if not admin_cluster_location_present:
            presence["cluster_location_variable_present"] = self._actions_variable_present(
                repo_owner=repo_owner,
                repo_name=repo_name,
                variable_name=_GKE_ENV_CLUSTER_LOCATION,
            )
        if not admin_project_id_present:
            presence["project_id_variable_present"] = self._actions_variable_present(
                repo_owner=repo_owner,
                repo_name=repo_name,
                variable_name=_GKE_ENV_PROJECT_ID,
            )
        if not admin_cluster_name_present and not presence["cluster_name_variable_present"]:
            presence["cluster_name_secret_present"] = self._actions_secret_present(
                repo_owner=repo_owner,
                repo_name=repo_name,
                secret_name=_GKE_ENV_CLUSTER_NAME,
            )
        if not admin_cluster_location_present and not presence["cluster_location_variable_present"]:
            presence["cluster_location_secret_present"] = self._actions_secret_present(
                repo_owner=repo_owner,
                repo_name=repo_name,
                secret_name=_GKE_ENV_CLUSTER_LOCATION,
            )
        if not admin_project_id_present and not presence["project_id_variable_present"]:
            presence["project_id_secret_present"] = self._actions_secret_present(
                repo_owner=repo_owner,
                repo_name=repo_name,
                secret_name=_GKE_ENV_PROJECT_ID,
            )

        resolution_details: dict[str, object] = {}

        def _resolve_field(
            *,
            field_name: str,
            admin_present: bool,
            variable_present: bool,
            secret_present: bool,
        ) -> tuple[bool, list[str]]:
            field_details: list[str] = []
            if admin_present:
                field_details.append(_GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG)
                resolution_details[f"{field_name}_resolution_source"] = _GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG
                resolution_details[f"{field_name}_resolution_details"] = list(field_details)
                return True, field_details
            field_details.append(_GKE_CONFIG_DETAIL_ADMIN_CONFIG_MISSING)
            repo_present = variable_present or secret_present
            if repo_present:
                field_details.append(_GKE_CONFIG_DETAIL_RESOLVED_FROM_REPO_CONFIG)
                resolution_details[f"{field_name}_resolution_source"] = _GKE_CONFIG_DETAIL_RESOLVED_FROM_REPO_CONFIG
                resolution_details[f"{field_name}_resolution_details"] = list(field_details)
                return True, field_details
            field_details.append(_GKE_CONFIG_DETAIL_REPO_CONFIG_MISSING)
            resolution_details[f"{field_name}_resolution_source"] = _GKE_CONFIG_DETAIL_ADMIN_CONFIG_MISSING
            resolution_details[f"{field_name}_resolution_details"] = list(field_details)
            return False, field_details

        cluster_name_resolved, cluster_name_details = _resolve_field(
            field_name="cluster_name",
            admin_present=admin_cluster_name_present,
            variable_present=presence["cluster_name_variable_present"],
            secret_present=presence["cluster_name_secret_present"],
        )
        cluster_location_resolved, cluster_location_details = _resolve_field(
            field_name="cluster_location",
            admin_present=admin_cluster_location_present,
            variable_present=presence["cluster_location_variable_present"],
            secret_present=presence["cluster_location_secret_present"],
        )
        project_id_resolved, project_id_details = _resolve_field(
            field_name="project_id",
            admin_present=admin_project_id_present,
            variable_present=presence["project_id_variable_present"],
            secret_present=presence["project_id_secret_present"],
        )
        resolution_details["effective_cluster_name_present"] = bool(cluster_name_resolved)
        resolution_details["effective_cluster_location_present"] = bool(cluster_location_resolved)
        resolution_details["effective_project_id_present"] = bool(project_id_resolved)

        missing_reason_codes: list[str] = []
        if not cluster_name_resolved:
            missing_reason_codes.append(_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME)
        if not cluster_location_resolved:
            missing_reason_codes.append(_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION)
        if not project_id_resolved:
            missing_reason_codes.append(_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID)

        prioritized_reason_code: str | None = None
        for candidate in _DEPLOY_GKE_CONFIG_MISSING_REASON_PRIORITY:
            if candidate in missing_reason_codes:
                prioritized_reason_code = candidate
                break

        per_field_details = [cluster_name_details, cluster_location_details, project_id_details]
        flattened_details = [detail for details in per_field_details for detail in details]
        deduped_details: list[str] = []
        seen_details: set[str] = set()
        for detail in flattened_details:
            if detail in seen_details:
                continue
            seen_details.add(detail)
            deduped_details.append(detail)
        if all(details == [_GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG] for details in per_field_details):
            resolution_source = _GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG
        elif any(_GKE_CONFIG_DETAIL_RESOLVED_FROM_REPO_CONFIG in details for details in per_field_details):
            if any(_GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG in details for details in per_field_details):
                resolution_source = _GKE_CONFIG_SOURCE_MIXED
            else:
                resolution_source = _GKE_CONFIG_DETAIL_RESOLVED_FROM_REPO_CONFIG
        elif prioritized_reason_code is not None:
            resolution_source = _GKE_CONFIG_SOURCE_MISSING
        else:
            resolution_source = _GKE_CONFIG_SOURCE_UNKNOWN
        resolution_details["gke_config_resolution_source"] = resolution_source
        resolution_details["gke_config_resolution_details"] = deduped_details

        return prioritized_reason_code, missing_reason_codes, presence, resolution_details

    def _validate_managed_image_pull_secret_config(
        self,
        *,
        managed_image_pull_secret_config: dict[str, object] | None = None,
    ) -> tuple[str | None, list[str], dict[str, bool], dict[str, object]]:
        config_payload = managed_image_pull_secret_config if isinstance(managed_image_pull_secret_config, dict) else {}
        presence = {
            "git_userid_configured": bool(config_payload.get("git_userid_configured")),
            "git_email_configured": bool(config_payload.get("git_email_configured")),
            "git_token_configured": bool(config_payload.get("git_token_configured")),
        }
        image_pull_secret_required = _managed_image_pull_secret_required(config_payload)
        missing_fields: list[str] = []
        if image_pull_secret_required and not presence["git_userid_configured"]:
            missing_fields.append(_GIT_ENV_USERID.lower())
        if image_pull_secret_required and not presence["git_email_configured"]:
            missing_fields.append(_GIT_ENV_EMAIL.lower())
        if image_pull_secret_required and not presence["git_token_configured"]:
            missing_fields.append(_GIT_ENV_TOKEN.lower())
        reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_IMAGE_PULL_SECRET_MISSING if missing_fields else None
        credentials_available = (not bool(missing_fields)) if image_pull_secret_required else True
        details = {
            "image_pull_secret_name": _MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
            "image_pull_secret_config_reason_code": reason_code,
            "image_pull_secret_configured": (not bool(missing_fields)) if image_pull_secret_required else True,
            "image_pull_secret_required": image_pull_secret_required,
            "image_pull_auth_mode": "private" if image_pull_secret_required else "public",
            "image_pull_secret_missing_fields": list(missing_fields),
            "image_pull_secret_config_source": _IMAGE_PULL_SECRET_CONFIG_SOURCE_CONTROL_PLANE,
            "private_image_auth_required": image_pull_secret_required,
            "private_image_credentials_available_in_control_plane": credentials_available,
            "target_repo_secrets_not_required": True,
            "image_pull_secret_not_provisioned": bool(image_pull_secret_required),
            "image_pull_secret_provisioning_unavailable": bool(image_pull_secret_required and bool(missing_fields)),
        }
        return reason_code, missing_fields, presence, details

    def _evaluate_manifest_namespace_alignment(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        kubernetes_namespace: str,
        manifest_paths: tuple[str, ...] | list[str] | None = None,
    ) -> tuple[bool, dict[str, bool], dict[str, bool], dict[str, str | None]]:
        alignment_by_path: dict[str, bool] = {}
        presence_by_path: dict[str, bool] = {}
        content_by_path: dict[str, str | None] = {}
        effective_manifest_paths = tuple(manifest_paths or _MBSRN_MANAGED_CORE_MANIFEST_PATHS)
        for manifest_path in effective_manifest_paths:
            payload = self._fetch_workflow_file_payload_on_ref(
                repo_owner=repo_owner,
                repo_name=repo_name,
                ref=ref,
                workflow_path=manifest_path,
            )
            presence_by_path[manifest_path] = isinstance(payload, dict)
            manifest_content = _decode_workflow_file_content(payload)
            content_by_path[manifest_path] = manifest_content
            alignment_by_path[manifest_path] = _manifest_content_matches_namespace(
                manifest_path=manifest_path,
                manifest_content=manifest_content,
                kubernetes_namespace=kubernetes_namespace,
            )
        return all(alignment_by_path.values()), alignment_by_path, presence_by_path, content_by_path

    def _ensure_workflow_dispatch_ready_for_target(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        workflow_file_payload: dict[str, object] | None = None,
    ) -> tuple[bool, tuple[str, ...], SEOMigrationGitHubWorkflowConformanceResult]:
        workflow_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                f"/actions/workflows/{urllib.parse.quote(target.workflow_id, safe='')}"
            ),
            expected_statuses=(200,),
            status_error_map={
                401: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                403: (
                    "token_not_authorized",
                    "GitHub token is not authorized for deploy operations.",
                ),
                404: (
                    "workflow_not_found",
                    "GitHub workflow target was not found.",
                ),
            },
            error_stage="workflow_lookup",
        )
        workflow_state = ""
        workflow_path = ""
        if isinstance(workflow_payload, dict):
            workflow_state = (_coerce_string(workflow_payload.get("state")) or "").strip().lower()
            workflow_path = (_coerce_string(workflow_payload.get("path")) or "").strip()
        if workflow_state and workflow_state != "active":
            raise SEOMigrationGitHubPublisherError(
                code="workflow_disabled",
                safe_message="GitHub workflow is disabled for the deploy target.",
                stage="workflow_lookup",
            )
        if workflow_path:
            expected_path = _workflow_repo_path(target.workflow_id)
            if workflow_path.strip().lower() != expected_path.strip().lower():
                raise SEOMigrationGitHubPublisherError(
                    code="workflow_file_missing",
                    safe_message="GitHub workflow file was not found on the deploy ref.",
                    stage="workflow_lookup",
                )
        trigger_types = _extract_workflow_trigger_types(workflow_file_payload)
        conformance = _evaluate_workflow_conformance(
            workflow_file_payload=workflow_file_payload,
            workflow_trigger_types=trigger_types,
        )
        if conformance.conformance_status == _WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_DISPATCH_MISSING:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_dispatch_missing",
                safe_message="GitHub workflow does not define workflow_dispatch.",
                stage="workflow_lookup",
            )
        if conformance.conformance_status == _WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_PLACEHOLDER_DETECTED:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_production_ready",
                safe_message=("GitHub workflow target is scaffold-only and not production-ready for deploy execution."),
                stage="workflow_lookup",
            )
        return True, tuple(sorted(trigger_types)), conformance

    def _dispatch_workflow_request(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        preflight_ref_verified: bool = False,
        preflight_workflow_verified: bool = False,
        preflight_dispatch_ready: bool = False,
    ) -> None:
        dispatch_identifier = normalize_workflow_dispatch_identifier_for_api(target.workflow_id) or target.workflow_id
        payload = {
            "ref": target.ref,
            "inputs": target.inputs,
        }
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MBSRN-MigrationPublisher/1.0",
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(
            url=(
                f"{self.api_base_url}/repos/{urllib.parse.quote(target.repo_owner)}/"
                f"{urllib.parse.quote(target.repo_name)}/actions/workflows/"
                f"{urllib.parse.quote(dispatch_identifier, safe='')}/dispatches"
            ),
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                if status_code != 204:
                    raise SEOMigrationGitHubPublisherError(
                        code="github_unexpected_status",
                        safe_message="GitHub operation returned an unexpected status code.",
                        status_code=status_code,
                        stage="workflow_dispatch",
                    )
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            response_message = self._extract_http_error_message(exc).lower()
            if status_code in {401, 403}:
                raise SEOMigrationGitHubPublisherError(
                    code="token_not_authorized",
                    safe_message="GitHub token is not authorized for deploy operations.",
                    status_code=status_code,
                    stage="workflow_dispatch",
                ) from exc
            if status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code="workflow_not_found",
                    safe_message="GitHub workflow target was not found.",
                    status_code=status_code,
                    stage="workflow_dispatch",
                ) from exc
            if status_code == 422:
                if "workflow_dispatch" in response_message:
                    raise SEOMigrationGitHubPublisherError(
                        code="workflow_dispatch_not_supported",
                        safe_message="GitHub workflow does not support workflow_dispatch.",
                        status_code=status_code,
                        stage="workflow_dispatch",
                    ) from exc
                if "ref" in response_message or "branch" in response_message:
                    raise SEOMigrationGitHubPublisherError(
                        code="branch_not_found_or_ref_invalid",
                        safe_message="GitHub deploy ref was not found or is invalid.",
                        status_code=status_code,
                        stage="workflow_dispatch",
                    ) from exc
                fallback_code = (
                    "branch_not_found_or_ref_invalid"
                    if (not preflight_ref_verified)
                    else ("workflow_file_missing" if not preflight_workflow_verified else "workflow_dispatch_rejected")
                )
                fallback_message = (
                    "GitHub deploy ref was not found or is invalid."
                    if fallback_code == "branch_not_found_or_ref_invalid"
                    else (
                        "GitHub workflow file was not found on the deploy ref."
                        if fallback_code == "workflow_file_missing"
                        else "GitHub rejected workflow dispatch for this target."
                    )
                )
                raise SEOMigrationGitHubPublisherError(
                    code=fallback_code,
                    safe_message=fallback_message,
                    status_code=status_code,
                    stage="workflow_dispatch",
                ) from exc
            if status_code in {408, 429, 500, 502, 503, 504}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_temporal_failure",
                    safe_message="GitHub publish/deploy request failed temporarily.",
                    status_code=status_code,
                    stage="workflow_dispatch",
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="GitHub publish/deploy request failed.",
                status_code=status_code,
                stage="workflow_dispatch",
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise SEOMigrationGitHubPublisherError(
                code="github_timeout",
                safe_message="GitHub publish/deploy request timed out.",
                stage="workflow_dispatch",
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                raise SEOMigrationGitHubPublisherError(
                    code="github_timeout",
                    safe_message="GitHub publish/deploy request timed out.",
                    stage="workflow_dispatch",
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_network_error",
                safe_message="GitHub publish/deploy network request failed.",
                stage="workflow_dispatch",
            ) from exc

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
        normalized_workflow_id = str(workflow_id or "").strip()
        if not normalized_workflow_id:
            raise SEOMigrationGitHubPublisherError(
                code="github_workflow_invalid",
                safe_message="Deploy workflow target is invalid.",
            )
        normalized_workflow_mode = _normalize_deploy_workflow_mode(deploy_workflow_mode)
        normalized_target_environment_key = _normalize_target_environment_key(target_environment_key)
        normalized_target_environment_source = _normalize_target_environment_source(target_environment_source)
        normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
        private_image_auth_required = _managed_image_pull_secret_required(managed_image_pull_secret_config)
        normalized_namespace_isolation_defaults = _normalize_namespace_isolation_defaults(namespace_isolation_defaults)
        policy_expectations = _managed_policy_expectations(normalized_namespace_isolation_defaults)
        derived_namespace, namespace_source = derive_site_kubernetes_namespace(
            repo_name=repo_name,
            site_id=site_id,
        )
        preview_hostname, _ = derive_site_preview_hostname(
            repo_name=repo_name,
            site_id=site_id,
        )
        workflow_path = _workflow_repo_path(normalized_workflow_id)
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "workflow_bootstrap_start",
                "operation_status": "started",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": branch,
                "workflow_id": normalized_workflow_id,
                "workflow_path": workflow_path,
                "deploy_workflow_mode": normalized_workflow_mode,
                "target_environment_key": normalized_target_environment_key,
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        try:
            self._ensure_repo_exists(repo_owner=repo_owner, repo_name=repo_name)
            default_branch = self._resolve_default_branch(repo_owner=repo_owner, repo_name=repo_name)
            repo_initialized = self._is_repository_initialized(
                repo_owner=repo_owner,
                repo_name=repo_name,
                default_branch=default_branch,
            )
            management_state = self._evaluate_repo_management_state(
                repo_owner=repo_owner,
                repo_name=repo_name,
                target_ref=branch,
                expected_business_id=_normalize_repo_management_id(business_id),
                expected_site_id=_normalize_repo_management_id(site_id),
                repo_initialized=repo_initialized,
                default_branch=default_branch,
                error_stage="workflow_provisioning",
            )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_repo_management_marker_check",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": branch,
                    "repo_initialized": repo_initialized,
                    "repo_management_status": management_state.status,
                    "repo_management_marker_present": management_state.marker_present,
                    "repo_management_marker_valid": management_state.marker_valid,
                    "repo_management_marker_matches_site": management_state.marker_matches_site,
                    "repo_management_marker_source_ref": management_state.source_ref,
                    "repo_management_blocker_code": management_state.blocker_code,
                },
                fallback_message="seo_migration_repo_management_marker_check",
                level=(logging.INFO if not management_state.blocker_code else logging.WARNING),
            )
            effective_business_id = _normalize_repo_management_id(business_id)
            effective_site_id = _normalize_repo_management_id(site_id)
            if (
                not dry_run
                and bool(repository_auto_create_created)
                and management_state.blocker_code
                in {
                    _GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISSING,
                    _GITHUB_REASON_REPO_ADOPTION_REQUIRED,
                }
                and effective_business_id
                and effective_site_id
            ):
                baseline_reconcile_result = self._reconcile_managed_repo_baseline_files(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    branch=branch,
                    business_id=effective_business_id,
                    site_id=effective_site_id,
                    dry_run=False,
                )
                _emit_structured_publisher_log(
                    payload={
                        "event": "seo_migration_repo_baseline_reconciliation",
                        "repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "ref": branch,
                        "repo_baseline_required": baseline_reconcile_result.get("repo_baseline_required"),
                        "repo_baseline_initialized": bool(repository_auto_create_created),
                        "repo_baseline_reconciled": baseline_reconcile_result.get("repo_baseline_reconciled"),
                        "repo_management_marker_present": management_state.marker_present,
                        "repo_management_marker_valid": management_state.marker_valid,
                        "readme_present": baseline_reconcile_result.get("readme_present"),
                        "gitignore_present": baseline_reconcile_result.get("gitignore_present"),
                        "license_present": baseline_reconcile_result.get("license_present"),
                    },
                    fallback_message="seo_migration_repo_baseline_reconciliation",
                    level=logging.INFO,
                )
                repo_initialized = self._is_repository_initialized(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    default_branch=default_branch,
                )
                management_state = self._evaluate_repo_management_state(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    target_ref=branch,
                    expected_business_id=effective_business_id,
                    expected_site_id=effective_site_id,
                    repo_initialized=repo_initialized,
                    default_branch=default_branch,
                    error_stage="workflow_provisioning",
                )
                _emit_structured_publisher_log(
                    payload={
                        "event": "seo_migration_repo_management_marker_check",
                        "repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "ref": branch,
                        "repo_initialized": repo_initialized,
                        "repo_management_status": management_state.status,
                        "repo_management_marker_present": management_state.marker_present,
                        "repo_management_marker_valid": management_state.marker_valid,
                        "repo_management_marker_matches_site": management_state.marker_matches_site,
                        "repo_management_marker_source_ref": management_state.source_ref,
                        "repo_management_blocker_code": management_state.blocker_code,
                        "repo_management_recheck_after_baseline_reconcile": True,
                    },
                    fallback_message="seo_migration_repo_management_marker_check",
                    level=(logging.INFO if not management_state.blocker_code else logging.WARNING),
                )
            if management_state.blocker_code:
                raise SEOMigrationGitHubPublisherError(
                    code=management_state.blocker_code,
                    safe_message=management_state.blocker_message
                    or "Repository is not managed by MBSRN and cannot be updated.",
                    stage="workflow_provisioning",
                )
            initialization_verified_ref = self._ensure_repository_initialized(
                repo_owner=repo_owner,
                repo_name=repo_name,
                ref=branch,
                allow_repair=not dry_run,
                repo_initialized_hint=repo_initialized,
                dry_run=dry_run,
                remediation_mode="workflow_provisioning",
                workflow_path=workflow_path,
                business_id=_normalize_repo_management_id(business_id),
                site_id=_normalize_repo_management_id(site_id),
                artifact_version_id=_coerce_string(artifact_version_id),
                repository_auto_create_created=repository_auto_create_created,
                default_branch=default_branch,
            )
            ref_ensure_result = self._ensure_ref_exists(
                repo_owner=repo_owner,
                repo_name=repo_name,
                ref=branch,
                allow_repair=not dry_run,
                ref_already_verified=initialization_verified_ref,
                dry_run=dry_run,
                remediation_mode="workflow_provisioning",
                workflow_path=workflow_path,
                business_id=_normalize_repo_management_id(business_id),
                site_id=_normalize_repo_management_id(site_id),
                artifact_version_id=_coerce_string(artifact_version_id),
                repository_auto_create_created=repository_auto_create_created,
                default_branch=default_branch,
            )
            if not ref_ensure_result.ref_exists:
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_REPO_INITIALIZATION_FAILED,
                    safe_message=("GitHub repository branch is still uninitialized after repository initialization."),
                    stage="workflow_provisioning",
                )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code == "github_request_failed":
                exc = self._classify_workflow_provisioning_request_failed(exc=exc)
            failure_operation_kind = "ref_check"
            if exc.code == _GITHUB_REASON_REPO_INITIALIZATION_FAILED:
                failure_operation_kind = "repo_initialization"
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": failure_operation_kind,
                    "operation_status": "failed",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": branch,
                    "workflow_id": normalized_workflow_id,
                    "workflow_path": workflow_path,
                    "http_status_code": exc.status_code,
                    "github_error_code": exc.code,
                    "github_error_message": _sanitize_github_error_message(exc.provider_message),
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.WARNING,
            )
            raise
        workflow_yaml = _render_managed_deploy_workflow_yaml(
            workflow_id=normalized_workflow_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            deploy_workflow_mode=normalized_workflow_mode,
            target_environment_key=normalized_target_environment_key,
            target_environment_source=normalized_target_environment_source,
            managed_gke_config=normalized_managed_gke_config,
            kubernetes_namespace=derived_namespace,
            namespace_source=namespace_source,
            preview_hostname=preview_hostname,
            private_image_auth_required=private_image_auth_required,
            site_id=site_id,
            namespace_isolation_defaults=normalized_namespace_isolation_defaults,
        )
        template_validation = _validate_managed_workflow_template_before_publish(
            workflow_yaml=workflow_yaml,
        )
        if not template_validation.is_valid:
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_managed_workflow_template_validation",
                    "operation_status": "failed",
                    "template_name": _MANAGED_WORKFLOW_TEMPLATE_NAME,
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": branch,
                    "workflow_id": normalized_workflow_id,
                    "workflow_path": workflow_path,
                    "site_id": _normalize_repo_management_id(site_id),
                    "reason_code": _GITHUB_REASON_MANAGED_WORKFLOW_TEMPLATE_INVALID,
                    "validation_errors": list(template_validation.validation_errors),
                },
                fallback_message="seo_migration_managed_workflow_template_validation",
                level=logging.WARNING,
            )
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_MANAGED_WORKFLOW_TEMPLATE_INVALID,
                safe_message="Managed deploy workflow template is invalid and publish is blocked.",
                stage="workflow_provisioning",
                provider_message=";".join(template_validation.validation_errors),
            )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_managed_workflow_template_validation",
                "operation_status": "passed",
                "template_name": _MANAGED_WORKFLOW_TEMPLATE_NAME,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": branch,
                "workflow_id": normalized_workflow_id,
                "workflow_path": workflow_path,
                "site_id": _normalize_repo_management_id(site_id),
                "reason_code": None,
                "validation_errors": [],
            },
            fallback_message="seo_migration_managed_workflow_template_validation",
            level=logging.INFO,
        )
        manifest_file_payloads = _render_managed_gke_manifest_files(
            repo_owner=repo_owner,
            repo_name=repo_name,
            target_environment_key=normalized_target_environment_key,
            target_environment_source=normalized_target_environment_source,
            kubernetes_namespace=derived_namespace,
            namespace_source=namespace_source,
            preview_hostname=preview_hostname,
            private_image_auth_required=private_image_auth_required,
            namespace_isolation_defaults=normalized_namespace_isolation_defaults,
            site_id=site_id,
        )
        runtime_file_payloads = _render_managed_site_runtime_files(
            repo_owner=repo_owner,
            repo_name=repo_name,
        )
        expected_managed_manifest_paths = _expected_managed_manifest_paths(normalized_namespace_isolation_defaults)
        managed_manifest_paths = tuple(
            path for path in expected_managed_manifest_paths if path in manifest_file_payloads
        )

        commit_sha: str | None = None
        any_file_updated = False
        file_sha_by_path: dict[str, str | None] = {}
        workflow_updated, workflow_sha, workflow_managed_outcome = self._upsert_managed_repo_file(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=workflow_path,
            content=workflow_yaml,
            marker=_MBSRN_MANAGED_WORKFLOW_MARKER,
            commit_message=f"chore(migration): provision deploy workflow {normalized_workflow_id}",
            dry_run=dry_run,
            allow_managed_placeholder_upgrade=True,
            workflow_id=normalized_workflow_id,
        )
        any_file_updated = any_file_updated or workflow_updated
        file_sha_by_path[workflow_path] = workflow_sha
        if workflow_sha:
            commit_sha = workflow_sha

        for manifest_path, manifest_content in manifest_file_payloads.items():
            manifest_updated, manifest_sha, _ = self._upsert_managed_repo_file(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                path=manifest_path,
                content=manifest_content,
                marker=_MBSRN_MANAGED_MANIFEST_MARKER,
                commit_message=f"chore(migration): provision managed k8s manifest {manifest_path}",
                dry_run=dry_run,
            )
            any_file_updated = any_file_updated or manifest_updated
            file_sha_by_path[manifest_path] = manifest_sha
            if manifest_sha:
                commit_sha = manifest_sha
        for runtime_path, runtime_content in runtime_file_payloads.items():
            runtime_updated, runtime_sha, _ = self._upsert_managed_repo_file(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                path=runtime_path,
                content=runtime_content,
                marker=_MBSRN_MANAGED_MANIFEST_MARKER,
                commit_message=f"chore(migration): provision managed runtime file {runtime_path}",
                dry_run=dry_run,
            )
            any_file_updated = any_file_updated or runtime_updated
            file_sha_by_path[runtime_path] = runtime_sha
            if runtime_sha:
                commit_sha = runtime_sha

        verified_workflow_sha = file_sha_by_path.get(workflow_path)
        namespace_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_NAMESPACE_FILE_PATH)
        deployment_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_DEPLOYMENT_FILE_PATH)
        service_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_SERVICE_FILE_PATH)
        ingress_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_INGRESS_FILE_PATH)
        resource_quota_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH)
        limit_range_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH)
        network_policy_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH)
        runtime_dockerfile_sha = file_sha_by_path.get(_MBSRN_MANAGED_SITE_RUNTIME_DOCKERFILE_PATH)
        expected_manifest_shas = [file_sha_by_path.get(path) for path in expected_managed_manifest_paths]
        workflow_verify_payload = self._fetch_existing_file_payload(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=workflow_path,
        )
        workflow_verify_trigger_types = _extract_workflow_trigger_types(workflow_verify_payload)
        workflow_verify_conformance = _evaluate_workflow_conformance(
            workflow_file_payload=workflow_verify_payload,
            workflow_trigger_types=workflow_verify_trigger_types,
        )
        managed_namespace_policies_aligned = (
            True
            if (
                not policy_expectations.get("resource_quota_expected")
                and not policy_expectations.get("limit_range_expected")
                and not policy_expectations.get("network_policy_expected")
            )
            else all(
                bool(file_sha_by_path.get(path))
                for path, expected in (
                    (_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH, policy_expectations.get("resource_quota_expected")),
                    (_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH, policy_expectations.get("limit_range_expected")),
                    (_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH, policy_expectations.get("network_policy_expected")),
                )
                if expected
            )
        )
        namespace_model_status = (
            _NAMESPACE_MODEL_STATUS_ALIGNED
            if (
                verified_workflow_sha
                and all(bool(item) for item in expected_manifest_shas)
                and bool(runtime_dockerfile_sha)
            )
            else _NAMESPACE_MODEL_STATUS_UNKNOWN
        )
        if dry_run:
            return SEOMigrationGitHubWorkflowProvisionResult(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                workflow_id=normalized_workflow_id,
                workflow_path=workflow_path,
                provisioned=False,
                commit_sha=commit_sha or verified_workflow_sha,
                deploy_workflow_mode=normalized_workflow_mode,
                target_environment_key=normalized_target_environment_key,
                target_environment_source=normalized_target_environment_source,
                kubernetes_namespace=derived_namespace,
                namespace_source=namespace_source,
                preview_hostname=preview_hostname,
                managed_manifest_paths=managed_manifest_paths,
                namespace_model_status=namespace_model_status,
                managed_resource_quota_expected=bool(policy_expectations.get("resource_quota_expected")),
                managed_resource_quota_present=(
                    bool(resource_quota_manifest_sha) if policy_expectations.get("resource_quota_expected") else None
                ),
                managed_limit_range_expected=bool(policy_expectations.get("limit_range_expected")),
                managed_limit_range_present=(
                    bool(limit_range_manifest_sha) if policy_expectations.get("limit_range_expected") else None
                ),
                managed_network_policy_expected=bool(policy_expectations.get("network_policy_expected")),
                managed_network_policy_present=(
                    bool(network_policy_manifest_sha) if policy_expectations.get("network_policy_expected") else None
                ),
                managed_namespace_policies_aligned=managed_namespace_policies_aligned,
                managed_workflow_outcome=workflow_managed_outcome,
            )
        if (
            not verified_workflow_sha
            or not namespace_manifest_sha
            or not deployment_manifest_sha
            or not service_manifest_sha
            or not ingress_manifest_sha
            or not runtime_dockerfile_sha
            or not all(bool(item) for item in expected_manifest_shas)
            or (workflow_updated and not workflow_verify_conformance.is_conformant)
        ):
            raise SEOMigrationGitHubPublisherError(
                code="workflow_provisioning_failed",
                safe_message="Deploy workflow provisioning could not be verified.",
                stage="workflow_provisioning",
            )
        return SEOMigrationGitHubWorkflowProvisionResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            workflow_id=normalized_workflow_id,
            workflow_path=workflow_path,
            provisioned=any_file_updated,
            commit_sha=commit_sha or verified_workflow_sha,
            deploy_workflow_mode=normalized_workflow_mode,
            target_environment_key=normalized_target_environment_key,
            target_environment_source=normalized_target_environment_source,
            kubernetes_namespace=derived_namespace,
            namespace_source=namespace_source,
            preview_hostname=preview_hostname,
            managed_manifest_paths=managed_manifest_paths,
            namespace_model_status=namespace_model_status,
            managed_resource_quota_expected=bool(policy_expectations.get("resource_quota_expected")),
            managed_resource_quota_present=(
                bool(resource_quota_manifest_sha) if policy_expectations.get("resource_quota_expected") else None
            ),
            managed_limit_range_expected=bool(policy_expectations.get("limit_range_expected")),
            managed_limit_range_present=(
                bool(limit_range_manifest_sha) if policy_expectations.get("limit_range_expected") else None
            ),
            managed_network_policy_expected=bool(policy_expectations.get("network_policy_expected")),
            managed_network_policy_present=(
                bool(network_policy_manifest_sha) if policy_expectations.get("network_policy_expected") else None
            ),
            managed_namespace_policies_aligned=managed_namespace_policies_aligned,
            managed_workflow_outcome=workflow_managed_outcome,
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
        workflow_path = _workflow_repo_path(target.workflow_id)
        self._ensure_repo_exists(repo_owner=target.repo_owner, repo_name=target.repo_name)
        ref_ensure_result = self._ensure_ref_exists(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            ref=target.ref,
            allow_repair=allow_ref_repair and (not dry_run),
            dry_run=dry_run,
            remediation_mode=remediation_mode,
            workflow_path=workflow_path,
        )
        if not ref_ensure_result.ref_exists:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                safe_message="GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                stage="ref_lookup",
            )
        workflow_file_payload = self._fetch_workflow_file_payload_on_ref(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            ref=target.ref,
            workflow_path=workflow_path,
        )
        workflow_exists = isinstance(workflow_file_payload, dict)
        if (not workflow_exists) and allow_workflow_repair and (not dry_run):
            self.ensure_deploy_workflow(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                branch=target.ref,
                workflow_id=target.workflow_id,
                dry_run=False,
                managed_image_pull_secret_config=managed_image_pull_secret_config,
            )
            workflow_file_payload = self._fetch_workflow_file_payload_on_ref(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                ref=target.ref,
                workflow_path=workflow_path,
            )
            workflow_exists = isinstance(workflow_file_payload, dict)
        if not workflow_exists:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_found",
                safe_message="GitHub workflow target was not found.",
                stage="workflow_lookup",
            )
        (
            workflow_dispatch_ready,
            workflow_trigger_types,
            workflow_conformance,
        ) = self._ensure_workflow_dispatch_ready_for_target(
            target=target,
            workflow_file_payload=workflow_file_payload,
        )
        workflow_management_classification = _classify_workflow_management_state(
            file_payload=workflow_file_payload,
            workflow_id=target.workflow_id,
            marker=_MBSRN_MANAGED_WORKFLOW_MARKER,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_deploy_workflow_readiness_source",
                "repo_owner": target.repo_owner,
                "repo_name": target.repo_name,
                "requested_ref": target.ref,
                "workflow_id": target.workflow_id,
                "workflow_path": workflow_path,
                "workflow_management_classification": workflow_management_classification,
                "workflow_conformance_status": workflow_conformance.conformance_status,
                "workflow_conformance_reasons": list(workflow_conformance.conformance_reasons),
            },
            fallback_message="seo_migration_deploy_workflow_readiness_source",
            level=logging.INFO,
        )
        normalized_namespace_isolation_defaults = _normalize_namespace_isolation_defaults(namespace_isolation_defaults)
        policy_expectations = _managed_policy_expectations(normalized_namespace_isolation_defaults)
        expected_manifest_paths = _expected_managed_manifest_paths(normalized_namespace_isolation_defaults)
        derived_namespace, namespace_source = derive_site_kubernetes_namespace(
            repo_name=target.repo_name,
            site_id=None,
        )
        preview_hostname, _ = derive_site_preview_hostname(
            repo_name=target.repo_name,
            site_id=None,
        )
        preview_certificate_name, _ = derive_site_preview_certificate_name(
            repo_name=target.repo_name,
            site_id=None,
        )
        preview_endpoint = resolve_managed_preview_endpoint_configuration(
            repo_name=target.repo_name,
            site_id=None,
            preview_hostname=preview_hostname,
            namespace_isolation_defaults=normalized_namespace_isolation_defaults,
        )
        preview_static_ip_name = _coerce_string(preview_endpoint.get("expected_static_ip_name"))
        preview_endpoint_reason_code = _coerce_string(preview_endpoint.get("reason_code"))
        uses_shared_preview_gateway = bool(preview_endpoint.get("uses_shared_preview_gateway"))
        ingress_static_ip_conflict_reason_code = (
            _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_STATIC_IP_CONFLICT
            if uses_shared_preview_gateway
            else _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_STATIC_IP_NOT_ALLOWED
        )
        workflow_content = _decode_workflow_file_content(workflow_file_payload) or ""
        deploy_auth_mode = _derive_managed_workflow_deploy_auth_mode(workflow_content=workflow_content)
        target_repo_deploy_secret_required = _managed_workflow_requires_target_repo_deploy_secret(
            deploy_auth_mode=deploy_auth_mode
        )
        target_repo_deploy_secret_name = (
            _MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME if target_repo_deploy_secret_required else None
        )
        target_repo_deploy_secret_present: bool | None = None
        expected_workflow_signature = _extract_managed_workflow_signature(workflow_yaml=workflow_content)
        observed_workflow_signature = _compute_managed_workflow_signature(workflow_yaml=workflow_content)
        workflow_integrity_status = _DEPLOY_WORKFLOW_INTEGRITY_STATUS_MISSING
        workflow_integrity_reason_code: str | None = _DEPLOY_WORKFLOW_INTEGRITY_REASON_SIGNATURE_MISSING
        if expected_workflow_signature:
            if expected_workflow_signature == observed_workflow_signature:
                workflow_integrity_status = _DEPLOY_WORKFLOW_INTEGRITY_STATUS_MATCH
                workflow_integrity_reason_code = None
            else:
                workflow_integrity_status = _DEPLOY_WORKFLOW_INTEGRITY_STATUS_MISMATCH
                workflow_integrity_reason_code = _DEPLOY_WORKFLOW_INTEGRITY_REASON_SIGNATURE_MISMATCH
        site_id_for_signature_log = (
            _normalize_repo_management_id(target.inputs.get("site_id")) if isinstance(target.inputs, dict) else None
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_managed_workflow_signature_validation",
                "repo_owner": target.repo_owner,
                "repo_name": target.repo_name,
                "requested_ref": target.ref,
                "workflow_id": target.workflow_id,
                "workflow_path": workflow_path,
                "site_id": site_id_for_signature_log,
                "integrity_status": workflow_integrity_status,
                "reason_code": workflow_integrity_reason_code,
                "expected_signature": _truncate_workflow_signature_for_log(expected_workflow_signature),
                "observed_signature": _truncate_workflow_signature_for_log(observed_workflow_signature),
            },
            fallback_message="seo_migration_managed_workflow_signature_validation",
            level=(
                logging.WARNING
                if workflow_integrity_status == _DEPLOY_WORKFLOW_INTEGRITY_STATUS_MISMATCH
                else logging.INFO
            ),
        )
        managed_workflow = _MBSRN_MANAGED_WORKFLOW_MARKER in workflow_content.lower()
        workflow_namespace_aligned: bool | None = None
        manifest_namespace_aligned: bool | None = None
        certificate_domain_aligned: bool | None = None
        certificate_domain_mismatch: bool | None = None
        stale_managed_certificate_present: bool | None = None
        ingress_certificate_mismatch: bool | None = None
        ingress_static_ip_conflict: bool | None = None
        stale_pre_shared_cert_binding_detected: bool | None = None
        content_identity_mismatch: bool | None = None
        image_pull_secret_referenced: bool | None = None
        image_pull_secret_reason_code: str | None = None
        image_pull_secret_missing_fields: list[str] = []
        image_pull_secret_presence: dict[str, bool] = {}
        image_pull_secret_details: dict[str, object] = {}
        image_pull_secret_required = _managed_image_pull_secret_required(managed_image_pull_secret_config)
        namespace_model_status = _NAMESPACE_MODEL_STATUS_UNKNOWN
        certificate_alignment_details: dict[str, object] = {}
        dns_record_matches_ingress: bool | None = None
        dns_expected_ip: str | None = None
        dns_observed_ip: str | None = None
        tls_certificate_status: str | None = None
        tls_domain_status: str | None = None
        ingress_ip: str | None = None
        ingress_conflict_detected: bool | None = None
        cert_identity_valid: bool | None = None
        deploy_https_ready: bool | None = None
        manifest_presence_by_path: dict[str, bool] = {}
        manifest_content_by_path: dict[str, str | None] = {}
        if managed_workflow:
            workflow_namespace_aligned = _workflow_content_matches_namespace(
                workflow_content=workflow_content,
                kubernetes_namespace=derived_namespace,
            )
            (
                manifest_namespace_aligned,
                _,
                manifest_presence_by_path,
                manifest_content_by_path,
            ) = self._evaluate_manifest_namespace_alignment(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                ref=target.ref,
                kubernetes_namespace=derived_namespace,
                manifest_paths=expected_manifest_paths,
            )
            (
                certificate_domain_aligned,
                certificate_alignment_details,
            ) = _evaluate_preview_certificate_alignment(
                ingress_manifest_content=manifest_content_by_path.get(_MBSRN_MANAGED_INGRESS_FILE_PATH),
                managed_certificate_manifest_content=manifest_content_by_path.get(_MBSRN_MANAGED_CERTIFICATE_FILE_PATH),
                expected_preview_hostname=preview_hostname,
                expected_certificate_name=preview_certificate_name,
                expected_static_ip_name=preview_static_ip_name,
            )
            stale_managed_certificate_present = bool(
                certificate_alignment_details.get("stale_managed_certificate_present")
            )
            ingress_certificate_mismatch = bool(certificate_alignment_details.get("ingress_certificate_mismatch"))
            certificate_domain_mismatch = bool(certificate_alignment_details.get("certificate_domain_mismatch"))
            ingress_static_ip_conflict = bool(certificate_alignment_details.get("ingress_static_ip_conflict"))
            stale_pre_shared_cert_binding_detected = bool(
                certificate_alignment_details.get("stale_pre_shared_cert_binding_detected")
            )
            managed_resource_quota_present = (
                bool(manifest_presence_by_path.get(_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH))
                if policy_expectations.get("resource_quota_expected")
                else None
            )
            managed_limit_range_present = (
                bool(manifest_presence_by_path.get(_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH))
                if policy_expectations.get("limit_range_expected")
                else None
            )
            managed_network_policy_present = (
                bool(manifest_presence_by_path.get(_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH))
                if policy_expectations.get("network_policy_expected")
                else None
            )
            managed_namespace_policies_aligned = (
                True
                if (
                    not policy_expectations.get("resource_quota_expected")
                    and not policy_expectations.get("limit_range_expected")
                    and not policy_expectations.get("network_policy_expected")
                )
                else all(
                    bool(manifest_namespace_aligned) and bool(manifest_presence_by_path.get(path))
                    for path, expected in (
                        (_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH, policy_expectations.get("resource_quota_expected")),
                        (_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH, policy_expectations.get("limit_range_expected")),
                        (_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH, policy_expectations.get("network_policy_expected")),
                    )
                    if expected
                )
            )
            namespace_model_status = (
                _NAMESPACE_MODEL_STATUS_ALIGNED
                if workflow_namespace_aligned and manifest_namespace_aligned and bool(certificate_domain_aligned)
                else _NAMESPACE_MODEL_STATUS_MISALIGNED
            )
        else:
            managed_resource_quota_present = None
            managed_limit_range_present = None
            managed_network_policy_present = None
            managed_namespace_policies_aligned = None
            certificate_domain_mismatch = None
            stale_managed_certificate_present = None
            ingress_certificate_mismatch = None
            ingress_static_ip_conflict = None
            stale_pre_shared_cert_binding_detected = None
        dispatch_service_availability = True
        dispatch_service_reason_code = "available"
        gke_config_missing_reason_codes: list[str] = []
        gke_config_presence: dict[str, bool] = {}
        gke_config_reason_code: str | None = None
        gke_config_details: dict[str, object] = {
            "managed_preview_endpoint_requested_mode": _coerce_string(preview_endpoint.get("requested_mode")),
            "managed_preview_endpoint_effective_mode": _coerce_string(preview_endpoint.get("effective_mode")),
            "uses_shared_preview_gateway": uses_shared_preview_gateway,
            "requires_dedicated_static_ip": bool(preview_endpoint.get("requires_dedicated_static_ip")),
            "shared_preview_static_ip_name": _coerce_string(preview_endpoint.get("shared_preview_static_ip_name")),
            "expected_preview_static_ip_name": preview_static_ip_name,
            "expected_preview_static_ip_name_source": _coerce_string(
                preview_endpoint.get("expected_static_ip_name_source")
            ),
        }
        if managed_workflow:
            (
                gke_config_reason_code,
                gke_config_missing_reason_codes,
                gke_config_presence,
                resolved_gke_config_details,
            ) = self._validate_managed_gke_environment_config(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                managed_gke_config=managed_gke_config,
            )
            gke_config_details = {
                **gke_config_details,
                **(resolved_gke_config_details if isinstance(resolved_gke_config_details, dict) else {}),
            }
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_deploy_gke_environment_config",
                    "repo_owner": target.repo_owner,
                    "repo_name": target.repo_name,
                    "requested_ref": target.ref,
                    "workflow_id": target.workflow_id,
                    "workflow_path": workflow_path,
                    "gke_config_reason_code": gke_config_reason_code,
                    "gke_config_missing_reason_codes": gke_config_missing_reason_codes,
                    **gke_config_details,
                    **gke_config_presence,
                },
                fallback_message="seo_migration_deploy_gke_environment_config",
                level=logging.INFO,
            )
            deployment_manifest_content = manifest_content_by_path.get(_MBSRN_MANAGED_DEPLOYMENT_FILE_PATH)
            deployment_image_reference = _extract_deployment_image_reference(
                deployment_manifest_content=deployment_manifest_content
            )
            deployment_image_repository, deployment_image_tag = _container_image_identity(deployment_image_reference)
            expected_image_repository = _derive_site_runtime_image_repository(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
            ).lower()
            legacy_generic_image_detected = _is_legacy_generic_site_runtime_image_repository(
                image_repository=deployment_image_repository,
                repo_owner=target.repo_owner,
            )
            content_identity_mismatch = bool(
                deployment_image_repository
                and expected_image_repository
                and deployment_image_repository != expected_image_repository
            )
            image_pull_secret_referenced = _deployment_references_image_pull_secret(
                deployment_manifest_content=deployment_manifest_content,
                image_pull_secret_name=_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
            )
            image_pull_secret_details = {
                "image_pull_secret_name": _MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
                "image_pull_secret_referenced": image_pull_secret_referenced,
                "image_pull_secret_required": image_pull_secret_required,
                "image_pull_auth_mode": "private" if image_pull_secret_required else "public",
                "site_runtime_image_repository_expected": expected_image_repository,
                "site_runtime_image_repository_observed": deployment_image_repository,
                "site_runtime_image_tag_observed": deployment_image_tag,
                "site_runtime_image_reference_observed": deployment_image_reference,
                "site_runtime_image_legacy_generic_detected": legacy_generic_image_detected,
                "site_runtime_image_expected_repository_matched": bool(
                    deployment_image_repository
                    and expected_image_repository
                    and deployment_image_repository == expected_image_repository
                ),
                "site_runtime_content_source": "site_repo_build",
            }
        if managed_workflow and namespace_model_status == _NAMESPACE_MODEL_STATUS_MISALIGNED:
            dispatch_service_availability = False
            dispatch_service_reason_code = "target_configuration_invalid"
        if managed_workflow and preview_endpoint_reason_code:
            dispatch_service_availability = False
            dispatch_service_reason_code = preview_endpoint_reason_code
        if managed_workflow and certificate_domain_mismatch is True:
            dispatch_service_availability = False
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_BOUND_TO_WRONG_SITE
        elif managed_workflow and stale_managed_certificate_present is True:
            dispatch_service_availability = False
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_IDENTITY_MISMATCH
        elif managed_workflow and ingress_certificate_mismatch is True:
            dispatch_service_availability = False
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_CERTIFICATE_ANNOTATION_MISMATCH
        elif managed_workflow and ingress_static_ip_conflict is True:
            dispatch_service_availability = False
            dispatch_service_reason_code = ingress_static_ip_conflict_reason_code
        elif managed_workflow and stale_pre_shared_cert_binding_detected is True:
            dispatch_service_availability = False
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_STALE_PRE_SHARED_CERT_BINDING
        elif managed_workflow and content_identity_mismatch is True:
            dispatch_service_availability = False
            dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_DEPLOYED_CONTENT_IDENTITY_MISMATCH
        if managed_workflow and gke_config_reason_code is not None:
            dispatch_service_availability = False
            dispatch_service_reason_code = gke_config_reason_code
        if managed_workflow and dispatch_service_availability and target_repo_deploy_secret_required:
            target_repo_deploy_secret_present = self._actions_secret_present(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                secret_name=_MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME,
            )
            if not target_repo_deploy_secret_present:
                dispatch_service_availability = False
                dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_REPO_DEPLOY_SECRET_MISSING
        if managed_workflow and dispatch_service_availability:
            if isinstance(managed_image_pull_secret_config, dict):
                (
                    image_pull_secret_reason_code,
                    image_pull_secret_missing_fields,
                    image_pull_secret_presence,
                    image_pull_secret_validation_details,
                ) = self._validate_managed_image_pull_secret_config(
                    managed_image_pull_secret_config=managed_image_pull_secret_config,
                )
                image_pull_secret_details = {
                    **image_pull_secret_details,
                    **image_pull_secret_validation_details,
                }
                _emit_structured_publisher_log(
                    payload={
                        "event": "seo_migration_deploy_image_pull_secret_config",
                        "repo_owner": target.repo_owner,
                        "repo_name": target.repo_name,
                        "requested_ref": target.ref,
                        "workflow_id": target.workflow_id,
                        "workflow_path": workflow_path,
                        "image_pull_secret_reason_code": image_pull_secret_reason_code,
                        "image_pull_secret_missing_fields": list(image_pull_secret_missing_fields),
                        **image_pull_secret_presence,
                        **image_pull_secret_details,
                    },
                    fallback_message="seo_migration_deploy_image_pull_secret_config",
                    level=logging.INFO,
                )
                if image_pull_secret_reason_code is not None:
                    dispatch_service_availability = False
                    dispatch_service_reason_code = image_pull_secret_reason_code
            else:
                image_pull_secret_details = {
                    **image_pull_secret_details,
                    "image_pull_secret_config_source": "unspecified",
                    "image_pull_secret_config_reason_code": None,
                    "image_pull_secret_configured": None,
                    "image_pull_secret_required": image_pull_secret_required,
                    "image_pull_auth_mode": "private" if image_pull_secret_required else "public",
                    "private_image_auth_required": image_pull_secret_required,
                    "private_image_credentials_available_in_control_plane": None,
                    "target_repo_secrets_not_required": True,
                    "image_pull_secret_not_provisioned": bool(image_pull_secret_required),
                    "image_pull_secret_provisioning_unavailable": bool(image_pull_secret_required),
                }
            if image_pull_secret_required and image_pull_secret_referenced is False:
                dispatch_service_availability = False
                dispatch_service_reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_IMAGE_PULL_SECRET_NOT_REFERENCED
        if managed_workflow and certificate_alignment_details:
            gke_config_details = {
                **gke_config_details,
                **certificate_alignment_details,
                "expected_preview_certificate_name": preview_certificate_name,
                "expected_preview_hostname": preview_hostname,
                "expected_preview_static_ip_name": preview_static_ip_name,
            }
            ingress_conflict_detected = bool(certificate_alignment_details.get("ingress_static_ip_conflict"))
            cert_identity_valid = bool(
                (certificate_domain_aligned is True)
                and (not bool(stale_managed_certificate_present))
                and (not bool(ingress_certificate_mismatch))
            )
            tls_domain_status = (
                "active"
                if cert_identity_valid is True
                else ("mismatched" if certificate_domain_mismatch is True else None)
            )
            gke_config_details = {
                **gke_config_details,
                "dns_record_matches_ingress": dns_record_matches_ingress,
                "dns_expected_ip": dns_expected_ip,
                "dns_observed_ip": dns_observed_ip,
                "tls_certificate_status": tls_certificate_status,
                "tls_domain_status": tls_domain_status,
                "ingress_ip": ingress_ip,
                "ingress_conflict_detected": ingress_conflict_detected,
                "cert_identity_valid": cert_identity_valid,
                "deploy_https_ready": deploy_https_ready,
            }
        if managed_workflow and image_pull_secret_details:
            gke_config_details = {
                **gke_config_details,
                **image_pull_secret_details,
                **image_pull_secret_presence,
            }
        gke_config_details = {
            **gke_config_details,
            "workflow_integrity_status": workflow_integrity_status,
            "workflow_integrity_reason_code": workflow_integrity_reason_code,
            "deploy_auth_mode": deploy_auth_mode,
            "target_repo_deploy_secret_required": target_repo_deploy_secret_required,
            "target_repo_deploy_secret_name": target_repo_deploy_secret_name,
            "target_repo_deploy_secret_present": target_repo_deploy_secret_present,
        }
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
            workflow_dispatch_ready=bool(workflow_dispatch_ready),
            workflow_dispatch_supported=True,
            workflow_trigger_types=workflow_trigger_types,
            dispatch_service_availability=dispatch_service_availability,
            dispatch_service_reason_code=dispatch_service_reason_code,
            dispatch_identifier_type=_workflow_dispatch_identifier_type(target.workflow_id),
            remediation_mode=remediation_mode.strip() or "none",
            workflow_conformance_checked=True,
            workflow_conformance_status=workflow_conformance.conformance_status,
            workflow_conformance_reasons=workflow_conformance.conformance_reasons,
            workflow_conformance_evidence_summary=workflow_conformance.evidence_summary,
            kubernetes_namespace=derived_namespace,
            namespace_source=namespace_source,
            preview_hostname=preview_hostname,
            workflow_namespace_aligned=workflow_namespace_aligned if managed_workflow else None,
            manifest_namespace_aligned=manifest_namespace_aligned if managed_workflow else None,
            namespace_model_status=namespace_model_status,
            managed_resource_quota_expected=bool(policy_expectations.get("resource_quota_expected")),
            managed_resource_quota_present=managed_resource_quota_present,
            managed_limit_range_expected=bool(policy_expectations.get("limit_range_expected")),
            managed_limit_range_present=managed_limit_range_present,
            managed_network_policy_expected=bool(policy_expectations.get("network_policy_expected")),
            managed_network_policy_present=managed_network_policy_present,
            managed_namespace_policies_aligned=managed_namespace_policies_aligned,
            dns_record_matches_ingress=dns_record_matches_ingress,
            dns_expected_ip=dns_expected_ip,
            dns_observed_ip=dns_observed_ip,
            tls_certificate_status=tls_certificate_status,
            tls_domain_status=tls_domain_status,
            ingress_ip=ingress_ip,
            ingress_conflict_detected=ingress_conflict_detected,
            cert_identity_valid=cert_identity_valid,
            deploy_https_ready=deploy_https_ready,
            workflow_integrity_status=workflow_integrity_status,
            workflow_integrity_reason_code=workflow_integrity_reason_code,
            managed_gke_config_details=(gke_config_details or None),
        )

    def _fetch_existing_sha(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        path: str,
    ) -> str | None:
        response_payload = self._fetch_existing_file_payload(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=path,
        )
        if not isinstance(response_payload, dict):
            return None
        sha = str(response_payload.get("sha") or "").strip()
        return sha or None

    def _fetch_existing_file_payload(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        path: str,
    ) -> dict[str, object] | None:
        try:
            response_payload = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                    f"/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}"
                ),
                expected_statuses=(200,),
                allow_404=True,
                error_stage="workflow_provisioning",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code == "github_request_failed":
                raise self._classify_workflow_provisioning_request_failed(exc=exc) from exc
            raise
        if isinstance(response_payload, dict):
            return response_payload
        return None

    def _reconcile_managed_repo_baseline_files(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        business_id: str | None,
        site_id: str | None,
        dry_run: bool,
    ) -> dict[str, bool]:
        normalized_business_id = _normalize_repo_management_id(business_id)
        normalized_site_id = _normalize_repo_management_id(site_id)
        if not normalized_business_id or not normalized_site_id:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_BASELINE_RECONCILIATION_FAILED,
                safe_message="Managed repository baseline reconciliation requires business/site ownership metadata.",
                stage="publish",
            )
        baseline_files = _render_repo_baseline_files(
            repo_owner=repo_owner,
            repo_name=repo_name,
            business_id=normalized_business_id,
            site_id=normalized_site_id,
        )
        presence_by_path: dict[str, bool] = {}
        for baseline_path in _MBSRN_MANAGED_REPO_BASELINE_RECONCILE_PATHS:
            presence_by_path[baseline_path] = self._repo_file_exists_on_ref(
                repo_owner=repo_owner,
                repo_name=repo_name,
                ref=branch,
                path=baseline_path,
                error_stage="publish",
            )
        missing_paths = [
            path for path in _MBSRN_MANAGED_REPO_BASELINE_RECONCILE_PATHS if not presence_by_path.get(path)
        ]
        reconciled = False
        for missing_path in missing_paths:
            self._upsert_repo_file_if_missing(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                path=missing_path,
                content=str(baseline_files.get(missing_path) or ""),
                commit_message=f"chore(migration): add managed baseline file {missing_path}",
                dry_run=dry_run,
            )
            if not dry_run:
                reconciled = True
            presence_by_path[missing_path] = True
        return {
            "repo_baseline_required": bool(missing_paths),
            "repo_baseline_reconciled": bool(reconciled),
            "readme_present": bool(presence_by_path.get(_MBSRN_MANAGED_REPO_BASELINE_README_PATH)),
            "gitignore_present": bool(presence_by_path.get(_MBSRN_MANAGED_REPO_BASELINE_GITIGNORE_PATH)),
            "license_present": bool(presence_by_path.get(_MBSRN_MANAGED_REPO_BASELINE_LICENSE_PATH)),
        }

    def _upsert_repo_file_if_missing(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        path: str,
        content: str,
        commit_message: str,
        dry_run: bool,
    ) -> None:
        existing_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
            status_error_map={
                401: (
                    _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                    "GitHub token is not authorized to read repository contents for publish.",
                ),
                403: (
                    _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                    "GitHub token is not authorized to read repository contents for publish.",
                ),
                409: (
                    _GITHUB_REASON_BRANCH_UNINITIALIZED,
                    "GitHub repository branch is missing or uninitialized for managed publish.",
                ),
                422: (
                    _GITHUB_REASON_BRANCH_UNINITIALIZED,
                    "GitHub repository branch is missing or uninitialized for managed publish.",
                ),
            },
            error_stage="publish",
        )
        existing_sha = (
            _coerce_string((existing_payload or {}).get("sha")) if isinstance(existing_payload, dict) else None
        )
        if existing_sha:
            return
        if dry_run:
            return
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        payload: dict[str, object] = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch,
            "committer": {
                "name": self.committer_name,
                "email": self.committer_email,
            },
        }
        try:
            _ = self._request_json(
                method="PUT",
                path=(
                    f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                    f"/contents/{urllib.parse.quote(path, safe='/')}"
                ),
                payload=payload,
                status_error_map={
                    401: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for publish.",
                    ),
                    403: (
                        _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for publish.",
                    ),
                },
                error_stage="publish",
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code == "github_request_failed":
                classified = self._classify_publish_request_failed(exc=exc)
                raise self._classify_repo_baseline_reconciliation_failure(exc=classified) from exc
            raise self._classify_repo_baseline_reconciliation_failure(exc=exc) from exc

    @staticmethod
    def _classify_repo_baseline_reconciliation_failure(
        *,
        exc: SEOMigrationGitHubPublisherError,
    ) -> SEOMigrationGitHubPublisherError:
        if exc.code in {
            _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
            _GITHUB_REASON_BRANCH_UNINITIALIZED,
            _GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISSING,
            _GITHUB_REASON_REPO_ADOPTION_REQUIRED,
            _GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISMATCH,
            _GITHUB_REASON_REPO_MANAGEMENT_MARKER_INVALID,
        }:
            return exc
        return SEOMigrationGitHubPublisherError(
            code=_GITHUB_REASON_REPO_BASELINE_RECONCILIATION_FAILED,
            safe_message="GitHub managed repository baseline reconciliation failed.",
            status_code=exc.status_code,
            stage=exc.stage or "publish",
            provider_message=exc.provider_message,
        )

    def _is_managed_file_payload(self, *, file_payload: dict[str, object] | None, marker: str) -> bool:
        if not isinstance(file_payload, dict):
            return False
        decoded = _decode_workflow_file_content(file_payload)
        if not decoded:
            return False
        return marker in decoded.lower()

    def _is_managed_placeholder_workflow_payload(
        self,
        *,
        file_payload: dict[str, object] | None,
        workflow_id: str,
    ) -> bool:
        if not isinstance(file_payload, dict):
            return False
        decoded = _decode_workflow_file_content(file_payload)
        if not decoded:
            return False
        return _is_managed_placeholder_workflow_content(
            workflow_content=decoded,
            workflow_id=workflow_id,
        )

    def _upsert_managed_repo_file(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        path: str,
        content: str,
        marker: str,
        commit_message: str,
        dry_run: bool,
        allow_managed_placeholder_upgrade: bool = False,
        workflow_id: str | None = None,
    ) -> tuple[bool, str | None, str | None]:
        existing_payload = self._fetch_existing_file_payload(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=path,
        )
        existing_sha = _coerce_string(existing_payload.get("sha")) if isinstance(existing_payload, dict) else None
        should_write = existing_payload is None
        existing_workflow_classification: str | None = None
        if allow_managed_placeholder_upgrade:
            existing_workflow_classification = _classify_workflow_management_state(
                file_payload=existing_payload,
                workflow_id=_coerce_string(workflow_id) or "",
                marker=marker,
            )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_publish_workflow_file_inspected",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": branch,
                    "workflow_path": path,
                    "workflow_id": _coerce_string(workflow_id),
                    "workflow_management_classification": existing_workflow_classification,
                },
                fallback_message="seo_migration_publish_workflow_file_inspected",
                level=logging.INFO,
            )
        if isinstance(existing_payload, dict) and self._is_managed_file_payload(
            file_payload=existing_payload,
            marker=marker.lower(),
        ):
            existing_decoded = _decode_workflow_file_content(existing_payload) or ""
            should_write = existing_decoded.strip() != content.strip()
        elif (
            allow_managed_placeholder_upgrade
            and isinstance(existing_payload, dict)
            and self._is_managed_placeholder_workflow_payload(
                file_payload=existing_payload,
                workflow_id=_coerce_string(workflow_id) or "",
            )
        ):
            existing_decoded = _decode_workflow_file_content(existing_payload) or ""
            should_write = existing_decoded.strip() != content.strip()

        workflow_outcome: str | None = None
        if allow_managed_placeholder_upgrade:
            workflow_outcome = _derive_managed_workflow_outcome(
                existing_payload=existing_payload,
                classification=existing_workflow_classification,
                should_write=should_write,
            )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_publish_workflow_file_upsert_decision",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": branch,
                    "workflow_path": path,
                    "workflow_id": _coerce_string(workflow_id),
                    "workflow_management_classification": existing_workflow_classification,
                    "workflow_upsert_action": "write" if should_write else "preserve",
                    "managed_workflow_outcome": workflow_outcome,
                },
                fallback_message="seo_migration_publish_workflow_file_upsert_decision",
                level=logging.INFO,
            )

        if not should_write:
            return False, existing_sha, workflow_outcome
        if dry_run:
            return False, existing_sha, workflow_outcome

        encoded_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        payload: dict[str, object] = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch,
            "committer": {
                "name": self.committer_name,
                "email": self.committer_email,
            },
        }
        if existing_sha:
            payload["sha"] = existing_sha
        put_path = (
            f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
            f"/contents/{urllib.parse.quote(path, safe='/')}"
        )
        is_workflow_file = path.lower().startswith(".github/workflows/")
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "file_upsert",
                "operation_status": "started",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": branch,
                "path": path,
                "write_mode": "update" if bool(existing_sha) else "create",
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        try:
            response_payload = self._request_json(
                method="PUT",
                path=put_path,
                payload=payload,
                status_error_map={
                    401: (
                        (
                            _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED
                            if is_workflow_file
                            else _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED
                        ),
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                    403: (
                        (
                            _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED
                            if is_workflow_file
                            else _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED
                        ),
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                },
                error_stage="workflow_provisioning",
            )
        except SEOMigrationGitHubPublisherError as exc:
            provider_message = _sanitize_github_error_message(exc.provider_message)
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "file_upsert",
                    "operation_status": "failed",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": branch,
                    "path": path,
                    "write_mode": "update" if bool(existing_sha) else "create",
                    "http_status_code": exc.status_code,
                    "github_error_code": exc.code,
                    "github_error_message": provider_message,
                    "workflow_file_target": is_workflow_file,
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.WARNING,
            )
            provider_message_lower = (provider_message or "").lower()
            branch_state_markers = (
                "branch",
                "ref",
                "reference",
                "repository is empty",
                "no commit",
                "no default branch",
                "empty repository",
                "uninitialized",
            )
            is_branch_state_error = exc.status_code == 409 or (
                exc.status_code == 422
                and (
                    not provider_message_lower
                    or any(marker in provider_message_lower for marker in branch_state_markers)
                )
            )
            if is_branch_state_error:
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                    safe_message="GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                    status_code=exc.status_code,
                    stage="workflow_provisioning",
                    provider_message=provider_message,
                ) from exc
            mapped_code = exc.code
            if exc.code == "github_request_failed":
                mapped_code = _GITHUB_REASON_WORKFLOW_PROVISIONING_FAILED
            raise SEOMigrationGitHubPublisherError(
                code=mapped_code,
                safe_message=exc.safe_message,
                status_code=exc.status_code,
                stage=exc.stage or "workflow_provisioning",
                provider_message=provider_message,
            ) from exc
        commit_sha: str | None = None
        if isinstance(response_payload, dict):
            commit_payload = response_payload.get("commit")
            if isinstance(commit_payload, dict):
                commit_sha = _coerce_string(commit_payload.get("sha"))
        verified_sha = self._fetch_existing_sha(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=path,
        )
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "file_upsert",
                "operation_status": "succeeded",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": branch,
                "path": path,
                "write_mode": "update" if bool(existing_sha) else "create",
                "workflow_file_target": is_workflow_file,
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        del commit_sha
        return True, verified_sha, workflow_outcome

    def _classify_workflow_provisioning_request_failed(
        self,
        *,
        exc: SEOMigrationGitHubPublisherError,
    ) -> SEOMigrationGitHubPublisherError:
        provider_message = _sanitize_github_error_message(exc.provider_message)
        provider_message_lower = (provider_message or "").lower()
        branch_state_markers = (
            "branch",
            "ref",
            "reference",
            "repository is empty",
            "empty repository",
            "no commit",
            "no default branch",
            "uninitialized",
        )
        if exc.status_code == 409 or (
            exc.status_code == 422
            and (not provider_message_lower or any(marker in provider_message_lower for marker in branch_state_markers))
        ):
            return SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                safe_message="GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                status_code=exc.status_code,
                stage=exc.stage or "workflow_provisioning",
                provider_message=provider_message,
            )
        return SEOMigrationGitHubPublisherError(
            code=_GITHUB_REASON_WORKFLOW_PROVISIONING_FAILED,
            safe_message="GitHub managed workflow provisioning request failed.",
            status_code=exc.status_code,
            stage=exc.stage or "workflow_provisioning",
            provider_message=provider_message,
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        expected_statuses: tuple[int, ...] = (200, 201),
        allow_404: bool = False,
        status_error_map: dict[int, tuple[str, str]] | None = None,
        error_stage: str | None = None,
        expect_object: bool = True,
    ) -> dict[str, object] | list[object] | None:
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MBSRN-MigrationPublisher/1.0",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url=f"{self.api_base_url}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                if status_code not in expected_statuses:
                    raise SEOMigrationGitHubPublisherError(
                        code="github_unexpected_status",
                        safe_message="GitHub operation returned an unexpected status code.",
                        status_code=status_code,
                        stage=error_stage,
                    )
                response_body = response.read().decode("utf-8", errors="replace").strip()
                if not response_body:
                    return None
                parsed = json.loads(response_body)
                if expect_object:
                    if not isinstance(parsed, dict):
                        return None
                    return parsed
                if isinstance(parsed, (dict, list)):
                    return parsed
                return None
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            provider_message = _sanitize_github_error_message(self._extract_http_error_message(exc))
            if allow_404 and status_code == 404:
                return None
            if status_error_map and status_code in status_error_map:
                code, safe_message = status_error_map[status_code]
                raise SEOMigrationGitHubPublisherError(
                    code=code,
                    safe_message=safe_message,
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            if status_code in {401, 403}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_auth_failed",
                    safe_message="GitHub publish/deploy authentication failed.",
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            if status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code="github_target_not_found",
                    safe_message="GitHub repository or workflow target was not found.",
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            if status_code in {408, 429, 500, 502, 503, 504}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_temporal_failure",
                    safe_message="GitHub publish/deploy request failed temporarily.",
                    status_code=status_code,
                    stage=error_stage,
                    provider_message=provider_message,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="GitHub publish/deploy request failed.",
                status_code=status_code,
                stage=error_stage,
                provider_message=provider_message,
            ) from exc
        except json.JSONDecodeError as exc:
            raise SEOMigrationGitHubPublisherError(
                code="github_parse_error",
                safe_message="GitHub response parsing failed.",
                stage=error_stage,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise SEOMigrationGitHubPublisherError(
                code="github_timeout",
                safe_message="GitHub publish/deploy request timed out.",
                stage=error_stage,
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                raise SEOMigrationGitHubPublisherError(
                    code="github_timeout",
                    safe_message="GitHub publish/deploy request timed out.",
                    stage=error_stage,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_network_error",
                safe_message="GitHub publish/deploy network request failed.",
                stage=error_stage,
            ) from exc

    @staticmethod
    def _extract_http_error_message(exc: urllib.error.HTTPError) -> str:
        try:
            payload = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:  # pragma: no cover - defensive
            return ""
        if not payload:
            return ""
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                message = parsed.get("message")
                if isinstance(message, str):
                    return message
        except Exception:  # pragma: no cover - defensive
            pass
        return payload[:300]


def _upsert_namespace_scoped_ghcr_pull_secret(
    *,
    gcp_deploy_key: str,
    project_id: str,
    cluster_location: str,
    cluster_name: str,
    kubernetes_namespace: str,
    git_userid: str,
    git_email: str,
    git_token: str,
    timeout_seconds: int,
) -> str:
    access_token = _resolve_google_access_token_from_service_account_json(
        credentials_json=gcp_deploy_key,
    )
    cluster_payload = _request_google_json(
        method="GET",
        url=(
            "https://container.googleapis.com/v1/projects/"
            f"{urllib.parse.quote(project_id, safe='')}/locations/"
            f"{urllib.parse.quote(cluster_location, safe='')}/clusters/"
            f"{urllib.parse.quote(cluster_name, safe='')}"
        ),
        access_token=access_token,
        timeout_seconds=timeout_seconds,
        error_stage="image_pull_secret_provision",
    )
    if not isinstance(cluster_payload, dict):
        raise SEOMigrationGitHubPublisherError(
            code="image_pull_secret_provisioning_failed",
            safe_message="Managed image pull secret provisioning could not resolve target GKE cluster metadata.",
            stage="image_pull_secret_provision",
        )
    cluster_endpoint = _coerce_string(cluster_payload.get("endpoint"))
    if not cluster_endpoint:
        raise SEOMigrationGitHubPublisherError(
            code="image_pull_secret_provisioning_failed",
            safe_message="Managed image pull secret provisioning could not resolve target GKE cluster endpoint.",
            stage="image_pull_secret_provision",
        )
    master_auth = cluster_payload.get("masterAuth")
    cluster_ca_certificate = ""
    if isinstance(master_auth, dict):
        cluster_ca_certificate = _coerce_string(master_auth.get("clusterCaCertificate"))
    if not cluster_ca_certificate:
        raise SEOMigrationGitHubPublisherError(
            code="image_pull_secret_provisioning_failed",
            safe_message="Managed image pull secret provisioning could not resolve target GKE cluster CA bundle.",
            stage="image_pull_secret_provision",
        )
    try:
        decoded_cluster_ca = base64.b64decode(cluster_ca_certificate.encode("ascii")).decode(
            "utf-8",
            errors="ignore",
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise SEOMigrationGitHubPublisherError(
            code="image_pull_secret_provisioning_failed",
            safe_message="Managed image pull secret provisioning could not decode target GKE cluster CA bundle.",
            stage="image_pull_secret_provision",
        ) from exc
    ssl_context = ssl.create_default_context(cadata=decoded_cluster_ca)

    namespace_path = "/api/v1/namespaces/" f"{urllib.parse.quote(kubernetes_namespace, safe='')}"
    namespace_payload = _request_kubernetes_json(
        method="GET",
        endpoint=cluster_endpoint,
        path=namespace_path,
        access_token=access_token,
        ssl_context=ssl_context,
        timeout_seconds=timeout_seconds,
        allow_404=True,
        error_stage="image_pull_secret_provision",
    )
    if not isinstance(namespace_payload, dict):
        _request_kubernetes_json(
            method="POST",
            endpoint=cluster_endpoint,
            path="/api/v1/namespaces",
            payload={
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": kubernetes_namespace,
                },
            },
            access_token=access_token,
            ssl_context=ssl_context,
            timeout_seconds=timeout_seconds,
            expected_statuses=(200, 201),
            error_stage="image_pull_secret_provision",
        )

    docker_auth = base64.b64encode(f"{git_userid}:{git_token}".encode("utf-8")).decode("ascii")
    docker_config_payload = {
        "auths": {
            "ghcr.io": {
                "username": git_userid,
                "password": git_token,
                "email": git_email,
                "auth": docker_auth,
            }
        }
    }
    encoded_docker_config = base64.b64encode(
        json.dumps(docker_config_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    secret_payload = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": _MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME,
            "namespace": kubernetes_namespace,
        },
        "type": "kubernetes.io/dockerconfigjson",
        "data": {
            ".dockerconfigjson": encoded_docker_config,
        },
    }
    secret_path = (
        "/api/v1/namespaces/"
        f"{urllib.parse.quote(kubernetes_namespace, safe='')}/secrets/"
        f"{urllib.parse.quote(_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME, safe='')}"
    )
    existing_secret_payload = _request_kubernetes_json(
        method="GET",
        endpoint=cluster_endpoint,
        path=secret_path,
        access_token=access_token,
        ssl_context=ssl_context,
        timeout_seconds=timeout_seconds,
        allow_404=True,
        error_stage="image_pull_secret_provision",
    )
    if isinstance(existing_secret_payload, dict):
        existing_metadata = existing_secret_payload.get("metadata")
        existing_resource_version = ""
        if isinstance(existing_metadata, dict):
            existing_resource_version = _coerce_string(existing_metadata.get("resourceVersion"))
        if existing_resource_version:
            secret_payload["metadata"]["resourceVersion"] = existing_resource_version
        _request_kubernetes_json(
            method="PUT",
            endpoint=cluster_endpoint,
            path=secret_path,
            payload=secret_payload,
            access_token=access_token,
            ssl_context=ssl_context,
            timeout_seconds=timeout_seconds,
            expected_statuses=(200,),
            error_stage="image_pull_secret_provision",
        )
        return _normalize_managed_image_pull_secret_action("updated")
    _request_kubernetes_json(
        method="POST",
        endpoint=cluster_endpoint,
        path=("/api/v1/namespaces/" f"{urllib.parse.quote(kubernetes_namespace, safe='')}/secrets"),
        payload=secret_payload,
        access_token=access_token,
        ssl_context=ssl_context,
        timeout_seconds=timeout_seconds,
        expected_statuses=(200, 201),
        error_stage="image_pull_secret_provision",
    )
    return _normalize_managed_image_pull_secret_action("created")


def _ensure_managed_site_global_static_ip(
    *,
    gcp_deploy_key: str | None,
    project_id: str,
    static_ip_name: str,
    timeout_seconds: int,
    labels: dict[str, str] | None = None,
    gcp_credential_source: str | None = None,
    gcp_principal_email: str | None = None,
    gcp_impersonated_service_account_email: str | None = None,
) -> dict[str, object]:
    normalized_project_id = _coerce_string(project_id)
    normalized_static_ip_name = _coerce_string(static_ip_name)
    normalized_labels: dict[str, str] = {}
    if isinstance(labels, dict):
        for raw_key, raw_value in labels.items():
            normalized_key = _coerce_string(raw_key).strip()
            normalized_value = _coerce_string(raw_value).strip()
            if normalized_key and normalized_value:
                normalized_labels[normalized_key] = normalized_value
    if not normalized_project_id or not normalized_static_ip_name:
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING,
            safe_message="Managed site static IP provisioning is missing required project or static IP name.",
            stage="static_ip_provision",
        )
    try:
        access_token = _resolve_google_access_token_for_managed_deploy_operations(
            credentials_json=gcp_deploy_key,
            impersonated_service_account_email=gcp_impersonated_service_account_email,
            missing_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING,
            missing_safe_message=("Managed deploy runtime credential is unavailable for static IP provisioning."),
            invalid_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING,
            invalid_safe_message=("Managed deploy runtime credential is invalid for static IP provisioning."),
            integration_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED,
            integration_safe_message=("Google auth runtime dependency is unavailable for static IP provisioning."),
            stage="static_ip_provision",
        )
    except SEOMigrationGitHubPublisherError as exc:
        raise _classify_managed_site_static_ip_provisioning_error(
            exc=exc,
            operation="credential_resolve",
            gcp_credential_source=gcp_credential_source,
            gcp_principal_email=gcp_principal_email,
            gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
            force_reason_code=(
                exc.code
                if exc.code
                in {
                    _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING,
                    _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID,
                    _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED,
                }
                else None
            ),
        ) from exc
    encoded_project = urllib.parse.quote(normalized_project_id, safe="")
    encoded_static_ip_name = urllib.parse.quote(normalized_static_ip_name, safe="")
    describe_url = (
        "https://compute.googleapis.com/compute/v1/projects/"
        f"{encoded_project}/global/addresses/{encoded_static_ip_name}"
    )
    create_url = "https://compute.googleapis.com/compute/v1/projects/" f"{encoded_project}/global/addresses"
    list_filter = urllib.parse.quote(f"name eq {normalized_static_ip_name}", safe="")
    list_url = (
        "https://compute.googleapis.com/compute/v1/projects/"
        f"{encoded_project}/global/addresses?filter={list_filter}&maxResults=2"
    )
    request_kwargs = {
        "access_token": access_token,
        "timeout_seconds": timeout_seconds,
        "error_stage": "static_ip_provision",
        "code_on_failure": _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED,
        "safe_message_on_failure": "Managed site static IP provisioning request to Google APIs failed.",
        "safe_message_on_timeout": "Managed site static IP provisioning request timed out.",
    }
    describe_max_attempts = 8
    describe_attempts = 0
    list_fallback_attempted = False
    list_fallback_match_count: int | None = None
    list_fallback_address_present: bool | None = None
    list_fallback_failure_code: str | None = None
    list_fallback_response_keys: tuple[str, ...] = ()

    def _coerce_static_ip_address(payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        return _coerce_string(payload.get("address"))

    def _coerce_static_ip_address_from_list_payload(payload: object) -> str | None:
        nonlocal list_fallback_match_count, list_fallback_address_present
        nonlocal list_fallback_failure_code, list_fallback_response_keys
        if not isinstance(payload, dict):
            list_fallback_match_count = 0
            list_fallback_address_present = False
            list_fallback_failure_code = "payload_invalid"
            list_fallback_response_keys = ()
            return None
        list_fallback_response_keys = tuple(
            sorted(
                key
                for key in payload.keys()
                if isinstance(key, str)
            )[:10]
        )
        items = payload.get("items")
        if not isinstance(items, list):
            list_fallback_match_count = 0
            list_fallback_address_present = False
            list_fallback_failure_code = "items_missing"
            return None
        matching_items: list[dict[str, object]] = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            item_name = _coerce_string(item.get("name"))
            if item_name == normalized_static_ip_name:
                matching_items.append(item)
        list_fallback_match_count = len(matching_items)
        matching_addresses = [
            address
            for item in matching_items
            for address in (_coerce_static_ip_address(item),)
            if address
        ]
        list_fallback_address_present = bool(matching_addresses)
        if list_fallback_match_count == 0:
            list_fallback_failure_code = "no_match"
            return None
        if list_fallback_match_count > 1:
            list_fallback_failure_code = "multiple_matches"
            return None
        if not matching_addresses:
            list_fallback_failure_code = "missing_address"
            return None
        list_fallback_failure_code = None
        return matching_addresses[0]

    def _derive_missing_address_diagnostics() -> tuple[str, str]:
        if list_fallback_attempted:
            if list_fallback_failure_code == "no_match":
                return (
                    "address_not_found_after_retry",
                    (
                        "Managed-site static IP ensure could not find a matching global address entry "
                        "after bounded describe retries and list fallback."
                    ),
                )
            if list_fallback_failure_code == "multiple_matches":
                return (
                    "address_ambiguous_after_retry",
                    (
                        "Managed-site static IP ensure found multiple matching global address entries "
                        "after bounded describe retries and list fallback, so dispatch is blocked."
                    ),
                )
            if list_fallback_failure_code == "missing_address":
                return (
                    "address_value_missing_after_retry",
                    (
                        "Managed-site static IP ensure found a matching global address entry but its "
                        "'address' field was empty after bounded describe retries and list fallback."
                    ),
                )
        return (
            "address_missing_after_retry",
            (
                "Managed-site static IP address payload was missing required field 'address' "
                "after bounded describe retries and list fallback."
            ),
        )

    def _raise_static_ip_address_missing(*, operation: str) -> None:
        diagnostics_error_code, diagnostics_error_summary = _derive_missing_address_diagnostics()
        reason_code = (
            _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT
            if list_fallback_match_count > 1
            else _DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_PROVISIONING_PENDING
        )
        error_category = "conflict" if list_fallback_match_count > 1 else "prerequisite_pending"
        raise SEOMigrationGitHubPublisherError(
            code=reason_code,
            safe_message=(
                "Managed-site static IP ensure could not resolve an address value after bounded describe retries."
            ),
            stage="static_ip_provision",
            diagnostics=_normalize_static_ip_error_diagnostics(
                {
                    "static_ip_operation": operation,
                    "static_ip_error_category": error_category,
                    "static_ip_error_code": diagnostics_error_code,
                    "static_ip_error_summary": diagnostics_error_summary,
                    "static_ip_describe_attempts": describe_attempts,
                    "retryable": list_fallback_match_count <= 1,
                    "static_ip_list_fallback_attempted": list_fallback_attempted,
                    "static_ip_list_fallback_match_count": list_fallback_match_count,
                    "static_ip_list_fallback_address_present": list_fallback_address_present,
                    "static_ip_list_fallback_failure_code": list_fallback_failure_code,
                    "static_ip_list_fallback_response_keys": list(list_fallback_response_keys),
                    "gcp_credential_source": gcp_credential_source,
                    "gcp_principal_email": gcp_principal_email,
                    "gcp_impersonated_service_account_email": gcp_impersonated_service_account_email,
                }
            ),
        )

    def _refresh_describe_payload(*, operation: str) -> dict[str, object] | None:
        nonlocal describe_attempts
        try:
            refreshed_payload = _request_google_json(
                method="GET",
                url=describe_url,
                allow_404=True,
                **request_kwargs,
            )
        except SEOMigrationGitHubPublisherError as exc:
            raise _classify_managed_site_static_ip_provisioning_error(
                exc=exc,
                operation=operation,
                gcp_credential_source=gcp_credential_source,
                gcp_principal_email=gcp_principal_email,
                gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
            ) from exc
        describe_attempts += 1
        if isinstance(refreshed_payload, dict):
            return refreshed_payload
        return None

    def _resolve_address_with_describe_retries(
        *,
        operation: str,
        initial_payload: object | None = None,
    ) -> str | None:
        nonlocal describe_attempts
        payload: object | None = initial_payload
        for attempt in range(describe_max_attempts):
            if payload is None:
                payload = _refresh_describe_payload(operation=operation)
            elif attempt == 0 and initial_payload is payload and isinstance(payload, dict):
                # Initial payload bypasses _refresh_describe_payload; count it here for diagnostics.
                describe_attempts += 1
            if isinstance(payload, dict):
                address = _coerce_static_ip_address(payload)
                if address:
                    return address
            if attempt + 1 >= describe_max_attempts:
                break
            payload = None
        return None

    def _resolve_address_with_list_fallback(*, operation: str) -> str | None:
        nonlocal list_fallback_attempted
        list_fallback_attempted = True
        try:
            list_payload = _request_google_json(
                method="GET",
                url=list_url,
                allow_404=True,
                **request_kwargs,
            )
        except SEOMigrationGitHubPublisherError as exc:
            raise _classify_managed_site_static_ip_provisioning_error(
                exc=exc,
                operation=operation,
                gcp_credential_source=gcp_credential_source,
                gcp_principal_email=gcp_principal_email,
                gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
            ) from exc
        return _coerce_static_ip_address_from_list_payload(list_payload)

    try:
        existing_payload = _request_google_json(
            method="GET",
            url=describe_url,
            allow_404=True,
            **request_kwargs,
        )
    except SEOMigrationGitHubPublisherError as exc:
        raise _classify_managed_site_static_ip_provisioning_error(
            exc=exc,
            operation="describe",
            gcp_credential_source=gcp_credential_source,
            gcp_principal_email=gcp_principal_email,
            gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
        ) from exc
    if isinstance(existing_payload, dict):
        existing_address = _resolve_address_with_describe_retries(
            operation="describe",
            initial_payload=existing_payload,
        )
        if not existing_address:
            existing_address = _resolve_address_with_list_fallback(operation="list_after_describe")
        if not existing_address:
            _raise_static_ip_address_missing(operation="describe")
        return {
            "static_ip_address": existing_address,
            "static_ip_created": False,
            "result": "exists",
        }

    try:
        create_payload: dict[str, object] = {
            "name": normalized_static_ip_name,
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
        }
        if normalized_labels:
            create_payload["labels"] = dict(normalized_labels)
        _request_google_json(
            method="POST",
            url=create_url,
            payload=create_payload,
            expected_statuses=(200, 201),
            **request_kwargs,
        )
    except SEOMigrationGitHubPublisherError as exc:
        if exc.status_code == 409:
            try:
                raced_payload = _request_google_json(
                    method="GET",
                    url=describe_url,
                    allow_404=True,
                    **request_kwargs,
                )
            except SEOMigrationGitHubPublisherError as describe_exc:
                raise _classify_managed_site_static_ip_provisioning_error(
                    exc=describe_exc,
                    operation="describe_after_create",
                    gcp_credential_source=gcp_credential_source,
                    gcp_principal_email=gcp_principal_email,
                    gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
                ) from describe_exc
            if isinstance(raced_payload, dict):
                raced_address = _resolve_address_with_describe_retries(
                    operation="describe_after_create",
                    initial_payload=raced_payload,
                )
                if not raced_address:
                    raced_address = _resolve_address_with_list_fallback(operation="list_after_describe")
                if not raced_address:
                    _raise_static_ip_address_missing(operation="describe_after_create")
                return {
                    "static_ip_address": raced_address,
                    "static_ip_created": False,
                    "result": "already_exists_after_race",
                }
            raise _classify_managed_site_static_ip_provisioning_error(
                exc=SEOMigrationGitHubPublisherError(
                    code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED,
                    safe_message=(
                        "Managed site static IP provisioning reported already exists but the address "
                        "could not be confirmed."
                    ),
                    status_code=exc.status_code,
                    stage="static_ip_provision",
                    provider_message=exc.provider_message,
                ),
                operation="describe_after_create",
                gcp_credential_source=gcp_credential_source,
                gcp_principal_email=gcp_principal_email,
                gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
                force_reason_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT,
            ) from exc
        raise _classify_managed_site_static_ip_provisioning_error(
            exc=exc,
            operation="create",
            gcp_credential_source=gcp_credential_source,
            gcp_principal_email=gcp_principal_email,
            gcp_impersonated_service_account_email=gcp_impersonated_service_account_email,
        ) from exc

    created_address = _resolve_address_with_describe_retries(operation="describe_after_create")
    if not created_address:
        created_address = _resolve_address_with_list_fallback(operation="list_after_describe")
    if not created_address:
        _raise_static_ip_address_missing(operation="describe_after_create")
    return {
        "static_ip_address": created_address,
        "static_ip_created": True,
        "result": "created",
    }


def _classify_managed_site_static_ip_provisioning_error(
    *,
    exc: SEOMigrationGitHubPublisherError,
    operation: str,
    gcp_credential_source: str | None = None,
    gcp_principal_email: str | None = None,
    gcp_impersonated_service_account_email: str | None = None,
    force_reason_code: str | None = None,
) -> SEOMigrationGitHubPublisherError:
    normalized_operation = _normalize_static_ip_operation(operation)
    sanitized_provider_message = _sanitize_github_error_message(exc.provider_message)
    provider_message_lower = (sanitized_provider_message or "").lower()
    status_code = exc.status_code

    reason_code = force_reason_code or _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED
    error_category = "provisioning_failed"
    permission_hint: str | None = None

    if force_reason_code is None:
        if _is_static_ip_api_disabled_error(
            status_code=status_code,
            provider_message_lower=provider_message_lower,
        ):
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_API_DISABLED
            error_category = "api_disabled"
        elif _is_static_ip_quota_exceeded_error(
            status_code=status_code,
            provider_message_lower=provider_message_lower,
        ):
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_QUOTA_EXCEEDED
            error_category = "quota_exceeded"
        elif _is_static_ip_project_not_found_error(
            status_code=status_code,
            provider_message_lower=provider_message_lower,
        ):
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROJECT_NOT_FOUND
            error_category = "project_not_found"
        elif _is_static_ip_conflict_error(
            status_code=status_code,
            provider_message_lower=provider_message_lower,
        ):
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT
            error_category = "conflict"
        elif _is_static_ip_permission_denied_error(
            status_code=status_code,
            provider_message_lower=provider_message_lower,
        ):
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PERMISSION_DENIED
            error_category = "permission_denied"
            principal_hint = _normalize_gcp_principal_email(gcp_principal_email)
            if principal_hint:
                permission_hint = (
                    f"Grant required global address permissions to {principal_hint} "
                    "(compute.globalAddresses.get/create)."
                )
            else:
                permission_hint = (
                    "Grant control-plane deploy identity permissions to describe/create global addresses "
                    "(compute.globalAddresses.get/create)."
                )
    elif force_reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID:
        error_category = "impersonation_config_invalid"
    elif force_reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED:
        error_category = "impersonation_permission_denied"
        source_principal_hint = _normalize_gcp_principal_email(gcp_principal_email)
        target_principal_hint = _normalize_gcp_impersonated_service_account_email(
            gcp_impersonated_service_account_email
        )
        if source_principal_hint and target_principal_hint:
            permission_hint = (
                f"Grant roles/iam.serviceAccountTokenCreator to {source_principal_hint} " f"on {target_principal_hint}."
            )
        elif target_principal_hint:
            permission_hint = (
                "Grant roles/iam.serviceAccountTokenCreator to the control-plane principal "
                f"on {target_principal_hint}."
            )
        else:
            permission_hint = (
                "Grant roles/iam.serviceAccountTokenCreator to the control-plane principal "
                "on the configured managed deploy service account."
            )
    elif force_reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT:
        error_category = "conflict"
    elif force_reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_ADDRESS_MISSING_AFTER_RETRY:
        error_category = "address_missing"

    error_summary = (
        _sanitize_static_ip_error_summary(
            provider_message=sanitized_provider_message,
            fallback_message=exc.safe_message,
        )
        or exc.safe_message
    )
    error_code = _derive_static_ip_error_code(
        provider_message_lower=provider_message_lower,
        status_code=status_code,
    )

    diagnostics = _normalize_static_ip_error_diagnostics(
        {
            "static_ip_operation": normalized_operation,
            "static_ip_error_category": error_category,
            "static_ip_error_code": error_code,
            "static_ip_error_summary": error_summary,
            "static_ip_exit_code": None,
            "static_ip_permission_hint": permission_hint,
            "gcp_credential_source": gcp_credential_source,
            "gcp_principal_email": gcp_principal_email,
            "gcp_impersonated_service_account_email": gcp_impersonated_service_account_email,
        }
    )

    return SEOMigrationGitHubPublisherError(
        code=reason_code,
        safe_message=_derive_static_ip_provisioning_safe_message(reason_code=reason_code),
        status_code=status_code,
        stage=exc.stage or "static_ip_provision",
        provider_message=sanitized_provider_message or exc.provider_message,
        diagnostics=diagnostics,
    )


def _is_static_ip_permission_denied_error(*, status_code: int | None, provider_message_lower: str) -> bool:
    if "permission denied" in provider_message_lower or "permission_denied" in provider_message_lower:
        return True
    if "required 'compute.addresses.create'" in provider_message_lower:
        return True
    if "required 'compute.globaladdresses.create'" in provider_message_lower:
        return True
    if status_code == 403:
        return True
    return False


def _is_static_ip_api_disabled_error(*, status_code: int | None, provider_message_lower: str) -> bool:
    if "compute engine api has not been used" in provider_message_lower:
        return True
    if "api not enabled" in provider_message_lower:
        return True
    if "service_disabled" in provider_message_lower:
        return True
    if status_code == 403 and "has not been used in project" in provider_message_lower:
        return True
    return False


def _is_static_ip_quota_exceeded_error(*, status_code: int | None, provider_message_lower: str) -> bool:
    if "quota_exceeded" in provider_message_lower:
        return True
    if "resource exhausted" in provider_message_lower or "resource_exhausted" in provider_message_lower:
        return True
    if "quota" in provider_message_lower and status_code in {403, 429}:
        return True
    return False


def _is_static_ip_project_not_found_error(*, status_code: int | None, provider_message_lower: str) -> bool:
    if "project not found" in provider_message_lower:
        return True
    if "invalid project" in provider_message_lower:
        return True
    if "not found for project" in provider_message_lower:
        return True
    if status_code == 404 and "project" in provider_message_lower:
        return True
    return False


def _is_static_ip_conflict_error(*, status_code: int | None, provider_message_lower: str) -> bool:
    if status_code == 409:
        return True
    if "already exists" in provider_message_lower:
        return True
    if "name conflict" in provider_message_lower:
        return True
    return False


def _sanitize_static_ip_error_summary(*, provider_message: str | None, fallback_message: str | None) -> str | None:
    summary = _sanitize_github_error_message(provider_message, max_length=300)
    if summary:
        lowered = summary.lower()
        if any(
            marker in lowered
            for marker in (
                "begin private key",
                "private_key",
                '"private_key"',
                "access_token",
                '"token"',
                "service_account",
                "gcp_deploy_key",
            )
        ):
            summary = None
    if summary:
        return summary
    return _sanitize_github_error_message(fallback_message, max_length=300)


def _derive_static_ip_error_code(*, provider_message_lower: str, status_code: int | None) -> str | None:
    if "service_disabled" in provider_message_lower:
        return "SERVICE_DISABLED"
    if "permission_denied" in provider_message_lower or "permission denied" in provider_message_lower:
        return "PERMISSION_DENIED"
    if "quota_exceeded" in provider_message_lower:
        return "QUOTA_EXCEEDED"
    if "resource_exhausted" in provider_message_lower or "resource exhausted" in provider_message_lower:
        return "RESOURCE_EXHAUSTED"
    if status_code is not None:
        return f"http_{int(status_code)}"
    return None


def _derive_static_ip_provisioning_safe_message(*, reason_code: str) -> str:
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_ADDRESS_MISSING:
        return (
            "Managed-site static IP ensure succeeded but did not return an address value. "
            "Verify global address describe permissions and retry."
        )
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_ADDRESS_MISSING_AFTER_RETRY:
        return (
            "Managed-site static IP ensure could not resolve an address value after bounded describe retries. "
            "Verify global address visibility and list/describe permissions, then retry."
        )
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID:
        return (
            "Managed deploy impersonation configuration is invalid. "
            "Configure GCP_MANAGED_DEPLOY as a service-account email only."
        )
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED:
        return (
            "Managed deploy impersonation is not authorized. "
            "Grant roles/iam.serviceAccountTokenCreator for the configured managed deploy service account."
        )
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PERMISSION_DENIED:
        return "Managed-site static IP provisioning is not authorized for the configured GCP project."
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_API_DISABLED:
        return (
            "Managed-site static IP provisioning requires Compute Engine API to be enabled "
            "for the configured GCP project."
        )
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_QUOTA_EXCEEDED:
        return "Managed-site static IP provisioning exceeded global static address quota in the configured GCP project."
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROJECT_NOT_FOUND:
        return "Managed-site static IP provisioning project configuration is invalid or not accessible."
    if reason_code == _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT:
        return (
            "Managed-site static IP provisioning encountered a static IP naming conflict and could not reconcile "
            "the expected global address."
        )
    return "Managed site static IP provisioning failed before deploy dispatch."


def _normalize_static_ip_operation(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    normalized_lower = normalized.strip().lower()
    if normalized_lower in {"describe", "create", "describe_after_create", "list_after_describe", "credential_resolve"}:
        return normalized_lower
    return None


def _normalize_static_ip_error_diagnostics(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    normalized_operation = _normalize_static_ip_operation(value.get("static_ip_operation"))
    normalized_category = _coerce_string(value.get("static_ip_error_category"))
    normalized_code = _coerce_string(value.get("static_ip_error_code"))
    normalized_summary = _sanitize_static_ip_error_summary(
        provider_message=_coerce_string(value.get("static_ip_error_summary")),
        fallback_message=None,
    )
    normalized_permission_hint = _sanitize_github_error_message(
        value.get("static_ip_permission_hint"),
        max_length=240,
    )
    normalized_exit_code = _coerce_int(value.get("static_ip_exit_code"))
    normalized_describe_attempts = _coerce_int(value.get("static_ip_describe_attempts"))
    if normalized_describe_attempts is not None:
        normalized_describe_attempts = max(0, int(normalized_describe_attempts))
    list_fallback_attempted = value.get("static_ip_list_fallback_attempted")
    normalized_list_fallback_attempted = (
        bool(list_fallback_attempted) if isinstance(list_fallback_attempted, bool) else None
    )
    normalized_list_fallback_match_count = _coerce_int(value.get("static_ip_list_fallback_match_count"))
    if normalized_list_fallback_match_count is not None:
        normalized_list_fallback_match_count = max(0, int(normalized_list_fallback_match_count))
    list_fallback_address_present = value.get("static_ip_list_fallback_address_present")
    normalized_list_fallback_address_present = (
        bool(list_fallback_address_present) if isinstance(list_fallback_address_present, bool) else None
    )
    normalized_list_fallback_failure_code = _coerce_string(value.get("static_ip_list_fallback_failure_code"))
    if normalized_list_fallback_failure_code:
        normalized_list_fallback_failure_code = normalized_list_fallback_failure_code.strip().lower()[:80]
    if normalized_list_fallback_failure_code not in {
        "payload_invalid",
        "items_missing",
        "no_match",
        "multiple_matches",
        "missing_address",
    }:
        normalized_list_fallback_failure_code = None
    normalized_list_fallback_response_keys: tuple[str, ...] = ()
    raw_list_fallback_response_keys = value.get("static_ip_list_fallback_response_keys")
    if isinstance(raw_list_fallback_response_keys, (list, tuple, set)):
        normalized_items: list[str] = []
        for item in raw_list_fallback_response_keys:
            candidate = _coerce_string(item)
            if not candidate:
                continue
            candidate = candidate.strip()[:80]
            if candidate and candidate not in normalized_items:
                normalized_items.append(candidate)
            if len(normalized_items) >= 16:
                break
        normalized_list_fallback_response_keys = tuple(normalized_items)
    credential_diagnostics = _normalize_gcp_credential_diagnostics(value)
    if normalized_exit_code is not None:
        normalized_exit_code = int(normalized_exit_code)
    return {
        "static_ip_operation": normalized_operation,
        "static_ip_error_category": normalized_category,
        "static_ip_error_code": normalized_code,
        "static_ip_error_summary": normalized_summary,
        "static_ip_exit_code": normalized_exit_code,
        "static_ip_describe_attempts": normalized_describe_attempts,
        "static_ip_list_fallback_attempted": normalized_list_fallback_attempted,
        "static_ip_list_fallback_match_count": normalized_list_fallback_match_count,
        "static_ip_list_fallback_address_present": normalized_list_fallback_address_present,
        "static_ip_list_fallback_failure_code": normalized_list_fallback_failure_code,
        "static_ip_list_fallback_response_keys": list(normalized_list_fallback_response_keys),
        "static_ip_permission_hint": normalized_permission_hint,
        "gcp_credential_source": credential_diagnostics.get("gcp_credential_source"),
        "gcp_principal_email": credential_diagnostics.get("gcp_principal_email"),
        "gcp_impersonated_service_account_email": credential_diagnostics.get("gcp_impersonated_service_account_email"),
    }


def _ensure_managed_site_dns_a_record(
    *,
    gcp_deploy_key: str | None,
    dns_project_id: str,
    dns_managed_zone: str,
    record_name: str,
    expected_ip_address: str,
    ttl: int,
    timeout_seconds: int,
    gcp_impersonated_service_account_email: str | None = None,
) -> dict[str, object]:
    normalized_project_id = _coerce_string(dns_project_id)
    normalized_zone = _coerce_string(dns_managed_zone)
    normalized_record_name = (_coerce_string(record_name) or "").strip().lower()
    normalized_expected_ip = _coerce_string(expected_ip_address)
    normalized_ttl = _coerce_int(ttl)
    if normalized_ttl is None or normalized_ttl <= 0:
        normalized_ttl = _MBSRN_MANAGED_PREVIEW_DNS_TTL_DEFAULT
    if not normalized_expected_ip:
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_ADDRESS_MISSING,
            safe_message=(
                "Managed-site static IP ensure succeeded but did not provide an address for DNS provisioning."
            ),
            stage="static_ip_provision",
        )
    if not normalized_project_id or not normalized_zone or not normalized_record_name:
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
            safe_message="Managed-site DNS provisioning is missing required DNS project/zone/record config.",
            stage="dns_provision",
        )
    access_token = _resolve_google_access_token_for_managed_deploy_operations(
        credentials_json=gcp_deploy_key,
        impersonated_service_account_email=gcp_impersonated_service_account_email,
        missing_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
        missing_safe_message=("Managed deploy runtime credential is unavailable for DNS provisioning."),
        invalid_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
        invalid_safe_message=("Managed deploy runtime credential is invalid for DNS provisioning."),
        integration_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PROVISIONING_FAILED,
        integration_safe_message=("Google auth runtime dependency is unavailable for DNS provisioning."),
        stage="dns_provision",
    )
    encoded_project = urllib.parse.quote(normalized_project_id, safe="")
    encoded_zone = urllib.parse.quote(normalized_zone, safe="")
    rrsets_url = "https://dns.googleapis.com/dns/v1/projects/" f"{encoded_project}/managedZones/{encoded_zone}/rrsets"
    changes_url = "https://dns.googleapis.com/dns/v1/projects/" f"{encoded_project}/managedZones/{encoded_zone}/changes"
    request_kwargs = {
        "access_token": access_token,
        "timeout_seconds": timeout_seconds,
        "error_stage": "dns_provision",
        "code_on_failure": _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PROVISIONING_FAILED,
        "safe_message_on_failure": "Managed-site DNS provisioning request to Google Cloud DNS failed.",
        "safe_message_on_timeout": "Managed-site DNS provisioning request timed out.",
    }

    def _rrset_url(record_type: str) -> str:
        query = urllib.parse.urlencode(
            {
                "name": normalized_record_name,
                "type": record_type,
            }
        )
        return f"{rrsets_url}?{query}"

    def _fetch_rrset(record_type: str) -> dict[str, object] | None:
        try:
            payload = _request_google_json(
                method="GET",
                url=_rrset_url(record_type),
                **request_kwargs,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.status_code == 403:
                raise SEOMigrationGitHubPublisherError(
                    code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PERMISSION_DENIED,
                    safe_message="Managed-site DNS provisioning is not authorized for the configured DNS project/zone.",
                    status_code=exc.status_code,
                    stage="dns_provision",
                    provider_message=exc.provider_message,
                ) from exc
            if exc.status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
                    safe_message=("Managed-site DNS managed zone configuration is invalid or not accessible."),
                    status_code=exc.status_code,
                    stage="dns_provision",
                    provider_message=exc.provider_message,
                ) from exc
            raise
        if not isinstance(payload, dict):
            return None
        rrsets = payload.get("rrsets")
        if not isinstance(rrsets, list):
            return None
        expected_type = record_type.strip().upper()
        for raw_rrset in rrsets:
            if not isinstance(raw_rrset, dict):
                continue
            rrset_name = (_coerce_string(raw_rrset.get("name")) or "").strip().lower()
            rrset_type = (_coerce_string(raw_rrset.get("type")) or "").strip().upper()
            if rrset_name != normalized_record_name or rrset_type != expected_type:
                continue
            rrset_ttl = _coerce_int(raw_rrset.get("ttl")) or normalized_ttl
            rrset_rrdatas_raw = raw_rrset.get("rrdatas")
            rrset_rrdatas: list[str] = []
            if isinstance(rrset_rrdatas_raw, list):
                for raw_rrdata in rrset_rrdatas_raw:
                    candidate = _coerce_string(raw_rrdata)
                    if candidate:
                        rrset_rrdatas.append(candidate)
            return {
                "name": normalized_record_name,
                "type": expected_type,
                "ttl": rrset_ttl,
                "rrdatas": _dedupe_strings(rrset_rrdatas),
            }
        return None

    def _extract_rrdatas(rrset: dict[str, object] | None) -> list[str]:
        if not isinstance(rrset, dict):
            return []
        raw_rrdatas = rrset.get("rrdatas")
        if not isinstance(raw_rrdatas, list):
            return []
        values: list[str] = []
        for raw in raw_rrdatas:
            candidate = _coerce_string(raw)
            if candidate:
                values.append(candidate)
        return _dedupe_strings(values)

    def _is_expected_rrset(rrset: dict[str, object] | None) -> bool:
        rrset_ips = _extract_rrdatas(rrset)
        return len(rrset_ips) == 1 and rrset_ips[0] == normalized_expected_ip

    cname_rrset = _fetch_rrset("CNAME")
    if cname_rrset is not None and _extract_rrdatas(cname_rrset):
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFLICTING_RECORD,
            safe_message=(
                "Managed-site DNS hostname has a conflicting CNAME record and cannot be managed as an A record."
            ),
            stage="dns_provision",
        )

    existing_a_rrset = _fetch_rrset("A")
    previous_ips = _extract_rrdatas(existing_a_rrset)
    existing_ttl = _coerce_int(existing_a_rrset.get("ttl")) if isinstance(existing_a_rrset, dict) else None
    if _is_expected_rrset(existing_a_rrset):
        return {
            "dns_record_name": normalized_record_name,
            "dns_record_type": "A",
            "dns_managed_zone": normalized_zone,
            "dns_project_id": normalized_project_id,
            "dns_expected_ip": normalized_expected_ip,
            "dns_previous_ips": previous_ips,
            "dns_created": False,
            "dns_updated": False,
            "dns_ttl": existing_ttl or normalized_ttl,
            "result": "exists",
        }

    saw_transaction_conflict = False
    for attempt in range(2):
        had_existing_before_change = existing_a_rrset is not None
        addition = {
            "name": normalized_record_name,
            "type": "A",
            "ttl": normalized_ttl,
            "rrdatas": [normalized_expected_ip],
        }
        payload: dict[str, object] = {"additions": [addition]}
        if isinstance(existing_a_rrset, dict):
            payload["deletions"] = [
                {
                    "name": normalized_record_name,
                    "type": "A",
                    "ttl": _coerce_int(existing_a_rrset.get("ttl")) or normalized_ttl,
                    "rrdatas": _extract_rrdatas(existing_a_rrset),
                }
            ]
        try:
            _request_google_json(
                method="POST",
                url=changes_url,
                payload=payload,
                expected_statuses=(200, 201),
                **request_kwargs,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.status_code == 403:
                raise SEOMigrationGitHubPublisherError(
                    code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PERMISSION_DENIED,
                    safe_message="Managed-site DNS provisioning is not authorized for the configured DNS project/zone.",
                    status_code=exc.status_code,
                    stage="dns_provision",
                    provider_message=exc.provider_message,
                ) from exc
            if exc.status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING,
                    safe_message=("Managed-site DNS managed zone configuration is invalid or not accessible."),
                    status_code=exc.status_code,
                    stage="dns_provision",
                    provider_message=exc.provider_message,
                ) from exc
            if exc.status_code == 409:
                saw_transaction_conflict = True
                refreshed_rrset = _fetch_rrset("A")
                if _is_expected_rrset(refreshed_rrset):
                    return {
                        "dns_record_name": normalized_record_name,
                        "dns_record_type": "A",
                        "dns_managed_zone": normalized_zone,
                        "dns_project_id": normalized_project_id,
                        "dns_expected_ip": normalized_expected_ip,
                        "dns_previous_ips": previous_ips,
                        "dns_created": False,
                        "dns_updated": False,
                        "dns_ttl": _coerce_int(refreshed_rrset.get("ttl")) or normalized_ttl,
                        "result": "already_correct_after_race",
                    }
                if attempt == 0:
                    existing_a_rrset = refreshed_rrset
                    refreshed_ips = _extract_rrdatas(refreshed_rrset)
                    if refreshed_ips:
                        previous_ips = refreshed_ips
                    continue
                raise SEOMigrationGitHubPublisherError(
                    code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_TRANSACTION_CONFLICT,
                    safe_message=("Managed-site DNS update encountered a concurrent transaction conflict."),
                    status_code=exc.status_code,
                    stage="dns_provision",
                    provider_message=exc.provider_message,
                ) from exc
            raise

        final_rrset: dict[str, object] | None = None
        for poll_index in range(3):
            final_rrset = _fetch_rrset("A")
            if _is_expected_rrset(final_rrset):
                break
            if poll_index < 2:
                time.sleep(1)
        if _is_expected_rrset(final_rrset):
            return {
                "dns_record_name": normalized_record_name,
                "dns_record_type": "A",
                "dns_managed_zone": normalized_zone,
                "dns_project_id": normalized_project_id,
                "dns_expected_ip": normalized_expected_ip,
                "dns_previous_ips": previous_ips,
                "dns_created": not had_existing_before_change,
                "dns_updated": had_existing_before_change,
                "dns_ttl": _coerce_int(final_rrset.get("ttl")) or normalized_ttl,
                "result": "updated" if had_existing_before_change else "created",
            }
        if saw_transaction_conflict:
            raise SEOMigrationGitHubPublisherError(
                code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_TRANSACTION_CONFLICT,
                safe_message=("Managed-site DNS update encountered a concurrent transaction conflict."),
                stage="dns_provision",
            )
        break

    raise SEOMigrationGitHubPublisherError(
        code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PROVISIONING_FAILED,
        safe_message=("Managed-site DNS change was requested but the expected A record was not observed."),
        stage="dns_provision",
    )


def _resolve_google_access_token_from_service_account_json(
    *,
    credentials_json: str,
    missing_code: str = "runtime_credential_missing",
    missing_safe_message: str = (
        "Managed deploy runtime credential is unavailable for image pull secret provisioning."
    ),
    invalid_code: str = "runtime_configuration_invalid",
    invalid_safe_message: str = ("Managed deploy runtime credential is invalid for image pull secret provisioning."),
    integration_code: str = "runtime_integration_unavailable",
    integration_safe_message: str = (
        "Google auth runtime dependency is unavailable for image pull secret provisioning."
    ),
    stage: str = "image_pull_secret_provision",
) -> str:
    normalized_credentials_json = _coerce_string(credentials_json)
    if not normalized_credentials_json:
        raise SEOMigrationGitHubPublisherError(
            code=missing_code,
            safe_message=missing_safe_message,
            stage=stage,
        )
    try:
        parsed_credentials = json.loads(normalized_credentials_json)
    except json.JSONDecodeError as exc:
        raise SEOMigrationGitHubPublisherError(
            code=invalid_code,
            safe_message=invalid_safe_message,
            stage=stage,
        ) from exc
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SEOMigrationGitHubPublisherError(
            code=integration_code,
            safe_message=integration_safe_message,
            stage=stage,
        ) from exc
    try:
        credentials = service_account.Credentials.from_service_account_info(
            parsed_credentials,
            scopes=("https://www.googleapis.com/auth/cloud-platform",),
        )
        credentials.refresh(GoogleAuthRequest())
        token = _coerce_string(getattr(credentials, "token", None))
    except Exception as exc:
        raise SEOMigrationGitHubPublisherError(
            code=invalid_code,
            safe_message=invalid_safe_message,
            stage=stage,
        ) from exc
    if not token:
        raise SEOMigrationGitHubPublisherError(
            code=invalid_code,
            safe_message=invalid_safe_message,
            stage=stage,
        )
    return token


def _resolve_google_access_token_from_google_auth_default(
    *,
    missing_code: str,
    missing_safe_message: str,
    integration_code: str,
    integration_safe_message: str,
    stage: str,
) -> str:
    try:
        from google.auth import default as google_auth_default
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SEOMigrationGitHubPublisherError(
            code=integration_code,
            safe_message=integration_safe_message,
            stage=stage,
        ) from exc
    try:
        credentials, _project_id = google_auth_default(
            scopes=("https://www.googleapis.com/auth/cloud-platform",),
        )
        credentials.refresh(GoogleAuthRequest())
        token = _coerce_string(getattr(credentials, "token", None))
    except Exception as exc:
        provider_message = _sanitize_github_error_message(str(exc), max_length=300)
        raise SEOMigrationGitHubPublisherError(
            code=missing_code,
            safe_message=missing_safe_message,
            stage=stage,
            provider_message=provider_message,
        ) from exc
    if not token:
        raise SEOMigrationGitHubPublisherError(
            code=missing_code,
            safe_message=missing_safe_message,
            stage=stage,
        )
    return token


def _resolve_google_access_token_for_managed_deploy_operations(
    *,
    credentials_json: str | None,
    impersonated_service_account_email: str | None = None,
    missing_code: str = "runtime_credential_missing",
    missing_safe_message: str = (
        "Managed deploy runtime credential is unavailable for image pull secret provisioning."
    ),
    invalid_code: str = "runtime_configuration_invalid",
    invalid_safe_message: str = ("Managed deploy runtime credential is invalid for image pull secret provisioning."),
    integration_code: str = "runtime_integration_unavailable",
    integration_safe_message: str = (
        "Google auth runtime dependency is unavailable for image pull secret provisioning."
    ),
    stage: str = "image_pull_secret_provision",
) -> str:
    normalized_impersonated_service_account_email = _coerce_string(impersonated_service_account_email)
    if normalized_impersonated_service_account_email:
        validated_impersonated_service_account_email = _validate_managed_deploy_impersonation_service_account_email(
            normalized_impersonated_service_account_email,
            stage=stage,
        )
        return _resolve_google_access_token_via_impersonation(
            credentials_json=credentials_json,
            target_service_account_email=validated_impersonated_service_account_email,
            missing_code=missing_code,
            missing_safe_message=missing_safe_message,
            invalid_code=invalid_code,
            invalid_safe_message=invalid_safe_message,
            integration_code=integration_code,
            integration_safe_message=integration_safe_message,
            permission_denied_code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED,
            permission_denied_safe_message=(
                "Managed deploy impersonation is not authorized. "
                "Grant roles/iam.serviceAccountTokenCreator for the configured managed deploy service account."
            ),
            stage=stage,
        )

    normalized_credentials_json = _coerce_string(credentials_json)
    if normalized_credentials_json:
        return _resolve_google_access_token_from_service_account_json(
            credentials_json=normalized_credentials_json,
            missing_code=missing_code,
            missing_safe_message=missing_safe_message,
            invalid_code=invalid_code,
            invalid_safe_message=invalid_safe_message,
            integration_code=integration_code,
            integration_safe_message=integration_safe_message,
            stage=stage,
        )
    return _resolve_google_access_token_from_google_auth_default(
        missing_code=missing_code,
        missing_safe_message=missing_safe_message,
        integration_code=integration_code,
        integration_safe_message=integration_safe_message,
        stage=stage,
    )


def _resolve_google_access_token_via_impersonation(
    *,
    credentials_json: str | None,
    target_service_account_email: str,
    missing_code: str,
    missing_safe_message: str,
    invalid_code: str,
    invalid_safe_message: str,
    integration_code: str,
    integration_safe_message: str,
    permission_denied_code: str,
    permission_denied_safe_message: str,
    stage: str,
) -> str:
    normalized_credentials_json = _coerce_string(credentials_json)
    try:
        from google.auth import default as google_auth_default
        from google.auth import impersonated_credentials
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SEOMigrationGitHubPublisherError(
            code=integration_code,
            safe_message=integration_safe_message,
            stage=stage,
        ) from exc

    source_credentials = None
    if normalized_credentials_json:
        try:
            parsed_credentials = json.loads(normalized_credentials_json)
        except json.JSONDecodeError as exc:
            raise SEOMigrationGitHubPublisherError(
                code=invalid_code,
                safe_message=invalid_safe_message,
                stage=stage,
            ) from exc
        try:
            source_credentials = service_account.Credentials.from_service_account_info(
                parsed_credentials,
                scopes=("https://www.googleapis.com/auth/cloud-platform",),
            )
        except Exception as exc:
            raise SEOMigrationGitHubPublisherError(
                code=invalid_code,
                safe_message=invalid_safe_message,
                stage=stage,
            ) from exc
    else:
        try:
            source_credentials, _project_id = google_auth_default(
                scopes=("https://www.googleapis.com/auth/cloud-platform",),
            )
        except Exception as exc:
            provider_message = _sanitize_github_error_message(str(exc), max_length=300)
            provider_message_lower = (provider_message or "").lower()
            if _is_managed_deploy_impersonation_permission_denied_error(provider_message_lower):
                raise SEOMigrationGitHubPublisherError(
                    code=permission_denied_code,
                    safe_message=permission_denied_safe_message,
                    stage=stage,
                    provider_message=provider_message,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code=missing_code,
                safe_message=missing_safe_message,
                stage=stage,
                provider_message=provider_message,
            ) from exc

    try:
        impersonated = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=target_service_account_email,
            target_scopes=("https://www.googleapis.com/auth/cloud-platform",),
            lifetime=3600,
        )
        impersonated.refresh(GoogleAuthRequest())
        token = _coerce_string(getattr(impersonated, "token", None))
    except Exception as exc:
        provider_message = _sanitize_github_error_message(str(exc), max_length=300)
        provider_message_lower = (provider_message or "").lower()
        if _is_managed_deploy_impersonation_permission_denied_error(provider_message_lower):
            raise SEOMigrationGitHubPublisherError(
                code=permission_denied_code,
                safe_message=permission_denied_safe_message,
                stage=stage,
                provider_message=provider_message,
            ) from exc
        raise SEOMigrationGitHubPublisherError(
            code=invalid_code,
            safe_message=invalid_safe_message,
            stage=stage,
            provider_message=provider_message,
        ) from exc
    if not token:
        raise SEOMigrationGitHubPublisherError(
            code=invalid_code,
            safe_message=invalid_safe_message,
            stage=stage,
        )
    return token


def _is_managed_deploy_impersonation_permission_denied_error(provider_message_lower: str) -> bool:
    if not provider_message_lower:
        return False
    return any(
        token in provider_message_lower
        for token in (
            "permission denied",
            "permission_denied",
            "iam.serviceaccounts.getaccesstoken",
            "service account token creator",
            "serviceaccounttokencreator",
            "403",
        )
    )


def _managed_deploy_impersonation_value_contains_secret_material(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith("{") or normalized.startswith("["):
        return True
    if "private_key" in normalized:
        return True
    if "-----begin" in normalized and "private key" in normalized:
        return True
    if '"type"' in normalized and "service_account" in normalized:
        return True
    return False


def _validate_managed_deploy_impersonation_service_account_email(
    value: object,
    *,
    stage: str,
) -> str:
    normalized = (_coerce_string(value) or "").strip().lower()
    if not normalized:
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID,
            safe_message=(
                "Managed deploy impersonation configuration is invalid. "
                "Set GCP_MANAGED_DEPLOY to a service account email."
            ),
            stage=stage,
        )
    if _managed_deploy_impersonation_value_contains_secret_material(normalized):
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID,
            safe_message=(
                "Managed deploy impersonation configuration is invalid. "
                "GCP_MANAGED_DEPLOY must contain only a service-account email."
            ),
            stage=stage,
        )
    if not _MANAGED_DEPLOY_SERVICE_ACCOUNT_EMAIL_PATTERN.match(normalized):
        raise SEOMigrationGitHubPublisherError(
            code=_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID,
            safe_message=(
                "Managed deploy impersonation configuration is invalid. "
                "GCP_MANAGED_DEPLOY must be a valid service-account email."
            ),
            stage=stage,
        )
    return normalized


def _request_google_json(
    *,
    method: str,
    url: str,
    access_token: str,
    timeout_seconds: int,
    payload: dict[str, object] | None = None,
    expected_statuses: tuple[int, ...] = (200,),
    allow_404: bool = False,
    error_stage: str | None = None,
    code_on_failure: str = "image_pull_secret_provisioning_failed",
    safe_message_on_failure: str = "Managed image pull secret provisioning request to Google APIs failed.",
    safe_message_on_timeout: str = "Managed image pull secret provisioning request timed out.",
) -> dict[str, object] | list[object] | None:
    body: bytes | None = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "MBSRN-MigrationPublisher/1.0",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    return _request_json_via_urllib(
        request=request,
        timeout_seconds=timeout_seconds,
        expected_statuses=expected_statuses,
        allow_404=allow_404,
        error_stage=error_stage,
        code_on_failure=code_on_failure,
        safe_message_on_failure=safe_message_on_failure,
        safe_message_on_timeout=safe_message_on_timeout,
    )


def _request_kubernetes_json(
    *,
    method: str,
    endpoint: str,
    path: str,
    access_token: str,
    ssl_context: ssl.SSLContext,
    timeout_seconds: int,
    payload: dict[str, object] | None = None,
    expected_statuses: tuple[int, ...] = (200,),
    allow_404: bool = False,
    error_stage: str | None = None,
    code_on_failure: str = "image_pull_secret_provisioning_failed",
    safe_message_on_failure: str = "Managed image pull secret provisioning request to Kubernetes API failed.",
    safe_message_on_timeout: str = "Managed image pull secret provisioning request timed out.",
) -> dict[str, object] | list[object] | None:
    body: bytes | None = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "MBSRN-MigrationPublisher/1.0",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url=f"https://{endpoint}{path}",
        data=body,
        method=method,
        headers=headers,
    )
    return _request_json_via_urllib(
        request=request,
        timeout_seconds=timeout_seconds,
        expected_statuses=expected_statuses,
        allow_404=allow_404,
        error_stage=error_stage,
        code_on_failure=code_on_failure,
        safe_message_on_failure=safe_message_on_failure,
        safe_message_on_timeout=safe_message_on_timeout,
        ssl_context=ssl_context,
    )


def _request_json_via_urllib(
    *,
    request: urllib.request.Request,
    timeout_seconds: int,
    expected_statuses: tuple[int, ...],
    allow_404: bool,
    error_stage: str | None,
    code_on_failure: str,
    safe_message_on_failure: str,
    safe_message_on_timeout: str,
    ssl_context: ssl.SSLContext | None = None,
) -> dict[str, object] | list[object] | None:
    try:
        if ssl_context is None:
            response_context = urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            )
        else:
            response_context = urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
                context=ssl_context,
            )
        with response_context as response:
            status_code = int(getattr(response, "status", 0) or 0)
            if status_code not in expected_statuses:
                raise SEOMigrationGitHubPublisherError(
                    code=code_on_failure,
                    safe_message=safe_message_on_failure,
                    status_code=status_code,
                    stage=error_stage,
                )
            response_body = response.read().decode("utf-8", errors="replace").strip()
            if not response_body:
                return None
            parsed = json.loads(response_body)
            if isinstance(parsed, (dict, list)):
                return parsed
            return None
    except urllib.error.HTTPError as exc:
        status_code = int(getattr(exc, "code", 0) or 0)
        if allow_404 and status_code == 404:
            return None
        provider_message = _sanitize_github_error_message(_extract_http_error_message_for_raw_http(exc))
        raise SEOMigrationGitHubPublisherError(
            code=code_on_failure,
            safe_message=safe_message_on_failure,
            status_code=status_code,
            stage=error_stage,
            provider_message=provider_message,
        ) from exc
    except json.JSONDecodeError as exc:
        raise SEOMigrationGitHubPublisherError(
            code=code_on_failure,
            safe_message=safe_message_on_failure,
            stage=error_stage,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise SEOMigrationGitHubPublisherError(
            code="github_timeout",
            safe_message=safe_message_on_timeout,
            stage=error_stage,
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
            raise SEOMigrationGitHubPublisherError(
                code="github_timeout",
                safe_message=safe_message_on_timeout,
                stage=error_stage,
            ) from exc
        raise SEOMigrationGitHubPublisherError(
            code=code_on_failure,
            safe_message=safe_message_on_failure,
            stage=error_stage,
        ) from exc


def _extract_http_error_message_for_raw_http(exc: urllib.error.HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:  # pragma: no cover - defensive
        return ""
    if not payload:
        return ""
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            message = parsed.get("message")
            if isinstance(message, str):
                return message
    except Exception:  # pragma: no cover - defensive
        pass
    return payload[:300]


def _resolve_google_credential_principal(
    *,
    credentials_json: object,
    timeout_seconds: int,
) -> tuple[str, str | None]:
    normalized_credentials = _coerce_string(credentials_json)
    if normalized_credentials:
        try:
            parsed = json.loads(normalized_credentials)
        except (TypeError, ValueError):
            return (_GCP_CREDENTIAL_SOURCE_UNKNOWN, None)
        if isinstance(parsed, dict):
            client_email = _normalize_gcp_principal_email(parsed.get("client_email"))
            return (_GCP_CREDENTIAL_SOURCE_SERVICE_ACCOUNT_JSON, client_email)
        return (_GCP_CREDENTIAL_SOURCE_UNKNOWN, None)
    metadata_email = _lookup_google_metadata_principal_email(timeout_seconds=timeout_seconds)
    if metadata_email:
        return (_GCP_CREDENTIAL_SOURCE_ADC_METADATA, metadata_email)
    return (_GCP_CREDENTIAL_SOURCE_UNKNOWN, None)


def _lookup_google_metadata_principal_email(*, timeout_seconds: int) -> str | None:
    metadata_url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
    request = urllib.request.Request(
        url=metadata_url,
        method="GET",
        headers={
            "Metadata-Flavor": "Google",
            "User-Agent": "MBSRN-MigrationPublisher/1.0",
        },
    )
    resolved_timeout = max(1, min(int(timeout_seconds or 0), 3))
    try:
        with urllib.request.urlopen(request, timeout=resolved_timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    return _normalize_gcp_principal_email(response_body)


def _normalize_gcp_credential_source(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    lowered = normalized.strip().lower()
    if lowered in {
        _GCP_CREDENTIAL_SOURCE_SERVICE_ACCOUNT_JSON,
        _GCP_CREDENTIAL_SOURCE_MANAGED_DEPLOY_IMPERSONATION,
        _GCP_CREDENTIAL_SOURCE_ADC_METADATA,
        _GCP_CREDENTIAL_SOURCE_UNKNOWN,
    }:
        return lowered
    return None


def _normalize_gcp_principal_email(value: object) -> str | None:
    normalized = _sanitize_github_error_message(value, max_length=200)
    if not normalized:
        return None
    lowered = normalized.strip().lower()
    if "@" not in lowered:
        return None
    if "private_key" in lowered or "token" in lowered:
        return None
    return lowered


def _normalize_gcp_impersonated_service_account_email(value: object) -> str | None:
    normalized = _normalize_gcp_principal_email(value)
    if not normalized:
        return None
    if _managed_deploy_impersonation_value_contains_secret_material(normalized):
        return None
    if not _MANAGED_DEPLOY_SERVICE_ACCOUNT_EMAIL_PATTERN.match(normalized):
        return None
    return normalized


def _normalize_gcp_credential_diagnostics(value: object) -> dict[str, object]:
    normalized_source: str | None = None
    normalized_principal: str | None = None
    normalized_impersonated_principal: str | None = None
    if isinstance(value, dict):
        normalized_source = _normalize_gcp_credential_source(value.get("gcp_credential_source"))
        normalized_principal = _normalize_gcp_principal_email(value.get("gcp_principal_email"))
        normalized_impersonated_principal = _normalize_gcp_impersonated_service_account_email(
            value.get("gcp_impersonated_service_account_email")
        )
    return {
        "gcp_credential_source": normalized_source,
        "gcp_principal_email": normalized_principal,
        "gcp_impersonated_service_account_email": normalized_impersonated_principal,
    }


def _join_repo_path(root: str, path: str) -> str:
    normalized_root = root.strip("/")
    normalized_path = path.strip("/")
    if not normalized_root:
        return normalized_path
    if not normalized_path:
        return normalized_root
    return f"{normalized_root}/{normalized_path}"


def _encrypt_actions_secret_value(*, public_key: str, secret_value: str) -> str:
    normalized_public_key = _coerce_string(public_key)
    normalized_secret_value = _coerce_string(secret_value)
    if not normalized_public_key or not normalized_secret_value:
        raise SEOMigrationGitHubPublisherError(
            code="github_secret_invalid",
            safe_message="GitHub Actions secret payload is invalid.",
            stage="secret_propagation",
        )
    try:
        import nacl.encoding
        import nacl.public
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise SEOMigrationGitHubPublisherError(
            code="runtime_configuration_invalid",
            safe_message="GitHub Actions secret encryption support is unavailable.",
            stage="secret_propagation",
        ) from exc
    try:
        key = nacl.public.PublicKey(
            normalized_public_key.encode("utf-8"),
            encoder=nacl.encoding.Base64Encoder(),
        )
        sealed_box = nacl.public.SealedBox(key)
        encrypted = sealed_box.encrypt(
            normalized_secret_value.encode("utf-8"),
            encoder=nacl.encoding.Base64Encoder(),
        )
    except Exception as exc:
        raise SEOMigrationGitHubPublisherError(
            code="github_secret_invalid",
            safe_message="GitHub Actions secret payload is invalid.",
            stage="secret_propagation",
        ) from exc
    return encrypted.decode("utf-8")


def _workflow_repo_path(workflow_id: str) -> str:
    normalized = str(workflow_id or "").strip().replace("\\", "/").lstrip("/")
    if not normalized or ".." in normalized:
        raise SEOMigrationGitHubPublisherError(
            code="github_workflow_invalid",
            safe_message="Deploy workflow target is invalid.",
        )
    if normalized.lower().startswith(".github/workflows/"):
        return normalized
    if normalized.lower().startswith("github/workflows/"):
        return f".{normalized}"
    return _join_repo_path(".github/workflows", normalized)


def _normalize_workflow_path_for_log(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    try:
        return _workflow_repo_path(normalized)
    except SEOMigrationGitHubPublisherError:
        compact = normalized.strip().replace("\\", "/").lstrip("/")
        if not compact:
            return None
        return compact[:200]


def normalize_workflow_dispatch_identifier_for_api(workflow_id: object) -> str | None:
    normalized = _coerce_string(workflow_id)
    if not normalized:
        return None
    try:
        workflow_path = _workflow_repo_path(normalized)
    except SEOMigrationGitHubPublisherError:
        return normalized.strip() or None
    workflow_name = workflow_path.rsplit("/", 1)[-1].strip()
    return workflow_name or normalized.strip() or None


def _normalize_deploy_workflow_mode(value: object) -> str:
    normalized = _coerce_string(value) or "site_repo_template_v1"
    normalized_lower = normalized.strip().lower()
    if normalized_lower not in {"site_repo_template_v1"}:
        return "site_repo_template_v1"
    return normalized_lower


def _normalize_target_environment_key(value: object) -> str:
    normalized = _coerce_string(value) or "gke_prod"
    normalized_lower = normalized.strip().lower()
    if not normalized_lower:
        return "gke_prod"
    return normalized_lower[:80]


def _normalize_target_environment_source(value: object) -> str:
    normalized = _coerce_string(value) or "admin_config"
    normalized_lower = normalized.strip().lower()
    if not normalized_lower:
        return "admin_config"
    return normalized_lower[:60]


_MBSRN_MANAGED_TEMPLATE_VERSION = "site_repo_template_v1"
_MBSRN_MANAGED_WORKFLOW_MARKER = f"mbsrn-managed-template:{_MBSRN_MANAGED_TEMPLATE_VERSION}"
_MBSRN_MANAGED_WORKFLOW_SIGNATURE_MARKER = "mbsrn-workflow-signature:"
_MBSRN_MANAGED_MANIFEST_MARKER = f"mbsrn-managed-manifest:{_MBSRN_MANAGED_TEMPLATE_VERSION}"
_MBSRN_MANAGED_TEMPLATE_MARKER_PREFIX = "mbsrn-managed-template:"
_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY = "mbsrn_managed_deploy_template_version"
_DEPLOY_RUNTIME_REASON_CODE_PRESENT_OUTPUT_KEY = "deploy_runtime_reason_code_present"
_MANAGED_DEPLOY_TEMPLATE_MARKER_PRESENT_OUTPUT_KEY = "managed_deploy_template_marker_present"
_MBSRN_MANAGED_LABEL = "mbsrn"
_MBSRN_MANAGED_STATIC_IP_LABEL_MANAGED_BY = "mbsrn-managed-by"
_MBSRN_MANAGED_STATIC_IP_LABEL_SITE_ID = "mbsrn-site-id"
_MBSRN_MANAGED_STATIC_IP_LABEL_PREVIEW_HOSTNAME = "mbsrn-preview-hostname"
_MBSRN_MANAGED_STATIC_IP_LABEL_REPO = "mbsrn-repo"
_MBSRN_MANAGED_NAMESPACE_FILE_PATH = "k8s/namespace.yaml"
_MBSRN_MANAGED_DEPLOYMENT_FILE_PATH = "k8s/deployment.yaml"
_MBSRN_MANAGED_SERVICE_FILE_PATH = "k8s/service.yaml"
_MBSRN_MANAGED_INGRESS_FILE_PATH = "k8s/ingress.yaml"
_MBSRN_MANAGED_CERTIFICATE_FILE_PATH = "k8s/managedcertificate.yaml"
_MBSRN_MANAGED_FRONTEND_CONFIG_FILE_PATH = "k8s/frontendconfig.yaml"
_MBSRN_MANAGED_BACKEND_CONFIG_FILE_PATH = "k8s/backendconfig.yaml"
_MBSRN_MANAGED_FRONTEND_CONFIG_NAME_PREFIX = "site-web-frontend-config"
_MBSRN_MANAGED_BACKEND_CONFIG_NAME_PREFIX = "site-web-backend-config"
_MBSRN_MANAGED_PREVIEW_STATIC_IP_NAME_PREFIX = "site-web-preview-ip"
_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH = "k8s/resourcequota.yaml"
_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH = "k8s/limitrange.yaml"
_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH = "k8s/networkpolicy.yaml"
_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME = "ghcr-pull-secret"
_MBSRN_MANAGED_SITE_WEB_IMAGE_REPO_NAME = "site-web"
_MBSRN_MANAGED_SITE_RUNTIME_DOCKERFILE_PATH = "site-runtime/Dockerfile"
_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME_PREFIX = "site-web-preview-cert"
_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX = "site.mbsrn.com"
_MBSRN_MANAGED_PREVIEW_DNS_ZONE_DEFAULT = "sites"
_MBSRN_MANAGED_PREVIEW_DNS_TTL_DEFAULT = 300
_MANAGED_PREVIEW_ENDPOINT_MODE_AUTO = "auto"
_MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY = "preview_shared_gateway"
_MANAGED_PREVIEW_ENDPOINT_MODE_DEDICATED_STATIC_IP = "dedicated_static_ip"
_MANAGED_PREVIEW_ENDPOINT_MODE_VALUES = {
    _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO,
    _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY,
    _MANAGED_PREVIEW_ENDPOINT_MODE_DEDICATED_STATIC_IP,
}
_MBSRN_MANAGED_REPO_BASELINE_README_PATH = "README.md"
_MBSRN_MANAGED_REPO_BASELINE_GITIGNORE_PATH = ".gitignore"
_MBSRN_MANAGED_REPO_BASELINE_LICENSE_PATH = "LICENSE"
_MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY = "private"
_MBSRN_MANAGED_REPO_BASELINE_RECONCILE_PATHS: tuple[str, ...] = (
    _MBSRN_REPO_MANAGEMENT_MARKER_PATH,
    _MBSRN_MANAGED_REPO_BASELINE_README_PATH,
    _MBSRN_MANAGED_REPO_BASELINE_GITIGNORE_PATH,
    _MBSRN_MANAGED_REPO_BASELINE_LICENSE_PATH,
)
_MBSRN_MANAGED_CORE_MANIFEST_PATHS: tuple[str, ...] = (
    _MBSRN_MANAGED_NAMESPACE_FILE_PATH,
    _MBSRN_MANAGED_DEPLOYMENT_FILE_PATH,
    _MBSRN_MANAGED_SERVICE_FILE_PATH,
    _MBSRN_MANAGED_INGRESS_FILE_PATH,
    _MBSRN_MANAGED_CERTIFICATE_FILE_PATH,
    _MBSRN_MANAGED_FRONTEND_CONFIG_FILE_PATH,
    _MBSRN_MANAGED_BACKEND_CONFIG_FILE_PATH,
)
_MBSRN_MANAGED_OPTIONAL_POLICY_MANIFEST_PATHS: tuple[str, ...] = (
    _MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH,
    _MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH,
    _MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH,
)
_MBSRN_MANAGED_MANIFEST_PATHS: tuple[str, ...] = (
    *_MBSRN_MANAGED_CORE_MANIFEST_PATHS,
    *_MBSRN_MANAGED_OPTIONAL_POLICY_MANIFEST_PATHS,
)
_NAMESPACE_MODEL_STATUS_ALIGNED = "aligned"
_NAMESPACE_MODEL_STATUS_MISALIGNED = "misaligned"
_NAMESPACE_MODEL_STATUS_UNKNOWN = "unknown"

_GKE_ENV_PROJECT_ID = "GCP_PROJECT_ID"
_GKE_ENV_CLUSTER_NAME = "KUBERNETES_CLUSTER_NAME"
_GKE_ENV_CLUSTER_LOCATION = "KUBERNETES_CLUSTER_LOCATION"
_GIT_ENV_USERID = "GIT_USERID"
_GIT_ENV_EMAIL = "GIT_EMAIL"
_GIT_ENV_TOKEN = "GIT_TOKEN"
_MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME = "GCP_DEPLOY_KEY"
_GCP_CREDENTIAL_SOURCE_SERVICE_ACCOUNT_JSON = "service_account_json"
_GCP_CREDENTIAL_SOURCE_MANAGED_DEPLOY_IMPERSONATION = "managed_deploy_impersonation"
_GCP_CREDENTIAL_SOURCE_ADC_METADATA = "adc_metadata_server"
_GCP_CREDENTIAL_SOURCE_UNKNOWN = "unknown"
_IMAGE_PULL_SECRET_CONFIG_SOURCE_CONTROL_PLANE = "control_plane_runtime"
_DEPLOY_AUTH_MODE_TARGET_REPO_SECRET = "target_repo_actions_secret"
_DEPLOY_AUTH_MODE_GITHUB_OIDC = "github_oidc_workload_identity"
_DEPLOY_AUTH_MODE_CONTROL_PLANE = "control_plane_managed"
_MANAGED_GKE_CONFIG_CLUSTER_NAME = "cluster_name"
_MANAGED_GKE_CONFIG_CLUSTER_LOCATION = "cluster_location"
_MANAGED_GKE_CONFIG_PROJECT_ID = "project_id"
_GKE_CONFIG_DETAIL_ADMIN_CONFIG_MISSING = "admin_config_missing"
_GKE_CONFIG_DETAIL_REPO_CONFIG_MISSING = "repo_config_missing"
_GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG = "resolved_from_admin_config"
_GKE_CONFIG_DETAIL_RESOLVED_FROM_REPO_CONFIG = "resolved_from_repo_config"
_GKE_CONFIG_SOURCE_MIXED = "mixed_admin_and_repo_config"
_GKE_CONFIG_SOURCE_MISSING = "missing_config"
_GKE_CONFIG_SOURCE_UNKNOWN = "unknown"
_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME = "missing_cluster_name"
_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION = "missing_cluster_location"
_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID = "missing_gcp_project_id"
_DEPLOY_DISPATCH_SERVICE_REASON_TARGET_REPO_DEPLOY_SECRET_MISSING = "target_repo_deploy_secret_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_IMAGE_PULL_SECRET_MISSING = "image_pull_secret_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_IMAGE_PULL_SECRET_NOT_REFERENCED = "image_pull_secret_not_referenced"
_DEPLOY_DISPATCH_SERVICE_REASON_CERTIFICATE_DOMAIN_MISMATCH = "certificate_domain_mismatch"
_DEPLOY_DISPATCH_SERVICE_REASON_STALE_MANAGED_CERTIFICATE_PRESENT = "stale_managed_certificate_present"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_OWNERSHIP_UNVERIFIED = (
    "managed_certificate_ownership_unverified"
)
_DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_CERTIFICATE_MISMATCH = "ingress_certificate_mismatch"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_IDENTITY_MISMATCH = "managed_certificate_identity_mismatch"
_DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_CERTIFICATE_ANNOTATION_MISMATCH = "ingress_certificate_annotation_mismatch"
_DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_BOUND_TO_WRONG_SITE = "tls_certificate_bound_to_wrong_site"
_DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_STATIC_IP_CONFLICT = "ingress_static_ip_conflict"
_DEPLOY_DISPATCH_SERVICE_REASON_SHARED_STATIC_IP_NOT_ALLOWED = "shared_static_ip_not_allowed_for_per_site_ingress"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROVISIONING_FAILED = (
    "managed_site_static_ip_provisioning_failed"
)
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFIG_MISSING = "managed_site_static_ip_config_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PERMISSION_DENIED = "managed_site_static_ip_permission_denied"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_API_DISABLED = "managed_site_static_ip_api_disabled"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_QUOTA_EXCEEDED = "managed_site_static_ip_quota_exceeded"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_PROJECT_NOT_FOUND = "managed_site_static_ip_project_not_found"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_CONFLICT = "managed_site_static_ip_conflict"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_ADDRESS_MISSING = "managed_site_static_ip_address_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_ADDRESS_MISSING_AFTER_RETRY = "static_ip_address_missing_after_retry"
_DEPLOY_DISPATCH_SERVICE_REASON_STATIC_IP_PROVISIONING_PENDING = "static_ip_provisioning_pending"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_CREATE_FAILED = "managed_certificate_create_failed"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_VISIBILITY_PENDING = "managed_certificate_visibility_pending"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_CONFIG_INVALID = (
    "managed_deploy_impersonation_config_invalid"
)
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_DEPLOY_IMPERSONATION_PERMISSION_DENIED = (
    "managed_deploy_impersonation_permission_denied"
)
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_MISSING = "managed_site_static_ip_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFIG_MISSING = "managed_site_dns_config_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PROVISIONING_FAILED = "managed_site_dns_provisioning_failed"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_CONFLICTING_RECORD = "managed_site_dns_conflicting_record"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_PERMISSION_DENIED = "managed_site_dns_permission_denied"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_DNS_TRANSACTION_CONFLICT = "managed_site_dns_transaction_conflict"
_DEPLOY_DISPATCH_SERVICE_REASON_EXPECTED_STATIC_IP_NOT_BOUND_TO_INGRESS = "expected_static_ip_not_bound_to_ingress"
_DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_MISSING = "shared_preview_gateway_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_HOSTNAME_MISSING = "shared_preview_gateway_hostname_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_DOMAIN_DRIFT_REPAIRED = "managed_certificate_domain_drift_repaired"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_DOMAIN_DRIFT_REPAIR_FAILED = (
    "managed_certificate_domain_drift_repair_failed"
)
_DEPLOY_DISPATCH_SERVICE_REASON_STALE_PRE_SHARED_CERT_BINDING = "stale_pre_shared_cert_binding_detected"
_DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE = "managed_certificate_failed_not_visible"
_DEPLOY_DISPATCH_SERVICE_REASON_DEPLOYED_CONTENT_IDENTITY_MISMATCH = "deployed_content_identity_mismatch"
_DEPLOY_DISPATCH_SERVICE_REASON_DNS_RECORD_MISMATCH = "dns_record_mismatch"
_DEPLOY_DISPATCH_SERVICE_REASON_DNS_POINTS_TO_OLD_INGRESS_IP = "dns_points_to_old_ingress_ip"
_DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_IP_ASSIGNED_BUT_DNS_NOT_UPDATED = "ingress_ip_assigned_but_dns_not_updated"
_DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING = "tls_certificate_provisioning"
_DEPLOY_WORKFLOW_INTEGRITY_STATUS_MATCH = "match"
_DEPLOY_WORKFLOW_INTEGRITY_STATUS_MISMATCH = "mismatch"
_DEPLOY_WORKFLOW_INTEGRITY_STATUS_MISSING = "missing"
_DEPLOY_WORKFLOW_INTEGRITY_REASON_SIGNATURE_MISSING = "managed_workflow_signature_missing"
_DEPLOY_WORKFLOW_INTEGRITY_REASON_SIGNATURE_MISMATCH = "managed_workflow_signature_mismatch"
_DEPLOY_RUNTIME_REASON_BACKENDCONFIG_HEALTH_CHECK_MISMATCH = "backendconfig_health_check_mismatch"
_DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY = "ingress_backend_unhealthy"
_DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_502 = "ingress_backend_502"
_DEPLOY_RUNTIME_REASON_SERVICE_HAS_NO_READY_ENDPOINTS = "service_has_no_ready_endpoints"
_DEPLOY_RUNTIME_REASON_POD_READY_BUT_INGRESS_BACKEND_UNHEALTHY = "pod_ready_but_ingress_backend_unhealthy"
_DEPLOY_RUNTIME_REASON_SERVICE_ENDPOINT_UNHEALTHY = "service_endpoint_unhealthy"
_DEPLOY_RUNTIME_REASON_SERVICE_ENDPOINT_MISSING = "service_endpoint_missing"
_DEPLOY_RUNTIME_REASON_BACKEND_CONFIG_HEALTHCHECK_UNHEALTHY = "backend_config_healthcheck_unhealthy"
_DEPLOY_RUNTIME_REASON_IN_CLUSTER_SERVICE_CURL_FAILED = "in_cluster_service_curl_failed"
_DEPLOY_RUNTIME_REASON_IN_CLUSTER_SERVICE_CURL_FAILED_AFTER_RETRIES = "in_cluster_service_curl_failed_after_retries"
_DEPLOY_RUNTIME_REASON_IN_CLUSTER_SERVICE_PROBE_TIMEOUT = "in_cluster_service_probe_timeout"
_DEPLOY_RUNTIME_REASON_NETWORK_POLICY_MAY_BLOCK_SERVICE_PROBE = "network_policy_may_block_service_probe"
_DEPLOY_RUNTIME_REASON_MANAGED_CERTIFICATE_METADATA_UNAVAILABLE = "managed_certificate_metadata_unavailable"
_DEPLOY_RUNTIME_REASON_PRE_SHARED_CERT_METADATA_MISMATCH = "pre_shared_cert_metadata_mismatch"
_DEPLOY_RUNTIME_REASON_RUNTIME_DEPLOYMENT_MISSING_AFTER_APPLY = "runtime_deployment_missing_after_apply"
_DEPLOY_RUNTIME_REASON_RUNTIME_SERVICE_MISSING_AFTER_APPLY = "runtime_service_missing_after_apply"
_DEPLOY_RUNTIME_REASON_RUNTIME_INGRESS_MISSING_AFTER_APPLY = "runtime_ingress_missing_after_apply"
_DEPLOY_RUNTIME_REASON_RUNTIME_MANAGED_CERTIFICATE_MISSING_AFTER_APPLY = (
    "runtime_managed_certificate_missing_after_apply"
)
_DEPLOY_RUNTIME_REASON_RUNTIME_FRONTEND_CONFIG_MISSING_AFTER_APPLY = "runtime_frontend_config_missing_after_apply"
_DEPLOY_RUNTIME_REASON_RUNTIME_BACKEND_CONFIG_MISSING_AFTER_APPLY = "runtime_backend_config_missing_after_apply"
_DEPLOY_RUNTIME_REASON_RUNTIME_SERVICE_ENDPOINTS_MISSING_AFTER_APPLY = "runtime_service_endpoints_missing_after_apply"
_DEPLOY_RUNTIME_REASON_SERVICE_PROBE_WAITING_FOR_CONVERGENCE = "service_probe_waiting_for_convergence"
_DEPLOY_RUNTIME_REASON_INGRESS_NEG_CONVERGENCE_PENDING = "ingress_neg_convergence_pending"
_DEPLOY_RUNTIME_REASON_INGRESS_STATUS_IP_STALE_OR_MISMATCHED = "ingress_status_ip_stale_or_mismatched"
_DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY_AFTER_ROLLOUT = "ingress_backend_unhealthy_after_rollout"
_DEPLOY_RUNTIME_REASON_PUBLIC_IMAGE_PULL_FAILED = "public_image_pull_failed"
_DEPLOY_RUNTIME_REASON_PRIVATE_IMAGE_PULL_FORBIDDEN = "private_image_pull_forbidden"
_DEPLOY_RUNTIME_REASON_REACHABLE_BUT_TLS_MISMATCH = "reachable_but_tls_certificate_mismatch"
_DEPLOY_RUNTIME_REASON_INGRESS_PENDING_BUT_HOST_REACHABLE = "ingress_address_pending_but_hostname_reachable"
_DEPLOY_RUNTIME_REASON_HTTPS_PROBE_TIMEOUT = "https_probe_timeout"
_DEPLOY_RUNTIME_REASON_HTTPS_PROBE_EMPTY_REPLY = "https_probe_empty_reply"
_DEPLOY_RUNTIME_REASON_HTTPS_PROBE_NOT_ATTEMPTED = "https_probe_not_attempted"
_DEPLOY_RUNTIME_REASON_HTTPS_PROBE_FAILED_AFTER_CONTROL_PLANE_READY = "https_probe_failed_after_control_plane_ready"
_DEPLOY_RUNTIME_REASON_RUNTIME_READINESS_UNKNOWN_FAILURE = "runtime_readiness_unknown_failure"
_DEPLOY_RUNTIME_REASON_MANAGED_DEPLOY_WORKFLOW_TEMPLATE_STALE = "managed_deploy_workflow_template_stale"
_DEPLOY_GKE_CONFIG_MISSING_REASON_PRIORITY: tuple[str, ...] = (
    _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME,
    _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION,
    _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID,
)
_DEFAULT_NAMESPACE_ISOLATION_DEFAULTS = {
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
    "managed_preview_endpoint": {
        "mode": _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO,
        "shared_preview_static_ip_name": None,
    },
}


def _normalize_managed_gke_config(value: object | None) -> dict[str, str | None]:
    normalized: dict[str, str | None] = {
        _MANAGED_GKE_CONFIG_CLUSTER_NAME: None,
        _MANAGED_GKE_CONFIG_CLUSTER_LOCATION: None,
        _MANAGED_GKE_CONFIG_PROJECT_ID: None,
    }
    if not isinstance(value, dict):
        return normalized
    cluster_name = (_coerce_string(value.get(_MANAGED_GKE_CONFIG_CLUSTER_NAME)) or "").strip().lower()
    cluster_location = (_coerce_string(value.get(_MANAGED_GKE_CONFIG_CLUSTER_LOCATION)) or "").strip().lower()
    project_id = (_coerce_string(value.get(_MANAGED_GKE_CONFIG_PROJECT_ID)) or "").strip().lower()
    normalized[_MANAGED_GKE_CONFIG_CLUSTER_NAME] = cluster_name or None
    normalized[_MANAGED_GKE_CONFIG_CLUSTER_LOCATION] = cluster_location or None
    normalized[_MANAGED_GKE_CONFIG_PROJECT_ID] = project_id or None
    return normalized


def _yaml_quote_scalar(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _managed_image_pull_secret_required(config_payload: dict[str, object] | None) -> bool:
    if not isinstance(config_payload, dict):
        return True
    return _coerce_bool(config_payload.get("private_image_auth_required"), default=True)


def _safe_identifier_fragment(value: object, *, fallback: str, max_length: int = 80) -> str:
    raw = _coerce_string(value) or ""
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


def _normalize_managed_site_static_ip_label_value(value: object) -> str | None:
    normalized = _safe_identifier_fragment(value, fallback="", max_length=63).strip("-")
    return normalized or None


def build_managed_site_static_ip_labels(
    *,
    repo_name: object,
    site_id: object | None = None,
    preview_hostname: object | None = None,
) -> dict[str, str]:
    normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower().rstrip(".")
    ownership_labels: dict[str, str] = {
        _MBSRN_MANAGED_STATIC_IP_LABEL_MANAGED_BY: _MBSRN_MANAGED_LABEL,
    }
    normalized_site_id = _normalize_managed_site_static_ip_label_value(site_id)
    normalized_preview_hostname_label = _normalize_managed_site_static_ip_label_value(
        normalized_preview_hostname
    )
    normalized_repo_name = _normalize_managed_site_static_ip_label_value(repo_name)
    if normalized_site_id:
        ownership_labels[_MBSRN_MANAGED_STATIC_IP_LABEL_SITE_ID] = normalized_site_id
    if normalized_preview_hostname_label:
        ownership_labels[_MBSRN_MANAGED_STATIC_IP_LABEL_PREVIEW_HOSTNAME] = (
            normalized_preview_hostname_label
        )
    if normalized_repo_name:
        ownership_labels[_MBSRN_MANAGED_STATIC_IP_LABEL_REPO] = normalized_repo_name
    return ownership_labels


def build_managed_certificate_ownership_labels(
    *,
    repo_name: object,
    site_id: object | None = None,
    preview_hostname: object | None = None,
) -> dict[str, str]:
    normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower().rstrip(".")
    normalized_repo_name = (_coerce_string(repo_name) or "").strip()
    if "/" in normalized_repo_name:
        normalized_repo_name = normalized_repo_name.rsplit("/", 1)[-1]
    ownership_labels: dict[str, str] = {
        "app.kubernetes.io/managed-by": _MBSRN_MANAGED_LABEL,
        "app.kubernetes.io/name": "site-web",
    }
    normalized_site_id = _safe_identifier_fragment(site_id, fallback="", max_length=60).strip("-")
    normalized_repo_fragment = _safe_identifier_fragment(normalized_repo_name, fallback="", max_length=40).strip("-")
    if normalized_repo_fragment:
        ownership_labels["mbsrn.io/repo"] = normalized_repo_fragment
    if normalized_site_id:
        ownership_labels["mbsrn.io/site-id"] = normalized_site_id
    if normalized_preview_hostname:
        ownership_labels["mbsrn.io/preview-hostname"] = normalized_preview_hostname
    return ownership_labels


def _managed_certificate_ownership_is_verified(
    *,
    managed_certificate_payload: dict[str, object],
    repo_name: object,
    site_id: object | None = None,
    preview_hostname: object | None = None,
) -> bool:
    expected_labels = build_managed_certificate_ownership_labels(
        repo_name=repo_name,
        site_id=site_id,
        preview_hostname=preview_hostname,
    )
    metadata_payload = managed_certificate_payload.get("metadata")
    labels_payload = metadata_payload.get("labels") if isinstance(metadata_payload, dict) else None
    if not isinstance(labels_payload, dict):
        return False
    for key, expected_value in expected_labels.items():
        observed_value = _coerce_string(labels_payload.get(key))
        if not observed_value:
            return False
        normalized_observed_value = observed_value.strip().lower().rstrip(".")
        normalized_expected_value = expected_value.strip().lower().rstrip(".")
        if normalized_observed_value != normalized_expected_value:
            return False
    return True


def derive_site_kubernetes_namespace(*, repo_name: object, site_id: object | None = None) -> tuple[str, str]:
    primary = _safe_identifier_fragment(repo_name, fallback="", max_length=63).strip("-")
    if primary:
        return primary, "repo_name"
    secondary = _safe_identifier_fragment(site_id, fallback="", max_length=63).strip("-")
    if secondary:
        return secondary, "site_id"
    raise SEOMigrationGitHubPublisherError(
        code="namespace_invalid",
        safe_message="Kubernetes namespace could not be derived from deploy target metadata.",
        stage="workflow_provisioning",
    )


def derive_site_preview_hostname(*, repo_name: object, site_id: object | None = None) -> tuple[str, str]:
    namespace, namespace_source = derive_site_kubernetes_namespace(repo_name=repo_name, site_id=site_id)
    host_label = _safe_identifier_fragment(namespace, fallback="", max_length=63).strip("-")
    if not host_label:
        raise SEOMigrationGitHubPublisherError(
            code="preview_hostname_invalid",
            safe_message="Preview hostname could not be derived from deploy target metadata.",
            stage="workflow_provisioning",
        )
    return f"{host_label}.{_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX}", namespace_source


def derive_site_preview_certificate_name(*, repo_name: object, site_id: object | None = None) -> tuple[str, str]:
    namespace, namespace_source = derive_site_kubernetes_namespace(repo_name=repo_name, site_id=site_id)
    suffix_budget = 63 - len(_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME_PREFIX) - 1
    suffix = _safe_identifier_fragment(namespace, fallback="", max_length=max(suffix_budget, 1)).strip("-")
    if not suffix:
        raise SEOMigrationGitHubPublisherError(
            code="preview_certificate_name_invalid",
            safe_message="Preview certificate name could not be derived from deploy target metadata.",
            stage="workflow_provisioning",
        )
    certificate_name = f"{_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME_PREFIX}-{suffix}"[:63].strip("-")
    if not certificate_name:
        raise SEOMigrationGitHubPublisherError(
            code="preview_certificate_name_invalid",
            safe_message="Preview certificate name could not be derived from deploy target metadata.",
            stage="workflow_provisioning",
        )
    return certificate_name, namespace_source


def _derive_site_scoped_resource_name(
    *,
    prefix: str,
    repo_name: object,
    site_id: object | None = None,
) -> tuple[str, str]:
    namespace, namespace_source = derive_site_kubernetes_namespace(repo_name=repo_name, site_id=site_id)
    suffix_budget = 63 - len(prefix) - 1
    suffix = _safe_identifier_fragment(namespace, fallback="", max_length=max(suffix_budget, 1)).strip("-")
    if not suffix:
        raise SEOMigrationGitHubPublisherError(
            code="managed_resource_name_invalid",
            safe_message="Managed resource name could not be derived from deploy target metadata.",
            stage="workflow_provisioning",
        )
    resource_name = f"{prefix}-{suffix}"[:63].strip("-")
    if not resource_name:
        raise SEOMigrationGitHubPublisherError(
            code="managed_resource_name_invalid",
            safe_message="Managed resource name could not be derived from deploy target metadata.",
            stage="workflow_provisioning",
        )
    return resource_name, namespace_source


def derive_site_preview_frontend_config_name(*, repo_name: object, site_id: object | None = None) -> tuple[str, str]:
    return _derive_site_scoped_resource_name(
        prefix=_MBSRN_MANAGED_FRONTEND_CONFIG_NAME_PREFIX,
        repo_name=repo_name,
        site_id=site_id,
    )


def derive_site_preview_backend_config_name(*, repo_name: object, site_id: object | None = None) -> tuple[str, str]:
    return _derive_site_scoped_resource_name(
        prefix=_MBSRN_MANAGED_BACKEND_CONFIG_NAME_PREFIX,
        repo_name=repo_name,
        site_id=site_id,
    )


def derive_site_preview_static_ip_name(*, repo_name: object, site_id: object | None = None) -> tuple[str, str]:
    return _derive_site_scoped_resource_name(
        prefix=_MBSRN_MANAGED_PREVIEW_STATIC_IP_NAME_PREFIX,
        repo_name=repo_name,
        site_id=site_id,
    )


def resolve_managed_preview_endpoint_configuration(
    *,
    repo_name: object,
    site_id: object | None,
    preview_hostname: object | None,
    namespace_isolation_defaults: dict[str, object] | None,
) -> dict[str, object]:
    normalized_defaults = _normalize_namespace_isolation_defaults(namespace_isolation_defaults)
    endpoint_settings = normalized_defaults.get("managed_preview_endpoint")
    endpoint_payload = endpoint_settings if isinstance(endpoint_settings, dict) else {}
    requested_mode = (
        _coerce_string(endpoint_payload.get("mode")) or _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO
    ).strip().lower()
    if requested_mode not in _MANAGED_PREVIEW_ENDPOINT_MODE_VALUES:
        requested_mode = _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO
    shared_preview_static_ip_name = _coerce_string(endpoint_payload.get("shared_preview_static_ip_name"))
    if shared_preview_static_ip_name:
        shared_preview_static_ip_name = shared_preview_static_ip_name.strip().lower()
    else:
        shared_preview_static_ip_name = None

    preview_hostname_normalized = (_coerce_string(preview_hostname) or "").strip().lower().rstrip(".")
    managed_preview_suffix = f".{_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX}"
    preview_hostname_is_managed = bool(
        preview_hostname_normalized and preview_hostname_normalized.endswith(managed_preview_suffix)
    )

    per_site_static_ip_name, per_site_static_ip_source = derive_site_preview_static_ip_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    effective_mode = _MANAGED_PREVIEW_ENDPOINT_MODE_DEDICATED_STATIC_IP
    if requested_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY:
        effective_mode = _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY
    elif requested_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_DEDICATED_STATIC_IP:
        effective_mode = _MANAGED_PREVIEW_ENDPOINT_MODE_DEDICATED_STATIC_IP
    elif preview_hostname_is_managed and shared_preview_static_ip_name:
        effective_mode = _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY

    expected_static_ip_name = (
        shared_preview_static_ip_name
        if effective_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY
        else per_site_static_ip_name
    )
    expected_static_ip_source = (
        "managed_preview_endpoint.shared_preview_static_ip_name"
        if effective_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY
        else per_site_static_ip_source
    )
    reason_code: str | None = None
    if effective_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY:
        if not preview_hostname_normalized:
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_HOSTNAME_MISSING
        elif not shared_preview_static_ip_name:
            reason_code = _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_MISSING
            expected_static_ip_name = per_site_static_ip_name
            expected_static_ip_source = per_site_static_ip_source

    return {
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "uses_shared_preview_gateway": effective_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_SHARED_GATEWAY,
        "requires_dedicated_static_ip": effective_mode == _MANAGED_PREVIEW_ENDPOINT_MODE_DEDICATED_STATIC_IP,
        "preview_hostname": preview_hostname_normalized or None,
        "preview_hostname_is_managed": preview_hostname_is_managed,
        "shared_preview_static_ip_name": shared_preview_static_ip_name,
        "expected_static_ip_name": expected_static_ip_name,
        "expected_static_ip_name_source": expected_static_ip_source,
        "reason_code": reason_code,
    }


def _derive_site_runtime_image_repository(*, repo_owner: object, repo_name: object) -> str:
    owner_fragment = _safe_identifier_fragment(repo_owner, fallback="", max_length=80).strip("-")
    if not owner_fragment:
        raise SEOMigrationGitHubPublisherError(
            code="runtime_image_repository_invalid",
            safe_message="Managed site runtime image repository could not be derived from target repository owner.",
            stage="workflow_provisioning",
        )
    repo_fragment = _safe_identifier_fragment(repo_name, fallback="", max_length=80).strip("-")
    if not repo_fragment:
        raise SEOMigrationGitHubPublisherError(
            code="runtime_image_repository_invalid",
            safe_message="Managed site runtime image repository could not be derived from target repository name.",
            stage="workflow_provisioning",
        )
    return f"ghcr.io/{owner_fragment}/{repo_fragment}-{_MBSRN_MANAGED_SITE_WEB_IMAGE_REPO_NAME}"


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _normalize_namespace_isolation_defaults(value: object | None) -> dict[str, object]:
    normalized = json.loads(json.dumps(_DEFAULT_NAMESPACE_ISOLATION_DEFAULTS))
    if not isinstance(value, dict):
        return normalized

    resource_quota = value.get("resource_quota")
    if isinstance(resource_quota, dict):
        normalized_rq = normalized["resource_quota"]
        if isinstance(normalized_rq, dict):
            normalized_rq["enabled"] = _coerce_bool(resource_quota.get("enabled"), default=False)
            for key in (
                "requests_cpu",
                "requests_memory",
                "limits_cpu",
                "limits_memory",
                "pods",
                "services",
                "configmaps",
                "secrets",
                "persistentvolumeclaims",
            ):
                if key in resource_quota and resource_quota.get(key) is not None:
                    normalized_rq[key] = str(resource_quota.get(key)).strip()

    limit_range = value.get("limit_range")
    if isinstance(limit_range, dict):
        normalized_lr = normalized["limit_range"]
        if isinstance(normalized_lr, dict):
            normalized_lr["enabled"] = _coerce_bool(limit_range.get("enabled"), default=False)
            for key in (
                "default_cpu",
                "default_memory",
                "default_request_cpu",
                "default_request_memory",
                "min_cpu",
                "min_memory",
                "max_cpu",
                "max_memory",
            ):
                if key in limit_range and limit_range.get(key) is not None:
                    normalized_lr[key] = str(limit_range.get(key)).strip()

    network_policy = value.get("network_policy")
    if isinstance(network_policy, dict):
        normalized_np = normalized["network_policy"]
        if isinstance(normalized_np, dict):
            normalized_np["enabled"] = _coerce_bool(network_policy.get("enabled"), default=False)
            mode = _coerce_string(network_policy.get("mode")) or "default_deny_ingress"
            normalized_np["mode"] = mode.strip().lower()[:80] or "default_deny_ingress"

    managed_preview_endpoint = value.get("managed_preview_endpoint")
    if isinstance(managed_preview_endpoint, dict):
        normalized_endpoint = normalized["managed_preview_endpoint"]
        if isinstance(normalized_endpoint, dict):
            mode = (_coerce_string(managed_preview_endpoint.get("mode")) or _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO).strip().lower()
            if mode not in _MANAGED_PREVIEW_ENDPOINT_MODE_VALUES:
                mode = _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO
            normalized_endpoint["mode"] = mode
            shared_preview_static_ip_name = _coerce_string(
                managed_preview_endpoint.get("shared_preview_static_ip_name")
            )
            if shared_preview_static_ip_name:
                shared_preview_static_ip_name = shared_preview_static_ip_name.strip().lower()
                shared_preview_static_ip_name = re.sub(r"[^a-z0-9-]", "-", shared_preview_static_ip_name)
                while "--" in shared_preview_static_ip_name:
                    shared_preview_static_ip_name = shared_preview_static_ip_name.replace("--", "-")
                shared_preview_static_ip_name = shared_preview_static_ip_name.strip("-")
            normalized_endpoint["shared_preview_static_ip_name"] = (
                shared_preview_static_ip_name[:63] if shared_preview_static_ip_name else None
            )

    return normalized


def _managed_policy_expectations(namespace_isolation_defaults: dict[str, object] | None) -> dict[str, bool]:
    normalized = _normalize_namespace_isolation_defaults(namespace_isolation_defaults)
    resource_quota = normalized.get("resource_quota")
    limit_range = normalized.get("limit_range")
    network_policy = normalized.get("network_policy")
    return {
        "resource_quota_expected": _coerce_bool(
            resource_quota.get("enabled") if isinstance(resource_quota, dict) else None,
            default=False,
        ),
        "limit_range_expected": _coerce_bool(
            limit_range.get("enabled") if isinstance(limit_range, dict) else None,
            default=False,
        ),
        "network_policy_expected": _coerce_bool(
            network_policy.get("enabled") if isinstance(network_policy, dict) else None,
            default=False,
        ),
    }


def _expected_managed_manifest_paths(namespace_isolation_defaults: dict[str, object] | None) -> tuple[str, ...]:
    expectations = _managed_policy_expectations(namespace_isolation_defaults)
    expected_paths: list[str] = list(_MBSRN_MANAGED_CORE_MANIFEST_PATHS)
    if expectations.get("resource_quota_expected"):
        expected_paths.append(_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH)
    if expectations.get("limit_range_expected"):
        expected_paths.append(_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH)
    if expectations.get("network_policy_expected"):
        expected_paths.append(_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH)
    return tuple(expected_paths)


def _normalize_workflow_yaml_for_signature(*, workflow_yaml: str) -> str:
    normalized = str(workflow_yaml or "").replace("\r\n", "\n").replace("\r", "\n")
    signature_line_prefix = f"# {_MBSRN_MANAGED_WORKFLOW_SIGNATURE_MARKER}".lower()
    normalized_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        if raw_line.strip().lower().startswith(signature_line_prefix):
            continue
        normalized_lines.append(raw_line.rstrip())
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def _compute_managed_workflow_signature(*, workflow_yaml: str) -> str:
    normalized_for_signature = _normalize_workflow_yaml_for_signature(workflow_yaml=workflow_yaml)
    return hashlib.sha256(normalized_for_signature.encode("utf-8")).hexdigest()


def _embed_managed_workflow_signature(*, workflow_yaml: str) -> str:
    normalized_yaml = str(workflow_yaml or "")
    if not normalized_yaml:
        return normalized_yaml
    signature = _compute_managed_workflow_signature(workflow_yaml=normalized_yaml)
    signature_line = f"# {_MBSRN_MANAGED_WORKFLOW_SIGNATURE_MARKER} {signature}\n"
    marker_line = f"# {_MBSRN_MANAGED_WORKFLOW_MARKER}\n"
    if normalized_yaml.startswith(marker_line):
        return marker_line + signature_line + normalized_yaml[len(marker_line) :]
    return signature_line + normalized_yaml


def _extract_managed_workflow_signature(*, workflow_yaml: str) -> str | None:
    signature_line_prefix = f"# {_MBSRN_MANAGED_WORKFLOW_SIGNATURE_MARKER}".lower()
    for raw_line in str(workflow_yaml or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if not stripped.lower().startswith(signature_line_prefix):
            continue
        signature_value = stripped[len(signature_line_prefix) :].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", signature_value):
            return signature_value
        return None
    return None


def _truncate_workflow_signature_for_log(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    lowered = normalized.strip().lower()
    if len(lowered) <= 12:
        return lowered
    return lowered[:12]


def _derive_managed_workflow_deploy_auth_mode(*, workflow_content: str) -> str:
    normalized = str(workflow_content or "").lower()
    if "secrets.gcp_deploy_key" in normalized:
        return _DEPLOY_AUTH_MODE_TARGET_REPO_SECRET
    if "workload_identity_provider:" in normalized and "service_account:" in normalized:
        return _DEPLOY_AUTH_MODE_GITHUB_OIDC
    return _DEPLOY_AUTH_MODE_CONTROL_PLANE


def _managed_workflow_requires_target_repo_deploy_secret(*, deploy_auth_mode: str) -> bool:
    return (str(deploy_auth_mode or "").strip().lower()) == _DEPLOY_AUTH_MODE_TARGET_REPO_SECRET


def _render_managed_deploy_workflow_yaml(
    *,
    workflow_id: str,
    repo_owner: str,
    repo_name: str,
    branch: str,
    deploy_workflow_mode: str,
    target_environment_key: str,
    target_environment_source: str,
    managed_gke_config: dict[str, object] | None,
    kubernetes_namespace: str,
    namespace_source: str,
    preview_hostname: str,
    namespace_isolation_defaults: dict[str, object] | None = None,
    private_image_auth_required: bool = False,
    site_id: str | None = None,
) -> str:
    normalized_workflow_id = str(workflow_id or "").strip() or "deploy-www-prod.yml"
    # Keep mode normalization deterministic even though generation currently has
    # a single production-safe template contract.
    _ = _normalize_deploy_workflow_mode(deploy_workflow_mode)
    normalized_environment_key = _safe_identifier_fragment(
        target_environment_key,
        fallback="gke-prod",
        max_length=60,
    )
    normalized_environment_source = _normalize_target_environment_source(target_environment_source)
    normalized_managed_gke_config = _normalize_managed_gke_config(managed_gke_config)
    cluster_name = normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_NAME)
    cluster_location = normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_CLUSTER_LOCATION)
    project_id = normalized_managed_gke_config.get(_MANAGED_GKE_CONFIG_PROJECT_ID)
    rendered_cluster_name = (
        _yaml_quote_scalar(cluster_name)
        if cluster_name
        else f"${{{{ vars.{_GKE_ENV_CLUSTER_NAME} || secrets.{_GKE_ENV_CLUSTER_NAME} }}}}"
    )
    rendered_cluster_location = (
        _yaml_quote_scalar(cluster_location)
        if cluster_location
        else f"${{{{ vars.{_GKE_ENV_CLUSTER_LOCATION} || secrets.{_GKE_ENV_CLUSTER_LOCATION} }}}}"
    )
    rendered_project_id = (
        _yaml_quote_scalar(project_id)
        if project_id
        else f"${{{{ vars.{_GKE_ENV_PROJECT_ID} || secrets.{_GKE_ENV_PROJECT_ID} }}}}"
    )
    normalized_repo_fragment = _safe_identifier_fragment(repo_name, fallback="site")
    site_runtime_image_repository = _derive_site_runtime_image_repository(
        repo_owner=repo_owner,
        repo_name=repo_name,
    )
    normalized_site_fragment = _safe_identifier_fragment(site_id, fallback="workspace")
    normalized_namespace = _safe_identifier_fragment(
        kubernetes_namespace, fallback=normalized_repo_fragment, max_length=63
    )
    normalized_namespace_source = _safe_identifier_fragment(namespace_source, fallback="repo-name", max_length=40)
    normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower()
    preview_certificate_name, _ = derive_site_preview_certificate_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    frontend_config_name, _ = derive_site_preview_frontend_config_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    backend_config_name, _ = derive_site_preview_backend_config_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    preview_endpoint = resolve_managed_preview_endpoint_configuration(
        repo_name=repo_name,
        site_id=site_id,
        preview_hostname=normalized_preview_hostname,
        namespace_isolation_defaults=_normalize_namespace_isolation_defaults(namespace_isolation_defaults),
    )
    preview_static_ip_name = _coerce_string(preview_endpoint.get("expected_static_ip_name")) or ""
    preview_endpoint_mode = _coerce_string(preview_endpoint.get("effective_mode")) or _MANAGED_PREVIEW_ENDPOINT_MODE_AUTO
    preview_endpoint_uses_shared_gateway = bool(preview_endpoint.get("uses_shared_preview_gateway"))
    preview_static_ip_missing_reason = (
        _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_MISSING
        if preview_endpoint_uses_shared_gateway
        else _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_MISSING
    )
    preview_static_ip_missing_message = (
        "Expected shared preview gateway static IP must be created and assigned by admin before deploy."
        if preview_endpoint_uses_shared_gateway
        else "Expected per-site static IP must be created and assigned by admin before deploy."
    )
    normalized_name = f"MBSRN Deploy {normalized_repo_fragment}"
    private_image_auth_value = "true" if private_image_auth_required else "false"
    verify_pull_secret_step = ""
    if private_image_auth_required:
        verify_pull_secret_step = (
            "      - name: Verify GHCR image pull secret\n"
            "        run: |\n"
            "          set -euo pipefail\n"
            '          kubectl get secret ghcr-pull-secret --namespace "$K8S_NAMESPACE"\n'
        )
    workflow_yaml_unsigned = (
        f"# {_MBSRN_MANAGED_WORKFLOW_MARKER}\n"
        f"name: {normalized_name}\n"
        "\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      replace_existing_runtime:\n"
        "        description: Replace existing managed-site runtime resources before deploy\n"
        "        required: false\n"
        "        default: false\n"
        "        type: boolean\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "  packages: write\n"
        "  id-token: write\n"
        "\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    outputs:\n"
        "      live_url: ${{ steps.resolve_live_url.outputs.live_url }}\n"
        "      resolved_live_url: ${{ steps.resolve_live_url.outputs.resolved_live_url }}\n"
        "      deployed_url: ${{ steps.resolve_live_url.outputs.deployed_url }}\n"
        "      host_reachable: ${{ steps.resolve_live_url.outputs.host_reachable }}\n"
        "      host_reachability_scheme: ${{ steps.resolve_live_url.outputs.host_reachability_scheme }}\n"
        "      dns_record_matches_ingress: ${{ steps.resolve_live_url.outputs.dns_record_matches_ingress }}\n"
        "      dns_expected_ip: ${{ steps.resolve_live_url.outputs.dns_expected_ip }}\n"
        "      dns_observed_ip: ${{ steps.resolve_live_url.outputs.dns_observed_ip }}\n"
        "      expected_static_ip_address: ${{ steps.resolve_live_url.outputs.expected_static_ip_address }}\n"
        "      static_ip_status: ${{ steps.resolve_live_url.outputs.static_ip_status }}\n"
        "      static_ip_users: ${{ steps.resolve_live_url.outputs.static_ip_users }}\n"
        "      tls_certificate_status: ${{ steps.resolve_live_url.outputs.tls_certificate_status }}\n"
        "      tls_domain_status: ${{ steps.resolve_live_url.outputs.tls_domain_status }}\n"
        "      ingress_status_ip: ${{ steps.resolve_live_url.outputs.ingress_status_ip }}\n"
        "      ingress_status_ip_matches_static_ip: ${{ steps.resolve_live_url.outputs.ingress_status_ip_matches_static_ip }}\n"
        "      static_ip_bound_to_expected_forwarding_rule: ${{ steps.resolve_live_url.outputs.static_ip_bound_to_expected_forwarding_rule }}\n"
        "      ingress_ip: ${{ steps.resolve_live_url.outputs.ingress_ip }}\n"
        "      ingress_conflict_detected: ${{ steps.resolve_live_url.outputs.ingress_conflict_detected }}\n"
        "      cert_identity_valid: ${{ steps.resolve_live_url.outputs.cert_identity_valid }}\n"
        "      https_probe_error_summary: ${{ steps.resolve_live_url.outputs.https_probe_error_summary }}\n"
        "      deploy_https_ready: ${{ steps.resolve_live_url.outputs.deploy_https_ready }}\n"
        f"      {_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}: ${{{{ steps.resolve_live_url.outputs.{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY} }}}}\n"
        "      site_runtime_image_reference: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}\n"
        "      site_runtime_image_selection_mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}\n"
        "      site_runtime_image_repository: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_repository }}\n"
        "      site_runtime_image_tag: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_tag }}\n"
        "      site_runtime_image_tag_source: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_tag_source }}\n"
        "      site_runtime_source_commit: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_source_commit }}\n"
        "      site_runtime_content_source: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_content_source }}\n"
        "      managed_site_runtime_replace_performed: ${{ steps.replace_managed_runtime.outputs.managed_site_runtime_replace_performed }}\n"
        "      managed_site_runtime_replace_scope: ${{ steps.replace_managed_runtime.outputs.managed_site_runtime_replace_scope }}\n"
        "      managed_site_runtime_replace_deleted_kinds: ${{ steps.replace_managed_runtime.outputs.managed_site_runtime_replace_deleted_kinds }}\n"
        "    environment:\n"
        f"      name: {normalized_environment_key}\n"
        "      url: ${{ steps.resolve_live_url.outputs.resolved_live_url }}\n"
        "    env:\n"
        f"      K8S_NAMESPACE: {normalized_namespace}\n"
        f"      MBSRN_NAMESPACE_SOURCE: {normalized_namespace_source}\n"
        f"      MBSRN_TARGET_ENVIRONMENT_KEY: {normalized_environment_key}\n"
        f"      MBSRN_TARGET_ENVIRONMENT_SOURCE: {normalized_environment_source}\n"
        f"      MBSRN_SITE_IDENTITY: {normalized_site_fragment}\n"
        f"      MBSRN_PREVIEW_HOSTNAME: {normalized_preview_hostname}\n"
        f"      MBSRN_PREVIEW_ENDPOINT_MODE: {preview_endpoint_mode}\n"
        "      MBSRN_REPLACE_EXISTING_RUNTIME: ${{ github.event.inputs.replace_existing_runtime || 'false' }}\n"
        f"      MBSRN_PREVIEW_CERTIFICATE_NAME: {preview_certificate_name}\n"
        f"      MBSRN_PREVIEW_STATIC_IP_NAME: {preview_static_ip_name}\n"
        f"      MBSRN_FRONTEND_CONFIG_NAME: {frontend_config_name}\n"
        f"      MBSRN_BACKEND_CONFIG_NAME: {backend_config_name}\n"
        f"      SITE_WEB_IMAGE_REPOSITORY: {site_runtime_image_repository}\n"
        "      SITE_WEB_IMAGE_TAG: ${{ vars.MBSRN_SITE_WEB_IMAGE_TAG || vars.SITE_WEB_IMAGE_TAG || secrets.MBSRN_SITE_WEB_IMAGE_TAG || secrets.SITE_WEB_IMAGE_TAG || '' }}\n"
        f'      PRIVATE_IMAGE_AUTH_REQUIRED: "{private_image_auth_value}"\n'
        f"      GKE_CLUSTER_NAME: {rendered_cluster_name}\n"
        f"      GKE_CLUSTER_LOCATION: {rendered_cluster_location}\n"
        f"      GKE_PROJECT_ID: {rendered_project_id}\n"
        "    steps:\n"
        "      - name: Checkout repository\n"
        "        uses: actions/checkout@v4\n"
        "      - name: Prepare managed site runtime build context\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          rm -rf site-runtime/context\n"
        "          mkdir -p site-runtime/context\n"
        "          rsync -a --delete \\\n"
        "            --exclude '.git/' \\\n"
        "            --exclude '.github/' \\\n"
        "            --exclude 'k8s/' \\\n"
        "            --exclude 'site-runtime/' \\\n"
        "            --exclude 'mbsrn.key' \\\n"
        "            --exclude 'README.md' \\\n"
        "            --exclude 'LICENSE' \\\n"
        "            --exclude '.gitignore' \\\n"
        "            ./ site-runtime/context/\n"
        "      - name: Login to GHCR\n"
        "        uses: docker/login-action@v3\n"
        "        with:\n"
        "          registry: ghcr.io\n"
        "          username: ${{ github.actor }}\n"
        "          password: ${{ secrets.GITHUB_TOKEN }}\n"
        "      - name: Build and push managed site runtime image\n"
        "        uses: docker/build-push-action@v6\n"
        "        with:\n"
        "          context: site-runtime\n"
        "          file: site-runtime/Dockerfile\n"
        "          push: true\n"
        "          provenance: false\n"
        "          tags: |\n"
        "            ${{ env.SITE_WEB_IMAGE_REPOSITORY }}:${{ github.sha }}\n"
        "            ${{ env.SITE_WEB_IMAGE_REPOSITORY }}:latest\n"
        "      - name: Validate GCP credentials\n"
        "        run: |\n"
        f'          if [ -z "${{{{ secrets.{_MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME} }}}}" ]; then\n'
        f'            echo "Missing {_MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME} secret"\n'
        '            echo "deploy_runtime_reason_code=target_repo_deploy_secret_missing"\n'
        f'            echo "deploy_runtime_reason_message=Managed deploy workflow requires target repo secret {_MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME}."\n'
        '            echo "deploy_runtime_failure_stage=workflow_execution"\n'
        "            exit 1\n"
        "          fi\n"
        "      - name: Validate GKE environment config\n"
        "        run: |\n"
        '          if [ -z "$GKE_CLUSTER_NAME" ]; then\n'
        '            echo "Missing managed GKE cluster name (admin config or legacy repo fallback)."\n'
        '            echo "deploy_runtime_reason_code=missing_cluster_name"\n'
        '            echo "deploy_runtime_reason_message=Managed deploy workflow missing required GKE cluster name configuration."\n'
        '            echo "deploy_runtime_failure_stage=workflow_execution"\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ -z "$GKE_CLUSTER_LOCATION" ]; then\n'
        '            echo "Missing managed GKE cluster location (admin config or legacy repo fallback)."\n'
        '            echo "deploy_runtime_reason_code=missing_cluster_location"\n'
        '            echo "deploy_runtime_reason_message=Managed deploy workflow missing required GKE cluster location configuration."\n'
        '            echo "deploy_runtime_failure_stage=workflow_execution"\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ -z "$GKE_PROJECT_ID" ]; then\n'
        '            echo "Missing managed GKE project id (admin config or legacy repo fallback)."\n'
        '            echo "deploy_runtime_reason_code=missing_gcp_project_id"\n'
        '            echo "deploy_runtime_reason_message=Managed deploy workflow missing required GKE project id configuration."\n'
        '            echo "deploy_runtime_failure_stage=workflow_execution"\n'
        "            exit 1\n"
        "          fi\n"
        "      - name: Authenticate to GCP\n"
        "        uses: google-github-actions/auth@v2\n"
        "        with:\n"
        f"          credentials_json: ${{{{ secrets.{_MANAGED_DEPLOY_TARGET_REPO_SECRET_NAME} }}}}\n"
        "          create_credentials_file: true\n"
        "          export_environment_variables: true\n"
        "      - name: Get GKE credentials\n"
        "        uses: google-github-actions/get-gke-credentials@v2\n"
        "        with:\n"
        "          cluster_name: ${{ env.GKE_CLUSTER_NAME }}\n"
        "          location: ${{ env.GKE_CLUSTER_LOCATION }}\n"
        "          project_id: ${{ env.GKE_PROJECT_ID }}\n"
        "      - name: Verify expected preview ingress static IP exists\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        '          if ! gcloud compute addresses describe "$MBSRN_PREVIEW_STATIC_IP_NAME" --global --project "$GKE_PROJECT_ID" >/dev/null 2>&1; then\n'
        f'            echo "deploy_runtime_reason_code={preview_static_ip_missing_reason}"\n'
        f'            echo "deploy_runtime_reason_message={preview_static_ip_missing_message}"\n'
        '            echo "deploy_runtime_failure_stage=ingress_verify"\n'
        '            echo "expected_static_ip_name=$MBSRN_PREVIEW_STATIC_IP_NAME"\n'
        '            echo "preview_endpoint_mode=$MBSRN_PREVIEW_ENDPOINT_MODE"\n'
        '            echo "gcp_project_id=$GKE_PROJECT_ID"\n'
        "            exit 1\n"
        "          fi\n"
        "      - name: Ensure namespace exists\n"
        "        run: kubectl apply -f k8s/namespace.yaml\n"
        f"{verify_pull_secret_step}"
        "      - name: Ensure managed-site endpoint prerequisites\n"
        "        id: ensure_managed_endpoint_prerequisites\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        '          endpoint_prerequisite_resource_kinds="managedcertificate,dns_record,global_static_ip"\n'
        '          runtime_resource_kinds="ingress,frontendconfig,backendconfig,service,deployment,networkpolicy"\n'
        "          fail_endpoint_prerequisite() {\n"
        '            local reason_code="$1"\n'
        '            local reason_message="$2"\n'
        '            local managed_certificate_state="${3:-unknown}"\n'
        '            local managed_certificate_status="${4:-}"\n'
        '            echo "deploy_runtime_reason_code=${reason_code}"\n'
        '            echo "deploy_runtime_reason_message=${reason_message}"\n'
        '            echo "deploy_runtime_failure_stage=ingress_verify"\n'
        '            echo "k8s_namespace=$K8S_NAMESPACE"\n'
        '            echo "ingress_name=site-web"\n'
        '            echo "preview_hostname=$MBSRN_PREVIEW_HOSTNAME"\n'
        '            echo "preview_endpoint_mode=$MBSRN_PREVIEW_ENDPOINT_MODE"\n'
        '            echo "expected_managed_certificate_name=$MBSRN_PREVIEW_CERTIFICATE_NAME"\n'
        '            echo "endpoint_prerequisite_resource_kinds=$endpoint_prerequisite_resource_kinds"\n'
        '            echo "runtime_resource_kinds=$runtime_resource_kinds"\n'
        '            echo "resolve_live_url_state_service_exists=unknown"\n'
        '            echo "resolve_live_url_state_endpoints_ready=unknown"\n'
        '            echo "resolve_live_url_state_managed_certificate_exists=$managed_certificate_state"\n'
        '            if [ -n "$managed_certificate_status" ]; then\n'
        '              echo "resolve_live_url_state_managed_certificate_status=$managed_certificate_status"\n'
        "            fi\n"
        '            echo "resolve_live_url_state_runtime_ready=false"\n'
        '            echo "resolve_live_url_state_ingress_address_resolved=false"\n'
        '            echo "resolve_live_url_state_deploy_https_ready=false"\n'
        '            echo "resolve_live_url_state_https_ready=false"\n'
        '            echo "resolve_live_url_state_runtime_ready_tls_pending=false"\n'
        '            echo "resolve_live_url_state_deploy_runtime_failure_stage=ingress_verify"\n'
        '            echo "resolve_live_url_state_deploy_runtime_reason_message=$reason_message"\n'
        f'            echo "resolve_live_url_state_{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}"\n'
        "            exit 1\n"
        "          }\n"
        "          wait_for_endpoint_prerequisite() {\n"
        '            local resource_kind="$1"\n'
        '            local resource_name="$2"\n'
        '            local max_attempts="$3"\n'
        '            local sleep_seconds="$4"\n'
        '            local reason_code="$5"\n'
        '            local reason_message="$6"\n'
        '            local managed_certificate_state="${7:-unknown}"\n'
        '            local managed_certificate_status="${8:-}"\n'
        '            local attempt=1\n'
        '            while [ "$attempt" -le "$max_attempts" ]; do\n'
        '              if kubectl get "$resource_kind" "$resource_name" --namespace "$K8S_NAMESPACE" >/dev/null 2>&1; then\n'
        "                return 0\n"
        "              fi\n"
        '              if [ "$attempt" -lt "$max_attempts" ]; then\n'
        '                sleep "$sleep_seconds"\n'
        "              fi\n"
        '              attempt=$((attempt + 1))\n'
        "            done\n"
        '            fail_endpoint_prerequisite "$reason_code" "$reason_message" "$managed_certificate_state" "$managed_certificate_status"\n'
        "          }\n"
        '          ingress_references_managed_certificate=false\n'
        '          if [ -f k8s/ingress.yaml ] && grep -q "networking.gke.io/managed-certificates:" k8s/ingress.yaml; then\n'
        '            ingress_references_managed_certificate=true\n'
        "          fi\n"
        '          if [ "$ingress_references_managed_certificate" != "true" ]; then\n'
        '            echo "managed_certificate_action=not_required" >> "$GITHUB_OUTPUT"\n'
        "            exit 0\n"
        "          fi\n"
        '          if [ ! -f k8s/managedcertificate.yaml ]; then\n'
        '            fail_endpoint_prerequisite "runtime_managed_certificate_missing_after_apply" "Ingress references a ManagedCertificate, but k8s/managedcertificate.yaml is missing from the managed runtime bundle." "false" "MISSING"\n'
        "          fi\n"
        '          managed_certificate_json="$(kubectl get managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" -o json 2>/dev/null || true)"\n'
        '          if [ -z "$managed_certificate_json" ]; then\n'
        '            fail_endpoint_prerequisite "runtime_managed_certificate_missing_after_apply" "ManagedCertificate is missing. Use the control-plane Provision TLS Certificate action before requesting GKE deploy." "false" "MISSING"\n'
        "          fi\n"
        '          cert_eval_output="$(MANAGED_CERTIFICATE_JSON="$managed_certificate_json" EXPECTED_PREVIEW_HOST="$MBSRN_PREVIEW_HOSTNAME" EXPECTED_CERT_NAME="$MBSRN_PREVIEW_CERTIFICATE_NAME" EXPECTED_SITE_ID="$MBSRN_SITE_IDENTITY" EXPECTED_REPO_NAME="$GITHUB_REPOSITORY" python - <<\'PY\'\n'
        "          import json\n"
        "          import os\n"
        "\n"
        "          def normalize_fragment(value: str, max_length: int) -> str:\n"
        "              cleaned = ''.join(character.lower() if character.isalnum() else '-' for character in value)\n"
        "              while '--' in cleaned:\n"
        "                  cleaned = cleaned.replace('--', '-')\n"
        "              cleaned = cleaned.strip('-')\n"
        "              return cleaned[:max_length]\n"
        "\n"
        "          raw = str(os.environ.get('MANAGED_CERTIFICATE_JSON') or '').strip()\n"
        "          expected_host = str(os.environ.get('EXPECTED_PREVIEW_HOST') or '').strip().lower().rstrip('.')\n"
        "          expected_cert_name = str(os.environ.get('EXPECTED_CERT_NAME') or '').strip().lower()\n"
        "          expected_site_id = normalize_fragment(str(os.environ.get('EXPECTED_SITE_ID') or '').strip(), 60)\n"
        "          expected_repo_name = str(os.environ.get('EXPECTED_REPO_NAME') or '').strip()\n"
        "          if '/' in expected_repo_name:\n"
        "              expected_repo_name = expected_repo_name.rsplit('/', 1)[-1]\n"
        "          expected_repo_label = normalize_fragment(expected_repo_name, 40)\n"
        "          payload = json.loads(raw) if raw else {}\n"
        "          metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}\n"
        "          labels_payload = metadata.get('labels') if isinstance(metadata.get('labels'), dict) else {}\n"
        "          resource_name = str(metadata.get('name') or '').strip().lower()\n"
        "          spec_domains = [\n"
        "              str(item).strip().lower().rstrip('.')\n"
        "              for item in (payload.get('spec', {}).get('domains') or [])\n"
        "              if str(item).strip()\n"
        "          ]\n"
        "          resource_name_matches_expected = bool(resource_name and expected_cert_name and resource_name == expected_cert_name)\n"
        "          domain_exact_match = bool(expected_host) and len(spec_domains) == 1 and spec_domains[0] == expected_host\n"
        "          observed_managed_by = str(labels_payload.get('app.kubernetes.io/managed-by') or '').strip().lower()\n"
        "          observed_name_label = str(labels_payload.get('app.kubernetes.io/name') or '').strip().lower()\n"
        "          observed_repo_label = str(labels_payload.get('mbsrn.io/repo') or '').strip().lower()\n"
        "          observed_site_id_label = str(labels_payload.get('mbsrn.io/site-id') or '').strip().lower()\n"
        "          observed_preview_hostname_label = str(labels_payload.get('mbsrn.io/preview-hostname') or '').strip().lower().rstrip('.')\n"
        "          ownership_checks = [\n"
        "              observed_managed_by == 'mbsrn',\n"
        "              observed_name_label == 'site-web',\n"
        "              observed_preview_hostname_label == expected_host,\n"
        "          ]\n"
        "          if expected_repo_label:\n"
        "              ownership_checks.append(observed_repo_label == expected_repo_label)\n"
        "          if expected_site_id:\n"
        "              ownership_checks.append(observed_site_id_label == expected_site_id)\n"
        "          ownership_verified = all(ownership_checks)\n"
        "          print('domain_exact_match=' + ('true' if domain_exact_match else 'false'))\n"
        "          print('resource_name_matches_expected=' + ('true' if resource_name_matches_expected else 'false'))\n"
        "          print('managed_certificate_ownership_verified=' + ('true' if ownership_verified else 'false'))\n"
        "          print('spec_domains=' + ','.join(spec_domains))\n"
        "          print(f'observed_managed_by={observed_managed_by}')\n"
        "          print(f'observed_name_label={observed_name_label}')\n"
        "          print(f'observed_repo_label={observed_repo_label}')\n"
        "          print(f'observed_site_id_label={observed_site_id_label}')\n"
        "          print(f'observed_preview_hostname_label={observed_preview_hostname_label}')\n"
        "          PY\n"
        '          )"\n'
        "          domain_exact_match=false\n"
        "          resource_name_matches_expected=false\n"
        "          managed_certificate_ownership_verified=false\n"
        '          observed_managed_certificate_domains=""\n'
        '          observed_managed_by=""\n'
        '          observed_name_label=""\n'
        '          observed_repo_label=""\n'
        '          observed_site_id_label=""\n'
        '          observed_preview_hostname_label=""\n'
        "          while IFS='=' read -r key value; do\n"
        '            case "$key" in\n'
        "              domain_exact_match)\n"
        '                domain_exact_match="$value"\n'
        "                ;;\n"
        "              resource_name_matches_expected)\n"
        '                resource_name_matches_expected="$value"\n'
        "                ;;\n"
        "              managed_certificate_ownership_verified)\n"
        '                managed_certificate_ownership_verified="$value"\n'
        "                ;;\n"
        "              spec_domains)\n"
        '                observed_managed_certificate_domains="$value"\n'
        "                ;;\n"
        "              observed_managed_by)\n"
        '                observed_managed_by="$value"\n'
        "                ;;\n"
        "              observed_name_label)\n"
        '                observed_name_label="$value"\n'
        "                ;;\n"
        "              observed_repo_label)\n"
        '                observed_repo_label="$value"\n'
        "                ;;\n"
        "              observed_site_id_label)\n"
        '                observed_site_id_label="$value"\n'
        "                ;;\n"
        "              observed_preview_hostname_label)\n"
        '                observed_preview_hostname_label="$value"\n'
        "                ;;\n"
        "            esac\n"
        '          done <<< "$cert_eval_output"\n'
        '          if [ "$resource_name_matches_expected" != "true" ]; then\n'
        '            echo "observed_managed_certificate_domains=$observed_managed_certificate_domains"\n'
        '            fail_endpoint_prerequisite "stale_managed_certificate_present" "ManagedCertificate resource identity does not match the expected deterministic certificate name." "true" "UNKNOWN"\n'
        "          fi\n"
        '          if [ "$managed_certificate_ownership_verified" != "true" ]; then\n'
        '            echo "observed_managed_by=$observed_managed_by"\n'
        '            echo "observed_name_label=$observed_name_label"\n'
        '            echo "observed_repo_label=$observed_repo_label"\n'
        '            echo "observed_site_id_label=$observed_site_id_label"\n'
        '            echo "observed_preview_hostname_label=$observed_preview_hostname_label"\n'
        '            fail_endpoint_prerequisite "managed_certificate_ownership_unverified" "ManagedCertificate ownership labels do not verify this site identity." "true" "UNKNOWN"\n'
        "          fi\n"
        '          if [ "$domain_exact_match" != "true" ]; then\n'
        '            echo "observed_managed_certificate_domains=$observed_managed_certificate_domains"\n'
        '            fail_endpoint_prerequisite "certificate_domain_mismatch" "ManagedCertificate spec.domains does not match the expected preview hostname." "true" "UNKNOWN"\n'
        "          fi\n"
        '          echo "managed_certificate_action=reused" >> "$GITHUB_OUTPUT"\n'
        "      - name: Replace existing managed-site runtime resources (optional)\n"
        "        id: replace_managed_runtime\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        '          replace_requested="$(echo "${MBSRN_REPLACE_EXISTING_RUNTIME:-false}" | tr \'[:upper:]\' \'[:lower:]\' | tr -d \'[:space:]\')"\n'
        '          scope_summary="namespace=${K8S_NAMESPACE};site_id=${MBSRN_SITE_IDENTITY};repo=${GITHUB_REPOSITORY}"\n'
        '          endpoint_prerequisite_resource_kinds="managedcertificate,dns_record,global_static_ip"\n'
        '          runtime_resource_kinds="ingress,frontendconfig,backendconfig,service,deployment,networkpolicy"\n'
        '          deleted_kinds="none"\n'
        "          append_deleted_kind() {\n"
        '            local next_kind="$1"\n'
        '            if [ -z "$next_kind" ]; then\n'
        "              return\n"
        "            fi\n"
        '            if [ "$deleted_kinds" = "none" ]; then\n'
        '              deleted_kinds="$next_kind"\n'
        "              return\n"
        "            fi\n"
        '            case ",$deleted_kinds," in\n'
        '              *",$next_kind,"*) ;;\n'
        '              *) deleted_kinds="${deleted_kinds},${next_kind}" ;;\n'
        "            esac\n"
        "          }\n"
        "          fail_replace_runtime() {\n"
        '            local failed_kind="$1"\n'
        '            local failed_name="$2"\n'
        '            echo "deploy_runtime_reason_code=managed_site_runtime_replace_failed"\n'
        '            echo "deploy_runtime_reason_message=Managed-site runtime replace failed while deleting ${failed_kind}/${failed_name}."\n'
        '            echo "deploy_runtime_failure_stage=workflow_execution"\n'
        '            echo "managed_site_runtime_replace_performed=false" >> "$GITHUB_OUTPUT"\n'
        '            echo "managed_site_runtime_replace_scope=$scope_summary" >> "$GITHUB_OUTPUT"\n'
        '            echo "managed_site_runtime_replace_deleted_kinds=$deleted_kinds" >> "$GITHUB_OUTPUT"\n'
        "            exit 1\n"
        "          }\n"
        "          delete_named_resource() {\n"
        '            local resource_kind="$1"\n'
        '            local resource_name="$2"\n'
        '            if kubectl delete "$resource_kind" "$resource_name" --namespace "$K8S_NAMESPACE" --ignore-not-found=true; then\n'
        '              append_deleted_kind "$resource_kind"\n'
        "            else\n"
        '              fail_replace_runtime "$resource_kind" "$resource_name"\n'
        "            fi\n"
        "          }\n"
        '          if [ "$replace_requested" != "true" ]; then\n'
        '            echo "managed_site_runtime_replace_performed=false" >> "$GITHUB_OUTPUT"\n'
        '            echo "managed_site_runtime_replace_scope=$scope_summary" >> "$GITHUB_OUTPUT"\n'
        '            echo "managed_site_runtime_replace_deleted_kinds=$deleted_kinds" >> "$GITHUB_OUTPUT"\n'
        "            exit 0\n"
        "          fi\n"
        '          echo "deploy_runtime_reason_code=managed_site_runtime_replace_requested"\n'
        '          echo "endpoint_prerequisite_resource_kinds=$endpoint_prerequisite_resource_kinds"\n'
        '          echo "runtime_resource_kinds=$runtime_resource_kinds"\n'
        '          echo "Replacing managed runtime resources in namespace ${K8S_NAMESPACE} for site ${MBSRN_SITE_IDENTITY}."\n'
        '          delete_named_resource "ingress" "site-web"\n'
        '          delete_named_resource "frontendconfig" "$MBSRN_FRONTEND_CONFIG_NAME"\n'
        '          delete_named_resource "backendconfig" "$MBSRN_BACKEND_CONFIG_NAME"\n'
        '          delete_named_resource "service" "site-web"\n'
        '          delete_named_resource "deployment" "site-web"\n'
        '          network_policy_selector="app.kubernetes.io/managed-by=mbsrn,mbsrn.io/site-id=${MBSRN_SITE_IDENTITY}"\n'
        '          if kubectl delete networkpolicy --namespace "$K8S_NAMESPACE" -l "$network_policy_selector" --ignore-not-found=true; then\n'
        '            append_deleted_kind "networkpolicy"\n'
        "          else\n"
        '            fail_replace_runtime "networkpolicy" "$network_policy_selector"\n'
        "          fi\n"
        '          echo "deploy_runtime_reason_code=managed_site_runtime_replace_completed"\n'
        '          echo "managed_site_runtime_replace_performed=true" >> "$GITHUB_OUTPUT"\n'
        '          echo "managed_site_runtime_replace_scope=$scope_summary" >> "$GITHUB_OUTPUT"\n'
        '          echo "managed_site_runtime_replace_deleted_kinds=$deleted_kinds" >> "$GITHUB_OUTPUT"\n'
        "      - name: Apply managed manifests\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          apply_manifest_if_present() {\n"
        '            local manifest_path=\"$1\"\n'
        "            if [ -f \"$manifest_path\" ]; then\n"
        '              kubectl apply -f \"$manifest_path\"\n'
        "            fi\n"
        "          }\n"
        "          emit_apply_failure_state() {\n"
        '            local reason_message=\"$1\"\n'
        '            local service_state=\"${2:-unknown}\"\n'
        '            local endpoints_state=\"${3:-unknown}\"\n'
        '            local managed_certificate_state=\"${4:-unknown}\"\n'
        '            local managed_certificate_status=\"${5:-}\"\n'
        '            echo \"resolve_live_url_state_service_exists=$service_state\"\n'
        '            echo \"resolve_live_url_state_endpoints_ready=$endpoints_state\"\n'
        '            echo \"resolve_live_url_state_managed_certificate_exists=$managed_certificate_state\"\n'
        '            if [ -n \"$managed_certificate_status\" ]; then\n'
        '              echo \"resolve_live_url_state_managed_certificate_status=$managed_certificate_status\"\n'
        "            fi\n"
        '            echo \"resolve_live_url_state_runtime_ready=false\"\n'
        '            echo \"resolve_live_url_state_ingress_address_resolved=false\"\n'
        '            echo \"resolve_live_url_state_deploy_https_ready=false\"\n'
        '            echo \"resolve_live_url_state_https_ready=false\"\n'
        '            echo \"resolve_live_url_state_runtime_ready_tls_pending=false\"\n'
        '            echo \"resolve_live_url_state_deploy_runtime_failure_stage=ingress_verify\"\n'
        '            echo \"resolve_live_url_state_deploy_runtime_reason_message=$reason_message\"\n'
        f'            echo \"resolve_live_url_state_{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}\"\n'
        "          }\n"
        "          fail_apply_resource() {\n"
        '            local reason_code=\"$1\"\n'
        '            local reason_message=\"$2\"\n'
        '            local service_state=\"${3:-unknown}\"\n'
        '            local endpoints_state=\"${4:-unknown}\"\n'
        '            local managed_certificate_state=\"${5:-unknown}\"\n'
        '            local managed_certificate_status=\"${6:-}\"\n'
        '            echo \"deploy_runtime_reason_code=${reason_code}\"\n'
        '            echo \"deploy_runtime_reason_message=${reason_message}\"\n'
        '            echo \"deploy_runtime_failure_stage=ingress_verify\"\n'
        '            echo \"k8s_namespace=$K8S_NAMESPACE\"\n'
        '            echo \"ingress_name=site-web\"\n'
        '            echo \"preview_hostname=$MBSRN_PREVIEW_HOSTNAME\"\n'
        '            echo \"preview_endpoint_mode=$MBSRN_PREVIEW_ENDPOINT_MODE\"\n'
        '            echo \"expected_managed_certificate_name=$MBSRN_PREVIEW_CERTIFICATE_NAME\"\n'
        '            emit_apply_failure_state \"$reason_message\" \"$service_state\" \"$endpoints_state\" \"$managed_certificate_state\" \"$managed_certificate_status\"\n'
        "            exit 1\n"
        "          }\n"
        "          wait_for_named_resource() {\n"
        '            local resource_kind=\"$1\"\n'
        '            local resource_name=\"$2\"\n'
        '            local max_attempts=\"$3\"\n'
        '            local sleep_seconds=\"$4\"\n'
        '            local reason_code=\"$5\"\n'
        '            local reason_message=\"$6\"\n'
        '            local service_state=\"${7:-unknown}\"\n'
        '            local endpoints_state=\"${8:-unknown}\"\n'
        '            local managed_certificate_state=\"${9:-unknown}\"\n'
        '            local managed_certificate_status=\"${10:-}\"\n'
        '            local attempt=1\n'
        '            while [ \"$attempt\" -le \"$max_attempts\" ]; do\n'
        '              if kubectl get \"$resource_kind\" \"$resource_name\" --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        "                return 0\n"
        "              fi\n"
        '              if [ \"$attempt\" -lt \"$max_attempts\" ]; then\n'
        '                sleep \"$sleep_seconds\"\n'
        "              fi\n"
        '              attempt=$((attempt + 1))\n'
        "            done\n"
        '            fail_apply_resource \"$reason_code\" \"$reason_message\" \"$service_state\" \"$endpoints_state\" \"$managed_certificate_state\" \"$managed_certificate_status\"\n'
        "          }\n"
        '          ingress_manifest_present=false\n'
        '          ingress_references_managed_certificate=false\n'
        '          if [ -f k8s/ingress.yaml ]; then\n'
        '            ingress_manifest_present=true\n'
        '            if grep -q \"networking.gke.io/managed-certificates:\" k8s/ingress.yaml; then\n'
        '              ingress_references_managed_certificate=true\n'
        "            fi\n"
        "          fi\n"
        '          apply_manifest_if_present \"k8s/resourcequota.yaml\"\n'
        '          apply_manifest_if_present \"k8s/limitrange.yaml\"\n'
        '          apply_manifest_if_present \"k8s/networkpolicy.yaml\"\n'
        "          while IFS= read -r manifest_path; do\n"
        '            [ -n \"$manifest_path\" ] || continue\n'
        '            kubectl apply -f \"$manifest_path\"\n'
        "          done < <(\n"
        "            find k8s -maxdepth 1 -type f -name '*.yaml' | sort \\\n"
        "              | grep -Ev '^k8s/(namespace|deployment|service|backendconfig|frontendconfig|managedcertificate|ingress|resourcequota|limitrange|networkpolicy)\\.yaml$' || true\n"
        "          )\n"
        '          apply_manifest_if_present \"k8s/backendconfig.yaml\"\n'
        '          apply_manifest_if_present \"k8s/service.yaml\"\n'
        '          wait_for_named_resource \"service\" \"site-web\" 10 3 \"runtime_service_missing_after_apply\" \"Service site-web is missing after managed manifest apply.\" \"false\" \"unknown\" \"unknown\"\n'
        '          apply_manifest_if_present \"k8s/deployment.yaml\"\n'
        '          apply_manifest_if_present \"k8s/frontendconfig.yaml\"\n'
        '          if [ \"$ingress_manifest_present\" = true ]; then\n'
        '            apply_manifest_if_present \"k8s/ingress.yaml\"\n'
        "          fi\n"
        "      - name: Verify required resources after apply\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          fail_missing_resource() {\n"
        '            local reason_code=\"$1\"\n'
        '            local reason_message=\"$2\"\n'
        '            local service_state=\"${3:-unknown}\"\n'
        '            local endpoints_state=\"${4:-unknown}\"\n'
        '            local managed_certificate_state=\"${5:-unknown}\"\n'
        '            local managed_certificate_status=\"${6:-}\"\n'
        '            echo \"deploy_runtime_reason_code=${reason_code}\"\n'
        '            echo \"deploy_runtime_reason_message=${reason_message}\"\n'
        '            echo \"deploy_runtime_failure_stage=ingress_verify\"\n'
        '            echo \"k8s_namespace=$K8S_NAMESPACE\"\n'
        '            echo \"ingress_name=site-web\"\n'
        '            echo \"preview_hostname=$MBSRN_PREVIEW_HOSTNAME\"\n'
        '            echo \"preview_endpoint_mode=$MBSRN_PREVIEW_ENDPOINT_MODE\"\n'
        '            echo \"expected_managed_certificate_name=$MBSRN_PREVIEW_CERTIFICATE_NAME\"\n'
        '            echo \"resolve_live_url_state_service_exists=$service_state\"\n'
        '            echo \"resolve_live_url_state_endpoints_ready=$endpoints_state\"\n'
        '            echo \"resolve_live_url_state_managed_certificate_exists=$managed_certificate_state\"\n'
        '            if [ -n \"$managed_certificate_status\" ]; then\n'
        '              echo \"resolve_live_url_state_managed_certificate_status=$managed_certificate_status\"\n'
        "            fi\n"
        '            echo \"resolve_live_url_state_runtime_ready=false\"\n'
        '            echo \"resolve_live_url_state_ingress_address_resolved=false\"\n'
        '            echo \"resolve_live_url_state_deploy_https_ready=false\"\n'
        '            echo \"resolve_live_url_state_https_ready=false\"\n'
        '            echo \"resolve_live_url_state_runtime_ready_tls_pending=false\"\n'
        '            echo \"resolve_live_url_state_deploy_runtime_failure_stage=ingress_verify\"\n'
        '            echo \"resolve_live_url_state_deploy_runtime_reason_message=$reason_message\"\n'
        f'            echo \"resolve_live_url_state_{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}\"\n'
        "            exit 1\n"
        "          }\n"
        '          if ! kubectl get deployment site-web --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        '            fail_missing_resource \"runtime_deployment_missing_after_apply\" \"Deployment site-web is missing after managed manifest apply.\" \"unknown\" \"unknown\" \"unknown\"\n'
        "          fi\n"
        '          if ! kubectl get service site-web --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        '            fail_missing_resource \"runtime_service_missing_after_apply\" \"Service site-web is missing after managed manifest apply.\" \"false\" \"unknown\" \"unknown\"\n'
        "          fi\n"
        '          ingress_manifest_present=false\n'
        '          if [ -f k8s/ingress.yaml ]; then\n'
        '            ingress_manifest_present=true\n'
        "          fi\n"
        '          if [ \"$ingress_manifest_present\" = true ] \\\n'
        '            && ! kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        '            fail_missing_resource \"runtime_ingress_missing_after_apply\" \"Ingress site-web is missing after managed manifest apply.\" \"true\" \"unknown\" \"unknown\"\n'
        "          fi\n"
        '          ingress_references_managed_certificate=false\n'
        '          ingress_references_frontend_config=false\n'
        '          if [ \"$ingress_manifest_present\" = true ]; then\n'
        '            if grep -q \"networking.gke.io/managed-certificates:\" k8s/ingress.yaml; then\n'
        '              ingress_references_managed_certificate=true\n'
        "            fi\n"
        '            if grep -q \"networking.gke.io/v1beta1.FrontendConfig:\" k8s/ingress.yaml; then\n'
        '              ingress_references_frontend_config=true\n'
        "            fi\n"
        "          fi\n"
        '          if [ \"$ingress_references_managed_certificate\" = true ] \\\n'
        '            && ! kubectl get managedcertificate \"$MBSRN_PREVIEW_CERTIFICATE_NAME\" --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        '            fail_missing_resource \"runtime_managed_certificate_missing_after_apply\" \"ManagedCertificate referenced by ingress is missing after managed manifest apply.\" \"true\" \"unknown\" \"false\" \"MISSING\"\n'
        "          fi\n"
        '          if [ \"$ingress_references_frontend_config\" = true ] \\\n'
        '            && ! kubectl get frontendconfig \"$MBSRN_FRONTEND_CONFIG_NAME\" --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        '            fail_missing_resource \"runtime_frontend_config_missing_after_apply\" \"FrontendConfig referenced by ingress is missing after managed manifest apply.\" \"true\" \"unknown\" \"unknown\"\n'
        "          fi\n"
        '          service_references_backend_config=false\n'
        '          if [ -f k8s/service.yaml ] && grep -q \"cloud.google.com/backend-config\" k8s/service.yaml; then\n'
        '            service_references_backend_config=true\n'
        "          fi\n"
        '          if [ \"$service_references_backend_config\" = true ] \\\n'
        '            && ! kubectl get backendconfig \"$MBSRN_BACKEND_CONFIG_NAME\" --namespace \"$K8S_NAMESPACE\" >/dev/null 2>&1; then\n'
        '            fail_missing_resource \"runtime_backend_config_missing_after_apply\" \"BackendConfig referenced by service is missing after managed manifest apply.\" \"true\" \"unknown\" \"unknown\"\n'
        "          fi\n"
        "      - name: Resolve managed site runtime image\n"
        "        id: resolve_site_runtime_image\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        '          selected_mode="immutable_sha"\n'
        '          selected_image="${SITE_WEB_IMAGE_REPOSITORY}:${GITHUB_SHA}"\n'
        '          selected_tag_source="github_sha_fallback"\n'
        '          normalized_tag="$(echo "${SITE_WEB_IMAGE_TAG:-}" | tr -d \'[:space:]\')"\n'
        '          if [ -n "$normalized_tag" ] && [ "$normalized_tag" != "latest" ]; then\n'
        "            if echo \"$normalized_tag\" | grep -Eq '^[A-Fa-f0-9]{7,64}$'; then\n"
        '              candidate_image="${SITE_WEB_IMAGE_REPOSITORY}:${normalized_tag}"\n'
        '              selected_image="$candidate_image"\n'
        '              selected_mode="immutable_sha"\n'
        '              selected_tag_source="configured_sha"\n'
        "            else\n"
        "              echo \"Configured SITE_WEB_IMAGE_TAG '$normalized_tag' is not a SHA-like tag; falling back to latest.\"\n"
        '              selected_image="${SITE_WEB_IMAGE_REPOSITORY}:latest"\n'
        '              selected_mode="fallback_latest"\n'
        '              selected_tag_source="configured_invalid_fallback_latest"\n'
        "            fi\n"
        '          elif [ "$normalized_tag" = "latest" ]; then\n'
        '            selected_image="${SITE_WEB_IMAGE_REPOSITORY}:latest"\n'
        '            selected_mode="fallback_latest"\n'
        '            selected_tag_source="configured_latest"\n'
        "          else\n"
        '            echo "SITE_WEB_IMAGE_TAG is empty; using GITHUB_SHA ${GITHUB_SHA}."\n'
        "          fi\n"
        '          echo "Managed site runtime image selected: ${selected_image} (mode=${selected_mode})"\n'
        '          kubectl set image deployment/site-web site-web="${selected_image}" --namespace "$K8S_NAMESPACE"\n'
        '          selected_repo="${selected_image}"\n'
        "          if echo \"$selected_repo\" | grep -q '@'; then\n"
        '            selected_repo="${selected_repo%%@*}"\n'
        '            selected_tag="digest"\n'
        "          else\n"
        '            selected_tag="latest"\n'
        "            if echo \"$selected_repo\" | grep -q ':'; then\n"
        '              selected_tag="${selected_repo##*:}"\n'
        '              selected_repo="${selected_repo%:*}"\n'
        "            fi\n"
        "          fi\n"
        "          {\n"
        '            echo "site_runtime_image_reference=${selected_image}"\n'
        '            echo "site_runtime_image_selection_mode=${selected_mode}"\n'
        '            echo "site_runtime_image_repository=${selected_repo}"\n'
        '            echo "site_runtime_image_tag=${selected_tag}"\n'
        '            echo "site_runtime_image_tag_source=${selected_tag_source}"\n'
        '            echo "site_runtime_source_commit=${GITHUB_SHA}"\n'
        '            echo "site_runtime_content_source=site_repo_build"\n'
        '          } >> "$GITHUB_OUTPUT"\n'
        "      - name: Verify rollout\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        '          if ! kubectl rollout status deployment/site-web --namespace "$K8S_NAMESPACE" --timeout=180s; then\n'
        '            echo "site-web rollout timed out in namespace $K8S_NAMESPACE; collecting bounded diagnostics."\n'
        '            kubectl get deployment site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get rs --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get pods --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get service site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o wide || true\n'
        '            deployment_describe_output="$(mktemp)"\n'
        '            kubectl describe deployment site-web --namespace "$K8S_NAMESPACE" > "$deployment_describe_output" 2>&1 || true\n'
        '            cat "$deployment_describe_output"\n'
        '            describe_pods_output="$(mktemp)"\n'
        '            kubectl describe pods --namespace "$K8S_NAMESPACE" -l app.kubernetes.io/name=site-web > "$describe_pods_output" 2>&1 || true\n'
        '            cat "$describe_pods_output"\n'
        '            service_describe_output="$(mktemp)"\n'
        '            kubectl describe service site-web --namespace "$K8S_NAMESPACE" > "$service_describe_output" 2>&1 || true\n'
        '            cat "$service_describe_output"\n'
        '            ingress_describe_output="$(mktemp)"\n'
        '            kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" > "$ingress_describe_output" 2>&1 || true\n'
        '            cat "$ingress_describe_output"\n'
        '            managedcertificate_describe_output="$(mktemp)"\n'
        '            kubectl describe managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" > "$managedcertificate_describe_output" 2>&1 || true\n'
        '            cat "$managedcertificate_describe_output"\n'
        '            backendconfig_describe_output="$(mktemp)"\n'
        '            kubectl describe backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" > "$backendconfig_describe_output" 2>&1 || true\n'
        '            cat "$backendconfig_describe_output"\n'
        '            endpoints_output="$(mktemp)"\n'
        '            kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o yaml > "$endpoints_output" 2>&1 || true\n'
        '            cat "$endpoints_output"\n'
        '            endpointslice_output="$(mktemp)"\n'
        '            kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o yaml > "$endpointslice_output" 2>&1 || true\n'
        '            cat "$endpointslice_output"\n'
        "            image_pull_detected=false\n"
        "            image_pull_secret_missing_detected=false\n"
        "            private_image_pull_forbidden_detected=false\n"
        "            public_image_pull_failed_detected=false\n"
        "            service_no_ready_endpoints_detected=false\n"
        "            ingress_backend_unhealthy_detected=false\n"
        "            pod_ready_detected=false\n"
        '            private_image_auth_required="${PRIVATE_IMAGE_AUTH_REQUIRED:-false}"\n'
        "            if grep -qiE 'ImagePullBackOff|ErrImagePull|pull access denied|manifest unknown|Failed to pull image' \"$describe_pods_output\"; then\n"
        "              image_pull_detected=true\n"
        '              echo "Likely rollout blocker: image pull backoff."\n'
        "            fi\n"
        '            if grep -qiE \'FailedToRetrieveImagePullSecret|image pull secret.*not found|pull secret.*not found|secret ".*" not found.*(pull|image)\' "$describe_pods_output"; then\n'
        '              if [ "$private_image_auth_required" = "true" ]; then\n'
        "                image_pull_detected=true\n"
        "                image_pull_secret_missing_detected=true\n"
        '                echo "Likely rollout blocker: image pull secret missing."\n'
        "              fi\n"
        "            fi\n"
        "            if grep -qiE 'failed to fetch anonymous token|403[[:space:]]+Forbidden|unauthorized|authentication required' \"$describe_pods_output\"; then\n"
        "              image_pull_detected=true\n"
        '              if [ "$private_image_auth_required" = "true" ]; then\n'
        "                private_image_pull_forbidden_detected=true\n"
        '                echo "Likely rollout blocker: private image pull forbidden."\n'
        '                if [ "$image_pull_secret_missing_detected" = false ]; then\n'
        '                  echo "Likely rollout blocker: image pull secret not referenced."\n'
        "                fi\n"
        "              else\n"
        "                public_image_pull_failed_detected=true\n"
        '                echo "Likely rollout blocker: public image pull failed."\n'
        "              fi\n"
        "            fi\n"
        "            if grep -qiE 'Ready:[[:space:]]+True|ContainersReady[[:space:]]+True|Condition[[:space:]]+Ready[[:space:]]+True' \"$describe_pods_output\"; then\n"
        "              pod_ready_detected=true\n"
        "            fi\n"
        '            if grep -qiE \'endpoints:[[:space:]]*<none>|subsets:[[:space:]]*\\[\\]|addresses:[[:space:]]*\\[\\]|notreadyaddresses|no endpoints available\' "$service_describe_output" "$endpoints_output" "$endpointslice_output"; then\n'
        "              service_no_ready_endpoints_detected=true\n"
        '              echo "Likely rollout blocker: service has no ready endpoints."\n'
        '              echo "deploy_runtime_reason_code=service_has_no_ready_endpoints"\n'
        '              echo "deploy_runtime_reason_code=service_endpoint_missing"\n'
        "            fi\n"
        '            if grep -qiE \'ingress backend.*unhealthy|backend service.*unhealthy|backend.*degraded mode|neg.*degraded mode|unhealthy backends\' "$deployment_describe_output" "$describe_pods_output" "$ingress_describe_output"; then\n'
        "              ingress_backend_unhealthy_detected=true\n"
        '              echo "Likely rollout blocker: ingress backend unhealthy."\n'
        '              echo "deploy_runtime_reason_code=ingress_backend_unhealthy"\n'
        '              echo "deploy_runtime_reason_code=ingress_backend_unhealthy_after_rollout"\n'
        "            fi\n"
        '            if grep -qiE \'502|bad gateway\' "$ingress_describe_output" "$service_describe_output"; then\n'
        '              echo "Likely rollout blocker: ingress backend 502."\n'
        '              echo "deploy_runtime_reason_code=ingress_backend_502"\n'
        "            fi\n"
        '            if [ "$pod_ready_detected" = true ] && [ "$ingress_backend_unhealthy_detected" = true ]; then\n'
        '              echo "Likely rollout blocker: pod ready but ingress backend unhealthy."\n'
        '              echo "deploy_runtime_reason_code=pod_ready_but_ingress_backend_unhealthy"\n'
        '              echo "deploy_runtime_reason_code=service_endpoint_unhealthy"\n'
        "            fi\n"
        '            if grep -qiE \'backendconfig.*healthcheck|healthcheck.*path|health check.*path|requestpath\' "$deployment_describe_output" "$describe_pods_output" "$backendconfig_describe_output"; then\n'
        '              echo "Likely rollout blocker: backendconfig health check mismatch."\n'
        '              echo "deploy_runtime_reason_code=backendconfig_health_check_mismatch"\n'
        '              echo "deploy_runtime_reason_code=backend_config_healthcheck_unhealthy"\n'
        "            fi\n"
        "            if grep -qiE 'failednotvisible' \"$managedcertificate_describe_output\"; then\n"
        '              echo "Likely rollout blocker: managed certificate failed visibility checks."\n'
        '              echo "deploy_runtime_reason_code=managed_certificate_failed_not_visible"\n'
        "            fi\n"
        "            if grep -qiE 'in-use and would result in a conflict|global static ip.*conflict|specified ip address is in-use' \"$ingress_describe_output\"; then\n"
        '              echo "Likely rollout blocker: ingress static IP conflict."\n'
        '              echo "deploy_runtime_reason_code=ingress_static_ip_conflict"\n'
        "            fi\n"
        "            if grep -qiE 'ingress\\.gcp\\.kubernetes\\.io/pre-shared-cert' \"$ingress_describe_output\"; then\n"
        '              echo "Observed ingress pre-shared certificate controller metadata; verify managed-certificate desired-state evidence."\n'
        '              echo "deploy_runtime_reason_code=pre_shared_cert_metadata_mismatch"\n'
        "            fi\n"
        '            if [ "$image_pull_secret_missing_detected" = true ]; then\n'
        '              echo "deploy_runtime_reason_code=image_pull_secret_missing"\n'
        '            elif [ "$private_image_pull_forbidden_detected" = true ]; then\n'
        '              echo "deploy_runtime_reason_code=private_image_pull_forbidden"\n'
        '            elif [ "$public_image_pull_failed_detected" = true ]; then\n'
        '              echo "deploy_runtime_reason_code=public_image_pull_failed"\n'
        "            fi\n"
        "            if grep -qiE 'manifest unknown|name unknown|[Ii]magePullBackOff.*not found|[Ff]ailed to pull image.*not found|ghcr\\.io/.+:.*not found' \"$describe_pods_output\"; then\n"
        "              image_pull_detected=true\n"
        '              echo "Likely rollout blocker: container image not found in registry."\n'
        "            fi\n"
        "            container_started_evidence=false\n"
        "            if grep -qiE 'Container ID:|Started:[[:space:]]+true|State:[[:space:]]+(Running|Terminated)' \"$describe_pods_output\"; then\n"
        "              container_started_evidence=true\n"
        "            fi\n"
        "            crash_direct_evidence=false\n"
        "            if grep -qiE 'CrashLoopBackOff|Back-off restarting failed container|OOMKilled|terminated with exit code|Last State:[[:space:]]+Terminated|Reason:[[:space:]]+Error' \"$describe_pods_output\"; then\n"
        "              crash_direct_evidence=true\n"
        "            fi\n"
        "            probe_direct_evidence=false\n"
        "            if grep -qiE 'Readiness probe failed|Liveness probe failed|Startup probe failed|Unhealthy|Probe errored' \"$describe_pods_output\"; then\n"
        "              probe_direct_evidence=true\n"
        "            fi\n"
        "            # Suppress crash/probe hints when current describe evidence shows image-pull blockers.\n"
        '            if [ "$image_pull_detected" = false ] && [ "$container_started_evidence" = true ] && [ "$crash_direct_evidence" = true ]; then\n'
        '              echo "Likely rollout blocker: pod crash/failing container startup."\n'
        "            fi\n"
        '            if [ "$image_pull_detected" = false ] && [ "$container_started_evidence" = true ] && [ "$probe_direct_evidence" = true ]; then\n'
        '              echo "Likely rollout blocker: readiness/liveness probe failure."\n'
        "            fi\n"
        '            if grep -qiE \'CreateContainerConfigError|CreateContainerError|secret ".*" not found|configmap ".*" not found\' "$describe_pods_output"; then\n'
        '              echo "Likely rollout blocker: config or secret reference failure."\n'
        "            fi\n"
        '            if grep -qiE \'exceeded quota|FailedCreate|forbidden: exceeded quota|requested: requests\\.(memory|cpu)|limited: requests\\.(memory|cpu)|limited: limits\\.\' "$deployment_describe_output" "$describe_pods_output"; then\n'
        '              echo "Likely rollout blocker: namespace ResourceQuota rejection."\n'
        "            fi\n"
        "            if grep -qiE 'FailedScheduling|Insufficient|didn.t match Pod.s node affinity|taint|node.s had' \"$describe_pods_output\"; then\n"
        '              echo "Likely rollout blocker: scheduling or resource availability issue."\n'
        "            fi\n"
        '            rm -f "$deployment_describe_output"\n'
        '            rm -f "$describe_pods_output"\n'
        '            rm -f "$service_describe_output"\n'
        '            rm -f "$ingress_describe_output"\n'
        '            rm -f "$managedcertificate_describe_output"\n'
        '            rm -f "$backendconfig_describe_output"\n'
        '            rm -f "$endpoints_output"\n'
        '            rm -f "$endpointslice_output"\n'
        '            recent_pods="$(kubectl get pods --namespace "$K8S_NAMESPACE" -l app.kubernetes.io/name=site-web --sort-by=.metadata.creationTimestamp -o name 2>/dev/null | tail -n 3)"\n'
        '            if [ -n "$recent_pods" ]; then\n'
        "              for pod in $recent_pods; do\n"
        '                echo "--- recent logs: $pod ---"\n'
        '                kubectl logs --namespace "$K8S_NAMESPACE" "$pod" -c site-web --tail=200 || kubectl logs --namespace "$K8S_NAMESPACE" "$pod" --tail=200 || true\n'
        "              done\n"
        "            fi\n"
        '            echo "deploy_runtime_reason_code=rollout_verification_failed"\n'
        '            echo "deploy_runtime_failure_stage=rollout_verify"\n'
        '            echo "deploy_runtime_reason_message=Managed deployment rollout did not converge before timeout and diagnostics were collected."\n'
        "            exit 1\n"
        "          fi\n"
        "      - name: Verify service and ingress\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        '          kubectl get service site-web --namespace "$K8S_NAMESPACE"\n'
        '          kubectl get ingress site-web --namespace "$K8S_NAMESPACE"\n'
        '          kubectl get service site-web --namespace "$K8S_NAMESPACE" -o yaml\n'
        '          kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o yaml\n'
        '          kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o yaml || true\n'
        '          kubectl describe service site-web --namespace "$K8S_NAMESPACE" || true\n'
        '          kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" || true\n'
        '          kubectl describe managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        '          kubectl describe backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        "          endpoint_wait_max_attempts=20\n"
        "          endpoint_wait_sleep_seconds=15\n"
        "          endpoint_wait_attempt=1\n"
        "          endpoint_convergence_reason_reported=false\n"
        '          endpoint_count=""\n'
        '          while [ "$endpoint_wait_attempt" -le "$endpoint_wait_max_attempts" ]; do\n'
        "            endpoint_count=\"$(kubectl get endpoints site-web --namespace \"$K8S_NAMESPACE\" -o jsonpath='{range .subsets[*].addresses[*]}x{end}' 2>/dev/null | wc -c | tr -d '[:space:]')\"\n"
        '            if [ -n "$endpoint_count" ] && [ "$endpoint_count" -gt 0 ]; then\n'
        "              break\n"
        "            fi\n"
        '            if [ "$endpoint_wait_attempt" -lt "$endpoint_wait_max_attempts" ]; then\n'
        '              if [ "$endpoint_convergence_reason_reported" = false ]; then\n'
        '                echo "deploy_runtime_reason_code=service_probe_waiting_for_convergence"\n'
        "                endpoint_convergence_reason_reported=true\n"
        "              fi\n"
        '              echo "Service endpoints not ready on attempt ${endpoint_wait_attempt}/${endpoint_wait_max_attempts}; retrying in ${endpoint_wait_sleep_seconds}s."\n'
        '              sleep "$endpoint_wait_sleep_seconds"\n'
        "            fi\n"
        "            endpoint_wait_attempt=$((endpoint_wait_attempt + 1))\n"
        "          done\n"
        '          if [ -z "$endpoint_count" ] || [ "$endpoint_count" -eq 0 ]; then\n'
        '            echo "deploy_runtime_reason_code=runtime_service_endpoints_missing_after_apply"\n'
        '            echo "deploy_runtime_reason_code=service_endpoint_missing"\n'
        '            echo "deploy_runtime_reason_code=service_has_no_ready_endpoints"\n'
        '            echo "deploy_runtime_reason_message=Service has no ready endpoints after rollout."\n'
        '            echo "deploy_runtime_failure_stage=rollout_verify"\n'
        "            exit 1\n"
        "          fi\n"
        "          probe_max_attempts=20\n"
        "          probe_sleep_seconds=15\n"
        "          probe_attempt=1\n"
        "          probe_success=false\n"
        "          convergence_reason_reported=false\n"
        "          in_cluster_probe_timeout_detected=false\n"
        '          last_probe_pod=""\n'
        '          last_probe_output=""\n'
        '          while [ "$probe_attempt" -le "$probe_max_attempts" ]; do\n'
        '            probe_pod="site-web-healthcheck-${GITHUB_RUN_ID:-run}-${GITHUB_RUN_ATTEMPT:-1}-${probe_attempt}"\n'
        "            probe_pod=\"$(echo \"$probe_pod\" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | cut -c1-63)\"\n"
        '            if [ -z "$probe_pod" ]; then\n'
        '              probe_pod="site-web-healthcheck-${probe_attempt}"\n'
        "            fi\n"
        '            last_probe_pod="$probe_pod"\n'
        '            kubectl delete pod "$probe_pod" --namespace "$K8S_NAMESPACE" --ignore-not-found || true\n'
        '            if [ -n "$last_probe_output" ] && [ -f "$last_probe_output" ]; then\n'
        '              rm -f "$last_probe_output"\n'
        "            fi\n"
        '            probe_output="$(mktemp)"\n'
        '            if kubectl run "$probe_pod" --namespace "$K8S_NAMESPACE" --image=curlimages/curl:8.10.1 --restart=Never --attach --command -- sh -c "curl -sS -f --connect-timeout 5 --max-time 15 http://site-web.${K8S_NAMESPACE}.svc.cluster.local:80/ >/dev/null" >"$probe_output" 2>&1; then\n'
        "              probe_success=true\n"
        '              rm -f "$probe_output"\n'
        '              last_probe_output=""\n'
        '              kubectl delete pod "$probe_pod" --namespace "$K8S_NAMESPACE" --ignore-not-found || true\n'
        "              break\n"
        "            fi\n"
        '            cat "$probe_output" || true\n'
        "            if grep -qiE 'curl: \\(28\\)|timed out|timeout was reached|failed to connect' \"$probe_output\"; then\n"
        "              in_cluster_probe_timeout_detected=true\n"
        "            fi\n"
        '            last_probe_output="$probe_output"\n'
        '            if [ "$probe_attempt" -lt "$probe_max_attempts" ]; then\n'
        '              kubectl delete pod "$probe_pod" --namespace "$K8S_NAMESPACE" --ignore-not-found || true\n'
        '              if [ "$convergence_reason_reported" = false ]; then\n'
        '                echo "deploy_runtime_reason_code=service_probe_waiting_for_convergence"\n'
        "                convergence_reason_reported=true\n"
        "              fi\n"
        '              echo "In-cluster service probe attempt ${probe_attempt}/${probe_max_attempts} failed; retrying in ${probe_sleep_seconds}s."\n'
        '              sleep "$probe_sleep_seconds"\n'
        "            fi\n"
        "            probe_attempt=$((probe_attempt + 1))\n"
        "          done\n"
        '          if [ "$probe_success" != true ]; then\n'
        '            if [ "$in_cluster_probe_timeout_detected" = true ]; then\n'
        '              echo "deploy_runtime_reason_code=in_cluster_service_probe_timeout"\n'
        '              echo "deploy_runtime_reason_code=network_policy_may_block_service_probe"\n'
        "            fi\n"
        '            echo "deploy_runtime_reason_code=in_cluster_service_curl_failed_after_retries"\n'
        '            echo "deploy_runtime_reason_code=in_cluster_service_curl_failed"\n'
        '            echo "deploy_runtime_reason_code=service_endpoint_unhealthy"\n'
        '            echo "deploy_runtime_reason_code=ingress_backend_unhealthy_after_rollout"\n'
        '            echo "deploy_runtime_reason_message=In-cluster service endpoint check failed after bounded retries."\n'
        '            echo "deploy_runtime_failure_stage=rollout_verify"\n'
        '            kubectl get networkpolicy --namespace "$K8S_NAMESPACE" -o yaml || true\n'
        '            kubectl describe networkpolicy --namespace "$K8S_NAMESPACE" || true\n'
        '            latest_site_web_pod="$(kubectl get pods --namespace "$K8S_NAMESPACE" -l app.kubernetes.io/name=site-web --sort-by=.metadata.creationTimestamp -o name 2>/dev/null | tail -n 1 | sed \'s#^pod/##\')"\n'
        '            if [ -n "$latest_site_web_pod" ]; then\n'
        '              kubectl get pod "$latest_site_web_pod" --namespace "$K8S_NAMESPACE" --show-labels || true\n'
        "            fi\n"
        '            kubectl get service site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'selector={.spec.selector}{"\\n"}ports={range .spec.ports[*]}{.name}:{.port}->{.targetPort}{"\\n"}{end}\' || true\n'
        '            kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o yaml || true\n'
        '            kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o yaml || true\n'
        '            if [ -n "$last_probe_output" ] && [ -f "$last_probe_output" ]; then\n'
        '              rm -f "$last_probe_output"\n'
        "            fi\n"
        '            if [ -n "$last_probe_pod" ]; then\n'
        '              kubectl logs "$last_probe_pod" --namespace "$K8S_NAMESPACE" --tail=200 || true\n'
        '              kubectl delete pod "$last_probe_pod" --namespace "$K8S_NAMESPACE" --ignore-not-found || true\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        "      - name: Resolve live URL from ingress status\n"
        "        id: resolve_live_url\n"
        "        env:\n"
        "          MBSRN_REPLACE_RUNTIME_PERFORMED: ${{ steps.replace_managed_runtime.outputs.managed_site_runtime_replace_performed || 'false' }}\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          max_attempts=40\n"
        "          sleep_seconds=15\n"
        "          wait_seconds=$((max_attempts * sleep_seconds))\n"
        '          resolve_started_at="$(date +%s)"\n'
        '          echo "Waiting up to ${wait_seconds}s for ingress external address assignment in namespace $K8S_NAMESPACE."\n'
        '          ingress_host=""\n'
        '          ingress_ip=""\n'
        '          ingress_spec_host=""\n'
        '          preview_host="$MBSRN_PREVIEW_HOSTNAME"\n'
        "          host_reachable=false\n"
        '          host_reachability_scheme=""\n'
        "          tls_mismatch_detected=false\n"
        "          backend_502_detected=false\n"
        "          dns_record_matches_ingress=false\n"
        '          dns_expected_ip=""\n'
        '          dns_observed_ip=""\n'
        '          expected_static_ip_address=""\n'
        '          static_ip_status=""\n'
        '          static_ip_users=""\n'
        '          tls_certificate_status=""\n'
        '          tls_domain_status=""\n'
        '          ingress_status_ip=""\n'
        "          ingress_status_ip_matches_static_ip=false\n"
        "          static_ip_bound_to_expected_forwarding_rule=false\n"
        "          ingress_conflict_detected=false\n"
        "          cert_identity_valid=false\n"
        "          deploy_https_ready=false\n"
        '          observed_managed_certificate_domains=""\n'
        '          observed_managed_certificate_status=""\n'
        '          observed_managed_certificate_domain_status=""\n'
        '          https_probe_error_summary=""\n'
        "          https_probe_attempted=false\n"
        "          http_fallback_attempted=false\n"
        "          control_plane_ready=false\n"
        '          live_url=""\n'
        '          preview_https_status=""\n'
        '          preview_http_status=""\n'
        "          preview_probe_attempt=0\n"
        "          preview_probe_elapsed_seconds=0\n"
        '          gce_backend_health_status=""\n'
        '          k8s_endpoint_ready=""\n'
        '          service_probe_status=""\n'
        '          in_cluster_service_status_code=""\n'
        '          endpoint_probe_status=""\n'
        '          endpoint_probe_status_code=""\n'
        '          runtime_probe_status=""\n'
        "          pod_restart_detected=false\n"
        '          replace_existing_runtime_requested="$(echo "${MBSRN_REPLACE_EXISTING_RUNTIME:-false}" | tr \'[:upper:]\' \'[:lower:]\' | tr -d \'[:space:]\')"\n'
        '          replace_existing_runtime_performed="$(echo "${MBSRN_REPLACE_RUNTIME_PERFORMED:-false}" | tr \'[:upper:]\' \'[:lower:]\' | tr -d \'[:space:]\')"\n'
        '          deploy_runtime_reason_message=""\n'
        '          service_exists="unknown"\n'
        '          endpoints_ready="unknown"\n'
        '          managed_certificate_exists="unknown"\n'
        '          resolve_live_url_log_path="$(mktemp)"\n'
        '          exec > >(tee -a "$resolve_live_url_log_path") 2>&1\n'
        "          deploy_runtime_failure_stage=ingress_evidence\n"
        f'          echo "{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}"\n'
        f'          echo "{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}" >> "$GITHUB_OUTPUT"\n'
        "          redact_sensitive_stream() {\n"
        "            sed -E \\\n"
        "              -e 's/(Authorization:).*/\\1 [REDACTED]/Ig' \\\n"
        "              -e 's/(Proxy-Authorization:).*/\\1 [REDACTED]/Ig' \\\n"
        "              -e 's/(Cookie:).*/\\1 [REDACTED]/Ig' \\\n"
        "              -e 's/(Set-Cookie:).*/\\1 [REDACTED]/Ig' \\\n"
        "              -e 's/(Bearer )[A-Za-z0-9._~+\\/=:-]+/\\1[REDACTED]/g' \\\n"
        "              -e 's/(Basic )[A-Za-z0-9._~+\\/=:-]+/\\1[REDACTED]/g' \\\n"
        "              -e 's/([A-Za-z0-9_]*(token|secret|password|api[_-]?key)[A-Za-z0-9_]*[=:][[:space:]]*)[^[:space:]]+/\\1[REDACTED]/Ig'\n"
        "          }\n"
        "          print_redacted_file() {\n"
        '            local file_path="$1"\n'
        "            if [ -f \"$file_path\" ]; then\n"
        '              cat "$file_path" | redact_sensitive_stream\n'
        "            fi\n"
        "          }\n"
        "          set_https_probe_error_summary() {\n"
            '            local probe_reason="$1"\n'
            '            local probe_exit_code="${2:-}"\n'
            '            local probe_status_code="${3:-}"\n'
            '            local probe_output_path="${4:-}"\n'
        '            local probe_detail=""\n'
        '            if [ -n "$probe_output_path" ] && [ -f "$probe_output_path" ]; then\n'
        "              probe_detail=\"$(head -n 1 \"$probe_output_path\" | tr -d '\\r' | tr '\\t' ' ' | sed 's/[[:space:]]\\+/ /g' | cut -c1-160)\"\n"
        "            fi\n"
        '            if [ -z "$probe_detail" ]; then\n'
        '              probe_detail="$probe_reason"\n'
        "            fi\n"
        '            https_probe_error_summary="reason=$probe_reason"\n'
        '            if [ -n "$probe_exit_code" ]; then\n'
        '              https_probe_error_summary="$https_probe_error_summary;exit_code=$probe_exit_code"\n'
        "            fi\n"
        '            if [ -n "$probe_status_code" ]; then\n'
        '              https_probe_error_summary="$https_probe_error_summary;status=$probe_status_code"\n'
        "            fi\n"
        '            if [ -n "${http_fallback_attempted:-}" ]; then\n'
        '              https_probe_error_summary="$https_probe_error_summary;http_fallback_attempted=$http_fallback_attempted"\n'
        "            fi\n"
        '            https_probe_error_summary="$https_probe_error_summary;detail=$probe_detail"\n'
        '            https_probe_error_summary="$(echo "$https_probe_error_summary" | tr -d \'\\r\' | cut -c1-240)"\n'
        "          }\n"
        "          ensure_https_probe_error_summary() {\n"
        '            if [ "$deploy_https_ready" = "true" ]; then\n'
        "              return\n"
        "            fi\n"
        '            if [ -n "$https_probe_error_summary" ]; then\n'
        "              return\n"
        "            fi\n"
        '            fallback_reason=""\n'
        '            fallback_detail=""\n'
        "            normalized_cert_status_local=\"$(echo \"${tls_certificate_status:-}\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        "            normalized_domain_status_local=\"$(echo \"${tls_domain_status:-}\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        '            if [ "$normalized_domain_status_local" = "PROVISIONING" ] || [ "$normalized_cert_status_local" = "PROVISIONING" ]; then\n'
        '              fallback_reason="managed_certificate_provisioning"\n'
        '              fallback_detail="managed certificate/domain status still PROVISIONING"\n'
        '            elif [ "${https_probe_attempted:-false}" = "true" ]; then\n'
        '              if [ "${control_plane_ready:-false}" = "true" ]; then\n'
        '                fallback_reason="https_probe_failed_after_control_plane_ready"\n'
        '                fallback_detail="probe_attempted_without_error_summary"\n'
        "              else\n"
        '                fallback_reason="https_probe_failed"\n'
        '                fallback_detail="probe_attempted_without_error_summary"\n'
        "              fi\n"
        '            elif [ "${dns_record_matches_ingress:-false}" != "true" ]; then\n'
        '              fallback_reason="dns_not_ready"\n'
        '              fallback_detail="dns_record_not_aligned_with_expected_ingress_target"\n'
        '            elif [ -z "${preview_host:-}" ] || { [ -z "${ingress_ip:-}" ] && [ "${host_reachable:-false}" != "true" ]; }; then\n'
        '              fallback_reason="host_resolution_pending"\n'
        '              fallback_detail="preview_host_or_ingress_not_ready"\n'
        '            elif [ "${cert_identity_valid:-false}" != "true" ] \\\n'
        '              || [ "$normalized_cert_status_local" != "ACTIVE" ] \\\n'
        '              || [ "$normalized_domain_status_local" != "ACTIVE" ]; then\n'
        '              fallback_reason="cert_not_ready"\n'
        '              fallback_detail="managed_certificate_not_active_or_identity_mismatch"\n'
        "            else\n"
        '              fallback_reason="https_probe_not_attempted"\n'
        '              fallback_detail="https_probe_not_attempted"\n'
        "            fi\n"
        '            https_probe_error_summary="reason=$fallback_reason;detail=$fallback_detail"\n'
        '            if [ "${https_probe_attempted:-false}" = "true" ]; then\n'
        '              https_probe_error_summary="$https_probe_error_summary;http_fallback_attempted=${http_fallback_attempted:-false}"\n'
        "            fi\n"
        '            https_probe_error_summary="$(echo "$https_probe_error_summary" | tr -d \'\\r\' | cut -c1-240)"\n'
        "          }\n"
        "          emit_resolve_live_url_state() {\n"
            "            ensure_https_probe_error_summary\n"
            '            runtime_ready_state="false"\n'
            '            if [ "$deploy_https_ready" = "true" ]; then\n'
            '              runtime_ready_state="true"\n'
            "            fi\n"
            '            ingress_address_resolved_state="false"\n'
            '            if [ -n "${ingress_ip:-}" ] || [ -n "${ingress_host:-}" ] || [ -n "${ingress_status_ip:-}" ]; then\n'
            '              ingress_address_resolved_state="true"\n'
            "            fi\n"
            '            endpoints_ready_state="${endpoints_ready:-unknown}"\n'
            '            if [ "$endpoints_ready_state" = "unknown" ] && [ -n "${k8s_endpoint_ready:-}" ]; then\n'
            '              endpoints_ready_state="$k8s_endpoint_ready"\n'
            "            fi\n"
            '            managed_certificate_status_state="$tls_certificate_status"\n'
            '            if [ -z "$managed_certificate_status_state" ] && [ -n "$observed_managed_certificate_status" ]; then\n'
            '              managed_certificate_status_state="$observed_managed_certificate_status"\n'
            "            fi\n"
            '            runtime_ready_tls_pending_state="false"\n'
            "            normalized_cert_status_state=\"$(echo \"${tls_certificate_status:-}\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
            "            normalized_domain_status_state=\"$(echo \"${tls_domain_status:-}\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
            '            if [ "$runtime_ready_state" != "true" ] \\\n'
            '              && [ "$ingress_address_resolved_state" = "true" ] \\\n'
            '              && { [ "$normalized_cert_status_state" = "PROVISIONING" ] || [ "$normalized_domain_status_state" = "PROVISIONING" ]; }; then\n'
            '              runtime_ready_tls_pending_state="true"\n'
            "            fi\n"
            '            echo "resolve_live_url_state_host_reachable=$host_reachable"\n'
            '            echo "resolve_live_url_state_host_reachability_scheme=$host_reachability_scheme"\n'
            '            echo "resolve_live_url_state_live_url=$live_url"\n'
            '            echo "resolve_live_url_state_dns_record_matches_ingress=$dns_record_matches_ingress"\n'
            '            echo "resolve_live_url_state_dns_expected_ip=$dns_expected_ip"\n'
            '            echo "resolve_live_url_state_dns_observed_ip=$dns_observed_ip"\n'
            '            echo "resolve_live_url_state_expected_static_ip_address=$expected_static_ip_address"\n'
            '            echo "resolve_live_url_state_static_ip_status=$static_ip_status"\n'
            '            echo "resolve_live_url_state_static_ip_users=$static_ip_users"\n'
            '            echo "resolve_live_url_state_ingress_status_ip=$ingress_status_ip"\n'
            '            echo "resolve_live_url_state_ingress_status_ip_matches_static_ip=$ingress_status_ip_matches_static_ip"\n'
            '            echo "resolve_live_url_state_static_ip_bound_to_expected_forwarding_rule=$static_ip_bound_to_expected_forwarding_rule"\n'
            '            echo "resolve_live_url_state_tls_certificate_status=$tls_certificate_status"\n'
            '            echo "resolve_live_url_state_tls_domain_status=$tls_domain_status"\n'
            '            echo "resolve_live_url_state_observed_managed_certificate_domains=$observed_managed_certificate_domains"\n'
            '            echo "resolve_live_url_state_observed_managed_certificate_status=$observed_managed_certificate_status"\n'
            '            echo "resolve_live_url_state_observed_managed_certificate_domain_status=$observed_managed_certificate_domain_status"\n'
            '            echo "resolve_live_url_state_https_probe_error_summary=$https_probe_error_summary"\n'
            '            echo "resolve_live_url_state_cert_identity_valid=$cert_identity_valid"\n'
            '            echo "resolve_live_url_state_deploy_https_ready=$deploy_https_ready"\n'
            '            echo "resolve_live_url_state_preview_https_status=$preview_https_status"\n'
            '            echo "resolve_live_url_state_preview_http_status=$preview_http_status"\n'
            '            echo "resolve_live_url_state_preview_probe_attempt=$preview_probe_attempt"\n'
            '            echo "resolve_live_url_state_preview_probe_elapsed_seconds=$preview_probe_elapsed_seconds"\n'
            '            echo "resolve_live_url_state_gce_backend_health_status=$gce_backend_health_status"\n'
            '            echo "resolve_live_url_state_k8s_endpoint_ready=$k8s_endpoint_ready"\n'
            '            echo "resolve_live_url_state_service_probe_status=$service_probe_status"\n'
            '            echo "resolve_live_url_state_in_cluster_service_status_code=$in_cluster_service_status_code"\n'
            '            echo "resolve_live_url_state_endpoint_probe_status=$endpoint_probe_status"\n'
            '            echo "resolve_live_url_state_endpoint_probe_status_code=$endpoint_probe_status_code"\n'
            '            echo "resolve_live_url_state_runtime_probe_status=$runtime_probe_status"\n'
            '            echo "resolve_live_url_state_pod_restart_detected=$pod_restart_detected"\n'
            '            echo "resolve_live_url_state_runtime_ready=$runtime_ready_state"\n'
            '            echo "resolve_live_url_state_ingress_address_resolved=$ingress_address_resolved_state"\n'
            '            echo "resolve_live_url_state_service_exists=$service_exists"\n'
            '            echo "resolve_live_url_state_endpoints_ready=$endpoints_ready_state"\n'
            '            echo "resolve_live_url_state_managed_certificate_exists=$managed_certificate_exists"\n'
            '            echo "resolve_live_url_state_managed_certificate_status=$managed_certificate_status_state"\n'
            '            echo "resolve_live_url_state_https_ready=$deploy_https_ready"\n'
            '            echo "resolve_live_url_state_runtime_ready_tls_pending=$runtime_ready_tls_pending_state"\n'
            '            echo "resolve_live_url_state_replace_existing_runtime_requested=$replace_existing_runtime_requested"\n'
            '            echo "resolve_live_url_state_replace_existing_runtime_performed=$replace_existing_runtime_performed"\n'
            '            echo "resolve_live_url_state_deploy_runtime_failure_stage=$deploy_runtime_failure_stage"\n'
            '            echo "resolve_live_url_state_deploy_runtime_reason_message=$deploy_runtime_reason_message"\n'
            f'            echo "resolve_live_url_state_{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}"\n'
        "          }\n"
        "          collect_ingress_502_runtime_diagnostics() {\n"
        "            preview_probe_elapsed_seconds=$(( $(date +%s) - resolve_started_at ))\n"
        "            if [ \"$preview_probe_elapsed_seconds\" -lt 0 ]; then\n"
        "              preview_probe_elapsed_seconds=0\n"
        "            fi\n"
        '            echo "Collecting ingress-502 runtime diagnostics for namespace $K8S_NAMESPACE (preview host: $preview_host)."\n'
        '            kubectl -n "$K8S_NAMESPACE" get pods -l app.kubernetes.io/name=site-web -o wide || true\n'
        '            pods_describe_output="$(mktemp)"\n'
        '            kubectl -n "$K8S_NAMESPACE" describe pods -l app.kubernetes.io/name=site-web > "$pods_describe_output" 2>&1 || true\n'
        '            print_redacted_file "$pods_describe_output"\n'
        "            if grep -qiE 'Restart Count:[[:space:]]*[1-9]|CrashLoopBackOff|Back-off restarting failed container|OOMKilled|Reason:[[:space:]]+Error' \"$pods_describe_output\"; then\n"
        "              pod_restart_detected=true\n"
        "            fi\n"
        '            rm -f "$pods_describe_output"\n'
        '            site_web_logs_output="$(mktemp)"\n'
        '            kubectl -n "$K8S_NAMESPACE" logs -l app.kubernetes.io/name=site-web --tail=200 --all-containers=true > "$site_web_logs_output" 2>&1 || true\n'
        '            print_redacted_file "$site_web_logs_output"\n'
        '            rm -f "$site_web_logs_output"\n'
        '            site_web_logs_previous_output="$(mktemp)"\n'
        '            kubectl -n "$K8S_NAMESPACE" logs -l app.kubernetes.io/name=site-web --previous --tail=100 --all-containers=true > "$site_web_logs_previous_output" 2>&1 || true\n'
        '            print_redacted_file "$site_web_logs_previous_output"\n'
        '            rm -f "$site_web_logs_previous_output"\n'
        '            deploy_yaml_output="$(mktemp)"\n'
        '            kubectl -n "$K8S_NAMESPACE" get deploy site-web -o yaml > "$deploy_yaml_output" 2>&1 || true\n'
        '            print_redacted_file "$deploy_yaml_output"\n'
        '            rm -f "$deploy_yaml_output"\n'
        '            kubectl -n "$K8S_NAMESPACE" get rs -l app.kubernetes.io/name=site-web -o wide || true\n'
        '            kubectl -n "$K8S_NAMESPACE" get events --sort-by=.lastTimestamp || true\n'
        '            ingress_describe_output_502="$(mktemp)"\n'
        '            kubectl -n "$K8S_NAMESPACE" describe ingress site-web > "$ingress_describe_output_502" 2>&1 || true\n'
        '            print_redacted_file "$ingress_describe_output_502"\n'
        "            if grep -qiE 'HEALTHY' \"$ingress_describe_output_502\"; then\n"
        '              gce_backend_health_status="HEALTHY"\n'
        "            elif grep -qiE 'UNHEALTHY|DEGRADED' \"$ingress_describe_output_502\"; then\n"
        '              gce_backend_health_status="UNHEALTHY"\n'
        "            else\n"
        '              gce_backend_health_status="UNKNOWN"\n'
        "            fi\n"
        '            rm -f "$ingress_describe_output_502"\n'
        '            endpoint_ip="$(kubectl -n "$K8S_NAMESPACE" get endpoints site-web -o jsonpath=\'{.subsets[0].addresses[0].ip}\' 2>/dev/null || true)"\n'
        '            if [ -n "$endpoint_ip" ]; then\n'
        '              k8s_endpoint_ready="true"\n'
        '              endpoints_ready="true"\n'
        "            else\n"
        '              k8s_endpoint_ready="false"\n'
        '              endpoints_ready="false"\n'
        "            fi\n"
        '            if [ -n "$preview_host" ]; then\n'
        '              preview_headers_output="$(mktemp)"\n'
        '              preview_body_output="$(mktemp)"\n'
        '              preview_https_status="$(curl --silent --show-error --connect-timeout 5 --max-time 15 -D "$preview_headers_output" -o "$preview_body_output" --write-out \'%{http_code}\' "https://$preview_host" 2>/dev/null || true)"\n'
        '              echo "Preview HTTPS diagnostics status: ${preview_https_status:-unknown}"\n'
        '              echo "--- preview HTTPS response headers (redacted) ---"\n'
        '              head -n 40 "$preview_headers_output" | redact_sensitive_stream || true\n'
        '              echo "--- preview HTTPS response snippet (redacted) ---"\n'
        '              head -c 300 "$preview_body_output" | tr -d \'\\r\' | redact_sensitive_stream || true\n'
        '              echo\n'
        '              rm -f "$preview_headers_output" "$preview_body_output"\n'
        "            fi\n"
        '            probe_pod="site-web-runtime-probe-${GITHUB_RUN_ID:-run}-${GITHUB_RUN_ATTEMPT:-1}"\n'
        "            probe_pod=\"$(echo \"$probe_pod\" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | cut -c1-63)\"\n"
        '            kubectl -n "$K8S_NAMESPACE" delete pod "$probe_pod" --ignore-not-found >/dev/null 2>&1 || true\n'
        '            service_probe_output="$(mktemp)"\n'
        '            if kubectl -n "$K8S_NAMESPACE" run "$probe_pod" --image=curlimages/curl:8.10.1 --restart=Never --attach --command -- sh -c "curl -sS --connect-timeout 5 --max-time 15 --output /tmp/body --write-out \'%{http_code}\' http://site-web.${K8S_NAMESPACE}.svc.cluster.local:80/" >"$service_probe_output" 2>&1; then\n'
        '              in_cluster_service_status_code="$(tr -cd \'0-9\' < "$service_probe_output" | tail -c 4)"\n'
        "              if [ \"$in_cluster_service_status_code\" = \"502\" ]; then\n"
        '                service_probe_status="http_502"\n'
        "              elif echo \"$in_cluster_service_status_code\" | grep -Eq '^[1-5][0-9][0-9]$'; then\n"
        '                service_probe_status="ok"\n'
        "              else\n"
        '                service_probe_status="unknown_status"\n'
        "              fi\n"
        "            else\n"
        '              service_probe_status="failed"\n'
        '              print_redacted_file "$service_probe_output"\n'
        "            fi\n"
        '            rm -f "$service_probe_output"\n'
        '            kubectl -n "$K8S_NAMESPACE" delete pod "$probe_pod" --ignore-not-found >/dev/null 2>&1 || true\n'
        '            if [ -n "$endpoint_ip" ]; then\n'
        '              endpoint_probe_output="$(mktemp)"\n'
        '              if kubectl -n "$K8S_NAMESPACE" run "$probe_pod" --image=curlimages/curl:8.10.1 --restart=Never --attach --command -- sh -c "curl -sS --connect-timeout 5 --max-time 15 --output /tmp/body --write-out \'%{http_code}\' http://${endpoint_ip}:8080/" >"$endpoint_probe_output" 2>&1; then\n'
        '                endpoint_probe_status_code="$(tr -cd \'0-9\' < "$endpoint_probe_output" | tail -c 4)"\n'
        "                if [ \"$endpoint_probe_status_code\" = \"502\" ]; then\n"
        '                  endpoint_probe_status="http_502"\n'
        "                elif echo \"$endpoint_probe_status_code\" | grep -Eq '^[1-5][0-9][0-9]$'; then\n"
        '                  endpoint_probe_status="ok"\n'
        "                else\n"
        '                  endpoint_probe_status="unknown_status"\n'
        "                fi\n"
        "              else\n"
        '                endpoint_probe_status="failed"\n'
        '                print_redacted_file "$endpoint_probe_output"\n'
        "              fi\n"
        '              rm -f "$endpoint_probe_output"\n'
        "            else\n"
        '              endpoint_probe_status="endpoint_missing"\n'
        "            fi\n"
        '            kubectl -n "$K8S_NAMESPACE" delete pod "$probe_pod" --ignore-not-found >/dev/null 2>&1 || true\n'
        '            runtime_probe_status="unknown"\n'
        '            if [ "$pod_restart_detected" = true ]; then\n'
        '              runtime_probe_status="pod_runtime_failure"\n'
        '            elif [ "$service_probe_status" = "http_502" ] || [ "$endpoint_probe_status" = "http_502" ]; then\n'
        '              runtime_probe_status="app_runtime_response_502"\n'
        '            elif [ "$service_probe_status" = "ok" ] && [ "$endpoint_probe_status" = "ok" ] \\\n'
        '              && [ "$preview_https_status" = "502" ] && [ "$gce_backend_health_status" = "HEALTHY" ]; then\n'
        '              runtime_probe_status="ingress_or_edge_convergence"\n'
        '            elif [ "$service_probe_status" = "failed" ] || [ "$endpoint_probe_status" = "failed" ]; then\n'
        '              runtime_probe_status="service_probe_failed"\n'
        "            fi\n"
        '            echo "deploy_runtime_reason_context=gce_backend_health=${gce_backend_health_status:-UNKNOWN};k8s_endpoint_ready=${k8s_endpoint_ready:-unknown};preview_https_status=${preview_https_status:-unknown};service_probe_status=${service_probe_status:-unknown};endpoint_probe_status=${endpoint_probe_status:-unknown};runtime_probe_status=${runtime_probe_status:-unknown}"\n'
        "          }\n"
        "          emit_final_deploy_runtime_summary() {\n"
        '            runtime_ready_state="false"\n'
        '            if [ "$deploy_https_ready" = "true" ]; then\n'
        '              runtime_ready_state="true"\n'
        "            fi\n"
        '            ingress_address_resolved_state="false"\n'
        '            if [ -n "${ingress_ip:-}" ] || [ -n "${ingress_host:-}" ] || [ -n "${ingress_status_ip:-}" ]; then\n'
        '              ingress_address_resolved_state="true"\n'
        "            fi\n"
        '            endpoints_ready_state="${endpoints_ready:-unknown}"\n'
        '            if [ "$endpoints_ready_state" = "unknown" ] && [ -n "${k8s_endpoint_ready:-}" ]; then\n'
        '              endpoints_ready_state="$k8s_endpoint_ready"\n'
        "            fi\n"
        '            managed_certificate_status_state="$tls_certificate_status"\n'
        '            if [ -z "$managed_certificate_status_state" ] && [ -n "$observed_managed_certificate_status" ]; then\n'
        '              managed_certificate_status_state="$observed_managed_certificate_status"\n'
        "            fi\n"
        '            runtime_ready_tls_pending_state="false"\n'
        "            normalized_cert_status_state=\"$(echo \"${tls_certificate_status:-}\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        "            normalized_domain_status_state=\"$(echo \"${tls_domain_status:-}\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        '            if [ "$runtime_ready_state" != "true" ] \\\n'
        '              && [ "$ingress_address_resolved_state" = "true" ] \\\n'
        '              && { [ "$normalized_cert_status_state" = "PROVISIONING" ] || [ "$normalized_domain_status_state" = "PROVISIONING" ]; }; then\n'
        '              runtime_ready_tls_pending_state="true"\n'
        "            fi\n"
        '            echo "runtime_ready=$runtime_ready_state"\n'
        '            echo "ingress_address_resolved=$ingress_address_resolved_state"\n'
        '            echo "service_exists=$service_exists"\n'
        '            echo "endpoints_ready=$endpoints_ready_state"\n'
        '            echo "managed_certificate_exists=$managed_certificate_exists"\n'
        '            echo "managed_certificate_status=$managed_certificate_status_state"\n'
        '            echo "https_ready=$deploy_https_ready"\n'
        '            echo "runtime_ready_tls_pending=$runtime_ready_tls_pending_state"\n'
        '            echo "replace_existing_runtime_requested=$replace_existing_runtime_requested"\n'
        '            echo "replace_existing_runtime_performed=$replace_existing_runtime_performed"\n'
        "          }\n"
        "          finalize_resolve_live_url() {\n"
        '            resolve_live_url_exit_code="$?"\n'
        "            trap - EXIT\n"
        '            if [ "$resolve_live_url_exit_code" -ne 0 ]; then\n'
        "              emit_resolve_live_url_state\n"
        '              observed_reason_code="$(grep -E \'^[[:space:]]*deploy_runtime_reason_code=\' "$resolve_live_url_log_path" | tail -n1 | cut -d\'=\' -f2- | tr -d \'\\r\' || true)"\n'
        '              if [ -z "$observed_reason_code" ]; then\n'
        f'                observed_reason_code="{_DEPLOY_RUNTIME_REASON_RUNTIME_READINESS_UNKNOWN_FAILURE}"\n'
        '                echo "deploy_runtime_reason_code=$observed_reason_code"\n'
        '                deploy_runtime_reason_message="Managed-site runtime readiness failed before a precise reason was recorded."\n'
        "              fi\n"
        '              observed_reason_message="$(grep -E \'^[[:space:]]*deploy_runtime_reason_message=\' "$resolve_live_url_log_path" | tail -n1 | cut -d\'=\' -f2- | tr -d \'\\r\' || true)"\n'
        '              if [ -n "$observed_reason_message" ]; then\n'
        '                deploy_runtime_reason_message="$observed_reason_message"\n'
        '              elif [ -z "$deploy_runtime_reason_message" ]; then\n'
        '                deploy_runtime_reason_message="Managed-site runtime readiness failed. Review workflow diagnostics for bounded evidence."\n'
        "              fi\n"
        '              observed_failure_stage="$(grep -E \'^[[:space:]]*deploy_runtime_failure_stage=\' "$resolve_live_url_log_path" | tail -n1 | cut -d\'=\' -f2- | tr -d \'\\r\' || true)"\n'
        '              if [ -n "$observed_failure_stage" ]; then\n'
        '                deploy_runtime_failure_stage="$observed_failure_stage"\n'
        "              fi\n"
        '              if [ -z "${deploy_runtime_failure_stage:-}" ]; then\n'
        '                deploy_runtime_failure_stage="ingress_evidence"\n'
        "              fi\n"
        '              echo "deploy_runtime_reason_code=$observed_reason_code"\n'
        '              echo "deploy_runtime_reason_message=$deploy_runtime_reason_message"\n'
        '              echo "deploy_runtime_failure_stage=$deploy_runtime_failure_stage"\n'
        "              emit_final_deploy_runtime_summary\n"
        "            fi\n"
        '            if [ -n "${resolve_live_url_log_path:-}" ] && [ -f "$resolve_live_url_log_path" ]; then\n'
        '              rm -f "$resolve_live_url_log_path"\n'
        "            fi\n"
        '            exit "$resolve_live_url_exit_code"\n'
        "          }\n"
        "          trap finalize_resolve_live_url EXIT\n"
        "          collect_resolve_live_url_evidence() {\n"
        '            ingress_host="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.status.loadBalancer.ingress[0].hostname}\' 2>/dev/null || true)"\n'
        '            ingress_ip="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.status.loadBalancer.ingress[0].ip}\' 2>/dev/null || true)"\n'
        '            ingress_spec_host="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.spec.rules[0].host}\' 2>/dev/null || true)"\n'
        '            if kubectl get service site-web --namespace "$K8S_NAMESPACE" >/dev/null 2>&1; then\n'
        '              service_exists="true"\n'
        "            else\n"
        '              service_exists="false"\n'
        "            fi\n"
        '            endpoints_address_probe="$(kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.subsets[0].addresses[0].ip}\' 2>/dev/null || true)"\n'
        '            if [ -n "$endpoints_address_probe" ]; then\n'
        '              endpoints_ready="true"\n'
        "            else\n"
        '              endpoints_ready="false"\n'
        "            fi\n"
        '            if [ -z "$preview_host" ] && [ -n "$ingress_spec_host" ]; then\n'
        '              preview_host="$ingress_spec_host"\n'
        "            fi\n"
        '            ingress_status_ip="$ingress_ip"\n'
        "            expected_static_ip_name=\"$(echo \"$MBSRN_PREVIEW_STATIC_IP_NAME\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        '            ingress_static_ip_annotation="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.metadata.annotations.kubernetes\\.io/ingress\\.global-static-ip-name}\' 2>/dev/null || true)"\n'
        "            normalized_ingress_static_ip_annotation=\"$(echo \"$ingress_static_ip_annotation\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        '            static_ip_metadata_json="$(gcloud compute addresses describe "$MBSRN_PREVIEW_STATIC_IP_NAME" --global --project "$GKE_PROJECT_ID" --format=\'json(name,address,status,users)\' 2>/dev/null || true)"\n'
        '            if [ -n "$static_ip_metadata_json" ]; then\n'
        '              static_ip_metadata_eval="$(STATIC_IP_METADATA_JSON="$static_ip_metadata_json" python - <<\'PY\'\n'
        "          import json\n"
        "          import os\n"
        "\n"
        "          raw = str(os.environ.get('STATIC_IP_METADATA_JSON') or '').strip()\n"
        "          payload = {}\n"
        "          if raw:\n"
        "              try:\n"
        "                  payload = json.loads(raw)\n"
        "              except Exception:\n"
        "                  payload = {}\n"
        "          address = str(payload.get('address') or '').strip()\n"
        "          status = str(payload.get('status') or '').strip().upper()\n"
        "          users = payload.get('users')\n"
        "          normalized_users = []\n"
        "          if isinstance(users, list):\n"
        "              for item in users:\n"
        "                  candidate = str(item or '').strip()\n"
        "                  if candidate:\n"
        "                      normalized_users.append(candidate)\n"
        "          print(f'address={address}')\n"
        "          print(f'status={status}')\n"
        "          print('users=' + ','.join(normalized_users))\n"
        "          PY\n"
        '              )"\n'
        "              while IFS='=' read -r key value; do\n"
        '                case "$key" in\n'
        "                  address)\n"
        '                    expected_static_ip_address="$value"\n'
        "                    ;;\n"
        "                  status)\n"
        '                    static_ip_status="$value"\n'
        "                    ;;\n"
        "                  users)\n"
        '                    static_ip_users="$value"\n'
        "                    ;;\n"
        "                esac\n"
        '              done <<< "$static_ip_metadata_eval"\n'
        "            fi\n"
        "            ingress_status_ip_matches_static_ip=false\n"
        '            if [ -n "$expected_static_ip_address" ]; then\n'
        '              dns_expected_ip="$expected_static_ip_address"\n'
        '              if [ -n "$ingress_status_ip" ] && [ "$ingress_status_ip" = "$expected_static_ip_address" ]; then\n'
        "                ingress_status_ip_matches_static_ip=true\n"
        "              fi\n"
        "            else\n"
        '              dns_expected_ip="$ingress_status_ip"\n'
        "            fi\n"
        "            static_ip_bound_to_expected_forwarding_rule=false\n"
        '            if [ -n "$static_ip_users" ] && [ -n "$K8S_NAMESPACE" ]; then\n'
        "              static_ip_users_lower=\"$(echo \"$static_ip_users\" | tr '[:upper:]' '[:lower:]')\"\n"
        "              namespace_token=\"$(echo \"$K8S_NAMESPACE\" | tr '[:upper:]' '[:lower:]')\"\n"
        "              if echo \"$static_ip_users_lower\" | grep -q '/forwardingrules/' \\\n"
        '                && echo "$static_ip_users_lower" | grep -q "$namespace_token" \\\n'
        "                && echo \"$static_ip_users_lower\" | grep -q 'site-web'; then\n"
        "                static_ip_bound_to_expected_forwarding_rule=true\n"
        "              fi\n"
        "            fi\n"
        '            dns_observed_ip=""\n'
        '            if [ -n "$preview_host" ]; then\n'
        "              if command -v dig >/dev/null 2>&1; then\n"
        "                dns_observed_ip=\"$(dig +short \"$preview_host\" A | grep -E '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$' | head -n1 | tr -d '[:space:]')\"\n"
        "              fi\n"
        '              if [ -z "$dns_observed_ip" ] && command -v nslookup >/dev/null 2>&1; then\n'
        "                dns_observed_ip=\"$(nslookup \"$preview_host\" 2>/dev/null | awk '/^Address: / {print $2}' | tail -n1 | tr -d '[:space:]')\"\n"
        "              fi\n"
        "            fi\n"
        '            if [ -n "$dns_expected_ip" ] && [ -n "$dns_observed_ip" ] && [ "$dns_observed_ip" = "$dns_expected_ip" ]; then\n'
        "              dns_record_matches_ingress=true\n"
        "            else\n"
        "              dns_record_matches_ingress=false\n"
        "            fi\n"
        '            managed_certificate_json="$(kubectl get managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" -o json 2>/dev/null || true)"\n'
        '            observed_managed_certificate_domains=""\n'
        '            observed_managed_certificate_status=""\n'
        '            observed_managed_certificate_domain_status=""\n'
        '            if [ -n "$managed_certificate_json" ]; then\n'
        '              managed_certificate_exists="true"\n'
        "              expected_cert_name_collect=\"$(echo \"$MBSRN_PREVIEW_CERTIFICATE_NAME\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        '              cert_collect_output="$(MANAGED_CERTIFICATE_JSON="$managed_certificate_json" EXPECTED_PREVIEW_HOST="$preview_host" EXPECTED_CERT_NAME="$expected_cert_name_collect" python - <<\'PY\'\n'
        "          import json\n"
        "          import os\n"
        "\n"
        "          raw = str(os.environ.get('MANAGED_CERTIFICATE_JSON') or '').strip()\n"
        "          expected_host = str(os.environ.get('EXPECTED_PREVIEW_HOST') or '').strip().lower()\n"
        "          payload = json.loads(raw) if raw else {}\n"
        "          spec_domains = [\n"
        "              str(item).strip().lower()\n"
        "              for item in (payload.get('spec', {}).get('domains') or [])\n"
        "              if str(item).strip()\n"
        "          ]\n"
        "          status_payload = payload.get('status') if isinstance(payload.get('status'), dict) else {}\n"
        "          cert_status = str(status_payload.get('certificateStatus') or '').strip().upper()\n"
        "          domain_status_payload = status_payload.get('domainStatus')\n"
        "          domain_status_map = {}\n"
        "          if isinstance(domain_status_payload, list):\n"
        "              for item in domain_status_payload:\n"
        "                  if not isinstance(item, dict):\n"
        "                      continue\n"
        "                  domain = str(item.get('domain') or '').strip().lower()\n"
        "                  status = str(item.get('status') or '').strip().upper()\n"
        "                  if domain:\n"
        "                      domain_status_map[domain] = status\n"
        "          elif isinstance(domain_status_payload, dict):\n"
        "              for key, value in domain_status_payload.items():\n"
        "                  domain = str(key or '').strip().lower()\n"
        "                  if not domain:\n"
        "                      continue\n"
        "                  if isinstance(value, dict):\n"
        "                      status = str(value.get('status') or '').strip().upper()\n"
        "                  else:\n"
        "                      status = str(value or '').strip().upper()\n"
        "                  domain_status_map[domain] = status\n"
        "          domain_status = domain_status_map.get(expected_host, '') if expected_host else ''\n"
        "          domain_exact_match = bool(expected_host) and len(spec_domains) == 1 and spec_domains[0] == expected_host\n"
        "          print(f'cert_status={cert_status}')\n"
        "          print(f'domain_status={domain_status}')\n"
        "          print('domain_exact_match=' + ('true' if domain_exact_match else 'false'))\n"
        "          print('spec_domains=' + ','.join(spec_domains))\n"
        "          PY\n"
        '              )"\n'
        "              domain_exact_match=false\n"
        "              while IFS='=' read -r key value; do\n"
        '                case "$key" in\n'
        "                  cert_status)\n"
        '                    tls_certificate_status="$value"\n'
        "                    ;;\n"
        "                  domain_status)\n"
        '                    tls_domain_status="$value"\n'
        "                    ;;\n"
        "                  domain_exact_match)\n"
        '                    domain_exact_match="$value"\n'
        "                    ;;\n"
        "                  spec_domains)\n"
        '                    observed_managed_certificate_domains="$value"\n'
        "                    ;;\n"
        "                esac\n"
        '              done <<< "$cert_collect_output"\n'
        "              normalized_cert_status=\"$(echo \"$tls_certificate_status\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        "              normalized_domain_status=\"$(echo \"$tls_domain_status\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        '              if [ -z "$observed_managed_certificate_domains" ] && [ "$domain_exact_match" = "true" ] && [ -n "$preview_host" ]; then\n'
        '                observed_managed_certificate_domains="$preview_host"\n'
        "              fi\n"
        '              observed_managed_certificate_status="$tls_certificate_status"\n'
        '              observed_managed_certificate_domain_status="$tls_domain_status"\n'
        '              if [ "$domain_exact_match" = "true" ]; then\n'
        "                cert_identity_valid=true\n"
        "              else\n"
        "                cert_identity_valid=false\n"
        "              fi\n"
        "            else\n"
        '              managed_certificate_exists="false"\n'
        "            fi\n"
        "          }\n"
        '          for attempt in $(seq 1 "$max_attempts"); do\n'
        '            preview_probe_attempt="$attempt"\n'
        '            ingress_host="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.status.loadBalancer.ingress[0].hostname}\' 2>/dev/null || true)"\n'
        '            ingress_ip="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.status.loadBalancer.ingress[0].ip}\' 2>/dev/null || true)"\n'
        '            ingress_spec_host="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.spec.rules[0].host}\' 2>/dev/null || true)"\n'
        '            if [ -z "$preview_host" ] && [ -n "$ingress_spec_host" ]; then\n'
        '              preview_host="$ingress_spec_host"\n'
        "            fi\n"
        '            if [ -n "$preview_host" ]; then\n'
        '              https_probe_output="$(mktemp)"\n'
        "              https_probe_attempted=true\n"
        '              if https_code="$(curl --silent --show-error --connect-timeout 5 --max-time 10 --output /dev/null --write-out \'%{http_code}\' "https://$preview_host" 2>"$https_probe_output")"; then\n'
        "                if echo \"$https_code\" | grep -Eq '^[1-5][0-9][0-9]$'; then\n"
        '                  preview_https_status="$https_code"\n'
        '                  if [ "$https_code" = "502" ]; then\n'
        "                    backend_502_detected=true\n"
        '                    set_https_probe_error_summary "ingress_backend_502" "" "$https_code" "$https_probe_output"\n'
        '                    echo "deploy_runtime_reason_code=ingress_backend_502"\n'
        '                    echo "Expected preview hostname responded with ${https_code} over HTTPS, indicating backend unhealthy state."\n'
        '                    rm -f "$https_probe_output"\n'
        "                    break\n"
        "                  fi\n"
        "                  host_reachable=true\n"
        '                  host_reachability_scheme="https"\n'
        '                  rm -f "$https_probe_output"\n'
        '                  echo "Expected preview hostname responded over HTTPS on attempt ${attempt}/${max_attempts} with status ${https_code}."\n'
        "                  break\n"
        "                fi\n"
        "              else\n"
        "                https_exit=$?\n"
        '                if [ "$https_exit" -eq 60 ] || grep -qiE \'SSL certificate problem|SSL_ERROR_BAD_CERT_DOMAIN|certificate subject name|no alternative certificate subject name\' "$https_probe_output"; then\n'
        "                  tls_mismatch_detected=true\n"
        '                  echo "Expected preview hostname is reachable but TLS certificate does not match."\n'
        '                  echo "deploy_runtime_reason_code=reachable_but_tls_certificate_mismatch"\n'
        '                  set_https_probe_error_summary "reachable_but_tls_certificate_mismatch" "$https_exit" "" "$https_probe_output"\n'
        '                  cat "$https_probe_output"\n'
        '                  rm -f "$https_probe_output"\n'
        "                  break\n"
        "                fi\n"
        "              fi\n"
        '              rm -f "$https_probe_output"\n'
        "              http_fallback_attempted=true\n"
        '              http_code="$(curl --silent --show-error --connect-timeout 5 --max-time 10 --output /dev/null --write-out \'%{http_code}\' "http://$preview_host" 2>/dev/null || true)"\n'
        "              if echo \"$http_code\" | grep -Eq '^[1-5][0-9][0-9]$'; then\n"
        '                preview_http_status="$http_code"\n'
        '                if [ "$http_code" = "502" ]; then\n'
        "                  backend_502_detected=true\n"
        '                  set_https_probe_error_summary "ingress_backend_502" "" "$http_code" ""\n'
        '                  echo "deploy_runtime_reason_code=ingress_backend_502"\n'
        '                  echo "Expected preview hostname responded with ${http_code} over HTTP, indicating backend unhealthy state."\n'
        "                  break\n"
        "                fi\n"
        "                host_reachable=true\n"
        '                host_reachability_scheme="http"\n'
        '                echo "Expected preview hostname responded over HTTP on attempt ${attempt}/${max_attempts} with status ${http_code}."\n'
        '                echo "deploy_runtime_reason_code=ingress_address_pending_but_hostname_reachable"\n'
        "                break\n"
        "              fi\n"
        "            fi\n"
        '            if [ -n "$ingress_host" ] || [ -n "$ingress_ip" ]; then\n'
        '              echo "Ingress external address resolved on attempt ${attempt}/${max_attempts}."\n'
        "              break\n"
        "            fi\n"
        '            if [ "$attempt" -lt "$max_attempts" ]; then\n'
        '              echo "Ingress external address not ready yet (attempt ${attempt}/${max_attempts}); sleeping ${sleep_seconds}s."\n'
        '              sleep "$sleep_seconds"\n'
        "            fi\n"
        "          done\n"
        "          collect_resolve_live_url_evidence\n"
        '          if [ "$tls_mismatch_detected" = true ]; then\n'
        "            normalized_cert_status_early=\"$(echo \"$tls_certificate_status\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        "            normalized_domain_status_early=\"$(echo \"$tls_domain_status\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        '            if [ "$normalized_domain_status_early" = "FAILED_NOT_VISIBLE" ] || [ "$normalized_cert_status_early" = "FAILED_NOT_VISIBLE" ]; then\n'
        '              echo "deploy_runtime_reason_code=managed_certificate_failed_not_visible"\n'
        '              echo "deploy_runtime_reason_message=ManagedCertificate is not visible; verify DNS and load balancer exposure."\n'
        '            elif [ "$normalized_domain_status_early" = "PROVISIONING" ] || [ "$normalized_cert_status_early" = "PROVISIONING" ] || [ "$normalized_domain_status_early" = "" ] || [ "$normalized_domain_status_early" = "UNKNOWN" ] || [ "$normalized_cert_status_early" = "UNKNOWN" ]; then\n'
        '              echo "deploy_runtime_reason_code=managed_certificate_pending"\n'
        '              echo "deploy_runtime_reason_code=tls_certificate_provisioning"\n'
        '              echo "deploy_runtime_reason_code=certificate_provisioning_pending"\n'
        '              echo "deploy_runtime_reason_code=runtime_ready_tls_pending"\n'
        '              echo "deploy_runtime_reason_message=ManagedCertificate provisioning/status is still pending for expected hostname."\n'
        "            else\n"
        '              echo "deploy_runtime_reason_code=tls_certificate_bound_to_wrong_site"\n'
        '              echo "deploy_runtime_reason_code=reachable_but_tls_certificate_mismatch"\n'
        '              echo "deploy_runtime_reason_message=Expected hostname is reachable but TLS certificate is bound to another site."\n'
        "            fi\n"
        '            kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" || true\n'
        '            kubectl describe managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$backend_502_detected" = true ]; then\n'
        '            if [ -z "$https_probe_error_summary" ]; then\n'
        '              set_https_probe_error_summary "ingress_backend_502" "" "502" ""\n'
        "            fi\n"
        "            collect_ingress_502_runtime_diagnostics\n"
        '            if [ "$gce_backend_health_status" = "HEALTHY" ] && [ "$service_probe_status" = "ok" ] && [ "$preview_https_status" = "502" ]; then\n'
        '              echo "deploy_runtime_reason_message=Preview hostname is reachable but returns HTTP 502 while GCE backend reports HEALTHY and in-cluster probes succeed. Likely ingress/LB edge convergence or stale backend path."\n'
        '            elif [ "$service_probe_status" = "http_502" ] || [ "$endpoint_probe_status" = "http_502" ]; then\n'
        '              echo "deploy_runtime_reason_message=Preview hostname is reachable but returns HTTP 502 and in-cluster service/endpoint probes also return 502. Likely app runtime response failure."\n'
        '            elif [ "$pod_restart_detected" = true ]; then\n'
        '              echo "deploy_runtime_reason_message=Preview hostname is reachable but returns HTTP 502 with pod restart/crash evidence. Likely pod runtime instability."\n'
        "            else\n"
        '              echo "deploy_runtime_reason_message=Ingress hostname is reachable but backend returned 5xx. Review pod logs, in-cluster service probe status, endpoint probe status, and backend health evidence."\n'
        "            fi\n"
        '            kubectl get service site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl describe service site-web --namespace "$K8S_NAMESPACE" || true\n'
        '            kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o wide || true\n'
        '            kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" || true\n'
        '            kubectl describe backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$host_reachable" = true ] && [ -n "$preview_host" ]; then\n'
        '            if [ "$host_reachability_scheme" = "http" ]; then\n'
        '              live_url="http://$preview_host"\n'
        "            else\n"
        '              live_url="https://$preview_host"\n'
        "            fi\n"
        '          elif [ -n "$preview_host" ]; then\n'
        '            live_url="https://$preview_host"\n'
        '          elif [ -n "$ingress_host" ]; then\n'
        '            live_url="https://$ingress_host"\n'
        '          elif [ -n "$ingress_ip" ]; then\n'
        '            live_url="http://$ingress_ip"\n'
        "          fi\n"
        '          if [ -z "$live_url" ]; then\n'
        '            if [ "$https_probe_attempted" != "true" ]; then\n'
        '              https_probe_error_summary="reason=https_probe_not_attempted;detail=https_probe_not_attempted"\n'
        '              echo "deploy_runtime_reason_code=https_probe_not_attempted"\n'
        "            fi\n"
        '            echo "Ingress created but external address is not assigned yet for namespace $K8S_NAMESPACE."\n'
        '            echo "Likely rollout blocker: ingress/load balancer provisioning still in progress."\n'
        '            echo "This may take several minutes on GKE."\n'
        '            echo "deploy_runtime_reason_code=ingress_address_pending"\n'
        '            echo "deploy_runtime_reason_message=Ingress created but external address not yet assigned."\n'
        '            kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" || true\n'
        '            kubectl get service site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o wide || true\n'
        '            kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o wide || true\n'
        '            kubectl get managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        '            managedcertificate_pending_output="$(mktemp)"\n'
        '            kubectl describe managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" > "$managedcertificate_pending_output" 2>&1 || true\n'
        '            cat "$managedcertificate_pending_output"\n'
        "            if grep -qiE 'failednotvisible' \"$managedcertificate_pending_output\"; then\n"
        '              echo "deploy_runtime_reason_code=managed_certificate_failed_not_visible"\n'
        "            fi\n"
        '            rm -f "$managedcertificate_pending_output"\n'
        '            ingress_pending_output="$(mktemp)"\n'
        '            kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" > "$ingress_pending_output" 2>&1 || true\n'
        '            cat "$ingress_pending_output"\n'
        "            if grep -qiE 'NEG|network endpoint group|load balancer|loadbalancer|creating|attaching|detaching|sync|provisioning|reconcile' \"$ingress_pending_output\"; then\n"
        '              echo "deploy_runtime_reason_code=ingress_neg_convergence_pending"\n'
        "            fi\n"
        "            if grep -qiE 'in-use and would result in a conflict|global static ip.*conflict|specified ip address is in-use' \"$ingress_pending_output\"; then\n"
        '              echo "deploy_runtime_reason_code=ingress_static_ip_conflict"\n'
        "            fi\n"
        '            pre_shared_pending_annotation="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.metadata.annotations.ingress\\.gcp\\.kubernetes\\.io/pre-shared-cert}\' 2>/dev/null || true)"\n'
        '            if [ -n "$pre_shared_pending_annotation" ]; then\n'
        '              echo "Observed ingress pre-shared certificate controller metadata: $pre_shared_pending_annotation"\n'
        "              expected_cert_name_pending=\"$(echo \"$MBSRN_PREVIEW_CERTIFICATE_NAME\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        "              pre_shared_pending_values=\"$(echo \"$pre_shared_pending_annotation\" | tr ',' '\\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d' | tr '[:upper:]' '[:lower:]')\"\n"
        "              pre_shared_pending_count=\"$(echo \"$pre_shared_pending_values\" | sed '/^$/d' | wc -l | tr -d '[:space:]')\"\n"
        '              pre_shared_pending_first="$(echo "$pre_shared_pending_values" | head -n1 | tr -d \'[:space:]\')"\n'
        "              pre_shared_pending_metadata_mismatch=false\n"
        '              if [ "$pre_shared_pending_count" -ne 1 ] || [ "$pre_shared_pending_first" != "$expected_cert_name_pending" ]; then\n'
        "                pre_shared_pending_metadata_mismatch=true\n"
        "              fi\n"
        '              if [ "$pre_shared_pending_metadata_mismatch" = true ]; then\n'
        '                echo "deploy_runtime_reason_code=pre_shared_cert_metadata_mismatch"\n'
        "              fi\n"
        "            fi\n"
        '            rm -f "$ingress_pending_output"\n'
        '            kubectl get frontendconfig "$MBSRN_FRONTEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        '            kubectl get backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ -z "$preview_host" ]; then\n'
        '            if [ "$https_probe_attempted" != "true" ]; then\n'
        '              https_probe_error_summary="reason=https_probe_not_attempted;detail=preview_host_missing"\n'
        '              echo "deploy_runtime_reason_code=https_probe_not_attempted"\n'
        "            fi\n"
        '            echo "deploy_runtime_reason_code=ingress_address_pending"\n'
        '            echo "deploy_runtime_reason_message=Preview hostname is missing; cannot validate DNS/TLS identity."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$host_reachable" = true ] && [ "$host_reachability_scheme" = "https" ] && [ -z "$ingress_ip" ]; then\n'
        '            ingress_ip="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.status.loadBalancer.ingress[0].ip}\' 2>/dev/null || true)"\n'
        '            ingress_host="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.status.loadBalancer.ingress[0].hostname}\' 2>/dev/null || true)"\n'
        '            if [ -n "$ingress_ip" ] || [ -n "$ingress_host" ]; then\n'
        '              echo "Ingress external address observed after HTTPS success verification."\n'
        "            fi\n"
        "          fi\n"
        '          if [ -z "$ingress_ip" ] && [ "$host_reachable" != "true" ]; then\n'
        '            echo "deploy_runtime_reason_code=ingress_address_pending"\n'
        '            echo "deploy_runtime_reason_message=Ingress external IP is required before DNS/TLS validation."\n'
        "            exit 1\n"
        "          fi\n"
        '          ingress_status_ip="$ingress_ip"\n'
        '          dns_expected_ip="$ingress_status_ip"\n'
        "          expected_static_ip_name=\"$(echo \"$MBSRN_PREVIEW_STATIC_IP_NAME\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        '          ingress_static_ip_annotation="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.metadata.annotations.kubernetes\\.io/ingress\\.global-static-ip-name}\' 2>/dev/null || true)"\n'
        "          normalized_ingress_static_ip_annotation=\"$(echo \"$ingress_static_ip_annotation\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        '          echo "expected_static_ip_name=$expected_static_ip_name"\n'
        '          echo "observed_ingress_static_ip_annotation=$ingress_static_ip_annotation"\n'
        '          if [ -z "$normalized_ingress_static_ip_annotation" ]; then\n'
        "            ingress_conflict_detected=true\n"
        '            echo "deploy_runtime_reason_code=expected_static_ip_not_bound_to_ingress"\n'
        '            echo "deploy_runtime_reason_message=Ingress is missing expected per-site static IP annotation binding."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$normalized_ingress_static_ip_annotation" != "$expected_static_ip_name" ]; then\n'
        "            ingress_conflict_detected=true\n"
        '            echo "deploy_runtime_reason_code=ingress_static_ip_conflict"\n'
        '            echo "deploy_runtime_reason_code=shared_static_ip_not_allowed_for_per_site_ingress"\n'
        '            echo "deploy_runtime_reason_message=Ingress static IP annotation does not match expected per-site static IP name."\n'
        "            exit 1\n"
        "          fi\n"
        '          static_ip_metadata_json="$(gcloud compute addresses describe "$MBSRN_PREVIEW_STATIC_IP_NAME" --global --project "$GKE_PROJECT_ID" --format=\'json(name,address,status,users)\' 2>/dev/null || true)"\n'
        '          if [ -n "$static_ip_metadata_json" ]; then\n'
        '            static_ip_metadata_eval="$(STATIC_IP_METADATA_JSON="$static_ip_metadata_json" python - <<\'PY\'\n'
        "          import json\n"
        "          import os\n"
        "\n"
        "          raw = str(os.environ.get('STATIC_IP_METADATA_JSON') or '').strip()\n"
        "          payload = {}\n"
        "          if raw:\n"
        "              try:\n"
        "                  payload = json.loads(raw)\n"
        "              except Exception:\n"
        "                  payload = {}\n"
        "          address = str(payload.get('address') or '').strip()\n"
        "          status = str(payload.get('status') or '').strip().upper()\n"
        "          users = payload.get('users')\n"
        "          normalized_users = []\n"
        "          if isinstance(users, list):\n"
        "              for item in users:\n"
        "                  candidate = str(item or '').strip()\n"
        "                  if candidate:\n"
        "                      normalized_users.append(candidate)\n"
        "          print(f'address={address}')\n"
        "          print(f'status={status}')\n"
        "          print('users=' + ','.join(normalized_users))\n"
        "          PY\n"
        '            )"\n'
        "            while IFS='=' read -r key value; do\n"
        '              case "$key" in\n'
        "                address)\n"
        '                  expected_static_ip_address="$value"\n'
        "                  ;;\n"
        "                status)\n"
        '                  static_ip_status="$value"\n'
        "                  ;;\n"
        "                users)\n"
        '                  static_ip_users="$value"\n'
        "                  ;;\n"
        "              esac\n"
        "            done <<EOF\n"
        "          $static_ip_metadata_eval\n"
        "          EOF\n"
        "          fi\n"
        '          if [ -n "$expected_static_ip_address" ]; then\n'
        '            dns_expected_ip="$expected_static_ip_address"\n'
        '            if [ -n "$ingress_status_ip" ] && [ "$ingress_status_ip" = "$expected_static_ip_address" ]; then\n'
        "              ingress_status_ip_matches_static_ip=true\n"
        "            fi\n"
        "          fi\n"
        "          namespace_binding_token=\"$(echo \"$K8S_NAMESPACE\" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')\"\n"
        '          if [ -n "$static_ip_users" ] && [ -n "$namespace_binding_token" ]; then\n'
        "            static_ip_users_lower=\"$(echo \"$static_ip_users\" | tr '[:upper:]' '[:lower:]')\"\n"
        "            while IFS= read -r static_user_entry; do\n"
        '              if [ -z "$static_user_entry" ]; then\n'
        "                continue\n"
        "              fi\n"
        "              if echo \"$static_user_entry\" | grep -Fq '/global/forwardingRules/' \\\n"
        "                && echo \"$static_user_entry\" | grep -Fq 'site-web' \\\n"
        '                && echo "$static_user_entry" | grep -Fq "$namespace_binding_token"; then\n'
        "                static_ip_bound_to_expected_forwarding_rule=true\n"
        "                break\n"
        "              fi\n"
        "            done <<EOF\n"
        "          $(echo \"$static_ip_users_lower\" | tr ',' '\\n')\n"
        "          EOF\n"
        "          fi\n"
        '          if [ -n "$expected_static_ip_address" ]; then\n'
        '            if [ "$static_ip_status" != "IN_USE" ] || [ "$static_ip_bound_to_expected_forwarding_rule" != "true" ]; then\n'
        "              ingress_conflict_detected=true\n"
        '              echo "deploy_runtime_reason_code=expected_static_ip_not_bound_to_ingress"\n'
        '              echo "deploy_runtime_reason_message=Reserved per-site static IP is not yet bound to expected forwarding rules for this site ingress."\n'
        '              echo "expected_static_ip_address=$expected_static_ip_address"\n'
        '              echo "static_ip_status=$static_ip_status"\n'
        '              echo "static_ip_users=$static_ip_users"\n'
        "              exit 1\n"
        "            fi\n"
        "          fi\n"
        '          if [ -z "$dns_expected_ip" ]; then\n'
        '            echo "deploy_runtime_reason_code=ingress_address_pending"\n'
        '            echo "deploy_runtime_reason_message=Neither ingress status IP nor reserved static IP address is available for DNS/TLS validation yet."\n'
        "            exit 1\n"
        "          fi\n"
        '          ingress_validation_output="$(mktemp)"\n'
        '          kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" > "$ingress_validation_output" 2>&1 || true\n'
        "          if grep -qiE 'in-use and would result in a conflict|global static ip.*conflict|specified ip address is in-use' \"$ingress_validation_output\"; then\n"
        "            ingress_conflict_detected=true\n"
        '            echo "deploy_runtime_reason_code=ingress_static_ip_conflict"\n'
        '            cat "$ingress_validation_output"\n'
        '            rm -f "$ingress_validation_output"\n'
        "            exit 1\n"
        "          fi\n"
        '          rm -f "$ingress_validation_output"\n'
        "          expected_cert_name=\"$(echo \"$MBSRN_PREVIEW_CERTIFICATE_NAME\" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')\"\n"
        "          pre_shared_cert_metadata_mismatch=false\n"
        "          pre_shared_cert_controller_cross_site_evidence=false\n"
        '          managed_cert_annotation="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.metadata.annotations.networking\\.gke\\.io/managed-certificates}\' 2>/dev/null || true)"\n'
        '          echo "managed_certificate_resource_name=$MBSRN_PREVIEW_CERTIFICATE_NAME"\n'
        '          echo "expected_preview_hostname=$preview_host"\n'
        '          echo "expected_managed_certificate_name=$expected_cert_name"\n'
        '          echo "observed_managed_certificate_annotation=$managed_cert_annotation"\n'
        "          managed_cert_annotation_values=\"$(echo \"$managed_cert_annotation\" | tr ',' '\\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d' | tr '[:upper:]' '[:lower:]')\"\n"
        "          managed_cert_annotation_count=\"$(echo \"$managed_cert_annotation_values\" | sed '/^$/d' | wc -l | tr -d '[:space:]')\"\n"
        '          managed_cert_annotation_first="$(echo "$managed_cert_annotation_values" | head -n1 | tr -d \'[:space:]\')"\n'
        '          if [ "$managed_cert_annotation_count" -le 0 ]; then\n'
        '            echo "deploy_runtime_reason_code=ingress_certificate_annotation_mismatch"\n'
        '            echo "deploy_runtime_reason_message=Ingress is missing managed certificate annotation."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$managed_cert_annotation_count" -gt 1 ]; then\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_identity_mismatch"\n'
        '            echo "deploy_runtime_reason_message=Ingress annotation references multiple managed certificates."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$managed_cert_annotation_first" != "$expected_cert_name" ]; then\n'
        '            echo "deploy_runtime_reason_code=ingress_certificate_annotation_mismatch"\n'
        '            echo "deploy_runtime_reason_message=Ingress managed certificate annotation does not match expected site certificate."\n'
        "            exit 1\n"
        "          fi\n"
        '          pre_shared_cert_annotation="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.metadata.annotations.ingress\\.gcp\\.kubernetes\\.io/pre-shared-cert}\' 2>/dev/null || true)"\n'
        '          if [ -n "$pre_shared_cert_annotation" ]; then\n'
        '            echo "observed_pre_shared_cert_annotation=$pre_shared_cert_annotation"\n'
        "            pre_shared_values=\"$(echo \"$pre_shared_cert_annotation\" | tr ',' '\\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d' | tr '[:upper:]' '[:lower:]')\"\n"
        "            pre_shared_count=\"$(echo \"$pre_shared_values\" | sed '/^$/d' | wc -l | tr -d '[:space:]')\"\n"
        '            pre_shared_first="$(echo "$pre_shared_values" | head -n1 | tr -d \'[:space:]\')"\n'
        '            if [ "$pre_shared_count" -ne 1 ] || [ "$pre_shared_first" != "$expected_cert_name" ]; then\n'
        "              pre_shared_cert_metadata_mismatch=true\n"
        "            fi\n"
        "            if echo \"$pre_shared_values\" | grep -qiE '^site-web-preview-cert-'; then\n"
        '              if ! echo "$pre_shared_values" | grep -qx "$expected_cert_name"; then\n'
        "                pre_shared_cert_controller_cross_site_evidence=true\n"
        "              fi\n"
        "            fi\n"
        '            if [ "$pre_shared_cert_metadata_mismatch" = true ]; then\n'
        '              echo "deploy_runtime_reason_code=pre_shared_cert_metadata_mismatch"\n'
        '              echo "Pre-shared cert annotation is controller metadata and does not block deploy by itself; relying on managed-certificate annotation/domain/TLS checks."\n'
        "            fi\n"
        "          fi\n"
        '          dns_ip=""\n'
        "          if command -v dig >/dev/null 2>&1; then\n"
        "            dns_ip=\"$(dig +short \"$preview_host\" A | grep -E '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$' | head -n1 | tr -d '[:space:]')\"\n"
        "          fi\n"
        '          if [ -z "$dns_ip" ] && command -v nslookup >/dev/null 2>&1; then\n'
        "            dns_ip=\"$(nslookup \"$preview_host\" 2>/dev/null | awk '/^Address: / {print $2}' | tail -n1 | tr -d '[:space:]')\"\n"
        "          fi\n"
        '          dns_observed_ip="$dns_ip"\n'
        '          if [ -z "$dns_observed_ip" ] || [ "$dns_observed_ip" != "$dns_expected_ip" ]; then\n'
        "            dns_record_matches_ingress=false\n"
        '            echo "deploy_runtime_reason_code=dns_record_mismatch"\n'
        '            if [ -z "$dns_observed_ip" ]; then\n'
        '              echo "deploy_runtime_reason_code=ingress_ip_assigned_but_dns_not_updated"\n'
        "            else\n"
        '              echo "deploy_runtime_reason_code=dns_points_to_old_ingress_ip"\n'
        "            fi\n"
        '            echo "deploy_runtime_reason_message=DNS A record does not match expected DNS target IP for preview hostname."\n'
        '            echo "expected_hostname=$preview_host"\n'
        '            echo "dns_expected_ip=$dns_expected_ip"\n'
        '            echo "ingress_ip=$ingress_status_ip"\n'
        '            echo "observed_dns_ip=$dns_observed_ip"\n'
        '            if [ -n "$expected_static_ip_address" ]; then\n'
        '              echo "expected_static_ip_address=$expected_static_ip_address"\n'
        '              echo "static_ip_status=$static_ip_status"\n'
        '              echo "static_ip_users=$static_ip_users"\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        "          dns_record_matches_ingress=true\n"
        '          if [ -n "$expected_static_ip_address" ] \\\n'
        '            && [ "$ingress_status_ip_matches_static_ip" != "true" ] \\\n'
        '            && [ "$static_ip_status" = "IN_USE" ] \\\n'
        '            && [ "$static_ip_bound_to_expected_forwarding_rule" = "true" ]; then\n'
        '            echo "deploy_runtime_reason_code=ingress_status_ip_stale_or_mismatched"\n'
        '            echo "Ingress status IP differs from reserved static IP, but reserved static IP is bound and DNS already matches expected static IP."\n'
        "          fi\n"
        '          managed_certificate_json="$(kubectl get managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" -o json 2>/dev/null || true)"\n'
        '          if [ -z "$managed_certificate_json" ]; then\n'
        '            managed_certificate_exists="false"\n'
        '            tls_certificate_status="MISSING"\n'
        '            tls_domain_status="MISSING"\n'
        '            observed_managed_certificate_status="MISSING"\n'
        '            deploy_runtime_failure_stage="ingress_evidence"\n'
        '            deploy_runtime_reason_message="Expected ManagedCertificate resource was not found in namespace."\n'
        '            echo "deploy_runtime_reason_code=runtime_managed_certificate_missing_after_apply"\n'
        '            echo "deploy_runtime_reason_message=$deploy_runtime_reason_message"\n'
        '            echo "k8s_namespace=$K8S_NAMESPACE"\n'
        '            echo "ingress_name=site-web"\n'
        '            echo "preview_hostname=$preview_host"\n'
        '            echo "preview_endpoint_mode=$MBSRN_PREVIEW_ENDPOINT_MODE"\n'
        '            echo "expected_managed_certificate_name=$MBSRN_PREVIEW_CERTIFICATE_NAME"\n'
        "            exit 1\n"
        "          fi\n"
        "          evaluate_managed_certificate() {\n"
        '            local managed_certificate_payload="$1"\n'
        '            MANAGED_CERTIFICATE_JSON="$managed_certificate_payload" EXPECTED_PREVIEW_HOST="$preview_host" EXPECTED_CERT_NAME="$expected_cert_name" EXPECTED_SITE_ID="$MBSRN_SITE_IDENTITY" EXPECTED_REPO_NAME="$GITHUB_REPOSITORY" python - <<\'PY\'\n'
        "          import json\n"
        "          import os\n"
        "\n"
        "          def normalize_fragment(value: str, max_length: int) -> str:\n"
        "              cleaned = ''.join(character.lower() if character.isalnum() else '-' for character in value)\n"
        "              while '--' in cleaned:\n"
        "                  cleaned = cleaned.replace('--', '-')\n"
        "              cleaned = cleaned.strip('-')\n"
        "              return cleaned[:max_length]\n"
        "\n"
        "          raw = str(os.environ.get('MANAGED_CERTIFICATE_JSON') or '').strip()\n"
        "          expected_host = str(os.environ.get('EXPECTED_PREVIEW_HOST') or '').strip().lower().rstrip('.')\n"
        "          expected_cert_name = str(os.environ.get('EXPECTED_CERT_NAME') or '').strip().lower()\n"
        "          expected_site_id = normalize_fragment(str(os.environ.get('EXPECTED_SITE_ID') or '').strip(), 60)\n"
        "          expected_repo_name = str(os.environ.get('EXPECTED_REPO_NAME') or '').strip()\n"
        "          if '/' in expected_repo_name:\n"
        "              expected_repo_name = expected_repo_name.rsplit('/', 1)[-1]\n"
        "          expected_repo_label = normalize_fragment(expected_repo_name, 40)\n"
        "          payload = json.loads(raw) if raw else {}\n"
        "          metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}\n"
        "          labels_payload = metadata.get('labels') if isinstance(metadata.get('labels'), dict) else {}\n"
        "          resource_name = str(metadata.get('name') or '').strip().lower()\n"
        "          spec_domains = [\n"
        "              str(item).strip().lower().rstrip('.')\n"
        "              for item in (payload.get('spec', {}).get('domains') or [])\n"
        "              if str(item).strip()\n"
        "          ]\n"
        "          status_payload = payload.get('status') if isinstance(payload.get('status'), dict) else {}\n"
        "          cert_status = str(status_payload.get('certificateStatus') or '').strip().upper()\n"
        "          domain_status_payload = status_payload.get('domainStatus')\n"
        "          domain_status_map = {}\n"
        "          if isinstance(domain_status_payload, list):\n"
        "              for item in domain_status_payload:\n"
        "                  if not isinstance(item, dict):\n"
        "                      continue\n"
        "                  domain = str(item.get('domain') or '').strip().lower().rstrip('.')\n"
        "                  status = str(item.get('status') or '').strip().upper()\n"
        "                  if domain:\n"
        "                      domain_status_map[domain] = status\n"
        "          elif isinstance(domain_status_payload, dict):\n"
        "              for key, value in domain_status_payload.items():\n"
        "                  domain = str(key or '').strip().lower().rstrip('.')\n"
        "                  if not domain:\n"
        "                      continue\n"
        "                  if isinstance(value, dict):\n"
        "                      status = str(value.get('status') or '').strip().upper()\n"
        "                  else:\n"
        "                      status = str(value or '').strip().upper()\n"
        "                  domain_status_map[domain] = status\n"
        "\n"
        "          domain_status = domain_status_map.get(expected_host, '')\n"
        "          domain_exact_match = len(spec_domains) == 1 and spec_domains[0] == expected_host\n"
        "          resource_name_matches_expected = bool(resource_name and expected_cert_name and resource_name == expected_cert_name)\n"
        "          observed_managed_by = str(labels_payload.get('app.kubernetes.io/managed-by') or '').strip().lower()\n"
        "          observed_name_label = str(labels_payload.get('app.kubernetes.io/name') or '').strip().lower()\n"
        "          observed_repo_label = str(labels_payload.get('mbsrn.io/repo') or '').strip().lower()\n"
        "          observed_site_id_label = str(labels_payload.get('mbsrn.io/site-id') or '').strip().lower()\n"
        "          observed_preview_hostname_label = str(labels_payload.get('mbsrn.io/preview-hostname') or '').strip().lower().rstrip('.')\n"
        "          ownership_checks = [\n"
        "              observed_managed_by == 'mbsrn',\n"
        "              observed_name_label == 'site-web',\n"
        "              observed_preview_hostname_label == expected_host,\n"
        "          ]\n"
        "          if expected_repo_label:\n"
        "              ownership_checks.append(observed_repo_label == expected_repo_label)\n"
        "          if expected_site_id:\n"
        "              ownership_checks.append(observed_site_id_label == expected_site_id)\n"
        "          ownership_verified = all(ownership_checks)\n"
        "          print(f'cert_status={cert_status}')\n"
        "          print(f'domain_status={domain_status}')\n"
        "          print('domain_exact_match=' + ('true' if domain_exact_match else 'false'))\n"
        "          print(f'resource_name={resource_name}')\n"
        "          print('resource_name_matches_expected=' + ('true' if resource_name_matches_expected else 'false'))\n"
        "          print('managed_certificate_ownership_verified=' + ('true' if ownership_verified else 'false'))\n"
        "          print('domain_count=' + str(len(spec_domains)))\n"
        "          print('spec_domains=' + ','.join(spec_domains))\n"
        "          print(f'observed_managed_by={observed_managed_by}')\n"
        "          print(f'observed_name_label={observed_name_label}')\n"
        "          print(f'observed_repo_label={observed_repo_label}')\n"
        "          print(f'observed_site_id_label={observed_site_id_label}')\n"
        "          print(f'observed_preview_hostname_label={observed_preview_hostname_label}')\n"
        "          PY\n"
        "          }\n"
        "          apply_managed_certificate_eval_output() {\n"
        '            local cert_eval_payload="$1"\n'
        "            domain_exact_match=false\n"
        "            resource_name_matches_expected=false\n"
        "            managed_certificate_ownership_verified=false\n"
        '            cert_resource_name=""\n'
        '            observed_managed_certificate_domains=""\n'
        '            observed_managed_by=""\n'
        '            observed_name_label=""\n'
        '            observed_repo_label=""\n'
        '            observed_site_id_label=""\n'
        '            observed_preview_hostname_label=""\n'
        "            while IFS='=' read -r key value; do\n"
        '              case "$key" in\n'
        "                cert_status)\n"
        '                  tls_certificate_status="$value"\n'
        "                  ;;\n"
        "                domain_status)\n"
        '                  tls_domain_status="$value"\n'
        "                  ;;\n"
        "                domain_exact_match)\n"
        '                  domain_exact_match="$value"\n'
        "                  ;;\n"
        "                resource_name)\n"
        '                  cert_resource_name="$value"\n'
        "                  ;;\n"
        "                resource_name_matches_expected)\n"
        '                  resource_name_matches_expected="$value"\n'
        "                  ;;\n"
        "                managed_certificate_ownership_verified)\n"
        '                  managed_certificate_ownership_verified="$value"\n'
        "                  ;;\n"
        "                spec_domains)\n"
        '                  observed_managed_certificate_domains="$value"\n'
        "                  ;;\n"
        "                observed_managed_by)\n"
        '                  observed_managed_by="$value"\n'
        "                  ;;\n"
        "                observed_name_label)\n"
        '                  observed_name_label="$value"\n'
        "                  ;;\n"
        "                observed_repo_label)\n"
        '                  observed_repo_label="$value"\n'
        "                  ;;\n"
        "                observed_site_id_label)\n"
        '                  observed_site_id_label="$value"\n'
        "                  ;;\n"
        "                observed_preview_hostname_label)\n"
        '                  observed_preview_hostname_label="$value"\n'
        "                  ;;\n"
        "              esac\n"
        '            done <<< "$cert_eval_payload"\n'
        "            normalized_cert_status=\"$(echo \"$tls_certificate_status\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        "            normalized_domain_status=\"$(echo \"$tls_domain_status\" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')\"\n"
        '            if [ -z "$observed_managed_certificate_domains" ] && [ "$domain_exact_match" = "true" ] && [ -n "$preview_host" ]; then\n'
        '              observed_managed_certificate_domains="$preview_host"\n'
        "            fi\n"
        '            observed_managed_certificate_status="$tls_certificate_status"\n'
        '            observed_managed_certificate_domain_status="$tls_domain_status"\n'
        '            if [ -z "$cert_resource_name" ]; then\n'
        '              cert_resource_name="$MBSRN_PREVIEW_CERTIFICATE_NAME"\n'
        "            fi\n"
        '            echo "observed_managed_certificate_domains=$observed_managed_certificate_domains"\n'
        '            echo "observed_managed_certificate_status=$observed_managed_certificate_status"\n'
        '            echo "observed_managed_certificate_domain_status=$observed_managed_certificate_domain_status"\n'
        "          }\n"
        '          cert_eval_output="$(evaluate_managed_certificate "$managed_certificate_json")"\n'
        '          apply_managed_certificate_eval_output "$cert_eval_output"\n'
        "          managed_certificate_metadata_available=false\n"
        '          if [ -n "$observed_managed_certificate_domains" ] || [ -n "$observed_managed_certificate_status" ] || [ -n "$observed_managed_certificate_domain_status" ]; then\n'
        "            managed_certificate_metadata_available=true\n"
        "          fi\n"
        '          if [ "$resource_name_matches_expected" != "true" ]; then\n'
        "            cert_identity_valid=false\n"
        '            if [ "$pre_shared_cert_controller_cross_site_evidence" = true ]; then\n'
        '              echo "deploy_runtime_reason_code=stale_pre_shared_cert_binding_detected"\n'
        "            fi\n"
        '            echo "deploy_runtime_reason_code=stale_managed_certificate_present"\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_identity_mismatch"\n'
        '            echo "deploy_runtime_reason_message=ManagedCertificate resource identity does not match expected deterministic certificate name."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$managed_certificate_ownership_verified" != "true" ]; then\n'
        "            cert_identity_valid=false\n"
        '            echo "observed_managed_by=$observed_managed_by"\n'
        '            echo "observed_name_label=$observed_name_label"\n'
        '            echo "observed_repo_label=$observed_repo_label"\n'
        '            echo "observed_site_id_label=$observed_site_id_label"\n'
        '            echo "observed_preview_hostname_label=$observed_preview_hostname_label"\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_ownership_unverified"\n'
        '            echo "deploy_runtime_reason_message=ManagedCertificate ownership labels do not verify this site identity."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$domain_exact_match" != "true" ]; then\n'
        "            cert_identity_valid=false\n"
        '            if [ "$managed_certificate_metadata_available" != "true" ] \\\n'
        '              && [ "$managed_certificate_ownership_verified" = "true" ] \\\n'
        '              && [ "$host_reachable" = true ] \\\n'
        '              && [ "$host_reachability_scheme" = "https" ] \\\n'
        '              && [ "$dns_record_matches_ingress" = "true" ] \\\n'
        '              && [ "$managed_cert_annotation_first" = "$expected_cert_name" ]; then\n'
        "              cert_identity_valid=true\n"
        '              echo "deploy_runtime_reason_code=managed_certificate_metadata_unavailable"\n'
        '              echo "deploy_runtime_reason_message=ManagedCertificate metadata unavailable from cluster API; HTTPS certificate identity and ingress annotation evidence are valid."\n'
        "            else\n"
        '              if [ "$pre_shared_cert_controller_cross_site_evidence" = true ]; then\n'
        '                echo "deploy_runtime_reason_code=stale_pre_shared_cert_binding_detected"\n'
        "              fi\n"
        '              echo "deploy_runtime_reason_code=certificate_domain_mismatch"\n'
        '              echo "deploy_runtime_reason_message=ManagedCertificate spec.domains does not match the expected preview hostname."\n'
        "              exit 1\n"
        "            fi\n"
        "          fi\n"
        "          cert_identity_valid=true\n"
        '          if [ "$managed_certificate_metadata_available" = "true" ] && ( [ "$normalized_domain_status" = "FAILED_NOT_VISIBLE" ] || [ "$normalized_cert_status" = "FAILED_NOT_VISIBLE" ] ); then\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_failed_not_visible"\n'
        '            echo "deploy_runtime_reason_message=ManagedCertificate is not visible; verify DNS and load balancer exposure."\n'
        '            if [ "$dns_record_matches_ingress" != "true" ]; then\n'
        '              echo "deploy_runtime_reason_code=dns_record_mismatch"\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        '          if [ "$managed_certificate_metadata_available" = "true" ] && ( [ "$normalized_domain_status" = "PROVISIONING" ] || [ "$normalized_cert_status" = "PROVISIONING" ] ); then\n'
        '            set_https_probe_error_summary "managed_certificate_provisioning" "" "" ""\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_provisioning"\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_pending"\n'
        '            echo "deploy_runtime_reason_code=tls_certificate_provisioning"\n'
        '            echo "deploy_runtime_reason_code=certificate_provisioning_pending"\n'
        '            echo "deploy_runtime_reason_code=runtime_ready_tls_pending"\n'
        '            echo "deploy_runtime_reason_message=Deploy reached the load balancer, but ManagedCertificate/TLS is still provisioning for expected hostname. Wait for ACTIVE status, then refresh or rerun deploy."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$managed_certificate_metadata_available" = "true" ] && [ "$normalized_domain_status" != "ACTIVE" ]; then\n'
        '            set_https_probe_error_summary "managed_certificate_provisioning" "" "" ""\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_provisioning"\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_pending"\n'
        '            echo "deploy_runtime_reason_code=tls_certificate_provisioning"\n'
        '            echo "deploy_runtime_reason_code=certificate_provisioning_pending"\n'
        '            echo "deploy_runtime_reason_code=runtime_ready_tls_pending"\n'
        '            echo "deploy_runtime_reason_message=ManagedCertificate domain status is not ACTIVE for expected hostname."\n'
        "            exit 1\n"
        "          fi\n"
        '          if [ "$managed_certificate_metadata_available" = "true" ] && [ -n "$normalized_cert_status" ] && [ "$normalized_cert_status" != "ACTIVE" ]; then\n'
        '            set_https_probe_error_summary "managed_certificate_provisioning" "" "" ""\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_provisioning"\n'
        '            echo "deploy_runtime_reason_code=managed_certificate_pending"\n'
        '            echo "deploy_runtime_reason_code=tls_certificate_provisioning"\n'
        '            echo "deploy_runtime_reason_code=certificate_provisioning_pending"\n'
        '            echo "deploy_runtime_reason_code=runtime_ready_tls_pending"\n'
        '            echo "deploy_runtime_reason_message=ManagedCertificate status is not ACTIVE yet."\n'
        "            exit 1\n"
        "          fi\n"
        "          static_ip_alignment_ready=false\n"
        '          if [ -n "$expected_static_ip_address" ]; then\n'
        '            if [ "$ingress_status_ip_matches_static_ip" = "true" ] || [ "$static_ip_bound_to_expected_forwarding_rule" = "true" ]; then\n'
        "              static_ip_alignment_ready=true\n"
        "            fi\n"
        "          else\n"
        "            static_ip_alignment_ready=true\n"
        "          fi\n"
        "          control_plane_ready=false\n"
        '          if [ "$dns_record_matches_ingress" = "true" ] \\\n'
        '            && [ "$cert_identity_valid" = "true" ] \\\n'
        '            && [ "$static_ip_alignment_ready" = "true" ] \\\n'
        '            && [ "$normalized_domain_status" = "ACTIVE" ] \\\n'
        '            && [ "$normalized_cert_status" = "ACTIVE" ]; then\n'
        "            control_plane_ready=true\n"
        "          fi\n"
        '          https_verify_output="$(mktemp)"\n'
        "          https_probe_attempted=true\n"
        '          if ! https_verify_code="$(curl --silent --show-error --connect-timeout 5 --max-time 10 --output /dev/null --write-out \'%{http_code}\' "https://$preview_host" 2>"$https_verify_output")"; then\n'
        "            https_verify_exit=$?\n"
        '            if [ "$https_verify_exit" -eq 60 ] || grep -qiE \'SSL certificate problem|SSL_ERROR_BAD_CERT_DOMAIN|certificate subject name|no alternative certificate subject name\' "$https_verify_output"; then\n'
        '              set_https_probe_error_summary "reachable_but_tls_certificate_mismatch" "$https_verify_exit" "" "$https_verify_output"\n'
        '              if [ "$pre_shared_cert_controller_cross_site_evidence" = true ]; then\n'
        '                echo "deploy_runtime_reason_code=stale_pre_shared_cert_binding_detected"\n'
        "              fi\n"
        '              echo "deploy_runtime_reason_code=tls_certificate_bound_to_wrong_site"\n'
        '              echo "deploy_runtime_reason_code=reachable_but_tls_certificate_mismatch"\n'
        '            elif [ "$https_verify_exit" -eq 28 ]; then\n'
        '              set_https_probe_error_summary "https_probe_timeout" "$https_verify_exit" "" "$https_verify_output"\n'
        '              echo "deploy_runtime_reason_code=https_probe_timeout"\n'
        '              if [ "$control_plane_ready" = "true" ]; then\n'
        '                echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"\n'
        '                echo "deploy_runtime_reason_message=DNS, IP, and certificate are ready, but HTTPS probe to preview host timed out."\n'
        "              fi\n"
        '            elif [ "$https_verify_exit" -eq 52 ]; then\n'
        '              set_https_probe_error_summary "https_probe_empty_reply" "$https_verify_exit" "" "$https_verify_output"\n'
        '              echo "deploy_runtime_reason_code=https_probe_empty_reply"\n'
        '              if [ "$control_plane_ready" = "true" ]; then\n'
        '                echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"\n'
        '                echo "deploy_runtime_reason_message=DNS, IP, and certificate are ready, but HTTPS probe returned an empty reply."\n'
        "              fi\n"
        "            else\n"
        '              if [ -z "$ingress_status_ip" ] && [ -z "$expected_static_ip_address" ] && [ "$host_reachable" != "true" ]; then\n'
        '                set_https_probe_error_summary "ingress_address_pending" "$https_verify_exit" "" "$https_verify_output"\n'
        '                echo "deploy_runtime_reason_code=ingress_address_pending"\n'
        '              elif [ "$normalized_domain_status" = "PROVISIONING" ] || [ "$normalized_cert_status" = "PROVISIONING" ]; then\n'
        '                set_https_probe_error_summary "managed_certificate_provisioning" "$https_verify_exit" "" "$https_verify_output"\n'
        '                echo "deploy_runtime_reason_code=managed_certificate_provisioning"\n'
        '                echo "deploy_runtime_reason_code=tls_certificate_provisioning"\n'
        '                echo "deploy_runtime_reason_code=certificate_provisioning_pending"\n'
        '                echo "deploy_runtime_reason_code=runtime_ready_tls_pending"\n'
        '                echo "deploy_runtime_reason_message=Deploy reached the load balancer, but ManagedCertificate/TLS is still provisioning for expected hostname. Wait for ACTIVE status, then refresh or rerun deploy."\n'
        '              elif [ "$control_plane_ready" = "true" ]; then\n'
        '                set_https_probe_error_summary "https_probe_failed_after_control_plane_ready" "$https_verify_exit" "" "$https_verify_output"\n'
        '                echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"\n'
        '                echo "deploy_runtime_reason_message=DNS, IP, and certificate are ready, but HTTPS probe to preview host is not yet successful. Check load balancer backend health, service endpoints, and app runtime readiness."\n'
        "              else\n"
        '                set_https_probe_error_summary "https_probe_failed" "$https_verify_exit" "" "$https_verify_output"\n'
        '                echo "deploy_runtime_reason_code=https_probe_failed"\n'
        "              fi\n"
        "            fi\n"
        '            cat "$https_verify_output"\n'
        '            rm -f "$https_verify_output"\n'
        "            exit 1\n"
        "          fi\n"
        '          rm -f "$https_verify_output"\n'
        '          preview_https_status="$https_verify_code"\n'
        "          if ! echo \"$https_verify_code\" | grep -Eq '^[1-5][0-9][0-9]$'; then\n"
        '            if [ "$control_plane_ready" = "true" ]; then\n'
        '              set_https_probe_error_summary "https_probe_failed_after_control_plane_ready" "" "$https_verify_code" ""\n'
        '              echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"\n'
        '              echo "deploy_runtime_reason_message=DNS, IP, and certificate are ready, but HTTPS probe to the preview host is not yet successful. Check load balancer backend health, service endpoints, and app runtime readiness."\n'
        "            else\n"
        '              set_https_probe_error_summary "https_probe_failed" "" "$https_verify_code" ""\n'
        '              echo "deploy_runtime_reason_code=https_probe_failed"\n'
        '              echo "deploy_runtime_reason_message=HTTPS probe did not return a valid HTTP status code."\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        '          if [ "$https_verify_code" = "502" ]; then\n'
        "            backend_502_detected=true\n"
        '            set_https_probe_error_summary "ingress_backend_502" "" "$https_verify_code" ""\n'
        '            echo "deploy_runtime_reason_code=ingress_backend_502"\n'
        "            collect_ingress_502_runtime_diagnostics\n"
        '            if [ "$gce_backend_health_status" = "HEALTHY" ] && [ "$service_probe_status" = "ok" ] && [ "$preview_https_status" = "502" ]; then\n'
        '              echo "deploy_runtime_reason_message=Preview hostname is reachable but returns HTTP 502 while GCE backend reports HEALTHY and in-cluster probes succeed. Likely ingress/LB edge convergence or stale backend path."\n'
        '            elif [ "$service_probe_status" = "http_502" ] || [ "$endpoint_probe_status" = "http_502" ]; then\n'
        '              echo "deploy_runtime_reason_message=Preview hostname is reachable but returns HTTP 502 and in-cluster service/endpoint probes also return 502. Likely app runtime response failure."\n'
        '            elif [ "$pod_restart_detected" = true ]; then\n'
        '              echo "deploy_runtime_reason_message=Preview hostname is reachable but returns HTTP 502 with pod restart/crash evidence. Likely pod runtime instability."\n'
        "            else\n"
        '              echo "deploy_runtime_reason_message=HTTPS probe reached ingress but backend returned 502. Review pod logs, in-cluster service probe status, endpoint probe status, and backend health evidence."\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        "          if echo \"$https_verify_code\" | grep -Eq '^5[0-9][0-9]$'; then\n"
        '            if [ "$control_plane_ready" = "true" ]; then\n'
        '              set_https_probe_error_summary "https_probe_failed_after_control_plane_ready" "" "$https_verify_code" ""\n'
        '              echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"\n'
        '              echo "deploy_runtime_reason_message=DNS, IP, and certificate are ready, but HTTPS probe to the preview host is not yet successful. Check load balancer backend health, service endpoints, and app runtime readiness."\n'
        "            else\n"
        '              set_https_probe_error_summary "https_probe_failed" "" "$https_verify_code" ""\n'
        '              echo "deploy_runtime_reason_code=https_probe_failed"\n'
        '              echo "deploy_runtime_reason_message=HTTPS probe returned 5xx before backend reached ready state."\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        "          if echo \"$https_verify_code\" | grep -Eq '^4[0-9][0-9]$'; then\n"
        '            if [ "$control_plane_ready" = "true" ]; then\n'
        '              set_https_probe_error_summary "https_probe_failed_after_control_plane_ready" "" "$https_verify_code" ""\n'
        '              echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"\n'
        '              echo "deploy_runtime_reason_message=DNS, IP, and certificate are ready, but HTTPS probe to the preview host is not yet successful. Check load balancer backend health, service endpoints, and app runtime readiness."\n'
        "            else\n"
        '              set_https_probe_error_summary "https_probe_failed" "" "$https_verify_code" ""\n'
        '              echo "deploy_runtime_reason_code=https_probe_failed"\n'
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        "          deploy_https_ready=true\n"
        '          live_url="https://$preview_host"\n'
        "          {\n"
            '            echo "live_url=$live_url"\n'
            '            echo "resolved_live_url=$live_url"\n'
            '            echo "deployed_url=$live_url"\n'
        '            echo "dns_record_matches_ingress=$dns_record_matches_ingress"\n'
        '            echo "dns_expected_ip=$dns_expected_ip"\n'
        '            echo "dns_observed_ip=$dns_observed_ip"\n'
        '            echo "expected_static_ip_address=$expected_static_ip_address"\n'
        '            echo "static_ip_status=$static_ip_status"\n'
        '            echo "static_ip_users=$static_ip_users"\n'
        '            echo "tls_certificate_status=$tls_certificate_status"\n'
        '            echo "tls_domain_status=$tls_domain_status"\n'
        '            echo "managed_certificate_resource_name=$MBSRN_PREVIEW_CERTIFICATE_NAME"\n'
        '            echo "observed_managed_certificate_domains=$observed_managed_certificate_domains"\n'
        '            echo "observed_managed_certificate_status=$observed_managed_certificate_status"\n'
        '            echo "observed_managed_certificate_domain_status=$observed_managed_certificate_domain_status"\n'
        '            echo "ingress_status_ip=$ingress_status_ip"\n'
        '            echo "ingress_status_ip_matches_static_ip=$ingress_status_ip_matches_static_ip"\n'
        '            echo "static_ip_bound_to_expected_forwarding_rule=$static_ip_bound_to_expected_forwarding_rule"\n'
        '            echo "ingress_ip=$ingress_ip"\n'
        '            echo "ingress_conflict_detected=$ingress_conflict_detected"\n'
        '            echo "cert_identity_valid=$cert_identity_valid"\n'
        '            echo "host_reachable=$host_reachable"\n'
        '            echo "host_reachability_scheme=$host_reachability_scheme"\n'
            '            echo "https_probe_error_summary=$https_probe_error_summary"\n'
            '            echo "deploy_https_ready=$deploy_https_ready"\n'
            '            echo "preview_https_status=$preview_https_status"\n'
            '            echo "preview_http_status=$preview_http_status"\n'
            '            echo "preview_probe_attempt=$preview_probe_attempt"\n'
            '            echo "preview_probe_elapsed_seconds=$preview_probe_elapsed_seconds"\n'
            '            echo "gce_backend_health_status=$gce_backend_health_status"\n'
            '            echo "k8s_endpoint_ready=$k8s_endpoint_ready"\n'
            '            echo "service_probe_status=$service_probe_status"\n'
            '            echo "in_cluster_service_status_code=$in_cluster_service_status_code"\n'
            '            echo "endpoint_probe_status=$endpoint_probe_status"\n'
            '            echo "endpoint_probe_status_code=$endpoint_probe_status_code"\n'
            '            echo "runtime_probe_status=$runtime_probe_status"\n'
            '            echo "pod_restart_detected=$pod_restart_detected"\n'
            '            echo "runtime_ready=true"\n'
            '            echo "ingress_address_resolved=true"\n'
            '            echo "service_exists=$service_exists"\n'
            '            echo "endpoints_ready=true"\n'
            '            echo "managed_certificate_exists=$managed_certificate_exists"\n'
            '            echo "managed_certificate_status=$tls_certificate_status"\n'
            '            echo "https_ready=true"\n'
            '            echo "runtime_ready_tls_pending=false"\n'
            '            echo "replace_existing_runtime_requested=$replace_existing_runtime_requested"\n'
            '            echo "replace_existing_runtime_performed=$replace_existing_runtime_performed"\n'
            f'            echo "{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}={_MBSRN_MANAGED_TEMPLATE_VERSION}"\n'
        '          } >> "$GITHUB_OUTPUT"\n'
        "      - name: Emit managed deployment metadata\n"
        "        run: |\n"
        f'          echo "MBSRN managed deploy workflow: {normalized_workflow_id}"\n'
        f'          echo "Repository: {repo_owner}/{repo_name}"\n'
        f'          echo "Branch: {branch}"\n'
        f'          echo "Kubernetes namespace: {normalized_namespace}"\n'
        f'          echo "Namespace source: {normalized_namespace_source}"\n'
        f'          echo "Target environment key: {normalized_environment_key}"\n'
        f'          echo "Target environment source: {normalized_environment_source}"\n'
        f'          echo "Site identity: {normalized_site_fragment}"\n'
        '          echo "Preview hostname: $MBSRN_PREVIEW_HOSTNAME"\n'
        '          echo "Preview certificate name: $MBSRN_PREVIEW_CERTIFICATE_NAME"\n'
        '          echo "FrontendConfig name: $MBSRN_FRONTEND_CONFIG_NAME"\n'
        '          echo "BackendConfig name: $MBSRN_BACKEND_CONFIG_NAME"\n'
        '          echo "Site runtime image: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}"\n'
        '          echo "Site runtime image selection mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}"\n'
        '          echo "Site runtime image repository: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_repository }}"\n'
        '          echo "Site runtime image tag: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_tag }}"\n'
        '          echo "Site runtime image tag source: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_tag_source }}"\n'
        '          echo "Site runtime source commit: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_source_commit }}"\n'
        '          echo "Site runtime content source: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_content_source }}"\n'
    )
    return _embed_managed_workflow_signature(workflow_yaml=workflow_yaml_unsigned)


def _render_managed_gke_manifest_files(
    *,
    repo_owner: str,
    repo_name: str,
    target_environment_key: str,
    target_environment_source: str,
    kubernetes_namespace: str,
    namespace_source: str,
    preview_hostname: str,
    namespace_isolation_defaults: dict[str, object] | None,
    site_id: str | None,
    private_image_auth_required: bool = False,
) -> dict[str, str]:
    site_runtime_image_repository = _derive_site_runtime_image_repository(
        repo_owner=repo_owner,
        repo_name=repo_name,
    )
    preview_certificate_name, _ = derive_site_preview_certificate_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    frontend_config_name, _ = derive_site_preview_frontend_config_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    backend_config_name, _ = derive_site_preview_backend_config_name(
        repo_name=repo_name,
        site_id=site_id,
    )
    repo_owner_fragment = _safe_identifier_fragment(repo_owner, fallback="mbsrn", max_length=40)
    repo_fragment = _safe_identifier_fragment(repo_name, fallback="site", max_length=40)
    env_key = _safe_identifier_fragment(target_environment_key, fallback="gke-prod", max_length=40)
    env_source = _safe_identifier_fragment(target_environment_source, fallback="admin-config", max_length=40)
    namespace = _safe_identifier_fragment(kubernetes_namespace, fallback=repo_fragment, max_length=63)
    namespace_origin = _safe_identifier_fragment(namespace_source, fallback="repo-name", max_length=40)
    site_fragment = _safe_identifier_fragment(site_id, fallback="workspace", max_length=60)
    normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower()
    preview_endpoint = resolve_managed_preview_endpoint_configuration(
        repo_name=repo_name,
        site_id=site_id,
        preview_hostname=normalized_preview_hostname,
        namespace_isolation_defaults=_normalize_namespace_isolation_defaults(namespace_isolation_defaults),
    )
    preview_static_ip_name = _coerce_string(preview_endpoint.get("expected_static_ip_name"))
    if not preview_static_ip_name:
        preview_static_ip_name, _ = derive_site_preview_static_ip_name(
            repo_name=repo_name,
            site_id=site_id,
        )
    image_pull_secrets_block = ""
    if private_image_auth_required:
        image_pull_secrets_block = (
            "      imagePullSecrets:\n" f"        - name: {_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME}\n"
        )

    labels = (
        f"    app.kubernetes.io/managed-by: {_MBSRN_MANAGED_LABEL}\n"
        f"    app.kubernetes.io/name: site-web\n"
        f"    mbsrn.io/repo: {repo_fragment}\n"
        f"    mbsrn.io/environment-key: {env_key}\n"
        f"    mbsrn.io/environment-source: {env_source}\n"
        f"    mbsrn.io/site-id: {site_fragment}\n"
        f"    mbsrn.io/namespace-source: {namespace_origin}\n"
        f"    mbsrn.io/preview-hostname: {normalized_preview_hostname}\n"
    )

    namespace_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        f"  name: {namespace}\n"
        "  labels:\n"
        f"{labels}"
    )
    image_repository = f"{site_runtime_image_repository}:latest"
    deployment_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: site-web\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        f"{labels}"
        "spec:\n"
        "  replicas: 1\n"
        "  selector:\n"
        "    matchLabels:\n"
        "      app.kubernetes.io/name: site-web\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        "        app.kubernetes.io/name: site-web\n"
        f"        app.kubernetes.io/managed-by: {_MBSRN_MANAGED_LABEL}\n"
        "    spec:\n"
        f"{image_pull_secrets_block}"
        "      containers:\n"
        "        - name: site-web\n"
        f"          image: {image_repository}\n"
        "          imagePullPolicy: IfNotPresent\n"
        "          env:\n"
        "            - name: HOSTNAME\n"
        '              value: "0.0.0.0"\n'
        "            - name: PORT\n"
        '              value: "8080"\n'
        "          ports:\n"
        "            - containerPort: 8080\n"
        "          resources:\n"
        "            requests:\n"
        "              cpu: 100m\n"
        "              memory: 256Mi\n"
        "            limits:\n"
        "              cpu: 500m\n"
        "              memory: 512Mi\n"
        "          readinessProbe:\n"
        "            httpGet:\n"
        "              path: /\n"
        "              port: 8080\n"
        "            initialDelaySeconds: 5\n"
        "            periodSeconds: 10\n"
    )
    service_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: site-web\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        f"{labels}"
        "  annotations:\n"
        "    cloud.google.com/neg: '{\"ingress\": true}'\n"
        f'    cloud.google.com/backend-config: \'{{"default": "{backend_config_name}"}}\'\n'
        "spec:\n"
        "  selector:\n"
        "    app.kubernetes.io/name: site-web\n"
        "  ports:\n"
        "    - name: http\n"
        "      port: 80\n"
        "      targetPort: 8080\n"
        "  type: ClusterIP\n"
    )
    ingress_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: networking.k8s.io/v1\n"
        "kind: Ingress\n"
        "metadata:\n"
        "  name: site-web\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        f"{labels}"
        "  annotations:\n"
        "    kubernetes.io/ingress.class: gce\n"
        f"    kubernetes.io/ingress.global-static-ip-name: {preview_static_ip_name}\n"
        f"    networking.gke.io/managed-certificates: {preview_certificate_name}\n"
        f"    networking.gke.io/v1beta1.FrontendConfig: {frontend_config_name}\n"
        "spec:\n"
        "  ingressClassName: gce\n"
        "  rules:\n"
        f"    - host: {normalized_preview_hostname}\n"
        "      http:\n"
        "        paths:\n"
        "          - path: /\n"
        "            pathType: Prefix\n"
        "            backend:\n"
        "              service:\n"
        "                name: site-web\n"
        "                port:\n"
        "                  number: 80\n"
    )
    managed_certificate_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: networking.gke.io/v1\n"
        "kind: ManagedCertificate\n"
        "metadata:\n"
        f"  name: {preview_certificate_name}\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        f"{labels}"
        "spec:\n"
        "  domains:\n"
        f"    - {normalized_preview_hostname}\n"
    )
    frontend_config_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: networking.gke.io/v1beta1\n"
        "kind: FrontendConfig\n"
        "metadata:\n"
        f"  name: {frontend_config_name}\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        f"{labels}"
        "spec:\n"
        "  redirectToHttps:\n"
        "    enabled: true\n"
    )
    backend_config_manifest = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "apiVersion: cloud.google.com/v1\n"
        "kind: BackendConfig\n"
        "metadata:\n"
        f"  name: {backend_config_name}\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        f"{labels}"
        "spec:\n"
        "  healthCheck:\n"
        "    type: HTTP\n"
        "    requestPath: /\n"
        "    port: 8080\n"
        "    checkIntervalSec: 10\n"
        "    timeoutSec: 5\n"
        "    healthyThreshold: 1\n"
        "    unhealthyThreshold: 3\n"
    )
    manifests: dict[str, str] = {
        _MBSRN_MANAGED_NAMESPACE_FILE_PATH: namespace_manifest,
        _MBSRN_MANAGED_DEPLOYMENT_FILE_PATH: deployment_manifest,
        _MBSRN_MANAGED_SERVICE_FILE_PATH: service_manifest,
        _MBSRN_MANAGED_INGRESS_FILE_PATH: ingress_manifest,
        _MBSRN_MANAGED_CERTIFICATE_FILE_PATH: managed_certificate_manifest,
        _MBSRN_MANAGED_FRONTEND_CONFIG_FILE_PATH: frontend_config_manifest,
        _MBSRN_MANAGED_BACKEND_CONFIG_FILE_PATH: backend_config_manifest,
    }
    normalized_defaults = _normalize_namespace_isolation_defaults(namespace_isolation_defaults)
    resource_quota_defaults = normalized_defaults.get("resource_quota")
    if isinstance(resource_quota_defaults, dict) and _coerce_bool(
        resource_quota_defaults.get("enabled"), default=False
    ):
        resource_quota_manifest = (
            f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
            "apiVersion: v1\n"
            "kind: ResourceQuota\n"
            "metadata:\n"
            "  name: site-resources\n"
            f"  namespace: {namespace}\n"
            "  labels:\n"
            f"{labels}"
            "spec:\n"
            "  hard:\n"
            f"    requests.cpu: {resource_quota_defaults.get('requests_cpu')}\n"
            f"    requests.memory: {resource_quota_defaults.get('requests_memory')}\n"
            f"    limits.cpu: {resource_quota_defaults.get('limits_cpu')}\n"
            f"    limits.memory: {resource_quota_defaults.get('limits_memory')}\n"
            f"    pods: \"{resource_quota_defaults.get('pods')}\"\n"
            f"    services: \"{resource_quota_defaults.get('services')}\"\n"
            f"    configmaps: \"{resource_quota_defaults.get('configmaps')}\"\n"
            f"    secrets: \"{resource_quota_defaults.get('secrets')}\"\n"
            f"    persistentvolumeclaims: \"{resource_quota_defaults.get('persistentvolumeclaims')}\"\n"
        )
        manifests[_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH] = resource_quota_manifest

    limit_range_defaults = normalized_defaults.get("limit_range")
    if isinstance(limit_range_defaults, dict) and _coerce_bool(limit_range_defaults.get("enabled"), default=False):
        limit_range_manifest = (
            f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
            "apiVersion: v1\n"
            "kind: LimitRange\n"
            "metadata:\n"
            "  name: site-container-limits\n"
            f"  namespace: {namespace}\n"
            "  labels:\n"
            f"{labels}"
            "spec:\n"
            "  limits:\n"
            "    - type: Container\n"
            "      default:\n"
            f"        cpu: {limit_range_defaults.get('default_cpu')}\n"
            f"        memory: {limit_range_defaults.get('default_memory')}\n"
            "      defaultRequest:\n"
            f"        cpu: {limit_range_defaults.get('default_request_cpu')}\n"
            f"        memory: {limit_range_defaults.get('default_request_memory')}\n"
            "      min:\n"
            f"        cpu: {limit_range_defaults.get('min_cpu')}\n"
            f"        memory: {limit_range_defaults.get('min_memory')}\n"
            "      max:\n"
            f"        cpu: {limit_range_defaults.get('max_cpu')}\n"
            f"        memory: {limit_range_defaults.get('max_memory')}\n"
        )
        manifests[_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH] = limit_range_manifest

    network_policy_defaults = normalized_defaults.get("network_policy")
    if isinstance(network_policy_defaults, dict) and _coerce_bool(
        network_policy_defaults.get("enabled"), default=False
    ):
        mode = _safe_identifier_fragment(
            network_policy_defaults.get("mode"), fallback="default-deny-ingress", max_length=60
        )
        network_policy_manifest = (
            f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: NetworkPolicy\n"
            "metadata:\n"
            "  name: site-default-deny-ingress\n"
            f"  namespace: {namespace}\n"
            "  labels:\n"
            f"{labels}"
            f"    mbsrn.io/network-policy-mode: {mode}\n"
            "spec:\n"
            "  podSelector: {}\n"
            "  policyTypes:\n"
            "    - Ingress\n"
            "---\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: NetworkPolicy\n"
            "metadata:\n"
            "  name: site-web-allow-managed-ingress\n"
            f"  namespace: {namespace}\n"
            "  labels:\n"
            f"{labels}"
            f"    mbsrn.io/network-policy-mode: {mode}\n"
            "spec:\n"
            "  podSelector:\n"
            "    matchLabels:\n"
            "      app.kubernetes.io/name: site-web\n"
            "  policyTypes:\n"
            "    - Ingress\n"
            "  ingress:\n"
            "    - from:\n"
            "        - podSelector: {}\n"
            "      ports:\n"
            "        - protocol: TCP\n"
            "          port: 8080\n"
            "    - from:\n"
            "        - ipBlock:\n"
            "            cidr: 35.191.0.0/16\n"
            "        - ipBlock:\n"
            "            cidr: 130.211.0.0/22\n"
            "      ports:\n"
            "        - protocol: TCP\n"
            "          port: 8080\n"
        )
        manifests[_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH] = network_policy_manifest
    return manifests


def _render_managed_site_runtime_files(
    *,
    repo_owner: str,
    repo_name: str,
) -> dict[str, str]:
    owner_fragment = _safe_identifier_fragment(repo_owner, fallback="owner", max_length=60)
    repo_fragment = _safe_identifier_fragment(repo_name, fallback="site", max_length=60)
    runtime_dockerfile = (
        f"# {_MBSRN_MANAGED_MANIFEST_MARKER}\n"
        "# Managed site runtime image build contract.\n"
        "# This image is built from generated site content in the target repo.\n"
        f"# content_identity: {owner_fragment}/{repo_fragment}\n"
        "FROM caddy:2.8-alpine\n"
        "WORKDIR /srv\n"
        "COPY context/ /srv/\n"
        "EXPOSE 8080\n"
        'CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":8080"]\n'
    )
    return {
        _MBSRN_MANAGED_SITE_RUNTIME_DOCKERFILE_PATH: runtime_dockerfile,
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _coerce_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if not candidate.isdigit():
            return None
        try:
            return int(candidate)
        except ValueError:
            return None
    return None


def _parse_iso8601_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    normalized = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return candidate
    return None


def _workflow_content_matches_namespace(*, workflow_content: str, kubernetes_namespace: str) -> bool:
    lowered_content = str(workflow_content or "").lower()
    namespace = str(kubernetes_namespace or "").strip().lower()
    if not lowered_content or not namespace:
        return False
    return (
        f"k8s_namespace: {namespace}" in lowered_content
        or f'k8s_namespace="{namespace}"' in lowered_content
        or f'--namespace "{namespace}"' in lowered_content
        or f"--namespace {namespace}" in lowered_content
    )


def _manifest_content_matches_namespace(
    *,
    manifest_path: str,
    manifest_content: str | None,
    kubernetes_namespace: str,
) -> bool:
    content = str(manifest_content or "").lower()
    namespace = str(kubernetes_namespace or "").strip().lower()
    if not content or not namespace:
        return False
    normalized_path = str(manifest_path or "").strip().lower()
    if normalized_path.endswith("namespace.yaml"):
        pattern = rf"(?m)^\s*name:\s*[\"']?{re.escape(namespace)}[\"']?\s*$"
        return re.search(pattern, content) is not None
    pattern = rf"(?m)^\s*namespace:\s*[\"']?{re.escape(namespace)}[\"']?\s*$"
    return re.search(pattern, content) is not None


def _deployment_references_image_pull_secret(
    *,
    deployment_manifest_content: str | None,
    image_pull_secret_name: str,
) -> bool:
    content = str(deployment_manifest_content or "").lower()
    secret_name = str(image_pull_secret_name or "").strip().lower()
    if not content or not secret_name:
        return False
    if "imagepullsecrets:" not in content:
        return False
    pattern = rf"(?m)^\s*-\s*name:\s*[\"']?{re.escape(secret_name)}[\"']?\s*$"
    return re.search(pattern, content) is not None


def _extract_deployment_image_reference(*, deployment_manifest_content: str | None) -> str | None:
    content = str(deployment_manifest_content or "")
    if not content:
        return None
    match = re.search(r"(?m)^\s*image:\s*([^\s#]+)\s*$", content)
    if not match:
        return None
    return match.group(1).strip() or None


def _container_image_identity(image_reference: str | None) -> tuple[str | None, str | None]:
    raw = str(image_reference or "").strip() or None
    if not raw:
        return None, None
    without_digest = raw.split("@", 1)[0]
    if not without_digest:
        return None, None
    last_slash = without_digest.rfind("/")
    last_colon = without_digest.rfind(":")
    if last_colon > last_slash:
        repository = without_digest[:last_colon]
        tag = without_digest[last_colon + 1 :] or None
    else:
        repository = without_digest
        tag = None
    return repository.lower() if repository else None, tag


def _is_legacy_generic_site_runtime_image_repository(
    *,
    image_repository: str | None,
    repo_owner: object,
) -> bool:
    observed_repository = str(image_repository or "").strip().lower() or None
    if not observed_repository:
        return False
    owner_fragment = _safe_identifier_fragment(repo_owner, fallback="", max_length=80).strip("-")
    if not owner_fragment:
        return False
    return observed_repository in {
        f"ghcr.io/{owner_fragment}/{_MBSRN_MANAGED_SITE_WEB_IMAGE_REPO_NAME}",
        "ghcr.io/mhanson13/site-web",
    }


def _evaluate_preview_certificate_alignment(
    *,
    ingress_manifest_content: str | None,
    managed_certificate_manifest_content: str | None,
    expected_preview_hostname: str,
    expected_certificate_name: str,
    expected_static_ip_name: str | None = None,
) -> tuple[bool, dict[str, object]]:
    ingress_content = str(ingress_manifest_content or "")
    certificate_content = str(managed_certificate_manifest_content or "")
    expected_host = str(expected_preview_hostname or "").strip().lower() or None
    expected_cert_name = str(expected_certificate_name or "").strip().lower() or None
    expected_static_ip = str(expected_static_ip_name or "").strip().lower() or None

    ingress_kind = _extract_manifest_scalar(
        ingress_content,
        pattern=r"(?m)^\s*kind:\s*([^\n#]+)$",
    )
    certificate_kind = _extract_manifest_scalar(
        certificate_content,
        pattern=r"(?m)^\s*kind:\s*([^\n#]+)$",
    )

    ingress_host: str | None = None
    ingress_cert_annotation: str | None = None
    ingress_cert_annotation_values: tuple[str, ...] = ()
    ingress_static_ip_annotation: str | None = None
    ingress_pre_shared_cert_annotation: str | None = None
    ingress_pre_shared_cert_annotation_values: tuple[str, ...] = ()
    if ingress_kind == "ingress":
        ingress_host = _extract_manifest_scalar(
            ingress_content,
            pattern=r"(?m)^\s*-\s*host:\s*([^\n#]+)$",
        )
        ingress_cert_annotation = _extract_manifest_scalar(
            ingress_content,
            pattern=r"(?m)^\s*networking\.gke\.io/managed-certificates:\s*([^\n#]+)$",
        )
        ingress_cert_annotation_values = _extract_comma_separated_values(ingress_cert_annotation)
        ingress_static_ip_annotation = _extract_manifest_scalar(
            ingress_content,
            pattern=r"(?m)^\s*kubernetes\.io/ingress\.global-static-ip-name:\s*([^\n#]+)$",
        )
        ingress_pre_shared_cert_annotation = _extract_manifest_scalar(
            ingress_content,
            pattern=r"(?m)^\s*ingress\.gcp\.kubernetes\.io/pre-shared-cert:\s*([^\n#]+)$",
        )
        ingress_pre_shared_cert_annotation_values = _extract_comma_separated_values(ingress_pre_shared_cert_annotation)

    certificate_name: str | None = None
    certificate_domains: tuple[str, ...] = ()
    if certificate_kind == "managedcertificate":
        certificate_name = _extract_manifest_scalar(
            certificate_content,
            pattern=r"(?m)^\s*name:\s*([^\n#]+)$",
        )
        certificate_domains = _extract_manifest_list_values(
            certificate_content,
            parent_key="domains",
        )

    host_conflict = bool(expected_host and ingress_host and ingress_host != expected_host)
    annotation_conflict = bool(
        expected_cert_name
        and ingress_cert_annotation_values
        and (expected_cert_name not in ingress_cert_annotation_values or len(ingress_cert_annotation_values) != 1)
    )
    certificate_name_conflict = bool(expected_cert_name and certificate_name and certificate_name != expected_cert_name)
    domain_conflict = bool(expected_host and certificate_domains and expected_host not in certificate_domains)
    annotation_includes_expected = bool(expected_cert_name and expected_cert_name in ingress_cert_annotation_values)
    stale_managed_certificate_names: list[str] = []
    if expected_cert_name and annotation_includes_expected:
        stale_managed_certificate_names.extend(
            value for value in ingress_cert_annotation_values if value and value != expected_cert_name
        )
    stale_managed_certificate_names = list(dict.fromkeys(stale_managed_certificate_names))
    stale_managed_certificate_present = bool(stale_managed_certificate_names)
    ingress_static_ip_matches_expected = bool(
        expected_static_ip and ingress_static_ip_annotation and ingress_static_ip_annotation == expected_static_ip
    )
    ingress_static_ip_name_mismatch = bool(
        expected_static_ip and ingress_static_ip_annotation and ingress_static_ip_annotation != expected_static_ip
    )
    ingress_static_ip_conflict = ingress_static_ip_name_mismatch
    shared_static_ip_not_allowed_for_per_site_ingress = ingress_static_ip_name_mismatch
    valid_pre_shared_cert_binding = bool(
        expected_cert_name
        and len(ingress_pre_shared_cert_annotation_values) == 1
        and ingress_pre_shared_cert_annotation_values[0] == expected_cert_name
    )
    pre_shared_cert_metadata_mismatch = bool(
        ingress_pre_shared_cert_annotation_values and not valid_pre_shared_cert_binding
    )
    pre_shared_cert_metadata_multiple_values = bool(len(ingress_pre_shared_cert_annotation_values) > 1)
    pre_shared_cert_known_managed_site_name_mismatch = bool(
        expected_cert_name
        and any(
            value.startswith(f"{_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME_PREFIX}-") and value != expected_cert_name
            for value in ingress_pre_shared_cert_annotation_values
        )
    )
    ingress_certificate_mismatch = bool(annotation_conflict or certificate_name_conflict)
    certificate_domain_mismatch = bool(host_conflict or domain_conflict)
    stale_pre_shared_cert_binding_detected = bool(
        pre_shared_cert_metadata_mismatch
        and (ingress_certificate_mismatch or certificate_domain_mismatch or stale_managed_certificate_present)
    )

    observed_evidence = any(
        value
        for value in (
            ingress_host,
            ingress_cert_annotation_values,
            certificate_name,
            certificate_domains,
        )
    )
    has_conflict = (
        certificate_domain_mismatch
        or ingress_certificate_mismatch
        or stale_managed_certificate_present
        or shared_static_ip_not_allowed_for_per_site_ingress
        or stale_pre_shared_cert_binding_detected
    )
    all_aligned = not has_conflict
    if has_conflict:
        alignment_status = "mismatched"
    elif observed_evidence:
        alignment_status = "aligned"
    else:
        alignment_status = "insufficient_evidence"

    return all_aligned, {
        "preview_certificate_ingress_host": ingress_host,
        "preview_certificate_ingress_annotation": ingress_cert_annotation,
        "preview_certificate_ingress_annotation_values": list(ingress_cert_annotation_values),
        "preview_certificate_ingress_static_ip_name": ingress_static_ip_annotation,
        "expected_preview_static_ip_name": expected_static_ip,
        "preview_certificate_ingress_static_ip_matches_expected": ingress_static_ip_matches_expected,
        "preview_certificate_ingress_static_ip_name_mismatch": ingress_static_ip_name_mismatch,
        "preview_certificate_ingress_pre_shared_cert_annotation": ingress_pre_shared_cert_annotation,
        "preview_certificate_ingress_pre_shared_cert_annotation_values": list(
            ingress_pre_shared_cert_annotation_values
        ),
        "preview_certificate_valid_pre_shared_cert_binding": valid_pre_shared_cert_binding,
        "pre_shared_cert_metadata_mismatch": pre_shared_cert_metadata_mismatch,
        "pre_shared_cert_metadata_multiple_values": pre_shared_cert_metadata_multiple_values,
        "pre_shared_cert_known_managed_site_name_mismatch": pre_shared_cert_known_managed_site_name_mismatch,
        "preview_certificate_name": certificate_name,
        "preview_certificate_domains": list(certificate_domains),
        "preview_certificate_ingress_host_conflict": host_conflict,
        "preview_certificate_annotation_conflict": annotation_conflict,
        "preview_certificate_name_conflict": certificate_name_conflict,
        "preview_certificate_domain_conflict": domain_conflict,
        "ingress_certificate_mismatch": ingress_certificate_mismatch,
        "stale_managed_certificate_present": stale_managed_certificate_present,
        "stale_managed_certificate_names": stale_managed_certificate_names,
        "ingress_static_ip_conflict": ingress_static_ip_conflict,
        "shared_static_ip_not_allowed_for_per_site_ingress": shared_static_ip_not_allowed_for_per_site_ingress,
        "stale_pre_shared_cert_binding_detected": stale_pre_shared_cert_binding_detected,
        "certificate_domain_mismatch": certificate_domain_mismatch,
        "managed_certificate_identity_mismatch": stale_managed_certificate_present,
        "ingress_certificate_annotation_mismatch": ingress_certificate_mismatch,
        "tls_certificate_bound_to_wrong_site": certificate_domain_mismatch,
        "managed_certificate_failed_not_visible": False,
        "preview_certificate_alignment_status": alignment_status,
    }


def _extract_manifest_scalar(content: str, *, pattern: str) -> str | None:
    if not content:
        return None
    match = re.search(pattern, content)
    if not match:
        return None
    value = match.group(1).strip().strip('"').strip("'").strip()
    return value.lower() if value else None


def _extract_manifest_list_values(content: str, *, parent_key: str) -> tuple[str, ...]:
    if not content:
        return ()
    parent_pattern = rf"(?ms)^\s*{re.escape(parent_key)}:\s*\n(?P<body>(?:\s*-\s*[^\n]+\n?)*)"
    match = re.search(parent_pattern, content)
    if not match:
        return ()
    values: list[str] = []
    for line in match.group("body").splitlines():
        item_match = re.match(r"^\s*-\s*([^\n#]+)$", line)
        if not item_match:
            continue
        normalized = item_match.group(1).strip().strip('"').strip("'").strip().lower()
        if normalized:
            values.append(normalized)
    return tuple(values)


def _extract_comma_separated_values(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return ()
    values = [token.strip().strip('"').strip("'").strip().lower() for token in str(raw_value).split(",")]
    return tuple(token for token in values if token)


def _status_links_to_workflow_run(*, status_item: dict[str, object], workflow_run_id: int) -> bool:
    needle = f"/actions/runs/{workflow_run_id}"
    for key in ("log_url", "target_url", "url"):
        value = _coerce_string(status_item.get(key))
        if value and needle in value:
            return True
    return False


def _classify_workflow_run_failure(
    *,
    failed_step_name: str | None,
    run_conclusion: str | None,
) -> tuple[str, str]:
    step_name = (failed_step_name or "").strip().lower()
    conclusion = (run_conclusion or "").strip().lower()
    if step_name:
        if "validate gcp credentials" in step_name:
            return "generated_workflow_requires_missing_gcp_deploy_key", "workflow_execution"
        if "authenticate to gcp" in step_name or "google-github-actions/auth" in step_name:
            return "gcp_auth_failed", "gcp_auth"
        if "get gke credentials" in step_name or "get-gke-credentials" in step_name:
            return "gke_credentials_failed", "cluster_credentials"
        if "apply managed manifests" in step_name or "kubectl apply" in step_name:
            return "kubectl_apply_failed", "manifest_apply"
        if "verify required resources after apply" in step_name:
            return "service_ingress_verification_failed", "ingress_verify"
        if "verify rollout" in step_name or "rollout status" in step_name:
            return "rollout_verification_failed", "rollout_verify"
        if "verify service and ingress" in step_name:
            return "service_ingress_verification_failed", "ingress_verify"
        if "resolve live url from ingress status" in step_name:
            return "ingress_endpoint_not_ready", "ingress_evidence"

    if conclusion == "cancelled":
        return "workflow_run_cancelled", "workflow_execution"
    if conclusion == "timed_out":
        return "workflow_run_timed_out", "workflow_execution"
    return "workflow_run_failed", "workflow_execution"


def _classify_cloudsql_proxy_failure_from_log_text(
    log_text: str | None,
) -> tuple[str | None, str | None]:
    normalized = (str(log_text or "")).strip().lower()
    if not normalized:
        return None, None
    if "deploy_runtime_reason_code=runtime_readiness_unknown_failure" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_READINESS_UNKNOWN_FAILURE, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_deploy_workflow_template_stale" in normalized:
        return _DEPLOY_RUNTIME_REASON_MANAGED_DEPLOY_WORKFLOW_TEMPLATE_STALE, "workflow_execution"
    if "deploy_runtime_reason_code=missing_cluster_name" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME, "workflow_execution"
    if "deploy_runtime_reason_code=missing_cluster_location" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION, "workflow_execution"
    if "deploy_runtime_reason_code=missing_gcp_project_id" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID, "workflow_execution"
    if "deploy_runtime_reason_code=backendconfig_health_check_mismatch" in normalized:
        return _DEPLOY_RUNTIME_REASON_BACKENDCONFIG_HEALTH_CHECK_MISMATCH, "rollout_verify"
    if "deploy_runtime_reason_code=ingress_backend_unhealthy" in normalized:
        return _DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY, "rollout_verify"
    if "deploy_runtime_reason_code=rollout_verification_failed" in normalized:
        return "rollout_verification_failed", "rollout_verify"
    if "deploy_runtime_reason_code=managed_certificate_provisioning" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING, "ingress_evidence"
    if "deploy_runtime_reason_code=target_repo_deploy_secret_missing" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_REPO_DEPLOY_SECRET_MISSING, "workflow_execution"
    if "deploy_runtime_reason_code=runtime_service_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_SERVICE_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=runtime_deployment_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_DEPLOYMENT_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=runtime_ingress_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_INGRESS_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=runtime_managed_certificate_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_MANAGED_CERTIFICATE_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=runtime_frontend_config_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_FRONTEND_CONFIG_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=runtime_backend_config_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_BACKEND_CONFIG_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=runtime_service_endpoints_missing_after_apply" in normalized:
        return _DEPLOY_RUNTIME_REASON_RUNTIME_SERVICE_ENDPOINTS_MISSING_AFTER_APPLY, "ingress_verify"
    if "deploy_runtime_reason_code=managed_site_runtime_replace_failed" in normalized:
        return "managed_site_runtime_replace_failed", "workflow_execution"
    if "deploy_runtime_reason_code=managed_site_runtime_replace_requested" in normalized:
        return "managed_site_runtime_replace_requested", "workflow_execution"
    if "deploy_runtime_reason_code=managed_site_runtime_replace_completed" in normalized:
        return "managed_site_runtime_replace_completed", "workflow_execution"
    if "deploy_runtime_reason_code=ingress_backend_502" in normalized:
        return _DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_502, "rollout_verify"
    if "deploy_runtime_reason_code=service_has_no_ready_endpoints" in normalized:
        return _DEPLOY_RUNTIME_REASON_SERVICE_HAS_NO_READY_ENDPOINTS, "rollout_verify"
    if "deploy_runtime_reason_code=service_endpoint_missing" in normalized:
        return _DEPLOY_RUNTIME_REASON_SERVICE_ENDPOINT_MISSING, "rollout_verify"
    if "deploy_runtime_reason_code=in_cluster_service_probe_timeout" in normalized:
        return _DEPLOY_RUNTIME_REASON_IN_CLUSTER_SERVICE_PROBE_TIMEOUT, "rollout_verify"
    if "deploy_runtime_reason_code=network_policy_may_block_service_probe" in normalized:
        return _DEPLOY_RUNTIME_REASON_NETWORK_POLICY_MAY_BLOCK_SERVICE_PROBE, "rollout_verify"
    if "deploy_runtime_reason_code=service_endpoint_unhealthy" in normalized:
        return _DEPLOY_RUNTIME_REASON_SERVICE_ENDPOINT_UNHEALTHY, "rollout_verify"
    if "deploy_runtime_reason_code=in_cluster_service_curl_failed_after_retries" in normalized:
        return _DEPLOY_RUNTIME_REASON_IN_CLUSTER_SERVICE_CURL_FAILED_AFTER_RETRIES, "rollout_verify"
    if "deploy_runtime_reason_code=in_cluster_service_curl_failed" in normalized:
        return _DEPLOY_RUNTIME_REASON_IN_CLUSTER_SERVICE_CURL_FAILED, "rollout_verify"
    if "deploy_runtime_reason_code=service_probe_waiting_for_convergence" in normalized:
        return _DEPLOY_RUNTIME_REASON_SERVICE_PROBE_WAITING_FOR_CONVERGENCE, "rollout_verify"
    if "deploy_runtime_reason_code=ingress_neg_convergence_pending" in normalized:
        return _DEPLOY_RUNTIME_REASON_INGRESS_NEG_CONVERGENCE_PENDING, "ingress_evidence"
    if "deploy_runtime_reason_code=ingress_status_ip_stale_or_mismatched" in normalized:
        return _DEPLOY_RUNTIME_REASON_INGRESS_STATUS_IP_STALE_OR_MISMATCHED, "ingress_evidence"
    if "deploy_runtime_reason_code=pod_ready_but_ingress_backend_unhealthy" in normalized:
        return _DEPLOY_RUNTIME_REASON_POD_READY_BUT_INGRESS_BACKEND_UNHEALTHY, "rollout_verify"
    if "deploy_runtime_reason_code=ingress_backend_unhealthy_after_rollout" in normalized:
        return _DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY_AFTER_ROLLOUT, "rollout_verify"
    if "deploy_runtime_reason_code=backend_config_healthcheck_unhealthy" in normalized:
        return _DEPLOY_RUNTIME_REASON_BACKEND_CONFIG_HEALTHCHECK_UNHEALTHY, "rollout_verify"
    if "deploy_runtime_reason_code=ingress_ip_assigned_but_dns_not_updated" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_IP_ASSIGNED_BUT_DNS_NOT_UPDATED, "ingress_evidence"
    if "deploy_runtime_reason_code=dns_points_to_old_ingress_ip" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_DNS_POINTS_TO_OLD_INGRESS_IP, "ingress_evidence"
    if "deploy_runtime_reason_code=dns_record_mismatch" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_DNS_RECORD_MISMATCH, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_site_static_ip_missing" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_MISSING, "ingress_verify"
    if "deploy_runtime_reason_code=shared_preview_gateway_missing" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_MISSING, "ingress_verify"
    if "deploy_runtime_reason_code=shared_preview_gateway_hostname_missing" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_PREVIEW_GATEWAY_HOSTNAME_MISSING, "ingress_verify"
    if "deploy_runtime_reason_code=expected_static_ip_not_bound_to_ingress" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_EXPECTED_STATIC_IP_NOT_BOUND_TO_INGRESS, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_certificate_pending" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING, "ingress_evidence"
    if "deploy_runtime_reason_code=tls_certificate_provisioning" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING, "ingress_evidence"
    if "deploy_runtime_reason_code=certificate_provisioning_pending" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING, "ingress_evidence"
    if "deploy_runtime_reason_code=runtime_ready_tls_pending" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING, "ingress_evidence"
    if "deploy_runtime_reason_code=certificate_domain_mismatch" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_CERTIFICATE_DOMAIN_MISMATCH, "ingress_evidence"
    if "deploy_runtime_reason_code=stale_managed_certificate_present" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_STALE_MANAGED_CERTIFICATE_PRESENT, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_certificate_ownership_unverified" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_OWNERSHIP_UNVERIFIED, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_certificate_domain_drift_repair_failed" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_DOMAIN_DRIFT_REPAIR_FAILED, "ingress_evidence"
    if "deploy_runtime_reason_code=tls_certificate_bound_to_wrong_site" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_BOUND_TO_WRONG_SITE, "ingress_evidence"
    if "deploy_runtime_reason_code=ingress_certificate_annotation_mismatch" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_CERTIFICATE_ANNOTATION_MISMATCH, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_certificate_identity_mismatch" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_IDENTITY_MISMATCH, "ingress_evidence"
    if "deploy_runtime_reason_code=shared_static_ip_not_allowed_for_per_site_ingress" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_STATIC_IP_NOT_ALLOWED, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_certificate_failed_not_visible" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE, "ingress_evidence"
    if "deploy_runtime_reason_code=ingress_static_ip_conflict" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_STATIC_IP_CONFLICT, "ingress_evidence"
    if "deploy_runtime_reason_code=stale_pre_shared_cert_binding_detected" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_STALE_PRE_SHARED_CERT_BINDING, "ingress_evidence"
    if "deploy_runtime_reason_code=pre_shared_cert_metadata_mismatch" in normalized:
        return _DEPLOY_RUNTIME_REASON_PRE_SHARED_CERT_METADATA_MISMATCH, "ingress_evidence"
    if "deploy_runtime_reason_code=managed_certificate_metadata_unavailable" in normalized:
        return _DEPLOY_RUNTIME_REASON_MANAGED_CERTIFICATE_METADATA_UNAVAILABLE, "ingress_evidence"
    if "deploy_runtime_reason_code=public_image_pull_failed" in normalized:
        return _DEPLOY_RUNTIME_REASON_PUBLIC_IMAGE_PULL_FAILED, "rollout_verify"
    if "deploy_runtime_reason_code=private_image_pull_forbidden" in normalized:
        return _DEPLOY_RUNTIME_REASON_PRIVATE_IMAGE_PULL_FORBIDDEN, "rollout_verify"
    if "deploy_runtime_reason_code=reachable_but_tls_certificate_mismatch" in normalized:
        return _DEPLOY_RUNTIME_REASON_REACHABLE_BUT_TLS_MISMATCH, "ingress_evidence"
    if "deploy_runtime_reason_code=https_probe_timeout" in normalized:
        return _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_TIMEOUT, "ingress_evidence"
    if "deploy_runtime_reason_code=https_probe_empty_reply" in normalized:
        return _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_EMPTY_REPLY, "ingress_evidence"
    if "deploy_runtime_reason_code=https_probe_not_attempted" in normalized:
        return _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_NOT_ATTEMPTED, "ingress_evidence"
    if "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready" in normalized:
        return _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_FAILED_AFTER_CONTROL_PLANE_READY, "ingress_evidence"
    if "deploy_runtime_reason_code=https_probe_failed" in normalized:
        return _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_FAILED_AFTER_CONTROL_PLANE_READY, "ingress_evidence"
    if "missing gcp_deploy_key secret" in normalized:
        return "generated_workflow_requires_missing_gcp_deploy_key", "workflow_execution"
    if "deploy_runtime_reason_code=ingress_address_pending_but_hostname_reachable" in normalized:
        return _DEPLOY_RUNTIME_REASON_INGRESS_PENDING_BUT_HOST_REACHABLE, "ingress_evidence"
    if "deploy_runtime_reason_code=image_pull_secret_missing" in normalized:
        return _DEPLOY_DISPATCH_SERVICE_REASON_IMAGE_PULL_SECRET_MISSING, "rollout_verify"
    if "deploy_runtime_reason_code=cloudsql_instance_inspection_failed" in normalized:
        return "cloudsql_instance_inspection_failed", "manifest_apply"
    if "deploy_runtime_reason_code=cloudsql_instance_invalid_state" in normalized:
        return "cloudsql_instance_invalid_state", "manifest_apply"
    has_invalid_state = "invalidstate" in normalized
    has_ephemeral_cert_failure = "fetch ephemeral cert failed" in normalized
    has_proxy_marker = "cloud-sql-proxy" in normalized or "cloud sql proxy" in normalized
    has_connection_failure = (
        "connection closed unexpectedly" in normalized
        or "connection reset by peer" in normalized
        or "connection refused" in normalized
        or "dial tcp 127.0.0.1:5432" in normalized
        or "dial tcp localhost:5432" in normalized
    )

    if has_invalid_state and has_ephemeral_cert_failure:
        return "cloudsql_instance_invalid_state", "manifest_apply"
    if has_ephemeral_cert_failure:
        return "cloudsql_proxy_ephemeral_cert_failed", "manifest_apply"
    if has_proxy_marker and has_connection_failure:
        return "cloudsql_proxy_connection_failed", "manifest_apply"
    return None, None


def _extract_runtime_failure_state_from_log_text(log_text: str | None) -> dict[str, str]:
    normalized = str(log_text or "")
    if not normalized:
        return {}
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    reason_code_present = False
    template_marker_present = False
    template_version: str | None = None
    template_version_prefix = f"{_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY}="
    resolve_template_version_prefix = f"resolve_live_url_state_{template_version_prefix}"

    for raw_line in normalized.splitlines():
        cleaned_line = ansi_escape.sub("", raw_line).strip()
        if not cleaned_line:
            continue
        lowered = cleaned_line.lower()
        if lowered.startswith("deploy_runtime_reason_code="):
            reason_code_value = cleaned_line.split("=", 1)[1].strip()
            sanitized_reason_code = _sanitize_github_error_message(
                reason_code_value,
                max_length=80,
            )
            if sanitized_reason_code:
                reason_code_present = True
        if lowered.startswith(resolve_template_version_prefix):
            template_version_value = cleaned_line.split("=", 1)[1].strip()
            sanitized_template_version = _sanitize_github_error_message(
                template_version_value,
                max_length=80,
            )
            if sanitized_template_version:
                template_version = sanitized_template_version
                template_marker_present = True
        elif lowered.startswith(template_version_prefix):
            template_version_value = cleaned_line.split("=", 1)[1].strip()
            sanitized_template_version = _sanitize_github_error_message(
                template_version_value,
                max_length=80,
            )
            if sanitized_template_version:
                template_version = sanitized_template_version
                template_marker_present = True

    output: dict[str, str] = {
        _DEPLOY_RUNTIME_REASON_CODE_PRESENT_OUTPUT_KEY: "true" if reason_code_present else "false",
        _MANAGED_DEPLOY_TEMPLATE_MARKER_PRESENT_OUTPUT_KEY: "true" if template_marker_present else "false",
    }
    if template_version:
        output[_MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY] = template_version
    return output


def _extract_resolve_live_url_state_from_log_text(log_text: str | None) -> dict[str, str]:
    normalized = str(log_text or "")
    if not normalized:
        return {}

    max_lengths: dict[str, int] = {
        "host_reachable": 8,
        "host_reachability_scheme": 12,
        "live_url": 240,
        "dns_record_matches_ingress": 8,
        "dns_expected_ip": 64,
        "dns_observed_ip": 64,
        "expected_static_ip_address": 64,
        "static_ip_status": 32,
        "static_ip_users": 720,
        "ingress_status_ip": 64,
        "ingress_status_ip_matches_static_ip": 8,
        "static_ip_bound_to_expected_forwarding_rule": 8,
        "tls_certificate_status": 64,
        "tls_domain_status": 64,
        "observed_managed_certificate_domains": 240,
        "observed_managed_certificate_status": 64,
        "observed_managed_certificate_domain_status": 64,
        "https_probe_error_summary": 240,
        "cert_identity_valid": 8,
        "deploy_https_ready": 8,
        "preview_https_status": 16,
        "preview_http_status": 16,
        "preview_probe_attempt": 8,
        "preview_probe_elapsed_seconds": 12,
        "gce_backend_health_status": 32,
        "k8s_endpoint_ready": 8,
        "service_probe_status": 40,
        "in_cluster_service_status_code": 16,
        "endpoint_probe_status": 40,
        "endpoint_probe_status_code": 16,
        "runtime_probe_status": 48,
        "pod_restart_detected": 8,
        "runtime_ready": 8,
        "ingress_address_resolved": 8,
        "service_exists": 12,
        "endpoints_ready": 12,
        "managed_certificate_exists": 12,
        "managed_certificate_status": 64,
        "https_ready": 8,
        "runtime_ready_tls_pending": 8,
        "replace_existing_runtime_requested": 8,
        "replace_existing_runtime_performed": 8,
        "deploy_runtime_failure_stage": 40,
        "deploy_runtime_reason_message": 240,
        _MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY: 80,
    }
    output: dict[str, str] = {}
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    for raw_line in normalized.splitlines():
        cleaned_line = ansi_escape.sub("", raw_line).strip()
        if "resolve_live_url_state_" not in cleaned_line:
            continue
        match = re.search(r"(resolve_live_url_state_[a-z0-9_]+)=(.*)$", cleaned_line)
        if match is None:
            continue
        raw_key = str(match.group(1) or "").strip().lower()
        raw_value = str(match.group(2) or "").strip()
        if not raw_key.startswith("resolve_live_url_state_"):
            continue
        normalized_key = raw_key[len("resolve_live_url_state_") :]
        if normalized_key not in max_lengths:
            continue
        sanitized_value = _sanitize_github_error_message(
            raw_value,
            max_length=max_lengths[normalized_key],
        )
        if sanitized_value is None:
            continue
        output[normalized_key] = sanitized_value

    return output


def _derive_https_probe_error_summary_for_failure(
    *,
    reason_code: str | None,
    failure_stage: str | None,
) -> str | None:
    normalized_reason = (_coerce_string(reason_code) or "").strip().lower()
    normalized_stage = (_coerce_string(failure_stage) or "").strip().lower()
    if normalized_stage not in {"ingress_verify", "ingress_evidence"}:
        return None

    reason_to_summary: dict[str, str] = {
        _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_TIMEOUT: "https_probe_timeout",
        _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_EMPTY_REPLY: "https_probe_empty_reply",
        _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_NOT_ATTEMPTED: "https_probe_not_attempted",
        _DEPLOY_RUNTIME_REASON_HTTPS_PROBE_FAILED_AFTER_CONTROL_PLANE_READY: (
            "https_probe_failed_after_control_plane_ready"
        ),
        _DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_502: "ingress_backend_502",
        _DEPLOY_RUNTIME_REASON_REACHABLE_BUT_TLS_MISMATCH: "cert_not_ready",
        _DEPLOY_RUNTIME_REASON_RUNTIME_MANAGED_CERTIFICATE_MISSING_AFTER_APPLY: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_CERTIFICATE_DOMAIN_MISMATCH: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_STALE_MANAGED_CERTIFICATE_PRESENT: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_OWNERSHIP_UNVERIFIED: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_BOUND_TO_WRONG_SITE: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_CERTIFICATE_ANNOTATION_MISMATCH: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_IDENTITY_MISMATCH: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_TLS_CERTIFICATE_PROVISIONING: "managed_certificate_provisioning",
        _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_CERTIFICATE_FAILED_NOT_VISIBLE: "cert_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_DNS_RECORD_MISMATCH: "dns_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_DNS_POINTS_TO_OLD_INGRESS_IP: "dns_not_ready",
        _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_IP_ASSIGNED_BUT_DNS_NOT_UPDATED: "dns_not_ready",
        _DEPLOY_RUNTIME_REASON_INGRESS_PENDING_BUT_HOST_REACHABLE: "host_resolution_pending",
        _DEPLOY_DISPATCH_SERVICE_REASON_MANAGED_SITE_STATIC_IP_MISSING: "host_resolution_pending",
        _DEPLOY_DISPATCH_SERVICE_REASON_EXPECTED_STATIC_IP_NOT_BOUND_TO_INGRESS: "host_resolution_pending",
        _DEPLOY_DISPATCH_SERVICE_REASON_SHARED_STATIC_IP_NOT_ALLOWED: "host_resolution_pending",
        _DEPLOY_DISPATCH_SERVICE_REASON_INGRESS_STATIC_IP_CONFLICT: "host_resolution_pending",
    }
    summary_reason = reason_to_summary.get(normalized_reason)
    if summary_reason is None:
        if normalized_stage == "ingress_evidence":
            summary_reason = "https_probe_failed_after_control_plane_ready"
        else:
            summary_reason = "host_resolution_pending"

    detail = "probe_failure_summary_unavailable"
    if summary_reason == "dns_not_ready":
        detail = "dns_record_not_aligned_with_expected_ingress_target"
    elif summary_reason == "cert_not_ready":
        detail = "certificate_identity_or_status_not_ready"
    elif summary_reason == "managed_certificate_provisioning":
        detail = "managed certificate/domain status still PROVISIONING"
    elif summary_reason == "host_resolution_pending":
        detail = "ingress_hostname_or_endpoint_not_ready"
    elif summary_reason == "https_probe_not_attempted":
        detail = "https_probe_not_attempted"
    elif summary_reason == "https_probe_failed_after_control_plane_ready":
        detail = "probe_attempted_without_error_summary"
    elif summary_reason == "ingress_backend_502":
        detail = "ingress_backend_returned_502"
    elif summary_reason == "https_probe_timeout":
        detail = "https_probe_timed_out"
    elif summary_reason == "https_probe_empty_reply":
        detail = "https_probe_returned_empty_reply"

    summary = f"reason={summary_reason};detail={detail}"
    sanitized_summary = _sanitize_github_error_message(summary, max_length=240)
    if sanitized_summary:
        return sanitized_summary
    return "reason=https_probe_failed_after_control_plane_ready;detail=probe_failure_summary_unavailable"


def _classify_rollout_blocker_hints_from_describe_outputs(
    *,
    deployment_describe_output: str | None,
    pods_describe_output: str | None,
    private_image_auth_required: bool = False,
) -> tuple[str, ...]:
    """Classify rollout blocker hints from namespace-scoped describe output.

    Keep this logic aligned with the managed deploy workflow shell diagnostics so
    tests can validate precedence and avoid false-positive blocker hints.
    """

    deployment_text = str(deployment_describe_output or "")
    pods_text = str(pods_describe_output or "")

    def _has(pattern: str, *texts: str) -> bool:
        return any(re.search(pattern, value, re.IGNORECASE) for value in texts if value)

    hints: list[str] = []

    image_pull_detected = False
    image_pull_secret_missing_detected = False
    if _has(r"ImagePullBackOff|ErrImagePull|pull access denied|manifest unknown|Failed to pull image", pods_text):
        image_pull_detected = True
        hints.append("image_pull_backoff")
        hints.append("image_pull_failure")
    if private_image_auth_required and _has(
        r"FailedToRetrieveImagePullSecret|image pull secret.*not found|pull secret.*not found|secret \".*\" not found.*(pull|image)",
        pods_text,
    ):
        image_pull_detected = True
        image_pull_secret_missing_detected = True
        hints.append("image_pull_secret_missing")
    if _has(r"failed to fetch anonymous token|403\s+Forbidden|unauthorized|authentication required", pods_text):
        image_pull_detected = True
        if private_image_auth_required:
            hints.append("private_image_pull_forbidden")
            hints.append("image_pull_forbidden")
            if not image_pull_secret_missing_detected:
                hints.append("image_pull_secret_not_referenced")
            hints.append("private_registry_auth_failure")
        else:
            hints.append("public_image_pull_failed")
    if _has(
        r"manifest unknown|name unknown|[Ii]magePullBackOff.*not found|[Ff]ailed to pull image.*not found|ghcr\.io/.+:.*not found",
        pods_text,
    ):
        image_pull_detected = True
        hints.append("container_image_not_found")

    if _has(
        r"CreateContainerConfigError|CreateContainerError|secret \".*\" not found|configmap \".*\" not found", pods_text
    ):
        hints.append("config_or_secret_reference_failure")

    if _has(
        r"exceeded quota|FailedCreate|forbidden: exceeded quota|requested: requests\.(memory|cpu)|limited: requests\.(memory|cpu)|limited: limits\.",
        deployment_text,
        pods_text,
    ):
        hints.append("resource_quota_rejection")

    if _has(r"FailedScheduling|Insufficient|didn.t match Pod.s node affinity|taint|node.s had", pods_text):
        hints.append("scheduling_or_resource_issue")

    if _has(
        r"endpoints:\s*<none>|subsets:\s*\[\]|addresses:\s*\[\]|notreadyaddresses|no endpoints available",
        deployment_text,
        pods_text,
    ):
        hints.append(_DEPLOY_RUNTIME_REASON_SERVICE_HAS_NO_READY_ENDPOINTS)
        hints.append(_DEPLOY_RUNTIME_REASON_SERVICE_ENDPOINT_MISSING)

    if _has(
        r"ingress backend.*unhealthy|backend service.*unhealthy|backend.*degraded mode|neg.*degraded mode|unhealthy backends",
        deployment_text,
        pods_text,
    ):
        hints.append(_DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY)
        hints.append(_DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY_AFTER_ROLLOUT)
    if _has(r"502|bad gateway", deployment_text, pods_text):
        hints.append(_DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_502)

    if _has(
        r"backendconfig.*healthcheck|healthcheck.*path|health check.*path|requestpath",
        deployment_text,
        pods_text,
    ):
        hints.append(_DEPLOY_RUNTIME_REASON_BACKENDCONFIG_HEALTH_CHECK_MISMATCH)
        hints.append(_DEPLOY_RUNTIME_REASON_BACKEND_CONFIG_HEALTHCHECK_UNHEALTHY)

    container_started_evidence = _has(
        r"Container ID:|Started:\s+true|State:\s+(Running|Terminated)",
        pods_text,
    )
    crash_direct_evidence = _has(
        r"CrashLoopBackOff|Back-off restarting failed container|OOMKilled|terminated with exit code|Last State:\s+Terminated|Reason:\s+Error",
        pods_text,
    )
    probe_direct_evidence = _has(
        r"Readiness probe failed|Liveness probe failed|Startup probe failed|Unhealthy|Probe errored",
        pods_text,
    )

    if not image_pull_detected and container_started_evidence and crash_direct_evidence:
        hints.append("pod_crash_or_startup_failure")
    if not image_pull_detected and container_started_evidence and probe_direct_evidence:
        hints.append("readiness_or_liveness_probe_failure")
    if container_started_evidence and _DEPLOY_RUNTIME_REASON_INGRESS_BACKEND_UNHEALTHY in hints:
        hints.append(_DEPLOY_RUNTIME_REASON_POD_READY_BUT_INGRESS_BACKEND_UNHEALTHY)
        hints.append(_DEPLOY_RUNTIME_REASON_SERVICE_ENDPOINT_UNHEALTHY)

    return tuple(dict.fromkeys(hints))


_WORKFLOW_CONFORMANCE_STATUS_CONFORMANT = "conformant"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_MISSING = "workflow_missing"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_UNREADABLE = "workflow_unreadable"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_DISPATCH_MISSING = "workflow_dispatch_missing"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_PLACEHOLDER_DETECTED = "workflow_placeholder_detected"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_CONTRACT_INCOMPLETE = "workflow_contract_incomplete"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_CONFORMANCE_UNKNOWN = "workflow_conformance_unknown"

_MANAGED_WORKFLOW_TEMPLATE_NAME = "managed_deploy_workflow_yaml"
_MANAGED_WORKFLOW_REQUIRED_STEP_NAME = "Resolve live URL from ingress status"
_MANAGED_WORKFLOW_REQUIRED_DEPLOY_OUTPUTS: tuple[str, ...] = (
    "live_url",
    "resolved_live_url",
    "deployed_url",
    "dns_record_matches_ingress",
    "dns_expected_ip",
    "dns_observed_ip",
    "tls_certificate_status",
    "tls_domain_status",
    "ingress_ip",
    "ingress_conflict_detected",
    "cert_identity_valid",
    "deploy_https_ready",
    _MBSRN_MANAGED_DEPLOY_TEMPLATE_VERSION_OUTPUT_KEY,
)

_WORKFLOW_CONFORMANCE_REQUIRED_DEPLOY_MARKERS: tuple[str, ...] = (
    "google-github-actions/auth",
    "google-github-actions/get-gke-credentials",
    "kubectl apply",
    "kubectl rollout",
    "gcloud container clusters get-credentials",
    "gcloud container",
)

_WORKFLOW_CONFORMANCE_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "mbsrn managed deploy placeholder",
    "placeholder deploy",
    "deploy step not yet implemented",
    "customize before production rollout",
    "get started with github actions",
)


def _is_managed_placeholder_workflow_content(*, workflow_content: str, workflow_id: str) -> bool:
    lowered = str(workflow_content or "").lower()
    if not lowered:
        return False
    workflow_id_normalized = str(workflow_id or "").strip().lower() or "deploy-www-prod.yml"
    has_template_marker = _MBSRN_MANAGED_TEMPLATE_MARKER_PREFIX in lowered
    has_placeholder_step = "placeholder deploy" in lowered
    has_customize_marker = "customize before production rollout" in lowered
    has_mode_scaffold_marker = "provisioned in mode" in lowered
    has_not_implemented_marker = "deploy step not yet implemented" in lowered
    has_workflow_provision_message = f"deploy workflow ({workflow_id_normalized}) provisioned" in lowered or (
        "deploy workflow (" in lowered and "provisioned" in lowered
    )
    has_mbsrn_placeholder_marker = "mbsrn managed deploy placeholder" in lowered
    if has_mbsrn_placeholder_marker:
        return True
    if has_template_marker and (has_placeholder_step or has_customize_marker or has_mode_scaffold_marker):
        return True
    if has_placeholder_step and has_workflow_provision_message and (has_customize_marker or has_mode_scaffold_marker):
        return True
    if has_placeholder_step and has_not_implemented_marker:
        return True
    return False


def _classify_workflow_management_state(
    *,
    file_payload: dict[str, object] | None,
    workflow_id: str,
    marker: str,
) -> str:
    if not isinstance(file_payload, dict):
        return "missing"
    decoded = _decode_workflow_file_content(file_payload)
    if not decoded:
        return "unreadable"
    lowered = decoded.lower()
    managed = marker.lower() in lowered
    placeholder = _is_managed_placeholder_workflow_content(
        workflow_content=decoded,
        workflow_id=workflow_id,
    )
    if managed and placeholder:
        return "managed_placeholder"
    if managed:
        return "managed_conformant_or_unknown"
    if placeholder:
        return "placeholder_non_managed"
    return "custom_or_non_managed"


def _derive_managed_workflow_outcome(
    *,
    existing_payload: dict[str, object] | None,
    classification: str | None,
    should_write: bool,
) -> str:
    if not isinstance(existing_payload, dict):
        return "managed_workflow_created"
    normalized_classification = str(classification or "").strip().lower()
    if normalized_classification in {
        "managed_placeholder",
        "managed_conformant_or_unknown",
        "placeholder_non_managed",
    }:
        if should_write:
            return "managed_workflow_upgraded"
        return "managed_workflow_already_current"
    return "managed_workflow_preserved_custom"


def _emit_structured_publisher_log(
    *,
    payload: dict[str, object],
    fallback_message: str,
    level: int = logging.INFO,
) -> None:
    if not isinstance(payload, dict):
        _LOGGER.log(level, fallback_message)
        return
    safe_payload = sanitize_log_payload(payload)
    if not isinstance(safe_payload, dict):
        _LOGGER.log(level, fallback_message)
        return
    try:
        message = json.dumps(safe_payload, ensure_ascii=True, sort_keys=True, default=str)
    except TypeError:
        message = fallback_message
    _LOGGER.log(level, message, extra={"json_fields": safe_payload})


def _normalize_repo_management_id(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    compact = normalized.strip()
    if not compact:
        return None
    return compact[:120]


def _normalize_repo_visibility(repo_payload: dict[str, object] | None) -> str | None:
    if not isinstance(repo_payload, dict):
        return None
    private_value = repo_payload.get("private")
    if isinstance(private_value, bool):
        return "private" if private_value else "public"
    visibility_value = (_coerce_string(repo_payload.get("visibility")) or "").strip().lower()
    if visibility_value in {"private", "public", "internal"}:
        return visibility_value
    return None


def _render_repo_baseline_files(
    *,
    repo_owner: str,
    repo_name: str,
    business_id: str,
    site_id: str,
) -> dict[str, str]:
    return {
        _MBSRN_REPO_MANAGEMENT_MARKER_PATH: _render_repo_management_marker_content(
            business_id=business_id,
            site_id=site_id,
        ),
        _MBSRN_MANAGED_REPO_BASELINE_README_PATH: _render_repo_baseline_readme_content(
            repo_owner=repo_owner,
            repo_name=repo_name,
        ),
        _MBSRN_MANAGED_REPO_BASELINE_GITIGNORE_PATH: _render_repo_baseline_gitignore_content(),
        _MBSRN_MANAGED_REPO_BASELINE_LICENSE_PATH: _render_repo_baseline_license_content(),
    }


def _render_repo_baseline_readme_content(*, repo_owner: str, repo_name: str) -> str:
    normalized_owner = (_coerce_string(repo_owner) or "").strip() or "unknown-owner"
    normalized_repo = (_coerce_string(repo_name) or "").strip() or "managed-site"
    return (
        f"# {normalized_repo}\n"
        "\n"
        f"This repository (`{normalized_owner}/{normalized_repo}`) is managed by MBSRN.\n"
        "\n"
        "- Ownership marker: `mbsrn.key`\n"
        "- Managed publish/deploy assets may be updated by MBSRN migration workflows.\n"
    )


def _render_repo_baseline_gitignore_content() -> str:
    return (
        "# Byte-compiled / optimized / DLL files\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        "*$py.class\n"
        "\n"
        "# Virtual environments\n"
        ".venv/\n"
        "venv/\n"
        "env/\n"
        "ENV/\n"
        "\n"
        "# Distribution / packaging\n"
        "build/\n"
        "dist/\n"
        "*.egg-info/\n"
        "\n"
        "# Test / coverage\n"
        ".pytest_cache/\n"
        ".coverage\n"
        "htmlcov/\n"
        "\n"
        "# IDE/editor\n"
        ".vscode/\n"
        ".idea/\n"
        "\n"
        "# OS-generated\n"
        ".DS_Store\n"
        "Thumbs.db\n"
    )


def _render_repo_baseline_license_content() -> str:
    return (
        "Apache License\n"
        "Version 2.0, January 2004\n"
        "http://www.apache.org/licenses/\n"
        "\n"
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\n"
        "\n"
        "1. Definitions.\n"
        "\n"
        '"License" shall mean the terms and conditions for use, reproduction,\n'
        "and distribution as defined by Sections 1 through 9 of this document.\n"
        "\n"
        '"Licensor" shall mean the copyright owner or entity authorized by\n'
        "the copyright owner that is granting the License.\n"
        "\n"
        '"Legal Entity" shall mean the union of the acting entity and all\n'
        "other entities that control, are controlled by, or are under common\n"
        "control with that entity. For the purposes of this definition,\n"
        '"control" means (i) the power, direct or indirect, to cause the\n'
        "direction or management of such entity, whether by contract or\n"
        "otherwise, or (ii) ownership of fifty percent (50%) or more of the\n"
        "outstanding shares, or (iii) beneficial ownership of such entity.\n"
        "\n"
        '"You" (or "Your") shall mean an individual or Legal Entity\n'
        "exercising permissions granted by this License.\n"
        "\n"
        '"Source" form shall mean the preferred form for making modifications,\n'
        "including but not limited to software source code, documentation\n"
        "source, and configuration files.\n"
        "\n"
        '"Object" form shall mean any form resulting from mechanical\n'
        "transformation or translation of a Source form, including but\n"
        "not limited to compiled object code, generated documentation,\n"
        "and conversions to other media types.\n"
        "\n"
        '"Work" shall mean the work of authorship, whether in Source or\n'
        "Object form, made available under the License, as indicated by a\n"
        "copyright notice that is included in or attached to the work\n"
        "(an example is provided in the Appendix below).\n"
        "\n"
        '"Derivative Works" shall mean any work, whether in Source or Object\n'
        "form, that is based on (or derived from) the Work and for which the\n"
        "editorial revisions, annotations, elaborations, or other modifications\n"
        "represent, as a whole, an original work of authorship. For the purposes\n"
        "of this License, Derivative Works shall not include works that remain\n"
        "separable from, or merely link (or bind by name) to the interfaces of,\n"
        "the Work and Derivative Works thereof.\n"
        "\n"
        '"Contribution" shall mean any work of authorship, including\n'
        "the original version of the Work and any modifications or additions\n"
        "to that Work or Derivative Works thereof, that is intentionally\n"
        "submitted to Licensor for inclusion in the Work by the copyright owner\n"
        "or by an individual or Legal Entity authorized to submit on behalf of\n"
        'the copyright owner. For the purposes of this definition, "submitted"\n'
        "means any form of electronic, verbal, or written communication sent to\n"
        "the Licensor or its representatives, including but not limited to\n"
        "communication on electronic mailing lists, source code control systems,\n"
        "and issue tracking systems that are managed by, or on behalf of, the\n"
        "Licensor for the purpose of discussing and improving the Work, but\n"
        "excluding communication that is conspicuously marked or otherwise\n"
        'designated in writing by the copyright owner as "Not a Contribution."\n'
        "\n"
        '"Contributor" shall mean Licensor and any individual or Legal Entity\n'
        "on behalf of whom a Contribution has been received by Licensor and\n"
        "subsequently incorporated within the Work.\n"
        "\n"
        "2. Grant of Copyright License. Subject to the terms and conditions of\n"
        "this License, each Contributor hereby grants to You a perpetual,\n"
        "worldwide, non-exclusive, no-charge, royalty-free, irrevocable\n"
        "copyright license to reproduce, prepare Derivative Works of,\n"
        "publicly display, publicly perform, sublicense, and distribute the\n"
        "Work and such Derivative Works in Source or Object form.\n"
        "\n"
        "3. Grant of Patent License. Subject to the terms and conditions of\n"
        "this License, each Contributor hereby grants to You a perpetual,\n"
        "worldwide, non-exclusive, no-charge, royalty-free, irrevocable\n"
        "(except as stated in this section) patent license to make, have made,\n"
        "use, offer to sell, sell, import, and otherwise transfer the Work,\n"
        "where such license applies only to those patent claims licensable\n"
        "by such Contributor that are necessarily infringed by their\n"
        "Contribution(s) alone or by combination of their Contribution(s)\n"
        "with the Work to which such Contribution(s) was submitted. If You\n"
        "institute patent litigation against any entity (including a\n"
        "cross-claim or counterclaim in a lawsuit) alleging that the Work\n"
        "or a Contribution incorporated within the Work constitutes direct\n"
        "or contributory patent infringement, then any patent licenses\n"
        "granted to You under this License for that Work shall terminate\n"
        "as of the date such litigation is filed.\n"
        "\n"
        "4. Redistribution. You may reproduce and distribute copies of the\n"
        "Work or Derivative Works thereof in any medium, with or without\n"
        "modifications, and in Source or Object form, provided that You\n"
        "meet the following conditions:\n"
        "\n"
        "(a) You must give any other recipients of the Work or\n"
        "Derivative Works a copy of this License; and\n"
        "\n"
        "(b) You must cause any modified files to carry prominent notices\n"
        "stating that You changed the files; and\n"
        "\n"
        "(c) You must retain, in the Source form of any Derivative Works\n"
        "that You distribute, all copyright, patent, trademark, and\n"
        "attribution notices from the Source form of the Work,\n"
        "excluding those notices that do not pertain to any part of\n"
        "the Derivative Works; and\n"
        "\n"
        '(d) If the Work includes a "NOTICE" text file as part of its\n'
        "distribution, then any Derivative Works that You distribute must\n"
        "include a readable copy of the attribution notices contained\n"
        "within such NOTICE file, excluding those notices that do not\n"
        "pertain to any part of the Derivative Works, in at least one\n"
        "of the following places: within a NOTICE text file distributed\n"
        "as part of the Derivative Works; within the Source form or\n"
        "documentation, if provided along with the Derivative Works; or,\n"
        "within a display generated by the Derivative Works, if and\n"
        "wherever such third-party notices normally appear. The contents\n"
        "of the NOTICE file are for informational purposes only and\n"
        "do not modify the License. You may add Your own attribution\n"
        "notices within Derivative Works that You distribute, alongside\n"
        "or as an addendum to the NOTICE text from the Work, provided\n"
        "that such additional attribution notices cannot be construed\n"
        "as modifying the License.\n"
        "\n"
        "You may add Your own copyright statement to Your modifications and\n"
        "may provide additional or different license terms and conditions\n"
        "for use, reproduction, or distribution of Your modifications, or\n"
        "for any such Derivative Works as a whole, provided Your use,\n"
        "reproduction, and distribution of the Work otherwise complies with\n"
        "the conditions stated in this License.\n"
        "\n"
        "5. Submission of Contributions. Unless You explicitly state otherwise,\n"
        "any Contribution intentionally submitted for inclusion in the Work\n"
        "by You to the Licensor shall be under the terms and conditions of\n"
        "this License, without any additional terms or conditions.\n"
        "Notwithstanding the above, nothing herein shall supersede or modify\n"
        "the terms of any separate license agreement you may have executed\n"
        "with Licensor regarding such Contributions.\n"
        "\n"
        "6. Trademarks. This License does not grant permission to use the trade\n"
        "names, trademarks, service marks, or product names of the Licensor,\n"
        "except as required for reasonable and customary use in describing the\n"
        "origin of the Work and reproducing the content of the NOTICE file.\n"
        "\n"
        "7. Disclaimer of Warranty. Unless required by applicable law or\n"
        "agreed to in writing, Licensor provides the Work (and each\n"
        'Contributor provides its Contributions) on an "AS IS" BASIS,\n'
        "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or\n"
        "implied, including, without limitation, any warranties or conditions\n"
        "of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A\n"
        "PARTICULAR PURPOSE. You are solely responsible for determining the\n"
        "appropriateness of using or redistributing the Work and assume any\n"
        "risks associated with Your exercise of permissions under this License.\n"
        "\n"
        "8. Limitation of Liability. In no event and under no legal theory,\n"
        "whether in tort (including negligence), contract, or otherwise,\n"
        "unless required by applicable law (such as deliberate and grossly\n"
        "negligent acts) or agreed to in writing, shall any Contributor be\n"
        "liable to You for damages, including any direct, indirect, special,\n"
        "incidental, or consequential damages of any character arising as a\n"
        "result of this License or out of the use or inability to use the\n"
        "Work (including but not limited to damages for loss of goodwill,\n"
        "work stoppage, computer failure or malfunction, or any and all\n"
        "other commercial damages or losses), even if such Contributor\n"
        "has been advised of the possibility of such damages.\n"
        "\n"
        "9. Accepting Warranty or Additional Liability. While redistributing\n"
        "the Work or Derivative Works thereof, You may choose to offer,\n"
        "and charge a fee for, acceptance of support, warranty, indemnity,\n"
        "or other liability obligations and/or rights consistent with this\n"
        "License. However, in accepting such obligations, You may act only\n"
        "on Your own behalf and on Your sole responsibility, not on behalf\n"
        "of any other Contributor, and only if You agree to indemnify,\n"
        "defend, and hold each Contributor harmless for any liability\n"
        "incurred by, or claims asserted against, such Contributor by reason\n"
        "of your accepting any such warranty or additional liability.\n"
        "\n"
        "END OF TERMS AND CONDITIONS\n"
    )


def _render_repo_management_marker_content(
    *,
    business_id: str,
    site_id: str,
    adopted_at: str | None = None,
    adopted_by: str | None = None,
) -> str:
    payload = {
        "version": 1,
        "managed_by": "mbsrn",
        "created_by": "mbsrn",
        "business_id": business_id,
        "site_id": site_id,
    }
    normalized_adopted_at = _coerce_string(adopted_at)
    normalized_adopted_by = _coerce_string(adopted_by)
    if normalized_adopted_at:
        payload["adopted_at"] = normalized_adopted_at
    if normalized_adopted_by:
        payload["adopted_by"] = normalized_adopted_by
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def _parse_repo_management_marker_payload(payload: dict[str, object] | None) -> tuple[str | None, str | None]:
    decoded = _decode_workflow_file_content(payload)
    if not decoded:
        return None, None
    try:
        parsed = json.loads(decoded)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    business_id = _normalize_repo_management_id(parsed.get("business_id"))
    site_id = _normalize_repo_management_id(parsed.get("site_id"))
    return business_id, site_id


def _sanitize_github_error_message(value: object, *, max_length: int = 240) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    compact = " ".join(normalized.replace("\r", " ").replace("\n", " ").split())
    if not compact:
        return None
    lowered = compact.lower()
    if "authorization" in lowered and "bearer" in lowered:
        return "authorization_header_redacted"
    if len(compact) > max_length:
        return compact[:max_length]
    return compact


def _extract_repo_initialization_step(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    lowered = normalized.strip().lower()
    prefix = "step_failed="
    if not lowered.startswith(prefix):
        return None
    step = lowered[len(prefix) :].split(";", 1)[0].strip()
    if step in {"blob", "tree", "commit", "ref"}:
        return step
    return None


def _extract_repo_initialization_request_path(value: object) -> str | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    lowered = normalized.strip().lower()
    prefix = "request_path="
    marker_index = lowered.find(prefix)
    if marker_index < 0:
        return None
    remainder = lowered[marker_index + len(prefix) :]
    request_path = remainder.split(";", 1)[0].strip()
    return request_path or None


def _extract_repo_initialization_payload_keys(value: object) -> tuple[str, ...] | None:
    normalized = _coerce_string(value)
    if not normalized:
        return None
    lowered = normalized.strip().lower()
    prefix = "payload_keys="
    marker_index = lowered.find(prefix)
    if marker_index < 0:
        return None
    remainder = lowered[marker_index + len(prefix) :]
    payload_keys_value = remainder.split(";", 1)[0].strip()
    if not payload_keys_value:
        return None
    keys = tuple(item.strip() for item in payload_keys_value.split(",") if item.strip())
    return keys or None


def _should_treat_ref_check_as_uninitialized(exc: SEOMigrationGitHubPublisherError) -> bool:
    normalized_code = (_coerce_string(exc.code) or "").strip().lower()
    if normalized_code == _GITHUB_REASON_BRANCH_UNINITIALIZED:
        return True
    provider_message = (_coerce_string(exc.provider_message) or "").strip().lower()
    if exc.status_code == 409 and provider_message:
        if "git repository is empty" in provider_message:
            return True
        if "empty repository" in provider_message:
            return True
        if "no default branch" in provider_message:
            return True
        if "uninitialized" in provider_message:
            return True
    return False


def _decode_workflow_file_content(workflow_file_payload: dict[str, object] | None) -> str | None:
    if not isinstance(workflow_file_payload, dict):
        return None
    encoding = (_coerce_string(workflow_file_payload.get("encoding")) or "").strip().lower()
    content = _coerce_string(workflow_file_payload.get("content"))
    if encoding != "base64" or not content:
        return None
    try:
        decoded = base64.b64decode(content, validate=False).decode("utf-8", errors="replace")
    except Exception:
        return None
    normalized = decoded.strip()
    return normalized or None


def _evaluate_workflow_conformance(
    *,
    workflow_file_payload: dict[str, object] | None,
    workflow_trigger_types: set[str] | tuple[str, ...] | list[str],
) -> SEOMigrationGitHubWorkflowConformanceResult:
    if not isinstance(workflow_file_payload, dict):
        return SEOMigrationGitHubWorkflowConformanceResult(
            is_conformant=False,
            conformance_status=_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_MISSING,
            conformance_reasons=("workflow_file_payload_missing",),
            evidence_summary="workflow_file_payload=missing",
        )

    decoded_content = _decode_workflow_file_content(workflow_file_payload)
    if decoded_content is None:
        return SEOMigrationGitHubWorkflowConformanceResult(
            is_conformant=False,
            conformance_status=_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_UNREADABLE,
            conformance_reasons=("workflow_file_content_unreadable",),
            evidence_summary="workflow_file_content=unreadable",
        )

    lowered = decoded_content.lower()
    normalized_trigger_types = {
        str(item).strip().lower() for item in (workflow_trigger_types or []) if str(item).strip()
    }
    has_dispatch_trigger = "workflow_dispatch" in lowered or "workflow_dispatch" in normalized_trigger_types
    if not has_dispatch_trigger:
        return SEOMigrationGitHubWorkflowConformanceResult(
            is_conformant=False,
            conformance_status=_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_DISPATCH_MISSING,
            conformance_reasons=("workflow_dispatch_trigger_missing",),
            evidence_summary="workflow_dispatch=false",
        )

    placeholder_markers = tuple(marker for marker in _WORKFLOW_CONFORMANCE_PLACEHOLDER_MARKERS if marker in lowered)
    if placeholder_markers:
        return SEOMigrationGitHubWorkflowConformanceResult(
            is_conformant=False,
            conformance_status=_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_PLACEHOLDER_DETECTED,
            conformance_reasons=("placeholder_workflow_content_detected",),
            evidence_summary=("workflow_dispatch=true;" f"placeholder_markers={','.join(placeholder_markers)}"),
        )

    required_marker_hits = tuple(
        marker for marker in _WORKFLOW_CONFORMANCE_REQUIRED_DEPLOY_MARKERS if marker in lowered
    )
    if not required_marker_hits:
        return SEOMigrationGitHubWorkflowConformanceResult(
            is_conformant=False,
            conformance_status=_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_CONTRACT_INCOMPLETE,
            conformance_reasons=("managed_deploy_contract_markers_missing",),
            evidence_summary="workflow_dispatch=true;required_deploy_markers=missing",
        )

    return SEOMigrationGitHubWorkflowConformanceResult(
        is_conformant=True,
        conformance_status=_WORKFLOW_CONFORMANCE_STATUS_CONFORMANT,
        conformance_reasons=(),
        evidence_summary=("workflow_dispatch=true;" f"required_deploy_markers={','.join(required_marker_hits)}"),
    )


def _validate_managed_workflow_template_before_publish(
    *,
    workflow_yaml: str,
) -> SEOMigrationManagedWorkflowTemplateValidationResult:
    normalized_yaml = str(workflow_yaml or "").strip()
    if not normalized_yaml:
        return SEOMigrationManagedWorkflowTemplateValidationResult(
            is_valid=False,
            validation_errors=("workflow_yaml_empty",),
        )
    try:
        parsed = yaml.safe_load(normalized_yaml)
    except yaml.YAMLError:
        return SEOMigrationManagedWorkflowTemplateValidationResult(
            is_valid=False,
            validation_errors=("workflow_yaml_parse_failed",),
        )

    validation_errors: list[str] = []
    if not isinstance(parsed, dict):
        return SEOMigrationManagedWorkflowTemplateValidationResult(
            is_valid=False,
            validation_errors=("workflow_yaml_root_not_mapping",),
        )

    trigger_config = _extract_workflow_trigger_config(parsed)
    if not _workflow_has_dispatch_trigger(trigger_config):
        validation_errors.append("workflow_dispatch_missing")

    jobs_config = parsed.get("jobs")
    deploy_config: object = None
    if isinstance(jobs_config, dict):
        deploy_config = jobs_config.get("deploy")
    else:
        validation_errors.append("jobs_deploy_missing")
    if not isinstance(deploy_config, dict):
        if "jobs_deploy_missing" not in validation_errors:
            validation_errors.append("jobs_deploy_missing")
        return SEOMigrationManagedWorkflowTemplateValidationResult(
            is_valid=False,
            validation_errors=tuple(validation_errors),
        )

    outputs_config = deploy_config.get("outputs")
    missing_outputs: list[str] = []
    if isinstance(outputs_config, dict):
        for output_name in _MANAGED_WORKFLOW_REQUIRED_DEPLOY_OUTPUTS:
            if output_name not in outputs_config:
                missing_outputs.append(output_name)
    else:
        missing_outputs = list(_MANAGED_WORKFLOW_REQUIRED_DEPLOY_OUTPUTS)
    if missing_outputs:
        validation_errors.append("deploy_outputs_missing:" + ",".join(missing_outputs))

    steps_config = deploy_config.get("steps")
    has_required_step = False
    if isinstance(steps_config, list):
        for step in steps_config:
            if not isinstance(step, dict):
                continue
            step_name = str(step.get("name") or "").strip()
            if step_name == _MANAGED_WORKFLOW_REQUIRED_STEP_NAME:
                has_required_step = True
                break
    if not has_required_step:
        validation_errors.append("resolve_live_url_step_missing")

    return SEOMigrationManagedWorkflowTemplateValidationResult(
        is_valid=(not validation_errors),
        validation_errors=tuple(validation_errors),
    )


def _extract_workflow_trigger_config(workflow_payload: dict[str, object]) -> object | None:
    if "on" in workflow_payload:
        return workflow_payload.get("on")
    if True in workflow_payload:
        return workflow_payload.get(True)
    for key, value in workflow_payload.items():
        if str(key).strip().lower() == "on":
            return value
    return None


def _workflow_has_dispatch_trigger(trigger_config: object) -> bool:
    if isinstance(trigger_config, dict):
        for key in trigger_config.keys():
            if str(key).strip() == "workflow_dispatch":
                return True
        return False
    if isinstance(trigger_config, list):
        for item in trigger_config:
            if str(item).strip() == "workflow_dispatch":
                return True
        return False
    return str(trigger_config or "").strip() == "workflow_dispatch"


def _extract_workflow_trigger_types(workflow_file_payload: dict[str, object] | None) -> set[str]:
    decoded = _decode_workflow_file_content(workflow_file_payload)
    if not decoded:
        return set()
    lowered = decoded.lower()
    triggers: set[str] = set()
    if "workflow_dispatch" in lowered:
        triggers.add("workflow_dispatch")
    if "push" in lowered:
        triggers.add("push")
    if "pull_request" in lowered:
        triggers.add("pull_request")
    return triggers


def _workflow_dispatch_identifier_type(workflow_id: str) -> str:
    normalized = str(workflow_id or "").strip()
    if normalized.isdigit():
        return "workflow_id"
    if normalized.lower().startswith(".github/workflows/") or normalized.lower().startswith("github/workflows/"):
        return "workflow_file_path"
    if "/" in normalized:
        return "workflow_file_path"
    if normalized.lower().endswith(".yml") or normalized.lower().endswith(".yaml"):
        return "workflow_file_path"
    return "workflow_id"

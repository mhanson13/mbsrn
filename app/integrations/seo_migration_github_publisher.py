from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from app.core.time import utc_now
from app.core.runtime_metadata import get_runtime_build_metadata

_LOGGER = logging.getLogger(__name__)
_VALID_REPO_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_VALID_REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED = "github_workflow_write_not_authorized"
_GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED = "github_contents_write_not_authorized"
_GITHUB_REASON_BRANCH_UNINITIALIZED = "github_branch_not_found_or_uninitialized"
_GITHUB_REASON_REPO_BOOTSTRAP_INVALID = "github_repo_state_invalid_for_bootstrap"
_GITHUB_REASON_WORKFLOW_PROVISIONING_FAILED = "github_workflow_provisioning_failed"
_GITHUB_REASON_CONTENTS_PUBLISH_FAILED = "github_contents_publish_failed"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISSING = "github_repo_management_marker_missing"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISMATCH = "github_repo_management_marker_mismatch"
_GITHUB_REASON_REPO_MANAGEMENT_MARKER_INVALID = "github_repo_management_marker_invalid"
_GITHUB_REASON_REPO_BOOTSTRAP_MARKER_WRITE_FAILED = "github_repo_bootstrap_marker_write_failed"
_GITHUB_REASON_REPO_BASELINE_RECONCILIATION_FAILED = "github_repo_baseline_reconciliation_failed"
_MBSRN_REPO_MANAGEMENT_MARKER_PATH = "mbsrn.key"


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
    content: str
    media_type: str


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
    managed_gke_config_details: dict[str, object] | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubWorkflowConformanceResult:
    is_conformant: bool
    conformance_status: str
    conformance_reasons: tuple[str, ...]
    evidence_summary: str | None = None


@dataclass(frozen=True)
class SEOMigrationGitHubPublisherError(RuntimeError):
    code: str
    safe_message: str
    status_code: int | None = None
    stage: str | None = None
    provider_message: str | None = None

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

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
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
        business_id: str | None = None,
        repository_auto_create_created: bool | None = None,
        artifact_version_id: str | None = None,
    ) -> SEOMigrationGitHubWorkflowProvisionResult:
        del (
            deploy_workflow_mode,
            target_environment_key,
            target_environment_source,
            managed_gke_config,
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
    ) -> SEOMigrationGitHubTargetReadinessResult:
        del allow_ref_repair, allow_workflow_repair, dry_run, managed_gke_config, namespace_isolation_defaults
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

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
    ) -> SEOMigrationGitHubDeployResult:
        del target, dry_run, managed_gke_config
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
        del (
            target,
            allow_ref_repair,
            allow_workflow_repair,
            dry_run,
            remediation_mode,
            managed_gke_config,
            namespace_isolation_defaults,
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
    ) -> None:
        normalized_token = token.strip()
        if not normalized_token:
            raise ValueError("GitHub token is required.")
        self.token = normalized_token
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.committer_name = committer_name.strip() or "MBSRN Migration Bot"
        self.committer_email = committer_email.strip() or "migration-bot@mbsrn.local"
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
                permissions_payload = (
                    repo_payload.get("permissions")
                    if isinstance(repo_payload, dict)
                    else None
                )
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
                    default_branch = (_coerce_string((repo_payload or {}).get("default_branch")) or "").strip() or "main"
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
                    if (not would_bootstrap_branch) and preflight_blocker_code is None:
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
                    baseline_ref = (
                        (_coerce_string(management_state.source_ref) or "").strip()
                        or normalized_ref
                    )
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
            "auto_init": False,
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

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        published_at = utc_now().isoformat()
        committed_paths: list[str] = []
        if dry_run:
            total_bytes = sum(len(item.content.encode("utf-8")) for item in files)
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
        effective_business_id = (
            _normalize_repo_management_id(target.business_id)
            or _normalize_repo_management_id(management_state.marker_business_id)
        )
        effective_site_id = (
            _normalize_repo_management_id(target.site_id)
            or _normalize_repo_management_id(management_state.marker_site_id)
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
            total_bytes += len(file_item.content.encode("utf-8"))
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
            existing_sha = (
                _coerce_string(existing_payload.get("sha"))
                if isinstance(existing_payload, dict)
                else None
            )
            encoded_content = base64.b64encode(file_item.content.encode("utf-8")).decode("ascii")
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
            and (
                not provider_message_lower
                or any(marker in provider_message_lower for marker in branch_state_markers)
            )
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
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                "/actions/secrets/public-key"
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

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
        managed_gke_config: dict[str, object] | None = None,
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
                    "effective_cluster_name_present": bool(
                        readiness_gke_details.get("effective_cluster_name_present")
                    ),
                    "effective_cluster_location_present": bool(
                        readiness_gke_details.get("effective_cluster_location_present")
                    ),
                    "effective_project_id_present": bool(
                        readiness_gke_details.get("effective_project_id_present")
                    ),
                    "gke_config_resolution_source": _coerce_string(
                        readiness_gke_details.get("gke_config_resolution_source")
                    ),
                    "dispatch_service_availability": bool(readiness_result.dispatch_service_availability),
                    "dispatch_service_reason_code": readiness_result.dispatch_service_reason_code,
                },
                fallback_message="seo_migration_dispatch_managed_gke_config_presence",
                level=(
                    logging.INFO
                    if readiness_result.dispatch_service_availability
                    else logging.WARNING
                ),
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
            ) = self._resolve_workflow_run_failure_details(
                target=target,
                workflow_run_id=run_id,
                workflow_run_status=run_status,
                workflow_run_conclusion=run_conclusion,
            )

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
            ) = self._resolve_workflow_run_failure_details(
                target=target,
                workflow_run_id=workflow_run_id,
                workflow_run_status=workflow_run_status,
                workflow_run_conclusion=workflow_run_conclusion,
            )

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
    ) -> tuple[str | None, str | None, str | None]:
        run_id = workflow_run_id if isinstance(workflow_run_id, int) and workflow_run_id > 0 else None
        run_status = (_coerce_string(workflow_run_status) or "").strip().lower()
        run_conclusion = (_coerce_string(workflow_run_conclusion) or "").strip().lower()
        if run_id is None or run_status != "completed" or run_conclusion in {"", "success"}:
            return None, None, None

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
                        failed_step_name = _coerce_string(step_item.get("name")) or _coerce_string(
                            job_item.get("name")
                        )
                        break
                if failed_step_name is None:
                    failed_step_name = _coerce_string(job_item.get("name"))
                break

        reason_code, failure_stage = _classify_workflow_run_failure(
            failed_step_name=failed_step_name,
            run_conclusion=run_conclusion,
        )
        if reason_code == "workflow_run_failed" and failed_job_id is not None:
            cloudsql_reason_code, cloudsql_failure_stage = self._classify_cloudsql_proxy_failure_from_job_logs(
                target=target,
                job_id=failed_job_id,
            )
            if cloudsql_reason_code:
                reason_code = cloudsql_reason_code
                if cloudsql_failure_stage:
                    failure_stage = cloudsql_failure_stage
        return reason_code, failure_stage, failed_step_name

    def _classify_cloudsql_proxy_failure_from_job_logs(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        job_id: int,
    ) -> tuple[str | None, str | None]:
        if job_id <= 0:
            return None, None
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
        return _classify_cloudsql_proxy_failure_from_log_text(logs_text)

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

    def _ensure_ref_exists(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        allow_repair: bool,
        dry_run: bool | None = None,
        remediation_mode: str | None = None,
        workflow_path: str | None = None,
        business_id: str | None = None,
        site_id: str | None = None,
        artifact_version_id: str | None = None,
        repository_auto_create_created: bool | None = None,
    ) -> None:
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
        ref_check_error: SEOMigrationGitHubPublisherError | None = None
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
            branch_exists = None
            ref_check_error = SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_BRANCH_UNINITIALIZED,
                safe_message="GitHub repository branch is missing or uninitialized for managed workflow provisioning.",
                status_code=exc.status_code,
                stage=exc.stage,
                provider_message=exc.provider_message,
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
            return
        decision_source = "missing_target_ref"
        if ref_check_error is not None:
            decision_source = "ref_check_uninitialized"
        _emit_structured_publisher_log(
            payload={
                "event": "seo_migration_workflow_provisioning_operation",
                "operation_kind": "repo_bootstrap_decision",
                "operation_status": "evaluated",
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "ref": normalized_ref,
                "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                "artifact_version_id": _coerce_string(artifact_version_id),
                "business_id": _coerce_string(business_id),
                "site_id": _coerce_string(site_id),
                "repo_exists": True,
                "repository_auto_create_created": (
                    bool(repository_auto_create_created)
                    if repository_auto_create_created is not None
                    else None
                ),
                "bootstrap_decision_source": decision_source,
                "github_error_code": (ref_check_error.code if ref_check_error else None),
                "http_status_code": (ref_check_error.status_code if ref_check_error else None),
                "github_error_message": (
                    _sanitize_github_error_message(ref_check_error.provider_message)
                    if ref_check_error
                    else None
                ),
                "dry_run": dry_run_value,
                "allow_repair": allow_repair_value,
                "remediation_mode": normalized_remediation_mode,
                "bootstrap_allowed": bootstrap_allowed,
                "will_attempt_bootstrap": bool(bootstrap_allowed),
                "bootstrap_blocked_reason": (
                    "bootstrap_disabled_by_execution_mode" if not bootstrap_allowed else None
                ),
                "git_commit": runtime_git_commit,
                "build_version": runtime_build_version,
            },
            fallback_message="seo_migration_workflow_provisioning_operation",
            level=logging.INFO,
        )
        if not bootstrap_allowed:
            if decision_source == "ref_check_uninitialized":
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_REPO_BOOTSTRAP_INVALID,
                    safe_message=(
                        "GitHub repository branch is uninitialized and bootstrap is disabled for this execution mode."
                    ),
                    status_code=(ref_check_error.status_code if ref_check_error else None),
                    stage=(ref_check_error.stage if ref_check_error else "workflow_provisioning"),
                    provider_message=(ref_check_error.provider_message if ref_check_error else None),
                )
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        default_branch = self._resolve_default_branch(repo_owner=repo_owner, repo_name=repo_name)
        try:
            default_branch_sha = self._resolve_branch_head_sha(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=default_branch,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if not _should_treat_ref_check_as_uninitialized(exc):
                raise
            bootstrap_error_code = exc.code
            bootstrap_status_code = exc.status_code
            bootstrap_provider_message = exc.provider_message
            if ref_check_error is not None:
                bootstrap_error_code = ref_check_error.code or bootstrap_error_code
                bootstrap_status_code = ref_check_error.status_code or bootstrap_status_code
                bootstrap_provider_message = ref_check_error.provider_message or bootstrap_provider_message
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "repo_bootstrap_decision",
                    "operation_status": "evaluated",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                    "artifact_version_id": _coerce_string(artifact_version_id),
                    "business_id": _coerce_string(business_id),
                    "site_id": _coerce_string(site_id),
                    "repo_exists": True,
                    "repository_auto_create_created": (
                        bool(repository_auto_create_created)
                        if repository_auto_create_created is not None
                        else None
                    ),
                    "bootstrap_decision_source": (
                        "ref_check_uninitialized" if ref_check_error is not None else "default_branch_ref_uninitialized"
                    ),
                    "github_error_code": bootstrap_error_code,
                    "http_status_code": bootstrap_status_code,
                    "github_error_message": _sanitize_github_error_message(bootstrap_provider_message),
                    "dry_run": dry_run_value,
                    "allow_repair": allow_repair_value,
                    "remediation_mode": normalized_remediation_mode,
                    "bootstrap_allowed": bootstrap_allowed,
                    "will_attempt_bootstrap": True,
                    "git_commit": runtime_git_commit,
                    "build_version": runtime_build_version,
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.INFO,
            )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "repo_bootstrap",
                    "operation_status": "started",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "ref": normalized_ref,
                    "workflow_path": _normalize_workflow_path_for_log(workflow_path),
                    "artifact_version_id": _coerce_string(artifact_version_id),
                    "business_id": _coerce_string(business_id),
                    "site_id": _coerce_string(site_id),
                    "repo_bootstrap_required": True,
                    "repo_bootstrap_state": "uninitialized_branch",
                    "github_error_code": bootstrap_error_code,
                    "http_status_code": bootstrap_status_code,
                    "github_error_message": _sanitize_github_error_message(bootstrap_provider_message),
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.INFO,
            )
            self._bootstrap_repository_branch(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=normalized_ref,
                business_id=business_id,
                site_id=site_id,
            )
            branch_exists_after_bootstrap = self._request_json(
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
            if not isinstance(branch_exists_after_bootstrap, dict):
                raise SEOMigrationGitHubPublisherError(
                    code=_GITHUB_REASON_REPO_BOOTSTRAP_INVALID,
                    safe_message=(
                        "GitHub repository target could not be initialized for managed workflow provisioning."
                    ),
                    stage="workflow_provisioning",
                )
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "repo_bootstrap",
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
                    "repo_bootstrap_state": "initialized_empty_repo",
                },
                fallback_message="seo_migration_workflow_provisioning_operation",
                level=logging.INFO,
            )
            return
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
                blocker_code=_GITHUB_REASON_REPO_MANAGEMENT_MARKER_MISSING,
                blocker_message=(
                    "GitHub repository exists but is not marked as MBSRN-managed (mbsrn.key missing)."
                ),
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
                blocker_message=(
                    "GitHub repository management marker (mbsrn.key) is invalid for managed publish."
                ),
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
        normalized_business_id = _normalize_repo_management_id(business_id)
        normalized_site_id = _normalize_repo_management_id(site_id)
        if not normalized_business_id or not normalized_site_id:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_BOOTSTRAP_MARKER_WRITE_FAILED,
                safe_message=(
                    "GitHub repository bootstrap requires managed ownership metadata and cannot proceed."
                ),
                stage="workflow_provisioning",
            )
        baseline_files = _render_repo_baseline_files(
            repo_owner=repo_owner,
            repo_name=repo_name,
            business_id=normalized_business_id,
            site_id=normalized_site_id,
        )
        blob_sha_by_path: dict[str, str] = {}
        for baseline_path, baseline_content in baseline_files.items():
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
            blob_sha = _coerce_string((blob_payload or {}).get("sha")) if isinstance(blob_payload, dict) else None
            if not blob_sha:
                marker_write_failure = baseline_path == _MBSRN_REPO_MANAGEMENT_MARKER_PATH
                raise SEOMigrationGitHubPublisherError(
                    code=(
                        _GITHUB_REASON_REPO_BOOTSTRAP_MARKER_WRITE_FAILED
                        if marker_write_failure
                        else _GITHUB_REASON_REPO_BOOTSTRAP_INVALID
                    ),
                    safe_message=(
                        "GitHub repository bootstrap could not write the managed ownership marker."
                        if marker_write_failure
                        else "GitHub repository target could not be initialized for managed workflow provisioning."
                    ),
                    stage="workflow_provisioning",
                )
            blob_sha_by_path[baseline_path] = blob_sha

        tree_payload = self._request_json(
            method="POST",
            path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/trees",
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
        tree_sha = _coerce_string((tree_payload or {}).get("sha")) if isinstance(tree_payload, dict) else None
        if not tree_sha:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_BOOTSTRAP_INVALID,
                safe_message="GitHub repository target could not be initialized for managed workflow provisioning.",
                stage="workflow_provisioning",
            )

        commit_payload = self._request_json(
            method="POST",
            path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/commits",
            payload={
                "message": "chore(migration): initialize repository for managed publish bootstrap",
                "tree": tree_sha,
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
        commit_sha = _coerce_string((commit_payload or {}).get("sha")) if isinstance(commit_payload, dict) else None
        if not commit_sha:
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_BOOTSTRAP_INVALID,
                safe_message="GitHub repository target could not be initialized for managed workflow provisioning.",
                stage="workflow_provisioning",
            )

        try:
            self._request_json(
                method="POST",
                path=f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}/git/refs",
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
            if exc.status_code == 422:
                return
            if exc.code in {
                "github_timeout",
                "github_network_error",
                "github_temporal_failure",
            }:
                raise
            raise SEOMigrationGitHubPublisherError(
                code=_GITHUB_REASON_REPO_BOOTSTRAP_INVALID,
                safe_message="GitHub repository target could not be initialized for managed workflow provisioning.",
                status_code=exc.status_code,
                stage="workflow_provisioning",
                provider_message=exc.provider_message,
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
        if all(
            details == [_GKE_CONFIG_DETAIL_RESOLVED_FROM_ADMIN_CONFIG] for details in per_field_details
        ):
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

    def _evaluate_manifest_namespace_alignment(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        kubernetes_namespace: str,
        manifest_paths: tuple[str, ...] | list[str] | None = None,
    ) -> tuple[bool, dict[str, bool], dict[str, bool]]:
        alignment_by_path: dict[str, bool] = {}
        presence_by_path: dict[str, bool] = {}
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
            alignment_by_path[manifest_path] = _manifest_content_matches_namespace(
                manifest_path=manifest_path,
                manifest_content=manifest_content,
                kubernetes_namespace=kubernetes_namespace,
            )
        return all(alignment_by_path.values()), alignment_by_path, presence_by_path

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
                code="workflow_not_dispatchable",
                safe_message="GitHub workflow is not dispatchable for the deploy target.",
                stage="workflow_lookup",
            )
        if workflow_path:
            expected_path = _workflow_repo_path(target.workflow_id)
            if workflow_path.strip().lower() != expected_path.strip().lower():
                raise SEOMigrationGitHubPublisherError(
                    code="workflow_not_found",
                    safe_message="GitHub workflow target was not found.",
                    stage="workflow_lookup",
                )
        trigger_types = _extract_workflow_trigger_types(workflow_file_payload)
        conformance = _evaluate_workflow_conformance(
            workflow_file_payload=workflow_file_payload,
            workflow_trigger_types=trigger_types,
        )
        if conformance.conformance_status == _WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_DISPATCH_MISSING:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_dispatchable",
                safe_message="GitHub workflow is not dispatchable for the deploy target.",
                stage="workflow_lookup",
            )
        if conformance.conformance_status == _WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_PLACEHOLDER_DETECTED:
            raise SEOMigrationGitHubPublisherError(
                code="workflow_not_production_ready",
                safe_message=(
                    "GitHub workflow target is scaffold-only and not production-ready for deploy execution."
                ),
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
                    if preflight_ref_verified and preflight_workflow_verified and preflight_dispatch_ready:
                        raise SEOMigrationGitHubPublisherError(
                            code="workflow_not_dispatchable",
                            safe_message="GitHub workflow is not dispatchable for the deploy target.",
                            status_code=status_code,
                            stage="workflow_dispatch",
                        ) from exc
                    raise SEOMigrationGitHubPublisherError(
                        code="branch_not_found_or_ref_invalid",
                        safe_message="GitHub deploy ref was not found or is invalid.",
                        status_code=status_code,
                        stage="workflow_dispatch",
                    ) from exc
                if preflight_ref_verified and preflight_workflow_verified and preflight_dispatch_ready:
                    raise SEOMigrationGitHubPublisherError(
                        code="workflow_not_dispatchable",
                        safe_message="GitHub workflow is not dispatchable for the deploy target.",
                        status_code=status_code,
                        stage="workflow_dispatch",
                    ) from exc
                raise SEOMigrationGitHubPublisherError(
                    code="branch_not_found_or_ref_invalid",
                    safe_message="GitHub deploy ref was not found or is invalid.",
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
            if management_state.blocker_code:
                raise SEOMigrationGitHubPublisherError(
                    code=management_state.blocker_code,
                    safe_message=management_state.blocker_message
                    or "Repository is not managed by MBSRN and cannot be updated.",
                    stage="workflow_provisioning",
                )
            self._ensure_ref_exists(
                repo_owner=repo_owner,
                repo_name=repo_name,
                ref=branch,
                allow_repair=not dry_run,
                dry_run=dry_run,
                remediation_mode="workflow_provisioning",
                workflow_path=workflow_path,
                business_id=_normalize_repo_management_id(business_id),
                site_id=_normalize_repo_management_id(site_id),
                artifact_version_id=_coerce_string(artifact_version_id),
                repository_auto_create_created=repository_auto_create_created,
            )
        except SEOMigrationGitHubPublisherError as exc:
            if exc.code == "github_request_failed":
                exc = self._classify_workflow_provisioning_request_failed(exc=exc)
            _emit_structured_publisher_log(
                payload={
                    "event": "seo_migration_workflow_provisioning_operation",
                    "operation_kind": "ref_check",
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
            site_id=site_id,
        )
        manifest_file_payloads = _render_managed_gke_manifest_files(
            repo_owner=repo_owner,
            repo_name=repo_name,
            target_environment_key=normalized_target_environment_key,
            target_environment_source=normalized_target_environment_source,
            kubernetes_namespace=derived_namespace,
            namespace_source=namespace_source,
            preview_hostname=preview_hostname,
            namespace_isolation_defaults=normalized_namespace_isolation_defaults,
            site_id=site_id,
        )
        expected_managed_manifest_paths = _expected_managed_manifest_paths(normalized_namespace_isolation_defaults)
        managed_manifest_paths = tuple(path for path in expected_managed_manifest_paths if path in manifest_file_payloads)

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

        verified_workflow_sha = file_sha_by_path.get(workflow_path)
        namespace_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_NAMESPACE_FILE_PATH)
        deployment_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_DEPLOYMENT_FILE_PATH)
        service_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_SERVICE_FILE_PATH)
        ingress_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_INGRESS_FILE_PATH)
        resource_quota_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH)
        limit_range_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH)
        network_policy_manifest_sha = file_sha_by_path.get(_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH)
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
                    bool(resource_quota_manifest_sha)
                    if policy_expectations.get("resource_quota_expected")
                    else None
                ),
                managed_limit_range_expected=bool(policy_expectations.get("limit_range_expected")),
                managed_limit_range_present=(
                    bool(limit_range_manifest_sha)
                    if policy_expectations.get("limit_range_expected")
                    else None
                ),
                managed_network_policy_expected=bool(policy_expectations.get("network_policy_expected")),
                managed_network_policy_present=(
                    bool(network_policy_manifest_sha)
                    if policy_expectations.get("network_policy_expected")
                    else None
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
                bool(resource_quota_manifest_sha)
                if policy_expectations.get("resource_quota_expected")
                else None
            ),
            managed_limit_range_expected=bool(policy_expectations.get("limit_range_expected")),
            managed_limit_range_present=(
                bool(limit_range_manifest_sha)
                if policy_expectations.get("limit_range_expected")
                else None
            ),
            managed_network_policy_expected=bool(policy_expectations.get("network_policy_expected")),
            managed_network_policy_present=(
                bool(network_policy_manifest_sha)
                if policy_expectations.get("network_policy_expected")
                else None
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
    ) -> SEOMigrationGitHubTargetReadinessResult:
        workflow_path = _workflow_repo_path(target.workflow_id)
        self._ensure_repo_exists(repo_owner=target.repo_owner, repo_name=target.repo_name)
        self._ensure_ref_exists(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            ref=target.ref,
            allow_repair=allow_ref_repair and (not dry_run),
            dry_run=dry_run,
            remediation_mode=remediation_mode,
            workflow_path=workflow_path,
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
        workflow_content = _decode_workflow_file_content(workflow_file_payload) or ""
        managed_workflow = _MBSRN_MANAGED_WORKFLOW_MARKER in workflow_content.lower()
        workflow_namespace_aligned: bool | None = None
        manifest_namespace_aligned: bool | None = None
        namespace_model_status = _NAMESPACE_MODEL_STATUS_UNKNOWN
        if managed_workflow:
            workflow_namespace_aligned = _workflow_content_matches_namespace(
                workflow_content=workflow_content,
                kubernetes_namespace=derived_namespace,
            )
            manifest_namespace_aligned, _, manifest_presence_by_path = self._evaluate_manifest_namespace_alignment(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                ref=target.ref,
                kubernetes_namespace=derived_namespace,
                manifest_paths=expected_manifest_paths,
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
                    bool(manifest_namespace_aligned)
                    and bool(manifest_presence_by_path.get(path))
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
                if workflow_namespace_aligned and manifest_namespace_aligned
                else _NAMESPACE_MODEL_STATUS_MISALIGNED
            )
        else:
            managed_resource_quota_present = None
            managed_limit_range_present = None
            managed_network_policy_present = None
            managed_namespace_policies_aligned = None
        dispatch_service_availability = True
        dispatch_service_reason_code = "available"
        gke_config_missing_reason_codes: list[str] = []
        gke_config_presence: dict[str, bool] = {}
        gke_config_reason_code: str | None = None
        gke_config_details: dict[str, object] = {}
        if managed_workflow:
            (
                gke_config_reason_code,
                gke_config_missing_reason_codes,
                gke_config_presence,
                gke_config_details,
            ) = self._validate_managed_gke_environment_config(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                managed_gke_config=managed_gke_config,
            )
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
        if managed_workflow and namespace_model_status == _NAMESPACE_MODEL_STATUS_MISALIGNED:
            dispatch_service_availability = False
            dispatch_service_reason_code = "target_configuration_invalid"
        if managed_workflow and gke_config_reason_code is not None:
            dispatch_service_availability = False
            dispatch_service_reason_code = gke_config_reason_code
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
            path
            for path in _MBSRN_MANAGED_REPO_BASELINE_RECONCILE_PATHS
            if not presence_by_path.get(path)
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
        existing_sha = _coerce_string((existing_payload or {}).get("sha")) if isinstance(existing_payload, dict) else None
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
        existing_sha = (
            _coerce_string(existing_payload.get("sha")) if isinstance(existing_payload, dict) else None
        )
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
                        _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED
                        if is_workflow_file
                        else _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
                        "GitHub token is not authorized to write repository contents for managed workflow provisioning.",
                    ),
                    403: (
                        _GITHUB_REASON_WORKFLOW_WRITE_NOT_AUTHORIZED
                        if is_workflow_file
                        else _GITHUB_REASON_CONTENTS_WRITE_NOT_AUTHORIZED,
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
            and (
                not provider_message_lower
                or any(marker in provider_message_lower for marker in branch_state_markers)
            )
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
_MBSRN_MANAGED_MANIFEST_MARKER = f"mbsrn-managed-manifest:{_MBSRN_MANAGED_TEMPLATE_VERSION}"
_MBSRN_MANAGED_TEMPLATE_MARKER_PREFIX = "mbsrn-managed-template:"
_MBSRN_MANAGED_LABEL = "mbsrn"
_MBSRN_MANAGED_NAMESPACE_FILE_PATH = "k8s/namespace.yaml"
_MBSRN_MANAGED_DEPLOYMENT_FILE_PATH = "k8s/deployment.yaml"
_MBSRN_MANAGED_SERVICE_FILE_PATH = "k8s/service.yaml"
_MBSRN_MANAGED_INGRESS_FILE_PATH = "k8s/ingress.yaml"
_MBSRN_MANAGED_CERTIFICATE_FILE_PATH = "k8s/managedcertificate.yaml"
_MBSRN_MANAGED_FRONTEND_CONFIG_FILE_PATH = "k8s/frontendconfig.yaml"
_MBSRN_MANAGED_BACKEND_CONFIG_FILE_PATH = "k8s/backendconfig.yaml"
_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH = "k8s/resourcequota.yaml"
_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH = "k8s/limitrange.yaml"
_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH = "k8s/networkpolicy.yaml"
_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME = "mbsrn-ghcr-pull"
_MBSRN_MANAGED_SITE_WEB_IMAGE_REPO_NAME = "site-web"
_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME = "site-web-preview-cert"
_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX = "site.mbsrn.com"
_MBSRN_MANAGED_REPO_BASELINE_README_PATH = "README.md"
_MBSRN_MANAGED_REPO_BASELINE_GITIGNORE_PATH = ".gitignore"
_MBSRN_MANAGED_REPO_BASELINE_LICENSE_PATH = "LICENSE"
_MBSRN_MANAGED_REPO_BASELINE_TARGET_VISIBILITY = "private"
_MBSRN_MANAGED_REPO_BASELINE_RECONCILE_PATHS: tuple[str, ...] = (
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


def _safe_identifier_fragment(value: object, *, fallback: str, max_length: int = 80) -> str:
    raw = _coerce_string(value) or ""
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


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


def _derive_site_runtime_image_repository(*, repo_owner: object) -> str:
    owner_fragment = _safe_identifier_fragment(repo_owner, fallback="", max_length=80).strip("-")
    if not owner_fragment:
        raise SEOMigrationGitHubPublisherError(
            code="runtime_image_repository_invalid",
            safe_message="Managed site runtime image repository could not be derived from target repository owner.",
            stage="workflow_provisioning",
        )
    return f"ghcr.io/{owner_fragment}/{_MBSRN_MANAGED_SITE_WEB_IMAGE_REPO_NAME}"


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
    site_runtime_image_repository = _derive_site_runtime_image_repository(repo_owner=repo_owner)
    normalized_site_fragment = _safe_identifier_fragment(site_id, fallback="workspace")
    normalized_namespace = _safe_identifier_fragment(kubernetes_namespace, fallback=normalized_repo_fragment, max_length=63)
    normalized_namespace_source = _safe_identifier_fragment(namespace_source, fallback="repo-name", max_length=40)
    normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower()
    normalized_name = f"MBSRN Deploy {normalized_repo_fragment}"
    return (
        f"# {_MBSRN_MANAGED_WORKFLOW_MARKER}\n"
        f"name: {normalized_name}\n"
        "\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "  packages: read\n"
        "  id-token: write\n"
        "\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    outputs:\n"
        "      live_url: ${{ steps.resolve_live_url.outputs.live_url }}\n"
        "      resolved_live_url: ${{ steps.resolve_live_url.outputs.resolved_live_url }}\n"
        "      deployed_url: ${{ steps.resolve_live_url.outputs.deployed_url }}\n"
        "      site_runtime_image_reference: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}\n"
        "      site_runtime_image_selection_mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}\n"
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
        f"      SITE_WEB_IMAGE_REPOSITORY: {site_runtime_image_repository}\n"
        "      SITE_WEB_IMAGE_TAG: ${{ vars.MBSRN_SITE_WEB_IMAGE_TAG || vars.SITE_WEB_IMAGE_TAG || secrets.MBSRN_SITE_WEB_IMAGE_TAG || secrets.SITE_WEB_IMAGE_TAG || '' }}\n"
        f"      GKE_CLUSTER_NAME: {rendered_cluster_name}\n"
        f"      GKE_CLUSTER_LOCATION: {rendered_cluster_location}\n"
        f"      GKE_PROJECT_ID: {rendered_project_id}\n"
        "    steps:\n"
        "      - name: Checkout repository\n"
        "        uses: actions/checkout@v4\n"
        "      - name: Validate GCP credentials\n"
        "        run: |\n"
        "          if [ -z \"${{ secrets.GCP_DEPLOY_KEY }}\" ]; then\n"
        "            echo \"Missing GCP_DEPLOY_KEY secret\"\n"
        "            exit 1\n"
        "          fi\n"
        "      - name: Validate GKE environment config\n"
        "        run: |\n"
        "          if [ -z \"$GKE_CLUSTER_NAME\" ]; then\n"
        "            echo \"Missing managed GKE cluster name (admin config or legacy repo fallback).\"\n"
        "            exit 1\n"
        "          fi\n"
        "          if [ -z \"$GKE_CLUSTER_LOCATION\" ]; then\n"
        "            echo \"Missing managed GKE cluster location (admin config or legacy repo fallback).\"\n"
        "            exit 1\n"
        "          fi\n"
        "          if [ -z \"$GKE_PROJECT_ID\" ]; then\n"
        "            echo \"Missing managed GKE project id (admin config or legacy repo fallback).\"\n"
        "            exit 1\n"
        "          fi\n"
        "      - name: Authenticate to GCP\n"
        "        uses: google-github-actions/auth@v2\n"
        "        with:\n"
        "          credentials_json: ${{ secrets.GCP_DEPLOY_KEY }}\n"
        "          create_credentials_file: true\n"
        "          export_environment_variables: true\n"
        "      - name: Get GKE credentials\n"
        "        uses: google-github-actions/get-gke-credentials@v2\n"
        "        with:\n"
        "          cluster_name: ${{ env.GKE_CLUSTER_NAME }}\n"
        "          location: ${{ env.GKE_CLUSTER_LOCATION }}\n"
        "          project_id: ${{ env.GKE_PROJECT_ID }}\n"
        "      - name: Ensure namespace exists\n"
        "        run: kubectl apply -f k8s/namespace.yaml\n"
        "      - name: Ensure GHCR image pull secret\n"
        "        env:\n"
        "          GHCR_PULL_USERNAME: ${{ github.actor }}\n"
        "          GHCR_PULL_TOKEN: ${{ github.token }}\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          if [ -z \"$GHCR_PULL_USERNAME\" ] || [ -z \"$GHCR_PULL_TOKEN\" ]; then\n"
        "            echo \"Missing GitHub workflow token context for GHCR pull secret provisioning.\"\n"
        "            exit 1\n"
        "          fi\n"
        "          kubectl create secret docker-registry "
        f"{_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME} "
        "            --namespace \"$K8S_NAMESPACE\" "
        "            --docker-server=ghcr.io "
        "            --docker-username=\"$GHCR_PULL_USERNAME\" "
        "            --docker-password=\"$GHCR_PULL_TOKEN\" "
        "            --dry-run=client -o yaml | kubectl apply -f -\n"
        "      - name: Reset stale site-web deployment\n"
        "        run: |\n"
        "          echo \"Resetting deployment to eliminate stale image references.\"\n"
        "          kubectl delete deployment site-web --namespace \"$K8S_NAMESPACE\" --ignore-not-found\n"
        "      - name: Apply managed manifests\n"
        "        run: |\n"
        "          kubectl apply -f k8s/deployment.yaml\n"
        "          kubectl apply -f k8s/\n"
        "      - name: Resolve managed site runtime image\n"
        "        id: resolve_site_runtime_image\n"
        "        env:\n"
        "          GHCR_PULL_USERNAME: ${{ github.actor }}\n"
        "          GHCR_PULL_TOKEN: ${{ github.token }}\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          selected_mode=\"fallback_latest\"\n"
        "          selected_image=\"${SITE_WEB_IMAGE_REPOSITORY}:latest\"\n"
        "          normalized_tag=\"$(echo \"${SITE_WEB_IMAGE_TAG:-}\" | tr -d '[:space:]')\"\n"
        "          if [ -n \"$normalized_tag\" ] && [ \"$normalized_tag\" != \"latest\" ]; then\n"
        "            if echo \"$normalized_tag\" | grep -Eq '^[A-Fa-f0-9]{7,64}$'; then\n"
        "              if [ -n \"${GHCR_PULL_USERNAME:-}\" ] && [ -n \"${GHCR_PULL_TOKEN:-}\" ]; then\n"
        "                echo \"$GHCR_PULL_TOKEN\" | docker login ghcr.io -u \"$GHCR_PULL_USERNAME\" --password-stdin >/dev/null 2>&1 || true\n"
        "              fi\n"
        "              candidate_image=\"${SITE_WEB_IMAGE_REPOSITORY}:${normalized_tag}\"\n"
        "              if docker manifest inspect \"$candidate_image\" >/dev/null 2>&1; then\n"
        "                selected_image=\"$candidate_image\"\n"
        "                selected_mode=\"immutable_sha\"\n"
        "              else\n"
        "                echo \"Configured SITE_WEB_IMAGE_TAG '$normalized_tag' is unavailable; falling back to latest.\"\n"
        "              fi\n"
        "            else\n"
        "              echo \"Configured SITE_WEB_IMAGE_TAG '$normalized_tag' is not a SHA-like tag; falling back to latest.\"\n"
        "            fi\n"
        "          fi\n"
        "          echo \"Managed site runtime image selected: ${selected_image} (mode=${selected_mode})\"\n"
        "          kubectl set image deployment/site-web site-web=\"${selected_image}\" --namespace \"$K8S_NAMESPACE\"\n"
        "          {\n"
        "            echo \"site_runtime_image_reference=${selected_image}\"\n"
        "            echo \"site_runtime_image_selection_mode=${selected_mode}\"\n"
        "          } >> \"$GITHUB_OUTPUT\"\n"
        "      - name: Verify rollout\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          if ! kubectl rollout status deployment/site-web --namespace \"$K8S_NAMESPACE\" --timeout=180s; then\n"
        "            echo \"site-web rollout timed out in namespace $K8S_NAMESPACE; collecting bounded diagnostics.\"\n"
        "            kubectl get deployment site-web --namespace \"$K8S_NAMESPACE\" -o wide || true\n"
        "            kubectl get rs --namespace \"$K8S_NAMESPACE\" -o wide || true\n"
        "            kubectl get pods --namespace \"$K8S_NAMESPACE\" -o wide || true\n"
        "            deployment_describe_output=\"$(mktemp)\"\n"
        "            kubectl describe deployment site-web --namespace \"$K8S_NAMESPACE\" > \"$deployment_describe_output\" 2>&1 || true\n"
        "            cat \"$deployment_describe_output\"\n"
        "            describe_pods_output=\"$(mktemp)\"\n"
        "            kubectl describe pods --namespace \"$K8S_NAMESPACE\" -l app.kubernetes.io/name=site-web > \"$describe_pods_output\" 2>&1 || true\n"
        "            cat \"$describe_pods_output\"\n"
        "            image_pull_detected=false\n"
        "            if grep -qiE 'ImagePullBackOff|ErrImagePull|pull access denied|manifest unknown|Failed to pull image' \"$describe_pods_output\"; then\n"
        "              image_pull_detected=true\n"
        "              echo \"Likely rollout blocker: image pull failure.\"\n"
        "            fi\n"
        "            if grep -qiE 'failed to fetch anonymous token|403[[:space:]]+Forbidden|unauthorized|authentication required' \"$describe_pods_output\"; then\n"
        "              image_pull_detected=true\n"
        "              echo \"Likely rollout blocker: private registry authentication failure.\"\n"
        "            fi\n"
        "            if grep -qiE 'manifest unknown|name unknown|[Ii]magePullBackOff.*not found|[Ff]ailed to pull image.*not found|ghcr\\.io/.+:.*not found' \"$describe_pods_output\"; then\n"
        "              image_pull_detected=true\n"
        "              echo \"Likely rollout blocker: container image not found in registry.\"\n"
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
        "            if [ \"$image_pull_detected\" = false ] && [ \"$container_started_evidence\" = true ] && [ \"$crash_direct_evidence\" = true ]; then\n"
        "              echo \"Likely rollout blocker: pod crash/failing container startup.\"\n"
        "            fi\n"
        "            if [ \"$image_pull_detected\" = false ] && [ \"$container_started_evidence\" = true ] && [ \"$probe_direct_evidence\" = true ]; then\n"
        "              echo \"Likely rollout blocker: readiness/liveness probe failure.\"\n"
        "            fi\n"
        "            if grep -qiE 'CreateContainerConfigError|CreateContainerError|secret \".*\" not found|configmap \".*\" not found' \"$describe_pods_output\"; then\n"
        "              echo \"Likely rollout blocker: config or secret reference failure.\"\n"
        "            fi\n"
        "            if grep -qiE 'exceeded quota|FailedCreate|forbidden: exceeded quota|requested: requests\\.(memory|cpu)|limited: requests\\.(memory|cpu)|limited: limits\\.' \"$deployment_describe_output\" \"$describe_pods_output\"; then\n"
        "              echo \"Likely rollout blocker: namespace ResourceQuota rejection.\"\n"
        "            fi\n"
        "            if grep -qiE 'FailedScheduling|Insufficient|didn.t match Pod.s node affinity|taint|node.s had' \"$describe_pods_output\"; then\n"
        "              echo \"Likely rollout blocker: scheduling or resource availability issue.\"\n"
        "            fi\n"
        "            rm -f \"$deployment_describe_output\"\n"
        "            rm -f \"$describe_pods_output\"\n"
        "            recent_pods=\"$(kubectl get pods --namespace \"$K8S_NAMESPACE\" -l app.kubernetes.io/name=site-web --sort-by=.metadata.creationTimestamp -o name 2>/dev/null | tail -n 3)\"\n"
        "            if [ -n \"$recent_pods\" ]; then\n"
        "              for pod in $recent_pods; do\n"
        "                echo \"--- recent logs: $pod ---\"\n"
        "                kubectl logs --namespace \"$K8S_NAMESPACE\" \"$pod\" -c site-web --tail=200 || kubectl logs --namespace \"$K8S_NAMESPACE\" \"$pod\" --tail=200 || true\n"
        "              done\n"
        "            fi\n"
        "            exit 1\n"
        "          fi\n"
        "      - name: Verify service and ingress\n"
        "        run: |\n"
        "          kubectl get service site-web --namespace \"$K8S_NAMESPACE\"\n"
        "          kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\"\n"
        "      - name: Resolve live URL from ingress status\n"
        "        id: resolve_live_url\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          max_attempts=40\n"
        "          sleep_seconds=15\n"
        "          wait_seconds=$((max_attempts * sleep_seconds))\n"
        "          echo \"Waiting up to ${wait_seconds}s for ingress external address assignment in namespace $K8S_NAMESPACE.\"\n"
        "          ingress_host=\"\"\n"
        "          ingress_ip=\"\"\n"
        "          ingress_spec_host=\"\"\n"
        "          preview_host=\"$MBSRN_PREVIEW_HOSTNAME\"\n"
        "          for attempt in $(seq 1 \"$max_attempts\"); do\n"
        "            ingress_host=\"$(kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)\"\n"
        "            ingress_ip=\"$(kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)\"\n"
        "            ingress_spec_host=\"$(kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\" -o jsonpath='{.spec.rules[0].host}' 2>/dev/null || true)\"\n"
        "            if [ -n \"$ingress_host\" ] || [ -n \"$ingress_ip\" ]; then\n"
        "              echo \"Ingress external address resolved on attempt ${attempt}/${max_attempts}.\"\n"
        "              break\n"
        "            fi\n"
        "            if [ \"$attempt\" -lt \"$max_attempts\" ]; then\n"
        "              echo \"Ingress external address not ready yet (attempt ${attempt}/${max_attempts}); sleeping ${sleep_seconds}s.\"\n"
        "              sleep \"$sleep_seconds\"\n"
        "            fi\n"
        "          done\n"
        "          live_url=\"\"\n"
        "          if [ -z \"$preview_host\" ] && [ -n \"$ingress_spec_host\" ]; then\n"
        "            preview_host=\"$ingress_spec_host\"\n"
        "          fi\n"
        "          if [ -n \"$preview_host\" ]; then\n"
        "            live_url=\"https://$preview_host\"\n"
        "          elif [ -n \"$ingress_host\" ]; then\n"
        "            live_url=\"https://$ingress_host\"\n"
        "          elif [ -n \"$ingress_ip\" ]; then\n"
        "            live_url=\"http://$ingress_ip\"\n"
        "          fi\n"
        "          if [ -z \"$live_url\" ]; then\n"
        "            echo \"Ingress created but external address is not assigned yet for namespace $K8S_NAMESPACE.\"\n"
        "            echo \"Likely rollout blocker: ingress/load balancer provisioning still in progress.\"\n"
        "            echo \"This may take several minutes on GKE.\"\n"
        "            echo \"deploy_runtime_reason_code=ingress_address_pending\"\n"
        "            echo \"deploy_runtime_reason_message=Ingress created but external address not yet assigned.\"\n"
        "            kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\" -o wide || true\n"
        "            kubectl describe ingress site-web --namespace \"$K8S_NAMESPACE\" || true\n"
        "            kubectl get service site-web --namespace \"$K8S_NAMESPACE\" -o wide || true\n"
        "            kubectl get endpoints site-web --namespace \"$K8S_NAMESPACE\" -o wide || true\n"
        "            kubectl get managedcertificate --namespace \"$K8S_NAMESPACE\" || true\n"
        "            kubectl get frontendconfig --namespace \"$K8S_NAMESPACE\" || true\n"
        "            exit 1\n"
        "          fi\n"
        "          {\n"
        "            echo \"live_url=$live_url\"\n"
        "            echo \"resolved_live_url=$live_url\"\n"
        "            echo \"deployed_url=$live_url\"\n"
        "          } >> \"$GITHUB_OUTPUT\"\n"
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
        "          echo \"Preview hostname: $MBSRN_PREVIEW_HOSTNAME\"\n"
        "          echo \"Site runtime image: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}\"\n"
        "          echo \"Site runtime image selection mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}\"\n"
    )


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
) -> dict[str, str]:
    site_runtime_image_repository = _derive_site_runtime_image_repository(repo_owner=repo_owner)
    repo_owner_fragment = _safe_identifier_fragment(repo_owner, fallback="mbsrn", max_length=40)
    repo_fragment = _safe_identifier_fragment(repo_name, fallback="site", max_length=40)
    env_key = _safe_identifier_fragment(target_environment_key, fallback="gke-prod", max_length=40)
    env_source = _safe_identifier_fragment(target_environment_source, fallback="admin-config", max_length=40)
    namespace = _safe_identifier_fragment(kubernetes_namespace, fallback=repo_fragment, max_length=63)
    namespace_origin = _safe_identifier_fragment(namespace_source, fallback="repo-name", max_length=40)
    site_fragment = _safe_identifier_fragment(site_id, fallback="workspace", max_length=60)
    normalized_preview_hostname = (_coerce_string(preview_hostname) or "").strip().lower()

    labels = (
        f"    app.kubernetes.io/managed-by: {_MBSRN_MANAGED_LABEL}\n"
        f"    app.kubernetes.io/name: site-web\n"
        f"    mbsrn.io/repo: {repo_fragment}\n"
        f"    mbsrn.io/environment-key: {env_key}\n"
        f"    mbsrn.io/environment-source: {env_source}\n"
        f"    mbsrn.io/site-id: {site_fragment}\n"
        f"    mbsrn.io/namespace-source: {namespace_origin}\n"
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
        "      imagePullSecrets:\n"
        f"        - name: {_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME}\n"
        "      containers:\n"
        "        - name: site-web\n"
        f"          image: {image_repository}\n"
        "          imagePullPolicy: IfNotPresent\n"
        "          env:\n"
        "            - name: HOSTNAME\n"
        "              value: \"0.0.0.0\"\n"
        "            - name: PORT\n"
        "              value: \"8080\"\n"
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
        "    cloud.google.com/backend-config: '{\"default\": \"site-web-backend-config\"}'\n"
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
        f"    networking.gke.io/managed-certificates: {_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME}\n"
        "    networking.gke.io/v1beta1.FrontendConfig: site-web-frontend-config\n"
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
        f"  name: {_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME}\n"
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
        "  name: site-web-frontend-config\n"
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
        "  name: site-web-backend-config\n"
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
    if isinstance(resource_quota_defaults, dict) and _coerce_bool(resource_quota_defaults.get("enabled"), default=False):
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
        mode = _safe_identifier_fragment(network_policy_defaults.get("mode"), fallback="default-deny-ingress", max_length=60)
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
        )
        manifests[_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH] = network_policy_manifest
    return manifests


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
        if "authenticate to gcp" in step_name or "google-github-actions/auth" in step_name:
            return "gcp_auth_failed", "gcp_auth"
        if "get gke credentials" in step_name or "get-gke-credentials" in step_name:
            return "gke_credentials_failed", "cluster_credentials"
        if "apply managed manifests" in step_name or "kubectl apply" in step_name:
            return "kubectl_apply_failed", "manifest_apply"
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


def _classify_rollout_blocker_hints_from_describe_outputs(
    *,
    deployment_describe_output: str | None,
    pods_describe_output: str | None,
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
    if _has(r"ImagePullBackOff|ErrImagePull|pull access denied|manifest unknown|Failed to pull image", pods_text):
        image_pull_detected = True
        hints.append("image_pull_failure")
    if _has(r"failed to fetch anonymous token|403\s+Forbidden|unauthorized|authentication required", pods_text):
        image_pull_detected = True
        hints.append("private_registry_auth_failure")
    if _has(r"manifest unknown|name unknown|[Ii]magePullBackOff.*not found|[Ff]ailed to pull image.*not found|ghcr\.io/.+:.*not found", pods_text):
        image_pull_detected = True
        hints.append("container_image_not_found")

    if _has(r"CreateContainerConfigError|CreateContainerError|secret \".*\" not found|configmap \".*\" not found", pods_text):
        hints.append("config_or_secret_reference_failure")

    if _has(
        r"exceeded quota|FailedCreate|forbidden: exceeded quota|requested: requests\.(memory|cpu)|limited: requests\.(memory|cpu)|limited: limits\.",
        deployment_text,
        pods_text,
    ):
        hints.append("resource_quota_rejection")

    if _has(r"FailedScheduling|Insufficient|didn.t match Pod.s node affinity|taint|node.s had", pods_text):
        hints.append("scheduling_or_resource_issue")

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

    return tuple(hints)


_WORKFLOW_CONFORMANCE_STATUS_CONFORMANT = "conformant"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_MISSING = "workflow_missing"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_UNREADABLE = "workflow_unreadable"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_DISPATCH_MISSING = "workflow_dispatch_missing"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_PLACEHOLDER_DETECTED = "workflow_placeholder_detected"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_CONTRACT_INCOMPLETE = "workflow_contract_incomplete"
_WORKFLOW_CONFORMANCE_STATUS_WORKFLOW_CONFORMANCE_UNKNOWN = "workflow_conformance_unknown"

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
    workflow_id_normalized = (str(workflow_id or "").strip().lower() or "deploy-www-prod.yml")
    has_template_marker = _MBSRN_MANAGED_TEMPLATE_MARKER_PREFIX in lowered
    has_placeholder_step = "placeholder deploy" in lowered
    has_customize_marker = "customize before production rollout" in lowered
    has_mode_scaffold_marker = "provisioned in mode" in lowered
    has_not_implemented_marker = "deploy step not yet implemented" in lowered
    has_workflow_provision_message = (
        f"deploy workflow ({workflow_id_normalized}) provisioned" in lowered
        or ("deploy workflow (" in lowered and "provisioned" in lowered)
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
    try:
        message = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    except TypeError:
        message = fallback_message
    _LOGGER.log(level, message)


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
        "\"License\" shall mean the terms and conditions for use, reproduction,\n"
        "and distribution as defined by Sections 1 through 9 of this document.\n"
        "\n"
        "\"Licensor\" shall mean the copyright owner or entity authorized by\n"
        "the copyright owner that is granting the License.\n"
        "\n"
        "\"Legal Entity\" shall mean the union of the acting entity and all\n"
        "other entities that control, are controlled by, or are under common\n"
        "control with that entity. For the purposes of this definition,\n"
        "\"control\" means (i) the power, direct or indirect, to cause the\n"
        "direction or management of such entity, whether by contract or\n"
        "otherwise, or (ii) ownership of fifty percent (50%) or more of the\n"
        "outstanding shares, or (iii) beneficial ownership of such entity.\n"
        "\n"
        "\"You\" (or \"Your\") shall mean an individual or Legal Entity\n"
        "exercising permissions granted by this License.\n"
        "\n"
        "\"Source\" form shall mean the preferred form for making modifications,\n"
        "including but not limited to software source code, documentation\n"
        "source, and configuration files.\n"
        "\n"
        "\"Object\" form shall mean any form resulting from mechanical\n"
        "transformation or translation of a Source form, including but\n"
        "not limited to compiled object code, generated documentation,\n"
        "and conversions to other media types.\n"
        "\n"
        "\"Work\" shall mean the work of authorship, whether in Source or\n"
        "Object form, made available under the License, as indicated by a\n"
        "copyright notice that is included in or attached to the work\n"
        "(an example is provided in the Appendix below).\n"
        "\n"
        "\"Derivative Works\" shall mean any work, whether in Source or Object\n"
        "form, that is based on (or derived from) the Work and for which the\n"
        "editorial revisions, annotations, elaborations, or other modifications\n"
        "represent, as a whole, an original work of authorship. For the purposes\n"
        "of this License, Derivative Works shall not include works that remain\n"
        "separable from, or merely link (or bind by name) to the interfaces of,\n"
        "the Work and Derivative Works thereof.\n"
        "\n"
        "\"Contribution\" shall mean any work of authorship, including\n"
        "the original version of the Work and any modifications or additions\n"
        "to that Work or Derivative Works thereof, that is intentionally\n"
        "submitted to Licensor for inclusion in the Work by the copyright owner\n"
        "or by an individual or Legal Entity authorized to submit on behalf of\n"
        "the copyright owner. For the purposes of this definition, \"submitted\"\n"
        "means any form of electronic, verbal, or written communication sent to\n"
        "the Licensor or its representatives, including but not limited to\n"
        "communication on electronic mailing lists, source code control systems,\n"
        "and issue tracking systems that are managed by, or on behalf of, the\n"
        "Licensor for the purpose of discussing and improving the Work, but\n"
        "excluding communication that is conspicuously marked or otherwise\n"
        "designated in writing by the copyright owner as \"Not a Contribution.\"\n"
        "\n"
        "\"Contributor\" shall mean Licensor and any individual or Legal Entity\n"
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
        "(d) If the Work includes a \"NOTICE\" text file as part of its\n"
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
        "Contributor provides its Contributions) on an \"AS IS\" BASIS,\n"
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


def _render_repo_management_marker_content(*, business_id: str, site_id: str) -> str:
    payload = {
        "version": 1,
        "created_by": "mbsrn",
        "business_id": business_id,
        "site_id": site_id,
    }
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
        return "workflow_numeric_id"
    if normalized.lower().startswith(".github/workflows/") or normalized.lower().startswith("github/workflows/"):
        return "workflow_file_path"
    if "/" in normalized:
        return "workflow_file_path"
    if normalized.lower().endswith(".yml") or normalized.lower().endswith(".yaml"):
        return "workflow_id"
    return "workflow_id"

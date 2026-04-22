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

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SEOMigrationGitHubPublishTarget:
    repo_owner: str
    repo_name: str
    branch: str
    artifact_root: str


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

    def __str__(self) -> str:
        return self.safe_message


class SEOMigrationGitHubPublisher:
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
    ) -> SEOMigrationGitHubWorkflowProvisionResult:
        del (
            deploy_workflow_mode,
            target_environment_key,
            target_environment_source,
            managed_gke_config,
            namespace_isolation_defaults,
            site_id,
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

        commit_shas: list[str] = []
        total_bytes = 0
        for file_item in files:
            total_bytes += len(file_item.content.encode("utf-8"))
            final_path = _join_repo_path(target.artifact_root, file_item.path)
            existing_sha = self._fetch_existing_sha(
                repo_owner=target.repo_owner,
                repo_name=target.repo_name,
                branch=target.branch,
                path=final_path,
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
            response_payload = self._request_json(
                method="PUT",
                path=(
                    f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                    f"/contents/{urllib.parse.quote(final_path, safe='/')}"
                ),
                payload=payload,
            )
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
            if allow_404 and status_code == 404:
                return None
            if status_error_map and status_code in status_error_map:
                code, safe_message = status_error_map[status_code]
                raise SEOMigrationGitHubPublisherError(
                    code=code,
                    safe_message=safe_message,
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            if status_code in {401, 403}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_auth_failed",
                    safe_message="GitHub publish/deploy authentication failed.",
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            if status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code="github_target_not_found",
                    safe_message="GitHub repository or workflow target was not found.",
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            if status_code in {408, 429, 500, 502, 503, 504}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_temporal_failure",
                    safe_message="GitHub publish/deploy request failed temporarily.",
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="GitHub publish/deploy request failed.",
                status_code=status_code,
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

    def _ensure_repo_exists(self, *, repo_owner: str, repo_name: str) -> None:
        self._request_json(
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

    def _ensure_ref_exists(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        allow_repair: bool,
    ) -> None:
        normalized_ref = str(ref or "").strip()
        if not normalized_ref:
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
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
            },
            error_stage="ref_lookup",
        )
        if isinstance(branch_exists, dict):
            return
        if not allow_repair:
            raise SEOMigrationGitHubPublisherError(
                code="branch_not_found_or_ref_invalid",
                safe_message="GitHub deploy ref was not found or is invalid.",
                stage="ref_lookup",
            )
        default_branch = self._resolve_default_branch(repo_owner=repo_owner, repo_name=repo_name)
        default_branch_sha = self._resolve_branch_head_sha(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=default_branch,
        )
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
                    "branch_not_found_or_ref_invalid",
                    "GitHub deploy ref was not found or is invalid.",
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
        self._ensure_repo_exists(repo_owner=repo_owner, repo_name=repo_name)
        self._ensure_ref_exists(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=branch,
            allow_repair=not dry_run,
        )
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
        response_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
        )
        if isinstance(response_payload, dict):
            return response_payload
        return None

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
        response_payload = self._request_json(
            method="PUT",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/contents/{urllib.parse.quote(path, safe='/')}"
            ),
            payload=payload,
        )
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
        del commit_sha
        return True, verified_sha, workflow_outcome

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
            if allow_404 and status_code == 404:
                return None
            if status_error_map and status_code in status_error_map:
                code, safe_message = status_error_map[status_code]
                raise SEOMigrationGitHubPublisherError(
                    code=code,
                    safe_message=safe_message,
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            if status_code in {401, 403}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_auth_failed",
                    safe_message="GitHub publish/deploy authentication failed.",
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            if status_code == 404:
                raise SEOMigrationGitHubPublisherError(
                    code="github_target_not_found",
                    safe_message="GitHub repository or workflow target was not found.",
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            if status_code in {408, 429, 500, 502, 503, 504}:
                raise SEOMigrationGitHubPublisherError(
                    code="github_temporal_failure",
                    safe_message="GitHub publish/deploy request failed temporarily.",
                    status_code=status_code,
                    stage=error_stage,
                ) from exc
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="GitHub publish/deploy request failed.",
                status_code=status_code,
                stage=error_stage,
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
_MBSRN_MANAGED_RESOURCE_QUOTA_FILE_PATH = "k8s/resourcequota.yaml"
_MBSRN_MANAGED_LIMIT_RANGE_FILE_PATH = "k8s/limitrange.yaml"
_MBSRN_MANAGED_NETWORK_POLICY_FILE_PATH = "k8s/networkpolicy.yaml"
_MBSRN_MANAGED_IMAGE_PULL_SECRET_NAME = "mbsrn-ghcr-pull"
_MBSRN_MANAGED_SITE_WEB_IMAGE_REPO_NAME = "site-web"
_MBSRN_MANAGED_PREVIEW_CERTIFICATE_NAME = "site-web-preview-cert"
_MBSRN_MANAGED_PREVIEW_DOMAIN_SUFFIX = "site.mbsrn.com"
_MBSRN_MANAGED_CORE_MANIFEST_PATHS: tuple[str, ...] = (
    _MBSRN_MANAGED_NAMESPACE_FILE_PATH,
    _MBSRN_MANAGED_DEPLOYMENT_FILE_PATH,
    _MBSRN_MANAGED_SERVICE_FILE_PATH,
    _MBSRN_MANAGED_INGRESS_FILE_PATH,
    _MBSRN_MANAGED_CERTIFICATE_FILE_PATH,
    _MBSRN_MANAGED_FRONTEND_CONFIG_FILE_PATH,
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
    manifests: dict[str, str] = {
        _MBSRN_MANAGED_NAMESPACE_FILE_PATH: namespace_manifest,
        _MBSRN_MANAGED_DEPLOYMENT_FILE_PATH: deployment_manifest,
        _MBSRN_MANAGED_SERVICE_FILE_PATH: service_manifest,
        _MBSRN_MANAGED_INGRESS_FILE_PATH: ingress_manifest,
        _MBSRN_MANAGED_CERTIFICATE_FILE_PATH: managed_certificate_manifest,
        _MBSRN_MANAGED_FRONTEND_CONFIG_FILE_PATH: frontend_config_manifest,
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

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from app.core.time import utc_now


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

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
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
        site_id: str | None = None,
    ) -> SEOMigrationGitHubWorkflowProvisionResult:
        del deploy_workflow_mode, target_environment_key, target_environment_source, site_id
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
    ) -> SEOMigrationGitHubTargetReadinessResult:
        del allow_ref_repair, allow_workflow_repair, dry_run
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

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
    ) -> SEOMigrationGitHubDeployResult:
        del target, dry_run
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

    def check_deploy_target_readiness(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        allow_ref_repair: bool = False,
        allow_workflow_repair: bool = False,
        dry_run: bool = False,
        remediation_mode: str = "none",
    ) -> SEOMigrationGitHubTargetReadinessResult:
        del target, allow_ref_repair, allow_workflow_repair, dry_run, remediation_mode
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

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
    ) -> SEOMigrationGitHubDeployResult:
        dispatched_at = utc_now().isoformat()
        workflow_output: dict[str, str] | None = None
        workflow_run_id: int | None = None
        workflow_run_status: str | None = None
        workflow_run_conclusion: str | None = None
        readiness_result: SEOMigrationGitHubTargetReadinessResult | None = None
        if not dry_run:
            readiness_result = self.check_deploy_target_readiness(
                target=target,
                allow_ref_repair=False,
                allow_workflow_repair=False,
                dry_run=False,
                remediation_mode="none",
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
        if run_status == "completed" and run_conclusion == "success":
            live_url = self._resolve_live_url_from_workflow_completion_metadata(
                target=target,
                workflow_run_id=run_id,
                dispatched_at=dispatched_at_candidate,
            )
            if live_url:
                workflow_output = {"live_url": live_url}

        return SEOMigrationGitHubDeployRunStatusResult(
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            workflow_run_id=run_id,
            workflow_run_status=run_status,
            workflow_run_conclusion=run_conclusion,
            workflow_output=workflow_output,
            refreshed_at=refreshed_at,
        )

    def _try_capture_post_dispatch_workflow_result(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dispatched_at: str,
    ) -> tuple[int | None, str | None, str | None, dict[str, str] | None]:
        try:
            run_payload = self._find_recent_workflow_run_for_dispatch(
                target=target,
                dispatched_at=dispatched_at,
            )
        except SEOMigrationGitHubPublisherError:
            return None, None, None, None

        if not isinstance(run_payload, dict):
            return None, None, None, None

        workflow_run_id = _coerce_int(run_payload.get("id"))
        workflow_run_status = _coerce_string(run_payload.get("status"))
        workflow_run_conclusion = _coerce_string(run_payload.get("conclusion"))

        workflow_output: dict[str, str] | None = None
        if workflow_run_status == "completed" and workflow_run_conclusion == "success":
            live_url = self._resolve_live_url_from_workflow_completion_metadata(
                target=target,
                workflow_run_id=workflow_run_id,
                dispatched_at=dispatched_at,
            )
            if live_url:
                workflow_output = {"live_url": live_url}

        return workflow_run_id, workflow_run_status, workflow_run_conclusion, workflow_output

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

        for attempt in range(3):
            runs_response = self._request_json(
                method="GET",
                path=(
                    f"/repos/{urllib.parse.quote(target.repo_owner)}/{urllib.parse.quote(target.repo_name)}"
                    f"/actions/workflows/{urllib.parse.quote(target.workflow_id, safe='')}/runs"
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
        workflow_path = _workflow_repo_path(normalized_workflow_id)
        self._ensure_repo_exists(repo_owner=repo_owner, repo_name=repo_name)
        self._ensure_ref_exists(
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=branch,
            allow_repair=not dry_run,
        )
        existing_sha = self._fetch_existing_sha(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=workflow_path,
        )
        if existing_sha:
            return SEOMigrationGitHubWorkflowProvisionResult(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                workflow_id=normalized_workflow_id,
                workflow_path=workflow_path,
                provisioned=False,
                commit_sha=existing_sha,
                deploy_workflow_mode=normalized_workflow_mode,
                target_environment_key=normalized_target_environment_key,
                target_environment_source=normalized_target_environment_source,
            )
        if dry_run:
            return SEOMigrationGitHubWorkflowProvisionResult(
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                workflow_id=normalized_workflow_id,
                workflow_path=workflow_path,
                provisioned=False,
                commit_sha=None,
                deploy_workflow_mode=normalized_workflow_mode,
                target_environment_key=normalized_target_environment_key,
                target_environment_source=normalized_target_environment_source,
            )

        encoded_content = base64.b64encode(
            _render_managed_deploy_workflow_yaml(
                workflow_id=normalized_workflow_id,
                repo_owner=repo_owner,
                repo_name=repo_name,
                branch=branch,
                deploy_workflow_mode=normalized_workflow_mode,
                target_environment_key=normalized_target_environment_key,
                target_environment_source=normalized_target_environment_source,
                site_id=site_id,
            ).encode("utf-8")
        ).decode("ascii")
        response_payload = self._request_json(
            method="PUT",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/contents/{urllib.parse.quote(workflow_path, safe='/')}"
            ),
            payload={
                "message": f"chore(migration): provision deploy workflow {normalized_workflow_id}",
                "content": encoded_content,
                "branch": branch,
                "committer": {
                    "name": self.committer_name,
                    "email": self.committer_email,
                },
            },
        )
        commit_sha: str | None = None
        if isinstance(response_payload, dict):
            commit_payload = response_payload.get("commit")
            if isinstance(commit_payload, dict):
                candidate = str(commit_payload.get("sha") or "").strip()
                if candidate:
                    commit_sha = candidate
        verified_sha = self._fetch_existing_sha(
            repo_owner=repo_owner,
            repo_name=repo_name,
            branch=branch,
            path=workflow_path,
        )
        if not verified_sha:
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
            provisioned=True,
            commit_sha=verified_sha or commit_sha,
            deploy_workflow_mode=normalized_workflow_mode,
            target_environment_key=normalized_target_environment_key,
            target_environment_source=normalized_target_environment_source,
        )

    def check_deploy_target_readiness(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        allow_ref_repair: bool = False,
        allow_workflow_repair: bool = False,
        dry_run: bool = False,
        remediation_mode: str = "none",
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
            dispatch_service_availability=True,
            dispatch_service_reason_code="available",
            dispatch_identifier_type=_workflow_dispatch_identifier_type(target.workflow_id),
            remediation_mode=remediation_mode.strip() or "none",
            workflow_conformance_checked=True,
            workflow_conformance_status=workflow_conformance.conformance_status,
            workflow_conformance_reasons=workflow_conformance.conformance_reasons,
            workflow_conformance_evidence_summary=workflow_conformance.evidence_summary,
        )

    def _fetch_existing_sha(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        branch: str,
        path: str,
    ) -> str | None:
        response_payload = self._request_json(
            method="GET",
            path=(
                f"/repos/{urllib.parse.quote(repo_owner)}/{urllib.parse.quote(repo_name)}"
                f"/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(branch, safe='')}"
            ),
            expected_statuses=(200,),
            allow_404=True,
        )
        if not isinstance(response_payload, dict):
            return None
        sha = str(response_payload.get("sha") or "").strip()
        return sha or None

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


def _safe_identifier_fragment(value: object, *, fallback: str, max_length: int = 80) -> str:
    raw = _coerce_string(value) or ""
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


def _render_managed_deploy_workflow_yaml(
    *,
    workflow_id: str,
    repo_owner: str,
    repo_name: str,
    branch: str,
    deploy_workflow_mode: str,
    target_environment_key: str,
    target_environment_source: str,
    site_id: str | None = None,
) -> str:
    normalized_workflow_id = str(workflow_id or "").strip() or "deploy-www-prod.yml"
    normalized_mode = _normalize_deploy_workflow_mode(deploy_workflow_mode)
    normalized_environment_key = _safe_identifier_fragment(
        target_environment_key,
        fallback="gke-prod",
        max_length=60,
    )
    normalized_environment_source = _normalize_target_environment_source(target_environment_source)
    normalized_repo_fragment = _safe_identifier_fragment(repo_name, fallback="site")
    normalized_site_fragment = _safe_identifier_fragment(site_id, fallback="workspace")
    normalized_name = f"MBSRN Deploy {normalized_repo_fragment}"
    if normalized_mode == "site_repo_template_v1":
        return (
            f"name: {normalized_name}\n"
            "\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            f"    environment: {normalized_environment_key}\n"
            "    steps:\n"
            "      - name: MBSRN managed deploy placeholder\n"
            "        run: |\n"
            f'          echo "MBSRN managed deploy workflow: {normalized_workflow_id}"\n'
            f'          echo "Repository: {repo_owner}/{repo_name}"\n'
            f'          echo "Branch: {branch}"\n'
            f'          echo "Target environment key: {normalized_environment_key}"\n'
            f'          echo "Target environment source: {normalized_environment_source}"\n'
            f'          echo "Site identity: {normalized_site_fragment}"\n'
        )
    return (
        f"name: {normalized_name}\n"
        "\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Placeholder deploy\n"
        f'        run: echo "Deploy workflow ({normalized_workflow_id}) provisioned in mode {normalized_mode}."\n'
    )


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


def _status_links_to_workflow_run(*, status_item: dict[str, object], workflow_run_id: int) -> bool:
    needle = f"/actions/runs/{workflow_run_id}"
    for key in ("log_url", "target_url", "url"):
        value = _coerce_string(status_item.get(key))
        if value and needle in value:
            return True
    return False


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
    "get started with github actions",
)


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

from __future__ import annotations

import base64
import io
import json
import logging
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

import app.integrations.seo_migration_github_publisher as github_publisher_module
from app.core.time import utc_now
from app.integrations.seo_migration_github_publisher import (
    GitHubSEOMigrationPublisher,
    SEOMigrationGitHubLiveRuntimeProbeResult,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisherError,
    _compute_managed_workflow_signature,
    _derive_site_runtime_image_repository,
    _render_managed_deploy_workflow_yaml,
    _render_managed_gke_manifest_files,
    _classify_cloudsql_proxy_failure_from_log_text,
    _derive_https_probe_error_summary_for_failure,
    _extract_resolve_live_url_state_from_log_text,
    _classify_rollout_blocker_hints_from_describe_outputs,
    _emit_structured_publisher_log,
    _resolve_google_credential_principal,
    _resolve_preview_resource_slug,
    build_managed_site_static_ip_labels,
    resolve_managed_preview_endpoint_configuration,
    derive_site_kubernetes_namespace,
    derive_site_preview_certificate_name,
    derive_site_preview_hostname,
    derive_site_preview_static_ip_name,
)


class _FakeHTTPResponse:
    def __init__(self, *, status: int, body: str = "", url: str | None = None) -> None:
        self.status = status
        self._body = body.encode("utf-8")
        self.url = url or ""

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False


def _http_error(url: str, *, status_code: int, message: str) -> urllib.error.HTTPError:
    payload = json.dumps({"message": message}, ensure_ascii=True).encode("utf-8")
    return urllib.error.HTTPError(
        url=url,
        code=status_code,
        msg=message,
        hdrs=None,
        fp=io.BytesIO(payload),
    )


def _dns_rrsets_response(
    *,
    name: str,
    record_type: str,
    rrdatas: list[str] | tuple[str, ...] | None,
    ttl: int = 300,
) -> _FakeHTTPResponse:
    rrsets: list[dict[str, object]] = []
    if rrdatas is not None:
        rrsets.append(
            {
                "name": name,
                "type": record_type,
                "ttl": ttl,
                "rrdatas": list(rrdatas),
            }
        )
    return _FakeHTTPResponse(status=200, body=json.dumps({"rrsets": rrsets}))


def _render_default_managed_workflow_yaml() -> str:
    return _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-tnmfire-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config=None,
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        private_image_auth_required=True,
        site_id="site-tnmfire",
    )


def _extract_resolve_live_url_run_script(workflow_yaml: str) -> str:
    parsed_workflow = yaml.safe_load(workflow_yaml)
    assert isinstance(parsed_workflow, dict)
    jobs = parsed_workflow.get("jobs")
    assert isinstance(jobs, dict)
    deploy_job = jobs.get("deploy")
    assert isinstance(deploy_job, dict)
    steps = deploy_job.get("steps")
    assert isinstance(steps, list)
    resolve_live_url_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and str(step.get("name") or "") == "Resolve live URL from ingress status"
        ),
        None,
    )
    assert isinstance(resolve_live_url_step, dict)
    return str(resolve_live_url_step.get("run") or "")


def _dispatch_target() -> SEOMigrationGitHubDeployTarget:
    return SEOMigrationGitHubDeployTarget(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        workflow_id="deploy-tnmfire-www-prod.yml",
        ref="main",
        inputs={"site_id": "site-1"},
    )


def _dispatch_target_with_workflow_path() -> SEOMigrationGitHubDeployTarget:
    return SEOMigrationGitHubDeployTarget(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        workflow_id=".github/workflows/deploy-tnmfire-www-prod.yml",
        ref="main",
        inputs={"site_id": "site-1"},
    )


def _encode_workflow_yaml(content: str) -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def _repo_management_marker_content(
    *,
    business_id: str = "business-1",
    site_id: str = "site-1",
) -> str:
    return (
        json.dumps(
            {
                "version": 1,
                "managed_by": "mbsrn",
                "created_by": "mbsrn",
                "business_id": business_id,
                "site_id": site_id,
            },
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _repo_management_marker_response(
    *,
    sha: str = "marker-sha",
    business_id: str = "business-1",
    site_id: str = "site-1",
) -> _FakeHTTPResponse:
    return _FakeHTTPResponse(
        status=200,
        body=json.dumps(
            {
                "sha": sha,
                "encoding": "base64",
                "content": _encode_workflow_yaml(
                    _repo_management_marker_content(
                        business_id=business_id,
                        site_id=site_id,
                    )
                ),
            }
        ),
    )


def _repo_management_marker_invalid_response(*, sha: str = "marker-invalid-sha") -> _FakeHTTPResponse:
    return _FakeHTTPResponse(
        status=200,
        body=json.dumps(
            {
                "sha": sha,
                "encoding": "base64",
                "content": _encode_workflow_yaml("not-json"),
            }
        ),
    )


def _managed_repo_baseline_present_responses() -> list[_FakeHTTPResponse]:
    return [
        _FakeHTTPResponse(status=200, body=json.dumps({"sha": "marker-sha"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"sha": "readme-sha"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"sha": "gitignore-sha"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"sha": "license-sha"})),
    ]


def _atomic_publish_responses(
    *,
    file_count: int = 1,
    commit_sha: str = "content-commit",
    artifact_root: str = "",
) -> list[_FakeHTTPResponse]:
    paths = ["index.html"] if file_count == 1 else ["index.html", "assets/hero.png"]
    if artifact_root:
        paths = [f"{artifact_root}/{path}" for path in paths]
    return [
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "parent-commit"}})),
        _FakeHTTPResponse(status=200, body=json.dumps({"tree": {"sha": "base-tree"}})),
        *[_FakeHTTPResponse(status=201, body=json.dumps({"sha": f"blob-{index}"})) for index in range(file_count)],
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "new-tree"})),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps(
                {
                    "sha": "new-tree",
                    "truncated": False,
                    "tree": [
                        {"path": path, "type": "blob", "sha": f"blob-{index}"} for index, path in enumerate(paths)
                    ],
                }
            ),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": commit_sha})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": commit_sha}})),
    ]


def _install_urlopen_stub(monkeypatch, responses, calls, payloads=None):
    queue = list(responses)

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if payloads is not None:
            request_body = getattr(request, "data", None)
            if request_body is None:
                payloads.append(None)
            else:
                payloads.append(json.loads(request_body.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)


def test_resolve_google_credential_principal_prefers_service_account_client_email() -> None:
    source, principal = _resolve_google_credential_principal(
        credentials_json=json.dumps(
            {
                "type": "service_account",
                "client_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
                "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----",
            }
        ),
        timeout_seconds=10,
    )

    assert source == "service_account_json"
    assert principal == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert principal and "private_key" not in principal


def test_resolve_google_credential_principal_uses_metadata_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._lookup_google_metadata_principal_email",
        lambda **kwargs: "wi-runtime@mbsrn-prod.iam.gserviceaccount.com",
    )
    source, principal = _resolve_google_credential_principal(
        credentials_json=None,
        timeout_seconds=10,
    )

    assert source == "adc_metadata_server"
    assert principal == "wi-runtime@mbsrn-prod.iam.gserviceaccount.com"


def test_resolve_google_credential_principal_returns_unknown_when_metadata_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._lookup_google_metadata_principal_email",
        lambda **kwargs: None,
    )
    source, principal = _resolve_google_credential_principal(
        credentials_json=None,
        timeout_seconds=10,
    )

    assert source == "unknown"
    assert principal is None


def _managed_file_verify_response(*, sha: str, marker: str) -> _FakeHTTPResponse:
    content = _encode_workflow_yaml(f"# {marker}\nname: Managed resource\n")
    return _FakeHTTPResponse(
        status=200,
        body=json.dumps(
            {
                "sha": sha,
                "encoding": "base64",
                "content": content,
            }
        ),
    )


def _managed_workflow_verify_response(
    *,
    sha: str,
    workflow_id: str = "deploy-tnmfire-www-prod.yml",
) -> _FakeHTTPResponse:
    workflow_content = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            f"name: MBSRN Deploy {workflow_id}\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            "      - run: gcloud container clusters get-credentials mbsrn-prod --region us-central1\n"
            "      - run: kubectl apply -f k8s/\n"
            "      - run: kubectl rollout status deployment/mbsrn-www -n mbsrn\n"
        )
    )
    return _FakeHTTPResponse(
        status=200,
        body=json.dumps(
            {
                "sha": sha,
                "encoding": "base64",
                "content": workflow_content,
            }
        ),
    )


def _gke_environment_config_present_responses() -> list[object]:
    return [
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_NAME"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_NAME"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_LOCATION"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_LOCATION"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "GCP_PROJECT_ID"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "GCP_PROJECT_ID"})),
    ]


def _managed_provisioning_responses(*, missing_verify_path: str | None = None) -> list[object]:
    responses: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
    ]
    responses.extend(
        _managed_file_upsert_responses(
            managed_paths=(
                ".github/workflows/deploy-tnmfire-www-prod.yml",
                "k8s/namespace.yaml",
                "k8s/deployment.yaml",
                "k8s/service.yaml",
                "k8s/ingress.yaml",
                "k8s/managedcertificate.yaml",
                "k8s/frontendconfig.yaml",
                "k8s/backendconfig.yaml",
                "site-runtime/Dockerfile",
            ),
            missing_verify_path=missing_verify_path,
        )
    )
    return responses


def _managed_provisioning_responses_with_paths(
    *,
    managed_paths: tuple[str, ...],
    missing_verify_path: str | None = None,
) -> list[object]:
    responses: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
    ]
    responses.extend(
        _managed_file_upsert_responses(
            managed_paths=managed_paths,
            missing_verify_path=missing_verify_path,
        )
    )
    return responses


def _managed_file_upsert_responses(
    *,
    managed_paths: tuple[str, ...],
    missing_verify_path: str | None = None,
) -> list[object]:
    if "site-runtime/Dockerfile" not in managed_paths:
        managed_paths = (*managed_paths, "site-runtime/Dockerfile")
    responses: list[object] = []
    for index, managed_path in enumerate(managed_paths, start=1):
        responses.append(
            _http_error(
                f"https://api.github.com/repos/mhanson13/tnmfire/contents/{managed_path}?ref=main",
                status_code=404,
                message="Not Found",
            )
        )
        responses.append(_FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": f"commit-{index}"}})))
        if missing_verify_path == managed_path:
            responses.append(
                _http_error(
                    f"https://api.github.com/repos/mhanson13/tnmfire/contents/{managed_path}?ref=main",
                    status_code=404,
                    message="Not Found",
                )
            )
        else:
            if managed_path.endswith(".yml"):
                responses.append(_managed_workflow_verify_response(sha=f"verified-{index}"))
            else:
                responses.append(
                    _managed_file_verify_response(
                        sha=f"verified-{index}",
                        marker="mbsrn-managed-manifest:site_repo_template_v1",
                    )
                )
    if missing_verify_path == ".github/workflows/deploy-tnmfire-www-prod.yml":
        responses.append(
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
                status_code=404,
                message="Not Found",
            )
        )
    else:
        responses.append(_managed_workflow_verify_response(sha="verified-final-workflow"))
    return responses


def test_ensure_repository_returns_exists_when_repo_present(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        ],
        calls,
    )

    result = publisher.ensure_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        auto_create_enabled=False,
        create_if_missing=True,
        expected_owner="mhanson13",
    )

    assert result.exists is True
    assert result.auto_create_attempted is False
    assert result.auto_create_created is False
    assert result.outcome == "repo_exists"
    assert calls == [("GET", "https://api.github.com/repos/mhanson13/tnmfire")]


def test_ensure_repository_check_only_reports_repo_missing(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    result = publisher.ensure_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        auto_create_enabled=True,
        create_if_missing=False,
        expected_owner="mhanson13",
    )

    assert result.exists is False
    assert result.auto_create_attempted is False
    assert result.auto_create_created is False
    assert result.outcome == "repo_missing"
    assert result.skipped_reason == "check_only"
    assert calls == [("GET", "https://api.github.com/repos/mhanson13/tnmfire")]


def test_ensure_repository_missing_repo_with_auto_create_disabled_raises_precise_reason(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_repository(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            auto_create_enabled=False,
            create_if_missing=True,
            expected_owner="mhanson13",
        )

    assert exc_info.value.code == "repo_auto_create_disabled"
    assert exc_info.value.stage == "repo_create"
    assert calls == [("GET", "https://api.github.com/repos/mhanson13/tnmfire")]


def test_ensure_repository_missing_repo_with_auto_create_enabled_creates_repository(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    observed_payload: dict[str, object] = {}
    queue = [
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"name": "tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "seed-sha"}})),
    ]

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST" and request.full_url == "https://api.github.com/orgs/mhanson13/repos":
            observed_payload.update(json.loads((request.data or b"{}").decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)

    result = publisher.ensure_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        auto_create_enabled=True,
        create_if_missing=True,
        expected_owner="mhanson13",
    )

    assert result.exists is True
    assert result.auto_create_attempted is True
    assert result.auto_create_created is True
    assert result.outcome == "repo_created"
    assert observed_payload.get("private") is True
    assert observed_payload.get("auto_init") is True
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("POST", "https://api.github.com/orgs/mhanson13/repos"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main"),
    ]


def test_ensure_repository_create_unauthorized_classifies_precisely(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/orgs/mhanson13/repos",
                status_code=403,
                message="Forbidden",
            ),
        ],
        calls,
    )

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_repository(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            auto_create_enabled=True,
            create_if_missing=True,
            expected_owner="mhanson13",
        )

    assert exc_info.value.code == "repo_auto_create_not_authorized"
    assert exc_info.value.stage == "repo_create"
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("POST", "https://api.github.com/orgs/mhanson13/repos"),
    ]


def test_ensure_repository_create_conflict_resolves_to_idempotent_success_when_repo_exists(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/orgs/mhanson13/repos",
                status_code=409,
                message="Conflict",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        ],
        calls,
    )

    result = publisher.ensure_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        auto_create_enabled=True,
        create_if_missing=True,
        expected_owner="mhanson13",
    )

    assert result.exists is True
    assert result.auto_create_attempted is True
    assert result.auto_create_created is False
    assert result.outcome == "repo_exists"
    assert result.skipped_reason == "created_during_race"
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("POST", "https://api.github.com/orgs/mhanson13/repos"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
    ]


def test_ensure_repository_personal_owner_falls_back_to_user_create(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/orgs/mhanson13/repos",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"login": "mhanson13"})),
            _FakeHTTPResponse(status=201, body=json.dumps({"name": "tnmfire"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "seed-sha"}})),
        ],
        calls,
    )

    result = publisher.ensure_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        auto_create_enabled=True,
        create_if_missing=True,
        expected_owner="mhanson13",
    )

    assert result.exists is True
    assert result.auto_create_attempted is True
    assert result.auto_create_created is True
    assert result.outcome == "repo_created"
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("POST", "https://api.github.com/orgs/mhanson13/repos"),
        ("GET", "https://api.github.com/user"),
        ("POST", "https://api.github.com/user/repos"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main"),
    ]


def test_ensure_repository_auto_create_defaults_to_private_visibility(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    observed_private_value: bool | None = None
    observed_auto_init: bool | None = None
    queue = [
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"name": "tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "seed-sha"}})),
    ]

    def _stub(request, timeout=None):
        nonlocal observed_private_value, observed_auto_init
        del timeout
        if request.get_method() == "POST" and request.full_url == "https://api.github.com/orgs/mhanson13/repos":
            payload = json.loads((request.data or b"{}").decode("utf-8"))
            observed_private_value = bool(payload.get("private"))
            observed_auto_init = bool(payload.get("auto_init"))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)

    publisher.ensure_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        auto_create_enabled=True,
        create_if_missing=True,
        expected_owner="mhanson13",
    )

    assert observed_private_value is True
    assert observed_auto_init is True


def test_run_publish_preflight_repo_exists_with_workflow_write_gap(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "full_name": "mhanson13/tnmfire",
                        "default_branch": "main",
                        "permissions": {"push": True},
                    }
                ),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows?per_page=1",
                status_code=403,
                message="Forbidden",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _repo_management_marker_response(),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="main",
        auto_create_enabled=False,
        expected_owner="mhanson13",
    )

    assert result.repo_exists is True
    assert result.repo_ensure_outcome == "exists"
    assert result.can_read_contents is True
    assert result.can_write_contents is True
    assert result.can_write_workflows is False
    assert result.preflight_status == "blocked"
    assert result.preflight_blocker_code == "github_workflow_write_not_authorized"
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows?per_page=1"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/branches/main"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main"),
    ]


def test_run_publish_preflight_repo_exists_with_missing_ref_reports_bootstrap_action(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "full_name": "mhanson13/tnmfire",
                        "default_branch": "main",
                        "permissions": {"push": True},
                    }
                ),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"total_count": 0, "workflows": []})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/branches/release",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=release",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="release",
        auto_create_enabled=False,
        expected_owner="mhanson13",
    )

    assert result.repo_exists is True
    assert result.target_ref == "release"
    assert result.target_ref_exists is False
    assert result.repo_initialized is False
    assert result.can_write_contents is True
    assert result.can_write_workflows is True
    assert result.would_bootstrap_branch is False
    assert result.preflight_status == "blocked"
    assert result.preflight_blocker_code == "github_repo_requires_manual_initialization"
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows?per_page=1"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/branches/release"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=release"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main"),
    ]


def test_run_publish_preflight_missing_repo_with_auto_create_enabled_reports_would_create(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="main",
        auto_create_enabled=True,
        expected_owner="mhanson13",
    )

    assert result.repo_exists is False
    assert result.repo_ensure_outcome == "would_create_on_publish"
    assert result.would_auto_create_repo is True
    assert result.preflight_status == "ready_with_actions"
    assert result.preflight_blocker_code is None
    assert calls == [("GET", "https://api.github.com/repos/mhanson13/tnmfire")]


def test_run_publish_preflight_missing_repo_with_auto_create_disabled_is_blocked(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="main",
        auto_create_enabled=False,
        expected_owner="mhanson13",
    )

    assert result.repo_exists is False
    assert result.repo_ensure_outcome == "skipped_policy_disabled"
    assert result.would_auto_create_repo is False
    assert result.preflight_status == "blocked"
    assert result.preflight_blocker_code == "repo_auto_create_disabled"
    assert calls == [("GET", "https://api.github.com/repos/mhanson13/tnmfire")]


def test_run_publish_preflight_existing_repo_without_management_marker_is_blocked(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "full_name": "mhanson13/tnmfire",
                        "default_branch": "main",
                        "permissions": {"push": True},
                    }
                ),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"total_count": 1, "workflows": [{"id": 1}]})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="main",
        auto_create_enabled=False,
        expected_owner="mhanson13",
        expected_business_id="business-1",
        expected_site_id="site-1",
    )

    assert result.preflight_status == "blocked"
    assert result.preflight_blocker_code == "github_repo_adoption_required"
    assert result.repo_management_status == "marker_missing"
    assert result.repo_management_marker_present is False
    assert result.repo_management_marker_valid is False
    assert result.repo_management_marker_matches_site is False


def test_run_publish_preflight_existing_repo_with_management_marker_mismatch_is_blocked(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "full_name": "mhanson13/tnmfire",
                        "default_branch": "main",
                        "permissions": {"push": True},
                    }
                ),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"total_count": 1, "workflows": [{"id": 1}]})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _repo_management_marker_response(
                business_id="different-business",
                site_id="different-site",
            ),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="main",
        auto_create_enabled=False,
        expected_owner="mhanson13",
        expected_business_id="business-1",
        expected_site_id="site-1",
    )

    assert result.preflight_status == "blocked"
    assert result.preflight_blocker_code == "github_repo_management_marker_mismatch"
    assert result.repo_management_status == "marker_mismatch"
    assert result.repo_management_marker_present is True
    assert result.repo_management_marker_valid is True
    assert result.repo_management_marker_matches_site is False
    assert result.repo_management_marker_business_id == "different-business"
    assert result.repo_management_marker_site_id == "different-site"


def test_run_publish_preflight_existing_managed_repo_missing_baseline_files_reports_reconcile_action(
    monkeypatch,
) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "full_name": "mhanson13/tnmfire",
                        "default_branch": "main",
                        "private": True,
                        "permissions": {"push": True},
                    }
                ),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"total_count": 1, "workflows": [{"id": 1}]})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _repo_management_marker_response(),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/LICENSE?ref=main",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )

    result = publisher.run_publish_preflight(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_ref="main",
        auto_create_enabled=False,
        expected_owner="mhanson13",
        expected_business_id="business-1",
        expected_site_id="site-1",
    )

    assert result.preflight_status == "ready_with_actions"
    assert result.preflight_blocker_code is None
    assert result.repo_visibility_target == "private"
    assert result.repo_visibility_observed == "private"
    assert result.repo_baseline_required is True
    assert result.repo_baseline_reconciliation_needed is True
    assert result.readme_present is False
    assert result.gitignore_present is False
    assert result.license_present is False
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows?per_page=1"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/branches/main"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire/contents/LICENSE?ref=main"),
    ]


def test_publish_files_blocks_existing_repo_without_management_marker(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
                business_id="business-1",
                site_id="site-1",
            ),
            files=[
                SEOMigrationGitHubPublishFile(
                    path="index.html",
                    content="<html><body>test</body></html>",
                    media_type="text/html",
                )
            ],
            commit_message="publish",
            dry_run=False,
        )
    assert exc_info.value.code == "github_repo_adoption_required"


def test_adopt_repository_writes_marker_for_existing_repo_without_marker(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"full_name": "mhanson13/tnmfire"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"full_name": "mhanson13/tnmfire", "default_branch": "main"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"object": {"sha": "main-sha"}}),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "commit-1"}})),
            _repo_management_marker_response(
                business_id="business-1",
                site_id="site-1",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.adopt_repository(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        ref="main",
        business_id="business-1",
        site_id="site-1",
        principal_id="principal-1",
        expected_owner="mhanson13",
    )

    assert result.marker_written is True
    assert result.adoption_outcome == "marker_written"
    assert result.management_status == "managed_marker_match"
    assert ("PUT", "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key") in calls


def test_adopt_repository_blocks_marker_mismatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"full_name": "mhanson13/tnmfire", "default_branch": "main"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"object": {"sha": "main-sha"}}),
            ),
            _repo_management_marker_response(
                business_id="different-business",
                site_id="different-site",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.adopt_repository(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            ref="main",
            business_id="business-1",
            site_id="site-1",
            principal_id="principal-1",
            expected_owner="mhanson13",
        )

    assert exc_info.value.code == "github_repo_management_marker_mismatch"


def test_adopt_repository_fails_for_existing_empty_repo(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"full_name": "mhanson13/tnmfire", "default_branch": "main"}),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
                status_code=409,
                message="Git Repository is empty.",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.adopt_repository(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            ref="main",
            business_id="business-1",
            site_id="site-1",
            principal_id="principal-1",
            expected_owner="mhanson13",
        )

    assert exc_info.value.code == "github_repo_requires_manual_initialization"


def test_publish_files_blocks_existing_repo_with_invalid_management_marker(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_invalid_response(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
                business_id="business-1",
                site_id="site-1",
            ),
            files=[
                SEOMigrationGitHubPublishFile(
                    path="index.html",
                    content="<html><body>test</body></html>",
                    media_type="text/html",
                )
            ],
            commit_message="publish",
            dry_run=False,
        )
    assert exc_info.value.code == "github_repo_management_marker_invalid"


def test_publish_files_allows_existing_repo_with_matching_management_marker(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(
                business_id="business-1",
                site_id="site-1",
            ),
            *_managed_repo_baseline_present_responses(),
            *_atomic_publish_responses(commit_sha="commit-1"),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.publish_files(
        target=SEOMigrationGitHubPublishTarget(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            artifact_root="",
            business_id="business-1",
            site_id="site-1",
        ),
        files=[
            SEOMigrationGitHubPublishFile(
                path="index.html",
                content="<html><body>test</body></html>",
                media_type="text/html",
            )
        ],
        commit_message="publish",
        dry_run=False,
    )

    assert result.files_published == 1
    assert result.committed_paths == ("index.html",)
    assert result.commit_shas == ("commit-1",)


def test_publish_files_commits_text_and_binary_package_with_one_atomic_ref_update(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    payloads: list[dict[str, object] | None] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            *_managed_repo_baseline_present_responses(),
            *_atomic_publish_responses(file_count=2, commit_sha="atomic-commit", artifact_root="site"),
        ],
        calls,
        payloads,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.publish_files(
        target=SEOMigrationGitHubPublishTarget(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            artifact_root="site",
            business_id="business-1",
            site_id="site-1",
        ),
        files=[
            SEOMigrationGitHubPublishFile(path="index.html", content="<html>ready</html>"),
            SEOMigrationGitHubPublishFile(path="assets/hero.png", content_bytes=b"\x89PNG\r\n"),
        ],
        commit_message="publish exact release",
        dry_run=False,
    )

    assert result.commit_shas == ("atomic-commit",)
    assert result.committed_paths == ("site/index.html", "site/assets/hero.png")
    assert sum(method == "PATCH" and "/git/refs/heads/main" in url for method, url in calls) == 1
    assert not any("/contents/site/" in url for _, url in calls)
    blob_payloads = [
        payload
        for (method, url), payload in zip(calls, payloads, strict=True)
        if method == "POST" and url.endswith("/git/blobs")
    ]
    assert [payload["encoding"] for payload in blob_payloads if payload is not None] == ["base64", "base64"]
    assert base64.b64decode(str(blob_payloads[1]["content"])) == b"\x89PNG\r\n"
    commit_payload = next(
        payload
        for (method, url), payload in zip(calls, payloads, strict=True)
        if method == "POST" and url.endswith("/git/commits")
    )
    assert commit_payload == {
        "message": "publish exact release",
        "tree": "new-tree",
        "parents": ["parent-commit"],
        "committer": {"name": "MBSRN Migration Bot", "email": "migration-bot@mbsrn.local"},
    }


def test_publish_files_does_not_create_commit_or_move_ref_when_tree_verification_fails(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            *_managed_repo_baseline_present_responses(),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "parent-commit"}})),
            _FakeHTTPResponse(status=200, body=json.dumps({"tree": {"sha": "base-tree"}})),
            _FakeHTTPResponse(status=201, body=json.dumps({"sha": "blob-0"})),
            _FakeHTTPResponse(status=201, body=json.dumps({"sha": "new-tree"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "new-tree", "truncated": False, "tree": []})),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
                business_id="business-1",
                site_id="site-1",
            ),
            files=[SEOMigrationGitHubPublishFile(path="index.html", content="<html>ready</html>")],
            commit_message="publish exact release",
            dry_run=False,
        )

    assert exc_info.value.code == "publish_tree_verification_failed"
    assert exc_info.value.stage == "publish_verification"
    assert not any(method == "POST" and url.endswith("/git/commits") for method, url in calls)
    assert not any(method == "PATCH" and "/git/refs/" in url for method, url in calls)


def test_publish_files_reconciles_missing_repo_baseline_files_for_managed_repo(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(
                business_id="business-1",
                site_id="site-1",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "marker-sha"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/LICENSE?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-readme"}})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-gitignore"}})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/LICENSE?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-license"}})),
            *_atomic_publish_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.publish_files(
        target=SEOMigrationGitHubPublishTarget(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            artifact_root="",
            business_id="business-1",
            site_id="site-1",
        ),
        files=[
            SEOMigrationGitHubPublishFile(
                path="index.html",
                content="<html><body>test</body></html>",
                media_type="text/html",
            )
        ],
        commit_message="publish",
        dry_run=False,
    )

    baseline_put_calls = [
        call
        for call in calls
        if call[0] == "PUT" and "/contents/" in call[1] and not call[1].endswith("/contents/index.html")
    ]
    assert len(baseline_put_calls) == 3
    assert any(call[1].endswith("/contents/README.md") for call in baseline_put_calls)
    assert any(call[1].endswith("/contents/.gitignore") for call in baseline_put_calls)
    assert any(call[1].endswith("/contents/LICENSE") for call in baseline_put_calls)
    assert result.files_published == 1
    assert result.committed_paths == ("index.html",)
    assert result.commit_shas == ("content-commit",)


def test_publish_files_reconciles_only_missing_baseline_files_without_overwriting_present_files(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(
                business_id="business-1",
                site_id="site-1",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "marker-sha"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "readme-sha"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "license-sha"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-gitignore"}})),
            *_atomic_publish_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    _ = publisher.publish_files(
        target=SEOMigrationGitHubPublishTarget(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            artifact_root="",
            business_id="business-1",
            site_id="site-1",
        ),
        files=[
            SEOMigrationGitHubPublishFile(
                path="index.html",
                content="<html><body>test</body></html>",
                media_type="text/html",
            )
        ],
        commit_message="publish",
        dry_run=False,
    )

    baseline_put_calls = [
        call
        for call in calls
        if call[0] == "PUT" and "/contents/" in call[1] and not call[1].endswith("/contents/index.html")
    ]
    assert baseline_put_calls == [
        ("PUT", "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore"),
    ]


def test_publish_files_classifies_repo_baseline_reconciliation_failure_precisely(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(
                business_id="business-1",
                site_id="site-1",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "marker-sha"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "gitignore-sha"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "license-sha"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md",
                status_code=500,
                message="Server Error",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
                business_id="business-1",
                site_id="site-1",
            ),
            files=[
                SEOMigrationGitHubPublishFile(
                    path="index.html",
                    content="<html><body>test</body></html>",
                    media_type="text/html",
                )
            ],
            commit_message="publish",
            dry_run=False,
        )

    assert exc_info.value.code == "github_repo_baseline_reconciliation_failed"


def test_derive_site_kubernetes_namespace_normalizes_repo_name_values() -> None:
    assert derive_site_kubernetes_namespace(repo_name="tnmfire", site_id=None) == ("tnmfire", "repo_name")
    assert derive_site_kubernetes_namespace(repo_name="Lars Construction", site_id=None) == (
        "lars-construction",
        "repo_name",
    )
    assert derive_site_kubernetes_namespace(repo_name="LARS___Construction!!!", site_id=None) == (
        "lars-construction",
        "repo_name",
    )


def test_derive_site_kubernetes_namespace_truncates_long_names_deterministically() -> None:
    long_repo = "A" * 90
    namespace, source = derive_site_kubernetes_namespace(repo_name=long_repo, site_id=None)
    assert source == "repo_name"
    assert len(namespace) == 63
    assert namespace == "a" * 63


def test_derive_site_kubernetes_namespace_rejects_empty_source_values() -> None:
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        derive_site_kubernetes_namespace(repo_name="   ", site_id=None)
    assert exc_info.value.code == "namespace_invalid"
    assert exc_info.value.stage == "workflow_provisioning"


def test_derive_site_preview_hostname_matches_namespace_slug() -> None:
    preview_hostname, source = derive_site_preview_hostname(repo_name="TnM Fire", site_id=None)
    assert preview_hostname == "tnm-fire.site.mbsrn.com"
    assert source == "repo_name"


def test_preview_resource_slug_uses_explicit_canonical_hostname_when_repository_differs() -> None:
    assert _resolve_preview_resource_slug(
        repo_name="unrelated-repository",
        preview_hostname="canonical-preview.site.mbsrn.com",
    ) == ("canonical-preview", "preview_slug")


def test_preview_resource_slug_rejects_non_platform_hostname() -> None:
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        _resolve_preview_resource_slug(
            repo_name="repository",
            preview_hostname="www.customer.example",
        )
    assert exc_info.value.code == "preview_hostname_invalid"


def test_derive_site_preview_certificate_name_is_site_scoped_and_dns1123_safe() -> None:
    certificate_name, source = derive_site_preview_certificate_name(repo_name="Sc Mechanical", site_id=None)
    assert source == "repo_name"
    assert certificate_name == "site-web-preview-cert-sc-mechanical"
    assert len(certificate_name) <= 63
    assert certificate_name.lower() == certificate_name
    assert "_" not in certificate_name


def test_derive_site_preview_certificate_name_is_stable_across_same_site_and_config() -> None:
    first_name, first_source = derive_site_preview_certificate_name(repo_name="Sc Mechanical", site_id="site-1")
    second_name, second_source = derive_site_preview_certificate_name(repo_name="Sc Mechanical", site_id="site-1")
    assert first_source == second_source
    assert first_name == second_name


def test_derive_site_preview_static_ip_name_is_site_scoped_and_dns1123_safe() -> None:
    static_ip_name, source = derive_site_preview_static_ip_name(repo_name="Sc Mechanical", site_id=None)
    assert source == "repo_name"
    assert static_ip_name == "site-web-preview-ip-sc-mechanical"
    assert len(static_ip_name) <= 63
    assert static_ip_name.lower() == static_ip_name
    assert "_" not in static_ip_name


def test_derive_site_runtime_image_repository_uses_owner_and_repo_scoped_path() -> None:
    assert (
        _derive_site_runtime_image_repository(repo_owner="mhanson13", repo_name="scmechanical")
        == "ghcr.io/mhanson13/scmechanical-site-web"
    )


def test_derive_site_runtime_image_repository_rejects_empty_owner_without_fallback() -> None:
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        _derive_site_runtime_image_repository(repo_owner="   ", repo_name="scmechanical")
    assert exc_info.value.code == "runtime_image_repository_invalid"
    assert exc_info.value.stage == "workflow_provisioning"


def test_derive_site_runtime_image_repository_rejects_empty_repo_name_without_fallback() -> None:
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        _derive_site_runtime_image_repository(repo_owner="mhanson13", repo_name="   ")
    assert exc_info.value.code == "runtime_image_repository_invalid"
    assert exc_info.value.stage == "workflow_provisioning"


def test_classify_rollout_blockers_prioritizes_image_pull_not_found_without_crash_or_probe() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            'Warning  Failed     kubelet  Failed to pull image "ghcr.io/mhanson13/site-web:latest": not found\n'
            "Warning  Failed     kubelet  Error: ErrImagePull\n"
            "Warning  Failed     kubelet  Back-off pulling image\n"
            "State: Waiting\nReason: ImagePullBackOff\n"
        ),
    )
    assert "image_pull_backoff" in hints
    assert "image_pull_failure" in hints
    assert "container_image_not_found" in hints
    assert "pod_crash_or_startup_failure" not in hints
    assert "readiness_or_liveness_probe_failure" not in hints


def test_classify_rollout_blockers_prioritizes_private_registry_auth_without_crash_hint() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            'Warning  Failed  kubelet  Failed to pull image "ghcr.io/mhanson13/site-web:latest": failed to fetch anonymous token: 403 Forbidden\n'
            "Warning  Failed  kubelet  pull access denied\n"
        ),
        private_image_auth_required=True,
    )
    assert "private_image_pull_forbidden" in hints
    assert "image_pull_forbidden" in hints
    assert "image_pull_secret_not_referenced" in hints
    assert "image_pull_failure" in hints
    assert "private_registry_auth_failure" in hints
    assert "pod_crash_or_startup_failure" not in hints


def test_classify_rollout_blockers_reports_missing_pull_secret() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            "Warning  Failed  kubelet  FailedToRetrieveImagePullSecret\n"
            'Warning  Failed  kubelet  secret "ghcr-pull-secret" not found for image pull\n'
        ),
        private_image_auth_required=True,
    )
    assert "image_pull_secret_missing" in hints
    assert "image_pull_forbidden" not in hints
    assert "pod_crash_or_startup_failure" not in hints


def test_classify_rollout_blockers_reports_public_image_pull_failed_in_public_mode() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            'Warning  Failed  kubelet  Failed to pull image "ghcr.io/mhanson13/site-web:latest": failed to fetch anonymous token: 403 Forbidden\n'
            "Warning  Failed  kubelet  pull access denied\n"
        ),
    )
    assert "public_image_pull_failed" in hints
    assert "image_pull_secret_missing" not in hints
    assert "image_pull_secret_not_referenced" not in hints


def test_classify_rollout_blockers_reports_real_crash_after_container_start() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            "Container ID:   containerd://abc123\n"
            "Started:        true\n"
            "State:          Terminated\n"
            "Last State:     Terminated\n"
            "Reason:         Error\n"
            "Warning  BackOff  kubelet  Back-off restarting failed container\n"
            "CrashLoopBackOff\n"
        ),
    )
    assert "pod_crash_or_startup_failure" in hints
    assert "image_pull_failure" not in hints
    assert "private_registry_auth_failure" not in hints


def test_classify_rollout_blockers_reports_probe_failure_only_with_started_container_evidence() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            "Container ID:   containerd://abc123\n"
            "Started:        true\n"
            "Warning  Unhealthy  kubelet  Readiness probe failed: Get http://10.0.0.2:3000/healthz: connection refused\n"
        ),
    )
    assert "readiness_or_liveness_probe_failure" in hints
    assert "image_pull_failure" not in hints


def test_classify_rollout_blockers_suppresses_crash_probe_when_current_blocker_is_image_pull() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            'Warning  Failed   kubelet  Failed to pull image "ghcr.io/mhanson13/site-web:latest": manifest unknown\n'
            "State: Waiting\nReason: ImagePullBackOff\n"
            "Container ID:   containerd://oldpod\n"
            "Started:        true\n"
            "CrashLoopBackOff\n"
            "Warning  Unhealthy  kubelet  Readiness probe failed\n"
        ),
    )
    assert "image_pull_failure" in hints
    assert "container_image_not_found" in hints
    assert "pod_crash_or_startup_failure" not in hints
    assert "readiness_or_liveness_probe_failure" not in hints


def test_classify_rollout_blockers_reports_backendconfig_and_ingress_backend_health_hints() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output=(
            "Events:\n"
            "  Warning  Sync  ingress-gce  ingress backend service unhealthy\n"
            "  Warning  Sync  ingress-gce  BackendConfig healthCheck path mismatch requestPath=/healthz\n"
        ),
        pods_describe_output="",
    )
    assert "ingress_backend_unhealthy" in hints
    assert "backendconfig_health_check_mismatch" in hints


def test_upsert_actions_secret_creates_secret_when_missing(monkeypatch) -> None:
    nacl_public = pytest.importorskip("nacl.public")
    nacl_encoding = pytest.importorskip("nacl.encoding")
    secret_key = nacl_public.PrivateKey.generate()
    public_key_b64 = secret_key.public_key.encode(encoder=nacl_encoding.Base64Encoder()).decode("utf-8")

    calls: list[tuple[str, str]] = []
    captured_put_payload: dict[str, object] = {}
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body="{}"),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/actions/secrets/GCP_DEPLOY_KEY",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"key_id": "key-1", "key": public_key_b64}),
        ),
        _FakeHTTPResponse(status=201, body=""),
    ]

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/actions/secrets/GCP_DEPLOY_KEY")
            and request.data
        ):
            captured_put_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.upsert_actions_secret(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        secret_name="GCP_DEPLOY_KEY",
        secret_value='{"type":"service_account"}',
    )

    assert result.action == "created"
    assert result.secret_name == "GCP_DEPLOY_KEY"
    assert captured_put_payload.get("key_id") == "key-1"
    encrypted_value = str(captured_put_payload.get("encrypted_value") or "")
    assert encrypted_value
    assert '{"type":"service_account"}' not in encrypted_value
    assert any(method == "GET" and url.endswith("/actions/secrets/public-key") for method, url in calls)


def test_upsert_actions_secret_updates_existing_secret(monkeypatch) -> None:
    nacl_public = pytest.importorskip("nacl.public")
    nacl_encoding = pytest.importorskip("nacl.encoding")
    secret_key = nacl_public.PrivateKey.generate()
    public_key_b64 = secret_key.public_key.encode(encoder=nacl_encoding.Base64Encoder()).decode("utf-8")

    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body="{}"),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "GCP_DEPLOY_KEY", "updated_at": "2026-04-17"})),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"key_id": "key-2", "key": public_key_b64}),
        ),
        _FakeHTTPResponse(status=204, body=""),
    ]

    _install_urlopen_stub(monkeypatch, queue, calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.upsert_actions_secret(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        secret_name="GCP_DEPLOY_KEY",
        secret_value='{"type":"service_account"}',
    )

    assert result.action == "updated"
    assert any(method == "GET" and url.endswith("/actions/secrets/GCP_DEPLOY_KEY") for method, url in calls)
    assert any(method == "PUT" and url.endswith("/actions/secrets/GCP_DEPLOY_KEY") for method, url in calls)


def test_publish_files_classifies_contents_write_forbidden(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            *_managed_repo_baseline_present_responses(),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "parent-commit"}})),
            _FakeHTTPResponse(status=200, body=json.dumps({"tree": {"sha": "base-tree"}})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/git/blobs",
                status_code=403,
                message="Resource not accessible by integration",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
            ),
            files=[
                SEOMigrationGitHubPublishFile(
                    path="index.html",
                    content="<html><body>test</body></html>",
                    media_type="text/html",
                )
            ],
            commit_message="publish",
            dry_run=False,
        )
    assert exc_info.value.code == "github_contents_write_not_authorized"
    assert exc_info.value.stage == "publish"
    assert not any(method == "PATCH" and "/git/refs/" in url for method, url in calls)


def test_publish_files_classifies_branch_uninitialized_from_lookup(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            *_managed_repo_baseline_present_responses(),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
                status_code=422,
                message="Invalid request. Branch main was not found.",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
            ),
            files=[
                SEOMigrationGitHubPublishFile(
                    path="index.html",
                    content="<html><body>test</body></html>",
                    media_type="text/html",
                )
            ],
            commit_message="publish",
            dry_run=False,
        )
    assert exc_info.value.code == "github_branch_not_found_or_uninitialized"
    assert exc_info.value.stage == "publish"


def test_publish_files_classifies_generic_request_failure(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            *_managed_repo_baseline_present_responses(),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "parent-commit"}})),
            _FakeHTTPResponse(status=200, body=json.dumps({"tree": {"sha": "base-tree"}})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/git/blobs",
                status_code=422,
                message="Validation Failed",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.publish_files(
            target=SEOMigrationGitHubPublishTarget(
                repo_owner="mhanson13",
                repo_name="tnmfire",
                branch="main",
                artifact_root="",
            ),
            files=[
                SEOMigrationGitHubPublishFile(
                    path="index.html",
                    content="<html><body>test</body></html>",
                    media_type="text/html",
                )
            ],
            commit_message="publish",
            dry_run=False,
        )
    assert exc_info.value.code == "github_contents_publish_failed"
    assert exc_info.value.code != "github_request_failed"
    assert exc_info.value.stage == "publish"


def test_dispatch_deploy_classifies_repo_not_found(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            )
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "repo_not_found"
    assert exc_info.value.stage == "repo_lookup"
    assert len(calls) == 1


def test_dispatch_deploy_classifies_workflow_not_found(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows/deploy-tnmfire-www-prod.yml",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "workflow_not_found"
    assert exc_info.value.stage == "workflow_lookup"
    assert len(calls) == 4


def test_dispatch_deploy_uses_workflow_file_path_identifier_when_provided(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(status=200, body=json.dumps({"workflow_runs": []})),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target_with_workflow_path(), dry_run=False)
    assert result.workflow_id == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert any(call[1].endswith("/actions/workflows/deploy-tnmfire-www-prod.yml/dispatches") for call in calls)
    assert any(
        "/actions/workflows/deploy-tnmfire-www-prod.yml/runs?event=workflow_dispatch&branch=main&per_page=10" in call[1]
        for call in calls
    )
    assert any(
        call[1].endswith("/actions/workflows/.github%2Fworkflows%2Fdeploy-tnmfire-www-prod.yml") for call in calls
    )


def test_dispatch_deploy_classifies_ref_invalid(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows/deploy-tnmfire-www-prod.yml/dispatches",
                status_code=422,
                message="No ref found for: main",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "branch_not_found_or_ref_invalid"
    assert exc_info.value.stage == "workflow_dispatch"
    assert len(calls) == 5


def test_dispatch_deploy_preflight_classifies_ref_invalid(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/branches/main",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "branch_not_found_or_ref_invalid"
    assert exc_info.value.stage == "ref_lookup"
    assert len(calls) == 2


def test_dispatch_deploy_classifies_workflow_dispatch_not_supported(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/workflows/deploy-tnmfire-www-prod.yml/dispatches",
                status_code=422,
                message="Workflow does not have 'workflow_dispatch' trigger",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "workflow_dispatch_not_supported"
    assert exc_info.value.stage == "workflow_dispatch"
    assert len(calls) == 5


def test_dispatch_deploy_classifies_workflow_not_dispatchable(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "disabled_manually",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "workflow_disabled"
    assert exc_info.value.stage == "workflow_lookup"
    assert len(calls) == 4


def test_dispatch_deploy_classifies_workflow_not_dispatchable_when_trigger_missing_on_ref(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    encoded_workflow = base64.b64encode(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  push:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: echo deploy\n"
        ).encode("utf-8")
    ).decode("ascii")
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": encoded_workflow,
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "workflow_dispatch_missing"
    assert exc_info.value.stage == "workflow_lookup"
    assert len(calls) == 4


def test_check_deploy_target_readiness_marks_workflow_conformant_when_managed_contract_markers_present(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    encoded_workflow = _encode_workflow_yaml(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - run: kubectl apply -f k8s\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": encoded_workflow,
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness.workflow_dispatch_ready is True
    assert readiness.workflow_conformance_checked is True
    assert readiness.workflow_conformance_status == "conformant"
    assert readiness.workflow_conformance_reasons == ()
    assert "required_deploy_markers" in str(readiness.workflow_conformance_evidence_summary or "")
    assert len(calls) == 4


def test_check_deploy_target_readiness_reports_workflow_integrity_match_with_valid_signature(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    unsigned_workflow = (
        "name: Deploy Site\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo deploy\n"
    )
    workflow_signature = _compute_managed_workflow_signature(workflow_yaml=unsigned_workflow)
    signed_workflow = f"# mbsrn-workflow-signature: {workflow_signature}\n{unsigned_workflow}"
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": _encode_workflow_yaml(signed_workflow),
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.workflow_integrity_status == "match"
    assert readiness.workflow_integrity_reason_code is None
    assert readiness.dispatch_service_availability is True
    assert len(calls) == 4


def test_check_deploy_target_readiness_reports_workflow_integrity_missing_without_signature(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    unsigned_workflow = (
        "name: Deploy Site\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo deploy\n"
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": _encode_workflow_yaml(unsigned_workflow),
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.workflow_integrity_status == "missing"
    assert readiness.workflow_integrity_reason_code == "managed_workflow_signature_missing"
    assert readiness.dispatch_service_availability is True
    assert len(calls) == 4


def test_check_deploy_target_readiness_reports_workflow_integrity_mismatch_for_modified_workflow(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    unsigned_workflow = (
        "name: Deploy Site\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo deploy\n"
    )
    mismatched_workflow = f"# mbsrn-workflow-signature: {'0' * 64}\n{unsigned_workflow}"
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": _encode_workflow_yaml(mismatched_workflow),
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.workflow_integrity_status == "mismatch"
    assert readiness.workflow_integrity_reason_code == "managed_workflow_signature_mismatch"
    assert readiness.dispatch_service_availability is True
    assert len(calls) == 4


def test_dispatch_deploy_allows_workflow_integrity_mismatch_without_blocking(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    unsigned_workflow = (
        "name: Deploy Site\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo deploy\n"
    )
    mismatched_workflow = f"# mbsrn-workflow-signature: {'0' * 64}\n{unsigned_workflow}"
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": _encode_workflow_yaml(mismatched_workflow),
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(status=200, body=json.dumps({"workflow_runs": []})),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)

    assert result.repo_owner == "mhanson13"
    assert result.repo_name == "tnmfire"
    assert any(call[1].endswith("/actions/workflows/deploy-tnmfire-www-prod.yml/dispatches") for call in calls)


def test_check_deploy_target_readiness_blocks_placeholder_workflow_as_not_production_ready(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    encoded_workflow = _encode_workflow_yaml(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Placeholder deploy\n"
            '        run: echo "Deploy step not yet implemented"\n'
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": encoded_workflow,
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.check_deploy_target_readiness(
            target=_dispatch_target(),
            allow_ref_repair=False,
            allow_workflow_repair=False,
            dry_run=False,
        )
    assert exc_info.value.code == "workflow_not_production_ready"
    assert exc_info.value.stage == "workflow_lookup"
    assert len(calls) == 4


def test_check_deploy_target_readiness_blocks_customize_before_rollout_placeholder_marker(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    encoded_workflow = _encode_workflow_yaml(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Provisioned workflow notice\n"
            '        run: echo "Deploy workflow (deploy-tnmfire-www-prod.yml) provisioned; customize before production rollout."\n'
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "base64",
                        "content": encoded_workflow,
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.check_deploy_target_readiness(
            target=_dispatch_target(),
            allow_ref_repair=False,
            allow_workflow_repair=False,
            dry_run=False,
        )
    assert exc_info.value.code == "workflow_not_production_ready"
    assert exc_info.value.stage == "workflow_lookup"
    assert len(calls) == 4


def test_check_deploy_target_readiness_classifies_unreadable_workflow_content_without_forcing_block(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "wfsha",
                        "encoding": "utf-8",
                        "content": "name: deploy",
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness.workflow_dispatch_ready is True
    assert readiness.workflow_conformance_checked is True
    assert readiness.workflow_conformance_status == "workflow_unreadable"
    assert readiness.workflow_conformance_reasons == ("workflow_file_content_unreadable",)
    assert readiness.workflow_conformance_evidence_summary == "workflow_file_content=unreadable"
    assert len(calls) == 4


def test_check_deploy_target_readiness_reports_aligned_namespace_for_managed_template(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness.kubernetes_namespace == "tnmfire"
    assert readiness.namespace_source == "repo_name"
    assert readiness.namespace_model_status == "aligned"
    assert readiness.workflow_namespace_aligned is True
    assert readiness.manifest_namespace_aligned is True
    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    assert len(calls) == 14


def test_check_deploy_target_readiness_reports_misaligned_namespace_for_managed_template(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest_wrong = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire-other\n"
        )
    )
    namespaced_manifest_wrong = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire-other\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest_wrong}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest_wrong}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest_wrong}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest_wrong}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest_wrong}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest_wrong}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest_wrong}
                ),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness.namespace_model_status == "misaligned"
    assert readiness.workflow_namespace_aligned is True
    assert readiness.manifest_namespace_aligned is False
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "target_configuration_invalid"
    assert len(calls) == 14


def test_check_deploy_target_readiness_flags_missing_cluster_name_configuration(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/variables/KUBERNETES_CLUSTER_NAME",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_LOCATION"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "GCP_PROJECT_ID"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/secrets/KUBERNETES_CLUSTER_NAME",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness.workflow_dispatch_ready is True
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "missing_cluster_name"
    assert readiness.workflow_conformance_status == "conformant"
    assert len(calls) == 15


def test_check_deploy_target_readiness_flags_missing_image_pull_secret_credentials(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config={
            "cluster_name": "mbsrn-cluster",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        managed_image_pull_secret_config={
            "private_image_auth_required": True,
            "git_userid_configured": False,
            "git_email_configured": False,
            "git_token_configured": False,
        },
    )
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "image_pull_secret_missing"
    details = readiness.managed_gke_config_details or {}
    assert details.get("image_pull_secret_name") == "ghcr-pull-secret"
    assert details.get("image_pull_secret_referenced") is True
    assert details.get("private_image_auth_required") is True
    assert details.get("private_image_credentials_available_in_control_plane") is False
    assert details.get("target_repo_secrets_not_required") is True
    assert details.get("image_pull_secret_not_provisioned") is True
    assert details.get("image_pull_secret_provisioning_unavailable") is True
    assert sorted(details.get("image_pull_secret_missing_fields") or []) == [
        "git_email",
        "git_token",
        "git_userid",
    ]
    assert not any("/actions/secrets/" in path for _, path in calls)


def test_check_deploy_target_readiness_flags_image_pull_secret_not_referenced(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    deployment_manifest_without_pull_secret = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": "sha-deployment",
                        "encoding": "base64",
                        "content": deployment_manifest_without_pull_secret,
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config={
            "cluster_name": "mbsrn-cluster",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        managed_image_pull_secret_config={
            "private_image_auth_required": True,
            "git_userid_configured": True,
            "git_email_configured": True,
            "git_token_configured": True,
        },
    )
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "image_pull_secret_not_referenced"
    details = readiness.managed_gke_config_details or {}
    assert details.get("image_pull_secret_name") == "ghcr-pull-secret"
    assert details.get("image_pull_secret_referenced") is False
    assert details.get("private_image_auth_required") is True
    assert details.get("private_image_credentials_available_in_control_plane") is True
    assert details.get("target_repo_secrets_not_required") is True
    assert details.get("image_pull_secret_not_provisioned") is True
    assert details.get("image_pull_secret_provisioning_unavailable") is False
    assert not any("/actions/secrets/" in path for _, path in calls)


def test_validate_managed_image_pull_secret_config_public_mode_allows_missing_git_credentials() -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    reason_code, missing_fields, _, details = publisher._validate_managed_image_pull_secret_config(
        managed_image_pull_secret_config={
            "private_image_auth_required": False,
            "git_userid_configured": False,
            "git_email_configured": False,
            "git_token_configured": False,
            "config_source": "control_plane_runtime",
        }
    )

    assert reason_code is None
    assert missing_fields == []
    assert details.get("image_pull_auth_mode") == "public"
    assert details.get("image_pull_secret_required") is False
    assert details.get("image_pull_secret_configured") is True
    assert details.get("private_image_auth_required") is False
    assert details.get("private_image_credentials_available_in_control_plane") is True
    assert details.get("target_repo_secrets_not_required") is True
    assert details.get("image_pull_secret_not_provisioned") is False
    assert details.get("image_pull_secret_provisioning_unavailable") is False


def test_validate_managed_image_pull_secret_config_private_mode_flags_control_plane_missing_credentials() -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    reason_code, missing_fields, _, details = publisher._validate_managed_image_pull_secret_config(
        managed_image_pull_secret_config={
            "private_image_auth_required": True,
            "git_userid_configured": True,
            "git_email_configured": False,
            "git_token_configured": False,
            "config_source": "control_plane_runtime",
        }
    )

    assert reason_code == "image_pull_secret_missing"
    assert missing_fields == ["git_email", "git_token"]
    assert details.get("private_image_auth_required") is True
    assert details.get("private_image_credentials_available_in_control_plane") is False
    assert details.get("target_repo_secrets_not_required") is True
    assert details.get("image_pull_secret_not_provisioned") is True
    assert details.get("image_pull_secret_provisioning_unavailable") is True


@pytest.mark.parametrize(
    ("missing_field", "expected_reason_code", "variable_name", "secret_name"),
    [
        (
            "cluster_name",
            "missing_cluster_name",
            "KUBERNETES_CLUSTER_NAME",
            "KUBERNETES_CLUSTER_NAME",
        ),
        (
            "cluster_location",
            "missing_cluster_location",
            "KUBERNETES_CLUSTER_LOCATION",
            "KUBERNETES_CLUSTER_LOCATION",
        ),
        (
            "project_id",
            "missing_gcp_project_id",
            "GCP_PROJECT_ID",
            "GCP_PROJECT_ID",
        ),
    ],
)
def test_check_deploy_target_readiness_uses_admin_managed_gke_config_first(
    monkeypatch,
    missing_field: str,
    expected_reason_code: str,
    variable_name: str,
    secret_name: str,
) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _http_error(
                f"https://api.github.com/repos/mhanson13/tnmfire/actions/variables/{variable_name}",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                f"https://api.github.com/repos/mhanson13/tnmfire/actions/secrets/{secret_name}",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    managed_gke_config = {
        "cluster_name": "mbsrn-cluster",
        "cluster_location": "us-central1",
        "project_id": "mbsrn-prod",
    }
    managed_gke_config[missing_field] = None
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config=managed_gke_config,
    )
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == expected_reason_code
    details = readiness.managed_gke_config_details or {}
    assert details.get("gke_config_resolution_source") in {"mixed_admin_and_repo_config", "missing_config"}
    resolution_details = details.get(f"{missing_field}_resolution_details")
    assert isinstance(resolution_details, list)
    assert "admin_config_missing" in resolution_details
    assert "repo_config_missing" in resolution_details


def test_check_deploy_target_readiness_resolves_managed_gke_config_from_admin_without_repo_fallback_calls(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config={
            "cluster_name": "mbsrn-cluster",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
    )
    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("gke_config_resolution_source") == "resolved_from_admin_config"
    assert details.get("deploy_auth_mode") == "control_plane_managed"
    assert details.get("target_repo_deploy_secret_required") is False
    assert details.get("target_repo_deploy_secret_name") is None
    assert details.get("target_repo_deploy_secret_present") is None
    assert all(
        not (
            method == "GET"
            and (
                "/actions/variables/KUBERNETES_CLUSTER_NAME" in url
                or "/actions/variables/KUBERNETES_CLUSTER_LOCATION" in url
                or "/actions/variables/GCP_PROJECT_ID" in url
                or "/actions/secrets/KUBERNETES_CLUSTER_NAME" in url
                or "/actions/secrets/KUBERNETES_CLUSTER_LOCATION" in url
                or "/actions/secrets/GCP_PROJECT_ID" in url
            )
        )
        for method, url in calls
    )
    assert len(calls) == 11


def test_check_deploy_target_readiness_blocks_when_target_repo_deploy_secret_is_missing(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "        with:\n"
            "          credentials_json: ${{ secrets.GCP_DEPLOY_KEY }}\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _http_error(
                "https://api.github.com/repos/acme/tnmfire-site/actions/secrets/GCP_DEPLOY_KEY",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config={
            "cluster_name": "mbsrn-cluster",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
    )
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "target_repo_deploy_secret_missing"
    details = readiness.managed_gke_config_details or {}
    assert details.get("deploy_auth_mode") == "target_repo_actions_secret"
    assert details.get("target_repo_deploy_secret_required") is True
    assert details.get("target_repo_deploy_secret_name") == "GCP_DEPLOY_KEY"
    assert details.get("target_repo_deploy_secret_present") is False
    assert any(method == "GET" and url.endswith("/actions/secrets/GCP_DEPLOY_KEY") for method, url in calls)


def test_check_deploy_target_readiness_resolves_managed_gke_config_from_repo_fallback_when_admin_missing(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_NAME"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_LOCATION"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "GCP_PROJECT_ID"})),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config={},
    )
    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("gke_config_resolution_source") == "resolved_from_repo_config"
    assert "resolved_from_repo_config" in (details.get("cluster_name_resolution_details") or [])
    assert all(
        not (
            method == "GET"
            and (
                "/actions/secrets/KUBERNETES_CLUSTER_NAME" in url
                or "/actions/secrets/KUBERNETES_CLUSTER_LOCATION" in url
                or "/actions/secrets/GCP_PROJECT_ID" in url
            )
        )
        for method, url in calls
    )
    assert len(calls) == 14


def test_check_deploy_target_readiness_treats_whitespace_admin_values_as_missing_and_uses_repo_fallback(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_NAME"})),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        managed_gke_config={
            "cluster_name": "   ",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
    )
    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("gke_config_resolution_source") == "mixed_admin_and_repo_config"
    cluster_resolution_details = details.get("cluster_name_resolution_details") or []
    assert "admin_config_missing" in cluster_resolution_details
    assert "resolved_from_repo_config" in cluster_resolution_details
    assert len(calls) == 12


def test_dispatch_deploy_classifies_token_not_authorized(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=403,
                message="Resource not accessible by integration",
            )
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert exc_info.value.code == "token_not_authorized"
    assert exc_info.value.stage == "repo_lookup"
    assert len(calls) == 1


def test_dispatch_deploy_uses_admin_managed_gke_config_for_readiness_and_dispatch(
    monkeypatch,
    caplog,
) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(status=200, body=json.dumps({"workflow_runs": []})),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
        ],
        calls,
    )
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(
        target=_dispatch_target(),
        dry_run=False,
        managed_gke_config={
            "cluster_name": "mbsrn-cluster",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
    )

    assert result.workflow_run_id is None
    assert all(
        not (
            method == "GET"
            and (
                "/actions/variables/KUBERNETES_CLUSTER_NAME" in url
                or "/actions/variables/KUBERNETES_CLUSTER_LOCATION" in url
                or "/actions/variables/GCP_PROJECT_ID" in url
                or "/actions/secrets/KUBERNETES_CLUSTER_NAME" in url
                or "/actions/secrets/KUBERNETES_CLUSTER_LOCATION" in url
                or "/actions/secrets/GCP_PROJECT_ID" in url
            )
        )
        for method, url in calls
    )
    readiness_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_dispatch_managed_gke_config_presence"' in record.msg
    ]
    assert readiness_logs
    assert '"effective_cluster_name_present": true' in readiness_logs[-1].msg
    assert '"effective_cluster_location_present": true' in readiness_logs[-1].msg
    assert '"effective_project_id_present": true' in readiness_logs[-1].msg


def test_dispatch_deploy_blocks_when_gke_config_missing_in_admin_and_repo_fallback(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/variables/KUBERNETES_CLUSTER_NAME",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/actions/secrets/KUBERNETES_CLUSTER_NAME",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.dispatch_deploy(
            target=_dispatch_target(),
            dry_run=False,
            managed_gke_config={
                "cluster_name": None,
                "cluster_location": "us-central1",
                "project_id": "mbsrn-prod",
            },
        )
    assert exc_info.value.code == "workflow_not_dispatchable"
    assert exc_info.value.stage == "workflow_lookup"
    assert any("/actions/variables/KUBERNETES_CLUSTER_NAME" in url for _, url in calls)
    assert any("/actions/secrets/KUBERNETES_CLUSTER_NAME" in url for _, url in calls)
    assert not any("/actions/variables/KUBERNETES_CLUSTER_LOCATION" in url for _, url in calls)
    assert not any("/actions/variables/GCP_PROJECT_ID" in url for _, url in calls)
    assert not any(method == "POST" and url.endswith("/dispatches") for method, url in calls)


def test_dispatch_deploy_uses_repo_fallback_when_admin_managed_gke_config_missing(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            "      - uses: google-github-actions/get-gke-credentials@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_NAME"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "KUBERNETES_CLUSTER_LOCATION"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "GCP_PROJECT_ID"})),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(status=200, body=json.dumps({"workflow_runs": []})),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
            _FakeHTTPResponse(status=200, body=json.dumps([])),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(
        target=_dispatch_target(),
        dry_run=False,
        managed_gke_config=None,
    )
    assert result.workflow_run_id is None
    assert any("/actions/variables/KUBERNETES_CLUSTER_NAME" in url for _, url in calls)
    assert any(method == "POST" and url.endswith("/dispatches") for method, url in calls)


def test_ensure_managed_site_static_ip_reuses_existing_address(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.149.170.250",
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key=json.dumps(
            {
                "type": "service_account",
                "client_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
                "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----",
            }
        ),
        dry_run=False,
    )

    assert result.static_ip_name == "site-web-preview-ip-tnmfire"
    assert result.static_ip_address == "34.149.170.250"
    assert result.static_ip_created is False
    assert result.gcp_project_id == "mbsrn-prod"
    assert result.result == "exists"
    assert result.gcp_credential_source == "service_account_json"
    assert result.gcp_principal_email == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        )
    ]


def test_ensure_managed_site_static_ip_refreshes_describe_when_address_missing(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.149.170.250",
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        dry_run=False,
    )

    assert result.static_ip_address == "34.149.170.250"
    assert result.result == "exists"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_creates_missing_address_before_dispatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "operation-1"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.160.224.212",
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        dry_run=False,
    )

    assert result.static_ip_name == "site-web-preview-ip-tnmfire"
    assert result.static_ip_address == "34.160.224.212"
    assert result.static_ip_created is True
    assert result.result == "created"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "POST",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
        ),
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_create_payload_includes_gcp_safe_ownership_labels(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    payloads: list[dict[str, object] | None] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-preview",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "operation-1"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-preview",
                        "address": "34.160.224.212",
                    }
                ),
            ),
        ],
        calls,
        payloads,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        preview_hostname="Preview.Site.MBSRN.com.",
        dry_run=False,
    )

    assert result.static_ip_created is True
    assert payloads == [
        None,
        {
            "name": "site-web-preview-ip-preview",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "labels": build_managed_site_static_ip_labels(
                repo_name="tnmfire",
                site_id="site-1",
                preview_hostname="Preview.Site.MBSRN.com.",
            ),
        },
        None,
    ]


def test_ensure_managed_site_static_ip_describes_again_when_created_payload_lacks_address(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "operation-1"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.160.224.212",
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        dry_run=False,
    )

    assert result.static_ip_name == "site-web-preview-ip-tnmfire"
    assert result.static_ip_address == "34.160.224.212"
    assert result.static_ip_created is True
    assert result.result == "created"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "POST",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
        ),
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_does_not_label_shared_preview_gateway_address_creation(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    payloads: list[dict[str, object] | None] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-preview-shared-ip",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "operation-1"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-preview-shared-ip",
                        "address": "34.160.224.212",
                    }
                ),
            ),
        ],
        calls,
        payloads,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        namespace_isolation_defaults={
            "managed_preview_endpoint": {
                "mode": "preview_shared_gateway",
                "shared_preview_static_ip_name": "site-preview-shared-ip",
            }
        },
        preview_hostname="tnmfire.site.mbsrn.com",
        dry_run=False,
    )

    assert result.static_ip_name == "site-preview-shared-ip"
    assert result.static_ip_created is True
    assert payloads == [
        None,
        {
            "name": "site-preview-shared-ip",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
        },
        None,
    ]


def test_ensure_managed_site_static_ip_handles_already_exists_race(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
                status_code=409,
                message="Already exists",
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.149.170.250",
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        dry_run=False,
    )

    assert result.static_ip_name == "site-web-preview-ip-tnmfire"
    assert result.static_ip_address == "34.149.170.250"
    assert result.static_ip_created is False
    assert result.result == "already_exists_after_race"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "POST",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
        ),
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_fails_when_address_missing_after_describe_refresh(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    describe_payloads = [
        _FakeHTTPResponse(
            status=200,
            body=json.dumps(
                {
                    "name": "site-web-preview-ip-tnmfire",
                }
            ),
        )
        for _ in range(8)
    ]
    _install_urlopen_stub(
        monkeypatch,
        [
            *describe_payloads,
            _FakeHTTPResponse(status=200, body=json.dumps({"items": [{"name": "site-web-preview-ip-tnmfire"}]})),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == "static_ip_provisioning_pending"
    assert exc_info.value.stage == "static_ip_provision"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("static_ip_error_category") == "prerequisite_pending"
    assert diagnostics.get("static_ip_operation") == "describe"
    assert diagnostics.get("static_ip_describe_attempts") == 8
    assert diagnostics.get("static_ip_list_fallback_attempted") is True
    assert diagnostics.get("static_ip_list_fallback_match_count") == 1
    assert diagnostics.get("static_ip_list_fallback_address_present") is False
    assert diagnostics.get("static_ip_list_fallback_response_keys") == ["items"]
    assert len(calls) == 9
    assert calls[0][0] == "GET"
    assert calls[-1] == (
        "GET",
        "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses?filter=name%20eq%20site-web-preview-ip-tnmfire&maxResults=2",
    )


def test_ensure_managed_site_static_ip_uses_list_fallback_when_single_match_has_address(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    describe_payloads = [
        _FakeHTTPResponse(
            status=200,
            body=json.dumps(
                {
                    "name": "site-web-preview-ip-tnmfire",
                }
            ),
        )
        for _ in range(8)
    ]
    _install_urlopen_stub(
        monkeypatch,
        [
            *describe_payloads,
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "items": [
                            {
                                "name": "site-web-preview-ip-tnmfire",
                                "address": "34.160.224.212",
                            }
                        ]
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key='{"type":"service_account"}',
        dry_run=False,
    )

    assert result.static_ip_name == "site-web-preview-ip-tnmfire"
    assert result.static_ip_address == "34.160.224.212"
    assert result.static_ip_created is False
    assert result.result == "exists"
    assert len(calls) == 9
    assert calls[-1] == (
        "GET",
        "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses?filter=name%20eq%20site-web-preview-ip-tnmfire&maxResults=2",
    )


def test_ensure_managed_site_static_ip_fails_closed_when_list_fallback_has_multiple_matches(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    describe_payloads = [
        _FakeHTTPResponse(
            status=200,
            body=json.dumps(
                {
                    "name": "site-web-preview-ip-tnmfire",
                }
            ),
        )
        for _ in range(8)
    ]
    _install_urlopen_stub(
        monkeypatch,
        [
            *describe_payloads,
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "items": [
                            {
                                "name": "site-web-preview-ip-tnmfire",
                                "address": "34.160.224.212",
                            },
                            {
                                "name": "site-web-preview-ip-tnmfire",
                                "address": "34.160.224.213",
                            },
                        ]
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_conflict"
    assert exc_info.value.stage == "static_ip_provision"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("static_ip_error_category") == "conflict"
    assert diagnostics.get("static_ip_error_code") == "address_ambiguous_after_retry"
    assert diagnostics.get("static_ip_operation") == "describe"
    assert diagnostics.get("static_ip_list_fallback_attempted") is True
    assert diagnostics.get("static_ip_list_fallback_match_count") == 2
    assert diagnostics.get("static_ip_list_fallback_address_present") is True
    assert diagnostics.get("static_ip_list_fallback_failure_code") == "multiple_matches"
    assert calls[-1] == (
        "GET",
        "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses?filter=name%20eq%20site-web-preview-ip-tnmfire&maxResults=2",
    )


def test_ensure_managed_site_static_ip_requires_project_config(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, [], calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_config_missing"
    assert exc_info.value.stage == "static_ip_provision"
    assert calls == []


def test_ensure_managed_site_static_ip_without_managed_deploy_email_uses_adc_path(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.160.224.212",
                    }
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_google_auth_default",
        lambda **kwargs: "token",
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_credential_principal",
        lambda **kwargs: ("adc_metadata_server", "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"),
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key=None,
        dry_run=False,
    )

    assert result.gcp_credential_source == "adc_metadata_server"
    assert result.gcp_principal_email == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert result.gcp_impersonated_service_account_email is None
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_uses_managed_deploy_impersonation_when_configured(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "name": "site-web-preview-ip-tnmfire",
                        "address": "34.160.224.212",
                    }
                ),
            ),
        ],
        calls,
    )
    captured_impersonation: dict[str, object] = {}

    def _capture_impersonation(**kwargs):
        captured_impersonation.update(kwargs)
        return "token"

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_via_impersonation",
        _capture_impersonation,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_credential_principal",
        lambda **kwargs: ("adc_metadata_server", "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"),
    )
    publisher = GitHubSEOMigrationPublisher(
        token="test-token",
        managed_deploy_service_account_email="mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com",
    )
    result = publisher.ensure_managed_site_static_ip(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        site_id="site-1",
        managed_gke_config={"project_id": "mbsrn-prod"},
        gcp_deploy_key=None,
        dry_run=False,
    )

    assert captured_impersonation.get("target_service_account_email") == (
        "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert result.gcp_credential_source == "managed_deploy_impersonation"
    assert result.gcp_principal_email == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert result.gcp_impersonated_service_account_email == ("mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com")
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_rejects_secret_like_managed_deploy_impersonation_value(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, [], calls)
    publisher = GitHubSEOMigrationPublisher(
        token="test-token",
        managed_deploy_service_account_email='{"type":"service_account","private_key":"secret"}',
    )
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key=None,
            dry_run=False,
        )

    assert exc_info.value.code == "managed_deploy_impersonation_config_invalid"
    assert exc_info.value.stage == "static_ip_provision"
    assert "private_key" not in (exc_info.value.safe_message or "").lower()
    assert "service-account email" in (exc_info.value.safe_message or "").lower()
    assert calls == []


def test_ensure_managed_site_static_ip_impersonation_permission_denied_is_classified(monkeypatch) -> None:
    def _raise_permission_denied(**kwargs):
        raise SEOMigrationGitHubPublisherError(
            code="managed_deploy_impersonation_permission_denied",
            safe_message=(
                "Managed deploy impersonation is not authorized. "
                "Grant roles/iam.serviceAccountTokenCreator for the configured managed deploy service account."
            ),
            stage=kwargs.get("stage", "static_ip_provision"),
            provider_message="PERMISSION_DENIED: iam.serviceAccounts.getAccessToken denied.",
        )

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_via_impersonation",
        _raise_permission_denied,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_credential_principal",
        lambda **kwargs: ("service_account_json", "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"),
    )
    publisher = GitHubSEOMigrationPublisher(
        token="test-token",
        managed_deploy_service_account_email="mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com",
    )
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key=json.dumps(
                {
                    "type": "service_account",
                    "client_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
                    "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----",
                }
            ),
            dry_run=False,
        )

    assert exc_info.value.code == "managed_deploy_impersonation_permission_denied"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("gcp_credential_source") == "managed_deploy_impersonation"
    assert diagnostics.get("gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert diagnostics.get("gcp_impersonated_service_account_email") == (
        "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert "private_key" not in json.dumps(diagnostics).lower()


def test_ensure_managed_site_static_ip_permission_failure_is_classified(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
                status_code=403,
                message="Forbidden",
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key=json.dumps(
                {
                    "type": "service_account",
                    "client_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
                    "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----",
                }
            ),
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_permission_denied"
    assert exc_info.value.stage == "static_ip_provision"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("static_ip_operation") == "create"
    assert diagnostics.get("static_ip_error_category") == "permission_denied"
    assert diagnostics.get("static_ip_error_code") == "http_403"
    assert diagnostics.get("static_ip_permission_hint")
    assert diagnostics.get("gcp_credential_source") == "service_account_json"
    assert diagnostics.get("gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert "private_key" not in json.dumps(diagnostics).lower()
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "POST",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
        ),
    ]


def test_ensure_managed_site_static_ip_permission_failure_during_describe_is_classified(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=403,
                message="PERMISSION_DENIED: Required 'compute.globalAddresses.get' permission.",
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_permission_denied"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("static_ip_operation") == "describe"
    assert diagnostics.get("static_ip_error_category") == "permission_denied"
    assert diagnostics.get("static_ip_error_code") == "PERMISSION_DENIED"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


@pytest.mark.parametrize(
    ("status_code", "message", "expected_reason_code", "expected_category", "expected_error_code"),
    [
        (
            400,
            "Invalid value for field 'resource.labels': 'mbsrn-preview-hostname'.",
            "managed_site_static_ip_provisioning_failed",
            "provisioning_failed",
            "http_400",
        ),
        (
            403,
            "SERVICE_DISABLED: Compute Engine API has not been used in project mbsrn-prod before.",
            "managed_site_static_ip_api_disabled",
            "api_disabled",
            "SERVICE_DISABLED",
        ),
        (
            403,
            "QUOTA_EXCEEDED: Quota exceeded for resource global addresses.",
            "managed_site_static_ip_quota_exceeded",
            "quota_exceeded",
            "QUOTA_EXCEEDED",
        ),
        (
            404,
            "Project not found for project mbsrn-prod.",
            "managed_site_static_ip_project_not_found",
            "project_not_found",
            "http_404",
        ),
        (
            500,
            "Unhandled backend failure while creating global address.",
            "managed_site_static_ip_provisioning_failed",
            "provisioning_failed",
            "http_500",
        ),
    ],
)
def test_ensure_managed_site_static_ip_failure_reason_codes_are_classified(
    monkeypatch,
    status_code: int,
    message: str,
    expected_reason_code: str,
    expected_category: str,
    expected_error_code: str,
) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
                status_code=status_code,
                message=message,
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == expected_reason_code
    assert exc_info.value.stage == "static_ip_provision"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("static_ip_operation") == "create"
    assert diagnostics.get("static_ip_error_category") == expected_category
    assert diagnostics.get("static_ip_error_code") == expected_error_code
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "POST",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
        ),
    ]


def test_ensure_managed_site_static_ip_conflict_when_race_cannot_be_reconciled(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
                status_code=409,
                message="Address already exists",
            ),
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_conflict"
    assert exc_info.value.stage == "static_ip_provision"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("static_ip_operation") == "describe_after_create"
    assert diagnostics.get("static_ip_error_category") == "conflict"
    assert calls == [
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
        (
            "POST",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
        ),
        (
            "GET",
            "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
        ),
    ]


def test_ensure_managed_site_static_ip_error_summary_redacts_secret_like_markers(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses/site-web-preview-ip-tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/addresses",
                status_code=403,
                message=(
                    "PERMISSION_DENIED: Required 'compute.globalAddresses.create'; "
                    "private_key=BEGIN PRIVATE KEY; access_token=token-value"
                ),
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_static_ip(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            site_id="site-1",
            managed_gke_config={"project_id": "mbsrn-prod"},
            gcp_deploy_key='{"type":"service_account"}',
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_permission_denied"
    diagnostics = exc_info.value.diagnostics or {}
    summary = str(diagnostics.get("static_ip_error_summary") or "").lower()
    assert "private_key" not in summary
    assert "access_token" not in summary
    assert "permission_denied" not in summary
    assert "managed site static ip provisioning" in summary


def test_ensure_managed_site_dns_uses_managed_deploy_impersonation_when_configured(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _dns_rrsets_response(name="tnmfire.site.mbsrn.com.", record_type="CNAME", rrdatas=None),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.160.224.212"],
                ttl=300,
            ),
        ],
        calls,
    )
    captured_impersonation: dict[str, object] = {}

    def _capture_impersonation(**kwargs):
        captured_impersonation.update(kwargs)
        return "token"

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_via_impersonation",
        _capture_impersonation,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_credential_principal",
        lambda **kwargs: ("adc_metadata_server", "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"),
    )
    publisher = GitHubSEOMigrationPublisher(
        token="test-token",
        managed_deploy_service_account_email="mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com",
    )
    result = publisher.ensure_managed_site_dns_a_record(
        preview_hostname="tnmfire.site.mbsrn.com",
        expected_ip_address="34.160.224.212",
        dns_managed_zone="sites",
        dns_project_id="mbsrn-prod",
        gcp_deploy_key=None,
        ttl=300,
        dry_run=False,
    )

    assert captured_impersonation.get("target_service_account_email") == (
        "mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com"
    )
    assert result.gcp_credential_source == "managed_deploy_impersonation"
    assert result.gcp_principal_email == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert result.gcp_impersonated_service_account_email == ("mbsrn-managed-deploy@mbsrn-prod.iam.gserviceaccount.com")
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
    ]


def test_ensure_managed_site_dns_creates_missing_record_before_dispatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _dns_rrsets_response(name="tnmfire.site.mbsrn.com.", record_type="CNAME", rrdatas=None),
            _dns_rrsets_response(name="tnmfire.site.mbsrn.com.", record_type="A", rrdatas=None),
            _FakeHTTPResponse(status=200, body=json.dumps({"id": "change-1", "status": "pending"})),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.160.224.212"],
                ttl=300,
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_dns_a_record(
        preview_hostname="tnmfire.site.mbsrn.com",
        expected_ip_address="34.160.224.212",
        dns_managed_zone="sites",
        dns_project_id="mbsrn-prod",
        gcp_deploy_key=json.dumps(
            {
                "type": "service_account",
                "client_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
                "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----",
            }
        ),
        ttl=300,
        dry_run=False,
    )

    assert result.dns_record_name == "tnmfire.site.mbsrn.com."
    assert result.dns_record_type == "A"
    assert result.dns_managed_zone == "sites"
    assert result.dns_project_id == "mbsrn-prod"
    assert result.dns_expected_ip == "34.160.224.212"
    assert result.dns_previous_ips == ()
    assert result.dns_created is True
    assert result.dns_updated is False
    assert result.dns_ttl == 300
    assert result.result == "created"
    assert result.gcp_credential_source == "service_account_json"
    assert result.gcp_principal_email == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
        (
            "POST",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/changes",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
    ]


def test_ensure_managed_site_dns_reuses_existing_correct_record(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _dns_rrsets_response(name="tnmfire.site.mbsrn.com.", record_type="CNAME", rrdatas=None),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.160.224.212"],
                ttl=300,
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_dns_a_record(
        preview_hostname="tnmfire.site.mbsrn.com",
        expected_ip_address="34.160.224.212",
        dns_managed_zone="sites",
        dns_project_id="mbsrn-prod",
        gcp_deploy_key='{"type":"service_account"}',
        ttl=300,
        dry_run=False,
    )

    assert result.dns_created is False
    assert result.dns_updated is False
    assert result.result == "exists"
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
    ]


def test_ensure_managed_site_dns_updates_old_and_multiple_ips(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _dns_rrsets_response(name="tnmfire.site.mbsrn.com.", record_type="CNAME", rrdatas=None),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.149.170.250", "34.149.170.251"],
                ttl=300,
            ),
            _FakeHTTPResponse(status=200, body=json.dumps({"id": "change-2", "status": "pending"})),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.160.224.212"],
                ttl=300,
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_dns_a_record(
        preview_hostname="tnmfire.site.mbsrn.com",
        expected_ip_address="34.160.224.212",
        dns_managed_zone="sites",
        dns_project_id="mbsrn-prod",
        gcp_deploy_key='{"type":"service_account"}',
        ttl=300,
        dry_run=False,
    )

    assert result.dns_created is False
    assert result.dns_updated is True
    assert result.dns_previous_ips == ("34.149.170.250", "34.149.170.251")
    assert result.result == "updated"
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
        (
            "POST",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/changes",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
    ]


def test_ensure_managed_site_dns_conflicting_cname_blocks_before_dispatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="CNAME",
                rrdatas=["legacy.example.net."],
                ttl=300,
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_dns_a_record(
            preview_hostname="tnmfire.site.mbsrn.com",
            expected_ip_address="34.160.224.212",
            dns_managed_zone="sites",
            dns_project_id="mbsrn-prod",
            gcp_deploy_key='{"type":"service_account"}',
            ttl=300,
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_dns_conflicting_record"
    assert exc_info.value.stage == "dns_provision"
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
    ]


def test_ensure_managed_site_dns_permission_denied_is_classified(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
                status_code=403,
                message="Forbidden",
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_dns_a_record(
            preview_hostname="tnmfire.site.mbsrn.com",
            expected_ip_address="34.160.224.212",
            dns_managed_zone="sites",
            dns_project_id="mbsrn-prod",
            gcp_deploy_key=json.dumps(
                {
                    "type": "service_account",
                    "client_email": "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com",
                    "private_key": "-----BEGIN PRIVATE KEY-----SECRET-----END PRIVATE KEY-----",
                }
            ),
            ttl=300,
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_dns_permission_denied"
    assert exc_info.value.stage == "dns_provision"
    diagnostics = exc_info.value.diagnostics or {}
    assert diagnostics.get("gcp_credential_source") == "service_account_json"
    assert diagnostics.get("gcp_principal_email") == "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"
    assert "private_key" not in json.dumps(diagnostics).lower()
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
    ]


def test_ensure_managed_site_dns_requires_config(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, [], calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_dns_a_record(
            preview_hostname="tnmfire.site.mbsrn.com",
            expected_ip_address="34.160.224.212",
            dns_managed_zone="",
            dns_project_id="mbsrn-prod",
            gcp_deploy_key='{"type":"service_account"}',
            ttl=300,
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_dns_config_missing"
    assert exc_info.value.stage == "dns_provision"
    assert calls == []


def test_ensure_managed_site_dns_requires_static_ip_address(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, [], calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_managed_site_dns_a_record(
            preview_hostname="tnmfire.site.mbsrn.com",
            expected_ip_address="",
            dns_managed_zone="sites",
            dns_project_id="mbsrn-prod",
            gcp_deploy_key='{"type":"service_account"}',
            ttl=300,
            dry_run=False,
        )

    assert exc_info.value.code == "managed_site_static_ip_address_missing"
    assert exc_info.value.stage == "static_ip_provision"
    assert calls == []


def test_ensure_managed_site_dns_transaction_conflict_retries_and_accepts_already_correct(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _dns_rrsets_response(name="tnmfire.site.mbsrn.com.", record_type="CNAME", rrdatas=None),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.149.170.250"],
                ttl=300,
            ),
            _http_error(
                "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/changes",
                status_code=409,
                message="Conflict",
            ),
            _dns_rrsets_response(
                name="tnmfire.site.mbsrn.com.",
                record_type="A",
                rrdatas=["34.160.224.212"],
                ttl=300,
            ),
        ],
        calls,
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_from_service_account_json",
        lambda **kwargs: "token",
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_managed_site_dns_a_record(
        preview_hostname="tnmfire.site.mbsrn.com",
        expected_ip_address="34.160.224.212",
        dns_managed_zone="sites",
        dns_project_id="mbsrn-prod",
        gcp_deploy_key='{"type":"service_account"}',
        ttl=300,
        dry_run=False,
    )

    assert result.dns_created is False
    assert result.dns_updated is False
    assert result.result == "already_correct_after_race"
    assert calls == [
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=CNAME",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
        (
            "POST",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/changes",
        ),
        (
            "GET",
            "https://dns.googleapis.com/dns/v1/projects/mbsrn-prod/managedZones/sites/rrsets?name=tnmfire.site.mbsrn.com.&type=A",
        ),
    ]


def _stub_managed_certificate_readiness_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    managed_certificate_payload: dict[str, object] | None,
) -> None:
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_credential_principal",
        lambda **kwargs: ("service_account_json", "mbsrn-api@mbsrn-prod.iam.gserviceaccount.com"),
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._resolve_google_access_token_for_managed_deploy_operations",
        lambda **kwargs: "token",
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._request_google_json",
        lambda **kwargs: {
            "endpoint": "34.111.22.11",
            "masterAuth": {"clusterCaCertificate": base64.b64encode(b"dummy-ca").decode("ascii")},
        },
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher.ssl.create_default_context",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._request_kubernetes_json",
        lambda **kwargs: managed_certificate_payload,
    )


def _build_managed_certificate_readiness_payload(
    *,
    domains: list[str],
    certificate_status: str,
    domain_status: str,
    labels: dict[str, str] | None = None,
) -> dict[str, object]:
    ownership_labels = github_publisher_module.build_managed_certificate_ownership_labels(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
    )
    if labels is not None:
        ownership_labels = dict(labels)
    return {
        "metadata": {
            "name": "site-web-preview-cert-tnmfire",
            "labels": ownership_labels,
        },
        "spec": {"domains": list(domains)},
        "status": {
            "certificateStatus": certificate_status,
            "domainStatus": [{"domain": domain, "status": domain_status} for domain in domains],
        },
    }


def test_check_managed_certificate_readiness_reports_missing_resource(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(
        monkeypatch,
        managed_certificate_payload=None,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.check_managed_certificate_readiness(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.managed_certificate_exists is False
    assert result.dispatch_service_reason_code == "managed_certificate_visibility_pending"
    assert result.managed_certificate_name.startswith("site-web-preview-cert-")


def test_ensure_managed_certificate_creates_missing_owned_resource(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(monkeypatch, managed_certificate_payload=None)
    kubernetes_requests: list[dict[str, object]] = []

    def _request_kubernetes_json(**kwargs):  # type: ignore[no-untyped-def]
        kubernetes_requests.append(dict(kwargs))
        if kwargs["method"] == "GET":
            return None
        return {
            "metadata": {"name": "site-web-preview-cert-tnmfire"},
            "status": {"certificateStatus": "PROVISIONING"},
        }

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._request_kubernetes_json",
        _request_kubernetes_json,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.ensure_managed_certificate(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.action == "created"
    assert result.readiness.managed_certificate_exists is True
    assert result.readiness.observed_managed_certificate_status == "PROVISIONING"
    namespace_create_request = next(
        request for request in kubernetes_requests if request["path"] == "/api/v1/namespaces"
    )
    assert namespace_create_request["method"] == "POST"
    assert namespace_create_request["payload"] == {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "tnmfire"},
    }
    create_request = kubernetes_requests[-1]
    assert create_request["method"] == "POST"
    assert create_request["path"] == "/apis/networking.gke.io/v1/namespaces/tnmfire/managedcertificates"
    payload = create_request["payload"]
    assert isinstance(payload, dict)
    assert payload["spec"] == {"domains": ["tnmfire.site.mbsrn.com"]}
    assert payload["metadata"]["labels"]["mbsrn.io/site-id"] == "site-1"


def test_ensure_managed_certificate_reuses_existing_namespace(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(monkeypatch, managed_certificate_payload=None)
    kubernetes_requests: list[dict[str, object]] = []

    def _request_kubernetes_json(**kwargs):  # type: ignore[no-untyped-def]
        kubernetes_requests.append(dict(kwargs))
        if kwargs["path"] == "/api/v1/namespaces/tnmfire":
            return {"metadata": {"name": "tnmfire"}}
        if kwargs["method"] == "GET":
            return None
        return {
            "metadata": {"name": "site-web-preview-cert-tnmfire"},
            "status": {"certificateStatus": "PROVISIONING"},
        }

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._request_kubernetes_json",
        _request_kubernetes_json,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.ensure_managed_certificate(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.action == "created"
    assert not any(request["path"] == "/api/v1/namespaces" for request in kubernetes_requests)


def test_check_managed_certificate_readiness_reports_provisioning_state(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(
        monkeypatch,
        managed_certificate_payload=_build_managed_certificate_readiness_payload(
            domains=["tnmfire.site.mbsrn.com"],
            certificate_status="PROVISIONING",
            domain_status="PROVISIONING",
        ),
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.check_managed_certificate_readiness(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.managed_certificate_exists is True
    assert result.certificate_domain_matches_expected is True
    assert result.observed_managed_certificate_status == "PROVISIONING"
    assert result.observed_managed_certificate_domain_status == "PROVISIONING"
    assert result.dispatch_service_reason_code == "tls_certificate_provisioning"


def test_check_managed_certificate_readiness_reports_active_state(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(
        monkeypatch,
        managed_certificate_payload=_build_managed_certificate_readiness_payload(
            domains=["tnmfire.site.mbsrn.com"],
            certificate_status="ACTIVE",
            domain_status="ACTIVE",
        ),
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.check_managed_certificate_readiness(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.managed_certificate_exists is True
    assert result.certificate_domain_matches_expected is True
    assert result.dispatch_service_reason_code is None


def test_workflow_dispatch_identifier_type_normalizes_numeric_ids_to_workflow_id() -> None:
    assert github_publisher_module._workflow_dispatch_identifier_type("12345") == "workflow_id"
    assert github_publisher_module._workflow_dispatch_identifier_type("deploy-prod.yml") == "workflow_file_path"


def test_check_managed_certificate_readiness_reports_domain_mismatch(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(
        monkeypatch,
        managed_certificate_payload=_build_managed_certificate_readiness_payload(
            domains=["wrong.site.mbsrn.com"],
            certificate_status="ACTIVE",
            domain_status="ACTIVE",
        ),
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.check_managed_certificate_readiness(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.managed_certificate_exists is True
    assert result.certificate_domain_matches_expected is False
    assert result.dispatch_service_reason_code == "certificate_domain_mismatch"


def test_check_managed_certificate_readiness_reports_ownership_unverified(monkeypatch) -> None:
    _stub_managed_certificate_readiness_dependencies(
        monkeypatch,
        managed_certificate_payload=_build_managed_certificate_readiness_payload(
            domains=["tnmfire.site.mbsrn.com"],
            certificate_status="ACTIVE",
            domain_status="ACTIVE",
            labels={
                "app.kubernetes.io/managed-by": "mbsrn",
                "app.kubernetes.io/name": "site-web",
                "mbsrn.io/repo": "another-site",
                "mbsrn.io/site-id": "site-1",
                "mbsrn.io/preview-hostname": "tnmfire.site.mbsrn.com",
            },
        ),
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")

    result = publisher.check_managed_certificate_readiness(
        repo_name="mhanson13/tnmfire",
        site_id="site-1",
        preview_hostname="tnmfire.site.mbsrn.com",
        kubernetes_namespace="tnmfire",
        managed_gke_config={
            "cluster_name": "cluster-1",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
        gcp_deploy_key='{"type":"service_account"}',
    )

    assert result.managed_certificate_exists is True
    assert result.certificate_domain_matches_expected is True
    assert result.dispatch_service_reason_code == "managed_certificate_ownership_unverified"


def test_dispatch_deploy_captures_workflow_output_live_url_from_completion_metadata(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    created_at = utc_now().isoformat()
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 99991,
                                "status": "completed",
                                "conclusion": "success",
                                "event": "workflow_dispatch",
                                "head_branch": "main",
                                "created_at": created_at,
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps([{"id": 12345}])),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    [
                        {
                            "state": "success",
                            "created_at": created_at,
                            "log_url": "https://github.com/mhanson13/tnmfire/actions/runs/99991",
                            "environment_url": "https://live.tnmfire.com",
                        }
                    ]
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert result.workflow_run_id == 99991
    assert result.workflow_run_status == "completed"
    assert result.workflow_run_conclusion == "success"
    assert result.workflow_output == {"live_url": "https://live.tnmfire.com"}
    assert len(calls) == 8


def test_dispatch_deploy_does_not_capture_unrelated_deployment_status_url(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    created_at = utc_now().isoformat()
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 99993,
                                "status": "completed",
                                "conclusion": "success",
                                "event": "workflow_dispatch",
                                "head_branch": "main",
                                "created_at": created_at,
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(status=200, body=json.dumps([{"id": 12346, "created_at": created_at}])),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    [
                        {
                            "state": "success",
                            "created_at": created_at,
                            "log_url": "https://github.com/mhanson13/tnmfire/actions/runs/11111",
                            "environment_url": "https://stale-or-unrelated.example",
                        }
                    ]
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert result.workflow_run_id == 99993
    assert result.workflow_run_status == "completed"
    assert result.workflow_run_conclusion == "success"
    assert result.workflow_output is None
    assert len(calls) == 8


def test_dispatch_deploy_without_completion_output_keeps_workflow_output_empty(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    created_at = utc_now().isoformat()
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 99992,
                                "status": "in_progress",
                                "conclusion": None,
                                "event": "workflow_dispatch",
                                "head_branch": "main",
                                "created_at": created_at,
                            }
                        ]
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert result.workflow_run_id == 99992
    assert result.workflow_run_status == "in_progress"
    assert result.workflow_run_conclusion is None
    assert result.workflow_output is None
    assert len(calls) == 6


def test_dispatch_deploy_classifies_failed_run_step_for_diagnostics(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    created_at = utc_now().isoformat()
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 99994,
                                "status": "completed",
                                "conclusion": "failure",
                                "event": "workflow_dispatch",
                                "head_branch": "main",
                                "created_at": created_at,
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "deploy",
                                "conclusion": "failure",
                                "steps": [
                                    {"name": "Checkout repository", "conclusion": "success"},
                                    {"name": "Resolve live URL from ingress status", "conclusion": "failure"},
                                ],
                            }
                        ]
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert result.workflow_run_id == 99994
    assert result.workflow_run_status == "completed"
    assert result.workflow_run_conclusion == "failure"
    assert result.workflow_output is not None
    assert result.workflow_output.get("deploy_https_ready") == "false"
    assert result.workflow_output.get("https_probe_error_summary") == (
        "reason=https_probe_failed_after_control_plane_ready;detail=probe_attempted_without_error_summary"
    )
    assert result.workflow_run_failure_reason_code == "ingress_endpoint_not_ready"
    assert result.workflow_run_failure_stage == "ingress_evidence"
    assert result.workflow_run_failure_step == "Resolve live URL from ingress status"
    assert len(calls) == 7


def test_dispatch_deploy_classifies_cloudsql_invalid_state_from_job_logs(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    created_at = utc_now().isoformat()
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 99001,
                                "status": "completed",
                                "conclusion": "failure",
                                "event": "workflow_dispatch",
                                "head_branch": "main",
                                "created_at": created_at,
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "id": 99123,
                                "name": "deploy",
                                "conclusion": "failure",
                                "steps": [
                                    {"name": "Checkout repository", "conclusion": "success"},
                                    {"name": "Run Alembic migrations (pre-rollout gate)", "conclusion": "failure"},
                                ],
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=(
                    "cloud-sql-proxy started and accepting connections\n"
                    "fetch ephemeral cert failed for instance project:region:db Error 409 invalidState\n"
                    "postgres connection closed unexpectedly\n"
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert result.workflow_run_id == 99001
    assert result.workflow_run_status == "completed"
    assert result.workflow_run_conclusion == "failure"
    assert result.workflow_run_failure_reason_code == "cloudsql_instance_invalid_state"
    assert result.workflow_run_failure_stage == "manifest_apply"
    assert result.workflow_run_failure_step == "Run Alembic migrations (pre-rollout gate)"
    assert any("/actions/jobs/99123/logs" in call[1] for call in calls)


def test_dispatch_deploy_classifies_cloudsql_inspection_failed_from_job_logs(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    created_at = utc_now().isoformat()
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "wfsha"})),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _FakeHTTPResponse(status=204),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "workflow_runs": [
                            {
                                "id": 99002,
                                "status": "completed",
                                "conclusion": "failure",
                                "event": "workflow_dispatch",
                                "head_branch": "main",
                                "created_at": created_at,
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "id": 99124,
                                "name": "deploy",
                                "conclusion": "failure",
                                "steps": [
                                    {"name": "Checkout repository", "conclusion": "success"},
                                    {"name": "Preflight Cloud SQL instance state", "conclusion": "failure"},
                                ],
                            }
                        ]
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=(
                    "::warning::cloudsql_instance_inspection_failed preflight attempt=1/3 "
                    "describe_failed=true state=unknown detail=permission_denied\n"
                    "deploy_runtime_reason_code=cloudsql_instance_inspection_failed\n"
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.dispatch_deploy(target=_dispatch_target(), dry_run=False)
    assert result.workflow_run_id == 99002
    assert result.workflow_run_status == "completed"
    assert result.workflow_run_conclusion == "failure"
    assert result.workflow_run_failure_reason_code == "cloudsql_instance_inspection_failed"
    assert result.workflow_run_failure_stage == "manifest_apply"
    assert result.workflow_run_failure_step == "Preflight Cloud SQL instance state"
    assert any("/actions/jobs/99124/logs" in call[1] for call in calls)


def test_refresh_deploy_run_status_classifies_failed_run_step(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "id": 777001,
                        "status": "completed",
                        "conclusion": "failure",
                        "created_at": "2026-04-16T11:00:00+00:00",
                        "updated_at": "2026-04-16T11:03:00+00:00",
                    }
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "deploy",
                                "conclusion": "failure",
                                "steps": [
                                    {"name": "Authenticate to GCP", "conclusion": "failure"},
                                ],
                            }
                        ]
                    }
                ),
            ),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.refresh_deploy_run_status(
        target=_dispatch_target(),
        workflow_run_id=777001,
        dispatched_at="2026-04-16T11:00:00+00:00",
    )
    assert result.workflow_run_id == 777001
    assert result.workflow_run_status == "completed"
    assert result.workflow_run_conclusion == "failure"
    assert result.workflow_output is None
    assert result.workflow_run_failure_reason_code == "gcp_auth_failed"
    assert result.workflow_run_failure_stage == "gcp_auth"
    assert result.workflow_run_failure_step == "Authenticate to GCP"
    assert len(calls) == 2


def test_probe_live_runtime_https_marks_success_with_https_200(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(
                status=200,
                body="",
                url="https://lars-construction.site.mbsrn.com/",
            )
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.probe_live_runtime_https(
        probe_url="https://lars-construction.site.mbsrn.com/",
    )

    assert isinstance(result, SEOMigrationGitHubLiveRuntimeProbeResult)
    assert result.host_reachable is True
    assert result.host_reachability_scheme == "https"
    assert result.deploy_https_ready is True
    assert result.cert_identity_valid is True
    assert result.https_probe_status_code == 200
    assert result.https_probe_error_summary is None
    assert result.live_url == "https://lars-construction.site.mbsrn.com/"
    assert len(calls) == 1


def test_probe_live_runtime_https_classifies_timeout(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _stub(request, timeout=None):  # type: ignore[no-untyped-def]
        del timeout
        calls.append((request.get_method(), request.full_url))
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.probe_live_runtime_https(
        probe_url="https://lars-construction.site.mbsrn.com/",
    )

    assert isinstance(result, SEOMigrationGitHubLiveRuntimeProbeResult)
    assert result.host_reachable is False
    assert result.deploy_https_ready is False
    assert result.cert_identity_valid is None
    assert result.https_probe_status_code is None
    assert "reason=https_probe_timeout" in str(result.https_probe_error_summary or "")
    assert len(calls) == 1


def test_classify_cloudsql_proxy_failure_prefers_specific_dns_sub_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "\n".join(
            [
                "deploy_runtime_reason_code=dns_record_mismatch",
                "deploy_runtime_reason_code=dns_points_to_old_ingress_ip",
            ]
        )
    )

    assert reason_code == "dns_points_to_old_ingress_ip"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_failed_not_visible_to_dns_context_when_present() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "\n".join(
            [
                "deploy_runtime_reason_code=managed_certificate_failed_not_visible",
                "deploy_runtime_reason_code=dns_record_mismatch",
            ]
        )
    )

    assert reason_code == "dns_record_mismatch"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_tls_provisioning_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=tls_certificate_provisioning"
    )

    assert reason_code == "tls_certificate_provisioning"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_managed_certificate_provisioning_to_tls_provisioning() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=managed_certificate_provisioning"
    )

    assert reason_code == "tls_certificate_provisioning"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_managed_certificate_pending_to_tls_provisioning() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "\n".join(
            [
                "backend health: HEALTHY",
                "deploy_runtime_reason_code=managed_certificate_pending",
            ]
        )
    )

    assert reason_code == "tls_certificate_provisioning"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_https_probe_failed_to_control_plane_ready_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=https_probe_failed"
    )

    assert reason_code == "https_probe_failed_after_control_plane_ready"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_https_probe_timeout_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=https_probe_timeout"
    )

    assert reason_code == "https_probe_timeout"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_https_probe_empty_reply_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=https_probe_empty_reply"
    )

    assert reason_code == "https_probe_empty_reply"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_https_probe_not_attempted_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=https_probe_not_attempted"
    )

    assert reason_code == "https_probe_not_attempted"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_runtime_replace_failed_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=managed_site_runtime_replace_failed"
    )

    assert reason_code == "managed_site_runtime_replace_failed"
    assert failure_stage == "workflow_execution"


def test_classify_cloudsql_proxy_failure_maps_runtime_service_missing_after_apply_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "\n".join(
            [
                "deploy_runtime_reason_code=managed_site_runtime_replace_failed",
                "deploy_runtime_reason_code=runtime_service_missing_after_apply",
            ]
        )
    )

    assert reason_code == "runtime_service_missing_after_apply"
    assert failure_stage == "ingress_verify"


def test_classify_cloudsql_proxy_failure_maps_runtime_managed_certificate_missing_after_apply_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=runtime_managed_certificate_missing_after_apply"
    )

    assert reason_code == "runtime_managed_certificate_missing_after_apply"
    assert failure_stage == "ingress_verify"


def test_classify_cloudsql_proxy_failure_maps_certificate_domain_mismatch_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=certificate_domain_mismatch"
    )

    assert reason_code == "certificate_domain_mismatch"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_stale_managed_certificate_present_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=stale_managed_certificate_present"
    )

    assert reason_code == "stale_managed_certificate_present"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_managed_certificate_ownership_unverified_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=managed_certificate_ownership_unverified"
    )

    assert reason_code == "managed_certificate_ownership_unverified"
    assert failure_stage == "ingress_evidence"


def test_extract_resolve_live_url_state_from_log_text_parses_sanitized_probe_details() -> None:
    state = _extract_resolve_live_url_state_from_log_text(
        "\n".join(
            [
                "resolve_live_url_state_host_reachable=false",
                "resolve_live_url_state_host_reachability_scheme=https",
                (
                    "resolve_live_url_state_https_probe_error_summary="
                    "reason=https_probe_timeout;exit_code=28;status=000;"
                    "detail=connection timed out while waiting for headers"
                ),
                "resolve_live_url_state_deploy_https_ready=false",
                "resolve_live_url_state_preview_https_status=502",
                "resolve_live_url_state_gce_backend_health_status=HEALTHY",
                "resolve_live_url_state_service_probe_status=ok",
                "resolve_live_url_state_endpoint_probe_status=ok",
                "resolve_live_url_state_runtime_probe_status=ingress_or_edge_convergence",
                "resolve_live_url_state_pod_restart_detected=false",
            ]
        )
    )

    assert state.get("host_reachable") == "false"
    assert state.get("host_reachability_scheme") == "https"
    assert state.get("deploy_https_ready") == "false"
    assert state.get("preview_https_status") == "502"
    assert state.get("gce_backend_health_status") == "HEALTHY"
    assert state.get("service_probe_status") == "ok"
    assert state.get("endpoint_probe_status") == "ok"
    assert state.get("runtime_probe_status") == "ingress_or_edge_convergence"
    assert state.get("pod_restart_detected") == "false"
    assert "https_probe_timeout" in str(state.get("https_probe_error_summary") or "")
    assert len(str(state.get("https_probe_error_summary") or "")) <= 240


def test_extract_runtime_failure_state_from_log_text_captures_reason_presence_and_template_marker() -> None:
    state = github_publisher_module._extract_runtime_failure_state_from_log_text(
        "\n".join(
            [
                "deploy_runtime_reason_code=https_probe_timeout",
                "resolve_live_url_state_mbsrn_managed_deploy_template_version=site_repo_template_v1",
            ]
        )
    )

    assert state.get("deploy_runtime_reason_code_present") == "true"
    assert state.get("managed_deploy_template_marker_present") == "true"
    assert state.get("mbsrn_managed_deploy_template_version") == "site_repo_template_v1"


def test_resolve_workflow_run_failure_details_falls_back_to_runtime_unknown_when_marker_present(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    target = _dispatch_target()

    def _fake_request_json(*, method, path, expected_statuses=(200,), **kwargs):  # type: ignore[no-untyped-def]
        del expected_statuses, kwargs
        assert method == "GET"
        if "/actions/runs/123/jobs" in path:
            return {
                "jobs": [
                    {
                        "id": 456,
                        "name": "deploy",
                        "conclusion": "failure",
                        "steps": [
                            {"name": "Resolve live URL from ingress status", "conclusion": "failure"},
                        ],
                    }
                ]
            }
        raise AssertionError(f"Unexpected JSON path: {path}")

    def _fake_request_text(*, method, path, expected_statuses=(200,), **kwargs):  # type: ignore[no-untyped-def]
        del expected_statuses, kwargs
        assert method == "GET"
        assert path.endswith("/actions/jobs/456/logs")
        return "\n".join(
            [
                "Error: Process completed with exit code 1.",
                "resolve_live_url_state_mbsrn_managed_deploy_template_version=site_repo_template_v1",
            ]
        )

    monkeypatch.setattr(publisher, "_request_json", _fake_request_json)
    monkeypatch.setattr(publisher, "_request_text", _fake_request_text)

    reason_code, failure_stage, failed_step_name, workflow_output = publisher._resolve_workflow_run_failure_details(
        target=target,
        workflow_run_id=123,
        workflow_run_status="completed",
        workflow_run_conclusion="failure",
    )

    assert reason_code == "runtime_readiness_unknown_failure"
    assert failure_stage == "ingress_evidence"
    assert failed_step_name == "Resolve live URL from ingress status"
    assert workflow_output is not None
    assert workflow_output.get("deploy_runtime_reason_message") == (
        "Managed-site runtime readiness failed before a precise reason was recorded."
    )
    assert workflow_output.get("deploy_runtime_reason_code_present") == "false"
    assert workflow_output.get("managed_deploy_template_marker_present") == "true"
    assert workflow_output.get("mbsrn_managed_deploy_template_version") == "site_repo_template_v1"


def test_resolve_workflow_run_failure_details_falls_back_to_template_stale_when_marker_missing(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    target = _dispatch_target()

    def _fake_request_json(*, method, path, expected_statuses=(200,), **kwargs):  # type: ignore[no-untyped-def]
        del expected_statuses, kwargs
        assert method == "GET"
        if "/actions/runs/123/jobs" in path:
            return {
                "jobs": [
                    {
                        "id": 456,
                        "name": "deploy",
                        "conclusion": "failure",
                        "steps": [
                            {"name": "Resolve live URL from ingress status", "conclusion": "failure"},
                        ],
                    }
                ]
            }
        raise AssertionError(f"Unexpected JSON path: {path}")

    def _fake_request_text(*, method, path, expected_statuses=(200,), **kwargs):  # type: ignore[no-untyped-def]
        del expected_statuses, kwargs
        assert method == "GET"
        assert path.endswith("/actions/jobs/456/logs")
        return "Error: Process completed with exit code 1."

    monkeypatch.setattr(publisher, "_request_json", _fake_request_json)
    monkeypatch.setattr(publisher, "_request_text", _fake_request_text)

    reason_code, failure_stage, failed_step_name, workflow_output = publisher._resolve_workflow_run_failure_details(
        target=target,
        workflow_run_id=123,
        workflow_run_status="completed",
        workflow_run_conclusion="failure",
    )

    assert reason_code == "managed_deploy_workflow_template_stale"
    assert failure_stage == "ingress_evidence"
    assert failed_step_name == "Resolve live URL from ingress status"
    assert workflow_output is not None
    assert (
        "reprovision target workflow template and retry deploy"
        in str(workflow_output.get("deploy_runtime_reason_message") or "").lower()
    )
    assert workflow_output.get("deploy_runtime_reason_code_present") == "false"
    assert workflow_output.get("managed_deploy_template_marker_present") == "false"


def test_derive_https_probe_error_summary_for_failure_maps_dns_reason() -> None:
    summary = _derive_https_probe_error_summary_for_failure(
        reason_code="dns_record_mismatch",
        failure_stage="ingress_evidence",
    )

    assert summary == "reason=dns_not_ready;detail=dns_record_not_aligned_with_expected_ingress_target"


def test_derive_https_probe_error_summary_for_failure_maps_timeout_reason() -> None:
    summary = _derive_https_probe_error_summary_for_failure(
        reason_code="https_probe_timeout",
        failure_stage="ingress_evidence",
    )

    assert summary == "reason=https_probe_timeout;detail=https_probe_timed_out"


def test_derive_https_probe_error_summary_for_failure_maps_tls_provisioning_reason() -> None:
    summary = _derive_https_probe_error_summary_for_failure(
        reason_code="tls_certificate_provisioning",
        failure_stage="ingress_evidence",
    )

    assert (
        summary == "reason=managed_certificate_provisioning;detail=managed certificate/domain status still PROVISIONING"
    )


def test_derive_https_probe_error_summary_for_failure_maps_missing_managed_certificate_reason() -> None:
    summary = _derive_https_probe_error_summary_for_failure(
        reason_code="runtime_managed_certificate_missing_after_apply",
        failure_stage="ingress_evidence",
    )

    assert summary == "reason=cert_not_ready;detail=certificate_identity_or_status_not_ready"


def test_derive_https_probe_error_summary_for_failure_maps_ownership_unverified_reason() -> None:
    summary = _derive_https_probe_error_summary_for_failure(
        reason_code="managed_certificate_ownership_unverified",
        failure_stage="ingress_evidence",
    )

    assert summary == "reason=cert_not_ready;detail=certificate_identity_or_status_not_ready"


def test_derive_https_probe_error_summary_for_failure_falls_back_for_ingress_stage_unknown_reason() -> None:
    summary = _derive_https_probe_error_summary_for_failure(
        reason_code="unknown_ingress_reason",
        failure_stage="ingress_evidence",
    )

    assert summary == "reason=https_probe_failed_after_control_plane_ready;detail=probe_attempted_without_error_summary"


def test_resolve_workflow_run_failure_details_backfills_blank_probe_summary_from_log_reason(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    target = _dispatch_target()

    def _fake_request_json(*, method, path, expected_statuses=(200,), **kwargs):  # type: ignore[no-untyped-def]
        del expected_statuses, kwargs
        assert method == "GET"
        if "/actions/runs/123/jobs" in path:
            return {
                "jobs": [
                    {
                        "id": 456,
                        "name": "deploy",
                        "conclusion": "failure",
                        "steps": [
                            {"name": "Unknown deploy failure step", "conclusion": "failure"},
                        ],
                    }
                ]
            }
        raise AssertionError(f"Unexpected JSON path: {path}")

    def _fake_request_text(*, method, path, expected_statuses=(200,), **kwargs):  # type: ignore[no-untyped-def]
        del expected_statuses, kwargs
        assert method == "GET"
        assert path.endswith("/actions/jobs/456/logs")
        return "\n".join(
            [
                "deploy_runtime_reason_code=https_probe_timeout",
                "resolve_live_url_state_host_reachable=false",
                "resolve_live_url_state_deploy_https_ready=false",
                "resolve_live_url_state_https_probe_error_summary=",
            ]
        )

    monkeypatch.setattr(publisher, "_request_json", _fake_request_json)
    monkeypatch.setattr(publisher, "_request_text", _fake_request_text)

    reason_code, failure_stage, failed_step_name, workflow_output = publisher._resolve_workflow_run_failure_details(
        target=target,
        workflow_run_id=123,
        workflow_run_status="completed",
        workflow_run_conclusion="failure",
    )

    assert reason_code == "https_probe_timeout"
    assert failure_stage == "ingress_evidence"
    assert failed_step_name == "Unknown deploy failure step"
    assert workflow_output is not None
    assert workflow_output.get("deploy_https_ready") == "false"
    assert workflow_output.get("host_reachable") == "false"
    assert workflow_output.get("https_probe_error_summary") == "reason=https_probe_timeout;detail=https_probe_timed_out"


def test_classify_cloudsql_proxy_failure_maps_managed_site_static_ip_missing_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=managed_site_static_ip_missing"
    )

    assert reason_code == "managed_site_static_ip_missing"
    assert failure_stage == "ingress_verify"


def test_classify_cloudsql_proxy_failure_maps_expected_static_ip_not_bound_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=expected_static_ip_not_bound_to_ingress"
    )

    assert reason_code == "expected_static_ip_not_bound_to_ingress"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_prefers_in_cluster_probe_timeout_over_generic_curl_failure() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "\n".join(
            [
                "deploy_runtime_reason_code=service_endpoint_unhealthy",
                "deploy_runtime_reason_code=in_cluster_service_curl_failed_after_retries",
                "deploy_runtime_reason_code=in_cluster_service_probe_timeout",
                "deploy_runtime_reason_code=in_cluster_service_curl_failed",
            ]
        )
    )

    assert reason_code == "in_cluster_service_probe_timeout"
    assert failure_stage == "rollout_verify"


def test_classify_cloudsql_proxy_failure_maps_network_policy_probe_hint_reason() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=network_policy_may_block_service_probe"
    )

    assert reason_code == "network_policy_may_block_service_probe"
    assert failure_stage == "rollout_verify"


def test_classify_cloudsql_proxy_failure_maps_ingress_neg_convergence_to_ingress_evidence_stage() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=ingress_neg_convergence_pending"
    )

    assert reason_code == "ingress_neg_convergence_pending"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_ingress_status_ip_stale_advisory_to_ingress_evidence_stage() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=ingress_status_ip_stale_or_mismatched"
    )

    assert reason_code == "ingress_status_ip_stale_or_mismatched"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_pre_shared_metadata_mismatch_to_ingress_evidence_stage() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=pre_shared_cert_metadata_mismatch"
    )

    assert reason_code == "pre_shared_cert_metadata_mismatch"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_managed_certificate_metadata_unavailable_advisory() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=managed_certificate_metadata_unavailable"
    )

    assert reason_code == "managed_certificate_metadata_unavailable"
    assert failure_stage == "ingress_evidence"


def test_classify_cloudsql_proxy_failure_maps_managed_certificate_domain_drift_repair_failed() -> None:
    reason_code, failure_stage = _classify_cloudsql_proxy_failure_from_log_text(
        "deploy_runtime_reason_code=managed_certificate_domain_drift_repair_failed"
    )

    assert reason_code == "managed_certificate_domain_drift_repair_failed"
    assert failure_stage == "ingress_evidence"


def test_ensure_deploy_workflow_creates_missing_file_and_verifies_presence(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, _managed_provisioning_responses(), calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )
    assert result.provisioned is True
    assert result.workflow_path == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert result.commit_sha == "verified-9"
    assert result.kubernetes_namespace == "tnmfire"
    assert result.namespace_source == "repo_name"
    assert result.namespace_model_status == "aligned"
    assert result.managed_manifest_paths == (
        "k8s/namespace.yaml",
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
        "k8s/managedcertificate.yaml",
        "k8s/frontendconfig.yaml",
        "k8s/backendconfig.yaml",
    )
    assert result.managed_resource_quota_expected is False
    assert result.managed_resource_quota_present is None
    assert result.managed_limit_range_expected is False
    assert result.managed_limit_range_present is None
    assert result.managed_network_policy_expected is False
    assert result.managed_network_policy_present is None
    assert result.managed_namespace_policies_aligned is True
    assert result.managed_workflow_outcome == "managed_workflow_created"
    assert len(calls) == 33
    assert calls[0][1].endswith("/repos/mhanson13/tnmfire")
    assert calls[1][1].endswith("/repos/mhanson13/tnmfire")
    assert calls[2][1].endswith("/repos/mhanson13/tnmfire/git/ref/heads/main")
    assert calls[3][1].endswith("/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main")
    assert calls[4][1].endswith("/repos/mhanson13/tnmfire/branches/main")
    assert calls[5][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main")
    assert calls[6][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
    assert any(call[1].endswith("/contents/k8s/namespace.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/deployment.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/service.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/ingress.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/managedcertificate.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/frontendconfig.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/backendconfig.yaml?ref=main") for call in calls)


def test_ensure_deploy_workflow_blocks_invalid_rendered_yaml_before_workflow_write(monkeypatch, caplog) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, _managed_provisioning_responses(), calls)

    def _render_invalid_workflow(**kwargs) -> str:
        del kwargs
        return 'name: broken-workflow\non:\n  workflow_dispatch:\njobs:\n  deploy:\n    steps:\n      - name: broken\n        run: |\n          echo "oops"\n    outputs: ['

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._render_managed_deploy_workflow_yaml",
        _render_invalid_workflow,
    )
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            site_id="site-1",
        )

    assert exc_info.value.code == "managed_workflow_template_invalid"
    assert exc_info.value.stage == "workflow_provisioning"
    assert not any(
        method == "PUT" and "/contents/.github/workflows/deploy-tnmfire-www-prod.yml" in url for method, url in calls
    )
    validation_logs = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_managed_workflow_template_validation"' in record.msg
    ]
    assert validation_logs
    latest_log = validation_logs[-1]
    assert '"operation_status": "failed"' in latest_log
    assert '"template_name": "managed_deploy_workflow_yaml"' in latest_log
    assert '"workflow_path": ".github/workflows/deploy-tnmfire-www-prod.yml"' in latest_log
    assert '"site_id": "site-1"' in latest_log
    assert '"reason_code": "managed_workflow_template_invalid"' in latest_log
    assert "test-token" not in latest_log


def test_ensure_deploy_workflow_blocks_missing_required_outputs_before_workflow_write(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, _managed_provisioning_responses(), calls)

    original_renderer = _render_managed_deploy_workflow_yaml

    def _render_missing_output(**kwargs) -> str:
        rendered = original_renderer(**kwargs)
        return rendered.replace(
            "      deploy_https_ready: ${{ steps.resolve_live_url.outputs.deploy_https_ready }}\n",
            "",
            1,
        )

    monkeypatch.setattr(
        "app.integrations.seo_migration_github_publisher._render_managed_deploy_workflow_yaml",
        _render_missing_output,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            site_id="site-1",
        )

    assert exc_info.value.code == "managed_workflow_template_invalid"
    assert exc_info.value.stage == "workflow_provisioning"
    assert "deploy_outputs_missing:deploy_https_ready" in str(exc_info.value.provider_message or "")
    assert not any(
        method == "PUT" and "/contents/.github/workflows/deploy-tnmfire-www-prod.yml" in url for method, url in calls
    )


def test_ensure_deploy_workflow_existing_empty_repo_requires_manual_initialization(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/branches/main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
    ]
    _install_urlopen_stub(monkeypatch, queue, calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            business_id="business-1",
            site_id="site-1",
        )

    assert exc_info.value.code == "github_repo_requires_manual_initialization"
    assert not any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)
    assert not any(
        method == "POST" and url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
        for method, url in calls
    )


def test_ensure_deploy_workflow_reconciles_baseline_for_newly_created_repo_before_workflow_provisioning(
    monkeypatch,
    caplog,
) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/LICENSE?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-marker"}})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/README.md?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-readme"}})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/.gitignore?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-gitignore"}})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/LICENSE?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "baseline-license"}})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
    ]
    queue.extend(
        _managed_file_upsert_responses(
            managed_paths=(
                ".github/workflows/deploy-tnmfire-www-prod.yml",
                "k8s/namespace.yaml",
                "k8s/deployment.yaml",
                "k8s/service.yaml",
                "k8s/ingress.yaml",
                "k8s/managedcertificate.yaml",
                "k8s/frontendconfig.yaml",
                "k8s/backendconfig.yaml",
            )
        )
    )
    _install_urlopen_stub(monkeypatch, queue, calls)
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
        business_id="business-1",
        site_id="site-1",
        repository_auto_create_created=True,
        artifact_version_id="artifact-1",
    )

    assert result.provisioned is True
    assert not any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)
    assert any(method == "PUT" and url.endswith("/contents/mbsrn.key") for method, url in calls)
    decision_logs = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, str)
        and '"event": "seo_migration_workflow_provisioning_operation"' in record.msg
        and '"operation_kind": "repo_bootstrap_decision"' in record.msg
    ]
    assert not decision_logs


def test_bootstrap_repository_branch_writes_mbsrn_management_marker(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_tree_payload: dict[str, object] = {}
    captured_commit_payload: dict[str, object] = {}
    captured_ref_payload: dict[str, object] = {}
    blob_contents: list[str] = []
    blob_payload_keys: list[tuple[str, ...]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "marker-blob-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "readme-blob-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "gitignore-blob-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "license-blob-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "tree-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "commit-sha"})),
        _FakeHTTPResponse(status=201, body="{}"),
    ]

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if request.data and request.get_method() == "POST" and request.full_url.endswith("/git/blobs"):
            payload = json.loads(request.data.decode("utf-8"))
            blob_contents.append(str(payload.get("content") or ""))
            blob_payload_keys.append(tuple(sorted(str(key) for key in payload.keys())))
        if request.data and request.get_method() == "POST" and request.full_url.endswith("/git/trees"):
            captured_tree_payload.update(json.loads(request.data.decode("utf-8")))
        if request.data and request.get_method() == "POST" and request.full_url.endswith("/git/commits"):
            captured_commit_payload.update(json.loads(request.data.decode("utf-8")))
        if request.data and request.get_method() == "POST" and request.full_url.endswith("/git/refs"):
            captured_ref_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    publisher._bootstrap_repository_branch(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        business_id="business-1",
        site_id="site-1",
    )

    tree_entries = captured_tree_payload.get("tree")
    assert isinstance(tree_entries, list)
    assert any(isinstance(item, dict) and item.get("path") == "mbsrn.key" for item in tree_entries)
    assert any(isinstance(item, dict) and item.get("path") == "README.md" for item in tree_entries)
    assert any(isinstance(item, dict) and item.get("path") == ".gitignore" for item in tree_entries)
    assert any(isinstance(item, dict) and item.get("path") == "LICENSE" for item in tree_entries)
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/git/blobs")
    assert not any("/contents/" in url for _, url in calls)
    assert not any("/branches/" in url for _, url in calls)
    assert not any("/git/ref/" in url for _, url in calls)
    assert blob_payload_keys
    assert all(keys == ("content", "encoding") for keys in blob_payload_keys)
    marker_blob_content = next((item for item in blob_contents if item.startswith("{")), "")
    assert marker_blob_content
    marker_payload = json.loads(marker_blob_content)
    assert marker_payload.get("business_id") == "business-1"
    assert marker_payload.get("site_id") == "site-1"
    assert any("# Byte-compiled / optimized / DLL files" in item for item in blob_contents)
    assert any(item.startswith("Apache License") for item in blob_contents)
    assert captured_commit_payload.get("parents") == []
    assert captured_ref_payload.get("ref") == "refs/heads/main"


@pytest.mark.parametrize(
    ("step_failed", "queue"),
    [
        (
            "blob",
            [
                _http_error(
                    "https://api.github.com/repos/mhanson13/tnmfire/git/blobs",
                    status_code=403,
                    message="Resource not accessible by integration",
                ),
            ],
        ),
        (
            "tree",
            [
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "marker-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "readme-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "gitignore-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "license-blob-sha"})),
                _http_error(
                    "https://api.github.com/repos/mhanson13/tnmfire/git/trees",
                    status_code=500,
                    message="Internal Server Error",
                ),
            ],
        ),
        (
            "commit",
            [
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "marker-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "readme-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "gitignore-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "license-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "tree-sha"})),
                _http_error(
                    "https://api.github.com/repos/mhanson13/tnmfire/git/commits",
                    status_code=422,
                    message="Validation failed",
                ),
            ],
        ),
        (
            "ref",
            [
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "marker-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "readme-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "gitignore-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "license-blob-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "tree-sha"})),
                _FakeHTTPResponse(status=201, body=json.dumps({"sha": "commit-sha"})),
                _http_error(
                    "https://api.github.com/repos/mhanson13/tnmfire/git/refs",
                    status_code=422,
                    message="Reference update failed",
                ),
            ],
        ),
    ],
)
def test_bootstrap_repository_branch_step_failure_maps_to_repo_initialization_failed(
    monkeypatch,
    step_failed: str,
    queue: list[object],
) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, queue, calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher._bootstrap_repository_branch(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            business_id="business-1",
            site_id="site-1",
        )

    assert exc_info.value.code == "github_repo_initialization_failed"
    provider_message = str(exc_info.value.provider_message or "")
    assert f"step_failed={step_failed}" in provider_message
    if step_failed == "blob":
        assert "request_path=/repos/mhanson13/tnmfire/git/blobs" in provider_message
        assert "payload_keys=content,encoding" in provider_message


def test_ensure_deploy_workflow_ref_check_409_empty_repo_requires_manual_initialization(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/branches/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
    ]
    _install_urlopen_stub(monkeypatch, queue, calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            business_id="business-1",
            site_id="site-1",
        )

    assert exc_info.value.code == "github_repo_requires_manual_initialization"
    assert not any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)


def test_ensure_deploy_workflow_ref_check_generic_409_empty_repo_logs_manual_init_requirement(
    monkeypatch,
    caplog,
) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
    ]
    _install_urlopen_stub(monkeypatch, queue, calls)
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    original_request_json = publisher._request_json
    branch_check_intercepted = {"done": False}

    def _patched_request_json(**kwargs):
        path = str(kwargs.get("path") or "")
        method = str(kwargs.get("method") or "").upper()
        if (not branch_check_intercepted["done"]) and method == "GET" and path.endswith("/branches/main"):
            branch_check_intercepted["done"] = True
            raise SEOMigrationGitHubPublisherError(
                code="github_request_failed",
                safe_message="GitHub publish/deploy request failed.",
                status_code=409,
                stage="ref_lookup",
                provider_message="Git Repository is empty.",
            )
        return original_request_json(**kwargs)

    monkeypatch.setattr(publisher, "_request_json", _patched_request_json)
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            business_id="business-1",
            site_id="site-1",
            artifact_version_id="artifact-1",
            repository_auto_create_created=False,
        )

    assert exc_info.value.code == "github_repo_requires_manual_initialization"
    assert branch_check_intercepted["done"] is True
    assert not any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)
    decision_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str)
        and '"event": "seo_migration_workflow_provisioning_operation"' in record.msg
        and '"operation_kind": "repo_bootstrap_decision"' in record.msg
    ]
    assert decision_logs
    assert '"bootstrap_decision_source": "ref_check_uninitialized"' in decision_logs[-1].msg
    assert '"will_attempt_bootstrap": false' in decision_logs[-1].msg
    assert '"repository_auto_create_created": false' in decision_logs[-1].msg
    assert '"allow_repair": true' in decision_logs[-1].msg
    assert '"bootstrap_allowed": true' in decision_logs[-1].msg
    assert '"dry_run": false' in decision_logs[-1].msg
    assert '"remediation_mode": "workflow_provisioning"' in decision_logs[-1].msg
    assert '"workflow_path": ".github/workflows/deploy-tnmfire-www-prod.yml"' in decision_logs[-1].msg
    assert '"artifact_version_id": "artifact-1"' in decision_logs[-1].msg
    assert '"business_id": "business-1"' in decision_logs[-1].msg
    assert '"site_id": "site-1"' in decision_logs[-1].msg
    assert any(
        isinstance(record.msg, str) and '"event": "repo_requires_manual_initialization"' in record.msg
        for record in caplog.records
    )


def test_ensure_deploy_workflow_logs_bootstrap_blocked_context_when_dry_run(
    monkeypatch,
    caplog,
) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/branches/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
    ]
    _install_urlopen_stub(monkeypatch, queue, calls)
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=True,
            business_id="business-1",
            site_id="site-1",
            artifact_version_id="artifact-2",
        )

    assert exc_info.value.code == "github_repo_initialization_failed"
    decision_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str)
        and '"event": "seo_migration_workflow_provisioning_operation"' in record.msg
        and '"operation_kind": "repo_bootstrap_decision"' in record.msg
    ]
    assert decision_logs
    assert '"bootstrap_decision_source": "ref_check_uninitialized"' in decision_logs[-1].msg
    assert '"dry_run": true' in decision_logs[-1].msg
    assert '"allow_repair": false' in decision_logs[-1].msg
    assert '"bootstrap_allowed": false' in decision_logs[-1].msg
    assert '"will_attempt_bootstrap": false' in decision_logs[-1].msg
    assert '"remediation_mode": "workflow_provisioning"' in decision_logs[-1].msg
    assert '"bootstrap_blocked_reason": "bootstrap_disabled_by_execution_mode"' in decision_logs[-1].msg
    assert '"workflow_path": ".github/workflows/deploy-tnmfire-www-prod.yml"' in decision_logs[-1].msg
    assert '"artifact_version_id": "artifact-2"' in decision_logs[-1].msg
    assert '"business_id": "business-1"' in decision_logs[-1].msg
    assert '"site_id": "site-1"' in decision_logs[-1].msg


def test_ensure_deploy_workflow_ref_check_409_empty_repo_preserves_manual_init_code(
    monkeypatch,
    caplog,
) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/branches/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=409,
            message="Git Repository is empty.",
        ),
    ]
    _install_urlopen_stub(monkeypatch, queue, calls)
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            business_id="business-1",
            site_id="site-1",
        )

    assert exc_info.value.code == "github_repo_requires_manual_initialization"
    assert exc_info.value.stage == "workflow_provisioning"
    failed_logs = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "repo_requires_manual_initialization"' in record.msg
    ]
    assert failed_logs
    assert '"step_failed": "manual_initialization_required"' in failed_logs[-1]


def test_ensure_deploy_workflow_default_ref_lookup_404_requires_manual_initialization(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/mbsrn.key?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/branches/main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/git/ref/heads/main",
            status_code=404,
            message="Reference does not exist",
        ),
    ]
    _install_urlopen_stub(monkeypatch, queue, calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
            business_id="business-1",
            site_id="site-1",
        )

    assert exc_info.value.code == "github_repo_requires_manual_initialization"
    assert not any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)


def test_ensure_deploy_workflow_initialized_repo_does_not_bootstrap(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(monkeypatch, _managed_provisioning_responses(), calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )

    assert result.provisioned is True
    assert not any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)
    assert not any(method == "POST" and url.endswith("/git/trees") for method, url in calls)
    assert not any(method == "POST" and url.endswith("/git/commits") for method, url in calls)


def test_ensure_deploy_workflow_classifies_workflow_write_forbidden(monkeypatch, caplog) -> None:
    calls: list[tuple[str, str]] = []
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml",
                status_code=403,
                message="Resource not accessible by integration",
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
        )

    assert exc_info.value.code == "github_workflow_write_not_authorized"
    assert exc_info.value.stage == "workflow_provisioning"
    failed_operation_logs = [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, str)
        and '"event": "seo_migration_workflow_provisioning_operation"' in record.msg
        and '"operation_status": "failed"' in record.msg
        and '"operation_kind": "file_upsert"' in record.msg
    ]
    assert failed_operation_logs
    assert '"http_status_code": 403' in failed_operation_logs[-1]
    assert '"github_error_code": "github_workflow_write_not_authorized"' in failed_operation_logs[-1]


def test_ensure_deploy_workflow_classifies_branch_uninitialized_when_put_reports_branch_error(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml",
                status_code=422,
                message="Invalid request. Branch main was not found.",
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
        )

    assert exc_info.value.code == "github_branch_not_found_or_uninitialized"
    assert exc_info.value.stage == "workflow_provisioning"


def test_ensure_deploy_workflow_classifies_contents_write_forbidden_on_manifest(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
            _managed_workflow_verify_response(sha="workflow-verified"),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/k8s/namespace.yaml?ref=main",
                status_code=404,
                message="Not Found",
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/k8s/namespace.yaml",
                status_code=403,
                message="Resource not accessible by integration",
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
        )

    assert exc_info.value.code == "github_contents_write_not_authorized"
    assert exc_info.value.stage == "workflow_provisioning"


def test_ensure_deploy_workflow_classifies_generic_file_lookup_failure(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
            _repo_management_marker_response(),
            _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
                status_code=422,
                message="Validation Failed",
            ),
        ],
        calls,
    )

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
        )

    assert exc_info.value.code == "github_workflow_provisioning_failed"
    assert exc_info.value.stage == "workflow_provisioning"


def test_ensure_deploy_workflow_provisions_dispatchable_trigger(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_put_payload: dict[str, object] = {}
    captured_deployment_put_payload: dict[str, object] = {}
    captured_service_put_payload: dict[str, object] = {}
    captured_ingress_put_payload: dict[str, object] = {}
    captured_managed_certificate_put_payload: dict[str, object] = {}
    captured_frontend_config_put_payload: dict[str, object] = {}
    captured_backend_config_put_payload: dict[str, object] = {}
    queue = _managed_provisioning_responses()

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
            and request.data
        ):
            captured_put_payload.update(json.loads(request.data.decode("utf-8")))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/k8s/deployment.yaml")
            and request.data
        ):
            captured_deployment_put_payload.update(json.loads(request.data.decode("utf-8")))
        if request.get_method() == "PUT" and request.full_url.endswith("/contents/k8s/service.yaml") and request.data:
            captured_service_put_payload.update(json.loads(request.data.decode("utf-8")))
        if request.get_method() == "PUT" and request.full_url.endswith("/contents/k8s/ingress.yaml") and request.data:
            captured_ingress_put_payload.update(json.loads(request.data.decode("utf-8")))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/k8s/managedcertificate.yaml")
            and request.data
        ):
            captured_managed_certificate_put_payload.update(json.loads(request.data.decode("utf-8")))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/k8s/frontendconfig.yaml")
            and request.data
        ):
            captured_frontend_config_put_payload.update(json.loads(request.data.decode("utf-8")))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/k8s/backendconfig.yaml")
            and request.data
        ):
            captured_backend_config_put_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )
    encoded_content = str(captured_put_payload.get("content") or "")
    assert encoded_content
    workflow_yaml = base64.b64decode(encoded_content).decode("utf-8")
    parsed_workflow = yaml.safe_load(workflow_yaml)
    assert isinstance(parsed_workflow, dict)
    encoded_deployment_content = str(captured_deployment_put_payload.get("content") or "")
    assert encoded_deployment_content
    deployment_yaml = base64.b64decode(encoded_deployment_content).decode("utf-8")
    encoded_service_content = str(captured_service_put_payload.get("content") or "")
    assert encoded_service_content
    service_yaml = base64.b64decode(encoded_service_content).decode("utf-8")
    encoded_ingress_content = str(captured_ingress_put_payload.get("content") or "")
    assert encoded_ingress_content
    ingress_yaml = base64.b64decode(encoded_ingress_content).decode("utf-8")
    encoded_managed_certificate_content = str(captured_managed_certificate_put_payload.get("content") or "")
    assert encoded_managed_certificate_content
    managed_certificate_yaml = base64.b64decode(encoded_managed_certificate_content).decode("utf-8")
    encoded_frontend_config_content = str(captured_frontend_config_put_payload.get("content") or "")
    assert encoded_frontend_config_content
    frontend_config_yaml = base64.b64decode(encoded_frontend_config_content).decode("utf-8")
    encoded_backend_config_content = str(captured_backend_config_put_payload.get("content") or "")
    assert encoded_backend_config_content
    backend_config_yaml = base64.b64decode(encoded_backend_config_content).decode("utf-8")
    assert "workflow_dispatch" in workflow_yaml
    assert "replace_existing_runtime:" in workflow_yaml
    assert "description: Replace existing managed-site runtime resources before deploy" in workflow_yaml
    assert "default: false" in workflow_yaml
    assert "type: boolean" in workflow_yaml
    assert "permissions:" in workflow_yaml
    assert "packages: write" in workflow_yaml
    assert "K8S_NAMESPACE: tnmfire" in workflow_yaml
    assert "MBSRN_PREVIEW_HOSTNAME: tnmfire.site.mbsrn.com" in workflow_yaml
    assert "MBSRN_PREVIEW_CERTIFICATE_NAME: site-web-preview-cert-tnmfire" in workflow_yaml
    assert "MBSRN_PREVIEW_STATIC_IP_NAME: site-web-preview-ip-tnmfire" in workflow_yaml
    assert (
        "MBSRN_REPLACE_EXISTING_RUNTIME: ${{ github.event.inputs.replace_existing_runtime || 'false' }}"
        in workflow_yaml
    )
    assert "MBSRN_FRONTEND_CONFIG_NAME: site-web-frontend-config-tnmfire" in workflow_yaml
    assert "MBSRN_BACKEND_CONFIG_NAME: site-web-backend-config-tnmfire" in workflow_yaml
    assert "SITE_WEB_IMAGE_REPOSITORY: ghcr.io/mhanson13/tnmfire-site-web" in workflow_yaml
    assert "ghcr.io/mbsrn/site-web" not in workflow_yaml
    assert 'PRIVATE_IMAGE_AUTH_REQUIRED: "true"' in workflow_yaml
    assert (
        "SITE_WEB_IMAGE_TAG: ${{ vars.MBSRN_SITE_WEB_IMAGE_TAG || vars.SITE_WEB_IMAGE_TAG || secrets.MBSRN_SITE_WEB_IMAGE_TAG || secrets.SITE_WEB_IMAGE_TAG || '' }}"
        in workflow_yaml
    )
    assert "Authenticate to GCP" in workflow_yaml
    assert "Get GKE credentials" in workflow_yaml
    assert "Verify expected preview ingress static IP exists" in workflow_yaml
    assert (
        'gcloud compute addresses describe "$MBSRN_PREVIEW_STATIC_IP_NAME" --global --project "$GKE_PROJECT_ID"'
        in workflow_yaml
    )
    assert "deploy_runtime_reason_code=managed_site_static_ip_missing" in workflow_yaml
    assert "Ensure namespace exists" in workflow_yaml
    assert "Verify GHCR image pull secret" in workflow_yaml
    assert 'kubectl get secret ghcr-pull-secret --namespace "$K8S_NAMESPACE"' in workflow_yaml
    assert "Ensure managed-site endpoint prerequisites" in workflow_yaml
    assert 'endpoint_prerequisite_resource_kinds="managedcertificate,dns_record,global_static_ip"' in workflow_yaml
    assert (
        'runtime_resource_kinds="ingress,frontendconfig,backendconfig,service,deployment,networkpolicy"'
        in workflow_yaml
    )
    assert "if [ ! -f k8s/managedcertificate.yaml ]; then" in workflow_yaml
    assert 'echo "managed_certificate_action=reused" >> "$GITHUB_OUTPUT"' in workflow_yaml
    assert "Use the control-plane Provision TLS Certificate action before requesting GKE deploy." in workflow_yaml
    assert 'fail_endpoint_prerequisite "managed_certificate_ownership_unverified"' in workflow_yaml
    assert 'fail_endpoint_prerequisite "certificate_domain_mismatch"' in workflow_yaml
    assert 'fail_endpoint_prerequisite "stale_managed_certificate_present"' in workflow_yaml
    ensure_endpoint_step_yaml = workflow_yaml.split(
        "      - name: Ensure managed-site endpoint prerequisites",
        1,
    )[
        1
    ].split("      - name: Replace existing managed-site runtime resources (optional)", 1)[0]
    assert 'kubectl get managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME"' in ensure_endpoint_step_yaml
    assert 'if [ -z "$managed_certificate_json" ]; then' in ensure_endpoint_step_yaml
    assert "kubectl apply -f k8s/managedcertificate.yaml" not in ensure_endpoint_step_yaml
    assert "Replace existing managed-site runtime resources (optional)" in workflow_yaml
    assert "deploy_runtime_reason_code=managed_site_runtime_replace_requested" in workflow_yaml
    assert "deploy_runtime_reason_code=managed_site_runtime_replace_completed" in workflow_yaml
    assert "deploy_runtime_reason_code=managed_site_runtime_replace_failed" in workflow_yaml
    assert 'delete_named_resource "ingress" "site-web"' in workflow_yaml
    assert 'delete_named_resource "managedcertificate" "$MBSRN_PREVIEW_CERTIFICATE_NAME"' not in workflow_yaml
    assert 'delete_named_resource "frontendconfig" "$MBSRN_FRONTEND_CONFIG_NAME"' in workflow_yaml
    assert 'delete_named_resource "backendconfig" "$MBSRN_BACKEND_CONFIG_NAME"' in workflow_yaml
    assert 'delete_named_resource "service" "site-web"' in workflow_yaml
    assert 'delete_named_resource "deployment" "site-web"' in workflow_yaml
    assert (
        'kubectl delete networkpolicy --namespace "$K8S_NAMESPACE" -l "$network_policy_selector" --ignore-not-found=true'
        in workflow_yaml
    )
    assert "managed_site_runtime_replace_performed" in workflow_yaml
    assert "managed_site_runtime_replace_scope" in workflow_yaml
    assert "managed_site_runtime_replace_deleted_kinds" in workflow_yaml
    assert "gcloud compute addresses delete" not in workflow_yaml
    assert "GIT_USERID: ${{ secrets.GIT_USERID }}" not in workflow_yaml
    assert "GIT_EMAIL: ${{ secrets.GIT_EMAIL }}" not in workflow_yaml
    assert "GIT_TOKEN: ${{ secrets.GIT_TOKEN }}" not in workflow_yaml
    assert "DOCKER_USERID" not in workflow_yaml
    assert "DOCKER_EMAIL" not in workflow_yaml
    assert "DOCKER_PAT" not in workflow_yaml
    assert "MIGRATION_GITHUB_TOKEN" not in workflow_yaml
    assert "kubectl create secret docker-registry ghcr-pull-secret" not in workflow_yaml
    assert "Apply managed manifests" in workflow_yaml
    ensure_endpoint_step_index = workflow_yaml.index("      - name: Ensure managed-site endpoint prerequisites")
    replace_runtime_step_index = workflow_yaml.index(
        "      - name: Replace existing managed-site runtime resources (optional)"
    )
    apply_manifests_step_index = workflow_yaml.index("      - name: Apply managed manifests")
    assert ensure_endpoint_step_index < replace_runtime_step_index < apply_manifests_step_index
    assert "apply_manifest_if_present() {" in workflow_yaml
    assert "wait_for_named_resource() {" in workflow_yaml
    assert 'apply_manifest_if_present "k8s/backendconfig.yaml"' in workflow_yaml
    assert 'apply_manifest_if_present "k8s/service.yaml"' in workflow_yaml
    assert (
        'wait_for_named_resource "service" "site-web" 10 3 "runtime_service_missing_after_apply" '
        '"Service site-web is missing after managed manifest apply."' in workflow_yaml
    )
    assert 'apply_manifest_if_present "k8s/deployment.yaml"' in workflow_yaml
    assert 'apply_manifest_if_present "k8s/frontendconfig.yaml"' in workflow_yaml
    assert 'apply_manifest_if_present "k8s/managedcertificate.yaml"' not in workflow_yaml
    apply_step_yaml = workflow_yaml.split("      - name: Apply managed manifests", 1)[1].split(
        "      - name: Verify required resources after apply",
        1,
    )[0]
    assert "kubectl apply -f k8s/managedcertificate.yaml" not in apply_step_yaml
    assert 'apply_manifest_if_present "k8s/ingress.yaml"' in workflow_yaml
    assert "Verify required resources after apply" in workflow_yaml
    assert 'fail_missing_resource "runtime_deployment_missing_after_apply"' in workflow_yaml
    assert 'fail_missing_resource "runtime_service_missing_after_apply"' in workflow_yaml
    assert 'fail_missing_resource "runtime_ingress_missing_after_apply"' in workflow_yaml
    assert 'fail_missing_resource "runtime_managed_certificate_missing_after_apply"' in workflow_yaml
    assert 'fail_missing_resource "runtime_frontend_config_missing_after_apply"' in workflow_yaml
    assert 'fail_missing_resource "runtime_backend_config_missing_after_apply"' in workflow_yaml
    assert 'if ! kubectl get deployment site-web --namespace "$K8S_NAMESPACE" >/dev/null 2>&1; then' in workflow_yaml
    assert 'if ! kubectl get service site-web --namespace "$K8S_NAMESPACE" >/dev/null 2>&1; then' in workflow_yaml
    assert "Resolve managed site runtime image" in workflow_yaml
    assert 'selected_mode="immutable_sha"' in workflow_yaml
    assert 'selected_tag_source="github_sha_fallback"' in workflow_yaml
    assert 'selected_image="${SITE_WEB_IMAGE_REPOSITORY}:${GITHUB_SHA}"' in workflow_yaml
    assert 'selected_mode="fallback_latest"' in workflow_yaml
    assert 'selected_mode="immutable_sha"' in workflow_yaml
    assert 'selected_tag_source="configured_sha"' in workflow_yaml
    assert 'selected_tag_source="configured_invalid_fallback_latest"' in workflow_yaml
    assert 'selected_tag_source="configured_latest"' in workflow_yaml
    assert 'kubectl set image deployment/site-web site-web="${selected_image}"' in workflow_yaml
    assert "Managed site runtime image selected: ${selected_image} (mode=${selected_mode})" in workflow_yaml
    assert "SITE_WEB_IMAGE_TAG is empty; using GITHUB_SHA ${GITHUB_SHA}." in workflow_yaml
    assert (
        "Configured SITE_WEB_IMAGE_TAG '$normalized_tag' is not a SHA-like tag; falling back to latest."
        in workflow_yaml
    )
    assert "Verify rollout" in workflow_yaml
    assert "Verify service and ingress" in workflow_yaml
    assert "project_id: ${{ env.GKE_PROJECT_ID }}" in workflow_yaml
    assert "Validate GCP credentials" in workflow_yaml
    assert "Missing GCP_DEPLOY_KEY secret" in workflow_yaml
    validate_credentials_step = next(
        step for step in parsed_workflow["jobs"]["deploy"]["steps"] if step.get("name") == "Validate GCP credentials"
    )
    assert validate_credentials_step["env"]["MBSRN_GCP_DEPLOY_CREDENTIALS_CONFIGURED"] == (
        "${{ secrets.GCP_DEPLOY_KEY != '' }}"
    )
    assert "secrets.GCP_DEPLOY_KEY" not in validate_credentials_step["run"]
    assert '"${MBSRN_GCP_DEPLOY_CREDENTIALS_CONFIGURED:-false}" != "true"' in validate_credentials_step["run"]
    assert "Validate GKE environment config" in workflow_yaml
    assert "Missing managed GKE cluster name (admin config or legacy repo fallback)." in workflow_yaml
    assert "Missing managed GKE cluster location (admin config or legacy repo fallback)." in workflow_yaml
    assert "Missing managed GKE project id (admin config or legacy repo fallback)." in workflow_yaml
    assert "credentials_json: ${{ secrets.GCP_DEPLOY_KEY }}" in workflow_yaml
    assert "create_credentials_file: true" in workflow_yaml
    assert "export_environment_variables: true" in workflow_yaml
    assert "workload_identity_provider:" not in workflow_yaml
    assert "service_account:" not in workflow_yaml
    assert "GKE_CLUSTER_NAME: ${{ vars.KUBERNETES_CLUSTER_NAME || secrets.KUBERNETES_CLUSTER_NAME }}" in workflow_yaml
    assert (
        "GKE_CLUSTER_LOCATION: ${{ vars.KUBERNETES_CLUSTER_LOCATION || secrets.KUBERNETES_CLUSTER_LOCATION }}"
        in workflow_yaml
    )
    assert "GKE_PROJECT_ID: ${{ vars.GCP_PROJECT_ID || secrets.GCP_PROJECT_ID }}" in workflow_yaml
    assert "cluster_name: ${{ env.GKE_CLUSTER_NAME }}" in workflow_yaml
    assert "location: ${{ env.GKE_CLUSTER_LOCATION }}" in workflow_yaml
    assert "project_id: ${{ env.GKE_PROJECT_ID }}" in workflow_yaml
    assert "outputs:" in workflow_yaml
    assert "live_url: ${{ steps.resolve_live_url.outputs.live_url }}" in workflow_yaml
    assert "resolved_live_url: ${{ steps.resolve_live_url.outputs.resolved_live_url }}" in workflow_yaml
    assert "deployed_url: ${{ steps.resolve_live_url.outputs.deployed_url }}" in workflow_yaml
    assert (
        "site_runtime_image_reference: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}"
        in workflow_yaml
    )
    assert (
        "site_runtime_image_selection_mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}"
        in workflow_yaml
    )
    assert (
        "site_runtime_image_repository: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_repository }}"
        in workflow_yaml
    )
    assert (
        "site_runtime_image_tag: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_tag }}"
        in workflow_yaml
    )
    assert (
        "site_runtime_image_tag_source: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_tag_source }}"
        in workflow_yaml
    )
    assert (
        "site_runtime_source_commit: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_source_commit }}"
        in workflow_yaml
    )
    assert (
        "site_runtime_content_source: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_content_source }}"
        in workflow_yaml
    )
    assert (
        "managed_site_runtime_replace_performed: ${{ steps.replace_managed_runtime.outputs.managed_site_runtime_replace_performed }}"
        in workflow_yaml
    )
    assert "url: ${{ steps.resolve_live_url.outputs.resolved_live_url }}" in workflow_yaml
    assert "kubectl apply -f k8s/\n" not in workflow_yaml
    assert "kubectl rollout status deployment/site-web" in workflow_yaml
    assert "site-web rollout timed out in namespace $K8S_NAMESPACE; collecting bounded diagnostics." in workflow_yaml
    assert 'kubectl get rs --namespace "$K8S_NAMESPACE" -o wide || true' in workflow_yaml
    assert (
        'kubectl describe deployment site-web --namespace "$K8S_NAMESPACE" > "$deployment_describe_output" 2>&1 || true'
        in workflow_yaml
    )
    assert 'kubectl describe pods --namespace "$K8S_NAMESPACE" -l app.kubernetes.io/name=site-web' in workflow_yaml
    assert "image_pull_detected=false" in workflow_yaml
    assert "image_pull_secret_missing_detected=false" in workflow_yaml
    assert "private_image_pull_forbidden_detected=false" in workflow_yaml
    assert "public_image_pull_failed_detected=false" in workflow_yaml
    assert 'private_image_auth_required="${PRIVATE_IMAGE_AUTH_REQUIRED:-false}"' in workflow_yaml
    assert "Likely rollout blocker: image pull backoff." in workflow_yaml
    assert "Likely rollout blocker: image pull secret missing." in workflow_yaml
    assert "Likely rollout blocker: private image pull forbidden." in workflow_yaml
    assert "Likely rollout blocker: public image pull failed." in workflow_yaml
    assert "Likely rollout blocker: image pull secret not referenced." in workflow_yaml
    assert "deploy_runtime_reason_code=image_pull_secret_missing" in workflow_yaml
    assert "deploy_runtime_reason_code=private_image_pull_forbidden" in workflow_yaml
    assert "deploy_runtime_reason_code=public_image_pull_failed" in workflow_yaml
    assert "Likely rollout blocker: service has no ready endpoints." in workflow_yaml
    assert "deploy_runtime_reason_code=service_has_no_ready_endpoints" in workflow_yaml
    assert "deploy_runtime_reason_code=service_endpoint_missing" in workflow_yaml
    assert "Likely rollout blocker: ingress backend unhealthy." in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_backend_unhealthy" in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_backend_unhealthy_after_rollout" in workflow_yaml
    assert "Likely rollout blocker: ingress backend 502." in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_backend_502" in workflow_yaml
    assert "Likely rollout blocker: pod ready but ingress backend unhealthy." in workflow_yaml
    assert "deploy_runtime_reason_code=pod_ready_but_ingress_backend_unhealthy" in workflow_yaml
    assert "deploy_runtime_reason_code=service_endpoint_unhealthy" in workflow_yaml
    assert "Likely rollout blocker: backendconfig health check mismatch." in workflow_yaml
    assert "deploy_runtime_reason_code=backendconfig_health_check_mismatch" in workflow_yaml
    assert "deploy_runtime_reason_code=backend_config_healthcheck_unhealthy" in workflow_yaml
    assert "Likely rollout blocker: container image not found in registry." in workflow_yaml
    assert "container_started_evidence=false" in workflow_yaml
    assert "crash_direct_evidence=false" in workflow_yaml
    assert "probe_direct_evidence=false" in workflow_yaml
    assert "Suppress crash/probe hints when current describe evidence shows image-pull blockers." in workflow_yaml
    assert (
        'if [ "$image_pull_detected" = false ] && [ "$container_started_evidence" = true ] && [ "$crash_direct_evidence" = true ]; then'
        in workflow_yaml
    )
    assert (
        'if [ "$image_pull_detected" = false ] && [ "$container_started_evidence" = true ] && [ "$probe_direct_evidence" = true ]; then'
        in workflow_yaml
    )
    assert "terminated with exit code|Last State:[[:space:]]+Terminated|Reason:[[:space:]]+Error" in workflow_yaml
    assert "CrashLoopBackOff|Back-off restarting failed container|OOMKilled|Error:" not in workflow_yaml
    assert "Likely rollout blocker: readiness/liveness probe failure." in workflow_yaml
    assert "Likely rollout blocker: config or secret reference failure." in workflow_yaml
    assert "Likely rollout blocker: namespace ResourceQuota rejection." in workflow_yaml
    assert "Likely rollout blocker: scheduling or resource availability issue." in workflow_yaml
    assert "Resolve live URL from ingress status" in workflow_yaml
    assert "max_attempts=40" in workflow_yaml
    assert "sleep_seconds=15" in workflow_yaml
    assert (
        "Waiting up to ${wait_seconds}s for ingress external address assignment in namespace $K8S_NAMESPACE."
        in workflow_yaml
    )
    assert 'kubectl get ingress site-web --namespace "$K8S_NAMESPACE"' in workflow_yaml
    assert 'kubectl get service site-web --namespace "$K8S_NAMESPACE" -o yaml' in workflow_yaml
    assert 'kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o yaml' in workflow_yaml
    assert (
        'kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o yaml || true'
        in workflow_yaml
    )
    assert 'kubectl describe service site-web --namespace "$K8S_NAMESPACE" || true' in workflow_yaml
    assert 'kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" || true' in workflow_yaml
    assert (
        'kubectl describe managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" || true'
        in workflow_yaml
    )
    assert (
        'kubectl describe backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true'
        in workflow_yaml
    )
    assert "probe_max_attempts=20" in workflow_yaml
    assert "probe_sleep_seconds=15" in workflow_yaml
    assert "endpoint_wait_max_attempts=20" in workflow_yaml
    assert "endpoint_wait_sleep_seconds=15" in workflow_yaml
    assert 'while [ "$endpoint_wait_attempt" -le "$endpoint_wait_max_attempts" ]; do' in workflow_yaml
    assert (
        "Service endpoints not ready on attempt ${endpoint_wait_attempt}/${endpoint_wait_max_attempts}; "
        "retrying in ${endpoint_wait_sleep_seconds}s." in workflow_yaml
    )
    assert 'while [ "$probe_attempt" -le "$probe_max_attempts" ]; do' in workflow_yaml
    assert 'if [ "$probe_attempt" -lt "$probe_max_attempts" ]; then' in workflow_yaml
    assert 'sleep "$probe_sleep_seconds"' in workflow_yaml
    verify_service_step_yaml = workflow_yaml.split("      - name: Verify service and ingress", 1)[1].split(
        "      - name: Resolve live URL from ingress status",
        1,
    )[0]
    assert "deploy_runtime_reason_code=runtime_service_endpoints_missing_after_apply" in verify_service_step_yaml
    assert "deploy_runtime_reason_code=service_probe_waiting_for_convergence" in verify_service_step_yaml
    assert "deploy_runtime_reason_code=ingress_neg_convergence_pending" not in verify_service_step_yaml
    assert "deploy_runtime_reason_code=in_cluster_service_probe_timeout" in verify_service_step_yaml
    assert "deploy_runtime_reason_code=network_policy_may_block_service_probe" in verify_service_step_yaml
    assert "deploy_runtime_reason_code=in_cluster_service_curl_failed_after_retries" in verify_service_step_yaml
    assert "deploy_runtime_reason_code=in_cluster_service_curl_failed" in verify_service_step_yaml
    assert 'kubectl get networkpolicy --namespace "$K8S_NAMESPACE" -o yaml || true' in verify_service_step_yaml
    assert 'kubectl describe networkpolicy --namespace "$K8S_NAMESPACE" || true' in verify_service_step_yaml
    assert (
        'kubectl get pod "$latest_site_web_pod" --namespace "$K8S_NAMESPACE" --show-labels || true'
        in verify_service_step_yaml
    )
    assert (
        'kubectl get service site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'selector={.spec.selector}'
        in verify_service_step_yaml
    )
    assert (
        "In-cluster service probe attempt ${probe_attempt}/${probe_max_attempts} failed; waiting for NEG/LB convergence before retrying."
        not in verify_service_step_yaml
    )
    assert "deploy_runtime_reason_code=pre_shared_cert_metadata_mismatch" in workflow_yaml
    assert (
        "Pre-shared cert annotation is controller metadata and does not block deploy by itself; relying on managed-certificate annotation/domain/TLS checks."
        in workflow_yaml
    )
    assert (
        'if [ "$pre_shared_count" -eq 1 ] && [ "$pre_shared_first" = "$expected_cert_name" ]; then'
        not in verify_service_step_yaml
    )
    assert "deploy_runtime_reason_code=ingress_neg_convergence_pending" in workflow_yaml
    assert 'kubectl delete pod "$probe_pod" --namespace "$K8S_NAMESPACE" --ignore-not-found || true' in workflow_yaml
    assert 'if ! kubectl run "$probe_pod"' not in workflow_yaml
    assert (
        'ingress_spec_host="$(kubectl get ingress site-web --namespace "$K8S_NAMESPACE" -o jsonpath=\'{.spec.rules[0].host}\' 2>/dev/null || true)"'
        in workflow_yaml
    )
    assert 'preview_host="$MBSRN_PREVIEW_HOSTNAME"' in workflow_yaml
    assert "host_reachable=false" in workflow_yaml
    assert "tls_mismatch_detected=false" in workflow_yaml
    assert "backend_502_detected=false" in workflow_yaml
    assert "https_probe_attempted=false" in workflow_yaml
    assert "http_fallback_attempted=false" in workflow_yaml
    assert "ensure_https_probe_error_summary() {" in workflow_yaml
    assert "ensure_https_probe_error_summary" in workflow_yaml
    assert 'fallback_reason="dns_not_ready"' in workflow_yaml
    assert 'fallback_reason="cert_not_ready"' in workflow_yaml
    assert 'fallback_reason="host_resolution_pending"' in workflow_yaml
    assert 'if [ -z "$preview_host" ] && [ -n "$ingress_spec_host" ]; then' in workflow_yaml
    assert "Expected preview hostname responded over HTTPS" in workflow_yaml
    assert "Expected preview hostname responded over HTTP" in workflow_yaml
    assert "deploy_runtime_reason_code=reachable_but_tls_certificate_mismatch" in workflow_yaml
    assert "deploy_runtime_reason_code=https_probe_timeout" in workflow_yaml
    assert "deploy_runtime_reason_code=https_probe_empty_reply" in workflow_yaml
    assert "deploy_runtime_reason_code=https_probe_not_attempted" in workflow_yaml
    assert "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready" in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_address_pending_but_hostname_reachable" in workflow_yaml
    assert 'if [ "$tls_mismatch_detected" = true ]; then' in workflow_yaml
    assert 'if [ "$backend_502_detected" = true ]; then' in workflow_yaml
    assert (
        'kubectl describe managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" || true'
        in workflow_yaml
    )
    assert (
        'kubectl describe backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true'
        in workflow_yaml
    )
    assert "Ingress created but external address is not assigned yet for namespace $K8S_NAMESPACE." in workflow_yaml
    assert "Likely rollout blocker: ingress/load balancer provisioning still in progress." in workflow_yaml
    assert "This may take several minutes on GKE." in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_address_pending" in workflow_yaml
    assert 'kubectl describe ingress site-web --namespace "$K8S_NAMESPACE" || true' in workflow_yaml
    assert 'kubectl get service site-web --namespace "$K8S_NAMESPACE" -o wide || true' in workflow_yaml
    assert 'kubectl get endpoints site-web --namespace "$K8S_NAMESPACE" -o wide || true' in workflow_yaml
    assert (
        'kubectl get endpointslice --namespace "$K8S_NAMESPACE" -l kubernetes.io/service-name=site-web -o wide || true'
        in workflow_yaml
    )
    assert (
        'kubectl get managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" || true'
        in workflow_yaml
    )
    assert (
        'kubectl get frontendconfig "$MBSRN_FRONTEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true' in workflow_yaml
    )
    assert (
        'kubectl get backendconfig "$MBSRN_BACKEND_CONFIG_NAME" --namespace "$K8S_NAMESPACE" || true' in workflow_yaml
    )
    assert "exit 1" in workflow_yaml
    assert 'echo "resolved_live_url=$live_url"' in workflow_yaml
    assert 'echo "live_url=$live_url"' in workflow_yaml
    assert 'echo "deployed_url=$live_url"' in workflow_yaml
    assert 'echo "dns_record_matches_ingress=$dns_record_matches_ingress"' in workflow_yaml
    assert 'echo "dns_expected_ip=$dns_expected_ip"' in workflow_yaml
    assert 'echo "dns_observed_ip=$dns_observed_ip"' in workflow_yaml
    assert 'echo "expected_static_ip_address=$expected_static_ip_address"' in workflow_yaml
    assert 'echo "static_ip_status=$static_ip_status"' in workflow_yaml
    assert 'echo "static_ip_users=$static_ip_users"' in workflow_yaml
    assert 'echo "tls_certificate_status=$tls_certificate_status"' in workflow_yaml
    assert 'echo "tls_domain_status=$tls_domain_status"' in workflow_yaml
    assert 'echo "ingress_status_ip=$ingress_status_ip"' in workflow_yaml
    assert 'echo "ingress_status_ip_matches_static_ip=$ingress_status_ip_matches_static_ip"' in workflow_yaml
    assert (
        'echo "static_ip_bound_to_expected_forwarding_rule=$static_ip_bound_to_expected_forwarding_rule"'
        in workflow_yaml
    )
    assert 'echo "ingress_ip=$ingress_ip"' in workflow_yaml
    assert 'echo "ingress_conflict_detected=$ingress_conflict_detected"' in workflow_yaml
    assert 'echo "cert_identity_valid=$cert_identity_valid"' in workflow_yaml
    assert 'echo "host_reachable=$host_reachable"' in workflow_yaml
    assert 'echo "host_reachability_scheme=$host_reachability_scheme"' in workflow_yaml
    assert 'echo "https_probe_error_summary=$https_probe_error_summary"' in workflow_yaml
    assert 'echo "deploy_https_ready=$deploy_https_ready"' in workflow_yaml
    assert "trap finalize_resolve_live_url EXIT" in workflow_yaml
    assert 'resolve_live_url_exit_code="$?"' in workflow_yaml
    assert "emit_final_deploy_runtime_summary" in workflow_yaml
    assert 'observed_reason_code="runtime_readiness_unknown_failure"' in workflow_yaml
    assert "Managed-site runtime readiness failed before a precise reason was recorded." in workflow_yaml
    assert 'echo "resolve_live_url_state_mbsrn_managed_deploy_template_version=site_repo_template_v1"' in workflow_yaml
    assert (
        "mbsrn_managed_deploy_template_version: ${{ steps.resolve_live_url.outputs.mbsrn_managed_deploy_template_version }}"
        in workflow_yaml
    )
    assert "--format='json(name,address,status,users)'" in workflow_yaml
    assert 'dns_expected_ip="$expected_static_ip_address"' in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_status_ip_stale_or_mismatched" in workflow_yaml
    assert "deploy_runtime_reason_code=dns_record_mismatch" in workflow_yaml
    assert "deploy_runtime_reason_code=dns_points_to_old_ingress_ip" in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_ip_assigned_but_dns_not_updated" in workflow_yaml
    assert "deploy_runtime_reason_code=managed_certificate_provisioning" in workflow_yaml
    assert "deploy_runtime_reason_code=tls_certificate_provisioning" in workflow_yaml
    assert "deploy_runtime_reason_code=certificate_domain_mismatch" in workflow_yaml
    assert "deploy_runtime_reason_code=stale_managed_certificate_present" in workflow_yaml
    assert "deploy_runtime_reason_code=managed_certificate_ownership_unverified" in workflow_yaml
    assert "deploy_runtime_reason_code=expected_static_ip_not_bound_to_ingress" in workflow_yaml
    assert "deploy_runtime_reason_code=shared_static_ip_not_allowed_for_per_site_ingress" in workflow_yaml
    assert (
        'kubectl delete managedcertificate "$MBSRN_PREVIEW_CERTIFICATE_NAME" --namespace "$K8S_NAMESPACE" --ignore-not-found=true'
        not in workflow_yaml
    )
    assert "kubectl apply -f k8s/managedcertificate.yaml" not in workflow_yaml
    assert 'kubectl apply -f k8s/ingress.yaml --namespace "$K8S_NAMESPACE" >/dev/null 2>&1 || true' not in workflow_yaml
    assert 'echo "observed_managed_certificate_domains=$observed_managed_certificate_domains"' in workflow_yaml
    assert 'echo "observed_managed_certificate_status=$observed_managed_certificate_status"' in workflow_yaml
    assert (
        'echo "observed_managed_certificate_domain_status=$observed_managed_certificate_domain_status"' in workflow_yaml
    )
    assert (
        'echo "Site runtime image: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}"'
        in workflow_yaml
    )
    assert (
        'echo "Site runtime image selection mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}"'
        in workflow_yaml
    )
    assert "resources:" in deployment_yaml
    assert "image: ghcr.io/mhanson13/tnmfire-site-web:latest" in deployment_yaml
    assert "ghcr.io/mbsrn/site-web" not in deployment_yaml
    assert "imagePullSecrets:" in deployment_yaml
    assert "name: ghcr-pull-secret" in deployment_yaml
    assert "containerPort: 8080" in deployment_yaml
    assert "env:" in deployment_yaml
    assert "name: HOSTNAME" in deployment_yaml
    assert 'value: "0.0.0.0"' in deployment_yaml
    assert "name: PORT" in deployment_yaml
    assert 'value: "8080"' in deployment_yaml
    assert "readinessProbe:" in deployment_yaml
    assert "path: /" in deployment_yaml
    assert "port: 8080" in deployment_yaml
    assert "\n            - containerPort: 80\n" not in deployment_yaml
    assert "requests:" in deployment_yaml
    assert "cpu: 100m" in deployment_yaml
    assert "memory: 256Mi" in deployment_yaml
    assert "limits:" in deployment_yaml
    assert "cpu: 500m" in deployment_yaml
    assert "memory: 512Mi" in deployment_yaml
    assert "targetPort: 8080" in service_yaml
    assert "cloud.google.com/neg: '{\"ingress\": true}'" in service_yaml
    assert 'cloud.google.com/backend-config: \'{"default": "site-web-backend-config-tnmfire"}\'' in service_yaml
    assert "kubernetes.io/ingress.class: gce" in ingress_yaml
    assert "kubernetes.io/ingress.global-static-ip-name: site-web-preview-ip-tnmfire" in ingress_yaml
    assert "ingress.gcp.kubernetes.io/pre-shared-cert" not in ingress_yaml
    assert "networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire" in ingress_yaml
    assert "networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire," not in ingress_yaml
    assert "networking.gke.io/v1beta1.FrontendConfig: site-web-frontend-config-tnmfire" in ingress_yaml
    assert "ingressClassName: gce" in ingress_yaml
    assert "host: tnmfire.site.mbsrn.com" in ingress_yaml
    assert "kind: ManagedCertificate" in managed_certificate_yaml
    assert "name: site-web-preview-cert-tnmfire" in managed_certificate_yaml
    assert "domains:" in managed_certificate_yaml
    assert "- tnmfire.site.mbsrn.com" in managed_certificate_yaml
    assert "mbsrn.io/preview-hostname: tnmfire.site.mbsrn.com" in managed_certificate_yaml
    assert "kind: FrontendConfig" in frontend_config_yaml
    assert "name: site-web-frontend-config-tnmfire" in frontend_config_yaml
    assert "redirectToHttps:" in frontend_config_yaml
    assert "enabled: true" in frontend_config_yaml
    assert "kind: BackendConfig" in backend_config_yaml
    assert "name: site-web-backend-config-tnmfire" in backend_config_yaml
    assert "healthCheck:" in backend_config_yaml
    assert "type: HTTP" in backend_config_yaml
    assert "requestPath: /" in backend_config_yaml
    assert "port: 8080" in backend_config_yaml
    assert "checkIntervalSec: 10" in backend_config_yaml
    assert "timeoutSec: 5" in backend_config_yaml
    assert "healthyThreshold: 1" in backend_config_yaml
    assert "unhealthyThreshold: 3" in backend_config_yaml
    assert len(calls) == 33


def test_managed_site_runtime_template_includes_healthz_route() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    healthz_route_path = repo_root / "frontend" / "www" / "app" / "healthz" / "route.ts"
    home_page_path = repo_root / "frontend" / "www" / "app" / "page.tsx"

    route_content = healthz_route_path.read_text(encoding="utf-8")
    home_page_content = home_page_path.read_text(encoding="utf-8")

    assert "export function GET()" in route_content
    assert 'new Response("ok"' in route_content
    assert "status: 200" in route_content
    assert "export default function HomePage" in home_page_content


def test_rendered_managed_templates_enable_pull_secret_only_for_private_image_auth_mode() -> None:
    workflow_yaml = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-tnmfire-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config=None,
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        private_image_auth_required=True,
        site_id="site-tnmfire",
    )
    manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-tnmfire",
        private_image_auth_required=True,
    )
    deployment_yaml = manifests["k8s/deployment.yaml"]

    assert 'PRIVATE_IMAGE_AUTH_REQUIRED: "true"' in workflow_yaml
    assert "Verify GHCR image pull secret" in workflow_yaml
    assert 'kubectl get secret ghcr-pull-secret --namespace "$K8S_NAMESPACE"' in workflow_yaml
    assert "imagePullSecrets:" in deployment_yaml
    assert "name: ghcr-pull-secret" in deployment_yaml


def test_rendered_self_managed_tls_templates_use_compute_pre_shared_certificate() -> None:
    fingerprint = "ab" * 32
    workflow_yaml = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="platfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config={
            "project_id": "mbsrn-prod",
            "cluster_name": "mbsrn-prod",
            "cluster_location": "us-central1",
        },
        kubernetes_namespace="platfire",
        namespace_source="repo_name",
        preview_hostname="platfire.site.mbsrn.com",
        private_image_auth_required=True,
        site_id="site-platfire",
        pre_shared_certificate_name="mbsrn-platfire-ab12cd34",
        pre_shared_certificate_fingerprint=fingerprint,
    )
    manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="platfire",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        kubernetes_namespace="platfire",
        namespace_source="repo_name",
        preview_hostname="platfire.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-platfire",
        private_image_auth_required=True,
        pre_shared_certificate_name="mbsrn-platfire-ab12cd34",
    )

    parsed_workflow = yaml.safe_load(workflow_yaml)
    assert isinstance(parsed_workflow, dict)
    validate_deploy_step = next(
        step
        for step in parsed_workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Validate deploy configuration"
    )
    assert validate_deploy_step["env"]["MBSRN_GCP_DEPLOY_CREDENTIALS_CONFIGURED"] == (
        "${{ secrets.GCP_DEPLOY_KEY != '' }}"
    )
    assert "secrets.GCP_DEPLOY_KEY" not in validate_deploy_step["run"]
    assert 'test "${MBSRN_GCP_DEPLOY_CREDENTIALS_CONFIGURED:-false}" = "true"' in validate_deploy_step["run"]
    assert "k8s/managedcertificate.yaml" not in manifests
    assert "networking.gke.io/managed-certificates" not in manifests["k8s/ingress.yaml"]
    assert "ingress.gcp.kubernetes.io/pre-shared-cert: mbsrn-platfire-ab12cd34" in manifests["k8s/ingress.yaml"]
    assert "MBSRN_TLS_CERTIFICATE_MODE: self-managed" in workflow_yaml
    assert f"MBSRN_EXPECTED_CERTIFICATE_FINGERPRINT: {fingerprint}" in workflow_yaml
    assert "gcloud compute ssl-certificates describe" in workflow_yaml
    assert "--insecure" in workflow_yaml
    assert "certificate_fingerprint_mismatch" in workflow_yaml
    assert 'while [ "$tls_attempt" -le 30 ]' in workflow_yaml
    assert 'openssl x509 -in "$served_certificate" -noout -checkhost "$MBSRN_PREVIEW_HOSTNAME"' in workflow_yaml
    assert "kubectl get managedcertificate" not in workflow_yaml


def test_self_managed_tls_alignment_requires_exact_pre_shared_certificate_annotation() -> None:
    aligned, details = github_publisher_module._evaluate_preview_certificate_alignment(
        ingress_manifest_content=(
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  annotations:\n"
            "    ingress.gcp.kubernetes.io/pre-shared-cert: wrong-resource\n"
            "spec:\n"
            "  rules:\n"
            "    - host: platfire.site.mbsrn.com\n"
        ),
        managed_certificate_manifest_content=None,
        expected_preview_hostname="platfire.site.mbsrn.com",
        expected_certificate_name="mbsrn-platfire-preview-tls",
        expected_static_ip_name=None,
        self_managed_tls_mode=True,
    )

    assert aligned is False
    assert details["preview_certificate_valid_pre_shared_cert_binding"] is False
    assert details["ingress_certificate_mismatch"] is True
    assert details["stale_pre_shared_cert_binding_detected"] is True


def test_rendered_self_managed_tls_template_rejects_incomplete_certificate_identity() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        _render_managed_deploy_workflow_yaml(
            workflow_id="deploy-www-prod.yml",
            repo_owner="mhanson13",
            repo_name="platfire",
            branch="main",
            deploy_workflow_mode="site_repo_template_v1",
            target_environment_key="gke_prod",
            target_environment_source="admin_config",
            managed_gke_config=None,
            kubernetes_namespace="platfire",
            namespace_source="repo_name",
            preview_hostname="platfire.site.mbsrn.com",
            site_id="site-platfire",
            pre_shared_certificate_name="mbsrn-platfire-ab12cd34",
            pre_shared_certificate_fingerprint=None,
        )


def test_resolve_managed_preview_endpoint_configuration_uses_shared_gateway_for_managed_preview_when_configured() -> (
    None
):
    resolved = resolve_managed_preview_endpoint_configuration(
        repo_name="tnmfire",
        site_id="site-tnmfire",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults={
            "managed_preview_endpoint": {
                "mode": "auto",
                "shared_preview_static_ip_name": "site-preview-shared-ip",
            }
        },
    )

    assert resolved.get("effective_mode") == "preview_shared_gateway"
    assert resolved.get("uses_shared_preview_gateway") is True
    assert resolved.get("requires_dedicated_static_ip") is False
    assert resolved.get("expected_static_ip_name") == "site-preview-shared-ip"
    assert resolved.get("reason_code") is None


def test_resolve_managed_preview_endpoint_configuration_auto_without_shared_config_falls_back_to_dedicated() -> None:
    resolved = resolve_managed_preview_endpoint_configuration(
        repo_name="tnmfire",
        site_id="site-tnmfire",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults={
            "managed_preview_endpoint": {
                "mode": "auto",
                "shared_preview_static_ip_name": None,
            }
        },
    )

    assert resolved.get("effective_mode") == "dedicated_static_ip"
    assert resolved.get("uses_shared_preview_gateway") is False
    assert resolved.get("requires_dedicated_static_ip") is True
    assert str(resolved.get("expected_static_ip_name") or "").startswith("site-web-preview-ip-")
    assert resolved.get("reason_code") is None


def test_resolve_managed_preview_endpoint_configuration_preserves_dedicated_mode_when_explicit() -> None:
    resolved = resolve_managed_preview_endpoint_configuration(
        repo_name="tnmfire",
        site_id="site-tnmfire",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults={
            "managed_preview_endpoint": {
                "mode": "dedicated_static_ip",
                "shared_preview_static_ip_name": "site-preview-shared-ip",
            }
        },
    )

    assert resolved.get("effective_mode") == "dedicated_static_ip"
    assert resolved.get("uses_shared_preview_gateway") is False
    assert resolved.get("requires_dedicated_static_ip") is True
    assert resolved.get("expected_static_ip_name") != "site-preview-shared-ip"
    assert str(resolved.get("expected_static_ip_name") or "").startswith("site-web-preview-ip-")
    assert resolved.get("reason_code") is None


def test_build_managed_site_static_ip_labels_normalizes_values() -> None:
    labels = build_managed_site_static_ip_labels(
        repo_name="My.Repo_Name",
        site_id="Site 123_/Alpha",
        preview_hostname="Preview.Site.MBSRN.com.",
    )

    assert labels == {
        "mbsrn-managed-by": "mbsrn",
        "mbsrn-site-id": "site-123-alpha",
        "mbsrn-preview-hostname": "preview-site-mbsrn-com",
        "mbsrn-repo": "my-repo-name",
    }


def test_rendered_managed_templates_preserve_dedicated_mode_static_ip_binding_when_explicit() -> None:
    namespace_defaults = {
        "managed_preview_endpoint": {
            "mode": "dedicated_static_ip",
            "shared_preview_static_ip_name": "site-preview-shared-ip",
        }
    }
    workflow_yaml = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-tnmfire-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config=None,
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults=namespace_defaults,
        private_image_auth_required=False,
        site_id="site-tnmfire",
    )

    assert "MBSRN_PREVIEW_ENDPOINT_MODE: dedicated_static_ip" in workflow_yaml
    assert "MBSRN_PREVIEW_STATIC_IP_NAME: site-preview-shared-ip" not in workflow_yaml
    assert "MBSRN_PREVIEW_STATIC_IP_NAME: site-web-preview-ip-tnmfire" in workflow_yaml


def test_rendered_managed_templates_use_shared_preview_gateway_static_ip_when_configured() -> None:
    namespace_defaults = {
        "managed_preview_endpoint": {
            "mode": "preview_shared_gateway",
            "shared_preview_static_ip_name": "site-preview-shared-ip",
        }
    }
    workflow_yaml = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-tnmfire-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config=None,
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults=namespace_defaults,
        private_image_auth_required=False,
        site_id="site-tnmfire",
    )
    manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults=namespace_defaults,
        site_id="site-tnmfire",
    )
    ingress_yaml = manifests["k8s/ingress.yaml"]

    assert "MBSRN_PREVIEW_ENDPOINT_MODE: preview_shared_gateway" in workflow_yaml
    assert "MBSRN_PREVIEW_STATIC_IP_NAME: site-preview-shared-ip" in workflow_yaml
    assert "deploy_runtime_reason_code=shared_preview_gateway_missing" in workflow_yaml
    assert "kubernetes.io/ingress.global-static-ip-name: site-preview-shared-ip" in ingress_yaml


def test_rendered_managed_templates_add_gateway_canary_resources_when_explicitly_enabled() -> None:
    namespace_defaults = {
        "managed_preview_endpoint": {
            "mode": "preview_shared_gateway",
            "shared_preview_static_ip_name": "mbsrn-preview-edge-ip",
            "gateway_api_enabled": True,
            "gateway_name": "mbsrn-preview-gateway",
            "gateway_namespace": "mbsrn",
            "certificate_map_name": "mbsrn-preview-cert-map",
            "certificate_name": "mbsrn-preview-wildcard",
            "dns_authorization_name": "mbsrn-preview-dns-auth",
            "certificate_domain": "*.site.mbsrn.com",
        }
    }

    manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="platfire",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        kubernetes_namespace="platfire",
        namespace_source="preview_slug",
        preview_hostname="platfire.site.mbsrn.com",
        namespace_isolation_defaults=namespace_defaults,
        site_id="site-platfire",
        pre_shared_certificate_name="mbsrn-preview-platfire-abcd",
    )

    assert "k8s/ingress.yaml" in manifests
    assert "k8s/gateway-service.yaml" in manifests
    assert "k8s/gateway-healthcheckpolicy.yaml" in manifests
    assert "k8s/httproute.yaml" in manifests
    namespace = yaml.safe_load(manifests["k8s/namespace.yaml"])
    gateway_service = yaml.safe_load(manifests["k8s/gateway-service.yaml"])
    route = yaml.safe_load(manifests["k8s/httproute.yaml"])
    assert namespace["metadata"]["labels"]["mbsrn.io/preview-route-access"] == "true"
    assert gateway_service["metadata"]["name"] == "site-web-gateway"
    assert "annotations" not in gateway_service["metadata"]
    assert route["spec"]["parentRefs"] == [
        {"name": "mbsrn-preview-gateway", "namespace": "mbsrn", "sectionName": "https"}
    ]
    assert route["spec"]["hostnames"] == ["platfire.site.mbsrn.com"]
    assert "ingress.gcp.kubernetes.io/pre-shared-cert: mbsrn-preview-platfire-abcd" in manifests[
        "k8s/ingress.yaml"
    ]


def test_rendered_managed_templates_reject_incomplete_enabled_gateway_configuration() -> None:
    with pytest.raises(ValueError, match="Shared preview Gateway configuration is incomplete"):
        _render_managed_gke_manifest_files(
            repo_owner="mhanson13",
            repo_name="platfire",
            target_environment_key="gke_prod",
            target_environment_source="admin_config",
            kubernetes_namespace="platfire",
            namespace_source="preview_slug",
            preview_hostname="platfire.site.mbsrn.com",
            namespace_isolation_defaults={
                "managed_preview_endpoint": {
                    "mode": "preview_shared_gateway",
                    "shared_preview_static_ip_name": "mbsrn-preview-edge-ip",
                    "gateway_api_enabled": True,
                }
            },
            site_id="site-platfire",
            pre_shared_certificate_name="mbsrn-preview-platfire-abcd",
        )


def test_render_managed_gke_manifests_network_policy_allows_site_web_probe_without_broad_ingress() -> None:
    manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_environment_key="gke-prod",
        target_environment_source="admin_config",
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults={
            "network_policy": {"enabled": True, "mode": "default_deny_ingress"},
        },
        site_id="site-tnmfire",
    )
    network_policy_yaml = manifests["k8s/networkpolicy.yaml"]
    parsed_docs = [doc for doc in yaml.safe_load_all(network_policy_yaml) if isinstance(doc, dict)]
    assert len(parsed_docs) == 2
    policies_by_name = {str((doc.get("metadata") or {}).get("name") or ""): doc for doc in parsed_docs}

    default_deny_policy = policies_by_name.get("site-default-deny-ingress")
    assert isinstance(default_deny_policy, dict)
    assert (default_deny_policy.get("spec") or {}).get("podSelector") == {}
    assert (default_deny_policy.get("spec") or {}).get("policyTypes") == ["Ingress"]
    assert (default_deny_policy.get("spec") or {}).get("ingress") in (None, [])

    allow_policy = policies_by_name.get("site-web-allow-managed-ingress")
    assert isinstance(allow_policy, dict)
    allow_spec = allow_policy.get("spec") or {}
    assert allow_spec.get("podSelector") == {"matchLabels": {"app.kubernetes.io/name": "site-web"}}
    assert allow_spec.get("policyTypes") == ["Ingress"]
    ingress_rules = allow_spec.get("ingress") or []
    assert len(ingress_rules) == 2
    assert (ingress_rules[0].get("from") or []) == [{"podSelector": {}}]
    assert (ingress_rules[0].get("ports") or []) == [{"protocol": "TCP", "port": 8080}]
    health_check_sources = sorted(
        str((source.get("ipBlock") or {}).get("cidr") or "")
        for source in (ingress_rules[1].get("from") or [])
        if isinstance(source, dict)
    )
    assert health_check_sources == ["130.211.0.0/22", "35.191.0.0/16"]
    assert (ingress_rules[1].get("ports") or []) == [{"protocol": "TCP", "port": 8080}]
    assert "namespaceSelector" not in network_policy_yaml
    assert "0.0.0.0/0" not in network_policy_yaml


def test_rendered_managed_workflow_yaml_parses_embedded_certificate_evaluation_script() -> None:
    workflow_yaml = _render_default_managed_workflow_yaml()

    parsed_workflow = yaml.safe_load(workflow_yaml)
    assert isinstance(parsed_workflow, dict)
    top_level_keys = {str(key) for key in parsed_workflow.keys()}
    for unexpected_python_key in ("import", "raw", "expected_host", "payload", "spec_domains"):
        assert unexpected_python_key not in top_level_keys

    run_script = _extract_resolve_live_url_run_script(workflow_yaml)
    assert "python - <<'PY'" in run_script
    assert "import json" in run_script
    assert "expected_host = str(os.environ.get('EXPECTED_PREVIEW_HOST') or '').strip().lower()" in run_script
    assert "payload = json.loads(raw) if raw else {}" in run_script
    assert "expected_static_ip_address" in run_script
    assert "static_ip_status" in run_script
    assert "static_ip_users" in run_script
    assert "ingress_status_ip" in run_script
    assert "ingress_status_ip_matches_static_ip" in run_script
    assert "static_ip_bound_to_expected_forwarding_rule" in run_script
    assert "evaluate_managed_certificate() {" in run_script
    assert "apply_managed_certificate_eval_output() {" in run_script
    assert "resource_name_matches_expected" in run_script
    assert "managed_certificate_ownership_verified" in run_script
    assert "deploy_runtime_reason_code=certificate_domain_mismatch" in run_script
    assert "deploy_runtime_reason_code=stale_managed_certificate_present" in run_script
    assert "deploy_runtime_reason_code=managed_certificate_ownership_unverified" in run_script
    assert "deploy_runtime_reason_code=managed_certificate_pending" in run_script
    assert "deploy_runtime_reason_code=https_probe_failed" in run_script
    assert "deploy_runtime_reason_code=ingress_status_ip_stale_or_mismatched" in run_script
    assert "emit_resolve_live_url_state()" in run_script
    assert "resolve_live_url_state_host_reachable" in run_script
    assert "resolve_live_url_state_deploy_https_ready" in run_script
    assert "resolve_live_url_state_static_ip_users" in run_script
    assert "resolve_live_url_state_ingress_status_ip" in run_script
    assert "resolve_live_url_state_observed_managed_certificate_domains" in run_script
    assert "resolve_live_url_state_https_probe_error_summary" in run_script
    assert "resolve_live_url_state_preview_https_status" in run_script
    assert "resolve_live_url_state_gce_backend_health_status" in run_script
    assert "resolve_live_url_state_service_probe_status" in run_script
    assert "resolve_live_url_state_endpoint_probe_status" in run_script
    assert "resolve_live_url_state_runtime_probe_status" in run_script
    assert "set_https_probe_error_summary() {" in run_script
    assert "ensure_https_probe_error_summary() {" in run_script
    assert "collect_ingress_502_runtime_diagnostics() {" in run_script
    assert 'kubectl -n "$K8S_NAMESPACE" get pods -l app.kubernetes.io/name=site-web -o wide || true' in run_script
    assert (
        'kubectl -n "$K8S_NAMESPACE" logs -l app.kubernetes.io/name=site-web --tail=200 --all-containers=true'
        in run_script
    )
    assert (
        'kubectl -n "$K8S_NAMESPACE" logs -l app.kubernetes.io/name=site-web --previous --tail=100 --all-containers=true'
        in run_script
    )
    assert 'kubectl -n "$K8S_NAMESPACE" get deploy site-web -o yaml' in run_script
    assert 'kubectl -n "$K8S_NAMESPACE" get rs -l app.kubernetes.io/name=site-web -o wide || true' in run_script
    assert 'kubectl -n "$K8S_NAMESPACE" get events --sort-by=.lastTimestamp || true' in run_script
    assert "http://site-web.${K8S_NAMESPACE}.svc.cluster.local:80/" in run_script
    assert 'runtime_probe_status="ingress_or_edge_convergence"' in run_script
    assert 'fallback_reason="dns_not_ready"' in run_script
    assert 'fallback_reason="cert_not_ready"' in run_script
    assert 'fallback_reason="host_resolution_pending"' in run_script
    assert "ensure_https_probe_error_summary" in run_script
    assert "http_fallback_attempted=$http_fallback_attempted" in run_script
    assert "collect_resolve_live_url_evidence() {" in run_script
    assert "collect_resolve_live_url_evidence" in run_script
    assert "STATIC_IP_METADATA_JSON=\"$static_ip_metadata_json\" python - <<'PY'" in run_script
    assert 'MANAGED_CERTIFICATE_JSON="$managed_certificate_json" EXPECTED_PREVIEW_HOST' in run_script
    assert 'MANAGED_CERTIFICATE_JSON="$managed_certificate_payload" EXPECTED_PREVIEW_HOST' in run_script
    assert "sys.stdin.read().strip()" not in run_script
    assert "Ingress external address observed after HTTPS success verification." in run_script
    assert (
        'if [ "$host_reachable" = true ] && [ "$host_reachability_scheme" = "https" ] && [ -z "$ingress_ip" ]; then'
        in run_script
    )
    assert 'if [ -z "$ingress_ip" ] && [ "$host_reachable" != "true" ]; then' in run_script
    assert 'if [ -z "$ingress_ip" ]; then' not in run_script
    assert 'echo "live_url=$live_url"' in run_script
    assert 'echo "host_reachable=$host_reachable"' in run_script
    assert 'echo "host_reachability_scheme=$host_reachability_scheme"' in run_script
    assert 'echo "https_probe_error_summary=$https_probe_error_summary"' in run_script
    assert 'echo "deploy_https_ready=$deploy_https_ready"' in run_script
    assert 'echo "deploy_runtime_reason_code=ingress_address_pending"' in run_script
    assert 'echo "deploy_runtime_reason_code=ingress_backend_502"' in run_script
    assert 'echo "deploy_runtime_reason_code=https_probe_timeout"' in run_script
    assert 'echo "deploy_runtime_reason_code=https_probe_empty_reply"' in run_script
    assert 'echo "deploy_runtime_reason_code=https_probe_not_attempted"' in run_script
    assert 'echo "deploy_runtime_reason_code=https_probe_failed_after_control_plane_ready"' in run_script
    assert 'echo "deploy_runtime_reason_code=reachable_but_tls_certificate_mismatch"' in run_script
    assert 'echo "deploy_runtime_reason_code=tls_certificate_bound_to_wrong_site"' in run_script
    assert 'echo "deploy_runtime_reason_code=managed_certificate_metadata_unavailable"' in run_script
    assert 'if [ "$managed_certificate_metadata_available" != "true" ]' in run_script
    assert '&& [ "$host_reachable" = true ]' in run_script
    assert '&& [ "$host_reachability_scheme" = "https" ]' in run_script
    assert '&& [ "$dns_record_matches_ingress" = "true" ]' in run_script
    assert '&& [ "$managed_cert_annotation_first" = "$expected_cert_name" ]; then' in run_script
    assert 'echo "observed_managed_certificate_domains=$observed_managed_certificate_domains"' in run_script
    assert (
        'if [ -z "$ingress_status_ip" ] && [ -z "$expected_static_ip_address" ] && [ "$host_reachable" != "true" ]; then'
        in run_script
    )
    assert 'dns_expected_ip="$expected_static_ip_address"' in run_script
    evidence_collect_index = run_script.index("collect_resolve_live_url_evidence")
    tls_failure_index = run_script.index('if [ "$tls_mismatch_detected" = true ]; then')
    assert evidence_collect_index < tls_failure_index
    static_ip_collect_index = run_script.index("static_ip_metadata_json=")
    dns_collect_index = run_script.index("dns_observed_ip=")
    https_failed_index = run_script.index("deploy_runtime_reason_code=https_probe_failed")
    cert_collect_index = run_script.index("managed_certificate_json=")
    cert_missing_index = run_script.index("deploy_runtime_reason_code=runtime_managed_certificate_missing_after_apply")
    cert_reason_index = run_script.index("deploy_runtime_reason_code=tls_certificate_bound_to_wrong_site")
    assert static_ip_collect_index < tls_failure_index
    assert dns_collect_index < https_failed_index
    assert cert_collect_index < cert_missing_index
    assert cert_collect_index < cert_reason_index
    annotation_mismatch_index = run_script.index("deploy_runtime_reason_code=ingress_certificate_annotation_mismatch")
    cert_domain_mismatch_index = run_script.index("deploy_runtime_reason_code=certificate_domain_mismatch")
    assert annotation_mismatch_index < cert_domain_mismatch_index
    assert 'tls_certificate_status="MISSING"' in run_script
    assert "expected_managed_certificate_name=$MBSRN_PREVIEW_CERTIFICATE_NAME" in run_script
    assert (
        "Neither ingress status IP nor reserved static IP address is available for DNS/TLS validation yet."
        in run_script
    )

    try:
        syntax_check = subprocess.run(
            ["bash", "-n"],
            input=run_script.encode("utf-8"),
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("bash is required to syntax-check rendered managed workflow shell script")
    assert syntax_check.returncode == 0, syntax_check.stderr.decode("utf-8", errors="replace")


def test_render_managed_gke_manifests_for_sc_mechanical_is_site_scoped() -> None:
    manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="sc-mechanical",
        target_environment_key="gke-prod",
        target_environment_source="admin_config",
        kubernetes_namespace="sc-mechanical",
        namespace_source="repo_name",
        preview_hostname="sc-mechanical.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-sc-mechanical",
    )
    ingress_yaml = manifests["k8s/ingress.yaml"]
    managed_certificate_yaml = manifests["k8s/managedcertificate.yaml"]
    service_yaml = manifests["k8s/service.yaml"]
    frontend_config_yaml = manifests["k8s/frontendconfig.yaml"]
    backend_config_yaml = manifests["k8s/backendconfig.yaml"]

    assert "host: sc-mechanical.site.mbsrn.com" in ingress_yaml
    assert "kubernetes.io/ingress.global-static-ip-name: site-web-preview-ip-sc-mechanical" in ingress_yaml
    assert "networking.gke.io/managed-certificates: site-web-preview-cert-sc-mechanical" in ingress_yaml
    assert "networking.gke.io/v1beta1.FrontendConfig: site-web-frontend-config-sc-mechanical" in ingress_yaml
    assert "name: site-web-preview-cert-sc-mechanical" in managed_certificate_yaml
    assert "- sc-mechanical.site.mbsrn.com" in managed_certificate_yaml
    assert "mbsrn.io/preview-hostname: sc-mechanical.site.mbsrn.com" in managed_certificate_yaml
    assert 'cloud.google.com/backend-config: \'{"default": "site-web-backend-config-sc-mechanical"}\'' in service_yaml
    assert "name: site-web-frontend-config-sc-mechanical" in frontend_config_yaml
    assert "name: site-web-backend-config-sc-mechanical" in backend_config_yaml
    assert "tnmfire.site.mbsrn.com" not in ingress_yaml
    assert "tnmfire.site.mbsrn.com" not in managed_certificate_yaml
    assert "site-web-preview-cert-tnmfire" not in ingress_yaml
    assert "site-web-preview-cert-tnmfire" not in managed_certificate_yaml


def test_render_managed_gke_manifests_isolated_across_sequential_sites() -> None:
    tnmfire_manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_environment_key="gke-prod",
        target_environment_source="admin_config",
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-tnmfire",
    )
    sc_mechanical_manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="sc-mechanical",
        target_environment_key="gke-prod",
        target_environment_source="admin_config",
        kubernetes_namespace="sc-mechanical",
        namespace_source="repo_name",
        preview_hostname="sc-mechanical.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-sc-mechanical",
    )

    tnmfire_ingress = tnmfire_manifests["k8s/ingress.yaml"]
    sc_mechanical_ingress = sc_mechanical_manifests["k8s/ingress.yaml"]
    tnmfire_cert = tnmfire_manifests["k8s/managedcertificate.yaml"]
    sc_mechanical_cert = sc_mechanical_manifests["k8s/managedcertificate.yaml"]
    tnmfire_service = tnmfire_manifests["k8s/service.yaml"]
    sc_mechanical_service = sc_mechanical_manifests["k8s/service.yaml"]

    assert "host: tnmfire.site.mbsrn.com" in tnmfire_ingress
    assert "host: sc-mechanical.site.mbsrn.com" in sc_mechanical_ingress
    assert "site-web-preview-cert-tnmfire" in tnmfire_ingress
    assert "site-web-preview-cert-sc-mechanical" in sc_mechanical_ingress
    assert "site-web-frontend-config-tnmfire" in tnmfire_ingress
    assert "site-web-frontend-config-sc-mechanical" in sc_mechanical_ingress
    assert "site-web-backend-config-tnmfire" in tnmfire_service
    assert "site-web-backend-config-sc-mechanical" in sc_mechanical_service
    assert "site-web-preview-cert-sc-mechanical" not in tnmfire_cert
    assert "site-web-preview-cert-tnmfire" not in sc_mechanical_cert
    assert "tnmfire.site.mbsrn.com" not in sc_mechanical_cert
    assert "sc-mechanical.site.mbsrn.com" not in tnmfire_cert


def test_managed_site_runtime_image_identity_is_repo_scoped_across_sites() -> None:
    tnmfire_workflow = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-tnmfire-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config=None,
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        private_image_auth_required=False,
        site_id="site-tnmfire",
    )
    sc_workflow = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-scmechanical-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="scmechanical",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config=None,
        kubernetes_namespace="scmechanical",
        namespace_source="repo_name",
        preview_hostname="scmechanical.site.mbsrn.com",
        private_image_auth_required=False,
        site_id="site-scmechanical",
    )
    tnmfire_manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        kubernetes_namespace="tnmfire",
        namespace_source="repo_name",
        preview_hostname="tnmfire.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-tnmfire",
    )
    sc_manifests = _render_managed_gke_manifest_files(
        repo_owner="mhanson13",
        repo_name="scmechanical",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        kubernetes_namespace="scmechanical",
        namespace_source="repo_name",
        preview_hostname="scmechanical.site.mbsrn.com",
        namespace_isolation_defaults=None,
        site_id="site-scmechanical",
    )

    assert "SITE_WEB_IMAGE_REPOSITORY: ghcr.io/mhanson13/tnmfire-site-web" in tnmfire_workflow
    assert "SITE_WEB_IMAGE_REPOSITORY: ghcr.io/mhanson13/scmechanical-site-web" in sc_workflow
    assert "MBSRN_PREVIEW_HOSTNAME: tnmfire.site.mbsrn.com" in tnmfire_workflow
    assert "MBSRN_PREVIEW_HOSTNAME: scmechanical.site.mbsrn.com" in sc_workflow
    assert 'dig +short "$preview_host" A' in tnmfire_workflow
    assert 'dig +short "$preview_host" A' in sc_workflow
    assert "image: ghcr.io/mhanson13/tnmfire-site-web:latest" in tnmfire_manifests["k8s/deployment.yaml"]
    assert "image: ghcr.io/mhanson13/scmechanical-site-web:latest" in sc_manifests["k8s/deployment.yaml"]
    assert "ghcr.io/mhanson13/site-web:latest" not in tnmfire_workflow
    assert "ghcr.io/mhanson13/site-web:latest" not in sc_workflow
    assert "ghcr.io/mbsrn/site-web:latest" not in tnmfire_workflow
    assert "ghcr.io/mbsrn/site-web:latest" not in sc_workflow


def test_ensure_deploy_workflow_renders_admin_managed_gke_values_before_repo_fallback(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_put_payload: dict[str, object] = {}
    queue = _managed_provisioning_responses()

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
            and request.data
        ):
            captured_put_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
        managed_gke_config={
            "cluster_name": "mbsrn-cluster",
            "cluster_location": "us-central1",
            "project_id": "mbsrn-prod",
        },
    )
    encoded_content = str(captured_put_payload.get("content") or "")
    assert encoded_content
    workflow_yaml = base64.b64decode(encoded_content).decode("utf-8")
    assert "GKE_CLUSTER_NAME: 'mbsrn-cluster'" in workflow_yaml
    assert "GKE_CLUSTER_LOCATION: 'us-central1'" in workflow_yaml
    assert "GKE_PROJECT_ID: 'mbsrn-prod'" in workflow_yaml
    assert (
        "GKE_CLUSTER_NAME: ${{ vars.KUBERNETES_CLUSTER_NAME || secrets.KUBERNETES_CLUSTER_NAME }}" not in workflow_yaml
    )
    assert (
        "GKE_CLUSTER_LOCATION: ${{ vars.KUBERNETES_CLUSTER_LOCATION || secrets.KUBERNETES_CLUSTER_LOCATION }}"
        not in workflow_yaml
    )
    assert "GKE_PROJECT_ID: ${{ vars.GCP_PROJECT_ID || secrets.GCP_PROJECT_ID }}" not in workflow_yaml


def test_ensure_deploy_workflow_upgrades_platform_managed_placeholder_workflow(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_workflow_put_payload: dict[str, object] = {}
    placeholder_workflow_content = _encode_workflow_yaml(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Placeholder deploy\n"
            '        run: echo "Deploy workflow (deploy-tnmfire-www-prod.yml) provisioned; customize before production rollout."\n'
        )
    )
    custom_manifest_content = _encode_workflow_yaml("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: placeholder\n")
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
        _managed_workflow_verify_response(sha="workflow-verified-upsert"),
    ]
    for index in range(1, 9):
        queue.append(
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": f"manifest-custom-{index}",
                        "encoding": "base64",
                        "content": custom_manifest_content,
                    }
                ),
            )
        )
    queue.append(_managed_workflow_verify_response(sha="workflow-verified-final"))

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
            and request.data
        ):
            captured_workflow_put_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )
    assert result.provisioned is True
    assert result.workflow_path == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert any(
        method == "PUT" and url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
        for method, url in calls
    )
    encoded_content = str(captured_workflow_put_payload.get("content") or "")
    assert encoded_content
    upgraded_workflow = base64.b64decode(encoded_content).decode("utf-8")
    assert "Authenticate to GCP" in upgraded_workflow
    assert "Get GKE credentials" in upgraded_workflow
    assert "Apply managed manifests" in upgraded_workflow
    assert "Resolve live URL from ingress status" in upgraded_workflow
    assert "customize before production rollout" not in upgraded_workflow.lower()
    assert "placeholder deploy" not in upgraded_workflow.lower()
    assert result.managed_workflow_outcome == "managed_workflow_upgraded"


def test_ensure_deploy_workflow_upgrades_legacy_platform_placeholder_workflow(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_workflow_put_payload: dict[str, object] = {}
    placeholder_workflow_content = _encode_workflow_yaml(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Placeholder deploy\n"
            '        run: echo "Deploy step not yet implemented"\n'
        )
    )
    custom_manifest_content = _encode_workflow_yaml("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: placeholder\n")
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
        _managed_workflow_verify_response(sha="workflow-verified-upsert"),
    ]
    for index in range(1, 9):
        queue.append(
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": f"manifest-custom-{index}",
                        "encoding": "base64",
                        "content": custom_manifest_content,
                    }
                ),
            )
        )
    queue.append(_managed_workflow_verify_response(sha="workflow-verified-final"))

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
            and request.data
        ):
            captured_workflow_put_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )
    assert result.provisioned is True
    assert result.workflow_path == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert any(
        method == "PUT" and url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
        for method, url in calls
    )
    encoded_content = str(captured_workflow_put_payload.get("content") or "")
    assert encoded_content
    upgraded_workflow = base64.b64decode(encoded_content).decode("utf-8")
    assert "Authenticate to GCP" in upgraded_workflow
    assert "Get GKE credentials" in upgraded_workflow
    assert "Apply managed manifests" in upgraded_workflow
    assert "Resolve live URL from ingress status" in upgraded_workflow
    assert "deploy step not yet implemented" not in upgraded_workflow.lower()
    assert "placeholder deploy" not in upgraded_workflow.lower()
    assert result.managed_workflow_outcome == "managed_workflow_upgraded"


def test_ensure_deploy_workflow_uses_production_template_for_unknown_mode(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_workflow_put_payload: dict[str, object] = {}
    queue = _managed_provisioning_responses()

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
            and request.data
        ):
            captured_workflow_put_payload.update(json.loads(request.data.decode("utf-8")))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
        deploy_workflow_mode="legacy_scaffold_v0",
    )
    assert result.provisioned is True
    encoded_content = str(captured_workflow_put_payload.get("content") or "")
    assert encoded_content
    rendered_workflow = base64.b64decode(encoded_content).decode("utf-8")
    assert "workflow_dispatch" in rendered_workflow
    assert "google-github-actions/auth@v2" in rendered_workflow
    assert "google-github-actions/get-gke-credentials@v2" in rendered_workflow
    assert "Ensure managed-site endpoint prerequisites" in rendered_workflow
    assert "kubectl apply -f k8s/managedcertificate.yaml" not in rendered_workflow
    assert 'apply_manifest_if_present "k8s/managedcertificate.yaml"' not in rendered_workflow
    assert "kubectl apply -f k8s/\n" not in rendered_workflow
    assert "resolved_live_url" in rendered_workflow
    assert "placeholder deploy" not in rendered_workflow.lower()
    assert "provisioned in mode" not in rendered_workflow.lower()


def test_publish_upgrade_and_readiness_validate_same_workflow_path_and_ref(monkeypatch, caplog) -> None:
    calls: list[tuple[str, str]] = []
    placeholder_workflow_content = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "# mbsrn managed deploy placeholder\n"
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Placeholder deploy\n"
            '        run: echo "Deploy step not yet implemented"\n'
        )
    )
    queue = _managed_provisioning_responses()
    queue[5] = _FakeHTTPResponse(
        status=200,
        body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
    )
    queue.extend(
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _managed_workflow_verify_response(sha="workflow-readiness"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "state": "active",
                        "path": ".github/workflows/deploy-tnmfire-www-prod.yml",
                    }
                ),
            ),
            _managed_file_verify_response(sha="manifest-r-1", marker="mbsrn-managed-manifest:site_repo_template_v1"),
            _managed_file_verify_response(sha="manifest-r-2", marker="mbsrn-managed-manifest:site_repo_template_v1"),
            _managed_file_verify_response(sha="manifest-r-3", marker="mbsrn-managed-manifest:site_repo_template_v1"),
            _managed_file_verify_response(sha="manifest-r-4", marker="mbsrn-managed-manifest:site_repo_template_v1"),
            *_gke_environment_config_present_responses(),
        ]
    )
    _install_urlopen_stub(monkeypatch, queue, calls)
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    provision_result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )
    assert provision_result.workflow_path == ".github/workflows/deploy-tnmfire-www-prod.yml"
    readiness_result = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness_result.workflow_path == ".github/workflows/deploy-tnmfire-www-prod.yml"
    assert readiness_result.requested_ref == "main"
    assert readiness_result.resolved_ref == "main"
    assert readiness_result.workflow_conformance_status == "conformant"
    assert readiness_result.workflow_dispatch_ready is True
    assert any(
        method == "PUT" and url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
        for method, url in calls
    )
    assert any(
        method == "GET" and url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main")
        for method, url in calls
    )
    assert any(
        method == "GET" and url.endswith("/actions/workflows/deploy-tnmfire-www-prod.yml") for method, url in calls
    )
    upsert_decision_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str)
        and '"event": "seo_migration_publish_workflow_file_upsert_decision"' in record.msg
    ]
    assert upsert_decision_logs
    assert '"managed_workflow_outcome": "managed_workflow_upgraded"' in upsert_decision_logs[-1].msg


def test_ensure_deploy_workflow_preserves_unknown_custom_workflow(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    custom_workflow_content = _encode_workflow_yaml(
        (
            "name: Custom Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Custom step\n"
            "        run: echo custom deploy\n"
        )
    )
    custom_manifest_content = _encode_workflow_yaml("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: custom\n")
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "custom-workflow-sha", "encoding": "base64", "content": custom_workflow_content}),
        ),
    ]
    for index in range(1, 9):
        queue.append(
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": f"manifest-custom-{index}",
                        "encoding": "base64",
                        "content": custom_manifest_content,
                    }
                ),
            )
        )
    queue.append(
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "custom-workflow-sha", "encoding": "base64", "content": custom_workflow_content}),
        )
    )

    _install_urlopen_stub(monkeypatch, queue, calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )
    assert result.provisioned is False
    assert result.managed_workflow_outcome == "managed_workflow_preserved_custom"
    assert not any(
        method == "PUT" and url.endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
        for method, url in calls
    )


def test_ensure_deploy_workflow_includes_optional_namespace_policy_manifests_when_enabled(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_paths = (
        ".github/workflows/deploy-tnmfire-www-prod.yml",
        "k8s/namespace.yaml",
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
        "k8s/managedcertificate.yaml",
        "k8s/frontendconfig.yaml",
        "k8s/backendconfig.yaml",
        "k8s/resourcequota.yaml",
        "k8s/limitrange.yaml",
        "k8s/networkpolicy.yaml",
    )
    _install_urlopen_stub(
        monkeypatch,
        _managed_provisioning_responses_with_paths(managed_paths=managed_paths),
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
        namespace_isolation_defaults={
            "resource_quota": {"enabled": True},
            "limit_range": {"enabled": True},
            "network_policy": {"enabled": True, "mode": "default_deny_ingress"},
        },
    )

    assert result.provisioned is True
    assert result.managed_manifest_paths == (
        "k8s/namespace.yaml",
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
        "k8s/managedcertificate.yaml",
        "k8s/frontendconfig.yaml",
        "k8s/backendconfig.yaml",
        "k8s/resourcequota.yaml",
        "k8s/limitrange.yaml",
        "k8s/networkpolicy.yaml",
    )
    assert result.managed_resource_quota_expected is True
    assert result.managed_resource_quota_present is True
    assert result.managed_limit_range_expected is True
    assert result.managed_limit_range_present is True
    assert result.managed_network_policy_expected is True
    assert result.managed_network_policy_present is True
    assert result.managed_namespace_policies_aligned is True
    assert any(call[1].endswith("/contents/k8s/resourcequota.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/limitrange.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/networkpolicy.yaml?ref=main") for call in calls)


def test_ensure_deploy_workflow_fails_when_upgraded_workflow_is_not_conformant(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    placeholder_workflow_content = _encode_workflow_yaml(
        (
            "name: Deploy Site\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Placeholder deploy\n"
            '        run: echo "Deploy workflow (deploy-tnmfire-www-prod.yml) provisioned; customize before production rollout."\n'
        )
    )
    non_conformant_workflow_content = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - name: Verify only\n"
            "        run: echo no deploy markers\n"
        )
    )
    custom_manifest_content = _encode_workflow_yaml("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: placeholder\n")
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"object": {"sha": "main-sha"}})),
        _repo_management_marker_response(),
        _FakeHTTPResponse(status=200, body=json.dumps({"name": "main"})),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
        _managed_workflow_verify_response(sha="workflow-verified-upsert"),
    ]
    for index in range(1, 9):
        queue.append(
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {
                        "sha": f"manifest-custom-{index}",
                        "encoding": "base64",
                        "content": custom_manifest_content,
                    }
                ),
            )
        )
    queue.append(
        _FakeHTTPResponse(
            status=200,
            body=json.dumps(
                {
                    "sha": "workflow-verified-final",
                    "encoding": "base64",
                    "content": non_conformant_workflow_content,
                }
            ),
        )
    )
    _install_urlopen_stub(monkeypatch, queue, calls)
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
        )
    assert exc_info.value.code == "workflow_provisioning_failed"
    assert exc_info.value.stage == "workflow_provisioning"


def test_ensure_deploy_workflow_fails_when_post_write_verification_missing(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    _install_urlopen_stub(
        monkeypatch,
        _managed_provisioning_responses(missing_verify_path=".github/workflows/deploy-tnmfire-www-prod.yml"),
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.ensure_deploy_workflow(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            branch="main",
            workflow_id="deploy-tnmfire-www-prod.yml",
            dry_run=False,
        )
    assert exc_info.value.code == "workflow_provisioning_failed"
    assert exc_info.value.stage == "workflow_provisioning"
    assert len(calls) >= 5


def test_check_deploy_target_readiness_flags_missing_expected_resource_quota_manifest(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/k8s/resourcequota.yaml?ref=main",
                status_code=404,
                message="Not Found",
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        namespace_isolation_defaults={
            "resource_quota": {"enabled": True},
        },
    )

    assert readiness.workflow_dispatch_ready is True
    assert readiness.managed_resource_quota_expected is True
    assert readiness.managed_resource_quota_present is False
    assert readiness.managed_limit_range_expected is False
    assert readiness.managed_network_policy_expected is False
    assert readiness.managed_namespace_policies_aligned is False
    assert readiness.namespace_model_status == "misaligned"
    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "target_configuration_invalid"
    assert any(call[1].endswith("/contents/k8s/resourcequota.yaml?ref=main") for call in calls)


def test_check_deploy_target_readiness_flags_certificate_domain_mismatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_mismatched = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-sc-mechanical\n"
            "spec:\n"
            "  rules:\n"
            "    - host: sc-mechanical.site.mbsrn.com\n"
        )
    )
    certificate_manifest_mismatched = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-sc-mechanical\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - sc-mechanical.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_mismatched}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_mismatched}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "tls_certificate_bound_to_wrong_site"
    details = readiness.managed_gke_config_details or {}
    assert details.get("preview_certificate_alignment_status") == "mismatched"
    assert details.get("expected_preview_hostname") == "tnmfire.site.mbsrn.com"
    assert details.get("preview_certificate_domains") == ["sc-mechanical.site.mbsrn.com"]


def test_check_deploy_target_readiness_flags_stale_managed_certificate_present(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_with_stale = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire,site-web-preview-cert-sc-mechanical\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_stale}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "managed_certificate_identity_mismatch"
    details = readiness.managed_gke_config_details or {}
    assert details.get("stale_managed_certificate_present") is True
    assert details.get("stale_managed_certificate_names") == ["site-web-preview-cert-sc-mechanical"]
    assert details.get("preview_certificate_ingress_annotation_values") == [
        "site-web-preview-cert-tnmfire",
        "site-web-preview-cert-sc-mechanical",
    ]


def test_check_deploy_target_readiness_flags_ingress_certificate_mismatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_mismatched_annotation = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-sc-mechanical\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_mismatched_annotation}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "ingress_certificate_annotation_mismatch"
    details = readiness.managed_gke_config_details or {}
    assert details.get("ingress_certificate_mismatch") is True
    assert details.get("stale_managed_certificate_present") is False
    assert details.get("preview_certificate_domain_conflict") is False


def test_check_deploy_target_readiness_flags_shared_static_ip_conflict(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_with_shared_ip = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    kubernetes.io/ingress.global-static-ip-name: mbsrn-site-lb-ip\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_shared_ip}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "shared_static_ip_not_allowed_for_per_site_ingress"
    details = readiness.managed_gke_config_details or {}
    assert details.get("ingress_static_ip_conflict") is True
    assert details.get("shared_static_ip_not_allowed_for_per_site_ingress") is True
    assert details.get("preview_certificate_ingress_static_ip_name") == "mbsrn-site-lb-ip"


def test_check_deploy_target_readiness_allows_shared_preview_gateway_static_ip_when_configured(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_with_shared_ip = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    kubernetes.io/ingress.global-static-ip-name: site-preview-shared-ip\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_shared_ip}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
        namespace_isolation_defaults={
            "managed_preview_endpoint": {
                "mode": "preview_shared_gateway",
                "shared_preview_static_ip_name": "site-preview-shared-ip",
            }
        },
    )

    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("managed_preview_endpoint_effective_mode") == "preview_shared_gateway"
    assert details.get("uses_shared_preview_gateway") is True
    assert details.get("preview_certificate_ingress_static_ip_name") == "site-preview-shared-ip"
    assert details.get("preview_certificate_ingress_static_ip_matches_expected") is True


def test_check_deploy_target_readiness_allows_expected_per_site_static_ip_name(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_with_expected_static_ip = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    kubernetes.io/ingress.global-static-ip-name: site-web-preview-ip-tnmfire\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_expected_static_ip}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("ingress_static_ip_conflict") is False
    assert details.get("shared_static_ip_not_allowed_for_per_site_ingress") is False
    assert details.get("preview_certificate_ingress_static_ip_name") == "site-web-preview-ip-tnmfire"
    assert details.get("preview_certificate_ingress_static_ip_matches_expected") is True


def test_check_deploy_target_readiness_allows_single_pre_shared_controller_metadata_mismatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    unsigned_workflow = (
        "# mbsrn-managed-template:site_repo_template_v1\n"
        "name: Managed Deploy\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    env:\n"
        "      K8S_NAMESPACE: tnmfire\n"
        "    steps:\n"
        "      - uses: google-github-actions/auth@v2\n"
        '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
    )
    workflow_signature = _compute_managed_workflow_signature(workflow_yaml=unsigned_workflow)
    managed_workflow = _encode_workflow_yaml(f"# mbsrn-workflow-signature: {workflow_signature}\n{unsigned_workflow}")
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_with_pre_shared = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "    ingress.gcp.kubernetes.io/pre-shared-cert: stale-cert-binding\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_pre_shared}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("pre_shared_cert_metadata_mismatch") is True
    assert details.get("stale_pre_shared_cert_binding_detected") is False
    assert details.get("preview_certificate_valid_pre_shared_cert_binding") is False
    assert details.get("preview_certificate_ingress_pre_shared_cert_annotation") == "stale-cert-binding"


def test_check_deploy_target_readiness_allows_expected_pre_shared_certificate_metadata(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespace_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Namespace\n"
            "metadata:\n"
            "  name: tnmfire\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    deployment_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      imagePullSecrets:\n"
            "        - name: ghcr-pull-secret\n"
        )
    )
    ingress_manifest_with_expected_pre_shared = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "    ingress.gcp.kubernetes.io/pre-shared-cert: site-web-preview-cert-tnmfire\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespace_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_expected_pre_shared}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is True
    assert readiness.dispatch_service_reason_code == "available"
    details = readiness.managed_gke_config_details or {}
    assert details.get("stale_pre_shared_cert_binding_detected") is False
    assert details.get("preview_certificate_valid_pre_shared_cert_binding") is True
    assert details.get("preview_certificate_ingress_pre_shared_cert_annotation_values") == [
        "site-web-preview-cert-tnmfire"
    ]


def test_check_deploy_target_readiness_marks_stale_pre_shared_binding_only_with_confirmed_domain_mismatch(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest_with_cross_site_pre_shared = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "    ingress.gcp.kubernetes.io/pre-shared-cert: site-web-preview-cert-sc-mechanical\n"
            "spec:\n"
            "  rules:\n"
            "    - host: sc-mechanical.site.mbsrn.com\n"
        )
    )
    certificate_manifest_expected = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest_with_cross_site_pre_shared}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest_expected}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "tls_certificate_bound_to_wrong_site"
    details = readiness.managed_gke_config_details or {}
    assert details.get("pre_shared_cert_metadata_mismatch") is True
    assert details.get("stale_pre_shared_cert_binding_detected") is True
    assert details.get("pre_shared_cert_known_managed_site_name_mismatch") is True


def test_check_deploy_target_readiness_flags_deployed_content_identity_mismatch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    env:\n"
            "      K8S_NAMESPACE: tnmfire\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    deployment_manifest_wrong_image = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: site-web\n"
            "          image: ghcr.io/mhanson13/scmechanical-site-web:latest\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
        )
    )
    ingress_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            "  namespace: tnmfire\n"
            "  annotations:\n"
            "    networking.gke.io/managed-certificates: site-web-preview-cert-tnmfire\n"
            "spec:\n"
            "  rules:\n"
            "    - host: tnmfire.site.mbsrn.com\n"
        )
    )
    certificate_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            "  name: site-web-preview-cert-tnmfire\n"
            "  namespace: tnmfire\n"
            "spec:\n"
            "  domains:\n"
            "    - tnmfire.site.mbsrn.com\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": ".github/workflows/deploy-tnmfire-www-prod.yml"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest_wrong_image}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200, body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest})
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "deployed_content_identity_mismatch"
    details = readiness.managed_gke_config_details or {}
    assert details.get("site_runtime_image_repository_expected") == "ghcr.io/mhanson13/tnmfire-site-web"
    assert details.get("site_runtime_image_repository_observed") == "ghcr.io/mhanson13/scmechanical-site-web"
    assert details.get("site_runtime_image_tag_observed") == "latest"
    assert details.get("site_runtime_image_repository_expected") != details.get(
        "site_runtime_image_repository_observed"
    )


@pytest.mark.parametrize(
    ("repo_owner", "repo_name", "workflow_id", "legacy_image_reference"),
    [
        (
            "mhanson13",
            "scmechanical",
            "deploy-scmechanical-www-prod.yml",
            "ghcr.io/mhanson13/site-web:latest",
        ),
        (
            "acmeowner",
            "lars-construction",
            "deploy-lars-construction-www-prod.yml",
            "ghcr.io/acmeowner/site-web:latest",
        ),
    ],
)
def test_check_deploy_target_readiness_flags_legacy_generic_runtime_images(
    monkeypatch,
    repo_owner: str,
    repo_name: str,
    workflow_id: str,
    legacy_image_reference: str,
) -> None:
    calls: list[tuple[str, str]] = []
    namespace, _ = derive_site_kubernetes_namespace(repo_name=repo_name, site_id="site-1")
    preview_hostname, _ = derive_site_preview_hostname(repo_name=repo_name, site_id="site-1")
    preview_certificate_name, _ = derive_site_preview_certificate_name(repo_name=repo_name, site_id="site-1")
    managed_workflow = _encode_workflow_yaml(
        (
            "# mbsrn-managed-template:site_repo_template_v1\n"
            "name: Managed Deploy\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            f"    env:\n      K8S_NAMESPACE: {namespace}\n"
            "    steps:\n"
            "      - uses: google-github-actions/auth@v2\n"
            '      - run: kubectl apply -n "$K8S_NAMESPACE" -f k8s/deployment.yaml\n'
        )
    )
    deployment_manifest_legacy_image = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: site-web\n"
            f"  namespace: {namespace}\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: site-web\n"
            f"          image: {legacy_image_reference}\n"
        )
    )
    namespaced_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: site-web\n"
            f"  namespace: {namespace}\n"
        )
    )
    ingress_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: site-web\n"
            f"  namespace: {namespace}\n"
            "  annotations:\n"
            f"    networking.gke.io/managed-certificates: {preview_certificate_name}\n"
            "spec:\n"
            "  rules:\n"
            f"    - host: {preview_hostname}\n"
        )
    )
    certificate_manifest = _encode_workflow_yaml(
        (
            "# mbsrn-managed-manifest:site_repo_template_v1\n"
            "apiVersion: networking.gke.io/v1\n"
            "kind: ManagedCertificate\n"
            "metadata:\n"
            f"  name: {preview_certificate_name}\n"
            f"  namespace: {namespace}\n"
            "spec:\n"
            "  domains:\n"
            f"    - {preview_hostname}\n"
        )
    )
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(status=200, body="{}"),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "wfsha", "encoding": "base64", "content": managed_workflow}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"state": "active", "path": f".github/workflows/{workflow_id}"}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-deployment", "encoding": "base64", "content": deployment_manifest_legacy_image}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200, body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": ingress_manifest})
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps(
                    {"sha": "sha-managedcertificate", "encoding": "base64", "content": certificate_manifest}
                ),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            _FakeHTTPResponse(
                status=200,
                body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest}),
            ),
            *_gke_environment_config_present_responses(),
        ],
        calls,
    )
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    readiness = publisher.check_deploy_target_readiness(
        target=SEOMigrationGitHubDeployTarget(
            repo_owner=repo_owner,
            repo_name=repo_name,
            workflow_id=workflow_id,
            ref="main",
            inputs={"site_id": "site-1"},
        ),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )

    assert readiness.dispatch_service_availability is False
    assert readiness.dispatch_service_reason_code == "deployed_content_identity_mismatch"
    details = readiness.managed_gke_config_details or {}
    assert details.get("site_runtime_image_legacy_generic_detected") is True
    assert details.get("site_runtime_image_reference_observed") == legacy_image_reference


def test_emit_structured_publisher_log_redacts_sensitive_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.integrations.seo_migration_github_publisher")
    _emit_structured_publisher_log(
        payload={
            "event": "seo_migration_managed_image_pull_secret_provisioning",
            "operation_status": "completed",
            "action": "updated",
            "git_token": "ghp_FAKE_SUPER_SECRET_TOKEN_FOR_TEST",
            "gcp_deploy_key": "FAKE_GCP_DEPLOY_KEY_FOR_TEST",
            "authorization": "Bearer FAKE_BEARER_SECRET_FOR_TEST",
            "cookie": "session=FAKE_COOKIE_SECRET_FOR_TEST",
            "database_url": "postgresql://user:pass@localhost:5432/db",
        },
        fallback_message="seo_migration_managed_image_pull_secret_provisioning",
    )

    structured_records = [
        record
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_managed_image_pull_secret_provisioning"
    ]
    assert structured_records
    payload = structured_records[-1].__dict__["json_fields"]
    serialized = structured_records[-1].getMessage()

    assert payload.get("operation_status") == "completed"
    assert payload.get("action") == "updated"
    assert payload.get("git_token") == "<redacted>"
    assert payload.get("gcp_deploy_key") == "<redacted>"
    assert payload.get("authorization") == "<redacted>"
    assert payload.get("cookie") == "<redacted>"
    assert payload.get("database_url") == "<redacted>"
    assert "ghp_FAKE_SUPER_SECRET_TOKEN_FOR_TEST" not in serialized
    assert "FAKE_GCP_DEPLOY_KEY_FOR_TEST" not in serialized
    assert "FAKE_BEARER_SECRET_FOR_TEST" not in serialized
    assert "FAKE_COOKIE_SECRET_FOR_TEST" not in serialized


def test_provision_managed_image_pull_secret_rejects_unexpected_action_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    monkeypatch.setattr(
        github_publisher_module,
        "_upsert_namespace_scoped_ghcr_pull_secret",
        lambda **kwargs: "ghp_FAKE_SUPER_SECRET_TOKEN_FOR_TEST",
    )

    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        publisher.provision_managed_image_pull_secret(
            repo_owner="mhanson13",
            repo_name="tnmfire",
            ref="main",
            kubernetes_namespace="tnmfire",
            managed_gke_config={
                "cluster_name": "cluster-1",
                "cluster_location": "us-central1",
                "project_id": "project-1",
            },
            git_userid="ci-user",
            git_email="ci@example.com",
            git_token="ghp_valid_test_token",
            gcp_deploy_key='{"type":"service_account","private_key":"FAKE_GCP_DEPLOY_KEY_FOR_TEST"}',
            dry_run=False,
        )

    assert exc_info.value.code == "image_pull_secret_provisioning_failed"

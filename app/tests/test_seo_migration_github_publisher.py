from __future__ import annotations

import io
import json
import base64
import urllib.error
import urllib.request

import pytest

from app.core.time import utc_now
from app.integrations.seo_migration_github_publisher import (
    GitHubSEOMigrationPublisher,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublisherError,
    _derive_site_runtime_image_repository,
    _classify_rollout_blocker_hints_from_describe_outputs,
    derive_site_kubernetes_namespace,
    derive_site_preview_hostname,
)


class _FakeHTTPResponse:
    def __init__(self, *, status: int, body: str = "") -> None:
        self.status = status
        self._body = body.encode("utf-8")

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


def _install_urlopen_stub(monkeypatch, responses, calls):
    queue = list(responses)

    def _stub(request, timeout=None):
        del timeout
        calls.append((request.get_method(), request.full_url))
        next_item = queue.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    monkeypatch.setattr(urllib.request, "urlopen", _stub)


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
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
    ]
    managed_paths = (
        ".github/workflows/deploy-tnmfire-www-prod.yml",
        "k8s/namespace.yaml",
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
        "k8s/managedcertificate.yaml",
        "k8s/frontendconfig.yaml",
        "k8s/backendconfig.yaml",
    )
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


def _managed_provisioning_responses_with_paths(
    *,
    managed_paths: tuple[str, ...],
    missing_verify_path: str | None = None,
) -> list[object]:
    responses: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
    ]
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
    _install_urlopen_stub(
        monkeypatch,
        [
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire",
                status_code=404,
                message="Not Found",
            ),
            _FakeHTTPResponse(status=201, body=json.dumps({"name": "tnmfire"})),
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
    assert result.auto_create_created is True
    assert result.outcome == "repo_created"
    assert calls == [
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
        ("POST", "https://api.github.com/orgs/mhanson13/repos"),
        ("GET", "https://api.github.com/repos/mhanson13/tnmfire"),
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
    ]


def test_ensure_repository_auto_create_defaults_to_private_visibility(monkeypatch) -> None:
    publisher = GitHubSEOMigrationPublisher(token="test-token")
    observed_private_value: bool | None = None
    queue = [
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"name": "tnmfire"})),
        _FakeHTTPResponse(status=200, body=json.dumps({"full_name": "mhanson13/tnmfire"})),
    ]

    def _stub(request, timeout=None):
        nonlocal observed_private_value
        del timeout
        if request.get_method() == "POST" and request.full_url == "https://api.github.com/orgs/mhanson13/repos":
            payload = json.loads((request.data or b"{}").decode("utf-8"))
            observed_private_value = bool(payload.get("private"))
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


def test_derive_site_runtime_image_repository_uses_owner_scoped_path() -> None:
    assert (
        _derive_site_runtime_image_repository(repo_owner="mhanson13")
        == "ghcr.io/mhanson13/site-web"
    )


def test_derive_site_runtime_image_repository_rejects_empty_owner_without_mbsrn_fallback() -> None:
    with pytest.raises(SEOMigrationGitHubPublisherError) as exc_info:
        _derive_site_runtime_image_repository(repo_owner="   ")
    assert exc_info.value.code == "runtime_image_repository_invalid"
    assert exc_info.value.stage == "workflow_provisioning"


def test_classify_rollout_blockers_prioritizes_image_pull_not_found_without_crash_or_probe() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            "Warning  Failed     kubelet  Failed to pull image \"ghcr.io/mhanson13/site-web:latest\": not found\n"
            "Warning  Failed     kubelet  Error: ErrImagePull\n"
            "Warning  Failed     kubelet  Back-off pulling image\n"
            "State: Waiting\nReason: ImagePullBackOff\n"
        ),
    )
    assert "image_pull_failure" in hints
    assert "container_image_not_found" in hints
    assert "pod_crash_or_startup_failure" not in hints
    assert "readiness_or_liveness_probe_failure" not in hints


def test_classify_rollout_blockers_prioritizes_private_registry_auth_without_crash_hint() -> None:
    hints = _classify_rollout_blocker_hints_from_describe_outputs(
        deployment_describe_output="",
        pods_describe_output=(
            "Warning  Failed  kubelet  Failed to pull image \"ghcr.io/mhanson13/site-web:latest\": failed to fetch anonymous token: 403 Forbidden\n"
            "Warning  Failed  kubelet  pull access denied\n"
        ),
    )
    assert "image_pull_failure" in hints
    assert "private_registry_auth_failure" in hints
    assert "pod_crash_or_startup_failure" not in hints


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
            "Warning  Failed   kubelet  Failed to pull image \"ghcr.io/mhanson13/site-web:latest\": manifest unknown\n"
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
    assert any(
        method == "GET" and url.endswith("/actions/secrets/public-key")
        for method, url in calls
    )


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
    assert any(
        method == "GET" and url.endswith("/actions/secrets/GCP_DEPLOY_KEY")
        for method, url in calls
    )
    assert any(
        method == "PUT" and url.endswith("/actions/secrets/GCP_DEPLOY_KEY")
        for method, url in calls
    )


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
        "/actions/workflows/deploy-tnmfire-www-prod.yml/runs?event=workflow_dispatch&branch=main&per_page=10"
        in call[1]
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
    assert exc_info.value.code == "workflow_not_dispatchable"
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
    assert exc_info.value.code == "workflow_not_dispatchable"
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
    assert exc_info.value.code == "workflow_not_dispatchable"
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest_wrong}),
            ),
                _FakeHTTPResponse(
                    status=200,
                    body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest_wrong}),
                ),
                _FakeHTTPResponse(
                    status=200,
                    body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest_wrong}),
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
    assert all(
        not (method == "GET" and ("/actions/variables/" in url or "/actions/secrets/" in url))
        for method, url in calls
    )
    assert len(calls) == 11


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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
        not (method == "GET" and "/actions/secrets/" in url)
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
        not (method == "GET" and ("/actions/variables/" in url or "/actions/secrets/" in url))
        for method, url in calls
    )
    readiness_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str)
        and '"event": "seo_migration_dispatch_managed_gke_config_presence"' in record.msg
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
                body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest}),
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
    assert result.workflow_output is None
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
    assert result.commit_sha == "verified-8"
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
    assert len(calls) == 27
    assert calls[0][1].endswith("/repos/mhanson13/tnmfire")
    assert calls[1][1].endswith("/repos/mhanson13/tnmfire/branches/main")
    assert calls[2][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main")
    assert calls[3][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
    assert any(call[1].endswith("/contents/k8s/namespace.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/deployment.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/service.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/ingress.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/managedcertificate.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/frontendconfig.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/backendconfig.yaml?ref=main") for call in calls)


def test_ensure_deploy_workflow_bootstraps_uninitialized_repo_branch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
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
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "blob-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "tree-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "commit-sha"})),
        _FakeHTTPResponse(status=201, body="{}"),
        _FakeHTTPResponse(status=200, body="{}"),
    ]
    queue.extend(_managed_provisioning_responses()[2:])
    _install_urlopen_stub(monkeypatch, queue, calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )

    assert result.provisioned is True
    assert any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)
    assert any(method == "POST" and url.endswith("/git/trees") for method, url in calls)
    assert any(method == "POST" and url.endswith("/git/commits") for method, url in calls)
    assert any(method == "POST" and url.endswith("/git/refs") for method, url in calls)


def test_ensure_deploy_workflow_bootstraps_when_default_ref_lookup_returns_404(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
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
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "blob-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "tree-sha"})),
        _FakeHTTPResponse(status=201, body=json.dumps({"sha": "commit-sha"})),
        _FakeHTTPResponse(status=201, body="{}"),
        _FakeHTTPResponse(status=200, body="{}"),
    ]
    queue.extend(_managed_provisioning_responses()[2:])
    _install_urlopen_stub(monkeypatch, queue, calls)

    publisher = GitHubSEOMigrationPublisher(token="test-token")
    result = publisher.ensure_deploy_workflow(
        repo_owner="mhanson13",
        repo_name="tnmfire",
        branch="main",
        workflow_id="deploy-tnmfire-www-prod.yml",
        dry_run=False,
    )

    assert result.provisioned is True
    assert any(method == "POST" and url.endswith("/git/blobs") for method, url in calls)
    assert any(method == "POST" and url.endswith("/git/trees") for method, url in calls)
    assert any(method == "POST" and url.endswith("/git/commits") for method, url in calls)
    assert any(method == "POST" and url.endswith("/git/refs") for method, url in calls)


def test_ensure_deploy_workflow_classifies_workflow_write_forbidden(monkeypatch, caplog) -> None:
    calls: list[tuple[str, str]] = []
    caplog.set_level("INFO", logger="app.integrations.seo_migration_github_publisher")
    _install_urlopen_stub(
        monkeypatch,
        [
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body="{}"),
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
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body="{}"),
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
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body="{}"),
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
            _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
            _FakeHTTPResponse(status=200, body="{}"),
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
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/k8s/service.yaml")
            and request.data
        ):
            captured_service_put_payload.update(json.loads(request.data.decode("utf-8")))
        if (
            request.get_method() == "PUT"
            and request.full_url.endswith("/contents/k8s/ingress.yaml")
            and request.data
        ):
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
    assert "permissions:" in workflow_yaml
    assert "packages: read" in workflow_yaml
    assert "K8S_NAMESPACE: tnmfire" in workflow_yaml
    assert "MBSRN_PREVIEW_HOSTNAME: tnmfire.site.mbsrn.com" in workflow_yaml
    assert "SITE_WEB_IMAGE_REPOSITORY: ghcr.io/mhanson13/site-web" in workflow_yaml
    assert "ghcr.io/mbsrn/site-web" not in workflow_yaml
    assert (
        "SITE_WEB_IMAGE_TAG: ${{ vars.MBSRN_SITE_WEB_IMAGE_TAG || vars.SITE_WEB_IMAGE_TAG || secrets.MBSRN_SITE_WEB_IMAGE_TAG || secrets.SITE_WEB_IMAGE_TAG || '' }}"
        in workflow_yaml
    )
    assert "Authenticate to GCP" in workflow_yaml
    assert "Get GKE credentials" in workflow_yaml
    assert "Ensure namespace exists" in workflow_yaml
    assert "Ensure GHCR image pull secret" in workflow_yaml
    assert "Reset stale site-web deployment" in workflow_yaml
    assert "Resetting deployment to eliminate stale image references." in workflow_yaml
    assert "kubectl delete deployment site-web --namespace \"$K8S_NAMESPACE\" --ignore-not-found" in workflow_yaml
    assert "GHCR_PULL_USERNAME: ${{ github.actor }}" in workflow_yaml
    assert "GHCR_PULL_TOKEN: ${{ github.token }}" in workflow_yaml
    assert "kubectl create secret docker-registry mbsrn-ghcr-pull" in workflow_yaml
    assert "Apply managed manifests" in workflow_yaml
    assert "kubectl apply -f k8s/deployment.yaml" in workflow_yaml
    assert "Resolve managed site runtime image" in workflow_yaml
    assert "selected_mode=\"fallback_latest\"" in workflow_yaml
    assert "selected_image=\"${SITE_WEB_IMAGE_REPOSITORY}:latest\"" in workflow_yaml
    assert "selected_mode=\"immutable_sha\"" in workflow_yaml
    assert "docker manifest inspect \"$candidate_image\"" in workflow_yaml
    assert "kubectl set image deployment/site-web site-web=\"${selected_image}\"" in workflow_yaml
    assert "Managed site runtime image selected: ${selected_image} (mode=${selected_mode})" in workflow_yaml
    assert "Configured SITE_WEB_IMAGE_TAG '$normalized_tag' is unavailable; falling back to latest." in workflow_yaml
    assert "Verify rollout" in workflow_yaml
    assert "Verify service and ingress" in workflow_yaml
    assert "project_id: ${{ env.GKE_PROJECT_ID }}" in workflow_yaml
    assert "Validate GCP credentials" in workflow_yaml
    assert "Missing GCP_DEPLOY_KEY secret" in workflow_yaml
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
    assert "url: ${{ steps.resolve_live_url.outputs.resolved_live_url }}" in workflow_yaml
    assert "kubectl apply -f k8s/" in workflow_yaml
    assert "kubectl rollout status deployment/site-web" in workflow_yaml
    assert "site-web rollout timed out in namespace $K8S_NAMESPACE; collecting bounded diagnostics." in workflow_yaml
    assert "kubectl get rs --namespace \"$K8S_NAMESPACE\" -o wide || true" in workflow_yaml
    assert (
        "kubectl describe deployment site-web --namespace \"$K8S_NAMESPACE\" > \"$deployment_describe_output\" 2>&1 || true"
        in workflow_yaml
    )
    assert "kubectl describe pods --namespace \"$K8S_NAMESPACE\" -l app.kubernetes.io/name=site-web" in workflow_yaml
    assert "image_pull_detected=false" in workflow_yaml
    assert "Likely rollout blocker: image pull failure." in workflow_yaml
    assert "Likely rollout blocker: private registry authentication failure." in workflow_yaml
    assert "Likely rollout blocker: container image not found in registry." in workflow_yaml
    assert "container_started_evidence=false" in workflow_yaml
    assert "crash_direct_evidence=false" in workflow_yaml
    assert "probe_direct_evidence=false" in workflow_yaml
    assert "Suppress crash/probe hints when current describe evidence shows image-pull blockers." in workflow_yaml
    assert (
        "if [ \"$image_pull_detected\" = false ] && [ \"$container_started_evidence\" = true ] && [ \"$crash_direct_evidence\" = true ]; then"
        in workflow_yaml
    )
    assert (
        "if [ \"$image_pull_detected\" = false ] && [ \"$container_started_evidence\" = true ] && [ \"$probe_direct_evidence\" = true ]; then"
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
    assert "Waiting up to ${wait_seconds}s for ingress external address assignment in namespace $K8S_NAMESPACE." in workflow_yaml
    assert "kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\"" in workflow_yaml
    assert "ingress_spec_host=\"$(kubectl get ingress site-web --namespace \"$K8S_NAMESPACE\" -o jsonpath='{.spec.rules[0].host}' 2>/dev/null || true)\"" in workflow_yaml
    assert "preview_host=\"$MBSRN_PREVIEW_HOSTNAME\"" in workflow_yaml
    assert "if [ -z \"$preview_host\" ] && [ -n \"$ingress_spec_host\" ]; then" in workflow_yaml
    assert "if [ -n \"$preview_host\" ]; then" in workflow_yaml
    assert "Ingress created but external address is not assigned yet for namespace $K8S_NAMESPACE." in workflow_yaml
    assert "Likely rollout blocker: ingress/load balancer provisioning still in progress." in workflow_yaml
    assert "This may take several minutes on GKE." in workflow_yaml
    assert "deploy_runtime_reason_code=ingress_address_pending" in workflow_yaml
    assert "kubectl describe ingress site-web --namespace \"$K8S_NAMESPACE\" || true" in workflow_yaml
    assert "kubectl get service site-web --namespace \"$K8S_NAMESPACE\" -o wide || true" in workflow_yaml
    assert "kubectl get endpoints site-web --namespace \"$K8S_NAMESPACE\" -o wide || true" in workflow_yaml
    assert "kubectl get managedcertificate --namespace \"$K8S_NAMESPACE\" || true" in workflow_yaml
    assert "kubectl get frontendconfig --namespace \"$K8S_NAMESPACE\" || true" in workflow_yaml
    assert "exit 1" in workflow_yaml
    assert "echo \"resolved_live_url=$live_url\"" in workflow_yaml
    assert "echo \"live_url=$live_url\"" in workflow_yaml
    assert "echo \"deployed_url=$live_url\"" in workflow_yaml
    assert (
        "echo \"Site runtime image: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_reference }}\""
        in workflow_yaml
    )
    assert (
        "echo \"Site runtime image selection mode: ${{ steps.resolve_site_runtime_image.outputs.site_runtime_image_selection_mode }}\""
        in workflow_yaml
    )
    assert "resources:" in deployment_yaml
    assert "image: ghcr.io/mhanson13/site-web:latest" in deployment_yaml
    assert "ghcr.io/mbsrn/site-web" not in deployment_yaml
    assert "imagePullSecrets:" in deployment_yaml
    assert "name: mbsrn-ghcr-pull" in deployment_yaml
    assert "containerPort: 8080" in deployment_yaml
    assert "env:" in deployment_yaml
    assert "name: HOSTNAME" in deployment_yaml
    assert "value: \"0.0.0.0\"" in deployment_yaml
    assert "name: PORT" in deployment_yaml
    assert "value: \"8080\"" in deployment_yaml
    assert "readinessProbe:" in deployment_yaml
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
    assert "cloud.google.com/backend-config: '{\"default\": \"site-web-backend-config\"}'" in service_yaml
    assert "kubernetes.io/ingress.class: gce" in ingress_yaml
    assert "networking.gke.io/managed-certificates: site-web-preview-cert" in ingress_yaml
    assert "networking.gke.io/v1beta1.FrontendConfig: site-web-frontend-config" in ingress_yaml
    assert "ingressClassName: gce" in ingress_yaml
    assert "host: tnmfire.site.mbsrn.com" in ingress_yaml
    assert "kind: ManagedCertificate" in managed_certificate_yaml
    assert "name: site-web-preview-cert" in managed_certificate_yaml
    assert "domains:" in managed_certificate_yaml
    assert "- tnmfire.site.mbsrn.com" in managed_certificate_yaml
    assert "kind: FrontendConfig" in frontend_config_yaml
    assert "name: site-web-frontend-config" in frontend_config_yaml
    assert "redirectToHttps:" in frontend_config_yaml
    assert "enabled: true" in frontend_config_yaml
    assert "kind: BackendConfig" in backend_config_yaml
    assert "name: site-web-backend-config" in backend_config_yaml
    assert "requestPath: /" in backend_config_yaml
    assert "port: 8080" in backend_config_yaml
    assert len(calls) == 27


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
    assert "GKE_CLUSTER_NAME: ${{ vars.KUBERNETES_CLUSTER_NAME || secrets.KUBERNETES_CLUSTER_NAME }}" not in workflow_yaml
    assert "GKE_CLUSTER_LOCATION: ${{ vars.KUBERNETES_CLUSTER_LOCATION || secrets.KUBERNETES_CLUSTER_LOCATION }}" not in workflow_yaml
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
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
        _managed_workflow_verify_response(sha="workflow-verified-upsert"),
    ]
    for index in range(1, 8):
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
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
        _managed_workflow_verify_response(sha="workflow-verified-upsert"),
    ]
    for index in range(1, 8):
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
    assert "kubectl apply -f k8s/" in rendered_workflow
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
    queue[2] = _FakeHTTPResponse(
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
        method == "GET"
        and url.endswith("/actions/workflows/deploy-tnmfire-www-prod.yml")
        for method, url in calls
    )
    upsert_decision_logs = [
        record
        for record in caplog.records
        if isinstance(record.msg, str) and '"event": "seo_migration_publish_workflow_file_upsert_decision"' in record.msg
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
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "custom-workflow-sha", "encoding": "base64", "content": custom_workflow_content}),
        ),
    ]
    for index in range(1, 8):
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
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
        _FakeHTTPResponse(
            status=200,
            body=json.dumps({"sha": "old-workflow-sha", "encoding": "base64", "content": placeholder_workflow_content}),
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "workflow-commit"}})),
        _managed_workflow_verify_response(sha="workflow-verified-upsert"),
    ]
    for index in range(1, 8):
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
            "      - run: kubectl apply -n \"$K8S_NAMESPACE\" -f k8s/deployment.yaml\n"
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
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-namespace", "encoding": "base64", "content": namespaced_manifest})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-deployment", "encoding": "base64", "content": namespaced_manifest})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-service", "encoding": "base64", "content": namespaced_manifest})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-ingress", "encoding": "base64", "content": namespaced_manifest})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-managedcertificate", "encoding": "base64", "content": namespaced_manifest})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-frontendconfig", "encoding": "base64", "content": namespaced_manifest})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "sha-backendconfig", "encoding": "base64", "content": namespaced_manifest})),
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



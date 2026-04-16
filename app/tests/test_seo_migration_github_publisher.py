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
    derive_site_kubernetes_namespace,
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
            marker = (
                "mbsrn-managed-template:site_repo_template_v1"
                if managed_path.endswith(".yml")
                else "mbsrn-managed-manifest:site_repo_template_v1"
            )
            responses.append(_managed_file_verify_response(sha=f"verified-{index}", marker=marker))
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
            marker = (
                "mbsrn-managed-template:site_repo_template_v1"
                if managed_path.endswith(".yml")
                else "mbsrn-managed-manifest:site_repo_template_v1"
            )
            responses.append(_managed_file_verify_response(sha=f"verified-{index}", marker=marker))
    return responses


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
    assert len(calls) == 8


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
    assert len(calls) == 8


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
    assert result.commit_sha == "verified-5"
    assert result.kubernetes_namespace == "tnmfire"
    assert result.namespace_source == "repo_name"
    assert result.namespace_model_status == "aligned"
    assert result.managed_manifest_paths == (
        "k8s/namespace.yaml",
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
    )
    assert result.managed_resource_quota_expected is False
    assert result.managed_resource_quota_present is None
    assert result.managed_limit_range_expected is False
    assert result.managed_limit_range_present is None
    assert result.managed_network_policy_expected is False
    assert result.managed_network_policy_present is None
    assert result.managed_namespace_policies_aligned is True
    assert len(calls) == 17
    assert calls[0][1].endswith("/repos/mhanson13/tnmfire")
    assert calls[1][1].endswith("/repos/mhanson13/tnmfire/branches/main")
    assert calls[2][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main")
    assert calls[3][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")
    assert any(call[1].endswith("/contents/k8s/namespace.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/deployment.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/service.yaml?ref=main") for call in calls)
    assert any(call[1].endswith("/contents/k8s/ingress.yaml?ref=main") for call in calls)


def test_ensure_deploy_workflow_provisions_dispatchable_trigger(monkeypatch) -> None:
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
    )
    encoded_content = str(captured_put_payload.get("content") or "")
    assert encoded_content
    workflow_yaml = base64.b64decode(encoded_content).decode("utf-8")
    assert "workflow_dispatch" in workflow_yaml
    assert "K8S_NAMESPACE: tnmfire" in workflow_yaml
    assert len(calls) == 17


def test_ensure_deploy_workflow_includes_optional_namespace_policy_manifests_when_enabled(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    managed_paths = (
        ".github/workflows/deploy-tnmfire-www-prod.yml",
        "k8s/namespace.yaml",
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
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
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/k8s/resourcequota.yaml?ref=main",
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

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


def test_check_deploy_target_readiness_preserves_placeholder_conformance_without_blocking_dispatch(monkeypatch) -> None:
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
    readiness = publisher.check_deploy_target_readiness(
        target=_dispatch_target(),
        allow_ref_repair=False,
        allow_workflow_repair=False,
        dry_run=False,
    )
    assert readiness.workflow_dispatch_ready is True
    assert readiness.workflow_dispatch_supported is True
    assert readiness.workflow_conformance_checked is True
    assert readiness.workflow_conformance_status == "workflow_placeholder_detected"
    assert readiness.workflow_conformance_reasons == ("placeholder_workflow_content_detected",)
    assert "placeholder_markers" in str(readiness.workflow_conformance_evidence_summary or "")
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
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "commit-created"}})),
            _FakeHTTPResponse(status=200, body=json.dumps({"sha": "verified-sha"})),
        ],
        calls,
    )
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
    assert result.commit_sha == "verified-sha"
    assert len(calls) == 5
    assert calls[0][1].endswith("/repos/mhanson13/tnmfire")
    assert calls[1][1].endswith("/repos/mhanson13/tnmfire/branches/main")
    assert calls[2][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main")
    assert calls[3][1].endswith("/contents/.github/workflows/deploy-tnmfire-www-prod.yml")


def test_ensure_deploy_workflow_provisions_dispatchable_trigger(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    captured_put_payload: dict[str, object] = {}
    queue: list[object] = [
        _FakeHTTPResponse(status=200, body=json.dumps({"default_branch": "main"})),
        _FakeHTTPResponse(status=200, body="{}"),
        _http_error(
            "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
            status_code=404,
            message="Not Found",
        ),
        _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "commit-created"}})),
        _FakeHTTPResponse(status=200, body=json.dumps({"sha": "verified-sha"})),
    ]

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
    assert len(calls) == 5


def test_ensure_deploy_workflow_fails_when_post_write_verification_missing(monkeypatch) -> None:
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
            _FakeHTTPResponse(status=201, body=json.dumps({"commit": {"sha": "commit-created"}})),
            _http_error(
                "https://api.github.com/repos/mhanson13/tnmfire/contents/.github/workflows/deploy-tnmfire-www-prod.yml?ref=main",
                status_code=404,
                message="Not Found",
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
    assert exc_info.value.code == "workflow_provisioning_failed"
    assert exc_info.value.stage == "workflow_provisioning"
    assert len(calls) == 5

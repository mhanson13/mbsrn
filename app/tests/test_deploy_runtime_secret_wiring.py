from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_api_deployment_wires_control_plane_git_credentials_from_secret() -> None:
    deployment_yaml = (_repo_root() / "k8s" / "api-deployment.yaml").read_text(encoding="utf-8")

    assert "- name: GIT_USERID" in deployment_yaml
    assert "key: GIT_USERID" in deployment_yaml
    assert "- name: GIT_EMAIL" in deployment_yaml
    assert "key: GIT_EMAIL" in deployment_yaml
    assert "- name: GIT_TOKEN" in deployment_yaml
    assert "key: GIT_TOKEN" in deployment_yaml


def test_deploy_prod_projects_git_credentials_into_control_plane_runtime_secret() -> None:
    workflow_yaml = (_repo_root() / ".github" / "workflows" / "deploy-prod.yml").read_text(encoding="utf-8")

    assert "GIT_USERID: ${{ secrets.GIT_USERID }}" in workflow_yaml
    assert "GIT_EMAIL: ${{ secrets.GIT_EMAIL }}" in workflow_yaml
    assert "GIT_TOKEN: ${{ secrets.GIT_TOKEN }}" in workflow_yaml
    assert "--from-literal=GIT_USERID=\"${GIT_USERID}\"" in workflow_yaml
    assert "--from-literal=GIT_EMAIL=\"${GIT_EMAIL}\"" in workflow_yaml
    assert "--from-literal=GIT_TOKEN=\"${GIT_TOKEN}\"" in workflow_yaml

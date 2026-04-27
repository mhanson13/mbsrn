from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_api_deployment_wires_control_plane_docker_credentials_from_secret() -> None:
    deployment_yaml = (_repo_root() / "k8s" / "api-deployment.yaml").read_text(encoding="utf-8")

    assert "- name: DOCKER_USERID" in deployment_yaml
    assert "key: DOCKER_USERID" in deployment_yaml
    assert "- name: DOCKER_EMAIL" in deployment_yaml
    assert "key: DOCKER_EMAIL" in deployment_yaml
    assert "- name: DOCKER_PAT" in deployment_yaml
    assert "key: DOCKER_PAT" in deployment_yaml


def test_deploy_prod_projects_docker_credentials_into_control_plane_runtime_secret() -> None:
    workflow_yaml = (_repo_root() / ".github" / "workflows" / "deploy-prod.yml").read_text(encoding="utf-8")

    assert "DOCKER_USERID: ${{ secrets.DOCKER_USERID }}" in workflow_yaml
    assert "DOCKER_EMAIL: ${{ secrets.DOCKER_EMAIL }}" in workflow_yaml
    assert "DOCKER_PAT: ${{ secrets.DOCKER_PAT }}" in workflow_yaml
    assert "--from-literal=DOCKER_USERID=\"${DOCKER_USERID}\"" in workflow_yaml
    assert "--from-literal=DOCKER_EMAIL=\"${DOCKER_EMAIL}\"" in workflow_yaml
    assert "--from-literal=DOCKER_PAT=\"${DOCKER_PAT}\"" in workflow_yaml

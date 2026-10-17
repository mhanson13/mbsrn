from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _deployment(path: str) -> dict[str, object]:
    return yaml.safe_load((REPOSITORY_ROOT / path).read_text(encoding="utf-8"))


def test_low_traffic_production_deployments_use_one_replica() -> None:
    for path in (
        "k8s/api-deployment.yaml",
        "k8s/ui-deployment.yaml",
        "k8s/www-deployment.yaml",
    ):
        deployment = _deployment(path)
        assert deployment["spec"]["replicas"] == 1


def test_capture_worker_uses_small_idle_requests_with_burst_headroom() -> None:
    deployment = _deployment("k8s/source-capture-worker-deployment.yaml")
    resources = deployment["spec"]["template"]["spec"]["containers"][0]["resources"]

    assert resources["requests"] == {
        "cpu": "100m",
        "memory": "256Mi",
        "ephemeral-storage": "512Mi",
    }
    assert resources["limits"] == {
        "cpu": "1",
        "memory": "1Gi",
        "ephemeral-storage": "1Gi",
    }


def test_workflows_have_bounded_low_traffic_resource_fallbacks() -> None:
    app_workflow = (REPOSITORY_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")
    www_workflow = (REPOSITORY_ROOT / ".github/workflows/deploy-www-prod.yml").read_text(encoding="utf-8")

    for expected in (
        "UI_MEMORY_REQUEST: ${{ vars.UI_MEMORY_REQUEST || '256Mi' }}",
        "UI_EPHEMERAL_STORAGE_REQUEST: ${{ vars.UI_EPHEMERAL_STORAGE_REQUEST || '256Mi' }}",
        "API_MEMORY_REQUEST: ${{ vars.API_MEMORY_REQUEST || '512Mi' }}",
        "API_EPHEMERAL_STORAGE_REQUEST: ${{ vars.API_EPHEMERAL_STORAGE_REQUEST || '1Gi' }}",
    ):
        assert expected in app_workflow

    for expected in (
        "WWW_MEMORY_REQUEST: ${{ vars.WWW_MEMORY_REQUEST || '384Mi' }}",
        "WWW_EPHEMERAL_STORAGE_REQUEST: ${{ vars.WWW_EPHEMERAL_STORAGE_REQUEST || '256Mi' }}",
    ):
        assert expected in www_workflow


def test_documentation_and_test_changes_do_not_trigger_production_builds() -> None:
    app_workflow = (REPOSITORY_ROOT / ".github/workflows/deploy-prod.yml").read_text(encoding="utf-8")

    for ignored_path in (
        '      - "docs/**"',
        '      - "**/*.md"',
        '      - "app/tests/**"',
        '      - "frontend/operator-ui/**/*.test.tsx"',
    ):
        assert ignored_path in app_workflow

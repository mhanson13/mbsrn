from __future__ import annotations

from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROD_RETENTION_CRONJOB = _REPO_ROOT / "k8s" / "api-seo-competitor-profile-retention-cronjob.yaml"
_BASE_RETENTION_CRONJOB = _REPO_ROOT / "infra" / "k8s" / "base" / "api-seo-competitor-profile-retention-cronjob.yaml"
_PROCFILE = _REPO_ROOT / "Procfile"
_EXPECTED_COMMAND = ["/cnb/process/seo-competitor-profile-retention"]
_EXPECTED_PROCFILE_LINE = (
    "seo-competitor-profile-retention: " "python -m app.cli.seo_competitor_profile_generation_retention_cleanup"
)
_UNSUPPORTED_INTERPRETERS = {"python", "python3"}


def _retention_container_command(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    containers = (
        doc.get("spec", {})
        .get("jobTemplate", {})
        .get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    retention_container = next(
        (container for container in containers if container.get("name") == "retention-cleanup"),
        None,
    )
    assert retention_container is not None, f"retention-cleanup container not found in {path}"

    command = retention_container.get("command")
    assert isinstance(command, list) and command, f"retention-cleanup command must be a non-empty list in {path}"
    return [str(part) for part in command]


def test_retention_cronjob_uses_buildpack_process_command() -> None:
    for path in (_PROD_RETENTION_CRONJOB, _BASE_RETENTION_CRONJOB):
        assert _retention_container_command(path) == _EXPECTED_COMMAND


def test_retention_cronjob_command_does_not_use_bare_python_interpreters() -> None:
    for path in (_PROD_RETENTION_CRONJOB, _BASE_RETENTION_CRONJOB):
        command = _retention_container_command(path)
        assert command[0] not in _UNSUPPORTED_INTERPRETERS


def test_procfile_defines_retention_process_for_buildpack_runtime() -> None:
    procfile_lines = _PROCFILE.read_text(encoding="utf-8").splitlines()
    assert _EXPECTED_PROCFILE_LINE in procfile_lines

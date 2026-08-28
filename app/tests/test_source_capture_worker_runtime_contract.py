from __future__ import annotations

from pathlib import Path
import re

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_capture_worker_is_sandboxed_and_uses_bounded_runtime_configuration() -> None:
    deployment = yaml.safe_load(
        (REPOSITORY_ROOT / "k8s" / "source-capture-worker-deployment.yaml").read_text(encoding="utf-8")
    )
    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["runtimeClassName"] == "gvisor"
    assert pod_spec["serviceAccountName"] == "mbsrn-api"
    assert pod_spec["securityContext"]["runAsNonRoot"] is True
    assert pod_spec["securityContext"]["runAsUser"] == 1000
    assert pod_spec["securityContext"]["runAsGroup"] == 1000
    assert pod_spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

    container = pod_spec["containers"][0]
    security_context = container["securityContext"]
    assert security_context["allowPrivilegeEscalation"] is False
    assert security_context["runAsNonRoot"] is True
    assert security_context["capabilities"]["drop"] == ["ALL"]
    assert "add" not in security_context["capabilities"]
    assert container["resources"]["limits"]["cpu"]
    assert container["resources"]["limits"]["memory"]


def test_capture_worker_playwright_package_matches_browser_image() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile.capture-worker").read_text(encoding="utf-8")
    requirements = (REPOSITORY_ROOT / "requirements-capture.txt").read_text(encoding="utf-8")
    image_match = re.search(r"playwright/python:v(?P<version>[0-9.]+)-noble", dockerfile)
    package_match = re.search(r"playwright==(?P<version>[0-9.]+)", requirements)
    assert image_match is not None
    assert package_match is not None
    assert image_match.group("version") == package_match.group("version")
    assert "USER pwuser" in dockerfile

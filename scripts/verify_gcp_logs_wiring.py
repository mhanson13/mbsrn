#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_DEPLOYMENT_PATH = REPO_ROOT / "k8s" / "api-deployment.yaml"
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"


def _print_ok(message: str) -> None:
    print(f"[OK] {message}")


def _print_fail(message: str) -> None:
    print(f"[FAIL] {message}")


def _print_warn(message: str) -> None:
    print(f"[WARN] {message}")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has_pattern(content: str, pattern: str) -> bool:
    return re.search(pattern, content, re.MULTILINE) is not None


def _run(command: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _verify_repo_wiring() -> bool:
    passed = True

    if not API_DEPLOYMENT_PATH.exists():
        _print_fail(f"Missing API deployment manifest: {API_DEPLOYMENT_PATH}")
        return False

    deployment_yaml = _read_text(API_DEPLOYMENT_PATH)
    workflow_yaml = _read_text(DEPLOY_WORKFLOW_PATH) if DEPLOY_WORKFLOW_PATH.exists() else ""

    if _has_pattern(deployment_yaml, r"^\s*serviceAccountName:\s*mbsrn-api\s*$"):
        _print_ok("k8s/api-deployment.yaml sets serviceAccountName: mbsrn-api")
    else:
        _print_fail("k8s/api-deployment.yaml must set serviceAccountName: mbsrn-api")
        passed = False

    if _has_pattern(deployment_yaml, r"^\s*-\s*name:\s*GCP_PROJECT_ID\s*$"):
        _print_ok("k8s/api-deployment.yaml includes GCP_PROJECT_ID runtime env wiring")
    else:
        _print_fail("k8s/api-deployment.yaml is missing GCP_PROJECT_ID runtime env wiring")
        passed = False

    if not workflow_yaml:
        _print_warn(f"Deploy workflow not found at {DEPLOY_WORKFLOW_PATH}; skipped workflow checks")
        return passed

    if _has_pattern(workflow_yaml, r"--from-literal=GCP_PROJECT_ID=\"\$\{GCP_PROJECT_ID\}\""):
        _print_ok("deploy-prod workflow writes GCP_PROJECT_ID into mbsrn-api-auth secret")
    else:
        _print_fail("deploy-prod workflow is missing mbsrn-api-auth GCP_PROJECT_ID secret wiring")
        passed = False

    return passed


def _verify_cluster_wiring(namespace: str, deployment: str, ksa: str) -> bool:
    passed = True

    code, sa_name, err = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "deploy",
            deployment,
            "-o",
            "jsonpath={.spec.template.spec.serviceAccountName}",
        ]
    )
    if code != 0:
        _print_fail(f"Failed to read deployment serviceAccountName via kubectl: {err or 'unknown kubectl error'}")
        return False
    if sa_name == ksa:
        _print_ok(f"Cluster deployment {namespace}/{deployment} uses expected KSA: {ksa}")
    else:
        _print_fail(f"Cluster deployment {namespace}/{deployment} uses KSA '{sa_name}' (expected '{ksa}')")
        passed = False

    code, gsa_annotation, err = _run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "sa",
            ksa,
            "-o",
            "jsonpath={.metadata.annotations.iam\\.gke\\.io/gcp-service-account}",
        ]
    )
    if code != 0:
        _print_fail(f"Failed to read KSA annotation via kubectl: {err or 'unknown kubectl error'}")
        return False
    if gsa_annotation:
        _print_ok(f"KSA annotation iam.gke.io/gcp-service-account is set: {gsa_annotation}")
    else:
        _print_fail(
            "KSA is missing iam.gke.io/gcp-service-account annotation (Workload Identity mapping is incomplete)"
        )
        passed = False

    code, deployment_json, err = _run(["kubectl", "-n", namespace, "get", "deploy", deployment, "-o", "json"])
    if code != 0:
        _print_fail(f"Failed to inspect deployment env via kubectl: {err or 'unknown kubectl error'}")
        return False
    try:
        payload = json.loads(deployment_json)
    except json.JSONDecodeError:
        _print_fail("Unable to parse deployment JSON returned by kubectl")
        return False

    containers = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    api_container = next((c for c in containers if c.get("name") == "mbsrn-api"), containers[0] if containers else {})
    env_names = {entry.get("name") for entry in api_container.get("env", []) if isinstance(entry, dict)}

    if "GCP_PROJECT_ID" in env_names:
        _print_ok("Cluster deployment exports runtime env GCP_PROJECT_ID")
    else:
        _print_fail("Cluster deployment is missing runtime env GCP_PROJECT_ID")
        passed = False

    return passed


def _print_manual_commands(namespace: str, deployment: str, ksa: str, project: str, gsa_email: str) -> None:
    project_hint = project or "<PROJECT_ID>"
    gsa_hint = gsa_email or f"<GSA_NAME>@{project_hint}.iam.gserviceaccount.com"
    print("\nManual verification / setup commands:")
    print(
        f"  kubectl -n {namespace} get deploy {deployment} -o jsonpath='{{.spec.template.spec.serviceAccountName}}{{\"\\n\"}}'"
    )
    print(
        f"  kubectl -n {namespace} get sa {ksa} -o jsonpath='{{.metadata.annotations.iam\\.gke\\.io/gcp-service-account}}{{\"\\n\"}}'"
    )
    print(f"  kubectl -n {namespace} annotate sa {ksa} iam.gke.io/gcp-service-account={gsa_hint} --overwrite")
    print(
        f"  gcloud iam service-accounts add-iam-policy-binding {gsa_hint} "
        f"--role=roles/iam.workloadIdentityUser "
        f"--member='serviceAccount:{project_hint}.svc.id.goog[{namespace}/{ksa}]' "
        f"--project {project_hint}"
    )
    print(
        f"  gcloud projects add-iam-policy-binding {project_hint} "
        f"--member='serviceAccount:{gsa_hint}' --role='roles/logging.viewer'"
    )
    print(f"  kubectl -n {namespace} rollout restart deployment/{deployment}")
    print(f"  kubectl -n {namespace} exec deploy/{deployment} -- sh -c " "'env | egrep \"GCP_PROJECT_ID\"'")
    print(
        f"  kubectl -n {namespace} exec deploy/{deployment} -- sh -c "
        '\'python - <<"PY"\n'
        "import google.auth\n"
        "creds, proj = google.auth.default()\n"
        'print("ADC_OK", bool(creds), "PROJECT", proj)\n'
        "PY'"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deployment wiring prerequisites for in-app GCP Logs Query.")
    parser.add_argument("--cluster", action="store_true", help="Also verify live cluster wiring via kubectl.")
    parser.add_argument("--namespace", default="mbsrn", help="Kubernetes namespace for cluster checks.")
    parser.add_argument("--deployment", default="mbsrn-api", help="API deployment name for cluster checks.")
    parser.add_argument("--ksa", default="mbsrn-api", help="Expected Kubernetes service account name.")
    parser.add_argument(
        "--project-id",
        default="",
        help="Project id hint for printed manual gcloud commands.",
    )
    parser.add_argument(
        "--gsa-email",
        default="",
        help="GSA email hint for printed manual gcloud/kubectl commands.",
    )
    args = parser.parse_args()

    repo_ok = _verify_repo_wiring()
    cluster_ok = True
    if args.cluster:
        print("\nRunning live-cluster checks...")
        cluster_ok = _verify_cluster_wiring(
            namespace=args.namespace,
            deployment=args.deployment,
            ksa=args.ksa,
        )
    else:
        print("\nLive-cluster checks skipped (use --cluster to validate deployed wiring).")

    _print_manual_commands(
        namespace=args.namespace,
        deployment=args.deployment,
        ksa=args.ksa,
        project=args.project_id,
        gsa_email=args.gsa_email,
    )

    if repo_ok and cluster_ok:
        print("\nResult: PASS")
        return 0
    print("\nResult: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())

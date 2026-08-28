from __future__ import annotations

import json
import re


REUSABLE_PREVIEW_CALLER_MARKER = "mbsrn-reusable-preview-caller:v1"

_WORKFLOW_REF_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/"
    r"[A-Za-z0-9_.-]+\.ya?ml@[A-Za-z0-9_./-]+$"
)
_WIF_PROVIDER_PATTERN = re.compile(
    r"^projects/[0-9]+/locations/global/workloadIdentityPools/"
    r"[a-z0-9-]+/providers/[a-z0-9-]+$"
)
_SERVICE_ACCOUNT_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$"
)
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_HOSTNAME_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_reusable_preview_deployment_settings(
    *,
    workflow_ref: str | None,
    workload_identity_provider: str | None,
    service_account: str | None,
) -> tuple[str, str, str] | None:
    values = tuple(str(value or "").strip() for value in (workflow_ref, workload_identity_provider, service_account))
    if not any(values):
        return None
    if not all(values):
        raise ValueError(
            "Reusable preview deployment requires workflow ref, workload identity provider, and service account."
        )
    normalized_ref, normalized_provider, normalized_service_account = values
    if not _WORKFLOW_REF_PATTERN.fullmatch(normalized_ref):
        raise ValueError("Reusable preview deployment workflow ref is invalid.")
    if not _WIF_PROVIDER_PATTERN.fullmatch(normalized_provider):
        raise ValueError("Reusable preview deployment workload identity provider is invalid.")
    if not _SERVICE_ACCOUNT_PATTERN.fullmatch(normalized_service_account):
        raise ValueError("Reusable preview deployment service account is invalid.")
    return normalized_ref, normalized_provider, normalized_service_account


def render_reusable_preview_caller_workflow(
    *,
    managed_template_marker: str,
    workflow_ref: str,
    workload_identity_provider: str,
    service_account: str,
    display_name: str,
    gcp_project_id: str,
    gke_cluster_name: str,
    gke_cluster_location: str,
    kubernetes_namespace: str,
    target_environment_key: str,
    target_environment_source: str,
    site_identity: str,
    preview_hostname: str,
    preview_static_ip_name: str,
    preview_certificate_name: str,
    expected_certificate_fingerprint: str,
    frontend_config_name: str,
    backend_config_name: str,
    site_runtime_image_repository: str,
    private_image_auth_required: bool,
) -> str:
    settings = validate_reusable_preview_deployment_settings(
        workflow_ref=workflow_ref,
        workload_identity_provider=workload_identity_provider,
        service_account=service_account,
    )
    assert settings is not None
    normalized_ref, normalized_provider, normalized_service_account = settings

    required_labels = {
        "gcp_project_id": gcp_project_id,
        "gke_cluster_name": gke_cluster_name,
        "gke_cluster_location": gke_cluster_location,
        "kubernetes_namespace": kubernetes_namespace,
        "target_environment_key": target_environment_key,
        "target_environment_source": target_environment_source,
        "site_identity": site_identity,
        "preview_static_ip_name": preview_static_ip_name,
        "preview_certificate_name": preview_certificate_name,
        "frontend_config_name": frontend_config_name,
        "backend_config_name": backend_config_name,
    }
    for field_name, value in required_labels.items():
        if not _DNS_LABEL_PATTERN.fullmatch(str(value or "").strip()):
            raise ValueError(f"Reusable preview deployment {field_name} is invalid.")
    normalized_hostname = str(preview_hostname or "").strip().lower().rstrip(".")
    if not _HOSTNAME_PATTERN.fullmatch(normalized_hostname):
        raise ValueError("Reusable preview deployment hostname is invalid.")
    normalized_fingerprint = re.sub(r"[^0-9a-f]", "", str(expected_certificate_fingerprint or "").lower())
    if not _FINGERPRINT_PATTERN.fullmatch(normalized_fingerprint):
        raise ValueError("Reusable preview deployment certificate fingerprint is invalid.")
    normalized_image_repository = str(site_runtime_image_repository or "").strip().lower()
    if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_./-]+", normalized_image_repository):
        raise ValueError("Reusable preview deployment image repository is invalid.")

    def quoted(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=True)

    private_image_auth = "true" if private_image_auth_required else "false"
    normalized_display_name = str(display_name or "").strip().lower()
    if not _DNS_LABEL_PATTERN.fullmatch(normalized_display_name):
        raise ValueError("Reusable preview deployment display name is invalid.")

    return f"""# {managed_template_marker}
# {REUSABLE_PREVIEW_CALLER_MARKER}
name: MBSRN Deploy {normalized_display_name}

on:
  workflow_dispatch:
    inputs:
      replace_existing_runtime:
        description: Replace existing managed-site runtime resources before deploy
        required: false
        default: false
        type: boolean

permissions:
  contents: read
  packages: write
  id-token: write

jobs:
  deploy:
    permissions:
      contents: read
      packages: write
      id-token: write
    uses: {normalized_ref}
    with:
      gcp_project_id: {quoted(gcp_project_id)}
      gke_cluster_name: {quoted(gke_cluster_name)}
      gke_cluster_location: {quoted(gke_cluster_location)}
      kubernetes_namespace: {quoted(kubernetes_namespace)}
      target_environment_key: {quoted(target_environment_key)}
      target_environment_source: {quoted(target_environment_source)}
      site_identity: {quoted(site_identity)}
      preview_hostname: {quoted(normalized_hostname)}
      preview_static_ip_name: {quoted(preview_static_ip_name)}
      preview_certificate_name: {quoted(preview_certificate_name)}
      expected_certificate_fingerprint: {quoted(normalized_fingerprint)}
      frontend_config_name: {quoted(frontend_config_name)}
      backend_config_name: {quoted(backend_config_name)}
      site_runtime_image_repository: {quoted(normalized_image_repository)}
      private_image_auth_required: {private_image_auth}
      workload_identity_provider: {quoted(normalized_provider)}
      service_account: {quoted(normalized_service_account)}
      replace_existing_runtime: ${{{{ inputs.replace_existing_runtime }}}}
"""

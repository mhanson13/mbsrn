from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.integrations.preview_deployment_workflow import (
    REUSABLE_PREVIEW_CALLER_MARKER,
    render_reusable_preview_caller_workflow,
    validate_reusable_preview_deployment_settings,
)
from app.integrations.seo_migration_github_publisher import (
    _derive_managed_workflow_deploy_auth_mode,
    _render_managed_deploy_workflow_yaml,
    _validate_managed_workflow_template_before_publish,
)


WORKFLOW_REF = "mhanson13/mbsrn/.github/workflows/deploy-site-preview.yml@main"
WIF_PROVIDER = "projects/1068908288067/locations/global/workloadIdentityPools/" "mbsrn-preview/providers/github"
SERVICE_ACCOUNT = "mbsrn-preview-deployer@mbsrn-prod.iam.gserviceaccount.com"


def test_reusable_preview_deployment_settings_require_all_or_none() -> None:
    assert (
        validate_reusable_preview_deployment_settings(
            workflow_ref=None,
            workload_identity_provider=None,
            service_account=None,
        )
        is None
    )

    with pytest.raises(ValueError, match="requires workflow ref"):
        validate_reusable_preview_deployment_settings(
            workflow_ref=WORKFLOW_REF,
            workload_identity_provider=None,
            service_account=None,
        )


def test_reusable_preview_caller_contains_only_bounded_inputs_and_oidc_auth() -> None:
    rendered = _render_managed_deploy_workflow_yaml(
        workflow_id="deploy-www-prod.yml",
        repo_owner="mhanson13",
        repo_name="platfire",
        branch="main",
        deploy_workflow_mode="site_repo_template_v1",
        target_environment_key="gke_prod",
        target_environment_source="admin_config",
        managed_gke_config={
            "project_id": "mbsrn-prod",
            "cluster_name": "mbsrn-prod",
            "cluster_location": "us-central1",
        },
        kubernetes_namespace="platfire",
        namespace_source="preview_slug",
        preview_hostname="platfire.site.mbsrn.com",
        resource_slug="platfire",
        site_id="site-platfire",
        private_image_auth_required=True,
        pre_shared_certificate_name="mbsrn-platfire-ab12cd34",
        pre_shared_certificate_fingerprint="ab" * 32,
        reusable_deployment_settings=(WORKFLOW_REF, WIF_PROVIDER, SERVICE_ACCOUNT),
    )

    parsed = yaml.safe_load(rendered)
    deploy = parsed["jobs"]["deploy"]
    validation = _validate_managed_workflow_template_before_publish(workflow_yaml=rendered)

    assert validation.is_valid is True
    assert deploy["uses"] == WORKFLOW_REF
    assert deploy["with"]["preview_hostname"] == "platfire.site.mbsrn.com"
    assert deploy["with"]["preview_certificate_name"] == "mbsrn-platfire-ab12cd34"
    assert deploy["with"]["workload_identity_provider"] == WIF_PROVIDER
    assert deploy["with"]["service_account"] == SERVICE_ACCOUNT
    assert REUSABLE_PREVIEW_CALLER_MARKER in rendered
    assert _derive_managed_workflow_deploy_auth_mode(workflow_content=rendered) == "github_oidc_workload_identity"
    assert "GCP_DEPLOY_KEY" not in rendered
    assert "credentials_json" not in rendered
    assert "kubectl apply" not in rendered


def test_reusable_preview_caller_rejects_non_preview_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        render_reusable_preview_caller_workflow(
            managed_template_marker="mbsrn-managed-template:site_repo_template_v1",
            workflow_ref=WORKFLOW_REF,
            workload_identity_provider=WIF_PROVIDER,
            service_account=SERVICE_ACCOUNT,
            display_name="platfire",
            gcp_project_id="mbsrn-prod",
            gke_cluster_name="mbsrn-prod",
            gke_cluster_location="us-central1",
            kubernetes_namespace="platfire",
            target_environment_key="gke-prod",
            target_environment_source="admin-config",
            site_identity="site-platfire",
            preview_hostname="bad hostname",
            preview_static_ip_name="site-web-preview-ip-platfire",
            preview_certificate_name="mbsrn-platfire-ab12cd34",
            expected_certificate_fingerprint="ab" * 32,
            frontend_config_name="site-web-frontend-config-platfire",
            backend_config_name="site-web-backend-config-platfire",
            site_runtime_image_repository="ghcr.io/mhanson13/platfire/site-web",
            private_image_auth_required=True,
        )


def test_central_reusable_workflow_uses_wif_and_never_applies_managed_certificate() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-site-preview.yml"
    content = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    assert isinstance(parsed, dict)
    assert "workflow_call" in parsed.get(True, parsed.get("on", {}))
    assert "google-github-actions/auth@v3" in content
    assert "workload_identity_provider:" in content
    assert "credentials_json" not in content
    assert "GCP_DEPLOY_KEY" not in content
    assert "kubectl apply -f k8s/managedcertificate.yaml" not in content
    assert "networking.gke.io/managed-certificates:" in content
    assert "legacy_managed_certificate_annotation_present" in content

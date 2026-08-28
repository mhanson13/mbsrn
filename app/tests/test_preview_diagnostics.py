from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

from app.integrations.tls_certificate import TLSCertificateCapabilityCheck
from app.services.preview_diagnostics import PreviewDiagnosticCollectionService
from app.services.tls_certificates import TLSCertificateCapabilityStatus, TLSCertificateValidationError


def test_preview_diagnostic_bundle_is_bounded_and_redacts_sensitive_fields() -> None:
    workspace = SimpleNamespace(
        id="workspace-1",
        source_site_status="ingested",
        migration_status="deploy_requested",
        publish_status="published",
        deploy_status="deploy_requested",
        latest_generated_artifact_version_id="artifact-1",
        latest_approved_artifact_version_id="artifact-1",
        last_published_artifact_version_id="artifact-1",
        last_deployed_artifact_version_id="artifact-1",
    )
    migration_service = SimpleNamespace(
        get_workspace_summary=lambda **_kwargs: SimpleNamespace(
            workspace=workspace,
            publish_readiness={
                "ready": True,
                "blocker_codes": [],
                "artifact_media_readiness": {
                    "ready": False,
                    "readiness_source": "artifact_snapshot",
                    "artifact_version_id": "artifact-1",
                    "selected_assets_count": 3,
                    "materialized_assets_count": 1,
                    "selected_not_materialized_count": 2,
                    "blocker_codes": ["artifact_media_missing"],
                    "blocker_reason_codes": ["workspace_media_object_missing"],
                    "blocker_reason_counts": {"workspace_media_object_missing": 2},
                    "selected_not_materialized_asset_ids": ["asset-2", "asset-3"],
                    "missing_referenced_media_paths": ["media/hero.webp"],
                    "content_base64": "must-not-leak",
                },
                "target": {
                    "repo_owner": "example-owner",
                    "repo_name": "example-site",
                    "branch": "main",
                    "gcp_deploy_key": "private-json-key",
                    "github_token": "github-secret-token",
                },
            },
            deploy_readiness={
                "ready": False,
                "blocker_codes": ["certificate_pending"],
                "target": {
                    "preview_hostname": "example-site.site.mbsrn.com",
                    "kubernetes_namespace": "example-site-a1b2c3d4",
                    "raw_provider_response": "sensitive-provider-payload",
                },
            },
        )
    )
    release = SimpleNamespace(
        id="release-1",
        artifact_version_id="artifact-1",
        release_number=1,
        status="waiting",
        preview_hostname="example-site.site.mbsrn.com",
        git_commit_sha="a" * 40,
        certificate_asset_id="asset-1",
        certificate_fingerprint_sha256="b" * 64,
        deployment_run_id=None,
    )
    operation = SimpleNamespace(
        support_id="support-1",
        status="waiting",
        active_gate="certificate",
        failure_reason_code=None,
        failure_message=None,
    )
    gate = SimpleNamespace(
        gate_name="certificate",
        status="waiting",
        reason_code="certificate_pending",
        message="Certificate ensure is waiting.",
        next_action="Ensure the certificate.",
        attempt_count=0,
        details_json={
            "provider_service": "compute",
            "provider_operation": "sslCertificates.insert",
            "provider_http_status": 400,
            "provider_status": "INVALID_ARGUMENT",
            "retryable": False,
            "missing_permissions": [],
            "raw_provider_response": "must-not-leak",
        },
    )
    release_state = SimpleNamespace(release=release, operation=operation, gates=(gate,))
    release_service = SimpleNamespace(
        list=lambda **_kwargs: [release_state],
        get=lambda **_kwargs: release_state,
    )
    asset = SimpleNamespace(
        id="asset-1",
        fingerprint_sha256="b" * 64,
        gcp_resource_name="example-site-cert",
        status="published",
    )
    binding = SimpleNamespace(observed_fingerprint_sha256=None)
    capability = TLSCertificateCapabilityStatus(
        project_id="test-project",
        ready=False,
        checks=(
            TLSCertificateCapabilityCheck(
                component="secret_manager",
                required_permissions=("secretmanager.secrets.create",),
                granted_permissions=(),
            ),
        ),
        reason_code="tls_permissions_missing",
        message="Missing permission.",
    )
    certificate_service = SimpleNamespace(
        get_capabilities=lambda: capability,
        get_site_status=lambda **_kwargs: SimpleNamespace(
            hostname="example-site.site.mbsrn.com",
            asset=asset,
            binding=binding,
            vaulted=True,
            published=True,
            manifest_state="published_to_repo",
            serving_state="not_verified",
        ),
    )
    collector = PreviewDiagnosticCollectionService(
        release_service=release_service,
        migration_service=migration_service,
        certificate_service=certificate_service,
    )

    bundle = collector.collect(business_id="business-1", site_id="site-1")

    assert bundle["support_id"] == "support-1"
    assert bundle["retention_days"] == 7
    assert (bundle["expires_at"] - bundle["collected_at"]).days == 7
    assert bundle["payload"]["release"]["id"] == "release-1"
    assert bundle["payload"]["media"] == {
        "ready": False,
        "readiness_source": "artifact_snapshot",
        "artifact_version_id": "artifact-1",
        "selected_assets_count": 3,
        "materialized_assets_count": 1,
        "selected_not_materialized_count": 2,
        "blocker_codes": ["artifact_media_missing"],
        "blocker_reason_codes": ["workspace_media_object_missing"],
        "selected_not_materialized_asset_ids": ["asset-2", "asset-3"],
        "missing_referenced_media_paths": ["media/hero.webp"],
        "blocker_reason_counts": {"workspace_media_object_missing": 2},
    }
    assert bundle["payload"]["release"]["gates"][0]["details"] == {
        "provider_service": "compute",
        "provider_operation": "sslCertificates.insert",
        "provider_http_status": 400,
        "provider_status": "INVALID_ARGUMENT",
        "retryable": False,
        "missing_permissions": [],
    }
    assert bundle["payload"]["tls_capabilities"]["checks"][0]["missing_permissions"] == ["secretmanager.secrets.create"]
    serialized = json.dumps(
        bundle, default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value)
    )
    assert "private-json-key" not in serialized
    assert "github-secret-token" not in serialized
    assert "sensitive-provider-payload" not in serialized
    assert "must-not-leak" not in serialized
    assert "private_key" not in serialized


def test_preview_diagnostic_bundle_uses_requested_release() -> None:
    requested_ids: list[str] = []
    release_state = SimpleNamespace(
        release=SimpleNamespace(
            id="release-requested",
            artifact_version_id="artifact-1",
            release_number=2,
            status="failed",
            preview_hostname="requested.site.mbsrn.com",
            git_commit_sha=None,
            certificate_asset_id=None,
            certificate_fingerprint_sha256=None,
            deployment_run_id=None,
        ),
        operation=SimpleNamespace(
            support_id=None,
            status="failed",
            active_gate="github",
            failure_reason_code="github_failed",
            failure_message="GitHub rejected the request.",
        ),
        gates=(),
    )
    release_service = SimpleNamespace(
        get=lambda **kwargs: requested_ids.append(kwargs["release_id"]) or release_state,
        list=lambda **_kwargs: [],
    )
    migration_service = SimpleNamespace(
        get_workspace_summary=lambda **_kwargs: SimpleNamespace(
            workspace=SimpleNamespace(
                id="workspace-1",
                source_site_status="ingested",
                migration_status="draft_approved",
                publish_status="ready",
                deploy_status="not_ready",
                latest_generated_artifact_version_id="artifact-1",
                latest_approved_artifact_version_id="artifact-1",
                last_published_artifact_version_id=None,
                last_deployed_artifact_version_id=None,
            ),
            publish_readiness={},
            deploy_readiness={},
        )
    )
    certificate_service = SimpleNamespace(
        get_capabilities=lambda: TLSCertificateCapabilityStatus(
            project_id="test-project",
            ready=True,
            checks=(),
            reason_code="tls_capabilities_ready",
            message="Ready.",
        ),
        get_site_status=lambda **_kwargs: SimpleNamespace(
            hostname="requested.site.mbsrn.com",
            asset=None,
            binding=None,
            vaulted=False,
            published=False,
            manifest_state="not_selected",
            serving_state="not_verified",
        ),
    )

    bundle = PreviewDiagnosticCollectionService(
        release_service=release_service,
        migration_service=migration_service,
        certificate_service=certificate_service,
    ).collect(
        business_id="business-1",
        site_id="site-1",
        release_id="release-requested",
    )

    assert requested_ids == ["release-requested"]
    assert bundle["release_id"] == "release-requested"
    assert bundle["collected_at"].tzinfo == timezone.utc


def test_preview_diagnostic_bundle_records_missing_preview_identity_instead_of_failing() -> None:
    workspace = SimpleNamespace(
        id="workspace-1",
        source_site_status="ingested",
        migration_status="draft_generated",
        publish_status="not_ready",
        deploy_status="not_ready",
        latest_generated_artifact_version_id="artifact-1",
        latest_approved_artifact_version_id=None,
        last_published_artifact_version_id=None,
        last_deployed_artifact_version_id=None,
    )
    migration_service = SimpleNamespace(
        get_workspace_summary=lambda **_kwargs: SimpleNamespace(
            workspace=workspace,
            publish_readiness={},
            deploy_readiness={},
        )
    )
    capability = TLSCertificateCapabilityStatus(
        project_id="test-project",
        ready=False,
        checks=(),
        reason_code="tls_permissions_missing",
        message="Missing permission.",
    )

    def missing_preview_identity(**_kwargs):
        raise TLSCertificateValidationError("preview_slug is required before preview infrastructure is created")

    certificate_service = SimpleNamespace(
        get_capabilities=lambda: capability,
        get_site_status=missing_preview_identity,
    )

    bundle = PreviewDiagnosticCollectionService(
        release_service=SimpleNamespace(list=lambda **_kwargs: []),
        migration_service=migration_service,
        certificate_service=certificate_service,
    ).collect(business_id="business-1", site_id="site-1")

    certificate = bundle["payload"]["certificate"]
    assert certificate["manifest_state"] == "unavailable"
    assert certificate["collection_error"] == {
        "status": "unavailable",
        "reason_code": "preview_slug_required",
        "message": "preview_slug is required before preview infrastructure is created",
    }

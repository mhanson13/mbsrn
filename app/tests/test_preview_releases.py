from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.business import Business
from app.models.preview_release import PreviewRelease
from app.models.seo_migration_artifact_version import SEOMigrationArtifactVersion
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_site import SEOSite
from app.models.tls_certificate import SiteTLSCertificateBinding, TLSCertificateAsset
from app.repositories.preview_release_repository import PreviewReleaseRepository
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.repositories.tls_certificate_repository import TLSCertificateRepository
from app.services.preview_release_execution import PreviewReleaseExecutionService
from app.services.preview_releases import (
    PreviewReleaseNotFoundError,
    PreviewReleaseService,
    PreviewReleaseValidationError,
)
from app.services.seo_migration import SEOMigrationValidationError


class _RecordingMigrationService:
    def __init__(self, db_session, *, fail_publish: bool = False) -> None:
        self.db_session = db_session
        self.fail_publish = fail_publish
        self.publish_calls: list[dict[str, object]] = []

    def publish_artifact_version(self, **kwargs):
        self.publish_calls.append(dict(kwargs))
        if self.fail_publish:
            raise SEOMigrationValidationError(
                "GitHub rejected the release package.",
                error_code="github_publish_rejected",
            )
        artifact = self.db_session.get(SEOMigrationArtifactVersion, kwargs["artifact_version_id"])
        assert artifact is not None
        artifact.publish_status = "published"
        artifact.last_published_commit_sha = "c" * 40
        self.db_session.commit()


class _UnusedCertificateService:
    pass


class _RecordingCertificateService:
    def __init__(self) -> None:
        self.ensure_calls: list[dict[str, object]] = []

    def ensure_for_site(self, **kwargs):
        self.ensure_calls.append(dict(kwargs))


def _seed_release_source(db_session) -> tuple[str, str, str]:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    workspace_id = "33333333-3333-3333-3333-333333333333"
    artifact_id = "44444444-4444-4444-4444-444444444444"
    db_session.add(
        Business(
            id=business_id,
            name="Preview Release Tenant",
            customer_auto_ack_enabled=True,
            contractor_alerts_enabled=True,
        )
    )
    db_session.add(
        SEOSite(
            id=site_id,
            business_id=business_id,
            display_name="Generic Pilot",
            base_url="https://unrelated-source.example/",
            normalized_domain="unrelated-source.example",
            preview_slug="generic-pilot",
            is_active=True,
            is_primary=True,
        )
    )
    db_session.add(
        SEOMigrationWorkspace(
            id=workspace_id,
            business_id=business_id,
            site_id=site_id,
            source_url="https://unrelated-source.example/",
            source_site_status="ingested",
            migration_status="draft_approved",
            publish_config_json={"repo_owner": "example-owner", "repo_name": "different-repo", "branch": "main"},
            publish_status="ready",
            deploy_status="not_ready",
        )
    )
    db_session.add(
        SEOMigrationArtifactVersion(
            id=artifact_id,
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace_id,
            version=1,
            status="completed",
            context_json={
                "artifact_media_manifest": {
                    "selected_assets_count": 1,
                    "materialized_assets_count": 1,
                    "manifest": [{"asset_id": "asset-1", "materialized": True}],
                }
            },
            generated_files_json=[
                {"path": "index.html", "content": "<html></html>"},
                {"path": "assets/images/hero.png", "content_base64": "aW1hZ2U="},
            ],
            file_count=2,
            total_bytes=20,
            provider_name="mock",
            model_name="mock",
            prompt_version="v1",
            approval_status="approved",
            publish_status="not_published",
            deploy_status="not_deployed",
        )
    )
    db_session.commit()
    return business_id, site_id, artifact_id


def _service(db_session) -> PreviewReleaseService:
    return PreviewReleaseService(
        session=db_session,
        site_repository=SEOSiteRepository(db_session),
        migration_repository=SEOMigrationRepository(db_session),
        release_repository=PreviewReleaseRepository(db_session),
        certificate_repository=TLSCertificateRepository(db_session),
    )


def test_preview_release_creation_is_idempotent_and_freezes_identity_and_media(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    service = _service(db_session)

    first = service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key="operator-request-1",
        principal_id="principal-1",
    )
    second = service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key="operator-request-2",
        principal_id="principal-1",
    )

    assert first.release.id == second.release.id
    assert first.release.preview_hostname == "generic-pilot.site.mbsrn.com"
    assert first.release.media_manifest_json["materialized_assets_count"] == 1
    assert [gate.gate_name for gate in first.gates] == [
        "source",
        "draft_package",
        "approval",
        "github",
        "certificate",
        "dns",
        "deployment",
        "verification",
    ]
    assert [gate.status for gate in first.gates[:3]] == ["ready", "ready", "ready"]
    assert first.operation.active_gate == "github"
    assert db_session.query(PreviewRelease).count() == 1
    site = db_session.get(SEOSite, site_id)
    assert site is not None
    assert site.preview_slug_locked_at is not None


def test_preview_release_rejects_incomplete_legacy_approved_package(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    artifact = db_session.get(SEOMigrationArtifactVersion, artifact_id)
    assert artifact is not None
    artifact.context_json = {
        "artifact_media_manifest": {
            "selected_assets_count": 1,
            "materialized_assets_count": 0,
            "manifest": [{"asset_id": "asset-1", "materialized": False}],
        }
    }
    artifact.generated_files_json = [{"path": "index.html", "content": "<html></html>"}]
    db_session.add(artifact)
    db_session.commit()

    with pytest.raises(PreviewReleaseValidationError) as release_error:
        _service(db_session).create_or_resume(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact_id,
            idempotency_key=None,
            principal_id="principal-1",
        )

    assert release_error.value.reason_code == "draft_package_incomplete"
    assert db_session.query(PreviewRelease).count() == 0


def test_preview_release_reconcile_uses_exact_artifact_and_certificate_fingerprint(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    service = _service(db_session)
    state = service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key=None,
        principal_id="principal-1",
    )
    artifact = db_session.get(SEOMigrationArtifactVersion, artifact_id)
    workspace = db_session.query(SEOMigrationWorkspace).filter_by(site_id=site_id).one()
    assert artifact is not None
    artifact.publish_status = "published"
    artifact.last_published_commit_sha = "a" * 40
    artifact.deploy_status = "deployed"
    workspace.last_deployed_artifact_version_id = artifact_id
    workspace.deploy_history_json = [
        {
            "artifact_version_id": artifact_id,
            "workflow_run_id": 123456,
            "status": "requested",
        }
    ]
    fingerprint = "b" * 64
    asset = TLSCertificateAsset(
        id="55555555-5555-5555-5555-555555555555",
        business_id=business_id,
        hostname="generic-pilot.site.mbsrn.com",
        display_name="Generic preview certificate",
        source="generated",
        custody="vaulted",
        certificate_kind="self_signed",
        key_algorithm="rsa_2048",
        fingerprint_sha256=fingerprint,
        serial_number="1",
        subject="CN=generic-pilot.site.mbsrn.com",
        issuer="CN=generic-pilot.site.mbsrn.com",
        san_dns_names_json=["generic-pilot.site.mbsrn.com"],
        not_valid_before=datetime.now(timezone.utc) - timedelta(days=1),
        not_valid_after=datetime.now(timezone.utc) + timedelta(days=90),
        vault_secret_name="mbsrn-tls-test",
        vault_secret_version="projects/test/secrets/test/versions/1",
        gcp_project_id="mbsrn-prod",
        gcp_resource_name="generic-pilot-cert",
        gcp_resource_scope="global",
        status="published",
    )
    binding = SiteTLSCertificateBinding(
        id="66666666-6666-6666-6666-666666666666",
        business_id=business_id,
        site_id=site_id,
        certificate_asset_id=asset.id,
        is_active=True,
        manifest_state="published_to_repo",
        serving_state="serving",
        observed_fingerprint_sha256=fingerprint,
        last_verified_at=datetime.now(timezone.utc),
    )
    db_session.add_all([artifact, workspace, asset, binding])
    db_session.commit()

    reconciled = service.reconcile(
        business_id=business_id,
        site_id=site_id,
        release_id=state.release.id,
    )

    assert reconciled.release.status == "ready"
    assert reconciled.release.git_commit_sha == "a" * 40
    assert reconciled.release.certificate_fingerprint_sha256 == fingerprint
    assert reconciled.release.deployment_run_id == "123456"
    assert reconciled.release.preview_url == "https://generic-pilot.site.mbsrn.com"
    assert all(gate.status == "ready" for gate in reconciled.gates)


def test_preview_release_lookup_is_tenant_scoped(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    service = _service(db_session)
    state = service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key=None,
        principal_id="principal-1",
    )

    with pytest.raises(PreviewReleaseNotFoundError):
        service.get(
            business_id="99999999-9999-9999-9999-999999999999",
            site_id=site_id,
            release_id=state.release.id,
        )


def test_preview_release_executor_advances_one_gate_and_uses_idempotent_publish(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    release_service = _service(db_session)
    state = release_service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key=None,
        principal_id="principal-1",
    )
    migration_service = _RecordingMigrationService(db_session)
    executor = PreviewReleaseExecutionService(
        release_service=release_service,
        migration_service=migration_service,
        certificate_service=_UnusedCertificateService(),
    )

    advanced = executor.advance(
        business_id=business_id,
        site_id=site_id,
        release_id=state.release.id,
        principal_id="principal-1",
    )

    assert len(migration_service.publish_calls) == 1
    assert migration_service.publish_calls[0]["provision_deploy_workflow"] is False
    assert migration_service.publish_calls[0]["duplicate_is_success"] is True
    assert next(gate for gate in advanced.gates if gate.gate_name == "github").status == "ready"
    assert advanced.operation.active_gate == "certificate"


def test_preview_release_executor_classifies_certificate_manifest_publish_failure(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    release_service = _service(db_session)
    state = release_service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key=None,
        principal_id="principal-1",
    )
    initial_migration_service = _RecordingMigrationService(db_session)
    PreviewReleaseExecutionService(
        release_service=release_service,
        migration_service=initial_migration_service,
        certificate_service=_UnusedCertificateService(),
    ).advance(
        business_id=business_id,
        site_id=site_id,
        release_id=state.release.id,
        principal_id="principal-1",
    )
    certificate_service = _RecordingCertificateService()
    failing_migration_service = _RecordingMigrationService(db_session, fail_publish=True)

    failed = PreviewReleaseExecutionService(
        release_service=release_service,
        migration_service=failing_migration_service,
        certificate_service=certificate_service,
    ).advance(
        business_id=business_id,
        site_id=site_id,
        release_id=state.release.id,
        principal_id="principal-1",
    )

    failed_gate = next(gate for gate in failed.gates if gate.gate_name == "certificate")
    assert len(certificate_service.ensure_calls) == 1
    assert failing_migration_service.publish_calls[0]["provision_deploy_workflow"] is True
    assert failing_migration_service.publish_calls[0]["duplicate_is_success"] is True
    assert failed_gate.status == "failed"
    assert failed_gate.reason_code == "preview_release_certificate_manifest_publish_failed"
    assert failed_gate.message == (
        "The certificate is published, but its deployment manifest could not be verified in GitHub."
    )
    assert failed_gate.next_action == ("Retry this release to publish and verify the certificate deployment manifest.")


def test_preview_release_executor_records_failure_and_can_retry(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    release_service = _service(db_session)
    state = release_service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key=None,
        principal_id="principal-1",
    )
    failing_migration_service = _RecordingMigrationService(db_session, fail_publish=True)
    failing_executor = PreviewReleaseExecutionService(
        release_service=release_service,
        migration_service=failing_migration_service,
        certificate_service=_UnusedCertificateService(),
    )

    failed = failing_executor.advance(
        business_id=business_id,
        site_id=site_id,
        release_id=state.release.id,
        principal_id="principal-1",
    )

    failed_gate = next(gate for gate in failed.gates if gate.gate_name == "github")
    assert failed_gate.status == "failed"
    assert failed_gate.reason_code == "github_publish_rejected"
    assert failed_gate.attempt_count == 1
    assert failed.operation.support_id

    succeeding_migration_service = _RecordingMigrationService(db_session)
    retried = PreviewReleaseExecutionService(
        release_service=release_service,
        migration_service=succeeding_migration_service,
        certificate_service=_UnusedCertificateService(),
    ).advance(
        business_id=business_id,
        site_id=site_id,
        release_id=state.release.id,
        principal_id="principal-1",
    )

    retried_gate = next(gate for gate in retried.gates if gate.gate_name == "github")
    assert retried_gate.status == "ready"
    assert retried_gate.attempt_count == 2


def test_preview_release_certificate_selection_is_immutable(db_session) -> None:
    business_id, site_id, artifact_id = _seed_release_source(db_session)
    service = _service(db_session)
    state = service.create_or_resume(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact_id,
        idempotency_key=None,
        principal_id="principal-1",
    )
    artifact = db_session.get(SEOMigrationArtifactVersion, artifact_id)
    workspace = db_session.query(SEOMigrationWorkspace).filter_by(site_id=site_id).one()
    assert artifact is not None
    artifact.publish_status = "published"
    artifact.last_published_commit_sha = "a" * 40
    artifact.deploy_status = "deployed"
    workspace.last_deployed_artifact_version_id = artifact_id
    now = datetime.now(timezone.utc)
    original_asset = TLSCertificateAsset(
        id="77777777-7777-7777-7777-777777777777",
        business_id=business_id,
        hostname="generic-pilot.site.mbsrn.com",
        display_name="Original preview certificate",
        source="generated",
        custody="vaulted",
        certificate_kind="self_signed",
        key_algorithm="rsa_2048",
        fingerprint_sha256="d" * 64,
        serial_number="2",
        subject="CN=generic-pilot.site.mbsrn.com",
        issuer="CN=generic-pilot.site.mbsrn.com",
        san_dns_names_json=["generic-pilot.site.mbsrn.com"],
        not_valid_before=now - timedelta(days=1),
        not_valid_after=now + timedelta(days=90),
        vault_secret_name="mbsrn-tls-original",
        vault_secret_version="projects/test/secrets/original/versions/1",
        gcp_project_id="mbsrn-prod",
        gcp_resource_name="generic-pilot-original",
        gcp_resource_scope="global",
        status="published",
    )
    original_binding = SiteTLSCertificateBinding(
        id="88888888-8888-8888-8888-888888888888",
        business_id=business_id,
        site_id=site_id,
        certificate_asset_id=original_asset.id,
        is_active=True,
        manifest_state="published_to_repo",
        serving_state="serving",
        observed_fingerprint_sha256=original_asset.fingerprint_sha256,
        last_verified_at=now,
    )
    db_session.add_all([artifact, workspace, original_asset, original_binding])
    db_session.commit()
    ready = service.reconcile(business_id=business_id, site_id=site_id, release_id=state.release.id)
    assert ready.release.status == "ready"

    replacement_asset = TLSCertificateAsset(
        id="99999999-9999-9999-9999-999999999999",
        business_id=business_id,
        hostname="generic-pilot.site.mbsrn.com",
        display_name="Replacement preview certificate",
        source="generated",
        custody="vaulted",
        certificate_kind="self_signed",
        key_algorithm="rsa_2048",
        fingerprint_sha256="e" * 64,
        serial_number="3",
        subject="CN=generic-pilot.site.mbsrn.com",
        issuer="CN=generic-pilot.site.mbsrn.com",
        san_dns_names_json=["generic-pilot.site.mbsrn.com"],
        not_valid_before=now - timedelta(days=1),
        not_valid_after=now + timedelta(days=90),
        vault_secret_name="mbsrn-tls-replacement",
        vault_secret_version="projects/test/secrets/replacement/versions/1",
        gcp_project_id="mbsrn-prod",
        gcp_resource_name="generic-pilot-replacement",
        gcp_resource_scope="global",
        status="published",
    )
    replacement_binding = SiteTLSCertificateBinding(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        business_id=business_id,
        site_id=site_id,
        certificate_asset_id=replacement_asset.id,
        is_active=True,
        manifest_state="published_to_repo",
        serving_state="serving",
        observed_fingerprint_sha256=replacement_asset.fingerprint_sha256,
        last_verified_at=now,
    )
    original_binding.is_active = False
    db_session.add_all([original_binding, replacement_asset, replacement_binding])
    db_session.commit()

    changed = service.reconcile(business_id=business_id, site_id=site_id, release_id=state.release.id)

    assert changed.release.certificate_asset_id == original_asset.id
    assert changed.release.certificate_fingerprint_sha256 == original_asset.fingerprint_sha256
    certificate_gate = next(gate for gate in changed.gates if gate.gate_name == "certificate")
    verification_gate = next(gate for gate in changed.gates if gate.gate_name == "verification")
    assert certificate_gate.status == "action_required"
    assert certificate_gate.reason_code == "release_certificate_changed"
    assert verification_gate.status == "waiting"

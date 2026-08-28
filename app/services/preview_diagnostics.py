from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.core.time import utc_now
from app.services.preview_releases import PreviewReleaseService
from app.services.seo_migration import SEOMigrationService
from app.services.tls_certificates import TLSCertificateService


_PUBLISH_TARGET_KEYS = (
    "enabled",
    "repo_owner",
    "repo_name",
    "branch",
    "artifact_root",
    "repo_exists",
    "ref_exists",
    "repo_management_state",
)
_DEPLOY_TARGET_KEYS = (
    "enabled",
    "repo_owner",
    "repo_name",
    "workflow_id",
    "ref",
    "preview_hostname",
    "kubernetes_namespace",
    "expected_static_ip_name",
    "expected_managed_certificate_name",
)


class PreviewDiagnosticCollectionService:
    """Builds a bounded, secret-free snapshot for administrator troubleshooting."""

    def __init__(
        self,
        *,
        release_service: PreviewReleaseService,
        migration_service: SEOMigrationService,
        certificate_service: TLSCertificateService,
    ) -> None:
        self.release_service = release_service
        self.migration_service = migration_service
        self.certificate_service = certificate_service

    def collect(
        self,
        *,
        business_id: str,
        site_id: str,
        release_id: str | None = None,
        retention_days: int = 7,
    ) -> dict[str, object]:
        bounded_retention_days = max(1, min(30, int(retention_days)))
        collected_at = utc_now()
        release_state = None
        if release_id:
            release_state = self.release_service.get(
                business_id=business_id,
                site_id=site_id,
                release_id=release_id,
            )
        else:
            releases = self.release_service.list(business_id=business_id, site_id=site_id)
            release_state = releases[0] if releases else None
        summary = self.migration_service.get_workspace_summary(business_id=business_id, site_id=site_id)
        capability_status = self.certificate_service.get_capabilities()
        certificate_status = self.certificate_service.get_site_status(business_id=business_id, site_id=site_id)
        publish_readiness = summary.publish_readiness if isinstance(summary.publish_readiness, dict) else {}
        deploy_readiness = summary.deploy_readiness if isinstance(summary.deploy_readiness, dict) else {}
        publish_target = publish_readiness.get("target")
        deploy_target = deploy_readiness.get("target")
        asset = certificate_status.asset
        binding = certificate_status.binding
        support_id = (
            release_state.operation.support_id
            if release_state is not None and release_state.operation.support_id
            else str(uuid4())
        )
        payload: dict[str, object] = {
            "workspace": {
                "id": summary.workspace.id,
                "source_site_status": summary.workspace.source_site_status,
                "migration_status": summary.workspace.migration_status,
                "publish_status": summary.workspace.publish_status,
                "deploy_status": summary.workspace.deploy_status,
                "latest_generated_artifact_version_id": summary.workspace.latest_generated_artifact_version_id,
                "latest_approved_artifact_version_id": summary.workspace.latest_approved_artifact_version_id,
                "last_published_artifact_version_id": summary.workspace.last_published_artifact_version_id,
                "last_deployed_artifact_version_id": summary.workspace.last_deployed_artifact_version_id,
            },
            "publish": {
                "ready": bool(publish_readiness.get("ready")),
                "blocker_codes": self._string_list(publish_readiness.get("blocker_codes")),
                "target": self._whitelist(publish_target, _PUBLISH_TARGET_KEYS),
            },
            "deployment": {
                "ready": bool(deploy_readiness.get("ready")),
                "blocker_codes": self._string_list(deploy_readiness.get("blocker_codes")),
                "target": self._whitelist(deploy_target, _DEPLOY_TARGET_KEYS),
            },
            "certificate": {
                "hostname": certificate_status.hostname,
                "asset_id": asset.id if asset is not None else None,
                "fingerprint_sha256": asset.fingerprint_sha256 if asset is not None else None,
                "gcp_resource_name": asset.gcp_resource_name if asset is not None else None,
                "status": asset.status if asset is not None else None,
                "vaulted": certificate_status.vaulted,
                "published": certificate_status.published,
                "manifest_state": certificate_status.manifest_state,
                "serving_state": certificate_status.serving_state,
                "observed_fingerprint_sha256": (
                    binding.observed_fingerprint_sha256 if binding is not None else None
                ),
            },
            "tls_capabilities": {
                "project_id": capability_status.project_id,
                "ready": capability_status.ready,
                "reason_code": capability_status.reason_code,
                "checks": [
                    {
                        "component": check.component,
                        "ready": check.ready,
                        "missing_permissions": list(check.missing_permissions),
                    }
                    for check in capability_status.checks
                ],
            },
        }
        if release_state is not None:
            payload["release"] = {
                "id": release_state.release.id,
                "artifact_version_id": release_state.release.artifact_version_id,
                "release_number": release_state.release.release_number,
                "status": release_state.release.status,
                "preview_hostname": release_state.release.preview_hostname,
                "git_commit_sha": release_state.release.git_commit_sha,
                "certificate_asset_id": release_state.release.certificate_asset_id,
                "certificate_fingerprint_sha256": release_state.release.certificate_fingerprint_sha256,
                "deployment_run_id": release_state.release.deployment_run_id,
                "operation": {
                    "status": release_state.operation.status,
                    "active_gate": release_state.operation.active_gate,
                    "failure_reason_code": release_state.operation.failure_reason_code,
                },
                "gates": [
                    {
                        "name": gate.gate_name,
                        "status": gate.status,
                        "reason_code": gate.reason_code,
                        "message": gate.message,
                        "next_action": gate.next_action,
                        "attempt_count": gate.attempt_count,
                    }
                    for gate in release_state.gates
                ],
            }
        return {
            "bundle_id": str(uuid4()),
            "support_id": support_id,
            "business_id": business_id,
            "site_id": site_id,
            "release_id": release_state.release.id if release_state is not None else None,
            "collected_at": collected_at,
            "expires_at": collected_at + timedelta(days=bounded_retention_days),
            "retention_days": bounded_retention_days,
            "payload": payload,
            "exclusions": [
                "credentials and tokens",
                "private keys and secret payloads",
                "raw provider responses",
                "raw media and captured website contents",
            ],
        }

    @staticmethod
    def _whitelist(value: object, keys: tuple[str, ...]) -> dict[str, object]:
        source = value if isinstance(value, dict) else {}
        return {key: source.get(key) for key in keys if key in source}

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [str(item)[:120] for item in value if str(item).strip()][:20]

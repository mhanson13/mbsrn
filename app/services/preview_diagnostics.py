from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

from app.core.time import utc_now
from app.services.preview_releases import PreviewReleaseService
from app.services.seo_migration import SEOMigrationService
from app.services.tls_certificates import (
    TLSCertificateConfigurationError,
    TLSCertificateNotFoundError,
    TLSCertificateService,
    TLSCertificateValidationError,
)

logger = logging.getLogger(__name__)


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
_SHARED_PREVIEW_EDGE_DIAGNOSTIC_KEYS = (
    "gcp_project_id",
    "static_ip_name",
    "gateway_name",
    "gateway_namespace",
    "certificate_map_name",
    "certificate_map_entry_name",
    "certificate_name",
    "certificate_domain",
    "expected_static_ip_address",
    "status",
    "reason_code",
    "provider_reason_code",
    "provider_stage",
    "configuration_error",
    "certificate_active",
    "certificate_map_attached",
    "gateway_programmed",
    "gateway_address_matches",
    "gcp_credential_source",
    "gcp_principal_email",
    "gcp_impersonated_service_account_email",
)
_GATE_DETAIL_KEYS = (
    "provider_service",
    "provider_operation",
    "provider_http_status",
    "provider_status",
    "retryable",
    "missing_permissions",
)
_MEDIA_DIAGNOSTIC_SCALAR_KEYS = (
    "ready",
    "readiness_source",
    "artifact_version_id",
    "selected_assets_count",
    "materialized_assets_count",
    "selected_not_materialized_count",
    "selected_media_updated_after_artifact_created",
    "selected_media_pending_generation",
    "selected_media_pending_generation_count",
    "missing_referenced_media_paths_count",
    "unresolved_generated_media_paths_count",
    "unresolved_internal_media_ids_count",
    "unresolved_image_token_references_count",
    "invalid_media_references_count",
    "generated_media_publish_payload_missing_paths_count",
)
_MEDIA_DIAGNOSTIC_LIST_KEYS = (
    "blocker_codes",
    "blocker_reason_codes",
    "warning_codes",
    "reasons",
    "warnings",
    "selected_not_materialized_asset_ids",
    "selected_media_pending_generation_ids",
    "missing_referenced_media_paths",
    "unresolved_generated_media_paths",
    "generated_media_publish_payload_missing_paths",
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
        certificate_status = None
        certificate_error: dict[str, object] | None = None
        try:
            certificate_status = self.certificate_service.get_site_status(business_id=business_id, site_id=site_id)
        except (TLSCertificateConfigurationError, TLSCertificateNotFoundError, TLSCertificateValidationError) as exc:
            certificate_error = {
                "status": "unavailable",
                "reason_code": getattr(exc, "reason_code", None) or self._certificate_reason_code(exc),
                "message": str(exc),
            }
        publish_readiness = summary.publish_readiness if isinstance(summary.publish_readiness, dict) else {}
        deploy_readiness = summary.deploy_readiness if isinstance(summary.deploy_readiness, dict) else {}
        media_readiness = publish_readiness.get("artifact_media_readiness")
        if not isinstance(media_readiness, dict):
            media_readiness = deploy_readiness.get("artifact_media_readiness")
        publish_target = publish_readiness.get("target")
        deploy_target = deploy_readiness.get("target")
        media_diagnostics = self._media_diagnostics(media_readiness)
        publish_ready = bool(publish_readiness.get("ready"))
        deployment_ready = bool(deploy_readiness.get("ready"))
        asset = certificate_status.asset if certificate_status is not None else None
        binding = certificate_status.binding if certificate_status is not None else None
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
                "ready": publish_ready,
                "blocker_codes": self._string_list(publish_readiness.get("blocker_codes")),
                "target": self._whitelist(publish_target, _PUBLISH_TARGET_KEYS),
            },
            "deployment": {
                "ready": deployment_ready,
                "blocker_codes": self._string_list(deploy_readiness.get("blocker_codes")),
                "target": self._whitelist(deploy_target, _DEPLOY_TARGET_KEYS),
                "shared_preview_edge": self._shared_preview_edge_diagnostics(deploy_readiness),
            },
            "media": media_diagnostics,
            "certificate": {
                "hostname": certificate_status.hostname if certificate_status is not None else None,
                "asset_id": asset.id if asset is not None else None,
                "fingerprint_sha256": asset.fingerprint_sha256 if asset is not None else None,
                "gcp_resource_name": asset.gcp_resource_name if asset is not None else None,
                "status": asset.status if asset is not None else None,
                "failure_reason_code": getattr(asset, "failure_reason_code", None) if asset is not None else None,
                "failure_message": getattr(asset, "failure_message", None) if asset is not None else None,
                "vaulted": certificate_status.vaulted if certificate_status is not None else False,
                "published": certificate_status.published if certificate_status is not None else False,
                "manifest_state": (
                    certificate_status.manifest_state if certificate_status is not None else "unavailable"
                ),
                "serving_state": certificate_status.serving_state if certificate_status is not None else "unavailable",
                "observed_fingerprint_sha256": (binding.observed_fingerprint_sha256 if binding is not None else None),
                "collection_error": certificate_error,
            },
            "tls_capabilities": {
                "project_id": capability_status.project_id,
                "ready": capability_status.ready,
                "reason_code": capability_status.reason_code,
                "checks": [
                    {
                        "component": check.component,
                        "ready": check.ready,
                        "verification_state": check.verification_state,
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
                    "failure_message": getattr(release_state.operation, "failure_message", None),
                },
                "gates": [
                    {
                        "name": gate.gate_name,
                        "status": gate.status,
                        "reason_code": gate.reason_code,
                        "message": gate.message,
                        "next_action": gate.next_action,
                        "attempt_count": gate.attempt_count,
                        "details": self._gate_details(getattr(gate, "details_json", None)),
                    }
                    for gate in release_state.gates
                ],
            }
        bundle = {
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
        logger.info(
            "Preview diagnostics collected",
            extra={
                "json_fields": {
                    "event": "preview_diagnostics_collected",
                    "support_id": support_id,
                    "business_id": business_id,
                    "site_id": site_id,
                    "release_id": bundle["release_id"],
                    "publish_ready": publish_ready,
                    "deployment_ready": deployment_ready,
                    "media_ready": media_diagnostics.get("ready"),
                }
            },
        )
        return bundle

    @staticmethod
    def _certificate_reason_code(exc: Exception) -> str:
        if "preview_slug" in str(exc).lower():
            return "preview_slug_required"
        if isinstance(exc, TLSCertificateNotFoundError):
            return "tls_resource_not_found"
        return "tls_status_unavailable"

    @staticmethod
    def _whitelist(value: object, keys: tuple[str, ...]) -> dict[str, object]:
        source = value if isinstance(value, dict) else {}
        return {key: source.get(key) for key in keys if key in source}

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [str(item)[:120] for item in value if str(item).strip()][:20]

    @classmethod
    def _gate_details(cls, value: object) -> dict[str, object]:
        details = cls._whitelist(value, _GATE_DETAIL_KEYS)
        if "missing_permissions" in details:
            details["missing_permissions"] = cls._string_list(details["missing_permissions"])
        for key in ("provider_service", "provider_operation", "provider_status"):
            if key in details and details[key] is not None:
                details[key] = str(details[key])[:120]
        return details

    @classmethod
    def _media_diagnostics(cls, value: object) -> dict[str, object]:
        source = value if isinstance(value, dict) else {}
        diagnostics = cls._whitelist(source, _MEDIA_DIAGNOSTIC_SCALAR_KEYS)
        for key in _MEDIA_DIAGNOSTIC_LIST_KEYS:
            if key in source:
                diagnostics[key] = cls._string_list(source[key])
        for key in ("blocker_reason_counts", "selected_not_materialized_reason_counts"):
            counts = source.get(key)
            if isinstance(counts, dict):
                diagnostics[key] = {
                    str(reason)[:120]: int(count)
                    for reason, count in list(counts.items())[:20]
                    if isinstance(count, int) and count >= 0
                }
        return diagnostics

    @classmethod
    def _shared_preview_edge_diagnostics(cls, deploy_readiness: object) -> dict[str, object]:
        source = deploy_readiness if isinstance(deploy_readiness, dict) else {}
        diagnostics_source = source.get("shared_preview_edge_diagnostics")
        diagnostics = cls._whitelist(diagnostics_source, _SHARED_PREVIEW_EDGE_DIAGNOSTIC_KEYS)
        reasons = cls._string_list(source.get("shared_preview_edge_reasons"))
        diagnostic_reasons = (
            cls._string_list(diagnostics_source.get("reasons"))
            if isinstance(diagnostics_source, dict)
            else []
        )
        missing_fields = (
            cls._string_list(diagnostics_source.get("missing_fields"))
            if isinstance(diagnostics_source, dict)
            else []
        )
        return {
            "enabled": source.get("uses_gateway_api") is True,
            "status": cls._bounded_string(source.get("shared_preview_edge_status"), max_length=40),
            "reason_code": cls._bounded_string(
                source.get("shared_preview_edge_reason_code"), max_length=80
            ),
            "reasons": reasons[:8],
            "certificate_active": source.get("shared_preview_certificate_active"),
            "certificate_map_attached": source.get("shared_preview_certificate_map_attached"),
            "gateway_programmed": source.get("shared_preview_gateway_programmed"),
            "gateway_address_matches": source.get("shared_preview_gateway_address_matches"),
            "diagnostics": {
                **diagnostics,
                "reasons": diagnostic_reasons[:8],
                "missing_fields": missing_fields[:8],
            },
        }

    @staticmethod
    def _bounded_string(value: object, *, max_length: int) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized[:max_length] or None

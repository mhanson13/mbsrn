from __future__ import annotations

import logging

from app.services.preview_releases import PreviewReleaseService, PreviewReleaseState
from app.services.seo_migration import (
    SEOMigrationNotFoundError,
    SEOMigrationService,
    SEOMigrationValidationError,
)
from app.services.tls_certificates import (
    TLSCertificateConfigurationError,
    TLSCertificateNotFoundError,
    TLSCertificateService,
    TLSCertificateValidationError,
)


logger = logging.getLogger(__name__)


class PreviewReleaseExecutionService:
    """Advances exactly one external preview-release gate per call."""

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

    def advance(
        self,
        *,
        business_id: str,
        site_id: str,
        release_id: str,
        principal_id: str | None,
    ) -> PreviewReleaseState:
        state = self.release_service.reconcile(
            business_id=business_id,
            site_id=site_id,
            release_id=release_id,
        )
        gate_name = state.operation.active_gate
        if state.release.status == "ready" or gate_name is None:
            return state
        gate = next(item for item in state.gates if item.gate_name == gate_name)
        if gate.status == "action_required" or gate_name in {"source", "draft_package", "approval"}:
            return state

        self.release_service.mark_gate_running(
            business_id=business_id,
            site_id=site_id,
            release_id=release_id,
            gate_name=gate_name,
        )
        try:
            if gate_name == "github":
                self.migration_service.publish_artifact_version(
                    business_id=business_id,
                    site_id=site_id,
                    artifact_version_id=state.release.artifact_version_id,
                    dry_run=False,
                    commit_message=f"Publish preview release {state.release.release_number}",
                    analytics_measurement_id=None,
                    principal_id=principal_id,
                    provision_deploy_workflow=False,
                    duplicate_is_success=True,
                )
            elif gate_name == "certificate":
                self.certificate_service.ensure_for_site(
                    business_id=business_id,
                    site_id=site_id,
                    principal_id=principal_id,
                )
                self.migration_service.publish_artifact_version(
                    business_id=business_id,
                    site_id=site_id,
                    artifact_version_id=state.release.artifact_version_id,
                    dry_run=False,
                    commit_message=None,
                    analytics_measurement_id=None,
                    principal_id=principal_id,
                    provision_deploy_workflow=True,
                    duplicate_is_success=True,
                )
            elif gate_name in {"dns", "deployment"}:
                self.migration_service.deploy_artifact_version(
                    business_id=business_id,
                    site_id=site_id,
                    artifact_version_id=state.release.artifact_version_id,
                    dry_run=False,
                    principal_id=principal_id,
                )
            elif gate_name == "verification":
                self.certificate_service.verify_site_endpoint(
                    business_id=business_id,
                    site_id=site_id,
                    principal_id=principal_id,
                )
        except (
            SEOMigrationNotFoundError,
            SEOMigrationValidationError,
            TLSCertificateConfigurationError,
            TLSCertificateNotFoundError,
            TLSCertificateValidationError,
        ) as exc:
            reason_code = (
                getattr(exc, "reason_code", None)
                or getattr(exc, "error_code", None)
                or f"preview_release_{gate_name}_failed"
            )
            return self.release_service.mark_gate_failed(
                business_id=business_id,
                site_id=site_id,
                release_id=release_id,
                gate_name=gate_name,
                reason_code=str(reason_code),
                message=str(exc),
                next_action=f"Resolve the {gate_name.replace('_', ' ')} issue, then retry this release.",
            )
        except Exception:
            logger.exception(
                "Unexpected preview release gate failure",
                extra={
                    "json_fields": {
                        "event": "preview_release_gate_unexpected_failure",
                        "business_id": business_id,
                        "site_id": site_id,
                        "release_id": release_id,
                        "gate_name": gate_name,
                    }
                },
            )
            return self.release_service.mark_gate_failed(
                business_id=business_id,
                site_id=site_id,
                release_id=release_id,
                gate_name=gate_name,
                reason_code="preview_release_unexpected_failure",
                message=f"The {gate_name.replace('_', ' ')} step failed unexpectedly.",
                next_action="Give the support ID to an administrator, then retry after the issue is resolved.",
            )
        return self.release_service.reconcile(
            business_id=business_id,
            site_id=site_id,
            release_id=release_id,
        )

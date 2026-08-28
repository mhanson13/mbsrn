from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.preview_identity import PreviewIdentityValidationError, build_site_preview_identity
from app.core.time import utc_now
from app.models.preview_release import PreviewRelease, PreviewReleaseGate, PreviewReleaseOperation
from app.repositories.preview_release_repository import PreviewReleaseRepository
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.repositories.tls_certificate_repository import TLSCertificateRepository


PREVIEW_RELEASE_GATE_NAMES = (
    "source",
    "draft_package",
    "approval",
    "github",
    "certificate",
    "dns",
    "deployment",
    "verification",
)
PREVIEW_RELEASE_GATE_STATES = {"waiting", "running", "ready", "action_required", "failed"}


class PreviewReleaseNotFoundError(ValueError):
    pass


class PreviewReleaseValidationError(ValueError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class PreviewReleaseState:
    release: PreviewRelease
    operation: PreviewReleaseOperation
    gates: tuple[PreviewReleaseGate, ...]


class PreviewReleaseService:
    def __init__(
        self,
        *,
        session: Session,
        site_repository: SEOSiteRepository,
        migration_repository: SEOMigrationRepository,
        release_repository: PreviewReleaseRepository,
        certificate_repository: TLSCertificateRepository,
    ) -> None:
        self.session = session
        self.site_repository = site_repository
        self.migration_repository = migration_repository
        self.release_repository = release_repository
        self.certificate_repository = certificate_repository

    def create_or_resume(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
        idempotency_key: str | None,
        principal_id: str | None,
    ) -> PreviewReleaseState:
        existing = self.release_repository.get_for_artifact(business_id, site_id, artifact_version_id)
        if existing is not None:
            return self.reconcile(business_id=business_id, site_id=site_id, release_id=existing.id)
        site = self.site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise PreviewReleaseNotFoundError("Site not found.")
        workspace = self.migration_repository.get_workspace_for_business_site(business_id, site_id)
        artifact = self.migration_repository.get_artifact_version_for_business_site(
            business_id,
            site_id,
            artifact_version_id,
        )
        if workspace is None or artifact is None:
            raise PreviewReleaseNotFoundError("Approved migration artifact not found.")
        if artifact.approval_status != "approved":
            raise PreviewReleaseValidationError(
                "The selected draft must be approved before a preview release is created.",
                reason_code="preview_release_approval_required",
            )
        try:
            identity = build_site_preview_identity(site.preview_slug)
        except PreviewIdentityValidationError as exc:
            raise PreviewReleaseValidationError(str(exc), reason_code="preview_slug_required") from exc
        operation_key = self._normalize_idempotency_key(
            idempotency_key or f"preview-release:{site_id}:{artifact_version_id}"
        )
        media_manifest = self._artifact_media_manifest(artifact.context_json)
        publish_config = workspace.publish_config_json if isinstance(workspace.publish_config_json, dict) else {}
        release = PreviewRelease(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            release_number=self.release_repository.next_release_number(site_id),
            status="waiting",
            preview_slug=identity.slug,
            preview_hostname=identity.hostname,
            media_manifest_json=media_manifest,
            repo_owner=self._optional_string(publish_config.get("repo_owner"), 120),
            repo_name=self._optional_string(publish_config.get("repo_name"), 255),
            repo_branch=self._optional_string(publish_config.get("branch"), 255),
            created_by_principal_id=principal_id,
        )
        operation = PreviewReleaseOperation(
            id=str(uuid4()),
            release_id=release.id,
            business_id=business_id,
            site_id=site_id,
            idempotency_key=operation_key,
            status="waiting",
            requested_by_principal_id=principal_id,
            started_at=utc_now(),
        )
        self.release_repository.create_release(release)
        self.release_repository.create_operation(operation)
        for ordinal, gate_name in enumerate(PREVIEW_RELEASE_GATE_NAMES, start=1):
            status, reason_code, message, next_action = self._initial_gate_state(
                gate_name=gate_name,
                workspace=workspace,
                artifact=artifact,
                media_manifest=media_manifest,
            )
            self.release_repository.create_gate(
                PreviewReleaseGate(
                    id=str(uuid4()),
                    release_id=release.id,
                    operation_id=operation.id,
                    gate_name=gate_name,
                    ordinal=ordinal,
                    status=status,
                    reason_code=reason_code,
                    message=message,
                    next_action=next_action,
                    completed_at=utc_now() if status == "ready" else None,
                )
            )
        site.preview_slug_locked_at = site.preview_slug_locked_at or utc_now()
        self.site_repository.save(site)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raced = self.release_repository.get_for_artifact(business_id, site_id, artifact_version_id)
            if raced is not None:
                return self.reconcile(business_id=business_id, site_id=site_id, release_id=raced.id)
            raise PreviewReleaseValidationError(
                "The preview release request conflicts with an existing operation.",
                reason_code="preview_release_idempotency_conflict",
            ) from exc
        return self.reconcile(business_id=business_id, site_id=site_id, release_id=release.id)

    def get(self, *, business_id: str, site_id: str, release_id: str) -> PreviewReleaseState:
        release = self.release_repository.get_for_business_site(business_id, site_id, release_id)
        if release is None:
            raise PreviewReleaseNotFoundError("Preview release not found.")
        operation = self.release_repository.get_operation(release.id)
        if operation is None:
            raise PreviewReleaseNotFoundError("Preview release operation not found.")
        return PreviewReleaseState(
            release=release,
            operation=operation,
            gates=tuple(self.release_repository.list_gates(release.id)),
        )

    def list(self, *, business_id: str, site_id: str) -> list[PreviewReleaseState]:
        return [
            self.get(business_id=business_id, site_id=site_id, release_id=release.id)
            for release in self.release_repository.list_for_business_site(business_id, site_id)
        ]

    def reconcile(self, *, business_id: str, site_id: str, release_id: str) -> PreviewReleaseState:
        state = self.get(business_id=business_id, site_id=site_id, release_id=release_id)
        release = state.release
        operation = state.operation
        workspace = self.migration_repository.get_workspace_for_business_site(business_id, site_id)
        artifact = self.migration_repository.get_artifact_version_for_business_site(
            business_id,
            site_id,
            release.artifact_version_id,
        )
        if workspace is None or artifact is None:
            raise PreviewReleaseNotFoundError("Preview release source state not found.")
        active_binding = self.certificate_repository.get_active_binding(business_id, site_id)
        gates_by_name = {gate.gate_name: gate for gate in state.gates}
        self._set_ready_if(
            gates_by_name["source"],
            workspace.source_site_status == "ingested",
            "Source ingest is ready.",
        )
        package_ready = self._package_ready(artifact.generated_files_json, release.media_manifest_json)
        self._set_ready_if(
            gates_by_name["draft_package"],
            package_ready,
            "Draft package and media manifest are complete.",
        )
        self._set_ready_if(
            gates_by_name["approval"],
            artifact.approval_status == "approved",
            "The selected draft is approved.",
        )
        github_ready = artifact.publish_status == "published" and bool(artifact.last_published_commit_sha)
        if github_ready:
            self._set_gate_ready(gates_by_name["github"], "The exact release package is published to GitHub.")
            release.git_commit_sha = artifact.last_published_commit_sha
        active_certificate_ready = bool(
            active_binding
            and active_binding.certificate_asset.status == "published"
            and active_binding.certificate_asset.gcp_resource_name
            and active_binding.manifest_state == "published_to_repo"
        )
        if release.certificate_asset_id is None and active_certificate_ready and active_binding is not None:
            release.certificate_asset_id = active_binding.certificate_asset.id
            release.certificate_fingerprint_sha256 = active_binding.certificate_asset.fingerprint_sha256
            release.certificate_resource_name = active_binding.certificate_asset.gcp_resource_name
        certificate_ready = bool(
            active_certificate_ready
            and active_binding is not None
            and active_binding.certificate_asset.id == release.certificate_asset_id
            and active_binding.certificate_asset.fingerprint_sha256 == release.certificate_fingerprint_sha256
            and active_binding.certificate_asset.gcp_resource_name == release.certificate_resource_name
        )
        if certificate_ready:
            self._set_gate_ready(
                gates_by_name["certificate"],
                "A self-managed preview certificate is selected in the deployment manifest.",
            )
        elif release.certificate_asset_id is not None:
            self._set_gate_action_required(
                gates_by_name["certificate"],
                reason_code="release_certificate_changed",
                message="The certificate selected for this release is no longer the active published certificate.",
                next_action="Restore the selected certificate binding or create a new preview release.",
            )
            self._set_gate_waiting(
                gates_by_name["verification"],
                reason_code="release_certificate_verification_invalidated",
                message="Endpoint verification must be repeated after the selected certificate is restored.",
                next_action="Restore the selected certificate, deploy it, then verify the endpoint again.",
            )
        deployed_exact_artifact = (
            workspace.last_deployed_artifact_version_id == release.artifact_version_id
            and artifact.deploy_status in {"deployed", "deploy_requested"}
        )
        if deployed_exact_artifact:
            self._set_gate_ready(gates_by_name["dns"], "Preview DNS was accepted by the exact release deployment.")
            self._set_gate_ready(gates_by_name["deployment"], "The exact release deployment was requested.")
            release.dns_hostname = release.preview_hostname
            release.deployment_run_id = release.deployment_run_id or self._deployment_run_id(
                workspace.deploy_history_json,
                artifact_id=release.artifact_version_id,
            )
        verified = bool(
            deployed_exact_artifact
            and active_binding
            and active_binding.certificate_asset.id == release.certificate_asset_id
            and active_binding.serving_state == "serving"
            and active_binding.observed_fingerprint_sha256 == release.certificate_fingerprint_sha256
        )
        if verified:
            self._set_gate_ready(
                gates_by_name["verification"], "The preview serves the selected certificate fingerprint."
            )
            release.preview_url = f"https://{release.preview_hostname}"
            release.verified_at = active_binding.last_verified_at or utc_now()
        ordered_gates = tuple(sorted(gates_by_name.values(), key=lambda gate: gate.ordinal))
        first_incomplete = next((gate for gate in ordered_gates if gate.status != "ready"), None)
        if all(gate.status == "ready" for gate in ordered_gates):
            release.status = "ready"
            operation.status = "ready"
            operation.active_gate = None
            operation.completed_at = operation.completed_at or utc_now()
        elif any(gate.status == "failed" for gate in ordered_gates):
            release.status = "failed"
            operation.status = "failed"
            operation.active_gate = first_incomplete.gate_name if first_incomplete else None
        elif any(gate.status == "action_required" for gate in ordered_gates):
            release.status = "action_required"
            operation.status = "action_required"
            operation.active_gate = first_incomplete.gate_name if first_incomplete else None
        else:
            release.status = "waiting"
            operation.status = "waiting"
            operation.active_gate = first_incomplete.gate_name if first_incomplete else None
        self.release_repository.save_release(release)
        self.release_repository.save_operation(operation)
        self.session.commit()
        return PreviewReleaseState(release=release, operation=operation, gates=ordered_gates)

    def mark_gate_running(
        self,
        *,
        business_id: str,
        site_id: str,
        release_id: str,
        gate_name: str,
    ) -> PreviewReleaseState:
        state = self.get(business_id=business_id, site_id=site_id, release_id=release_id)
        gate = next((item for item in state.gates if item.gate_name == gate_name), None)
        if gate is None:
            raise PreviewReleaseValidationError(
                "Preview release gate was not found.",
                reason_code="preview_release_gate_not_found",
            )
        if any(item.status != "ready" for item in state.gates if item.ordinal < gate.ordinal):
            raise PreviewReleaseValidationError(
                "Earlier preview release gates must be ready before this gate can run.",
                reason_code="preview_release_gate_dependency_incomplete",
            )
        gate.status = "running"
        gate.reason_code = None
        gate.message = f"{gate_name.replace('_', ' ').title()} is running."
        gate.next_action = None
        gate.attempt_count += 1
        gate.started_at = utc_now()
        gate.completed_at = None
        state.release.status = "running"
        state.operation.status = "running"
        state.operation.active_gate = gate_name
        state.operation.failure_reason_code = None
        state.operation.failure_message = None
        self.release_repository.save_gate(gate)
        self.release_repository.save_release(state.release)
        self.release_repository.save_operation(state.operation)
        self.session.commit()
        return self.get(business_id=business_id, site_id=site_id, release_id=release_id)

    def mark_gate_failed(
        self,
        *,
        business_id: str,
        site_id: str,
        release_id: str,
        gate_name: str,
        reason_code: str,
        message: str,
        next_action: str,
    ) -> PreviewReleaseState:
        state = self.get(business_id=business_id, site_id=site_id, release_id=release_id)
        gate = next((item for item in state.gates if item.gate_name == gate_name), None)
        if gate is None:
            raise PreviewReleaseValidationError(
                "Preview release gate was not found.",
                reason_code="preview_release_gate_not_found",
            )
        gate.status = "failed"
        gate.reason_code = self._optional_string(reason_code, 120) or "preview_release_gate_failed"
        gate.message = self._optional_string(message, 500) or "The preview release gate failed."
        gate.next_action = self._optional_string(next_action, 500)
        gate.completed_at = utc_now()
        state.release.status = "failed"
        state.operation.status = "failed"
        state.operation.active_gate = gate_name
        state.operation.failure_reason_code = gate.reason_code
        state.operation.failure_message = gate.message
        state.operation.support_id = state.operation.support_id or str(uuid4())
        state.operation.completed_at = None
        self.release_repository.save_gate(gate)
        self.release_repository.save_release(state.release)
        self.release_repository.save_operation(state.operation)
        self.session.commit()
        return self.get(business_id=business_id, site_id=site_id, release_id=release_id)

    @staticmethod
    def _artifact_media_manifest(context_json: object) -> dict[str, object]:
        context = context_json if isinstance(context_json, dict) else {}
        manifest = context.get("artifact_media_manifest")
        return deepcopy(manifest) if isinstance(manifest, dict) else {}

    @staticmethod
    def _package_ready(generated_files: object, media_manifest: object) -> bool:
        files = generated_files if isinstance(generated_files, list) else []
        has_index = any(isinstance(item, dict) and item.get("path") == "index.html" for item in files)
        manifest = media_manifest if isinstance(media_manifest, dict) else {}
        selected = int(manifest.get("selected_assets_count") or 0)
        materialized = int(manifest.get("materialized_assets_count") or 0)
        return has_index and materialized >= selected

    @staticmethod
    def _deployment_run_id(history: object, *, artifact_id: str) -> str | None:
        items = history if isinstance(history, list) else []
        for item in reversed(items):
            if not isinstance(item, dict) or str(item.get("artifact_version_id") or "") != artifact_id:
                continue
            value = item.get("workflow_run_id") or item.get("deploy_trace_id")
            normalized = str(value or "").strip()
            if normalized:
                return normalized[:80]
        return None

    def _initial_gate_state(
        self,
        *,
        gate_name: str,
        workspace: object,
        artifact: object,
        media_manifest: dict[str, object],
    ) -> tuple[str, str | None, str, str | None]:
        if gate_name == "source":
            ready = getattr(workspace, "source_site_status", None) == "ingested"
            return self._binary_gate(ready, "source_not_ingested", "Source ingest is ready.", "Run source ingest.")
        if gate_name == "draft_package":
            ready = self._package_ready(getattr(artifact, "generated_files_json", None), media_manifest)
            return self._binary_gate(
                ready,
                "draft_package_incomplete",
                "Draft package and media manifest are complete.",
                "Regenerate the draft after resolving missing media.",
            )
        if gate_name == "approval":
            ready = getattr(artifact, "approval_status", None) == "approved"
            return self._binary_gate(
                ready, "approval_required", "The selected draft is approved.", "Approve the draft."
            )
        messages = {
            "github": (
                "github_publish_pending",
                "GitHub publication is waiting.",
                "Publish the exact release package.",
            ),
            "certificate": (
                "certificate_ensure_pending",
                "Preview certificate ensure is waiting.",
                "Ensure a self-managed preview certificate.",
            ),
            "dns": ("dns_ensure_pending", "Preview DNS ensure is waiting.", "Ensure preview DNS."),
            "deployment": ("deployment_pending", "Preview deployment is waiting.", "Deploy the exact release commit."),
            "verification": (
                "verification_pending",
                "Endpoint verification is waiting.",
                "Verify DNS, response, and certificate fingerprint.",
            ),
        }
        reason, message, action = messages[gate_name]
        return "waiting", reason, message, action

    @staticmethod
    def _binary_gate(
        ready: bool,
        reason_code: str,
        ready_message: str,
        next_action: str,
    ) -> tuple[str, str | None, str, str | None]:
        if ready:
            return "ready", None, ready_message, None
        return "action_required", reason_code, next_action, next_action

    @staticmethod
    def _set_gate_ready(gate: PreviewReleaseGate, message: str) -> None:
        gate.status = "ready"
        gate.reason_code = None
        gate.message = message
        gate.next_action = None
        gate.completed_at = gate.completed_at or utc_now()

    @staticmethod
    def _set_gate_action_required(
        gate: PreviewReleaseGate,
        *,
        reason_code: str,
        message: str,
        next_action: str,
    ) -> None:
        gate.status = "action_required"
        gate.reason_code = reason_code
        gate.message = message
        gate.next_action = next_action
        gate.completed_at = None

    @staticmethod
    def _set_gate_waiting(
        gate: PreviewReleaseGate,
        *,
        reason_code: str,
        message: str,
        next_action: str,
    ) -> None:
        gate.status = "waiting"
        gate.reason_code = reason_code
        gate.message = message
        gate.next_action = next_action
        gate.completed_at = None

    @classmethod
    def _set_ready_if(cls, gate: PreviewReleaseGate, ready: bool, message: str) -> None:
        if ready and gate.status != "ready":
            cls._set_gate_ready(gate, message)

    @staticmethod
    def _normalize_idempotency_key(value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 120:
            raise PreviewReleaseValidationError(
                "idempotency_key must contain 1 to 120 characters.",
                reason_code="preview_release_idempotency_key_invalid",
            )
        return normalized

    @staticmethod
    def _optional_string(value: object, max_length: int) -> str | None:
        normalized = str(value or "").strip()
        return normalized[:max_length] if normalized else None

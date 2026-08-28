from __future__ import annotations

from datetime import timedelta
import json
import logging
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.core.safe_url import UnsafePublicURLError, normalize_public_http_url
from app.integrations.migration_media_storage import MigrationMediaStorage, MigrationMediaStorageError
from app.models.seo_migration_source_capture import SEOMigrationSourceCapture
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_migration_source_capture_repository import SEOMigrationSourceCaptureRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.faithful_source_capture import (
    FaithfulSourceCaptureError,
    FaithfulSourceCaptureResult,
)
from app.services.seo_migration_ingest import SEOMigrationSourceIngestError, SEOMigrationSourceIngestService


logger = logging.getLogger(__name__)
_AUTHORIZATION_STATEMENT_VERSION = "faithful-snapshot-authorization-v1"


class FaithfulCaptureEngine(Protocol):
    def capture(
        self,
        *,
        source_url: str,
        page_limit: int,
        asset_limit: int,
        max_total_bytes: int,
    ) -> FaithfulSourceCaptureResult: ...


class SourceCaptureNotFoundError(LookupError):
    pass


class SourceCaptureValidationError(ValueError):
    pass


class SEOMigrationSourceCaptureService:
    def __init__(
        self,
        *,
        session: Session,
        site_repository: SEOSiteRepository,
        migration_repository: SEOMigrationRepository,
        capture_repository: SEOMigrationSourceCaptureRepository,
        ingest_service: SEOMigrationSourceIngestService,
        storage: MigrationMediaStorage,
        faithful_engine: FaithfulCaptureEngine,
        max_attempts: int = 3,
        stale_after_seconds: int = 600,
    ) -> None:
        self.session = session
        self.site_repository = site_repository
        self.migration_repository = migration_repository
        self.capture_repository = capture_repository
        self.ingest_service = ingest_service
        self.storage = storage
        self.faithful_engine = faithful_engine
        self.max_attempts = max(1, int(max_attempts))
        self.stale_after_seconds = max(60, int(stale_after_seconds))

    def queue_capture(
        self,
        *,
        business_id: str,
        site_id: str,
        mode: str,
        source_url: str | None,
        authorization_acknowledged: bool,
        idempotency_key: str,
        page_limit: int,
        asset_limit: int,
        max_total_bytes: int,
        principal_id: str | None,
    ) -> SEOMigrationSourceCapture:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in {"analyze_rebuild", "faithful_snapshot"}:
            raise SourceCaptureValidationError("Source capture mode is invalid.")
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if not normalized_idempotency_key:
            raise SourceCaptureValidationError("idempotency_key is required.")

        existing = self._resolve_idempotent_capture(
            business_id=business_id,
            site_id=site_id,
            idempotency_key=normalized_idempotency_key,
            normalized_mode=normalized_mode,
            source_url=source_url,
            page_limit=page_limit,
            asset_limit=asset_limit,
            max_total_bytes=max_total_bytes,
        )
        if existing is not None:
            return existing

        site = self.site_repository.get_for_business(business_id, site_id)
        workspace = self.migration_repository.lock_workspace_for_business_site(business_id, site_id)
        if site is None or workspace is None:
            raise SourceCaptureNotFoundError("Migration workspace was not found.")
        existing = self._resolve_idempotent_capture(
            business_id=business_id,
            site_id=site_id,
            idempotency_key=normalized_idempotency_key,
            normalized_mode=normalized_mode,
            source_url=source_url,
            page_limit=page_limit,
            asset_limit=asset_limit,
            max_total_bytes=max_total_bytes,
        )
        if existing is not None:
            return existing
        effective_source_url = str(source_url or workspace.source_url or "").strip()
        if not effective_source_url:
            raise SourceCaptureValidationError("source_url is required before capture.")
        try:
            effective_source_url = normalize_public_http_url(effective_source_url, require_dns=False)
        except UnsafePublicURLError as exc:
            raise SourceCaptureValidationError(str(exc)) from exc
        if normalized_mode == "faithful_snapshot" and not authorization_acknowledged:
            raise SourceCaptureValidationError("Authorization acknowledgment is required for a faithful snapshot.")

        now = utc_now()
        capture = SEOMigrationSourceCapture(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            idempotency_key=normalized_idempotency_key,
            source_version=self.capture_repository.next_source_version(site_id=site_id),
            mode=normalized_mode,
            status="queued",
            requested_source_url=effective_source_url,
            authorization_acknowledged=bool(
                authorization_acknowledged if normalized_mode == "faithful_snapshot" else False
            ),
            authorization_statement_version=(
                _AUTHORIZATION_STATEMENT_VERSION if normalized_mode == "faithful_snapshot" else None
            ),
            authorization_acknowledged_by_principal_id=(
                principal_id if normalized_mode == "faithful_snapshot" else None
            ),
            authorization_acknowledged_at=(now if normalized_mode == "faithful_snapshot" else None),
            requested_page_limit=max(1, int(page_limit)),
            requested_asset_limit=max(1, int(asset_limit)),
            requested_max_total_bytes=max(10_000, int(max_total_bytes)),
            browser_engine="chromium" if normalized_mode == "faithful_snapshot" else None,
            manifest_json=None,
            page_count=0,
            asset_count=0,
            total_bytes=0,
            unsupported_features_json=[],
            warning_codes_json=[],
            failure_reason_code=None,
            failure_message=None,
            attempt_count=0,
            created_by_principal_id=principal_id,
        )
        self.capture_repository.create(capture)
        workspace.source_url = effective_source_url
        workspace.ingestion_mode = normalized_mode
        workspace.latest_source_capture_id = capture.id
        workspace.source_site_status = "ingest_queued"
        workspace.migration_status = "source_ingesting"
        workspace.updated_by_principal_id = principal_id
        self.migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(capture)
        return capture

    def _resolve_idempotent_capture(
        self,
        *,
        business_id: str,
        site_id: str,
        idempotency_key: str,
        normalized_mode: str,
        source_url: str | None,
        page_limit: int,
        asset_limit: int,
        max_total_bytes: int,
    ) -> SEOMigrationSourceCapture | None:
        existing = self.capture_repository.get_by_idempotency_key(
            business_id=business_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            return None
        if existing.site_id != site_id:
            raise SourceCaptureValidationError("Idempotency key is already in use.")
        requested_source_url = str(source_url or "").strip()
        if requested_source_url:
            try:
                requested_source_url = normalize_public_http_url(requested_source_url, require_dns=False)
            except UnsafePublicURLError as exc:
                raise SourceCaptureValidationError(str(exc)) from exc
        if (
            existing.mode != normalized_mode
            or (requested_source_url and existing.requested_source_url != requested_source_url)
            or existing.requested_page_limit != max(1, int(page_limit))
            or existing.requested_asset_limit != max(1, int(asset_limit))
            or existing.requested_max_total_bytes != max(10_000, int(max_total_bytes))
        ):
            raise SourceCaptureValidationError("Idempotency key was reused with different capture parameters.")
        return existing

    def get_capture(
        self,
        *,
        business_id: str,
        site_id: str,
        capture_id: str,
    ) -> SEOMigrationSourceCapture:
        capture = self.capture_repository.get_for_business_site(
            business_id=business_id,
            site_id=site_id,
            capture_id=capture_id,
        )
        if capture is None:
            raise SourceCaptureNotFoundError("Source capture was not found.")
        return capture

    def list_captures(
        self,
        *,
        business_id: str,
        site_id: str,
        limit: int = 20,
    ) -> list[SEOMigrationSourceCapture]:
        if self.site_repository.get_for_business(business_id, site_id) is None:
            raise SourceCaptureNotFoundError("Site was not found.")
        return self.capture_repository.list_for_business_site(
            business_id=business_id,
            site_id=site_id,
            limit=limit,
        )

    def execute_next_queued_capture(self) -> SEOMigrationSourceCapture | None:
        capture_id = self.capture_repository.oldest_queued_id()
        if capture_id is None:
            return None
        return self.execute_queued_capture(capture_id=capture_id)

    def execute_queued_capture(self, *, capture_id: str) -> SEOMigrationSourceCapture | None:
        existing = self.capture_repository.get_by_id(capture_id=capture_id)
        if existing is None:
            return None
        if not self.capture_repository.claim_for_execution(capture_id=capture_id):
            self.session.rollback()
            return None
        now = utc_now()
        existing.started_at = now
        existing.failure_reason_code = None
        existing.failure_message = None
        self.capture_repository.save(existing)
        self.session.commit()
        self.session.refresh(existing)

        try:
            if existing.mode == "faithful_snapshot":
                self._execute_faithful(existing)
            else:
                self._execute_analyze(existing)
            return self._complete_capture(existing)
        except FaithfulSourceCaptureError as exc:
            return self._fail_capture(existing, reason_code=exc.reason_code, message=str(exc))
        except SEOMigrationSourceIngestError as exc:
            return self._fail_capture(existing, reason_code="source_ingest_failed", message=str(exc))
        except MigrationMediaStorageError as exc:
            return self._fail_capture(existing, reason_code="source_storage_failed", message=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception(
                "source_capture_execution_failed capture_id=%s business_id=%s site_id=%s",
                existing.id,
                existing.business_id,
                existing.site_id,
            )
            return self._fail_capture(
                existing,
                reason_code="capture_internal_error",
                message="Source capture failed unexpectedly. Use the support ID to investigate.",
            )

    def reconcile_stale_captures(self) -> int:
        cutoff = utc_now() - timedelta(seconds=self.stale_after_seconds)
        stale = self.capture_repository.list_stale_running(started_before=cutoff)
        for capture in stale:
            warnings = list(capture.warning_codes_json or [])
            if capture.attempt_count < self.max_attempts:
                capture.status = "queued"
                capture.started_at = None
                capture.failure_reason_code = None
                capture.failure_message = None
                if "worker_interrupted_retry" not in warnings:
                    warnings.append("worker_interrupted_retry")
                capture.warning_codes_json = warnings
            else:
                capture.status = "failed"
                capture.completed_at = utc_now()
                capture.failure_reason_code = "worker_retry_limit_reached"
                capture.failure_message = "Source capture stopped before completion and reached its retry limit."
                self._apply_workspace_failure_if_current(capture)
            self.capture_repository.save(capture)
        if stale:
            self.session.commit()
        return len(stale)

    def _execute_analyze(self, capture: SEOMigrationSourceCapture) -> None:
        result = self.ingest_service.ingest_homepage(source_url=capture.requested_source_url)
        snapshot = dict(result.snapshot)
        manifest = {
            "schema_version": 1,
            "capture_id": capture.id,
            "source_version": capture.source_version,
            "mode": capture.mode,
            "source_url": result.source_url,
            "snapshot": snapshot,
            "objects": [],
            "unsupported_features": [],
            "warning_codes": list(result.warnings),
        }
        self._store_manifest(capture, manifest)
        capture.manifest_json = manifest
        capture.page_count = int(snapshot.get("pages_scanned_count") or 0)
        capture.asset_count = 0
        capture.total_bytes = 0
        capture.unsupported_features_json = []
        capture.warning_codes_json = [str(item)[:120] for item in result.warnings]
        self._apply_workspace_success(capture, source_snapshot=snapshot, source_url=result.source_url)

    def _execute_faithful(self, capture: SEOMigrationSourceCapture) -> None:
        result = self.faithful_engine.capture(
            source_url=capture.requested_source_url,
            page_limit=capture.requested_page_limit,
            asset_limit=capture.requested_asset_limit,
            max_total_bytes=capture.requested_max_total_bytes,
        )
        stored_items: list[dict[str, object]] = []
        total_bytes = 0
        for captured_object in result.objects:
            storage_key = (
                f"source-captures/{capture.business_id}/{capture.site_id}/{capture.id}/"
                f"attempt-{capture.attempt_count}/{captured_object.artifact_path}"
            )
            stored = self.storage.write(
                key=storage_key,
                payload=captured_object.payload,
                content_type=captured_object.content_type,
            )
            if stored.sha256 != captured_object.sha256 or stored.size_bytes != captured_object.size_bytes:
                raise MigrationMediaStorageError("Stored source object verification failed.")
            total_bytes += stored.size_bytes
            stored_items.append(
                {
                    "kind": captured_object.kind,
                    "source_url": captured_object.source_url,
                    "final_url": captured_object.final_url,
                    "artifact_path": captured_object.artifact_path,
                    "content_type": captured_object.content_type,
                    "size_bytes": stored.size_bytes,
                    "sha256": stored.sha256,
                    "storage": {
                        "provider": stored.provider,
                        "bucket": stored.bucket,
                        "key": stored.key,
                        "generation": stored.generation,
                    },
                }
            )
        manifest = {
            "schema_version": 1,
            "capture_id": capture.id,
            "source_version": capture.source_version,
            "mode": capture.mode,
            "browser_engine": "chromium",
            "source_url": result.source_url,
            "final_url": result.final_url,
            "title": result.title,
            "pages": list(result.pages),
            "objects": stored_items,
            "unsupported_features": list(result.unsupported_features),
            "warning_codes": list(result.warning_codes),
            "blocked_external_request_count": result.blocked_external_request_count,
        }
        self._store_manifest(capture, manifest)
        capture.manifest_json = manifest
        capture.page_count = len(result.pages)
        capture.asset_count = sum(1 for item in result.objects if item.kind == "first_party_asset")
        capture.total_bytes = total_bytes
        capture.unsupported_features_json = list(result.unsupported_features)
        capture.warning_codes_json = list(result.warning_codes)
        source_snapshot = _faithful_source_snapshot(capture=capture, result=result, manifest=manifest)
        self._apply_workspace_success(capture, source_snapshot=source_snapshot, source_url=result.source_url)

    def _store_manifest(self, capture: SEOMigrationSourceCapture, manifest: dict[str, object]) -> None:
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        storage_key = (
            f"source-captures/{capture.business_id}/{capture.site_id}/{capture.id}/"
            f"attempt-{capture.attempt_count}/manifest.json"
        )
        stored = self.storage.write(key=storage_key, payload=payload, content_type="application/json")
        capture.manifest_storage_provider = stored.provider
        capture.manifest_storage_key = stored.key
        capture.manifest_storage_generation = stored.generation
        capture.manifest_sha256 = stored.sha256

    def _complete_capture(self, capture: SEOMigrationSourceCapture) -> SEOMigrationSourceCapture:
        capture.status = "completed"
        capture.failure_reason_code = None
        capture.failure_message = None
        capture.completed_at = utc_now()
        self.capture_repository.save(capture)
        self.session.commit()
        self.session.refresh(capture)
        return capture

    def _fail_capture(
        self,
        capture: SEOMigrationSourceCapture,
        *,
        reason_code: str,
        message: str,
    ) -> SEOMigrationSourceCapture:
        capture.status = "failed"
        capture.failure_reason_code = str(reason_code or "capture_failed")[:120]
        capture.failure_message = " ".join(str(message or "Source capture failed.").split())[:500]
        capture.completed_at = utc_now()
        self._apply_workspace_failure_if_current(capture)
        self.capture_repository.save(capture)
        self.session.commit()
        self.session.refresh(capture)
        return capture

    def _apply_workspace_success(
        self,
        capture: SEOMigrationSourceCapture,
        *,
        source_snapshot: dict[str, object],
        source_url: str,
    ) -> None:
        workspace = self.migration_repository.get_workspace_for_business_site(capture.business_id, capture.site_id)
        if workspace is None or workspace.latest_source_capture_id != capture.id:
            return
        workspace.source_url = source_url
        workspace.ingestion_mode = capture.mode
        workspace.source_site_status = "ingested"
        workspace.migration_status = "source_ingested"
        workspace.imported_source_snapshot_json = source_snapshot
        workspace.updated_by_principal_id = capture.created_by_principal_id
        self.migration_repository.save_workspace(workspace)

    def _apply_workspace_failure_if_current(self, capture: SEOMigrationSourceCapture) -> None:
        workspace = self.migration_repository.get_workspace_for_business_site(capture.business_id, capture.site_id)
        if workspace is None or workspace.latest_source_capture_id != capture.id:
            return
        workspace.source_site_status = "ingest_failed"
        workspace.migration_status = "source_needs_review"
        self.migration_repository.save_workspace(workspace)


def _faithful_source_snapshot(
    *,
    capture: SEOMigrationSourceCapture,
    result: FaithfulSourceCaptureResult,
    manifest: dict[str, object],
) -> dict[str, object]:
    pages = list(result.pages)
    text_blocks = [
        str(page.get("text_excerpt"))
        for page in pages
        if isinstance(page, dict) and str(page.get("text_excerpt") or "").strip()
    ]
    asset_urls = [
        str(item.get("source_url"))
        for item in manifest.get("objects", [])
        if isinstance(item, dict) and item.get("kind") == "first_party_asset"
    ]
    return {
        "source_url": result.source_url,
        "fetched_at": utc_now().isoformat(),
        "final_url": result.final_url,
        "status_code": 200,
        "content_type": "text/html",
        "title": result.title,
        "headings": [],
        "contact_signals": [],
        "phone_numbers": [],
        "emails": [],
        "addresses": [],
        "internal_links": [str(page.get("final_url")) for page in pages if isinstance(page, dict)],
        "service_blocks": text_blocks[:20],
        "pages_scanned_count": len(pages),
        "pages_scanned": [str(page.get("final_url")) for page in pages if isinstance(page, dict)],
        "asset_references": {"captured_first_party": asset_urls[:200]},
        "discovered_images": [],
        "cleaned_text_blocks": text_blocks[:120],
        "warnings": list(result.warning_codes),
        "faithful_capture": {
            "capture_id": capture.id,
            "source_version": capture.source_version,
            "manifest_storage_provider": capture.manifest_storage_provider,
            "manifest_storage_generation": capture.manifest_storage_generation,
            "manifest_sha256": capture.manifest_sha256,
            "unsupported_features": list(result.unsupported_features),
            "page_count": len(pages),
            "asset_count": len(asset_urls),
            "pages": pages[:25],
        },
    }

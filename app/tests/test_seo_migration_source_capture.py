from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.migration_media_storage import LocalMigrationMediaStorage
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_site import SEOSite
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_migration_source_capture_repository import SEOMigrationSourceCaptureRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.faithful_source_capture import (
    FaithfulCapturedObject,
    FaithfulSourceCaptureResult,
)
from app.services.seo_migration_ingest import SEOMigrationIngestResult
from app.services.seo_migration_source_capture import (
    SEOMigrationSourceCaptureService,
    SourceCaptureNotFoundError,
    SourceCaptureValidationError,
)


class _FakeFaithfulEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def capture(self, **kwargs: object) -> FaithfulSourceCaptureResult:
        self.calls.append(kwargs)
        return FaithfulSourceCaptureResult(
            source_url=str(kwargs["source_url"]),
            final_url="https://www.example.com/",
            title="Rendered Example",
            objects=(
                FaithfulCapturedObject(
                    kind="rendered_page",
                    source_url="https://example.com/",
                    final_url="https://www.example.com/",
                    artifact_path="pages/001-home.html",
                    content_type="text/html; charset=utf-8",
                    payload=b"<html><body>Rendered source</body></html>",
                ),
                FaithfulCapturedObject(
                    kind="first_party_asset",
                    source_url="https://www.example.com/assets/brand.png",
                    final_url="https://www.example.com/assets/brand.png",
                    artifact_path="assets/brand.png",
                    content_type="image/png",
                    payload=b"png-bytes",
                ),
            ),
            pages=(
                {
                    "source_url": "https://example.com/",
                    "final_url": "https://www.example.com/",
                    "artifact_path": "pages/001-home.html",
                    "title": "Rendered Example",
                    "text_excerpt": "Rendered source",
                },
            ),
            unsupported_features=("server_side_forms_require_replacement",),
            warning_codes=("external_resources_blocked",),
            blocked_external_request_count=2,
        )


class _FakeAnalyzeIngest:
    def ingest_homepage(self, *, source_url: str) -> SEOMigrationIngestResult:
        return SEOMigrationIngestResult(
            source_url=source_url,
            snapshot={"source_url": source_url, "title": "Analyzed", "pages_scanned_count": 1},
            warnings=(),
        )


def _build_service(
    db_session: Session,
    *,
    storage_root: Path,
    engine: _FakeFaithfulEngine | None = None,
) -> tuple[SEOMigrationSourceCaptureService, _FakeFaithfulEngine]:
    faithful_engine = engine or _FakeFaithfulEngine()
    return (
        SEOMigrationSourceCaptureService(
            session=db_session,
            site_repository=SEOSiteRepository(db_session),
            migration_repository=SEOMigrationRepository(db_session),
            capture_repository=SEOMigrationSourceCaptureRepository(db_session),
            ingest_service=_FakeAnalyzeIngest(),  # type: ignore[arg-type]
            storage=LocalMigrationMediaStorage(root=storage_root),
            faithful_engine=faithful_engine,
        ),
        faithful_engine,
    )


def _seed_workspace(db_session: Session, *, business_id: str, site_id: str = "site-capture") -> SEOMigrationWorkspace:
    site = SEOSite(
        id=site_id,
        business_id=business_id,
        base_url="https://example.com/",
        normalized_domain="example.com",
        display_name="Capture Example",
    )
    workspace = SEOMigrationWorkspace(
        id=f"workspace-{site_id}",
        business_id=business_id,
        site_id=site_id,
        source_url="https://example.com/",
        source_site_status="not_ingested",
        migration_status="draft",
        ingestion_mode="analyze_rebuild",
        publish_status="not_ready",
        deploy_status="not_ready",
    )
    db_session.add_all([site, workspace])
    db_session.commit()
    return workspace


def test_faithful_capture_requires_explicit_authorization(
    db_session: Session,
    seeded_business,
    tmp_path: Path,
) -> None:
    _seed_workspace(db_session, business_id=seeded_business.id)
    service, _engine = _build_service(db_session, storage_root=tmp_path)
    with pytest.raises(SourceCaptureValidationError, match="Authorization acknowledgment"):
        service.queue_capture(
            business_id=seeded_business.id,
            site_id="site-capture",
            mode="faithful_snapshot",
            source_url=None,
            authorization_acknowledged=False,
            idempotency_key="capture-without-authorization",
            page_limit=10,
            asset_limit=200,
            max_total_bytes=50_000_000,
            principal_id="operator-1",
        )


def test_faithful_capture_is_idempotent_and_freezes_storage_generations(
    db_session: Session,
    seeded_business,
    tmp_path: Path,
) -> None:
    workspace = _seed_workspace(db_session, business_id=seeded_business.id)
    service, engine = _build_service(db_session, storage_root=tmp_path)
    capture = service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="faithful_snapshot",
        source_url=None,
        authorization_acknowledged=True,
        idempotency_key="faithful-1",
        page_limit=10,
        asset_limit=200,
        max_total_bytes=50_000_000,
        principal_id="operator-1",
    )
    duplicate = service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="faithful_snapshot",
        source_url=None,
        authorization_acknowledged=True,
        idempotency_key="faithful-1",
        page_limit=10,
        asset_limit=200,
        max_total_bytes=50_000_000,
        principal_id="operator-1",
    )
    assert duplicate.id == capture.id
    assert capture.authorization_statement_version == "faithful-snapshot-authorization-v1"
    assert capture.authorization_acknowledged_by_principal_id == "operator-1"

    completed = service.execute_queued_capture(capture_id=capture.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.page_count == 1
    assert completed.asset_count == 1
    assert completed.manifest_sha256
    assert completed.manifest_storage_generation == completed.manifest_sha256
    assert engine.calls == [
        {
            "source_url": "https://example.com/",
            "page_limit": 10,
            "asset_limit": 200,
            "max_total_bytes": 50_000_000,
        }
    ]
    manifest = completed.manifest_json or {}
    objects = manifest.get("objects")
    assert isinstance(objects, list)
    assert all(isinstance(item, dict) and item.get("sha256") for item in objects)
    assert all(isinstance(item, dict) and isinstance(item.get("storage"), dict) for item in objects)
    assert all(
        isinstance(item, dict)
        and isinstance(item.get("storage"), dict)
        and "/attempt-1/" in str(item["storage"].get("key"))
        for item in objects
    )
    assert completed.manifest_storage_key is not None
    assert "/attempt-1/manifest.json" in completed.manifest_storage_key

    db_session.refresh(workspace)
    assert workspace.ingestion_mode == "faithful_snapshot"
    assert workspace.source_site_status == "ingested"
    snapshot = workspace.imported_source_snapshot_json or {}
    faithful = snapshot.get("faithful_capture")
    assert isinstance(faithful, dict)
    assert faithful.get("capture_id") == capture.id
    assert faithful.get("manifest_sha256") == completed.manifest_sha256
    assert "manifest_storage_key" not in faithful


def test_capture_idempotency_key_rejects_different_parameters(
    db_session: Session,
    seeded_business,
    tmp_path: Path,
) -> None:
    _seed_workspace(db_session, business_id=seeded_business.id)
    service, _engine = _build_service(db_session, storage_root=tmp_path)
    service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="faithful_snapshot",
        source_url=None,
        authorization_acknowledged=True,
        idempotency_key="faithful-stable-request",
        page_limit=10,
        asset_limit=200,
        max_total_bytes=50_000_000,
        principal_id="operator-1",
    )

    with pytest.raises(SourceCaptureValidationError, match="different capture parameters"):
        service.queue_capture(
            business_id=seeded_business.id,
            site_id="site-capture",
            mode="faithful_snapshot",
            source_url=None,
            authorization_acknowledged=True,
            idempotency_key="faithful-stable-request",
            page_limit=11,
            asset_limit=200,
            max_total_bytes=50_000_000,
            principal_id="operator-1",
        )


def test_older_capture_cannot_overwrite_newer_workspace_selection(
    db_session: Session,
    seeded_business,
    tmp_path: Path,
) -> None:
    workspace = _seed_workspace(db_session, business_id=seeded_business.id)
    service, _engine = _build_service(db_session, storage_root=tmp_path)
    first = service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="faithful_snapshot",
        source_url=None,
        authorization_acknowledged=True,
        idempotency_key="faithful-old",
        page_limit=10,
        asset_limit=200,
        max_total_bytes=50_000_000,
        principal_id="operator-1",
    )
    second = service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="faithful_snapshot",
        source_url=None,
        authorization_acknowledged=True,
        idempotency_key="faithful-new",
        page_limit=10,
        asset_limit=200,
        max_total_bytes=50_000_000,
        principal_id="operator-1",
    )
    service.execute_queued_capture(capture_id=first.id)
    db_session.refresh(workspace)
    assert workspace.latest_source_capture_id == second.id
    assert workspace.source_site_status == "ingest_queued"
    assert workspace.imported_source_snapshot_json is None


def test_capture_lookup_is_tenant_and_site_scoped(
    db_session: Session,
    seeded_business,
    tmp_path: Path,
) -> None:
    _seed_workspace(db_session, business_id=seeded_business.id)
    service, _engine = _build_service(db_session, storage_root=tmp_path)
    capture = service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="analyze_rebuild",
        source_url=None,
        authorization_acknowledged=False,
        idempotency_key="analyze-1",
        page_limit=8,
        asset_limit=120,
        max_total_bytes=10_000_000,
        principal_id="operator-1",
    )
    with pytest.raises(SourceCaptureNotFoundError):
        service.get_capture(
            business_id="other-business",
            site_id="site-capture",
            capture_id=capture.id,
        )


def test_stale_capture_retries_then_fails_at_attempt_limit(
    db_session: Session,
    seeded_business,
    tmp_path: Path,
) -> None:
    workspace = _seed_workspace(db_session, business_id=seeded_business.id)
    service, _engine = _build_service(db_session, storage_root=tmp_path)
    capture = service.queue_capture(
        business_id=seeded_business.id,
        site_id="site-capture",
        mode="analyze_rebuild",
        source_url=None,
        authorization_acknowledged=False,
        idempotency_key="stale-capture",
        page_limit=8,
        asset_limit=120,
        max_total_bytes=10_000_000,
        principal_id="operator-1",
    )
    capture.status = "running"
    capture.attempt_count = 1
    capture.started_at = utc_now() - timedelta(minutes=20)
    db_session.commit()

    assert service.reconcile_stale_captures() == 1
    db_session.refresh(capture)
    assert capture.status == "queued"
    assert capture.started_at is None
    assert capture.warning_codes_json == ["worker_interrupted_retry"]

    capture.status = "running"
    capture.attempt_count = 3
    capture.started_at = utc_now() - timedelta(minutes=20)
    db_session.commit()

    assert service.reconcile_stale_captures() == 1
    db_session.refresh(capture)
    db_session.refresh(workspace)
    assert capture.status == "failed"
    assert capture.failure_reason_code == "worker_retry_limit_reached"
    assert workspace.source_site_status == "ingest_failed"

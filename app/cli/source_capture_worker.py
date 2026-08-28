from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import time
from collections.abc import Sequence

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.integrations.migration_media_storage import (
    GoogleCloudStorageMigrationMediaStorage,
    LocalMigrationMediaStorage,
    MigrationMediaStorage,
)
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_migration_source_capture_repository import SEOMigrationSourceCaptureRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.faithful_source_capture import PlaywrightFaithfulSourceCaptureEngine
from app.services.seo_migration_ingest import SEOMigrationSourceIngestService
from app.services.seo_migration_source_capture import SEOMigrationSourceCaptureService


logger = logging.getLogger(__name__)
_stop_requested = False


def _request_stop(_signal_number: int, _frame: object) -> None:
    global _stop_requested
    _stop_requested = True


def _build_storage(settings: Settings) -> MigrationMediaStorage:
    if settings.migration_media_storage_backend == "gcs":
        return GoogleCloudStorageMigrationMediaStorage(
            bucket=settings.migration_media_gcs_bucket or "",
            project_id=settings.migration_media_gcs_project_id,
            timeout_seconds=settings.migration_media_gcs_timeout_seconds,
            api_base_url=settings.migration_media_gcs_api_base_url,
        )
    return LocalMigrationMediaStorage(root=Path(settings.migration_media_storage_root))


def run_worker_iteration(*, settings: Settings) -> bool:
    with SessionLocal() as session:
        service = SEOMigrationSourceCaptureService(
            session=session,
            site_repository=SEOSiteRepository(session),
            migration_repository=SEOMigrationRepository(session),
            capture_repository=SEOMigrationSourceCaptureRepository(session),
            ingest_service=SEOMigrationSourceIngestService(),
            storage=_build_storage(settings),
            faithful_engine=PlaywrightFaithfulSourceCaptureEngine(
                navigation_timeout_seconds=settings.faithful_capture_navigation_timeout_seconds,
                capture_timeout_seconds=settings.faithful_capture_timeout_seconds,
                render_wait_milliseconds=settings.faithful_capture_render_wait_milliseconds,
                max_resource_bytes=settings.faithful_capture_max_resource_bytes,
            ),
            stale_after_seconds=settings.faithful_capture_stale_after_seconds,
        )
        reconciled = service.reconcile_stale_captures()
        if reconciled:
            logger.warning("source_capture_worker_reconciled_stale count=%s", reconciled)
        capture = service.execute_next_queued_capture()
        if capture is None:
            return False
        logger.info(
            "source_capture_worker_completed capture_id=%s business_id=%s site_id=%s status=%s mode=%s",
            capture.id,
            capture.business_id,
            capture.site_id,
            capture.status,
            capture.mode,
        )
        return True


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.source_capture_worker",
        description="Process durable asynchronous migration source-capture runs.",
    )
    parser.add_argument("--once", action="store_true", help="Process at most one queued capture and exit.")
    args = parser.parse_args(argv)
    settings = get_settings()
    runtime_probe = PlaywrightFaithfulSourceCaptureEngine(
        navigation_timeout_seconds=settings.faithful_capture_navigation_timeout_seconds,
        capture_timeout_seconds=settings.faithful_capture_timeout_seconds,
        render_wait_milliseconds=settings.faithful_capture_render_wait_milliseconds,
        max_resource_bytes=settings.faithful_capture_max_resource_bytes,
    )
    try:
        runtime_probe.verify_runtime()
    except Exception:  # noqa: BLE001
        logger.exception("source_capture_worker_browser_capability_failed")
        return 1
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    logger.info(
        "source_capture_worker_started storage_backend=%s poll_seconds=%s",
        settings.migration_media_storage_backend,
        settings.faithful_capture_worker_poll_seconds,
    )
    while not _stop_requested:
        processed = run_worker_iteration(settings=settings)
        if args.once:
            return 0
        if not processed:
            time.sleep(settings.faithful_capture_worker_poll_seconds)
    logger.info("source_capture_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

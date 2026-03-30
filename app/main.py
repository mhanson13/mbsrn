from __future__ import annotations

import logging
import time
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.routes import (
    admin_runtime_router,
    auth_router,
    businesses_router,
    integrations_router,
    intake_router,
    jobs_router,
    leads_router,
    seo_router,
    seo_v1_router,
)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine, get_database_target

settings = get_settings()
app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)

API_CSP_VALUE = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = REPO_ROOT / "alembic"


def _is_local_like_env() -> bool:
    return settings.app_env in {"local", "development", "dev", "test"}


def _should_auto_create_schema() -> bool:
    return _is_local_like_env() and settings.db_auto_create_local


def _should_enforce_schema_readiness() -> bool:
    return not _is_local_like_env()


def _can_run_local_schema_autocreate() -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
    except SQLAlchemyError:
        return False, "database_inspection_failed"

    if not table_names:
        return True, "empty_database"
    if "alembic_version" in table_names:
        return False, "alembic_version_present"
    return False, "existing_tables_present"


def _is_security_headers_scope(path: str) -> bool:
    return path.startswith("/api") or path == "/health"


def _resolve_expected_alembic_head() -> str | None:
    try:
        config = Config(str(ALEMBIC_INI_PATH))
        config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to resolve expected Alembic head revision: %s", exc)
        return None

    if len(heads) != 1:
        logger.error("Expected exactly one Alembic head revision, got %s: %s", len(heads), heads)
        return None
    return heads[0]


EXPECTED_ALEMBIC_HEAD = _resolve_expected_alembic_head()
DATABASE_TARGET_HOST, DATABASE_TARGET_PORT = get_database_target()
DATABASE_TARGET_PORT_LABEL = str(DATABASE_TARGET_PORT) if DATABASE_TARGET_PORT is not None else "default"
_LOCALHOST_DATABASE_TARGETS = {"localhost", "127.0.0.1", "::1"}
_CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_MAX_ATTEMPTS = 15
_CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_RETRY_DELAY_SECONDS = 1.0
_SCHEMA_READINESS_LOGGED_REVISION: str | None = None


def _is_localhost_database_target() -> bool:
    return DATABASE_TARGET_HOST.strip().lower() in _LOCALHOST_DATABASE_TARGETS


def _database_target_classification() -> str:
    if _is_localhost_database_target():
        return "loopback"
    if DATABASE_TARGET_HOST.strip():
        return "network"
    return "unknown"


def _is_cloudsql_proxy_mode() -> bool:
    return settings.app_env == "production" and settings.db_connection_mode == "cloudsql_proxy"


def _ensure_database_connectivity() -> None:
    if settings.app_env == "production" and _is_localhost_database_target() and not _is_cloudsql_proxy_mode():
        raise RuntimeError(
            "Production DB config regression detected: resolved localhost target is invalid when APP_ENV=production"
        )

    max_attempts = 1
    retry_delay_seconds = 0.0
    if _is_cloudsql_proxy_mode() and _is_localhost_database_target():
        max_attempts = _CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_MAX_ATTEMPTS
        retry_delay_seconds = _CLOUDSQL_PROXY_STARTUP_CONNECTIVITY_RETRY_DELAY_SECONDS
        logger.info(
            "Startup database connectivity check using cloudsql proxy retry budget host=%s port=%s app_env=%s "
            "db_connection_mode=%s max_attempts=%s retry_delay_seconds=%s",
            DATABASE_TARGET_HOST,
            DATABASE_TARGET_PORT_LABEL,
            settings.app_env,
            settings.db_connection_mode,
            max_attempts,
            retry_delay_seconds,
        )

    start = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Startup database connectivity check succeeded host=%s port=%s app_env=%s db_connection_mode=%s "
                "attempt=%s max_attempts=%s elapsed_ms=%s proxy_retry_path_entered=%s recovered_after_retry=%s",
                DATABASE_TARGET_HOST,
                DATABASE_TARGET_PORT_LABEL,
                settings.app_env,
                settings.db_connection_mode,
                attempt,
                max_attempts,
                elapsed_ms,
                max_attempts > 1,
                attempt > 1,
            )
            return
        except SQLAlchemyError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if attempt >= max_attempts:
                logger.error(
                    "Startup database connectivity check failed host=%s port=%s app_env=%s db_connection_mode=%s "
                    "attempt=%s max_attempts=%s elapsed_ms=%s error=%s",
                    DATABASE_TARGET_HOST,
                    DATABASE_TARGET_PORT_LABEL,
                    settings.app_env,
                    settings.db_connection_mode,
                    attempt,
                    max_attempts,
                    elapsed_ms,
                    exc,
                )
                raise RuntimeError(
                    "Startup database connectivity check failed. Verify DATABASE_URL and database reachability."
                ) from exc

            logger.warning(
                "Startup database connectivity check retrying host=%s port=%s app_env=%s db_connection_mode=%s "
                "attempt=%s max_attempts=%s elapsed_ms=%s error=%s",
                DATABASE_TARGET_HOST,
                DATABASE_TARGET_PORT_LABEL,
                settings.app_env,
                settings.db_connection_mode,
                attempt,
                max_attempts,
                elapsed_ms,
                exc,
            )
            time.sleep(retry_delay_seconds)


def _check_schema_readiness() -> tuple[bool, dict[str, object]]:
    global _SCHEMA_READINESS_LOGGED_REVISION
    if EXPECTED_ALEMBIC_HEAD is None:
        return False, {
            "status": "not_ready",
            "service": settings.app_name,
            "reason": "expected_revision_unresolved",
        }

    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM alembic_version")).all()
    except SQLAlchemyError as exc:
        logger.warning(
            "Schema readiness query failed host=%s port=%s error=%s",
            DATABASE_TARGET_HOST,
            DATABASE_TARGET_PORT_LABEL,
            exc,
        )
        return False, {
            "status": "not_ready",
            "service": settings.app_name,
            "reason": "alembic_version_unavailable",
            "expected_revision": EXPECTED_ALEMBIC_HEAD,
            "database_host": DATABASE_TARGET_HOST,
            "database_port": DATABASE_TARGET_PORT_LABEL,
        }

    revisions = sorted({str(row[0]).strip() for row in rows if row and row[0] is not None and str(row[0]).strip()})
    if len(revisions) != 1:
        logger.warning("Schema readiness found invalid alembic_version state: %s", revisions)
        return False, {
            "status": "not_ready",
            "service": settings.app_name,
            "reason": "invalid_alembic_version_state",
            "expected_revision": EXPECTED_ALEMBIC_HEAD,
            "current_revisions": revisions,
        }
    if revisions[0] != EXPECTED_ALEMBIC_HEAD:
        logger.warning(
            "Schema readiness revision mismatch expected=%s current=%s",
            EXPECTED_ALEMBIC_HEAD,
            revisions[0],
        )
        return False, {
            "status": "not_ready",
            "service": settings.app_name,
            "reason": "schema_revision_mismatch",
            "expected_revision": EXPECTED_ALEMBIC_HEAD,
            "current_revisions": revisions,
        }
    if _SCHEMA_READINESS_LOGGED_REVISION != revisions[0]:
        logger.info(
            "Schema readiness passed expected=%s current=%s host=%s port=%s app_env=%s db_connection_mode=%s",
            EXPECTED_ALEMBIC_HEAD,
            revisions[0],
            DATABASE_TARGET_HOST,
            DATABASE_TARGET_PORT_LABEL,
            settings.app_env,
            settings.db_connection_mode,
        )
        _SCHEMA_READINESS_LOGGED_REVISION = revisions[0]
    return True, {
        "status": "ok",
        "service": settings.app_name,
        "schema_revision": revisions[0],
    }


def _configure_cors() -> None:
    if not settings.api_cors_allowed_origins:
        logger.info("CORS middleware disabled (API_CORS_ALLOWED_ORIGINS not set).")
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api_cors_allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        allow_credentials=False,
    )
    logger.info("CORS middleware enabled for %d origin(s).", len(settings.api_cors_allowed_origins))


def _configure_security_headers() -> None:
    if not settings.security_headers_enabled:
        logger.warning("Security response headers are disabled by configuration.")
        return

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        if _is_security_headers_scope(request.url.path):
            response.headers.setdefault("Content-Security-Policy", API_CSP_VALUE)

        if settings.security_headers_hsts_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.security_headers_hsts_max_age_seconds}; includeSubDomains",
            )
        return response

    logger.info(
        "Security headers middleware enabled (hsts_enabled=%s, hsts_max_age=%s).",
        settings.security_headers_hsts_enabled,
        settings.security_headers_hsts_max_age_seconds,
    )


_configure_cors()
_configure_security_headers()


@app.on_event("startup")
def on_startup() -> None:
    if _should_enforce_schema_readiness():
        logger.info(
            "Startup schema readiness expectation expected_revision=%s app_env=%s db_connection_mode=%s "
            "database_target_classification=%s host=%s port=%s",
            EXPECTED_ALEMBIC_HEAD or "unresolved",
            settings.app_env,
            settings.db_connection_mode,
            _database_target_classification(),
            DATABASE_TARGET_HOST,
            DATABASE_TARGET_PORT_LABEL,
        )
        _ensure_database_connectivity()

    if _should_auto_create_schema():
        can_autocreate, reason = _can_run_local_schema_autocreate()
        if not can_autocreate:
            logger.warning(
                "Skipping local schema auto-create (reason=%s). "
                "Use `alembic upgrade head` to align local schema state.",
                reason,
            )
            return
        logger.warning(
            "Local schema auto-create is enabled (app_env=%s, DB_AUTO_CREATE_LOCAL=%s). "
            "Alembic remains authoritative for non-local environments.",
            settings.app_env,
            settings.db_auto_create_local,
        )
        Base.metadata.create_all(bind=engine)
        return

    logger.info(
        "Skipping startup schema auto-create (app_env=%s, DB_AUTO_CREATE_LOCAL=%s). "
        "Expected schema authority: Alembic migrations.",
        settings.app_env,
        settings.db_auto_create_local,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/healthz")
def readiness_health() -> Response:
    if not _should_enforce_schema_readiness():
        return JSONResponse(status_code=200, content={"status": "ok", "service": settings.app_name})

    ready, payload = _check_schema_readiness()
    if ready:
        return JSONResponse(status_code=200, content=payload)
    return JSONResponse(status_code=503, content=payload)


app.include_router(intake_router)
app.include_router(leads_router)
app.include_router(jobs_router)
app.include_router(businesses_router)
app.include_router(admin_runtime_router)
app.include_router(auth_router)
app.include_router(integrations_router)
app.include_router(seo_router)
app.include_router(seo_v1_router)

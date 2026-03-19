from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.routes import (
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
from app.db.session import engine

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


def _check_schema_readiness() -> tuple[bool, dict[str, object]]:
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
        logger.warning("Schema readiness query failed: %s", exc)
        return False, {
            "status": "not_ready",
            "service": settings.app_name,
            "reason": "alembic_version_unavailable",
            "expected_revision": EXPECTED_ALEMBIC_HEAD,
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
    if _should_auto_create_schema():
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
app.include_router(auth_router)
app.include_router(integrations_router)
app.include_router(seo_router)
app.include_router(seo_v1_router)

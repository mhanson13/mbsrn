from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
from app.db.session import SessionLocal, engine
from app.repositories.business_repository import BusinessRepository

settings = get_settings()
app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)

API_CSP_VALUE = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


def _is_local_like_env() -> bool:
    return settings.app_env in {"local", "development", "dev", "test"}


def _should_auto_create_schema() -> bool:
    return _is_local_like_env() and settings.db_auto_create_local


def _is_security_headers_scope(path: str) -> bool:
    return path.startswith("/api") or path == "/health"


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
        if not settings.default_business_id:
            raise RuntimeError(
                "DEFAULT_BUSINESS_ID is required when local schema auto-create is enabled."
            )
        logger.warning(
            "Local schema auto-create is enabled (app_env=%s, DB_AUTO_CREATE_LOCAL=%s). "
            "Alembic remains authoritative for non-local environments.",
            settings.app_env,
            settings.db_auto_create_local,
        )
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        try:
            BusinessRepository(session).get_or_create(
                business_id=settings.default_business_id,
                name="T&M Fire",
                notification_phone="+13035550101",
                notification_email="owner@tmfire.example",
            )
            session.commit()
        finally:
            session.close()
        return

    logger.info(
        "Skipping startup schema auto-create (app_env=%s, DB_AUTO_CREATE_LOCAL=%s). "
        "Expected schema authority: Alembic migrations.",
        settings.app_env,
        settings.db_auto_create_local,
    )


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(intake_router)
app.include_router(leads_router)
app.include_router(jobs_router)
app.include_router(businesses_router)
app.include_router(auth_router)
app.include_router(integrations_router)
app.include_router(seo_router)
app.include_router(seo_v1_router)

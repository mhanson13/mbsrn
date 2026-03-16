from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import auth_router, businesses_router, intake_router, jobs_router, leads_router, seo_router, seo_v1_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.repositories.business_repository import BusinessRepository

settings = get_settings()
app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)


def _is_local_like_env() -> bool:
    return settings.app_env in {"local", "development", "dev", "test"}


def _should_auto_create_schema() -> bool:
    return _is_local_like_env() and settings.db_auto_create_local


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
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(intake_router)
app.include_router(leads_router)
app.include_router(jobs_router)
app.include_router(businesses_router)
app.include_router(auth_router)
app.include_router(seo_router)
app.include_router(seo_v1_router)

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import auth_router, businesses_router, intake_router, jobs_router, leads_router, seo_router, seo_v1_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.repositories.business_repository import BusinessRepository

settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def on_startup() -> None:
    # For MVP speed: auto-create tables. Alembic is included for later migration control.
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

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_database_target(database_url: str) -> tuple[str, int | None]:
    parsed = urlparse(database_url)
    host = (parsed.hostname or "").strip() or "unknown"
    port = parsed.port
    if port is None and parsed.scheme.lower().startswith("postgresql"):
        port = 5432
    return host, port


# future=True style is default on SQLAlchemy 2.x
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
_DATABASE_TARGET_HOST, _DATABASE_TARGET_PORT = _resolve_database_target(settings.database_url)
logger.info(
    "Database target resolved: host=%s, port=%s",
    _DATABASE_TARGET_HOST,
    str(_DATABASE_TARGET_PORT) if _DATABASE_TARGET_PORT is not None else "default",
)


def get_database_target() -> tuple[str, int | None]:
    return _DATABASE_TARGET_HOST, _DATABASE_TARGET_PORT


def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

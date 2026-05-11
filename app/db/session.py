from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS = 10
_DEFAULT_POSTGRES_POOL_TIMEOUT_SECONDS = 10
_DEFAULT_POSTGRES_POOL_RECYCLE_SECONDS = 1800


def _resolve_database_target(database_url: str) -> tuple[str, int | None]:
    parsed = urlparse(database_url)
    host = (parsed.hostname or "").strip() or "unknown"
    port = parsed.port
    if port is None and parsed.scheme.lower().startswith("postgresql"):
        port = 5432
    return host, port


def _build_engine_options(database_url: str) -> dict[str, object]:
    options: dict[str, object] = {"pool_pre_ping": True}
    try:
        backend_name = (make_url(database_url).get_backend_name() or "").strip().lower()
    except Exception:  # noqa: BLE001
        backend_name = ""
    if backend_name.startswith("postgresql"):
        options["pool_timeout"] = _DEFAULT_POSTGRES_POOL_TIMEOUT_SECONDS
        options["pool_recycle"] = _DEFAULT_POSTGRES_POOL_RECYCLE_SECONDS
        options["connect_args"] = {"connect_timeout": _DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS}
    return options


# future=True style is default on SQLAlchemy 2.x
_ENGINE_OPTIONS = _build_engine_options(settings.database_url)
engine = create_engine(settings.database_url, **_ENGINE_OPTIONS)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
_DATABASE_TARGET_HOST, _DATABASE_TARGET_PORT = _resolve_database_target(settings.database_url)
logger.info(
    "Database target resolved: host=%s, port=%s",
    _DATABASE_TARGET_HOST,
    str(_DATABASE_TARGET_PORT) if _DATABASE_TARGET_PORT is not None else "default",
)
logger.info(
    "Database engine options resolved: pool_pre_ping=%s pool_timeout=%s pool_recycle=%s connect_timeout=%s",
    _ENGINE_OPTIONS.get("pool_pre_ping"),
    _ENGINE_OPTIONS.get("pool_timeout", "default"),
    _ENGINE_OPTIONS.get("pool_recycle", "default"),
    (_ENGINE_OPTIONS.get("connect_args") or {}).get("connect_timeout", "default"),
)


def get_database_target() -> tuple[str, int | None]:
    return _DATABASE_TARGET_HOST, _DATABASE_TARGET_PORT


def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

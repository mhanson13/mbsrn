from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Literal

from app.core.config import get_settings

try:
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - redis optional for local/test
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)


ConsumeRefreshStatus = Literal["ok", "missing", "reused"]
_PRODUCTION_LIKE_ENVS = {"production", "staging"}


@dataclass(frozen=True)
class RefreshTokenState:
    jti: str
    business_id: str
    principal_id: str
    principal_identity_id: str | None
    expires_at_epoch: int


@dataclass(frozen=True)
class RefreshConsumeResult:
    status: ConsumeRefreshStatus
    state: RefreshTokenState | None = None


class SessionStateStore:
    def revoke_jti(self, *, jti: str, expires_at_epoch: int) -> None:
        raise NotImplementedError

    def is_jti_revoked(self, *, jti: str) -> bool:
        raise NotImplementedError

    def put_refresh_state(self, state: RefreshTokenState) -> None:
        raise NotImplementedError

    def consume_refresh_state(self, *, jti: str, revoke_until_epoch: int) -> RefreshConsumeResult:
        raise NotImplementedError

    def set_principal_revoked_after(self, *, business_id: str, principal_id: str, issued_after_epoch: int) -> None:
        raise NotImplementedError

    def get_principal_revoked_after(self, *, business_id: str, principal_id: str) -> int | None:
        raise NotImplementedError

    def set_identity_revoked_after(self, *, identity_id: str, issued_after_epoch: int) -> None:
        raise NotImplementedError

    def get_identity_revoked_after(self, *, identity_id: str) -> int | None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class InMemorySessionStateStore(SessionStateStore):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revoked_jti: dict[str, int] = {}
        self._refresh_states: dict[str, RefreshTokenState] = {}
        self._principal_revoked_after: dict[str, int] = {}
        self._identity_revoked_after: dict[str, int] = {}

    def revoke_jti(self, *, jti: str, expires_at_epoch: int) -> None:
        with self._lock:
            self._revoked_jti[jti] = expires_at_epoch

    def is_jti_revoked(self, *, jti: str) -> bool:
        now = _epoch_now()
        with self._lock:
            exp = self._revoked_jti.get(jti)
            if exp is None:
                return False
            if exp <= now:
                self._revoked_jti.pop(jti, None)
                return False
            return True

    def put_refresh_state(self, state: RefreshTokenState) -> None:
        with self._lock:
            self._refresh_states[state.jti] = state

    def consume_refresh_state(self, *, jti: str, revoke_until_epoch: int) -> RefreshConsumeResult:
        now = _epoch_now()
        with self._lock:
            state = self._refresh_states.pop(jti, None)
            if state is not None:
                self._revoked_jti[jti] = max(revoke_until_epoch, now + 1)
                return RefreshConsumeResult(status="ok", state=state)

            exp = self._revoked_jti.get(jti)
            if exp is not None and exp > now:
                return RefreshConsumeResult(status="reused")
            if exp is not None and exp <= now:
                self._revoked_jti.pop(jti, None)
            return RefreshConsumeResult(status="missing")

    def set_principal_revoked_after(self, *, business_id: str, principal_id: str, issued_after_epoch: int) -> None:
        key = _principal_key(business_id=business_id, principal_id=principal_id)
        with self._lock:
            current = self._principal_revoked_after.get(key, 0)
            self._principal_revoked_after[key] = max(current, issued_after_epoch)

    def get_principal_revoked_after(self, *, business_id: str, principal_id: str) -> int | None:
        key = _principal_key(business_id=business_id, principal_id=principal_id)
        with self._lock:
            value = self._principal_revoked_after.get(key)
            return value if value and value > 0 else None

    def set_identity_revoked_after(self, *, identity_id: str, issued_after_epoch: int) -> None:
        with self._lock:
            current = self._identity_revoked_after.get(identity_id, 0)
            self._identity_revoked_after[identity_id] = max(current, issued_after_epoch)

    def get_identity_revoked_after(self, *, identity_id: str) -> int | None:
        with self._lock:
            value = self._identity_revoked_after.get(identity_id)
            return value if value and value > 0 else None

    def clear(self) -> None:
        with self._lock:
            self._revoked_jti.clear()
            self._refresh_states.clear()
            self._principal_revoked_after.clear()
            self._identity_revoked_after.clear()


class RedisSessionStateStore(SessionStateStore):
    def __init__(self, *, client: Redis, key_prefix: str = "workboots:session") -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")

    def revoke_jti(self, *, jti: str, expires_at_epoch: int) -> None:
        ttl = max(1, expires_at_epoch - _epoch_now())
        self._client.set(self._key_revoked_jti(jti), "1", ex=ttl)

    def is_jti_revoked(self, *, jti: str) -> bool:
        return bool(self._client.exists(self._key_revoked_jti(jti)))

    def put_refresh_state(self, state: RefreshTokenState) -> None:
        ttl = max(1, state.expires_at_epoch - _epoch_now())
        payload = json.dumps(
            {
                "jti": state.jti,
                "business_id": state.business_id,
                "principal_id": state.principal_id,
                "principal_identity_id": state.principal_identity_id,
                "expires_at_epoch": state.expires_at_epoch,
            },
            separators=(",", ":"),
        )
        self._client.set(self._key_refresh_state(state.jti), payload, ex=ttl)

    def consume_refresh_state(self, *, jti: str, revoke_until_epoch: int) -> RefreshConsumeResult:
        key = self._key_refresh_state(jti)
        payload = self._client.getdel(key)  # atomic consume for replay protection
        if payload is not None:
            ttl = max(1, revoke_until_epoch - _epoch_now())
            self._client.set(self._key_revoked_jti(jti), "1", ex=ttl)
            state = self._decode_refresh_state(payload)
            return RefreshConsumeResult(status="ok", state=state)

        if self._client.exists(self._key_revoked_jti(jti)):
            return RefreshConsumeResult(status="reused")
        return RefreshConsumeResult(status="missing")

    def set_principal_revoked_after(self, *, business_id: str, principal_id: str, issued_after_epoch: int) -> None:
        key = self._key_principal_revoked_after(business_id=business_id, principal_id=principal_id)
        current = self._client.get(key)
        current_int = int(current) if current else 0
        if issued_after_epoch > current_int:
            self._client.set(key, str(issued_after_epoch))

    def get_principal_revoked_after(self, *, business_id: str, principal_id: str) -> int | None:
        key = self._key_principal_revoked_after(business_id=business_id, principal_id=principal_id)
        value = self._client.get(key)
        if not value:
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None

    def set_identity_revoked_after(self, *, identity_id: str, issued_after_epoch: int) -> None:
        key = self._key_identity_revoked_after(identity_id=identity_id)
        current = self._client.get(key)
        current_int = int(current) if current else 0
        if issued_after_epoch > current_int:
            self._client.set(key, str(issued_after_epoch))

    def get_identity_revoked_after(self, *, identity_id: str) -> int | None:
        key = self._key_identity_revoked_after(identity_id=identity_id)
        value = self._client.get(key)
        if not value:
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None

    def clear(self) -> None:
        # Keep production-safe: no broad Redis scans from app runtime.
        return None

    def _key_revoked_jti(self, jti: str) -> str:
        return f"{self._key_prefix}:revoked:jti:{jti}"

    def _key_refresh_state(self, jti: str) -> str:
        return f"{self._key_prefix}:refresh:active:{jti}"

    def _key_principal_revoked_after(self, *, business_id: str, principal_id: str) -> str:
        return f"{self._key_prefix}:revoked-after:principal:{business_id}:{principal_id}"

    def _key_identity_revoked_after(self, *, identity_id: str) -> str:
        return f"{self._key_prefix}:revoked-after:identity:{identity_id}"

    def _decode_refresh_state(self, payload: str | bytes) -> RefreshTokenState:
        raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        parsed = json.loads(raw)
        return RefreshTokenState(
            jti=str(parsed["jti"]),
            business_id=str(parsed["business_id"]),
            principal_id=str(parsed["principal_id"]),
            principal_identity_id=(
                str(parsed["principal_identity_id"]) if parsed.get("principal_identity_id") is not None else None
            ),
            expires_at_epoch=int(parsed["expires_at_epoch"]),
        )


_SESSION_STATE_STORE: SessionStateStore | None = None
_SESSION_STATE_STORE_SIG: tuple[str, str, str, str] | None = None


def get_session_state_store() -> SessionStateStore:
    global _SESSION_STATE_STORE, _SESSION_STATE_STORE_SIG
    settings = get_settings()
    sig = (
        settings.session_state_backend,
        settings.redis_url or "",
        settings.environment.strip().lower(),
        str(settings.session_state_fail_open).lower(),
    )
    if _SESSION_STATE_STORE is not None and _SESSION_STATE_STORE_SIG == sig:
        return _SESSION_STATE_STORE

    _SESSION_STATE_STORE = _build_store()
    _SESSION_STATE_STORE_SIG = sig
    return _SESSION_STATE_STORE


def _build_store() -> SessionStateStore:
    settings = get_settings()
    backend = settings.session_state_backend
    redis_url = (settings.redis_url or "").strip()
    env = settings.environment.strip().lower()
    app_env = settings.app_env.strip().lower()
    fail_open = settings.session_state_fail_open
    allow_inmemory_fallback = settings.session_state_allow_inmemory_fallback

    logger.info(
        "session_state_backend_init backend=%s env=%s app_env=%s redis_configured=%s fail_open=%s "
        "allow_inmemory_fallback=%s",
        backend,
        env,
        app_env,
        bool(redis_url),
        fail_open,
        allow_inmemory_fallback,
    )

    if backend not in {"auto", "inmemory", "redis"}:
        raise RuntimeError("SESSION_STATE_BACKEND must be one of: auto, inmemory, redis.")

    if backend == "inmemory":
        return _select_inmemory_store(
            configured_backend=backend,
            env=env,
            app_env=app_env,
            redis_configured=bool(redis_url),
            fail_open=fail_open,
            allow_inmemory_fallback=allow_inmemory_fallback,
            reason="explicit_inmemory_backend",
            fallback_occurred=False,
        )

    if backend == "redis" and not redis_url:
        raise RuntimeError("SESSION_STATE_BACKEND=redis requires REDIS_URL.")

    if backend == "redis" or (backend == "auto" and redis_url):
        if Redis is None:
            if backend == "auto":
                return _select_inmemory_store(
                    configured_backend=backend,
                    env=env,
                    app_env=app_env,
                    redis_configured=bool(redis_url),
                    fail_open=fail_open,
                    allow_inmemory_fallback=allow_inmemory_fallback,
                    reason="redis_client_unavailable_auto_fallback",
                    fallback_occurred=True,
                )
            raise RuntimeError("Redis backend configured for session state but redis client is unavailable.")
        try:
            client = Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            _emit_backend_selection_event(
                configured_backend=backend,
                selected_backend="redis",
                env=env,
                app_env=app_env,
                redis_configured=bool(redis_url),
                fail_open=fail_open,
                allow_inmemory_fallback=allow_inmemory_fallback,
                reason="redis_connected",
                fallback_occurred=False,
                degraded_mode=False,
                level=logging.INFO,
            )
            return RedisSessionStateStore(client=client)
        except RedisError as exc:
            if fail_open:
                return _select_inmemory_store(
                    configured_backend=backend,
                    env=env,
                    app_env=app_env,
                    redis_configured=bool(redis_url),
                    fail_open=fail_open,
                    allow_inmemory_fallback=allow_inmemory_fallback,
                    reason=f"redis_unavailable_fail_open:{exc.__class__.__name__}",
                    fallback_occurred=True,
                )
            logger.error(
                "Redis session state unavailable; fail-open disabled. backend=%s env=%s",
                backend,
                env,
            )
            raise RuntimeError("Unable to initialize Redis session state store.") from exc

    return _select_inmemory_store(
        configured_backend=backend,
        env=env,
        app_env=app_env,
        redis_configured=bool(redis_url),
        fail_open=fail_open,
        allow_inmemory_fallback=allow_inmemory_fallback,
        reason="redis_not_configured_auto_fallback",
        fallback_occurred=True,
    )


def _select_inmemory_store(
    *,
    configured_backend: str,
    env: str,
    app_env: str,
    redis_configured: bool,
    fail_open: bool,
    allow_inmemory_fallback: bool,
    reason: str,
    fallback_occurred: bool,
) -> InMemorySessionStateStore:
    degraded_mode = env in _PRODUCTION_LIKE_ENVS
    risk_level = "high" if degraded_mode else "normal"
    if degraded_mode and not allow_inmemory_fallback:
        _emit_backend_selection_event(
            configured_backend=configured_backend,
            selected_backend="none",
            env=env,
            app_env=app_env,
            redis_configured=redis_configured,
            fail_open=fail_open,
            allow_inmemory_fallback=allow_inmemory_fallback,
            reason=f"{reason}:blocked_by_session_state_allow_inmemory_fallback",
            fallback_occurred=fallback_occurred,
            degraded_mode=True,
            level=logging.ERROR,
        )
        raise RuntimeError(
            "Session state backend resolved to in-memory in production/staging while "
            "SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false."
        )

    level = logging.ERROR if degraded_mode else logging.WARNING
    _emit_backend_selection_event(
        configured_backend=configured_backend,
        selected_backend="inmemory",
        env=env,
        app_env=app_env,
        redis_configured=redis_configured,
        fail_open=fail_open,
        allow_inmemory_fallback=allow_inmemory_fallback,
        reason=reason,
        fallback_occurred=fallback_occurred,
        degraded_mode=degraded_mode,
        level=level,
    )
    if degraded_mode:
        logger.error(
            "Session state backend resolved to in-memory store in production/staging. "
            "This is degraded for multi-replica production runtime. "
            "risk_level=%s fallback_occurred=%s reason=%s",
            risk_level,
            fallback_occurred,
            reason,
        )
    else:
        logger.warning("Session state backend using in-memory store (single-instance scope).")
    return InMemorySessionStateStore()


def _emit_backend_selection_event(
    *,
    configured_backend: str,
    selected_backend: str,
    env: str,
    app_env: str,
    redis_configured: bool,
    fail_open: bool,
    allow_inmemory_fallback: bool,
    reason: str,
    fallback_occurred: bool,
    degraded_mode: bool,
    level: int,
) -> None:
    risk_level = "high" if degraded_mode else "normal"
    logger.log(
        level,
        "session_state_backend_selection event=session_state_backend_selection "
        "configured_backend=%s selected_backend=%s reason=%s env=%s app_env=%s redis_configured=%s "
        "fail_open=%s allow_inmemory_fallback=%s fallback_occurred=%s degraded_mode=%s risk_level=%s",
        configured_backend,
        selected_backend,
        reason,
        env,
        app_env,
        redis_configured,
        fail_open,
        allow_inmemory_fallback,
        fallback_occurred,
        degraded_mode,
        risk_level,
    )


def _epoch_now() -> int:
    return int(time.time())


def _principal_key(*, business_id: str, principal_id: str) -> str:
    return f"{business_id}:{principal_id}"


def dt_to_epoch_seconds(value: datetime) -> int:
    if value.tzinfo is None:
        return int(value.replace(tzinfo=timezone.utc).timestamp())
    return int(value.astimezone(timezone.utc).timestamp())

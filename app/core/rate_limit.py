from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time

from app.core.config import get_settings

try:
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - redis optional for local/test
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


@dataclass
class _RateLimitBucket:
    window_start_epoch: float
    count: int


class RateLimiter:
    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    """Small fixed-window in-memory limiter for local/dev fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _RateLimitBucket] = {}

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or (now - bucket.window_start_epoch) >= window_seconds:
                self._buckets[key] = _RateLimitBucket(window_start_epoch=now, count=1)
                return RateLimitDecision(allowed=True, retry_after_seconds=0)

            if bucket.count >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket.window_start_epoch)))
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

            bucket.count += 1
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


class RedisRateLimiter(RateLimiter):
    """Fixed-window Redis limiter for distributed multi-pod enforcement."""

    def __init__(
        self,
        *,
        client: Redis,
        key_prefix: str = "workboots:ratelimit",
        fail_open: bool = True,
    ) -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")
        self._fail_open = fail_open

    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

        now_epoch = int(time.time())
        window_bucket = now_epoch // window_seconds
        bucket_key = f"{self._key_prefix}:{key}:{window_bucket}"

        try:
            with self._client.pipeline() as pipe:
                pipe.incr(bucket_key)
                pipe.ttl(bucket_key)
                count, ttl = pipe.execute()

            count_int = int(count)
            ttl_int = int(ttl)
            if count_int == 1:
                self._client.expire(bucket_key, window_seconds + 1)
                ttl_int = window_seconds + 1

            if count_int > limit:
                retry_after = max(1, ttl_int if ttl_int > 0 else 1)
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        except RedisError:
            if self._fail_open:
                logger.warning("Redis rate limiter unavailable; fail-open enabled.")
                return RateLimitDecision(allowed=True, retry_after_seconds=0)
            logger.error("Redis rate limiter unavailable; fail-open disabled.")
            return RateLimitDecision(allowed=False, retry_after_seconds=max(1, window_seconds))

    def clear(self) -> None:
        # Keep runtime-safe: no broad Redis scans from application code.
        return None


_RATE_LIMITER: RateLimiter | None = None
_RATE_LIMITER_SIG: tuple[str, str, str, str] | None = None


def get_rate_limiter() -> RateLimiter:
    global _RATE_LIMITER, _RATE_LIMITER_SIG
    settings = get_settings()
    sig = (
        settings.rate_limit_backend,
        settings.redis_url or "",
        settings.environment.strip().lower(),
        str(settings.rate_limit_fail_open).lower(),
    )
    if _RATE_LIMITER is not None and _RATE_LIMITER_SIG == sig:
        return _RATE_LIMITER

    _RATE_LIMITER = _build_rate_limiter()
    _RATE_LIMITER_SIG = sig
    return _RATE_LIMITER


def _build_rate_limiter() -> RateLimiter:
    settings = get_settings()
    backend = settings.rate_limit_backend
    redis_url = (settings.redis_url or "").strip()
    env = settings.environment.strip().lower()
    fail_open = settings.rate_limit_fail_open

    logger.info(
        "rate_limit_backend_init backend=%s env=%s redis_configured=%s fail_open=%s",
        backend,
        env,
        bool(redis_url),
        fail_open,
    )

    if backend not in {"auto", "inmemory", "redis"}:
        raise RuntimeError("RATE_LIMIT_BACKEND must be one of: auto, inmemory, redis.")

    if backend == "inmemory":
        logger.warning("Rate limiter using in-memory backend (single-instance scope).")
        return InMemoryRateLimiter()

    if backend == "redis" and not redis_url:
        raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL.")

    if backend == "redis" or (backend == "auto" and redis_url):
        if Redis is None:
            if backend == "auto":
                logger.warning("Redis client unavailable with RATE_LIMIT_BACKEND=auto; using in-memory backend.")
                return InMemoryRateLimiter()
            raise RuntimeError("Redis backend configured for rate limiting but redis client is unavailable.")
        try:
            client = Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            logger.info("Rate limiter initialized with Redis backend.")
            return RedisRateLimiter(client=client, fail_open=fail_open)
        except RedisError as exc:
            if fail_open:
                logger.warning(
                    "Redis rate limiter unavailable; fail-open enabled. Falling back to in-memory backend. error=%s",
                    exc,
                )
                return InMemoryRateLimiter()
            logger.error(
                "Redis rate limiter unavailable; fail-open disabled. backend=%s env=%s",
                backend,
                env,
            )
            raise RuntimeError("Unable to initialize Redis rate limiter.") from exc

    logger.warning("Rate limiter defaulted to in-memory backend (Redis not configured).")
    return InMemoryRateLimiter()

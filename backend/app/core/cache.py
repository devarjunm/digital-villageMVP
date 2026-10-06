"""Redis-backed cache with a safe in-process fallback.

Rules:
  * Only public or short-lived derived data is cached (weather, market, catalogs,
    rate-limit counters, job status). User-private data is never cached here.
  * If Redis is unreachable the cache degrades to a bounded in-process dict and
    reports `available=False` in health output — the application keeps working
    single-node, and operators can see the degradation.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard
    import redis as redis_lib
except Exception:  # pragma: no cover
    redis_lib = None  # type: ignore[assignment]


class _MemoryCache:
    """Tiny TTL dict used when Redis is not configured/reachable (dev, tests)."""

    def __init__(self, max_entries: int = 2048) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._max = max_entries

    def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at and expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl: int | None) -> None:
        if len(self._data) >= self._max:
            # drop the oldest 10% — deterministic and cheap
            for k in sorted(self._data, key=lambda k: self._data[k][0])[: self._max // 10]:
                self._data.pop(k, None)
        self._data[key] = (time.time() + ttl if ttl else 0.0, value)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def incr(self, key: str, ttl: int | None) -> int:
        current = int(self.get(key) or 0) + 1
        item = self._data.get(key)
        expires_at = item[0] if item else (time.time() + ttl if ttl else 0.0)
        self._data[key] = (expires_at, str(current))
        return current

    def ttl(self, key: str) -> int:
        item = self._data.get(key)
        if not item or not item[0]:
            return -1
        return max(0, int(item[0] - time.time()))

    def flush_prefix(self, prefix: str) -> int:
        keys = [k for k in self._data if k.startswith(prefix)]
        for k in keys:
            self._data.pop(k, None)
        return len(keys)


class CacheClient:
    """Facade over Redis with graceful degradation and JSON helpers."""

    def __init__(self, url: str | None = None, *, force_memory: bool = False) -> None:
        self._memory = _MemoryCache()
        self._redis: Any = None
        self._url = url or settings.redis_url
        self._forced_memory = force_memory
        if not force_memory and redis_lib is not None:
            try:
                client = redis_lib.Redis.from_url(
                    self._url, decode_responses=True, socket_connect_timeout=1, socket_timeout=2
                )
                client.ping()
                self._redis = client
            except Exception as exc:
                logger.warning(
                    "redis_unavailable_falling_back_to_memory",
                    extra={"extra_fields": {"error": str(exc)}},
                )
                self._redis = None

    # ---------------------------------------------------------------- state
    @property
    def available(self) -> bool:
        return self._redis is not None

    @property
    def backend(self) -> str:
        return "redis" if self.available else "memory"

    def health(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "backend": "memory", "detail": "redis not reachable"}
        try:
            self._redis.ping()
            return {"available": True, "backend": "redis"}
        except Exception as exc:
            return {"available": False, "backend": "redis", "detail": str(exc)}

    # ------------------------------------------------------------ primitive
    def get(self, key: str) -> str | None:
        if self.available:
            try:
                return self._redis.get(key)
            except Exception:
                pass
        return self._memory.get(key)

    def set(self, key: str, value: str, ttl: int | None = 300) -> None:
        if self.available:
            try:
                self._redis.set(key, value, ex=ttl)
                return
            except Exception:
                pass
        self._memory.set(key, value, ttl)

    def delete(self, key: str) -> None:
        if self.available:
            with contextlib.suppress(Exception):
                self._redis.delete(key)
        self._memory.delete(key)

    def incr(self, key: str, ttl: int | None = None) -> int:
        if self.available:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(key)
                if ttl:
                    pipe.expire(key, ttl)
                value, _ = pipe.execute()
                return int(value)
            except Exception:
                pass
        return self._memory.incr(key, ttl)

    def get_int(self, key: str) -> int:
        raw = self.get(key)
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    def ttl(self, key: str) -> int:
        if self.available:
            try:
                return int(self._redis.ttl(key))
            except Exception:
                pass
        return self._memory.ttl(key)

    def flush_prefix(self, prefix: str) -> int:
        if self.available:
            try:
                count = 0
                for key in self._redis.scan_iter(match=f"{prefix}*", count=500):
                    self._redis.delete(key)
                    count += 1
                return count
            except Exception:
                pass
        return self._memory.flush_prefix(prefix)

    # ----------------------------------------------------------- json layer
    def get_json(self, key: str) -> Any | None:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl: int | None = 300) -> None:
        self.set(key, json.dumps(value, default=str), ttl)

    # -------------------------------------------------------- counter logic
    def rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """Fixed-window counter. Returns (allowed, remaining, retry_after)."""
        count = self.incr(key, ttl=window_seconds)
        remaining = max(0, limit - count)
        retry_after = max(1, self.ttl(key)) if count > limit else 0
        return count <= limit, remaining, retry_after


_cache: CacheClient | None = None


def get_cache() -> CacheClient:
    global _cache
    if _cache is None:
        _cache = CacheClient()
    return _cache


def reset_cache_for_tests(url: str | None = None, *, memory: bool = False) -> CacheClient:
    global _cache
    _cache = CacheClient(url, force_memory=memory)
    return _cache

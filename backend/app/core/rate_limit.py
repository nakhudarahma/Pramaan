"""Small in-process sliding-window rate limiter for public endpoints.

For multi-instance deployments replace the store with Redis.  The interface is
intentionally simple so a shared store can be dropped in later.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from app.config import get_settings
from app.core.exceptions import RateLimitError


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            cutoff = now - window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            # Bound memory in a long-running process.
            if len(self._events) > 10_000:
                stale = [k for k, v in self._events.items() if not v or v[-1] < cutoff]
                for k in stale:
                    self._events.pop(k, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()


def client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return host or "unknown"


def rate_limit(scope: str, limit_getter: Callable[[], int], window_seconds: int = 60):
    """FastAPI dependency factory."""

    async def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = limit_getter()
        if limit <= 0:
            return
        key = f"{scope}:{client_key(request)}"
        if not limiter.allow(key, limit, window_seconds):
            raise RateLimitError(
                "Too many requests. Please try again shortly.",
                details={"scope": scope, "retry_after_seconds": window_seconds},
            )

    return dependency


def _settings() -> object:
    return get_settings()

"""Simple in-memory rate limiting utilities."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    """Per-client fixed-window rate limiter using deque timestamps."""

    def __init__(self, requests_per_window: int, window_seconds: int) -> None:
        self._requests = max(requests_per_window, 1)
        self._window = max(window_seconds, 1)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, client_key: str) -> bool:
        now = time.time()
        with self._lock:
            dq = self._hits[client_key]
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self._requests:
                return False
            dq.append(now)
            return True


def build_rate_limiter_dependency(
    limiter: InMemoryRateLimiter,
    enabled: bool,
) -> Callable[[Request], None]:
    def _dependency(request: Request) -> None:
        if not enabled:
            return
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return _dependency

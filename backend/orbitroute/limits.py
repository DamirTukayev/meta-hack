"""Small in-memory sliding-window rate limiter for the public endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_events: int, window_s: float, clock=time.monotonic):
        self.max_events, self.window_s, self._clock = max_events, window_s, clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> float:
        """Record an event for `key`. Returns 0 if allowed, else the seconds to wait before retrying."""
        now = self._clock()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.max_events:
                return self.window_s - (now - q[0])
            q.append(now)
            return 0.0

"""Per-user limit of questions per hour: every AI answer costs money."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, per_hour: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_hour = per_hour
        self.clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> float:
        """Records a question and returns 0, or returns the seconds to wait (nothing recorded)."""
        now = self.clock()
        hits = self._hits[user_id]
        while hits and hits[0] <= now - 3600:
            hits.popleft()
        if len(hits) >= self.per_hour:
            return hits[0] + 3600 - now
        hits.append(now)
        return 0.0

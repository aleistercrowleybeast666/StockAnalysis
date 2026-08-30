from __future__ import annotations

import threading
import time
from collections.abc import Callable


class DomainRateLimiter:
    def __init__(
        self,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = max(0.0, interval_seconds)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    def wait(self, domain: str) -> None:
        with self._lock:
            now = self._clock()
            previous = self._last_request.get(domain)
            scheduled = (
                max(now, previous + self._interval)
                if previous is not None
                else now
            )
            self._last_request[domain] = scheduled
        remaining = scheduled - now
        if remaining > 0:
            self._sleep(remaining)

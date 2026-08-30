from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def Retry_Execute(
    operation: Callable[[], T],
    should_retry: Callable[[Exception], bool],
    attempts: int = 3,
    base_delay: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            last_error = error
            if attempt + 1 >= attempts or not should_retry(error):
                raise
            sleep(base_delay * (2**attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry operation did not run")


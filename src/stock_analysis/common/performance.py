from __future__ import annotations

import threading
from collections import Counter
from typing import Any


class RequestStatistics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._elapsed_seconds = 0.0
        self._retry_count = 0
        self._direct_requests = 0
        self._proxy_requests = 0
        self._by_domain: Counter[str] = Counter()
        self._by_endpoint: Counter[str] = Counter()

    def Request_Record(self, domain: str, endpoint: str, mode: str) -> None:
        with self._lock:
            self._total_requests += 1
            self._by_domain[domain] += 1
            self._by_endpoint[endpoint] += 1
            if mode == "direct":
                self._direct_requests += 1
            else:
                self._proxy_requests += 1

    def Success_Record(self, elapsed_seconds: float = 0.0) -> None:
        with self._lock:
            self._successful_requests += 1
            self._elapsed_seconds += max(0.0, elapsed_seconds)

    def Failure_Record(self, elapsed_seconds: float = 0.0) -> None:
        with self._lock:
            self._failed_requests += 1
            self._elapsed_seconds += max(0.0, elapsed_seconds)

    def Retry_Record(self) -> None:
        with self._lock:
            self._retry_count += 1

    def Snapshot_Get(self) -> dict[str, Any]:
        with self._lock:
            return {
                "http_requests": self._total_requests,
                "http_successes": self._successful_requests,
                "http_failures": self._failed_requests,
                "http_elapsed_seconds": round(self._elapsed_seconds, 3),
                "retries": self._retry_count,
                "direct_requests": self._direct_requests,
                "proxy_requests": self._proxy_requests,
                "requests_by_domain": dict(self._by_domain),
                "requests_by_endpoint": dict(self._by_endpoint),
            }


def Statistics_Merge(items: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "http_requests": 0,
        "http_successes": 0,
        "http_failures": 0,
        "http_elapsed_seconds": 0.0,
        "retries": 0,
        "direct_requests": 0,
        "proxy_requests": 0,
        "requests_by_domain": {},
        "requests_by_endpoint": {},
    }
    for item in items:
        for key in (
            "http_requests",
            "http_successes",
            "http_failures",
            "retries",
            "direct_requests",
            "proxy_requests",
        ):
            result[key] += int(item.get(key, 0))
        result["http_elapsed_seconds"] += float(item.get("http_elapsed_seconds", 0.0))
        for group in ("requests_by_domain", "requests_by_endpoint"):
            target = result[group]
            for name, count in item.get(group, {}).items():
                target[name] = target.get(name, 0) + int(count)
    result["http_elapsed_seconds"] = round(result["http_elapsed_seconds"], 3)
    return result

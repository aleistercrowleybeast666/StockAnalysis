from __future__ import annotations

import threading

import httpx
import pytest

import stock_analysis.sources.base as base_module
from stock_analysis.common.rate_limit import DomainRateLimiter
from stock_analysis.common.retry import Retry_Execute
from stock_analysis.domain.enums import NetworkMode
from stock_analysis.sources.base import HttpJsonClient, SourceError


def test_rate_limiter_releases_lock_before_different_hosts_sleep() -> None:
    barrier = threading.Barrier(2)
    limiter = DomainRateLimiter(
        1.0,
        clock=lambda: 0.0,
        sleep=lambda _delay: barrier.wait(timeout=2),
    )
    limiter.wait("one.example")
    limiter.wait("two.example")
    errors: list[Exception] = []

    def wait(domain: str) -> None:
        try:
            limiter.wait(domain)
        except Exception as error:  # pragma: no cover - assertion below exposes it
            errors.append(error)

    threads = [
        threading.Thread(target=wait, args=("one.example",)),
        threading.Thread(target=wait, args=("two.example",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert not errors
    assert all(not thread.is_alive() for thread in threads)


def test_network_modes_build_expected_direct_and_proxy_order() -> None:
    cases = [
        (NetworkMode.DIRECT, True, ["direct"]),
        (NetworkMode.SYSTEM_PROXY, True, ["proxy"]),
        (NetworkMode.DOMESTIC_DIRECT, True, ["direct", "proxy"]),
        (NetworkMode.DOMESTIC_DIRECT, False, ["proxy"]),
    ]
    for mode, domestic, expected in cases:
        client = HttpJsonClient(
            "test", network_mode=mode, domestic=domestic, request_interval=0
        )
        assert [name for name, _client in client._clients] == expected
        client.close()


def test_endpoint_failure_does_not_disable_later_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal actual_requests
        actual_requests += 1
        return httpx.Response(503, json={"error": "temporarily unavailable"})

    client = HttpJsonClient(
        "test-source",
        network_mode=NetworkMode.DIRECT,
        request_interval=0,
    )
    for _mode, existing in client._clients:
        existing.close()
    client._clients = [
        (
            "direct",
            httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
        )
    ]

    def retry_without_sleep(operation, should_retry, attempts=3, base_delay=0.4):
        return Retry_Execute(
            operation,
            should_retry,
            attempts=attempts,
            base_delay=base_delay,
            sleep=lambda _delay: None,
        )

    monkeypatch.setattr(base_module, "Retry_Execute", retry_without_sleep)
    with pytest.raises(SourceError, match="暂时不可用|网络连接失败"):
        client.RequestJson(
            "https://example.test/api",
            request_id="first",
            endpoint_key="flow-full-a-share",
        )
    assert actual_requests == 3

    with pytest.raises(SourceError, match="暂时不可用|网络连接失败"):
        client.RequestJson(
            "https://example.test/api",
            request_id="second",
            endpoint_key="flow-full-a-share",
        )
    assert actual_requests == 6
    statistics = client.Statistics_Get()
    assert "circuit_breaks" not in statistics
    assert "negative_cache_hits" not in statistics
    client.close()

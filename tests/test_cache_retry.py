from __future__ import annotations

from pathlib import Path

import pytest

from stock_analysis.common.paths import Paths_GetRuntimePaths
from stock_analysis.common.retry import Retry_Execute
from stock_analysis.domain.enums import Market
from stock_analysis.pipeline.fetch import FetchCoordinator
from stock_analysis.sources.fixture import FixtureSource


class _CountingFixture(FixtureSource):
    def __init__(self) -> None:
        super().__init__()
        self.financial_calls = 0

    def Financials_Fetch(self, security, years):
        self.financial_calls += 1
        return super().Financials_Fetch(security, years)


def test_run_local_request_reuse_has_no_persistent_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STOCK_ANALYSIS_HOME", str(tmp_path / "runtime"))
    source = _CountingFixture()
    security = source.SecurityList_Fetch(Market.A_SHARE)[0]
    coordinator = FetchCoordinator(source)
    first = coordinator.Financials_Fetch(security, {2025})
    second = coordinator.Financials_Fetch(security, {2025})
    paths = Paths_GetRuntimePaths()

    assert first is second
    assert source.financial_calls == 1
    assert coordinator.reuse_count == 1
    assert not hasattr(paths, "cache_root")
    assert not hasattr(paths, "database_file")
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_retry_is_bounded_and_only_for_retryable_errors() -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def operation() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("temporary")
        return "ok"

    assert Retry_Execute(
        operation,
        lambda error: isinstance(error, TimeoutError),
        attempts=3,
        base_delay=0.1,
        sleep=sleeps.append,
    ) == "ok"
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]

    with pytest.raises(ValueError):
        Retry_Execute(
            lambda: (_ for _ in ()).throw(ValueError("bad schema")),
            lambda error: isinstance(error, TimeoutError),
            sleep=lambda _delay: None,
        )

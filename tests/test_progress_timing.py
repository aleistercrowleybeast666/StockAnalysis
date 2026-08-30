from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, MarketScopeMode, PipelineRunResult
from stock_analysis.domain.models import Security
from stock_analysis.pipeline.runner import PipelineRunner
from stock_analysis.sources.fixture import FixtureSource


class TimedFixtureSource(FixtureSource):
    """Use long deterministic delays so coverage tracing cannot skew the curve."""

    def Quotes_Fetch(self, securities: Sequence[Security]):
        time.sleep(0.64)
        return super().Quotes_Fetch(securities)

    def Financials_Fetch(self, security: Security, years: set[int]):
        time.sleep(0.3)
        return super().Financials_Fetch(security, years)

    def IPO_Fetch(self, security: Security):
        time.sleep(0.2)
        return super().IPO_Fetch(security)

    def BlockTrade_Fetch(self, security: Security, year: int):
        time.sleep(0.07)
        return super().BlockTrade_Fetch(security, year)

    def Flow_Fetch(self, security: Security):
        time.sleep(0.28)
        return super().Flow_Fetch(security)


def test_weighted_progress_tracks_injected_wall_clock_midpoint(
    tmp_path: Path,
) -> None:
    events = []

    def progress_capture(progress) -> None:
        events.append((time.perf_counter(), progress))

    summary = PipelineRunner(
        AppConfig(
            financial_year=2025,
            trading_year=2025,
            markets=[Market.A_SHARE, Market.HK],
            a_share_scope_mode=MarketScopeMode.ALL,
            hk_scope_mode=MarketScopeMode.ALL,
            output_directory=str(tmp_path),
            fixture_mode=True,
            concurrency=1,
            request_interval=0,
        ),
        TimedFixtureSource(),
        progress_capture,
    ).run(tmp_path / "timed-progress.xlsx")

    assert summary.result is PipelineRunResult.SUCCESS
    assert events[0][1].stage == "证券范围"
    assert events[0][1].overall_total == 0

    planned = [(stamp, item) for stamp, item in events if item.overall_total > 0]
    start_time = planned[0][0]
    finish_time = planned[-1][0]
    midpoint = start_time + (finish_time - start_time) / 2
    midpoint_item = max(
        (event for event in planned if event[0] <= midpoint),
        key=lambda event: event[0],
    )[1]
    midpoint_ratio = midpoint_item.overall_completed / midpoint_item.overall_total

    assert 0.40 <= midpoint_ratio <= 0.60
    ratios = [item.overall_completed / item.overall_total for _, item in planned]
    assert ratios == sorted(ratios)
    assert max(
        following - current
        for current, following in zip(ratios, ratios[1:], strict=False)
    ) <= 0.1
    assert ratios[-1] == 1.0

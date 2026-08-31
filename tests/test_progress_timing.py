from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, MarketScopeMode, PipelineRunResult
from stock_analysis.domain.models import BatchProgressUpdate, Security
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


class BatchProgressFixtureSource(FixtureSource):
    def BlockTrades_Fetch(
        self, securities: Sequence[Security], year: int, progress_callback=None
    ):
        results = {
            security.key: self.BlockTrade_Fetch(security, year)
            for security in securities
        }
        for completed in range(1, 6):
            if progress_callback is not None:
                progress_callback(
                    BatchProgressUpdate(
                        stage_fraction=completed / 5,
                        completed=completed,
                        total=5,
                        current_company="fixture batch",
                        message=f"fixture request batch {completed}/5",
                    )
                )
        return results


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
    total_duration = finish_time - start_time
    seventy_stamp = next(
        stamp
        for stamp, item in planned
        if item.overall_completed / item.overall_total >= 0.70
    )
    ninety_stamp = next(
        stamp
        for stamp, item in planned
        if item.overall_completed / item.overall_total >= 0.90
    )
    assert (seventy_stamp - start_time) / total_duration >= 0.30
    assert (finish_time - ninety_stamp) / total_duration <= 0.30


def test_real_batch_updates_advance_determinate_progress(tmp_path: Path) -> None:
    events = []
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
        BatchProgressFixtureSource(),
        events.append,
    ).run(tmp_path / "batch-progress.xlsx")

    assert summary.result is PipelineRunResult.SUCCESS
    batches = [
        item
        for item in events
        if item.current_company == "fixture batch"
    ]
    assert [item.completed for item in batches] == [1, 2, 3, 4, 5]
    assert all(item.total == 5 for item in batches)
    ratios = [item.overall_completed / item.overall_total for item in batches]
    assert ratios == sorted(ratios)
    assert len(set(ratios)) == 5


def test_top_n_work_plan_uses_quote_batches_and_dynamic_archive_scan_work(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        financial_year=2025,
        trading_year=2025,
        markets=[Market.A_SHARE, Market.HK],
        a_share_scope_mode=MarketScopeMode.TOP_MARKET_CAP,
        a_share_top_n=3,
        hk_scope_mode=MarketScopeMode.TOP_MARKET_CAP,
        hk_top_n=3,
        output_directory=str(tmp_path),
        fixture_mode=False,
    )
    universe = [
        *[
            Security(Market.A_SHARE, "SSE", f"{600000 + index:06d}", f"A{index}")
            for index in range(5_551)
        ],
        *[
            Security(Market.HK, "HKEX", f"{index + 1:05d}", f"H{index}")
            for index in range(2_751)
        ],
    ]
    runner = PipelineRunner(config, FixtureSource())

    runner._WorkPlan_Initialize(universe)  # noqa: SLF001
    totals = runner._overall_work_totals  # noqa: SLF001

    assert 20_000 < totals["获取行情与市值"] < 50_000
    assert totals["年度全市场大宗交易"] > totals["年度财务"]
    assert "补全入选公司行情" in totals
    assert "证券范围" not in totals
    assert sum(totals.values()) == runner._OVERALL_WORK_UNITS  # noqa: SLF001

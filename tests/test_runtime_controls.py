from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from stock_analysis.app.task_manager import _MarketScope_DescriptionGet
from stock_analysis.common.logging import Logging_Close, Logging_Configure
from stock_analysis.common.paths import Resources_GetRoot
from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, MarketScopeMode, PipelineRunResult
from stock_analysis.domain.models import FinancialPeriod
from stock_analysis.pipeline.merge import Period_Select
from stock_analysis.pipeline.runner import PipelineRunner
from stock_analysis.sources.fixture import FixtureSource


def test_period_selection_uses_latest_matching_report() -> None:
    early = FinancialPeriod("A股:1", date(2024, 6, 30), 2024, date(2024, 8, 1), "CNY", 1, 1, 1, 1)
    annual = FinancialPeriod("A股:1", date(2024, 12, 31), 2024, date(2025, 4, 1), "CNY", 2, 1, 1, 1)
    assert Period_Select([early, annual], 2024) is annual
    assert Period_Select([annual], 2023) is None


def test_all_scope_log_description_does_not_show_inactive_top_n() -> None:
    assert _MarketScope_DescriptionGet(MarketScopeMode.ALL, 100) == "全部公司"
    assert _MarketScope_DescriptionGet(MarketScopeMode.TOP_MARKET_CAP, 100) == (
        "总市值前 100 家"
    )


def test_cancelled_pipeline_stops_without_export(tmp_path: Path) -> None:
    runner = PipelineRunner(
        AppConfig(
            financial_year=2025,
            trading_year=2025,
            markets=[Market.A_SHARE],
            a_share_scope_mode=MarketScopeMode.TOP_MARKET_CAP,
            a_share_top_n=2,
            output_directory=str(tmp_path),
            fixture_mode=True,
            request_interval=0,
        ),
        FixtureSource(),
    )
    runner.cancel()
    summary = runner.run(tmp_path / "should-not-exist.xlsx")
    assert summary.result is PipelineRunResult.CANCELLED
    assert summary.output_path is None
    assert not (tmp_path / "should-not-exist.xlsx").exists()


def test_logging_writes_and_releases_file(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "test.log"
    logger = Logging_Configure(log_path)
    logger.info("fixture pipeline started")
    Logging_Close(logger)
    assert "fixture pipeline started" in log_path.read_text(encoding="utf-8")
    assert not [handler for handler in logger.handlers if isinstance(handler, logging.FileHandler)]
    log_path.unlink()


def test_frozen_resource_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert Resources_GetRoot() == tmp_path / "resources"

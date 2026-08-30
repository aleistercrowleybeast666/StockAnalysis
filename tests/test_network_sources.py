from __future__ import annotations

import os
from datetime import date

import pytest

from stock_analysis.domain.enums import DataStatus, Market, NetworkMode
from stock_analysis.domain.models import Security
from stock_analysis.sources.base import HttpJsonClient
from stock_analysis.sources.eastmoney import EastmoneySource
from stock_analysis.sources.etnet import EtnetSource
from stock_analysis.sources.exchanges import OfficialAShareListSource
from stock_analysis.sources.hkex import HkexSecurityListSource
from stock_analysis.sources.tonghuashun import TonghuashunSource
from stock_analysis.sources.tradego import TradegoSource

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("RUN_NETWORK_TESTS") != "1",
        reason="set RUN_NETWORK_TESTS=1 to run live source checks",
    ),
]


def test_live_a_share_representative_sample() -> None:
    client = HttpJsonClient(
        "东方财富",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = EastmoneySource(client)
    try:
        sample = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
        financials = source.Financials_Fetch(sample, {2024})
        assert financials.provenance.status in {DataStatus.OK, DataStatus.MISSING}
        assert financials.value is not None
        assert any(period.fiscal_year == 2024 for period in financials.value)
    finally:
        source.close()


def test_live_hk_representative_sample_and_official_list() -> None:
    eastmoney_client = HttpJsonClient(
        "东方财富",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    hkex_client = HttpJsonClient(
        "HKEX",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = EastmoneySource(eastmoney_client)
    try:
        securities = HkexSecurityListSource(hkex_client).SecurityList_Fetch(limit=3)
        assert len(securities) == 3
        assert all(item.market is Market.HK for item in securities)
        sample = Security(Market.HK, "HKEX", "00700", "腾讯控股")
        financials = source.Financials_Fetch(sample, {2024})
        assert financials.value is not None
        assert financials.provenance.status in {DataStatus.OK, DataStatus.MISSING}
        assert any(period.fiscal_year == 2024 for period in financials.value)
    finally:
        source.close()
        hkex_client.close()


def test_live_official_a_share_list() -> None:
    client = HttpJsonClient(
        "沪深北交易所官方证券列表",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = OfficialAShareListSource(client)
    try:
        securities = source.SecurityList_Fetch()
        assert len(securities) > 4500
        assert {security.exchange for security in securities} >= {"SSE", "SZSE", "BSE"}
        assert {"600000", "000001"} <= {security.code for security in securities}
    finally:
        source.close()


def test_live_selected_batch_quotes_for_both_markets() -> None:
    client = HttpJsonClient(
        "东方财富",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = EastmoneySource(client)
    try:
        samples = [
            Security(Market.A_SHARE, "SSE", "600519", "贵州茅台"),
            Security(Market.HK, "HKEX", "00700", "腾讯控股"),
        ]
        quotes = source.Quotes_Fetch(samples)
        assert set(quotes) == {item.key for item in samples}
        assert all(item.value is not None for item in quotes.values())
        assert all(item.provenance.status is DataStatus.OK for item in quotes.values())
    finally:
        source.close()


def test_live_selected_a_share_block_trades_are_not_false_zero() -> None:
    client = HttpJsonClient(
        "东方财富",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = EastmoneySource(client)
    try:
        samples = [
            Security(Market.A_SHARE, "SSE", "600519", "贵州茅台"),
            Security(Market.A_SHARE, "SSE", "601318", "中国平安"),
            Security(Market.A_SHARE, "SZSE", "000001", "平安银行"),
        ]
        results = source.BlockTrades_Fetch(samples, 2025)
        assert all(results[item.key].value is not None for item in samples)
        assert all(results[item.key].value.trade_count > 0 for item in samples)  # type: ignore[union-attr]
        assert all(results[item.key].value.total_amount > 0 for item in samples)  # type: ignore[union-attr]
    finally:
        source.close()


def test_live_etnet_hk_complete_year_block_trade_sample() -> None:
    client = HttpJsonClient(
        "ETNet",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = EtnetSource(client, concurrency=2)
    try:
        sample = Security(Market.HK, "HKEX", "00002", "CLP HOLDINGS")
        result = source.BlockTrade_Fetch(sample, 2026)
        assert result.provenance.status in {DataStatus.OK, DataStatus.MISSING}
        if result.value is not None:
            assert result.value.trade_count >= 0
            assert result.value.total_amount >= 0
            assert result.value.currency == "HKD"
        else:
            assert "无法证明年度区间完整" in (
                result.provenance.missing_reason or ""
            )
    finally:
        source.close()


def test_live_tonghuashun_a_share_ipo_capital_and_5_22_day_flow() -> None:
    client = HttpJsonClient(
        "同花顺",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = TonghuashunSource(client)
    try:
        mobile = Security(
            Market.A_SHARE,
            "SSE",
            "600941",
            "中国移动",
            listing_date=date(2022, 1, 5),
        )
        capital = source.PostIssueShares_Fetch(mobile, mobile.listing_date)
        assert capital.value is not None
        assert capital.value > 20_000_000_000

        maotai = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
        flow = source.Flow_Fetch(maotai)
        assert flow.value is not None
        assert flow.value.five_day_net is not None
        assert flow.value.one_month_net is not None
        assert flow.provenance.field_statuses["近五个交易日资金净额"] is DataStatus.OK
        assert (
            flow.provenance.field_statuses["近一月资金净额（最近22个交易日）"]
            is DataStatus.OK
        )
    finally:
        client.close()


def test_live_eastmoney_hk_five_and_twenty_day_flow() -> None:
    client = HttpJsonClient(
        "东方财富",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = EastmoneySource(client)
    try:
        samples = [
            Security(Market.HK, "HKEX", "00700", "腾讯控股"),
            Security(Market.HK, "HKEX", "00941", "中国移动"),
            Security(Market.HK, "HKEX", "09988", "阿里巴巴-W"),
        ]
        for security in samples:
            flow = source.Flow_Fetch(security)
            assert flow.provenance.status in {DataStatus.OK, DataStatus.MISSING}
            if flow.value is not None:
                assert flow.value.five_day_net is not None
                assert flow.value.one_month_net is not None
                assert flow.value.currency == "HKD"
                assert flow.provenance.field_statuses["近五个交易日资金净额"] is DataStatus.OK
                assert (
                    flow.provenance.field_statuses[
                        "近一月资金净额（最近20个交易日）"
                    ]
                    is DataStatus.OK
                )
            else:
                assert flow.provenance.field_statuses[
                    "近一月资金净额（最近20个交易日）"
                ] is DataStatus.MISSING
    finally:
        source.close()


def test_live_tradego_hk_five_and_twenty_day_flow() -> None:
    client = HttpJsonClient(
        "TradeGo",
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        domestic=True,
        request_interval=0.05,
    )
    source = TradegoSource(client)
    try:
        samples = [
            Security(Market.HK, "HKEX", "00700", "腾讯控股"),
            Security(Market.HK, "HKEX", "09988", "阿里巴巴-W"),
        ]
        results = source.Flows_Fetch(samples, date.today())
        for security in samples:
            result = results[security.key]
            assert result.value is not None
            assert result.value.five_day_net is not None
            assert result.value.one_month_net is not None
            assert result.provenance.field_statuses[
                "近一月资金净额（最近20个交易日）"
            ] is DataStatus.OK
    finally:
        source.close()

from __future__ import annotations

from datetime import date

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import (
    BatchProgressUpdate,
    BlockTradeData,
    FinancialPeriod,
    FlowData,
    IPOInfo,
    Quote,
    Security,
)
from stock_analysis.sources.base import Provenance_Create, SourceError, SourceValue
from stock_analysis.sources.registry import LiveMarketDataSource


class _EastmoneyBlocks:
    source_name = "东方财富"

    def BlockTrades_Fetch(self, securities, year):
        return {
            security.key: SourceValue(
                BlockTradeData(security.key, year, 2, 100.0, "CNY"),
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    "fixture",
                    DataStatus.OK,
                ),
            )
            for security in securities
        }


class _FailingHkBlocks:
    def BlockTrade_Fetch(self, security, year):
        raise RuntimeError(f"{security.code}-{year}-模拟失败")


class _MissingHkBlockBatch:
    source_name = "ETNet"

    def BlockTrades_Fetch(self, securities, year):
        return {
            security.key: SourceValue(
                None,
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    f"year={year}",
                    DataStatus.MISSING,
                    missing_reason="年度列表不完整",
                ),
            )
            for security in securities
        }


class _MissingHkBlockSingle:
    source_name = "AASTOCKS"

    def BlockTrade_Fetch(self, security, year):
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                f"year={year}",
                DataStatus.MISSING,
                missing_reason="只有当日快照",
            ),
        )


class _SuccessfulHkexBlocks:
    source_name = "HKEX"

    def BlockTrades_Fetch(self, securities, year, progress_callback=None):
        if progress_callback is not None:
            for completed in range(5):
                progress_callback(completed, 4)
        return {
            security.key: SourceValue(
                BlockTradeData(security.key, year, 3, 90_000_000.0, "HKD"),
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    "official daily reports",
                    DataStatus.OK,
                ),
            )
            for security in securities
        }


class _Unused:
    configured = False


class _BatchQuoteSource:
    source_name = "东方财富"

    def Quotes_Fetch(self, securities, progress_callback=None):
        results = {}
        for security in securities:
            results[security.key] = SourceValue(
                Quote(security.key, date(2026, 8, 31), None, 100.0, "CNY"),
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    "batch",
                    DataStatus.OK,
                ),
            )
            if progress_callback is not None:
                progress_callback(security)
        return results


class _QuoteFallbackCounter:
    source_name = "腾讯行情"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def Quote_Fetch(self, security):
        self.calls.append(security.code)
        return SourceValue(
            Quote(security.key, date(2026, 8, 31), 10.0, None, "CNY"),
            Provenance_Create(
                security,
                "最新行情",
                self.source_name,
                "fallback",
                DataStatus.OK,
            ),
        )


class _EastmoneyMappedFinancials:
    source_name = "东方财富"

    def Financials_Fetch(self, security, years):
        period = FinancialPeriod(
            security.key,
            date(2025, 12, 31),
            2025,
            None,
            "HKD",
            100.0,
            60.0,
            20.0,
            18.0,
        )
        return SourceValue(
            [period],
            Provenance_Create(
                security, "年度财务", self.source_name, "hk-own", DataStatus.OK
            ),
        )

    def FinancialsMappedAForHk_Fetch(
        self, hk_security, _a_security, years, _evidence
    ):
        periods = [
            FinancialPeriod(
                hk_security.key,
                date(year, 12, 31),
                year,
                None,
                "HKD",
                float(year),
                1.0,
                1.0,
                1.0,
                original_currency="CNY",
            )
            for year in years
        ]
        return SourceValue(
            periods,
            Provenance_Create(
                hk_security,
                "年度财务",
                self.source_name,
                "A/H mapping",
                DataStatus.OK,
            ),
        )


class _EastmoneyPartialIpo:
    source_name = "东方财富"

    def IPO_Fetch(self, security):
        value = IPOInfo(security.key, None, None, 100.0, None, None)
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                "eastmoney",
                DataStatus.OK,
                field_statuses={
                    "上市日期": DataStatus.MISSING,
                    "发行价": DataStatus.MISSING,
                    "发行股数": DataStatus.OK,
                    "发行后总股本": DataStatus.MISSING,
                    "发行时总市值": DataStatus.MISSING,
                },
            ),
        )


class _EtnetListingIpo:
    source_name = "ETNet"

    def IPO_Fetch(self, security):
        value = IPOInfo(
            security.key, date(2004, 6, 16), 3.7, None, None, None
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                "company profile",
                DataStatus.OK,
                field_statuses={
                    "上市日期": DataStatus.OK,
                    "发行价": DataStatus.OK,
                },
            ),
        )


class _FlakyHistoryFlow:
    source_name = "历史资金流主源"

    def __init__(self, failed_code: str) -> None:
        self.failed_code = failed_code
        self.calls: list[str] = []

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        self.calls.append(security.code)
        if security.code == self.failed_code:
            raise SourceError("模拟历史接口断连")
        return _FlowValue_Create(security, one_month_net=22.0)


class _IndividualFlowFallback:
    source_name = "逐只资金流备源"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        self.calls.append(security.code)
        return _FlowValue_Create(security, one_month_net=22.0)


class _FailingIndividualFlowFallback:
    source_name = "失败逐只资金流备源"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        self.calls.append(security.code)
        raise SourceError("模拟同花顺 HTTP 403")


class _BatchHkFlowFallback:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def Flows_Fetch(self, securities, as_of_date):
        self.calls.append([security.code for security in securities])
        return {
            security.key: _FlowValue_Create(security, one_month_net=None)
            for security in securities
        }


def _FlowValue_Create(
    security: Security, *, one_month_net: float | None
) -> SourceValue[FlowData]:
    currency = "CNY" if security.market is Market.A_SHARE else "HKD"
    return SourceValue(
        FlowData(security.key, date(2026, 8, 28), 5.0, one_month_net, currency),
        Provenance_Create(
            security,
            "资金流",
            "测试源",
            "fixture",
            DataStatus.OK,
            standard_currency=currency,
        ),
    )


def test_hk_block_failure_does_not_discard_successful_a_share_batch() -> None:
    source = LiveMarketDataSource(
        _EastmoneyBlocks(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _FailingHkBlocks(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=2,
    )
    a_share = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    hk = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    results = source.BlockTrades_Fetch([a_share, hk], date.today().year)

    assert results[a_share.key].value is not None
    assert results[a_share.key].value.trade_count == 2
    assert results[hk.key].value is None
    assert results[hk.key].provenance.status is DataStatus.ERROR


def test_hk_block_fallback_chain_records_every_attempt_and_uses_hkex_value() -> None:
    source = LiveMarketDataSource(
        _EastmoneyBlocks(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _MissingHkBlockSingle(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        etnet=_MissingHkBlockBatch(),  # type: ignore[arg-type]
        hkex_block=_SuccessfulHkexBlocks(),  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=2,
    )
    security = Security(Market.HK, "HKEX", "03750", "宁德时代")

    result = source.BlockTrades_Fetch([security], 2025)[security.key]

    assert result.value is not None
    assert result.value.trade_count == 3
    assert result.provenance.source_name == "ETNet+AASTOCKS+HKEX"
    assert result.provenance.primary_source == "ETNet"
    assert "年度列表不完整" in (result.provenance.missing_reason or "")
    assert "只有当日快照" in (result.provenance.missing_reason or "")


def test_hk_block_progress_reserves_most_work_for_real_daily_report_batches() -> None:
    source = LiveMarketDataSource(
        _EastmoneyBlocks(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _MissingHkBlockSingle(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        etnet=_MissingHkBlockBatch(),  # type: ignore[arg-type]
        hkex_block=_SuccessfulHkexBlocks(),  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=2,
    )
    securities = [
        Security(Market.A_SHARE, "SSE", "600519", "贵州茅台"),
        Security(Market.HK, "HKEX", "03750", "宁德时代"),
    ]
    updates: list[BatchProgressUpdate] = []

    source.BlockTrades_Fetch(
        securities,
        2025,
        progress_callback=lambda update: updates.append(update),  # type: ignore[arg-type]
    )

    fractions = [update.stage_fraction for update in updates]
    hkex_updates = [
        update for update in updates if update.current_company == "HKEX 公开日报"
    ]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert hkex_updates[0].stage_fraction == 0.10
    assert hkex_updates[-1].stage_fraction == 0.98
    assert len(hkex_updates) == 5


def test_a_flow_probe_requires_every_sample_before_fanning_out() -> None:
    securities = [
        Security(Market.A_SHARE, "SSE", f"60000{index}", f"公司{index}")
        for index in range(4)
    ]
    primary = _FlakyHistoryFlow(securities[1].code)
    fallback = _IndividualFlowFallback()
    source = LiveMarketDataSource(
        primary,  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        fallback,  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        fallback,  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=2,
    )
    progressed: list[str] = []

    results = source.Flows_Fetch(
        securities, progress_callback=lambda security: progressed.append(security.code)
    )

    assert primary.calls == [security.code for security in securities[:3]]
    assert sorted(fallback.calls) == sorted(security.code for security in securities)
    assert sorted(progressed) == sorted(security.code for security in securities)
    assert all(results[security.key].value is not None for security in securities)


def test_a_flow_fallback_uses_tencent_after_tonghuashun_error() -> None:
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    tonghuashun = _FailingIndividualFlowFallback()
    tencent = _IndividualFlowFallback()
    source = LiveMarketDataSource(
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        tencent,  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        tonghuashun,  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=1,
    )

    result = source._AFlowFallback_Fetch(security)  # noqa: SLF001

    assert result.value is not None
    assert result.value.five_day_net == 5.0
    assert tonghuashun.calls == [security.code]
    assert tencent.calls == [security.code]
    assert "模拟同花顺 HTTP 403" in result.provenance.source_ref


def test_a_flow_fallback_prefers_complete_sina_history() -> None:
    security = Security(Market.A_SHARE, "BSE", "920002", "万达轴承")
    sina = _IndividualFlowFallback()
    tonghuashun = _FailingIndividualFlowFallback()
    tencent = _IndividualFlowFallback()
    source = LiveMarketDataSource(
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        tencent,  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        tonghuashun,  # type: ignore[arg-type]
        sina=sina,  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=1,
    )

    result = source._AFlowFallback_Fetch(security)  # noqa: SLF001

    assert result.value is not None
    assert result.value.one_month_net == 22.0
    assert sina.calls == [security.code]
    assert tonghuashun.calls == []
    assert tencent.calls == []


def test_hk_flow_probe_requires_every_sample_before_fanning_out() -> None:
    securities = [
        Security(Market.HK, "HKEX", f"0000{index}", f"公司{index}")
        for index in range(4)
    ]
    primary = _FlakyHistoryFlow(securities[1].code)
    fallback = _BatchHkFlowFallback()
    source = LiveMarketDataSource(
        primary,  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        fallback,  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=2,
    )
    progressed: list[str] = []

    results = source.Flows_Fetch(
        securities,
        as_of_date=date(2026, 8, 28),
        progress_callback=lambda security: progressed.append(security.code),
    )

    assert primary.calls == [security.code for security in securities[:3]]
    assert fallback.calls == [[security.code for security in securities]]
    assert progressed == [security.code for security in securities]
    assert all(results[security.key].value is not None for security in securities)


def test_hk_financial_history_uses_verified_ah_mapping_only_for_missing_years() -> None:
    source = LiveMarketDataSource(
        _EastmoneyMappedFinancials(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=1,
    )
    security = Security(Market.HK, "HKEX", "03308", "中际旭创")

    result = source.Financials_Fetch(security, {2025, 2024, 2022})

    assert {period.fiscal_year for period in result.value} == {2025, 2024, 2022}
    assert next(period for period in result.value if period.fiscal_year == 2025).revenue == 100.0
    assert "A/H" in result.provenance.source_ref


def test_hk_ipo_fallback_merges_listing_fields_without_using_current_share_capital() -> None:
    source = LiveMarketDataSource(
        _EastmoneyPartialIpo(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        etnet=_EtnetListingIpo(),  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=1,
    )
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = source.IPO_Fetch(security)

    assert result.value is not None
    assert result.value.listing_date == date(2004, 6, 16)
    assert result.value.issue_price == 3.7
    assert result.value.issued_shares == 100.0
    assert result.value.post_issue_total_shares is None
    assert result.value.issue_market_cap is None


def test_quote_merge_fills_price_field_without_overwriting_primary_market_cap() -> None:
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    primary = SourceValue(
        Quote(security.key, date(2026, 8, 28), None, 1_600_000_000_000.0, "CNY"),
        Provenance_Create(
            security,
            "最新行情",
            "东方财富",
            "batch quote",
            DataStatus.OK,
            field_statuses={
                "最新可得价格": DataStatus.MISSING,
                "最新总市值": DataStatus.OK,
                "行情日期": DataStatus.OK,
            },
        ),
    )
    fallback = SourceValue(
        Quote(security.key, date(2026, 8, 31), 1_300.0, 9.0, "CNY"),
        Provenance_Create(
            security,
            "最新行情",
            "腾讯行情",
            "qt.gtimg.cn",
            DataStatus.OK,
        ),
    )

    result = LiveMarketDataSource._QuoteResults_Merge(  # noqa: SLF001
        security, primary, fallback
    )

    assert result.value is not None
    assert result.value.price == 1_300.0
    assert result.value.market_cap == 1_600_000_000_000.0
    assert result.value.quote_date == date(2026, 8, 31)
    assert result.provenance.field_statuses["最新可得价格"] is DataStatus.OK
    assert result.provenance.field_statuses["最新总市值"] is DataStatus.OK


def test_universe_quote_batch_does_not_fan_out_fallback_until_company_is_selected() -> None:
    fallback = _QuoteFallbackCounter()
    source = LiveMarketDataSource(
        _BatchQuoteSource(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        fallback,  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        _Unused(),  # type: ignore[arg-type]
        sample_mode=True,
        concurrency=1,
    )
    securities = [
        Security(Market.A_SHARE, "SSE", f"60000{index}", f"公司{index}")
        for index in range(3)
    ]

    ranking_quotes = source.Quotes_Fetch(securities)

    assert fallback.calls == []
    selected = securities[0]
    output_quote = source.OutputQuote_Fetch(selected, ranking_quotes[selected.key])
    assert fallback.calls == [selected.code]
    assert output_quote.value is not None
    assert output_quote.value.price == 10.0
    assert output_quote.value.market_cap == 100.0

from __future__ import annotations

from datetime import date

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import BlockTradeData, FlowData, Security
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


class _Unused:
    configured = False


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

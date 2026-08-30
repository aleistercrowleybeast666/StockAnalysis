from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

import pytest

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import Security
from stock_analysis.sources.aastocks import AastocksSource
from stock_analysis.sources.base import SourceError, SourceSchemaError, SourceUnsupportedError
from stock_analysis.sources.cninfo import CninfoSource
from stock_analysis.sources.eastmoney import EastmoneySource
from stock_analysis.sources.etnet import EtnetSource
from stock_analysis.sources.fx import FxRate
from stock_analysis.sources.hkex import HkexBlockTradeSource
from stock_analysis.sources.tencent import TencentQuoteSource
from stock_analysis.sources.tonghuashun import TonghuashunSource
from stock_analysis.sources.tradego import TradegoSource


class FakeClient:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def RequestJson(self, _url: str, *, request_id: str, **_kwargs) -> dict[str, Any]:
        self.requests.append(request_id)
        self.calls.append({"url": _url, "request_id": request_id, **_kwargs})
        if request_id.startswith("security-list-") and "paged-list" in self.responses:
            page = int(request_id.rsplit("-", 1)[-1])
            start = (page - 1) * 100
            if page <= 5:
                rows = [
                    {"f12": f"{600000 + index:06d}", "f14": f"公司{index}"}
                    for index in range(start, start + 100)
                ]
            elif page == 6:
                rows = [{"f12": "300750", "f14": "宁德时代"}]
            else:
                rows = []
            return {"data": {"total": 501, "diff": rows}}
        return self.responses[request_id]

    def close(self) -> None:
        return None


class FakeFxSource:
    def Rate_Fetch(self, _source: str, _target: str, _on_date: date) -> FxRate:
        return FxRate(0.9, date(2024, 12, 30))

    def close(self) -> None:
        return None


class FakeBytesClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def RequestBytes(self, _url: str, **_kwargs) -> bytes:
        return self.payload

    def close(self) -> None:
        return None


class MappedBytesClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.requests: list[str] = []

    def RequestBytes(self, _url: str, *, request_id: str, **_kwargs) -> bytes:
        self.requests.append(request_id)
        return self.payloads[request_id]

    def close(self) -> None:
        return None


class _HkexDailyReportClient:
    def __init__(self, archive_start: date, section: str) -> None:
        self.archive_start = archive_start
        self.section = section.encode("latin-1")
        self.requests: list[str] = []

    def RequestBytes(
        self, url: str, *, request_id: str, headers: dict[str, str], **_kwargs
    ) -> bytes:
        self.requests.append(request_id)
        matched = re.search(r"d(\d{6})e\.htm", url)
        assert matched is not None
        traded_on = date.fromisoformat(
            f"20{matched.group(1)[:2]}-"
            f"{matched.group(1)[2:4]}-{matched.group(1)[4:]}"
        )
        if headers.get("Range") == "bytes=0-0":
            if traded_on < self.archive_start:
                raise SourceError("HKEX 请求失败（HTTP 404）")
            return b"<"
        return self.section


class _HkexCalendarClient:
    def RequestJson(self, _url: str, **_kwargs) -> dict[str, Any]:
        return {
            "data": {
                "hkHSI": {
                    "day": [
                        ["2025-01-02", "1"],
                        ["2025-05-20", "1"],
                        ["2025-05-21", "1"],
                    ]
                }
            }
        }


def test_tonghuashun_post_issue_shares_uses_explicit_listing_row() -> None:
    payload = """
    <table>
      <tr><th>变动日期</th><th>变动原因</th><th>变动后总股本</th></tr>
      <tr><td>2022-01-05</td><td>A股上市,配售股份上市</td><td>213.21亿</td></tr>
      <tr><td>2024-12-31</td><td>年报</td><td>215.17亿</td></tr>
    </table>
    """.encode("gb18030")
    security = Security(
        Market.A_SHARE,
        "SSE",
        "600941",
        "中国移动",
        listing_date=date(2022, 1, 5),
    )

    result = TonghuashunSource(FakeBytesClient(payload)).PostIssueShares_Fetch(  # type: ignore[arg-type]
        security, security.listing_date
    )

    assert result.value == pytest.approx(21_321_000_000)
    assert result.provenance.approximate is True
    assert result.provenance.field_statuses["发行后总股本"] is DataStatus.OK


def test_tonghuashun_post_issue_shares_rejects_current_or_unrelated_capital() -> None:
    text = """
    <table>
      <tr><td>2018-06-11</td><td>定期报告</td><td>21.72亿</td></tr>
      <tr><td>2026-06-30</td><td>半年报</td><td>45.63亿</td></tr>
    </table>
    """

    assert (
        TonghuashunSource._PostIssueShares_Parse(  # noqa: SLF001
            text, date(2018, 6, 11)
        )
        is None
    )


def test_tonghuashun_flow_uses_latest_daily_series_for_5_and_22_days() -> None:
    old = [
        {"date": f"2024-01-{index + 1:02d}", "value": str(index), "field": "0"}
        for index in range(20)
    ]
    start = date(2026, 7, 1)
    current = [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "value": str(index),
            "field": None,
        }
        for index in range(30)
    ]
    payload = (
        f"<html><body>{json.dumps(old)}资金流向{json.dumps(current)}</body></html>"
    ).encode("gb18030")
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")

    result = TonghuashunSource(FakeBytesClient(payload)).Flow_Fetch(security)  # type: ignore[arg-type]

    assert result.value is not None
    assert result.value.end_date == start + timedelta(days=29)
    assert result.value.five_day_net == pytest.approx(135 * 10_000)
    assert result.value.one_month_net == pytest.approx(407 * 10_000)
    assert result.provenance.field_statuses["近五个交易日资金净额"] is DataStatus.OK
    assert (
        result.provenance.field_statuses["近一月资金净额（最近22个交易日）"]
        is DataStatus.OK
    )


def test_security_list_paginates_and_maps_flags() -> None:
    client = FakeClient({"paged-list": {}})
    source = EastmoneySource(client)  # type: ignore[arg-type]
    result = source.SecurityList_Fetch(Market.A_SHARE)
    assert len(result) == 501
    assert result[-1].code == "300750"
    assert result[-1].exchange == "SZSE"
    assert len(client.requests) == 6

    limited_client = FakeClient(
        {
            "security-list-A股-20-page-1": {
                "data": {
                    "total": 2,
                    "diff": [
                        {"f12": "000001", "f14": "平安银行"},
                        {"f12": "600001", "f14": "ST 测试"},
                    ],
                }
            }
        }
    )
    limited = EastmoneySource(limited_client).SecurityList_Fetch(Market.A_SHARE, 2)  # type: ignore[arg-type]
    assert limited[0].is_financial is True
    assert limited[1].is_st is True


def test_security_list_schema_change_has_clear_error() -> None:
    client = FakeClient({"security-list-A股-20-page-1": {"unexpected": {}}})
    with pytest.raises(SourceSchemaError, match="结构发生变化"):
        EastmoneySource(client).SecurityList_Fetch(Market.A_SHARE, 1)  # type: ignore[arg-type]


def test_a_share_financial_mapping_and_missing_period() -> None:
    client = FakeClient(
        {
            "a-financial-600519": {
                "result": {
                    "data": [
                        {
                            "REPORTDATE": "2024-12-31",
                            "NOTICE_DATE": "2025-04-01",
                            "DATATYPE": "年报",
                            "TOTAL_OPERATE_INCOME": 1000,
                            "PARENT_NETPROFIT": 200,
                            "XSMLL": 40,
                        }
                    ]
                }
            },
            "a-cashflow-600519": {
                "result": {
                    "data": [
                        {
                            "REPORT_DATE": "2024-12-31",
                            "DATE_TYPE_CODE": "001",
                            "NETCASH_OPERATE": 180,
                        }
                    ]
                }
            },
        }
    )
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    value = EastmoneySource(client).Financials_Fetch(security, {2024})  # type: ignore[arg-type]
    assert value.provenance.status is DataStatus.OK
    assert value.provenance.approximate is True
    assert value.value and value.value[0].operating_cost == pytest.approx(600)
    assert value.value[0].operating_cash_flow == 180

    missing = EastmoneySource(client).Financials_Fetch(security, {2023})  # type: ignore[arg-type]
    assert missing.value == []
    assert missing.provenance.status is DataStatus.MISSING


def test_hk_financial_quote_ipo_and_allowed_missing_groups() -> None:
    client = FakeClient(
        {
            "hk-financial-00700": {
                "result": {
                    "data": [
                        {
                            "REPORT_DATE": "2024-12-31",
                            "DATE_TYPE_CODE": "001",
                            "OPERATE_INCOME": 1000,
                            "GROSS_PROFIT": 450,
                            "HOLDER_PROFIT": 220,
                            "NETCASH_OPERATE": 260,
                            "CURRENCY": "HKD",
                        }
                    ]
                }
            },
            "quote-港股-00700": {
                "data": {"f43": 455.2, "f116": 4_000_000, "f124": 1_788_000_000}
            },
            "ipo-港股-00700": {
                "result": {
                    "data": [
                        {
                            "LISTING_DATE": "2004-06-16",
                            "ISSUE_PRICE": 3.7,
                            "ISSUE_NUM": 1000,
                            "TOTAL_SHARES_AFTER_ISSUE": 10_000,
                        }
                    ]
                }
            },
            "flow-hk-00700": {"data": {"klines": []}},
        }
    )
    source = EastmoneySource(client)  # type: ignore[arg-type]
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")
    financials = source.Financials_Fetch(security, {2024})
    quote = source.Quote_Fetch(security)
    ipo = source.IPO_Fetch(security)
    assert financials.value and financials.value[0].operating_cost == 550
    assert quote.value and quote.value.price == pytest.approx(455.2)
    assert ipo.value and ipo.value.listing_date == date(2004, 6, 16)
    assert ipo.value.issue_market_cap == pytest.approx(37_000)
    assert ipo.value.approximate is False
    assert source.BlockTrade_Fetch(security, 2026).provenance.status is DataStatus.MISSING
    assert source.Flow_Fetch(security).provenance.status is DataStatus.MISSING


def test_hk_non_hkd_financials_are_converted() -> None:
    client = FakeClient(
        {
            "hk-financial-09988": {
                "result": {
                    "data": [
                        {
                            "REPORT_DATE": "2024-12-31",
                            "DATE_TYPE_CODE": "001",
                            "OPERATE_INCOME": 1000,
                            "GROSS_PROFIT": 400,
                            "HOLDER_PROFIT": 100,
                            "NETCASH_OPERATE": 150,
                            "CURRENCY": "CNY",
                        }
                    ]
                }
            }
        }
    )
    security = Security(Market.HK, "HKEX", "09988", "阿里巴巴-W")
    value = EastmoneySource(client, FakeFxSource()).Financials_Fetch(security, {2024})  # type: ignore[arg-type]
    assert value.value
    period = value.value[0]
    assert period.currency == "HKD"
    assert period.original_currency == "CNY"
    assert period.revenue == pytest.approx(900)
    assert period.operating_cost == pytest.approx(540)
    assert period.fx_rate == pytest.approx(0.9)
    assert period.fx_date == date(2024, 12, 30)


def test_verified_ah_mapping_converts_a_share_history_for_hk_security() -> None:
    client = FakeClient(
        {
            "a-financial-300308": {
                "result": {
                    "data": [
                        {
                            "REPORTDATE": "2022-12-31",
                            "DATATYPE": "年报",
                            "TOTAL_OPERATE_INCOME": 1000,
                            "PARENT_NETPROFIT": 200,
                            "XSMLL": 40,
                        }
                    ]
                }
            },
            "a-cashflow-300308": {
                "result": {
                    "data": [
                        {
                            "REPORT_DATE": "2022-12-31",
                            "DATE_TYPE_CODE": "001",
                            "NETCASH_OPERATE": 180,
                        }
                    ]
                }
            },
        }
    )
    hk = Security(Market.HK, "HKEX", "03308", "中际旭创")
    a_share = Security(Market.A_SHARE, "SZSE", "300308", "中际旭创")

    result = EastmoneySource(client, FakeFxSource()).FinancialsMappedAForHk_Fetch(  # type: ignore[arg-type]
        hk, a_share, {2022}, "03308.HK / 300308.SZ"
    )

    assert result.value and result.value[0].security_key == hk.key
    assert result.value[0].currency == "HKD"
    assert result.value[0].original_currency == "CNY"
    assert result.value[0].revenue == pytest.approx(900)
    assert "A/H" in (result.value[0].quality_note or "")


def test_a_share_flow_calculates_five_and_twenty_two_days() -> None:
    klines = [
        f"{date(2026, 1, 1) + timedelta(days=index)},{index + 1},0,0"
        for index in range(30)
    ]
    client = FakeClient({"flow-600519": {"data": {"klines": klines}}})
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    result = EastmoneySource(client).Flow_Fetch(security)  # type: ignore[arg-type]
    assert result.value is not None
    assert result.value.five_day_net == 140
    assert result.value.one_month_net == 429
    assert result.provenance.status is DataStatus.OK
    assert client.calls[0]["url"].endswith("/fflow/daykline/get")
    assert client.calls[0]["endpoint_key"] == "flow-history-a-share-600519"


def test_hk_flow_calculates_five_and_twenty_days_in_hkd() -> None:
    klines = [
        f"{date(2026, 1, 1) + timedelta(days=index)},{index + 1},0,0"
        for index in range(30)
    ]
    client = FakeClient({"flow-hk-00700": {"data": {"klines": klines}}})
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = EastmoneySource(client).Flow_Fetch(security)  # type: ignore[arg-type]

    assert result.value is not None
    assert result.value.five_day_net == 140
    assert result.value.one_month_net == 410
    assert result.value.currency == "HKD"
    assert result.provenance.field_statuses["近五个交易日资金净额"] is DataStatus.OK
    assert (
        result.provenance.field_statuses["近一月资金净额（最近20个交易日）"]
        is DataStatus.OK
    )
    assert client.calls[0]["params"]["secid"] == "116.00700"
    assert client.calls[0]["endpoint_key"] == "flow-history-hk-00700"


def test_a_share_flow_keeps_five_day_value_when_twenty_two_days_are_missing() -> None:
    klines = [
        f"{date(2026, 1, 1) + timedelta(days=index)},{index + 1},0,0"
        for index in range(10)
    ]
    client = FakeClient({"flow-600519": {"data": {"klines": klines}}})
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    result = EastmoneySource(client).Flow_Fetch(security)  # type: ignore[arg-type]
    assert result.value is not None
    assert result.value.five_day_net == 40
    assert result.value.one_month_net is None
    assert result.provenance.status is DataStatus.OK
    assert "22 日字段留空" in (result.provenance.missing_reason or "")


def test_empty_quote_and_flow_are_explicitly_missing() -> None:
    client = FakeClient(
        {
            "quote-A股-600519": {"data": None},
            "flow-600519": {"data": {"klines": []}},
        }
    )
    source = EastmoneySource(client)  # type: ignore[arg-type]
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    assert source.Quote_Fetch(security).provenance.status is DataStatus.MISSING
    assert source.Flow_Fetch(security).provenance.status is DataStatus.MISSING


def test_quote_without_source_timestamp_is_missing_not_system_date() -> None:
    client = FakeClient(
        {"quote-A股-600519": {"data": {"f43": 10.0, "f116": 100_000_000}}}
    )
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    result = EastmoneySource(client).Quote_Fetch(security)  # type: ignore[arg-type]
    assert result.value is None
    assert result.provenance.status is DataStatus.MISSING
    assert "真实行情时间" in (result.provenance.missing_reason or "")


def test_public_quote_fallback_parsers_keep_true_dates_and_market_caps() -> None:
    hk_html = b"""
    Last Updated: 2026-08-28 16:08
    Last Price</td><td><strong>455.200</strong></td>
    Market Capital</td><td>4,143.75B</td>
    """
    hk_security = Security(Market.HK, "HKEX", "00700", "腾讯控股")
    hk_result = AastocksSource(FakeBytesClient(hk_html)).Quote_Fetch(hk_security)  # type: ignore[arg-type]
    assert hk_result.value is not None
    assert hk_result.value.quote_date == date(2026, 8, 28)
    assert hk_result.value.market_cap == pytest.approx(4_143_750_000_000)

    tencent_fields = [""] * 88
    tencent_fields[3] = "1297.40"
    tencent_fields[30] = "20260828161500"
    tencent_fields[45] = "16218.56"
    a_payload = ('v_sh600519="' + "~".join(tencent_fields) + '";').encode()
    a_security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    a_result = TencentQuoteSource(FakeBytesClient(a_payload)).Quote_Fetch(a_security)  # type: ignore[arg-type]
    assert a_result.value is not None
    assert a_result.value.quote_date == date(2026, 8, 28)
    assert a_result.value.market_cap == pytest.approx(1_621_856_000_000)


def test_aastocks_money_flow_parses_five_real_trading_days_only() -> None:
    rows = "".join(
        f"<tr><td>2026/08/{day:02d}</td>"
        f"<td>0</td><td>0</td><td>0</td><td>0</td>"
        f"<td>{amount}</td><td>0</td></tr>"
        for day, amount in (
            (24, "241.46M"),
            (25, "15.36M"),
            (26, "378.40M"),
            (27, "167.99M"),
            (28, "1.61B"),
        )
    )
    payload = (
        "<div>Historical Money Flow Data (Last 5 trading days)</div>"
        f"<table><tbody>{rows}</tbody></table>"
    ).encode()
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = AastocksSource(FakeBytesClient(payload)).Flow_Fetch(security)  # type: ignore[arg-type]

    assert result.value is not None
    assert result.value.end_date == date(2026, 8, 28)
    assert result.value.five_day_net == pytest.approx(2_413_210_000)
    assert result.value.one_month_net is None
    assert result.provenance.field_statuses["近五个交易日资金净额"] is DataStatus.OK
    assert (
        result.provenance.field_statuses["近一月资金净额（最近20个交易日）"]
        is DataStatus.MISSING
    )


def test_aastocks_block_page_records_daily_evidence_without_faking_annual_data() -> None:
    payload = b"""
    <script>
    var _stat = {data:[],turn:'11.11B'};
    var btc = new btController({tdate:'20260828'});
    </script>
    """
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = AastocksSource(FakeBytesClient(payload)).BlockTrade_Fetch(  # type: ignore[arg-type]
        security, 2026
    )

    assert result.value is None
    assert "2026-08-28" in (result.provenance.missing_reason or "")
    assert "年度字段保持空白" in (result.provenance.missing_reason or "")


def test_etnet_block_trade_aggregates_complete_year_details() -> None:
    list_page = b"""
    <div class="DivArticleList dotLine">
      <p class="date">24/08/2026 09:04</p>
      <p class="ArticleHdr"><a href="quote_blocktrade_detail.php?newsid=20260824283&amp;page=1&amp;code=700">item</a></p>
    </div>
    <div class="DivArticleList dotLine">
      <p><span class="date">13/08/2026 09:31</span>
      <a href="quote_blocktrade_detail.php?newsid=20260813286&amp;page=1&amp;code=700">item</a></p>
    </div>
    <div class="DivArticleList dotLine">
      <p><span class="date">31/12/2025 09:01</span>
      <a href="quote_blocktrade_detail.php?newsid=20251231281&amp;page=1&amp;code=700">old</a></p>
    </div>
    """
    individual = b"""
    <article><div id="NewsContent">
    [ET Net News Agency, 24 August 2026] Two direct manual trades of shares
    of TENCENT (00700) were registered. The deals amounted to HK$84.32m.
    </div></article>
    """
    table = b"""
    <article><div id="NewsContent"><table><tbody>
    <tr><td>TENCENT (00700)</td><td>A direct manual trade of 89,300 shares</td>
    <td>HK$446.4</td><td>HK$39.86m</td></tr>
    <tr><td>AIA (01299)</td><td>7 block trades of shares</td>
    <td>HK$71.5</td><td>HK$549.06m</td></tr>
    </tbody></table></div></article>
    """
    client = MappedBytesClient(
        {
            "etnet-block-list-00700-page-1": list_page,
            "etnet-block-detail-20260824283": individual,
            "etnet-block-detail-20260813286": table,
        }
    )
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = EtnetSource(client, concurrency=2).BlockTrade_Fetch(  # type: ignore[arg-type]
        security, 2026
    )

    assert result.value is not None
    assert result.value.trade_count == 3
    assert result.value.total_amount == pytest.approx(124_180_000)
    assert result.provenance.status is DataStatus.OK
    assert "etnet-block-detail-20251231281" not in client.requests


def test_etnet_block_trade_continues_past_visible_ten_page_navigation() -> None:
    payloads = {}
    for page in range(1, 13):
        published = "31/12/2025" if page == 12 else f"{29 - page:02d}/08/2026"
        news_id = f"{20250000000 + page}"
        payloads[f"etnet-block-list-00700-page-{page}"] = (
            f'<p class="date">{published} 09:01</p>'
            f'<a href="quote_blocktrade_detail.php?newsid={news_id}&amp;page={page}&amp;code=700">item</a>'
        ).encode()
    client = MappedBytesClient(payloads)
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = EtnetSource(client, concurrency=2)._BlockNewsList_Fetch(  # type: ignore[arg-type]  # noqa: SLF001
        security, 2026
    )

    assert result.complete_for_year is True
    assert result.page_count == 12
    assert "etnet-block-list-00700-page-11" in client.requests
    assert "etnet-block-list-00700-page-12" in client.requests


def test_etnet_block_trade_stops_on_repeated_page_without_claiming_complete() -> None:
    page = b"""
    <p class="date">28/08/2026 09:01</p>
    <a href="quote_blocktrade_detail.php?newsid=20260828281&amp;page=1&amp;code=700">item</a>
    """
    client = MappedBytesClient(
        {
            "etnet-block-list-00700-page-1": page,
            "etnet-block-list-00700-page-2": page,
        }
    )
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = EtnetSource(client, concurrency=1)._BlockNewsList_Fetch(  # type: ignore[arg-type]  # noqa: SLF001
        security, 2026
    )

    assert result.complete_for_year is False
    assert "重复" in result.stop_reason
    assert "etnet-block-list-00700-page-3" not in client.requests


def test_etnet_block_trade_does_not_write_false_zero_for_pruned_past_year() -> None:
    current_page = b"""
    <div class="DivArticleList dotLine"><p class="date">09/03/2026 09:01</p>
    <p><a href="quote_blocktrade_detail.php?newsid=20260309281&amp;page=1&amp;code=2">item</a></p></div>
    """
    client = MappedBytesClient(
        {
            "etnet-block-list-00002-page-1": current_page,
            "etnet-block-list-00002-page-2": b"<html>no more records</html>",
        }
    )
    security = Security(Market.HK, "HKEX", "00002", "中电控股")

    result = EtnetSource(client, concurrency=1).BlockTrade_Fetch(  # type: ignore[arg-type]
        security, 2025
    )

    assert result.value is None
    assert result.provenance.status is DataStatus.MISSING
    assert "无法证明年度区间完整" in (result.provenance.missing_reason or "")
    assert all("detail" not in request for request in client.requests)


def test_hkex_block_section_matches_verified_etnet_threshold_sample() -> None:
    section = """
    SALES RECORDS OVER $500,000
      700 TENCENT < P50,900-511.50 P50,000-510.876 P200,000-510.875
                    P103,740-510.461 P44,460-510.462 P130,300-511.50
                    P178,900-511.50 P198,900-511.50 P77,700-511.50
                    X1,000-511.00 >
    """

    values = HkexBlockTradeSource._BlockSection_Parse(  # noqa: SLF001
        section, {"00700"}
    )

    assert values["00700"][0] == 6
    assert values["00700"][1] == pytest.approx(454_766_924.14)


def test_hkex_block_batch_only_writes_complete_post_listing_interval() -> None:
    section = """
    SALES RECORDS OVER $500,000
     3750 CATL             < P100,000-300.00 X100,000-250.00
                            P50,000-300.00 >
    AMENDMENT RECORDS FOR TRADE
    """
    source = HkexBlockTradeSource(
        _HkexDailyReportClient(date(2025, 5, 20), section),  # type: ignore[arg-type]
        _HkexCalendarClient(),  # type: ignore[arg-type]
        concurrency=2,
    )
    old_listing = Security(
        Market.HK,
        "HKEX",
        "00700",
        "腾讯控股",
        listing_date=date(2004, 6, 16),
    )
    new_listing = Security(
        Market.HK,
        "HKEX",
        "03750",
        "宁德时代",
        listing_date=date(2025, 5, 20),
    )

    progress: list[tuple[int, int]] = []
    results = source.BlockTrades_Fetch(
        [old_listing, new_listing],
        2025,
        progress_callback=lambda completed, total: progress.append(
            (completed, total)
        ),
    )

    assert results[old_listing.key].value is None
    assert results[old_listing.key].provenance.status is DataStatus.MISSING
    assert "最早可验证日报=2025-05-20" in (
        results[old_listing.key].provenance.missing_reason or ""
    )
    assert results[new_listing.key].value is not None
    assert results[new_listing.key].value.trade_count == 4
    assert results[new_listing.key].value.total_amount == pytest.approx(110_000_000)
    assert progress[0][0] == 0
    assert progress[-1][0] == progress[-1][1]
    assert [completed for completed, _total in progress] == sorted(
        completed for completed, _total in progress
    )


def test_etnet_company_profile_supplies_only_verified_listing_fields() -> None:
    payload = b"""
    <tr><td>Issued Share Capital</td><td>9,103,146,761</td></tr>
    <tr><td>Listing Date</td><td>16/06/2004</td></tr>
    <tr><td>Listing Price &nbsp;(HKD)</td><td>3.700</td></tr>
    """
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = EtnetSource(FakeBytesClient(payload)).IPO_Fetch(security)  # type: ignore[arg-type]

    assert result.value is not None
    assert result.value.listing_date == date(2004, 6, 16)
    assert result.value.issue_price == pytest.approx(3.7)
    assert result.value.issued_shares is None
    assert result.value.post_issue_total_shares is None
    assert result.value.issue_market_cap is None


def test_post_issue_share_parsers_require_listing_evidence() -> None:
    a_rows = {
        "lngbbd": [
            {
                "END_DATE": "2026-01-01",
                "TOTAL_SHARES": 999_000_000,
                "CHANGE_REASON": "回购",
            },
            {
                "END_DATE": "2001-08-27",
                "TOTAL_SHARES": 250_000_000,
                "CHANGE_REASON": "首发A股上市",
            },
        ]
    }
    assert EastmoneySource._PostIssueSharesA_Get(  # noqa: SLF001
        a_rows, date(2001, 8, 27)
    ) == pytest.approx(250_000_000)
    assert EastmoneySource._PostIssueSharesA_Get(  # noqa: SLF001
        {"lngbbd": [a_rows["lngbbd"][0]]}, date(2001, 8, 27)
    ) is None

    hk_rows = [
        {
            "CHANGE_DATE": "2026-08-26",
            "HK_SHARES": 9_103_146_761,
            "CHANGE_REASON": "股份期权",
        },
        {
            "CHANGE_DATE": "2004-06-16",
            "HK_SHARES": 1_680_641_260,
            "CHANGE_REASON": "新股上市",
        },
    ]
    assert EastmoneySource._PostIssueSharesHk_Get(  # noqa: SLF001
        hk_rows, date(2004, 6, 16)
    ) == pytest.approx(1_680_641_260)


def test_tencent_flow_fallback_parses_five_days_without_faking_twenty_two() -> None:
    fields = [""] * 18
    fields[0] = "sh600519"
    fields[3] = "10"
    fields[13] = "20260828"
    fields[14] = "20260827^30^20"
    fields[15] = "20260826^40^20"
    fields[16] = "20260825^20^30"
    fields[17] = "20260824^50^20"
    payload = ('v_ff_sh600519="' + "~".join(fields) + '";').encode("gb18030")
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")

    result = TencentQuoteSource(FakeBytesClient(payload)).Flow_Fetch(security)  # type: ignore[arg-type]

    assert result.value is not None
    assert result.value.five_day_net == pytest.approx(600_000)
    assert result.value.one_month_net is None


def test_tradego_batch_flow_returns_verified_five_and_twenty_day_values() -> None:
    client = FakeClient(
        {
            "tradego-hk-flow-5-offset-0": {
                "His": [{"_Code": "E00700", "NetIn": "2.28B"}]
            },
            "tradego-hk-flow-20-offset-0": {
                "His": [{"_Code": "E00700", "NetIn": "7.03B"}]
            },
        }
    )
    security = Security(Market.HK, "HKEX", "00700", "腾讯控股")

    result = TradegoSource(client).Flows_Fetch(  # type: ignore[arg-type]
        [security], date(2026, 8, 28)
    )[security.key]

    assert result.value is not None
    assert result.value.five_day_net == pytest.approx(2.28e9)
    assert result.value.one_month_net == pytest.approx(7.03e9)
    assert result.provenance.approximate is False
    assert result.provenance.field_statuses[
        "近一月资金净额（最近20个交易日）"
    ] is DataStatus.OK
    assert client.requests == [
        "tradego-hk-flow-5-offset-0",
        "tradego-hk-flow-20-offset-0",
    ]


def test_batch_quotes_fill_one_hundred_companies_without_single_requests() -> None:
    securities = [
        Security(Market.A_SHARE, "SSE", f"{600000 + index:06d}", f"公司{index}")
        for index in range(100)
    ]
    rows = [
        {
            "f12": security.code,
            "f13": 1,
            "f2": 10 + index,
            "f20": 1_000_000 + index,
            "f124": 1_788_000_000,
        }
        for index, security in enumerate(securities)
    ]
    client = FakeClient(
        {
            "batch-quotes-selected-1": {
                "data": {"total": 100, "diff": rows}
            }
        }
    )
    result = EastmoneySource(client).Quotes_Fetch(securities)  # type: ignore[arg-type]
    assert len(result) == 100
    assert client.requests == ["batch-quotes-selected-1"]
    assert all(value.value and value.value.market_cap for value in result.values())


def test_batch_quotes_can_mix_a_share_and_hk_in_one_request() -> None:
    securities = [
        Security(Market.A_SHARE, "SSE", "600519", "贵州茅台"),
        Security(Market.HK, "HKEX", "00700", "腾讯控股"),
    ]
    client = FakeClient(
        {
            "batch-quotes-selected-1": {
                "data": {
                    "total": 2,
                    "diff": [
                        {
                            "f12": "600519",
                            "f13": 1,
                            "f2": 1297.4,
                            "f20": 1_621_855_869_137,
                            "f124": 1_788_000_000,
                        },
                        {
                            "f12": "00700",
                            "f13": 116,
                            "f2": 455.2,
                            "f20": 4_143_752_405_607,
                            "f124": 1_788_000_000,
                        },
                    ],
                }
            }
        }
    )
    result = EastmoneySource(client).Quotes_Fetch(securities)  # type: ignore[arg-type]
    assert client.requests == ["batch-quotes-selected-1"]
    assert result[securities[0].key].value.currency == "CNY"  # type: ignore[union-attr]
    assert result[securities[1].key].value.currency == "HKD"  # type: ignore[union-attr]


def test_market_block_trades_are_aggregated_and_no_trade_is_zero() -> None:
    first = Security(Market.A_SHARE, "SSE", "600001", "公司一")
    second = Security(Market.A_SHARE, "SSE", "600002", "公司二")
    client = FakeClient(
        {
            "block-trade-selected-2026-batch-1-page-1": {
                "result": {
                    "pages": 1,
                    "data": [
                        {"SECURITY_CODE": "600001", "DEAL_AMT": 12.5},
                        {"SECURITY_CODE": "600001", "DEAL_AMT": 7.5},
                    ],
                }
            }
        }
    )
    result = EastmoneySource(client).BlockTrades_Fetch(  # type: ignore[arg-type]
        [first, second], 2026
    )
    assert client.requests == ["block-trade-selected-2026-batch-1-page-1"]
    params = client.calls[0]["params"]
    assert "DEAL_NUM" not in params["columns"]
    assert 'SECURITY_CODE in ("600001","600002")' in params["filter"]
    assert result[first.key].value is not None
    assert result[first.key].value.trade_count == 2
    assert result[first.key].value.total_amount == pytest.approx(20.0)
    assert result[second.key].value is not None
    assert result[second.key].value.trade_count == 0
    assert result[second.key].value.total_amount == 0.0


def test_block_trade_application_failure_is_not_treated_as_zero() -> None:
    security = Security(Market.A_SHARE, "SSE", "600001", "公司一")
    client = FakeClient(
        {
            "block-trade-selected-2026-batch-1-page-1": {
                "success": False,
                "message": "请求字段不存在",
                "result": None,
            }
        }
    )
    with pytest.raises(SourceSchemaError, match="请求字段不存在"):
        EastmoneySource(client).BlockTrades_Fetch(  # type: ignore[arg-type]
            [security], 2026
        )


def test_cninfo_requires_official_credentials_and_maps_registered_api() -> None:
    security = Security(Market.A_SHARE, "SSE", "600519", "贵州茅台")
    unconfigured = CninfoSource(
        FakeClient(),  # type: ignore[arg-type]
        access_token=None,
        income_api_url=None,
        cashflow_api_url=None,
    )
    with pytest.raises(SourceUnsupportedError, match="未配置巨潮官方 API"):
        unconfigured.Financials_Fetch(security, {2025})

    client = FakeClient(
        {
            "cninfo-financial-income-a-share-600519": {
                "records": [
                    {
                        "REPORT_DATE": "2025-12-31",
                        "ANNOUNCEMENT_DATE": "2026-03-31",
                        "TOTAL_OPERATING_REVENUE": "1,000",
                        "TOTAL_OPERATING_COST": 600,
                        "PARENT_NET_PROFIT": 200,
                        "IS_CONSOLIDATED": 1,
                        "IS_RESTATEMENT": 1,
                    }
                ]
            },
            "cninfo-financial-cashflow-a-share-600519": {
                "data": [
                    {
                        "REPORT_DATE": "2025-12-31",
                        "NET_CASH_FLOW_OPERATING": 180,
                    }
                ]
            },
        }
    )
    source = CninfoSource(
        client,  # type: ignore[arg-type]
        access_token="registered-token",
        income_api_url="https://webapi.cninfo.com.cn/api/registered/income",
        cashflow_api_url="https://webapi.cninfo.com.cn/api/registered/cashflow",
    )
    result = source.Financials_Fetch(security, {2025})
    assert result.value and result.value[0].revenue == 1000
    assert result.value[0].operating_cash_flow == 180
    assert result.value[0].is_consolidated is True
    assert result.value[0].is_restatement is True
    assert result.provenance.primary_source == source.source_name

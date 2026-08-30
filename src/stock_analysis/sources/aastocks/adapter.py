from __future__ import annotations

import html
import re
from datetime import date, datetime

from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.fields import FLOW_FIVE_DAY_FIELD, FLOW_ONE_MONTH_HK_FIELD
from stock_analysis.domain.models import BlockTradeData, FlowData, Quote, Security
from stock_analysis.sources.base import HttpJsonClient, Provenance_Create, SourceValue


class AastocksSource:
    source_name = "AASTOCKS"
    QUOTE_URL = "https://www.aastocks.com/pkages/web/bcomsec/eng/whatshot/quote_v2.asp"
    BLOCK_URL = "https://www.aastocks.com/en/stocks/analysis/blocktrade.aspx"
    FLOW_URL = "https://www.aastocks.com/en/stocks/analysis/moneyflow.aspx"

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        payload = self._client.RequestBytes(
            self.QUOTE_URL,
            params={"symbol": security.code},
            request_id=f"aastocks-quote-{security.code}",
            referer="https://www.aastocks.com/en/stocks/quote/quick-quote.aspx",
            endpoint_key=f"aastocks-quote-{security.code}",
        )
        text = html.unescape(payload.decode("utf-8", errors="replace"))
        date_match = re.search(
            r"Last\s+Updated:\s*(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}", text, re.I
        )
        price_match = re.search(
            r"Last\s+Price.*?<strong>\s*([\d,.]+)\s*</strong>", text, re.I | re.S
        )
        cap_match = re.search(
            r"Market\s+Capital\s*</td>\s*<td[^>]*>\s*([\d,.]+)\s*([KMBT]?)",
            text,
            re.I | re.S,
        )
        quote_date = (
            datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
            if date_match
            else None
        )
        price = self._ScaledNumber_Get(price_match.group(1), "") if price_match else None
        market_cap = (
            self._ScaledNumber_Get(cap_match.group(1), cap_match.group(2))
            if cap_match
            else None
        )
        if quote_date is None or (price is None and market_cap is None):
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    f"quote_v2.asp?symbol={security.code}",
                    DataStatus.MISSING,
                    standard_currency="HKD",
                    missing_reason="AASTOCKS 行情页没有可验证的行情日期或数值",
                    primary_source="东方财富",
                ),
            )
        return SourceValue(
            Quote(security.key, quote_date, price, market_cap, "HKD"),
            Provenance_Create(
                security,
                "最新行情",
                self.source_name,
                f"quote_v2.asp?symbol={security.code}（网页披露时间）",
                DataStatus.OK,
                original_currency="HKD",
                standard_currency="HKD",
                primary_source="东方财富",
            ),
        )

    def BlockTrade_Fetch(
        self, security: Security, year: int
    ) -> SourceValue[BlockTradeData]:
        payload = self._client.RequestBytes(
            self.BLOCK_URL,
            params={"symbol": security.code},
            request_id=f"aastocks-block-{security.code}-{year}",
            referer="https://www.aastocks.com/en/stocks/analysis/blocktrade.aspx",
            endpoint_key=f"aastocks-block-{security.code}",
            headers=self._PageHeaders_Get(security.code),
        )
        text = html.unescape(payload.decode("utf-8", errors="replace"))
        snapshot_date, snapshot_turnover = self._BlockSnapshot_Parse(text)
        if snapshot_date is None:
            missing_reason = "AASTOCKS 页面未返回可验证的 Block Trades 日期和统计"
            source_ref = f"blocktrade.aspx?symbol={security.code}"
        else:
            turnover_text = (
                f"，当日页面总成交口径={snapshot_turnover}"
                if snapshot_turnover
                else ""
            )
            missing_reason = (
                f"已解析 AASTOCKS {snapshot_date.isoformat()} 当日 Block Trades"
                f"{turnover_text}，但页面未提供 {year} 年完整区间，年度字段保持空白"
            )
            source_ref = (
                f"blocktrade.aspx?symbol={security.code}；"
                f"页面日期={snapshot_date.isoformat()}；目标年度={year}"
            )
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                source_ref,
                DataStatus.MISSING,
                standard_currency="HKD",
                missing_reason=missing_reason,
                primary_source=self.source_name,
                field_statuses={
                    "当年累计大宗交易笔数": DataStatus.MISSING,
                    "当年累计大宗交易金额": DataStatus.MISSING,
                },
            ),
        )

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        payload = self._client.RequestBytes(
            self.FLOW_URL,
            params={"symbol": security.code, "type": "h"},
            request_id=f"aastocks-flow-{security.code}",
            referer=(
                "https://www.aastocks.com/en/stocks/quote/quick-quote.aspx"
                f"?symbol={security.code}"
            ),
            endpoint_key=f"aastocks-flow-{security.code}",
            headers=self._PageHeaders_Get(security.code),
        )
        text = html.unescape(payload.decode("utf-8", errors="replace"))
        values = self._FlowHistory_Parse(text)
        if len(values) < 5:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    f"moneyflow.aspx?symbol={security.code}&type=h",
                    DataStatus.MISSING,
                    standard_currency="HKD",
                    missing_reason=(
                        f"AASTOCKS 历史页仅解析到 {len(values)} 个有效交易日，"
                        "不足 5 日"
                    ),
                    primary_source=self.source_name,
                    field_statuses={
                        FLOW_FIVE_DAY_FIELD: DataStatus.MISSING,
                        FLOW_ONE_MONTH_HK_FIELD: DataStatus.MISSING,
                    },
                ),
            )
        values.sort(key=lambda item: item[0])
        value = FlowData(
            security_key=security.key,
            end_date=values[-1][0],
            five_day_net=sum(amount for _day, amount in values[-5:]),
            one_month_net=None,
            currency="HKD",
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                (
                    f"moneyflow.aspx?symbol={security.code}&type=h；"
                    "Historical Money Flow Data (Last 5 trading days)，Overall"
                ),
                DataStatus.OK,
                original_currency="HKD",
                standard_currency="HKD",
                missing_reason=(
                    "AASTOCKS 公开历史页仅提供最近 5 个交易日；"
                    "已填写 5 日，20 日保持空白"
                ),
                primary_source=self.source_name,
                field_statuses={
                    FLOW_FIVE_DAY_FIELD: DataStatus.OK,
                    FLOW_ONE_MONTH_HK_FIELD: DataStatus.MISSING,
                },
            ),
        )

    @staticmethod
    def _PageHeaders_Get(code: str) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml",
            "Cookie": f"AALTP=1; MasterSymbol={code}; LatestRTQuotedStocks={code}",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
            ),
        }

    @classmethod
    def _FlowHistory_Parse(cls, text: str) -> list[tuple[date, float]]:
        section = re.search(
            r"Historical\s+Money\s+Flow\s+Data\s*"
            r"\(Last\s+5\s+trading\s+days\).*?<tbody>(.*?)</tbody>",
            text,
            re.I | re.S,
        )
        if section is None:
            return []
        result: list[tuple[date, float]] = []
        for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", section.group(1), re.I | re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.I | re.S)
            if len(cells) < 7:
                continue
            day_text = cls._HtmlText_Get(cells[0])
            amount_text = cls._HtmlText_Get(cells[5])
            try:
                parsed_day = datetime.strptime(day_text, "%Y/%m/%d").date()
            except ValueError:
                continue
            amount = cls._SignedScaledNumber_Get(amount_text)
            if amount is not None:
                result.append((parsed_day, amount))
        return result

    @staticmethod
    def _BlockSnapshot_Parse(text: str) -> tuple[date | None, str | None]:
        date_match = re.search(r"\btdate\s*:\s*['\"](\d{8})['\"]", text, re.I)
        stat_match = re.search(
            r"var\s+_stat\s*=\s*\{.*?\bturn\s*:\s*['\"]([^'\"]+)['\"]",
            text,
            re.I | re.S,
        )
        try:
            snapshot_date = (
                datetime.strptime(date_match.group(1), "%Y%m%d").date()
                if date_match
                else None
            )
        except ValueError:
            snapshot_date = None
        return snapshot_date, stat_match.group(1).strip() if stat_match else None

    @staticmethod
    def _HtmlText_Get(fragment: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()

    @classmethod
    def _SignedScaledNumber_Get(cls, value: str) -> float | None:
        text = value.strip().replace(",", "")
        match = re.fullmatch(r"([+-]?[\d.]+)\s*([KMBT]?)", text, re.I)
        if match is None:
            return None
        return cls._ScaledNumber_Get(match.group(1), match.group(2))

    @staticmethod
    def _ScaledNumber_Get(value: str, unit: str) -> float | None:
        try:
            number = float(value.replace(",", ""))
        except ValueError:
            return None
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(unit.upper(), 1.0)
        return number * multiplier

    def close(self) -> None:
        self._client.close()

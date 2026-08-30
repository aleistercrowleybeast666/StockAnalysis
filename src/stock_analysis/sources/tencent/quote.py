from __future__ import annotations

from datetime import date, datetime

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import FlowData, Quote, Security
from stock_analysis.sources.base import HttpJsonClient, Provenance_Create, SourceValue


class TencentQuoteSource:
    source_name = "腾讯行情"
    QUOTE_URL = "https://qt.gtimg.cn/q="

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    @staticmethod
    def _Symbol_Get(security: Security) -> str:
        if security.market is Market.HK:
            return f"r_hk{security.code}"
        prefix = "sh" if security.exchange == "SSE" else "bj" if security.exchange == "BSE" else "sz"
        return f"{prefix}{security.code}"

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        symbol = self._Symbol_Get(security)
        payload = self._client.RequestBytes(
            f"{self.QUOTE_URL}{symbol}",
            request_id=f"tencent-quote-{security.key}",
            referer="https://gu.qq.com/",
            endpoint_key=f"tencent-quote-{security.market.value}-{security.code}",
        )
        text = payload.decode("gb18030", errors="replace")
        body = text.split('="', 1)[-1].rsplit('"', 1)[0]
        fields = body.split("~")
        price = self._Number_Get(fields, 3)
        timestamp = fields[30].strip() if len(fields) > 30 else ""
        quote_date = None
        if len(timestamp) >= 8 and timestamp[:8].isdigit():
            quote_date = datetime.strptime(timestamp[:8], "%Y%m%d").date()
        market_cap_hundred_million = self._Number_Get(fields, 45)
        market_cap = (
            market_cap_hundred_million * 100_000_000
            if market_cap_hundred_million is not None
            else None
        )
        currency = "CNY" if security.market is Market.A_SHARE else "HKD"
        if quote_date is None or (price is None and market_cap is None):
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    f"qt.gtimg.cn {symbol}",
                    DataStatus.MISSING,
                    standard_currency=currency,
                    missing_reason="腾讯行情返回字段不完整",
                ),
            )
        return SourceValue(
            Quote(security.key, quote_date, price, market_cap, currency),
            Provenance_Create(
                security,
                "最新行情",
                self.source_name,
                f"qt.gtimg.cn {symbol}（最新价、真实行情时间、总市值）",
                DataStatus.OK,
                original_currency=currency,
                standard_currency=currency,
                primary_source="东方财富",
            ),
        )

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        if security.market is not Market.A_SHARE:
            raise ValueError("腾讯 5 日资金流备源仅用于 A 股")
        symbol = self._Symbol_Get(security)
        payload = self._client.RequestBytes(
            f"{self.QUOTE_URL}ff_{symbol}",
            request_id=f"tencent-flow-{security.code}",
            referer=f"https://gu.qq.com/{symbol}",
            endpoint_key=f"tencent-flow-a-share-{security.code}",
        )
        text = payload.decode("gb18030", errors="replace")
        body = text.split('="', 1)[-1].rsplit('"', 1)[0]
        fields = body.split("~")
        values: list[tuple[date, float]] = []
        current_amount = self._Number_Get(fields, 3)
        current_date = self._CompactDate_Parse(fields[13] if len(fields) > 13 else "")
        if current_amount is not None and current_date is not None:
            values.append((current_date, current_amount * 10_000))
        for item in fields[14:]:
            parts = item.split("^")
            if len(parts) < 3:
                continue
            item_date = self._CompactDate_Parse(parts[0])
            try:
                inflow = float(parts[1].replace(",", ""))
                outflow = float(parts[2].replace(",", ""))
            except ValueError:
                continue
            if item_date is not None:
                values.append((item_date, (inflow - outflow) * 10_000))
        values = sorted(dict(values).items())
        if len(values) < 5:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    f"qt.gtimg.cn q=ff_{symbol}",
                    DataStatus.MISSING,
                    standard_currency="CNY",
                    missing_reason=f"腾讯资金流仅解析到 {len(values)} 个有效交易日",
                    primary_source="东方财富",
                    field_statuses={
                        "近五个交易日资金净额": DataStatus.MISSING,
                        "近一月资金净额（最近22个交易日）": DataStatus.MISSING,
                    },
                ),
            )
        value = FlowData(
            security_key=security.key,
            end_date=values[-1][0],
            five_day_net=sum(amount for _day, amount in values[-5:]),
            one_month_net=None,
            currency="CNY",
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                f"qt.gtimg.cn q=ff_{symbol}（主力流入减主力流出，5 日）",
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                missing_reason="腾讯公开接口仅提供最近 5 个交易日；22 日字段留空",
                primary_source="东方财富",
                field_statuses={
                    "近五个交易日资金净额": DataStatus.OK,
                    "近一月资金净额（最近22个交易日）": DataStatus.MISSING,
                },
            ),
        )

    @staticmethod
    def _CompactDate_Parse(value: str) -> date | None:
        text = str(value).strip()
        if len(text) < 8 or not text[:8].isdigit():
            return None
        try:
            return datetime.strptime(text[:8], "%Y%m%d").date()
        except ValueError:
            return None

    @staticmethod
    def _Number_Get(fields: list[str], index: int) -> float | None:
        if index >= len(fields):
            return None
        try:
            return float(fields[index].replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    def close(self) -> None:
        self._client.close()

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from stock_analysis.common.paths import Resources_GetPath
from stock_analysis.domain.calculations import Calculation_IssueMarketCap
from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import (
    BlockTradeData,
    FinancialPeriod,
    FlowData,
    IPOInfo,
    Quote,
    Security,
)
from stock_analysis.sources.base import MarketDataSource, Provenance_Create, SourceValue


class FixtureSource(MarketDataSource):
    source_name = "内置测试数据"

    def __init__(self, fixture_path: Path | None = None) -> None:
        path = fixture_path or Resources_GetPath("fixtures/market_data.json")
        self._data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    def SecurityList_Fetch(self, market: Market, limit: int = 0) -> list[Security]:
        result = [
            self._Security_FromRow(market, row)
            for row in self._data["securities"][market.value]
        ]
        return result[:limit] if limit > 0 else result

    @staticmethod
    def _Security_FromRow(market: Market, row: dict[str, Any]) -> Security:
        return Security(
            market=market,
            exchange=row["exchange"],
            code=row["code"],
            name=row["name"],
            listing_date=date.fromisoformat(row["listing_date"])
            if row.get("listing_date")
            else None,
            is_st=bool(row.get("is_st", False)),
            is_financial=bool(row.get("is_financial", False)),
            industry=row.get("industry"),
            board=row.get("board"),
            concepts=tuple(str(item) for item in row.get("concepts", [])),
            legacy_codes=tuple(str(item) for item in row.get("legacy_codes", [])),
        )

    def Financials_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]:
        periods = []
        for row in self._data["financials"].get(security.key, []):
            if int(row["fiscal_year"]) not in years:
                continue
            periods.append(
                FinancialPeriod(
                    security_key=security.key,
                    report_end=date.fromisoformat(row["report_end"]),
                    fiscal_year=int(row["fiscal_year"]),
                    announcement_date=(
                        date.fromisoformat(row["announcement_date"])
                        if row.get("announcement_date")
                        else None
                    ),
                    currency=row["currency"],
                    revenue=row.get("revenue"),
                    operating_cost=row.get("operating_cost"),
                    parent_net_profit=row.get("parent_net_profit"),
                    operating_cash_flow=row.get("operating_cash_flow"),
                    original_currency=row.get("original_currency", row["currency"]),
                    fx_rate=row.get("fx_rate"),
                    fx_date=date.fromisoformat(row["fx_date"]) if row.get("fx_date") else None,
                )
            )
        status = DataStatus.OK if periods else DataStatus.MISSING
        return SourceValue(
            periods,
            Provenance_Create(
                security,
                "年度财务",
                self.source_name,
                "resources/fixtures/market_data.json",
                status,
                original_currency=periods[0].original_currency if periods else None,
                standard_currency="CNY" if security.market is Market.A_SHARE else "HKD",
                missing_reason=None if periods else "fixture 中没有目标年度",
            ),
        )

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        row = self._data["quotes"].get(security.key)
        value = (
            Quote(
                security_key=security.key,
                quote_date=date.fromisoformat(row["quote_date"]),
                price=row.get("price"),
                market_cap=row.get("market_cap"),
                currency=row["currency"],
            )
            if row
            else None
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "最新行情",
                self.source_name,
                "resources/fixtures/market_data.json",
                DataStatus.OK if value else DataStatus.MISSING,
                original_currency=row["currency"] if row else None,
                standard_currency=row["currency"] if row else None,
                missing_reason=None if value else "fixture 行情缺失",
            ),
        )

    def IPO_Fetch(self, security: Security) -> SourceValue[IPOInfo]:
        row = self._data["ipo"].get(security.key)
        calculated_market_cap = None
        if row:
            calculated_market_cap, _approximate = Calculation_IssueMarketCap(
                row.get("issue_price"), row.get("post_issue_total_shares"), None
            )
        value = (
            IPOInfo(
                security_key=security.key,
                listing_date=date.fromisoformat(row["listing_date"])
                if row.get("listing_date")
                else None,
                issue_price=row.get("issue_price"),
                issued_shares=row.get("issued_shares"),
                post_issue_total_shares=row.get("post_issue_total_shares"),
                issue_market_cap=calculated_market_cap,
                approximate=False,
            )
            if row
            else None
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                "resources/fixtures/market_data.json",
                DataStatus.OK if value else DataStatus.MISSING,
                missing_reason=None if value else "fixture 发行信息缺失",
                approximate=value.approximate if value else False,
            ),
        )

    def BlockTrade_Fetch(
        self, security: Security, year: int
    ) -> SourceValue[BlockTradeData]:
        row = self._data["block_trades"].get(security.key)
        currency = "CNY" if security.market is Market.A_SHARE else "HKD"
        value = BlockTradeData(
            security_key=security.key,
            year=year,
            trade_count=int(row.get("trade_count") or 0) if row else 0,
            total_amount=float(row.get("total_amount") or 0.0) if row else 0.0,
            currency=str(row.get("currency") or currency) if row else currency,
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                "resources/fixtures/market_data.json",
                DataStatus.OK,
            ),
        )

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        row = self._data["flows"].get(security.key)
        quote_row = self._data["quotes"].get(security.key) or {}
        currency = "CNY" if security.market is Market.A_SHARE else "HKD"
        value = (
            FlowData(
                security_key=security.key,
                end_date=date.fromisoformat(row["end_date"]),
                five_day_net=row.get("five_day_net"),
                one_month_net=row.get("one_month_net"),
                currency=row["currency"],
            )
            if row
            else FlowData(
                security_key=security.key,
                end_date=date.fromisoformat(quote_row.get("quote_date", "2026-08-28")),
                five_day_net=0.0,
                one_month_net=0.0,
                currency=currency,
            )
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                "resources/fixtures/market_data.json",
                DataStatus.OK,
            ),
        )

    def Flows_FetchFast(
        self, securities: Sequence[Security]
    ) -> dict[str, SourceValue[FlowData]]:
        return {security.key: self.Flow_Fetch(security) for security in securities}

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from typing import Any, TypeVar

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import (
    BlockTradeData,
    FinancialPeriod,
    FlowData,
    IPOInfo,
    Provenance,
    Quote,
    Security,
)

T = TypeVar("T")


def Model_Encode(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [Model_Encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): Model_Encode(item) for key, item in value.items()}
    return Model_Encode(asdict(value))


def Security_Decode(data: dict[str, Any]) -> Security:
    return Security(
        market=Market(data["market"]),
        exchange=data["exchange"],
        code=data["code"],
        name=data["name"],
        security_type=data.get("security_type", "普通股"),
        listing_status=data.get("listing_status", "上市"),
        listing_date=date.fromisoformat(data["listing_date"])
        if data.get("listing_date")
        else None,
        is_st=bool(data.get("is_st", False)),
        is_financial=bool(data.get("is_financial", False)),
        industry=data.get("industry"),
        board=data.get("board"),
        concepts=tuple(str(item) for item in data.get("concepts", []) if str(item).strip()),
        legacy_codes=tuple(
            str(item) for item in data.get("legacy_codes", []) if str(item).strip()
        ),
    )


def FinancialPeriod_Decode(data: dict[str, Any]) -> FinancialPeriod:
    return FinancialPeriod(
        security_key=data["security_key"],
        report_end=date.fromisoformat(data["report_end"]),
        fiscal_year=int(data["fiscal_year"]),
        announcement_date=date.fromisoformat(data["announcement_date"])
        if data.get("announcement_date")
        else None,
        currency=data["currency"],
        revenue=data.get("revenue"),
        operating_cost=data.get("operating_cost"),
        parent_net_profit=data.get("parent_net_profit"),
        operating_cash_flow=data.get("operating_cash_flow"),
        original_currency=data.get("original_currency"),
        fx_rate=data.get("fx_rate"),
        fx_date=date.fromisoformat(data["fx_date"]) if data.get("fx_date") else None,
        is_consolidated=data.get("is_consolidated"),
        is_restatement=data.get("is_restatement"),
        quality_note=data.get("quality_note"),
    )


def Quote_Decode(data: dict[str, Any]) -> Quote:
    return Quote(
        security_key=data["security_key"],
        quote_date=date.fromisoformat(data["quote_date"]),
        price=data.get("price"),
        market_cap=data.get("market_cap"),
        currency=data["currency"],
    )


def IPO_Decode(data: dict[str, Any]) -> IPOInfo:
    return IPOInfo(
        security_key=data["security_key"],
        listing_date=date.fromisoformat(data["listing_date"])
        if data.get("listing_date")
        else None,
        issue_price=data.get("issue_price"),
        issued_shares=data.get("issued_shares"),
        post_issue_total_shares=data.get("post_issue_total_shares"),
        issue_market_cap=data.get("issue_market_cap"),
        approximate=bool(data.get("approximate", False)),
    )


def BlockTrade_Decode(data: dict[str, Any]) -> BlockTradeData:
    return BlockTradeData(
        security_key=data["security_key"],
        year=int(data["year"]),
        trade_count=data.get("trade_count"),
        total_amount=data.get("total_amount"),
        currency=data["currency"],
    )


def Flow_Decode(data: dict[str, Any]) -> FlowData:
    return FlowData(
        security_key=data["security_key"],
        end_date=date.fromisoformat(data["end_date"]),
        five_day_net=data.get("five_day_net"),
        one_month_net=data.get("one_month_net"),
        currency=data["currency"],
    )


def Provenance_Decode(data: dict[str, Any]) -> Provenance:
    return Provenance(
        market=Market(data["market"]),
        code=data["code"],
        company_name=data["company_name"],
        field_group=data["field_group"],
        source_name=data["source_name"],
        source_ref=data["source_ref"],
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        original_currency=data.get("original_currency"),
        standard_currency=data.get("standard_currency"),
        status=DataStatus(data["status"]),
        missing_reason=data.get("missing_reason"),
        approximate=bool(data.get("approximate", False)),
        primary_source=data.get("primary_source"),
    )

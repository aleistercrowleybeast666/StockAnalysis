from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.models import FlowData, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceSchemaError,
    SourceValue,
)


class TradegoSource:
    """TradeGo public five-trading-day HK money-flow ranking."""

    source_name = "TradeGo 港股资金流"
    FLOW_URL = "https://data.tradego8.com/RDS.aspx"
    _WINDOWS = {5: 153}

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    def Flows_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date,
    ) -> dict[str, SourceValue[FlowData]]:
        securities_by_code = {security.code.zfill(5): security for security in securities}
        five_day = self._Window_Fetch(5, set(securities_by_code))
        results: dict[str, SourceValue[FlowData]] = {}
        for code, security in securities_by_code.items():
            five_value = five_day.get(code)
            if five_value is None:
                results[security.key] = SourceValue(
                    None,
                    Provenance_Create(
                        security,
                        "资金流",
                        self.source_name,
                        "RDS.aspx PkgType=12012（5 日公开排行）",
                        DataStatus.MISSING,
                        standard_currency="HKD",
                        missing_reason="公开排行未返回该港股代码",
                        field_statuses={
                            "近五个交易日资金净额": DataStatus.MISSING,
                            "近一月资金净额（最近22个交易日）": DataStatus.MISSING,
                        },
                    ),
                )
                continue
            value = FlowData(
                security_key=security.key,
                end_date=as_of_date,
                five_day_net=five_value,
                # 公开源只有 20 日口径，不能写入明确标为 22 日的列。
                one_month_net=None,
                currency="HKD",
            )
            results[security.key] = SourceValue(
                value,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    (
                        "RDS.aspx PkgType=12012，5 日 NetIn；"
                        f"截止日按本次港股行情日 {as_of_date.isoformat()} 对齐"
                    ),
                    DataStatus.OK,
                    original_currency="HKD",
                    standard_currency="HKD",
                    missing_reason=(
                        "该公开源只披露 20 日口径，不能冒充最近 22 个交易日；"
                        "因此 22 日字段留空"
                    ),
                    approximate=False,
                    field_statuses={
                        "近五个交易日资金净额": (
                            DataStatus.OK if five_value is not None else DataStatus.MISSING
                        ),
                        "近一月资金净额（最近22个交易日）": DataStatus.MISSING,
                    },
                ),
            )
        return results

    def _Window_Fetch(self, days: int, wanted_codes: set[str]) -> dict[str, float]:
        sort_id = self._WINDOWS[days]
        results: dict[str, float] = {}
        page_size = 2000
        for offset in range(0, 6000, page_size):
            payload = self._client.RequestJson(
                self.FLOW_URL,
                params={
                    "code": f"{days}.{page_size}.0.{offset}.{sort_id}",
                    "PkgType": 12012,
                    "val": 1,
                },
                request_id=f"tradego-hk-flow-{days}-offset-{offset}",
                referer=(
                    "https://data.tradego8.com/indices/"
                    f"MF_His_stock.aspx?Time={days}&A=0&T={sort_id}"
                ),
                endpoint_key=f"tradego-hk-flow-{days}-day",
            )
            rows = payload.get("His")
            if not isinstance(rows, list):
                raise SourceSchemaError("TradeGo 港股资金流响应缺少 His 数组")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = self._Code_Normalize(row.get("_Code"))
                if code not in wanted_codes:
                    continue
                amount = self._Amount_Parse(row.get("NetIn"))
                if amount is not None:
                    results[code] = amount
            if wanted_codes <= results.keys() or len(rows) < page_size:
                break
        return results

    @staticmethod
    def _Code_Normalize(value: object) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        return digits.zfill(5) if digits else ""

    @staticmethod
    def _Amount_Parse(value: object) -> float | None:
        text = str(value or "").strip().replace(",", "")
        match = re.fullmatch(r"([+-]?[\d.]+)\s*([KMBT]?)", text, re.I)
        if match is None:
            return None
        try:
            number = float(match.group(1))
        except ValueError:
            return None
        multiplier = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
        return number * multiplier[match.group(2).upper()]

    def close(self) -> None:
        self._client.close()

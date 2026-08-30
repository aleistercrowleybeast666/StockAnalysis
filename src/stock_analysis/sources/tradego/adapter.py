from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.fields import FLOW_FIVE_DAY_FIELD, FLOW_ONE_MONTH_HK_FIELD
from stock_analysis.domain.models import FlowData, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceError,
    SourceSchemaError,
    SourceValue,
)


class TradegoSource:
    """TradeGo public 5/20-trading-day HK money-flow rankings."""

    source_name = "TradeGo 港股资金流"
    FLOW_URL = "https://data.tradego8.com/RDS.aspx"
    _WINDOWS = {5: 153, 20: 153}

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    def Flows_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date,
    ) -> dict[str, SourceValue[FlowData]]:
        securities_by_code = {security.code.zfill(5): security for security in securities}
        wanted_codes = set(securities_by_code)
        window_values: dict[int, dict[str, float]] = {}
        window_errors: dict[int, str] = {}
        for days in self._WINDOWS:
            try:
                window_values[days] = self._Window_Fetch(days, wanted_codes)
            except SourceError as error:
                window_values[days] = {}
                window_errors[days] = str(error)
        if len(window_errors) == len(self._WINDOWS):
            raise SourceError(
                "TradeGo 5/20 日资金流均不可用："
                + "；".join(
                    f"{days} 日={reason}" for days, reason in window_errors.items()
                )
            )
        results: dict[str, SourceValue[FlowData]] = {}
        for code, security in securities_by_code.items():
            five_value = window_values[5].get(code)
            twenty_value = window_values[20].get(code)
            if five_value is None and twenty_value is None:
                results[security.key] = SourceValue(
                    None,
                    Provenance_Create(
                        security,
                        "资金流",
                        self.source_name,
                        "RDS.aspx PkgType=12012（5/20 日公开排行）",
                        DataStatus.MISSING,
                        standard_currency="HKD",
                        missing_reason=(
                            "公开 5/20 日排行均未返回该港股代码"
                            + (
                                "；" + "；".join(
                                    f"{days} 日请求失败：{reason}"
                                    for days, reason in window_errors.items()
                                )
                                if window_errors
                                else ""
                            )
                        ),
                        field_statuses={
                            FLOW_FIVE_DAY_FIELD: DataStatus.MISSING,
                            FLOW_ONE_MONTH_HK_FIELD: DataStatus.MISSING,
                        },
                    ),
                )
                continue
            value = FlowData(
                security_key=security.key,
                end_date=as_of_date,
                five_day_net=five_value,
                one_month_net=twenty_value,
                currency="HKD",
            )
            results[security.key] = SourceValue(
                value,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    (
                        "RDS.aspx PkgType=12012，5 日/20 日 NetIn；"
                        f"截止日按本次港股行情日 {as_of_date.isoformat()} 对齐"
                    ),
                    DataStatus.OK,
                    original_currency="HKD",
                    standard_currency="HKD",
                    missing_reason=(
                        "；".join(
                            f"{days} 日请求失败：{reason}"
                            for days, reason in window_errors.items()
                        )
                        or (
                            "未取得字段："
                            + "、".join(
                                field
                                for field, item in (
                                    (FLOW_FIVE_DAY_FIELD, five_value),
                                    (FLOW_ONE_MONTH_HK_FIELD, twenty_value),
                                )
                                if item is None
                            )
                            if five_value is None or twenty_value is None
                            else None
                        )
                    ),
                    approximate=False,
                    field_statuses={
                        FLOW_FIVE_DAY_FIELD: (
                            DataStatus.OK if five_value is not None else DataStatus.MISSING
                        ),
                        FLOW_ONE_MONTH_HK_FIELD: (
                            DataStatus.OK
                            if twenty_value is not None
                            else DataStatus.MISSING
                        ),
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

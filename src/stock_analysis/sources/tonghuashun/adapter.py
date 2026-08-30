from __future__ import annotations

import json
import re
from datetime import date, datetime

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import FlowData, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceValue,
)
from stock_analysis.sources.parsers import Parser_ParseHtmlTable


class TonghuashunSource:
    source_name = "同花顺"
    EQUITY_URL = "https://basic.10jqka.com.cn/{code}/equity.html"
    FLOW_URL = "https://doctor.10jqka.com.cn/{code}/"

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    def close(self) -> None:
        self._client.close()

    def PostIssueShares_Fetch(
        self, security: Security, listing_date: date | None
    ) -> SourceValue[float]:
        if security.market is not Market.A_SHARE or listing_date is None:
            return self._Missing_Create(
                security,
                "仅对已知上市日期的 A 股查询同花顺历次股本变动",
            )
        url = self.EQUITY_URL.format(code=security.code)
        payload = self._client.RequestBytes(
            url,
            request_id=f"tonghuashun-equity-{security.code}",
            referer=f"https://basic.10jqka.com.cn/{security.code}/",
            endpoint_key="tonghuashun-equity-a-share",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
                ),
            },
        )
        text = payload.decode("gb18030", errors="replace")
        shares = self._PostIssueShares_Parse(text, listing_date)
        if shares is None:
            return self._Missing_Create(
                security,
                f"同花顺历次股本变动未找到 {listing_date.isoformat()} 的 A股上市总股本",
            )
        return SourceValue(
            shares,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                (
                    f"{url}；历次股本变动；上市日={listing_date.isoformat()}；"
                    "页面披露单位换算"
                ),
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                approximate=True,
                primary_source="东方财富",
                field_statuses={"发行后总股本": DataStatus.OK},
            ),
        )

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        if security.market is not Market.A_SHARE:
            return self._FlowMissing_Create(security, "同花顺该适配器仅用于 A 股资金流")
        url = self.FLOW_URL.format(code=security.code)
        payload = self._client.RequestBytes(
            url,
            request_id=f"tonghuashun-flow-{security.code}",
            referer=f"https://stockpage.10jqka.com.cn/{security.code}/Funds/",
            endpoint_key="tonghuashun-doctor-flow-a-share",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
                ),
            },
        )
        text = payload.decode("gb18030", errors="replace")
        values = self._FlowHistory_Parse(text)
        if len(values) < 5:
            return self._FlowMissing_Create(
                security,
                f"同花顺资金面公开页仅解析到 {len(values)} 个有效交易日",
            )
        five_day_net = sum(amount for _day, amount in values[-5:])
        one_month_net = (
            sum(amount for _day, amount in values[-22:])
            if len(values) >= 22
            else None
        )
        field_statuses = {
            "近五个交易日资金净额": DataStatus.OK,
            "近一月资金净额（最近22个交易日）": (
                DataStatus.OK if one_month_net is not None else DataStatus.MISSING
            ),
        }
        missing_reason = (
            None
            if one_month_net is not None
            else f"同花顺资金面公开页仅提供 {len(values)} 个有效交易日，22 日字段留空"
        )
        return SourceValue(
            FlowData(
                security_key=security.key,
                end_date=values[-1][0],
                five_day_net=five_day_net,
                one_month_net=one_month_net,
                currency="CNY",
            ),
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                (
                    f"{url}；资金面诊股每日资金净值；"
                    f"截止={values[-1][0].isoformat()}；页面单位=万元"
                ),
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                missing_reason=missing_reason,
                primary_source="东方财富",
                field_statuses=field_statuses,
            ),
        )

    @classmethod
    def _PostIssueShares_Parse(cls, text: str, listing_date: date) -> float | None:
        target_date = listing_date.isoformat()
        for row in Parser_ParseHtmlTable(text):
            if len(row) < 3 or row[0].strip() != target_date:
                continue
            reason = re.sub(r"\s+", "", row[1])
            if "A股上市" not in reason and not ("首发" in reason and "上市" in reason):
                continue
            shares = cls._ShareValue_Parse(row[2])
            if shares is not None and shares > 0:
                return shares
        return None

    @staticmethod
    def _ShareValue_Parse(value: str) -> float | None:
        text = re.sub(r"[\s,，]", "", str(value))
        match = re.fullmatch(r"([+-]?[\d.]+)(亿|万|股)?", text)
        if match is None:
            return None
        try:
            number = float(match.group(1))
        except ValueError:
            return None
        multiplier = {"亿": 100_000_000.0, "万": 10_000.0, "股": 1.0, None: 1.0}
        return number * multiplier[match.group(2)]

    @staticmethod
    def _FlowHistory_Parse(text: str) -> list[tuple[date, float]]:
        candidates: list[list[tuple[date, float]]] = []
        for array_text in re.findall(r"\[[^\[\]]*\]", text, re.S):
            if '"date"' not in array_text or '"field"' not in array_text:
                continue
            try:
                items = json.loads(array_text)
            except (TypeError, ValueError):
                continue
            if not isinstance(items, list):
                continue
            parsed: dict[date, float] = {}
            for item in items:
                if not isinstance(item, dict) or "field" not in item:
                    continue
                try:
                    item_date = datetime.strptime(
                        str(item.get("date") or ""), "%Y-%m-%d"
                    ).date()
                    amount_wan = float(item.get("value"))
                except (TypeError, ValueError):
                    continue
                parsed[item_date] = amount_wan * 10_000.0
            if len(parsed) >= 5:
                candidates.append(sorted(parsed.items()))
        if not candidates:
            return []
        return max(candidates, key=lambda values: (values[-1][0], len(values)))

    def _Missing_Create(self, security: Security, reason: str) -> SourceValue[float]:
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                f"basic.10jqka.com.cn/{security.code}/equity.html",
                DataStatus.MISSING,
                standard_currency="CNY",
                missing_reason=reason,
                primary_source="东方财富",
                field_statuses={"发行后总股本": DataStatus.MISSING},
            ),
        )

    def _FlowMissing_Create(
        self, security: Security, reason: str
    ) -> SourceValue[FlowData]:
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                f"doctor.10jqka.com.cn/{security.code}/",
                DataStatus.MISSING,
                standard_currency="CNY",
                missing_reason=reason,
                primary_source="东方财富",
                field_statuses={
                    "近五个交易日资金净额": DataStatus.MISSING,
                    "近一月资金净额（最近22个交易日）": DataStatus.MISSING,
                },
            ),
        )

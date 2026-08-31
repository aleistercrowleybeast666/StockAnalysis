from __future__ import annotations

import json
import re
from datetime import date, datetime

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import FlowData, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceError,
    SourceSchemaError,
    SourceValue,
)
from stock_analysis.sources.normalization import Security_ConceptsNormalize
from stock_analysis.sources.parsers import Parser_ParseHtmlTable


class TonghuashunSource:
    source_name = "同花顺"
    EQUITY_URL = "https://basic.10jqka.com.cn/{code}/equity.html"
    FLOW_URL = "https://f10.10jqka.com.cn/{code}/funds/"
    CONCEPT_URL = (
        "https://stockpage.10jqka.com.cn/stock_page/api/v1/"
        "stockpage/company/profile"
    )

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
        missing_results: list[SourceValue[FlowData]] = []
        errors: list[str] = []
        for request_code in self._RequestCodes_Get(security):
            try:
                result = self._FlowCode_Fetch(security, request_code)
            except SourceError as error:
                errors.append(f"{request_code}：{error}")
                continue
            if result.value is not None:
                return result
            missing_results.append(result)
        reasons = [
            (
                f"{result.provenance.source_ref}："
                f"{result.provenance.missing_reason or '未返回有效资金流'}"
            )
            for result in missing_results
        ]
        reasons.extend(errors)
        if not missing_results:
            raise SourceError("；".join(reasons) or "同花顺资金流查询失败")
        return self._FlowMissing_Create(
            security,
            "当前代码及北交所官方旧代码均无有效历史；" + "；".join(reasons),
        )

    def _FlowCode_Fetch(
        self, security: Security, request_code: str
    ) -> SourceValue[FlowData]:
        url = self.FLOW_URL.format(code=request_code)
        request_id = (
            f"tonghuashun-flow-{security.code}"
            if request_code == security.code
            else f"tonghuashun-flow-{security.code}-via-{request_code}"
        )
        payload = self._client.RequestBytes(
            url,
            request_id=request_id,
            referer=f"https://stockpage.10jqka.com.cn/{request_code}/funds/",
            endpoint_key="tonghuashun-f10-funds-a-share",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
                ),
            },
        )
        text = payload.decode("utf-8", errors="replace")
        values = self._FlowHistory_Parse(text)
        if len(values) < 5:
            return self._FlowMissing_Create(
                security,
                f"同花顺资金面公开页仅解析到 {len(values)} 个有效交易日",
                request_code=request_code,
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
                    f"{url}；历史资金数据一览；"
                    f"截止={values[-1][0].isoformat()}；页面单位=万元"
                    + (
                        f"；北交所官方新旧代码映射={security.code}->{request_code}"
                        if request_code != security.code
                        else ""
                    )
                ),
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                missing_reason=missing_reason,
                primary_source="东方财富",
                field_statuses=field_statuses,
            ),
        )

    def Concepts_Fetch(self, security: Security) -> SourceValue[tuple[str, ...]]:
        if security.market is not Market.A_SHARE:
            return self._ConceptsMissing_Create(security, "同花顺概念仅用于 A 股")
        missing_results: list[SourceValue[tuple[str, ...]]] = []
        errors: list[str] = []
        for request_code in self._RequestCodes_Get(security):
            try:
                result = self._ConceptsCode_Fetch(security, request_code)
            except SourceError as error:
                errors.append(f"{request_code}：{error}")
                continue
            if result.value:
                return result
            missing_results.append(result)
        reasons = [
            result.provenance.missing_reason or "未返回常规概念"
            for result in missing_results
        ]
        reasons.extend(errors)
        if not missing_results:
            raise SourceError("；".join(reasons) or "同花顺概念查询失败")
        return self._ConceptsMissing_Create(
            security,
            "当前代码及北交所官方旧代码均无有效概念；" + "；".join(reasons),
        )

    def _ConceptsCode_Fetch(
        self, security: Security, request_code: str
    ) -> SourceValue[tuple[str, ...]]:
        market_id = self._MarketId_Get(security, request_code)
        request_id = (
            f"tonghuashun-concepts-{security.code}"
            if request_code == security.code
            else f"tonghuashun-concepts-{security.code}-via-{request_code}"
        )
        payload = self._client.RequestJson(
            self.CONCEPT_URL,
            params={"code": request_code, "marketId": market_id},
            request_id=request_id,
            referer=(
                f"https://stockpage.10jqka.com.cn/{request_code}/corporate-profile/"
            ),
            endpoint_key="tonghuashun-company-profile-concepts-a-share",
            headers={
                "Accept": "application/json,text/plain,*/*",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
                ),
            },
        )
        data = payload.get("data")
        concept_info = data.get("conceptInfo") if isinstance(data, dict) else None
        rows = concept_info.get("concepts") if isinstance(concept_info, dict) else None
        values = Security_ConceptsNormalize(
            [
                str(row.get("conceptName") or "")
                for row in rows or []
                if isinstance(row, dict)
            ]
        )
        if not values:
            return self._ConceptsMissing_Create(
                security,
                "同花顺公司资料接口未返回常规概念",
                request_code=request_code,
            )
        return SourceValue(
            values,
            Provenance_Create(
                security,
                "概念",
                self.source_name,
                (
                    "stock_page/api/v1/stockpage/company/profile；"
                    f"查询代码={request_code}；marketId={market_id}；"
                    "conceptInfo.concepts"
                    + (
                        f"；北交所官方新旧代码映射={security.code}->{request_code}"
                        if request_code != security.code
                        else ""
                    )
                ),
                DataStatus.OK,
                primary_source=self.source_name,
                field_statuses={"概念": DataStatus.OK},
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
    def _RequestCodes_Get(security: Security) -> tuple[str, ...]:
        result = [security.code]
        for code in security.legacy_codes:
            normalized = str(code).strip()
            if (
                len(normalized) == 6
                and normalized.isdigit()
                and normalized not in result
            ):
                result.append(normalized)
        return tuple(result)

    @staticmethod
    def _MarketId_Get(security: Security, request_code: str | None = None) -> str:
        if security.exchange == "SSE":
            return "17"
        if security.exchange == "SZSE":
            return "33"
        code = request_code or security.code
        return "151" if code.startswith("92") else "145"

    @staticmethod
    def _FlowHistory_Parse(text: str) -> list[tuple[date, float]]:
        table_values: dict[date, float] = {}
        try:
            table_rows = Parser_ParseHtmlTable(text)
        except SourceSchemaError:
            table_rows = []
        for row in table_rows:
            if len(row) < 5:
                continue
            day_text = re.sub(r"\D", "", row[0])
            if len(day_text) != 8:
                continue
            try:
                item_date = datetime.strptime(day_text, "%Y%m%d").date()
                amount_wan = float(row[3].replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            table_values[item_date] = amount_wan * 10_000.0
        if len(table_values) >= 5:
            return sorted(table_values.items())

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
        self,
        security: Security,
        reason: str,
        *,
        request_code: str | None = None,
    ) -> SourceValue[FlowData]:
        code = request_code or security.code
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                f"f10.10jqka.com.cn/{code}/funds/",
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

    def _ConceptsMissing_Create(
        self,
        security: Security,
        reason: str,
        *,
        request_code: str | None = None,
    ) -> SourceValue[tuple[str, ...]]:
        code = request_code or security.code
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "概念",
                self.source_name,
                (
                    "stock_page/api/v1/stockpage/company/profile；"
                    f"查询代码={code}；marketId={self._MarketId_Get(security, code)}"
                ),
                DataStatus.MISSING,
                missing_reason=reason,
                primary_source=self.source_name,
                field_statuses={"概念": DataStatus.MISSING},
            ),
        )

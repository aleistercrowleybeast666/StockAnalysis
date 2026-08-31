from __future__ import annotations

import json
import re
from datetime import date, datetime

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.fields import FLOW_FIVE_DAY_FIELD, FLOW_ONE_MONTH_A_FIELD
from stock_analysis.domain.models import FlowData, Quote, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceSchemaError,
    SourceValue,
)
from stock_analysis.sources.normalization import Security_ConceptsNormalize
from stock_analysis.sources.parsers import Parser_ParseHtmlTable


class SinaSource:
    source_name = "新浪财经"
    QUOTE_URL = "https://hq.sinajs.cn/list="
    FLOW_URL = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "MoneyFlow.ssl_qsfx_zjlrqs"
    )
    RELATED_URL = (
        "https://vip.stock.finance.sina.com.cn/corp/go.php/"
        "vCI_CorpXiangGuan/stockid/{code}.phtml"
    )

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    @staticmethod
    def _Symbol_Get(security: Security) -> str:
        prefix = (
            "sh"
            if security.exchange == "SSE"
            else "bj"
            if security.exchange == "BSE"
            else "sz"
        )
        return f"{prefix}{security.code}"

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        symbol = self._Symbol_Get(security)
        payload = self._client.RequestBytes(
            f"{self.QUOTE_URL}{symbol}",
            request_id=f"sina-quote-{security.code}",
            referer="https://finance.sina.com.cn/",
            endpoint_key="sina-quote-a-share",
            headers={"Accept": "text/plain,*/*"},
        )
        text = payload.decode("gb18030", errors="replace")
        body_match = re.search(r'=\s*"([^"]*)"', text)
        fields = body_match.group(1).split(",") if body_match else []
        price = self._Number_Get(fields, 3)
        quote_date = None
        if len(fields) > 30:
            try:
                quote_date = datetime.strptime(fields[30].strip(), "%Y-%m-%d").date()
            except ValueError:
                quote_date = None
        if quote_date is None or price is None:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    f"hq.sinajs.cn/list={symbol}",
                    DataStatus.MISSING,
                    standard_currency="CNY",
                    missing_reason="新浪行情没有返回可验证的最新价或交易日期",
                    primary_source="东方财富",
                    field_statuses={
                        "最新可得价格": DataStatus.MISSING,
                        "行情日期": DataStatus.MISSING,
                    },
                ),
            )
        return SourceValue(
            Quote(security.key, quote_date, price, None, "CNY"),
            Provenance_Create(
                security,
                "最新行情",
                self.source_name,
                f"hq.sinajs.cn/list={symbol}（最新价、交易日期）",
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                primary_source="东方财富",
                field_statuses={
                    "最新可得价格": DataStatus.OK,
                    "最新总市值": DataStatus.MISSING,
                    "行情日期": DataStatus.OK,
                },
            ),
        )

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        if security.market is not Market.A_SHARE:
            return self._FlowMissing_Create(
                security, "新浪财经该资金流适配器仅用于 A 股"
            )
        symbol = self._Symbol_Get(security)
        payload = self._client.RequestBytes(
            self.FLOW_URL,
            params={
                "page": 1,
                "num": 30,
                "sort": "opendate",
                "asc": 0,
                "daima": symbol,
            },
            request_id=f"sina-flow-{security.code}",
            referer="https://finance.sina.com.cn/",
            endpoint_key="sina-a-share-30-day-main-flow",
            headers={"Accept": "application/json,text/plain,*/*"},
        )
        try:
            rows = json.loads(payload.decode("utf-8", errors="replace"))
        except (UnicodeError, ValueError) as error:
            raise SourceSchemaError("新浪资金流返回的不是有效 JSON") from error
        if not isinstance(rows, list):
            raise SourceSchemaError("新浪资金流 JSON 根节点不是数组")
        values: dict[date, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                item_date = datetime.strptime(
                    str(row.get("opendate") or ""), "%Y-%m-%d"
                ).date()
                amount = float(row.get("r0_net"))
            except (TypeError, ValueError):
                continue
            values[item_date] = amount
        history = sorted(values.items())
        if len(history) < 5:
            return self._FlowMissing_Create(
                security,
                f"新浪主力资金历史仅返回 {len(history)} 个有效交易日",
                symbol=symbol,
            )
        one_month_net = (
            sum(amount for _day, amount in history[-22:])
            if len(history) >= 22
            else None
        )
        missing_reason = (
            None
            if one_month_net is not None
            else f"已取得 5 日资金流；有效历史仅 {len(history)} 日，22 日字段留空"
        )
        return SourceValue(
            FlowData(
                security_key=security.key,
                end_date=history[-1][0],
                five_day_net=sum(amount for _day, amount in history[-5:]),
                one_month_net=one_month_net,
                currency="CNY",
            ),
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                (
                    "MoneyFlow.ssl_qsfx_zjlrqs；"
                    f"daima={symbol}；r0_net 主力净流入；"
                    f"截止={history[-1][0].isoformat()}"
                ),
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                missing_reason=missing_reason,
                primary_source="东方财富",
                field_statuses={
                    FLOW_FIVE_DAY_FIELD: DataStatus.OK,
                    FLOW_ONE_MONTH_A_FIELD: (
                        DataStatus.OK
                        if one_month_net is not None
                        else DataStatus.MISSING
                    ),
                },
            ),
        )

    def Concepts_Fetch(self, security: Security) -> SourceValue[tuple[str, ...]]:
        url = self.RELATED_URL.format(code=security.code)
        payload = self._client.RequestBytes(
            url,
            request_id=f"sina-related-{security.code}",
            referer="https://vip.stock.finance.sina.com.cn/",
            endpoint_key="sina-related-index-a-share",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        text = payload.decode("gb18030", errors="replace")
        values: list[str] = []
        for row in Parser_ParseHtmlTable(text):
            if len(row) < 3:
                continue
            name = re.sub(r"\s+", " ", row[0]).strip()
            code = re.sub(r"\s+", "", row[1])
            if not name or name in {"指数名称", "相关指数", "名称"}:
                continue
            if not re.fullmatch(r"[A-Za-z0-9.()_-]{4,20}", code):
                continue
            out_date = row[3].strip() if len(row) > 3 else ""
            if out_date and re.search(r"\d{4}", out_date):
                continue
            values.append(name)
        concepts = Security_ConceptsNormalize(values)
        if not concepts:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "概念",
                    self.source_name,
                    url,
                    DataStatus.MISSING,
                    missing_reason="新浪相关资料页未返回仍在有效期内的概念/指数标签",
                    primary_source="同花顺",
                    field_statuses={"概念": DataStatus.MISSING},
                ),
            )
        return SourceValue(
            concepts,
            Provenance_Create(
                security,
                "概念",
                self.source_name,
                f"{url}（当前相关指数标签，作为概念备源）",
                DataStatus.OK,
                primary_source="同花顺",
                field_statuses={"概念": DataStatus.OK},
            ),
        )

    def _FlowMissing_Create(
        self,
        security: Security,
        reason: str,
        *,
        symbol: str | None = None,
    ) -> SourceValue[FlowData]:
        request_symbol = symbol or self._Symbol_Get(security)
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                f"MoneyFlow.ssl_qsfx_zjlrqs；daima={request_symbol}",
                DataStatus.MISSING,
                standard_currency="CNY",
                missing_reason=reason,
                primary_source="东方财富",
                field_statuses={
                    FLOW_FIVE_DAY_FIELD: DataStatus.MISSING,
                    FLOW_ONE_MONTH_A_FIELD: DataStatus.MISSING,
                },
            ),
        )

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

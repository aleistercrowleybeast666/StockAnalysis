from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from dateutil.parser import isoparse

from stock_analysis.domain.calculations import (
    Calculation_ConvertCurrency,
    Calculation_IssueMarketCap,
)
from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.fields import (
    FLOW_FIVE_DAY_FIELD,
    FlowOneMonthDays_Get,
    FlowOneMonthField_Get,
)
from stock_analysis.domain.models import (
    BlockTradeData,
    FinancialPeriod,
    FlowData,
    IPOInfo,
    Quote,
    Security,
)
from stock_analysis.sources.base import (
    HttpJsonClient,
    MarketDataSource,
    Provenance_Create,
    SourceError,
    SourceSchemaError,
    SourceValue,
)
from stock_analysis.sources.fx import FrankfurterFxSource
from stock_analysis.sources.normalization import (
    Security_AShareBoardGet,
    Security_ExchangeFromCode,
    Security_FinancialClassify,
    Security_Secucode,
)


def _ParseDate(value: Any) -> date | None:
    if value in (None, "", "-"):
        return None
    try:
        return isoparse(str(value)).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _Float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _QuoteDate_Parse(value: Any) -> date | None:
    timestamp = _Float(value)
    if timestamp is None or timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, UTC).date()
    except (OSError, OverflowError, ValueError):
        return None


def _Currency_Normalize(value: Any) -> str:
    text = str(value or "HKD").strip().upper()
    aliases = {
        "港元": "HKD",
        "港币": "HKD",
        "人民币": "CNY",
        "RMB": "CNY",
        "美元": "USD",
        "欧元": "EUR",
    }
    return aliases.get(text, text)


def _DataCenterResult_Get(
    data: dict[str, Any], context: str
) -> tuple[list[dict[str, Any]], int]:
    if data.get("success") is False:
        message = data.get("message") or data.get("msg") or data.get("code")
        raise SourceSchemaError(f"{context}接口返回失败：{message or '未知错误'}")
    result = data.get("result")
    if not isinstance(result, dict):
        raise SourceSchemaError(f"{context}响应缺少有效 result 对象")
    rows = result.get("data")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise SourceSchemaError(f"{context}响应 data 字段不是数组")
    normalized_rows = [row for row in rows if isinstance(row, dict)]
    pages = int(_Float(result.get("pages")) or 0)
    return normalized_rows, pages


class EastmoneySource(MarketDataSource):
    source_name = "东方财富"
    QUOTE_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"
    QUOTE_BATCH_URL = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
    LIST_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
    DATA_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    F10_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    FLOW_FALLBACK_URL = "https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get"
    A_SHARE_CAPITAL_URL = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/"
        "CapitalStockStructure/PageAjax"
    )

    def __init__(
        self,
        client: HttpJsonClient,
        fx_source: FrankfurterFxSource | None = None,
    ) -> None:
        self._client = client
        self._fx_source = fx_source

    @staticmethod
    def _Secid(security: Security) -> str:
        if security.market is Market.HK:
            return f"116.{security.code}"
        return f"{1 if security.exchange == 'SSE' else 0}.{security.code}"

    @staticmethod
    def _MarketFilter(market: Market) -> str:
        return (
            "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
            if market is Market.A_SHARE
            else "m:116+t:3,m:116+t:4,m:116+t:1"
        )

    def SecurityList_Fetch(self, market: Market, limit: int = 0) -> list[Security]:
        market_filter = self._MarketFilter(market)
        # 该端点会把过大的 pz 静默限制为 100。若仍按请求的 500
        # 判断“最后一页”，首个 100 行响应会被误认为完整证券池。
        page_size = min(max(limit if limit > 0 else 100, 20), 100)
        result: list[Security] = []
        seen_keys: set[str] = set()
        raw_count = 0
        page_number = 1
        while page_number <= 100:
            data = self._client.RequestJson(
                self.LIST_URL,
                params={
                    "pn": page_number,
                    "pz": page_size,
                    "po": 1,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f12",
                    "fs": market_filter,
                    "fields": "f12,f14,f13,f2,f20,f100",
                },
                request_id=(
                    f"security-list-{market.value}-{page_size}-page-{page_number}"
                ),
                referer="https://quote.eastmoney.com/",
                endpoint_key=f"security-list-{market.value}",
            )
            payload = data.get("data")
            if not isinstance(payload, dict) or "diff" not in payload:
                raise SourceSchemaError("东方财富证券列表结构发生变化")
            rows = payload["diff"]
            if not isinstance(rows, list):
                raise SourceSchemaError("东方财富证券列表不是数组")
            raw_count += len(rows)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("f12") or "")
                name = str(row.get("f14") or "").strip()
                if not code or not name:
                    continue
                exchange = "HKEX" if market is Market.HK else Security_ExchangeFromCode(code)
                industry = str(row.get("f100") or "").strip() or None
                security = Security(
                    market=market,
                    exchange=exchange,
                    code=code.zfill(5) if market is Market.HK else code,
                    name=name,
                    is_st="ST" in name.upper(),
                    is_financial=Security_FinancialClassify(
                        name, industry, security_code=code
                    ),
                    industry=industry,
                    board=(
                        Security_AShareBoardGet(exchange, code)
                        if market is Market.A_SHARE
                        else None
                    ),
                )
                if security.key not in seen_keys:
                    seen_keys.add(security.key)
                    result.append(security)
            if limit > 0 and len(result) >= limit:
                break
            total = _Float(payload.get("total"))
            if not rows or (total is not None and raw_count >= total):
                break
            if total is None and len(rows) < page_size:
                break
            page_number += 1
        return result[:limit] if limit > 0 else result

    def Financials_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]:
        if security.market is Market.HK:
            return self._FinancialsHk_Fetch(security, years)
        return self._FinancialsA_Fetch(security, years)

    def FinancialsMappedAForHk_Fetch(
        self,
        hk_security: Security,
        a_share_security: Security,
        years: set[int],
        mapping_evidence: str,
    ) -> SourceValue[list[FinancialPeriod]]:
        if not years:
            return SourceValue(
                [],
                Provenance_Create(
                    hk_security,
                    "年度财务",
                    self.source_name,
                    mapping_evidence,
                    DataStatus.MISSING,
                    standard_currency="HKD",
                    missing_reason="A/H 映射没有待补年度",
                ),
            )
        if self._fx_source is None:
            raise SourceSchemaError("A/H 映射财务需要 CNY/HKD 历史汇率源")
        source = self._FinancialsA_Fetch(a_share_security, years)
        mapped: list[FinancialPeriod] = []
        for period in source.value or []:
            rate = self._fx_source.Rate_Fetch("CNY", "HKD", period.report_end)
            mapped.append(
                replace(
                    period,
                    security_key=hk_security.key,
                    currency="HKD",
                    revenue=Calculation_ConvertCurrency(period.revenue, rate.rate),
                    operating_cost=Calculation_ConvertCurrency(
                        period.operating_cost, rate.rate
                    ),
                    parent_net_profit=Calculation_ConvertCurrency(
                        period.parent_net_profit, rate.rate
                    ),
                    operating_cash_flow=Calculation_ConvertCurrency(
                        period.operating_cash_flow, rate.rate
                    ),
                    original_currency="CNY",
                    fx_rate=rate.rate,
                    fx_date=rate.rate_date,
                    quality_note=(
                        f"A/H 同一发行人历史映射：{mapping_evidence}"
                    ),
                )
            )
        return SourceValue(
            mapped,
            Provenance_Create(
                hk_security,
                "年度财务",
                self.source_name,
                (
                    f"A/H 同一发行人映射 {hk_security.code}.HK <- "
                    f"{a_share_security.code}.{a_share_security.exchange}；"
                    f"{mapping_evidence}；RPT_LICO_FN_CPD + RPT_DMSK_FN_CASHFLOW"
                ),
                DataStatus.OK if mapped else DataStatus.MISSING,
                original_currency="CNY",
                standard_currency="HKD",
                missing_reason=(
                    None if mapped else "映射后的 A 股代码没有返回待补完整年度"
                ),
                primary_source=self.source_name,
            ),
        )

    def _FinancialsA_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]:
        income_data = self._client.RequestJson(
            self.DATA_URL,
            params={
                "reportName": "RPT_LICO_FN_CPD",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{security.code}")',
                "pageNumber": 1,
                "pageSize": 200,
                "sortTypes": -1,
                "sortColumns": "REPORTDATE",
            },
            request_id=f"a-financial-{security.code}",
            referer=f"https://data.eastmoney.com/bbsj/{security.code}.html",
            endpoint_key="financial-income-a-share",
        )
        cash_data = self._client.RequestJson(
            self.DATA_URL,
            params={
                "reportName": "RPT_DMSK_FN_CASHFLOW",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{security.code}")',
                "pageNumber": 1,
                "pageSize": 200,
                "sortTypes": -1,
                "sortColumns": "REPORT_DATE",
            },
            request_id=f"a-cashflow-{security.code}",
            referer=f"https://data.eastmoney.com/bbsj/{security.code}.html",
            endpoint_key="financial-cashflow-a-share",
        )
        income_rows = (income_data.get("result") or {}).get("data") or []
        cash_rows = (cash_data.get("result") or {}).get("data") or []
        if not isinstance(income_rows, list) or not isinstance(cash_rows, list):
            raise SourceSchemaError("A 股财务响应 data 字段不是数组")
        cash_by_year: dict[int, dict[str, Any]] = {}
        for row in cash_rows:
            report_date = _ParseDate(row.get("REPORT_DATE"))
            if (
                report_date
                and report_date.year in years
                and report_date.month == 12
                and row.get("DATE_TYPE_CODE") in (None, "001")
            ):
                cash_by_year.setdefault(report_date.year, row)
        periods: list[FinancialPeriod] = []
        for row in income_rows:
            report_date = _ParseDate(row.get("REPORTDATE"))
            if report_date is None or report_date.year not in years or report_date.month != 12:
                continue
            report_label = f"{row.get('DATATYPE', '')}{row.get('DATEMMDD', '')}"
            if "年报" not in report_label and report_date.day != 31:
                continue
            revenue = _Float(row.get("TOTAL_OPERATE_INCOME"))
            gross_margin = _Float(row.get("XSMLL"))
            operating_cost = (
                revenue * (1.0 - gross_margin / 100.0)
                if revenue is not None and gross_margin is not None
                else None
            )
            cash = cash_by_year.get(report_date.year, {})
            periods.append(
                FinancialPeriod(
                    security_key=security.key,
                    report_end=report_date,
                    fiscal_year=report_date.year,
                    announcement_date=_ParseDate(row.get("NOTICE_DATE")),
                    currency="CNY",
                    revenue=revenue,
                    operating_cost=operating_cost,
                    parent_net_profit=_Float(row.get("PARENT_NETPROFIT")),
                    operating_cash_flow=_Float(cash.get("NETCASH_OPERATE")),
                    original_currency="CNY",
                )
            )
        status = DataStatus.OK if periods else DataStatus.MISSING
        reason = None if periods else "没有找到所选完整年度的结构化 A 股财务数据"
        return SourceValue(
            periods,
            Provenance_Create(
                security,
                "年度财务",
                self.source_name,
                "RPT_LICO_FN_CPD + RPT_DMSK_FN_CASHFLOW",
                status,
                original_currency="CNY",
                standard_currency="CNY",
                missing_reason=reason,
                approximate=any(period.operating_cost is not None for period in periods),
            ),
        )

    def _FinancialsHk_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]:
        data = self._client.RequestJson(
            self.F10_URL,
            params={
                "reportName": "RPT_HKF10_FN_MAININDICATOR",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{security.code}")',
                "pageNumber": 1,
                "pageSize": 200,
                "sortTypes": -1,
                "sortColumns": "REPORT_DATE",
                "source": "F10",
                "client": "PC",
            },
            request_id=f"hk-financial-{security.code}",
            referer=(
                "https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/"
                f"index.html?code={security.code}"
            ),
            endpoint_key="financial-hk",
        )
        rows = (data.get("result") or {}).get("data") or []
        if not isinstance(rows, list):
            raise SourceSchemaError("港股财务响应 data 字段不是数组")
        periods: list[FinancialPeriod] = []
        for row in rows:
            report_date = _ParseDate(row.get("REPORT_DATE"))
            if report_date is None or report_date.year not in years:
                continue
            report_type = str(row.get("REPORT_TYPE") or row.get("REPORT_TYPE_DETAILS") or "")
            if row.get("DATE_TYPE_CODE") != "001" and "年报" not in report_type:
                continue
            revenue = _Float(row.get("OPERATE_INCOME"))
            gross_profit = _Float(row.get("GROSS_PROFIT"))
            original_currency = _Currency_Normalize(row.get("CURRENCY"))
            fx_rate = 1.0
            fx_date = report_date
            if original_currency != "HKD":
                if self._fx_source is None:
                    raise SourceSchemaError(
                        f"港股财务币种 {original_currency} 需要汇率源才能换算为 HKD"
                    )
                rate = self._fx_source.Rate_Fetch(original_currency, "HKD", report_date)
                fx_rate = rate.rate
                fx_date = rate.rate_date
            revenue = Calculation_ConvertCurrency(revenue, fx_rate)
            gross_profit = Calculation_ConvertCurrency(gross_profit, fx_rate)
            operating_cost = (
                revenue - gross_profit
                if revenue is not None and gross_profit is not None
                else None
            )
            periods.append(
                FinancialPeriod(
                    security_key=security.key,
                    report_end=report_date,
                    fiscal_year=report_date.year,
                    announcement_date=None,
                    currency="HKD",
                    revenue=revenue,
                    operating_cost=operating_cost,
                    parent_net_profit=Calculation_ConvertCurrency(
                        _Float(row.get("HOLDER_PROFIT")), fx_rate
                    ),
                    operating_cash_flow=Calculation_ConvertCurrency(
                        _Float(row.get("NETCASH_OPERATE")), fx_rate
                    ),
                    original_currency=original_currency,
                    fx_rate=fx_rate,
                    fx_date=fx_date,
                )
            )
        status = DataStatus.OK if periods else DataStatus.MISSING
        reason = None if periods else "没有找到所选完整年度的结构化港股财务数据"
        return SourceValue(
            periods,
            Provenance_Create(
                security,
                "年度财务",
                self.source_name,
                "RPT_HKF10_FN_MAININDICATOR",
                status,
                original_currency=periods[0].original_currency if periods else None,
                standard_currency="HKD",
                missing_reason=reason,
            ),
        )

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        data = self._client.RequestJson(
            self.QUOTE_URL,
            params={
                "secid": self._Secid(security),
                "fltt": 2,
                "invt": 2,
                "fields": "f43,f57,f58,f59,f84,f116,f124",
            },
            request_id=f"quote-{security.market.value}-{security.code}",
            referer="https://quote.eastmoney.com/",
            endpoint_key=f"quote-single-{security.market.value}",
        )
        row = data.get("data")
        if not isinstance(row, dict):
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    "push2 stock/get",
                    DataStatus.MISSING,
                    missing_reason="行情接口返回空数据",
                ),
            )
        currency = "CNY" if security.market is Market.A_SHARE else "HKD"
        quote_date = _QuoteDate_Parse(row.get("f124"))
        quote = (
            Quote(
                security_key=security.key,
                quote_date=quote_date,
                price=_Float(row.get("f43")),
                market_cap=_Float(row.get("f116")),
                currency=currency,
            )
            if quote_date is not None
            else None
        )
        status = (
            DataStatus.OK
            if quote is not None
            and (quote.price is not None or quote.market_cap is not None)
            else DataStatus.MISSING
        )
        return SourceValue(
            quote if status is DataStatus.OK else None,
            Provenance_Create(
                security,
                "最新行情",
                self.source_name,
                "push2 stock/get f43,f116",
                status,
                original_currency=currency,
                standard_currency=currency,
                missing_reason=(
                    None
                    if status is DataStatus.OK
                    else "真实行情时间缺失，或最新价和总市值均缺失"
                ),
            ),
        )

    def Quotes_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Quote]]:
        results: dict[str, SourceValue[Quote]] = {}
        by_secid = {self._Secid(item): item for item in securities}
        remaining = {item.key for item in securities}
        batch_size = 100
        for offset in range(0, len(securities), batch_size):
            batch = list(securities[offset : offset + batch_size])
            batch_number = offset // batch_size + 1
            data = self._client.RequestJson(
                self.QUOTE_BATCH_URL,
                params={
                    "secids": ",".join(self._Secid(item) for item in batch),
                    "fltt": 2,
                    "invt": 2,
                    "fields": "f12,f13,f2,f20,f124",
                },
                request_id=f"batch-quotes-selected-{batch_number}",
                referer="https://quote.eastmoney.com/",
                endpoint_key="batch-quotes-selected",
            )
            payload = data.get("data")
            if not isinstance(payload, dict):
                raise SourceSchemaError("东方财富指定证券批量行情结构发生变化")
            rows = payload.get("diff") or []
            if not isinstance(rows, list):
                raise SourceSchemaError("东方财富指定证券批量行情 diff 字段不是数组")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("f12") or "")
                market_id = str(row.get("f13") or "")
                security = by_secid.get(f"{market_id}.{code}")
                if security is None:
                    candidates = [item for item in batch if item.code == code]
                    security = candidates[0] if len(candidates) == 1 else None
                if security is None:
                    continue
                currency = "CNY" if security.market is Market.A_SHARE else "HKD"
                quote_date = _QuoteDate_Parse(row.get("f124"))
                quote = (
                    Quote(
                        security_key=security.key,
                        quote_date=quote_date,
                        price=_Float(row.get("f2")),
                        market_cap=_Float(row.get("f20")),
                        currency=currency,
                    )
                    if quote_date is not None
                    else None
                )
                status = (
                    DataStatus.OK
                    if quote is not None
                    and (quote.price is not None or quote.market_cap is not None)
                    else DataStatus.MISSING
                )
                results[security.key] = SourceValue(
                    quote if status is DataStatus.OK else None,
                    Provenance_Create(
                        security,
                        "最新行情",
                        self.source_name,
                        "push2 ulist.np/get f2,f20,f124（按指定证券分批）",
                        status,
                        original_currency=currency,
                        standard_currency=currency,
                        missing_reason=(
                            None
                            if status is DataStatus.OK
                            else "指定证券批量行情缺少真实行情时间，或最新价和总市值均缺失"
                        ),
                    ),
                )
                remaining.discard(security.key)
            if progress_callback is not None:
                for security in batch:
                    progress_callback(security)
        securities_by_key = {item.key: item for item in securities}
        for security_key in remaining:
            security = securities_by_key[security_key]
            currency = "CNY" if security.market is Market.A_SHARE else "HKD"
            results[security.key] = SourceValue(
                None,
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    "push2 ulist.np/get（按指定证券分批）",
                    DataStatus.MISSING,
                    standard_currency=currency,
                    missing_reason="指定证券批量行情未返回该证券",
                ),
            )
        return results

    def IPO_Fetch(self, security: Security) -> SourceValue[IPOInfo]:
        if security.market is Market.HK:
            report_name = "RPT_HKF10_INFO_SECURITYINFO"
            source = "F10"
        else:
            report_name = "RPT_PCF10_ORG_ISSUEINFO"
            source = "HSF10"
        secucode = Security_Secucode(security.code, security.market)
        data = self._client.RequestJson(
            self.F10_URL,
            params={
                "reportName": report_name,
                "columns": "ALL",
                "filter": f'(SECUCODE="{secucode}")',
                "pageNumber": 1,
                "pageSize": 5,
                "source": source,
                "client": "PC",
            },
            request_id=f"ipo-{security.market.value}-{security.code}",
            referer="https://emweb.securities.eastmoney.com/",
            endpoint_key=f"ipo-{security.market.value}",
        )
        rows = (data.get("result") or {}).get("data") or []
        row = rows[0] if isinstance(rows, list) and rows else {}
        issue_price = _Float(row.get("ISSUE_PRICE"))
        issued_shares = _Float(row.get("ISSUE_NUM") or row.get("TOTAL_ISSUE_NUM"))
        post_issue_total_shares = _Float(
            row.get("TOTAL_SHARES_AFTER_ISSUE")
            or row.get("AFTER_ISSUE_TOTAL_SHARES")
            or row.get("POST_ISSUE_TOTAL_SHARES")
        )
        listing_date = _ParseDate(row.get("LISTING_DATE")) or security.listing_date
        equity_source_ref: str | None = None
        equity_error: str | None = None
        if post_issue_total_shares is None:
            try:
                if security.market is Market.A_SHARE:
                    capital_data = self._client.RequestJson(
                        self.A_SHARE_CAPITAL_URL,
                        params={
                            "code": (
                                f"SH{security.code}"
                                if security.exchange == "SSE"
                                else f"SZ{security.code}"
                            )
                        },
                        request_id=f"ipo-capital-a-share-{security.code}",
                        referer="https://emweb.securities.eastmoney.com/",
                        endpoint_key="ipo-capital-history-a-share",
                    )
                    post_issue_total_shares = self._PostIssueSharesA_Get(
                        capital_data, listing_date
                    )
                    equity_source_ref = "PC_HSF10 CapitalStockStructure/lngbbd"
                else:
                    capital_data = self._client.RequestJson(
                        self.F10_URL,
                        params={
                            "reportName": "RPT_HKF10_INFO_EQUITY",
                            "columns": (
                                "SECUCODE,CHANGE_DATE,HK_SHARES,CHANGE_REASON,"
                                "NOTICE_DATE"
                            ),
                            "filter": f'(SECUCODE="{secucode}")',
                            "pageNumber": 1,
                            "pageSize": 500,
                            "sortTypes": "1",
                            "sortColumns": "CHANGE_DATE",
                            "source": "F10",
                            "client": "PC",
                        },
                        request_id=f"ipo-capital-hk-{security.code}",
                        referer="https://emweb.securities.eastmoney.com/",
                        endpoint_key="ipo-capital-history-hk",
                    )
                    capital_rows, _pages = _DataCenterResult_Get(
                        capital_data, "港股历史股本"
                    )
                    post_issue_total_shares = self._PostIssueSharesHk_Get(
                        capital_rows, listing_date
                    )
                    equity_source_ref = "RPT_HKF10_INFO_EQUITY"
            except SourceError as error:
                equity_error = str(error)
        issue_market_cap, approximate = Calculation_IssueMarketCap(
            issue_price,
            post_issue_total_shares,
            issued_shares if security.market is Market.A_SHARE else None,
        )
        ipo = IPOInfo(
            security_key=security.key,
            listing_date=listing_date,
            issue_price=issue_price,
            issued_shares=issued_shares,
            post_issue_total_shares=post_issue_total_shares,
            issue_market_cap=issue_market_cap,
            approximate=approximate,
        )
        has_data = any(
            value is not None
            for value in (ipo.listing_date, ipo.issue_price, ipo.issued_shares, ipo.issue_market_cap)
        )
        currency = "CNY" if security.market is Market.A_SHARE else "HKD"
        field_statuses = {
            "上市日期": DataStatus.OK if ipo.listing_date is not None else DataStatus.MISSING,
            "发行价": DataStatus.OK if ipo.issue_price is not None else DataStatus.MISSING,
            "发行股数": DataStatus.OK if ipo.issued_shares is not None else DataStatus.MISSING,
            "发行后总股本": (
                DataStatus.OK
                if ipo.post_issue_total_shares is not None
                else DataStatus.MISSING
            ),
            "发行时总市值": (
                DataStatus.OK if ipo.issue_market_cap is not None else DataStatus.MISSING
            ),
        }
        missing_fields = [
            name for name, status in field_statuses.items() if status is not DataStatus.OK
        ]
        source_ref = report_name
        if equity_source_ref:
            source_ref += f" + {equity_source_ref}"
        missing_reason = None
        if missing_fields:
            missing_reason = f"未取得字段：{', '.join(missing_fields)}"
            if equity_error:
                missing_reason += f"；历史股本备源失败：{equity_error}"
        return SourceValue(
            ipo if has_data else None,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                source_ref,
                DataStatus.OK if has_data else DataStatus.MISSING,
                original_currency=currency,
                standard_currency=currency,
                missing_reason=missing_reason or (
                    None if has_data else "发行信息接口未返回可用字段"
                ),
                approximate=approximate,
                field_statuses=field_statuses,
            ),
        )

    @staticmethod
    def _PostIssueSharesA_Get(
        data: dict[str, Any], listing_date: date | None
    ) -> float | None:
        rows = data.get("lngbbd")
        if not isinstance(rows, list):
            return None
        candidates: list[tuple[int, date, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            shares = _Float(row.get("TOTAL_SHARES"))
            change_date = _ParseDate(row.get("END_DATE"))
            reason = str(row.get("CHANGE_REASON") or "")
            if shares is None or shares <= 0 or change_date is None:
                continue
            explicit_ipo = "首发" in reason and "上市" in reason
            same_listing_date = listing_date is not None and change_date == listing_date
            if not explicit_ipo and not same_listing_date:
                continue
            candidates.append((0 if explicit_ipo else 1, change_date, shares))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    @staticmethod
    def _PostIssueSharesHk_Get(
        rows: Sequence[dict[str, Any]], listing_date: date | None
    ) -> float | None:
        candidates: list[tuple[int, date, float]] = []
        for row in rows:
            shares = _Float(row.get("HK_SHARES"))
            change_date = _ParseDate(row.get("CHANGE_DATE"))
            reason = str(row.get("CHANGE_REASON") or "")
            if shares is None or shares <= 0 or change_date is None:
                continue
            explicit_ipo = "新股" in reason and "上市" in reason
            same_listing_date = listing_date is not None and change_date == listing_date
            if not explicit_ipo and not same_listing_date:
                continue
            candidates.append((0 if explicit_ipo else 1, change_date, shares))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    def BlockTrade_Fetch(
        self, security: Security, year: int
    ) -> SourceValue[BlockTradeData]:
        if security.market is Market.HK:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    "hk-source-chain-pending",
                    DataStatus.MISSING,
                    standard_currency="HKD",
                    missing_reason="东方财富未提供港股同口径大宗交易数据，等待港股备源",
                ),
            )
        data = self._client.RequestJson(
            self.DATA_URL,
            params={
                "reportName": "RPT_DATA_BLOCKTRADE",
                "columns": "SECURITY_CODE,TRADE_DATE,DEAL_AMT",
                "filter": (
                    f'(SECURITY_CODE="{security.code}")'
                    f"(TRADE_DATE>='{year}-01-01')(TRADE_DATE<='{year}-12-31')"
                ),
                "pageNumber": 1,
                "pageSize": 500,
                "sortTypes": -1,
                "sortColumns": "TRADE_DATE",
                "source": "WEB",
                "client": "WEB",
            },
            request_id=f"block-trade-{security.code}-{year}",
            referer="https://data.eastmoney.com/dzjy/",
            endpoint_key="block-trade-single-a-share-v2",
        )
        rows, _pages = _DataCenterResult_Get(data, "大宗交易")
        amounts = [_Float(row.get("DEAL_AMT")) for row in rows]
        total_amount = sum(value for value in amounts if value is not None) if rows else 0.0
        value = BlockTradeData(
            security_key=security.key,
            year=year,
            trade_count=len(rows) if rows else 0,
            total_amount=total_amount,
            currency="CNY",
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                "RPT_DATA_BLOCKTRADE",
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
            ),
        )

    def BlockTrades_Fetch(
        self, securities: Sequence[Security], year: int
    ) -> dict[str, SourceValue[BlockTradeData]]:
        results: dict[str, SourceValue[BlockTradeData]] = {}
        a_share_securities = [
            security for security in securities if security.market is Market.A_SHARE
        ]
        for security in securities:
            if security.market is not Market.HK:
                continue
            results[security.key] = SourceValue(
                None,
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    "hk-source-chain-pending",
                    DataStatus.OPTIONAL_MISSING,
                    standard_currency="HKD",
                    missing_reason="东方财富未提供港股同口径大宗交易数据，等待港股备源",
                ),
            )
        if not a_share_securities:
            return results

        by_code = {security.code: security for security in a_share_securities}
        aggregates = {code: [0, 0.0] for code in by_code}
        page_size = 500
        selected_batch_size = 100
        selected_codes = list(by_code)
        for batch_index, start in enumerate(
            range(0, len(selected_codes), selected_batch_size), 1
        ):
            batch_codes = selected_codes[start : start + selected_batch_size]
            codes_filter = ",".join(f'"{code}"' for code in batch_codes)
            page_number = 1
            while page_number <= 1000:
                data = self._client.RequestJson(
                    self.DATA_URL,
                    params={
                        "reportName": "RPT_DATA_BLOCKTRADE",
                        "columns": "SECURITY_CODE,TRADE_DATE,DEAL_AMT",
                        "filter": (
                            f"(SECURITY_CODE in ({codes_filter}))"
                            f"(TRADE_DATE>='{year}-01-01')"
                            f"(TRADE_DATE<='{year}-12-31')"
                        ),
                        "pageNumber": page_number,
                        "pageSize": page_size,
                        "sortTypes": -1,
                        "sortColumns": "TRADE_DATE",
                        "source": "WEB",
                        "client": "WEB",
                    },
                    request_id=(
                        f"block-trade-selected-{year}-batch-{batch_index}-"
                        f"page-{page_number}"
                    ),
                    referer="https://data.eastmoney.com/dzjy/",
                    endpoint_key="block-trade-selected-a-share-v2",
                )
                rows, pages = _DataCenterResult_Get(data, "所选 A 股大宗交易")
                for row in rows:
                    code = str(row.get("SECURITY_CODE") or "")
                    aggregate = aggregates.get(code)
                    if aggregate is None:
                        continue
                    aggregate[0] += 1
                    amount = _Float(row.get("DEAL_AMT"))
                    if amount is not None:
                        aggregate[1] += amount
                if (
                    not rows
                    or len(rows) < page_size
                    or (pages and page_number >= pages)
                ):
                    break
                page_number += 1
        for code, security in by_code.items():
            count, amount = aggregates[code]
            results[security.key] = SourceValue(
                BlockTradeData(
                    security_key=security.key,
                    year=year,
                    trade_count=int(count),
                    total_amount=float(amount),
                    currency="CNY",
                ),
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    f"RPT_DATA_BLOCKTRADE {year}（所选证券分批查询后聚合）",
                    DataStatus.OK,
                    original_currency="CNY",
                    standard_currency="CNY",
                ),
            )
        return results

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        is_hk = security.market is Market.HK
        market_label = "hk" if is_hk else "a-share"
        currency = "HKD" if is_hk else "CNY"
        one_month_days = FlowOneMonthDays_Get(security.market)
        one_month_field = FlowOneMonthField_Get(security.market)
        flow_params = {
            "lmt": 30,
            "klt": 101,
            "secid": self._Secid(security),
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        }
        browser_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
            ),
            "Origin": "https://quote.eastmoney.com",
        }
        primary_error: SourceError | None = None
        try:
            data = self._client.RequestJson(
                self.FLOW_URL,
                params=flow_params,
                request_id=(
                    f"flow-hk-{security.code}" if is_hk else f"flow-{security.code}"
                ),
                referer="https://data.eastmoney.com/zjlx/",
                endpoint_key=f"flow-history-{market_label}-{security.code}",
                headers=browser_headers,
            )
            source_ref = (
                "push2his fflow/daykline，港股 market=116，f52 主力净流入"
                if is_hk
                else "push2his fflow/daykline f52"
            )
        except SourceError as error:
            primary_error = error
            data = self._client.RequestJson(
                self.FLOW_FALLBACK_URL,
                params=flow_params,
                request_id=(
                    f"flow-hk-fallback-{security.code}"
                    if is_hk
                    else f"flow-fallback-{security.code}"
                ),
                referer="https://data.eastmoney.com/zjlx/",
                endpoint_key=f"flow-delay-{market_label}-{security.code}",
                headers=browser_headers,
            )
            source_ref = "push2delay fflow/daykline f52（历史端点失败后的备源）"
        response_code = data.get("rc")
        if response_code not in (None, 0):
            raise SourceSchemaError(f"资金流接口返回错误码 {response_code}")
        payload = data.get("data")
        if payload is not None and not isinstance(payload, dict):
            raise SourceSchemaError("资金流响应 data 字段不是对象")
        klines = ((payload or {}).get("klines")) or []
        if not isinstance(klines, list):
            raise SourceSchemaError("资金流响应 klines 字段不是数组")
        values_by_date: dict[date, float] = {}
        for item in klines:
            parts = str(item).split(",")
            if len(parts) < 2:
                continue
            parsed_date = _ParseDate(parts[0])
            amount = _Float(parts[1])
            if parsed_date is not None and amount is not None:
                values_by_date[parsed_date] = amount
        values = sorted(values_by_date.items(), key=lambda item: item[0])
        if len(values) < 5:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    source_ref,
                    DataStatus.MISSING,
                    standard_currency=currency,
                    missing_reason=(
                        f"资金流仅返回 {len(values)} 个有效交易日，不足 5 个交易日"
                        + (f"；历史主源失败：{primary_error}" if primary_error else "")
                    ),
                    field_statuses={
                        FLOW_FIVE_DAY_FIELD: DataStatus.MISSING,
                        one_month_field: DataStatus.MISSING,
                    },
                ),
            )
        one_month_net = (
            sum(item[1] for item in values[-one_month_days:])
            if len(values) >= one_month_days
            else None
        )
        value = FlowData(
            security_key=security.key,
            end_date=values[-1][0],
            five_day_net=sum(item[1] for item in values[-5:]),
            one_month_net=one_month_net,
            currency=currency,
        )
        missing_reason = None
        if one_month_net is None:
            missing_reason = (
                f"已取得 5 日资金流；有效历史仅 {len(values)} 日，"
                f"{one_month_days} 日字段留空"
            )
            if primary_error:
                missing_reason += f"；历史主源失败：{primary_error}"
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "资金流",
                self.source_name,
                source_ref,
                DataStatus.OK,
                original_currency=currency,
                standard_currency=currency,
                missing_reason=missing_reason,
                field_statuses={
                    FLOW_FIVE_DAY_FIELD: DataStatus.OK,
                    one_month_field: (
                        DataStatus.OK
                        if one_month_net is not None
                        else DataStatus.MISSING
                    ),
                },
            ),
        )

    def close(self) -> None:
        self._client.close()
        if self._fx_source is not None:
            self._fx_source.close()

    def Performance_Get(self) -> dict[str, Any]:
        return self._client.Statistics_Get()

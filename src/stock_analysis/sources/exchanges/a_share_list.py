from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import Security
from stock_analysis.sources.base import HttpJsonClient, SourceError, SourceSchemaError
from stock_analysis.sources.normalization import (
    Security_AShareBoardGet,
    Security_FinancialClassify,
)
from stock_analysis.sources.parsers import (
    Parser_ParseHtmlTable,
    Parser_ParseJsonOrJsonp,
    Parser_ParseSzseStockWorkbook,
)


def _Date_Parse(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    for format_text in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], format_text).date()
        except ValueError:
            continue
    return None


def _Name_Normalize(value: object) -> str:
    return "".join(str(value or "").split())


def _Financial_Check(name: str, industry: str) -> bool:
    return Security_FinancialClassify(name, industry)


def _Security_Create(
    exchange: str,
    code: object,
    name: object,
    listing_date: object,
    industry: object,
) -> Security | None:
    raw_code = str(code or "").strip().split(".")[0]
    normalized_code = raw_code.zfill(6)
    normalized_name = _Name_Normalize(name)
    normalized_industry = str(industry or "").strip()
    if not raw_code or not normalized_code.isdigit() or not normalized_name:
        return None
    return Security(
        market=Market.A_SHARE,
        exchange=exchange,
        code=normalized_code,
        name=normalized_name,
        listing_date=_Date_Parse(listing_date),
        is_st="ST" in normalized_name.upper(),
        is_financial=_Financial_Check(normalized_name, normalized_industry),
        industry=normalized_industry or None,
        board=Security_AShareBoardGet(exchange, normalized_code),
    )


class OfficialAShareListSource:
    source_name = "沪深北交易所官方证券列表"
    SSE_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
    SSE_REFERER = "https://www.sse.com.cn/assortment/stock/list/share/"
    SZSE_URL = "https://www.szse.cn/api/report/ShowReport"
    SZSE_REFERER = "https://www.szse.cn/market/product/stock/list/index.html"
    BSE_URL = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
    BSE_REFERER = "https://www.bse.cn/nq/listedcompany.html"
    BSE_CODE_MAPPING_URL = "https://www.bse.cn/service/code_mapping.html"

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client
        self._logger = logging.getLogger("stock_analysis.sources.bse")

    def _Sse_Fetch(self) -> list[Security]:
        result: list[Security] = []
        for stock_type in ("1", "8"):
            payload = self._client.RequestJson(
                self.SSE_URL,
                params={
                    "STOCK_TYPE": stock_type,
                    "REG_PROVINCE": "",
                    "CSRC_CODE": "",
                    "STOCK_CODE": "",
                    "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
                    "COMPANY_STATUS": "2,4,5,7,8",
                    "type": "inParams",
                    "isPagination": "true",
                    "pageHelp.cacheSize": 1,
                    "pageHelp.beginPage": 1,
                    "pageHelp.pageSize": 5000,
                    "pageHelp.pageNo": 1,
                },
                request_id=f"sse-a-share-list-{stock_type}",
                referer=self.SSE_REFERER,
                endpoint_key="security-list-sse",
            )
            rows = payload.get("result")
            if not isinstance(rows, list) or not rows:
                raise SourceSchemaError(f"上交所股票列表类型 {stock_type} 结构异常")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                security = _Security_Create(
                    "SSE",
                    row.get("A_STOCK_CODE"),
                    row.get("SEC_NAME_CN"),
                    row.get("LIST_DATE"),
                    row.get("CSRC_CODE_DESC"),
                )
                if security is not None:
                    result.append(security)
        return result

    def _Szse_Fetch(self) -> list[Security]:
        payload = self._client.RequestBytes(
            self.SZSE_URL,
            params={"SHOWTYPE": "XLSX", "CATALOGID": "1110", "TABKEY": "tab1"},
            request_id="szse-a-share-list-xlsx",
            referer=self.SZSE_REFERER,
            endpoint_key="security-list-szse",
        )
        result: list[Security] = []
        for row in Parser_ParseSzseStockWorkbook(payload):
            security = _Security_Create(
                "SZSE",
                row["code"],
                row["name"],
                row["listing_date"],
                row["industry"],
            )
            if security is not None:
                result.append(security)
        return result

    def _BsePage_Fetch(self, page: int) -> dict[str, Any]:
        payload = self._client.RequestBytes(
            self.BSE_URL,
            method="POST",
            data={
                "page": str(page),
                "typejb": "T",
                "xxfcbj[]": "2",
                "xxzqdm": "",
                "sortfield": "xxzqdm",
                "sorttype": "asc",
                "callback": "stockAnalysisCallback",
            },
            request_id=f"bse-a-share-list-page-{page}",
            referer=self.BSE_REFERER,
            endpoint_key="security-list-bse",
        )
        parsed = Parser_ParseJsonOrJsonp(payload.decode("utf-8"))
        if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], dict):
            raise SourceSchemaError("北交所股票列表结构异常")
        return parsed[0]

    def _BseCodeMapping_Fetch(self) -> dict[str, str]:
        payload = self._client.RequestBytes(
            self.BSE_CODE_MAPPING_URL,
            request_id="bse-a-share-code-mapping",
            referer="https://www.bse.cn/",
            endpoint_key="security-code-mapping-bse",
        )
        rows = Parser_ParseHtmlTable(payload.decode("utf-8", errors="replace"))
        mapping: dict[str, str] = {}
        for row in rows:
            if len(row) < 5:
                continue
            old_code = str(row[3]).strip()
            new_code = str(row[4]).strip()
            if (
                len(old_code) == 6
                and old_code.isdigit()
                and len(new_code) == 6
                and new_code.isdigit()
                and new_code.startswith("92")
                and old_code != new_code
            ):
                mapping[new_code] = old_code
        if not mapping:
            raise SourceSchemaError("北交所新旧代码对照表没有解析到有效映射")
        return mapping

    def _Bse_Fetch(self) -> list[Security]:
        try:
            legacy_code_by_current = self._BseCodeMapping_Fetch()
        except SourceError as error:
            legacy_code_by_current = {}
            self._logger.warning(
                "北交所官方新旧代码对照表不可用；证券名单继续，但旧代码备源回退不可用：%s",
                error,
            )
        result: list[Security] = []
        page = 0
        total_pages = 1
        while page < total_pages:
            payload = self._BsePage_Fetch(page)
            rows = payload.get("content")
            if not isinstance(rows, list):
                raise SourceSchemaError("北交所股票列表缺少 content 数组")
            try:
                total_pages = max(1, int(payload.get("totalPages") or 1))
            except (TypeError, ValueError) as error:
                raise SourceSchemaError("北交所股票列表页数无效") from error
            for row in rows:
                if not isinstance(row, dict):
                    continue
                security = _Security_Create(
                    "BSE",
                    row.get("xxzqdm"),
                    row.get("xxzqjc"),
                    row.get("fxssrq") or row.get("xxgprq"),
                    row.get("xxhyzl"),
                )
                if security is not None:
                    legacy_code = legacy_code_by_current.get(security.code)
                    result.append(
                        replace(
                            security,
                            legacy_codes=(legacy_code,) if legacy_code else (),
                        )
                    )
            page += 1
        return result

    def SecurityList_Fetch(self, limit: int = 0) -> list[Security]:
        try:
            securities = self._Sse_Fetch() + self._Szse_Fetch() + self._Bse_Fetch()
        except SourceError:
            raise
        except Exception as error:
            raise SourceSchemaError(f"沪深北官方股票列表解析失败：{error}") from error
        unique = {security.code: security for security in securities}
        result = sorted(unique.values(), key=lambda security: security.code)
        if not result:
            raise SourceSchemaError("沪深北官方股票列表为空")
        return result[:limit] if limit > 0 else result

    def close(self) -> None:
        self._client.close()

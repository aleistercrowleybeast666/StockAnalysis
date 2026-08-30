from __future__ import annotations

from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import Security
from stock_analysis.sources.base import HttpJsonClient, SourceSchemaError
from stock_analysis.sources.normalization import Security_FinancialClassify
from stock_analysis.sources.parsers import Parser_ParseHkexWorkbook


class HkexSecurityListSource:
    source_name = "HKEX"
    LIST_URL = (
        "https://www.hkex.com.hk/eng/services/trading/securities/"
        "securitieslists/ListOfSecurities.xlsx"
    )

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client

    def SecurityList_Fetch(self, limit: int = 0) -> list[Security]:
        payload = self._client.RequestBytes(
            self.LIST_URL,
            request_id="hkex-security-list",
            referer="https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists",
            endpoint_key="security-list-hkex",
        )
        rows = Parser_ParseHkexWorkbook(payload)
        securities = [
            Security(
                market=Market.HK,
                exchange="HKEX",
                code=row["code"],
                name=row["name"],
                is_financial=Security_FinancialClassify(
                    row["name"], security_code=row["code"]
                ),
            )
            for row in rows
        ]
        if len(securities) < 100:
            raise SourceSchemaError(
                f"HKEX 证券列表仅解析出 {len(securities)} 行，疑似工作表维度或下载不完整"
            )
        return securities[:limit] if limit > 0 else securities

    def close(self) -> None:
        self._client.close()

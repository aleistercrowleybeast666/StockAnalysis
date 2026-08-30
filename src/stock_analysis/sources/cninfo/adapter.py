from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

from dateutil.parser import isoparse

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import FinancialPeriod, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceSchemaError,
    SourceUnsupportedError,
    SourceValue,
)


def _Date_Parse(value: Any) -> date | None:
    if value in (None, "", "-"):
        return None
    try:
        return isoparse(str(value)).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _Float_Parse(value: Any, multiplier: float) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", "")) * multiplier
    except (TypeError, ValueError):
        return None


def _First_Get(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, "", "-"):
            return row[name]
    return None


def _Bool_Parse(value: Any) -> bool | None:
    if value in (None, "", "-"):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "是", "合并", "已追溯"}:
        return True
    if text in {"0", "false", "no", "n", "否", "母公司", "未追溯"}:
        return False
    return None


class CninfoSource:
    """巨潮官方数据服务适配器。

    巨潮官方数据服务站点要求登录/注册后查看 API 文档。适配器只在用户通过
    环境变量提供官方 API 地址与访问令牌时请求，不尝试绕过权限；未配置时由
    组合数据源自动回退东方财富。
    """

    source_name = "巨潮资讯（CNINFO Data Service）"
    _OFFICIAL_HOST = "webapi.cninfo.com.cn"

    def __init__(
        self,
        client: HttpJsonClient,
        *,
        access_token: str | None,
        income_api_url: str | None,
        cashflow_api_url: str | None,
        amount_multiplier: float = 1.0,
    ) -> None:
        self._client = client
        self._access_token = (access_token or "").strip()
        self._income_api_url = (income_api_url or "").strip()
        self._cashflow_api_url = (cashflow_api_url or "").strip()
        self._amount_multiplier = amount_multiplier
        invalid = [
            url
            for url in (self._income_api_url, self._cashflow_api_url)
            if url and urlparse(url).hostname != self._OFFICIAL_HOST
        ]
        self._configuration_error = (
            "巨潮 API 地址必须位于 webapi.cninfo.com.cn" if invalid else None
        )

    @property
    def configured(self) -> bool:
        return bool(
            not self._configuration_error
            and
            self._access_token
            and self._income_api_url
            and self._cashflow_api_url
        )

    @staticmethod
    def _Rows_Get(payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[Any] = [
            payload.get("records"),
            payload.get("data"),
        ]
        result = payload.get("result")
        if isinstance(result, dict):
            candidates.extend((result.get("records"), result.get("data")))
        for candidate in candidates:
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
        raise SourceSchemaError("巨潮 API 响应未包含 records/data 数组")

    def _RequestRows(
        self,
        api_url: str,
        security: Security,
        years: set[int],
        endpoint_key: str,
    ) -> list[dict[str, Any]]:
        payload = self._client.RequestJson(
            api_url,
            method="POST",
            data={
                "scode": security.code,
                "sdate": f"{min(years)}-01-01",
                "edate": f"{max(years)}-12-31",
            },
            headers={"Authorization": self._access_token},
            request_id=f"cninfo-{endpoint_key}-{security.code}",
            referer="https://webapi.cninfo.com.cn/",
            endpoint_key=endpoint_key,
        )
        return self._Rows_Get(payload)

    def Financials_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]:
        if security.market is not Market.A_SHARE:
            raise SourceUnsupportedError("巨潮财务适配器当前仅用于 A 股")
        if not self.configured:
            raise SourceUnsupportedError(
                self._configuration_error
                or (
                    "未配置巨潮官方 API 凭证/端点（CNINFO_ACCESS_TOKEN、"
                    "CNINFO_INCOME_API_URL、CNINFO_CASHFLOW_API_URL）"
                )
            )
        income_rows = self._RequestRows(
            self._income_api_url,
            security,
            years,
            "financial-income-a-share",
        )
        cash_rows = self._RequestRows(
            self._cashflow_api_url,
            security,
            years,
            "financial-cashflow-a-share",
        )
        cash_by_year: dict[int, dict[str, Any]] = {}
        for row in cash_rows:
            report_date = _Date_Parse(
                _First_Get(row, ("REPORT_DATE", "REPORTDATE", "END_DATE", "F001D"))
            )
            if report_date and report_date.year in years:
                cash_by_year.setdefault(report_date.year, row)

        periods: list[FinancialPeriod] = []
        for row in income_rows:
            report_date = _Date_Parse(
                _First_Get(row, ("REPORT_DATE", "REPORTDATE", "END_DATE", "F001D"))
            )
            if report_date is None or report_date.year not in years:
                continue
            cash = cash_by_year.get(report_date.year, {})
            periods.append(
                FinancialPeriod(
                    security_key=security.key,
                    report_end=report_date,
                    fiscal_year=report_date.year,
                    announcement_date=_Date_Parse(
                        _First_Get(
                            row,
                            ("ANNOUNCEMENT_DATE", "DECLAREDATE", "NOTICE_DATE", "F002D"),
                        )
                    ),
                    currency=str(
                        _First_Get(row, ("CURRENCY", "CURRENCY_CODE")) or "CNY"
                    ).upper(),
                    revenue=_Float_Parse(
                        _First_Get(
                            row,
                            (
                                "TOTAL_OPERATING_REVENUE",
                                "TOTAL_OPERATE_INCOME",
                                "OPERATING_REVENUE",
                                "REVENUE",
                            ),
                        ),
                        self._amount_multiplier,
                    ),
                    operating_cost=_Float_Parse(
                        _First_Get(
                            row,
                            (
                                "TOTAL_OPERATING_COST",
                                "TOTAL_OPERATE_COST",
                                "OPERATING_COST",
                            ),
                        ),
                        self._amount_multiplier,
                    ),
                    parent_net_profit=_Float_Parse(
                        _First_Get(
                            row,
                            (
                                "PARENT_NET_PROFIT",
                                "PARENT_NETPROFIT",
                                "NET_PROFIT_PARENT",
                            ),
                        ),
                        self._amount_multiplier,
                    ),
                    operating_cash_flow=_Float_Parse(
                        _First_Get(
                            cash,
                            (
                                "NET_CASH_FLOW_OPERATING",
                                "NETCASH_OPERATE",
                                "OPERATING_CASH_FLOW_NET",
                            ),
                        ),
                        self._amount_multiplier,
                    ),
                    original_currency="CNY",
                    is_consolidated=_Bool_Parse(
                        _First_Get(
                            row,
                            ("IS_CONSOLIDATED", "CONSOLIDATED_FLAG", "MERGE_FLAG"),
                        )
                    ),
                    is_restatement=_Bool_Parse(
                        _First_Get(
                            row,
                            ("IS_RESTATEMENT", "RESTATEMENT_FLAG", "ADJUSTED_FLAG"),
                        )
                    ),
                    quality_note=str(
                        _First_Get(row, ("QUALITY_NOTE", "DATA_QUALITY"))
                        or "巨潮注册 API 原始披露口径；合并/追溯标志以接口返回为准"
                    ),
                )
            )
        usable = [period for period in periods if period.revenue is not None]
        if not usable:
            raise SourceSchemaError("巨潮 API 未返回目标年度可用营业收入")
        return SourceValue(
            usable,
            Provenance_Create(
                security,
                "年度财务",
                self.source_name,
                "已注册的巨潮利润表 + 现金流量表 API",
                DataStatus.OK,
                original_currency="CNY",
                standard_currency="CNY",
                primary_source=self.source_name,
            ),
        )

    def close(self) -> None:
        self._client.close()

    def Performance_Get(self) -> dict[str, Any]:
        return self._client.Statistics_Get()

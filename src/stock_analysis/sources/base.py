from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Generic, TypeVar
from urllib.parse import urlparse

import httpx

from stock_analysis.common.performance import RequestStatistics
from stock_analysis.common.rate_limit import DomainRateLimiter
from stock_analysis.common.retry import Retry_Execute
from stock_analysis.domain.enums import DataStatus, Market, NetworkMode
from stock_analysis.domain.fields import FLOW_FIVE_DAY_FIELD, FlowOneMonthField_Get
from stock_analysis.domain.models import (
    BatchProgressUpdate,
    BlockTradeData,
    FinancialPeriod,
    FlowData,
    IPOInfo,
    Provenance,
    Quote,
    Security,
)
from stock_analysis.version import __version__

T = TypeVar("T")


class SourceError(RuntimeError):
    """数据源错误基类。"""


class RetryableSourceError(SourceError):
    """可有限重试的网络错误。"""


class SourceSchemaError(SourceError):
    """结构变化或字段缺失。"""


class SourceUnsupportedError(SourceError):
    """来源明确不支持此字段组。"""


class SourceUnavailableError(SourceError):
    """当前请求的数据源不可用。"""


@dataclass(slots=True)
class SourceValue(Generic[T]):
    value: T | None
    provenance: Provenance


class HttpJsonClient:
    def __init__(
        self,
        source_name: str,
        *,
        trust_env: bool | None = None,
        network_mode: NetworkMode | None = None,
        domestic: bool = True,
        request_interval: float = 0.6,
        timeout: httpx.Timeout | None = None,
        statistics: RequestStatistics | None = None,
    ) -> None:
        self.source_name = source_name
        self._logger = logging.getLogger("stock_analysis.http")
        self._limiter = DomainRateLimiter(request_interval)
        self._statistics = statistics or RequestStatistics()
        selected_mode = network_mode
        if selected_mode is None:
            selected_mode = (
                NetworkMode.SYSTEM_PROXY if trust_env else NetworkMode.DIRECT
            )
        timeout_config = timeout or httpx.Timeout(
            connect=10.0, read=20.0, write=20.0, pool=10.0
        )
        headers = {
            "User-Agent": f"StockAnalysis/{__version__} (+local personal analysis)",
            "Accept": "application/json,text/plain,*/*",
        }
        if selected_mode is NetworkMode.SYSTEM_PROXY:
            modes = [("proxy", True)]
        elif selected_mode is NetworkMode.DIRECT:
            modes = [("direct", False)]
        elif domestic:
            modes = [("direct", False), ("proxy", True)]
        else:
            modes = [("proxy", True)]
        self._clients = [
            (
                mode,
                httpx.Client(
                    trust_env=mode_trust_env,
                    follow_redirects=True,
                    timeout=timeout_config,
                    headers=headers,
                ),
            )
            for mode, mode_trust_env in modes
        ]

    def close(self) -> None:
        for _mode, client in self._clients:
            client.close()

    def Statistics_Get(self) -> dict[str, Any]:
        return self._statistics.Snapshot_Get()

    @staticmethod
    def _ShouldRetry(error: Exception) -> bool:
        return isinstance(error, (RetryableSourceError, httpx.TransportError))

    def RequestBytes(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        method: str = "GET",
        request_id: str,
        referer: str | None = None,
        endpoint_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        domain = urlparse(url).netloc
        endpoint = endpoint_key or f"{method.upper()}:{urlparse(url).path}"
        operation_count = 0

        def operation() -> bytes:
            nonlocal operation_count
            if operation_count > 0:
                self._statistics.Retry_Record()
            operation_count += 1
            self._limiter.wait(domain)
            request_headers = dict(headers or {})
            if referer:
                request_headers["Referer"] = referer
            last_transport_error: httpx.TransportError | None = None
            for mode_index, (request_mode, client) in enumerate(self._clients):
                self._statistics.Request_Record(domain, endpoint, request_mode)
                request_started = time.perf_counter()
                try:
                    response = client.request(
                        method,
                        url,
                        params=params,
                        data=data,
                        headers=request_headers or None,
                    )
                except httpx.TransportError as error:
                    elapsed = time.perf_counter() - request_started
                    self._statistics.Failure_Record(elapsed)
                    self._logger.info(
                        "source=%s endpoint=%s mode=%s result=transport_error "
                        "elapsed=%.3fs error=%s",
                        self.source_name,
                        endpoint,
                        request_mode,
                        elapsed,
                        error,
                    )
                    last_transport_error = error
                    if mode_index + 1 < len(self._clients):
                        self._logger.info(
                            "%s 请求 %s 直连失败，尝试系统代理：%s",
                            self.source_name,
                            request_id,
                            error,
                        )
                        continue
                    raise
                elapsed = time.perf_counter() - request_started
                if response.status_code == 429 or response.status_code >= 500:
                    self._statistics.Failure_Record(elapsed)
                    self._logger.info(
                        "source=%s endpoint=%s mode=%s result=http_%s elapsed=%.3fs",
                        self.source_name,
                        endpoint,
                        request_mode,
                        response.status_code,
                        elapsed,
                    )
                    error = RetryableSourceError(
                        f"{self.source_name} 暂时不可用（HTTP {response.status_code}）"
                    )
                    raise error
                if response.status_code >= 400:
                    self._statistics.Failure_Record(elapsed)
                    self._logger.info(
                        "source=%s endpoint=%s mode=%s result=http_%s elapsed=%.3fs",
                        self.source_name,
                        endpoint,
                        request_mode,
                        response.status_code,
                        elapsed,
                    )
                    raise SourceError(
                        f"{self.source_name} 请求失败（HTTP {response.status_code}）"
                    )
                self._statistics.Success_Record(elapsed)
                self._logger.info(
                    "source=%s endpoint=%s mode=%s result=success status=%s elapsed=%.3fs",
                    self.source_name,
                    endpoint,
                    request_mode,
                    response.status_code,
                    elapsed,
                )
                return response.content
            if last_transport_error is not None:
                raise last_transport_error
            raise SourceError(f"{self.source_name} 没有可用的网络请求模式")

        try:
            return Retry_Execute(operation, self._ShouldRetry, attempts=3, base_delay=0.4)
        except (httpx.TransportError, RetryableSourceError) as error:
            self._logger.error(
                "%s 请求 %s 连续重试后仍失败：%s",
                self.source_name,
                request_id,
                error,
                exc_info=True,
            )
            raise SourceError(f"{self.source_name} 网络连接失败：{error}") from error

    def RequestJson(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        method: str = "GET",
        request_id: str,
        referer: str | None = None,
        endpoint_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload = self.RequestBytes(
            url,
            params=params,
            data=data,
            method=method,
            request_id=request_id,
            referer=referer,
            endpoint_key=endpoint_key,
            headers=headers,
        )
        try:
            data = httpx.Response(200, content=payload).json()
        except ValueError as error:
            raise SourceSchemaError(f"{self.source_name} 返回的不是有效 JSON") from error
        if not isinstance(data, dict):
            raise SourceSchemaError(f"{self.source_name} JSON 根节点不是对象")
        return data


def Provenance_Create(
    security: Security,
    field_group: str,
    source_name: str,
    source_ref: str,
    status: DataStatus,
    *,
    original_currency: str | None = None,
    standard_currency: str | None = None,
    missing_reason: str | None = None,
    approximate: bool = False,
    primary_source: str | None = None,
    field_statuses: dict[str, DataStatus] | None = None,
) -> Provenance:
    return Provenance(
        market=security.market,
        code=security.code,
        company_name=security.name,
        field_group=field_group,
        source_name=source_name,
        source_ref=source_ref,
        fetched_at=datetime.now(UTC),
        original_currency=original_currency,
        standard_currency=standard_currency,
        status=status,
        missing_reason=missing_reason,
        approximate=approximate,
        primary_source=primary_source or source_name,
        field_statuses=dict(field_statuses or {}),
    )


class MarketDataSource(ABC):
    source_name: str

    @abstractmethod
    def SecurityList_Fetch(self, market: Market, limit: int = 0) -> list[Security]: ...

    @abstractmethod
    def Financials_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]: ...

    @abstractmethod
    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]: ...

    @abstractmethod
    def IPO_Fetch(self, security: Security) -> SourceValue[IPOInfo]: ...

    @abstractmethod
    def BlockTrade_Fetch(
        self, security: Security, year: int
    ) -> SourceValue[BlockTradeData]: ...

    @abstractmethod
    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]: ...

    def Quotes_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Quote]]:
        results: dict[str, SourceValue[Quote]] = {}
        for security in securities:
            results[security.key] = self.Quote_Fetch(security)
            if progress_callback is not None:
                progress_callback(security)
        return results

    def OutputQuote_Fetch(
        self,
        security: Security,
        primary: SourceValue[Quote] | None = None,
    ) -> SourceValue[Quote]:
        return primary if primary is not None else self.Quote_Fetch(security)

    def Profiles_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Security]]:
        results: dict[str, SourceValue[Security]] = {}
        for security in securities:
            statuses = {
                "板块": DataStatus.OK if security.board else DataStatus.MISSING,
                "行业": DataStatus.OK if security.industry else DataStatus.MISSING,
            }
            results[security.key] = SourceValue(
                security,
                Provenance_Create(
                    security,
                    "板块与行业",
                    self.source_name,
                    "证券列表元数据",
                    (
                        DataStatus.OK
                        if security.board or security.industry
                        else DataStatus.OPTIONAL_MISSING
                    ),
                    missing_reason=(
                        None
                        if all(status is DataStatus.OK for status in statuses.values())
                        else "证券列表元数据未同时提供板块和行业"
                    ),
                    field_statuses=statuses,
                ),
            )
            if progress_callback is not None:
                progress_callback(security)
        return results

    def Concepts_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Security]]:
        results: dict[str, SourceValue[Security]] = {}
        for security in securities:
            status = DataStatus.OK if security.concepts else DataStatus.OPTIONAL_MISSING
            results[security.key] = SourceValue(
                security,
                Provenance_Create(
                    security,
                    "概念",
                    self.source_name,
                    "证券列表元数据",
                    status,
                    missing_reason=None if security.concepts else "证券列表没有概念标签",
                    field_statuses={"概念": status},
                ),
            )
            if progress_callback is not None:
                progress_callback(security)
        return results

    def BlockTrades_Fetch(
        self,
        securities: Sequence[Security],
        year: int,
        progress_callback: Callable[[Security | BatchProgressUpdate], None] | None = None,
    ) -> dict[str, SourceValue[BlockTradeData]]:
        results: dict[str, SourceValue[BlockTradeData]] = {}
        for security in securities:
            results[security.key] = self.BlockTrade_Fetch(security, year)
            if progress_callback is not None:
                progress_callback(security)
        return results

    def Flows_FetchFast(
        self, securities: Sequence[Security]
    ) -> dict[str, SourceValue[FlowData]]:
        results: dict[str, SourceValue[FlowData]] = {}
        for security in securities:
            currency = "CNY" if security.market is Market.A_SHARE else "HKD"
            results[security.key] = SourceValue(
                None,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    "fast-mode-no-reliable-batch-endpoint",
                    DataStatus.OPTIONAL_MISSING,
                    standard_currency=currency,
                    missing_reason=(
                        "快速模式未发现可靠的批量近五个交易日同口径字段，"
                        "为避免逐股慢请求，本次留空"
                    ),
                ),
            )
        return results

    def Flows_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date | None = None,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        _ = as_of_date
        results: dict[str, SourceValue[FlowData]] = {}
        errors: list[tuple[Security, Exception]] = []
        for security in securities:
            try:
                results[security.key] = self.Flow_Fetch(security)
            except Exception as error:
                errors.append((security, error))
            else:
                if progress_callback is not None:
                    progress_callback(security)
        if errors and not results:
            raise errors[0][1]
        for security, error in errors:
            currency = "CNY" if security.market is Market.A_SHARE else "HKD"
            results[security.key] = SourceValue(
                None,
                Provenance_Create(
                    security,
                    "资金流",
                    self.source_name,
                    "single-security-flow-fallback",
                    DataStatus.ERROR,
                    standard_currency=currency,
                    missing_reason=str(error),
                    field_statuses={
                        FLOW_FIVE_DAY_FIELD: DataStatus.ERROR,
                        FlowOneMonthField_Get(security.market): DataStatus.ERROR,
                    },
                ),
            )
            if progress_callback is not None:
                progress_callback(security)
        return results

    def Performance_Get(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None

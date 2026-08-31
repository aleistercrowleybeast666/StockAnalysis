from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from datetime import date
from inspect import signature
from typing import Any, TypeVar, cast

from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import (
    BatchProgressUpdate,
    BlockTradeData,
    FinancialPeriod,
    FlowData,
    IPOInfo,
    Quote,
    Security,
)
from stock_analysis.sources.base import MarketDataSource, SourceValue

T = TypeVar("T")


class FetchCoordinator:
    """一次运行内去重网络请求；不会读取或写入任何跨运行缓存。"""

    def __init__(self, source: MarketDataSource) -> None:
        self._source = source
        self._logger = logging.getLogger("stock_analysis.pipeline.fetch")
        self._values: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._reuse_count = 0

    @property
    def reuse_count(self) -> int:
        with self._lock:
            return self._reuse_count

    def _Value_Fetch(self, key: str, fetcher: Callable[[], T]) -> T:
        with self._lock:
            if key in self._values:
                self._reuse_count += 1
                return cast(T, self._values[key])
        value = fetcher()
        with self._lock:
            existing = self._values.setdefault(key, value)
        return cast(T, existing)

    def SecurityList_Fetch(self, market: Market, limit: int = 0) -> list[Security]:
        values = self._Value_Fetch(
            f"security-list:{market.value}",
            lambda: self._source.SecurityList_Fetch(market, 0),
        )
        minimums = getattr(self._source, "security_list_minimums", {})
        minimum_count = int(minimums.get(market, 0)) if isinstance(minimums, dict) else 0
        if minimum_count and len(values) < minimum_count:
            self._logger.warning(
                "%s 证券池本次只取得 %s 家，低于完整性阈值 %s；"
                "程序不使用跨运行缓存，将继续使用本次实时结果并明确记录不足",
                market.value,
                len(values),
                minimum_count,
            )
        return list(values[:limit] if limit > 0 else values)

    def Financials_Fetch(
        self, security: Security, years: set[int]
    ) -> SourceValue[list[FinancialPeriod]]:
        years_key = ",".join(map(str, sorted(years)))
        return self._Value_Fetch(
            f"financial:{security.key}:{years_key}",
            lambda: self._source.Financials_Fetch(security, years),
        )

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        return self._Value_Fetch(
            f"quote:{security.key}", lambda: self._source.Quote_Fetch(security)
        )

    def Quotes_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Quote]]:
        results: dict[str, SourceValue[Quote]] = {}
        missing: list[Security] = []
        with self._lock:
            for security in securities:
                key = f"quote:{security.key}"
                if key in self._values:
                    self._reuse_count += 1
                    results[security.key] = cast(SourceValue[Quote], self._values[key])
                    if progress_callback is not None:
                        progress_callback(security)
                else:
                    missing.append(security)
        if missing:
            fetcher = self._source.Quotes_Fetch
            if "progress_callback" in signature(fetcher).parameters:
                fetched = fetcher(missing, progress_callback)
            else:
                fetched = fetcher(missing)
                if progress_callback is not None:
                    for security in missing:
                        progress_callback(security)
            with self._lock:
                for security in missing:
                    value = fetched.get(security.key)
                    if value is None:
                        continue
                    self._values[f"quote:{security.key}"] = value
                    results[security.key] = value
        return results

    def OutputQuote_Fetch(self, security: Security) -> SourceValue[Quote]:
        with self._lock:
            primary = cast(
                SourceValue[Quote] | None,
                self._values.get(f"quote:{security.key}"),
            )
        return self._Value_Fetch(
            f"output-quote:{security.key}",
            lambda: self._source.OutputQuote_Fetch(security, primary),
        )

    def Profiles_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Security]]:
        return self._SecurityBatch_Fetch(
            "profile",
            securities,
            self._source.Profiles_Fetch,
            progress_callback,
        )

    def Concepts_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Security]]:
        return self._SecurityBatch_Fetch(
            "concepts",
            securities,
            self._source.Concepts_Fetch,
            progress_callback,
        )

    def _SecurityBatch_Fetch(
        self,
        key_prefix: str,
        securities: Sequence[Security],
        fetcher: Callable[..., dict[str, SourceValue[Security]]],
        progress_callback: Callable[[Security], None] | None,
    ) -> dict[str, SourceValue[Security]]:
        results: dict[str, SourceValue[Security]] = {}
        missing: list[Security] = []
        with self._lock:
            for security in securities:
                key = f"{key_prefix}:{security.key}"
                if key in self._values:
                    self._reuse_count += 1
                    results[security.key] = cast(
                        SourceValue[Security], self._values[key]
                    )
                    if progress_callback is not None:
                        progress_callback(security)
                else:
                    missing.append(security)
        if missing:
            if "progress_callback" in signature(fetcher).parameters:
                fetched = fetcher(missing, progress_callback)
            else:
                fetched = fetcher(missing)
                if progress_callback is not None:
                    for security in missing:
                        progress_callback(security)
            with self._lock:
                for security in missing:
                    value = fetched.get(security.key)
                    if value is None:
                        continue
                    self._values[f"{key_prefix}:{security.key}"] = value
                    results[security.key] = value
        return results

    def IPO_Fetch(self, security: Security) -> SourceValue[IPOInfo]:
        return self._Value_Fetch(
            f"ipo:{security.key}", lambda: self._source.IPO_Fetch(security)
        )

    def BlockTrade_Fetch(
        self, security: Security, year: int
    ) -> SourceValue[BlockTradeData]:
        return self._Value_Fetch(
            f"block:{security.key}:{year}",
            lambda: self._source.BlockTrade_Fetch(security, year),
        )

    def BlockTrades_Fetch(
        self,
        securities: Sequence[Security],
        year: int,
        progress_callback: Callable[[Security | BatchProgressUpdate], None] | None = None,
    ) -> dict[str, SourceValue[BlockTradeData]]:
        results: dict[str, SourceValue[BlockTradeData]] = {}
        missing: list[Security] = []
        with self._lock:
            for security in securities:
                key = f"block:{security.key}:{year}"
                if key in self._values:
                    self._reuse_count += 1
                    results[security.key] = cast(
                        SourceValue[BlockTradeData], self._values[key]
                    )
                    if progress_callback is not None:
                        progress_callback(security)
                else:
                    missing.append(security)
        if missing:
            source_fetch = self._source.BlockTrades_Fetch
            if "progress_callback" in signature(source_fetch).parameters:
                fetched = source_fetch(missing, year, progress_callback)
            else:
                fetched = source_fetch(missing, year)
                if progress_callback is not None:
                    for security in missing:
                        progress_callback(security)
            with self._lock:
                for security in missing:
                    value = fetched.get(security.key)
                    if value is None:
                        continue
                    self._values[f"block:{security.key}:{year}"] = value
                    results[security.key] = value
        return results

    def Flow_Fetch(self, security: Security) -> SourceValue[FlowData]:
        return self._Value_Fetch(
            f"flow:{security.key}", lambda: self._source.Flow_Fetch(security)
        )

    def Flows_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date | None = None,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        results: dict[str, SourceValue[FlowData]] = {}
        missing: list[Security] = []
        with self._lock:
            for security in securities:
                key = f"flow:{security.key}"
                if key in self._values:
                    self._reuse_count += 1
                    results[security.key] = cast(
                        SourceValue[FlowData], self._values[key]
                    )
                    if progress_callback is not None:
                        progress_callback(security)
                else:
                    missing.append(security)
        if missing:
            source_fetch = self._source.Flows_Fetch
            if "progress_callback" in signature(source_fetch).parameters:
                fetched = source_fetch(missing, as_of_date, progress_callback)
            else:
                fetched = source_fetch(missing, as_of_date)
                if progress_callback is not None:
                    for security in missing:
                        progress_callback(security)
            with self._lock:
                for security in missing:
                    value = fetched.get(security.key)
                    if value is None:
                        continue
                    self._values[f"flow:{security.key}"] = value
                    results[security.key] = value
        return results

    def Flows_FetchFast(
        self, securities: Sequence[Security]
    ) -> dict[str, SourceValue[FlowData]]:
        return self.Flows_Fetch(securities)

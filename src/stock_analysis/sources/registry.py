from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from typing import Any

from stock_analysis.common.performance import Statistics_Merge
from stock_analysis.config.models import AppConfig
from stock_analysis.domain.calculations import Calculation_IssueMarketCap
from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import BlockTradeData, FlowData, Quote, Security
from stock_analysis.sources.aastocks import AastocksSource
from stock_analysis.sources.base import (
    HttpJsonClient,
    MarketDataSource,
    Provenance_Create,
    SourceError,
    SourceValue,
)
from stock_analysis.sources.cninfo import CninfoSource
from stock_analysis.sources.eastmoney import EastmoneySource
from stock_analysis.sources.etnet import EtnetSource
from stock_analysis.sources.exchanges import OfficialAShareListSource
from stock_analysis.sources.fixture import FixtureSource
from stock_analysis.sources.fx import FrankfurterFxSource
from stock_analysis.sources.hkex import HkexSecurityListSource
from stock_analysis.sources.tencent import TencentQuoteSource
from stock_analysis.sources.tonghuashun import TonghuashunSource
from stock_analysis.sources.tradego import TradegoSource


class LiveMarketDataSource(MarketDataSource):
    source_name = "公开结构化数据组合源"
    security_list_minimums = {Market.A_SHARE: 4_000, Market.HK: 1_000}
    _SAMPLES = {
        Market.A_SHARE: [
            Security(Market.A_SHARE, "SSE", "600519", "贵州茅台"),
            Security(Market.A_SHARE, "SZSE", "000001", "平安银行", is_financial=True),
            Security(Market.A_SHARE, "SZSE", "300750", "宁德时代"),
            Security(Market.A_SHARE, "SSE", "688981", "中芯国际"),
        ],
        Market.HK: [
            Security(Market.HK, "HKEX", "00700", "腾讯控股"),
            Security(Market.HK, "HKEX", "00941", "中国移动"),
            Security(Market.HK, "HKEX", "09988", "阿里巴巴-W"),
            Security(Market.HK, "HKEX", "00005", "汇丰控股", is_financial=True),
        ],
    }

    def __init__(
        self,
        eastmoney: EastmoneySource,
        hkex: HkexSecurityListSource,
        official_a_share: OfficialAShareListSource,
        cninfo: CninfoSource,
        tencent: TencentQuoteSource,
        aastocks: AastocksSource,
        tradego: TradegoSource,
        tonghuashun: TonghuashunSource | None = None,
        etnet: EtnetSource | None = None,
        *,
        sample_mode: bool,
        concurrency: int,
        clients: Sequence[HttpJsonClient] = (),
    ) -> None:
        self._eastmoney = eastmoney
        self._hkex = hkex
        self._official_a_share = official_a_share
        self._cninfo = cninfo
        self._tencent = tencent
        self._aastocks = aastocks
        self._tradego = tradego
        self._tonghuashun = tonghuashun
        self._etnet = etnet
        self._sample_mode = sample_mode
        self.security_list_minimums = (
            {} if sample_mode else {Market.A_SHARE: 4_000, Market.HK: 1_000}
        )
        self._clients = list(clients)
        self._logger = logging.getLogger("stock_analysis.sources")
        self._cninfo_log_lock = threading.Lock()
        self._cninfo_unconfigured_logged = False
        self._concurrency = max(1, concurrency)

    def SecurityList_Fetch(self, market: Market, limit: int = 0) -> list[Security]:
        if self._sample_mode:
            samples = list(self._SAMPLES[market])
            return samples[:limit] if limit > 0 else samples
        if market is Market.HK:
            try:
                values = self._hkex.SecurityList_Fetch(limit)
                if limit <= 0 and len(values) < self.security_list_minimums[market]:
                    raise SourceError(
                        f"HKEX 证券列表仅返回 {len(values)} 家，低于完整性阈值"
                    )
                return values
            except SourceError as primary_error:
                self._logger.warning(
                    "HKEX 证券列表失败，改用东方财富港股列表：%s", primary_error
                )
                return self._eastmoney.SecurityList_Fetch(market, limit)
        try:
            values = self._official_a_share.SecurityList_Fetch(limit)
            if limit <= 0 and len(values) < self.security_list_minimums[market]:
                raise SourceError(
                    f"沪深北交易所官方 A 股列表仅返回 {len(values)} 家，低于完整性阈值"
                )
            return values
        except SourceError as primary_error:
            self._logger.warning(
                "沪深北交易所官方 A 股列表失败，改用东方财富列表：%s",
                primary_error,
            )
            try:
                return self._eastmoney.SecurityList_Fetch(market, limit)
            except SourceError as fallback_error:
                raise SourceError(
                    f"A 股证券列表主源失败：{primary_error}；"
                    f"东方财富备源失败：{fallback_error}"
                ) from fallback_error

    def Financials_Fetch(self, security: Security, years: set[int]):
        if security.market is Market.HK:
            return self._eastmoney.Financials_Fetch(security, years)
        try:
            return self._cninfo.Financials_Fetch(security, years)
        except SourceError as primary_error:
            with self._cninfo_log_lock:
                should_log = self._cninfo.configured or not self._cninfo_unconfigured_logged
                self._cninfo_unconfigured_logged = True
            if should_log:
                self._logger.warning(
                    "巨潮 A 股财务主源不可用，自动回退东方财富：%s", primary_error
                )
            fallback = self._eastmoney.Financials_Fetch(security, years)
            provenance = replace(
                fallback.provenance,
                primary_source=self._cninfo.source_name,
                source_ref=(
                    f"{fallback.provenance.source_ref}；巨潮回退原因：{primary_error}"
                ),
            )
            return SourceValue(fallback.value, provenance)

    def Quote_Fetch(self, security: Security):
        try:
            primary = self._eastmoney.Quote_Fetch(security)
        except SourceError as error:
            primary = None
            primary_reason = str(error)
        else:
            if primary.value is not None:
                return primary
            primary_reason = primary.provenance.missing_reason or "东方财富行情为空"
        fallback_source = (
            self._aastocks if security.market is Market.HK else self._tencent
        )
        fallback = fallback_source.Quote_Fetch(security)
        provenance = replace(
            fallback.provenance,
            primary_source=self._eastmoney.source_name,
            source_ref=(
                f"{fallback.provenance.source_ref}；东方财富回退原因：{primary_reason}"
            ),
        )
        return SourceValue(fallback.value, provenance)

    def Quotes_Fetch(
        self, securities: Sequence[Security]
    ) -> dict[str, SourceValue[Quote]]:
        try:
            results = self._eastmoney.Quotes_Fetch(securities)
        except SourceError as error:
            self._logger.warning("东方财富批量行情不可用，逐只改用行情备源：%s", error)
            results = {}
        for security in securities:
            result = results.get(security.key)
            if result is not None and result.value is not None:
                continue
            try:
                results[security.key] = self.Quote_Fetch(security)
            except SourceError as fallback_error:
                self._logger.warning(
                    "%s %s 行情主备源均失败：%s",
                    security.market.value,
                    security.code,
                    fallback_error,
                )
        return results

    def IPO_Fetch(self, security: Security):
        primary = self._eastmoney.IPO_Fetch(security)
        ipo = primary.value
        if (
            security.market is not Market.A_SHARE
            or ipo is None
            or ipo.post_issue_total_shares is not None
            or self._tonghuashun is None
        ):
            return primary
        try:
            fallback = self._tonghuashun.PostIssueShares_Fetch(
                security, ipo.listing_date or security.listing_date
            )
        except SourceError as error:
            reason = f"同花顺历史股本备源失败：{error}"
            return SourceValue(
                ipo,
                replace(
                    primary.provenance,
                    source_ref=f"{primary.provenance.source_ref}；{reason}",
                    missing_reason=reason,
                ),
            )
        if fallback.value is None:
            reason = fallback.provenance.missing_reason or "同花顺历史股本备源为空"
            return SourceValue(
                ipo,
                replace(
                    primary.provenance,
                    source_ref=(
                        f"{primary.provenance.source_ref}；"
                        f"{fallback.provenance.source_ref}"
                    ),
                    missing_reason=reason,
                ),
            )
        issue_market_cap, _unused = Calculation_IssueMarketCap(
            ipo.issue_price,
            fallback.value,
            ipo.issued_shares,
        )
        merged = replace(
            ipo,
            post_issue_total_shares=fallback.value,
            issue_market_cap=issue_market_cap,
            approximate=True,
        )
        field_statuses = dict(primary.provenance.field_statuses)
        field_statuses["发行后总股本"] = DataStatus.OK
        field_statuses["发行时总市值"] = (
            DataStatus.OK if issue_market_cap is not None else DataStatus.MISSING
        )
        missing_fields = [
            name for name, status in field_statuses.items() if status is not DataStatus.OK
        ]
        return SourceValue(
            merged,
            replace(
                fallback.provenance,
                source_ref=(
                    f"{fallback.provenance.source_ref}；东方财富发行资料="
                    f"{primary.provenance.source_ref}"
                ),
                missing_reason=(
                    f"未取得字段：{', '.join(missing_fields)}"
                    if missing_fields
                    else None
                ),
                field_statuses=field_statuses,
            ),
        )

    def BlockTrade_Fetch(self, security: Security, year: int):
        if security.market is Market.HK:
            if self._etnet is not None:
                return self._etnet.BlockTrade_Fetch(security, year)
            return self._aastocks.BlockTrade_Fetch(security, year)
        return self._eastmoney.BlockTrade_Fetch(security, year)

    def BlockTrades_Fetch(
        self,
        securities: Sequence[Security],
        year: int,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[BlockTradeData]]:
        a_share = [item for item in securities if item.market is Market.A_SHARE]
        hk = [item for item in securities if item.market is Market.HK]
        results: dict[str, SourceValue[BlockTradeData]] = {}
        if a_share:
            try:
                results.update(self._eastmoney.BlockTrades_Fetch(a_share, year))
            except Exception as error:
                self._logger.warning(
                    "A 股年度大宗交易批量源失败；港股阶段仍将独立继续：%s",
                    error,
                )
                for security in a_share:
                    results[security.key] = self._BlockTradeError_Create(
                        security, year, "东方财富 A 股年度大宗交易", error
                    )
            if progress_callback is not None:
                for security in a_share:
                    progress_callback(security)
        if hk and self._etnet is not None:
            try:
                results.update(self._etnet.BlockTrades_Fetch(hk, year))
            except Exception as error:
                self._logger.warning(
                    "ETNet 港股年度大宗/大额交易批量源失败；逐只记录错误：%s",
                    error,
                )
                for security in hk:
                    results[security.key] = self._BlockTradeError_Create(
                        security, year, "ETNet 港股 Block Trades", error
                    )
            if progress_callback is not None:
                for security in hk:
                    progress_callback(security)
        else:
            for security in hk:
                try:
                    results[security.key] = self._aastocks.BlockTrade_Fetch(
                        security, year
                    )
                except Exception as error:
                    self._logger.warning(
                        "港股 %s 年度大宗/大额交易失败；其他证券继续：%s",
                        security.code,
                        error,
                    )
                    results[security.key] = self._BlockTradeError_Create(
                        security, year, "AASTOCKS 港股 Block Trades", error
                    )
                if progress_callback is not None:
                    progress_callback(security)
        return results

    @staticmethod
    def _BlockTradeError_Create(
        security: Security,
        year: int,
        source_name: str,
        error: Exception,
    ) -> SourceValue[BlockTradeData]:
        currency = "CNY" if security.market is Market.A_SHARE else "HKD"
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "大宗交易",
                source_name,
                f"年度={year}",
                DataStatus.ERROR,
                standard_currency=currency,
                missing_reason=str(error),
                field_statuses={
                    "当年累计大宗交易笔数": DataStatus.ERROR,
                    "当年累计大宗交易金额": DataStatus.ERROR,
                },
            ),
        )

    def Flow_Fetch(self, security: Security):
        if security.market is Market.HK:
            return self._aastocks.Flow_Fetch(security)
        return self._eastmoney.Flow_Fetch(security)

    def Flows_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date | None = None,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        a_share = [item for item in securities if item.market is Market.A_SHARE]
        hk = [item for item in securities if item.market is Market.HK]
        reported: set[str] = set()

        def report_once(security: Security) -> None:
            if progress_callback is None or security.key in reported:
                return
            reported.add(security.key)
            progress_callback(security)

        results = self._AFlows_Fetch(a_share, report_once)
        results.update(
            self._HkFlows_Fetch(hk, as_of_date or date.today(), report_once)
        )
        return results

    def _AFlows_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        if not securities:
            return {}
        probe_results: dict[str, SourceValue[FlowData]] = {}
        healthy_probe_count = 0
        probe_errors: list[str] = []
        probe_count = min(3, len(securities))
        for security in securities[:probe_count]:
            try:
                result = self._eastmoney.Flow_Fetch(security)
            except SourceError as error:
                probe_errors.append(str(error))
                continue
            probe_results[security.key] = result
            if result.value is not None and result.value.one_month_net is not None:
                healthy_probe_count += 1
        if healthy_probe_count != probe_count:
            self._logger.warning(
                "A 股资金流历史主源健康探测未全部取得 22 日数据"
                "（成功=%s/%s，错误=%s）；"
                "本次运行剩余证券直接切换同花顺资金面备源，避免重复数百次失效请求",
                healthy_probe_count,
                probe_count,
                probe_errors[:1] or "返回历史不足",
            )
            fallback_results = self._ParallelFlow_Fetch(
                securities,
                self._AFlowFallback_Fetch,
                "同花顺 A 股资金流备源",
                progress_callback,
            )
            for security in securities:
                fallback = fallback_results.get(security.key)
                primary = probe_results.get(security.key)
                if fallback is not None and (
                    fallback.value is not None or primary is None
                ):
                    probe_results[security.key] = fallback
            return probe_results
        if progress_callback is not None:
            for security in securities[:probe_count]:
                progress_callback(security)
        remaining = securities[probe_count:]
        probe_results.update(
            self._ParallelFlow_Fetch(
                remaining,
                self._AFlow_WithFallbackFetch,
                "A 股资金流主备源",
                progress_callback,
            )
        )
        return probe_results

    def _AFlow_WithFallbackFetch(self, security: Security) -> SourceValue[FlowData]:
        try:
            primary = self._eastmoney.Flow_Fetch(security)
        except SourceError as error:
            primary = None
            primary_reason = str(error)
        else:
            if primary.value is not None:
                return primary
            primary_reason = primary.provenance.missing_reason or "东方财富资金流为空"
        fallback = self._AFlowFallback_Fetch(security)
        return SourceValue(
            fallback.value,
            replace(
                fallback.provenance,
                primary_source=self._eastmoney.source_name,
                source_ref=(
                    f"{fallback.provenance.source_ref}；东方财富回退原因："
                    f"{primary_reason}"
                ),
            ),
        )

    def _AFlowFallback_Fetch(self, security: Security) -> SourceValue[FlowData]:
        if self._tonghuashun is not None:
            return self._tonghuashun.Flow_Fetch(security)
        return self._tencent.Flow_Fetch(security)

    def _HkFlows_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        if not securities:
            return {}
        probe_results: dict[str, SourceValue[FlowData]] = {}
        probe_errors: list[str] = []
        probe_count = min(3, len(securities))
        healthy_probe_count = 0
        for security in securities[:probe_count]:
            try:
                result = self._eastmoney.Flow_Fetch(security)
            except SourceError as error:
                probe_errors.append(str(error))
                continue
            probe_results[security.key] = result
            if result.value is not None and result.value.one_month_net is not None:
                healthy_probe_count += 1
        if healthy_probe_count != probe_count:
            self._logger.warning(
                "港股资金流历史主源健康探测未全部取得 22 日数据"
                "（成功=%s/%s，错误=%s）；"
                "本次运行剩余证券改用 TradeGo/AASTOCKS 5 日来源",
                healthy_probe_count,
                probe_count,
                probe_errors[:1] or "返回历史不足",
            )
            return self._HkFiveDayFallbacks_Fetch(
                securities, as_of_date, progress_callback
            )
        if progress_callback is not None:
            for security in securities[:probe_count]:
                progress_callback(security)
        probe_results.update(
            self._ParallelFlow_Fetch(
                securities[probe_count:],
                self._eastmoney.Flow_Fetch,
                "东方财富港股 5/22 日资金流主源",
                progress_callback,
            )
        )
        missing = [
            security
            for security in securities
            if probe_results.get(security.key) is None
            or probe_results[security.key].value is None
            or probe_results[security.key].value.five_day_net is None
        ]
        if missing:
            fallbacks = self._HkFiveDayFallbacks_Fetch(
                missing, as_of_date
            )
            probe_results.update(fallbacks)
        return probe_results

    def _HkFiveDayFallbacks_Fetch(
        self,
        securities: Sequence[Security],
        as_of_date: date,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        try:
            results = self._tradego.Flows_Fetch(securities, as_of_date)
        except SourceError as error:
            self._logger.warning("TradeGo 港股批量资金流不可用，改用 AASTOCKS 5 日页：%s", error)
            results = {}
        missing = [
            security
            for security in securities
            if results.get(security.key) is None
            or results[security.key].value is None
            or results[security.key].value.five_day_net is None
        ]
        if progress_callback is not None:
            missing_keys = {security.key for security in missing}
            for security in securities:
                if security.key not in missing_keys:
                    progress_callback(security)
        if missing:
            fallbacks = self._ParallelFlow_Fetch(
                missing,
                self._aastocks.Flow_Fetch,
                "AASTOCKS 港股 5 日资金流备源",
                progress_callback,
            )
            for security in missing:
                if security.key in fallbacks:
                    results[security.key] = fallbacks[security.key]
        return results

    def _ParallelFlow_Fetch(
        self,
        securities: Sequence[Security],
        fetcher: Any,
        source_label: str,
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[FlowData]]:
        results: dict[str, SourceValue[FlowData]] = {}
        if not securities:
            return results
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {executor.submit(fetcher, security): security for security in securities}
            for future in as_completed(futures):
                security = futures[future]
                try:
                    results[security.key] = future.result()
                except Exception as error:
                    self._logger.warning(
                        "%s %s 失败，其他公司继续：%s",
                        source_label,
                        security.code,
                        error,
                    )
                    results[security.key] = SourceValue(
                        None,
                        Provenance_Create(
                            security,
                            "资金流",
                            source_label,
                            source_label,
                            DataStatus.ERROR,
                            standard_currency=(
                                "CNY" if security.market is Market.A_SHARE else "HKD"
                            ),
                            missing_reason=str(error),
                            field_statuses={
                                "近五个交易日资金净额": DataStatus.ERROR,
                                "近一月资金净额（最近22个交易日）": DataStatus.ERROR,
                            },
                        ),
                    )
                if progress_callback is not None:
                    progress_callback(security)
        return results

    def Flows_FetchFast(
        self, securities: Sequence[Security]
    ) -> dict[str, SourceValue[FlowData]]:
        return self._eastmoney.Flows_FetchFast(securities)

    def Performance_Get(self) -> dict[str, Any]:
        return Statistics_Merge([client.Statistics_Get() for client in self._clients])

    def close(self) -> None:
        self._eastmoney.close()
        self._hkex.close()
        self._official_a_share.close()
        self._cninfo.close()
        self._tencent.close()
        self._aastocks.close()
        self._tradego.close()
        if self._tonghuashun is not None:
            self._tonghuashun.close()
        if self._etnet is not None:
            self._etnet.close()


def SourceRegistry_Create(
    config: AppConfig,
) -> MarketDataSource:
    if config.fixture_mode:
        return FixtureSource()
    eastmoney_client = HttpJsonClient(
        "东方财富",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    hkex_client = HttpJsonClient(
        "HKEX",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    fx_client = HttpJsonClient(
        "Frankfurter",
        network_mode=config.network_mode,
        domestic=False,
        request_interval=config.request_interval,
    )
    official_a_share_client = HttpJsonClient(
        "沪深北交易所官方证券列表",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    cninfo_client = HttpJsonClient(
        "巨潮资讯",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    tencent_client = HttpJsonClient(
        "腾讯行情",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    aastocks_client = HttpJsonClient(
        "AASTOCKS",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    tradego_client = HttpJsonClient(
        "TradeGo 港股资金流",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    tonghuashun_client = HttpJsonClient(
        "同花顺",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    etnet_client = HttpJsonClient(
        "ETNet",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    try:
        cninfo_multiplier = float(os.environ.get("CNINFO_AMOUNT_MULTIPLIER", "1"))
    except ValueError:
        cninfo_multiplier = 1.0
    cninfo_source = CninfoSource(
        cninfo_client,
        access_token=os.environ.get("CNINFO_ACCESS_TOKEN"),
        income_api_url=os.environ.get("CNINFO_INCOME_API_URL"),
        cashflow_api_url=os.environ.get("CNINFO_CASHFLOW_API_URL"),
        amount_multiplier=cninfo_multiplier,
    )
    return LiveMarketDataSource(
        EastmoneySource(
            eastmoney_client, FrankfurterFxSource(fx_client)
        ),
        HkexSecurityListSource(hkex_client),
        OfficialAShareListSource(official_a_share_client),
        cninfo_source,
        TencentQuoteSource(tencent_client),
        AastocksSource(aastocks_client),
        TradegoSource(tradego_client),
        TonghuashunSource(tonghuashun_client),
        EtnetSource(etnet_client, concurrency=config.concurrency),
        sample_mode=config.test_mode,
        concurrency=config.concurrency,
        clients=(
            eastmoney_client,
            hkex_client,
            fx_client,
            official_a_share_client,
            cninfo_client,
            tencent_client,
            aastocks_client,
            tradego_client,
            tonghuashun_client,
            etnet_client,
        ),
    )

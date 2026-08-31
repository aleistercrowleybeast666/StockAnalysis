from __future__ import annotations

import logging
import os
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from inspect import signature
from typing import Any

from stock_analysis.common.performance import Statistics_Merge
from stock_analysis.config.models import AppConfig
from stock_analysis.domain.calculations import Calculation_IssueMarketCap
from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.fields import (
    FLOW_FIVE_DAY_FIELD,
    FlowOneMonthField_Get,
)
from stock_analysis.domain.models import (
    BatchProgressUpdate,
    BlockTradeData,
    FlowData,
    Quote,
    Security,
)
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
from stock_analysis.sources.hkex import HkexBlockTradeSource, HkexSecurityListSource
from stock_analysis.sources.issuer_mapping import IssuerMapping_Find
from stock_analysis.sources.normalization import (
    Security_AShareBoardGet,
    Security_FinancialClassify,
)
from stock_analysis.sources.sina import SinaSource
from stock_analysis.sources.tencent import TencentQuoteSource
from stock_analysis.sources.tonghuashun import TonghuashunSource
from stock_analysis.sources.tradego import TradegoSource


class LiveMarketDataSource(MarketDataSource):
    source_name = "公开结构化数据组合源"
    security_list_minimums = {Market.A_SHARE: 4_000, Market.HK: 1_000}
    _BLOCK_HKEX_SCAN_START_FRACTION = 0.10
    _BLOCK_HKEX_SCAN_END_FRACTION = 0.98
    _SAMPLES = {
        Market.A_SHARE: [
            Security(Market.A_SHARE, "SSE", "600519", "贵州茅台", board="沪市主板"),
            Security(
                Market.A_SHARE,
                "SZSE",
                "000001",
                "平安银行",
                is_financial=True,
                board="深市主板",
            ),
            Security(Market.A_SHARE, "SZSE", "300750", "宁德时代", board="创业板"),
            Security(Market.A_SHARE, "SSE", "688981", "中芯国际", board="科创板"),
        ],
        Market.HK: [
            Security(Market.HK, "HKEX", "00700", "腾讯控股", board="主板"),
            Security(Market.HK, "HKEX", "00941", "中国移动", board="主板"),
            Security(Market.HK, "HKEX", "09988", "阿里巴巴-W", board="主板"),
            Security(
                Market.HK,
                "HKEX",
                "00005",
                "汇丰控股",
                is_financial=True,
                board="主板",
            ),
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
        hkex_block: HkexBlockTradeSource | None = None,
        sina: SinaSource | None = None,
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
        self._hkex_block = hkex_block
        self._sina = sina
        self._sample_mode = sample_mode
        self.security_list_minimums = (
            {} if sample_mode else {Market.A_SHARE: 4_000, Market.HK: 1_000}
        )
        self._clients = list(clients)
        self._logger = logging.getLogger("stock_analysis.sources")
        self._cninfo_log_lock = threading.Lock()
        self._cninfo_unconfigured_logged = False
        self._concurrency = max(1, concurrency)
        self._classification_lock = threading.Lock()
        self._classification_cache: dict[str, SourceValue[Security]] = {}
        self._classification_source_counts: Counter[str] = Counter()
        self._classification_company_fallbacks = 0
        self._classification_company_keys: set[str] = set()

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
                try:
                    metadata_values = self._eastmoney.SecurityList_Fetch(market, 0)
                except SourceError as metadata_error:
                    self._logger.warning(
                        "东方财富港股行业批量元数据不可用，保留 HKEX 名单与板块：%s",
                        metadata_error,
                    )
                    return values
                metadata_by_code = {item.code: item for item in metadata_values}
                merged: list[Security] = []
                industry_hits = 0
                for security in values:
                    metadata = metadata_by_code.get(security.code)
                    industry = metadata.industry if metadata is not None else None
                    if industry:
                        industry_hits += 1
                    merged.append(
                        replace(
                            security,
                            industry=industry or security.industry,
                            is_financial=Security_FinancialClassify(
                                security.name,
                                industry or security.industry,
                                security_code=security.code,
                            ),
                        )
                    )
                self._logger.info(
                    "港股证券元数据批量合并：HKEX 板块=%s/%s，东方财富行业=%s/%s",
                    sum(bool(item.board) for item in merged),
                    len(merged),
                    industry_hits,
                    len(merged),
                )
                return merged
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
            primary_error: SourceError | None = None
            try:
                primary = self._eastmoney.Financials_Fetch(security, years)
            except SourceError as error:
                primary_error = error
                primary = None
            primary_periods = list(primary.value or []) if primary is not None else []
            available_years = {period.fiscal_year for period in primary_periods}
            missing_years = set(years) - available_years
            mapping = IssuerMapping_Find(security)
            if not missing_years or mapping is None:
                if primary is not None:
                    return primary
                assert primary_error is not None
                raise primary_error
            try:
                mapped = self._eastmoney.FinancialsMappedAForHk_Fetch(
                    security,
                    mapping.AShareSecurity_Create(),
                    missing_years,
                    mapping.evidence,
                )
            except SourceError as mapping_error:
                if primary is None:
                    raise SourceError(
                        f"港股自身财务失败：{primary_error}；A/H 映射失败：{mapping_error}"
                    ) from mapping_error
                return SourceValue(
                    primary_periods,
                    replace(
                        primary.provenance,
                        source_ref=(
                            f"{primary.provenance.source_ref}；"
                            f"A/H 映射 {mapping.a_share_code} 失败：{mapping_error}"
                        ),
                        missing_reason=(
                            f"缺少年度 {sorted(missing_years)}；"
                            f"A/H 映射失败：{mapping_error}"
                        ),
                    ),
                )
            merged_by_year = {
                period.fiscal_year: period for period in mapped.value or []
            }
            merged_by_year.update(
                {period.fiscal_year: period for period in primary_periods}
            )
            merged = [merged_by_year[year] for year in sorted(merged_by_year, reverse=True)]
            unresolved = sorted(set(years) - set(merged_by_year))
            primary_ref = (
                primary.provenance.source_ref
                if primary is not None
                else f"港股自身财务失败：{primary_error}"
            )
            return SourceValue(
                merged,
                replace(
                    mapped.provenance,
                    source_ref=f"{primary_ref}；{mapped.provenance.source_ref}",
                    missing_reason=(
                        f"仍缺少完整年度：{unresolved}" if unresolved else None
                    ),
                    status=DataStatus.OK if merged else DataStatus.MISSING,
                ),
            )
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

    def Quote_Fetch(self, security: Security) -> SourceValue[Quote]:
        try:
            primary = self._eastmoney.Quote_Fetch(security)
        except SourceError as error:
            primary = None
            primary_error = str(error)
        else:
            primary_error = None
        return self._QuoteFallbacks_Apply(security, primary, primary_error)

    def Quotes_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Quote]]:
        try:
            return self._eastmoney.Quotes_Fetch(securities, progress_callback)
        except SourceError as error:
            self._logger.warning(
                "东方财富全市场批量行情不可用；为避免排名阶段产生数千次逐公司请求，"
                "不在证券池阶段扩散备源：%s",
                error,
            )
            raise

    def OutputQuote_Fetch(
        self,
        security: Security,
        primary: SourceValue[Quote] | None = None,
    ) -> SourceValue[Quote]:
        if primary is None:
            return self.Quote_Fetch(security)
        return self._QuoteFallbacks_Apply(security, primary, None)

    def _QuoteFallbacks_Apply(
        self,
        security: Security,
        primary: SourceValue[Quote] | None,
        primary_error: str | None,
    ) -> SourceValue[Quote]:
        current = primary
        errors = [f"东方财富：{primary_error}"] if primary_error else []
        fallback_sources: list[Any]
        if security.market is Market.HK:
            fallback_sources = [
                source for source in (self._etnet, self._aastocks) if source is not None
            ]
        else:
            fallback_sources = [self._tencent]
            if self._sina is not None:
                fallback_sources.append(self._sina)
        for source in fallback_sources:
            value = current.value if current is not None else None
            if (
                value is not None
                and value.price is not None
                and value.market_cap is not None
            ):
                break
            try:
                fallback = source.Quote_Fetch(security)
            except SourceError as error:
                errors.append(f"{source.source_name}：{error}")
                continue
            current = self._QuoteResults_Merge(security, current, fallback)
        if current is None:
            return SourceValue(
                None,
                Provenance_Create(
                    security,
                    "最新行情",
                    self.source_name,
                    "；".join(errors) or "行情主备源均无返回",
                    DataStatus.MISSING,
                    standard_currency=(
                        "CNY" if security.market is Market.A_SHARE else "HKD"
                    ),
                    missing_reason="；".join(errors) or "行情主备源均未取得",
                    primary_source=self._eastmoney.source_name,
                    field_statuses={
                        "最新可得价格": DataStatus.MISSING,
                        "最新总市值": DataStatus.MISSING,
                        "行情日期": DataStatus.MISSING,
                    },
                ),
            )
        if errors:
            current = SourceValue(
                current.value,
                replace(
                    current.provenance,
                    source_ref=f"{current.provenance.source_ref}；{'；'.join(errors)}",
                    missing_reason=(
                        "；".join(
                            filter(
                                None,
                                (current.provenance.missing_reason, *errors),
                            )
                        )
                        or None
                    ),
                ),
            )
        return current

    @staticmethod
    def _QuoteResults_Merge(
        security: Security,
        current: SourceValue[Quote] | None,
        fallback: SourceValue[Quote],
    ) -> SourceValue[Quote]:
        current_quote = current.value if current is not None else None
        fallback_quote = fallback.value
        price = (
            current_quote.price
            if current_quote is not None and current_quote.price is not None
            else fallback_quote.price
            if fallback_quote is not None
            else None
        )
        market_cap = (
            current_quote.market_cap
            if current_quote is not None and current_quote.market_cap is not None
            else fallback_quote.market_cap
            if fallback_quote is not None
            else None
        )
        price_from_fallback = (
            current_quote is None or current_quote.price is None
        ) and fallback_quote is not None and fallback_quote.price is not None
        quote_date = (
            fallback_quote.quote_date
            if price_from_fallback
            else current_quote.quote_date
            if current_quote is not None
            else fallback_quote.quote_date
            if fallback_quote is not None
            else None
        )
        currency = (
            current_quote.currency
            if current_quote is not None
            else fallback_quote.currency
            if fallback_quote is not None
            else "CNY"
            if security.market is Market.A_SHARE
            else "HKD"
        )
        value = (
            Quote(security.key, quote_date, price, market_cap, currency)
            if quote_date is not None and (price is not None or market_cap is not None)
            else None
        )
        provenances = [
            item
            for item in (
                current.provenance if current is not None else None,
                fallback.provenance,
            )
            if item is not None
        ]
        source_names = "+".join(dict.fromkeys(item.source_name for item in provenances))
        missing_fields = [
            field
            for field, field_value in (
                ("最新可得价格", price),
                ("最新总市值", market_cap),
                ("行情日期", quote_date),
            )
            if field_value is None
        ]
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "最新行情",
                source_names or "行情组合源",
                "；".join(
                    f"{item.source_name}={item.source_ref}" for item in provenances
                ),
                DataStatus.OK if value is not None else DataStatus.MISSING,
                original_currency=currency,
                standard_currency=currency,
                missing_reason=(
                    f"字段级回退后仍缺：{'、'.join(missing_fields)}"
                    if missing_fields
                    else None
                ),
                primary_source="东方财富",
                field_statuses={
                    "最新可得价格": (
                        DataStatus.OK if price is not None else DataStatus.MISSING
                    ),
                    "最新总市值": (
                        DataStatus.OK if market_cap is not None else DataStatus.MISSING
                    ),
                    "行情日期": (
                        DataStatus.OK if quote_date is not None else DataStatus.MISSING
                    ),
                },
            ),
        )

    def Profiles_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Security]]:
        with self._classification_lock:
            self._classification_company_keys.update(item.key for item in securities)
        results: dict[str, SourceValue[Security]] = {}
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {
                executor.submit(self._Profile_FetchOne, security): security
                for security in securities
            }
            for future in as_completed(futures):
                security = futures[future]
                try:
                    results[security.key] = future.result()
                except Exception as error:
                    self._logger.warning(
                        "%s %s 板块/行业补全失败：%s",
                        security.market.value,
                        security.code,
                        error,
                    )
                    board = security.board or (
                        Security_AShareBoardGet(security.exchange, security.code)
                        if security.market is Market.A_SHARE
                        else None
                    )
                    results[security.key] = SourceValue(
                        replace(security, board=board),
                        Provenance_Create(
                            security,
                            "板块与行业",
                            self.source_name,
                            "证券列表元数据与公司资料备源",
                            DataStatus.MISSING,
                            missing_reason=str(error),
                            field_statuses={
                                "板块": DataStatus.OK if board else DataStatus.MISSING,
                                "行业": (
                                    DataStatus.OK
                                    if security.industry
                                    else DataStatus.MISSING
                                ),
                            },
                        ),
                    )
                if progress_callback is not None:
                    progress_callback(security)
        return results

    def _Profile_FetchOne(self, security: Security) -> SourceValue[Security]:
        board = security.board or (
            Security_AShareBoardGet(security.exchange, security.code)
            if security.market is Market.A_SHARE
            else None
        )
        if security.market is Market.A_SHARE or security.industry:
            source_name = (
                "沪深北交易所证券列表"
                if security.market is Market.A_SHARE
                else "HKEX+东方财富"
            )
            value = replace(
                security,
                board=board,
                is_financial=Security_FinancialClassify(
                    security.name,
                    security.industry,
                    security_code=security.code,
                ),
            )
            self._Classification_Record(f"板块/行业:{source_name}")
            return SourceValue(
                value,
                Provenance_Create(
                    security,
                    "板块与行业",
                    source_name,
                    "证券列表批量元数据",
                    DataStatus.OK if board or security.industry else DataStatus.MISSING,
                    missing_reason=(
                        None
                        if board and security.industry
                        else "证券列表未同时提供板块和行业"
                    ),
                    field_statuses={
                        "板块": DataStatus.OK if board else DataStatus.MISSING,
                        "行业": (
                            DataStatus.OK if security.industry else DataStatus.MISSING
                        ),
                    },
                ),
            )
        profile = self._HkProfile_Ensure(security, require_concepts=False)
        value = replace(profile.value or security, board=board)
        return SourceValue(
            value,
            replace(
                profile.provenance,
                field_group="板块与行业",
                source_name=f"HKEX+{profile.provenance.source_name}",
                source_ref=f"HKEX ListOfSecurities.xlsx；{profile.provenance.source_ref}",
                field_statuses={
                    **profile.provenance.field_statuses,
                    "板块": DataStatus.OK if board else DataStatus.MISSING,
                    "行业": DataStatus.OK if value.industry else DataStatus.MISSING,
                },
            ),
        )

    def Concepts_Fetch(
        self,
        securities: Sequence[Security],
        progress_callback: Callable[[Security], None] | None = None,
    ) -> dict[str, SourceValue[Security]]:
        with self._classification_lock:
            self._classification_company_keys.update(item.key for item in securities)
        results: dict[str, SourceValue[Security]] = {}
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {
                executor.submit(self._Concept_FetchOne, security): security
                for security in securities
            }
            for future in as_completed(futures):
                security = futures[future]
                try:
                    results[security.key] = future.result()
                except Exception as error:
                    self._logger.warning(
                        "%s %s 概念采集失败：%s",
                        security.market.value,
                        security.code,
                        error,
                    )
                    results[security.key] = SourceValue(
                        security,
                        Provenance_Create(
                            security,
                            "概念",
                            self.source_name,
                            "概念主备源",
                            DataStatus.OPTIONAL_MISSING,
                            missing_reason=str(error),
                            field_statuses={"概念": DataStatus.MISSING},
                        ),
                    )
                if progress_callback is not None:
                    progress_callback(security)
        return results

    def _Concept_FetchOne(self, security: Security) -> SourceValue[Security]:
        if security.market is Market.HK:
            profile = self._HkProfile_Ensure(security, require_concepts=True)
            value = profile.value or security
            return SourceValue(
                value,
                replace(
                    profile.provenance,
                    field_group="概念",
                    field_statuses={
                        "概念": (
                            DataStatus.OK if value.concepts else DataStatus.MISSING
                        )
                    },
                ),
            )
        errors: list[str] = []
        concept_result: SourceValue[tuple[str, ...]] | None = None
        if self._tonghuashun is not None:
            try:
                concept_result = self._tonghuashun.Concepts_Fetch(security)
            except SourceError as error:
                errors.append(f"同花顺：{error}")
            if concept_result is not None and concept_result.value:
                self._Classification_Record("概念:同花顺")
        if (concept_result is None or not concept_result.value) and self._sina is not None:
            with self._classification_lock:
                self._classification_company_fallbacks += 1
            try:
                fallback = self._sina.Concepts_Fetch(security)
            except SourceError as error:
                errors.append(f"新浪财经：{error}")
            else:
                concept_result = self._ConceptResult_Combine(concept_result, fallback)
                if fallback.value:
                    self._Classification_Record("概念:新浪财经")
        concepts = concept_result.value if concept_result and concept_result.value else ()
        value = replace(security, concepts=concepts)
        if concept_result is None:
            return SourceValue(
                value,
                Provenance_Create(
                    security,
                    "概念",
                    "同花顺+新浪财经",
                    "概念主备源",
                    DataStatus.OPTIONAL_MISSING,
                    missing_reason="；".join(errors) or "概念主备源未返回",
                    primary_source="同花顺",
                    field_statuses={"概念": DataStatus.MISSING},
                ),
            )
        return SourceValue(
            value,
            replace(
                concept_result.provenance,
                missing_reason=(
                    "；".join(filter(None, (concept_result.provenance.missing_reason, *errors)))
                    or None
                ),
            ),
        )

    def _HkProfile_Ensure(
        self, security: Security, *, require_concepts: bool
    ) -> SourceValue[Security]:
        with self._classification_lock:
            cached = self._classification_cache.get(security.key)
        if cached is not None:
            cached_value = cached.value
            if not require_concepts or (cached_value is not None and cached_value.concepts):
                return cached
        primary = cached
        if primary is None and self._etnet is not None:
            try:
                primary = self._etnet.Profile_Fetch(security)
            except SourceError as error:
                primary = SourceValue(
                    security,
                    Provenance_Create(
                        security,
                        "行业与概念",
                        "ETNet",
                        "content/cpy/eng/company_info.php",
                        DataStatus.SOURCE_UNAVAILABLE,
                        missing_reason=f"ETNet 公司资料请求失败：{error}",
                        primary_source="东方财富",
                        field_statuses={
                            "行业": DataStatus.MISSING,
                            "概念": DataStatus.MISSING,
                        },
                    ),
                )
            else:
                if primary.value is not None and (
                    primary.value.industry or primary.value.concepts
                ):
                    self._Classification_Record("行业/概念:ETNet")
        primary_value = primary.value if primary is not None else None
        needs_fallback = primary_value is None or (
            not primary_value.concepts if require_concepts else not primary_value.industry
        )
        if needs_fallback:
            with self._classification_lock:
                self._classification_company_fallbacks += 1
            try:
                fallback = self._aastocks.Profile_Fetch(primary_value or security)
            except SourceError as error:
                result = SourceValue(
                    primary_value or security,
                    replace(
                        primary.provenance
                        if primary is not None
                        else Provenance_Create(
                            security,
                            "行业与概念",
                            "ETNet+AASTOCKS",
                            "公司资料主备源",
                            DataStatus.SOURCE_UNAVAILABLE,
                            primary_source="东方财富",
                        ),
                        source_name=(
                            f"{primary.provenance.source_name}+AASTOCKS"
                            if primary is not None
                            else "ETNet+AASTOCKS"
                        ),
                        source_ref=(
                            f"{primary.provenance.source_ref}；AASTOCKS 公司资料请求失败"
                            if primary is not None
                            else "AASTOCKS 公司资料请求失败"
                        ),
                        missing_reason=(
                            f"{primary.provenance.missing_reason or ''}；"
                            f"AASTOCKS 公司资料请求失败：{error}"
                            if primary is not None
                            else f"AASTOCKS 公司资料请求失败：{error}"
                        ).strip("；"),
                    ),
                )
            else:
                result = self._ProfileResults_Merge(security, primary, fallback)
                if fallback.value is not None and (
                    fallback.value.industry or fallback.value.concepts
                ):
                    self._Classification_Record("行业/概念:AASTOCKS")
        elif primary is not None:
            result = primary
        else:
            result = SourceValue(
                security,
                Provenance_Create(
                    security,
                    "行业与概念",
                    "ETNet+AASTOCKS",
                    "公司资料主备源",
                    DataStatus.MISSING,
                    missing_reason="港股公司资料主备源未返回",
                    field_statuses={
                        "行业": DataStatus.MISSING,
                        "概念": DataStatus.MISSING,
                    },
                ),
            )
        with self._classification_lock:
            self._classification_cache[security.key] = result
        return result

    @staticmethod
    def _ProfileResults_Merge(
        security: Security,
        primary: SourceValue[Security] | None,
        fallback: SourceValue[Security],
    ) -> SourceValue[Security]:
        primary_value = primary.value if primary is not None else None
        fallback_value = fallback.value
        industry = (
            primary_value.industry
            if primary_value is not None and primary_value.industry
            else fallback_value.industry
            if fallback_value is not None
            else security.industry
        )
        concepts = (
            primary_value.concepts
            if primary_value is not None and primary_value.concepts
            else fallback_value.concepts
            if fallback_value is not None
            else security.concepts
        )
        value = replace(
            primary_value or fallback_value or security,
            industry=industry,
            concepts=concepts,
            is_financial=Security_FinancialClassify(
                security.name,
                industry,
                security_code=security.code,
            ),
        )
        provenances = [
            item
            for item in (
                primary.provenance if primary is not None else None,
                fallback.provenance,
            )
            if item is not None
        ]
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "行业与概念",
                "+".join(dict.fromkeys(item.source_name for item in provenances)),
                "；".join(
                    f"{item.source_name}={item.source_ref}" for item in provenances
                ),
                DataStatus.OK if industry or concepts else DataStatus.MISSING,
                missing_reason=(
                    None
                    if industry and concepts
                    else "港股行业/相关指数标签字段级回退后仍有空白"
                ),
                primary_source="东方财富",
                field_statuses={
                    "行业": DataStatus.OK if industry else DataStatus.MISSING,
                    "概念": DataStatus.OK if concepts else DataStatus.MISSING,
                },
            ),
        )

    @staticmethod
    def _ConceptResult_Combine(
        primary: SourceValue[tuple[str, ...]] | None,
        fallback: SourceValue[tuple[str, ...]],
    ) -> SourceValue[tuple[str, ...]]:
        if primary is None:
            return fallback
        value = primary.value or fallback.value
        return SourceValue(
            value,
            replace(
                fallback.provenance if fallback.value else primary.provenance,
                source_name=f"{primary.provenance.source_name}+{fallback.provenance.source_name}",
                source_ref=(
                    f"{primary.provenance.source_ref}；{fallback.provenance.source_ref}"
                ),
                primary_source="同花顺",
            ),
        )

    def _Classification_Record(self, name: str) -> None:
        with self._classification_lock:
            self._classification_source_counts[name] += 1

    def IPO_Fetch(self, security: Security):
        primary = self._eastmoney.IPO_Fetch(security)
        ipo = primary.value
        if security.market is Market.HK and self._etnet is not None:
            needs_etnet = (
                ipo is None
                or ipo.listing_date is None
                or ipo.issue_price is None
            )
            if needs_etnet:
                try:
                    etnet = self._etnet.IPO_Fetch(security)
                except SourceError as error:
                    return SourceValue(
                        ipo,
                        replace(
                            primary.provenance,
                            source_ref=(
                                f"{primary.provenance.source_ref}；"
                                f"ETNet 公司资料备源失败：{error}"
                            ),
                            missing_reason=(
                                f"{primary.provenance.missing_reason or '东方财富字段不完整'}；"
                                f"ETNet 备源失败：{error}"
                            ),
                        ),
                    )
                if etnet.value is not None:
                    fallback = etnet.value
                    merged = replace(
                        ipo or fallback,
                        listing_date=(
                            ipo.listing_date
                            if ipo is not None and ipo.listing_date is not None
                            else fallback.listing_date
                        ),
                        issue_price=(
                            ipo.issue_price
                            if ipo is not None and ipo.issue_price is not None
                            else fallback.issue_price
                        ),
                    )
                    issue_market_cap, approximate = Calculation_IssueMarketCap(
                        merged.issue_price,
                        merged.post_issue_total_shares,
                        merged.issued_shares,
                    )
                    # issued_shares is not a substitute for post-issue total
                    # shares. Calculation_IssueMarketCap only uses it as an
                    # explicit approximation for legacy A-share paths, so HK
                    # keeps the market cap blank unless historical total shares
                    # were actually obtained.
                    if merged.post_issue_total_shares is None:
                        issue_market_cap = None
                        approximate = False
                    merged = replace(
                        merged,
                        issue_market_cap=issue_market_cap,
                        approximate=approximate,
                    )
                    statuses = dict(primary.provenance.field_statuses)
                    statuses.update(
                        {
                            "上市日期": (
                                DataStatus.OK
                                if merged.listing_date is not None
                                else DataStatus.MISSING
                            ),
                            "发行价": (
                                DataStatus.OK
                                if merged.issue_price is not None
                                else DataStatus.MISSING
                            ),
                            "发行股数": (
                                DataStatus.OK
                                if merged.issued_shares is not None
                                else DataStatus.MISSING
                            ),
                            "发行后总股本": (
                                DataStatus.OK
                                if merged.post_issue_total_shares is not None
                                else DataStatus.MISSING
                            ),
                            "发行时总市值": (
                                DataStatus.OK
                                if merged.issue_market_cap is not None
                                else DataStatus.MISSING
                            ),
                        }
                    )
                    missing_fields = [
                        name
                        for name, status in statuses.items()
                        if status is not DataStatus.OK
                    ]
                    return SourceValue(
                        merged,
                        replace(
                            etnet.provenance,
                            source_name=(
                                f"{primary.provenance.source_name} + "
                                f"{etnet.provenance.source_name}"
                            ),
                            source_ref=(
                                f"{primary.provenance.source_ref}；字段级回退="
                                f"{etnet.provenance.source_ref}"
                            ),
                            status=DataStatus.OK,
                            missing_reason=(
                                f"未取得字段：{', '.join(missing_fields)}"
                                if missing_fields
                                else None
                            ),
                            field_statuses=statuses,
                        ),
                    )
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
            return self.BlockTrades_Fetch([security], year)[security.key]
        return self._eastmoney.BlockTrade_Fetch(security, year)

    def BlockTrades_Fetch(
        self,
        securities: Sequence[Security],
        year: int,
        progress_callback: Callable[[Security | BatchProgressUpdate], None] | None = None,
    ) -> dict[str, SourceValue[BlockTradeData]]:
        a_share = [item for item in securities if item.market is Market.A_SHARE]
        hk = [item for item in securities if item.market is Market.HK]
        results: dict[str, SourceValue[BlockTradeData]] = {}

        def BlockBatchProgress_Report(
            stage_fraction: float,
            completed: int,
            total: int,
            current_company: str,
            message: str,
        ) -> None:
            if progress_callback is None:
                return
            progress_callback(
                BatchProgressUpdate(
                    stage_fraction=stage_fraction,
                    completed=completed,
                    total=total,
                    current_company=current_company,
                    message=message,
                )
            )

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
            if hk:
                BlockBatchProgress_Report(
                    0.03,
                    len(a_share),
                    len(securities),
                    "A 股批量大宗交易",
                    f"A 股年度大宗交易批量完成 {len(a_share)} 家",
                )
        if hk:
            hk_attempts: dict[str, list[SourceValue[BlockTradeData]]] = {
                security.key: [] for security in hk
            }
            if self._etnet is not None:
                try:
                    primary_results = self._etnet.BlockTrades_Fetch(hk, year)
                except Exception as error:
                    self._logger.warning(
                        "ETNet 港股年度大宗/大额交易批量源失败；备源仍继续：%s",
                        error,
                    )
                    primary_results = {
                        security.key: self._BlockTradeError_Create(
                            security, year, "ETNet", error
                        )
                        for security in hk
                    }
                for security in hk:
                    hk_attempts[security.key].append(primary_results[security.key])
                BlockBatchProgress_Report(
                    0.07,
                    len(hk),
                    len(hk),
                    "ETNet 深分页",
                    f"ETNet 港股年度大额交易深分页完成 {len(hk)} 家",
                )

            needs_aastocks = [
                security
                for security in hk
                if not hk_attempts[security.key]
                or hk_attempts[security.key][-1].value is None
            ]
            if needs_aastocks:
                with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
                    futures = {
                        executor.submit(
                            self._aastocks.BlockTrade_Fetch, security, year
                        ): security
                        for security in needs_aastocks
                    }
                    for future in as_completed(futures):
                        security = futures[future]
                        try:
                            attempt = future.result()
                        except Exception as error:
                            self._logger.warning(
                                "AASTOCKS 港股大宗/大额交易 %s 失败；"
                                "HKEX 备源仍继续：%s",
                                security.code,
                                error,
                            )
                            attempt = self._BlockTradeError_Create(
                                security, year, "AASTOCKS", error
                            )
                        hk_attempts[security.key].append(attempt)
                BlockBatchProgress_Report(
                    self._BLOCK_HKEX_SCAN_START_FRACTION,
                    len(needs_aastocks),
                    len(needs_aastocks),
                    "AASTOCKS 大额交易",
                    f"AASTOCKS 港股大额交易回退完成 {len(needs_aastocks)} 家",
                )

            needs_hkex = [
                security
                for security in hk
                if not hk_attempts[security.key]
                or hk_attempts[security.key][-1].value is None
            ]
            if needs_hkex and self._hkex_block is not None:
                try:
                    def HkexBatchProgress_Report(completed: int, total: int) -> None:
                        if progress_callback is None or total <= 0:
                            return
                        scan_span = (
                            self._BLOCK_HKEX_SCAN_END_FRACTION
                            - self._BLOCK_HKEX_SCAN_START_FRACTION
                        )
                        stage_fraction = self._BLOCK_HKEX_SCAN_START_FRACTION + (
                            scan_span * completed / total
                        )
                        BlockBatchProgress_Report(
                            stage_fraction,
                            completed,
                            total,
                            "HKEX 公开日报",
                            "HKEX 港股年度大宗交易公开日报 "
                            f"{completed}/{total}",
                        )

                    fetch_parameters = signature(
                        self._hkex_block.BlockTrades_Fetch
                    ).parameters
                    if "progress_callback" in fetch_parameters:
                        hkex_results = self._hkex_block.BlockTrades_Fetch(
                            needs_hkex,
                            year,
                            progress_callback=HkexBatchProgress_Report,
                        )
                    else:
                        hkex_results = self._hkex_block.BlockTrades_Fetch(
                            needs_hkex, year
                        )
                except Exception as error:
                    self._logger.warning(
                        "HKEX 港股年度大宗交易备源批量失败：%s", error
                    )
                    hkex_results = {
                        security.key: self._BlockTradeError_Create(
                            security, year, "HKEX", error
                        )
                        for security in needs_hkex
                    }
                for security in needs_hkex:
                    hk_attempts[security.key].append(hkex_results[security.key])

            for security in hk:
                attempts = hk_attempts[security.key]
                if not attempts:
                    attempts.append(
                        self._BlockTradeError_Create(
                            security,
                            year,
                            "港股大宗交易",
                            SourceError("未配置可用的数据源"),
                        )
                    )
                selected = next(
                    (attempt for attempt in attempts if attempt.value is not None),
                    attempts[-1],
                )
                results[security.key] = self._BlockTradeAttempts_Combine(
                    selected, attempts
                )
        BlockBatchProgress_Report(
            1.0,
            len(securities),
            len(securities),
            "年度大宗交易汇总",
            f"年度大宗/大额交易完成 {len(securities)} 家",
        )
        return results

    @staticmethod
    def _BlockTradeAttempts_Combine(
        selected: SourceValue[BlockTradeData],
        attempts: list[SourceValue[BlockTradeData]],
    ) -> SourceValue[BlockTradeData]:
        source_names = list(
            dict.fromkeys(
                attempt.provenance.source_name
                for attempt in attempts
                if attempt.provenance.source_name
            )
        )
        refs = [
            f"{attempt.provenance.source_name}={attempt.provenance.source_ref}"
            for attempt in attempts
        ]
        failed_reasons = [
            f"{attempt.provenance.source_name}：{attempt.provenance.missing_reason}"
            for attempt in attempts
            if attempt.value is None and attempt.provenance.missing_reason
        ]
        provenance = replace(
            selected.provenance,
            source_name="+".join(source_names),
            source_ref="；".join(refs),
            missing_reason=(
                selected.provenance.missing_reason
                if selected.value is None
                else ("；".join(failed_reasons) if failed_reasons else None)
            ),
            primary_source=(
                attempts[0].provenance.source_name
                if attempts
                else selected.provenance.primary_source
            ),
        )
        return SourceValue(selected.value, provenance)

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
                "本次运行剩余证券直接切换新浪 30 日历史、同花顺和腾讯备用链，"
                "避免重复数千次失效请求",
                healthy_probe_count,
                probe_count,
                probe_errors[:1] or "返回历史不足",
            )
            fallback_results = self._ParallelFlow_Fetch(
                securities,
                self._AFlowFallback_Fetch,
                "A 股资金流新浪/同花顺/腾讯备用链",
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
        combined: SourceValue[FlowData] | None = None
        missing_results: list[SourceValue[FlowData]] = []
        failed_attempts: list[str] = []
        sources: list[tuple[str, Any]] = []
        if self._sina is not None:
            sources.append(("新浪财经", self._sina.Flow_Fetch))
        if self._tonghuashun is not None:
            sources.append(("同花顺", self._tonghuashun.Flow_Fetch))
        sources.append(("腾讯资金流", self._tencent.Flow_Fetch))

        for source_name, fetcher in sources:
            try:
                result = fetcher(security)
            except (SourceError, ValueError) as error:
                failed_attempts.append(f"{source_name}：{error}")
                continue
            if result.value is None:
                missing_results.append(result)
                failed_attempts.append(
                    f"{source_name}："
                    f"{result.provenance.missing_reason or '未返回有效资金流'}"
                )
                continue
            combined = (
                result
                if combined is None
                else self._FlowValues_Merge(security, combined, result)
            )
            if (
                combined.value is not None
                and combined.value.five_day_net is not None
                and combined.value.one_month_net is not None
            ):
                break

        if combined is None:
            reason = "；".join(failed_attempts) or "A 股资金流全部备用源均无数据"
            if missing_results:
                last_result = missing_results[-1]
                return SourceValue(
                    None,
                    replace(
                        last_result.provenance,
                        source_ref=f"{last_result.provenance.source_ref}；失败尝试={reason}",
                        missing_reason=reason,
                    ),
                )
            raise SourceError(reason)
        if failed_attempts:
            return SourceValue(
                combined.value,
                replace(
                    combined.provenance,
                    source_ref=(
                        f"{combined.provenance.source_ref}；"
                        f"失败尝试={'；'.join(failed_attempts)}"
                    ),
                ),
            )
        return combined

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
                "港股资金流历史主源健康探测未全部取得 20 日数据"
                "（成功=%s/%s，错误=%s）；"
                "本次运行剩余证券改用 TradeGo 5/20 日与 AASTOCKS 5 日来源",
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
                "东方财富港股 5/20 日资金流主源",
                progress_callback,
            )
        )
        missing = [
            security
            for security in securities
            if probe_results.get(security.key) is None
            or probe_results[security.key].value is None
            or probe_results[security.key].value.five_day_net is None
            or probe_results[security.key].value.one_month_net is None
        ]
        if missing:
            fallbacks = self._HkFiveDayFallbacks_Fetch(
                missing, as_of_date
            )
            for security in missing:
                fallback = fallbacks.get(security.key)
                primary = probe_results.get(security.key)
                if fallback is not None:
                    probe_results[security.key] = self._FlowValues_Merge(
                        security, primary, fallback
                    )
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
            self._logger.warning("TradeGo 港股批量 5/20 日资金流不可用，改用 AASTOCKS 5 日页：%s", error)
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
                    results[security.key] = self._FlowValues_Merge(
                        security,
                        results.get(security.key),
                        fallbacks[security.key],
                    )
        return results

    @staticmethod
    def _FlowValues_Merge(
        security: Security,
        primary: SourceValue[FlowData] | None,
        fallback: SourceValue[FlowData],
    ) -> SourceValue[FlowData]:
        primary_value = primary.value if primary is not None else None
        fallback_value = fallback.value
        five_day = (
            primary_value.five_day_net
            if primary_value is not None and primary_value.five_day_net is not None
            else fallback_value.five_day_net
            if fallback_value is not None
            else None
        )
        one_month = (
            primary_value.one_month_net
            if primary_value is not None and primary_value.one_month_net is not None
            else fallback_value.one_month_net
            if fallback_value is not None
            else None
        )
        chosen = primary_value or fallback_value
        value = (
            FlowData(
                security.key,
                max(
                    item.end_date
                    for item in (primary_value, fallback_value)
                    if item is not None
                ),
                five_day,
                one_month,
                "CNY" if security.market is Market.A_SHARE else "HKD",
            )
            if chosen is not None
            else None
        )
        one_month_field = FlowOneMonthField_Get(security.market)
        provenance = fallback.provenance
        if primary is not None:
            provenance = replace(
                fallback.provenance,
                source_name=f"{primary.provenance.source_name} + {fallback.provenance.source_name}",
                source_ref=(
                    f"{primary.provenance.source_ref}；字段级回退="
                    f"{fallback.provenance.source_ref}"
                ),
                primary_source=primary.provenance.source_name,
            )
        statuses = dict(provenance.field_statuses)
        statuses[FLOW_FIVE_DAY_FIELD] = (
            DataStatus.OK if five_day is not None else DataStatus.MISSING
        )
        statuses[one_month_field] = (
            DataStatus.OK if one_month is not None else DataStatus.MISSING
        )
        missing_fields = [name for name, status in statuses.items() if status is not DataStatus.OK]
        return SourceValue(
            value,
            replace(
                provenance,
                status=DataStatus.OK if value is not None else provenance.status,
                field_statuses=statuses,
                missing_reason=(
                    f"未取得字段：{', '.join(missing_fields)}" if missing_fields else None
                ),
            ),
        )

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
                                FLOW_FIVE_DAY_FIELD: DataStatus.ERROR,
                                FlowOneMonthField_Get(security.market): DataStatus.ERROR,
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
        performance = Statistics_Merge(
            [client.Statistics_Get() for client in self._clients]
        )
        classification_requests = sum(
            int(count)
            for endpoint, count in performance.get("requests_by_endpoint", {}).items()
            if "profile" in endpoint.lower() or "concept" in endpoint.lower()
        )
        with self._classification_lock:
            company_count = len(self._classification_company_keys)
            performance["classification"] = {
                "source_counts": dict(self._classification_source_counts),
                "batch_metadata_hits": sum(
                    count
                    for name, count in self._classification_source_counts.items()
                    if "交易所" in name or "东方财富" in name
                ),
                "company_fallbacks": self._classification_company_fallbacks,
                "profile_cache_entries": len(self._classification_cache),
                "company_count": company_count,
                "http_requests": classification_requests,
                "http_requests_per_company": round(
                    classification_requests / company_count, 3
                )
                if company_count
                else 0.0,
            }
        return performance

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
        if self._sina is not None:
            self._sina.close()


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
        request_interval=max(config.request_interval, 0.05),
    )
    etnet_client = HttpJsonClient(
        "ETNet",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=config.request_interval,
    )
    sina_client = HttpJsonClient(
        "新浪财经",
        network_mode=config.network_mode,
        domestic=True,
        request_interval=max(config.request_interval, 0.05),
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
        HkexBlockTradeSource(
            hkex_client,
            tencent_client,
            concurrency=config.concurrency,
        ),
        SinaSource(sina_client),
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
            sina_client,
        ),
    )

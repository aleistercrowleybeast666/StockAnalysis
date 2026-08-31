from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import (
    CompanyStatus,
    DataStatus,
    Market,
    MarketScopeMode,
    PipelineRunResult,
)
from stock_analysis.domain.fields import FLOW_FIVE_DAY_FIELD, FlowOneMonthField_Get
from stock_analysis.domain.models import (
    AnalysisIssue,
    AnalysisRecord,
    BatchProgressUpdate,
    MarketSelectionStats,
    RunProgress,
    RunSummary,
    Security,
)
from stock_analysis.pipeline.fetch import FetchCoordinator
from stock_analysis.pipeline.merge import Period_Select
from stock_analysis.pipeline.metrics import Metrics_Calculate
from stock_analysis.pipeline.universe import (
    Universe_BuildDetailed,
    Universe_RankByMarketCap,
)
from stock_analysis.pipeline.validate import Record_Validate
from stock_analysis.sources.base import (
    MarketDataSource,
    SourceUnavailableError,
    SourceValue,
)

ProgressCallback = Callable[[RunProgress], None]
BatchProgressCallback = Callable[[Security | BatchProgressUpdate], None]
BatchOperation = Callable[[BatchProgressCallback], dict[str, SourceValue[Any]]]
ParallelOperation = Callable[[Security], SourceValue[Any]]
ValueAssign = Callable[[AnalysisRecord, Any | None], None]


class PipelineCancelled(RuntimeError):
    pass


class PipelineRunner:
    _STAGE_TIME_WEIGHTS = {
        "获取行情与市值": 8,
        "年度财务": 30,
        "补全入选公司行情": 4,
        "板块与行业": 3,
        "概念": 8,
        "上市与发行信息": 20,
        "年度全市场大宗交易": 10,
        "资金流": 25,
        "标准化、计算与校验": 2,
        "生成 Excel": 2,
    }
    _OVERALL_WORK_UNITS = 100_000
    _HK_ARCHIVE_ESTIMATED_TRADING_DAYS = 250
    _HK_ARCHIVE_DAILY_REPORT_COST = 3

    def __init__(
        self,
        config: AppConfig,
        source: MarketDataSource,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._config = config
        self._source = source
        self._logger = logging.getLogger("stock_analysis.pipeline")
        self._progress_callback = progress_callback or (lambda _progress: None)
        self._cancel_event = threading.Event()
        self._stage_durations: dict[str, float] = {}
        self._financial_progress_completed = 0
        self._financial_progress_total = 0
        self._overall_work_totals: dict[str, int] = {}
        self._overall_work_completed: dict[str, int] = {}
        self._stage_company_totals: dict[str, int] = {}
        self._coordinator = FetchCoordinator(source)

    def cancel(self) -> None:
        self._cancel_event.set()

    def _CheckCancelled(self) -> None:
        if self._cancel_event.is_set():
            raise PipelineCancelled("任务已取消")

    @staticmethod
    def _Optional_Check(record: AnalysisRecord, stage: str) -> bool:
        return stage not in {"financials", "年度财务"} and not stage.endswith(
            "财务数据"
        )

    @staticmethod
    def _CoreStage_Check(stage: str) -> bool:
        return stage in {"financials", "年度财务"}

    def _Issue_AddFromSource(
        self,
        record: AnalysisRecord,
        stage: str,
        result: SourceValue[Any],
    ) -> None:
        provenance = result.provenance
        record.provenance.append(provenance)
        if provenance.status is DataStatus.OK:
            return
        optional = self._Optional_Check(record, stage) or provenance.status in {
            DataStatus.OPTIONAL_MISSING,
            DataStatus.NOT_APPLICABLE,
            DataStatus.UNSUPPORTED,
        }
        field_status = provenance.status
        if optional and field_status in {DataStatus.MISSING, DataStatus.UNSUPPORTED}:
            field_status = DataStatus.OPTIONAL_MISSING
        if optional and field_status in {
            DataStatus.OPTIONAL_MISSING,
            DataStatus.NOT_APPLICABLE,
            DataStatus.UNSUPPORTED,
        }:
            return
        record.issues.append(
            AnalysisIssue(
                market=record.security.market,
                code=record.security.code,
                company_name=record.security.name,
                stage=stage,
                reason=provenance.missing_reason
                or f"{provenance.field_group}状态为 {field_status.value}",
                source_name=provenance.source_name,
                field_name=provenance.field_group,
                field_status=field_status,
                is_core=self._CoreStage_Check(stage),
                optional=optional,
                primary_source=provenance.primary_source,
                endpoint=provenance.source_ref,
                fetched_at=provenance.fetched_at,
            )
        )

    def _Issue_AddException(
        self,
        record: AnalysisRecord,
        stage: str,
        error: Exception,
    ) -> None:
        optional = self._Optional_Check(record, stage)
        status = (
            DataStatus.SOURCE_UNAVAILABLE
            if isinstance(error, SourceUnavailableError)
            else DataStatus.ERROR
        )
        record.issues.append(
            AnalysisIssue(
                market=record.security.market,
                code=record.security.code,
                company_name=record.security.name,
                stage=stage,
                reason=str(error),
                source_name=self._source.source_name,
                field_name=stage,
                field_status=status,
                is_core=self._CoreStage_Check(stage),
                optional=optional,
                primary_source=self._source.source_name,
            )
        )

    def _GroupedIssue_Add(
        self,
        records: Sequence[AnalysisRecord],
        stage: str,
        error: Exception,
    ) -> None:
        if not records:
            return
        first_record = records[0]
        optional = self._Optional_Check(first_record, stage)
        status = (
            DataStatus.SOURCE_UNAVAILABLE
            if isinstance(error, SourceUnavailableError)
            else DataStatus.ERROR
        )
        affected = len(records)
        first_record.issues.append(
            AnalysisIssue(
                market=first_record.security.market,
                code=first_record.security.code,
                company_name=first_record.security.name,
                stage=stage,
                reason=(
                    f"{error}；共影响 {affected} 家公司，同类错误已归并，"
                    "相关可选字段留空"
                ),
                source_name=self._source.source_name,
                field_name=stage,
                field_status=status,
                is_core=self._CoreStage_Check(stage),
                optional=optional,
                primary_source=self._source.source_name,
            )
        )

    def _Result_Apply(
        self,
        record: AnalysisRecord,
        stage: str,
        result: SourceValue[Any],
        assign: ValueAssign,
    ) -> None:
        self._Issue_AddFromSource(record, stage, result)
        record.field_statuses.update(result.provenance.field_statuses)
        assign(record, result.value)

    def _WorkPlan_Initialize(self, securities: Sequence[Security]) -> None:
        planned_company_count = 0
        planned_market_counts: dict[Market, int] = {}
        for market in self._config.markets:
            market_count = sum(item.market is market for item in securities)
            scope_mode, top_n = self._config.MarketScope_Get(market)
            selected_count = (
                market_count
                if scope_mode is MarketScopeMode.ALL
                else min(top_n, market_count)
            )
            planned_company_count += selected_count
            planned_market_counts[market] = selected_count

        stage_company_counts = {
            "获取行情与市值": len(securities),
            "年度财务": planned_company_count,
            "补全入选公司行情": planned_company_count,
            "板块与行业": planned_company_count,
            "概念": planned_company_count,
            "上市与发行信息": planned_company_count,
            "年度全市场大宗交易": planned_company_count,
            "资金流": planned_company_count,
            "标准化、计算与校验": planned_company_count,
            "生成 Excel": planned_company_count,
        }
        stage_workloads = {
            stage: self._STAGE_TIME_WEIGHTS[stage] * count
            for stage, count in stage_company_counts.items()
            if count > 0
        }
        stage_workloads["获取行情与市值"] = (
            self._STAGE_TIME_WEIGHTS["获取行情与市值"]
            * max(1, ceil(len(securities) / 100))
        )
        planned_hk_count = planned_market_counts.get(Market.HK, 0)
        if (
            not self._config.fixture_mode
            and planned_hk_count > 0
            and self._config.financial_year < datetime.now().year
        ):
            stage_workloads["年度全市场大宗交易"] += (
                self._HK_ARCHIVE_ESTIMATED_TRADING_DAYS
                * self._HK_ARCHIVE_DAILY_REPORT_COST
            )
        workload_total = sum(stage_workloads.values()) or 1
        self._stage_company_totals = dict(stage_company_counts)
        self._overall_work_totals = {}
        allocated = 0
        active_stages = list(stage_workloads)
        for stage in active_stages[:-1]:
            units = round(
                self._OVERALL_WORK_UNITS
                * stage_workloads[stage]
                / workload_total
            )
            self._overall_work_totals[stage] = units
            allocated += units
        if active_stages:
            self._overall_work_totals[active_stages[-1]] = (
                self._OVERALL_WORK_UNITS - allocated
            )
        self._overall_work_completed = {
            stage: 0 for stage in self._overall_work_totals
        }
        self._logger.info(
            "总进度计划建立：证券池=%s，预计处理公司=%s，阶段工作量=%s；"
            "准备证券范围不预占固定百分比，总进度按批量请求数、入选公司数和"
            "历史交易日报扫描量动态规划，阶段内部按实际完成比例推进",
            len(securities),
            planned_company_count,
            self._overall_work_totals,
        )

    def _WorkPlan_StageTotalSet(self, stage: str, company_count: int) -> None:
        if stage not in self._overall_work_totals:
            return
        self._stage_company_totals[stage] = max(0, company_count)

    def _WorkPlan_StageProgressSet(self, stage: str, company_count: int) -> None:
        stage_units = self._overall_work_totals.get(stage)
        if stage_units is None:
            return
        company_total = self._stage_company_totals.get(stage, 0)
        if company_total <= 0:
            fraction = 1.0 if company_count > 0 else 0.0
        else:
            fraction = min(1.0, max(0.0, company_count / company_total))
        completed_units = round(stage_units * fraction)
        self._overall_work_completed[stage] = max(
            self._overall_work_completed.get(stage, 0), completed_units
        )

    def _WorkPlan_StageFractionSet(self, stage: str, fraction: float) -> None:
        stage_units = self._overall_work_totals.get(stage)
        if stage_units is None:
            return
        completed_units = round(stage_units * min(1.0, max(0.0, fraction)))
        self._overall_work_completed[stage] = max(
            self._overall_work_completed.get(stage, 0), completed_units
        )

    def _WorkPlan_DownstreamTotalsUpdate(
        self,
        active_records: Sequence[AnalysisRecord],
        records: Sequence[AnalysisRecord],
    ) -> None:
        active_count = len(active_records)
        self._WorkPlan_StageTotalSet("补全入选公司行情", active_count)
        self._WorkPlan_StageTotalSet("板块与行业", active_count)
        self._WorkPlan_StageTotalSet("概念", active_count)
        self._WorkPlan_StageTotalSet("上市与发行信息", active_count)
        self._WorkPlan_StageTotalSet("年度全市场大宗交易", active_count)
        self._WorkPlan_StageTotalSet("资金流", active_count)
        self._WorkPlan_StageTotalSet("标准化、计算与校验", len(records))
        self._WorkPlan_StageTotalSet("生成 Excel", len(records))

    def _WorkPlan_TotalsGet(self) -> tuple[int, int]:
        overall_total = sum(self._overall_work_totals.values())
        overall_completed = sum(
            min(self._overall_work_completed.get(stage, 0), total)
            for stage, total in self._overall_work_totals.items()
        )
        return overall_completed, overall_total

    def _WorkPlan_Complete(self) -> None:
        self._overall_work_completed = dict(self._overall_work_totals)

    def _Progress_Emit(
        self,
        stage: str,
        company: str,
        completed: int,
        total: int,
        success: int,
        partial: int,
        failed: int,
        message: str,
        *,
        excluded: int = 0,
    ) -> None:
        overall_completed, overall_total = self._WorkPlan_TotalsGet()
        self._logger.info(
            "阶段=%s，进度=%s/%s，公司=%s，成功=%s，部分缺失=%s，失败=%s，"
            "排除=%s，本次运行内复用=%s，总工作量=%s/%s，消息=%s",
            stage,
            completed,
            total,
            company or "-",
            success,
            partial,
            failed,
            excluded,
            self._coordinator.reuse_count,
            overall_completed,
            overall_total,
            message,
        )
        self._progress_callback(
            RunProgress(
                stage=stage,
                current_company=company,
                completed=completed,
                total=total,
                success=success,
                missing=partial,
                failed=failed,
                message=message,
                excluded=excluded,
                overall_completed=overall_completed,
                overall_total=overall_total,
            )
        )

    def _BatchStage_Run(
        self,
        stage: str,
        records: Sequence[AnalysisRecord],
        operation: BatchOperation,
        assign: ValueAssign,
    ) -> None:
        if not records:
            return
        self._CheckCancelled()
        started = time.perf_counter()
        reported_keys: set[str] = set()

        def progress_report(
            update: Security | BatchProgressUpdate,
        ) -> None:
            if isinstance(update, BatchProgressUpdate):
                self._WorkPlan_StageFractionSet(stage, update.stage_fraction)
                self._Progress_Emit(
                    stage,
                    update.current_company,
                    update.completed,
                    update.total,
                    0,
                    0,
                    0,
                    update.message,
                )
                return
            security = update
            if security.key in reported_keys:
                return
            previous_units = self._overall_work_completed.get(stage, 0)
            reported_keys.add(security.key)
            completed_count = len(reported_keys)
            self._WorkPlan_StageProgressSet(stage, completed_count)
            if self._overall_work_completed.get(stage, 0) <= previous_units:
                return
            self._Progress_Emit(
                stage,
                security.name,
                completed_count,
                len(records),
                0,
                0,
                0,
                f"{stage} {completed_count}/{len(records)}",
            )

        self._WorkPlan_StageProgressSet(stage, 0)
        self._Progress_Emit(stage, "", 0, len(records), 0, 0, 0, f"开始{stage}")
        try:
            results = operation(progress_report)
        except PipelineCancelled:
            raise
        except Exception as error:
            self._logger.warning("%s 批量阶段失败：%s", stage, error, exc_info=True)
            if self._Optional_Check(records[0], stage):
                self._GroupedIssue_Add(records, stage, error)
            else:
                for record in records:
                    self._Issue_AddException(record, stage, error)
            self._WorkPlan_StageProgressSet(stage, len(records))
            self._Progress_Emit(
                stage,
                "",
                len(records),
                len(records),
                0,
                len(records),
                0,
                f"{stage}批量端点不可用，已记录并继续",
            )
        else:
            for record in records:
                self._CheckCancelled()
                result = results.get(record.security.key)
                if result is None:
                    self._Issue_AddException(
                        record, stage, RuntimeError("批量数据源未返回该证券")
                    )
                else:
                    self._Result_Apply(record, stage, result, assign)
                progress_report(record.security)
        finally:
            self._stage_durations[stage] = time.perf_counter() - started

    def _ParallelStage_Run(
        self,
        stage: str,
        records: Sequence[AnalysisRecord],
        operation: ParallelOperation,
        assign: ValueAssign,
        *,
        collapse_errors: bool = False,
        progress_offset: int = 0,
        progress_total: int | None = None,
    ) -> None:
        if not records:
            return
        self._CheckCancelled()
        started = time.perf_counter()
        futures: dict[Future[SourceValue[Any]], AnalysisRecord] = {}
        grouped_errors: list[tuple[AnalysisRecord, Exception]] = []
        executor = ThreadPoolExecutor(
            max_workers=self._config.concurrency,
            thread_name_prefix=f"stock-{stage}",
        )
        try:
            for record in records:
                futures[executor.submit(operation, record.security)] = record
            for completed, future in enumerate(as_completed(futures), 1):
                self._CheckCancelled()
                record = futures[future]
                try:
                    result = future.result()
                except Exception as error:
                    if collapse_errors:
                        grouped_errors.append((record, error))
                    else:
                        self._logger.warning(
                            "%s %s 的 %s 采集失败：%s",
                            record.security.market.value,
                            record.security.code,
                            stage,
                            error,
                            exc_info=True,
                        )
                        self._Issue_AddException(record, stage, error)
                else:
                    self._Result_Apply(record, stage, result, assign)
                overall_completed = progress_offset + completed
                overall_total = progress_total or len(records)
                self._WorkPlan_StageProgressSet(stage, overall_completed)
                self._Progress_Emit(
                    stage,
                    record.security.name,
                    overall_completed,
                    overall_total,
                    0,
                    0,
                    0,
                    f"{stage} {overall_completed}/{overall_total}",
                )
        except PipelineCancelled:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
            if grouped_errors:
                first_error = grouped_errors[0][1]
                affected_records = [item[0] for item in grouped_errors]
                self._logger.warning(
                    "%s 批量采集不可用：%s；共影响 %s 家，同类错误已归并",
                    stage,
                    first_error,
                    len(affected_records),
                )
                self._GroupedIssue_Add(affected_records, stage, first_error)
        finally:
            self._stage_durations[stage] = self._stage_durations.get(
                stage, 0.0
            ) + (time.perf_counter() - started)

    def _Financial_Assign(self, record: AnalysisRecord, value: Any | None) -> None:
        periods = value if isinstance(value, list) else []
        record.current = Period_Select(periods, self._config.financial_year)
        record.previous = Period_Select(periods, self._config.financial_year - 1)
        record.three_year_base = Period_Select(periods, self._config.financial_year - 3)

    @staticmethod
    def _Attribute_Assign(attribute: str) -> ValueAssign:
        return lambda record, value: setattr(record, attribute, value)

    @staticmethod
    def _Security_Assign(record: AnalysisRecord, value: Any | None) -> None:
        if isinstance(value, Security):
            record.security = value

    def _DirectFieldStatuses_Add(self, record: AnalysisRecord) -> None:
        quote = record.quote
        ipo = record.ipo
        block = record.block_trade
        flow = record.flow
        one_month_field = FlowOneMonthField_Get(record.security.market)
        field_values = {
            "板块": record.security.board,
            "行业": record.security.industry,
            "概念": record.security.concepts or None,
            "最新总市值": quote.market_cap if quote else None,
            "最新可得价格": quote.price if quote else None,
            "上市日期": (ipo.listing_date if ipo else None)
            or record.security.listing_date,
            "发行价": ipo.issue_price if ipo else None,
            "发行股数": ipo.issued_shares if ipo else None,
            "发行时总市值": ipo.issue_market_cap if ipo else None,
            "当年累计大宗交易笔数": block.trade_count if block else None,
            "当年累计大宗交易金额": block.total_amount if block else None,
            FLOW_FIVE_DAY_FIELD: flow.five_day_net if flow else None,
            one_month_field: flow.one_month_net if flow else None,
        }
        for name, value in field_values.items():
            if value is not None:
                record.field_statuses[name] = DataStatus.OK
            else:
                record.field_statuses.setdefault(name, DataStatus.MISSING)
        for name in (
            FLOW_FIVE_DAY_FIELD,
            one_month_field,
        ):
            if record.field_statuses[name] is DataStatus.MISSING:
                record.field_statuses[name] = DataStatus.OPTIONAL_MISSING

    @staticmethod
    def _FieldIssues_Add(record: AnalysisRecord) -> None:
        existing = {issue.field_name for issue in record.issues if issue.field_name}
        core_fields = {"营业收入", "实际报告期", "报表币种"}
        for field_name, status in record.field_statuses.items():
            if status in {DataStatus.OK, DataStatus.NOT_APPLICABLE}:
                continue
            if field_name in existing:
                continue
            if field_name not in core_fields:
                continue
            record.issues.append(
                AnalysisIssue(
                    market=record.security.market,
                    code=record.security.code,
                    company_name=record.security.name,
                    stage="calculate",
                    reason=f"{field_name}：{status.value}",
                    field_name=field_name,
                    field_status=status,
                    is_core=True,
                    optional=False,
                )
            )

    def _Records_Finalize(
        self, records: Sequence[AnalysisRecord]
    ) -> tuple[int, int, int, int]:
        started = time.perf_counter()
        success = partial = failed = excluded = 0
        total = len(records)
        self._WorkPlan_StageProgressSet("标准化、计算与校验", 0)
        for completed, record in enumerate(records, 1):
            self._CheckCancelled()
            Metrics_Calculate(record)
            self._DirectFieldStatuses_Add(record)
            record.issues.extend(Record_Validate(record))
            self._FieldIssues_Add(record)
            status = record.company_status
            if status is CompanyStatus.SUCCESS:
                success += 1
            elif status is CompanyStatus.PARTIAL:
                partial += 1
            elif status is CompanyStatus.FAILED:
                failed += 1
            else:
                excluded += 1
            self._WorkPlan_StageProgressSet(
                "标准化、计算与校验", completed
            )
            self._Progress_Emit(
                "标准化、计算与校验",
                record.security.name,
                completed,
                total,
                success,
                partial,
                failed,
                f"{record.security.name}：{status.value}",
                excluded=excluded,
            )
        self._stage_durations["标准化、计算与校验"] = time.perf_counter() - started
        return success, partial, failed, excluded

    def _UniverseQuotes_Fetch(
        self, securities: Sequence[Security]
    ) -> dict[str, SourceValue[Any]]:
        if not securities:
            return {}
        stage = "获取行情与市值"
        started = time.perf_counter()
        self._CheckCancelled()
        self._WorkPlan_StageProgressSet(stage, 0)
        self._Progress_Emit(
            stage,
            "",
            0,
            len(securities),
            0,
            0,
            0,
            "正在批量获取最新行情与总市值",
        )
        reported_keys: set[str] = set()

        def progress_report(security: Security) -> None:
            if security.key in reported_keys:
                return
            previous_units = self._overall_work_completed.get(stage, 0)
            reported_keys.add(security.key)
            completed_count = len(reported_keys)
            self._WorkPlan_StageProgressSet(stage, completed_count)
            if self._overall_work_completed.get(stage, 0) <= previous_units:
                return
            self._Progress_Emit(
                stage,
                security.name,
                completed_count,
                len(securities),
                0,
                0,
                0,
                f"批量行情与市值 {completed_count}/{len(securities)}",
            )

        results = self._coordinator.Quotes_Fetch(securities, progress_report)
        valid_count = sum(
            result.value is not None
            and result.value.market_cap is not None
            and result.value.market_cap > 0
            for result in results.values()
        )
        self._WorkPlan_StageProgressSet(stage, len(securities))
        self._Progress_Emit(
            stage,
            "",
            len(securities),
            len(securities),
            0,
            0,
            0,
            f"行情与市值获取完成，可用于排名 {valid_count} 家",
        )
        self._stage_durations[stage] = time.perf_counter() - started
        return results

    @staticmethod
    def _NoCoreFinancial_Mark(record: AnalysisRecord) -> None:
        record.excluded_reason = "未取得所选年度营业收入，已跳过"
        if any(issue.is_core for issue in record.issues):
            return
        record.issues.append(
            AnalysisIssue(
                market=record.security.market,
                code=record.security.code,
                company_name=record.security.name,
                stage="selection",
                reason=record.excluded_reason,
                field_name="营业收入",
                field_status=DataStatus.MISSING,
                is_core=True,
            )
        )

    def _MarketCandidates_Select(
        self,
        market: Market,
        securities: Sequence[Security],
        quote_results: dict[str, SourceValue[Any]],
        identified_count: int,
        delisted_count: int,
    ) -> tuple[list[AnalysisRecord], list[AnalysisRecord], MarketSelectionStats]:
        scope_mode, top_n = self._config.MarketScope_Get(market)
        quote_values = {
            security.key: (
                quote_results[security.key].value
                if security.key in quote_results
                else None
            )
            for security in securities
        }
        ranked = Universe_RankByMarketCap(securities, quote_values)
        ranked_keys = {security.key for security in ranked}
        unranked = sorted(
            (security for security in securities if security.key not in ranked_keys),
            key=lambda security: security.code,
        )
        stats = MarketSelectionStats(
            market=market,
            scope=scope_mode.value,
            identified_count=identified_count,
            ranked_count=len(ranked),
            selected_target_count=(
                top_n if scope_mode is MarketScopeMode.TOP_MARKET_CAP else None
            ),
            skipped_delisted_count=delisted_count,
        )
        if scope_mode is MarketScopeMode.TOP_MARKET_CAP:
            if not ranked:
                raise RuntimeError(
                    f"{market.value} 暂时无法取得有效总市值，不能按总市值筛选"
                )
            candidate_order = ranked
            target_count: int | None = top_n
            batch_size = 1
            next_batch_size = min(len(candidate_order), top_n)
        else:
            candidate_order = ranked + unranked
            target_count = None
            batch_size = max(20, min(200, len(candidate_order) or 20))
            next_batch_size = batch_size

        planned_candidate_count = (
            min(target_count, len(candidate_order))
            if target_count is not None
            else len(candidate_order)
        )
        if target_count is None:
            self._logger.info(
                "%s 范围确认：未勾选市值限制，将分批采集全部 %s 家合格公司，"
                "不使用界面中保留的 N 值",
                market.value,
                len(candidate_order),
            )
        else:
            self._logger.info(
                "%s 范围确认：限制为总市值前 %s 家；仅在核心财务缺失时补位",
                market.value,
                target_count,
            )

        selected: list[AnalysisRecord] = []
        skipped: list[AnalysisRecord] = []
        offset = 0
        years = {
            self._config.financial_year,
            self._config.financial_year - 1,
            self._config.financial_year - 3,
        }
        while offset < len(candidate_order):
            self._CheckCancelled()
            end = min(len(candidate_order), offset + next_batch_size)
            if target_count is not None:
                previous_extra = max(0, offset - planned_candidate_count)
                current_extra = max(0, end - planned_candidate_count)
                self._financial_progress_total += current_extra - previous_extra
                self._WorkPlan_StageTotalSet(
                    "年度财务", self._financial_progress_total
                )
            batch = [AnalysisRecord(security=item) for item in candidate_order[offset:end]]
            for record in batch:
                quote_result = quote_results.get(record.security.key)
                if quote_result is not None:
                    self._Result_Apply(
                        record,
                        "最新行情",
                        quote_result,
                        self._Attribute_Assign("quote"),
                    )
            stats.candidate_count += len(batch)
            self._WorkPlan_StageProgressSet(
                "年度财务", self._financial_progress_completed
            )
            self._Progress_Emit(
                "年度财务",
                "",
                self._financial_progress_completed,
                self._financial_progress_total,
                0,
                0,
                0,
                (
                    f"正在获取{market.value}全部公司的年度财务数据"
                    if target_count is None
                    else f"正在获取{market.value}候选公司的年度财务数据"
                ),
            )
            self._ParallelStage_Run(
                "年度财务",
                batch,
                lambda security: self._coordinator.Financials_Fetch(security, years),
                self._Financial_Assign,
                progress_offset=self._financial_progress_completed,
                progress_total=self._financial_progress_total,
            )
            self._financial_progress_completed += len(batch)
            for record in batch:
                if target_count is not None and len(selected) >= target_count:
                    break
                if record.has_core_financials:
                    selected.append(record)
                else:
                    self._NoCoreFinancial_Mark(record)
                    skipped.append(record)
                    stats.skipped_no_core_financial_count += 1
            offset = end
            if target_count is not None and len(selected) >= target_count:
                break
            next_batch_size = (
                max(batch_size, target_count - len(selected))
                if target_count is not None
                else batch_size
            )

        stats.generated_count = len(selected)
        if not selected:
            raise RuntimeError(f"{market.value}没有可生成分析表的公司")
        if target_count is not None and len(selected) < target_count:
            self._logger.warning(
                "%s 证券池总量不足：目标=%s，可按市值排名=%s，最终可生成=%s，"
                "缺少核心财务已跳过=%s",
                market.value,
                target_count,
                len(ranked),
                len(selected),
                stats.skipped_no_core_financial_count,
            )
        else:
            self._logger.info(
                "%s 范围选择完成：模式=%s，目标=%s，候选财务=%s，跳过=%s，生成=%s",
                market.value,
                scope_mode.value,
                target_count or "全部",
                stats.candidate_count,
                stats.skipped_no_core_financial_count,
                stats.generated_count,
            )
        return selected, skipped, stats

    def _FinancialProgress_Initialize(
        self,
        securities: Sequence[Security],
        quote_results: dict[str, SourceValue[Any]],
    ) -> None:
        total = 0
        for market in self._config.markets:
            market_securities = [item for item in securities if item.market is market]
            scope_mode, top_n = self._config.MarketScope_Get(market)
            if scope_mode is MarketScopeMode.ALL:
                total += len(market_securities)
                continue
            quote_values = {
                security.key: (
                    quote_results[security.key].value
                    if security.key in quote_results
                    else None
                )
                for security in market_securities
            }
            ranked = Universe_RankByMarketCap(market_securities, quote_values)
            total += min(top_n, len(ranked))
        self._financial_progress_completed = 0
        self._financial_progress_total = total
        self._WorkPlan_StageTotalSet("年度财务", total)

    def _Performance_Get(self, total_seconds: float) -> dict[str, Any]:
        performance = dict(self._source.Performance_Get())
        performance.update(
            {
                "run_local_reuse": self._coordinator.reuse_count,
                "stage_seconds": {
                    name: round(value, 3)
                    for name, value in self._stage_durations.items()
                },
                "total_seconds": round(total_seconds, 3),
            }
        )
        return performance

    def _CancelledSummary_Create(
        self,
        started_at: datetime,
        records: list[AnalysisRecord],
        started_clock: float,
    ) -> RunSummary:
        performance = self._Performance_Get(time.perf_counter() - started_clock)
        return RunSummary(
            result=PipelineRunResult.CANCELLED,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            output_path=None,
            records=records,
            issues=[issue for record in records for issue in record.issues],
            success_count=0,
            partial_count=0,
            failed_count=0,
            excluded_count=0,
            config_snapshot=self._config.to_dict(),
            performance=performance,
        )

    def _FailedSummary_Create(
        self,
        started_at: datetime,
        started_clock: float,
        stage: str,
        error: Exception,
        *,
        records: list[AnalysisRecord] | None = None,
        market_stats: dict[Market, MarketSelectionStats] | None = None,
    ) -> RunSummary:
        selected_records = records or []
        issue = AnalysisIssue(
            market=self._config.markets[0],
            code="",
            company_name="",
            stage=stage,
            reason=str(error),
            source_name=self._source.source_name,
            field_name=stage,
            field_status=(
                DataStatus.SOURCE_UNAVAILABLE
                if isinstance(error, SourceUnavailableError)
                else DataStatus.ERROR
            ),
            is_core=True,
        )
        performance = self._Performance_Get(time.perf_counter() - started_clock)
        return RunSummary(
            result=PipelineRunResult.FAILED,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            output_path=None,
            records=selected_records,
            issues=[issue, *(item for record in selected_records for item in record.issues)],
            success_count=0,
            partial_count=0,
            failed_count=1,
            config_snapshot=self._config.to_dict(),
            performance=performance,
            market_stats=market_stats or {},
        )

    def run(self, output_path: Path | None = None) -> RunSummary:
        from stock_analysis.export.workbook import Workbook_Export

        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()
        records: list[AnalysisRecord] = []
        market_stats: dict[Market, MarketSelectionStats] = {}
        self._Progress_Emit("证券范围", "", 0, 0, 0, 0, 0, "正在加载证券列表")
        universe_started = time.perf_counter()
        try:
            universe_result = Universe_BuildDetailed(self._config, self._coordinator)
        except Exception as error:
            self._logger.exception("证券列表加载失败：%s", error)
            return self._FailedSummary_Create(
                started_at, started_clock, "证券范围", error
            )
        self._stage_durations["证券范围"] = time.perf_counter() - universe_started
        universe = universe_result.securities
        self._WorkPlan_Initialize(universe)

        try:
            quote_results = self._UniverseQuotes_Fetch(universe)
            self._FinancialProgress_Initialize(universe, quote_results)
            active_records: list[AnalysisRecord] = []
            skipped_records: list[AnalysisRecord] = []
            for market in self._config.markets:
                market_universe = [item for item in universe if item.market is market]
                selected, skipped, stats = self._MarketCandidates_Select(
                    market,
                    market_universe,
                    quote_results,
                    universe_result.identified_counts.get(market, len(market_universe)),
                    universe_result.delisted_counts.get(market, 0),
                )
                active_records.extend(selected)
                skipped_records.extend(skipped)
                market_stats[market] = stats
            records = active_records + skipped_records
            self._WorkPlan_DownstreamTotalsUpdate(active_records, records)
            self._ParallelStage_Run(
                "补全入选公司行情",
                active_records,
                self._coordinator.OutputQuote_Fetch,
                self._Attribute_Assign("quote"),
            )
            self._BatchStage_Run(
                "板块与行业",
                active_records,
                lambda progress_callback: self._coordinator.Profiles_Fetch(
                    [record.security for record in active_records],
                    progress_callback,
                ),
                self._Security_Assign,
            )
            self._BatchStage_Run(
                "概念",
                active_records,
                lambda progress_callback: self._coordinator.Concepts_Fetch(
                    [record.security for record in active_records],
                    progress_callback,
                ),
                self._Security_Assign,
            )
            self._ParallelStage_Run(
                "上市与发行信息",
                active_records,
                self._coordinator.IPO_Fetch,
                self._Attribute_Assign("ipo"),
            )
            active_securities = [
                replace(
                    record.security,
                    listing_date=(
                        record.ipo.listing_date
                        if record.ipo is not None
                        and record.ipo.listing_date is not None
                        else record.security.listing_date
                    ),
                )
                for record in active_records
            ]
            self._BatchStage_Run(
                "年度全市场大宗交易",
                active_records,
                lambda progress_callback: self._coordinator.BlockTrades_Fetch(
                    active_securities,
                    self._config.financial_year,
                    progress_callback,
                ),
                self._Attribute_Assign("block_trade"),
            )
            flow_as_of_date = max(
                (
                    record.quote.quote_date
                    for record in active_records
                    if record.quote is not None
                ),
                default=None,
            )
            self._BatchStage_Run(
                "资金流",
                active_records,
                lambda progress_callback: self._coordinator.Flows_Fetch(
                    active_securities,
                    flow_as_of_date,
                    progress_callback,
                ),
                self._Attribute_Assign("flow"),
            )
            success, partial, failed, excluded = self._Records_Finalize(records)
        except PipelineCancelled:
            self._logger.info("任务收到取消请求，已停止后续阶段")
            return self._CancelledSummary_Create(started_at, records, started_clock)
        except Exception as error:
            self._logger.exception("公司范围选择或数据采集失败：%s", error)
            return self._FailedSummary_Create(
                started_at,
                started_clock,
                "公司范围与数据采集",
                error,
                records=records,
                market_stats=market_stats,
            )

        selected_output = output_path
        if selected_output is None:
            output_root = Path(self._config.output_directory).expanduser()
            output_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            selected_output = output_root / f"股票分析表_{timestamp}.xlsx"
        self._WorkPlan_StageProgressSet("生成 Excel", 0)
        self._Progress_Emit(
            "生成 Excel",
            "",
            0,
            len(records),
            success,
            partial,
            failed,
            "正在写入 Excel",
            excluded=excluded,
        )
        result = PipelineRunResult.SUCCESS
        export_started = time.perf_counter()
        performance = self._Performance_Get(time.perf_counter() - started_clock)
        try:
            Workbook_Export(
                records,
                self._config,
                selected_output,
                {
                    "started_at": started_at,
                    "success_count": success,
                    "partial_count": partial,
                    "failed_count": failed,
                    "excluded_count": excluded,
                    "run_local_reuse": self._coordinator.reuse_count,
                    "performance": performance,
                    "market_stats": market_stats,
                },
            )
        except Exception as error:
            self._logger.exception("工作簿导出失败：%s", error)
            result = PipelineRunResult.FAILED
            selected_output = None
        else:
            self._WorkPlan_StageProgressSet("生成 Excel", len(records))
        self._stage_durations["生成 Excel"] = time.perf_counter() - export_started
        performance = self._Performance_Get(time.perf_counter() - started_clock)
        all_issues = [issue for record in records for issue in record.issues]
        if selected_output is not None:
            self._WorkPlan_Complete()
        self._Progress_Emit(
            "完成" if selected_output else "失败",
            "",
            len(records),
            len(records),
            success,
            partial,
            failed,
            f"输出：{selected_output}" if selected_output else "工作簿生成失败",
            excluded=excluded,
        )
        return RunSummary(
            result=result,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            output_path=selected_output,
            records=records,
            issues=all_issues,
            success_count=success,
            partial_count=partial,
            failed_count=failed,
            excluded_count=excluded,
            config_snapshot=self._config.to_dict(),
            performance=performance,
            market_stats=market_stats,
        )

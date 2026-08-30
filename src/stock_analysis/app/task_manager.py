from __future__ import annotations

import threading
from pathlib import Path

from stock_analysis.common.logging import Logging_Close, Logging_Configure
from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import MarketScopeMode
from stock_analysis.domain.models import RunProgress, RunSummary
from stock_analysis.pipeline.runner import PipelineRunner, ProgressCallback
from stock_analysis.sources.registry import SourceRegistry_Create


def _MarketScope_DescriptionGet(mode: MarketScopeMode, top_n: int) -> str:
    if mode is MarketScopeMode.ALL:
        return "全部公司"
    return f"总市值前 {top_n} 家"


class TaskManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runner: PipelineRunner | None = None

    def run(
        self,
        config: AppConfig,
        *,
        output_path: Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RunSummary:
        logger = Logging_Configure()
        source = None
        try:
            logger.info(
                "任务开始：分析年度=%s，市场=%s，测试模式=%s，"
                "A股范围=%s，港股范围=%s，资金流=A股及港股自动尝试，"
                "网络模式=%s，并发=%s，输出目录=%s",
                config.financial_year,
                ",".join(market.value for market in config.markets),
                config.test_mode or config.fixture_mode,
                _MarketScope_DescriptionGet(
                    config.a_share_scope_mode, config.a_share_top_n
                ),
                _MarketScope_DescriptionGet(config.hk_scope_mode, config.hk_top_n),
                config.network_mode.value,
                config.concurrency,
                config.output_directory,
            )
            source = SourceRegistry_Create(config)
            runner = PipelineRunner(config, source, progress_callback)
            with self._lock:
                self._runner = runner
            summary = runner.run(output_path)
            logger.info(
                "任务结束：结果=%s，成功=%s，部分缺失=%s，失败=%s，排除=%s，"
                "本次运行内复用=%s，性能=%s，输出=%s",
                summary.result.value,
                summary.success_count,
                summary.partial_count,
                summary.failed_count,
                summary.excluded_count,
                summary.performance.get("run_local_reuse", 0),
                summary.performance,
                summary.output_path,
            )
            return summary
        except Exception:
            logger.exception("后台任务发生未捕获异常")
            raise
        finally:
            with self._lock:
                self._runner = None
            try:
                if source is not None:
                    source.close()
            except Exception:
                logger.exception("关闭数据源时发生异常")
            Logging_Close(logger)

    def cancel(self) -> None:
        with self._lock:
            runner = self._runner
        if runner is not None:
            runner.cancel()


def TaskManager_NullProgress(_progress: RunProgress) -> None:
    return None

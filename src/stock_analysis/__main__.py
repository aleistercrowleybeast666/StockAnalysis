from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stock_analysis.config.storage import Config_Load
from stock_analysis.domain.enums import MarketScopeMode, PipelineRunResult
from stock_analysis.version import APP_DISPLAY_NAME, __version__


def Arguments_Parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="StockAnalysis", description=APP_DISPLAY_NAME)
    parser.add_argument("--version", action="store_true", help="显示版本并退出")
    parser.add_argument("--self-test", action="store_true", help="执行本地自检")
    parser.add_argument("--report", type=Path, help="自检 JSON 报告路径")
    parser.add_argument("--headless", action="store_true", help="无界面运行完整流水线")
    parser.add_argument("--config", type=Path, help="配置 JSON 路径")
    parser.add_argument("--fixture-mode", action="store_true", help="仅使用确定性内置数据")
    parser.add_argument("--max-a-share-companies", type=int, help="覆盖配置中的 A 股独立上限")
    parser.add_argument("--max-hk-companies", type=int, help="覆盖配置中的港股独立上限")
    parser.add_argument("--output", type=Path, help="覆盖输出工作簿路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = Arguments_Parse(argv)
    if arguments.version:
        print(__version__)
        return 0
    if arguments.self_test:
        from stock_analysis.app.application import SelfTest_Run
        from stock_analysis.common.paths import Paths_GetRuntimePaths

        report_path = arguments.report or Paths_GetRuntimePaths().data_root / "self_test.json"
        report = SelfTest_Run(report_path)
        return 0 if report["ok"] else 1

    config = Config_Load(arguments.config) if arguments.config else Config_Load()
    if arguments.fixture_mode:
        config.fixture_mode = True
        config.test_mode = True
    if arguments.max_a_share_companies is not None:
        config.a_share_scope_mode = (
            MarketScopeMode.TOP_MARKET_CAP
            if arguments.max_a_share_companies > 0
            else MarketScopeMode.ALL
        )
        if arguments.max_a_share_companies > 0:
            config.a_share_top_n = arguments.max_a_share_companies
    if arguments.max_hk_companies is not None:
        config.hk_scope_mode = (
            MarketScopeMode.TOP_MARKET_CAP
            if arguments.max_hk_companies > 0
            else MarketScopeMode.ALL
        )
        if arguments.max_hk_companies > 0:
            config.hk_top_n = arguments.max_hk_companies
    config.validate()

    if arguments.headless:
        from stock_analysis.app.application import Application_RunPipeline

        summary = Application_RunPipeline(config, output_path=arguments.output)
        print(
            json.dumps(
                {
                    "result": summary.result.value,
                    "output_path": str(summary.output_path) if summary.output_path else None,
                    "success": summary.success_count,
                    "partial": summary.partial_count,
                    "failed": summary.failed_count,
                    "excluded": summary.excluded_count,
                    "run_local_reuse": summary.performance.get("run_local_reuse", 0),
                    "performance": summary.performance,
                },
                ensure_ascii=False,
            )
        )
        return 0 if summary.result in {PipelineRunResult.SUCCESS, PipelineRunResult.PARTIAL} else 1

    from stock_analysis.app.application import Application_RunGui

    return Application_RunGui(config)


if __name__ == "__main__":
    sys.exit(main())

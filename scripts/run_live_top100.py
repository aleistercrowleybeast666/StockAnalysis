from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from audit_workbook_coverage import CoverageReports_Write, Workbook_Audit

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import (
    Market,
    MarketScopeMode,
    NetworkMode,
    TableSortMode,
)
from stock_analysis.domain.models import RunProgress, RunSummary
from stock_analysis.pipeline.runner import PipelineRunner
from stock_analysis.sources.registry import SourceRegistry_Create


def Arguments_Parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 A/H 真实网络验收")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--coverage-json", type=Path)
    parser.add_argument("--coverage-markdown", type=Path)
    parser.add_argument(
        "--allow-coverage-failure",
        action="store_true",
        help="仅用于生成明确标记为阻断的测试预览；正式门禁不得使用",
    )
    parser.add_argument("--year", type=int, default=date.today().year - 1)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument(
        "--all-companies",
        action="store_true",
        help="忽略 Top N，按 A/H 各自全部正常上市公司执行全量验收",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--request-interval", type=float, default=0.0)
    parser.add_argument("--exclude-st", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        help="控制终端日志详细程度；进度阶段摘要始终输出",
    )
    return parser.parse_args()


def ProgressRecorder_Create() -> tuple[list[dict[str, Any]], Any]:
    started = time.perf_counter()
    events: list[dict[str, Any]] = []
    lock = threading.Lock()
    last_key: tuple[str, int | None] | None = None

    def Progress_Record(progress: RunProgress) -> None:
        nonlocal last_key
        percent = (
            round(progress.overall_completed * 100 / progress.overall_total)
            if progress.overall_total > 0
            else None
        )
        key = (progress.stage, percent)
        with lock:
            if key == last_key:
                return
            last_key = key
            event = {
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "stage": progress.stage,
                "stage_completed": progress.completed,
                "stage_total": progress.total,
                "overall_percent": percent,
                "message": progress.message,
            }
            events.append(event)
        if len(events) == 1 or events[-2]["stage"] != progress.stage:
            print(
                f"[{event['elapsed_seconds']:8.3f}s] {progress.stage} "
                f"{progress.completed}/{progress.total} 总进度={percent}%",
                flush=True,
            )

    return events, Progress_Record


def SummaryPayload_Create(
    summary: RunSummary, progress_events: list[dict[str, Any]]
) -> dict[str, Any]:
    market_stats: dict[str, dict[str, Any]] = {}
    for market, stats in summary.market_stats.items():
        value = asdict(stats)
        value["market"] = stats.market.value
        market_stats[market.value] = value
    issue_counts = Counter(
        (
            issue.market.value,
            issue.stage,
            issue.field_name or "",
            issue.field_status.value,
            issue.reason,
        )
        for issue in summary.issues
    )
    return {
        "result": summary.result.value,
        "started_at": summary.started_at.isoformat(),
        "finished_at": summary.finished_at.isoformat(),
        "output_path": str(summary.output_path) if summary.output_path else None,
        "record_count": len(summary.records),
        "success_count": summary.success_count,
        "partial_count": summary.partial_count,
        "failed_count": summary.failed_count,
        "excluded_count": summary.excluded_count,
        "config": summary.config_snapshot,
        "performance": summary.performance,
        "market_stats": market_stats,
        "issue_count": len(summary.issues),
        "top_issues": [
            {
                "market": key[0],
                "stage": key[1],
                "field": key[2],
                "status": key[3],
                "reason": key[4],
                "count": count,
            }
            for key, count in issue_counts.most_common(50)
        ],
        "progress_events": progress_events,
    }


def Main_Run() -> int:
    args = Arguments_Parse()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run_report = args.run_report or args.output.with_suffix(".run.json")
    coverage_json = args.coverage_json or args.output.parent / "COVERAGE_FINAL.json"
    coverage_markdown = (
        args.coverage_markdown or args.output.parent / "COVERAGE_FINAL.md"
    )
    run_report.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    scope_mode = (
        MarketScopeMode.ALL
        if args.all_companies
        else MarketScopeMode.TOP_MARKET_CAP
    )
    config = AppConfig(
        financial_year=args.year,
        trading_year=args.year,
        markets=[Market.A_SHARE, Market.HK],
        a_share_scope_mode=scope_mode,
        a_share_top_n=args.top_n,
        hk_scope_mode=scope_mode,
        hk_top_n=args.top_n,
        include_st=not args.exclude_st,
        include_financial=True,
        table_sort_mode=TableSortMode.MARKET_CAP,
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        output_directory=str(args.output.parent),
        test_mode=False,
        fixture_mode=False,
        concurrency=args.concurrency,
        request_interval=args.request_interval,
    )
    config.validate()
    events, progress_callback = ProgressRecorder_Create()
    source = SourceRegistry_Create(config)
    try:
        summary = PipelineRunner(config, source, progress_callback).run(args.output)
    finally:
        source.close()
    payload = SummaryPayload_Create(summary, events)
    if summary.output_path is None:
        run_report.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"运行报告：{run_report}")
        return 1

    coverage_report = Workbook_Audit(summary.output_path)
    CoverageReports_Write(coverage_report, coverage_json, coverage_markdown)
    payload["coverage_gate"] = coverage_report["release_gate"]
    run_report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"工作簿：{summary.output_path}")
    print(f"运行报告：{run_report}")
    print(f"覆盖率报告：{coverage_json}；{coverage_markdown}")
    print(
        "公司状态："
        f"成功 {summary.success_count}，部分 {summary.partial_count}，"
        f"失败 {summary.failed_count}，排除 {summary.excluded_count}"
    )
    if not coverage_report["release_gate"]["passed"]:
        print("字段覆盖率发布门禁未通过", flush=True)
        return 0 if args.allow_coverage_failure else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(Main_Run())

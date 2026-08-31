#!/usr/bin/env python3
"""Run an all-A-share live audit for 5/22-day money-flow fallbacks."""

from __future__ import annotations

import argparse
import json
import threading
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, NetworkMode
from stock_analysis.sources.registry import LiveMarketDataSource, SourceRegistry_Create


def Arguments_Parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--request-interval", type=float, default=0.0)
    return parser.parse_args()


def Main_Run() -> int:
    arguments = Arguments_Parse()
    config = AppConfig(
        markets=[Market.A_SHARE],
        financial_year=date.today().year - 1,
        trading_year=date.today().year - 1,
        fixture_mode=False,
        network_mode=NetworkMode.DOMESTIC_DIRECT,
        concurrency=arguments.concurrency,
        request_interval=arguments.request_interval,
    )
    config.validate()
    source = SourceRegistry_Create(config)
    if not isinstance(source, LiveMarketDataSource):
        raise TypeError("真实网络审计必须使用 LiveMarketDataSource")
    completed = 0
    lock = threading.Lock()

    def Progress_Record(_security: Any) -> None:
        nonlocal completed
        with lock:
            completed += 1
            if completed % 500 == 0:
                print(f"资金流进度：{completed}", flush=True)

    try:
        securities = source.SecurityList_Fetch(Market.A_SHARE)
        results = source.Flows_Fetch(
            securities,
            date.today(),
            Progress_Record,
        )
        performance = source.Performance_Get()
    finally:
        source.close()

    five_count = sum(
        value.value is not None and value.value.five_day_net is not None
        for value in results.values()
    )
    month_count = sum(
        value.value is not None and value.value.one_month_net is not None
        for value in results.values()
    )
    bse = [security for security in securities if security.exchange == "BSE"]
    bse_five_count = sum(
        results[security.key].value is not None
        and results[security.key].value.five_day_net is not None
        for security in bse
        if security.key in results
    )
    bse_month_count = sum(
        results[security.key].value is not None
        and results[security.key].value.one_month_net is not None
        for security in bse
        if security.key in results
    )
    source_counts = Counter(
        value.provenance.source_name for value in results.values()
    )
    missing_reasons = Counter(
        value.provenance.missing_reason or "未记录原因"
        for value in results.values()
        if value.value is None
        or value.value.five_day_net is None
        or value.value.one_month_net is None
    )
    total = len(securities)
    payload = {
        "date": date.today().isoformat(),
        "company_count": total,
        "five_day_count": five_count,
        "five_day_coverage": round(five_count / total, 6) if total else 0.0,
        "twenty_two_day_count": month_count,
        "twenty_two_day_coverage": round(month_count / total, 6) if total else 0.0,
        "bse_company_count": len(bse),
        "bse_five_day_count": bse_five_count,
        "bse_twenty_two_day_count": bse_month_count,
        "source_counts": dict(source_counts),
        "top_missing_reasons": [
            {"reason": reason, "count": count}
            for reason, count in missing_reasons.most_common(30)
        ],
        "performance": performance,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "company_count",
                    "five_day_count",
                    "five_day_coverage",
                    "twenty_two_day_count",
                    "twenty_two_day_coverage",
                    "bse_company_count",
                    "bse_five_day_count",
                    "bse_twenty_two_day_count",
                    "source_counts",
                )
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0 if five_count / total >= 0.90 and month_count / total >= 0.90 else 3


if __name__ == "__main__":
    raise SystemExit(Main_Run())

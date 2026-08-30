from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from stock_analysis.domain.enums import (
    Market,
    MarketScopeMode,
    NetworkMode,
    TableSortMode,
)


@dataclass(slots=True)
class AppConfig:
    financial_year: int = field(default_factory=lambda: date.today().year - 1)
    trading_year: int = field(default_factory=lambda: date.today().year - 1)
    markets: list[Market] = field(default_factory=lambda: [Market.A_SHARE, Market.HK])
    a_share_scope_mode: MarketScopeMode = MarketScopeMode.ALL
    a_share_top_n: int = 100
    hk_scope_mode: MarketScopeMode = MarketScopeMode.ALL
    hk_top_n: int = 100
    include_st: bool = True
    include_financial: bool = True
    table_sort_mode: TableSortMode = TableSortMode.MARKET_CAP
    network_mode: NetworkMode = NetworkMode.DOMESTIC_DIRECT
    output_directory: str = field(default_factory=lambda: str(Path.home() / "Documents"))
    test_mode: bool = False
    fixture_mode: bool = False
    concurrency: int = 4
    request_interval: float = 0.6

    def validate(self) -> None:
        latest_complete_year = date.today().year - 1
        if not 1990 <= self.financial_year <= latest_complete_year:
            raise ValueError(
                f"完整财务年度必须为 1990 到 {latest_complete_year}"
            )
        if not 1990 <= self.trading_year <= latest_complete_year:
            raise ValueError(
                f"交易统计年度必须为 1990 到 {latest_complete_year}"
            )
        if not self.markets:
            raise ValueError("至少选择一个市场")
        if self.a_share_top_n <= 0:
            raise ValueError("A 股总市值前 N 家的 N 必须大于 0")
        if self.hk_top_n <= 0:
            raise ValueError("港股总市值前 N 家的 N 必须大于 0")
        if not 1 <= self.concurrency <= 8:
            raise ValueError("并发数必须为 1 到 8")
        if not 0.0 <= self.request_interval <= 10.0:
            raise ValueError("请求间隔必须为 0 到 10 秒")
        if not self.output_directory.strip():
            raise ValueError("输出目录不能为空")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["markets"] = [market.value for market in self.markets]
        result["a_share_scope_mode"] = self.a_share_scope_mode.value
        result["hk_scope_mode"] = self.hk_scope_mode.value
        result["table_sort_mode"] = self.table_sort_mode.value
        result["network_mode"] = self.network_mode.value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        allowed = {
            "financial_year",
            "trading_year",
            "markets",
            "a_share_scope_mode",
            "a_share_top_n",
            "hk_scope_mode",
            "hk_top_n",
            "include_st",
            "include_financial",
            "table_sort_mode",
            "network_mode",
            "output_directory",
            "test_mode",
            "fixture_mode",
            "concurrency",
            "request_interval",
        }
        clean = {key: value for key, value in data.items() if key in allowed}
        legacy_scope_fields = (
            (
                "max_a_share_companies",
                "a_share_scope_mode",
                "a_share_top_n",
            ),
            ("max_hk_companies", "hk_scope_mode", "hk_top_n"),
        )
        for legacy_name, mode_name, top_n_name in legacy_scope_fields:
            if mode_name in clean:
                continue
            try:
                legacy_limit = int(data.get(legacy_name, 0))
            except (TypeError, ValueError):
                legacy_limit = 0
            clean[mode_name] = (
                MarketScopeMode.TOP_MARKET_CAP
                if legacy_limit > 0
                else MarketScopeMode.ALL
            )
            if legacy_limit > 0:
                clean[top_n_name] = legacy_limit
        if "network_mode" not in clean and "use_system_proxy" in data:
            clean["network_mode"] = (
                NetworkMode.DOMESTIC_DIRECT
                if bool(data["use_system_proxy"])
                else NetworkMode.DIRECT
            )
        if "markets" in clean:
            clean["markets"] = [Market(item) for item in clean["markets"]]
        if "a_share_scope_mode" in clean:
            if clean["a_share_scope_mode"] == "全部正常上市公司":
                clean["a_share_scope_mode"] = MarketScopeMode.ALL.value
            clean["a_share_scope_mode"] = MarketScopeMode(clean["a_share_scope_mode"])
        if "hk_scope_mode" in clean:
            if clean["hk_scope_mode"] == "全部正常上市公司":
                clean["hk_scope_mode"] = MarketScopeMode.ALL.value
            clean["hk_scope_mode"] = MarketScopeMode(clean["hk_scope_mode"])
        if "table_sort_mode" in clean:
            clean["table_sort_mode"] = TableSortMode(clean["table_sort_mode"])
        if "network_mode" in clean:
            clean["network_mode"] = NetworkMode(clean["network_mode"])
        config = cls(**clean)
        config.validate()
        return config

    def MarketScope_Get(self, market: Market) -> tuple[MarketScopeMode, int]:
        if market is Market.A_SHARE:
            return self.a_share_scope_mode, self.a_share_top_n
        return self.hk_scope_mode, self.hk_top_n

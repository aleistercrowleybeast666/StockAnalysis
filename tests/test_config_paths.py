from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from stock_analysis.common.paths import Paths_GetRuntimePaths, Resources_GetPath
from stock_analysis.config.models import AppConfig
from stock_analysis.config.storage import Config_Load, Config_Save
from stock_analysis.domain.enums import (
    Market,
    MarketScopeMode,
    NetworkMode,
    TableSortMode,
)


def test_default_config_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings" / "config.json"
    config = AppConfig(
        financial_year=2025,
        trading_year=2025,
        markets=[Market.HK],
        include_st=False,
        output_directory=str(tmp_path),
        a_share_scope_mode=MarketScopeMode.TOP_MARKET_CAP,
        a_share_top_n=3,
        hk_scope_mode=MarketScopeMode.TOP_MARKET_CAP,
        hk_top_n=7,
        table_sort_mode=TableSortMode.REVENUE,
    )
    Config_Save(config, path)
    loaded = Config_Load(path)
    assert loaded.to_dict() == config.to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["markets"] == ["港股"]


def test_corrupt_config_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    loaded = Config_Load(path)
    assert isinstance(loaded, AppConfig)
    assert not path.exists()
    assert len(list(tmp_path.glob("config.corrupt.*.json"))) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("concurrency", 0),
        ("a_share_top_n", 0),
        ("hk_top_n", -1),
        ("request_interval", 20.0),
    ],
)
def test_invalid_config_is_rejected(field: str, value: object, tmp_path: Path) -> None:
    config = AppConfig(output_directory=str(tmp_path))
    setattr(config, field, value)
    with pytest.raises(ValueError):
        config.validate()


def test_current_incomplete_year_is_not_selectable_as_complete_year(
    tmp_path: Path,
) -> None:
    current_year = date.today().year
    config = AppConfig(
        financial_year=current_year,
        trading_year=current_year,
        output_directory=str(tmp_path),
    )
    with pytest.raises(ValueError, match=str(current_year - 1)):
        config.validate()


def test_legacy_total_target_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "financial_year": 2025,
                "trading_year": 2025,
                "markets": ["A股", "港股"],
                "max_companies": 100,
                "output_directory": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = Config_Load(path)
    assert not hasattr(loaded, "max_companies")
    assert loaded.a_share_scope_mode is MarketScopeMode.ALL
    assert loaded.hk_scope_mode is MarketScopeMode.ALL


def test_legacy_all_scope_label_is_still_loadable(tmp_path: Path) -> None:
    loaded = AppConfig.from_dict(
        {
            "a_share_scope_mode": "全部正常上市公司",
            "hk_scope_mode": "全部正常上市公司",
            "output_directory": str(tmp_path),
        }
    )

    assert loaded.a_share_scope_mode is MarketScopeMode.ALL
    assert loaded.hk_scope_mode is MarketScopeMode.ALL


@pytest.mark.parametrize(
    ("legacy_limit", "expected_mode", "expected_top_n"),
    [
        (0, MarketScopeMode.ALL, 100),
        (100, MarketScopeMode.TOP_MARKET_CAP, 100),
        (37, MarketScopeMode.TOP_MARKET_CAP, 37),
    ],
)
def test_legacy_market_limit_migrates(
    legacy_limit: int,
    expected_mode: MarketScopeMode,
    expected_top_n: int,
    tmp_path: Path,
) -> None:
    loaded = AppConfig.from_dict(
        {
            "markets": ["A股", "港股"],
            "max_a_share_companies": legacy_limit,
            "max_hk_companies": legacy_limit,
            "output_directory": str(tmp_path),
        }
    )
    assert loaded.a_share_scope_mode is expected_mode
    assert loaded.hk_scope_mode is expected_mode
    assert loaded.a_share_top_n == expected_top_n
    assert loaded.hk_top_n == expected_top_n


def test_legacy_cache_and_flow_controls_are_ignored(tmp_path: Path) -> None:
    loaded = AppConfig.from_dict(
        {
            "markets": ["A股"],
            "flow_mode": "完整模式（较慢）",
            "include_a_share_flow": False,
            "update_mode": "优先缓存",
            "max_a_share_companies": 10,
            "output_directory": str(tmp_path),
        }
    )
    assert not hasattr(loaded, "include_a_share_flow")
    assert not hasattr(loaded, "flow_mode")
    assert not hasattr(loaded, "update_mode")


def test_legacy_proxy_flag_migrates_to_domestic_direct_first(tmp_path: Path) -> None:
    path = tmp_path / "legacy-proxy.json"
    path.write_text(
        json.dumps(
            {
                "financial_year": 2025,
                "trading_year": 2025,
                "markets": ["A股"],
                "use_system_proxy": True,
                "output_directory": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert Config_Load(path).network_mode is NetworkMode.DOMESTIC_DIRECT


def test_runtime_paths_respect_override(isolated_runtime_home: Path) -> None:
    paths = Paths_GetRuntimePaths()
    assert paths.data_root == isolated_runtime_home.resolve()
    assert paths.logs_root.is_dir()
    assert not hasattr(paths, "database_file")
    assert not hasattr(paths, "cache_root")
    assert Resources_GetPath("templates/分析表.xlsx").is_file()


def test_frozen_windows_logs_are_beside_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    portable_root = tmp_path / "portable"
    executable = portable_root / "StockAnalysis.exe"
    monkeypatch.delenv("STOCK_ANALYSIS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "stock_analysis.common.paths.user_data_dir",
        lambda *_args, **_kwargs: str(tmp_path / "appdata"),
    )
    paths = Paths_GetRuntimePaths()
    assert paths.logs_root == portable_root / "logs"
    assert paths.log_file == portable_root / "logs" / "stock_analysis.log"
    assert paths.logs_root.is_dir()


def test_frozen_logs_stay_portable_when_data_home_is_overridden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    portable_root = tmp_path / "portable"
    data_root = tmp_path / "isolated-data"
    monkeypatch.setenv("STOCK_ANALYSIS_HOME", str(data_root))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(portable_root / "StockAnalysis.exe"))

    paths = Paths_GetRuntimePaths()

    assert paths.data_root == data_root.resolve()
    assert not hasattr(paths, "cache_root")
    assert paths.logs_root == portable_root / "logs"


def test_frozen_macos_logs_are_sibling_of_app_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "StockAnalysis.app" / "Contents" / "MacOS" / "StockAnalysis"
    monkeypatch.delenv("STOCK_ANALYSIS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr("stock_analysis.common.paths.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "stock_analysis.common.paths.user_data_dir",
        lambda *_args, **_kwargs: str(tmp_path / "Library" / "Application Support"),
    )
    paths = Paths_GetRuntimePaths()
    assert paths.logs_root == tmp_path / "logs"

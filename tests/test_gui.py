from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QRadioButton

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, MarketScopeMode, TableSortMode
from stock_analysis.domain.models import RunProgress
from stock_analysis.ui.config_widget import ConfigWidget
from stock_analysis.ui.main_window import MainWindow
from stock_analysis.ui.progress_widget import ProgressWidget
from stock_analysis.ui.theme import LIGHT_THEME_COLORS, LIGHT_THEME_QSS


def test_config_widget_round_trip_and_simplified_controls(qtbot, tmp_path: Path) -> None:
    config = AppConfig(
        financial_year=2025,
        trading_year=2025,
        markets=[Market.A_SHARE],
        a_share_scope_mode=MarketScopeMode.TOP_MARKET_CAP,
        a_share_top_n=37,
        hk_scope_mode=MarketScopeMode.ALL,
        hk_top_n=200,
        include_st=False,
        table_sort_mode=TableSortMode.REVENUE,
        output_directory=str(tmp_path),
        test_mode=True,
        concurrency=2,
        request_interval=0.2,
    )
    widget = ConfigWidget(config)
    qtbot.addWidget(widget)
    result = widget.config()
    assert result.to_dict() == config.to_dict()
    assert widget.a_share_top_n.currentText() == "37"
    assert widget.hk_top_n.currentText() == "200"
    assert TableSortMode(widget.table_sort_mode.currentData()) is TableSortMode.REVENUE
    assert widget.findChild(QCheckBox, "include_a_share_flow") is None
    assert not widget.include_st.isChecked()
    assert widget.findChild(QCheckBox, "include_st") is widget.include_st
    assert not widget.hk_scope_row.isEnabled()
    assert not widget.findChild(QGroupBox, "advanced_group")
    for removed_name in (
        "trading_year",
        "include_financial",
        "update_mode",
        "flow_mode",
        "network_mode",
        "test_mode",
        "max_a_share_companies",
        "max_hk_companies",
        "concurrency",
        "request_interval",
    ):
        assert widget.findChild(QComboBox, removed_name) is None
    widget.set_running(True)
    assert not widget.financial_year.isEnabled()


def test_scope_controls_toggle_and_default_year(qtbot, tmp_path: Path) -> None:
    widget = ConfigWidget(AppConfig(output_directory=str(tmp_path)))
    qtbot.addWidget(widget)
    assert int(widget.financial_year.currentData()) == date.today().year - 1
    assert widget.market_a.isChecked()
    assert widget.market_hk.isChecked()
    assert not widget.a_share_scope_limit.isChecked()
    assert not widget.hk_scope_limit.isChecked()
    assert not widget.a_share_top_n.isEnabled()

    widget.a_share_scope_limit.setChecked(True)
    assert widget.a_share_top_n.isEnabled()
    widget.a_share_scope_limit.setChecked(False)
    assert not widget.a_share_top_n.isEnabled()
    assert widget.a_share_top_n.isHidden()
    assert not widget._a_share_scope_hint.isHidden()
    assert widget._a_share_scope_hint.text() == "全部公司"
    widget.market_hk.setChecked(False)
    assert not widget.hk_scope_row.isEnabled()
    widget.market_hk.setChecked(True)
    assert widget.hk_scope_row.isEnabled()


def test_progress_widget_and_main_window_basics(qtbot, tmp_path: Path) -> None:
    progress_widget = ProgressWidget()
    qtbot.addWidget(progress_widget)
    progress_widget.reset()
    progress_widget.update_progress(
        RunProgress("证券范围", "", 0, 0, 0, 0, 0, "正在准备证券池")
    )
    assert progress_widget.progress_bar.minimum() == 0
    assert progress_widget.progress_bar.maximum() == 0
    assert "数量确定后" in progress_widget.count_label.text()
    assert not progress_widget.log.isVisible()
    assert not hasattr(progress_widget, "outcome_label")

    progress_widget.update_progress(
        RunProgress(
            "获取行情与市值",
            "",
            5,
            5,
            0,
            0,
            0,
            "行情完成",
            overall_completed=100,
            overall_total=1000,
        )
    )
    assert progress_widget.progress_bar.maximum() == 100
    assert progress_widget.progress_bar.value() == 10
    progress_widget.update_progress(
        RunProgress(
            "年度财务",
            "样例公司",
            2,
            4,
            0,
            0,
            0,
            "正在处理年度财务",
            overall_completed=400,
            overall_total=1000,
        )
    )
    assert progress_widget.progress_bar.value() == 40
    assert "样例公司" in progress_widget.company_label.text()
    progress_widget.update_progress(
        RunProgress("完成", "", 4, 4, 0, 0, 0, "完成")
    )
    assert progress_widget.progress_bar.value() == 100

    progress_widget.reset()
    progress_widget.update_progress(
        RunProgress(
            "资金流",
            "样例公司",
            2,
            4,
            0,
            0,
            0,
            "资金流",
            overall_completed=900,
            overall_total=1000,
        )
    )
    assert progress_widget.progress_bar.value() == 90

    window = MainWindow(AppConfig(output_directory=str(tmp_path), fixture_mode=True))
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle().startswith("股票分析表生成器")
    assert window.start_button.text() == "开始生成"
    assert window.cancel_button.text() == "取消"
    assert not window.cancel_button.isEnabled()
    assert LIGHT_THEME_COLORS["button"] in window.styleSheet()
    assert "缓存" not in window.config_widget.findChild(QGroupBox, "").title()


def test_theme_has_visible_checkboxes_and_single_blue_accent(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow(AppConfig(output_directory=str(tmp_path), fixture_mode=True))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert "QCheckBox::indicator:unchecked" in LIGHT_THEME_QSS
    assert not window.config_widget.findChildren(QRadioButton)
    assert "border: 2px solid #64748B" in LIGHT_THEME_QSS
    assert "checkbox_checked.svg" in LIGHT_THEME_QSS
    assert LIGHT_THEME_COLORS["main_title"] == LIGHT_THEME_COLORS["button"]
    assert LIGHT_THEME_COLORS["section_title"] == LIGHT_THEME_COLORS["button"]
    assert LIGHT_THEME_COLORS["focus"] == LIGHT_THEME_COLORS["button"]


def test_start_updates_button_state(qtbot, monkeypatch, tmp_path: Path) -> None:
    window = MainWindow(AppConfig(output_directory=str(tmp_path), fixture_mode=True))
    qtbot.addWidget(window)

    def fake_start(_config: AppConfig) -> None:
        assert window.progress_widget.progress_bar.minimum() == 0
        assert window.progress_widget.progress_bar.maximum() == 0
        window._controller.running_changed.emit(True)

    monkeypatch.setattr(window._controller, "start", fake_start)
    window.start_button.click()
    assert not window.start_button.isEnabled()
    assert window.cancel_button.isEnabled()
    assert window.status_label.text() == "运行中…"
    window._controller.running_changed.emit(False)

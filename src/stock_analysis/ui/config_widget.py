from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, MarketScopeMode, TableSortMode


class ConfigWidget(QWidget):
    config_changed = Signal()
    _COMMON_TOP_N = (50, 100, 200, 500)

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("config_widget")
        self._base_config = config
        self._BuildUi()
        self.apply_config(config)

    def _BuildUi(self) -> None:
        layout = QVBoxLayout(self)

        analysis = QGroupBox("分析年度")
        analysis_form = QFormLayout(analysis)
        self.financial_year = QComboBox()
        self.financial_year.setObjectName("financial_year")
        current_year = date.today().year
        for year in range(current_year - 1, max(1990, current_year - 21), -1):
            self.financial_year.addItem(str(year), year)
        analysis_form.addRow("完整财务年度", self.financial_year)
        layout.addWidget(analysis)

        scope = QGroupBox("股票范围")
        scope_layout = QVBoxLayout(scope)
        (
            self.market_a,
            self.a_share_scope_limit,
            self.a_share_top_n,
            self.a_share_scope_row,
        ) = self._MarketScope_Create("A 股", "a_share")
        (
            self.market_hk,
            self.hk_scope_limit,
            self.hk_top_n,
            self.hk_scope_row,
        ) = self._MarketScope_Create("港股", "hk")
        scope_layout.addWidget(self.market_a)
        scope_layout.addWidget(self.a_share_scope_row)
        scope_layout.addSpacing(5)
        scope_layout.addWidget(self.market_hk)
        scope_layout.addWidget(self.hk_scope_row)
        self.include_st = QCheckBox("包含 ST 股票（仅 A 股）")
        self.include_st.setObjectName("include_st")
        self.include_st.setToolTip(
            "未勾选时，会在范围筛选阶段排除名称中带 ST 或 *ST 的 A 股公司。"
        )
        scope_layout.addSpacing(5)
        scope_layout.addWidget(self.include_st)
        sort_row = QWidget()
        sort_layout = QHBoxLayout(sort_row)
        sort_layout.setContentsMargins(0, 0, 0, 0)
        sort_layout.addWidget(QLabel("表格排序"))
        self.table_sort_mode = QComboBox()
        self.table_sort_mode.setObjectName("table_sort_mode")
        self.table_sort_mode.addItem("按最新总市值（默认）", TableSortMode.MARKET_CAP)
        self.table_sort_mode.addItem("按分析年度营业收入", TableSortMode.REVENUE)
        sort_layout.addWidget(self.table_sort_mode, 1)
        scope_layout.addWidget(sort_row)
        scope_note = QLabel(
            "勾选“限制为总市值前”时按最新总市值取前 N 家；"
            "未勾选时取该市场全部公司。范围筛选和最终表格排序相互独立。"
        )
        scope_note.setObjectName("scope_note")
        scope_note.setWordWrap(True)
        scope_layout.addWidget(scope_note)
        layout.addWidget(scope)

        output = QGroupBox("输出位置")
        output_form = QFormLayout(output)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_directory = QLineEdit()
        self.output_directory.setObjectName("output_directory")
        self.browse_button = QPushButton("选择…")
        self.browse_button.setObjectName("browse_button")
        self.browse_button.clicked.connect(self._Browse_Clicked)
        output_layout.addWidget(self.output_directory, 1)
        output_layout.addWidget(self.browse_button)
        output_form.addRow("保存目录", output_row)
        layout.addWidget(output)

        note = QLabel(
            "正常不适用或公开网站未覆盖的可选字段会显示“—”，不会影响整份表生成。"
        )
        note.setObjectName("user_note")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.financial_year.currentIndexChanged.connect(self.config_changed)
        self.output_directory.textChanged.connect(self.config_changed)
        self.include_st.toggled.connect(self.config_changed)
        self.table_sort_mode.currentIndexChanged.connect(self.config_changed)
        for market_checkbox, scope_limit, top_n in (
            (self.market_a, self.a_share_scope_limit, self.a_share_top_n),
            (self.market_hk, self.hk_scope_limit, self.hk_top_n),
        ):
            market_checkbox.toggled.connect(self._MarketControls_Update)
            market_checkbox.toggled.connect(self.config_changed)
            scope_limit.toggled.connect(self._MarketControls_Update)
            scope_limit.toggled.connect(self.config_changed)
            top_n.currentTextChanged.connect(self.config_changed)

    def _MarketScope_Create(
        self, label: str, object_prefix: str
    ) -> tuple[QCheckBox, QCheckBox, QComboBox, QWidget]:
        market = QCheckBox(label)
        market.setObjectName(f"market_{'a' if object_prefix == 'a_share' else 'hk'}")
        scope_limit = QCheckBox("限制为总市值前")
        scope_limit.setObjectName(f"{object_prefix}_scope_limit")
        scope_limit.setToolTip(
            "未勾选时不使用右侧数量，采集该市场全部合格公司。"
        )
        top_n = QComboBox()
        top_n.setObjectName(f"{object_prefix}_top_n")
        top_n.setEditable(True)
        top_n.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        top_n.setMinimumWidth(88)
        for value in self._COMMON_TOP_N:
            top_n.addItem(str(value), value)
        unit = QLabel("家")
        unit.setObjectName(f"{object_prefix}_top_n_unit")
        scope_hint = QLabel("全部公司")
        scope_hint.setObjectName(f"{object_prefix}_scope_hint")
        setattr(self, f"_{object_prefix}_top_n_unit", unit)
        setattr(self, f"_{object_prefix}_scope_hint", scope_hint)
        row = QWidget()
        row.setObjectName(f"{object_prefix}_scope_row")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(24, 0, 0, 0)
        row_layout.addWidget(scope_limit)
        row_layout.addWidget(top_n)
        row_layout.addWidget(unit)
        row_layout.addWidget(scope_hint)
        row_layout.addStretch(1)
        return market, scope_limit, top_n, row

    def _MarketControls_Update(self) -> None:
        for checked, row, scope_limit, top_n, unit, scope_hint in (
            (
                self.market_a.isChecked(),
                self.a_share_scope_row,
                self.a_share_scope_limit,
                self.a_share_top_n,
                self._a_share_top_n_unit,
                self._a_share_scope_hint,
            ),
            (
                self.market_hk.isChecked(),
                self.hk_scope_row,
                self.hk_scope_limit,
                self.hk_top_n,
                self._hk_top_n_unit,
                self._hk_scope_hint,
            ),
        ):
            row.setEnabled(checked)
            scope_limit.setEnabled(checked)
            top_n.setEnabled(checked and scope_limit.isChecked())
            top_n.setVisible(scope_limit.isChecked())
            unit.setVisible(scope_limit.isChecked())
            scope_hint.setText(
                "全部公司" if checked else "该市场未启用"
            )
            scope_hint.setVisible(not scope_limit.isChecked())

    def _Browse_Clicked(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录",
            self.output_directory.text() or str(Path.home()),
        )
        if selected:
            self.output_directory.setText(selected)

    @staticmethod
    def _TopN_Set(control: QComboBox, value: int) -> None:
        index = control.findData(value)
        if index >= 0:
            control.setCurrentIndex(index)
        else:
            control.setEditText(str(value))

    @staticmethod
    def _TopN_Get(control: QComboBox, market_name: str) -> int:
        text = control.currentText().strip().removesuffix("家").strip()
        try:
            value = int(text)
        except ValueError as error:
            raise ValueError(f"{market_name}总市值公司数必须是整数") from error
        if not 1 <= value <= 10000:
            raise ValueError(f"{market_name}总市值公司数必须为 1 到 10000")
        return value

    def apply_config(self, config: AppConfig) -> None:
        self._base_config = config
        self.financial_year.setCurrentText(str(config.financial_year))
        self.market_a.setChecked(Market.A_SHARE in config.markets)
        self.market_hk.setChecked(Market.HK in config.markets)
        self.a_share_scope_limit.setChecked(
            config.a_share_scope_mode is MarketScopeMode.TOP_MARKET_CAP
        )
        self.hk_scope_limit.setChecked(
            config.hk_scope_mode is MarketScopeMode.TOP_MARKET_CAP
        )
        self._TopN_Set(self.a_share_top_n, config.a_share_top_n)
        self._TopN_Set(self.hk_top_n, config.hk_top_n)
        self.include_st.setChecked(config.include_st)
        sort_index = self.table_sort_mode.findData(config.table_sort_mode)
        self.table_sort_mode.setCurrentIndex(max(0, sort_index))
        self.output_directory.setText(config.output_directory)
        self._MarketControls_Update()

    def config(self) -> AppConfig:
        markets = []
        if self.market_a.isChecked():
            markets.append(Market.A_SHARE)
        if self.market_hk.isChecked():
            markets.append(Market.HK)
        year = int(self.financial_year.currentData())
        config = AppConfig(
            financial_year=year,
            trading_year=year,
            markets=markets,
            a_share_scope_mode=(
                MarketScopeMode.TOP_MARKET_CAP
                if self.a_share_scope_limit.isChecked()
                else MarketScopeMode.ALL
            ),
            a_share_top_n=self._TopN_Get(self.a_share_top_n, "A 股"),
            hk_scope_mode=(
                MarketScopeMode.TOP_MARKET_CAP
                if self.hk_scope_limit.isChecked()
                else MarketScopeMode.ALL
            ),
            hk_top_n=self._TopN_Get(self.hk_top_n, "港股"),
            include_st=self.include_st.isChecked(),
            include_financial=True,
            table_sort_mode=TableSortMode(self.table_sort_mode.currentData()),
            network_mode=self._base_config.network_mode,
            output_directory=self.output_directory.text().strip(),
            test_mode=self._base_config.test_mode,
            fixture_mode=self._base_config.fixture_mode,
            concurrency=self._base_config.concurrency,
            request_interval=self._base_config.request_interval,
        )
        config.validate()
        return config

    def set_running(self, running: bool) -> None:
        self.setEnabled(not running)

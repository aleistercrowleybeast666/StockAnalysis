from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from stock_analysis.domain.models import RunProgress


class ProgressWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overall_percent = 0
        layout = QVBoxLayout(self)
        summary = QGroupBox("生成进度")
        summary.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        form = QFormLayout(summary)
        self.stage_label = QLabel("等待开始")
        self.stage_label.setObjectName("stage_label")
        self.company_label = QLabel("—")
        self.company_label.setObjectName("company_label")
        self.count_label = QLabel("0 / 0")
        self.count_label.setObjectName("count_label")
        form.addRow("当前任务", self.stage_label)
        form.addRow("正在处理", self.company_label)
        form.addRow("任务进度", self.count_label)
        layout.addWidget(summary)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progress_bar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("总进度 %p%")
        layout.addWidget(self.progress_bar)

        self.details_button = QToolButton()
        self.details_button.setObjectName("details_button")
        self.details_button.setText("详细信息")
        self.details_button.setCheckable(True)
        layout.addWidget(self.details_button)
        self.log = QTextEdit()
        self.log.setObjectName("progress_log")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("详细运行信息将在这里显示。")
        self.log.setVisible(False)
        layout.addWidget(self.log, 1)
        self.bottom_space = QWidget()
        self.bottom_space.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.bottom_space, 1)
        self.details_button.toggled.connect(self._Details_Toggled)

    def _Details_Toggled(self, checked: bool) -> None:
        self.log.setVisible(checked)
        self.bottom_space.setVisible(not checked)

    def reset(self) -> None:
        self.stage_label.setText("正在准备证券范围与数据源")
        self.company_label.setText("—")
        self.count_label.setText("正在准备证券范围与数据源")
        self._overall_percent = 0
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("正在准备…")
        self.log.clear()

    def update_progress(self, progress: RunProgress) -> None:
        self.stage_label.setText(self._StageText_Get(progress.stage))
        self.company_label.setText(progress.current_company or "—")
        self._overall_percent = self._OverallPercent_Calculate(progress)
        preparing = progress.stage == "证券范围" and progress.total <= 0
        if preparing:
            self.count_label.setText("正在准备证券范围与数据源，数量确定后计算总进度")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("正在准备…")
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("总进度 %p%")
            if progress.total > 0:
                self.count_label.setText(
                    f"{progress.completed} / {progress.total}｜总进度 {self._overall_percent}%"
                )
            else:
                self.count_label.setText(f"总进度 {self._overall_percent}%")
            self.progress_bar.setValue(self._overall_percent)
        if progress.message:
            self.append_log(progress.message)

    def _OverallPercent_Calculate(self, progress: RunProgress) -> int:
        if progress.stage == "完成":
            return 100
        if progress.overall_total <= 0:
            return self._overall_percent
        fraction = min(
            1.0,
            max(0.0, progress.overall_completed / progress.overall_total),
        )
        calculated = min(99, round(100 * fraction))
        return max(self._overall_percent, calculated)

    @staticmethod
    def _StageText_Get(stage: str) -> str:
        return {
            "证券范围": "正在获取证券列表…",
            "获取行情与市值": "正在获取行情与总市值…",
            "年度财务": "正在分析公司财务数据…",
            "上市与发行信息": "正在获取上市与发行资料…",
            "年度全市场大宗交易": "正在汇总大宗交易…",
            "资金流": "正在获取 A 股及港股资金流…",
            "标准化、计算与校验": "正在计算分析指标…",
            "生成 Excel": "正在生成 Excel…",
            "完成": "生成完成",
            "失败": "生成失败",
        }.get(stage, stage)

    def append_log(self, message: str) -> None:
        self.log.append(message)

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from stock_analysis.app.controller import ApplicationController
from stock_analysis.common.paths import Paths_GetRuntimePaths
from stock_analysis.config.models import AppConfig
from stock_analysis.config.storage import Config_Save
from stock_analysis.domain.enums import DataStatus, Market, PipelineRunResult
from stock_analysis.domain.models import AnalysisIssue, RunProgress, RunSummary
from stock_analysis.ui.config_widget import ConfigWidget
from stock_analysis.ui.progress_widget import ProgressWidget
from stock_analysis.ui.theme import LIGHT_THEME_QSS
from stock_analysis.version import APP_DISPLAY_NAME, __version__


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("main_window")
        self.setStyleSheet(LIGHT_THEME_QSS)
        self.setWindowTitle(f"{APP_DISPLAY_NAME} {__version__}")
        self.resize(1060, 720)
        self._last_output: Path | None = None
        self._completion_dialog: QMessageBox | None = None
        self._close_after_cancel = False
        self._controller = ApplicationController(self)
        self._BuildUi(config)
        self._ConnectSignals()

    def _BuildUi(self, config: AppConfig) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        title = QLabel(APP_DISPLAY_NAME)
        title.setObjectName("main_title")
        subtitle = QLabel("本地生成 A 股与港股年度分析表，不提供投资建议。")
        subtitle.setObjectName("main_subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        splitter = QSplitter()
        self.config_widget = ConfigWidget(config)
        self.progress_widget = ProgressWidget()
        splitter.addWidget(self.config_widget)
        splitter.addWidget(self.progress_widget)
        splitter.setSizes([430, 610])
        root.addWidget(splitter, 1)

        controls = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status_label")
        self.open_folder_button = QPushButton("打开输出目录")
        self.open_folder_button.setObjectName("open_folder_button")
        self.open_folder_button.setEnabled(False)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.setEnabled(False)
        self.start_button = QPushButton("开始生成")
        self.start_button.setObjectName("start_button")
        self.start_button.setDefault(True)
        controls.addWidget(self.status_label, 1)
        controls.addWidget(self.open_folder_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.start_button)
        root.addLayout(controls)
        self.setCentralWidget(central)

    def _ConnectSignals(self) -> None:
        self.start_button.clicked.connect(self._Start_Clicked)
        self.cancel_button.clicked.connect(self._Cancel_Clicked)
        self.open_folder_button.clicked.connect(self._OpenFolder_Clicked)
        self._controller.progress.connect(self._Progress_Handle)
        self._controller.finished.connect(self._Finished_Handle)
        self._controller.error.connect(self._Error_Handle)
        self._controller.running_changed.connect(self._Running_Changed)

    def _Start_Clicked(self) -> None:
        try:
            config = self.config_widget.config()
            Config_Save(config)
        except Exception as error:
            self.status_label.setText(f"配置错误：{error}")
            self.progress_widget.append_log(f"配置错误：{error}")
            return
        self._last_output = None
        self.open_folder_button.setEnabled(False)
        self.progress_widget.reset()
        self.status_label.setText("运行中…")
        QApplication.processEvents()
        try:
            self._controller.start(config)
        except Exception as error:
            self._Error_Handle(str(error))

    def _Cancel_Clicked(self) -> None:
        self.status_label.setText("正在取消…")
        self.cancel_button.setEnabled(False)
        self._controller.cancel()

    def _Progress_Handle(self, progress: RunProgress) -> None:
        self.progress_widget.update_progress(progress)

    def _Finished_Handle(self, summary: RunSummary) -> None:
        if summary.output_path is not None:
            self._last_output = summary.output_path
            self.open_folder_button.setEnabled(True)
        if summary.result is PipelineRunResult.CANCELLED:
            self.status_label.setText("已取消")
        elif summary.result is PipelineRunResult.FAILED:
            reason = summary.issues[0].reason if summary.issues else "未知错误"
            self.status_label.setText(f"生成失败：{reason}")
            self.status_label.setToolTip(f"{reason}\n日志：{Paths_GetRuntimePaths().log_file}")
        else:
            self.status_label.setText(f"已完成：{summary.output_path}")
        grouped_issues: dict[tuple[str, str, str], tuple[AnalysisIssue, int]] = {}
        for issue in summary.issues:
            key = (issue.stage, issue.reason, issue.field_status.value)
            existing = grouped_issues.get(key)
            grouped_issues[key] = (
                (existing or (issue, 0))[0],
                (existing or (issue, 0))[1] + 1,
            )
        for issue_object, count in list(grouped_issues.values())[:20]:
            issue = issue_object
            company_text = issue.code or "-"
            if count > 1:
                company_text = f"{count} 家公司"
            self.progress_widget.append_log(
                f"异常 [{issue.stage}] {company_text}：{issue.reason}"
            )
        if summary.result is PipelineRunResult.FAILED:
            self.progress_widget.append_log(f"详细日志：{Paths_GetRuntimePaths().log_file}")
        self.progress_widget.append_log(f"内部任务结果：{summary.result.value}")
        if summary.performance:
            self.progress_widget.append_log(
                "性能摘要：HTTP 请求 "
                f"{summary.performance.get('http_requests', 0)}，"
                f"重试 {summary.performance.get('retries', 0)}，"
                f"总耗时 {summary.performance.get('total_seconds', 0)} 秒"
            )
        if summary.output_path is not None:
            self._CompletionDialog_Show(summary)

    def _CompletionDialog_Show(self, summary: RunSummary) -> None:
        generated_counts: dict[Market, int] = {}
        for market in (Market.A_SHARE, Market.HK):
            stats = summary.market_stats.get(market)
            generated_counts[market] = (
                stats.generated_count
                if stats is not None
                else sum(
                    record.security.market is market and not record.excluded_reason
                    for record in summary.records
                )
            )
        quote_dates = [
            record.quote.quote_date
            for record in summary.records
            if not record.excluded_reason and record.quote is not None
        ]
        latest_quote_date = max(quote_dates).isoformat() if quote_dates else "未取得"
        analysis_year = summary.config_snapshot.get("financial_year", "-")
        lines = [
            "生成完成",
            "",
            f"A 股：{generated_counts[Market.A_SHARE]} 家",
            f"港股：{generated_counts[Market.HK]} 家",
            f"分析年度：{analysis_year}",
            f"最新行情日期：{latest_quote_date}",
        ]
        if self._Summary_HasMissingPublicData(summary):
            lines.extend(["", "部分公开数据未取得，详情见工作簿第三页。"])
        lines.extend(["", "输出文件：", str(summary.output_path)])
        dialog = QMessageBox(self)
        dialog.setWindowTitle("生成完成")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("\n".join(lines))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.finished.connect(lambda _result: setattr(self, "_completion_dialog", None))
        self._completion_dialog = dialog
        dialog.open()

    @staticmethod
    def _Summary_HasMissingPublicData(summary: RunSummary) -> bool:
        key_fields = {
            "发行时总市值",
            "市值增长率",
            "当年累计大宗交易笔数",
            "当年累计大宗交易金额",
            "近五个交易日资金净额",
            "近一月资金净额（最近22个交易日）",
        }
        for record in summary.records:
            if record.excluded_reason:
                continue
            for field_name in key_fields:
                status = record.field_statuses.get(field_name)
                if status not in {DataStatus.OK, DataStatus.NOT_APPLICABLE}:
                    return True
        return False

    def _Error_Handle(self, message: str) -> None:
        self.status_label.setText(f"失败：{message}")
        self.progress_widget.append_log(f"后台任务异常：{message}")
        self.progress_widget.append_log(f"详细日志：{Paths_GetRuntimePaths().log_file}")

    def _Running_Changed(self, running: bool) -> None:
        self.config_widget.set_running(running)
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if not running and self._close_after_cancel:
            self._close_after_cancel = False
            QTimer.singleShot(0, self.close)

    def _OpenFolder_Clicked(self) -> None:
        if self._last_output is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output.parent)))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override name
        if self._controller.is_running:
            answer = QMessageBox.question(
                self,
                "任务仍在运行",
                "关闭窗口将取消当前任务，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._close_after_cancel = True
            self._controller.cancel()
            self.status_label.setText("正在取消任务，完成后关闭…")
            event.ignore()
            return
        event.accept()

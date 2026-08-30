from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.models import RunProgress, RunSummary
from stock_analysis.ui.workers import PipelineWorker


class ApplicationController(QObject):
    progress = Signal(object)
    finished = Signal(object)
    error = Signal(str)
    running_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, config: AppConfig) -> None:
        if self.is_running:
            raise RuntimeError("已有任务正在运行")
        thread = QThread(self)
        worker = PipelineWorker(config)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._Progress_Forward)
        worker.finished.connect(self._Finished_Handle)
        worker.error.connect(self._Error_Handle)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._Thread_Finished)
        self._thread = thread
        self._worker = worker
        self.running_changed.emit(True)
        thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _Progress_Forward(self, progress: RunProgress) -> None:
        self.progress.emit(progress)

    def _Finished_Handle(self, summary: RunSummary) -> None:
        self.finished.emit(summary)

    def _Error_Handle(self, message: str) -> None:
        self.error.emit(message)

    def _Thread_Finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.deleteLater()
        self.running_changed.emit(False)


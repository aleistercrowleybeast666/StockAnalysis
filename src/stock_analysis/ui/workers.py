from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from stock_analysis.app.task_manager import TaskManager
from stock_analysis.config.models import AppConfig


class PipelineWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._manager = TaskManager()

    @Slot()
    def run(self) -> None:
        try:
            summary = self._manager.run(
                self._config,
                progress_callback=lambda value: self.progress.emit(value),
            )
            self.finished.emit(summary)
        except Exception as error:
            self.error.emit(str(error))

    @Slot()
    def cancel(self) -> None:
        self._manager.cancel()


from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from stock_analysis.app.task_manager import TaskManager
from stock_analysis.common.paths import Paths_GetRuntimePaths, Resources_GetPath
from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market, PipelineRunResult
from stock_analysis.domain.models import RunSummary
from stock_analysis.export.workbook import Workbook_Validate
from stock_analysis.version import (
    APP_DISPLAY_NAME,
    APP_INTERNAL_NAME,
    ORGANIZATION_NAME,
    __version__,
)


def Application_RunPipeline(
    config: AppConfig,
    *,
    output_path: Path | None = None,
    progress_callback=None,
) -> RunSummary:
    return TaskManager().run(
        config, output_path=output_path, progress_callback=progress_callback
    )


def Application_RunGui(config: AppConfig) -> int:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from stock_analysis.ui.main_window import MainWindow
    from stock_analysis.ui.theme import LIGHT_THEME_QSS

    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setApplicationName(APP_INTERNAL_NAME)
    application = QApplication.instance() or QApplication([])
    application.setApplicationDisplayName(APP_DISPLAY_NAME)
    application.setStyleSheet(LIGHT_THEME_QSS)
    window = MainWindow(config)
    window.show()
    return application.exec()


def SelfTest_Run(report_path: Path) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    previous_home = os.environ.get("STOCK_ANALYSIS_HOME")
    with tempfile.TemporaryDirectory(prefix="StockAnalysis_selftest_") as temporary:
        temporary_root = Path(temporary)
        os.environ["STOCK_ANALYSIS_HOME"] = str(temporary_root / "runtime")
        try:
            template = Resources_GetPath("templates/分析表.xlsx")
            fixture = Resources_GetPath("fixtures/market_data.json")
            checks["resources"] = {
                "ok": template.is_file() and fixture.is_file(),
                "template": str(template),
                "fixture": str(fixture),
            }
            paths = Paths_GetRuntimePaths()
            checks["paths"] = {
                "ok": all(
                    path.exists()
                    for path in (paths.data_root, paths.logs_root)
                ),
                "data_root": str(paths.data_root),
                "logs_root": str(paths.logs_root),
            }

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtCore import QLibraryInfo
            from PySide6.QtWidgets import QApplication, QWidget

            application = QApplication.instance() or QApplication([])
            widget = QWidget()
            widget.setWindowTitle(APP_DISPLAY_NAME)
            widget.close()
            plugins_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
            checks["qt"] = {"ok": bool(application and plugins_path), "plugins": plugins_path}

            output = temporary_root / "股票分析 自检.xlsx"
            config = AppConfig(
                financial_year=2025,
                trading_year=2025,
                markets=[Market.A_SHARE, Market.HK],
                output_directory=str(temporary_root),
                fixture_mode=True,
                test_mode=True,
                concurrency=2,
                request_interval=0.0,
            )
            summary = Application_RunPipeline(config, output_path=output)
            Workbook_Validate(output)
            checks["no_persistent_cache"] = {
                "ok": not any(
                    temporary_root.rglob("*.sqlite3")
                ) and not (paths.data_root / "cache").exists()
            }
            checks["fixture_export"] = {
                "ok": output.is_file()
                and summary.result in {PipelineRunResult.SUCCESS, PipelineRunResult.PARTIAL},
                "rows": len(summary.records),
                "output": str(output),
            }
        except Exception as error:
            checks["exception"] = {"ok": False, "error": str(error)}
        finally:
            if previous_home is None:
                os.environ.pop("STOCK_ANALYSIS_HOME", None)
            else:
                os.environ["STOCK_ANALYSIS_HOME"] = previous_home
    ok = bool(checks) and all(bool(item.get("ok")) for item in checks.values())
    report = {"ok": ok, "version": __version__, "checks": checks}
    report_path = report_path.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_report.replace(report_path)
    return report

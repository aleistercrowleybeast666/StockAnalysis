from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from stock_analysis.common.paths import Paths_GetRuntimePaths


def Logging_Configure(log_path: Path | None = None) -> logging.Logger:
    path = log_path or Paths_GetRuntimePaths().log_file
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("stock_analysis")
    logger.setLevel(logging.INFO)
    resolved = str(path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == resolved:
            return logger
    handler = RotatingFileHandler(
        path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def Logging_Close(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)
